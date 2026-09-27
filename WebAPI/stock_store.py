# -*- coding: utf-8 -*-
"""
Stock DAO — stock / stock_industry / stock_financial_report / stock_holder_num
四表 + sync_watermark / sync_job 运维表的 PG 持久化。

字段所有权（stock-metadata-sync）：
- 身份（同步）：code / name / exchange / ipo_date / board / industry_l1
- 用户（保护）：enabled（仅名单缺失分支可改）/ kl_types / autypes / tags / notes
- 档案（同步）：巨潮 16 列
- 快照（同步）：8 列
静态字段（ipo_date / found_date）首次写入后不再覆盖（IS NULL 才写）。
"""

import json
import logging
import os

from datetime import datetime, timezone
from typing import Any, Optional

from .config import PG_DSN

log = logging.getLogger("stock_store")


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


def gen_name_py(name: str) -> str:
    """生成股票名称的拼音首字母串（小写），如「平安银行」→ payh。

    非中文字符原样拼入后小写（「ST昌鱼」→ stcy）；空串过滤后拼接。
    pypinyin 为懒加载依赖：未安装时返回 ""（不炸服务）。
    """
    if not name:
        return ""
    try:
        from pypinyin import Style, lazy_pinyin
    except ImportError:
        return ""
    try:
        letters = lazy_pinyin(name, style=Style.FIRST_LETTER)
    except Exception:
        return ""
    return "".join(s.lower() for s in letters if s)


# 进程级一次性 name_py 存量回填标志（见 _backfill_name_py）
_name_py_backfilled = False


def _backfill_name_py(conn) -> None:
    """存量回填 name_py：SELECT name_py='' AND name<>'' 后批量 UPDATE。

    条件 name_py='' 天然幂等（漏生成的新写入口重启即自愈）；模块级 flag 保证每进程至多执行一次。
    pypinyin 不可用时跳过并打日志（不置空值）。首次建表/补列成功后由 _ensure_tables 调用。
    """
    global _name_py_backfilled
    if _name_py_backfilled:
        return
    try:
        import pypinyin  # noqa: F401  # 可用性探测
    except ImportError:
        log.warning("name_py 存量回填跳过：pypinyin 未安装")
        _name_py_backfilled = True
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT code, name FROM stock WHERE name_py = '' AND name <> ''"
            )
            rows = cur.fetchall()
            if rows:
                cur.executemany(
                    "UPDATE stock SET name_py = %s WHERE code = %s",
                    [(gen_name_py(name), code) for code, name in rows],
                )
        conn.commit()
        _name_py_backfilled = True
        if rows:
            log.info("name_py 存量回填完成：%d 行", len(rows))
    except Exception:
        # DB 异常：跳过不炸服务（条件幂等，下次调用/进程启动重试）
        log.exception("name_py 存量回填失败（稍后重试）")


