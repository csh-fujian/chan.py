# -*- coding: utf-8 -*-
"""
System 路由 — 权限管理 API（用户/角色/权限，design D2）+ LLM 供应商预设管理（kline-page-change design D8.1）。

权限管理读接口挂 require_menu_system（menu:system）、写接口挂 require_manage（manage），
数据源为 B 套 RBAC（system_store）；LLM 供应商接口保持现状（require_manage）。
"""

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..auth import hash_password, require_manage, require_menu_system
from ..llm_client import LLMError, complete
from ..llm_store import (
    activate_provider,
    create_provider,
    delete_provider,
    get_provider,
    list_providers,
    resolve_llm_config,
)
from ..config import get_llm_env
from ..system_store import (
    bind_role_users,
    create_role,
    create_user,
    delete_role,
    delete_user,
    list_permissions,
    list_role_users,
    list_roles,
    list_users,
    set_password,
    update_role,
    update_user,
)

router = APIRouter(prefix="/api/system", tags=["system"])


def _check_date_param(value: str, name: str) -> str:
    """日期查询参数校验（YYYY-MM-DD），非法 → 422。"""
    if not value:
        return value
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{name} 需为 YYYY-MM-DD 日期")
    return value


# ---- LLM 供应商预设（全部挂 get_current_user + manage 权限，design D8.1） ----

class LlmProviderCreate(BaseModel):
    name: str
    base_url: str
    api_key: str
    model: str


class LlmTestBody(BaseModel):
    id: Optional[int] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None


@router.get("/llm")
async def llm_list(current_user: dict = Depends(require_manage)):
    """供应商预设列表（api_key 脱敏：仅尾 4 位）。"""
    return list_providers()


@router.post("/llm")
async def llm_create(body: LlmProviderCreate, current_user: dict = Depends(require_manage)):
    """新增供应商预设。"""
    return create_provider(body.name, body.base_url, body.api_key, body.model)


@router.post("/llm/test")
async def llm_test(body: LlmTestBody, current_user: dict = Depends(require_manage)):
    """
    测试连接：有 id 用该预设，否则有字段用字段（覆盖当前解析结果），否则用当前激活解析结果。
    返回 {ok, detail}（成功或供应商错误原文）。
    """
    if body.id is not None:
        prov = get_provider(body.id)
        if prov is None:
            raise HTTPException(status_code=404, detail=f"LLM provider {body.id} not found")
        cfg = {
            "base_url": prov["base_url"],
            "api_key": prov["api_key"],
            "model": prov["model"],
        }
    elif body.base_url or body.api_key or body.model:
        base = resolve_llm_config() or {"base_url": "", "api_key": "", "model": ""}
        cfg = {
            "base_url": body.base_url or base["base_url"],
            "api_key": body.api_key if body.api_key is not None else base["api_key"],
            "model": body.model or base["model"],
        }
    else:
        resolved = resolve_llm_config()
        if resolved is None:
            return {"ok": False, "detail": "LLM 未配置"}
        cfg = resolved

    if not cfg.get("base_url") or not cfg.get("model"):
        return {"ok": False, "detail": "LLM 未配置"}

    try:
        complete("", "ping", get_llm_env()["timeout"], config=cfg)
        return {"ok": True, "detail": "连接成功"}
    except LLMError as e:
        return {"ok": False, "detail": str(e)}


@router.post("/llm/{provider_id}/activate")
async def llm_activate(provider_id: int, current_user: dict = Depends(require_manage)):
    """激活预设（事务内先全部置 false 再置目标 true，active 唯一）。"""
    ok = activate_provider(provider_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"LLM provider {provider_id} not found")
    return {"success": True}


@router.delete("/llm/{provider_id}")
async def llm_delete(provider_id: int, current_user: dict = Depends(require_manage)):
    """删除预设。"""
    ok = delete_provider(provider_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"LLM provider {provider_id} not found")
    return {"success": True}


# ---- 用户管理（design D2） ----

class UserCreate(BaseModel):
    username: str = Field(min_length=1)
    nickname: str = ""
    password: str = Field(min_length=1)
    role: str = Field(min_length=1)


class UserUpdate(BaseModel):
    nickname: Optional[str] = None
    role: Optional[str] = None
    status: Optional[Literal["active", "disabled"]] = None


