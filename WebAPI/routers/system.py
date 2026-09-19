# -*- coding: utf-8 -*-
"""
System 路由 — 权限管理 API（stub）。
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/users")
async def system_users():
    """用户列表。"""
    return []


@router.post("/users")
async def system_create_user(body: dict):
    """新建用户。"""
    return {"id": 0, "created_at": 0, **body}


@router.put("/users/{user_id}")
async def system_update_user(user_id: int, body: dict):
    """更新用户。"""
    return {"success": True}


@router.delete("/users/{user_id}")
async def system_delete_user(user_id: int):
    """删除用户。"""
    return {"success": True}


@router.post("/users/{user_id}/reset-password")
async def system_reset_password(user_id: int):
    """重置密码。"""
    return {"success": True, "id": user_id}


@router.get("/roles")
async def system_roles():
    """角色列表。"""
    return []


@router.post("/roles")
async def system_create_role(body: dict):
    """新建角色。"""
    return {"id": 0, "user_count": 0, **body}


@router.put("/roles/{role_id}")
async def system_update_role(role_id: int, body: dict):
    """更新角色。"""
    return {"success": True}


@router.delete("/roles/{role_id}")
async def system_delete_role(role_id: int):
    """删除角色。"""
    return {"success": True}


@router.get("/permissions")
async def system_permissions():
    """权限列表。"""
    return []