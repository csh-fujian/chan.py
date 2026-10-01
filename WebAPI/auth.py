# -*- coding: utf-8 -*-
"""
认证模块 — JWT 鉴权 + B 套 RBAC（app_user/role/permission/role_permission）。

支持:
- POST /api/auth/login  — 用户名+密码登录，返回 JWT token
- POST /api/auth/me     — 根据 token 获取当前用户信息
- POST /api/auth/logout — 登出

权限读取路径（system-page-change design D3）：
- 用户按 username 解析 `app_user`（token 中的 user_id 是历史签发载荷，不作为查询键）
- 密码用 bcrypt 对比 `app_user.password_hash`；`enabled=false` 拒绝登录
- 权限码经 `role → role_permission → permission.code` join 得出
- 角色 `is_admin=true` 视为拥有全部权限（守卫全放行，与种子全量授权互为兜底）
- `chan_user` 中存在而 `app_user` 中不存在的 username → 按未登录/401 处理

依赖: bcrypt（密码哈希）+ psycopg2
"""

import hashlib
import os
import time
from typing import Optional

from fastapi import Depends, Header, HTTPException


# ---- 简易 token 生成（不依赖第三方 JWT 库） ----

_SECRET = os.environ.get("CHAN_JWT_SECRET", "chan-py-dev-secret-key")
_TOKEN_TTL = 86400 * 7  # 7 天


def _make_token(user_id: int, username: str) -> str:
    """生成简易 token: base64(timestamp:user_id:username:signature)."""
    ts = int(time.time())
    payload = f"{ts}:{user_id}:{username}"
    sig = hashlib.sha256(f"{payload}:{_SECRET}".encode()).hexdigest()[:16]
    import base64
    token = base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()
    return token


def _verify_token(token: str) -> Optional[dict]:
    """验证 token，成功返回 {user_id, username}，失败返回 None."""
    import base64
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        parts = raw.split(":")
        if len(parts) < 4:
            return None
        ts_str, user_id_str, username, sig = parts[0], parts[1], parts[2], parts[3]
        ts = int(ts_str)
        user_id = int(user_id_str)
        # 检查过期
        if time.time() - ts > _TOKEN_TTL:
            return None
        # 校验签名
        expected_sig = hashlib.sha256(
            f"{ts}:{user_id}:{username}:{_SECRET}".encode()
        ).hexdigest()[:16]
        if not _timing_safe_equal(sig, expected_sig):
            return None
        return {"user_id": user_id, "username": username}
    except Exception:
        return None


def _timing_safe_equal(a: str, b: str) -> bool:
    """防时序攻击的字符串比较."""
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a, b):
        result |= ord(x) ^ ord(y)
    return result == 0


# ---- PG 用户查询（B 套 RBAC，design D3） ----

def _get_pg_conn():
    """获取 PG 连接."""
    import psycopg2
    pg_dsn = os.environ.get("PG_DSN")
    if not pg_dsn:
        raise HTTPException(
            status_code=500,
            detail="PG_DSN not configured. Set PG_DSN environment variable to enable auth.",
        )
    try:
        return psycopg2.connect(pg_dsn)
    except psycopg2.OperationalError as e:
        # PG 不可达：认证强依赖数据库，不能降级，返回 503 而非裸 500
        raise HTTPException(
            status_code=503,
            detail="数据库暂时不可用，请稍后重试",
        ) from e


def hash_password(plain: str) -> str:
    """bcrypt 哈希口令（写入 app_user.password_hash）。"""
    import bcrypt
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _check_password(plain: str, stored_hash: str) -> bool:
    """bcrypt 校验口令；哈希损坏/格式非法时按不匹配处理。"""
    import bcrypt
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), stored_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _load_perms(cur, role_id: int, is_admin: bool) -> list:
    """权限码：role → role_permission → permission.code；is_admin 视为拥有全部权限。"""
    if is_admin:
        cur.execute("SELECT code FROM permission")
    else:
        cur.execute(
            """SELECT p.code FROM permission p
               JOIN role_permission rp ON rp.permission_id = p.id
               WHERE rp.role_id = %s""",
            (role_id,),
        )
    return [r[0] for r in cur.fetchall()]


def _row_to_user(row, perms: list) -> dict:
    """app_user JOIN role 行 → 用户信息字典（保持 login/me 兼容字段）。"""
    user_id, uname, nickname, role_code, is_admin, enabled = row
    return {
        "id": user_id,
        "username": uname,
        "nickname": nickname,
        "role": role_code,
        "status": "active" if enabled else "disabled",
        "perms": perms,
        "is_admin": is_admin,
    }


def _load_user_by_username(cur, username: str) -> dict:
    """按 username 解析 app_user + role；不存在 → 401（chan_user 遗留用户按未登录处理）。"""
    cur.execute(
        """SELECT u.id, u.username, u.display_name, r.code, r.is_admin, u.enabled, u.role_id
           FROM app_user u JOIN role r ON u.role_id = r.id
           WHERE u.username = %s""",
        (username,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="用户不存在")

    _user_id, _uname, _nickname, _role_code, is_admin, enabled, role_id = row
    if not enabled:
        raise HTTPException(status_code=403, detail="账号已禁用")

    perms = _load_perms(cur, role_id, is_admin)
    return _row_to_user(
        (_user_id, _uname, _nickname, _role_code, is_admin, enabled), perms
    )


def _authenticate(username: str, password: str) -> dict:
    """验证用户名密码（app_user + bcrypt），返回用户信息字典."""
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT u.id, u.username, u.password_hash, u.display_name,
                          r.code, r.is_admin, u.enabled, u.role_id
                   FROM app_user u JOIN role r ON u.role_id = r.id
                   WHERE u.username = %s""",
                (username,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=401, detail="用户名或密码错误")

            user_id, uname, stored_hash, nickname, role_code, is_admin, enabled, role_id = row

            if not enabled:
                raise HTTPException(status_code=403, detail="账号已禁用")

            if not _check_password(password, stored_hash):
                raise HTTPException(status_code=401, detail="用户名或密码错误")

            perms = _load_perms(cur, role_id, is_admin)
            return {
                "id": user_id,
                "username": uname,
                "nickname": nickname,
                "role": role_code,
                "status": "active" if enabled else "disabled",
                "perms": perms,
                "is_admin": is_admin,
            }
    finally:
        conn.close()


def get_current_user(authorization: str = Header(default="")) -> dict:
    """从 Authorization header 提取当前用户（Dependency 方式，按 username 解析 app_user）。"""
    if not authorization:
        raise HTTPException(status_code=401, detail="未提供认证信息")

    token = authorization.replace("Bearer ", "")
    payload = _verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")

    # token 中的 user_id 为历史签发载荷（可能仍是 chan_user id），一律以 username 解析
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            return _load_user_by_username(cur, payload["username"])
    finally:
        conn.close()


def require_manage(user: dict = Depends(get_current_user)) -> dict:
    """依赖：get_current_user + manage 权限位检查（无权限 → 403；is_admin 全放行）。"""
    if user.get("is_admin") or "manage" in (user.get("perms") or []):
        return user
    raise HTTPException(status_code=403, detail="无管理权限")


def require_menu_system(user: dict = Depends(get_current_user)) -> dict:
    """依赖：/system 读接口守卫 — 需 menu:system 权限（无权限 → 403；is_admin 全放行）。"""
    if user.get("is_admin") or "menu:system" in (user.get("perms") or []):
        return user
    raise HTTPException(status_code=403, detail="无系统管理页面权限")