class ResetPasswordBody(BaseModel):
    password: str = Field(min_length=1)


@router.get("/users")
async def system_users(
    username: str = Query(""),
    role: str = Query(""),
    status: Literal["active", "disabled", ""] = Query(""),
    created_from: str = Query(""),
    created_to: str = Query(""),
    current_user: dict = Depends(require_menu_system),
):
    """用户条件查询（username 模糊 / role code 精确 / status / 创建日期区间，AND 组合，不分页）。"""
    _check_date_param(created_from, "created_from")
    _check_date_param(created_to, "created_to")
    return list_users(
        username=username,
        role_code=role,
        status=status,
        created_from=created_from,
        created_to=created_to,
    )


@router.post("/users")
async def system_create_user(
    body: UserCreate, current_user: dict = Depends(require_manage)
):
    """新建用户（密码 bcrypt 落库；用户名重复 → 409）。"""
    return create_user(
        username=body.username,
        nickname=body.nickname,
        password_hash=hash_password(body.password),
        role_code=body.role,
    )


@router.put("/users/{user_id}")
async def system_update_user(
    user_id: int, body: UserUpdate, current_user: dict = Depends(require_manage)
):
    """更新用户（昵称/角色/状态局部更新）；admin 用户不可停用、不可改出 admin 角色。"""
    update_user(
        user_id,
        nickname=body.nickname,
        role_code=body.role,
        status=body.status,
    )
    return {"success": True}


@router.delete("/users/{user_id}")
async def system_delete_user(
    user_id: int, current_user: dict = Depends(require_manage)
):
    """删除用户；admin 用户 → 403。"""
    delete_user(user_id)
    return {"success": True}


@router.post("/users/{user_id}/reset-password")
async def system_reset_password(
    user_id: int, body: ResetPasswordBody, current_user: dict = Depends(require_manage)
):
    """重置密码（管理员输入新密码，非空；原密码即失效）。"""
    set_password(user_id, hash_password(body.password))
    return {"success": True, "id": user_id}


# ---- 角色管理（design D2） ----

class RoleCreate(BaseModel):
    name: str = Field(min_length=1)
    code: str = Field(min_length=1)
    description: str = ""
    perms: Optional[list[str]] = None


class RoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    perms: Optional[list[str]] = None


class RoleUsersBody(BaseModel):
    user_ids: list[int]


@router.get("/roles")
async def system_roles(
    name: str = Query(""),
    current_user: dict = Depends(require_menu_system),
):
    """角色列表（name 模糊），返回 user_count / perms / is_admin。"""
    return list_roles(name=name)


@router.get("/roles/{role_id}/users")
async def system_role_users(
    role_id: int, current_user: dict = Depends(require_menu_system)
):
    """角色下已绑定用户列表（字段同用户条件查询）。"""
    return list_role_users(role_id)


@router.put("/roles/{role_id}/users")
async def system_bind_role_users(
    role_id: int, body: RoleUsersBody, current_user: dict = Depends(require_manage)
):
    """批量绑定：user_ids 中用户的角色全部改为本角色（覆盖式单角色，原角色自动解除）。"""
    bind_role_users(role_id, body.user_ids)
    return {"success": True}


@router.post("/roles")
async def system_create_role(
    body: RoleCreate, current_user: dict = Depends(require_manage)
):
    """新建角色（code 重复 → 409）；默认 perms 为空集合。"""
    return create_role(
        name=body.name, code=body.code, description=body.description, perms=body.perms
    )


@router.put("/roles/{role_id}")
async def system_update_role(
    role_id: int, body: RoleUpdate, current_user: dict = Depends(require_manage)
):
    """更新角色（name/description 局部）；携带 perms 时全量替换权限，admin 角色携带 perms → 403。"""
    update_role(
        role_id,
        name=body.name,
        description=body.description,
        perms=body.perms,
    )
    return {"success": True}


@router.delete("/roles/{role_id}")
async def system_delete_role(
    role_id: int, current_user: dict = Depends(require_manage)
):
    """删除角色；admin 角色 → 403；仍有用户绑定 → 409。"""
    delete_role(role_id)
    return {"success": True}


@router.get("/permissions")
async def system_permissions(current_user: dict = Depends(require_menu_system)):
    """权限清单（type→category：menu→菜单、button→管理），供权限配置页渲染勾选项。"""
    return list_permissions()