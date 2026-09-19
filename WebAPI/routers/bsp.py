# -*- coding: utf-8 -*-
"""
BSP 路由 — 买卖点查询 API。
"""

from typing import Optional

from fastapi import APIRouter, Query

from ..bsp_store import (
    get_bsp_by_code,
    query_bsp,
    query_bsp_aggregate,
)

router = APIRouter(prefix="/api/bsp", tags=["bsp"])


@router.get("")
async def bsp_list(
    page: int = Query(1),
    page_size: int = Query(20),
    keyword: str = Query(""),
    bsp_type: str = Query(""),
    direction: str = Query(""),
    kl_type: str = Query(""),
):
    """买卖点列表（分页 + 筛选）。"""
    is_buy = None
    if direction == "buy":
        is_buy = True
    elif direction == "sell":
        is_buy = False

    # keyword 匹配 code 或 stock.name
    result = query_bsp(
        kl_type=kl_type if kl_type else "",
        bsp_type=bsp_type if bsp_type else "",
        is_buy=is_buy,
        page=page,
        page_size=page_size,
    )

    # 如果有 keyword 过滤，前端已在请求中加入（当前 store 层未直接支持 keyword）
    # 所以在这里做额外过滤
    if keyword and result["items"]:
        kw = keyword.lower()
        result["items"] = [
            i
            for i in result["items"]
            if kw in i["code"].lower() or kw in i.get("name", "").lower()
        ]
        result["total"] = len(result["items"])

    return result


@router.get("/aggregate")
async def bsp_aggregate(
    kl_type: str = Query(""),
    date: str = Query(""),
    bsp_type: str = Query(""),
    direction: str = Query(""),
):
    """买卖点板块聚合。"""
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


@router.get("/{code}")
async def bsp_by_code(
    code: str,
    kl_types: Optional[str] = Query(None, alias="kl_types"),
):
    """指定股票的多级别买卖点（区间套）。"""
    kl_list = [t.strip() for t in kl_types.split(",")] if kl_types else None
    return get_bsp_by_code(code, kl_list)