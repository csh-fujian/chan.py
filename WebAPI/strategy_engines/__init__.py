# -*- coding: utf-8 -*-
"""
策略引擎层 — strategy-signal-page design D3/D5 + strategy-task-redesign design D5/D6。

- `StrategyEngine` 协议：统一扫描接口 scan(code, kl_type_db, autype, watermark)，
  返回 SignalEvent dict 列表；引擎内部自行管理状态演进（watching →
  triggered/expired/running 等），框架不统一驱动状态机（语义是策略私有的）。
- `StrategyDefinition` dataclass：策略定义声明（id/name/group_name/engine_key/
  sort/params_schema/states/columns/detail_schema），由代码注册（随版本发布），
  用户不可增删。
- `DEFINITIONS` 注册表：dict[str, StrategyDefinition]；新策略接入 = 注册定义 +
  写引擎，前端零改动（schema 驱动渲染）。
- `validate_params`：按 params_schema 校验参数（类型/最小/最大/enum 选项集/
  未知键），返回 (normalized_params, errors)；desc/detail_schema 是展示元数据
  不参与校验。enum 类型（design D4）：options 枚举集校验，错误文案带合法值
  列表，_TYPE_CAST 不动（enum 走独立分支，value 透传字符串）。

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
    - name：显示名（如「放量启动回调」）
    - group_name：侧栏分组名（如「量价策略」）
    - engine_key：引擎注册键（DEFINITIONS 内查 ENGINE_REGISTRY）
    - sort：侧栏排序
    - params_schema：参数模式 [{key,label,type,default,min,max,desc}]
      （desc：参数说明文案，前端参数名旁 tooltip 展示，strategy-task-redesign D6）
    - states：状态集 [{value,label,color}]（信号生命周期状态取值域）
    - columns：表格私有列 [{key,label,type}]（值取自 signal payload）
    - detail_schema：任务详情展示积木块声明（strategy-task-redesign design D5，
      新策略注册必填；块类型 v1 全集：summary / per_stock / signals / kv /
      timeline / chart，声明驱动前端通用积木组件渲染，新策略零前端改动）
    """

    id: str
    name: str
    group_name: str
    engine_key: str
    sort: int = 0
    params_schema: list[dict] = field(default_factory=list)
    states: list[dict] = field(default_factory=list)
    columns: list[dict] = field(default_factory=list)
    detail_schema: list[dict] = field(default_factory=list)


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
    - params_schema 声明里的 precision/step 是前端输入控件的展示元数据
      （数值精度/步进，D12），不参与校验——本函数只迭代用户 params 键与
      schema 的 key，声明的多余字段天然忽略，无需放行逻辑

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

        # enum 分支（vp-entry-strategy-integration design D4）：取值必须在
        # options[].value 集合内（错误文案带合法值列表）；value 透传字符串
        if ptype == "enum":
            options = [str(o["value"]) for o in p.get("options") or []]
            if not options:
                errors.append(f"{key} 的 enum 声明缺少 options")
                continue
            value = str(value)
            if value not in options:
                errors.append(
                    f"{key} 取值必须是 {'/'.join(options)}，收到 {value}"
                )
                continue
            normalized[key] = value
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
# 通用绩效计算（strategy-signal-outcome design D3）
# ----------------------------------------------------------------------

# 绩效三时段窗口（交易日数，spec 定死：入场日后 +7/+14/+30）
OUTCOME_HORIZONS = (7, 14, 30)
# 加权求和权重（spec 定死，D13：7日×50% + 14日×30% + 30日×20%，不做参数）
OUTCOME_WEIGHTS = (0.5, 0.3, 0.2)
# 成功判定阈值（D13：加权总收益 > 5% 判成功，不做参数）
OUTCOME_THRESHOLD = 0.05


