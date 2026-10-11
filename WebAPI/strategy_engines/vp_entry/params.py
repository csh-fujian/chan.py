# -*- coding: utf-8 -*-
"""
量价三段式买点 V3 参数常量表（tasks 2.1）

单一参数来源，供状态机精判（signal_rule.py）与 SQL 粗筛共用，禁止散落魔数。
参数分两类：
    - 定死参数：spec 明确「定死不做扫描」，全程序唯一取值
    - 扫描参数：spec 标注敏感性集合，回测做参数扫描；默认值 = 定死版取值

对应 spec: openspec/changes/volume-price-entry-rule/specs/entry-signal-rule/spec.md

运行方式（项目根目录）：
    .venv/Scripts/python.exe -X utf8 -c "from WebAPI.strategy_engines.vp_entry.params import VPParams; print(VPParams())"
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FixedParams:
    """定死参数（不参与扫描，全程序唯一取值）"""

    # ---- 蓄势期（W = A-7 … A-1，共 7 根日 K） ----
    cv7_max: float = 0.25              # CV7 = std(V)/mean(V) ≤ 0.25（ddof=1）
    single_day_ret_limit: float = 0.05  # 单日防异动 |ret_i| ≤ 5%
    vol_mean_gate: float = 0.8         # 均值门 mean(V_i) ≤ 0.8 × MA60V(A-1)
    # 严格版逐日门 ∀i∈W: V_i < MA60V(i) 无阈值参数，仅作为 A/B 对照口径开关

    # ---- A 日 ----
    a_day_ret_min: float = 0.05        # ret_A ≥ 5%
    a_day_vol_mult: float = 2.0        # V_A ≥ 2 × mean(V_i, i∈W)（2026-10-11 口径修订：原 2.5 下调）
    a_day_new_high_days: int = 10      # C_A > max(C_{A-10} … C_{A-1}) 10 日收盘新高

    # ---- 调整期 ----
    peak_anchor_ratio: float = 0.8     # 量能峰锚定 V_i ≥ 0.8×V_A（定死，不做扫描）
    dp_end_shrink_ratio: float = 0.5   # 末段缩量 mean(V, D'末min(3,|D'|)日) ≤ 0.5×V_A
    stag_high_mult: float = 1.02       # 滞涨 C_i ≤ max(H_A, H_P)×1.02

    # ---- B 日分钟触发 ----
    r_low: float = 0.005               # r(t) ∈ [0.5%, 3%]
    r_high: float = 0.03
    minute_vol_mult: float = 3.0       # 最近 5 分钟量 ≥ 3 × 前 20 分钟 5 分钟窗均量
    vp_mult: float = 2.0               # VP(t) ≥ 2 × mean(V_i, i∈D'末3日)
    observe_window_minutes: int = 15   # 已开市 ≥ 15 分钟（09:35 为第 1 根 bar）

    # ---- Spring 豁免 ----
    spring_wick_body_ratio: float = 2.0  # 下影线 ≥ 2 × 实体

    # ---- 数据门槛 ----
    min_daily_bars: int = 61           # 次新排除：日线不足 61 根排除（MA60V 不可得）
    ma60v_window: int = 60             # MA60V 窗口

    # ---- 日线退化版（无分钟数据） ----
    daily_open_low: float = 0.0        # 高开 0% < O_B/C_{B-1}-1 ≤ 3%
    daily_open_high: float = 0.03
    daily_vol_mult: float = 2.0        # V_B ≥ 2 × mean(V_i, i∈D'末3日)

    # ---- F(t) 虚拟量 ----
    f_window_days: int = 60            # F(t) 样本取近 60 个交易日

    # ---- 其他 ----
    basement_len: int = 7              # 蓄势期长度（固定 7 根）
    daily_end_vol_days: int = 3        # D' 末段缩量窗口（≤3 日）


@dataclass(frozen=True)
class ScanParams:
    """扫描参数（spec 标注敏感性集合；默认值 = 定死版取值）"""

    cv7_max_list: tuple = (0.20, 0.25, 0.30)           # CV7 敏感性
    n_max_list: tuple = (5, 7, 9)                      # 调整期超时 N
    r_w_list: tuple = (0.10, 0.12, 0.15)               # 区间盒宽敏感性
    stop_loss_list: tuple = (0.08, 0.12)               # 止损容忍
    vol_gate_list: tuple = ("mean", "strict")           # 量能门 {严格,均值}


@dataclass(frozen=True)
class VPParams:
    """V3 判定参数总表 = 定死参数 + 可扫描参数（组合扫描用）

    可覆盖扫描参数（默认取定死值）取值域说明：
    - 任务侧（VpEntryEngine）：连续区间，由 params_schema 的 min/max 声明与
      validate_params 把关（本 dataclass 不再做离散集合校验）；
    - 回测侧（sensitivity.py）：离散敏感性集合，由 assert_scan_params 显式
      断言（回测纪律留在回测世界）。
    """

    # 可覆盖的扫描参数（默认取定死值）
    cv7_max: float = 0.25                # CV7 门（敏感性 {0.20, 0.25, 0.30}；任务侧连续区间 [0.15, 0.35]）
    box_width_max: float = 0.12          # R_W 区间盒宽（敏感性 {10%, 12%, 15%}；任务侧连续区间 [0.08, 0.18]）
    n_max: int = 7                       # 调整期超时 N（敏感性 {5, 7, 9}；任务侧连续区间 [4, 10]）
    stop_loss: float = 0.12              # 止损容忍（0.88 = 1-0.12，定死版取值；敏感性 {0.08, 0.12}；任务侧连续区间 [0.05, 0.15]）
    vol_gate: str = "mean"               # 量能门版本：mean=均值门 / strict=逐日严格门

    # 定死参数整体携带（dataclass 组合，单一来源）
    fixed: FixedParams = field(default_factory=FixedParams)

    def __post_init__(self):
        # 敏感性集合断言已外移至回测侧（Debug/vp_entry/sensitivity.py 的
        # assert_scan_params，design D1/D2）：任务侧参数为连续取值域
        # （params_schema 声明 min/max），此处只保留 vol_gate 取值域断言
        # （enum 校验在 strategy_engines.validate_params 前移把关）。
        if self.vol_gate not in ("mean", "strict"):
            raise ValueError(f"vol_gate 必须是 mean/strict，收到 {self.vol_gate!r}")

    @property
    def stop_loss_price_ratio(self) -> float:
        """止损价系数（定死版 0.88 = 1 - 0.12）"""
        return 1.0 - self.stop_loss

    def describe(self) -> str:
        return (
            f"VPParams(cv7={self.cv7_max}, box={self.box_width_max:.0%}, "
            f"N={self.n_max}, stop={self.stop_loss:.2f}, gate={self.vol_gate})"
        )


# 扫描参数集合（回测敏感性扫描用：3×3×3×2×2 = 108 组合）
SCAN = ScanParams()


if __name__ == "__main__":
    print(VPParams())
