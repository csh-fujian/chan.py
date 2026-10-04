# -*- coding: utf-8 -*-
"""
策略引擎层 — strategy-signal-page design D3/D5。

- `StrategyEngine` 协议：统一扫描接口 scan(code, kl_type_db, autype, watermark)，
  返回 SignalEvent dict 列表；引擎内部自行管理状态演进（watching →
  triggered/expired/running 等），框架不统一驱动状态机（语义是策略私有的）。
- `StrategyDefinition` dataclass：策略定义声明（id/name/group_name/engine_key/
  sort/params_schema/states/columns），由代码注册（随版本发布），用户不可增删。
- `DEFINITIONS` 注册表：dict[str, StrategyDefinition]；新策略接入 = 注册定义 +
  写引擎，前端零改动（schema 驱动渲染）。
- `validate_params`：按 params_schema 校验参数（类型/最小/最大/未知键），返回
  (normalized_params, errors)。

硬性约束：引擎 SHALL NOT import CChan 任何模块，只读 DuckDB 原始 K 线
（spec「不触碰缠论内核」场景）。
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

log = logging.getLogger("strategy_engines")


@dataclass
class StrategyDefinition:
    """策略定义（代码注册，非用户 CRUD）。

    - id：策略标识（如 'vol_breakout_pullback'），PG strategy.id 同名对齐
    - name：显示名（如「放量首板回调」）
    - group_name：侧栏分组名（如「量价策略」）
    - engine_key：引擎注册键（DEFINITIONS 内查 ENGINE_REGISTRY）
    - sort：侧栏排序
    - params_schema：参数模式 [{key,label,type,default,min,max}]
    - states：状态集 [{value,label,color}]（信号生命周期状态取值域）
    - columns：表格私有列 [{key,label,type}]（值取自 signal payload）
    """

    id: str
    name: str
    group_name: str
    engine_key: str
    sort: int = 0
    params_schema: list[dict] = field(default_factory=list)
    states: list[dict] = field(default_factory=list)
    columns: list[dict] = field(default_factory=list)


@runtime_checkable
class StrategyEngine(Protocol):
    """策略引擎统一接口（design D3）。

    scan 输入待扫键（code + DuckDB 侧 kl_type/autype）与该 (实例, code) 的
    扫描水位；输出 SignalEvent dict 列表 + 新水位。watermark 语义：
    watermark 非空且其后无新 K 线 → 不重算（返回空事件 + 原水位）。
    """

    def scan(
        self,
        code: str,
        kl_type_db: str = "K_DAY",
        autype: str = "QFQ",
        watermark: Optional[str] = None,
    ) -> list[dict]:
        ...


# ----------------------------------------------------------------------
# params_schema 校验（strategy-signal-page 任务 2.1）
# ----------------------------------------------------------------------

_TYPE_CAST = {
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
}


def validate_params(
    definition: StrategyDefinition, params: Optional[dict]
) -> tuple[dict, list[str]]:
    """按 definition.params_schema 校验 params（strategy-signal-page 2.1）。

    - 未提供的键取 default；未知键报错（防静默吞参数）
    - 类型不符 / 小于 min / 大于 max 报错
    - bool 视为 int 的子类型放行（isinstance(True, int) 为 True，需显式排除）

    返回 (normalized_params, errors)：errors 为空即校验通过。
    """
    normalized: dict = {}
    errors: list[str] = []

    if params is None:
        params = {}
    if not isinstance(params, dict):
        return {}, ["params 必须为对象（键值对）"]

    schema_keys = {p["key"] for p in definition.params_schema}
    for k in params:
        if k not in schema_keys:
            errors.append(f"未知参数: {k}")

    for p in definition.params_schema:
        key = p["key"]
        ptype = p.get("type", "str")
        if key in params:
            value = params[key]
        elif "default" in p:
            value = p["default"]
        else:
            errors.append(f"缺少必填参数: {key}")
            continue

        cast = _TYPE_CAST.get(ptype)
        if cast is None:
            # 未知类型声明：按 str 透传（注册表自声明，引擎写入前自校验）
            normalized[key] = value
            continue

        if ptype in ("int", "float") and isinstance(value, bool):
            errors.append(f"{key} 需为 {ptype}，收到 bool")
            continue
        try:
            value = cast(value)
        except (TypeError, ValueError):
            errors.append(f"{key} 需为 {ptype}")
            continue

        if ptype == "int" and isinstance(value, float):
            errors.append(f"{key} 需为 int")
            continue
        if "min" in p and value < p["min"]:
            errors.append(f"{key} 不能小于 {p['min']}（收到 {value}）")
            continue
        if "max" in p and value > p["max"]:
            errors.append(f"{key} 不能大于 {p['max']}（收到 {value}）")
            continue
        normalized[key] = value

    return normalized, errors


# ----------------------------------------------------------------------
# 定义注册表 + 引擎注册表（代码注册，随版本发布）
# ----------------------------------------------------------------------

DEFINITIONS: dict[str, StrategyDefinition] = {}
ENGINE_REGISTRY: dict[str, StrategyEngine] = {}


def register_definition(definition: StrategyDefinition) -> None:
    """注册策略定义（幂等：同名覆盖，便于测试与模块重载）。"""
    DEFINITIONS[definition.id] = definition


def register_engine(engine_key: str, engine: StrategyEngine) -> None:
    """注册策略引擎实例（幂等：同名覆盖）。"""
    ENGINE_REGISTRY[engine_key] = engine


def get_definition(strategy_id: str) -> Optional[StrategyDefinition]:
    """取策略定义；不存在返回 None。"""
    return DEFINITIONS.get(strategy_id)


def get_engine(engine_key: str) -> Optional[StrategyEngine]:
    """取策略引擎；不存在返回 None。"""
    return ENGINE_REGISTRY.get(engine_key)


# ----------------------------------------------------------------------
# 首个定义：vol_breakout_pullback（放量首板回调，design D3）
# ----------------------------------------------------------------------

register_definition(StrategyDefinition(
    id="vol_breakout_pullback",
    name="放量首板回调",
    group_name="量价策略",
    engine_key="vol_breakout_pullback",
    sort=1,
    params_schema=[
        {"key": "pullback_max_days", "label": "回调天数上限", "type": "int",
         "default": 5, "min": 1, "max": 20},
        {"key": "volume_ratio_min", "label": "首板放量倍数下限", "type": "float",
         "default": 2.0, "min": 1.0, "max": 10.0},
        {"key": "volume_shrink_max", "label": "回调缩量阈值", "type": "float",
         "default": 0.8, "min": 0.1, "max": 1.0},
    ],
    states=[
        {"value": "watching", "label": "回调中", "color": "info"},
        {"value": "triggered", "label": "已触发", "color": "warning"},
        {"value": "expired", "label": "已失效", "color": "danger"},
        {"value": "running", "label": "已启动", "color": "success"},
    ],
    columns=[
        {"key": "first_board_date", "label": "首板日", "type": "date"},
        {"key": "pullback_days", "label": "回调天数", "type": "int"},
        {"key": "volume_ratio", "label": "放量倍数", "type": "float"},
    ],
))

# 引擎在 vol_breakout.py 导入时自注册（延迟导入避免模块循环依赖：
# vol_breakout 只依赖 KLineStore 与本注册表，无环，直接导入）
from .vol_breakout import VolBreakoutPullbackEngine  # noqa: E402

register_engine("vol_breakout_pullback", VolBreakoutPullbackEngine())
