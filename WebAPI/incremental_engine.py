# -*- coding: utf-8 -*-
"""
买卖点补算引擎 — 方案 C：水位驱动的幂等补算（bsp-page-change design D2/D3/D4）。

职责：
- 首次接入（D3）：DuckDB 全量 K 线 → CChan(trigger_step=True) 全量计算 →
  已确认结构落 chan_structure、买卖点落 bsp_index、pickle 快照落 chan_snapshot。
- 增量续算（D3）：读 chan_snapshot → chan_load_pickle → trigger_load(新 K 线) →
  只算未确认尾部 → 落库并更新快照；快照缺失/损坏/续算异常时回退该股票全量重算。
- 水位补算（D2）：DuckDB max(time_key)（源水位）vs recompute_cursor（处理水位），
  src > cur 才补算，否则跳过——电平触发，任意入口漏发下一次触发自动补上。
- 整套替换写入（D4）：每 (code,kl_type,autype) 事务内 DELETE→INSERT 当前买卖点全集
  → upsert 结构/快照 → 同事务推进 recompute_cursor（游标与数据同生共死）。

入口（均可重入、幂等）：
  - 服务启动 / 定时 tick / 日终调度：见 WebAPI/app.py 的 _bsp_scheduler
  - 手动 API：POST /api/bsp/catch-up（WebAPI/routers/bsp.py）
  - CLI（cron/首次全市场接入/日终兜底）：
        PYTHONPATH=. python -m WebAPI.incremental_engine --catch-up [--codes sz.000001,...]
                                                      [--periods D,60m] [--day 2026-10-01]
                                                      [--limit N] [--force]
        PYTHONPATH=. python -m WebAPI.incremental_engine --eod [--day 2026-10-01]

绝不做的事：不在灌数进程内计算（灌数持 DuckDB 单写锁）；计算侧只读 DuckDB、只写 PG。
周期词表（D1）：bsp_index/chan_structure/chan_snapshot 的 kl_type 存 bsp 词表（D/W/M/60m/30m），
DuckDB 枚举名（K_DAY…）只在 recompute_cursor 与 DuckDB 边界出现，桥接统一走 chan_service。
"""

import argparse
import logging
import os
import sys
import tempfile
from typing import Any, Optional

import psycopg2

from ChanAnalyse.Chan import CChan
from ChanAnalyse.ChanConfig import CChanConfig
from ChanAnalyse.Common.CEnum import AUTYPE
from ChanAnalyse.DataAPI.DuckDBAPI import CDuckDB
from ChanAnalyse.DataAPI.KLineStore import KLineStore, ctime_to_str
from ChanAnalyse.DataAPI.RecomputeCursor import RecomputeCursor

from .bsp_store import get_snapshot, persist_full_set
from .chan_service import period_of_db_name, resolve_period
from .config import DUCKDB_PATH, PG_DSN
from .serializer import _serialize_bi, _serialize_seg, _serialize_zs

log = logging.getLogger("incremental_engine")

DEFAULT_AUTYPE = "QFQ"


# ----------------------------------------------------------------------
# 词表桥接（D1）
# ----------------------------------------------------------------------

def _period_vocab(period: str) -> tuple[str, Any, str]:
    """任意周期词表 → (canonical, KL_TYPE, kl_type_db)。

    canonical 进 bsp_index/chan_structure/chan_snapshot；kl_type_db（K_DAY…）
    只进 recompute_cursor / DuckDB。
    """
    return resolve_period(period)


# ----------------------------------------------------------------------
# DuckDB 读取（只读，短连接 + 锁重试，见 KLineStore）
# ----------------------------------------------------------------------

def _duckdb_path() -> str:
    return DUCKDB_PATH if os.path.exists(DUCKDB_PATH) else "Data/kl_store.duckdb"


def _load_klus(code: str, kl_type, autype: str, begin: str | None = None):
    """从 DuckDB 读取 CKLine_Unit 列表（升序）。begin 为 time_key 字符串（含）。"""
    api = CDuckDB(code, k_type=kl_type, begin_date=begin, autype=AUTYPE[autype])
    api.db_path = _duckdb_path()
    return list(api.get_kl_data())


def source_watermark(code: str, kl_type_db: str, autype: str = DEFAULT_AUTYPE) -> str | None:
    """源水位 = DuckDB max(time_key)。无数据返回 None。"""
    with KLineStore(_duckdb_path(), read_only=True) as store:
        return store.max_time_key(code, kl_type_db, autype)


