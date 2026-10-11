# -*- coding: utf-8 -*-
"""
B 日分钟级触发扫描（tasks 2.4）

对 B 日逐 5 分钟 bar 检查 spec 阶段四的 4 个触发条件，取首个全部满足的 bar t*：

1. 累计涨幅区间：r(t) = C_t/C_{B-1}-1 ∈ [0.5%, 3%]
2. 分钟放量：最近 5 分钟成交量 ≥ 3 × 前 20 分钟内 5 分钟窗口均量
   （「最近 5 分钟」= 当前 bar 的成交量；「前 20 分钟」= 当前 bar 之前 4 根 bar）
3. 虚拟全天量：VP(t) = 累计量(t)/F(t) ≥ 2 × mean(V_i, i∈D'末3日)
4. 最小观察窗：已开市 ≥ 15 分钟（09:35 为第 1 根 bar 计数，即第 4 根 09:50 起）

放弃：r(t) 越过 3% 上限后仍未触发，或收盘（最后一根 bar）仍未触发 → 返回 None。
买价 = 触发 bar 收盘价。同一 A 日至多一信号由 signal_rule 状态机保证（本函数
单次调用只返回首个触发）。

分钟数据输入为 DataFrame（time_key/open/high/low/close/volume 列，同 kline 表
结构）。BaoStock 5 分钟 bar 时间戳从 09:35 起（每 bar 标记区间终点）。
"""

import pandas as pd

from .params import VPParams
from .vp_volume import cumulative_volumes, vp_at

# 观察窗：已开市 ≥ 15 分钟 → bar 序号（1 起）≥ 4（09:35 第 1 根，09:50 第 4 根）
OBSERVE_START_IDX = 4


def scan_minute_trigger(
    day_df: pd.DataFrame,
    b_prev_close: float,
    dp_end_mean_vol: float,
    params: VPParams | None = None,
    f_ratio: dict[int, float] | None = None,
):
    """扫描 B 日分钟数据，返回首个触发 bar。

    返回：
        (bar_time_key, 触发bar收盘价, vp与阈值之比) 或 None（放弃）

    参数：
        day_df:          B 日 5 分钟 DataFrame（kline 表结构）
        b_prev_close:    B-1 日收盘价（r(t) 分母）
        dp_end_mean_vol: D' 末 3 日均量（VP 门槛的基准量）
        params:          判定参数（默认 VPParams()）
        f_ratio:         该股 F(t)（vp_volume.build_f_ratio 产出，bar 序号 1 起）；
                         None 时用均匀分布兜底（仅测试/诊断，回测必须传真实 F，
                         见 vp_volume.default_f_ratio 的注释）
    """
    p = params or VPParams()
    fx = p.fixed
    if f_ratio is None:
        from .vp_volume import default_f_ratio
        f_ratio = default_f_ratio()

    df = day_df.sort_values("time_key").reset_index(drop=True)
    if len(df) == 0 or b_prev_close <= 0:
        return None

    vols = [float(v) for v in df["volume"]]
    closes = [float(c) for c in df["close"]]
    cums = cumulative_volumes(df)
    times = [str(t) for t in df["time_key"]]

    for i in range(len(df)):
        idx1 = i + 1  # 当日 bar 序号（1 起）
        r_t = closes[i] / b_prev_close - 1.0

        # 条件 4：最小观察窗（已开市 ≥ 15 分钟）
        if idx1 < OBSERVE_START_IDX:
            # 观察窗未到，仍需跟踪涨幅是否越线（越线即放弃，即使未到观察窗）
            if r_t > fx.r_high:
                return None
            continue

        # 条件 1：累计涨幅区间
        if r_t > fx.r_high:
            # r(t) 越过上限仍未触发 → 当日放弃（spec：「涨幅越过上限前未触发」）
            return None
        if r_t < fx.r_low:
            continue

        # 条件 2：分钟放量（最近 5 分钟量 ≥ 3 × 前 20 分钟 5 分钟窗均量）
        # 「前 20 分钟」= 当前 bar 之前的 4 根 bar（每根 5 分钟）；开市不足 20 分钟
        # 时按窗口内实际存在的 bar 取均值（spec 未定义不足 20 分钟的口径，按字面
        # 「前 20 分钟内」取实际存在 bar），无前序 bar 则不满足
        if i == 0:
            continue
        prev = vols[max(0, i - 4):i]
        prev_mean = sum(prev) / len(prev)
        if vols[i] < fx.minute_vol_mult * prev_mean:
            continue

        # 条件 3：VP(t) ≥ 2 × D' 末 3 日均量
        vp = vp_at(cums[i], idx1, f_ratio)
        if vp is None:
            continue
        if vp < fx.vp_mult * dp_end_mean_vol:
            continue

        # 全部满足：首个触发 bar，买价 = 该 bar 收盘价
        vp_ratio = vp / (fx.vp_mult * dp_end_mean_vol) if dp_end_mean_vol > 0 else None
        return times[i], closes[i], vp_ratio

    # 收盘仍未触发 → 放弃
    return None
