# -*- coding: utf-8 -*-
"""
LLM 供应商预设 DAO — llm_provider 表（kline-page-change design D8.1）。

配置解析链（每请求实时取、不缓存进程内，切换即时生效）：
    1. PG 中 active=true 的预设
    2. 环境变量 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL / LLM_TIMEOUT（默认 60s）
    3. 均无 → None（路由侧转 503「LLM 未配置」）

约束：至多一条 active=true（activate_provider 事务内先全部置 false 再置目标 true）。
PG 连接失败直接 503、不做内存回退（对齐 qa_store）。
"""

import logging
from typing import Any, Optional

from fastapi import HTTPException

from .config import PG_DSN, get_llm_env

log = logging.getLogger("llm_store")


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


def mask_api_key(api_key: str) -> str:
    """api_key 脱敏：仅保留尾 4 位，形如 "****abcd"。"""
    if not api_key:
        return ""
    return "****" + api_key[-4:]


# ---- 表确保 ----

def _ensure_tables():
    """惰性建表（与 init.sql 幂等 DDL 一致）。"""
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_provider (
                    id          SERIAL PRIMARY KEY,
                    name        TEXT NOT NULL,
                    base_url    TEXT NOT NULL,
                    api_key     TEXT NOT NULL,
                    model       TEXT NOT NULL,
                    active      BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        conn.commit()
    finally:
        conn.close()


def _row_to_provider(row: tuple, *, mask: bool) -> dict[str, Any]:
    provider_id, name, base_url, api_key, model, active = row
    return {
        "id": provider_id,
        "name": name,
        "base_url": base_url,
        "api_key": mask_api_key(api_key) if mask else api_key,
        "model": model,
        "active": bool(active),
    }


# ---- llm_provider CRUD ----

def list_providers() -> list[dict[str, Any]]:
    """供应商预设列表（api_key 脱敏）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, name, base_url, api_key, model, active
                   FROM llm_provider
                   ORDER BY id"""
            )
            return [_row_to_provider(r, mask=True) for r in cur.fetchall()]
    finally:
        conn.close()


def get_provider(provider_id: int) -> Optional[dict[str, Any]]:
    """取单条预设（含完整 api_key，供测试连接/激活解析用）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, name, base_url, api_key, model, active
                   FROM llm_provider WHERE id = %s""",
                (provider_id,),
            )
            row = cur.fetchone()
            return _row_to_provider(row, mask=False) if row else None
    finally:
        conn.close()


def get_active_provider() -> Optional[dict[str, Any]]:
    """取 active=true 的预设（含完整 api_key）；至多一条。"""
    _ensure_tables()
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, name, base_url, api_key, model, active
                   FROM llm_provider WHERE active = TRUE
                   ORDER BY id LIMIT 1"""
            )
            row = cur.fetchone()
            return _row_to_provider(row, mask=False) if row else None
    finally:
        conn.close()


def create_provider(name: str, base_url: str, api_key: str, model: str) -> dict[str, Any]:
    """新增供应商预设，返回脱敏后的记录。"""
    _ensure_tables()
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO llm_provider (name, base_url, api_key, model)
                   VALUES (%s, %s, %s, %s)
                   RETURNING id, name, base_url, api_key, model, active""",
                (name, base_url, api_key, model),
            )
            row = cur.fetchone()
        conn.commit()
        return _row_to_provider(row, mask=True)
    finally:
        conn.close()


def activate_provider(provider_id: int) -> bool:
    """激活指定预设：事务内先全部置 false 再置目标 true（active 唯一）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM llm_provider WHERE id = %s", (provider_id,))
            if cur.fetchone() is None:
                conn.rollback()
                return False
            cur.execute("UPDATE llm_provider SET active = FALSE WHERE active = TRUE")
            cur.execute(
                "UPDATE llm_provider SET active = TRUE WHERE id = %s",
                (provider_id,),
            )
        conn.commit()
        return True
    finally:
        conn.close()


def delete_provider(provider_id: int) -> bool:
    """删除预设，返回是否存在并删除。"""
    _ensure_tables()
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM llm_provider WHERE id = %s", (provider_id,))
            affected = cur.rowcount
        conn.commit()
        return affected > 0
    finally:
        conn.close()


# ---- 三层解析链（design D8.1） ----

def resolve_llm_config() -> Optional[dict[str, Any]]:
    """
    解析当前 LLM 配置（每请求实时取、不缓存进程内）。

    PG active=true 预设 → env 兜底 → 均无返回 None。
    返回 {base_url, api_key, model, timeout, source}。
    """
    prov = get_active_provider()
    env = get_llm_env()
    if prov is not None:
        return {
            "base_url": prov["base_url"],
            "api_key": prov["api_key"],
            "model": prov["model"],
            "timeout": env["timeout"],
            "source": "pg",
        }
    if env["base_url"] and env["model"]:
        return {
            "base_url": env["base_url"],
            "api_key": env["api_key"],
            "model": env["model"],
            "timeout": env["timeout"],
            "source": "env",
        }
    return None
