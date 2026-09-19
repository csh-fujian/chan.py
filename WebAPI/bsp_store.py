# -*- coding: utf-8 -*-
"""
BSP DAO — chan_structure / bsp_index / chan_snapshot 表的 PG 持久化。
"""

import json
import os

from typing import Any, Optional

import psycopg2

from .config import PG_DSN


def _get_pg_conn():
    """获取 PG 连接，PG_DSN 未配置时返回 None。"""
    if not PG_DSN:
        return None
    return psycopg2.connect(PG_DSN)


def _ensure_tables():
    """惰性建表（CREATE TABLE IF NOT EXISTS）。"""
    conn = _get_pg_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS chan_structure (
                    code       VARCHAR NOT NULL,
                    kl_type    VARCHAR NOT NULL,
                    autype     VARCHAR NOT NULL DEFAULT 'QFQ',
                    structure  JSONB NOT NULL DEFAULT '{}',
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (code, kl_type, autype)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS bsp_index (
                    code       VARCHAR NOT NULL,
                    kl_type    VARCHAR NOT NULL,
                    autype     VARCHAR NOT NULL DEFAULT 'QFQ',
                    bsp_date   DATE NOT NULL,
                    bsp_type   VARCHAR NOT NULL,
                    is_buy     BOOLEAN NOT NULL,
                    price      DOUBLE PRECISION NOT NULL,
                    time_key   VARCHAR NOT NULL,
                    UNIQUE (code, kl_type, autype, bsp_date, bsp_type, is_buy, time_key)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS chan_snapshot (
                    code       VARCHAR NOT NULL,
                    kl_type    VARCHAR NOT NULL,
                    autype     VARCHAR NOT NULL DEFAULT 'QFQ',
                    pickle     BYTEA NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (code, kl_type, autype)
                )
                """
            )
        conn.commit()
    finally:
        conn.close()


def upsert_chan_structure(code: str, kl_type: str, autype: str, structure: dict) -> None:
    """写入或更新缠论结构 JSONB。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO chan_structure (code, kl_type, autype, structure)
                   VALUES (%s, %s, %s, %s::jsonb)
                   ON CONFLICT (code, kl_type, autype) DO UPDATE SET
                     structure  = EXCLUDED.structure,
                     updated_at = NOW()""",
                (code, kl_type, autype, json.dumps(structure, ensure_ascii=False)),
            )
        conn.commit()
    finally:
        conn.close()


def get_chan_structure(code: str, kl_type: str, autype: str = "QFQ") -> Optional[dict]:
    """获取缠论结构。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT structure FROM chan_structure WHERE code=%s AND kl_type=%s AND autype=%s",
                (code, kl_type, autype),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if row:
        raw = row[0]
        if isinstance(raw, str):
            return json.loads(raw)
        return raw
    return None


def upsert_bsp_index(
    code: str,
    kl_type: str,
    autype: str,
    bsp_date: str,
    bsp_type: str,
    is_buy: bool,
    price: float,
    time_key: str,
) -> None:
    """写入买卖点索引（INSERT ON CONFLICT DO NOTHING）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO bsp_index (code, kl_type, autype, bsp_date, bsp_type, is_buy, price, time_key)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (code, kl_type, autype, bsp_date, bsp_type, is_buy, time_key) DO NOTHING""",
                (code, kl_type, autype, bsp_date, bsp_type, is_buy, price, time_key),
            )
        conn.commit()
    finally:
        conn.close()


def query_bsp(
    kl_type: str = "",
    date: str = "",
    bsp_type: str = "",
    is_buy: Optional[bool] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """条件查询买卖点，返回 {items, total, page, page_size}。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    conditions = []
    params: list[Any] = []

    if kl_type:
        conditions.append("b.kl_type = %s")
        params.append(kl_type)
    if date:
        conditions.append("b.bsp_date = %s")
        params.append(date)
    if bsp_type:
        conditions.append("b.bsp_type = %s")
        params.append(bsp_type)
    if is_buy is not None:
        conditions.append("b.is_buy = %s")
        params.append(is_buy)

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) FROM bsp_index b {where_clause}",
                params,
            )
            total = cur.fetchone()[0]

            offset = (page - 1) * page_size
            cur.execute(
                f"""
                SELECT b.code, b.kl_type, b.autype, b.bsp_date, b.bsp_type,
                       b.is_buy, b.price, b.time_key,
                       COALESCE(s.name, b.code) AS stock_name
                FROM bsp_index b
                LEFT JOIN stock s ON b.code = s.code
                {where_clause}
                ORDER BY b.bsp_date DESC, b.code
                LIMIT %s OFFSET %s
                """,
                params + [page_size, offset],
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    items = []
    for row in rows:
        code_val, kt, at, bd, bt, ib, price, tk, stock_name = row
        item = {
            "code": code_val,
            "name": stock_name,
            "kl_type": kt,
            "bsp_date": bd.isoformat() if hasattr(bd, "isoformat") else str(bd),
            "bsp_type": bt,
            "is_buy": ib,
            "price": price,
            "time_key": tk,
        }
        # 附加行业信息
        industries = _get_top_industries_for_code(code_val, 3)
        item["industries"] = [{"name": i["name"]} for i in industries]
        items.append(item)

    return {"items": items, "total": total, "page": page, "page_size": page_size}


def query_bsp_aggregate(
    kl_type: str = "",
    date: str = "",
    bsp_type: str = "",
    is_buy: Optional[bool] = None,
) -> list[dict]:
    """GROUP BY 主行业聚合买卖点。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return []

    conditions = ["si.rank = 0"]  # 仅取主行业
    params: list[Any] = []

    if kl_type:
        conditions.append("b.kl_type = %s")
        params.append(kl_type)
    if date:
        conditions.append("b.bsp_date = %s")
        params.append(date)
    if bsp_type:
        conditions.append("b.bsp_type = %s")
        params.append(bsp_type)
    if is_buy is not None:
        conditions.append("b.is_buy = %s")
        params.append(is_buy)

    where_clause = "WHERE " + " AND ".join(conditions)

    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT si.industry_name, COUNT(*) AS cnt
                FROM bsp_index b
                JOIN stock_industry si ON b.code = si.code
                {where_clause}
                GROUP BY si.industry_name
                ORDER BY cnt DESC
                """,
                params,
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    return [{"industry": r[0], "count": r[1]} for r in rows]


def get_bsp_by_code(code: str, kl_types: Optional[list[str]] = None) -> list[dict]:
    """获取指定股票的多级别买卖点。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return []

    if kl_types:
        kl_list = ", ".join(f"'{kt}'" for kt in kl_types)
        sql = f"""
            SELECT code, kl_type, autype, bsp_date, bsp_type, is_buy, price, time_key
            FROM bsp_index
            WHERE code = %s AND kl_type IN ({kl_list})
            ORDER BY bsp_date DESC, kl_type
        """
        params: tuple = (code,)
    else:
        sql = """
            SELECT code, kl_type, autype, bsp_date, bsp_type, is_buy, price, time_key
            FROM bsp_index
            WHERE code = %s
            ORDER BY bsp_date DESC, kl_type
        """
        params = (code,)

    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()

    return [
        {
            "code": r[0],
            "kl_type": r[1],
            "autype": r[2],
            "bsp_date": r[3].isoformat() if hasattr(r[3], "isoformat") else str(r[3]),
            "bsp_type": r[4],
            "is_buy": r[5],
            "price": r[6],
            "time_key": r[7],
        }
        for r in rows
    ]


def save_snapshot(code: str, kl_type: str, autype: str, pickle_bytes: bytes) -> None:
    """保存 CChan pickle 快照。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO chan_snapshot (code, kl_type, autype, pickle)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (code, kl_type, autype) DO UPDATE SET
                     pickle     = EXCLUDED.pickle,
                     updated_at = NOW()""",
                (code, kl_type, autype, psycopg2.Binary(pickle_bytes)),
            )
        conn.commit()
    finally:
        conn.close()


def get_snapshot(code: str, kl_type: str, autype: str = "QFQ") -> Optional[bytes]:
    """获取 CChan pickle 快照。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pickle FROM chan_snapshot WHERE code=%s AND kl_type=%s AND autype=%s",
                (code, kl_type, autype),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if row and row[0]:
        return bytes(row[0])
    return None


def _get_top_industries_for_code(code: str, limit: int = 3) -> list[dict]:
    """内部辅助：获取 top N 行业。"""
    conn = _get_pg_conn()
    if conn is None:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT industry_name, rank, is_primary FROM stock_industry WHERE code=%s ORDER BY rank LIMIT %s",
                (code, limit),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [{"name": r[0], "rank": r[1], "is_primary": r[2]} for r in rows]


# 模块加载时自动建表
_ensure_tables()