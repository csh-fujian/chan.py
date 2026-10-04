# -*- coding: utf-8 -*-
"""
Performance 路由 — 买卖点绩效统计 API（performance-page-change design D1/D2）。

统计口径 A：样本 = monitor 表 status='completed' 结算记录；聚合在
performance_store 完成（复用 monitor_store.list_completed 的上下文回查链路），
本路由只做参数解析与调用。source/instance_id 参数兑现 strategy-signal-page
design D7 预留契约（chan / strategy+实例精确匹配 / watchlist）。

PG 不可用时 list_completed 返回 []，接口自然降级空集。

group_id 参数（design D9）：校验语义与 monitor 路由 D3 完全一致——正整数或
字面 'ungrouped'（未分组哨兵），非法 422。monitor.py 的 _parse_group_id_param
是模块级私有名，跨模块导入私有名不优雅，此处本地复制同款实现（正则与报错
文案同源，语义对齐 monitor-group-change design D3）。
"""

import re

from fastapi import APIRouter, HTTPException, Query

from ..performance_store import get_performance_samples, get_performance_stats

router = APIRouter(prefix="/api/performance", tags=["performance"])

# 分组过滤哨兵（与 routers/monitor.py D3 同款）：group_id 只接受正整数字符串
# 或字面 "ungrouped"
_GROUP_ID_PATTERN = re.compile(r"^(ungrouped|[1-9]\d*)$")


def _parse_group_id_param(raw: str) -> str:
    """校验 group_id query 参数：返回 "ungrouped" 或正整数字符串，非法值抛 422。"""
    if not _GROUP_ID_PATTERN.match(raw):
        raise HTTPException(
            status_code=422,
            detail="group_id 仅接受正整数或字面 'ungrouped'（未分组）",
        )
    return raw


@router.get("/stats")
async def performance_stats(
    source: str = Query("", description="信号来源过滤（chan/strategy/watchlist）"),
    instance_id: int = Query(0, description="策略实例 id 过滤（>0 时与 source='strategy' 联合精确匹配）"),
    group_id: str = Query("", description="监控分组过滤：正整数或字面 'ungrouped'（未分组）"),
):
    """买卖点绩效统计：completed 样本按 (bsp_type, kl_type) 分组聚合。

    返回 [{bsp_type, kl_type, samples, win_rate, avg_pnl, profit_ratio, expectancy}]，
    按 samples 降序；bsp_type 为原始枚举原样分组（如 '2s'/'2'，前端负责文案映射）。
    """
    parsed_group_id = _parse_group_id_param(group_id) if group_id else None
    return get_performance_stats(
        source=source,
        instance_id=instance_id,
        group_id=parsed_group_id,
    )


@router.get("/samples")
async def performance_samples(
    bsp_type: str = Query("", description="买卖点类型过滤（精确匹配）"),
    kl_type: str = Query("", description="K 线周期过滤（精确匹配）"),
    source: str = Query("", description="信号来源过滤（chan/strategy/watchlist）"),
    instance_id: int = Query(0, description="策略实例 id 过滤（>0 时与 source='strategy' 联合精确匹配）"),
    group_id: str = Query("", description="监控分组过滤：正整数或字面 'ungrouped'（未分组）"),
):
    """绩效样本明细：completed 结算样本行（对齐前端 PerformanceSample 契约）。

    含 code/name/bsp_type/kl_type/source_type/strategy_label/direction/
    bsp_date/end_date/hold_days/bsp_price/end_price/profit/attribution
    （归因摘要为 evidence 按时间序 '\\n' 连接，未归因为空串）。
    """
    parsed_group_id = _parse_group_id_param(group_id) if group_id else None
    return get_performance_samples(
        bsp_type=bsp_type,
        kl_type=kl_type,
        source=source,
        instance_id=instance_id,
        group_id=parsed_group_id,
    )