# ----------------------------------------------------------------------
# pickle 快照 <-> BYTEA（复用 CChan.chan_dump_pickle/chan_load_pickle，经临时文件）
# ----------------------------------------------------------------------

def _dump_pickle_bytes(chan: CChan) -> bytes:
    fd, path = tempfile.mkstemp(suffix=".chanpkl")
    os.close(fd)
    try:
        chan.chan_dump_pickle(path)
        with open(path, "rb") as f:
            return f.read()
    finally:
        os.remove(path)


def _load_pickle_chan(data: bytes) -> CChan:
    fd, path = tempfile.mkstemp(suffix=".chanpkl")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        return CChan.chan_load_pickle(path)
    finally:
        os.remove(path)


# ----------------------------------------------------------------------
# 计算（D3：trigger_step=True，全量与续算同一机制）
# ----------------------------------------------------------------------

def _make_chan(code: str, kl_type, autype: str) -> CChan:
    """trigger_step=True 的空 CChan（外部推送模式；构造时不做全量 load）。"""
    config = CChanConfig({"trigger_step": True, "kl_data_check": False})
    return CChan(
        code=code,
        data_src="custom:DuckDBAPI.CDuckDB",
        lv_list=[kl_type],
        config=config,
        autype=AUTYPE[autype],
    )


def _compute_full(code: str, kl_type, autype: str) -> CChan | None:
    """首次接入/回退路径：全量 K 线一次性 trigger_load 全量计算。"""
    klus = _load_klus(code, kl_type, autype)
    if not klus:
        return None
    chan = _make_chan(code, kl_type, autype)
    chan.trigger_load({kl_type: klus})
    return chan


def _compute_incremental(
    code: str, kl_type, autype: str, cursor: str, snapshot_bytes: bytes
) -> CChan:
    """续算路径：pickle 恢复 → trigger_load(严格晚于 cursor 的新 K 线) → 只算未确认尾部。

    快照损坏/续算异常由调用方捕获并回退全量（D3）。
    """
    chan = _load_pickle_chan(snapshot_bytes)
    new_klus = [k for k in _load_klus(code, kl_type, autype, begin=cursor) if ctime_to_str(k.time) > cursor]
    if new_klus:
        chan.trigger_load({kl_type: new_klus})
    return chan


# ----------------------------------------------------------------------
# 结果抽取
# ----------------------------------------------------------------------

def _extract_bsp_rows(chan: CChan, kl_type) -> list[tuple]:
    """bs_point_lst 当前全集 → bsp_index 行 (bsp_date, bsp_type, is_buy, price, time_key)。

    一个点多类型（如 T1+T1P）按类型展开多行（唯一键含 bsp_type，过滤才可精确命中）。
    price：买点取 klu.low、卖点取 klu.high（chan-stock-manage D4 语义）。
    """
    kl = chan[kl_type]
    rows: list[tuple] = []
    for bsp in kl.bs_point_lst.getSortedBspList():
        klu = bsp.klu
        price = float(klu.low if bsp.is_buy else klu.high)
        time_key = ctime_to_str(klu.time)
        bsp_date = klu.time.toDateStr("-")
        for t in bsp.type:
            rows.append((bsp_date, t.value, bool(bsp.is_buy), price, time_key))
    return rows


def _extract_structure(chan: CChan, kl_type) -> dict:
    """已确认 bi/seg/zs 序列化几何 → chan_structure.structure JSONB（契约对齐 chan-web-viewer D2）。"""
    kl = chan[kl_type]
    return {
        "bi": _serialize_bi([bi for bi in kl.bi_list if bi.is_sure]),
        "seg": _serialize_seg([seg for seg in kl.seg_list if seg.is_sure]),
        "zs": _serialize_zs([zs for zs in kl.zs_list if zs.is_sure]),
        "seg_zs": _serialize_zs([zs for zs in kl.segzs_list if zs.is_sure]),
    }


# ----------------------------------------------------------------------
# 单只补算（D3/D4）
# ----------------------------------------------------------------------

def _get_cursor(code: str, kl_type_db: str, autype_db: str) -> str | None:
    if not PG_DSN:
        return None
    try:
        return RecomputeCursor(PG_DSN).get(code, kl_type_db, autype_db)
    except psycopg2.Error:
        return None


