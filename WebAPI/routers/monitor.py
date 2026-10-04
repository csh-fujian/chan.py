# -*- coding: utf-8 -*-
"""
Monitor 路由 — 交易监控 API。
"""

import re
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from ..llm_client import LLMError, complete
from ..llm_prompts import ATTRIBUTION_SYSTEM_PROMPT, build_attribution_prompt
from ..llm_store import resolve_llm_config
from ..monitor_store import (
    create_group,
    create_monitor,
    delete_group,
    end_monitor,
    get_aggregate_profit_series,
    get_attribution,
    get_group,
    get_monitor,
    get_profit_series,
    list_completed,
    list_groups,
    list_monitoring,
    list_monitor_sources,
    rename_group,
    reorder_groups,
    save_attribution,
    settle_monitor,
)

router = APIRouter(prefix="/api/monitor", tags=["monitor"])

# 分组过滤哨兵（design D3）：query 参数 group_id 只接受正整数字符串或字面 "ungrouped"
_GROUP_ID_PATTERN = re.compile(r"^(ungrouped|[1-9]\d*)$")


def _parse_group_id_param(raw: str) -> str:
    """校验 group_id query 参数：返回 "ungrouped" 或正整数字符串，非法值抛 422。"""
    if not _GROUP_ID_PATTERN.match(raw):
        raise HTTPException(
            status_code=422,
            detail="group_id 仅接受正整数或字面 'ungrouped'（未分组）",
        )
    return raw


def _llm_error_to_http(e: LLMError) -> HTTPException:
    """LLM 调用失败 → HTTP 异常：错误透传，保留上游 4xx/5xx 语义。

    上游 401/403 归 502（属于供应商密钥/权限问题，非本服务会话问题——
    若透传 401 会被前端误判为登录过期强制登出）；其余 4xx 原样透传；
    5xx / 网络失败 / 响应解析失败 → 502。
    """
    status = 502
    m = re.search(r"LLM 返回 HTTP (\d+)", str(e))
    if m:
        upstream = int(m.group(1))
        if 400 <= upstream <= 499 and upstream not in (401, 403):
            status = upstream
    return HTTPException(status_code=status, detail=f"LLM 调用失败: {e}")


def _parse_reason_type(text: str) -> str:
    """从归因输出解析归因类别（计算逻辑错误 / 缠论失效），解析不出时回退 LLM归因。"""
    m = re.search(r"【归因类别】\s*([^\n\r]*)", text)
    category = m.group(1) if m else text[:200]
    if "计算逻辑" in category:
        return "计算逻辑错误"
    if "缠论" in category:
        return "缠论失效"
    return "LLM归因"


@router.get("")
async def monitor_list(keyword: str = Query(""), group_id: str = Query("")):
    """监控列表（status='monitoring'），group_id 支持正整数或字面 'ungrouped'。"""
    parsed = _parse_group_id_param(group_id) if group_id else None
    return list_monitoring(keyword=keyword, group_id=parsed)


@router.get("/completed")
async def monitor_completed(keyword: str = Query(""), group_id: str = Query("")):
    """监控完成列表，group_id 支持正整数或字面 'ungrouped'。"""
    parsed = _parse_group_id_param(group_id) if group_id else None
    return list_completed(keyword=keyword, group_id=parsed)


@router.get("/sources")
async def monitor_sources():
    """来源字典（design D14）：distinct (source_type, instance_id) + 实例名，前端来源下拉消费。"""
    return list_monitor_sources()


@router.get("/profit-series")
async def monitor_aggregate_profit_series():
    """聚合盈利走势时序（所有已完成监控汇总）。"""
    return get_aggregate_profit_series()


