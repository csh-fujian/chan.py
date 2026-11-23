# -*- coding: utf-8 -*-
"""形态信号 PG 存储（chan-pattern-buy-signal 任务 3.1）。

表 pattern_signal：唯一键 (code, kl_type, autype, pattern_type, confirm_time_key)。
只落稳定字段（design D4）：分数/档位/参考线/失效标记/detail JSONB（关键点与
量比数据），**不落文案**——注意事项/建议/评分明细由读取侧按当前口径现算
（pattern_meta.PATTERN_META）。

PG_DSN 未配置或不可达时静默降级（与 bsp_store 同模式）：写跳过、查询返回空。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

import psycopg2

log = logging.getLogger("pattern_store")

PG_DSN = os.environ.get("PG_DSN", "")

_pg_down = False


def _get_pg_conn():
    """获取 PG 连接，PG_DSN 未配置或 PG 不可达时返回 None（降级）。"""
    global _pg_down
    if not PG_DSN:
        return None
    try:
        conn = psycopg2.connect(PG_DSN)
    except psycopg2.OperationalError as e:
        if not _pg_down:
            log.warning("PG 不可达，形态存储降级为无数据库模式: %s", e)
            _pg_down = True
        return None
    if _pg_down:
        log.info("PG 连接已恢复（形态存储）")
        _pg_down = False
    return conn


def _ensure_tables():
    """惰性建表（CREATE TABLE IF NOT EXISTS）。"""
    conn = _get_pg_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS pattern_signal (
                    code VARCHAR(32) NOT NULL,
                    kl_type VARCHAR(16) NOT NULL,
                    autype VARCHAR(16) NOT NULL DEFAULT 'QFQ',
                    pattern_type VARCHAR(32) NOT NULL,
                    pattern_date VARCHAR(10) NOT NULL,
                    confirm_time_key VARCHAR(32) NOT NULL,
                    price DOUBLE PRECISION,
                    ref_line_high DOUBLE PRECISION,
                    ref_line_low DOUBLE PRECISION,
                    score SMALLINT,
                    qual VARCHAR(8),
                    invalid BOOLEAN NOT NULL DEFAULT FALSE,
                    veto VARCHAR(32),
                    detail JSONB,
                    direction VARCHAR(4) NOT NULL DEFAULT 'buy',
                    updated_at TIMESTAMP DEFAULT NOW(),
                    CONSTRAINT pk_pattern_signal UNIQUE
                        (code, kl_type, autype, pattern_type, confirm_time_key)
                )
                """
            )
            # chan-pattern-sell-signal：direction 加列（幂等，存量行回填 'buy'）
            cur.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'pattern_signal' AND column_name = 'direction'
                    ) THEN
                        ALTER TABLE pattern_signal
                            ADD COLUMN direction VARCHAR(4) NOT NULL DEFAULT 'buy';
                    END IF;
                END
                $$;
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_pattern_signal_query "
                "ON pattern_signal (pattern_type, kl_type, pattern_date)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_pattern_signal_code "
                "ON pattern_signal (code, kl_type)"
            )
        conn.commit()
    finally:
        conn.close()