def recompute_stock(
    code: str,
    period: str,
    autype: str = DEFAULT_AUTYPE,
    force_full: bool = False,
) -> Optional[dict]:
    """补算单只 (code, kl_type, autype) 并整套替换落库。

    不做水位判断（那是 catch_up 的职责）——调用即计算+写入；force_full=True 强制
    全量重算（快照异常回退、索引被外部篡改后的收敛都走这条）。
    返回 summary dict；该股票在 DuckDB 无数据时返回 None。
    """
    if not PG_DSN:
        raise RuntimeError("PG_DSN 未配置，补算引擎需要 PostgreSQL")

    canonical, kl_type, kl_type_db = _period_vocab(period)
    autype_db = AUTYPE[autype].name

    src = source_watermark(code, kl_type_db, autype_db)
    if src is None:
        log.info("skip %s %s: DuckDB 无 K 线", code, canonical)
        return None

    cursor = _get_cursor(code, kl_type_db, autype_db)
    snapshot = None
    if not force_full and cursor is not None:
        snapshot = get_snapshot(code, canonical, autype)

    mode = "full"
    chan = None
    if snapshot and cursor is not None:
        try:
            chan = _compute_incremental(code, kl_type, autype, cursor, snapshot)
            mode = "incremental"
        except Exception:
            log.exception("续算失败，回退全量重算: %s %s", code, canonical)
            chan = None
    if chan is None:
        chan = _compute_full(code, kl_type, autype)
        mode = "full"

    if chan is None:
        log.info("skip %s %s: 计算无数据", code, canonical)
        return None

    bsp_rows = _extract_bsp_rows(chan, kl_type)
    structure = _extract_structure(chan, kl_type)
    pickle_bytes = _dump_pickle_bytes(chan)

    # 事务：DELETE→INSERT 全集 + 结构/快照 upsert + 推进游标（D4 层 2+3）
    conn = psycopg2.connect(PG_DSN)
    try:
        inserted = persist_full_set(
            conn,
            code=code,
            kl_type=canonical,
            autype=autype,
            bsp_rows=bsp_rows,
            structure=structure,
            pickle_bytes=pickle_bytes,
            last_processed_time=src,
            kl_type_db=kl_type_db,
            autype_db=autype_db,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    log.info(
        "recompute %s %s mode=%s bsp_rows=%d cursor->%s",
        code, canonical, mode, inserted, src,
    )
    return {
        "code": code,
        "kl_type": canonical,
        "autype": autype,
        "mode": mode,
        "bsp_rows": inserted,
        "cursor": src,
    }


# ----------------------------------------------------------------------
# 水位补算入口（D2）：catch_up / 日终流水线（D2 日终为主）
# ----------------------------------------------------------------------

def _load_cursor_map() -> dict[tuple[str, str, str], str]:
    """一次性读回全部处理水位 {(code, kl_type_db, autype_db): last_processed_time}。"""
    if not PG_DSN:
        return {}
    conn = psycopg2.connect(PG_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT code, kl_type, autype, last_processed_time FROM recompute_cursor")
            rows = cur.fetchall()
    finally:
        conn.close()
    return {(c, k, a): t for c, k, a, t in rows}


def list_stale_keys(
    codes: Optional[list[str]] = None,
    periods: Optional[list[str]] = None,
    day: str | None = None,
    limit: int = 0,
    force: bool = False,
) -> list[tuple[str, str, str]]:
    """列出待补算键 (code, period, autype_db)。

    - 默认水位门（D2）：源水位 > 处理水位（或游标缺失）才列出；force=True 无视水位
      （范围内全部键，用于索引被篡改后的整套收敛）。
    - codes/periods：范围过滤（periods 为 bsp 词表值，D/W/M/60m/30m）
    - day：仅保留源水位日期等于该日的键（日终「当日有新增 K 线」语义）
    - limit：>0 时截断（分批跑，游标天然断点可续）
    """
    kl_filter = None
    if periods:
        kl_filter = {resolve_period(p)[2] for p in periods}

    params: list[Any] = []
    where = []
    if codes:
        ph = ", ".join(["?"] * len(codes))
        where.append(f"code IN ({ph})")
        params.extend(codes)
    if kl_filter:
        ph = ", ".join(["?"] * len(kl_filter))
        where.append(f"kl_type IN ({ph})")
        params.extend(sorted(kl_filter))
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    with KLineStore(_duckdb_path(), read_only=True) as store:
        rows = store.execute(
            f"SELECT code, kl_type, autype, max(time_key) FROM kline {where_sql} GROUP BY 1, 2, 3",
            params,
        )

    cursors = _load_cursor_map()
    stale: list[tuple[str, str, str]] = []
    for code, kl_type_db, autype_db, src in rows:
        if day and not str(src).startswith(day):
            continue
        cur = cursors.get((code, kl_type_db, autype_db))
        if not force and cur is not None and str(src) <= str(cur):
            continue  # src <= cur：数据无变化，跳过（重复触发幂等）
        stale.append((code, period_of_db_name(kl_type_db) or kl_type_db, autype_db))

    stale.sort()
    if limit and limit > 0:
        stale = stale[:limit]
    return stale


def catch_up(
    codes: Optional[list[str]] = None,
    periods: Optional[list[str]] = None,
    day: str | None = None,
    limit: int = 0,
    force: bool = False,
) -> dict:
    """水位补算：对 src > cur 的键逐只补算（D2，幂等可重入）。

    force=True 跳过水位门，范围内全部键整套重写（重算路径不变：有快照仍续算/异常
    回退全量；写入恒为 DELETE→INSERT 当前全集，因此即使数据无变化也收敛回全集）。
    """
    if not PG_DSN:
        raise RuntimeError("PG_DSN 未配置，补算引擎需要 PostgreSQL")

    keys = list_stale_keys(codes=codes, periods=periods, day=day, limit=limit, force=force)

    done, failed = [], []
    for code, period, autype_db in keys:
        autype = autype_db if autype_db in AUTYPE.__members__ else DEFAULT_AUTYPE
        try:
            summary = recompute_stock(code, period, autype=autype)
            if summary is not None:
                done.append(summary)
        except Exception as e:
            log.exception("catch_up 失败: %s %s", code, period)
            failed.append({"code": code, "kl_type": period, "error": str(e)})

    return {
        "scanned": len(keys),
        "updated": len(done),
        "failed": failed,
        "results": done,
    }


def run_eod_pipeline(day: str | None = None, codes: Optional[list[str]] = None, limit: int = 0) -> dict:
    """日终流水线（D2：日终为主、盘中预留）：扫描当日有新增 K 线的股票执行 catch_up。

    入口选择（bsp-page-change 3.7）：服务内日终调度为主（app.py _bsp_scheduler 每日
    BSP_EOD_AT 触发），本函数同时是 CLI 入口（`python -m WebAPI.incremental_engine --eod`），
    便于 cron 兜底与离线验证；两入口共用同一实现，天然幂等。
    """
    import datetime as _dt

    if not day:
        day = _dt.datetime.now().strftime("%Y-%m-%d")
    log.info("eod pipeline start day=%s", day)
    result = catch_up(codes=codes, day=day, limit=limit)
    log.info("eod pipeline done day=%s updated=%d", day, result["updated"])
    return result


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def _parse_args(argv):
    p = argparse.ArgumentParser(description="买卖点补算引擎（方案 C 水位驱动）")
    p.add_argument("--catch-up", action="store_true", help="水位补算（src>cur 的键）")
    p.add_argument("--eod", action="store_true", help="日终流水线（当日新增 K 线股票的 catch_up）")
    p.add_argument("--codes", default="", help="逗号分隔股票代码（默认全部）")
    p.add_argument("--periods", default="", help="逗号分隔周期（D,W,M,60m,30m；默认全部）")
    p.add_argument("--day", default="", help="YYYY-MM-DD（--eod 默认今天；--catch-up 作过滤）")
    p.add_argument("--limit", type=int, default=0, help="本批最多处理键数（0=不限）")
    p.add_argument("--force", action="store_true", help="跳过水位门，范围内全部整套重写")
    return p.parse_args(argv)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    codes = [c.strip() for c in args.codes.split(",") if c.strip()] or None
    periods = [s.strip() for s in args.periods.split(",") if s.strip()] or None
    day = args.day or None

    if args.eod:
        result = run_eod_pipeline(day=day, codes=codes, limit=args.limit)
    elif args.catch_up:
        result = catch_up(codes=codes, periods=periods, day=day, limit=args.limit, force=args.force)
    else:
        print("需指定 --catch-up 或 --eod（--help 查看用法）")
        return 2

    print(f"scanned={result['scanned']} updated={result['updated']} failed={len(result['failed'])}")
    for r in result["results"]:
        print(f"  {r['code']} {r['kl_type']} mode={r['mode']} rows={r['bsp_rows']} cursor={r['cursor']}")
    for f in result["failed"]:
        print(f"  FAILED {f['code']} {f['kl_type']}: {f['error']}")
    return 0 if not result["failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