@router.post("")
async def monitor_create(body: dict):
    """加入监控（可选携带 group_id，不传归「未分组」）。

    策略信号来源（strategy-signal-page design D6）：body 可选携带
    source_type/instance_id/signal_date；缺省 'chan'（既有调用不传，行为不变）。
    source_type='strategy' 时 instance_id 与 signal_date 必填（422）。
    source_type='watchlist'（watchlist-page-change design D8）：自选页人工
    挑选来源，直接放行透传；非法值 422（store 层另有兜底 'chan'）。
    """
    code = body.get("code", "")
    kl_type = body.get("kl_type", "K_DAY")
    entry_price = body.get("entry_price", 0)
    monitor_start_time = body.get("monitor_start_time", "")
    group_id = body.get("group_id", None)
    source_type = body.get("source_type", "chan")
    instance_id = body.get("instance_id", None)
    signal_date = body.get("signal_date", None)

    if not code:
        raise HTTPException(status_code=422, detail="code is required")
    if not entry_price:
        raise HTTPException(status_code=422, detail="entry_price is required")
    if group_id is not None:
        if not isinstance(group_id, int) or isinstance(group_id, bool) or group_id <= 0:
            raise HTTPException(status_code=422, detail="group_id must be a positive integer")
        if get_group(group_id) is None:
            raise HTTPException(status_code=400, detail=f"分组 {group_id} 不存在")

    # 来源字段校验（strategy-signal-downstream spec「策略信号加监控」）；
    # 'watchlist' 放行（watchlist-page-change design D8：自选来源第三取值，
    # 无附带字段；非法值 422，store 层兜底 'chan'）
    if source_type not in ("chan", "strategy", "watchlist"):
        raise HTTPException(status_code=422, detail="source_type 仅接受 'chan'、'strategy' 或 'watchlist'")
    if source_type == "strategy":
        if not isinstance(instance_id, int) or isinstance(instance_id, bool) or instance_id <= 0:
            raise HTTPException(status_code=422, detail="strategy 来源必须携带正整数 instance_id")
        if not signal_date or not isinstance(signal_date, str):
            raise HTTPException(status_code=422, detail="strategy 来源必须携带 signal_date（YYYY-MM-DD）")
        try:
            datetime.strptime(signal_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=422, detail="signal_date 需为 YYYY-MM-DD 日期")
        # 实例存在性校验（404 语义与分组不存在一致按 400/404 区分：实例不存在 404）
        from ..strategy_store import get_instance

        if get_instance(instance_id) is None:
            raise HTTPException(status_code=404, detail=f"策略实例 {instance_id} 不存在")

    result = create_monitor(
        code=code,
        kl_type=kl_type,
        entry_price=entry_price,
        monitor_start_time=monitor_start_time,
        group_id=group_id,
        source_type=source_type,
        instance_id=instance_id,
        signal_date=signal_date,
    )
    if not result:
        raise HTTPException(status_code=500, detail="Failed to create monitor")
    return result


# ---- 分组管理（monitor-group-change design D2，对齐 watchlist 路由风格）----


@router.get("/groups")
async def monitor_groups():
    """监控分组列表（含每组 monitoring/completed 记录计数）。"""
    return list_groups()


@router.post("/groups")
async def monitor_create_group(body: dict):
    """新建分组（空名/重名返回 400，sort_order 追加到末尾）。"""
    name = body.get("name", "")
    if not isinstance(name, str) or not name.strip():
        raise HTTPException(status_code=400, detail="分组名称不能为空")
    result = create_group(name)
    if result is None:
        raise HTTPException(status_code=400, detail=f"分组名称「{name.strip()}」已存在")
    return result


@router.put("/groups/reorder")
async def monitor_reorder_groups(body: dict):
    """分组拖拽排序：body {"ids": [3, 1, 2]}，按下标全量覆盖 sort_order。"""
    ids = body.get("ids", None)
    if ids is None:
        raise HTTPException(status_code=422, detail="ids is required")
    if not isinstance(ids, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        raise HTTPException(status_code=422, detail="ids must be a list of group ids")
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=422, detail="ids must not contain duplicates")
    ok = reorder_groups(ids)
    if not ok:
        raise HTTPException(status_code=404, detail="Some groups in ids not found")
    return {"success": True}


