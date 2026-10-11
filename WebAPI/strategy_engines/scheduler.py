# -*- coding: utf-8 -*-
"""
策略扫描调度（strategy-signal-page 任务 2.3 / design D4 + strategy-task-redesign
design D2/D3/D4 任务模型改造）。

- 独立 strategy_scan_cursor（(task_id, code) → watermark），不与
  recompute_cursor 混用（缠论是计算游标，策略是扫描游标）
- run_task：从 strategy_store 读任务行 → 按 scope 枚举 code（显式范围直接用
  固化快照；'all' 枚举 DuckDB 日线全量 + stock_store 名称过滤 ST/*ST）→
  从 progress_scanned 处续扫 → 每 code：读水位 → engine.scan → upsert_signals
  （带 params_version）→ 显式范围写逐股结果 → 推进 progress_scanned → 边界
  检查暂停（status != 'running' 即停，design D4「每个 code 边界」）
- 全量回算 = 水位为 None 时扫全史（引擎本身读全历史序列重算，唯一键 upsert 幂等）
- 逐股结果分叉（spec「逐股结果按范围分叉」）：显式范围任务每 code 落
  strategy_task_stock_result 行（含未匹配与失败）；'all' 范围只推进聚合计数
  （progress_scanned/total），不落逐股结果（存储量约束）
- 失败单键 try/except 不中断整批；返回 {scanned, updated, failed} 摘要
- 执行模型：单并发（design D4 备选多 worker 被否决——DuckDB 只读 + PG 写，
  单进程串行已够用；多任务同时 running 时逐个排队执行）
- EOD 调度：run_eod_tasks 只取 mode='persistent' 的任务做增量扫描（水位门
  逻辑不变）；test 任务只在用户启动时执行

调用方：WebAPI/routers/strategy.py（start/resume 触发，asyncio.to_thread）、
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

# 'all' 范围的 ST 名称过滤前缀（spec「全量兜底排除 ST 与 *ST」；名称缺失放行，
# design D3「宁多勿漏」）
_ST_PREFIXES = ("ST", "*ST")


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


def _filter_st_codes(codes: list[str]) -> list[str]:
    """'all' 范围的 ST/*ST 过滤（design D3：按 stock_store 名称前缀匹配）。

    名称缺失的股票放行（宁多勿漏——股票元数据新鲜度不构成漏扫理由）；
    stock_store 不可用时全量放行（降级不阻塞扫描）。
    """
    try:
        from .scope_resolver import get_stock_names

        names = get_stock_names(codes)
    except Exception as e:
        log.warning("读取股票名称失败，ST 过滤降级为全量放行: %s", e)
        return codes
    return [
        c for c in codes
        if not _is_st_name(names.get(c))
    ]


def _is_st_name(name: Optional[str]) -> bool:
    """名称前缀匹配 ST/*ST（None = 元数据缺失，放行不算 ST）。"""
    if not name:
        return False
    n = name.strip().upper()
    return n.startswith("ST") or n.startswith("*ST")


def _task_codes(task: dict) -> tuple[list[str], bool]:
    """解析任务的待扫 code 集合（design D3/D4）。

    返回 (codes, explicit_scope)：
    - 显式范围（manual/watchlist/bsp_query）：直接用固化快照 scope_codes，
      explicit_scope=True（调度写逐股结果）
    - 'all'：枚举 DuckDB 日线全量 + ST 过滤，explicit_scope=False（不落逐股结果）
    """
    scope_type = task.get("scope_type") or "all"
    if scope_type != "all" and task.get("scope_codes"):
        return list(task["scope_codes"]), True

    codes = list_all_codes()
    codes = _filter_st_codes(codes)
    return codes, False


def run_task(task_id: int, batch: int = 0) -> dict:
    """对一个任务执行（续跑/增量）扫描（design D4：单 worker 的执行单位）。

    - 从任务行 progress_scanned 处续扫（remaining 语义天然内建：已扫前缀
      跳过，新参数只作用于剩余 code —— full 语义由 resume_task 在调用前
      清零进度/水位/信号实现，design D2）
    - 每 code 边界：提交进度 + 检查任务状态（status != 'running' 即停，
      暂停响应最长延迟一只股票的扫描时间，design D4 Risks）
    - 每 code 提交进度（乐观进度：前端轮询任务列表可见，D4）
    - 幂等：引擎 upsert 走唯一键 + ON CONFLICT ... WHERE frozen = FALSE，
      重复扫描不产生重复信号、frozen 行不被覆盖
    - 全量回算 = 水位为 None 时（引擎读全历史序列，首扫自然全量）
    - 逐股结果分叉：explicit_scope=True 每 code 落 strategy_task_stock_result
      （matched/run_status/message/signal_date），False 只推进计数

    返回 {scanned, updated, failed, paused}；任务不存在/定义缺失返回 failed
    带 reason。任务扫完自动置 done。
    """
    from . import get_definition, get_engine

    task = strategy_store.get_task(task_id)
    if task is None:
        return {"scanned": 0, "updated": 0, "failed": [{"reason": f"任务 {task_id} 不存在"}], "paused": False}
    definition = get_definition(task["strategy_id"])
    engine = get_engine(task["strategy_id"]) or get_engine(definition.engine_key if definition else "")
    if definition is None or engine is None:
        reason = f"策略定义/引擎缺失: {task['strategy_id']}"
        log.warning("run_task 跳过: %s", reason)
        return {"scanned": 0, "updated": 0, "failed": [{"reason": reason}], "paused": False}

    codes, explicit_scope = _task_codes(task)

    # 进度总数按当前范围长度刷新（范围编辑后总数随之变化，design D2）
    scanned = task.get("progress_scanned") or 0
    total = len(codes)
    if task.get("progress_total") != total:
        strategy_store.set_task_status(task_id, task["status"], scanned=scanned, total=total)
        task["progress_total"] = total

    # 已扫前缀跳过（remaining 续跑；full 在 resume 时清零，此处恒为 0）
    pending_codes = codes[scanned:] if scanned <= total else []
    if batch and batch > 0:
        pending_codes = pending_codes[:batch]

    params = task["params"]
    params_version = task["params_version"]
    cursors = strategy_store.get_scan_cursors(task_id)
    scan_with_params = getattr(engine, "scan_with_params", None)

    updated = 0
    failed = []
    paused = False
    scan_count = 0  # 本轮实际扫描的 code 数（不含跳过前缀）

    for code in pending_codes:
        # code 边界：检查暂停（design D4——status 翻转后下一边界停止）
        status = strategy_store.get_task_status(task_id)
        if status is None or status != "running":
            paused = True
            log.info("run_task %s 在 code=%s 边界暂停（status=%s）", task_id, code, status)
            break

        watermark = cursors.get(code)
        try:
            if scan_with_params is not None:
                events = scan_with_params(
                    code,
                    params,
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
            scan_count += 1
            scanned += 1
            matched = bool(events)
            if events:
                strategy_store.upsert_signals(task_id, events, params_version)
                updated += 1
                # 推进水位（事件里带 watermark_new；引擎无事件但有新数据时
                # 由 scan 的空返回兜底——空返回即无演进，不推进）
                new_wm = events[0].get("watermark_new")
                if new_wm:
                    strategy_store.set_scan_cursor(task_id, code, str(new_wm))
            elif watermark is None:
                # 首扫无信号（该 code 不满足策略条件）：也要推进水位，
                # 否则每个调度周期都会重扫全历史
                new_wm = _latest_time_key(code)
                if new_wm:
                    strategy_store.set_scan_cursor(task_id, code, new_wm)

            # 逐股结果分叉（spec「逐股结果按范围分叉」）：显式范围每 code 落行
            # （UNIQUE(task_id, code) 重跑覆盖）；全量范围不落
            if explicit_scope:
                signal_date = events[0]["signal_date"] if events else None
                message = None
                if events:
                    message = f"命中 {len(events)} 条信号"
                strategy_store.upsert_stock_result(
                    task_id,
                    code,
                    matched=matched,
                    run_status="ok",
                    params_version=params_version,
                    message=message,
                    signal_date=signal_date,
                )

            # 每 code 提交进度（design D4 乐观进度）
            strategy_store.set_task_status(
                task_id, "running", scanned=scanned, total=total
            )
        except Exception as e:
            # 单键失败不中断整批：计数推进 + 失败摘要 + 显式范围落 failed 结果行
            log.warning("扫描失败 task=%s code=%s: %s", task_id, code, e)
            scan_count += 1
            scanned += 1
            failed.append({"code": code, "error": str(e)})
            if explicit_scope:
                try:
                    strategy_store.upsert_stock_result(
                        task_id,
                        code,
                        matched=False,
                        run_status="failed",
                        params_version=params_version,
                        message=str(e),
                        signal_date=None,
                    )
                except Exception:
                    log.exception("逐股失败结果落库异常 task=%s code=%s", task_id, code)
            strategy_store.set_task_status(
                task_id, "running", scanned=scanned, total=total
            )

    # 扫完（未暂停且无剩余）→ done（spec：执行完成）
    if not paused and scanned >= total:
        strategy_store.set_task_status(task_id, "done", scanned=scanned, total=total)

    log.info(
        "run_task %s(%s) round_scanned=%d progress=%d/%d updated=%d failed=%d paused=%s",
        task_id, task["strategy_id"], scan_count, scanned, total,
        updated, len(failed), paused,
    )
    return {"scanned": scan_count, "updated": updated, "failed": failed, "paused": paused}


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


def run_eod_tasks(batch: int = 0) -> list[dict]:
    """EOD 日终调度：全部 persistent 任务增量扫描（design D4）。

    只取 mode='persistent' 的任务（test 任务不参与日终调度，spec
    「日终增量扫描」）；水位门不变（无新 K 线的 code 不重扫）。
    任务处于 running 状态时跳过本轮（避免与单 worker 执行器竞争）。
    返回各任务摘要列表；单任务失败不影响其余任务。
    """
    summaries = []
    for task in strategy_store.list_persistent_tasks():
        try:
            if task["status"] == "running":
                # 执行器正在跑该任务（启动/续跑入口），本轮 EOD 跳过防竞争
                summaries.append({
                    "task_id": task["id"],
                    "strategy_id": task["strategy_id"],
                    "scanned": 0, "updated": 0, "failed": [],
                    "skipped": "running",
                })
                continue
            # EOD 增量：临时置 running 防并发重入，扫完自动回 done
            strategy_store.set_task_status(task["id"], "running")
            summaries.append({
                "task_id": task["id"],
                "strategy_id": task["strategy_id"],
                **run_task(task["id"], batch=batch),
            })
        except Exception as e:
            log.exception("策略扫描失败 task=%s", task["id"])
            # 异常时任务状态复位（不留 running 残留态）
            try:
                strategy_store.set_task_status(task["id"], "done")
            except Exception:
                pass
            summaries.append({
                "task_id": task["id"],
                "strategy_id": task["strategy_id"],
                "scanned": 0, "updated": 0,
                "failed": [{"reason": str(e)}],
            })
    return summaries