def _ensure_tables():
    """惰性建表 + 幂等演进（CREATE IF NOT EXISTS + ALTER ADD COLUMN IF NOT EXISTS）。

    与 WebAPI/init.sql 保持一致：新库直建全列，存量库自动补齐缺失列/子表。
    """
    conn = _get_pg_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS stock (
                    code            VARCHAR PRIMARY KEY,
                    name            VARCHAR NOT NULL DEFAULT '',
                    name_py         VARCHAR NOT NULL DEFAULT '',
                    exchange        VARCHAR NOT NULL DEFAULT '',
                    ipo_date        DATE,
                    board           VARCHAR NOT NULL DEFAULT '',
                    industry_l1     VARCHAR NOT NULL DEFAULT '',
                    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
                    kl_types        VARCHAR[] NOT NULL DEFAULT '{}',
                    autypes         VARCHAR[] NOT NULL DEFAULT '{}',
                    tags            VARCHAR[] NOT NULL DEFAULT '{}',
                    notes           TEXT NOT NULL DEFAULT '',
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    full_name       VARCHAR NOT NULL DEFAULT '',
                    en_name         VARCHAR NOT NULL DEFAULT '',
                    former_names    TEXT NOT NULL DEFAULT '',
                    legal_person    VARCHAR NOT NULL DEFAULT '',
                    reg_capital     VARCHAR NOT NULL DEFAULT '',
                    found_date      DATE,
                    website         VARCHAR NOT NULL DEFAULT '',
                    email           VARCHAR NOT NULL DEFAULT '',
                    phone           VARCHAR NOT NULL DEFAULT '',
                    fax             VARCHAR NOT NULL DEFAULT '',
                    reg_addr        TEXT NOT NULL DEFAULT '',
                    office_addr     TEXT NOT NULL DEFAULT '',
                    postal_code     VARCHAR NOT NULL DEFAULT '',
                    main_business   TEXT NOT NULL DEFAULT '',
                    business_scope  TEXT NOT NULL DEFAULT '',
                    intro           TEXT NOT NULL DEFAULT '',
                    price           NUMERIC(12,4),
                    total_mv        NUMERIC(18,4),
                    float_mv        NUMERIC(18,4),
                    pe_ttm          NUMERIC(14,4),
                    pb              NUMERIC(14,4),
                    turnover_rate   NUMERIC(10,4),
                    main_net_inflow NUMERIC(18,4),
                    snapshot_at     TIMESTAMPTZ
                )
                """
            )
            # 存量库补列（幂等，DDL 与 init.sql 完全一致）
            for stmt in _STOCK_COLUMN_ALTERS:
                cur.execute(stmt)
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
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS stock_financial_report (
                    code VARCHAR NOT NULL REFERENCES stock(code) ON DELETE CASCADE,
                    statement_type VARCHAR NOT NULL,
                    report_date DATE NOT NULL,
                    report_type VARCHAR NOT NULL DEFAULT '',
                    report_name VARCHAR NOT NULL DEFAULT '',
                    notice_date DATE,
                    data JSONB NOT NULL DEFAULT '{}',
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (code, statement_type, report_date)
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_sfr_code ON stock_financial_report (code)"
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS stock_holder_num (
                    code VARCHAR NOT NULL REFERENCES stock(code) ON DELETE CASCADE,
                    stat_date DATE NOT NULL,
                    notice_date DATE,
                    holder_num BIGINT,
                    prev_holder_num BIGINT,
                    holder_num_change BIGINT,
                    holder_num_change_pct NUMERIC(12,4),
                    avg_hold_mv NUMERIC(18,4),
                    avg_hold_shares NUMERIC(18,4),
                    total_share NUMERIC(18,4),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (code, stat_date)
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_shn_code ON stock_holder_num (code)"
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_watermark (
                    code VARCHAR NOT NULL,
                    domain VARCHAR NOT NULL,
                    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (code, domain)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_job (
                    id SERIAL PRIMARY KEY,
                    domains TEXT[] NOT NULL DEFAULT '{}',
                    scope VARCHAR NOT NULL DEFAULT 'market',
                    force BOOLEAN NOT NULL DEFAULT TRUE,
                    status VARCHAR NOT NULL DEFAULT 'running',
                    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    finished_at TIMESTAMPTZ,
                    summary JSONB,
                    CONSTRAINT chk_sync_job_status CHECK (status IN ('running','interrupted','done','failed'))
                )
                """
            )
            # updated_at 触发器收敛为仅响应用户列变更（与 init.sql 一致，幂等）
            cur.execute(
                """
                CREATE OR REPLACE FUNCTION update_updated_at_column()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.updated_at = NOW();
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
                """
            )
            cur.execute("DROP TRIGGER IF EXISTS trg_stock_updated_at ON stock")
            cur.execute(
                """
                CREATE TRIGGER trg_stock_updated_at BEFORE UPDATE ON stock FOR EACH ROW
                WHEN (OLD.enabled IS DISTINCT FROM NEW.enabled
                   OR OLD.kl_types IS DISTINCT FROM NEW.kl_types
                   OR OLD.autypes IS DISTINCT FROM NEW.autypes
                   OR OLD.tags IS DISTINCT FROM NEW.tags
                   OR OLD.notes IS DISTINCT FROM NEW.notes)
                EXECUTE FUNCTION update_updated_at_column()
                """
            )
        conn.commit()
        # 存量 name_py 一次性回填（进程级 flag，条件幂等）
        _backfill_name_py(conn)
    finally:
        conn.close()


