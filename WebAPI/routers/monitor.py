# -*- coding: utf-8 -*-
"""
Monitor 路由 — 交易监控 API。
"""

import re

from fastapi import APIRouter, HTTPException, Query

from ..llm_client import LLMError, complete
from ..llm_prompts import ATTRIBUTION_SYSTEM_PROMPT, build_attribution_prompt
from ..llm_store import resolve_llm_config
from ..monitor_store import (
    create_monitor,
    end_monitor,
    get_aggregate_profit_series,
    get_attribution,
    get_monitor,
    get_profit_series,
    list_completed,
    list_monitoring,
    save_attribution,
    settle_monitor,
)

router = APIRouter(prefix="/api/monitor", tags=["monitor"])


def _llm_error_to_http(e: LLMError) -> HTTPException:
    """LLM 调用失败 → HTTP 异常：错误透传，保留上游 4xx/5xx 语义。

    上游 401/403 归 502（属于供应商密钥/权限问题，非本服务会话问题——
    若透传 401 会被前端误判为登录过期强制登出）；其余 4xx 原样透传；
    5xx / 网络失败 / 响应解析失败 → 502。
    """
    status = 502
    m = re.search(r"LLM 返回 HTTP (\d+)", str(e))
    if m:
        upstream = int(m.group(1))
        if 400 <= upstream <= 499 and upstream not in (401, 403):
            status = upstream
    return HTTPException(status_code=status, detail=f"LLM 调用失败: {e}")


def _parse_reason_type(text: str) -> str:
    """从归因输出解析归因类别（计算逻辑错误 / 缠论失效），解析不出时回退 LLM归因。"""
    m = re.search(r"【归因类别】\s*([^\n\r]*)", text)
    category = m.group(1) if m else text[:200]
    if "计算逻辑" in category:
        return "计算逻辑错误"
    if "缠论" in category:
        return "缠论失效"
    return "LLM归因"


@router.get("")
async def monitor_list(keyword: str = Query("")):
    """监控列表（status='monitoring'）。"""
    return list_monitoring(keyword=keyword)


@router.get("/completed")
async def monitor_completed(keyword: str = Query("")):
    """监控完成列表。"""
    return list_completed(keyword=keyword)


@router.get("/profit-series")
async def monitor_aggregate_profit_series():
    """聚合盈利走势时序（所有已完成监控汇总）。"""
    return get_aggregate_profit_series()


@router.post("")
async def monitor_create(body: dict):
    """加入监控。"""
    code = body.get("code", "")
    kl_type = body.get("kl_type", "K_DAY")
    entry_price = body.get("entry_price", 0)
    monitor_start_time = body.get("monitor_start_time", "")

    if not code:
        raise HTTPException(status_code=422, detail="code is required")
    if not entry_price:
        raise HTTPException(status_code=422, detail="entry_price is required")

    result = create_monitor(
        code=code,
        kl_type=kl_type,
        entry_price=entry_price,
        monitor_start_time=monitor_start_time,
    )
    if not result:
        raise HTTPException(status_code=500, detail="Failed to create monitor")
    return result


@router.post("/{monitor_id}/end")
async def monitor_end(monitor_id: int, body: dict | None = None):
    """手动结束监控（可选传入 sold_price/sold_at/pnl_pct）。"""
    if body and body.get("sold_price"):
        result = settle_monitor(
            monitor_id,
            sold_price=body.get("sold_price", 0),
            sold_at=body.get("sold_at", ""),
            pnl_pct=body.get("pnl_pct", 0),
        )
    else:
        result = end_monitor(monitor_id)

    if not result:
        raise HTTPException(status_code=404, detail=f"Monitor {monitor_id} not found")
    return result


@router.get("/{monitor_id}")
async def monitor_detail(monitor_id: int):
    """监控详情。"""
    result = get_monitor(monitor_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Monitor {monitor_id} not found")
    return result


@router.post("/{monitor_id}/analyze")
async def monitor_analyze(monitor_id: int):
    """大模型归因分析（design D5/U5：真实生成、失败显式报错且不落库）。

    - 标的最终盈利 >= 5% → 400「仅分析盈利低于 5% 的标的」
    - LLM 未配置 → 400「LLM 未配置」
    - 供应商调用失败 → 错误透传（4xx/5xx 语义保留），不写任何占位归因记录
    - 成功才经 save_attribution 持久化
    """
    monitor = get_monitor(monitor_id)
    if not monitor:
        raise HTTPException(status_code=404, detail=f"Monitor {monitor_id} not found")

    pnl_pct = monitor.get("pnl_pct")
    if pnl_pct is None or float(pnl_pct) >= 5:
        raise HTTPException(status_code=400, detail="仅分析盈利低于 5% 的标的")

    llm_cfg = resolve_llm_config()
    if llm_cfg is None:
        raise HTTPException(status_code=400, detail="LLM 未配置")

    prompt = build_attribution_prompt(monitor)
    try:
        text = complete(
            ATTRIBUTION_SYSTEM_PROMPT,
            prompt,
            llm_cfg.get("timeout", 60.0),
            config=llm_cfg,
        )
    except LLMError as e:
        # 调用失败：不写任何占位归因记录
        raise _llm_error_to_http(e) from e

    if not text:
        raise HTTPException(status_code=502, detail="LLM 返回空归因结果")

    save_attribution(monitor_id, _parse_reason_type(text), text)
    return {"success": True, "id": monitor_id, "attribution": get_attribution(monitor_id)}


@router.get("/{monitor_id}/profit-series")
async def monitor_profit_series(monitor_id: int):
    """监控盈利走势时序。"""
    return get_profit_series(monitor_id)


@router.get("/{monitor_id}/attribution")
async def monitor_attribution(monitor_id: int):
    """监控归因列表。"""
    return get_attribution(monitor_id)