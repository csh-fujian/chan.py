# -*- coding: utf-8 -*-
"""
范围解析辅助 — 'all' 范围的 ST/*ST 过滤所需的股票名称批量读取
（strategy-task-redesign design D3）。

scheduler 的 _filter_st_codes 消费：按 code 批量取 stock 表名称。
名称缺失的股票由调用方放行（宁多勿漏），本模块只负责取数。
独立小模块避免 scheduler 与 stock_store 的导入环（stock_store 体积大且
被多方引用，这里只需要一个只读查询）。
"""

import logging
from typing import Optional

from ..config import PG_DSN

log = logging.getLogger("strategy_scope_resolver")


def get_stock_names(codes: list[str]) -> dict[str, Optional[str]]:
    """批量读取股票名称 {code: name}（stock 表无该 code 的键缺省为 None）。

    PG 不可用返回空 dict（调用方全量放行，ST 过滤降级不阻塞扫描）。
    """
    if not codes:
        return {}
    import psycopg2

    if not PG_DSN:
        return {}
    try:
        conn = psycopg2.connect(PG_DSN)
    except psycopg2.OperationalError as e:
        log.warning("PG 不可达，ST 过滤降级为全量放行: %s", e)
        return {}
    result: dict[str, Optional[str]] = {c: None for c in codes}
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT code, name FROM stock WHERE code = ANY(%s)", (codes,))
            for code, name in cur.fetchall():
                result[code] = name
    except Exception:
        log.exception("批量读取股票名称失败，ST 过滤降级为全量放行")
        result = {c: None for c in codes}
    finally:
        conn.close()
    return result
