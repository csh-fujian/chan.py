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
    system,
    watchlist,
)

log = logging.getLogger("meta_sync_scheduler")

# 到期检查间隔（秒）：默认 3600（小时级），可用环境变量覆盖（可测试性）
META_SYNC_INTERVAL_SECONDS = int(os.environ.get("META_SYNC_INTERVAL_SECONDS", "3600"))


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


@asynccontextmanager
async def _lifespan(app: FastAPI):
    task = asyncio.create_task(_meta_sync_scheduler())
    try:
        yield
    finally:
        task.cancel()
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- 挂载业务路由 ----
app.include_router(stocks.router)
app.include_router(watchlist.router)
app.include_router(bsp.router)
app.include_router(monitor.router)
app.include_router(performance.router)
app.include_router(screener.router)
app.include_router(alerts.router)
app.include_router(system.router)
app.include_router(qa.router)
