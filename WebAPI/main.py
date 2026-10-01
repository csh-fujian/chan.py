# -*- coding: utf-8 -*-
"""
FastAPI 应用 — chan-web-viewer 后端入口。

启动方式:
    uvicorn WebAPI.main:app --host 0.0.0.0 --port 8000

注意：必须在项目根目录运行，或设置 PYTHONPATH 指向项目根目录，
以确保 from ChanAnalyse.Common.CEnum / Chan / DataAPI 等导入正常工作。

业务路由（stocks/bsp/watchlist/monitor/performance/screener/alerts/system/qa）
已迁移到独立路由器文件中，通过 app.py 组装。本文件仅保留：
  - /api/health         健康检查
  - /api/auth/*          认证相关
  - /api/klines          K线 + 缠论计算
"""

from typing import Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel

from .app import app
from .auth import _authenticate, _make_token, get_current_user
from .cache import get_chan_cache
from .chan_service import (
    _compute_chan,
    _resolve_data_src,
    _resolve_kl_type,
)
from .serializer import serialize_chan


@app.get("/api/health")
async def health():
    """健康检查端点。"""
    return {"status": "ok"}


# ---- Auth 端点 ----


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
async def login(body: LoginRequest):
    """
    用户登录。

    验证用户名密码，返回 JWT token + 用户信息 + 权限列表。
    """
    user = _authenticate(body.username, body.password)
    token = _make_token(user["id"], user["username"])
    return {
        "token": f"{token}",
        "user": {
            "id": user["id"],
            "username": user["username"],
            "nickname": user["nickname"],
            "role": user["role"],
            "status": user["status"],
        },
        "perms": user["perms"],
    }


@app.post("/api/auth/me")
async def me(user: dict = Depends(get_current_user)):
    """
    获取当前登录用户信息。

    从 Authorization header 提取 Bearer token，返回用户信息 + 权限列表。
    权限读取走 B 套 RBAC（app_user，按 username 解析，design D3）。
    """
    return {
        "user": {
            "id": user["id"],
            "username": user["username"],
            "nickname": user["nickname"],
            "role": user["role"],
            "status": user["status"],
        },
        "perms": user["perms"],
    }


@app.post("/api/auth/logout")
async def logout():
    """登出（token 由前端清除，后端无状态）。"""
    return {"success": True}


@app.get("/api/klines")
async def get_klines(
    symbol: str = Query(..., description="股票代码，如 sz.000001"),
    period: str = Query("1d", description="K线周期: 5m/15m/30m/60m/1d/1w/1M"),
    end: Optional[int] = Query(
        None,
        description="增量加载分页游标（毫秒），返回 <= 此时间戳的更早K线",
    ),
):
    """
    获取指定标的的 K 线数据和完整缠论结构。

    返回 design.md D2 契约格式的 JSON:
    - klines: 原始 K 线 (timestamp/open/high/low/close/volume)
    - bi: 笔 (begin/end + dir + is_sure)
    - seg: 线段（同 bi 结构）
    - zs: 笔中枢 (begin_t/end_t/low/high/mid)
    - seg_zs: 线段中枢（同 zs 结构）
    - bsp: 买卖点 (t/v/is_buy/types)

    **增量加载 (design.md D4)**：
      ?end=<ts> 分页契约预留在接口签名上。阶段一（日线/常见周期数据量小）先全量返回
      K线+缠论；短周期历史过长时前端可通过 getBars('backward') 请求更早 K 线，
      此时后端返回 timestamp <= end 的 K 线子集，缠论 overlay 全量返回。
    """
    kl_type = _resolve_kl_type(period)
    data_src = _resolve_data_src(period)

    # 尝试缓存命中
    cache = get_chan_cache()
    cached_hit, cached_data = cache.get(symbol, kl_type)

    try:
        chan = _compute_chan(symbol, kl_type, data_src)
    except Exception as e:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Failed to compute Chan theory for {symbol!r} ({period}): {e}. "
                "The symbol may not exist in the database, or the data source may be unavailable."
            ),
        )

    result = serialize_chan(chan, kl_type)

    # 增量加载分页支持：若指定 end，只返回时间戳 <= end 的 K 线
    if end is not None and end > 0:
        result["klines"] = [k for k in result["klines"] if k["timestamp"] <= end]
    # 缠论 overlay 始终全量返回 -- 按时间戳锚定，与 K 线加载范围解耦

    # 写入缓存（异步容错：失败不影响响应）
    cache.set(symbol, kl_type, result)

    return result