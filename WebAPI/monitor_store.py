# -*- coding: utf-8 -*-
"""
Monitor DAO — monitor 表的 PG 持久化 + 归因/盈利计算。
"""

from datetime import datetime, timezone

from typing import Any, Optional

from .config import PG_DSN


def _get_pg_conn():
    """获取 PG 连接，PG_DSN 未配置时返回 None。"""
    if not PG_DSN:
        return None
    import psycopg2

    return psycopg2.connect(PG_DSN)


def _ensure_tables():
    """惰性建表。"""
    conn = _get_pg_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS monitor (
                    id                  SERIAL PRIMARY KEY,
                    code                VARCHAR NOT NULL,
                    kl_type             VARCHAR NOT NULL,
                    monitor_start_time  VARCHAR NOT NULL,
                    entry_price         DOUBLE PRECISION NOT NULL,
                    status              VARCHAR NOT NULL DEFAULT 'monitoring',
                    sold_price          DOUBLE PRECISION,
                    sold_at             TIMESTAMPTZ,
                    pnl_pct             DOUBLE PRECISION,
                    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS monitor_attribution (
                    id          SERIAL PRIMARY KEY,
                    monitor_id  INT NOT NULL REFERENCES monitor(id) ON DELETE CASCADE,
                    reason_type VARCHAR NOT NULL,
                    evidence    TEXT NOT NULL DEFAULT '',
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        conn.commit()
    finally:
        conn.close()


# ---- CRUD ----

def create_monitor(
    code: str,
    kl_type: str,
    entry_price: float,
    monitor_start_time: str,
) -> Optional[dict]:
    """创建一条监控记录。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO monitor (code, kl_type, entry_price, monitor_start_time)
                   VALUES (%s, %s, %s, %s)
                   RETURNING id, code, kl_type, monitor_start_time, entry_price, status,
                             sold_price, sold_at, pnl_pct, created_at""",
                (code, kl_type, entry_price, monitor_start_time),
            )
            row = cur.fetchone()
        conn.commit()
        return _row_to_dict(row)
    finally:
        conn.close()


def list_monitoring(
    keyword: str = "",
) -> list[dict]:
    """列出正在监控中的记录（status='monitoring'）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return []
    conditions = ["m.status = 'monitoring'"]
    params: list[Any] = []
    if keyword:
        conditions.append("(m.code ILIKE %s OR s.name ILIKE %s)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])

    where = "WHERE " + " AND ".join(conditions)
    sql = f"""
        SELECT m.id, m.code, m.kl_type, m.monitor_start_time, m.entry_price,
               m.status, m.sold_price, m.sold_at, m.pnl_pct, m.created_at,
               COALESCE(s.name, m.code) AS stock_name
        FROM monitor m
        LEFT JOIN stock s ON m.code = s.code
        {where}
        ORDER BY m.created_at DESC
    """
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()
    result = [_row_to_dict(row, stock_name=row[10]) for row in rows]
    # 补充实时盈利（通过 DuckDB 最新价计算）
    _enrich_with_real_time_pnl(result)
    return result


def list_completed(
    keyword: str = "",
) -> list[dict]:
    """列出已完成的监控记录。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return []
    conditions = ["m.status = 'completed'"]
    params: list[Any] = []
    if keyword:
        conditions.append("(m.code ILIKE %s OR s.name ILIKE %s)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])

    where = "WHERE " + " AND ".join(conditions)
    sql = f"""
        SELECT m.id, m.code, m.kl_type, m.monitor_start_time, m.entry_price,
               m.status, m.sold_price, m.sold_at, m.pnl_pct, m.created_at,
               COALESCE(s.name, m.code) AS stock_name
        FROM monitor m
        LEFT JOIN stock s ON m.code = s.code
        {where}
        ORDER BY m.created_at DESC
    """
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()
    return [_row_to_dict(row, stock_name=row[10]) for row in rows]


def settle_monitor(monitor_id: int, sold_price: float, sold_at: str, pnl_pct: float) -> Optional[dict]:
    """平仓结算 — status -> completed。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE monitor SET status='completed', sold_price=%s, sold_at=%s, pnl_pct=%s
                   WHERE id=%s
                   RETURNING id, code, kl_type, monitor_start_time, entry_price, status,
                             sold_price, sold_at, pnl_pct, created_at""",
                (sold_price, sold_at, pnl_pct, monitor_id),
            )
            row = cur.fetchone()
        conn.commit()
        if row:
            return _row_to_dict(row)
        return None
    finally:
        conn.close()


def end_monitor(monitor_id: int) -> Optional[dict]:
    """手动结束监控。"""
    return settle_monitor(monitor_id, 0, datetime.now(timezone.utc).isoformat(), 0)


def get_monitor(monitor_id: int) -> Optional[dict]:
    """获取单条监控。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT m.id, m.code, m.kl_type, m.monitor_start_time, m.entry_price,
                          m.status, m.sold_price, m.sold_at, m.pnl_pct, m.created_at,
                          COALESCE(s.name, m.code) AS stock_name
                   FROM monitor m LEFT JOIN stock s ON m.code = s.code
                   WHERE m.id=%s""",
                (monitor_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if row:
        return _row_to_dict(row, stock_name=row[10])
    return None


# ---- 归因 ----

def save_attribution(monitor_id: int, reason_type: str, evidence: str) -> Optional[dict]:
    """保存监控归因。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO monitor_attribution (monitor_id, reason_type, evidence) VALUES (%s, %s, %s) RETURNING id, monitor_id, reason_type, evidence, created_at",
                (monitor_id, reason_type, evidence),
            )
            row = cur.fetchone()
        conn.commit()
        if row:
            return {
                "id": row[0],
                "monitor_id": row[1],
                "reason_type": row[2],
                "evidence": row[3],
                "created_at": row[4].isoformat() if hasattr(row[4], "isoformat") else str(row[4]),
            }
        return None
    finally:
        conn.close()


def get_attribution(monitor_id: int) -> list[dict]:
    """获取监控归因列表。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, monitor_id, reason_type, evidence, created_at FROM monitor_attribution WHERE monitor_id=%s ORDER BY created_at DESC",
                (monitor_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            "id": r[0],
            "monitor_id": r[1],
            "reason_type": r[2],
            "evidence": r[3],
            "created_at": r[4].isoformat() if hasattr(r[4], "isoformat") else str(r[4]),
        }
        for r in rows
    ]


# ---- 盈利走势 ----

def get_aggregate_profit_series() -> list[dict]:
    """获取所有已完成监控的聚合盈利走势时序（按天汇总 PnL）。"""
    completed = list_completed()
    if not completed:
        return []

    from .config import DUCKDB_PATH
    import os

    if not os.path.exists(DUCKDB_PATH):
        return []

    try:
        import duckdb
        from datetime import datetime

        conn = duckdb.connect(DUCKDB_PATH, read_only=True)
        try:
            # 汇总每天的 PnL：对每个已完成监控，计算入场以来的每日 PnL 并累加
            daily: dict[str, float] = {}
            for item in completed:
                code = item["code"]
                start_time = item["monitor_start_time"]
                entry_price = item.get("entry_price", 0)
                if not entry_price:
                    continue
                rows = conn.execute(
                    """
                    SELECT time_key, close
                    FROM kline
                    WHERE code = ? AND kl_type = 'K_DAY' AND autype = 'QFQ' AND time_key >= ?
                    ORDER BY time_key
                    """,
                    (code, start_time),
                ).fetchall()
                for time_key, close in rows:
                    if close:
                        pnl = round((close - entry_price) / entry_price * 100, 2)
                        daily[time_key] = daily.get(time_key, 0) + pnl
        finally:
            conn.close()

        # 按日期排序，累加
        series: list[dict] = []
        cumulative = 0.0
        for date_str in sorted(daily.keys()):
            cumulative += daily[date_str]
            # 日期格式化：提取日期部分
            date_part = date_str[:10] if " " in date_str else date_str
            series.append({"date": date_part, "value": round(cumulative, 2)})
        return series
    except Exception:
        return []


def get_profit_series(monitor_id: int) -> list[dict]:
    """获取监控记录从入场到当前的盈利走势时序。"""
    monitor = get_monitor(monitor_id)
    if not monitor:
        return []

    # 从 DuckDB 获取自监控开始时间以来的日线收盘价
    code = monitor["code"]
    start_time = monitor["monitor_start_time"]
    entry_price = monitor["entry_price"]

    from .config import DUCKDB_PATH
    import os

    if not os.path.exists(DUCKDB_PATH):
        return []

    try:
        import duckdb

        conn = duckdb.connect(DUCKDB_PATH, read_only=True)
        try:
            # 日线按 time_key 升序
            rows = conn.execute(
                """
                SELECT time_key, close
                FROM kline
                WHERE code = ? AND kl_type = 'K_DAY' AND autype = 'QFQ' AND time_key >= ?
                ORDER BY time_key
                """,
                (code, start_time),
            ).fetchall()
        finally:
            conn.close()

        series = []
        for time_key, close in rows:
            if close and entry_price and entry_price != 0:
                pnl = round((close - entry_price) / entry_price * 100, 2)
            else:
                pnl = 0
            series.append({"date": time_key, "close": close or 0, "pnl_pct": pnl})
        return series
    except Exception:
        return []


# ---- 辅助 ----

def _row_to_dict(row, stock_name: Optional[str] = None) -> dict:
    """将 DB 行转为字典。"""
    return {
        "id": row[0],
        "code": row[1],
        "kl_type": row[2],
        "monitor_start_time": row[3],
        "entry_price": row[4],
        "status": row[5],
        "sold_price": row[6],
        "sold_at": row[7].isoformat() if hasattr(row[7], "isoformat") and row[7] else None,
        "pnl_pct": row[8],
        "created_at": row[9].isoformat() if hasattr(row[9], "isoformat") else str(row[9]),
        "name": stock_name or row[1],
    }


def _enrich_with_real_time_pnl(items: list[dict]) -> None:
    """用 DuckDB 最新收盘价计算实时浮盈。"""
    from .config import DUCKDB_PATH
    import os

    if not items or not os.path.exists(DUCKDB_PATH):
        return

    codes = list({i["code"] for i in items})
    if not codes:
        return

    try:
        import duckdb

        conn = duckdb.connect(DUCKDB_PATH, read_only=True)
        try:
            code_list = ", ".join(f"'{c}'" for c in codes)
            rows = conn.execute(
                f"""
                SELECT code, close
                FROM kline
                WHERE code IN ({code_list})
                  AND kl_type = 'K_DAY'
                  AND autype = 'QFQ'
                ORDER BY time_key DESC
                """
            ).fetchall()
        finally:
            conn.close()

        latest_prices: dict[str, float] = {}
        for code, close in rows:
            if code not in latest_prices and close:
                latest_prices[code] = close

        for item in items:
            code = item["code"]
            if code in latest_prices and item["entry_price"] and item["entry_price"] != 0:
                item["current_price"] = latest_prices[code]
                item["current_pnl_pct"] = round(
                    (latest_prices[code] - item["entry_price"]) / item["entry_price"] * 100, 2
                )
            else:
                item["current_price"] = None
                item["current_pnl_pct"] = None
    except Exception:
        pass


# 模块加载时自动建表
_ensure_tables()