# -*- coding: utf-8 -*-
"""
Stock DAO — stock / stock_industry 表的 PG 持久化。
"""

import json
import os

from typing import Any, Optional

from .config import PG_DSN


def _get_pg_conn():
    """获取 PG 连接，PG_DSN 未配置时返回 None。"""
    if not PG_DSN:
        return None
    import psycopg2

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
                CREATE TABLE IF NOT EXISTS stock (
                    code       VARCHAR PRIMARY KEY,
                    name       VARCHAR NOT NULL DEFAULT '',
                    exchange   VARCHAR NOT NULL DEFAULT '',
                    enabled    BOOLEAN NOT NULL DEFAULT TRUE,
                    kl_types   VARCHAR[] NOT NULL DEFAULT '{}',
                    autypes    VARCHAR[] NOT NULL DEFAULT '{}',
                    tags       VARCHAR[] NOT NULL DEFAULT '{}',
                    notes      TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS stock_industry (
                    code          VARCHAR NOT NULL REFERENCES stock(code) ON DELETE CASCADE,
                    industry_name VARCHAR NOT NULL,
                    rank          INT NOT NULL DEFAULT 0,
                    is_primary    BOOLEAN NOT NULL DEFAULT FALSE,
                    PRIMARY KEY (code, industry_name)
                )
                """
            )
        conn.commit()
    finally:
        conn.close()


def upsert_stock(
    code: str,
    name: str = "",
    exchange: str = "",
    enabled: bool = True,
    kl_types: Optional[list[str]] = None,
    autypes: Optional[list[str]] = None,
    tags: Optional[list[str]] = None,
    notes: str = "",
) -> dict:
    """INSERT ON CONFLICT UPDATE，返回写入后的 dict。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return _fallback_stock(code, name, exchange, enabled)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO stock (code, name, exchange, enabled, kl_types, autypes, tags, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (code) DO UPDATE SET
                    name     = EXCLUDED.name,
                    exchange = EXCLUDED.exchange,
                    enabled  = EXCLUDED.enabled,
                    kl_types = EXCLUDED.kl_types,
                    autypes  = EXCLUDED.autypes,
                    tags     = EXCLUDED.tags,
                    notes    = EXCLUDED.notes,
                    updated_at = NOW()
                """,
                (
                    code,
                    name,
                    exchange,
                    enabled,
                    kl_types or [],
                    autypes or [],
                    tags or [],
                    notes,
                ),
            )
        conn.commit()
        return get_stock(code)
    finally:
        conn.close()


def list_stocks(
    q: str = "",
    exchange: str = "",
    industry: str = "",
    enabled: Optional[bool] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """筛选分页查询股票列表，返回 {items, total, page, page_size}。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return _fallback_list_stocks(q, page, page_size)

    conditions = []
    params: list[Any] = []

    if q:
        conditions.append("(s.code ILIKE %s OR s.name ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])
    if exchange:
        conditions.append("s.exchange = %s")
        params.append(exchange)
    if enabled is not None:
        conditions.append("s.enabled = %s")
        params.append(enabled)

    where_clause = ""
    join_clause = ""
    if industry:
        join_clause = "JOIN stock_industry si ON s.code = si.code"
        conditions.append("si.industry_name = %s")
        params.append(industry)
        where_clause = "WHERE " + " AND ".join(conditions)
    elif conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    try:
        with conn.cursor() as cur:
            # count
            cur.execute(
                f"SELECT COUNT(*) FROM stock s {join_clause} {where_clause}",
                params,
            )
            total = cur.fetchone()[0]

            # items
            offset = (page - 1) * page_size
            cur.execute(
                f"""
                SELECT s.code, s.name, s.exchange, s.enabled,
                       s.kl_types, s.autypes, s.tags, s.notes,
                       s.created_at, s.updated_at
                FROM stock s {join_clause}
                {where_clause}
                ORDER BY s.code
                LIMIT %s OFFSET %s
                """,
                params + [page_size, offset],
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    items = []
    for row in rows:
        code_val, name_val, ex, en, klts, ats, tgs, nts, c_at, u_at = row
        industries = _get_industries_for_code(code_val)
        items.append(
            {
                "code": code_val,
                "name": name_val,
                "exchange": ex,
                "enabled": en,
                "kl_types": klts or [],
                "autypes": ats or [],
                "tags": tgs or [],
                "notes": nts,
                "industries": [{"name": i["name"], "rank": i["rank"], "is_primary": i["is_primary"]} for i in industries],
                "created_at": c_at.isoformat() if c_at else None,
                "updated_at": u_at.isoformat() if u_at else None,
            }
        )

    return {"items": items, "total": total, "page": page, "page_size": page_size}


def _get_industries_for_code(code: str) -> list[dict]:
    """获取指定股票的行业列表。"""
    conn = _get_pg_conn()
    if conn is None:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT industry_name, rank, is_primary FROM stock_industry WHERE code=%s ORDER BY rank",
                (code,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [{"name": r[0], "rank": r[1], "is_primary": r[2]} for r in rows]


def get_stock(code: str) -> Optional[dict]:
    """获取单条股票 + 行业列表。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return _fallback_stock(code, code)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT code, name, exchange, enabled, kl_types, autypes, tags, notes, created_at, updated_at FROM stock WHERE code=%s",
                (code,),
            )
            row = cur.fetchone()
            if not row:
                return None
            (
                code_val,
                name_val,
                exchange,
                enabled,
                kl_types,
                autypes,
                tags,
                notes,
                created_at,
                updated_at,
            ) = row
    finally:
        conn.close()

    industries = _get_industries_for_code(code_val)
    return {
        "code": code_val,
        "name": name_val,
        "exchange": exchange,
        "enabled": enabled,
        "kl_types": kl_types or [],
        "autypes": autypes or [],
        "tags": tags or [],
        "notes": notes,
        "industries": [
            {"name": i["name"], "rank": i["rank"], "is_primary": i["is_primary"]}
            for i in industries
        ],
        "created_at": created_at.isoformat() if created_at else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
    }


def delete_stock(code: str) -> bool:
    """删除股票，返回是否成功删除。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM stock WHERE code=%s", (code,))
            deleted = cur.rowcount > 0
        conn.commit()
        return deleted
    finally:
        conn.close()


def upsert_industries(code: str, industries: list[dict]) -> None:
    """批量 upsert 行业（先删后插策略）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM stock_industry WHERE code=%s", (code,))
            for ind in industries:
                cur.execute(
                    """INSERT INTO stock_industry (code, industry_name, rank, is_primary)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (code, industry_name) DO UPDATE SET
                         rank = EXCLUDED.rank,
                         is_primary = EXCLUDED.is_primary""",
                    (
                        code,
                        ind.get("name", ind.get("industry_name", "")),
                        ind.get("rank", 0),
                        ind.get("is_primary", False),
                    ),
                )
        conn.commit()
    finally:
        conn.close()


def get_top_industries(code: str, limit: int = 3) -> list[dict]:
    """取 rank 最小的 N 个行业。"""
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


def import_stocks(all_stocks: list[dict]) -> dict:
    """全市场批量导入，返回 {imported, skipped}。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return {"imported": 0, "skipped": len(all_stocks)}
    imported = 0
    skipped = 0
    try:
        with conn.cursor() as cur:
            for s in all_stocks:
                code = s.get("code", "")
                if not code:
                    skipped += 1
                    continue
                try:
                    cur.execute(
                        """INSERT INTO stock (code, name, exchange, enabled, kl_types, autypes, tags, notes)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                           ON CONFLICT (code) DO UPDATE SET
                             name     = EXCLUDED.name,
                             exchange = EXCLUDED.exchange,
                             enabled  = EXCLUDED.enabled,
                             updated_at = NOW()""",
                        (
                            code,
                            s.get("name", code),
                            s.get("exchange", ""),
                            s.get("enabled", True),
                            s.get("kl_types", []),
                            s.get("autypes", []),
                            s.get("tags", []),
                            s.get("notes", ""),
                        ),
                    )
                    imported += 1
                except Exception:
                    skipped += 1
        conn.commit()
    finally:
        conn.close()
    return {"imported": imported, "skipped": skipped}


def get_stocks_with_daily_close(codes: list[str]) -> list[dict]:
    """根据代码列表获取股票信息并附带 DuckDB 最新收盘价。"""
    stocks_by_code: dict[str, dict] = {}

    conn = _get_pg_conn()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT code, name, exchange FROM stock WHERE code = ANY(%s)",
                    (codes,),
                )
                for row in cur.fetchall():
                    stocks_by_code[row[0]] = {"code": row[0], "name": row[1] or row[0], "exchange": row[2] or ""}
        finally:
            conn.close()

    # 补充 DuckDB 内最新的收盘价
    latest_prices = _get_latest_close_from_duckdb(codes)

    result = []
    for code in codes:
        stock = stocks_by_code.get(code, {"code": code, "name": code, "exchange": ""})
        industries = get_top_industries(code, 3)
        price_info = latest_prices.get(code, {})
        result.append(
            {
                "code": stock["code"],
                "name": stock["name"],
                "exchange": stock.get("exchange", ""),
                "industries": [i["name"] for i in industries],
                "price": price_info.get("close", 0),
                "change_pct": price_info.get("change_pct", 0),
                "region": "--",
                "concepts": [],
            }
        )
    return result


def _get_latest_close_from_duckdb(codes: list[str]) -> dict[str, dict]:
    """从 DuckDB 获取各股票最新的收盘价和涨跌幅。"""
    from .config import DUCKDB_PATH

    if not codes or not os.path.exists(DUCKDB_PATH):
        return {}

    try:
        import duckdb

        conn = duckdb.connect(DUCKDB_PATH, read_only=True)
        try:
            code_list = ", ".join(f"'{c}'" for c in codes)
            result = conn.execute(
                f"""
                SELECT code, close, time_key
                FROM kline
                WHERE code IN ({code_list})
                  AND kl_type = 'K_DAY'
                  AND autype = 'QFQ'
                ORDER BY time_key DESC
                """
            ).fetchall()
        finally:
            conn.close()

        # 取每只股票最新一条
        latest: dict[str, dict] = {}
        seen: set[str] = set()
        for code_val, close, time_key in result:
            if code_val not in seen:
                seen.add(code_val)
                latest[code_val] = {"close": close or 0}

        # 补充涨跌幅（需要前一条日线）
        if latest:
            for code_val in list(latest.keys()):
                try:
                    conn2 = duckdb.connect(DUCKDB_PATH, read_only=True)
                    try:
                        rows = conn2.execute(
                            f"""
                            SELECT close FROM kline
                            WHERE code = '{code_val}'
                              AND kl_type = 'K_DAY'
                              AND autype = 'QFQ'
                            ORDER BY time_key DESC
                            LIMIT 2
                            """
                        ).fetchall()
                    finally:
                        conn2.close()
                    if len(rows) >= 2 and rows[1][0]:
                        prev_close = rows[1][0]
                        cur_close = latest[code_val]["close"]
                        if prev_close and prev_close != 0:
                            latest[code_val]["change_pct"] = round(
                                (cur_close - prev_close) / prev_close * 100, 2
                            )
                        else:
                            latest[code_val]["change_pct"] = 0
                    else:
                        latest[code_val]["change_pct"] = 0
                except Exception:
                    latest[code_val]["change_pct"] = 0

        return latest
    except Exception:
        return {}


def _fallback_list_stocks(q: str = "", page: int = 1, page_size: int = 20) -> dict:
    """PG 不可用时从 DuckDB 读取股票列表兜底。"""
    from .config import DUCKDB_PATH
    import os

    if not os.path.exists(DUCKDB_PATH):
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    try:
        import duckdb

        conn = duckdb.connect(DUCKDB_PATH, read_only=True)
        try:
            # 取所有唯一的 code，按 code 排序
            rows = conn.execute(
                "SELECT DISTINCT code FROM kline ORDER BY code"
            ).fetchall()
            all_codes = [r[0] for r in rows]

            # 过滤
            if q:
                q_lower = q.lower()
                all_codes = [c for c in all_codes if q_lower in c.lower()]

            total = len(all_codes)
            offset = (page - 1) * page_size
            page_codes = all_codes[offset : offset + page_size]

            items = [
                {
                    "code": c,
                    "name": c,
                    "exchange": c.split(".")[0] if "." in c else "",
                    "enabled": True,
                    "kl_types": [],
                    "autypes": [],
                    "tags": [],
                    "notes": "",
                    "industries": [],
                    "created_at": None,
                    "updated_at": None,
                }
                for c in page_codes
            ]
            return {"items": items, "total": total, "page": page, "page_size": page_size}
        finally:
            conn.close()
    except Exception:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}


def _fallback_stock(code: str, name: str = "", exchange: str = "", enabled: bool = True) -> dict:
    """PG 不可用时的兜底返回。"""
    return {
        "code": code,
        "name": name or code,
        "exchange": exchange,
        "enabled": enabled,
        "kl_types": [],
        "autypes": [],
        "tags": [],
        "notes": "",
        "industries": [],
        "created_at": None,
        "updated_at": None,
    }


# 模块加载时自动建表
_ensure_tables()