"""
KLineStore —— 原始 K 线的本地持久化层（DuckDB 单文件）。

职责：把 DataAPI 适配器拉到的原始 K 线（OHLCV + 时间 + code/kl_type/autype 元信息）
落盘到本地 DuckDB 单文件，并提供幂等写入（INSERT OR REPLACE）与区间查询。

本模块只做「存储」，不负责拉取（拉取复用既有 BaoStock/Akshare 适配器，见
Data/download_kl.py）与回读（回读见 DataAPI/DuckDBAPI.py 的 CDuckDB 适配器）。

设计约定（对应 openspec 变更 persist-kl-to-duckdb 的 design.md）：
- 一行 = 一根 K 线，主键为 (code, kl_type, autype, time_key)。
- kl_type / autype 存枚举的 `.name` 字符串（如 "K_DAY" / "QFQ"），由读适配器还原为枚举。
- time_key 存规范化的「无时区北京时间」字符串 "YYYY-MM-DD HH:MM:SS"（而非 TIMESTAMP），
  以便日线（时分秒均为 0）与分钟线都能无损往返，且不受 DuckDB TIMESTAMP 隐式时区影响。
"""

import logging
import os
import random
import time
from contextlib import contextmanager

import pandas as pd

# DuckDB 为可选依赖，仅在使用 KLineStore 时才会 import；延迟导入避免无依赖场景报错。
import duckdb

log = logging.getLogger("KLineStore")

# 字段顺序固定，upsert 与 query 均按此对齐。
# 默认 DuckDB 单文件路径（灌数脚本与读适配器共用；可用 KLineStore 构造参数覆盖）。
# 相对路径基于项目根目录（CLAUDE.md 约定所有脚本从根目录运行）。
DEFAULT_DB_PATH = "Data/kl_store.duckdb"

_TIME_KEY = "time_key"
_COLUMNS = [
    "code",
    "kl_type",
    "autype",
    _TIME_KEY,
    "open",
    "high",
    "low",
    "close",
    "volume",
    "turnover",
    "turnover_rate",
]

