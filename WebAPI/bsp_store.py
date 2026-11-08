# -*- coding: utf-8 -*-
"""
BSP DAO — chan_structure / bsp_index / chan_snapshot 表的 PG 持久化。
"""

import json
import logging
import os
from datetime import date as _date
from datetime import timedelta
from typing import Any, Optional

import psycopg2

from .chan_service import PERIOD_MAP
from .config import PG_DSN
from .stock_store import ST_EXCLUDE_SQL

log = logging.getLogger("bsp_store")

# ---- 方向化标签 → (原始枚举集合, is_buy) ----
# 与前端 utils/bsp.ts 的 TYPE_MAP 同构。原始枚举: '1','2','2s','3a','3b','1p'
#
# 放在 store 层而非 router：方向化标签有两个消费方——`/api/bsp` 的查询参数，
# 以及 `scope_type='bsp_query'` 的任务范围固化（`strategy_store`）。若只在
# router 解析，任务固化会拿标签去匹配原始枚举列，类型筛选被静默忽略。
DIRECTIONAL_LABELS: dict[str, tuple[list[str], bool]] = {
    "1B": (["1"], True),
    "1S": (["1"], False),
    "2B": (["2"], True),
    "2S": (["2"], False),
    "L2B": (["2s"], True),
    "L2S": (["2s"], False),
    # 三买/三卖自 chan-standard-bsp 起语义分叉，标签必须可区分：
    # 3a = 中枢在「下一条线段」内，3b = 中枢在「当前线段」内。
    # 保留合并标签 3B/3S 作为「两类都要」的快捷筛选，避免老书签/老任务失效。
    "3B": (["3a", "3b"], True),
    "3S": (["3a", "3b"], False),
    "3B(后)": (["3a"], True),
    "3B(内)": (["3b"], True),
    "3S(后)": (["3a"], False),
    "3S(内)": (["3b"], False),
    "PZ-B": (["1p"], True),
    "PZ-S": (["1p"], False),
}


def resolve_bsp_type(bsp_type: str) -> tuple[list[str], Optional[bool]]:
    """bsp_type 查询参数 → (原始枚举集合, is_buy 约束)。

    方向化标签（2B/3S/3B(后)...）→ 枚举集合 + 方向约束（design D11，修复选标签
    查不到记录的既有 bug）；原始枚举直传（如 '2'）→ 仅类型匹配、无方向约束。
    """
    if bsp_type in DIRECTIONAL_LABELS:
        types, is_buy = DIRECTIONAL_LABELS[bsp_type]
        return list(types), is_buy
    return [bsp_type], None


def _get_pg_conn():
    """获取 PG 连接，PG_DSN 未配置或 PG 不可达时返回 None（降级为无数据库模式）。"""
    global _pg_down
    if not PG_DSN:
        return None

    try:
        conn = psycopg2.connect(PG_DSN)
    except psycopg2.OperationalError as e:
        if not _pg_down:
            log.warning("PG 不可达，降级为无数据库模式: %s", e)
            _pg_down = True
        return None
    if _pg_down:
        log.info("PG 连接已恢复")
        _pg_down = False
    return conn


# PG 连接失败降级状态（仅状态翻转时记一次日志，防止每个请求刷屏）
_pg_down = False


