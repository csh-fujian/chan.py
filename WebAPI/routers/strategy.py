# -*- coding: utf-8 -*-
"""
Strategy 路由 — 策略信号页 API（strategy-signal-page 任务 3.1）。

- GET  /api/strategy/definitions：定义树（params_schema/states/columns 声明
  驱动前端渲染，design D5）+ 实例节点（含信号计数）
- POST /api/strategy/instances：创建实例（params 校验失败 422）+ 触发全量
  回算（BackgroundTasks 异步，design D2「建实例即全量回算」）
- PATCH /api/strategy/instances/{id}/enabled：启停（实例不可变：无参数修改入口）
- DELETE /api/strategy/instances/{id}：删除（级联删信号）
- POST /api/strategy/instances/{id}/scan：手动补算（BackgroundTasks，幂等）
- GET  /api/strategy/signals：分页筛选（PageRes 契约 {list,total,page,page_size}，
  行含 stock 名称/行业/方向/payload）

风格对齐 routers/bsp.py（_check_date_param 校验、PageRes 契约、行业按页批量）。
"""

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from ..bsp_store import get_industries_for_codes
from ..strategy_engines.scheduler import scan_instance
from ..strategy_store import (
    create_instance,
    delete_instance,
    get_definitions_with_instances,
    get_instance,
    query_signals,
    set_enabled,
)

log = logging.getLogger("strategy_router")

router = APIRouter(prefix="/api/strategy", tags=["strategy"])


def _check_date_param(value: str, name: str) -> str:
    """日期查询参数校验（YYYY-MM-DD），非法 → 422（风格同 routers/bsp.py）。"""
    if not value:
        return value
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{name} 需为 YYYY-MM-DD 日期")
    return value


@router.get("/definitions")
async def strategy_definitions():
    """策略定义树（定义分组 → 实例节点 + 信号计数，侧栏数据源）。

    响应：[{id,name,group_name,sort,params_schema,states,columns,
    instances:[{id,label,params,enabled,signal_count}]}]
    """
    return get_definitions_with_instances()


@router.post("/instances")
async def strategy_create_instance(body: dict, background: BackgroundTasks):
    """创建参数实例（design D2：不可变 + 建实例即全量回算）。

    - params 按 params_schema 校验（非法 → 422，spec「参数非法被拒绝」）
    - 全量回算走 BackgroundTasks 异步（扫 DuckDB 全历史，数据量可能较大，
      立即返回创建结果，回算在响应后执行；幂等可重入）
    """
    strategy_id = body.get("strategy_id", "")
    label = body.get("label", "")
    params = body.get("params", {})

    if not strategy_id or not isinstance(strategy_id, str):
        raise HTTPException(status_code=422, detail="strategy_id is required")
    if not label or not isinstance(label, str) or not label.strip():
        raise HTTPException(status_code=422, detail="label 不能为空")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise HTTPException(status_code=422, detail="params 必须为对象（键值对）")

    try:
        instance = create_instance(strategy_id, label, params)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    # 全量回算（水位为 None → 引擎扫全史，design D2；失败不影响实例创建结果）
    async def _run_full_scan():
        try:
            await asyncio.to_thread(scan_instance, instance["id"])
        except Exception:
            log.exception("实例全量回算失败 instance=%s", instance["id"])

    background.add_task(_run_full_scan)
    return instance


@router.patch("/instances/{instance_id}/enabled")
async def strategy_set_instance_enabled(instance_id: int, body: dict):
    """启用/停用实例（停用不参与调度，已产生信号仍可查询）。"""
    if not isinstance(body.get("enabled"), bool):
        raise HTTPException(status_code=422, detail="enabled 需为布尔值")
    if get_instance(instance_id) is None:
        raise HTTPException(status_code=404, detail=f"实例 {instance_id} 不存在")
    ok = set_enabled(instance_id, body["enabled"])
    if not ok:
        raise HTTPException(status_code=500, detail="启用状态更新失败")
    return {"success": True}


@router.delete("/instances/{instance_id}")
async def strategy_delete_instance(instance_id: int):
    """删除实例（级联删除其信号与扫描游标，spec「删除后其信号不可再查询」）。"""
    if get_instance(instance_id) is None:
        raise HTTPException(status_code=404, detail=f"实例 {instance_id} 不存在")
    ok = delete_instance(instance_id)
    if not ok:
        raise HTTPException(status_code=500, detail="实例删除失败")
    return {"success": True}


@router.post("/instances/{instance_id}/scan")
async def strategy_scan(instance_id: int, background: BackgroundTasks):
    """手动触发补算（BackgroundTasks 异步；从当前水位续扫，幂等可重入）。"""
    if get_instance(instance_id) is None:
        raise HTTPException(status_code=404, detail=f"实例 {instance_id} 不存在")

    async def _run():
        try:
            await asyncio.to_thread(scan_instance, instance_id)
        except Exception:
            log.exception("实例补算失败 instance=%s", instance_id)

    background.add_task(_run)
    return {"success": True, "message": f"实例 {instance_id} 补算已提交后台执行"}


@router.get("/signals")
async def strategy_signals(
    instance_id: int = Query(..., description="策略实例 id"),
    page: int = Query(1),
    page_size: int = Query(20),
    state: str = Query(""),
    direction: str = Query(""),
    date_from: str = Query(""),
    date_to: str = Query(""),
    keyword: str = Query(""),
):
    """信号列表（分页 + 筛选，spec「筛选与分页」）。

    响应契约 PageRes：{list, total, page, page_size}；行字段
    {code,name,industries,signal_date(YYYY-MM-DD),state,is_buy→direction,
    entry_ref_price,stop_ref_price,payload}。行业按页批量单条 SQL（对齐 bsp 路由）。
    """
    _check_date_param(date_from, "date_from")
    _check_date_param(date_to, "date_to")

    if get_instance(instance_id) is None:
        raise HTTPException(status_code=404, detail=f"实例 {instance_id} 不存在")

    result = query_signals(
        instance_id=instance_id,
        state=state if state else "",
        direction=direction if direction else "",
        date_from=date_from if date_from else "",
        date_to=date_to if date_to else "",
        keyword=keyword if keyword else "",
        page=page,
        page_size=page_size,
    )

    # 行业（rank≤3）按页批量单条 SQL（替代 N+1）
    industries_map = get_industries_for_codes([i["code"] for i in result["items"]])

    records = []
    for it in result["items"]:
        records.append({
            "id": it["id"],
            "code": it["code"],
            "name": it["name"],
            "industries": industries_map.get(it["code"], []),
            "signal_date": it["signal_date"],
            "state": it["state"],
            "is_buy": it["is_buy"],
            "direction": "buy" if it["is_buy"] else "sell",
            "entry_ref_price": it["entry_ref_price"],
            "stop_ref_price": it["stop_ref_price"],
            "payload": it["payload"],
            "frozen": it["frozen"],
        })

    return {
        "list": records,
        "total": result["total"],
        "page": result["page"],
        "page_size": result["page_size"],
    }