def compute_outcome(
    entry_idx: int, entry_price: float, kl: list[tuple]
) -> tuple:
    """匹配信号绩效计算（两策略引擎共用，strategy-signal-outcome design D3/D13）。

    - kl 为 (time_key, open, high, low, close, volume) 元组列表（引擎手上的
      全历史日线）；entry_idx 为入场日在 kl 中的索引；entry_price 为买入
      基准价（= 信号行 entry_ref_price 口径，各策略自定义）
    - 收益率 = kl[entry_idx + d].close / entry_price - 1（d ∈ 7/14/30），
      越界（未来数据不足）的时段收益率为 None，对应收盘价同为 None
    - outcome 规则（D13 加权求和，spec「信号存储与状态机」）：
      总收益 = ret_7d×0.5 + ret_14d×0.3 + ret_30d×0.2；总收益 > 0.05 →
      'success'，否则 'failed'；三时段任一不可得 → 'pending'（数据不足，
      不做权重归一化、不按 0 计入——口径无隐式假设）

    返回 (ret_7d, ret_14d, ret_30d, outcome, close_7d, close_14d, close_30d)，
    close_* 为对应时段的收盘价过程字段（D10 消费，越界为 None）。
    """
    n = len(kl)
    rets: list = []
    closes: list = []
    for d in OUTCOME_HORIZONS:
        j = entry_idx + d
        if j < n and entry_price and entry_price > 0:
            c = float(kl[j][4])
            rets.append(c / entry_price - 1.0)
            closes.append(c)
        else:
            rets.append(None)
            closes.append(None)

    if any(r is None for r in rets):
        outcome = "pending"
    else:
        total = sum(r * w for r, w in zip(rets, OUTCOME_WEIGHTS))
        outcome = "success" if total > OUTCOME_THRESHOLD else "failed"

    ret_7d, ret_14d, ret_30d = rets
    close_7d, close_14d, close_30d = closes
    return ret_7d, ret_14d, ret_30d, outcome, close_7d, close_14d, close_30d


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
# 首个定义：vol_breakout_pullback（放量启动回调，design D3；原名「放量首板
# 回调」，strategy-signal-outcome D11 涨幅门槛参数化后同步改名）
# ----------------------------------------------------------------------

register_definition(StrategyDefinition(
    id="vol_breakout_pullback",
    name="放量启动回调",
    group_name="量价策略",
    engine_key="vol_breakout_pullback",
    sort=1,
    params_schema=[
        # precision/step 为前端输入控件展示元数据（数值精度/步进，D12），
        # validate_params 不消费（见其 docstring）；desc 为普通用户白话
        # （含义 + 调高/调低后果，strategy-signal-outcome 6.9）
        {"key": "pullback_max_days", "label": "回调天数上限", "type": "int",
         "default": 5, "min": 1, "max": 20, "precision": 0, "step": 1,
         "desc": "启动日之后最多观察多少个交易日的回调，超过这个天数还没企稳就放弃。"
                 "调高（如 10）愿意等更久，信号更多但等待期变长；调低（如 3）只接受"
                 "很快止跌的形态，信号更少但更干脆。默认 5 个交易日。"},
        {"key": "volume_ratio_min", "label": "启动放量倍数下限", "type": "float",
         "default": 2.0, "min": 1.0, "max": 10.0, "precision": 1, "step": 0.1,
         "desc": "启动日成交量需要达到前 20 日平均成交量的多少倍。调高（如 3.0）"
                 "要求放量大更猛，信号更少但启动力度更强；调低（如 1.5）轻微放量"
                 "也算，信号更多但质量参差。默认 2.0 倍。"},
        {"key": "a_pct_min", "label": "启动日涨幅门槛", "type": "float",
         "default": 0.05, "min": 0.03, "max": 0.15, "precision": 2, "step": 0.01,
         "desc": "启动日当天收盘涨幅的最低要求。调高（如 0.098）只筛选接近涨停的"
                 "强势上涨日，信号更少但更强；调低（如 0.03）纳入温和上涨日，"
                 "信号更多但强度较弱。默认 0.05 即当天至少涨 5%。"},
        {"key": "volume_shrink_max", "label": "回调缩量阈值", "type": "float",
         "default": 0.8, "min": 0.1, "max": 1.0, "precision": 1, "step": 0.1,
         "desc": "回调期间成交量需要缩到启动日成交量的多少比例以下才算有效缩量。"
                 "调高（如 0.9）允许回调中保留较多量能，容易通过但缩量形态不纯；"
                 "调低（如 0.5）要求回调明显缩量，形态更标准但信号更少。默认 0.8。"},
    ],
    states=[
        {"value": "watching", "label": "回调中", "color": "info"},
        {"value": "triggered", "label": "已触发", "color": "warning"},
        {"value": "expired", "label": "已失效", "color": "danger"},
        {"value": "running", "label": "已启动", "color": "success"},
    ],
    columns=[
        {"key": "pullback_days", "label": "回调天数", "type": "int"},
        {"key": "volume_ratio", "label": "放量倍数", "type": "float"},
        # A/B 点与绩效列（strategy-signal-outcome 2.4 + 6.1 D12 返工：价格+涨幅
        # 合并为 price_pct 单列，声明 priceKey/pctKey 双 key，值从行/payload 取；
        # 不再有独立价格 float 列与独立涨幅 pct 列）
        {"key": "a_date", "label": "A日", "type": "date"},
        {"key": "a_price", "label": "A日股价", "type": "price_pct",
         "priceKey": "a_close", "pctKey": "a_pct"},
        {"key": "b_date", "label": "B日", "type": "date"},
        {"key": "b_price", "label": "B日股价", "type": "price_pct",
         "priceKey": "b_close", "pctKey": "b_day_pct"},
        {"key": "close_7d_price", "label": "7日股价", "type": "price_pct",
         "priceKey": "close_7d", "pctKey": "ret_7d"},
        {"key": "close_14d_price", "label": "14日股价", "type": "price_pct",
         "priceKey": "close_14d", "pctKey": "ret_14d"},
        {"key": "close_30d_price", "label": "30日股价", "type": "price_pct",
         "priceKey": "close_30d", "pctKey": "ret_30d"},
        {"key": "outcome", "label": "成功判定", "type": "outcome"},
    ],
    # 任务详情积木块（strategy-task-redesign design D5 v1 声明）：
    # summary（进度/匹配/失败汇总）→ per_stock（逐股结果，scope='all' 时前端静默
    # 隐藏）→ signals（信号表格）→ kv（绩效准确率统计；D12/6.5 返工：删
    # first_board_date_hist/avg_volume_ratio/avg_pullback_days 三个形态统计项，
    # 策略摘要聚焦绩效，形态统计不再展示）
    detail_schema=[
        {"type": "summary"},
        {"type": "per_stock"},
        {"type": "signals"},
        {"type": "kv", "items": [
            # 绩效准确率统计项（D6：值由 detail API compute_outcome_kv_stats 聚合）
            {"key": "accuracy", "label": "准确率", "fmt": "pct"},
            {"key": "success_cnt", "label": "成功数", "fmt": "int"},
            {"key": "failed_cnt", "label": "失败数", "fmt": "int"},
            {"key": "pending_cnt", "label": "数据不足数", "fmt": "int"},
            {"key": "avg_ret_7d", "label": "平均7日收益", "fmt": "pct"},
            {"key": "avg_ret_14d", "label": "平均14日收益", "fmt": "pct"},
            {"key": "avg_ret_30d", "label": "平均30日收益", "fmt": "pct"},
        ]},
    ],
))

