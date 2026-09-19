# -*- coding: utf-8 -*-
"""
Screener 路由 — 选股器 API（stub）。
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/screener", tags=["screener"])


@router.get("/strategies")
async def screener_strategies():
    """策略列表。"""
    return []


@router.post("/strategies")
async def screener_create_strategy(body: dict):
    """新建策略。"""
    return {"id": 0, **body, "last_run": None, "result_count": 0}


@router.put("/strategies/{strategy_id}")
async def screener_update_strategy(strategy_id: int, body: dict):
    """更新策略。"""
    return {"success": True}


@router.delete("/strategies/{strategy_id}")
async def screener_delete_strategy(strategy_id: int):
    """删除策略。"""
    return {"success": True}


@router.post("/strategies/{strategy_id}/run")
async def screener_run_strategy(strategy_id: int):
    """执行策略。"""
    return {"results": [], "count": 0}