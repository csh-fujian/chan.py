# -*- coding: utf-8 -*-
"""
Performance 路由 — 买卖点绩效统计 API（stub）。
"""

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/performance", tags=["performance"])


@router.get("/stats")
async def performance_stats():
    """买卖点绩效统计。"""
    return []


@router.get("/samples")
async def performance_samples(bsp_type: str = Query("")):
    """绩效样本明细。"""
    return []