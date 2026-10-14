# -*- coding: utf-8 -*-
"""
缠论买点结论读取器（strategy-volume-breakout-pullback design D3/D5）。

B3/B4 判定消费缠论买点，引擎经本模块间接获取，不 import 缠论计算内核：

    查 PG bsp_index（只读，code + kl_type + 买方向）
      |-- 有行（哪怕不含目标窗口内的买点——缠论已算过，无买点是真的无）
      |     --> 直接用
      |-- 无行（该 code+周期 从未算过缠论）
      |     --> 补算链路（强语义，用户既定流程）：
      |        1) 查 DuckDB K 线存在性，无则调灌数（download_kl.ingest，
      |           函数级复用，不 subprocess）
      |        2) 调 incremental_engine.recompute_stock 单只缠论补算
      |           （整套替换落 PG bsp_index）
      |        3) 回读 bsp_index
      `-- 链路失败（接口限频/PG 不可用/ST 跳过）--> 本次返回空集
          （D5 暂态降级：不打标不淘汰，下次扫描重试）

量级控制：补算只在「PG 无该 (code, period) 行」时触发（recompute 是幂等
整套替换，重复触发无意义）；全量任务首扫会集中触发，一次性成本。

硬性约束：本模块对 bsp_index 只读（写入仅经 recompute_stock 的整套替换
语义）；不 import ChanAnalyse 计算模块（灌数/补算经 download_kl /
incremental_engine 间接调用）。
"""

import logging
from typing import Optional

from ..config import PG_DSN

log = logging.getLogger("strategy_bsp_reader")

# 周期词表（bsp_index 的 kl_type 取值 ↔ DuckDB 的 kl_type 枚举名）
# 'D' 日线 / '30m' 30 分钟，与 incremental_engine._period_vocab 同源口径
_PERIOD_KLTYPE_DB = {"D": "K_DAY", "30m": "K_30M"}

# 灌数模块懒导入缓存（Data/ 不在包内，sys.path 注入一次）
_ingest = None


def _load_ingest():
    """懒加载 Data/download_kl.ingest（模块级缓存，失败下次重试）。"""
    global _ingest
    if _ingest is None:
        import sys
        import os

        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)
        from Data.download_kl import ingest

        _ingest = ingest
    return _ingest


def _query_bsp_buy_rows(code: str, period: str) -> list[dict]:
    """只读查询 bsp_index：该 code + 周期的全部买点行（含未确认）。"""
    import psycopg2

    conn = psycopg2.connect(PG_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT bsp_date, bsp_type, price, time_key, is_sure
                   FROM bsp_index
                   WHERE code = %s AND kl_type = %s AND is_buy = TRUE
                   ORDER BY time_key""",
                (code, period),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            "bsp_date": r[0].isoformat() if hasattr(r[0], "isoformat") else str(r[0]),
            "bsp_type": r[1],
            "price": r[2],
            "time_key": str(r[3]) if r[3] is not None else None,
            "is_sure": bool(r[4]),
        }
        for r in rows
    ]


def _has_rows(code: str, period: str) -> bool:
    """该 (code, period) 在 bsp_index 是否有任何行（不限买卖/确认）。"""
    import psycopg2

    conn = psycopg2.connect(PG_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM bsp_index WHERE code = %s AND kl_type = %s LIMIT 1",
                (code, period),
            )
            return cur.fetchone() is not None
    finally:
        conn.close()


def _ensure_kl_data(code: str, period: str) -> bool:
    """DuckDB 该周期 K 线存在性检查，无则灌数（BaoStock 全量）。

    返回灌数后是否仍有数据（数据源确实无此股/周期时为 False，调用方按
    「无缠论数据」处理）。灌数异常上抛由调用方降级。
    """
    kl_type_db = _PERIOD_KLTYPE_DB[period]
    from ..config import DUCKDB_PATH
    import os
    from ChanAnalyse.DataAPI.KLineStore import DEFAULT_DB_PATH, KLineStore

    db = DUCKDB_PATH if os.path.exists(DUCKDB_PATH) else DEFAULT_DB_PATH
    from ChanAnalyse.Common.CEnum import AUTYPE, KL_TYPE

    kl_type = KL_TYPE[kl_type_db]
    autype = AUTYPE["QFQ"]
    with KLineStore(db) as store:
        wm = store.max_time_key(code, kl_type.name, autype.name)
        if wm is not None:
            return True  # 已有数据，无需灌数
    # 无数据 → 全量灌（manage_auth=True 自管 BaoStock 登录）
    ingest = _load_ingest()
    with KLineStore(db) as store:
        ingest(code, kl_type, autype, store=store, manage_auth=True)
        wm = store.max_time_key(code, kl_type.name, autype.name)
        return wm is not None


def get_bsp_buy_points(
    code: str,
    period: str,
    *,
    allow_recompute: bool = True,
) -> Optional[list[dict]]:
    """取该 code + 周期的缠论买点行集合（engine B3/B4 判定入口）。

    返回：
    - list[dict]：买点行（可为空列表——缠论算过但该区间无买点）
    - None：数据不可得（补算链路失败 / PG 未配置 / 周期不支持），
      调用方按 D5 暂态降级处理（B 级不判定，不淘汰信号）
    """
    if not PG_DSN:
        log.warning("PG_DSN 未配置，跳过 %s %s 缠论买点读取", code, period)
        return None
    if period not in _PERIOD_KLTYPE_DB:
        log.warning("周期 %s 不在 B 点判定支持集（D/30m）", period)
        return None

    try:
        rows = _query_bsp_buy_rows(code, period)
        if rows:
            return rows  # 有买点行，直接用
        if not allow_recompute:
            return rows

        # 无买点行：区分「算过但无买点」与「从未算过」——后者才补算
        if _has_rows(code, period):
            return rows  # 缠论已算过该股，无买点是真的无买点

        # 从未算过 → 补算链路（强语义）
        log.info("[engine补算] %s %s 无缠论结论，触发灌数+补算链路", code, period)
        if not _ensure_kl_data(code, period):
            log.warning("[engine补算] %s %s 灌数后仍无 K 线（数据源无此股/周期）", code, period)
            return None

        from .incremental_engine import recompute_stock

        summary = recompute_stock(code, period, "QFQ")
        if summary is None:
            log.warning("[engine补算] %s %s 缠论补算无结果（ST 跳过或无数据）", code, period)
            return None
        rows = _query_bsp_buy_rows(code, period)
        log.info("[engine补算] %s %s 补算完成，回读买点 %d 行", code, period, len(rows))
        return rows
    except Exception as e:
        # D5 暂态降级：链路失败（限频/PG 故障）本次不可判，不淘汰信号
        log.warning("[engine补算] %s %s 补算链路失败（下次扫描重试）: %s", code, period, e)
        return None