def upsert_pattern_rows(code: str, kl_type: str, autype: str, rows: list[tuple]) -> int:
    """批量写入形态信号（INSERT ON CONFLICT DO UPDATE，重复检测幂等覆盖）。

    rows 元组序与 pattern_detector.ROW_FIELDS 对齐：
    (pattern_type, pattern_date, confirm_time_key, price,
     ref_line_high, ref_line_low, score, qual, invalid, veto, detail_json,
     direction)
    """
    if not rows:
        return 0
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return 0
    n = 0
    try:
        with conn.cursor() as cur:
            for r in rows:
                direction = r[11] if len(r) > 11 and r[11] else "buy"
                cur.execute(
                    """
                    INSERT INTO pattern_signal
                        (code, kl_type, autype, pattern_type, pattern_date,
                         confirm_time_key, price, ref_line_high, ref_line_low,
                         score, qual, invalid, veto, detail, direction)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    ON CONFLICT (code, kl_type, autype, pattern_type, confirm_time_key)
                    DO UPDATE SET
                        pattern_date = EXCLUDED.pattern_date,
                        price = EXCLUDED.price,
                        ref_line_high = EXCLUDED.ref_line_high,
                        ref_line_low = EXCLUDED.ref_line_low,
                        score = EXCLUDED.score,
                        qual = EXCLUDED.qual,
                        invalid = EXCLUDED.invalid,
                        veto = EXCLUDED.veto,
                        detail = EXCLUDED.detail,
                        direction = EXCLUDED.direction,
                        updated_at = NOW()
                    """,
                    (code, kl_type, autype, r[0], r[1], r[2], r[3], r[4], r[5],
                     r[6], r[7], r[8], r[9], r[10], direction),
                )
                n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def query_patterns(
    pattern_type: str = "",
    kl_type: str = "",
    date_from: str = "",
    date_to: str = "",
    code: str = "",
    code_keyword: str = "",
    invalid: Optional[bool] = None,
    score_min: Optional[int] = None,
    direction: str = "",
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """分页查询形态信号（routers/pattern.py 使用）。

    失效状态筛选：invalid=None 全部；True 只看失效；False 只看有效。
    score_min：置信分下限（NULL 分的存量行被该条件排除——「未评估」行不猜分）。
    direction：'buy' / 'sell' 方向过滤（空=全部）。
    """
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return {"items": [], "total": 0}

    where = ["1=1"]
    params: list = []
    if pattern_type:
        where.append("pattern_type = %s")
        params.append(pattern_type)
    if kl_type:
        where.append("kl_type = %s")
        params.append(kl_type)
    if direction:
        where.append("direction = %s")
        params.append(direction)
    if date_from:
        where.append("pattern_date >= %s")
        params.append(date_from)
    if date_to:
        where.append("pattern_date <= %s")
        params.append(date_to)
    if code:
        where.append("code = %s")
        params.append(code)
    if code_keyword:
        where.append("code LIKE %s OR detail->>'name' LIKE %s")
        params.extend([f"%{code_keyword}%", f"%{code_keyword}%"])
    if invalid is not None:
        where.append("invalid = %s")
        params.append(invalid)
    if score_min is not None:
        where.append("score >= %s")
        params.append(score_min)

    where_sql = " AND ".join(where)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT count(*) FROM pattern_signal WHERE {where_sql}", params)
            total = cur.fetchone()[0]
            offset = max(0, (page - 1) * page_size)
            cur.execute(
                f"""
                SELECT code, kl_type, autype, pattern_type, pattern_date,
                       confirm_time_key, price, ref_line_high, ref_line_low,
                       score, qual, invalid, veto, detail, direction
                FROM pattern_signal WHERE {where_sql}
                ORDER BY confirm_time_key DESC, code
                LIMIT %s OFFSET %s
                """,
                params + [page_size, offset],
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    items = []
    for r in rows:
        detail = r[13] if isinstance(r[13], dict) else (
            json.loads(r[13]) if r[13] else {})
        items.append({
            "code": r[0], "kl_type": r[1], "autype": r[2],
            "pattern_type": r[3], "pattern_date": r[4],
            "confirm_time_key": r[5], "price": r[6],
            "ref_line_high": r[7], "ref_line_low": r[8],
            "score": r[9], "qual": r[10], "invalid": r[11], "veto": r[12],
            "detail": detail, "direction": r[14] if len(r) > 14 else "buy",
        })
    return {"items": items, "total": total}


def get_patterns_by_code(code: str, kl_types: Optional[list] = None) -> list[dict]:
    """指定股票的多周期形态信号（K 线页 overlay 数据源）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return []
    try:
        with conn.cursor() as cur:
            if kl_types:
                cur.execute(
                    """
                    SELECT code, kl_type, autype, pattern_type, pattern_date,
                           confirm_time_key, price, ref_line_high, ref_line_low,
                           score, qual, invalid, veto, detail, direction
                    FROM pattern_signal
                    WHERE code = %s AND kl_type = ANY(%s)
                    ORDER BY confirm_time_key
                    """,
                    (code, kl_types),
                )
            else:
                cur.execute(
                    """
                    SELECT code, kl_type, autype, pattern_type, pattern_date,
                           confirm_time_key, price, ref_line_high, ref_line_low,
                           score, qual, invalid, veto, detail, direction
                    FROM pattern_signal
                    WHERE code = %s
                    ORDER BY confirm_time_key
                    """,
                    (code,),
                )
            rows = cur.fetchall()
    finally:
        conn.close()

    out = []
    for r in rows:
        detail = r[13] if isinstance(r[13], dict) else (
            json.loads(r[13]) if r[13] else {})
        out.append({
            "code": r[0], "kl_type": r[1], "autype": r[2],
            "pattern_type": r[3], "pattern_date": r[4],
            "confirm_time_key": r[5], "price": r[6],
            "ref_line_high": r[7], "ref_line_low": r[8],
            "score": r[9], "qual": r[10], "invalid": r[11], "veto": r[12],
            "detail": detail, "direction": r[14] if len(r) > 14 else "buy",
        })
    return out