# 引擎在 vol_breakout.py 导入时自注册（延迟导入避免模块循环依赖：
# vol_breakout 只依赖 KLineStore 与本注册表，无环，直接导入）
from .vol_breakout import VolBreakoutPullbackEngine  # noqa: E402

register_engine("vol_breakout_pullback", VolBreakoutPullbackEngine())

# ----------------------------------------------------------------------
# 第二个定义：vp_entry（量价三段式买点，vp-entry-strategy-integration D4）
# ----------------------------------------------------------------------

register_definition(StrategyDefinition(
    id="vp_entry",
    name="量价三段式买点",
    group_name="量价策略",
    engine_key="vp_entry",
    sort=2,
    params_schema=[
        # precision/step 为前端输入控件展示元数据（D12），validate_params 不消费
        {"key": "cv7_max", "label": "蓄势期 CV7 门限", "type": "float",
         "default": 0.25, "min": 0.15, "max": 0.35, "precision": 2, "step": 0.01,
         "desc": "启动前横盘蓄势阶段成交量平稳程度的要求（数值越小要求越平稳）。"
                 "调高（如 0.30）允许蓄势期量能波动大一些，机会更多但形态松散；"
                 "调低（如 0.20）要求量能高度平稳，信号更少但基底更扎实。默认 0.25。"},
        {"key": "box_width_max", "label": "区间盒宽上限", "type": "float",
         "default": 0.12, "min": 0.08, "max": 0.18, "precision": 2, "step": 0.01,
         "desc": "启动前横盘蓄势阶段价格波动幅度的上限（相对前收盘的比例）。"
                 "调高（如 0.15）允许横盘期间涨跌幅度大，筛选更宽松；调低（如 0.10）"
                 "要求横盘更窄更紧凑，形态更严格。默认 0.12 即振幅不超过 12%。"},
        {"key": "n_max", "label": "调整期超时天数", "type": "int",
         "default": 7, "min": 4, "max": 10, "precision": 0, "step": 1,
         "desc": "放量启动日之后最多等待多少个交易日出现买点，超时就放弃该形态。"
                 "调高（如 10）愿意多等几天，能捕捉回踩慢一点的形态但资金占用久；"
                 "调低（如 5）只接受快速回踩到位的形态，信号更少。默认 7 天。"},
        {"key": "stop_loss", "label": "止损容忍", "type": "float",
         "default": 0.12, "min": 0.05, "max": 0.15, "precision": 2, "step": 0.01,
         "desc": "买入价最多允许回撤多少比例（止损线同时参考启动日开盘价，取更高"
                 "保护位）。调高（如 0.15）能扛更大波动不轻易止损，但单次亏损可能"
                 "更深；调低（如 0.08）止损更早更严格，单次亏损小但容易被洗出去。"
                 "默认 0.12 即最多亏 12%。"},
        {"key": "vol_gate", "label": "量能门口径", "type": "enum",
         "default": "mean", "options": [
             {"value": "mean", "label": "均值门"},
             {"value": "strict", "label": "严格门"},
         ],
         "desc": "蓄势期量能收缩的判定方式：均值门看整段平均量够不够小（宽，信号多）；"
                 "严格门要求每一天的量都低于当天基准（严，信号少但更扎实）。"
                 "不确定就选默认的均值门。"},
    ],
    states=[
        # 三态（design D3）：VP 信号只有触发后才有生命周期，无 watching 态
        {"value": "triggered", "label": "观察中", "color": "warning"},
        {"value": "running", "label": "已启动", "color": "success"},
        {"value": "expired", "label": "已淘汰", "color": "danger"},
    ],
    columns=[
        {"key": "a_date", "label": "A日", "type": "date"},
        {"key": "p_date", "label": "量能峰日", "type": "date"},
        {"key": "entry_mode", "label": "触发方式", "type": "str"},
        {"key": "volume_ratio", "label": "放量倍数", "type": "float"},
        {"key": "spring", "label": "Spring", "type": "str"},
        {"key": "drift_bucket", "label": "净漂移桶", "type": "str"},
        {"key": "wick_box", "label": "影线盒宽", "type": "float"},
        {"key": "box_days", "label": "蓄势天数", "type": "int"},
        # A/B 点与绩效列（strategy-signal-outcome 3.2 + 6.1 D12 返工：价格+涨幅
        # 合并为 price_pct 单列，声明 priceKey/pctKey 双 key，值从行/payload 取；
        # a_date/p_date/entry_ref_price 已有列语义不重复，不再有独立价格 float
        # 列与独立涨幅 pct 列）
        {"key": "a_price", "label": "A日股价", "type": "price_pct",
         "priceKey": "a_close", "pctKey": "a_pct"},
        {"key": "b_date", "label": "B日", "type": "date"},
        {"key": "b_price", "label": "B日股价", "type": "price_pct",
         "priceKey": "b_close", "pctKey": "b_day_pct"},
        {"key": "close_7d_price", "label": "7日股价", "type": "price_pct",
         "priceKey": "close_7d", "pctKey": "ret_7d"},
        {"key": "close_14d_price", "label": "14日股价", "type": "price_pct",
         "priceKey": "close_14d", "pctKey": "ret_14d"},
        {"key": "close_30d_price", "label": "30日股价", "type": "price_pct",
         "priceKey": "close_30d", "pctKey": "ret_30d"},
        {"key": "outcome", "label": "成功判定", "type": "outcome"},
    ],
    # 任务详情积木块（design D5）：summary → per_stock（显式范围）→ signals →
    # kv（基底特征统计：分钟版占比、三桶漂移分布等，detail API 服务端聚合；
    # 绩效准确率统计项由 compute_outcome_kv_stats 通用聚合注入，D6）
    detail_schema=[
        {"type": "summary"},
        {"type": "per_stock"},
        {"type": "signals"},
        {"type": "kv", "title": "基底特征统计", "items": [
            {"key": "total_signals", "label": "信号总数", "fmt": "int"},
            {"key": "minute_ratio", "label": "分钟版占比", "fmt": "str"},
            {"key": "daily_ratio", "label": "日线版占比", "fmt": "str"},
            {"key": "spring_ratio", "label": "Spring 豁免占比", "fmt": "str"},
            {"key": "drift_low_ratio", "label": "净漂移·低桶", "fmt": "str"},
            {"key": "drift_mid_ratio", "label": "净漂移·中桶", "fmt": "str"},
            {"key": "drift_high_ratio", "label": "净漂移·高桶", "fmt": "str"},
            {"key": "avg_wick_box", "label": "平均影线盒宽", "fmt": "float"},
            {"key": "avg_box_days", "label": "平均蓄势天数", "fmt": "float"},
            {"key": "avg_a_ret", "label": "平均 A 日涨幅", "fmt": "str"},
            {"key": "alive_signals", "label": "存活信号数", "fmt": "int"},
            # 绩效准确率统计项（strategy-signal-outcome 3.2/D6）
            {"key": "accuracy", "label": "准确率", "fmt": "pct"},
            {"key": "success_cnt", "label": "成功数", "fmt": "int"},
            {"key": "failed_cnt", "label": "失败数", "fmt": "int"},
            {"key": "pending_cnt", "label": "数据不足数", "fmt": "int"},
            {"key": "avg_ret_7d", "label": "平均7日收益", "fmt": "pct"},
            {"key": "avg_ret_14d", "label": "平均14日收益", "fmt": "pct"},
            {"key": "avg_ret_30d", "label": "平均30日收益", "fmt": "pct"},
        ]},
    ],
))

# 引擎在 vp_entry/engine.py 内自注册（判定内核同包相对导入，无环）
from .vp_entry.engine import VpEntryEngine  # noqa: E402

register_engine("vp_entry", VpEntryEngine())
