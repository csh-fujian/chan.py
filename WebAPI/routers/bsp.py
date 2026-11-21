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
    resolve_bsp_type,
    ENTRY_PSEUDO_TYPES,
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


def _grade_of(it: dict):
    """列表行的用户可读分级（chan-bsp-grading）。

    落库只存稳定的 `grade_score` / `grade_qual`（文案会随版本调整，落库会让
    存量行与新文案并存），这里按**当前** `bsp_grade` 口径重新拼出完整结构：
    分数与定性直接用库里存的值（那是对该时点判据的忠实记录），
    `advice` / `blocked_by` 用当前措辞现算。

    `grade_score` 为 NULL = 本变更前的存量行，前端按「未评估」处理（回 None），
    而不是拿 ladder 猜一个分数 —— 存量行的 feature 已缺失，猜出来的分数是假的。
    """
    score = it.get("grade_score")
    if score is None:
        return None
    from ..bsp_grade import BLOCKED_UNKNOWN, grade_bsp, grade_for_score

    is_buy = bool(it.get("is_buy"))
    is_sure = bool(it.get("is_sure"))
    ladder = it.get("ladder")
    # 存量行的 `bsp1_standard_reason` 不在 bsp_index 里，无法还原「卡在哪」。
    # 已知的只有库里存的分数本身：据此反推它当初是「判据被卡住」还是
    # 「判据全过只欠确认」—— 分数 >= 60 说明当初走完了整条判据链，
    # 只是缺最后的结构确认。
    score = int(score)
    blocked_reason = None if (is_sure or score >= 60) else BLOCKED_UNKNOWN
    g = grade_bsp(ladder, is_buy=is_buy, is_sure=is_sure,
                  blocked_reason=blocked_reason)
    # 用库里存的分数覆盖现算值：判据是当时算的，分数应忠实于当时的结果。
    # 定性/建议必须跟着分数一起重算，否则 20 分会显示成「一般」。
    # 已确认行例外：`grade_bsp` 早返回的「已确认成立」比通用档位措辞更准。
    g["score"] = score
    if it.get("grade_qual"):
        g["grade"] = it["grade_qual"]
        if not g["confirmed"]:
            g["advice"] = grade_for_score(score, is_buy)[1]
    if not is_sure and blocked_reason == BLOCKED_UNKNOWN:
        # bsp_index 只存 ladder/分数，不存短路原因，说不出具体是哪一项没过。
        # 与其笼统地讲「无法判断」，不如告诉用户去哪儿看得到明细。
        g["blocked_by"] = "判据明细不在列表数据里，展开 K 线页可看具体卡在哪一步"
    return g


def _record_id(it: dict) -> str:
    """稳定的记录标识（bsp-page-level-filter-and-batch-monitor D4）。

    bsp_index 无自增主键，原 `(page-1)*page_size+idx+1` 行号占位会随查询条件
    与页码重复，导致前端 `row-key` + reserve-selection 在切换筛选后把「已选」
    落到另一批记录上（批量提交会写错股票）。故改为由记录自身业务字段拼成的
    复合键，字段集与表的 UNIQUE 约束同构，保证唯一且可跨查询复现。
    """
    return "|".join(
        [
            it["code"],
            it["kl_type"],
            it["autype"],
            it["bsp_date"],
            it["bsp_type"],
            "B" if it["is_buy"] else "S",
            it["time_key"],
        ]
    )


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
    sure: str = Query(""),
    ladder: str = Query(""),
):
    """买卖点列表（分页 + 筛选；date_from/date_to 为 YYYY-MM-DD 日期范围，
    双端齐备按闭区间 [date_from, date_to] 匹配，只传一端单边过滤，双空不过滤）。

    sure（bsp-sure-annotation D3）：确认状态过滤，取值 confirmed（只看已确认）/
    preview（只看未确认）；缺省不过滤；非法取值返回 400（三态字符串与
    direction 同风格，缺省语义显式无歧义）。

    ladder（bsp-page-level-filter-and-batch-monitor D1）：确认阶梯级别过滤，
    取值 L1/L2/L3/L4；缺省不过滤（无「未定级」桶——存量行按 is_sure 兜底后
    必为 L4 或 L2）。过滤下推同一 WHERE，与列表「级别」列回显同口径。

    响应契约 PageRes<BspRecord>：{list, total, page, page_size}，每行携带
    is_sure（记录确认状态，spec「记录携带确认状态」）；id 为由记录自身字段
    拼成的稳定复合键（spec「记录标识稳定」），非行号占位。
    """
    _check_date_param(date_from, "date_from")
    _check_date_param(date_to, "date_to")

    is_buy = None
    if direction == "buy":
        is_buy = True
    elif direction == "sell":
        is_buy = False

    # 确认状态三态解析（D3）
    # 注：直调（非 HTTP 层，如 Debug/bsp_engine_regression.py T7.4）缺省参数
    # 拿到的是 Query 实例而非 str —— 非 str 视同缺省，不误入 400 分支。
    is_sure: Optional[bool] = None
    if sure == "confirmed":
        is_sure = True
    elif sure == "preview":
        is_sure = False
    elif isinstance(sure, str) and sure != "":
        raise HTTPException(status_code=400, detail="sure 需为 confirmed 或 preview")

    # 过滤下推（2.3/2.6）：keyword/kl_type/bsp_type/direction/date_from~date_to
    # 同一 WHERE，COUNT 与分页共用，total = 过滤后总数；无命中 list=[] 且 total=0
    # bsp_type 支持方向化标签（2B/3S/PZ-B...，design D11）与原始枚举直传，
    # 以及介入点伪类型（entry/entry1/entry2/entry3，chan-entry-point-candidate
    # 4.3：翻译为 entry_point=TRUE + 家族类型约束，方向由行自身 is_buy 承载）
    bsp_types, label_is_buy = resolve_bsp_type(bsp_type) if bsp_type else ([], None)
    if label_is_buy is not None:
        is_buy = label_is_buy  # 标签自带方向语义，覆盖 direction 参数
    entry_only = bool(bsp_type) and bsp_type in ENTRY_PSEUDO_TYPES

    result = query_bsp(
        kl_type=kl_type if kl_type else "",
        date_from=date_from if date_from else "",
        date_to=date_to if date_to else "",
        bsp_types=bsp_types,
        is_buy=is_buy,
        keyword=keyword if keyword else "",
        page=page,
        page_size=page_size,
        is_sure=is_sure,
        ladder=ladder if ladder else "",
        entry_only=entry_only,
    )

    items = result["items"]

    # 行业（rank≤3）按页批量单条 SQL（替代 N+1）
    industries_map = get_industries_for_codes([i["code"] for i in items])

    # 现价/涨跌幅按页批量取 DuckDB 最新两根 K 线；失败降级 0（列表照常渲染）
    price_map = fetch_current_prices([(i["code"], i["kl_type"]) for i in items])

    records = []
    for it in items:
        current_price, change_pct = price_map.get((it["code"], it["kl_type"]), (0.0, 0.0))
        records.append({
            "id": _record_id(it),  # 稳定复合键（D4，替代行号占位）
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
            "is_sure": it["is_sure"],
            "ladder": it.get("ladder"),
            # 用户可读分级（chan-bsp-grading）：落库只有稳定的 score/qual，
            # 文案在这里按当前口径现算，保证存量行也能拿到最新措辞。
            "grade": _grade_of(it),
            # 介入点候选（chan-entry-point-candidate 4.3）：类型化合成的数据源
            "entry_point": it.get("entry_point", False),
            "entry_method": it.get("entry_method"),
            "entry_level": it.get("entry_level"),
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
