# -*- coding: utf-8 -*-
"""
QA DAO — qa_record / user_setting 表的 PG 持久化（kline-page-change design D4）。

与 watchlist_store 的差异：问答记录强依赖 PG——连接失败直接 503、不做内存回退
（避免重启即丢记录的假象，区别于 watchlist 的离线降级）。

序列化约定（与前端 QaRecord 钉死）：
    {id, question, answer, starred, created_at}，created_at 为毫秒 epoch 数字。
"""

import logging
from typing import Any, Optional

from fastapi import HTTPException

from .config import PG_DSN

log = logging.getLogger("qa_store")


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


# ---- 表确保 ----

def _ensure_tables():
    """惰性建表（与 init.sql 幂等 DDL 一致）。"""
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS qa_record (
                    id          SERIAL PRIMARY KEY,
                    user_id     INTEGER NOT NULL REFERENCES chan_user(id),
                    question    TEXT NOT NULL,
                    answer      TEXT NOT NULL,
                    starred     BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_qa_record_user_created
                    ON qa_record (user_id, created_at DESC)
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_setting (
                    user_id     INTEGER NOT NULL REFERENCES chan_user(id),
                    key         TEXT NOT NULL,
                    value       TEXT NOT NULL,
                    PRIMARY KEY (user_id, key)
                )
                """
            )
        conn.commit()
    finally:
        conn.close()


def _row_to_record(row: tuple) -> dict[str, Any]:
    """qa_record 行 → 前端 QaRecord（created_at 毫秒 epoch）。"""
    record_id, question, answer, starred, created_at = row
    return {
        "id": record_id,
        "question": question,
        "answer": answer,
        "starred": bool(starred),
        "created_at": int(created_at.timestamp() * 1000),
    }


# ---- qa_record CRUD（全部按 user_id 隔离） ----

def create_record(user_id: int, question: str, answer: str) -> dict[str, Any]:
    """落库一条问答记录，返回 QaRecord。"""
    _ensure_tables()
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO qa_record (user_id, question, answer)
                   VALUES (%s, %s, %s)
                   RETURNING id, question, answer, starred, created_at""",
                (user_id, question, answer),
            )
            row = cur.fetchone()
        conn.commit()
        return _row_to_record(row)
    finally:
        conn.close()


def list_records(user_id: int) -> list[dict[str, Any]]:
    """当前用户的问答记录，created_at 倒序。"""
    _ensure_tables()
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, question, answer, starred, created_at
                   FROM qa_record
                   WHERE user_id = %s
                   ORDER BY created_at DESC""",
                (user_id,),
            )
            return [_row_to_record(r) for r in cur.fetchall()]
    finally:
        conn.close()


def star_record(user_id: int, record_id: int, starred: bool) -> bool:
    """单条打星/取消，校验归属；不属于当前用户返回 False（路由侧转 404）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE qa_record SET starred = %s
                   WHERE id = %s AND user_id = %s""",
                (starred, record_id, user_id),
            )
            affected = cur.rowcount
        conn.commit()
        return affected > 0
    finally:
        conn.close()


def batch_star(user_id: int, ids: list[int], starred: bool) -> int:
    """批量打星，仅作用于当前用户的指定记录，返回受影响条数。"""
    if not ids:
        return 0
    _ensure_tables()
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE qa_record SET starred = %s
                   WHERE user_id = %s AND id = ANY(%s)""",
                (starred, user_id, list(ids)),
            )
            affected = cur.rowcount
        conn.commit()
        return affected
    finally:
        conn.close()


def delete_unstarred(user_id: int) -> int:
    """删除当前用户所有未打星记录，返回删除条数。"""
    _ensure_tables()
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM qa_record WHERE user_id = %s AND starred = FALSE",
                (user_id,),
            )
            affected = cur.rowcount
        conn.commit()
        return affected
    finally:
        conn.close()


# ---- user_setting（系统提示词等按用户配置） ----

def get_setting(user_id: int, key: str) -> Optional[str]:
    """读取用户配置；未设置返回 None。"""
    _ensure_tables()
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT value FROM user_setting WHERE user_id = %s AND key = %s",
                (user_id, key),
            )
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        conn.close()


def set_setting(user_id: int, key: str, value: str) -> None:
    """写入用户配置（upsert）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO user_setting (user_id, key, value)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (user_id, key) DO UPDATE SET value = EXCLUDED.value""",
                (user_id, key, value),
            )
        conn.commit()
    finally:
        conn.close()
