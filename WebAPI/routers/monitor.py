# -*- coding: utf-8 -*-
"""
Monitor 路由 — 交易监控 API。
"""

from fastapi import APIRouter, HTTPException, Query

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
    """大模型归因分析（stub — 返回占位归因）。"""
    monitor = get_monitor(monitor_id)
    if not monitor:
        raise HTTPException(status_code=404, detail=f"Monitor {monitor_id} not found")

    # Stub 归因：写入一条占位归因记录
    existing = get_attribution(monitor_id)
    if not existing:
        save_attribution(monitor_id, "auto", "LLM 归因结果占位（待接入大模型）")

    return {"success": True, "id": monitor_id, "attribution": get_attribution(monitor_id)}


@router.get("/{monitor_id}/profit-series")
async def monitor_profit_series(monitor_id: int):
    """监控盈利走势时序。"""
    return get_profit_series(monitor_id)


@router.get("/{monitor_id}/attribution")
async def monitor_attribution(monitor_id: int):
    """监控归因列表。"""
    return get_attribution(monitor_id)