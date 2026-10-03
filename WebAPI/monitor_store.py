# -*- coding: utf-8 -*-
"""
Monitor DAO — monitor 表的 PG 持久化 + 归因/盈利计算。
"""

import logging
from datetime import datetime, timezone

from typing import Any, Optional

from .config import PG_DSN

log = logging.getLogger("monitor_store")


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
    # 补齐契约字段（买卖点上下文/行业，design D5）+ 实时盈利/极值（DuckDB）
    _fill_bsp_context(result)
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
    result = [_row_to_dict(row, stock_name=row[10]) for row in rows]
    # 完成页与监控中列表消费同一套字段（design D5）；结算价/盈亏由 sold_price/pnl_pct 映射
    _fill_bsp_context(result)
    _enrich_with_real_time_pnl(result)
    for it in result:
        it["end_price"] = it.get("sold_price") or 0
        it["profit"] = it.get("pnl_pct") or 0
        it["end_date"] = _to_ms(it["sold_at"]) if it.get("sold_at") else 0
        it["attribution"] = ""
        it["ai_analyzed"] = False
    return result


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
    """保存监控归因（替换式：同 monitor_id 旧归因先删，支持重复分析）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            # init.sql 侧 uq_ma_monitor_id UNIQUE(monitor_id)：重复分析需替换而非追加
            cur.execute(
                "DELETE FROM monitor_attribution WHERE monitor_id = %s",
                (monitor_id,),
            )
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


def _to_ms(time_str: str) -> int:
    """时间字符串 → 毫秒时间戳（失败返回 0）。"""
    try:
        return int(datetime.fromisoformat(time_str).timestamp() * 1000)
    except Exception:
        return 0


def _fill_bsp_context(items: list[dict]) -> None:
    """补齐前端 MonitorItem 契约字段（monitor-page-change design D5）。

    monitor 表只存监控本体（code/kl_type/entry_price/...），前端列表还需要
    买卖点上下文与行业/极值列。字段来源：
    - bsp_price ← entry_price（监控以买卖点价格入场，同值换名）
    - bsp_type/direction/bsp_date ← bsp_index 按 (code,kl_type) 回查监控开始前
      最近一条买卖点（监控的语义起点）；查不到给兜底值
    - industries ← stock_industry 批量查（rank≤3 名称数组）
    - current_price/change_pct/max_profit/max_drawdown ← DuckDB（_enrich_with_real_time_pnl）
    """
    if not items:
        return

    # bsp_index 回查：每 (code, kl_type) 取 monitor_start_time 前最近一条
    try:
        conn = _get_pg_conn()
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    for it in items:
                        cur.execute(
                            """
                            SELECT bsp_type, is_buy, bsp_date
                            FROM bsp_index
                            WHERE code = %s AND kl_type = %s AND time_key <= %s
                            ORDER BY time_key DESC
                            LIMIT 1
                            """,
                            (it["code"], it["kl_type"], it["monitor_start_time"]),
                        )
                        row = cur.fetchone()
                        if row:
                            it["bsp_type"] = row[0]
                            it["direction"] = "buy" if row[1] else "sell"
                            it["bsp_date"] = _to_ms(row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2]))
                        else:
                            it["bsp_type"] = ""
                            it["direction"] = "buy"
                            it["bsp_date"] = _to_ms(it["monitor_start_time"])
            finally:
                conn.close()
        else:
            for it in items:
                it["bsp_type"] = ""
                it["direction"] = "buy"
                it["bsp_date"] = _to_ms(it["monitor_start_time"])
    except Exception:
        log.exception("补齐买卖点上下文失败，使用兜底值")
        for it in items:
            it.setdefault("bsp_type", "")
            it.setdefault("direction", "buy")
            it.setdefault("bsp_date", _to_ms(it["monitor_start_time"]))

    # 行业（rank≤3）批量单条 SQL
    try:
        from .bsp_store import get_industries_for_codes

        ind_map = get_industries_for_codes(list({it["code"] for it in items}))
        for it in items:
            it["industries"] = ind_map.get(it["code"], [])
    except Exception:
        for it in items:
            it["industries"] = []

    # 入场价即买卖点价格（同值换名）
    for it in items:
        it["bsp_price"] = it["entry_price"]


def _enrich_with_real_time_pnl(items: list[dict]) -> None:
    """用 DuckDB 最新收盘价计算实时浮盈 + 涨跌幅 + 监控期间极值（design D5）。

    - current_price：最新日线收盘价
    - current_pnl_pct：(当前价 − 入场价) / 入场价 × 100，自买卖点起持有至当前的
      模拟买入累计涨跌（monitor-page-change design D8 收益率列）
    - change_pct：(最新 - 前收) / 前收 * 100
    - max_profit/max_drawdown：自 monitor_start_time 起日线收盘价相对 entry_price
      的最大上行/最大下行百分比（监控期间浮盈极值口径）
    DuckDB 不可用时降级 current_price=None、change_pct=0、极值 0，不阻塞列表。
    """
    from .config import DUCKDB_PATH
    import os

    if not items or not os.path.exists(DUCKDB_PATH):
        for it in items:
            it.setdefault("current_price", None)
            it.setdefault("current_pnl_pct", None)
            it.setdefault("change_pct", 0)
            it.setdefault("max_profit", 0)
            it.setdefault("max_drawdown", 0)
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
                SELECT code, time_key, close
                FROM kline
                WHERE code IN ({code_list})
                  AND kl_type = 'K_DAY'
                  AND autype = 'QFQ'
                ORDER BY time_key DESC
                """
            ).fetchall()
        finally:
            conn.close()

        # 最新两根 → 现价/涨跌幅；全量序列 → 监控期间极值
        latest_two: dict[str, list[float]] = {}
        series: dict[str, list[tuple[str, float]]] = {}
        for code, time_key, close in rows:
            if close is None:
                continue
            series.setdefault(code, []).append((str(time_key), float(close)))
            two = latest_two.setdefault(code, [])
            if len(two) < 2:
                two.append(float(close))

        for item in items:
            code = item["code"]
            entry = item.get("entry_price") or 0
            two = latest_two.get(code, [])
            item["current_price"] = two[0] if two else None
            # 收益率：自买卖点（入场价）起持有至今的累计涨跌
            if two and entry:
                item["current_pnl_pct"] = round((two[0] - entry) / entry * 100, 2)
            else:
                item["current_pnl_pct"] = None
            if len(two) == 2 and two[1]:
                item["change_pct"] = round((two[0] - two[1]) / two[1] * 100, 2)
            else:
                item["change_pct"] = 0

            # 监控期间极值（series 为时间降序；只取 monitor_start_time 之后的行）
            start = item.get("monitor_start_time") or ""
            highs = [
                c for tk, c in series.get(code, [])
                if c and entry and tk >= start
            ]
            if highs and entry:
                item["max_profit"] = round((max(highs) - entry) / entry * 100, 2)
                item["max_drawdown"] = round((min(highs) - entry) / entry * 100, 2)
            else:
                item["max_profit"] = 0
                item["max_drawdown"] = 0
    except Exception:
        for it in items:
            it.setdefault("current_price", None)
            it.setdefault("current_pnl_pct", None)
            it.setdefault("change_pct", 0)
            it.setdefault("max_profit", 0)
            it.setdefault("max_drawdown", 0)


# 模块加载时自动建表
_ensure_tables()