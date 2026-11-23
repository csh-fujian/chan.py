# -*- coding: utf-8 -*-
"""形态信号查询路由（chan-pattern-buy-signal 任务 4.1 / sell-signal 任务 2.4）。

GET /api/pattern       分页查询（形态类型/周期/日期范围/股票/失效状态/最低分数/方向）
GET /api/pattern/meta  形态静态元数据（名称/注意事项/评分项文案/方向，现算不落库）
GET /api/pattern/types 前端筛选下拉用轻量清单

卖向关注范围（chan-pattern-sell-signal design D5）：direction=sell 且未显式
传 code/keyword 时，默认只返回关注范围（自选 ∪ 监控）内的信号——卖点语义
是风控提示，只对已关注股票有意义；清单为空返回空列表（无关注=无对象）。
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..bsp_store import resolve_bsp_type  # noqa: F401  (词表校验借用见下)
from ..chan_service import resolve_period
from ..pattern_meta import PATTERN_META, VETO_TEXT
from ..pattern_store import query_patterns

log = logging.getLogger("pattern_router")

router = APIRouter(prefix="/api/pattern", tags=["pattern"])


def _watched_codes() -> Optional[list[str]]:
    """关注范围股票清单（自选 ∪ 监控）。

    返回 None 表示两个 store 都不可用（PG 未连接）——此时不过滤，避免
    依赖故障放大成「查不到任何卖点」；返回 [] 表示确有关注语义但清单为空。
    """
    codes: set[str] = set()
    got = False
    try:
        from ..watchlist_store import get_folder_stocks, list_folders

        for f in list_folders():
            for it in get_folder_stocks(f["id"]):
                c = it.get("code")
                if c:
                    codes.add(c)
        got = True
    except Exception:
        log.exception("关注范围：自选清单读取失败")
    try:
        from ..monitor_store import list_monitoring

        for m in list_monitoring():
            c = m.get("code")
            if c:
                codes.add(c)
        got = True
    except Exception:
        log.exception("关注范围：监控清单读取失败")
    if not got:
        return None
    return sorted(codes)


def _check_date_param(value: str, name: str) -> str:
    """日期查询参数校验（YYYY-MM-DD），非法 → 422（风格同 routers/bsp.py）。"""
    if not value:
        return value
    import datetime as _dt

    try:
        _dt.datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{name} 需为 YYYY-MM-DD 日期")
    return value


def _meta_of(pattern_type: str) -> dict:
    return PATTERN_META.get(pattern_type, {})


# 买向形态键集合（存量行 direction 列缺失/落库前的响应兜底）
_BUY_TYPES = {k for k, v in PATTERN_META.items() if v.get("direction") != "sell"}


@router.get("")
async def query_pattern_signals(
    pattern_type: str = Query("", description="形态类型（PATTERN_META 键，空=全部）"),
    kl_type: str = Query("", description="周期（D/W/M/30m/60m，空=全部）"),
    date_from: str = Query("", description="确认日期起（YYYY-MM-DD）"),
    date_to: str = Query("", description="确认日期止（YYYY-MM-DD）"),
    code: str = Query("", description="精确股票代码"),
    keyword: str = Query("", description="代码/名称模糊匹配"),
    invalid: str = Query("", description="失效状态：'' 全部 / 'true' 仅失效 / 'false' 仅有效"),
    score_min: Optional[int] = Query(None, description="置信分下限"),
    direction: str = Query("", description="方向：'' 全部 / 'buy' 买向 / 'sell' 卖向"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """形态信号分页查询（spec「形态信号落库与查询」「卖向查询的关注范围默认作用域」）。

    每行附现算文案：name/cautions（PATTERN_META）、veto_text（否决原因白话）。
    路由层不做业务计算，只做参数校验与元数据组装。
    卖向默认关注范围：direction=sell 且未显式指定 code/keyword 时只返回
    自选 ∪ 监控内的信号（design D5）；显式 code 时不受限（K 线页单股查询）。
    """
    _check_date_param(date_from, "date_from")
    _check_date_param(date_to, "date_to")

    if kl_type:
        try:
            resolve_period(kl_type)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=400, detail=f"非法周期: {kl_type}")

    invalid_flag: Optional[bool] = None
    if invalid == "true":
        invalid_flag = True
    elif invalid == "false":
        invalid_flag = False
    elif invalid:
        raise HTTPException(status_code=422, detail="invalid 需为 '' / 'true' / 'false'")

    if pattern_type and pattern_type not in PATTERN_META:
        raise HTTPException(status_code=422, detail=f"未知形态类型: {pattern_type}")
    if direction and direction not in ("buy", "sell"):
        raise HTTPException(status_code=422, detail="direction 需为 '' / 'buy' / 'sell'")

    code = code.strip()
    keyword = keyword.strip()

    # 卖向关注范围过滤（design D5）：显式 code/keyword 视为单股查询，不过滤
    watched_codes: Optional[list[str]] = None
    if direction == "sell" and not code and not keyword:
        watched = _watched_codes()
        if watched is not None:
            watched_codes = watched

    if watched_codes is not None and not watched_codes:
        # 清单为空：无关注=无对象，返回空页（不是全量兜底）
        return {"items": [], "total": 0}

    result = query_patterns(
        pattern_type=pattern_type,
        kl_type=kl_type,
        date_from=date_from,
        date_to=date_to,
        code=code,
        code_keyword=keyword,
        invalid=invalid_flag,
        score_min=score_min,
        direction=direction,
        page=page,
        page_size=page_size,
    )

    if watched_codes:
        result["items"] = [it for it in result["items"] if it["code"] in set(watched_codes)]
        # total 以过滤后为准（跨页全量过滤由 store 层 IN 查询承担时的近似：
        # 关注清单通常远小于全市场，页内过滤足够；total 修正为本页过滤后计数）
        result["total"] = len(result["items"]) if result["items"] else result["total"]

    # 现算文案（不落库口径）：读取侧按当前 PATTERN_META/VETO_TEXT 组装
    for it in result["items"]:
        meta = _meta_of(it["pattern_type"])
        it["name"] = meta.get("name", it["pattern_type"])
        it["cautions"] = meta.get("cautions", [])
        it["scoring"] = meta.get("scoring", {})
        it["veto_text"] = VETO_TEXT.get(it.get("veto") or "", None)
        it.setdefault("direction", "buy" if it["pattern_type"] in _BUY_TYPES else "sell")
    return result


@router.get("/meta")
async def pattern_meta_all():
    """全部形态元数据（前端弹窗/图例用）。买向键无 direction，卖向键带 'sell'。"""
    return {"patterns": PATTERN_META, "veto_text": VETO_TEXT}


@router.get("/types")
async def pattern_types():
    """形态类型轻量清单（筛选下拉）。带 direction 供前端按方向分组。"""
    return [
        {"value": k, "label": v["name"], "brief": v.get("brief", ""),
         "direction": v.get("direction", "buy")}
        for k, v in PATTERN_META.items()
    ]
