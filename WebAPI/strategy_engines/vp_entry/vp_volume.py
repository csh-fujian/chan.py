# -*- coding: utf-8 -*-
"""
虚拟全天量模块：F(t) 分时量能分布 + VP(t)（tasks 2.3）

口径（spec「虚拟全天量 VP 的计算口径」）：
    F(t)  = 该股近 60 个交易日「截至时刻 t 的累计量占全天量比例」的中位数
    VP(t) = 累计量(t) / F(t)
禁止线性外推（累计量 × 240/已开市分钟数）。

样本日过滤（停牌/缺数据日剔除）：
- 只取「当日 bar 数完整」的交易日入样本（BaoStock 5M 全交易日 48 根 bar，
  停牌日整段缺失、bar 数不足的异常日剔除——见 data_availability.md 附录）。
- 当日 bar 数完整但含零成交 bar 的，保留（真实成交状态，非脏数据）。

分钟数据输入为 DataFrame（time_key/open/high/low/close/volume 列，同 kline
表结构）；BaoStock 5 分钟 bar 时间戳从 09:35 起（每 bar 标记区间终点），
「已开市 ≥ 15 分钟」观察窗以 09:35 为第 1 根 bar 计数（即第 4 根 09:50 起
满足 15 分钟观察窗——见 minute_trigger.py，本模块只提供 bar 序号语义）。
"""

import statistics

import pandas as pd

FULL_BARS_PER_DAY = 48  # BaoStock 5M 全交易日 48 根 bar（09:35~11:30 + 13:05~15:00）


def build_f_ratio(history_df: pd.DataFrame, window: int = 60) -> dict[int, float]:
    """由该股近期 5 分钟历史数据构造 F(t)。

    参数：
        history_df: 历史分钟 DataFrame（time_key/open/high/low/close/volume，
                    同 kline 表结构，可含多个交易日，须按时间升序或乱序皆可）
        window:     取最近 window 个「完整样本日」

    返回：
        {bar序号(1起): 累计量占比}，bar 序号语义 = 当日第几根 5 分钟 bar
        （09:35 为第 1 根）。开市不足 15 分钟（序号 < 4）的 F 值也可能极小，
        由 minute_trigger 的观察窗条件兜底（spec Scenario：早盘巨量不误触发）。
    """
    df = history_df
    if df is None or len(df) == 0:
        raise ValueError("history_df 为空，无法构造 F(t)")

    df = df.copy()
    # time_key 形如 "YYYY-MM-DD HH:MM:SS"（kline 表结构）
    df["_date"] = df["time_key"].str.slice(0, 10)
    df["_t"] = df["time_key"].str.slice(11, 16)  # "HH:MM"

    # 按交易日分桶；仅保留 bar 数完整的样本日（停牌/缺数据日剔除）
    day_groups = df.groupby("_date")
    full_days: list[pd.DataFrame] = []
    for _, g in day_groups:
        if len(g) == FULL_BARS_PER_DAY:
            full_days.append(g)
    if not full_days:
        raise ValueError("无 bar 数完整的样本日，无法构造 F(t)")

    # 只取最近 window 个完整样本日
    full_days = full_days[-window:]

    # 每个样本日：按 bar 序号累计量 / 全天量
    samples_by_idx: dict[int, list[float]] = {}
    for g in full_days:
        g = g.sort_values("_t")
        total = g["volume"].sum()
        if total <= 0:
            continue  # 全天零成交（极端停牌态残余），不入样本
        cum = 0.0
        for i, v in enumerate(g["volume"], start=1):
            cum += v
            samples_by_idx.setdefault(i, []).append(cum / total)

    # 各时刻取中位数
    return {i: statistics.median(vs) for i, vs in samples_by_idx.items()}


def cumulative_volumes(day_df: pd.DataFrame) -> list[float]:
    """单日分钟数据的逐 bar 累计量（按时间升序）"""
    df = day_df.sort_values("time_key")
    cums: list[float] = []
    cum = 0.0
    for v in df["volume"]:
        cum += v
        cums.append(cum)
    return cums


def vp_at(cum_volume: float, bar_idx: int, f_ratio: dict[int, float]) -> float | None:
    """某时刻的 VP(t) = 累计量(t) / F(t)。

    bar_idx 为 1 起的当日 bar 序号；F 缺该序号样本时返回 None
    （调用方按「不可得 → 不触发」处理）。
    """
    f = f_ratio.get(bar_idx)
    if f is None or f <= 0:
        return None
    return cum_volume / f


def default_f_ratio() -> dict[int, float]:
    """兜底 F：全天量均匀分布（每根 bar 占 1/48）。

    仅用于无历史分钟数据的测试/诊断场景（回测必须用 build_f_ratio 的
    逐股精确口径，spec 禁止线性外推作为判定口径——本兜底同样不得用于
    回测判定，minute_trigger 会在无 F 时给出诊断标记）。
    """
    return {i: i / FULL_BARS_PER_DAY for i in range(1, FULL_BARS_PER_DAY + 1)}