# stock 表幂等补列（顺序与 init.sql 一致）
_STOCK_COLUMN_ALTERS = [
    "ALTER TABLE stock ADD COLUMN IF NOT EXISTS ipo_date DATE",
    "ALTER TABLE stock ADD COLUMN IF NOT EXISTS board VARCHAR NOT NULL DEFAULT ''",
    "ALTER TABLE stock ADD COLUMN IF NOT EXISTS industry_l1 VARCHAR NOT NULL DEFAULT ''",
    "ALTER TABLE stock ADD COLUMN IF NOT EXISTS full_name VARCHAR NOT NULL DEFAULT ''",
    "ALTER TABLE stock ADD COLUMN IF NOT EXISTS en_name VARCHAR NOT NULL DEFAULT ''",
    "ALTER TABLE stock ADD COLUMN IF NOT EXISTS former_names TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE stock ADD COLUMN IF NOT EXISTS legal_person VARCHAR NOT NULL DEFAULT ''",
    "ALTER TABLE stock ADD COLUMN IF NOT EXISTS reg_capital VARCHAR NOT NULL DEFAULT ''",
    "ALTER TABLE stock ADD COLUMN IF NOT EXISTS found_date DATE",
    "ALTER TABLE stock ADD COLUMN IF NOT EXISTS website VARCHAR NOT NULL DEFAULT ''",
    "ALTER TABLE stock ADD COLUMN IF NOT EXISTS email VARCHAR NOT NULL DEFAULT ''",
    "ALTER TABLE stock ADD COLUMN IF NOT EXISTS phone VARCHAR NOT NULL DEFAULT ''",
    "ALTER TABLE stock ADD COLUMN IF NOT EXISTS fax VARCHAR NOT NULL DEFAULT ''",
    "ALTER TABLE stock ADD COLUMN IF NOT EXISTS reg_addr TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE stock ADD COLUMN IF NOT EXISTS office_addr TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE stock ADD COLUMN IF NOT EXISTS postal_code VARCHAR NOT NULL DEFAULT ''",
    "ALTER TABLE stock ADD COLUMN IF NOT EXISTS main_business TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE stock ADD COLUMN IF NOT EXISTS business_scope TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE stock ADD COLUMN IF NOT EXISTS intro TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE stock ADD COLUMN IF NOT EXISTS price NUMERIC(12,4)",
    "ALTER TABLE stock ADD COLUMN IF NOT EXISTS total_mv NUMERIC(18,4)",
    "ALTER TABLE stock ADD COLUMN IF NOT EXISTS float_mv NUMERIC(18,4)",
    "ALTER TABLE stock ADD COLUMN IF NOT EXISTS pe_ttm NUMERIC(14,4)",
    "ALTER TABLE stock ADD COLUMN IF NOT EXISTS pb NUMERIC(14,4)",
    "ALTER TABLE stock ADD COLUMN IF NOT EXISTS turnover_rate NUMERIC(10,4)",
    "ALTER TABLE stock ADD COLUMN IF NOT EXISTS main_net_inflow NUMERIC(18,4)",
    "ALTER TABLE stock ADD COLUMN IF NOT EXISTS snapshot_at TIMESTAMPTZ",
    "ALTER TABLE stock ADD COLUMN IF NOT EXISTS name_py VARCHAR NOT NULL DEFAULT ''",
]


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
                INSERT INTO stock (code, name, name_py, exchange, enabled, kl_types, autypes, tags, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (code) DO UPDATE SET
                    name     = EXCLUDED.name,
                    name_py  = EXCLUDED.name_py,
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
                    gen_name_py(name),
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
        conditions.append("(s.code ILIKE %s OR s.name ILIKE %s OR s.name_py ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
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


def _meta_str(v) -> str:
    """元数据字符串字段：空值 → ""，日期/时间 → isoformat 字符串。"""
    if v is None:
        return ""
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v if isinstance(v, str) else str(v)


def _meta_num(v):
    """元数据数值字段：NUMERIC(Decimal) → float，空值 → None。"""
    return float(v) if v is not None else None


def get_stock_meta(code: str) -> Optional[dict]:
    """获取单只股票元数据（K 线页「股票信息」tab 专用聚合）。

    一次请求内读 stock 单行（档案 16 列 + 快照 8 列 + 身份补充 exchange/ipo_date/board
    + code/name/tags/notes）与 stock_holder_num 近 1 年股东户数序列（stat_date 升序，
    形如 [{stat_date, holder_num}, ...]）。

    键恒定存在：无值时字符串 ""、数值 None、序列为 []；股票不存在返回 None。
    """
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT code, name, exchange, ipo_date, board,
                       full_name, en_name, former_names, legal_person, reg_capital,
                       found_date, website, email, phone, fax,
                       reg_addr, office_addr, postal_code, main_business, business_scope,
                       intro,
                       price, total_mv, float_mv, pe_ttm, pb, turnover_rate,
                       main_net_inflow, snapshot_at,
                       tags, notes
                FROM stock WHERE code=%s
                """,
                (code,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cur.execute(
                """
                SELECT stat_date, holder_num
                FROM stock_holder_num
                WHERE code=%s AND stat_date >= CURRENT_DATE - INTERVAL '1 year'
                ORDER BY stat_date ASC
                """,
                (code,),
            )
            holder_rows = cur.fetchall()
    finally:
        conn.close()

    (
        code_val,
        name_val,
        exchange,
        ipo_date,
        board,
        full_name,
        en_name,
        former_names,
        legal_person,
        reg_capital,
        found_date,
        website,
        email,
        phone,
        fax,
        reg_addr,
        office_addr,
        postal_code,
        main_business,
        business_scope,
        intro,
        price,
        total_mv,
        float_mv,
        pe_ttm,
        pb,
        turnover_rate,
        main_net_inflow,
        snapshot_at,
        tags,
        notes,
    ) = row

    return {
        "code": code_val,
        "name": _meta_str(name_val),
        # A 公司档案 16 列
        "full_name": _meta_str(full_name),
        "en_name": _meta_str(en_name),
        "former_names": _meta_str(former_names),
        "legal_person": _meta_str(legal_person),
        "reg_capital": _meta_str(reg_capital),
        "found_date": _meta_str(found_date),
        "website": _meta_str(website),
        "email": _meta_str(email),
        "phone": _meta_str(phone),
        "fax": _meta_str(fax),
        "reg_addr": _meta_str(reg_addr),
        "office_addr": _meta_str(office_addr),
        "postal_code": _meta_str(postal_code),
        "main_business": _meta_str(main_business),
        "business_scope": _meta_str(business_scope),
        "intro": _meta_str(intro),
        # D 行情快照 8 列（来自同步落库的估值快照，非 K 线推导）
        "price": _meta_num(price),
        "total_mv": _meta_num(total_mv),
        "float_mv": _meta_num(float_mv),
        "pe_ttm": _meta_num(pe_ttm),
        "pb": _meta_num(pb),
        "turnover_rate": _meta_num(turnover_rate),
        "main_net_inflow": _meta_num(main_net_inflow),
        "snapshot_at": _meta_str(snapshot_at),
        # 身份补充
        "exchange": _meta_str(exchange),
        "ipo_date": _meta_str(ipo_date),
        "board": _meta_str(board),
        # 用户列
        "tags": list(tags or []),
        "notes": _meta_str(notes),
        # 股东户数近 1 年序列（stat_date 升序）
        "holders": [
            {
                "stat_date": d.isoformat() if d is not None else "",
                "holder_num": int(n) if n is not None else None,
            }
            for d, n in holder_rows
        ],
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


# ---------------------------------------------------------------------------
# 按域写入（stock-metadata-sync）：UPDATE SET 只含本域列
# ---------------------------------------------------------------------------


def code_exists(code: str) -> bool:
    """股票行是否存在（股票池边界判定）。"""
    conn = _get_pg_conn()
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM stock WHERE code=%s", (code,))
            return cur.fetchone() is not None
    finally:
        conn.close()


def list_pool_codes(enabled: Optional[bool] = None) -> list[str]:
    """列出股票池代码；enabled=None 表示全部行（identity 域用）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return []
    try:
        with conn.cursor() as cur:
            if enabled is None:
                cur.execute("SELECT code FROM stock ORDER BY code")
            else:
                cur.execute("SELECT code FROM stock WHERE enabled = %s ORDER BY code", (enabled,))
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def apply_identity(
    code: str,
    name: str,
    exchange: str,
    ipo_date,
    board: str,
    industry_l1: str,
    in_list: bool,
) -> str:
    """身份域写入。返回 'created' | 'updated' | 'disabled' | 'unchanged'。

    - in_list=False（三所名单均缺失）：仅置 enabled=false，不刷新来源字段、不删行；
    - in_list=True 且行不存在：INSERT（用户列取默认值）；
    - in_list=True 且行存在：UPDATE 身份列；ipo_date 为静态字段，仅当目标列为 NULL 时写。
    """
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return "unchanged"
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM stock WHERE code=%s", (code,))
            exists = cur.fetchone() is not None

            if not in_list:
                if not exists:
                    return "unchanged"
                cur.execute(
                    "UPDATE stock SET enabled = FALSE WHERE code=%s AND enabled IS DISTINCT FROM FALSE",
                    (code,),
                )
                changed = cur.rowcount > 0
                conn.commit()
                return "disabled" if changed else "unchanged"

            if not exists:
                cur.execute(
                    """
                    INSERT INTO stock (code, name, name_py, exchange, ipo_date, board, industry_l1)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (code, name, gen_name_py(name), exchange, ipo_date, board, industry_l1),
                )
                conn.commit()
                return "created"

            cur.execute(
                """
                UPDATE stock SET
                    name        = %s,
                    name_py     = %s,
                    exchange    = %s,
                    board       = %s,
                    industry_l1 = %s,
                    ipo_date    = CASE WHEN stock.ipo_date IS NULL THEN %s ELSE stock.ipo_date END
                WHERE code = %s
                """,
                (name, gen_name_py(name), exchange, board, industry_l1, ipo_date, code),
            )
        conn.commit()
        return "updated"
    finally:
        conn.close()


def apply_profile(
    code: str,
    full_name: str = "",
    en_name: str = "",
    former_names: str = "",
    legal_person: str = "",
    reg_capital: str = "",
    found_date=None,
    website: str = "",
    email: str = "",
    phone: str = "",
    fax: str = "",
    reg_addr: str = "",
    office_addr: str = "",
    postal_code: str = "",
    main_business: str = "",
    business_scope: str = "",
    intro: str = "",
) -> bool:
    """档案域写入：仅 SET 巨潮 16 列，不碰身份/用户列。

    found_date 为静态字段，仅当目标列为 NULL 时写。行不存在返回 False（档案不建档）。
    """
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE stock SET
                    full_name      = %s,
                    en_name        = %s,
                    former_names   = %s,
                    legal_person   = %s,
                    reg_capital    = %s,
                    found_date     = CASE WHEN stock.found_date IS NULL THEN %s ELSE stock.found_date END,
                    website        = %s,
                    email          = %s,
                    phone          = %s,
                    fax            = %s,
                    reg_addr       = %s,
                    office_addr    = %s,
                    postal_code    = %s,
                    main_business  = %s,
                    business_scope = %s,
                    intro          = %s
                WHERE code = %s
                """,
                (
                    full_name,
                    en_name,
                    former_names,
                    legal_person,
                    reg_capital,
                    found_date,
                    website,
                    email,
                    phone,
                    fax,
                    reg_addr,
                    office_addr,
                    postal_code,
                    main_business,
                    business_scope,
                    intro,
                    code,
                ),
            )
            updated = cur.rowcount > 0
        conn.commit()
        return updated
    finally:
        conn.close()


def apply_snapshot(
    code: str,
    price=None,
    total_mv=None,
    float_mv=None,
    pe_ttm=None,
    pb=None,
    turnover_rate=None,
    main_net_inflow=None,
    snapshot_at=None,
) -> bool:
    """快照域写入：仅 SET 快照 8 列（整行覆盖语义）。行不存在返回 False。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE stock SET
                    price           = %s,
                    total_mv        = %s,
                    float_mv        = %s,
                    pe_ttm          = %s,
                    pb              = %s,
                    turnover_rate   = %s,
                    main_net_inflow = %s,
                    snapshot_at     = %s
                WHERE code = %s
                """,
                (price, total_mv, float_mv, pe_ttm, pb, turnover_rate, main_net_inflow, snapshot_at, code),
            )
            updated = cur.rowcount > 0
        conn.commit()
        return updated
    finally:
        conn.close()


def apply_industries(code: str, industries: list[dict]) -> bool:
    """行业域写入：包装 upsert_industries（先删后插）。行不存在返回 False。"""
    if not code_exists(code):
        return False
    upsert_industries(code, industries)
    return True


def upsert_financial(
    code: str,
    statement_type: str,
    report_date,
    notice_date=None,
    report_type: str = "",
    report_name: str = "",
    data: Optional[dict] = None,
) -> bool:
    """财务三表 upsert（复合主键 code+statement_type+report_date）。

    股票池边界：code 不在 stock 表 → 返回 False 不写（新档案只从名单建档）。
    """
    _ensure_tables()
    if not code_exists(code):
        return False
    conn = _get_pg_conn()
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO stock_financial_report
                    (code, statement_type, report_date, report_type, report_name, notice_date, data)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (code, statement_type, report_date) DO UPDATE SET
                    report_type = EXCLUDED.report_type,
                    report_name = EXCLUDED.report_name,
                    notice_date = EXCLUDED.notice_date,
                    data        = EXCLUDED.data,
                    updated_at  = NOW()
                """,
                (
                    code,
                    statement_type,
                    report_date,
                    report_type,
                    report_name,
                    notice_date,
                    json.dumps(data or {}, ensure_ascii=False, default=str),
                ),
            )
        conn.commit()
        return True
    finally:
        conn.close()


def upsert_holder_num(
    code: str,
    stat_date,
    notice_date=None,
    holder_num=None,
    prev_holder_num=None,
    holder_num_change=None,
    holder_num_change_pct=None,
    avg_hold_mv=None,
    avg_hold_shares=None,
    total_share=None,
) -> bool:
    """股东户数 upsert（复合主键 code+stat_date）。股票池边界同 upsert_financial。"""
    _ensure_tables()
    if not code_exists(code):
        return False
    conn = _get_pg_conn()
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO stock_holder_num
                    (code, stat_date, notice_date, holder_num, prev_holder_num,
                     holder_num_change, holder_num_change_pct,
                     avg_hold_mv, avg_hold_shares, total_share)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (code, stat_date) DO UPDATE SET
                    notice_date          = EXCLUDED.notice_date,
                    holder_num           = EXCLUDED.holder_num,
                    prev_holder_num      = EXCLUDED.prev_holder_num,
                    holder_num_change    = EXCLUDED.holder_num_change,
                    holder_num_change_pct = EXCLUDED.holder_num_change_pct,
                    avg_hold_mv          = EXCLUDED.avg_hold_mv,
                    avg_hold_shares      = EXCLUDED.avg_hold_shares,
                    total_share          = EXCLUDED.total_share,
                    updated_at           = NOW()
                """,
                (
                    code,
                    stat_date,
                    notice_date,
                    holder_num,
                    prev_holder_num,
                    holder_num_change,
                    holder_num_change_pct,
                    avg_hold_mv,
                    avg_hold_shares,
                    total_share,
                ),
            )
        conn.commit()
        return True
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 运维表：单元水位 + 任务记录
# ---------------------------------------------------------------------------


