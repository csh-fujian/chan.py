# -*- coding: utf-8 -*-
"""
Stock 路由 — 股票管理 API。

注意: 静态路由（/status, /export-config, /sync, /sync/status）必须在参数化路由（/{code}）之前定义。
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Union

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from .. import meta_sync, stock_store
from ..stock_store import (
    delete_stock,
    get_stock,
    get_stock_meta,
    get_stocks_with_daily_close,
    import_stocks,
    list_stocks,
    upsert_industries,
    upsert_stock,
)

router = APIRouter(prefix="/api/stocks", tags=["stocks"])

log = logging.getLogger("stocks_api")


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


# ---- 元数据同步（stock-metadata-sync）----
# 防重入标志（与 app.py 内置到期检查调度共用）
_SYNC_RUNNING = False
_SYNC_STARTED_AT: Optional[datetime] = None
_SYNC_JOB_ID: Optional[int] = None


class StockSyncRequest(BaseModel):
    """手动元数据同步请求。"""

    code: Optional[str] = Field(default=None, description="单只代码；缺省=全市场")
    domains: Optional[list[str]] = Field(
        default=None,
        description="域列表：identity/profile/industry/snapshot/financial/holders；缺省=全部",
    )
    force: bool = Field(default=True, description="无视到期间隔强制刷新（仍走断点续传）")


class SyncSummary(BaseModel):
    """同步汇总。"""

    created: int = 0
    updated: int = 0
    disabled: int = 0
    skipped: int = 0
    degraded: bool = False
    failed: list[tuple[str, str, str]] = []
    domains_run: list[str] = []


class SyncStartResponse(BaseModel):
    """全市场后台同步已启动。"""

    started: bool
    job_id: int


class SyncStatusResponse(BaseModel):
    """同步状态（running 取内存标志，时间/汇总取 PG sync_job 最近一行）。"""

    running: bool
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    last_summary: Optional[dict] = None
    job_id: Optional[int] = None
    status: Optional[str] = None


def _begin_market_sync(domains: Optional[list[str]], force: bool) -> Optional[int]:
    """原子占住防重入标志并创建 sync_job 行；已有任务在跑返回 None。"""
    global _SYNC_RUNNING, _SYNC_STARTED_AT, _SYNC_JOB_ID
    if _SYNC_RUNNING:
        return None
    _SYNC_RUNNING = True
    _SYNC_STARTED_AT = datetime.now(timezone.utc)
    doms = list(domains) if domains else list(meta_sync.DOMAIN_ORDER)
    try:
        job_id = stock_store.create_sync_job(doms, "market", force)
    except Exception:
        _SYNC_RUNNING = False
        _SYNC_STARTED_AT = None
        raise
    _SYNC_JOB_ID = job_id
    return job_id


async def _run_market_sync_task(
    domains: Optional[list[str]], force: bool, job_id: int
) -> None:
    """后台全市场同步（BackgroundTasks / 调度协程共用）：try/finally 清标志。"""
    global _SYNC_RUNNING, _SYNC_STARTED_AT, _SYNC_JOB_ID
    try:
        await asyncio.to_thread(
            meta_sync.sync,
            codes=None,
            domains=list(domains) if domains else list(meta_sync.DOMAIN_ORDER),
            force=force,
            job_id=job_id,
        )
    except Exception:  # sync 内部已把 sync_job 置 failed/interrupted（部分汇总持久化）
        log.exception("market meta sync task failed")
    finally:
        _SYNC_RUNNING = False
        _SYNC_STARTED_AT = None
        _SYNC_JOB_ID = None


@router.post(
    "/sync",
    response_model=Union[SyncSummary, SyncStartResponse],
    summary="手动元数据同步",
)
async def sync_stock_meta_endpoint(
    body: StockSyncRequest,
    background_tasks: BackgroundTasks,
):
    """手动触发元数据同步。

    - 有 code：同步执行（asyncio.to_thread 跑 sync），直接返回该标的同步汇总；
    - 无 code（全市场）：BackgroundTasks 后台执行并返回 job_id；运行中拒绝重入（409）。
    """
    if body.domains:
        invalid = [d for d in body.domains if d not in meta_sync.DOMAIN_ORDER]
        if invalid:
            raise HTTPException(
                status_code=422,
                detail=f"invalid domains: {invalid}; valid: {list(meta_sync.DOMAIN_ORDER)}",
            )

    if body.code:
        summary = await asyncio.to_thread(
            meta_sync.sync,
            codes=[body.code],
            domains=body.domains,
            force=body.force,
        )
        return SyncSummary(
            created=summary["created"],
            updated=summary["updated"],
            disabled=summary["disabled"],
            skipped=summary["skipped"],
            degraded=summary["degraded"],
            failed=[tuple(f) for f in summary["failed"]],
            domains_run=summary["domains_run"],
        )

    job_id = _begin_market_sync(body.domains, body.force)
    if job_id is None:
        raise HTTPException(status_code=409, detail="sync already running")
    background_tasks.add_task(_run_market_sync_task, body.domains, body.force, job_id)
    return SyncStartResponse(started=True, job_id=job_id)


@router.get(
    "/sync/status",
    response_model=SyncStatusResponse,
    summary="元数据同步状态",
)
async def sync_meta_status():
    """同步状态：running 取内存标志；时间/汇总取 PG sync_job 最近一行（重启后仍可查）。

    读取时把进程重启遗留的 running 孤儿任务置为 interrupted（spec 场景：孤儿按 interrupted 处理）。
    """
    stock_store.mark_orphan_jobs_interrupted(keep_id=_SYNC_JOB_ID)
    last = stock_store.get_last_sync_job()
    running = _SYNC_RUNNING
    return SyncStatusResponse(
        running=running,
        started_at=last.get("started_at") if last else None,
        finished_at=last.get("finished_at") if last else None,
        last_summary=last.get("summary") if last else None,
        job_id=_SYNC_JOB_ID if running else (last.get("id") if last else None),
        status="running" if running else (last.get("status") if last else None),
    )


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


@router.get("/{code}/meta")
async def stock_meta(code: str):
    """股票元数据（K 线页「股票信息」tab）：档案+快照+身份补充+tags/notes+股东户数近 1 年。

    键恒定存在（空值为 ""/null/[]）；库外 code 返回 404。
    """
    meta = get_stock_meta(code)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Stock {code!r} not found")
    return meta


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