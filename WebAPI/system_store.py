# -*- coding: utf-8 -*-
"""
System DAO — /system 权限管理页的用户/角色/权限读写（B 套 RBAC 表）。

数据表（init.sql Part 3）：app_user / role / permission / role_permission。
契约见 system-page-change design D2；守卫在 routers/system.py 挂载：
读接口 require_menu_system、写接口 require_manage。

约束（spec system-management）：
- 用户单角色（app_user.role_id），绑定/换角色均为覆盖式，原角色关系自动解除
- admin 用户（所属角色 is_admin=true）不可删除、不可停用、不可被改出 admin 角色
- admin 角色不可删除、其权限不可修改（name/description 编辑允许）
- 仍有用户绑定的角色不可删除（业务层 409，不依赖 FK 报错）

PG 连接失败直接 503、不做内存回退（对齐 llm_store）。
"""

import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import HTTPException

from .config import PG_DSN

log = logging.getLogger("system_store")


def _get_pg_conn():
    """获取 PG 连接，PG_DSN 未配置或 PG 不可达时抛 503（无内存回退）。"""
    if not PG_DSN:
        raise HTTPException(status_code=503, detail="数据库暂时不可用，请稍后重试")
    import psycopg2

    try:
        return psycopg2.connect(PG_DSN)
    except psycopg2.OperationalError as e:
        log.warning("PG 不可达: %s", e)
        raise HTTPException(
            status_code=503, detail="数据库暂时不可用，请稍后重试"
        ) from e


# ---- 行转换 ----

def _is_unique_violation(e: Exception) -> bool:
    """是否唯一约束冲突（用户名/角色 code 并发重复插入兜底）。"""
    import psycopg2

    return isinstance(e, psycopg2.errors.UniqueViolation)


def _ms_epoch(dt: Optional[datetime]) -> Optional[int]:
    """TIMESTAMPTZ → 毫秒 epoch 数字（前端 User.created_at: number）。"""
    if dt is None:
        return None
    return int(dt.timestamp() * 1000)


def _user_to_dict(row: tuple) -> dict:
    """(id, username, display_name, role_code, role_name, enabled, created_at) → dict。"""
    user_id, username, nickname, role_code, role_name, enabled, created_at = row
    return {
        "id": user_id,
        "username": username,
        "nickname": nickname,
        "role": role_code,
        "role_name": role_name,
        "status": "active" if enabled else "disabled",
        "created_at": _ms_epoch(created_at),
    }


# ---- 内部工具 ----

def _fetch_user_row(cur, user_id: int) -> Optional[tuple]:
    """查用户 + 角色行：(id, username, display_name, role_code, role_name, enabled,
    created_at, role_id, role_is_admin)。"""
    cur.execute(
        """SELECT u.id, u.username, u.display_name, r.code, r.name, u.enabled,
                  u.created_at, u.role_id, r.is_admin
           FROM app_user u JOIN role r ON u.role_id = r.id
           WHERE u.id = %s""",
        (user_id,),
    )
    return cur.fetchone()


def _require_user_row(cur, user_id: int) -> tuple:
    row = _fetch_user_row(cur, user_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"用户 {user_id} 不存在")
    return row


