# -*- coding: utf-8 -*-
"""
Watchlist DAO — watchlist_folder / watchlist_item 表的 PG 持久化。
"""

from typing import Any, Optional

from .config import PG_DSN


def _get_pg_conn():
    """获取 PG 连接，PG_DSN 未配置时返回 None。"""
    if not PG_DSN:
        return None
    import psycopg2

    return psycopg2.connect(PG_DSN)


# ---- 内存降级存储（PG 不可用时）----

_next_fallback_id = 2
_WATCH_FOLDERS: list[dict] = [
    {"id": 1, "name": "默认自选", "codes": []},
]


def _find_fallback_folder(folder_id: int) -> Optional[dict]:
    for f in _WATCH_FOLDERS:
        if f["id"] == folder_id:
            return f
    return None


# ---- 表确保 ----

def _ensure_tables():
    """惰性建表。"""
    conn = _get_pg_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS watchlist_folder (
                    id         SERIAL PRIMARY KEY,
                    name       VARCHAR NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS watchlist_item (
                    folder_id  INT NOT NULL REFERENCES watchlist_folder(id) ON DELETE CASCADE,
                    code       VARCHAR NOT NULL,
                    added_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (folder_id, code)
                )
                """
            )
        conn.commit()
    finally:
        conn.close()


# ---- Folder CRUD ----

def create_folder(name: str) -> dict:
    """创建自选分组。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return _fallback_create_folder(name)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO watchlist_folder (name) VALUES (%s) RETURNING id, name, created_at",
                (name,),
            )
            row = cur.fetchone()
        conn.commit()
        return {"id": row[0], "name": row[1], "created_at": row[2].isoformat(), "codes": _get_folder_codes(row[0])}
    finally:
        conn.close()


def list_folders() -> list[dict]:
    """列出所有自选分组，含 codes 列表和 stock_count。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return _WATCH_FOLDERS
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT f.id, f.name, f.created_at,
                       COALESCE(ARRAY(SELECT wi.code FROM watchlist_item wi WHERE wi.folder_id = f.id ORDER BY wi.added_at), '{}') AS codes
                FROM watchlist_folder f
                ORDER BY f.id
                """
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            "id": r[0],
            "name": r[1],
            "created_at": r[2].isoformat() if hasattr(r[2], "isoformat") else str(r[2]),
            "codes": list(r[3]) if r[3] else [],
            "stock_count": len(r[3]) if r[3] else 0,
        }
        for r in rows
    ]


def rename_folder(folder_id: int, name: str) -> bool:
    """重命名分组。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return _fallback_rename_folder(folder_id, name)
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE watchlist_folder SET name=%s WHERE id=%s", (name, folder_id))
            ok = cur.rowcount > 0
        conn.commit()
        return ok
    finally:
        conn.close()


def delete_folder(folder_id: int) -> bool:
    """删除分组（级联删除 items）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return _fallback_delete_folder(folder_id)
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM watchlist_folder WHERE id=%s", (folder_id,))
            ok = cur.rowcount > 0
        conn.commit()
        return ok
    finally:
        conn.close()


# ---- Item 操作 ----

def add_stock(folder_id: int, code: str) -> bool:
    """添加股票到分组。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return _fallback_add_stock(folder_id, code)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO watchlist_item (folder_id, code) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (folder_id, code),
            )
            ok = cur.rowcount > 0
        conn.commit()
        return ok
    finally:
        conn.close()


def remove_stock(folder_id: int, code: str) -> bool:
    """从分组移出股票。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return _fallback_remove_stock(folder_id, code)
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM watchlist_item WHERE folder_id=%s AND code=%s", (folder_id, code))
            ok = cur.rowcount > 0
        conn.commit()
        return ok
    finally:
        conn.close()


def get_folder_stocks(folder_id: int) -> list[dict]:
    """获取分组内股票列表（含行业 top3 + DuckDB 最新收盘价）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return _fallback_get_folder_stocks(folder_id)

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT code FROM watchlist_item WHERE folder_id=%s ORDER BY added_at", (folder_id,))
            codes = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()

    if not codes:
        return []

    from .stock_store import get_stocks_with_daily_close

    return get_stocks_with_daily_close(codes)


def move_stock(from_folder: int, to_folder: int, code: str) -> bool:
    """移动股票从一个分组到另一个分组（原子操作）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return _fallback_move_stock(from_folder, to_folder, code)
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM watchlist_item WHERE folder_id=%s AND code=%s", (from_folder, code))
            deleted = cur.rowcount > 0
            if deleted:
                cur.execute(
                    "INSERT INTO watchlist_item (folder_id, code) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (to_folder, code),
                )
        conn.commit()
        return deleted
    finally:
        conn.close()


def _get_folder_codes(folder_id: int) -> list[str]:
    """内部：获取分组的 codes 列表。"""
    conn = _get_pg_conn()
    if conn is None:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT code FROM watchlist_item WHERE folder_id=%s ORDER BY added_at", (folder_id,))
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


# ---- 降级方案（内存）----

def _fallback_create_folder(name: str) -> dict:
    global _next_fallback_id
    f = {"id": _next_fallback_id, "name": name, "codes": []}
    _next_fallback_id += 1
    _WATCH_FOLDERS.append(f)
    return dict(f)


def _fallback_rename_folder(folder_id: int, name: str) -> bool:
    f = _find_fallback_folder(folder_id)
    if f:
        f["name"] = name
        return True
    return False


def _fallback_delete_folder(folder_id: int) -> bool:
    global _WATCH_FOLDERS
    initial_len = len(_WATCH_FOLDERS)
    _WATCH_FOLDERS = [x for x in _WATCH_FOLDERS if x["id"] != folder_id]
    return len(_WATCH_FOLDERS) < initial_len


def _fallback_add_stock(folder_id: int, code: str) -> bool:
    f = _find_fallback_folder(folder_id)
    if f and code not in f["codes"]:
        f["codes"].append(code)
        return True
    return False


def _fallback_remove_stock(folder_id: int, code: str) -> bool:
    f = _find_fallback_folder(folder_id)
    if f and code in f["codes"]:
        f["codes"].remove(code)
        return True
    return False


def _fallback_get_folder_stocks(folder_id: int) -> list[dict]:
    """内存降级：从 DuckDB 获取最新收盘价，PG 不可用时兜底。"""
    f = _find_fallback_folder(folder_id)
    if not f or not f["codes"]:
        return []

    # 尝试用 DuckDB + PG（如果可用）丰富数据
    from .stock_store import get_stocks_with_daily_close

    try:
        return get_stocks_with_daily_close(list(f["codes"]))
    except Exception:
        pass

    # 最后的兜底：至少展示代码
    return [
        {
            "code": c,
            "name": c,
            "industries": [],
            "region": "--",
            "concepts": [],
            "price": 0,
            "change_pct": 0,
        }
        for c in f["codes"]
    ]


def _fallback_move_stock(from_folder: int, to_folder: int, code: str) -> bool:
    src = _find_fallback_folder(from_folder)
    dst = _find_fallback_folder(to_folder)
    if src and dst and code in src["codes"]:
        src["codes"].remove(code)
        if code not in dst["codes"]:
            dst["codes"].append(code)
        return True
    return False


# 模块加载时自动建表
_ensure_tables()