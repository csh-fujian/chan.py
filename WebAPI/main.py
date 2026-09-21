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

import os
from typing import Optional

from fastapi import Header, HTTPException, Query
from pydantic import BaseModel

from ChanAnalyse.Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from ChanAnalyse.Chan import CChan
from ChanAnalyse.ChanConfig import CChanConfig

from .app import app
from .auth import _authenticate, _make_token, _verify_token
from .cache import get_chan_cache
from .serializer import serialize_chan

# ---- 周期字符串 -> KL_TYPE 映射 ----
PERIOD_MAP: dict[str, KL_TYPE] = {
    "1m": KL_TYPE.K_1M,
    "5m": KL_TYPE.K_5M,
    "1h": KL_TYPE.K_60M,
    "1d": KL_TYPE.K_DAY,
    "1w": KL_TYPE.K_WEEK,
    "1M": KL_TYPE.K_MON,
}


def _resolve_kl_type(period: str) -> KL_TYPE:
    """将前端周期字符串转换为 KL_TYPE 枚举，非法值抛出 400。"""
    kl_type = PERIOD_MAP.get(period)
    if kl_type is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported period: {period!r}. "
                f"Valid values: {list(PERIOD_MAP.keys())}"
            ),
        )
    return kl_type


def _resolve_data_src(period: str) -> str:
    """
    确定数据源。

    优先使用 DuckDB 离线源；如果 DuckDB 文件不存在，对日线使用 BaoStock 兜底。
    其他周期在 DuckDB 缺失时报错。
    """
    from ChanAnalyse.DataAPI.KLineStore import DEFAULT_DB_PATH

    if os.path.exists(DEFAULT_DB_PATH):
        return "custom:DuckDBAPI.CDuckDB"

    if period == "1d":
        return DATA_SRC.BAO_STOCK

    raise HTTPException(
        status_code=404,
        detail=(
            f"DuckDB file {DEFAULT_DB_PATH!r} not found, "
            f"and BaoStock fallback only supports daily ('1d') period."
        ),
    )


def _compute_chan(symbol: str, kl_type: KL_TYPE, data_src: str) -> CChan:
    """创建 CChan 实例并执行完整计算。"""
    config = CChanConfig(
        conf={"trigger_step": False, "kl_data_check": False},
    )
    chan = CChan(
        code=symbol,
        data_src=data_src,
        lv_list=[kl_type],
        config=config,
        autype=AUTYPE.QFQ,
    )
    return chan


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
async def me(authorization: str = Header(default="")):
    """
    获取当前登录用户信息。

    从 Authorization header 提取 Bearer token，返回用户信息 + 权限列表。
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="未提供认证信息")

    token = authorization.replace("Bearer ", "")
    payload = _verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="登录已过期")

    from .auth import _get_pg_conn

    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, nickname, role, status FROM chan_user WHERE id = %s",
                (payload["user_id"],),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=401, detail="用户不存在")
            user_id, uname, nickname, role, status = row
            cur.execute(
                "SELECT code FROM chan_user_permission WHERE user_id = %s",
                (user_id,),
            )
            perms = [r[0] for r in cur.fetchall()]
            return {
                "user": {
                    "id": user_id,
                    "username": uname,
                    "nickname": nickname,
                    "role": role,
                    "status": status,
                },
                "perms": perms,
            }
    finally:
        conn.close()


@app.post("/api/auth/logout")
async def logout():
    """登出（token 由前端清除，后端无状态）。"""
    return {"success": True}


@app.get("/api/klines")
async def get_klines(
    symbol: str = Query(..., description="股票代码，如 sz.000001"),
    period: str = Query("1d", description="K线周期: 1m/5m/1h/1d/1w/1M"),
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