def _require_role_row(cur, role_id: int) -> tuple:
    """查角色行：(id, name, code, description, is_admin)。"""
    cur.execute(
        "SELECT id, name, code, description, is_admin FROM role WHERE id = %s",
        (role_id,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"角色 {role_id} 不存在")
    return row


def _role_id_by_code(cur, role_code: str) -> int:
    cur.execute("SELECT id FROM role WHERE code = %s", (role_code,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"角色 {role_code} 不存在")
    return row[0]


def _fetch_role_perms(cur, role_id: int) -> list:
    cur.execute(
        """SELECT p.code FROM permission p
           JOIN role_permission rp ON rp.permission_id = p.id
           WHERE rp.role_id = %s ORDER BY p.id""",
        (role_id,),
    )
    return [r[0] for r in cur.fetchall()]


def _user_count_of_role(cur, role_id: int) -> int:
    cur.execute("SELECT COUNT(*) FROM app_user WHERE role_id = %s", (role_id,))
    return cur.fetchone()[0]


def _check_admin_user_protected(row: tuple, action: str) -> None:
    """admin 用户保护：所属角色 is_admin=true 时禁止删除/停用/改出 admin 角色。"""
    if row[8]:  # role_is_admin
        raise HTTPException(status_code=403, detail=f"admin 用户{action}")


# ---- 用户查询（design D2 GET /users） ----

def list_users(
    username: str = "",
    role_code: str = "",
    status: str = "",
    created_from: str = "",
    created_to: str = "",
) -> list[dict]:
    """四条件 AND 组合查询（均可选、不分页），返回用户列表。"""
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            conditions: list[str] = []
            params: list[Any] = []
            if username:
                conditions.append("u.username ILIKE %s")
                params.append(f"%{username}%")
            if role_code:
                conditions.append("r.code = %s")
                params.append(role_code)
            if status == "active":
                conditions.append("u.enabled = TRUE")
            elif status == "disabled":
                conditions.append("u.enabled = FALSE")
            if created_from:
                conditions.append("u.created_at::date >= %s::date")
                params.append(created_from)
            if created_to:
                conditions.append("u.created_at::date <= %s::date")
                params.append(created_to)

            where_clause = ""
            if conditions:
                where_clause = "WHERE " + " AND ".join(conditions)

            cur.execute(
                f"""SELECT u.id, u.username, u.display_name, r.code, r.name,
                           u.enabled, u.created_at
                    FROM app_user u JOIN role r ON u.role_id = r.id
                    {where_clause}
                    ORDER BY u.id""",
                params,
            )
            return [_user_to_dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_user(user_id: int) -> Optional[dict]:
    """单个用户（字段同 list_users）。"""
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            row = _fetch_user_row(cur, user_id)
            if not row:
                return None
            return _user_to_dict(row[:7])
    finally:
        conn.close()


# ---- 用户写操作（design D2 POST/PUT/DELETE /users + reset-password） ----

def create_user(
    username: str, nickname: str, password_hash: str, role_code: str
) -> dict:
    """创建用户；用户名重复 → 409，角色 code 不存在 → 404。"""
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM app_user WHERE username = %s", (username,))
            if cur.fetchone():
                raise HTTPException(status_code=409, detail="用户名已存在")

            role_id = _role_id_by_code(cur, role_code)
            try:
                cur.execute(
                    """INSERT INTO app_user (username, password_hash, display_name, role_id, enabled)
                       VALUES (%s, %s, %s, %s, TRUE)
                       RETURNING id""",
                    (username, password_hash, nickname, role_id),
                )
                user_id = cur.fetchone()[0]
            except Exception as e:  # 并发重复插入兜底（uq_app_user_username）
                conn.rollback()
                if _is_unique_violation(e):
                    raise HTTPException(status_code=409, detail="用户名已存在") from e
                raise
            conn.commit()

            row = _require_user_row(cur, user_id)
            return _user_to_dict(row[:7])
    finally:
        conn.close()


def update_user(
    user_id: int,
    nickname: Optional[str] = None,
    role_code: Optional[str] = None,
    status: Optional[str] = None,
) -> dict:
    """局部更新用户（昵称/角色/状态）；admin 用户删除/停用/改出 admin 角色 → 403。"""
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            row = _require_user_row(cur, user_id)

            new_role_id: Optional[int] = None
            # admin 保护：停用 / 改出 admin 角色（改昵称允许）
            if status == "disabled":
                _check_admin_user_protected(row, "不可停用")
            if role_code is not None:
                new_role_id = _role_id_by_code(cur, role_code)
                cur.execute("SELECT is_admin FROM role WHERE id = %s", (new_role_id,))
                new_is_admin = cur.fetchone()[0]
                if row[8] and not new_is_admin:
                    _check_admin_user_protected(row, "不可改出 admin 角色")

            sets: list[str] = []
            params: list[Any] = []
            if nickname is not None:
                sets.append("display_name = %s")
                params.append(nickname)
            if new_role_id is not None:
                sets.append("role_id = %s")
                params.append(new_role_id)
            if status is not None:
                sets.append("enabled = %s")
                params.append(status == "active")

            if sets:
                cur.execute(
                    f"UPDATE app_user SET {', '.join(sets)} WHERE id = %s",
                    params + [user_id],
                )
            conn.commit()

            row = _require_user_row(cur, user_id)
            return _user_to_dict(row[:7])
    finally:
        conn.close()


def delete_user(user_id: int) -> None:
    """删除用户；admin 用户 → 403。"""
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            row = _require_user_row(cur, user_id)
            _check_admin_user_protected(row, "不可删除")
            cur.execute("DELETE FROM app_user WHERE id = %s", (user_id,))
        conn.commit()
    finally:
        conn.close()


def set_password(user_id: int, password_hash: str) -> None:
    """重置口令（写入 bcrypt hash，原口令失效）。"""
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            _require_user_row(cur, user_id)
            cur.execute(
                "UPDATE app_user SET password_hash = %s WHERE id = %s",
                (password_hash, user_id),
            )
        conn.commit()
    finally:
        conn.close()


# ---- 角色查询（design D2 GET /roles、GET /roles/{id}/users） ----

def list_roles(name: str = "") -> list[dict]:
    """角色列表（name 模糊可选），含 user_count / perms / is_admin。"""
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            if name:
                cur.execute(
                    """SELECT id, name, code, description, is_admin FROM role
                       WHERE name ILIKE %s ORDER BY id""",
                    (f"%{name}%",),
                )
            else:
                cur.execute(
                    "SELECT id, name, code, description, is_admin FROM role ORDER BY id"
                )
            rows = cur.fetchall()

            cur.execute("SELECT role_id, COUNT(*) FROM app_user GROUP BY role_id")
            count_map = dict(cur.fetchall())

            cur.execute(
                """SELECT rp.role_id, p.code FROM role_permission rp
                   JOIN permission p ON p.id = rp.permission_id
                   ORDER BY rp.role_id, p.id"""
            )
            perm_map: dict[int, list] = {}
            for role_id, code in cur.fetchall():
                perm_map.setdefault(role_id, []).append(code)
    finally:
        conn.close()

    return [
        {
            "id": r[0],
            "name": r[1],
            "code": r[2],
            "description": r[3],
            "is_admin": r[4],
            "user_count": count_map.get(r[0], 0),
            "perms": perm_map.get(r[0], []),
        }
        for r in rows
    ]


def list_role_users(role_id: int) -> list[dict]:
    """角色下已绑定用户（字段同用户条件查询）。"""
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            _require_role_row(cur, role_id)
            cur.execute(
                """SELECT u.id, u.username, u.display_name, r.code, r.name,
                          u.enabled, u.created_at
                   FROM app_user u JOIN role r ON u.role_id = r.id
                   WHERE u.role_id = %s
                   ORDER BY u.id""",
                (role_id,),
            )
            return [_user_to_dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


# ---- 角色-用户绑定（design D2 PUT /roles/{id}/users，覆盖式单角色语义） ----

def bind_role_users(role_id: int, user_ids: list[int]) -> None:
    """把 user_ids 中的用户角色全部改为本角色（原角色关系自动解除）。

    user_ids 含 admin 用户且目标角色非 admin → 403（改出 admin 角色）。
    """
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            role = _require_role_row(cur, role_id)
            target_is_admin = role[4]

            if user_ids and not target_is_admin:
                cur.execute(
                    """SELECT u.id FROM app_user u JOIN role r ON u.role_id = r.id
                       WHERE u.id = ANY(%s) AND r.is_admin = TRUE""",
                    (user_ids,),
                )
                if cur.fetchone():
                    raise HTTPException(
                        status_code=403, detail="admin 用户不可改出 admin 角色"
                    )

            if user_ids:
                cur.execute(
                    "UPDATE app_user SET role_id = %s WHERE id = ANY(%s)",
                    (role_id, user_ids),
                )
        conn.commit()
    finally:
        conn.close()


# ---- 角色写操作（design D2 POST/PUT/DELETE /roles） ----

def create_role(
    name: str, code: str, description: str, perms: Optional[list[str]] = None
) -> dict:
    """创建角色；code 重复 → 409。默认无授权（perms 为空集合）。"""
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM role WHERE code = %s", (code,))
            if cur.fetchone():
                raise HTTPException(status_code=409, detail="角色代码已存在")

            try:
                cur.execute(
                    """INSERT INTO role (name, code, description, is_admin)
                       VALUES (%s, %s, %s, FALSE)
                       RETURNING id""",
                    (name, code, description),
                )
                role_id = cur.fetchone()[0]
            except Exception as e:  # 并发重复插入兜底（uq_role_code）
                conn.rollback()
                if _is_unique_violation(e):
                    raise HTTPException(status_code=409, detail="角色代码已存在") from e
                raise

            if perms:
                cur.execute(
                    """INSERT INTO role_permission (role_id, permission_id)
                       SELECT %s, id FROM permission WHERE code = ANY(%s)
                       ON CONFLICT (role_id, permission_id) DO NOTHING""",
                    (role_id, perms),
                )
            perms_out = _fetch_role_perms(cur, role_id)
        conn.commit()

        return {
            "id": role_id,
            "name": name,
            "code": code,
            "description": description,
            "is_admin": False,
            "user_count": 0,
            "perms": perms_out,
        }
    finally:
        conn.close()


def update_role(
    role_id: int,
    name: Optional[str] = None,
    description: Optional[str] = None,
    perms: Optional[list[str]] = None,
) -> None:
    """编辑角色（name/description 局部）；携带 perms 时全量替换角色权限。

    admin 角色携带 perms → 403（name/description 编辑允许，spec 仅限定删除与权限两处保护）。
    """
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            role = _require_role_row(cur, role_id)

            if perms is not None and role[4]:  # is_admin
                raise HTTPException(
                    status_code=403, detail="admin 角色权限不可修改"
                )

            sets: list[str] = []
            params: list[Any] = []
            if name is not None:
                sets.append("name = %s")
                params.append(name)
            if description is not None:
                sets.append("description = %s")
                params.append(description)
            if sets:
                cur.execute(
                    f"UPDATE role SET {', '.join(sets)} WHERE id = %s",
                    params + [role_id],
                )

            if perms is not None:
                # 全量替换：删差集 + 插入缺失（ON CONFLICT 幂等）
                cur.execute(
                    """DELETE FROM role_permission
                       WHERE role_id = %s
                         AND permission_id NOT IN (
                             SELECT id FROM permission WHERE code = ANY(%s))""",
                    (role_id, perms),
                )
                cur.execute(
                    """INSERT INTO role_permission (role_id, permission_id)
                       SELECT %s, id FROM permission WHERE code = ANY(%s)
                       ON CONFLICT (role_id, permission_id) DO NOTHING""",
                    (role_id, perms),
                )
        conn.commit()
    finally:
        conn.close()


def delete_role(role_id: int) -> None:
    """删除角色；admin 角色 → 403；仍有用户绑定 → 409（提示先转移）。"""
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            role = _require_role_row(cur, role_id)
            if role[4]:  # is_admin
                raise HTTPException(status_code=403, detail="admin 角色不可删除")

            if _user_count_of_role(cur, role_id) > 0:
                raise HTTPException(
                    status_code=409, detail="角色下仍有用户，请先转移其用户"
                )

            cur.execute("DELETE FROM role WHERE id = %s", (role_id,))
        conn.commit()
    finally:
        conn.close()


# ---- 权限清单（design D2 GET /permissions） ----

_CATEGORY_MAP = {"menu": "菜单", "button": "管理"}


def list_permissions() -> list[dict]:
    """全部权限项：{id, code, name, category}；type→category：menu→菜单、button→管理。"""
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, code, name, type FROM permission ORDER BY id")
            rows = cur.fetchall()
    finally:
        conn.close()

    return [
        {
            "id": r[0],
            "code": r[1],
            "name": r[2],
            "category": _CATEGORY_MAP.get(r[3], r[3]),
        }
        for r in rows
    ]
