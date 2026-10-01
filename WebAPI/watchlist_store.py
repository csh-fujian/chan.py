# -*- coding: utf-8 -*-
"""
Watchlist DAO — watchlist_folder / watchlist_item 表的 PG 持久化。
"""

import logging
from typing import Any, Optional

from .config import PG_DSN

log = logging.getLogger("watchlist_store")


def _get_pg_conn():
    """获取 PG 连接，PG_DSN 未配置或 PG 不可达时返回 None（降级为无数据库模式）。"""
    global _pg_down
    if not PG_DSN:
        return None
    import psycopg2

    try:
        conn = psycopg2.connect(PG_DSN)
    except psycopg2.OperationalError as e:
        if not _pg_down:
            log.warning("PG 不可达，降级为无数据库模式: %s", e)
            _pg_down = True
        return None
    if _pg_down:
        log.info("PG 连接已恢复")
        _pg_down = False
    return conn


# PG 连接失败降级状态（仅状态翻转时记一次日志，防止每个请求刷屏）
_pg_down = False


# ---- 内存降级存储（PG 不可用时）----

_next_fallback_id = 2
_WATCH_FOLDERS: list[dict] = [
    {"id": 1, "name": "默认自选", "codes": [], "sort_order": 1},
]


def _find_fallback_folder(folder_id: int) -> Optional[dict]:
    for f in _WATCH_FOLDERS:
        if f["id"] == folder_id:
            return f
    return None


# ---- 表确保 ----

def _ensure_tables():
    """惰性建表 + sort_order 补列与一次性回填（幂等，每次请求执行均安全）。"""
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
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    sort_order INT NOT NULL DEFAULT 0
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS watchlist_item (
                    folder_id  INT NOT NULL REFERENCES watchlist_folder(id) ON DELETE CASCADE,
                    code       VARCHAR NOT NULL,
                    added_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    sort_order INT NOT NULL DEFAULT 0,
                    UNIQUE (folder_id, code)
                )
                """
            )
            # 存量库补列（幂等）
            cur.execute(
                "ALTER TABLE watchlist_folder ADD COLUMN IF NOT EXISTS sort_order INT NOT NULL DEFAULT 0"
            )
            cur.execute(
                "ALTER TABLE watchlist_item ADD COLUMN IF NOT EXISTS sort_order INT NOT NULL DEFAULT 0"
            )
            # 一次性回填：sort_order 1 基且永不为 0（此后 WHERE sort_order = 0 永不命中）。
            # folder 按 id 回填；item 在惰性建表的存量库中无 id 列，按 added_at 序编号
            # （与旧行为 ORDER BY added_at 一致，语义同 SET sort_order = id）。
            cur.execute("UPDATE watchlist_folder SET sort_order = id WHERE sort_order = 0")
            cur.execute(
                """
                UPDATE watchlist_item wi
                SET sort_order = s.rn
                FROM (
                    SELECT folder_id, code,
                           ROW_NUMBER() OVER (PARTITION BY folder_id ORDER BY added_at, code) AS rn
                    FROM watchlist_item
                    WHERE sort_order = 0
                ) s
                WHERE wi.folder_id = s.folder_id AND wi.code = s.code AND wi.sort_order = 0
                """
            )
        conn.commit()
    finally:
        conn.close()


# ---- Folder CRUD ----

def create_folder(name: str) -> dict:
    """创建自选分组（sort_order 追加到末尾，1 基且永不为 0）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return _fallback_create_folder(name)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO watchlist_folder (name, sort_order)
                VALUES (%s, COALESCE((SELECT MAX(sort_order) FROM watchlist_folder), 0) + 1)
                RETURNING id, name, created_at
                """,
                (name,),
            )
            row = cur.fetchone()
        conn.commit()
        return {"id": row[0], "name": row[1], "created_at": row[2].isoformat(), "codes": _get_folder_codes(row[0])}
    finally:
        conn.close()


def list_folders() -> list[dict]:
    """列出所有自选分组，含 codes 列表和 stock_count（按 sort_order, id 排序）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return _WATCH_FOLDERS
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT f.id, f.name, f.created_at,
                       COALESCE(ARRAY(SELECT wi.code FROM watchlist_item wi WHERE wi.folder_id = f.id ORDER BY wi.sort_order, wi.added_at, wi.code), '{}') AS codes
                FROM watchlist_folder f
                ORDER BY f.sort_order, f.id
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
    """添加股票到分组（sort_order 追加到该分组末尾，永不为 0）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return _fallback_add_stock(folder_id, code)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO watchlist_item (folder_id, code, sort_order)
                VALUES (%s, %s, COALESCE((SELECT MAX(sort_order) FROM watchlist_item WHERE folder_id = %s), 0) + 1)
                ON CONFLICT DO NOTHING
                """,
                (folder_id, code, folder_id),
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


