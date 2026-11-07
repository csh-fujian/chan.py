# -*- coding: utf-8 -*-
"""
缠论参数配置路由（chan-config-panel）。

端点：
    GET  /api/chan-config              当前生效配置（全量生效值 + 版本 + 档位）
    GET  /api/chan-config/schema       参数元数据（分组 / 控件 / 白话解释 / 默认值）
    PUT  /api/chan-config              保存配置（构造期校验 → 落库 → bump version）
    POST /api/chan-config/recompute    单只股票的后台重算（当前股票保存后刷新 PG 索引）
    POST /api/chan-config/sync         全库批量同步（后台，内存标志防重入）
    GET  /api/chan-config/sync/status  同步进度 / 失败明细 / 结果是否已过期

权限：
    读接口挂 `require_menu_kline`（能看到 K 线页即能看到参数）
    写接口与同步挂 `require_manage`

设计要点见 openspec/changes/chan-config-panel/design.md：
    D4  保存前构造期校验（含 bs_type 的延迟断言前移）
    D7  保存后的重算是**两段式**：/api/klines 立即重拉（秒级）、PG 索引后台重算
    D8  批量同步复用 `catch_up(force=True)` + 任务表记录进度
    D12 PG 不可达：读降级（返回内核默认）、写 503
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import chan_config_store as store
from ..auth import require_manage, require_menu_kline
from ..chan_config_schema import build_schema

log = logging.getLogger("chan_config_router")

router = APIRouter(prefix="/api/chan-config", tags=["chan-config"])

# 批量同步的防重入标志（进程内）。任务表记录持久进度，本标志只防并发启动。
_SYNC_RUNNING = False


# ----------------------------------------------------------------------
# 请求 / 响应模型
# ----------------------------------------------------------------------

class ConfigSaveRequest(BaseModel):
    """保存配置：只提交**用户显式改过的键**，未提交的项跟随档位预设。"""

    overrides: dict = Field(
        default_factory=dict,
        description="显式覆盖项（键为参数 key）；未包含的项跟随内核默认与档位预设",
    )
    preset: str = Field(default="standard", description="档位预设名（standard/legacy）")
    full_snapshot: Optional[dict] = Field(
        default=None,
        description="全量快照（参数 key → 保存时的生效值），仅用于展示与审计",
    )


class RecomputeRequest(BaseModel):
    """单只股票重算请求。"""

    code: str = Field(..., description="股票代码，如 sz.000001")
    period: str = Field(default="D", description="周期（D/W/M/60m/30m/15m/5m）")
    autype: str = Field(default="QFQ", description="复权方式（QFQ/HFQ/NONE）")


# ----------------------------------------------------------------------
# 读
# ----------------------------------------------------------------------

@router.get("")
def get_config(user: dict = Depends(require_menu_kline)):
    """当前生效配置。

    返回 `effective`（全部参数的生效值，已展开默认与档位）、`overrides`（用户显式改过的
    键，用于判断「哪些项被用户改过」）、`preset` / `version` / `initialized`。

    PG 不可达时降级为内核默认（`initialized=false`），不报错 —— 与
    `/api/klines` 的失败开放取向一致（design D12）。

    **整份响应必须走 `store.encode_config()`**：legacy 档的
    `divergence_rate` 是 `float("inf")`，标准 JSON 不接受非有限浮点，
    裸返回会让 starlette 在 `json.dumps` 处抛
    `ValueError: Out of range float values are not JSON compliant: inf`
    （表现为 500）。`/schema` 早已这么处理，此处此前漏了 —— 档位修好后
    切到 legacy 立刻暴露。
    """
    meta = store.load_with_meta()
    effective = _effective_from_meta(meta)
    return store.encode_config({
        "effective": effective,
        "overrides": meta["overrides"],
        "preset": meta["preset"],
        "version": meta["version"],
        "initialized": meta["initialized"],
    })


def _conf_from_meta(meta: dict):
    """按「已保存配置 + 已落库档位」构造一次 `CChanConfig`（反射用）。

    **档位要显式补**：`bsp_preset` 存的是 `preset` 列而不是 overrides 里的键，
    只传 overrides 会让 `CChanConfig` 按硬编码默认 `standard` 展开 ——
    legacy 档下界面显示的仍是 standard 的值，与计算链路不符（详见
    `chan_config_store.load_preset()`）。`setdefault` 保证用户显式写过的
    `bsp_preset` 优先。

    存储里的配置坏掉时降级为内核默认，不让读接口 500（design D12）。
    """
    from ChanAnalyse.ChanConfig import CChanConfig

    overrides = dict(meta["overrides"])
    overrides.setdefault("bsp_preset", meta.get("preset") or "standard")
    try:
        return CChanConfig(store.to_kernel(store.apply_derived(overrides)))
    except Exception as e:
        log.warning("生效配置构造失败，降级为内核默认: %s", e)
        return CChanConfig()


def _effective_from_meta(meta: dict) -> dict:
    """把 overrides 展开为全量生效值（内核默认 + 档位 + 用户覆盖）。

    做法是构造一次 `CChanConfig` 再逐项反射读取 —— 与计算链路用的是同一套
    默认值与档位展开逻辑，不会出现「界面显示值与实际计算值不符」。
    """
    from ..chan_config_schema import PARAMS, _read_default

    conf = _conf_from_meta(meta)
    out = {}
    for spec in PARAMS:
        key = spec["key"]
        try:
            out[key] = _read_default(conf, key)
        except Exception:
            out[key] = None
    return store.to_flat(out)


@router.get("/schema")
def get_schema(user: dict = Depends(require_menu_kline)):
    """参数元数据：分组、控件类型、合法取值、白话解释、默认值。

    回应里三份默认值语义不同：
        - `params[].default` —— 按**当前已保存配置**反射，用户改过就跟着变。
          用于展示「这一项现在是多少」。
        - `kernel_defaults` —— **内核出厂默认**，永远不随用户配置漂移。
        - `preset_baselines[档位]` —— 该档位**预设展开后**的默认值。前端
          「恢复默认」与 overrides 比较基线都用这一份（legacy 档会在十余项上
          与 standard 不同，用 `kernel_defaults` 会把这些预设项误判成用户覆盖）。

    `divergence_rate` 在 legacy 档是 `inf`，而 `json.dumps` 拒绝非有限浮点，
    故整份响应走 `store.encode_config()`（与配置读写同一套 inf ↔ "inf" 编码）。
    """
    meta = store.load_with_meta()
    return store.encode_config(build_schema(_conf_from_meta(meta)))


# ----------------------------------------------------------------------
# 写
# ----------------------------------------------------------------------

def _validation_detail(e: "store.ConfigValidationError") -> dict:
    """422 响应体：可定位参数 + 内核异常原文（design D4，前端据此定位到控件）。"""
    return {"message": str(e), "param": e.param, "kernel_message": e.kernel_message}


@router.put("")
def put_config(body: ConfigSaveRequest, user: dict = Depends(require_manage)):
    """保存配置。

    流程（design D3 / D4）：
        1. 构造期校验（非法 → 422，透传内核异常原文并附可定位参数名）
        2. 落库：overrides（生效语义）+ 全量快照（展示/审计）+ preset，bump version
        3. 返回新版本号 —— 前端据此重拉 `/api/klines` 并触发当前股票重算

    校验失败时不写入任何内容，`GET /api/chan-config` 仍返回旧配置。
    """
    try:
        # `preset` 是独立字段，不经过 `validate_config()`（那只校验 overrides）。
        # 档位现已真正进入计算链路（`build_conf()` 回填），非法档位名一旦落库，
        # 后续每次 `CChanConfig(...)` 都会抛 `unknown bsp_preset`，**所有** K 线
        # 计算请求 500 —— 必须在写入前拦住。
        preset = store.validate_preset(body.preset)
        cleaned = store.validate_config(body.overrides)
    except store.ConfigValidationError as e:
        raise HTTPException(status_code=422, detail=_validation_detail(e))

    snapshot = body.full_snapshot
    if snapshot is not None:
        snapshot = store.to_kernel(store.apply_derived(dict(snapshot)))
        snapshot = store.to_flat(snapshot)

    try:
        version = store.save(
            cleaned, preset, full_snapshot=snapshot,
            updated_by=user.get("username"),
        )
    except store.ConfigStoreUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))

    return {"ok": True, "version": version, "overrides": cleaned, "preset": preset}


# ----------------------------------------------------------------------
# 单只重算（design D7 第二段）
# ----------------------------------------------------------------------

@router.post("/recompute")
async def recompute_endpoint(
    body: RecomputeRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_manage),
):
    """触发单只股票的后台重算（刷新 PG 索引）。

    `force_full=False` —— 指纹已因配置变更而变化，`recompute_stock` 内部会自动转全量。
    立即返回受理标识，前端用 `/api/klines` 的重新加载做即时反馈。
    """
    from ..incremental_engine import recompute_stock

    try:
        canonical = _canonical_period(body.period)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    background_tasks.add_task(
        _run_recompute, body.code, canonical, body.autype.upper()
    )
    return {"accepted": True, "code": body.code, "period": canonical,
            "autype": body.autype.upper()}


def _canonical_period(period: str) -> str:
    """周期校验与规范化（复用 chan_service 的词表桥接）。"""
    from ..chan_service import PERIOD_MAP, PERIOD_CANONICAL

    kl_type = PERIOD_MAP.get(period)
    if kl_type is None:
        raise ValueError(
            f"Unsupported period: {period!r}. Valid values: {list(PERIOD_MAP.keys())}"
        )
    return PERIOD_CANONICAL[kl_type]


def _run_recompute(code: str, period: str, autype: str) -> None:
    """后台执行单只重算（异常只记日志，不向客户端抛）。"""
    from ..incremental_engine import recompute_stock

    try:
        result = recompute_stock(code, period, autype=autype, force_full=False)
        if result is None:
            log.info("recompute %s %s: 无数据或无变化", code, period)
        else:
            log.info("recompute %s %s: mode=%s rows=%s",
                     code, period, result.get("mode"), result.get("bsp_rows"))
    except Exception:
        log.exception("recompute 失败: %s %s", code, period)


# ----------------------------------------------------------------------
# 批量同步（design D8）
# ----------------------------------------------------------------------

@router.post("/sync")
async def sync_endpoint(
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_manage),
):
    """全库批量同步：按**当前生效配置**重算全部 (code, period, autype) 键。

    与 `catch_up(force=True)` 等价（跳过水位门，范围内全部整套重写），
    后台执行，进度写 `chan_config_sync_job`。已有任务在跑返回 409。
    """
    global _SYNC_RUNNING
    if _SYNC_RUNNING:
        raise HTTPException(status_code=409, detail="已有同步任务在运行")

    meta = store.load_with_meta()
    version = meta["version"] or 0
    try:
        job_id = store.sync_job_create(version)
    except store.ConfigStoreUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))

    _SYNC_RUNNING = True
    background_tasks.add_task(_run_sync, job_id, version)
    return {"started": True, "job_id": job_id, "config_version": version}


async def _run_sync(job_id: int, config_version: int) -> None:
    """后台全库同步：逐键推进进度，结束时写汇总与终态。"""
    global _SYNC_RUNNING
    from ..incremental_engine import catch_up

    done = failed = 0
    details: list = []

    def _progress(total: int, done_n: int, failed_n: int) -> None:
        nonlocal done, failed
        done, failed = done_n, failed_n
        store.sync_job_progress(job_id, done_n, failed_n, total=total)

    try:
        result = await asyncio.to_thread(
            catch_up, None, None, None, 0, True, _progress
        )
        done = result.get("updated", 0)
        details = result.get("failed", [])
        failed = len(details)
        stale = store.load_with_meta()["version"] != config_version
        store.sync_job_finish(job_id, "done", done, failed, {
            "scanned": result.get("scanned", 0),
            "updated": done,
            "failed": details,
            "stale": stale,
        })
    except Exception as e:
        log.exception("批量同步失败")
        store.sync_job_finish(job_id, "failed", done, failed, {"error": str(e)})
    finally:
        _SYNC_RUNNING = False


@router.get("/sync/status")
def sync_status_endpoint(user: dict = Depends(require_menu_kline)):
    """最近一次同步任务的状态。

    `running` 取进程内标志（跨进程不可见，重启后为 false），进度与汇总取任务表。
    `stale=true` 表示任务启动后配置又变了，结果不代表当前口径。
    """
    job = store.sync_job_latest()
    if job is None:
        return {"running": _SYNC_RUNNING, "job": None, "stale": False}
    return {
        "running": _SYNC_RUNNING,
        "job": {
            "job_id": job["job_id"],
            "status": job["status"],
            "total": job["total"],
            "done": job["done"],
            "failed": job["failed"],
            "summary": job["summary"],
            "started_at": job["started_at"],
            "finished_at": job["finished_at"],
            "config_version": job["config_version"],
            "current_version": job["current_version"],
        },
        "stale": job["stale"],
    }