def set_watermark(code: str, domain: str) -> None:
    """单元成功后立即持久化完成水位。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sync_watermark (code, domain, synced_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (code, domain) DO UPDATE SET synced_at = NOW()
                """,
                (code, domain),
            )
        conn.commit()
    finally:
        conn.close()


def get_watermarks(codes: list[str], domain: str) -> dict[str, datetime]:
    """批量取 (code, domain) 水位：{code: synced_at}。"""
    if not codes:
        return {}
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return {}
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT code, synced_at FROM sync_watermark WHERE domain=%s AND code = ANY(%s)",
                (domain, list(codes)),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return {r[0]: r[1] for r in rows}


def is_due(code: str, domain: str, interval_seconds: int, now: Optional[datetime] = None) -> bool:
    """到期判定：水位缺失或超间隔 = 到期。"""
    now = now or datetime.now(timezone.utc)
    wms = get_watermarks([code], domain)
    wm = wms.get(code)
    if wm is None:
        return True
    if wm.tzinfo is None:
        wm = wm.replace(tzinfo=timezone.utc)
    return (now - wm).total_seconds() >= interval_seconds


def create_sync_job(
    domains: list[str],
    scope: str = "market",
    force: bool = True,
) -> int:
    """创建任务记录（status=running），返回 job id。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return 0
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sync_job (domains, scope, force, status)
                VALUES (%s, %s, %s, 'running')
                RETURNING id
                """,
                (list(domains), scope, force),
            )
            job_id = cur.fetchone()[0]
        conn.commit()
        return job_id
    finally:
        conn.close()


