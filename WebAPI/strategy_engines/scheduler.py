# -*- coding: utf-8 -*-
"""
策略扫描调度（strategy-signal-page 任务 2.3 / design D4）。

- 独立 strategy_scan_cursor（(instance_id, code) → watermark），不与
  recompute_cursor 混用（缠论是计算游标，策略是扫描游标）
- scan_instance：从 strategy_store 读实例 + 定义 → 对每个 code：读水位 →
  engine.scan → upsert_signals → 推进水位。全量回算 = 水位为 None 时扫全史
  （引擎本身读全历史序列重算，唯一键 upsert 幂等）
- code 集合默认从 DuckDB kline 表枚举（kl_type='K_DAY'）
- 失败单键 try/except 不中断整批；返回 {scanned, updated, failed} 摘要

调用方：WebAPI/routers/strategy.py（手动补算，BackgroundTasks）、
WebAPI/app.py（_strategy_eod_loop 日终增量扫描）。
"""

import logging
from typing import Optional

from ..config import DUCKDB_PATH
from .. import strategy_store

log = logging.getLogger("strategy_scheduler")

# 默认扫描的 DuckDB 侧 kl_type/autype（首版只做日线）
DEFAULT_KL_TYPE_DB = "K_DAY"
DEFAULT_AUTYPE = "QFQ"


def _duckdb_path() -> str:
    """DuckDB 路径（与 incremental_engine._duckdb_path 同口径）。"""
    import os

    if os.path.exists(DUCKDB_PATH):
        return DUCKDB_PATH
    from ChanAnalyse.DataAPI.KLineStore import DEFAULT_DB_PATH

    return DEFAULT_DB_PATH


def list_all_codes() -> list[str]:
    """枚举 DuckDB 日线全部 code（扫描键集合，design D3 复用 catchup 键枚举思路）。"""
    try:
        from ChanAnalyse.DataAPI.KLineStore import KLineStore

        with KLineStore(_duckdb_path(), read_only=True) as store:
            rows = store.execute(
                "SELECT DISTINCT code FROM kline WHERE kl_type = ?",
                [DEFAULT_KL_TYPE_DB],
            )
        return [r[0] for r in rows]
    except Exception as e:
        log.warning("枚举 DuckDB code 失败: %s", e)
        return []


def scan_instance(
    instance_id: int,
    codes: Optional[list[str]] = None,
    batch: int = 0,
) -> dict:
    """对一个实例执行（增量/全量）扫描：水位门 + 引擎扫描 + 信号 upsert + 水位推进。

    - codes：待扫 code 集合（None = DuckDB 日线全量枚举）
    - batch：>0 时截断（分批跑，水位天然断点可续）
    - 幂等：引擎 upsert 走唯一键 + ON CONFLICT ... WHERE frozen = FALSE，
      重复扫描不产生重复信号、frozen 行不被覆盖
    - 全量回算 = 水位为 None 时（引擎读全历史序列，首扫自然全量）

    返回 {scanned, updated, failed}；实例不存在/定义缺失返回 failed 带 reason。
    """
    from . import get_definition, get_engine

    instance = strategy_store.get_instance(instance_id)
    if instance is None:
        return {"scanned": 0, "updated": 0, "failed": [{"reason": f"实例 {instance_id} 不存在"}]}
    definition = get_definition(instance["strategy_id"])
    engine = get_engine(instance["strategy_id"]) or get_engine(definition.engine_key if definition else "")
    if definition is None or engine is None:
        reason = f"策略定义/引擎缺失: {instance['strategy_id']}"
        log.warning("scan_instance 跳过: %s", reason)
        return {"scanned": 0, "updated": 0, "failed": [{"reason": reason}]}

    if codes is None:
        codes = list_all_codes()
    if batch and batch > 0:
        codes = codes[:batch]

    # 一次读回全部水位（批量调度，避免逐键查库）
    cursors = strategy_store.get_scan_cursors(instance_id)

    scanned = 0
    updated = 0
    failed = []
    scan_with_params = getattr(engine, "scan_with_params", None)
    for code in codes:
        watermark = cursors.get(code)
        try:
            if scan_with_params is not None:
                events = scan_with_params(
                    code,
                    instance["params"],
                    kl_type_db=DEFAULT_KL_TYPE_DB,
                    autype=DEFAULT_AUTYPE,
                    watermark=watermark,
                )
            else:
                # 协议兜底：引擎只实现 scan（不带参数）时按默认参数扫
                events = engine.scan(
                    code,
                    kl_type_db=DEFAULT_KL_TYPE_DB,
                    autype=DEFAULT_AUTYPE,
                    watermark=watermark,
                )
            scanned += 1
            if events:
                strategy_store.upsert_signals(instance_id, events)
                updated += 1
                # 推进水位（事件里带 watermark_new；引擎无事件但有新数据时
                # 由 scan 的空返回兜底——空返回即无演进，不推进）
                new_wm = events[0].get("watermark_new")
                if new_wm:
                    strategy_store.set_scan_cursor(instance_id, code, str(new_wm))
            elif watermark is None:
                # 首扫无信号（该 code 不满足策略条件）：也要推进水位，
                # 否则每个调度周期都会重扫全历史
                new_wm = _latest_time_key(code)
                if new_wm:
                    strategy_store.set_scan_cursor(instance_id, code, new_wm)
        except Exception as e:
            log.warning("扫描失败 instance=%s code=%s: %s", instance_id, code, e)
            failed.append({"code": code, "error": str(e)})

    log.info(
        "scan_instance %s(%s) scanned=%d updated=%d failed=%d",
        instance_id, instance["strategy_id"], scanned, updated, len(failed),
    )
    return {"scanned": scanned, "updated": updated, "failed": failed}


def _latest_time_key(code: str) -> Optional[str]:
    """取某 code 日线最新 time_key（首扫无信号时推进水位用）。"""
    try:
        from ChanAnalyse.DataAPI.KLineStore import KLineStore

        with KLineStore(_duckdb_path(), read_only=True) as store:
            rows = store.execute(
                "SELECT max(time_key) FROM kline WHERE code = ? AND kl_type = ?",
                [code, DEFAULT_KL_TYPE_DB],
            )
        return str(rows[0][0]) if rows and rows[0][0] else None
    except Exception as e:
        log.warning("读取最新水位失败 %s: %s", code, e)
        return None


def scan_all_enabled(batch: int = 0) -> list[dict]:
    """对全部启用实例执行增量扫描（EOD 调度入口，design D4）。

    返回各实例摘要列表；单实例失败不影响其余实例。
    """
    summaries = []
    for ins in strategy_store.list_enabled_instances():
        try:
            summaries.append({
                "instance_id": ins["id"],
                "strategy_id": ins["strategy_id"],
                **scan_instance(ins["id"], batch=batch),
            })
        except Exception as e:
            log.exception("策略扫描失败 instance=%s", ins["id"])
            summaries.append({
                "instance_id": ins["id"],
                "strategy_id": ins["strategy_id"],
                "scanned": 0, "updated": 0,
                "failed": [{"reason": str(e)}],
            })
    return summaries
