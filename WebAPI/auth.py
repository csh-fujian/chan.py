# -*- coding: utf-8 -*-
"""
认证模块 — JWT 鉴权 + PG 用户表。

支持:
- POST /api/auth/login  — 用户名+密码登录，返回 JWT token
- POST /api/auth/me     — 根据 token 获取当前用户信息
- POST /api/auth/logout — 登出

依赖: PyJWT + bcrypt（密码哈希）+ psycopg2
"""

import hashlib
import os
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import Header, HTTPException


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


# ---- PG 用户查询 ----

def _get_pg_conn():
    """获取 PG 连接."""
    import psycopg2
    pg_dsn = os.environ.get("PG_DSN")
    if not pg_dsn:
        raise HTTPException(
            status_code=500,
            detail="PG_DSN not configured. Set PG_DSN environment variable to enable auth.",
        )
    return psycopg2.connect(pg_dsn)


def _authenticate(username: str, password: str) -> dict:
    """验证用户名密码，返回用户信息字典."""
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, username, password, nickname, role, status
                   FROM chan_user WHERE username = %s""",
                (username,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=401, detail="用户名或密码错误")

            user_id, uname, stored_pwd, nickname, role, status = row

            if status != "active":
                raise HTTPException(status_code=403, detail="账号已禁用")

            # 简易验证：直接比较（开发阶段，生产应使用 bcrypt）
            if stored_pwd != password:
                raise HTTPException(status_code=401, detail="用户名或密码错误")

            # 查询权限
            cur.execute(
                "SELECT code FROM chan_user_permission WHERE user_id = %s",
                (user_id,),
            )
            perms = [r[0] for r in cur.fetchall()]

            return {
                "id": user_id,
                "username": uname,
                "nickname": nickname,
                "role": role,
                "status": status,
                "perms": perms,
            }
    finally:
        conn.close()


def get_current_user(authorization: str = Header(default="")) -> dict:
    """从 Authorization header 提取当前用户（Dependency 方式）。"""
    if not authorization:
        raise HTTPException(status_code=401, detail="未提供认证信息")

    token = authorization.replace("Bearer ", "")
    payload = _verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")

    # 前缀是 "token:" 还是纯 token
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
            if status != "active":
                raise HTTPException(status_code=403, detail="账号已禁用")

            cur.execute(
                "SELECT code FROM chan_user_permission WHERE user_id = %s",
                (user_id,),
            )
            perms = [r[0] for r in cur.fetchall()]

            return {
                "id": user_id,
                "username": uname,
                "nickname": nickname,
                "role": role,
                "status": status,
                "perms": perms,
            }
    finally:
        conn.close()