def _ensure_tables():
    """惰性建表（CREATE TABLE IF NOT EXISTS）。"""
    conn = _get_pg_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS chan_structure (
                    code       VARCHAR NOT NULL,
                    kl_type    VARCHAR NOT NULL,
                    autype     VARCHAR NOT NULL DEFAULT 'QFQ',
                    structure  JSONB NOT NULL DEFAULT '{}',
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (code, kl_type, autype)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS bsp_index (
                    code       VARCHAR NOT NULL,
                    kl_type    VARCHAR NOT NULL,
                    autype     VARCHAR NOT NULL DEFAULT 'QFQ',
                    bsp_date   DATE NOT NULL,
                    bsp_type   VARCHAR NOT NULL,
                    is_buy     BOOLEAN NOT NULL,
                    price      DOUBLE PRECISION NOT NULL,
                    time_key   VARCHAR NOT NULL,
                    is_sure    BOOLEAN NOT NULL DEFAULT TRUE,
                    ladder     VARCHAR(32),
                    UNIQUE (code, kl_type, autype, bsp_date, bsp_type, is_buy, time_key)
                )
                """
            )
            # 阶梯列宽扩容（chan-bsp-ladder-change D5）：三轴组合值如
            # `L2|L2-3|L3-3`（13 字符）超出旧 VARCHAR(2)。幂等：仅当当前宽度
            # 不足时 ALTER，重复执行不报错（information_schema 查当前定义）。
            cur.execute(
                """
                DO $$
                DECLARE cur_len INT;
                BEGIN
                    SELECT character_maximum_length INTO cur_len
                    FROM information_schema.columns
                    WHERE table_name = 'bsp_index' AND column_name = 'ladder';
                    IF cur_len IS NOT NULL AND cur_len < 16 THEN
                        ALTER TABLE bsp_index ALTER COLUMN ladder TYPE VARCHAR(16);
                    END IF;
                END $$;
                """
            )
            # 五轴组合扩容（chan-standard-bsp2-change D6）：T2 五轴组合如
            # `P1|S3|C2|K3|T1`（14 字符），取 32 留余量。幂等同上。
            cur.execute(
                """
                DO $$
                DECLARE cur_len INT;
                BEGIN
                    SELECT character_maximum_length INTO cur_len
                    FROM information_schema.columns
                    WHERE table_name = 'bsp_index' AND column_name = 'ladder';
                    IF cur_len IS NOT NULL AND cur_len < 32 THEN
                        ALTER TABLE bsp_index ALTER COLUMN ladder TYPE VARCHAR(32);
                    END IF;
                END $$;
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS chan_snapshot (
                    code       VARCHAR NOT NULL,
                    kl_type    VARCHAR NOT NULL,
                    autype     VARCHAR NOT NULL DEFAULT 'QFQ',
                    pickle     BYTEA NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (code, kl_type, autype)
                )
                """
            )
            # 配置指纹（chan-standard-bsp D11）：快照续算只重算未确认尾部，
            # 已确认前缀里的旧口径买卖点会原样保留。切档位后必须靠指纹识别
            # 并强制全量重算，否则新旧口径会混在同一份 bsp_index 里。
            cur.execute(
                "ALTER TABLE chan_snapshot ADD COLUMN IF NOT EXISTS config_fingerprint VARCHAR"
            )
        conn.commit()
    finally:
        conn.close()


def upsert_chan_structure(code: str, kl_type: str, autype: str, structure: dict) -> None:
    """写入或更新缠论结构 JSONB。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO chan_structure (code, kl_type, autype, structure)
                   VALUES (%s, %s, %s, %s::jsonb)
                   ON CONFLICT (code, kl_type, autype) DO UPDATE SET
                     structure  = EXCLUDED.structure,
                     updated_at = NOW()""",
                (code, kl_type, autype, json.dumps(structure, ensure_ascii=False)),
            )
        conn.commit()
    finally:
        conn.close()


def get_chan_structure(code: str, kl_type: str, autype: str = "QFQ") -> Optional[dict]:
    """获取缠论结构。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT structure FROM chan_structure WHERE code=%s AND kl_type=%s AND autype=%s",
                (code, kl_type, autype),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if row:
        raw = row[0]
        if isinstance(raw, str):
            return json.loads(raw)
        return raw
    return None


def upsert_bsp_index(
    code: str,
    kl_type: str,
    autype: str,
    bsp_date: str,
    bsp_type: str,
    is_buy: bool,
    price: float,
    time_key: str,
) -> None:
    """写入买卖点索引（INSERT ON CONFLICT DO NOTHING）。

    is_sure 走列默认值 TRUE（bsp-sure-annotation D2：该遗留单行写路径不携带
    确认推导，保守按已确认写入；主链路 persist_full_set 全集替换携带准确值）。
    """
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO bsp_index (code, kl_type, autype, bsp_date, bsp_type, is_buy, price, time_key)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (code, kl_type, autype, bsp_date, bsp_type, is_buy, time_key) DO NOTHING""",
                (code, kl_type, autype, bsp_date, bsp_type, is_buy, price, time_key),
            )
        conn.commit()
    finally:
        conn.close()


def _date_range_conditions(
    date_from: str, date_to: str, conditions: list[str], params: list[Any]
) -> None:
    """日期范围条件追加（bsp-page-change 2.6/D5/D7）：半开区间 `[date_from, date_to + 1)`。

    只传一端单边过滤、双空不过滤；date_to 含当日（闭区间语义），实现为
    Python 侧 `date.fromisoformat(date_to) + 1 day` 后与 bsp_date（DATE 列）比较。
    """
    if date_from:
        conditions.append("b.bsp_date >= %s")
        params.append(_date.fromisoformat(date_from))
    if date_to:
        conditions.append("b.bsp_date < %s")
        params.append(_date.fromisoformat(date_to) + timedelta(days=1))


def query_bsp(
    kl_type: str = "",
    date_from: str = "",
    date_to: str = "",
    bsp_types: Optional[list[str]] = None,
    is_buy: Optional[bool] = None,
    keyword: str = "",
    page: int = 1,
    page_size: int = 20,
    is_sure: Optional[bool] = None,
    ladder: str = "",
) -> dict:
    """条件查询买卖点，返回 {items, total, page, page_size}。

    bsp-page-change 2.3/2.6：keyword（code/name/name_py ILIKE）与
    kl_type/is_buy/date_from~date_to（半开区间范围，D7）全部下推进
    同一 WHERE，COUNT 与分页共用该条件，total = 过滤后总数；无命中返回
    list=[] 且 total=0。行业信息不再逐行查询（N+1），由 router 层按页批量取。

    bsp_types（design D11）：原始枚举集合（如 ['2'] 或 ['3a','3b']），IN 匹配；
    方向语义由 is_buy 承载（router 层从方向化标签解析）。空列表不过滤。

    is_sure（bsp-sure-annotation D3）：确认状态三态过滤——True 只回已确认行、
    False 只回未确认行、None 不过滤；与 keyword 等条件下推同一 WHERE，
    COUNT 与分页共用。响应每行携带 is_sure。

    **ST 过滤（exclude-st-stocks D6 读侧补齐）**：ST 排除只作用于写入侧（重算
    入口 return None），存量 ST 行仍在 bsp_index 里。读侧必须同样过滤，否则
    买卖点页、区间套与行业聚合仍会展示已停止分析的 ST 标的。谓词复用
    `stock_store.ST_EXCLUDE_SQL`（单一判定来源），因此 FROM 必须 LEFT JOIN
    stock——本函数原已有该 join，仅补谓词。
    """
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    conditions = [ST_EXCLUDE_SQL]
    params: list[Any] = []

    if kl_type:
        conditions.append("b.kl_type = %s")
        params.append(kl_type)
    _date_range_conditions(date_from, date_to, conditions, params)
    if bsp_types:
        ph = ", ".join(["%s"] * len(bsp_types))
        conditions.append(f"b.bsp_type IN ({ph})")
        params.extend(bsp_types)
    if is_buy is not None:
        conditions.append("b.is_buy = %s")
        params.append(is_buy)
    if is_sure is not None:
        conditions.append("b.is_sure = %s")
        params.append(is_sure)
    if ladder:
        # 存量行 ladder 为 NULL → 按 is_sure 兜底映射后匹配（同 ladder_of_legacy）：
        # L4 与 L2 能命中存量行，L1/L3 不命中（存量数据无该信息，值域只有 L4/L2）
        conditions.append(
            "COALESCE(b.ladder, CASE WHEN b.is_sure THEN 'L4' ELSE 'L2' END) = %s"
        )
        params.append(ladder)
    if keyword:
        kw = f"%{keyword}%"
        conditions.append("(b.code ILIKE %s OR s.name ILIKE %s OR s.name_py ILIKE %s)")
        params.extend([kw, kw, kw])

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    try:
        with conn.cursor() as cur:
            # COUNT 与分页共用同一 WHERE（keyword 依赖 stock join，故 FROM/JOIN 保持一致）
            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM bsp_index b
                LEFT JOIN stock s ON b.code = s.code
                {where_clause}
                """,
                params,
            )
            total = cur.fetchone()[0]

            offset = (page - 1) * page_size
            cur.execute(
                f"""
                SELECT b.code, b.kl_type, b.autype, b.bsp_date, b.bsp_type,
                       b.is_buy, b.price, b.time_key,
                       COALESCE(s.name, b.code) AS stock_name,
                       b.is_sure, b.ladder
                FROM bsp_index b
                LEFT JOIN stock s ON b.code = s.code
                {where_clause}
                ORDER BY b.bsp_date DESC, b.code
                LIMIT %s OFFSET %s
                """,
                params + [page_size, offset],
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    items = []
    for row in rows:
        code_val, kt, at, bd, bt, ib, price, tk, stock_name, sure, ladder_raw = row
        items.append({
            "code": code_val,
            "name": stock_name,
            "kl_type": kt,
            "autype": at,
            "bsp_date": bd.isoformat() if hasattr(bd, "isoformat") else str(bd),
            "bsp_type": bt,
            "is_buy": ib,
            "price": price,
            "time_key": tk,
            "is_sure": sure,
            # ladder 原样返回（chan-bsp-ladder-change D3）：NULL 是合法值
            # （非一买类型 / 不可评估），前端显示「未定级」。
            # 旧 `ladder_of_legacy` 兜底已退役——旧 L1/L2/L3 语义反转，
            # 用 is_sure 猜一个值会把「未定级」误报成「虚笔候选」。
            "ladder": ladder_raw,
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}


def query_bsp_aggregate(
    kl_type: str = "",
    date_from: str = "",
    date_to: str = "",
    bsp_type: str = "",
    is_buy: Optional[bool] = None,
) -> list[dict]:
    """GROUP BY 主行业聚合买卖点。

    bsp-page-change 2.6：date 参数连带升级为 date_from/date_to（半开区间
    `[date_from, date_to + 1)`），与主查询 query_bsp 语义保持一致，避免契约漂移。

    **ST 过滤**：与 query_bsp 同口径（`ST_EXCLUDE_SQL`），故补 LEFT JOIN stock。
    缺失该过滤会让行业聚合把已排除分析的 ST 标的计入行业信号密度。
    """
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return []

    conditions = ["si.rank = 0", ST_EXCLUDE_SQL]  # 仅取主行业
    params: list[Any] = []

    if kl_type:
        conditions.append("b.kl_type = %s")
        params.append(kl_type)
    _date_range_conditions(date_from, date_to, conditions, params)
    if bsp_type:
        conditions.append("b.bsp_type = %s")
        params.append(bsp_type)
    if is_buy is not None:
        conditions.append("b.is_buy = %s")
        params.append(is_buy)

    where_clause = "WHERE " + " AND ".join(conditions)

    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT si.industry_name, COUNT(*) AS cnt
                FROM bsp_index b
                JOIN stock_industry si ON b.code = si.code
                LEFT JOIN stock s ON b.code = s.code
                {where_clause}
                GROUP BY si.industry_name
                ORDER BY cnt DESC
                """,
                params,
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    return [{"industry": r[0], "count": r[1]} for r in rows]


def get_bsp_by_code(code: str, kl_types: Optional[list[str]] = None) -> list[dict]:
    """获取指定股票的多级别买卖点（区间套）。

    bsp-page-change 2.5：kl_types IN 改为参数化占位符，消除字符串拼接注入面。

    **ST 过滤**：与 query_bsp 同口径（`ST_EXCLUDE_SQL`）。ST 标的返回空列表
    ——其买卖点已不再维护，返回存量行会让区间套展示过期结论。
    """
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return []

    if kl_types:
        placeholders = ", ".join(["%s"] * len(kl_types))
        sql = f"""
            SELECT b.code, b.kl_type, b.autype, b.bsp_date, b.bsp_type,
                   b.is_buy, b.price, b.time_key, b.is_sure, b.ladder
            FROM bsp_index b
            LEFT JOIN stock s ON b.code = s.code
            WHERE b.code = %s AND b.kl_type IN ({placeholders})
              AND {ST_EXCLUDE_SQL}
            ORDER BY b.bsp_date DESC, b.kl_type
        """
        params: tuple = (code, *kl_types)
    else:
        sql = f"""
            SELECT b.code, b.kl_type, b.autype, b.bsp_date, b.bsp_type,
                   b.is_buy, b.price, b.time_key, b.is_sure, b.ladder
            FROM bsp_index b
            LEFT JOIN stock s ON b.code = s.code
            WHERE b.code = %s AND {ST_EXCLUDE_SQL}
            ORDER BY b.bsp_date DESC, b.kl_type
        """
        params = (code,)

    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()

    return [
        {
            "code": r[0],
            "kl_type": r[1],
            "autype": r[2],
            "bsp_date": r[3].isoformat() if hasattr(r[3], "isoformat") else str(r[3]),
            "bsp_type": r[4],
            "is_buy": r[5],
            "price": r[6],
            "time_key": r[7],
            "is_sure": r[8],
            # ladder 原样返回（NULL = 未定级，见上方 query_bsp 的同口径说明）
            "ladder": r[9],
        }
        for r in rows
    ]


def save_snapshot(code: str, kl_type: str, autype: str, pickle_bytes: bytes,
                  fingerprint: Optional[str] = None) -> None:
    """保存 CChan pickle 快照（连同买卖点配置指纹）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO chan_snapshot (code, kl_type, autype, pickle, config_fingerprint)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (code, kl_type, autype) DO UPDATE SET
                     pickle     = EXCLUDED.pickle,
                     config_fingerprint = EXCLUDED.config_fingerprint,
                     updated_at = NOW()""",
                (code, kl_type, autype, psycopg2.Binary(pickle_bytes), fingerprint),
            )
        conn.commit()
    finally:
        conn.close()


def get_snapshot(code: str, kl_type: str, autype: str = "QFQ") -> Optional[bytes]:
    """获取 CChan pickle 快照。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pickle FROM chan_snapshot WHERE code=%s AND kl_type=%s AND autype=%s",
                (code, kl_type, autype),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if row and row[0]:
        return bytes(row[0])
    return None


def get_snapshot_fingerprint(code: str, kl_type: str, autype: str = "QFQ") -> Optional[str]:
    """获取快照记录的买卖点配置指纹。

    Returns:
        指纹字符串；快照不存在或该行未记录指纹（改造前的存量行）时返回 None。
        调用方应把 ``None`` 视为「不匹配」，即强制全量重算——
        存量行的口径未知，不能假定它属于当前档位。
    """
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT config_fingerprint FROM chan_snapshot "
                "WHERE code=%s AND kl_type=%s AND autype=%s",
                (code, kl_type, autype),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def get_industries_for_codes(codes: list[str], limit: int = 3) -> dict[str, list[str]]:
    """按页批量获取股票行业名（rank 升序取前 limit 个，bsp-page-change 2.4）。

    单条 SQL 替代逐行 N+1 查询；返回 {code: [industry_name, ...]}，未命中行业不出现。
    """
    if not codes:
        return {}
    conn = _get_pg_conn()
    if conn is None:
        return {}
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT code, industry_name
                FROM stock_industry
                WHERE code = ANY(%s) AND rank < %s
                ORDER BY code, rank, industry_name
                """,
                (codes, limit),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    result: dict[str, list[str]] = {}
    for code_val, name in rows:
        result.setdefault(code_val, []).append(name)
    return result


def fetch_current_prices(keys: list[tuple[str, str]]) -> dict[tuple[str, str], tuple[float, float]]:
    """按页批量取股票最新两根 K 线收盘价 → 现价/涨跌幅（bsp-page-change 2.4）。

    keys 为 (code, kl_type) 列表（kl_type 用 bsp 词表值，如 "D"），一次 DuckDB 查询
    覆盖整页（≤ page_size 只）；按 (code, kl_type) 分区取最新两根，current_price =
    最新收盘价，change_pct = (最新 - 前收) / 前收 * 100（无前收时为 0）。

    DuckDB 被灌数锁住/不可用时降级返回空映射（调用方给 0，列表照常渲染，不阻塞）。
    """
    if not keys:
        return {}
    # bsp 词表 -> DuckDB 枚举名（D1 桥接）；未知词表的行跳过
    pairs: list[tuple[str, str, str]] = []  # (code, period, kl_type_db_name)
    for code, period in keys:
        kl_type = PERIOD_MAP.get(period)
        if kl_type is None:
            continue
        pairs.append((code, period, kl_type.name))
    if not pairs:
        return {}

    codes = sorted({c for c, _, _ in pairs})
    kl_names = sorted({k for _, _, k in pairs})
    code_ph = ", ".join(["?"] * len(codes))
    kl_ph = ", ".join(["?"] * len(kl_names))

    try:
        from ChanAnalyse.DataAPI.KLineStore import DEFAULT_DB_PATH, KLineStore

        from .config import DUCKDB_PATH

        db_path = DUCKDB_PATH if os.path.exists(DUCKDB_PATH) else DEFAULT_DB_PATH
        with KLineStore(db_path, read_only=True) as store:
            rows = store.execute(
                f"""
                SELECT code, kl_type, close, rn FROM (
                    SELECT code, kl_type, close,
                           ROW_NUMBER() OVER (PARTITION BY code, kl_type ORDER BY time_key DESC) AS rn
                    FROM kline
                    WHERE code IN ({code_ph}) AND kl_type IN ({kl_ph}) AND autype = 'QFQ'
                ) t WHERE rn <= 2
                """,
                codes + kl_names,
            )
    except Exception as e:  # 锁冲突/文件缺失等：降级为 0，不阻塞列表
        log.warning("DuckDB 现价批量查询失败，降级为 0: %s", e)
        return {}

    closes: dict[tuple[str, str], dict[int, float]] = {}
    for code_val, kl_name, close, rn in rows:
        closes.setdefault((code_val, kl_name), {})[int(rn)] = float(close)

    result: dict[tuple[str, str], tuple[float, float]] = {}
    for code, period, kl_name in pairs:
        two = closes.get((code, kl_name), {})
        cur_close = two.get(1)
        if cur_close is None:
            continue
        prev_close = two.get(2)
        if prev_close:
            change_pct = (cur_close - prev_close) / prev_close * 100.0
        else:
            change_pct = 0.0
        result[(code, period)] = (cur_close, round(change_pct, 2))
    return result


def get_price_at(code: str, kl_type: str, time_key: str) -> Optional[dict]:
    """取该股票指定周期上不晚于 time_key 的最近一根 K 线收盘价（bsp-page-change D12）。

    监控弹窗价格联动用：加入监控即加入「所选时间点的价格」。kl_type 为 bsp 词表值
    （D/W/M/30m/60m），经 PERIOD_MAP 桥接为 DuckDB 枚举名。无数据返回 None（调用方 404）。
    """
    from ChanAnalyse.DataAPI.KLineStore import DEFAULT_DB_PATH, KLineStore

    from .config import DUCKDB_PATH

    kl_name = PERIOD_MAP.get(kl_type)
    if kl_name is None:
        return None
    db_path = DUCKDB_PATH if os.path.exists(DUCKDB_PATH) else DEFAULT_DB_PATH
    try:
        with KLineStore(db_path, read_only=True) as store:
            rows = store.execute(
                """
                SELECT time_key, close FROM kline
                WHERE code = ? AND kl_type = ? AND autype = 'QFQ' AND time_key <= ?
                ORDER BY time_key DESC LIMIT 1
                """,
                [code, kl_name.name, time_key],
            )
    except Exception as e:  # 锁冲突/文件缺失：与 fetch_current_prices 同口径降级
        log.warning("price-at 查询失败: %s %s %s: %s", code, kl_type, time_key, e)
        return None
    if not rows:
        return None
    tk, close = rows[0]
    return {"price": float(close), "time_key": str(tk)}


# ---- 整套替换写入（幂等层 2+3，bsp-page-change D4）----


def _delete_bsp_rows(cur, code: str, kl_type: str, autype: str) -> int:
    cur.execute(
        "DELETE FROM bsp_index WHERE code=%s AND kl_type=%s AND autype=%s",
        (code, kl_type, autype),
    )
    return cur.rowcount


def _insert_bsp_rows(cur, code: str, kl_type: str, autype: str, bsp_rows) -> int:
    """层 1 幂等：唯一键 + ON CONFLICT DO NOTHING（防并发/集合内重复写）。

    bsp_rows 为 7 元行 (bsp_date, bsp_type, is_buy, price, time_key, is_sure, ladder)
    （bsp-sure-annotation D1/D5 的 is_sure 与 bsp-ladder-change D1 的 ladder
    均由 incremental_engine 推导后传入）。
    """
    if not bsp_rows:
        return 0
    cur.executemany(
        """INSERT INTO bsp_index (code, kl_type, autype, bsp_date, bsp_type, is_buy, price, time_key, is_sure, ladder)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (code, kl_type, autype, bsp_date, bsp_type, is_buy, time_key) DO NOTHING""",
        [(code, kl_type, autype, bd, bt, ib, pr, tk, su, ld) for (bd, bt, ib, pr, tk, su, ld) in bsp_rows],
    )
    return cur.rowcount


def _upsert_structure(cur, code: str, kl_type: str, autype: str, structure: dict) -> None:
    cur.execute(
        """INSERT INTO chan_structure (code, kl_type, autype, structure)
           VALUES (%s, %s, %s, %s::jsonb)
           ON CONFLICT (code, kl_type, autype) DO UPDATE SET
             structure  = EXCLUDED.structure,
             updated_at = NOW()""",
        (code, kl_type, autype, json.dumps(structure, ensure_ascii=False)),
    )


def _upsert_snapshot(cur, code: str, kl_type: str, autype: str, pickle_bytes: bytes,
                     fingerprint: Optional[str] = None) -> None:
    cur.execute(
        """INSERT INTO chan_snapshot (code, kl_type, autype, pickle, config_fingerprint)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (code, kl_type, autype) DO UPDATE SET
             pickle     = EXCLUDED.pickle,
             config_fingerprint = EXCLUDED.config_fingerprint,
             updated_at = NOW()""",
        (code, kl_type, autype, psycopg2.Binary(pickle_bytes), fingerprint),
    )


def _advance_cursor(cur, code: str, kl_type_db: str, autype_db: str, last_processed_time: str) -> None:
    """同事务推进 recompute_cursor（游标与数据同生共死，D4 层 3）。

    注意：这里必须走调用方的事务连接，不能用 RecomputeCursor.set()（自连接自提交）。
    """
    cur.execute(
        """
        INSERT INTO recompute_cursor (code, kl_type, autype, last_processed_time)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (code, kl_type, autype)
        DO UPDATE SET last_processed_time = EXCLUDED.last_processed_time
        """,
        (code, kl_type_db, autype_db, last_processed_time),
    )


def persist_full_set(
    conn,
    code: str,
    kl_type: str,
    autype: str,
    bsp_rows,
    structure: dict,
    pickle_bytes: bytes,
    last_processed_time: str,
    kl_type_db: str,
    autype_db: str,
    config_fingerprint: Optional[str] = None,
) -> int:
    """整套替换写入（幂等层 2+3）——在调用方已开启的事务内执行，不 commit。

    DELETE 该 (code,kl_type,autype) 旧行 → INSERT 当前买卖点全集（层 1 ON CONFLICT
    DO NOTHING）→ upsert chan_structure / chan_snapshot → 同事务推进 recompute_cursor。
    任一步失败由调用方 rollback，杜绝「游标已走、数据没落」或反之。

    kl_type/autype 用 bsp 词表值（如 "D"/"QFQ"）；kl_type_db/autype_db 用 DuckDB
    枚举名（如 "K_DAY"），只出现在 recompute_cursor 边界（D1）。

    返回插入的索引行数。
    """
    with conn.cursor() as cur:
        _delete_bsp_rows(cur, code, kl_type, autype)
        inserted = _insert_bsp_rows(cur, code, kl_type, autype, bsp_rows)
        _upsert_structure(cur, code, kl_type, autype, structure)
        _upsert_snapshot(cur, code, kl_type, autype, pickle_bytes, config_fingerprint)
        _advance_cursor(cur, code, kl_type_db, autype_db, last_processed_time)
    return inserted


# 模块加载时自动建表
_ensure_tables()