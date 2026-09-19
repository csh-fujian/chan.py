# -*- coding: utf-8 -*-
"""
Stock 路由 — 股票管理 API。

注意: 静态路由（/status, /export-config）必须在参数化路由（/{code}）之前定义。
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..stock_store import (
    delete_stock,
    get_stock,
    get_stocks_with_daily_close,
    import_stocks,
    list_stocks,
    upsert_industries,
    upsert_stock,
)

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


# ---- 静态路由（必须在参数化路由之前）----


@router.get("/industries")
async def stock_industries():
    """行业列表（完整实现在 chan-stock-manage）。"""
    return []


@router.get("/status")
async def stocks_status():
    """灌数状态（返回 DuckDB 统计信息）。"""
    from ..config import DUCKDB_PATH
    import os

    if not os.path.exists(DUCKDB_PATH):
        return {"total_stocks": 0, "total_bars": 0, "last_update": None}

    try:
        import duckdb

        conn = duckdb.connect(DUCKDB_PATH, read_only=True)
        try:
            row = conn.execute(
                "SELECT COUNT(DISTINCT code), COUNT(*), MAX(time_key) FROM kline"
            ).fetchone()
            return {
                "total_stocks": row[0] if row else 0,
                "total_bars": row[1] if row else 0,
                "last_update": row[2] if row else None,
            }
        finally:
            conn.close()
    except Exception:
        return {"total_stocks": 0, "total_bars": 0, "last_update": None}


@router.get("/export-config")
async def stocks_export_config():
    """导出灌数配置。"""
    from ..stock_store import _get_pg_conn

    pg_conn = _get_pg_conn()
    if pg_conn is not None:
        try:
            with pg_conn.cursor() as cur:
                cur.execute("SELECT code, kl_types, autypes FROM stock WHERE enabled = TRUE")
                rows = cur.fetchall()
        finally:
            pg_conn.close()
        return [
            {
                "code": r[0],
                "kl_types": r[1] or ["K_DAY"],
                "autypes": r[2] or ["QFQ"],
            }
            for r in rows
        ]

    from ..config import DUCKDB_PATH
    import os

    if os.path.exists(DUCKDB_PATH):
        try:
            import duckdb

            conn = duckdb.connect(DUCKDB_PATH, read_only=True)
            try:
                rows = conn.execute(
                    "SELECT DISTINCT code FROM kline ORDER BY code"
                ).fetchall()
                return [
                    {"code": r[0], "kl_types": ["K_DAY"], "autypes": ["QFQ"]}
                    for r in rows
                ]
            finally:
                conn.close()
        except Exception:
            pass
    return []


@router.post("/import")
async def import_stocks_endpoint(body: dict):
    """批量导入股票。"""
    stocks = body.get("stocks", [])
    return import_stocks(stocks)


# ---- 集合路由 ----


@router.get("")
async def list_stocks_endpoint(
    q: str = Query(""),
    exchange: str = Query(""),
    industry: str = Query(""),
    enabled: Optional[bool] = Query(None),
    page: int = Query(1),
    page_size: int = Query(20),
):
    """股票列表（筛选 + 分页）。"""
    return list_stocks(
        q=q,
        exchange=exchange,
        industry=industry,
        enabled=enabled,
        page=page,
        page_size=page_size,
    )


@router.post("")
async def upsert_stock_endpoint(body: dict):
    """新增或更新股票。"""
    code = body.get("code", "")
    if not code:
        raise HTTPException(status_code=422, detail="code is required")
    stock = upsert_stock(
        code=code,
        name=body.get("name", code),
        exchange=body.get("exchange", ""),
        enabled=body.get("enabled", True),
        kl_types=body.get("kl_types"),
        autypes=body.get("autypes"),
        tags=body.get("tags"),
        notes=body.get("notes", ""),
    )
    industries_data = body.get("industries", [])
    if industries_data:
        upsert_industries(code, industries_data)
    return stock


# ---- 参数化路由（/{code} 必须在最后）----


@router.get("/{code}/profile")
async def stock_profile(code: str):
    """标的详情（供前端 K 线页 profile）。"""
    stock = get_stock(code)
    if not stock:
        return {
            "code": code,
            "name": code,
            "industries": [],
            "region": "--",
            "concepts": [],
            "price": 0,
            "change_pct": 0,
        }

    profiles = get_stocks_with_daily_close([code])
    if profiles:
        return profiles[0]
    return stock


@router.get("/{code}")
async def get_stock_endpoint(code: str):
    """股票详情。"""
    stock = get_stock(code)
    if not stock:
        raise HTTPException(status_code=404, detail=f"Stock {code!r} not found")
    return stock


@router.delete("/{code}")
async def delete_stock_endpoint(code: str):
    """删除股票。"""
    ok = delete_stock(code)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Stock {code!r} not found")
    return {"success": True}