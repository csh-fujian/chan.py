# -*- coding: utf-8 -*-
"""
FastAPI 应用组装 — 挂载各 router，配置 CORS、中间件、内置到期检查调度。
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import meta_sync
from .routers import (
    alerts,
    bsp,
    monitor,
    performance,
    qa,
    screener,
    stocks,
    strategy,
    system,
    watchlist,
)

log = logging.getLogger("meta_sync_scheduler")
bsp_log = logging.getLogger("bsp_scheduler")
strategy_log = logging.getLogger("strategy_scheduler")

# 到期检查间隔（秒）：默认 3600（小时级），可用环境变量覆盖（可测试性）
META_SYNC_INTERVAL_SECONDS = int(os.environ.get("META_SYNC_INTERVAL_SECONDS", "3600"))

# ---- 买卖点补算调度（bsp-page-change D2：启动 + 低频 tick + 日终，电平触发可漏发自愈）----
# BSP_CATCHUP_ENABLED=0 关闭调度入口（回滚手段：关调度即可，引擎只写 PG）
# BSP_CATCHUP_TICK_SECONDS 低频 tick 间隔（默认 3600）
# BSP_CATCHUP_BATCH 每次 tick 最多补算键数（默认 20，分批跑游标天然断点可续；首次
#   全市场接入用 CLI: PYTHONPATH=. python -m WebAPI.incremental_engine --catch-up --limit 0）
# BSP_EOD_AT 日终触发时刻 "HH:MM"（默认 16:30，收盘后；日终为主、盘中预留）
BSP_CATCHUP_ENABLED = os.environ.get("BSP_CATCHUP_ENABLED", "1") != "0"
BSP_CATCHUP_TICK_SECONDS = int(os.environ.get("BSP_CATCHUP_TICK_SECONDS", "3600"))
BSP_CATCHUP_BATCH = int(os.environ.get("BSP_CATCHUP_BATCH", "20"))
BSP_EOD_AT = os.environ.get("BSP_EOD_AT", "16:30")

# ---- 策略信号扫描调度（strategy-signal-page design D4：EOD 复用 + 独立游标表）----
# STRATEGY_SCAN_ENABLED=0 关闭策略扫描（回滚手段：关调度即可）
STRATEGY_SCAN_ENABLED = os.environ.get("STRATEGY_SCAN_ENABLED", "1") != "0"


async def _meta_sync_scheduler(interval_seconds: Optional[int] = None) -> None:
    """内置到期检查协程（任务 4.3）。

    每 `META_SYNC_INTERVAL_SECONDS`（默认 1 小时）醒来一次；非 running 时调用
    due_domains() 做到期判定，有到期域即以 force=False 走与手动触发相同的后台执行
    路径（共用 _SYNC_RUNNING 防重入）；未到期时零网络请求。
    """
    interval = interval_seconds if interval_seconds is not None else META_SYNC_INTERVAL_SECONDS
    log.info("meta sync scheduler started, interval=%ss", interval)
    while True:
        await asyncio.sleep(interval)
        try:
            if stocks._SYNC_RUNNING:
                continue
            due = await asyncio.to_thread(meta_sync.due_domains)
            if not due:
                continue
            domains = [d for d in meta_sync.DOMAIN_ORDER if d in set(due)]
            log.info("due domains found: %s", domains)
            job_id = stocks._begin_market_sync(domains, force=False)
            if job_id is None:
                continue  # 手动任务刚好抢先 —— 共用防重入
            asyncio.create_task(stocks._run_market_sync_task(domains, False, job_id))
        except asyncio.CancelledError:
            log.info("meta sync scheduler cancelled")
            raise
        except Exception:  # 调度失败不影响服务
            log.exception("meta sync scheduler iteration failed")


async def _bsp_tick_loop() -> None:
    """低频 tick 水位补算（bsp-page-change 3.6：启动触发 + 定时触发）。

    启动即跑一批（电平触发：无论错过多少次调度，任何入口触发时自然补上），
    之后每 BSP_CATCHUP_TICK_SECONDS 醒来一批；每批最多 BSP_CATCHUP_BATCH 个键。
    """
    from .incremental_engine import catch_up

    first = True
    while True:
        if not first:
            await asyncio.sleep(BSP_CATCHUP_TICK_SECONDS)
        first = False
        try:
            result = await asyncio.to_thread(catch_up, None, None, None, BSP_CATCHUP_BATCH, False)
            if result["updated"] or result["failed"]:
                bsp_log.info(
                    "catch_up tick: scanned=%s updated=%s failed=%s",
                    result["scanned"], result["updated"], len(result["failed"]),
                )
        except asyncio.CancelledError:
            bsp_log.info("bsp tick loop cancelled")
            raise
        except Exception:
            bsp_log.exception("bsp catch_up tick failed")


def _seconds_until(hhmm: str) -> float:
    """距下一次 hh:mm（本地时间）的秒数。"""
    import datetime as _dt

    now = _dt.datetime.now()
    try:
        hour, minute = (int(x) for x in hhmm.split(":"))
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    except ValueError:
        bsp_log.warning("BSP_EOD_AT=%r 非法，回退 16:30", hhmm)
        target = now.replace(hour=16, minute=30, second=0, microsecond=0)
    if target <= now:
        target += _dt.timedelta(days=1)
    return (target - now).total_seconds()


async def _bsp_eod_loop() -> None:
    """日终流水线（bsp-page-change 3.7）：每日 BSP_EOD_AT 扫描当日有新增 K 线的股票补算。

    入口选择：服务内日终调度为主（与 _meta_sync_scheduler 同模式），CLI
    `python -m WebAPI.incremental_engine --eod` 为 cron 兜底，两入口共用同一实现。
    """
    from .incremental_engine import run_eod_pipeline

    while True:
        await asyncio.sleep(_seconds_until(BSP_EOD_AT))
        try:
            result = await asyncio.to_thread(run_eod_pipeline)
            bsp_log.info("eod pipeline: scanned=%s updated=%s", result["scanned"], result["updated"])
        except asyncio.CancelledError:
            bsp_log.info("bsp eod loop cancelled")
            raise
        except Exception:
            bsp_log.exception("bsp eod pipeline failed")


def _run_strategy_eod() -> dict:
    """策略日终扫描（strategy-signal-page 任务 3.2）：全部 enabled 实例增量扫描。

    对全部启用实例跑 scan_all_enabled（水位门：无新 K 线的 code 不重扫；
    幂等：唯一键 + ON CONFLICT ... WHERE frozen = FALSE）。返回汇总摘要
    {instances, scanned, updated, failed}。
    """
    from .strategy_engines.scheduler import scan_all_enabled

    summaries = scan_all_enabled()
    scanned = sum(s.get("scanned", 0) for s in summaries)
    updated = sum(s.get("updated", 0) for s in summaries)
    failed = sum(len(s.get("failed", [])) for s in summaries)
    return {
        "instances": len(summaries),
        "scanned": scanned,
        "updated": updated,
        "failed": failed,
    }


async def _strategy_eod_loop() -> None:
    """策略信号日终调度（strategy-signal-page design D4）。

    在 _bsp_eod_loop 触发点之后顺序执行（同一 BSP_EOD_AT 时刻，策略阶段在
    bsp 阶段之后追加），独立 try/except、独立 logger——策略扫描失败互不影响
    bsp 日终流水线（设计 D4「失败互不影响」）。
    """
    while True:
        await asyncio.sleep(_seconds_until(BSP_EOD_AT))
        try:
            result = await asyncio.to_thread(_run_strategy_eod)
            strategy_log.info(
                "strategy eod: instances=%s scanned=%s updated=%s failed=%s",
                result["instances"], result["scanned"], result["updated"], result["failed"],
            )
        except asyncio.CancelledError:
            strategy_log.info("strategy eod loop cancelled")
            raise
        except Exception:
            strategy_log.exception("strategy eod scan failed")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    tasks = [asyncio.create_task(_meta_sync_scheduler())]
    if BSP_CATCHUP_ENABLED:
        tasks.append(asyncio.create_task(_bsp_tick_loop()))
        tasks.append(asyncio.create_task(_bsp_eod_loop()))
    else:
        bsp_log.info("bsp catch-up scheduler disabled (BSP_CATCHUP_ENABLED=0)")
    # 策略扫描日终调度（strategy-signal-page design D4）：独立开关，bsp 关闭不影响
    if STRATEGY_SCAN_ENABLED:
        tasks.append(asyncio.create_task(_strategy_eod_loop()))
    else:
        strategy_log.info("strategy scan scheduler disabled (STRATEGY_SCAN_ENABLED=0)")
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="chan.py Web Viewer API",
    description="缠论技术分析 JSON API -- K 线 + 笔/线段/中枢/买卖点",
    version="0.1.0",
    lifespan=_lifespan,
)

# ---- CORS 中间件 ----
# 5174 = Vite 在 5173 被占时的自动换端口（本地开发便利）
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- 挂载业务路由 ----
app.include_router(stocks.router)
app.include_router(watchlist.router)
app.include_router(bsp.router)
app.include_router(monitor.router)
app.include_router(strategy.router)
app.include_router(performance.router)
app.include_router(screener.router)
app.include_router(alerts.router)
app.include_router(system.router)
app.include_router(qa.router)
