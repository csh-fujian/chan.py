# -*- coding: utf-8 -*-
"""
Strategy 路由 — 策略任务页 API（strategy-task-redesign design D6 全集）。

- GET    /api/strategy/definitions：定义树（params_schema 含 desc、
  detail_schema 声明驱动前端渲染）+ 任务节点（含信号计数/进度）
- POST   /api/strategy/tasks：创建任务（范围三种来源解析快照 + params 校验）
- GET    /api/strategy/tasks：任务列表（strategy_id/user_group/status/mode
  过滤，任务信息 + 进度条数据）
- GET    /api/strategy/tasks/{id}：任务详情主体
- PATCH  /api/strategy/tasks/{id}：编辑（仅 paused；test 可改参数/范围，
  persistent 仅范围——参数冻结）
- DELETE /api/strategy/tasks/{id}：删除（级联删信号/逐股结果）
- POST   /api/strategy/tasks/{id}/start：启动（pending/paused → running，
  BackgroundTasks 异步扫描）
- POST   /api/strategy/tasks/{id}/pause：暂停（running → paused，执行器在
  code 边界停止）
- POST   /api/strategy/tasks/{id}/resume：续跑（仅 paused；body 带
  rerun: full|remaining，design D2 两种续跑语义）
- POST   /api/strategy/tasks/{id}/promote：转正（test done → persistent）
- POST   /api/strategy/tasks/{id}/copy：复制（继承参数与范围为 test 任务）
- GET    /api/strategy/tasks/{id}/detail：任务详情（task + summary +
  per_stock? + signals_page + kv_payload? + definition.detail_schema，
  design D5；kv_payload 为 vp-entry-strategy-integration D5 新增）
- GET    /api/strategy/signals：信号分页筛选（task_id 维度 + params_version
  透出，PageRes 契约 {list,total,page,page_size}）

实例相关端点全部删除（strategy_instance 废弃，BREAKING）。

风格对齐 routers/bsp.py（_check_date_param 校验、PageRes 契约、行业按页批量）。
"""

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from ..bsp_store import get_industries_for_codes
from ..stock_store import StockNameSourceUnavailable
from ..strategy_engines.scheduler import run_task
from ..strategy_store import (
    compute_outcome_kv_stats,
    compute_vp_entry_kv_stats,
    copy_task,
    count_stock_results,
    create_task,
    delete_task,
    get_definitions_with_tasks,
    get_signal_for_monitor,
    get_task,
    list_tasks,
    pause_task,
    promote_task,
    query_signals,
    query_stock_results,
    resolve_scope_codes,
    resume_task,
    set_task_status,
    start_task,
    update_task,
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


def _get_task_or_404(task_id: int) -> dict:
    """取任务行；不存在抛 404（路由层统一存在性校验）。"""
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    return task


def _run_task_background(task_id: int) -> None:
    """后台执行任务的包装（失败只记日志不影响响应，幂等可重入）。

    exclude-st-stocks：扫描开始前要先解析 code 集合，而该步骤需按名称排除
    ST（失败关闭）——PG 名称来源不可用时 `_task_codes` 抛
    `StockNameSourceUnavailable`，扫描一行都没跑。start_task/resume_task 已把
    状态置为 running，此处若不复位，任务会永久停在 running（阻塞暂停/删除/
    再次启动）。故捕获该异常后把任务复位为 paused（可续跑），而不是笼统吞掉。
    """
    try:
        run_task(task_id)
    except StockNameSourceUnavailable as e:
        log.error(
            "任务扫描未开始：ST 判定名称来源（PG）不可用 task=%s: %s", task_id, e
        )
        try:
            # 复位为 paused（非 running）：任务未执行任何 code，可待 PG 恢复后续跑。
            set_task_status(task_id, "paused")
        except Exception:
            log.exception("任务状态复位失败 task=%s", task_id)
    except Exception:
        log.exception("任务后台扫描失败 task=%s", task_id)


@router.get("/definitions")
async def strategy_definitions():
    """策略定义树（定义分组 → 任务节点 + 信号计数/进度，侧栏数据源）。

    响应：[{id,name,group_name,sort,params_schema(含 desc),states,columns,
    detail_schema,tasks:[{...任务字段..., signal_count}]}]
    """
    return get_definitions_with_tasks()


# ----------------------------------------------------------------------
# 任务 CRUD 与操作（design D6）
# ----------------------------------------------------------------------

@router.post("/tasks")
async def strategy_create_task(body: dict):
    """创建任务（spec「创建任务」：params 校验通过后进入 pending）。

    - params 按 params_schema 校验（非法 → 422，spec「参数非法被拒绝」）
    - scope 三种来源 + 全量兜底（spec「任务股票范围选择」）：
      * scope_type='manual'：body.scope_codes 直接传 code 列表
      * scope_type='watchlist'：body.watchlist_folder_id，创建时读文件夹固化快照
      * scope_type='bsp_query'：body.bsp_query 查询条件 dict，调 bsp 查询固化
      * scope_type='all'（缺省）：全量 A 股，执行时排除 ST/*ST
    - user_group：纯组织性标签（新字符串即新建分组，spec「自定义分组」）

    创建后不自动执行（spec「启动任务」：用户显式 start）。
    """
    strategy_id = body.get("strategy_id", "")
    label = body.get("label", "")
    params = body.get("params", {})
    scope_type = body.get("scope_type", "all")
    user_group = body.get("user_group", "")
    created_by = body.get("created_by")

    if not strategy_id or not isinstance(strategy_id, str):
        raise HTTPException(status_code=422, detail="strategy_id is required")
    if not label or not isinstance(label, str) or not label.strip():
        raise HTTPException(status_code=422, detail="label 不能为空")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise HTTPException(status_code=422, detail="params 必须为对象（键值对）")
    if user_group is not None and not isinstance(user_group, str):
        raise HTTPException(status_code=422, detail="user_group 需为字符串")

    # 范围解析 → 固化快照（design D3：创建时点解析一次，此后来源变化无关）
    try:
        scope_codes = resolve_scope_codes(
            scope_type,
            manual_codes=body.get("scope_codes"),
            watchlist_folder_id=body.get("watchlist_folder_id"),
            bsp_query=body.get("bsp_query"),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    try:
        task = create_task(
            strategy_id=strategy_id,
            label=label,
            params=params,
            scope_type=scope_type,
            scope_codes=scope_codes,
            mode=body.get("mode", "test"),
            user_group=user_group or "",
            created_by=created_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return task


@router.get("/tasks")
async def strategy_tasks(
    strategy_id: str = Query("", description="按策略定义过滤"),
    user_group: str = Query("", description="按用户分组过滤"),
    status: str = Query("", description="按状态过滤（pending/running/paused/done）"),
    mode: str = Query("", description="按形态过滤（test/persistent）"),
):
    """任务列表（spec「任务执行与进度管理」：基础信息/策略类型/分组/创建时间/
    创建人/执行进度——progress_scanned/progress_total 前端进度条消费）。"""
    if status and status not in ("pending", "running", "paused", "done"):
        raise HTTPException(status_code=422, detail=f"status 非法: {status}")
    if mode and mode not in ("test", "persistent"):
        raise HTTPException(status_code=422, detail=f"mode 非法: {mode}")
    return list_tasks(
        strategy_id=strategy_id or None,
        user_group=user_group or None,
        status=status or None,
        mode=mode or None,
    )


@router.get("/tasks/{task_id}")
async def strategy_get_task(task_id: int):
    """任务详情主体（单任务全字段）。"""
    return _get_task_or_404(task_id)


@router.patch("/tasks/{task_id}")
async def strategy_edit_task(task_id: int, body: dict):
    """编辑任务（spec「任务编辑与两种续跑语义」：仅 paused 可编辑）。

    - test 任务：参数与范围都可改（params 变化时服务端 params_version +1）
    - persistent 任务：仅范围可改（spec「persistent 参数冻结」——尝试改参数
      → 409 提示复制为新测试任务）
    - 范围编辑 = 重新固化快照（三种来源同创建时的解析语义），下次执行生效
    """
    task = _get_task_or_404(task_id)
    if task["status"] != "paused":
        raise HTTPException(
            status_code=409,
            detail=f"任务状态为 {task['status']}，仅 paused 状态可编辑",
        )

    label = body.get("label")
    user_group = body.get("user_group")
    params = body.get("params")
    scope_type = body.get("scope_type")

    if label is not None and (not isinstance(label, str) or not label.strip()):
        raise HTTPException(status_code=422, detail="label 不能为空")
    if user_group is not None and not isinstance(user_group, str):
        raise HTTPException(status_code=422, detail="user_group 需为字符串")

    # persistent 参数冻结（spec「persistent 参数冻结」）
    if params is not None and task["mode"] == "persistent":
        raise HTTPException(
            status_code=409,
            detail="persistent 任务参数已冻结（调参请复制为新的测试任务）",
        )

    # 范围编辑：重新解析快照（design D3 同创建语义）
    scope_codes = None
    if scope_type is not None:
        try:
            scope_codes = resolve_scope_codes(
                scope_type,
                manual_codes=body.get("scope_codes"),
                watchlist_folder_id=body.get("watchlist_folder_id"),
                bsp_query=body.get("bsp_query"),
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

    try:
        return update_task(
            task_id,
            label=label,
            user_group=user_group,
            params=params,
            scope_type=scope_type,
            scope_codes=scope_codes,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.delete("/tasks/{task_id}")
async def strategy_delete_task(task_id: int):
    """删除任务（spec「删除任务」：信号与逐股结果一并删除，不可恢复）。

    running 状态先拒绝（409）——用户先暂停再删，避免与执行器竞争。
    """
    task = _get_task_or_404(task_id)
    if task["status"] == "running":
        raise HTTPException(status_code=409, detail="任务执行中，请先暂停再删除")
    ok = delete_task(task_id)
    if not ok:
        raise HTTPException(status_code=500, detail="任务删除失败")
    return {"success": True}


@router.post("/tasks/{task_id}/start")
async def strategy_start_task(task_id: int, background: BackgroundTasks):
    """启动任务（spec「启动任务」：pending → running，进度从 0 开始推进）。

    扫描走 BackgroundTasks 异步（asyncio.to_thread，全量范围数据量可能较大，
    立即返回，扫描在响应后执行；幂等可重入——已扫前缀与水位天然断点）。
    """
    _get_task_or_404(task_id)
    try:
        task = start_task(task_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    background.add_task(asyncio.to_thread, _run_task_background, task_id)
    return task


@router.post("/tasks/{task_id}/pause")
async def strategy_pause_task(task_id: int):
    """暂停任务（spec「暂停任务」：running → paused，已产生信号与逐股结果保留）。

    执行器在每个 code 边界检查状态，下一边界停止（暂停响应最长延迟一只
    股票的扫描时间，design D4）。
    """
    _get_task_or_404(task_id)
    try:
        return pause_task(task_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.post("/tasks/{task_id}/resume")
async def strategy_resume_task(task_id: int, body: dict, background: BackgroundTasks):
    """续跑任务（design D2 两种续跑语义，spec「编辑后默认重新运行」）。

    body.rerun ∈ full（缺省，重新运行：清信号+逐股结果+水位+进度重扫）|
    remaining（剩余股票继续：保留已扫结果，从当前进度起用当前参数续跑）。
    """
    _get_task_or_404(task_id)
    rerun = body.get("rerun", "full")
    if rerun not in ("full", "remaining"):
        raise HTTPException(status_code=422, detail="rerun 仅接受 full 或 remaining")
    try:
        task = resume_task(task_id, rerun=rerun)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    background.add_task(asyncio.to_thread, _run_task_background, task_id)
    return task


@router.post("/tasks/{task_id}/promote")
async def strategy_promote_task(task_id: int):
    """转正（spec「转正」：done 的 test 任务 → persistent，纳入日终调度，
    既有信号保留；mode 翻转即被 EOD 循环（只取 persistent）纳入）。"""
    _get_task_or_404(task_id)
    try:
        return promote_task(task_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/tasks/{task_id}/copy")
async def strategy_copy_task(task_id: int, body: dict):
    """复制任务（spec「复制任务调参」：继承参数与范围为新的 test 任务，
    可自由编辑；信号/进度/水位不复制，从零扫描）。"""
    _get_task_or_404(task_id)
    label = body.get("label")
    if label is not None and (not isinstance(label, str) or not label.strip()):
        raise HTTPException(status_code=422, detail="label 不能为空")
    try:
        return copy_task(task_id, label=label)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


# ----------------------------------------------------------------------
# 任务详情（design D5：detail_schema 声明驱动渲染的数据源）
# ----------------------------------------------------------------------

@router.get("/tasks/{task_id}/detail")
async def strategy_task_detail(task_id: int):
    """任务详情（design D5：{task, summary, per_stock?, signals_page,
    kv_payload?, definition.detail_schema}，前端按声明渲染）。

    - summary：进度/匹配数/失败数聚合计数（显式范围来自逐股结果表，
      'all' 范围来自任务进度 + 信号计数）；键名 total/scanned/matched/
      failed 对齐前端 BlockSummary 契约（mock 同构）
    - per_stock：仅显式范围任务返回（scope='all' 时后端直接不返回该键，
      前端 per_stock 块静默隐藏逻辑与后端一致，spec「逐股块全量隐藏」）；
      行数 = scope 股票数（全量不落逐股结果），前端无分页 UI，
      返回数组而非分页对象
    - signals_page：信号列表分页（同 /api/strategy/signals 契约）；
      数据源只取匹配信号（matched_only=True，state ∈ triggered/running——
      expired 策略放弃态不出现在任务详情，strategy-signal-outcome spec
      「任务详情只展示匹配信号」）；行透传绩效四字段 ret_7d/ret_14d/ret_30d/
      outcome（NULL 表示无绩效/数据不足，前端显示 '--'）
    - kv_payload：定义 detail_schema 含 kv 块时返回（vp-entry-strategy
      design D5：vp_entry 由 compute_vp_entry_kv_stats 服务端聚合基底
      特征统计——信号总数/两版占比/spring 占比/三桶分布/平均影线盒宽/
      平均蓄势天数/平均 A 日涨幅/存活数）+ 通用绩效聚合（strategy-signal-
      outcome D6：compute_outcome_kv_stats——accuracy/success_cnt/failed_cnt/
      pending_cnt/avg 三时段收益，两策略同路径注入；vol_breakout 的三个
      形态统计项 first_board_date_hist/avg_volume_ratio/avg_pullback_days
      已按 D12/6.5 删除，只保留绩效统计）
    - definition：所属策略定义的 params_schema/states/columns/detail_schema
    """
    task = _get_task_or_404(task_id)
    from ..strategy_engines import get_definition

    definition = get_definition(task["strategy_id"])

    # signals 块数据（复用 /signals 的分页契约；只取匹配信号，D6）
    result = query_signals(
        task_id=task_id,
        state="",
        direction="",
        page=1,
        page_size=20,
        matched_only=True,
    )
    industries_map = get_industries_for_codes([i["code"] for i in result["items"]])
    signals_list = []
    for it in result["items"]:
        signals_list.append({
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
            "params_version": it["params_version"],
            "ret_7d": it["ret_7d"],
            "ret_14d": it["ret_14d"],
            "ret_30d": it["ret_30d"],
            "outcome": it["outcome"],
        })

    # summary 块数据（进度 + 匹配/失败计数；键名 total/scanned/matched/
    # failed 对齐前端 BlockSummary 契约）
    explicit_scope = task["scope_type"] != "all"
    total_signals = query_signals(task_id, page_size=1)["total"]
    if explicit_scope:
        counts = count_stock_results(task_id)
        summary = {
            "total": task["progress_total"],
            "scanned": task["progress_scanned"],
            "matched": counts["matched"],
            "failed": counts["failed"],
        }
    else:
        # 'all' 范围：无逐股结果行，聚合计数来自任务进度与信号总数
        summary = {
            "total": task["progress_total"],
            "scanned": task["progress_scanned"],
            "matched": total_signals,
            "failed": 0,
        }

    detail: dict = {
        "task": task,
        "summary": summary,
        "signals_page": {
            "list": signals_list,
            "total": result["total"],
            "page": result["page"],
            "page_size": result["page_size"],
        },
        "definition": {
            "id": definition.id,
            "name": definition.name,
            "group_name": definition.group_name,
            "params_schema": definition.params_schema,
            "states": definition.states,
            "columns": definition.columns,
            "detail_schema": definition.detail_schema,
        } if definition else None,
    }

    # kv 块数据（vp-entry-strategy-integration design D5）：声明驱动——定义的
    # detail_schema 含 kv 块时返回 kv_payload（键与块 items[].key 对齐）；
    # vp_entry 由 compute_vp_entry_kv_stats 聚合基底特征统计，其余定义缺
    # provider 时返回空载荷（前端 kv 块显示 '--'，不报错）。
    # 绩效准确率通用聚合（strategy-signal-outcome D6）：两策略 kv 都注入
    # compute_outcome_kv_stats（与 vp_entry 逻辑同路径——含 kv 块才注入）
    if definition and any(b.get("type") == "kv" for b in definition.detail_schema):
        if task["strategy_id"] == "vp_entry":
            kv_payload = compute_vp_entry_kv_stats(task_id)
        else:
            kv_payload = {}
        kv_payload.update(compute_outcome_kv_stats(task_id))
        detail["kv_payload"] = kv_payload

    # per_stock 块数据：仅显式范围返回（design D5：'all' 静默不返回）；
    # 数组契约（行数 = scope 股票数，前端 BlockPerStock 无分页 UI）
    if explicit_scope:
        per = query_stock_results(task_id, page=1, page_size=10000)
        detail["per_stock"] = per["items"]
    return detail


# ----------------------------------------------------------------------
# 信号查询（strategy-signal spec：任务维度 + params_version 透出）
# ----------------------------------------------------------------------

@router.get("/signals")
async def strategy_signals(
    task_id: int = Query(..., description="策略任务 id"),
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
    entry_ref_price,stop_ref_price,payload,params_version}。行业按页批量单条
    SQL（对齐 bsp 路由）；params_version 供前端版本标识（spec「信号版本归因」）。
    """
    _check_date_param(date_from, "date_from")
    _check_date_param(date_to, "date_to")

    _get_task_or_404(task_id)

    result = query_signals(
        task_id=task_id,
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
            "params_version": it["params_version"],
            "ret_7d": it["ret_7d"],
            "ret_14d": it["ret_14d"],
            "ret_30d": it["ret_30d"],
            "outcome": it["outcome"],
        })

    return {
        "list": records,
        "total": result["total"],
        "page": result["page"],
        "page_size": result["page_size"],
    }


# ----------------------------------------------------------------------
# 信号回查（monitor 加监控上下文定位用，routers/monitor 消费同一 store 函数）
# ----------------------------------------------------------------------


@router.get("/signals/for-monitor")
async def strategy_signal_for_monitor(
    task_id: int = Query(..., description="策略任务 id"),
    signal_date: str = Query(..., description="信号日期 YYYY-MM-DD"),
    code: str = Query(..., description="股票编码"),
):
    """按任务 + 信号日期 + 编码定位信号（monitor 加监控上下文回查）。

    返回 {state, is_buy, entry_ref_price}；查不到 404（调用方兜底）。
    """
    _check_date_param(signal_date, "signal_date")
    _get_task_or_404(task_id)
    sig = get_signal_for_monitor(task_id, signal_date, code)
    if sig is None:
        raise HTTPException(status_code=404, detail="未找到对应信号")
    return sig