_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS kline (
  code          VARCHAR,
  kl_type       VARCHAR,
  autype        VARCHAR,
  time_key      VARCHAR,
  open          DOUBLE,
  high          DOUBLE,
  low           DOUBLE,
  close         DOUBLE,
  volume        DOUBLE,
  turnover      DOUBLE,
  turnover_rate DOUBLE,
  PRIMARY KEY (code, kl_type, autype, time_key)
)
"""


def ctime_to_str(ct) -> str:
    """把 CTime（含 year/month/day/hour/minute/second 字段）序列化为规范化时间字符串。

    CTime 有 `auto` 语义：日线的 hour/minute/second 均为 0，`to_str()` 会省略时间部分。
    这里统一补零输出完整 "YYYY-MM-DD HH:MM:SS"，保证读回时能精确重建字段。
    """
    return (
        f"{ct.year:04d}-{ct.month:02d}-{ct.day:02d} "
        f"{ct.hour:02d}:{ct.minute:02d}:{ct.second:02d}"
    )


def str_to_ctime(s: str):
    """把 ctime_to_str 产出的字符串还原为 CTime。仅在读适配器需要时调用。

    使用 auto=True（CTime 默认），与 BaoStock 的 `parse_time_column` 一致：
    日线（时分秒为 0）读回后时间戳落在当日 23:59:59，从而在多级别分析中正确
    成为当日分钟线的父级。若用 auto=False 则日线时间戳停在 00:00:00，会排在
    当日分钟线之前，破坏父子对齐。
    """
    from ChanAnalyse.Common.CTime import CTime

    date_part, time_part = str(s).split(" ")
    year, month, day = (int(x) for x in date_part.split("-"))
    hour, minute, second = (int(x) for x in time_part.split(":"))
    return CTime(year, month, day, hour, minute, second, auto=True)


def _normalize_time(value, is_end: bool = False) -> str:
    """把用户传入的区间边界规范化为 time_key 字符串。

    - "YYYY-MM-DD"（纯日期）：begin 补为 "00:00:00"，end 补为 "23:59:59"，
      使日期边界能覆盖当日全部 bar（含分钟线）。
    - 已是 "YYYY-MM-DD HH:MM:SS" 则原样返回。
    """
    s = str(value).strip()
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s + (" 23:59:59" if is_end else " 00:00:00")
    return s


# 打开连接遇到「锁冲突」时的自旋重试：30 × 0.2s = 最多等 6s。
# DuckDB 的文件锁是连接级独占/共享锁：读写连接持有独占锁期间，read_only
# 连接同样打不开（1.5.5 实测）。因此并发不靠 read_only 单独实现，而是靠
# 「两端都短连接 + 见锁自旋」：写方按任务开合连接（见 Data/download_kl.py），
# 读方在写方持锁的短暂窗口内重试等待。
LOCK_RETRY_ATTEMPTS = 30
LOCK_RETRY_INTERVAL = 0.2


class KLineStore:
    """K 线存储：打开/创建 DuckDB 单文件，建表，提供 upsert 与 query。

    并发模型（重要，勿改回长连接）：DuckDB 的文件锁是**读写互斥**——只要有一方
    持着读写连接，另一方（含 read_only）一律打不开（1.5.5 实测）。若灌数整批持锁
    数小时，后端整个期间都读不到数据。因此对文件库本类采用**按操作短连接**：
    每次 upsert/query/delete/max_time_key 各自开连接、执行完立即释放（毫秒级窗口），
    网络拉取/限频 sleep 期间不持锁；再配合 _connect 的锁冲突自旋重试（随机抖动），
    读写两端可互相穿插。":memory:" 无法重开，保持单条长连接。

    read_only=True（查询路径用）：不建库、不建表、不可写；文件不存在时回退为
    读写连接（等价旧的自动建库行为）。
    """

    def __init__(self, db_path: str, read_only: bool = False):
        # 只读连接既不能对不存在的文件建库，也不能执行建表 DDL，
        # 故文件不存在时回退为读写连接（与旧行为一致：自动创建空库）。
        if read_only and db_path != ":memory:" and not os.path.exists(db_path):
            log.debug("read_only: %s 不存在，回退为读写连接以建库", db_path)
            read_only = False
        self._db_path = db_path
        self._read_only = read_only
        if db_path == ":memory:":
            # 内存库不能重开，只能长连接持有
            self._conn = self._connect(db_path, read_only)
            if not read_only:
                self._conn.execute(_TABLE_SCHEMA)
        else:
            self._conn = None
            if not read_only:
                # 文件库只在写模式下建表；读模式首次查询时自然校验表存在
                with self._open() as conn:
                    conn.execute(_TABLE_SCHEMA)

    # ------------------------------------------------------------------
    # 连接管理：短连接 + 锁冲突自旋
    # ------------------------------------------------------------------
    @staticmethod
    def _connect(db_path: str, read_only: bool):
        """打开连接；遇到锁冲突自旋重试（随机抖动防两端同步碰撞），其它异常立即抛出。"""
        last_err = None
        for attempt in range(LOCK_RETRY_ATTEMPTS):
            try:
                return duckdb.connect(db_path, read_only=read_only)
            except Exception as e:
                if "Could not set lock" not in str(e):
                    raise
                last_err = e
                if attempt + 1 < LOCK_RETRY_ATTEMPTS:
                    time.sleep(LOCK_RETRY_INTERVAL + random.uniform(0, 0.1))
        log.warning(
            "等待 DuckDB 锁超时（最多 %d × %.1fs）：%s",
            LOCK_RETRY_ATTEMPTS, LOCK_RETRY_INTERVAL, last_err,
        )
        raise last_err

    @contextmanager
    def _open(self):
        """按操作开合短连接（:memory: 复用长连接）。"""
        if self._conn is not None:
            yield self._conn
            return
        conn = self._connect(self._db_path, self._read_only)
        try:
            yield conn
        finally:
            conn.close()

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def execute(self, sql: str, params=None) -> list:
        """执行任意 SQL 并返回全部行（元组列表）。供测试/诊断用，短连接执行。"""
        with self._open() as conn:
            return conn.execute(sql, params or []).fetchall()

    # ------------------------------------------------------------------
    # 读写
    # ------------------------------------------------------------------
    def upsert(self, df: pd.DataFrame) -> int:
        """幂等写入：按主键 (code, kl_type, autype, time_key) 去重，后写覆盖前写。

        返回实际写入行数（INSERT OR REPLACE 对重复键亦计为一行）。
        入参 DataFrame 需包含 _COLUMNS 中的列；缺失列以 NULL 填充。
        """
        if df is None or len(df) == 0:
            return 0
        # 对齐列序，缺失列补 NULL，多余列丢弃。
        normalized = df.reindex(columns=_COLUMNS)
        with self._open() as conn:
            conn.register("_upsert_df", normalized)
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO kline SELECT * FROM _upsert_df"
                )
            finally:
                conn.unregister("_upsert_df")
        return len(normalized)

    def query(self, code, kl_type, autype, begin=None, end=None) -> pd.DataFrame:
        """按 code/kl_type/autype 与可选时间区间查询，按 time_key 升序返回。

        begin/end 支持纯日期（补零/补满）或完整时间字符串。
        """
        params = [code, kl_type, autype]
        where = "WHERE code = ? AND kl_type = ? AND autype = ?"
        if begin is not None:
            where += " AND time_key >= ?"
            params.append(_normalize_time(begin, is_end=False))
        if end is not None:
            where += " AND time_key <= ?"
            params.append(_normalize_time(end, is_end=True))
        sql = f"SELECT {', '.join(_COLUMNS)} FROM kline {where} ORDER BY time_key"
        with self._open() as conn:
            return conn.execute(sql, params).fetchdf()

    def delete(self, code, kl_type, autype, begin=None, end=None) -> int:
        """删除某 (code, kl_type, autype) 的全部或指定区间 K 线。

        用于 --full 全量重刷与 --begin/--end 区间重刷。返回被删除行数。
        """
        params = [code, kl_type, autype]
        where = "code = ? AND kl_type = ? AND autype = ?"
        if begin is not None:
            where += " AND time_key >= ?"
            params.append(_normalize_time(begin, is_end=False))
        if end is not None:
            where += " AND time_key <= ?"
            params.append(_normalize_time(end, is_end=True))
        with self._open() as conn:
            cnt = conn.execute(
                f"SELECT count(*) FROM kline WHERE {where}", params
            ).fetchone()[0]
            conn.execute(f"DELETE FROM kline WHERE {where}", params)
        return cnt

    def max_time_key(self, code, kl_type, autype):
        """返回某 (code, kl_type, autype) 当前最新的 time_key，作为断点续拉的水位。

        无任何数据时返回 None。
        """
        with self._open() as conn:
            row = conn.execute(
                "SELECT max(time_key) FROM kline WHERE code = ? AND kl_type = ? AND autype = ?",
                [code, kl_type, autype],
            ).fetchone()
        return row[0] if row else None
