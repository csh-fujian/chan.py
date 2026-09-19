# -*- coding: utf-8 -*-
"""
Alerts 路由 — 预警管理 API（stub）。
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("/rules")
async def alerts_rules():
    """预警规则列表。"""
    return []


@router.post("/rules")
async def alerts_create_rule(body: dict):
    """新建预警规则。"""
    return {"id": 0, **body, "trigger_count": 0, "created_at": 0}


@router.put("/rules/{rule_id}")
async def alerts_update_rule(rule_id: int, body: dict):
    """更新预警规则。"""
    return {"success": True}


@router.delete("/rules/{rule_id}")
async def alerts_delete_rule(rule_id: int):
    """删除预警规则。"""
    return {"success": True}


@router.get("/notifications")
async def alerts_notifications():
    """站内通知列表。"""
    return []


@router.post("/notifications/read-all")
async def alerts_mark_all_read():
    """全部已读。"""
    return {"success": True}


@router.post("/notifications/{notif_id}/read")
async def alerts_mark_read(notif_id: int):
    """标记已读。"""
    return {"success": True}