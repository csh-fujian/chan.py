# -*- coding: utf-8 -*-
"""
FastAPI 应用组装 — 挂载各 router，配置 CORS、中间件。
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

app = FastAPI(
    title="chan.py Web Viewer API",
    description="缠论技术分析 JSON API -- K 线 + 笔/线段/中枢/买卖点",
    version="0.1.0",
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