def finish_sync_job(job_id: int, status: str, summary: Optional[dict] = None) -> None:
    """结束任务：status ∈ running/interrupted/done/failed，汇总持久化。"""
    if not job_id:
        return
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE sync_job
                SET status = %s,
                    finished_at = NOW(),
                    summary = %s::jsonb
                WHERE id = %s
                """,
                (status, json.dumps(summary or {}, ensure_ascii=False, default=str), job_id),
            )
        conn.commit()
    finally:
        conn.close()


def get_last_sync_job(domains: Optional[list[str]] = None) -> Optional[dict]:
    """取最近一次任务记录；domains 给定时仅返回 domains 集合相同的任务。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            if domains is not None:
                cur.execute(
                    """
                    SELECT id, domains, scope, force, status, started_at, finished_at, summary
                    FROM sync_job
                    WHERE domains @> %s::text[] AND domains <@ %s::text[]
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (list(domains), list(domains)),
                )
            else:
                cur.execute(
                    """
                    SELECT id, domains, scope, force, status, started_at, finished_at, summary
                    FROM sync_job
                    ORDER BY id DESC
                    LIMIT 1
                    """
                )
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {
        "id": row[0],
        "domains": list(row[1] or []),
        "scope": row[2],
        "force": row[3],
        "status": row[4],
        "started_at": row[5],
        "finished_at": row[6],
        "summary": row[7],
    }


def mark_orphan_jobs_interrupted(keep_id: Optional[int] = None) -> int:
    """把 status=running 且非当前任务（keep_id）的孤儿任务置为 interrupted。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return 0
    try:
        with conn.cursor() as cur:
            if keep_id is None:
                cur.execute(
                    """
                    UPDATE sync_job
                    SET status = 'interrupted', finished_at = NOW()
                    WHERE status = 'running'
                    """
                )
            else:
                cur.execute(
                    """
                    UPDATE sync_job
                    SET status = 'interrupted', finished_at = NOW()
                    WHERE status = 'running' AND id != %s
                    """,
                    (keep_id,),
                )
            n = cur.rowcount
        conn.commit()
        return n
    finally:
        conn.close()


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
                        """INSERT INTO stock (code, name, name_py, exchange, enabled, kl_types, autypes, tags, notes)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                           ON CONFLICT (code) DO UPDATE SET
                             name     = EXCLUDED.name,
                             name_py  = EXCLUDED.name_py,
                             exchange = EXCLUDED.exchange,
                             enabled  = EXCLUDED.enabled,
                             updated_at = NOW()""",
                        (
                            code,
                            s.get("name", code),
                            gen_name_py(s.get("name", code)),
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