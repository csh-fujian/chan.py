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


# ---- 内存降级存储（PG 不可用时，分组实体；监控记录本身不提供内存降级，与现状一致）----

_next_fallback_group_id = 1
_MONITOR_GROUPS: list[dict] = []


def _find_fallback_group(group_id: int) -> Optional[dict]:
    for g in _MONITOR_GROUPS:
        if g["id"] == group_id:
            return g
    return None


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
            # 分组表（design D1）：name UNIQUE 与 watchlist_folder 风格对齐
            # （watchlist_folder 无 UNIQUE，分组语义要求名称唯一，UNIQUE 在此显式承载查重约束）
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS monitor_group (
                    id          SERIAL PRIMARY KEY,
                    name        VARCHAR NOT NULL UNIQUE,
                    sort_order  INT NOT NULL DEFAULT 0,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            # 存量库补列（幂等）：FK ON DELETE SET NULL，删除分组时记录归「未分组」
            cur.execute(
                """
                ALTER TABLE monitor
                ADD COLUMN IF NOT EXISTS group_id INT REFERENCES monitor_group(id) ON DELETE SET NULL
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
            # 策略信号来源维度（strategy-signal-page design D6）：纯加列带
            # DEFAULT，存量行 NULL → source_type 兜底 'chan'（查询侧 COALESCE）
            cur.execute(
                """
                ALTER TABLE monitor
                ADD COLUMN IF NOT EXISTS source_type VARCHAR NOT NULL DEFAULT 'chan'
                """
            )
            cur.execute(
                """
                ALTER TABLE monitor
                ADD COLUMN IF NOT EXISTS instance_id INT
                """
            )
            cur.execute(
                """
                ALTER TABLE monitor
                ADD COLUMN IF NOT EXISTS signal_date DATE
                """
            )
            # FK 单独语句（ADD COLUMN IF NOT EXISTS 不支持内联 REFERENCES 的幂等性；
            # 约束名固定便于识别；已存在时 IF NOT EXISTS 幂等跳过）
            cur.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'fk_monitor_instance_id'
                          AND conrelid = 'monitor'::regclass
                    ) THEN
                        ALTER TABLE monitor
                        ADD CONSTRAINT fk_monitor_instance_id
                        FOREIGN KEY (instance_id) REFERENCES strategy_instance(id);
                    END IF;
                END $$;
                """
            )
        conn.commit()
    finally:
        conn.close()


# ---- CRUD ----

def _group_filter_condition(
    group_filter: Optional[str | int],
    conditions: list[str],
    params: list[Any],
) -> None:
    """按 design D3 附加分组过滤条件：

    - None/缺省 → 不过滤（「全部」）
    - "ungrouped"（哨兵字符串）→ group_id IS NULL（「未分组」）
    - 正整数 → group_id = <id>（精确匹配）
    """
    if group_filter is None:
        return
    if group_filter == "ungrouped":
        conditions.append("m.group_id IS NULL")
    else:
        conditions.append("m.group_id = %s")
        params.append(int(group_filter))


def create_monitor(
    code: str,
    kl_type: str,
    entry_price: float,
    monitor_start_time: str,
    group_id: Optional[int] = None,
    source_type: str = "chan",
    instance_id: Optional[int] = None,
    signal_date: Optional[str] = None,
) -> Optional[dict]:
    """创建一条监控记录（group_id 未传写 NULL = 未分组）。

    策略信号来源（strategy-signal-page design D6/D8）：
    - source_type='strategy' 且 instance_id/signal_date 齐备：来源字段落库，
      并在同一事务内冻结对应 strategy_signal 行（frozen=TRUE，状态不再被
      引擎覆盖）——加监控成功与冻结同生共死
    - source_type='chan'（缺省）：行为与既有调用完全一致（来源列落 'chan'，
      不触碰 strategy_signal）
    - source_type='watchlist'（watchlist-page-change design D8）：自选页
      人工挑选来源，仅落来源列（无信号行可冻结）；非白名单值兜底 'chan'
    """
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO monitor (code, kl_type, entry_price, monitor_start_time, group_id,
                                        source_type, instance_id, signal_date)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id, code, kl_type, monitor_start_time, entry_price, status,
                             sold_price, sold_at, pnl_pct, created_at,
                             source_type, instance_id, signal_date""",
                (
                    code, kl_type, entry_price, monitor_start_time, group_id,
                    # 白名单放行 'watchlist'（watchlist-page-change design D8：
                    # 复用 source_type 第三取值，纯校验放行无 DDL）；非法值兜底 'chan'
                    source_type if source_type in ("chan", "strategy", "watchlist") else "chan",
                    instance_id if source_type == "strategy" else None,
                    signal_date if source_type == "strategy" else None,
                ),
            )
            row = cur.fetchone()
            # 同事务冻结信号（design D8：加监控成功与 frozen 置位同事务）
            if source_type == "strategy" and instance_id is not None and signal_date:
                from .strategy_store import freeze_signal_in_conn

                freeze_signal_in_conn(cur, instance_id, code, signal_date)
        conn.commit()
        return _row_to_dict(row)
    finally:
        conn.close()


def list_monitoring(
    keyword: str = "",
    group_id: Optional[str | int] = None,
) -> list[dict]:
    """列出正在监控中的记录（status='monitoring'），group_id 过滤语义见 _group_filter_condition。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return []
    conditions = ["m.status = 'monitoring'"]
    params: list[Any] = []
    if keyword:
        conditions.append("(m.code ILIKE %s OR s.name ILIKE %s)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    _group_filter_condition(group_id, conditions, params)

    where = "WHERE " + " AND ".join(conditions)
    sql = f"""
        SELECT m.id, m.code, m.kl_type, m.monitor_start_time, m.entry_price,
               m.status, m.sold_price, m.sold_at, m.pnl_pct, m.created_at,
               COALESCE(m.source_type, 'chan') AS source_type,
               m.instance_id, m.signal_date,
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
    result = [_row_to_dict(row[:13], stock_name=row[13]) for row in rows]
    # 补齐契约字段（买卖点上下文/行业，design D5）+ 实时盈利/极值（DuckDB）
    _fill_bsp_context(result)
    _enrich_with_real_time_pnl(result)
    return result


def list_completed(
    keyword: str = "",
    group_id: Optional[str | int] = None,
) -> list[dict]:
    """列出已完成的监控记录，group_id 过滤语义见 _group_filter_condition。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return []
    conditions = ["m.status = 'completed'"]
    params: list[Any] = []
    if keyword:
        conditions.append("(m.code ILIKE %s OR s.name ILIKE %s)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    _group_filter_condition(group_id, conditions, params)

    where = "WHERE " + " AND ".join(conditions)
    sql = f"""
        SELECT m.id, m.code, m.kl_type, m.monitor_start_time, m.entry_price,
               m.status, m.sold_price, m.sold_at, m.pnl_pct, m.created_at,
               COALESCE(m.source_type, 'chan') AS source_type,
               m.instance_id, m.signal_date,
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
    result = [_row_to_dict(row[:13], stock_name=row[13]) for row in rows]
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
                             sold_price, sold_at, pnl_pct, created_at,
                             source_type, instance_id, signal_date""",
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
    """手动结束监控 — 以 DuckDB 日线最新收盘价结算（与监控中收益率同口径，design D8）。

    - sold_price：最新收盘价；pnl_pct = (现价 − entry_price) / entry_price × 100
    - DuckDB 不可用或无行情数据时降级为 0（原行为，不阻塞结束操作）
    """
    sold_price = 0.0
    pnl_pct = 0.0

    # 先取该监控的入场价，再查最新收盘价
    monitor = get_monitor(monitor_id)
    if monitor:
        entry = monitor.get("entry_price") or 0
        latest = _latest_daily_close(monitor["code"])
        if entry and latest:
            sold_price = latest
            pnl_pct = round((latest - entry) / entry * 100, 2)

    return settle_monitor(monitor_id, sold_price, datetime.now(timezone.utc).isoformat(), pnl_pct)


def _latest_daily_close(code: str) -> Optional[float]:
    """取某 code 日线（QFQ）最新收盘价；DuckDB 不可用/无数据返回 None。"""
    import os

    from .config import DUCKDB_PATH

    if not code or not os.path.exists(DUCKDB_PATH):
        return None
    try:
        import duckdb

        conn = duckdb.connect(DUCKDB_PATH, read_only=True)
        try:
            rows = conn.execute(
                """SELECT close FROM kline
                   WHERE code = ? AND kl_type = 'K_DAY' AND autype = 'QFQ'
                     AND close IS NOT NULL
                   ORDER BY time_key DESC LIMIT 1""",
                [code],
            ).fetchall()
        finally:
            conn.close()
        if rows and rows[0][0] is not None:
            return float(rows[0][0])
    except Exception:
        return None
    return None


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
                          COALESCE(m.source_type, 'chan') AS source_type,
                          m.instance_id, m.signal_date,
                          COALESCE(s.name, m.code) AS stock_name
                   FROM monitor m LEFT JOIN stock s ON m.code = s.code
                   WHERE m.id=%s""",
                (monitor_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if row:
        return _row_to_dict(row[:13], stock_name=row[13])
    return None


# ---- 分组 CRUD（monitor-group-change design D1/D2）----


def _check_group_name(name: str) -> Optional[str]:
    """校验分组名称：返回去空白后的名称；空名称返回 None。"""
    return name.strip() or None


def create_group(name: str) -> dict | None:
    """创建监控分组（名称查重 + sort_order 追加到末尾）。

    返回新分组 dict；名称非法（空/仅空白）或与现有分组重名时返回 None。
    """
    clean = _check_group_name(name)
    if clean is None:
        return None
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return _fallback_create_group(clean)
    try:
        with conn.cursor() as cur:
            # 查重 + 取末尾 sort_order（与 watchlist create_folder 同构，显式查重给出明确错误语义）
            cur.execute("SELECT id FROM monitor_group WHERE name = %s", (clean,))
            if cur.fetchone() is not None:
                return None
            cur.execute(
                """
                INSERT INTO monitor_group (name, sort_order)
                VALUES (%s, COALESCE((SELECT MAX(sort_order) FROM monitor_group), 0) + 1)
                RETURNING id, name, sort_order, created_at
                """,
                (clean,),
            )
            row = cur.fetchone()
        conn.commit()
        return _group_row_to_dict(row, monitoring_count=0, completed_count=0)
    finally:
        conn.close()


def list_groups() -> list[dict]:
    """列出全部分组（按 sort_order, id 排序），含每组 monitoring/completed 记录计数。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return _fallback_list_groups()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT g.id, g.name, g.sort_order, g.created_at,
                       COUNT(m.id) FILTER (WHERE m.status = 'monitoring') AS monitoring_count,
                       COUNT(m.id) FILTER (WHERE m.status = 'completed') AS completed_count
                FROM monitor_group g
                LEFT JOIN monitor m ON m.group_id = g.id
                GROUP BY g.id, g.name, g.sort_order, g.created_at
                ORDER BY g.sort_order, g.id
                """
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [
        _group_row_to_dict(
            (r[0], r[1], r[2], r[3]),
            monitoring_count=r[4],
            completed_count=r[5],
        )
        for r in rows
    ]


def get_group(group_id: int) -> Optional[dict]:
    """获取单个分组（存在性校验用）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        g = _find_fallback_group(group_id)
        return dict(g) if g else None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, sort_order, created_at FROM monitor_group WHERE id = %s",
                (group_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    return _group_row_to_dict(row) if row else None


def rename_group(group_id: int, name: str) -> bool:
    """重命名分组（名称查重）。

    返回 True 成功；名称非法/重名/分组不存在返回 False（语义由调用方区分 400/404）。
    """
    clean = _check_group_name(name)
    if clean is None:
        return False
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return _fallback_rename_group(group_id, clean)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM monitor_group WHERE name = %s AND id != %s",
                (clean, group_id),
            )
            if cur.fetchone() is not None:
                return False
            cur.execute(
                "UPDATE monitor_group SET name = %s WHERE id = %s",
                (clean, group_id),
            )
            ok = cur.rowcount > 0
        conn.commit()
        return ok
    finally:
        conn.close()


def delete_group(group_id: int) -> bool:
    """删除分组（组内监控记录由 FK ON DELETE SET NULL 置为「未分组」，不删记录）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return _fallback_delete_group(group_id)
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM monitor_group WHERE id = %s", (group_id,))
            ok = cur.rowcount > 0
        conn.commit()
        return ok
    finally:
        conn.close()


def reorder_groups(ids: list[int]) -> bool:
    """全量覆盖分组排序：按下标写入 sort_order = 1..n（单事务，幂等）。

    ids 中每个 id 必须存在且不重复，否则整体回滚返回 False。
    """
    _ensure_tables()
    if len(set(ids)) != len(ids):
        return False
    conn = _get_pg_conn()
    if conn is None:
        return _fallback_reorder_groups(ids)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM monitor_group WHERE id = ANY(%s)", (ids,))
            existing = {r[0] for r in cur.fetchall()}
            if len(existing) != len(ids):
                conn.rollback()
                return False
            for i, gid in enumerate(ids, start=1):
                cur.execute("UPDATE monitor_group SET sort_order = %s WHERE id = %s", (i, gid))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---- 分组内存降级（PG 不可用时）----


def _fallback_create_group(name: str) -> dict | None:
    global _next_fallback_group_id
    if any(g["name"] == name for g in _MONITOR_GROUPS):
        return None
    max_order = max((g["sort_order"] for g in _MONITOR_GROUPS), default=0)
    g = {
        "id": _next_fallback_group_id,
        "name": name,
        "sort_order": max_order + 1,
        "monitoring_count": 0,
        "completed_count": 0,
    }
    _next_fallback_group_id += 1
    _MONITOR_GROUPS.append(g)
    return dict(g)


def _fallback_list_groups() -> list[dict]:
    return [dict(g) for g in sorted(_MONITOR_GROUPS, key=lambda g: (g["sort_order"], g["id"]))]


def _fallback_rename_group(group_id: int, name: str) -> bool:
    g = _find_fallback_group(group_id)
    if g is None:
        return False
    if any(x["name"] == name and x["id"] != group_id for x in _MONITOR_GROUPS):
        return False
    g["name"] = name
    return True


def _fallback_delete_group(group_id: int) -> bool:
    global _MONITOR_GROUPS
    initial_len = len(_MONITOR_GROUPS)
    _MONITOR_GROUPS = [g for g in _MONITOR_GROUPS if g["id"] != group_id]
    return len(_MONITOR_GROUPS) < initial_len


def _fallback_reorder_groups(ids: list[int]) -> bool:
    """内存降级：直接重排 _MONITOR_GROUPS 列表序（给定序前置，其余保持相对序）。"""
    if len(set(ids)) != len(ids):
        return False
    if any(_find_fallback_group(i) is None for i in ids):
        return False
    by_id = {g["id"]: g for g in _MONITOR_GROUPS}
    reordered = [by_id[i] for i in ids] + [g for g in _MONITOR_GROUPS if g["id"] not in set(ids)]
    _MONITOR_GROUPS[:] = reordered
    for idx, g in enumerate(_MONITOR_GROUPS, start=1):
        g["sort_order"] = idx
    return True


def _group_row_to_dict(row, monitoring_count: int = 0, completed_count: int = 0) -> dict:
    """分组 DB 行 → 字典（row: id, name, sort_order, created_at）。"""
    return {
        "id": row[0],
        "name": row[1],
        "sort_order": row[2],
        "created_at": row[3].isoformat() if hasattr(row[3], "isoformat") else str(row[3]),
        "monitoring_count": monitoring_count or 0,
        "completed_count": completed_count or 0,
    }


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


def list_attributions_map() -> dict[int, list[str]]:
    """一次拉全表归因文本，按 monitor_id 分组（performance-page-change 任务 3.3）。

    绩效样本明细批量消费：避免逐样本 N 次 get_attribution 连接回查。
    - 顺序：created_at 升序（摘要多行拼接按时间自然阅读）
    - PG 不可用 / 查询失败返回 {}（未归因样本摘要为空串）
    """
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return {}
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT monitor_id, evidence FROM monitor_attribution ORDER BY created_at ASC, id ASC"
            )
            rows = cur.fetchall()
    except Exception:
        log.exception("归因全表查询失败")
        return {}
    finally:
        conn.close()
    result: dict[int, list[str]] = {}
    for monitor_id, evidence in rows:
        result.setdefault(monitor_id, []).append(evidence or "")
    return result


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


def list_monitor_sources() -> list[dict]:
    """来源字典（design D14）：monitor 表 distinct (source_type, instance_id) + 实例名。

    返回 [{value, label, source_type, instance_id?}]：
    - value 为前端过滤键：'chan' / 'strategy:<instance_id>' / 'watchlist'
    - label 为下拉展示名：缠论 / 策略名·实例名 / 自选
    PG 不可用返回 []；实例名缺失时降级 strategy_id 文本。
    """
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT DISTINCT source_type, instance_id
                   FROM monitor
                   ORDER BY source_type, instance_id"""
            )
            rows = cur.fetchall()
    except Exception:
        log.exception("来源字典查询失败")
        return []
    finally:
        conn.close()

    # 实例名（策略名·实例名）批量解析，复用 _fill_bsp_context 的语义
    def _instance_label(instance_id: int) -> str:
        try:
            from .strategy_store import get_instance

            ins = get_instance(instance_id)
            if ins:
                from .strategy_engines import DEFINITIONS

                defn = DEFINITIONS.get(ins["strategy_id"])
                strategy_name = defn.name if defn else ins["strategy_id"]
                return f"{strategy_name} · {ins['label']}"
        except Exception:
            log.exception("实例名解析失败: %s", instance_id)
        return f"策略实例 {instance_id}"

    result: list[dict] = []
    for source_type, instance_id in rows:
        st = source_type or "chan"  # 旧行 NULL 兜底
        if st == "strategy" and instance_id is not None:
            result.append({
                "value": f"strategy:{instance_id}",
                "label": _instance_label(instance_id),
                "source_type": "strategy",
                "instance_id": instance_id,
            })
        elif st == "watchlist":
            result.append({"value": "watchlist", "label": "自选", "source_type": "watchlist"})
        else:
            # chan / 缺省去重为一项
            if not any(r["value"] == "chan" for r in result):
                result.append({"value": "chan", "label": "缠论", "source_type": "chan"})
    return result


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
    """将 DB 行转为字典。

    strategy-signal-page design D6：兼容两种行形态——
    - 10 列（旧 SELECT/RETURNING）：来源字段取缺省（source_type='chan'，
      instance_id/signal_date=None）
    - 13 列（新 SELECT/RETURNING）：row[10..12] = source_type/instance_id/signal_date
    """
    d = {
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
    if len(row) >= 13:
        d["source_type"] = row[10] or "chan"  # 旧行 NULL 兜底（spec 存量数据兼容）
        d["instance_id"] = row[11]
        d["signal_date"] = (
            row[12].isoformat()[:10]
            if hasattr(row[12], "isoformat") and row[12]
            else (row[12] if isinstance(row[12], (str, type(None))) else None)
        )
    else:
        d["source_type"] = "chan"
        d["instance_id"] = None
        d["signal_date"] = None
    return d


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
    - bsp_type/direction/bsp_date ← 按 source_type 分叉（strategy-signal-page
      design D6 / downstream spec「买卖点上下文回查分叉」）：
      * 'chan'：bsp_index 按 (code,kl_type) 回查监控开始前最近一条买卖点
        （监控的语义起点，现状路径不变）；查不到给兜底值
      * 'strategy'：strategy_signal 按 (instance_id, signal_date) 定位信号行，
        bsp_type=state、direction←is_buy、bsp_date=signal_date、
        bsp_price=entry_ref_price；查不到给兜底值（与现状兜底一致）
    - industries ← stock_industry 批量查（rank≤3 名称数组）
    - current_price/change_pct/max_profit/max_drawdown ← DuckDB（_enrich_with_real_time_pnl）
    """
    if not items:
        return

    chan_items = [it for it in items if (it.get("source_type") or "chan") == "chan"]
    strategy_items = [it for it in items if (it.get("source_type") or "chan") == "strategy"]

    # chan 来源：bsp_index 回查（每 (code, kl_type) 取 monitor_start_time 前最近一条）
    try:
        conn = _get_pg_conn()
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    for it in chan_items:
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
            for it in chan_items:
                it["bsp_type"] = ""
                it["direction"] = "buy"
                it["bsp_date"] = _to_ms(it["monitor_start_time"])
    except Exception:
        log.exception("补齐买卖点上下文失败，使用兜底值")
        for it in chan_items:
            it.setdefault("bsp_type", "")
            it.setdefault("direction", "buy")
            it.setdefault("bsp_date", _to_ms(it["monitor_start_time"]))

    # strategy 来源：strategy_signal 按 (instance_id, signal_date, code) 定位
    # （downstream spec「策略监控回查」：上下文来自信号行，非 bsp_index）
    # strategy_label（「策略名 · 实例名 · 状态」）供前端来源标签列（downstream spec
    # 「监控列表来源展示」）：定义/实例名来自 strategy_store，状态文案来自 states 声明
    _strategy_label_cache: dict[int, tuple[str, str]] = {}  # instance_id -> (策略名, 实例名)
    for it in strategy_items:
        sig = None
        strategy_label = None
        try:
            if it.get("instance_id") is not None and it.get("signal_date"):
                from .strategy_store import get_signal_for_monitor

                sig = get_signal_for_monitor(
                    it["instance_id"], it["signal_date"], it["code"]
                )
                if sig and it["instance_id"] not in _strategy_label_cache:
                    from .strategy_store import get_instance

                    ins = get_instance(it["instance_id"])
                    if ins:
                        from .strategy_engines import DEFINITIONS

                        defn = DEFINITIONS.get(ins["strategy_id"])
                        _strategy_label_cache[it["instance_id"]] = (
                            defn.name if defn else ins["strategy_id"],
                            ins["label"],
                        )
        except Exception:
            log.exception("策略信号回查失败，使用兜底值: %s", it.get("code"))
            sig = None
        if sig:
            it["bsp_type"] = sig["state"]
            it["direction"] = "buy" if sig["is_buy"] else "sell"
            it["bsp_date"] = _to_ms(str(it["signal_date"]))
            if sig.get("entry_ref_price"):
                it["bsp_price"] = sig["entry_ref_price"]
            names = _strategy_label_cache.get(it["instance_id"])
            if names:
                strategy_label = f"{names[0]} · {names[1]} · {sig['state']}"
        else:
            # 兜底同现状（spec：查不到时使用与现状一致的兜底策略）
            it["bsp_type"] = ""
            it["direction"] = "buy"
            it["bsp_date"] = _to_ms(it["monitor_start_time"])
        it["strategy_label"] = strategy_label

    # 行业（rank≤3）批量单条 SQL
    try:
        from .bsp_store import get_industries_for_codes

        ind_map = get_industries_for_codes(list({it["code"] for it in items}))
        for it in items:
            it["industries"] = ind_map.get(it["code"], [])
    except Exception:
        for it in items:
            it["industries"] = []

    # 入场价即买卖点价格（同值换名；strategy 命中信号行时已被 entry_ref_price 覆盖）
    for it in items:
        if "bsp_price" not in it:
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