@router.patch("/groups/{group_id}")
async def monitor_rename_group(group_id: int, body: dict):
    """重命名分组（空名/重名 400，不存在 404）。"""
    name = body.get("name", "")
    if not isinstance(name, str) or not name.strip():
        raise HTTPException(status_code=400, detail="分组名称不能为空")
    ok = rename_group(group_id, name)
    if not ok:
        # 名称查重失败（合法名但撞名）与分组不存在需区分：先确认分组存在
        if get_group(group_id) is None:
            raise HTTPException(status_code=404, detail=f"分组 {group_id} 不存在")
        raise HTTPException(status_code=400, detail=f"分组名称「{name.strip()}」已存在")
    return {"success": True}


@router.delete("/groups/{group_id}")
async def monitor_delete_group(group_id: int):
    """删除分组（组内监控记录归「未分组」，不删除记录）。"""
    ok = delete_group(group_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"分组 {group_id} 不存在")
    return {"success": True}


@router.post("/{monitor_id}/end")
async def monitor_end(monitor_id: int, body: dict | None = None):
    """手动结束监控（可选传入 sold_price/sold_at/pnl_pct）。"""
    if body and body.get("sold_price"):
        result = settle_monitor(
            monitor_id,
            sold_price=body.get("sold_price", 0),
            sold_at=body.get("sold_at", ""),
            pnl_pct=body.get("pnl_pct", 0),
        )
    else:
        result = end_monitor(monitor_id)

    if not result:
        raise HTTPException(status_code=404, detail=f"Monitor {monitor_id} not found")
    return result


@router.get("/{monitor_id}")
async def monitor_detail(monitor_id: int):
    """监控详情。"""
    result = get_monitor(monitor_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Monitor {monitor_id} not found")
    return result


@router.post("/{monitor_id}/analyze")
async def monitor_analyze(monitor_id: int):
    """大模型归因分析（design D5/U5：真实生成、失败显式报错且不落库）。

    - 标的最终盈利 >= 5% → 400「仅分析盈利低于 5% 的标的」
    - LLM 未配置 → 400「LLM 未配置」
    - 供应商调用失败 → 错误透传（4xx/5xx 语义保留），不写任何占位归因记录
    - 成功才经 save_attribution 持久化
    """
    monitor = get_monitor(monitor_id)
    if not monitor:
        raise HTTPException(status_code=404, detail=f"Monitor {monitor_id} not found")

    pnl_pct = monitor.get("pnl_pct")
    if pnl_pct is None or float(pnl_pct) >= 5:
        raise HTTPException(status_code=400, detail="仅分析盈利低于 5% 的标的")

    llm_cfg = resolve_llm_config()
    if llm_cfg is None:
        raise HTTPException(status_code=400, detail="LLM 未配置")

    prompt = build_attribution_prompt(monitor)
    try:
        text = complete(
            ATTRIBUTION_SYSTEM_PROMPT,
            prompt,
            llm_cfg.get("timeout", 60.0),
            config=llm_cfg,
        )
    except LLMError as e:
        # 调用失败：不写任何占位归因记录
        raise _llm_error_to_http(e) from e

    if not text:
        raise HTTPException(status_code=502, detail="LLM 返回空归因结果")

    save_attribution(monitor_id, _parse_reason_type(text), text)
    return {"success": True, "id": monitor_id, "attribution": get_attribution(monitor_id)}


@router.get("/{monitor_id}/profit-series")
async def monitor_profit_series(monitor_id: int):
    """监控盈利走势时序。"""
    return get_profit_series(monitor_id)


@router.get("/{monitor_id}/attribution")
async def monitor_attribution(monitor_id: int):
    """监控归因列表。"""
    return get_attribution(monitor_id)