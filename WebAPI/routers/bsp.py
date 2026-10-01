# -*- coding: utf-8 -*-
"""
BSP 路由 — 买卖点查询 API。

bsp-page-change D5：
- 过滤下推（2.3/2.6）：keyword/kl_type/bsp_type/direction/date 全部进 store 层 WHERE，
  COUNT 与分页共用条件，total = 过滤后总数。
- 契约适配（2.4）：store 返回原始行，router 映射为前端 PageRes{list,total,page,page_size}
  与 BspRecord（bsp_price←price、direction←is_buy、bsp_date→ms、industries: string[]）；
  industries 按页批量单条 SQL（替代 N+1）；current_price/change_pct 按页批量取
  DuckDB 最新两根 K 线收盘价，DuckDB 不可用时降级 0（列表照常渲染）。
- 手动补算入口（3.6）：POST /api/bsp/catch-up → 引擎 catch_up（水位驱动、幂等）。
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..bsp_store import (
    fetch_current_prices,
    get_bsp_by_code,
    get_industries_for_codes,
    query_bsp,
    query_bsp_aggregate,
)
from ..incremental_engine import catch_up

log = logging.getLogger("bsp_router")

router = APIRouter(prefix="/api/bsp", tags=["bsp"])


def _to_ms(bsp_date_iso: str, time_key: str) -> int:
    """bsp_date → 毫秒时间戳（与 /api/klines 的 bsp.t 同一 CTime 语义，D5）。"""
    try:
        from ChanAnalyse.DataAPI.KLineStore import str_to_ctime

        return int(str_to_ctime(time_key).ts * 1000)
    except Exception:
        import datetime as _dt

        try:
            dt = _dt.datetime.strptime(bsp_date_iso, "%Y-%m-%d")
            return int(dt.timestamp() * 1000)
        except Exception:
            return 0


@router.get("")
async def bsp_list(
    page: int = Query(1),
    page_size: int = Query(20),
    keyword: str = Query(""),
    bsp_type: str = Query(""),
    direction: str = Query(""),
    kl_type: str = Query(""),
    date: str = Query(""),
):
    """买卖点列表（分页 + 筛选；date 为 YYYY-MM-DD 精确日期，不带时行为不变）。

    响应契约 PageRes<BspRecord>：{list, total, page, page_size}。
    """
    is_buy = None
    if direction == "buy":
        is_buy = True
    elif direction == "sell":
        is_buy = False

    # 过滤下推（2.3/2.6）：keyword/kl_type/bsp_type/direction/date 同一 WHERE，
    # COUNT 与分页共用，total = 过滤后总数；无命中 list=[] 且 total=0
    result = query_bsp(
        kl_type=kl_type if kl_type else "",
        date=date if date else "",
        bsp_type=bsp_type if bsp_type else "",
        is_buy=is_buy,
        keyword=keyword if keyword else "",
        page=page,
        page_size=page_size,
    )

    items = result["items"]

    # 行业（rank≤3）按页批量单条 SQL（替代 N+1）
    industries_map = get_industries_for_codes([i["code"] for i in items])

    # 现价/涨跌幅按页批量取 DuckDB 最新两根 K 线；失败降级 0（列表照常渲染）
    price_map = fetch_current_prices([(i["code"], i["kl_type"]) for i in items])

    records = []
    for idx, it in enumerate(items):
        current_price, change_pct = price_map.get((it["code"], it["kl_type"]), (0.0, 0.0))
        records.append({
            "id": (page - 1) * page_size + idx + 1,  # 行号占位（表无 id 列）
            "code": it["code"],
            "name": it["name"],
            "industries": industries_map.get(it["code"], []),
            "bsp_type": it["bsp_type"],
            "direction": "buy" if it["is_buy"] else "sell",
            "bsp_price": it["price"],
            "current_price": current_price,
            "bsp_date": _to_ms(it["bsp_date"], it["time_key"]),
            "kl_type": it["kl_type"],
            "change_pct": change_pct,
        })

    return {
        "list": records,
        "total": result["total"],
        "page": result["page"],
        "page_size": result["page_size"],
    }


@router.get("/aggregate")
async def bsp_aggregate(
    kl_type: str = Query(""),
    date: str = Query(""),
    bsp_type: str = Query(""),
    direction: str = Query(""),
):
    """买卖点板块聚合（bsp-page-change D6：冻结现状，不进验收）。"""
    is_buy = None
    if direction == "buy":
        is_buy = True
    elif direction == "sell":
        is_buy = False

    return query_bsp_aggregate(
        kl_type=kl_type if kl_type else "",
        date=date if date else "",
        bsp_type=bsp_type if bsp_type else "",
        is_buy=is_buy,
    )


@router.post("/catch-up")
async def bsp_catch_up(
    background: bool = Query(False, description="true 时后台执行，立即返回受理结果"),
    codes: str = Query("", description="逗号分隔股票代码；空=全部"),
    kl_type: str = Query("", description="周期（D/W/M/60m/30m）；空=全部"),
    day: str = Query("", description="YYYY-MM-DD，仅补算源水位在该日的键；空=不过滤"),
    limit: int = Query(0, description="本批最多处理键数，0=不限"),
    force: bool = Query(False, description="跳过水位门，范围内全部整套重写"),
):
    """手动触发水位补算（3.6：启动/定时/手动多入口之一，幂等可重入）。"""
    code_list = [c.strip() for c in codes.split(",") if c.strip()] or None
    period_list = [p.strip() for p in kl_type.split(",") if p.strip()] or None

    if background:
        async def _run():
            try:
                await asyncio.to_thread(catch_up, code_list, period_list, day or None, limit, force)
            except Exception:
                log.exception("后台补算失败")

        asyncio.create_task(_run())
        return {"accepted": True, "background": True}

    try:
        return await asyncio.to_thread(catch_up, code_list, period_list, day or None, limit, force)
    except HTTPException:
        raise  # 周期词表非法等 400（3.2 既有行为）
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/{code}")
async def bsp_by_code(
    code: str,
    kl_types: Optional[str] = Query(None, alias="kl_types"),
):
    """指定股票的多级别买卖点（区间套）。

    2.5：kl_types IN 为参数化占位符（消除字符串拼接注入面）。
    """
    kl_list = [t.strip() for t in kl_types.split(",")] if kl_types else None
    return get_bsp_by_code(code, kl_list)
