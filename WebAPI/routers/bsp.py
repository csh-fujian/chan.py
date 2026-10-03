# -*- coding: utf-8 -*-
"""
BSP 路由 — 买卖点查询 API。

bsp-page-change D5：
- 过滤下推（2.3/2.6）：keyword/kl_type/bsp_type/direction/date_from~date_to 全部进
  store 层 WHERE，COUNT 与分页共用条件，total = 过滤后总数。
- 契约适配（2.4）：store 返回原始行，router 映射为前端 PageRes{list,total,page,page_size}
  与 BspRecord（bsp_price←price、direction←is_buy、bsp_date→ms、industries: string[]）；
  industries 按页批量单条 SQL（替代 N+1）；current_price/change_pct 按页批量取
  DuckDB 最新两根 K 线收盘价，DuckDB 不可用时降级 0（列表照常渲染）。
- 日期范围（2.6/D7）：date_from/date_to（YYYY-MM-DD）半开区间
  `[date_from, date_to + 1)` 下推 SQL，只传一端单边过滤、双空不过滤。
- 手动补算入口（3.6）：POST /api/bsp/catch-up → 引擎 catch_up（水位驱动、幂等）。
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..bsp_store import (
    fetch_current_prices,
    get_bsp_by_code,
    get_industries_for_codes,
    get_price_at,
    query_bsp,
    query_bsp_aggregate,
)
from ..chan_service import resolve_period
from ..incremental_engine import catch_up

log = logging.getLogger("bsp_router")

router = APIRouter(prefix="/api/bsp", tags=["bsp"])


def _check_date_param(value: str, name: str) -> str:
    """日期查询参数校验（YYYY-MM-DD），非法 → 422（风格同 routers/system.py，勿跨模块导入私有函数）。"""
    if not value:
        return value
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{name} 需为 YYYY-MM-DD 日期")
    return value


# 方向化标签 → (原始枚举集合, is_buy)；与前端 utils/bsp.ts TYPE_MAP 同构（design D11）
# 原始枚举: '1','2','2s','3a','3b','1p'
_DIRECTIONAL_LABELS: dict[str, tuple[list[str], bool]] = {
    "1B": (["1"], True),
    "1S": (["1"], False),
    "2B": (["2"], True),
    "2S": (["2"], False),
    "L2B": (["2s"], True),
    "L2S": (["2s"], False),
    "3B": (["3a", "3b"], True),
    "3S": (["3a", "3b"], False),
    "PZ-B": (["1p"], True),
    "PZ-S": (["1p"], False),
}


def _resolve_bsp_type(bsp_type: str) -> tuple[list[str], Optional[bool]]:
    """bsp_type 查询参数 → (原始枚举集合, is_buy 约束)。

    方向化标签（2B/3S/PZ-B...）→ 枚举集合 + 方向约束（design D11，修复选标签
    查不到记录的既有 bug）；原始枚举直传（如 '2'）→ 仅类型匹配、无方向约束。
    """
    if bsp_type in _DIRECTIONAL_LABELS:
        types, is_buy = _DIRECTIONAL_LABELS[bsp_type]
        return types, is_buy
    return [bsp_type], None


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
    date_from: str = Query(""),
    date_to: str = Query(""),
):
    """买卖点列表（分页 + 筛选；date_from/date_to 为 YYYY-MM-DD 日期范围，
    双端齐备按闭区间 [date_from, date_to] 匹配，只传一端单边过滤，双空不过滤）。

    响应契约 PageRes<BspRecord>：{list, total, page, page_size}。
    """
    _check_date_param(date_from, "date_from")
    _check_date_param(date_to, "date_to")

    is_buy = None
    if direction == "buy":
        is_buy = True
    elif direction == "sell":
        is_buy = False

    # 过滤下推（2.3/2.6）：keyword/kl_type/bsp_type/direction/date_from~date_to
    # 同一 WHERE，COUNT 与分页共用，total = 过滤后总数；无命中 list=[] 且 total=0
    # bsp_type 支持方向化标签（2B/3S/PZ-B...，design D11）与原始枚举直传
    bsp_types, label_is_buy = _resolve_bsp_type(bsp_type) if bsp_type else ([], None)
    if label_is_buy is not None:
        is_buy = label_is_buy  # 标签自带方向语义，覆盖 direction 参数

    result = query_bsp(
        kl_type=kl_type if kl_type else "",
        date_from=date_from if date_from else "",
        date_to=date_to if date_to else "",
        bsp_types=bsp_types,
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
    date_from: str = Query(""),
    date_to: str = Query(""),
    bsp_type: str = Query(""),
    direction: str = Query(""),
):
    """买卖点板块聚合（bsp-page-change D6：冻结现状，不进验收）。

    2.6：date 参数连带升级为 date_from/date_to（与主查询同一范围语义，避免契约漂移）。
    """
    _check_date_param(date_from, "date_from")
    _check_date_param(date_to, "date_to")

    is_buy = None
    if direction == "buy":
        is_buy = True
    elif direction == "sell":
        is_buy = False

    return query_bsp_aggregate(
        kl_type=kl_type if kl_type else "",
        date_from=date_from if date_from else "",
        date_to=date_to if date_to else "",
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


@router.get("/price-at")
async def bsp_price_at(
    code: str = Query(..., description="股票代码"),
    kl_type: str = Query(..., description="周期（D/W/M/60m/30m）"),
    time: str = Query(..., description="时间点（YYYY-MM-DD HH:MM:SS 或 YYYY-MM-DD）"),
):
    """取该股票指定周期上不晚于 time 的最近一根 K 线收盘价（design D12）。

    监控弹窗价格联动用：加入监控即加入所选时间点的价格。无数据 404。
    注意：本路由必须注册在 /{code} 之前（FastAPI 按注册顺序匹配）。
    """
    if not code.strip():
        raise HTTPException(status_code=422, detail="code 不能为空")
    try:
        resolve_period(kl_type)
    except HTTPException:
        raise
    if not time.strip():
        raise HTTPException(status_code=422, detail="time 不能为空")

    result = await asyncio.to_thread(get_price_at, code.strip(), kl_type, time.strip())
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"{code} 在 {time} 之前无 {kl_type} K 线数据",
        )
    return result


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
