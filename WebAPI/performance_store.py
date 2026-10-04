# -*- coding: utf-8 -*-
"""
Performance store — 买卖点绩效聚合（performance-page-change design D1/D2）。

统计口径 A：样本 = monitor 表 status='completed' 记录（list_completed 已回查
bsp_type / bsp_date / strategy_label 等上下文并完成字段映射）；聚合按
(bsp_type, kl_type) 分组，输出样本数/胜率/平均盈亏/盈亏比/期望值。

- bsp_type 原样聚合分组（原始枚举如 '2s'/'2'，前端负责映射文案，后端不改写）
- source 过滤：'chan'/'strategy'/'watchlist' 精确匹配 source_type；
  instance_id > 0 时与 source='strategy' 联合精确匹配
- 归因摘要：list_attributions_map 一次拉全表，按 monitor_id 拼接（任务 3.3）
- PG 不可用时 list_completed 返回 []，自然降级空集
- group_id 过滤（design D9）：直接下推 list_completed 的 SQL WHERE
  （_group_filter_condition，'ungrouped' → IS NULL，正整数 → = N），与
  monitor 路由 /completed 完全同源——list_completed 的 SELECT 列表不含
  group_id 列，行字段比对方案不成立，无需补列
"""

import logging
from typing import Any

from .monitor_store import list_attributions_map, list_completed

log = logging.getLogger("performance_store")

# 样本不足提示阈值（spec「样本不足提示」：样本数 < 5 统计意义有限，标记由前端渲染，
# 后端不裁剪数据、不加标记字段——诚实呈现而非隐藏）
SAMPLE_INSUFFICIENT_THRESHOLD = 5


def _filter_completed(
    items: list[dict],
    source: str = "",
    instance_id: int = 0,
    bsp_type: str = "",
    kl_type: str = "",
) -> list[dict]:
    """按来源/实例/类型/周期过滤 completed 样本。

    - source：非空时精确匹配 source_type（chan/strategy/watchlist）
    - instance_id：> 0 时仅保留 source_type='strategy' 且 instance_id 相等的样本
    - bsp_type / kl_type：非空时精确匹配
    """
    result = items
    if source:
        result = [it for it in result if (it.get("source_type") or "chan") == source]
    if instance_id and instance_id > 0:
        result = [
            it
            for it in result
            if (it.get("source_type") or "chan") == "strategy"
            and it.get("instance_id") == instance_id
        ]
    if bsp_type:
        result = [it for it in result if it.get("bsp_type") == bsp_type]
    if kl_type:
        result = [it for it in result if it.get("kl_type") == kl_type]
    return result


def _aggregate_group(items: list[dict]) -> dict[str, Any]:
    """单 (bsp_type, kl_type) 分组聚合（design D1 口径）。

    - samples：样本数
    - win_rate：pnl_pct > 0 样本占比（百分数，1 位小数）
    - avg_pnl：pnl_pct 均值（2 位小数）
    - profit_ratio：平均盈利 / |平均亏损|（无亏损样本返回 0，2 位小数）
    - expectancy：胜率(小数)×平均盈利 − 败率×|平均亏损|（2 位小数）
    """
    pnls = [float(it.get("pnl_pct") or 0) for it in items]
    samples = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    win_count = len(wins)
    win_rate_dec = win_count / samples if samples else 0.0
    avg_pnl = sum(pnls) / samples if samples else 0.0
    avg_win = sum(wins) / win_count if win_count else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    profit_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0.0
    expectancy = win_rate_dec * avg_win - (1 - win_rate_dec) * avg_loss
    return {
        "samples": samples,
        "win_rate": round(win_rate_dec * 100, 1),
        "avg_pnl": round(avg_pnl, 2),
        "profit_ratio": round(profit_ratio, 2),
        "expectancy": round(expectancy, 2),
    }


def get_performance_stats(
    source: str = "",
    instance_id: int = 0,
    group_id: str | None = None,
) -> list[dict[str, Any]]:
    """绩效统计：completed 样本按 (bsp_type, kl_type) GROUP BY 聚合。

    返回 [{bsp_type, kl_type, samples, win_rate, avg_pnl, profit_ratio, expectancy}]，
    按 samples 降序（样本多的分组靠前，便于前端优先展示）。

    group_id：'ungrouped'（未分组）或正整数字符串，None 不过滤——下推
    list_completed SQL WHERE（语义同 monitor 路由 /completed）。
    """
    items = _filter_completed(
        list_completed(group_id=group_id),
        source=source,
        instance_id=instance_id,
    )
    groups: dict[tuple[str, str], list[dict]] = {}
    for it in items:
        key = (it.get("bsp_type") or "", it.get("kl_type") or "")
        groups.setdefault(key, []).append(it)

    rows = [
        {"bsp_type": bsp_type, "kl_type": kl_type, **_aggregate_group(group_items)}
        for (bsp_type, kl_type), group_items in groups.items()
    ]
    rows.sort(key=lambda r: r["samples"], reverse=True)
    return rows


def get_performance_samples(
    bsp_type: str = "",
    kl_type: str = "",
    source: str = "",
    instance_id: int = 0,
    group_id: str | None = None,
) -> list[dict[str, Any]]:
    """绩效样本明细：completed 样本行映射（对齐前端 PerformanceSample 契约）。

    - bsp_date：_fill_bsp_context 回查的买卖点时间（毫秒）优先，缺省回退
      monitor_start_time
    - end_date：sold_at 毫秒时间戳；hold_days：sold_at − bsp_date 天数（整数 ≥ 0）
    - attribution：归因 evidence 按时间序 '\n' 连接（任务 3.3，未归因为空串）
    - strategy_label：仅 strategy 来源携带（_fill_bsp_context 已填充），其余空串
    - group_id：'ungrouped'（未分组）或正整数字符串，None 不过滤——下推
      list_completed SQL WHERE（语义同 monitor 路由 /completed）
    """
    items = _filter_completed(
        list_completed(group_id=group_id),
        source=source,
        instance_id=instance_id,
        bsp_type=bsp_type,
        kl_type=kl_type,
    )
    attributions = list_attributions_map()

    DAY_MS = 86_400_000
    rows: list[dict[str, Any]] = []
    for it in items:
        bsp_date = it.get("bsp_date") or _to_ms_of(it.get("monitor_start_time"))
        end_date = it.get("end_date") or 0
        hold_days = max(0, int((end_date - bsp_date) / DAY_MS)) if end_date and bsp_date else 0
        rows.append(
            {
                "id": it.get("id"),
                "code": it.get("code"),
                "name": it.get("name") or it.get("code"),
                "bsp_type": it.get("bsp_type") or "",
                "kl_type": it.get("kl_type") or "",
                "source_type": it.get("source_type") or "chan",
                "strategy_label": it.get("strategy_label") or "",
                "direction": it.get("direction") or "buy",
                "bsp_date": bsp_date,
                "end_date": end_date,
                "hold_days": hold_days,
                "bsp_price": it.get("entry_price") or 0,
                "end_price": it.get("sold_price") or 0,
                "profit": it.get("pnl_pct") or 0,
                "attribution": "\n".join(attributions.get(it.get("id"), [])),
            }
        )
    return rows


def _to_ms_of(time_str: Any) -> int:
    """时间字符串 → 毫秒时间戳（复用 monitor_store._to_ms 语义，失败返回 0）。"""
    from .monitor_store import _to_ms

    if not time_str or not isinstance(time_str, str):
        return 0
    return _to_ms(time_str)