def get_folder_stocks(folder_id: int, q: str = "") -> list[dict]:
    """获取分组内股票列表（含行业 top3 + DuckDB 最新收盘价），q 非空时按 code/name 子串过滤。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return _fallback_get_folder_stocks(folder_id, q)

    codes = _get_folder_codes(folder_id, q)
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
                    """
                    INSERT INTO watchlist_item (folder_id, code, sort_order)
                    VALUES (%s, %s, COALESCE((SELECT MAX(sort_order) FROM watchlist_item WHERE folder_id = %s), 0) + 1)
                    ON CONFLICT DO NOTHING
                    """,
                    (to_folder, code, to_folder),
                )
        conn.commit()
        return deleted
    finally:
        conn.close()


def _get_folder_codes(folder_id: int, q: str = "") -> list[str]:
    """内部：获取分组的 codes 列表（按 sort_order 排序；q 非空时按 code/name 子串过滤）。

    q 过滤在 SQL 层做：LEFT JOIN stock（stock 表可能缺该 code，仅按 code 匹配的行不能丢），
    条件为 code ILIKE 或 name ILIKE；q 为空时行为与旧版一致（全量）。
    """
    conn = _get_pg_conn()
    if conn is None:
        return []
    try:
        with conn.cursor() as cur:
            if q:
                cur.execute(
                    """
                    SELECT wi.code FROM watchlist_item wi
                    LEFT JOIN stock s ON s.code = wi.code
                    WHERE wi.folder_id = %s
                      AND (wi.code ILIKE %s OR s.name ILIKE %s)
                    ORDER BY wi.sort_order, wi.added_at, wi.code
                    """,
                    (folder_id, f"%{q}%", f"%{q}%"),
                )
            else:
                cur.execute(
                    "SELECT code FROM watchlist_item WHERE folder_id=%s ORDER BY sort_order, added_at, code",
                    (folder_id,),
                )
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


# ---- 排序（sort_order 全量覆盖，1..n）----

def reorder_folders(ids: list[int]) -> bool:
    """全量覆盖文件夹排序：按下标写入 sort_order = 1..n（单事务，幂等）。

    ids 中每个 id 必须存在且不重复，否则整体回滚返回 False。
    """
    _ensure_tables()
    if len(set(ids)) != len(ids):
        return False
    conn = _get_pg_conn()
    if conn is None:
        return _fallback_reorder_folders(ids)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM watchlist_folder WHERE id = ANY(%s)", (ids,))
            existing = {r[0] for r in cur.fetchall()}
            if len(existing) != len(ids):
                conn.rollback()
                return False
            for i, fid in enumerate(ids, start=1):
                cur.execute("UPDATE watchlist_folder SET sort_order=%s WHERE id=%s", (i, fid))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def reorder_folder_stocks(folder_id: int, codes: list[str]) -> bool:
    """全量覆盖分组内股票排序：按数组下标写入 sort_order = 1..n（单事务，幂等）。

    codes 中每个 code 必须存在于该分组且不重复，否则整体回滚返回 False。
    """
    _ensure_tables()
    if len(set(codes)) != len(codes):
        return False
    conn = _get_pg_conn()
    if conn is None:
        return _fallback_reorder_folder_stocks(folder_id, codes)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT code FROM watchlist_item WHERE folder_id=%s AND code = ANY(%s)",
                (folder_id, codes),
            )
            existing = {r[0] for r in cur.fetchall()}
            if len(existing) != len(codes):
                conn.rollback()
                return False
            for i, code in enumerate(codes, start=1):
                cur.execute(
                    "UPDATE watchlist_item SET sort_order=%s WHERE folder_id=%s AND code=%s",
                    (i, folder_id, code),
                )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---- 降级方案（内存）----

def _fallback_create_folder(name: str) -> dict:
    global _next_fallback_id
    max_order = max((x.get("sort_order", 0) for x in _WATCH_FOLDERS), default=0)
    f = {"id": _next_fallback_id, "name": name, "codes": [], "sort_order": max_order + 1}
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


def _fallback_get_folder_stocks(folder_id: int, q: str = "") -> list[dict]:
    """内存降级：从 DuckDB 获取最新收盘价，PG 不可用时兜底；q 非空时按 code/name 子串过滤。"""
    f = _find_fallback_folder(folder_id)
    if not f or not f["codes"]:
        return []

    # 尝试用 DuckDB + PG（如果可用）丰富数据
    from .stock_store import get_stocks_with_daily_close

    rows: list[dict]
    try:
        rows = get_stocks_with_daily_close(list(f["codes"]))
    except Exception:
        # 最后的兜底：至少展示代码
        rows = [
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

    if q:
        ql = q.lower()
        rows = [
            r for r in rows
            if ql in str(r.get("code", "")).lower() or ql in str(r.get("name", "")).lower()
        ]
    return rows


def _fallback_move_stock(from_folder: int, to_folder: int, code: str) -> bool:
    src = _find_fallback_folder(from_folder)
    dst = _find_fallback_folder(to_folder)
    if src and dst and code in src["codes"]:
        src["codes"].remove(code)
        if code not in dst["codes"]:
            dst["codes"].append(code)
        return True
    return False


def _fallback_reorder_folders(ids: list[int]) -> bool:
    """内存降级：直接重排 _WATCH_FOLDERS 列表序（给定序前置，其余保持相对序）。"""
    if len(set(ids)) != len(ids):
        return False
    if any(_find_fallback_folder(i) is None for i in ids):
        return False
    by_id = {f["id"]: f for f in _WATCH_FOLDERS}
    reordered = [by_id[i] for i in ids] + [f for f in _WATCH_FOLDERS if f["id"] not in set(ids)]
    _WATCH_FOLDERS[:] = reordered
    for idx, f in enumerate(_WATCH_FOLDERS, start=1):
        f["sort_order"] = idx
    return True


def _fallback_reorder_folder_stocks(folder_id: int, codes: list[str]) -> bool:
    """内存降级：直接重排分组 codes 数组序（给定序前置，其余保持相对序）。"""
    f = _find_fallback_folder(folder_id)
    if not f:
        return False
    if len(set(codes)) != len(codes):
        return False
    if any(c not in f["codes"] for c in codes):
        return False
    code_set = set(codes)
    f["codes"] = list(codes) + [c for c in f["codes"] if c not in code_set]
    return True


# 模块加载时自动建表
_ensure_tables()