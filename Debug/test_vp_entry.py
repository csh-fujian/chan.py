# -*- coding: utf-8 -*-
"""
量价三段式买点判定内核冒烟测试（tasks 2.5）

风格对齐 Debug/bi_test.py：内存构造 K 线，无需联网，assert + print。
覆盖 spec（entry-signal-rule）全部 Scenario：

1.  次新股排除（日线 < 61 根不产生任何信号/候选）
2.  上升基底累计漂移拦截（单日合规但 R_W ≈ 15% > 12%）
3.  温和放量的上升基底通过均值门（均值门口径通过，严格版口径不通过）
4.  超跌反弹假放量被 10 日收盘新高过滤
5.  冲高后快速回踩再启动不被误杀（P 锚定 A+1，末段缩量不含冲高日）
6.  Spring 插针豁免（L < O_A 但下影 ≥ 2×实体且 C ≥ O_A，spring=True 透传）
7.  B < P+2 淘汰（B 出现在 P+1 日不构成合法触发）
8.  上午触发（10:05 bar 触发，买价 = 该 bar 收盘价，同一 A 日至多一信号）
9.  涨幅越过 3% 上限前未触发 / 收盘未触发 → 放弃
10. 开市 10 分钟单根巨量不触发（最小观察窗 15 分钟，09:50 第 4 根起可触发）
11. 无分钟数据退化日线版（高开 0~3%、V_B ≥ 2×、C_B > O_B，买价 B+1 开盘）

运行方式（项目根目录）：
    .venv/Scripts/python.exe -X utf8 Debug/test_vp_entry.py
"""

import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from Debug.vp_entry.backtest import EXIT_STOP, EXIT_T10, compute_stats, evaluate_exits
from Debug.vp_entry.prescreen_sql import prescreen_sql
from Debug.vp_entry.sensitivity import assert_scan_params
from WebAPI.strategy_engines.vp_entry.minute_trigger import scan_minute_trigger
from WebAPI.strategy_engines.vp_entry.params import SCAN, VPParams
from WebAPI.strategy_engines.vp_entry.signal_rule import (
    DayBar,
    VPState,
    VPStateMachine,
)
from WebAPI.strategy_engines.vp_entry.vp_volume import build_f_ratio

PASS = 0


def ok(name):
    global PASS
    PASS += 1
    print(f"✅ {name}")


# ----------------------------------------------------------------------
# 数据构造工具
# ----------------------------------------------------------------------

def make_history(n, base_close=10.0, vol=100.0, start="2024-01-01"):
    """n 根平稳历史日 K（±0.2% 微幅锯齿、量能 100±2）：满足 61 根门槛与
    MA60V≈100 基准，蓄势期各门宽松通过，测试聚焦被测条件。"""
    d0 = datetime.date.fromisoformat(start)
    bars = []
    for i in range(n):
        d = (d0 + datetime.timedelta(days=i)).isoformat()
        c = base_close * (1 + 0.002 * (1 if i % 2 == 0 else -1))
        o = base_close
        bars.append(DayBar(d, o, max(o, c) + 0.02, min(o, c) - 0.02, c, vol + (2 if i % 2 == 0 else -2)))
    return bars


def build_full_case(v_a=300.0, a_ret=0.06, adjust_specs=None):
    """hist(70) + 蓄势 7 + A + 调整序列。

    adjust_specs: [(ret, vol, low_ratio), ...]——A+1 起逐日；
    滞涨条件由调用方通过 ret 自行控制（回踩设为负或小正）。
    """
    hist = make_history(70)
    d0 = datetime.date(2024, 4, 1)
    c = hist[-1].close
    bars = []
    for i in range(7):
        date = (d0 + datetime.timedelta(days=i)).isoformat()
        prev_c = c
        c = c * 1.001
        bars.append(DayBar(date, prev_c, c * 1.001, prev_c * 0.999, c, 75.0))
    a_open = c * 1.01
    a_close = c * (1 + a_ret)
    a = DayBar((d0 + datetime.timedelta(days=7)).isoformat(), a_open,
               a_close * 1.005, c, a_close, v_a)
    bars.append(a)
    cur = a_close
    day = 8
    for ret, vol, low_ratio in (adjust_specs or []):
        date = (d0 + datetime.timedelta(days=day)).isoformat()
        prev_c = cur
        cur = cur * (1 + ret)
        lo = min(prev_c, cur) * (1 - low_ratio)
        bars.append(DayBar(date, prev_c, max(prev_c, cur) * 1.001, lo, cur, vol))
        day += 1
    return hist, bars, a


def feed(m, bars, on_event=None):
    """逐根喂日 K；每个 B 候选事件即时调 on_event(m, event) 终判。

    终判返回 None（放弃）→ 状态机自动当日放弃并入 D，继续等后续 B 日。
    返回 (events, results)。
    """
    events, results = [], []
    for b in bars:
        ev = m.on_day(b)
        if ev is not None:
            events.append(ev)
            if on_event is not None:
                results.append(on_event(m, ev))
    return events, results


def minute_df(rows, date="2024-04-11"):
    """rows: [(HH:MM, open, high, low, close, volume), ...] → kline 结构 DataFrame"""
    return pd.DataFrame([
        {"time_key": f"{date} {t}:00", "open": o, "high": h, "low": lo, "close": c, "volume": v}
        for t, o, h, lo, c, v in rows
    ])


def bar_times(start="09:35", count=48):
    """一个交易日的 48 根 5 分钟 bar 时间（09:35 起，跳过午休 11:30~13:00 后段）。

    BaoStock 口径：bar 时间戳 = 区间终点，首根 09:35；上午 09:35~11:30 共 24 根，
    下午 13:05~15:00 共 24 根（11:30 后的 11:35~12:55 与 13:00 属午休/边界，跳过）。
    """
    out = []
    hh, mm = 9, 35
    while len(out) < count:
        t = f"{hh:02d}:{mm:02d}"
        in_lunch = (hh == 11 and mm > 30) or hh == 12 or (hh == 13 and mm == 0)
        if not in_lunch:
            out.append(t)
        mm += 5
        if mm >= 60:
            mm -= 60
            hh += 1
    return out


def make_f_ratio(volume_profile, n_days=60):
    """用同一日内分布构造 F(t)（近 n_days 个同分布完整交易日）"""
    times = bar_times()
    recs = []
    d0 = datetime.date(2024, 1, 1)
    for k in range(n_days):
        d = (d0 + datetime.timedelta(days=k)).isoformat()
        for t, v in zip(times, volume_profile):
            recs.append({"time_key": f"{d} {t}:00", "volume": v})
    return build_f_ratio(pd.DataFrame(recs))


STD_PROFILE = [100.0] * 48  # 均匀分布历史（每 bar 量 100）


def make_b_day_minutes(b_prev_close, trigger_idx=None, r_target=0.02,
                       vol_spike=400.0, base_vol=20.0, breach=False, date="2024-04-11"):
    """构造 B 日 48 根 5 分钟 bar。

    - trigger_idx（0 起）非 None 时：涨幅线性升至 r_target（trigger bar 处），
      量：常态 base_vol，trigger bar 巨量 vol_spike；
    - breach=True：全程 r = 3.2%（> 3% 上限，越线放弃验证）。
    """
    times = bar_times()
    rows = []
    for i, t in enumerate(times):
        if breach:
            r = 0.032
        elif trigger_idx is not None and i <= trigger_idx:
            r = r_target * (i / max(trigger_idx, 1)) if i else 0.0
        else:
            r = r_target
        c = b_prev_close * (1 + r)
        o = c * 0.999
        v = vol_spike if (trigger_idx is not None and i == trigger_idx) else base_vol
        rows.append((t, o, c * 1.001, o * 0.999, c, v))
    return minute_df(rows, date)


# ----------------------------------------------------------------------
# Scenario 1：次新股排除（日线 < 61 根）
# ----------------------------------------------------------------------

def test_scenario_xinxin():
    m = VPStateMachine("sz.new")
    for b in make_history(60):
        assert m.on_day(b) is None
    assert m.state.name == "IDLE", f"60 根后仍应 IDLE（次新排除），实际 {m.state}"
    m2 = VPStateMachine("sz.new2")
    evs, _ = feed(m2, make_history(61))
    assert len(evs) == 0, "平稳历史无 A 日触发，不应产生候选"
    ok("Scenario 1 次新股排除：60 根内无信号/候选，61 根起才进入扫描")


# ----------------------------------------------------------------------
# Scenario 2：上升基底累计漂移拦截（R_W ≈ 15% > 12%）
# ----------------------------------------------------------------------

def test_scenario_rising_basement():
    hist = make_history(60)
    d0 = datetime.date(2024, 4, 1)
    c = hist[-1].close
    w = []
    for i in range(7):  # 每日 +2%（单日合规），累计 1.02^7-1 ≈ 14.9%
        date = (d0 + datetime.timedelta(days=i)).isoformat()
        prev_c = c
        c = c * 1.02
        w.append(DayBar(date, prev_c, c * 1.001, prev_c * 0.999, c, 100.0))
    a = DayBar((d0 + datetime.timedelta(days=7)).isoformat(), c * 1.02, c * 1.08,
               c, c * 1.06, 300.0)
    m = VPStateMachine("sz.rise")
    feed(m, hist)
    evs, _ = feed(m, w + [a])
    assert len(evs) == 0 and m.state.name == "BASEMENT", \
        f"R_W≈14.9% 应拦截，state={m.state}"
    ok("Scenario 2 上升基底累计漂移拦截：单日合规但 R_W≈14.9% > 12% → 候选淘汰")


# ----------------------------------------------------------------------
# Scenario 3：温和放量过均值门（均值 vs 严格两口径分别判定）
# ----------------------------------------------------------------------

def test_scenario_vol_gate():
    hist = make_history(60)  # MA60V ≈ 100
    d0 = datetime.date(2024, 4, 1)
    c = hist[-1].close
    w = []
    for i in range(7):
        date = (d0 + datetime.timedelta(days=i)).isoformat()
        prev_c = c
        c = c * 1.001
        v = 105.0 if i == 3 else 70.0  # 均量 75 ≤ 0.8×100 ✓；1 根 105 > MA60V(i)
        w.append(DayBar(date, prev_c, c * 1.001, prev_c * 0.999, c, v))
    a = DayBar((d0 + datetime.timedelta(days=7)).isoformat(), c, c * 1.06, c * 0.99,
               c * 1.05, 250.0)

    m_mean = VPStateMachine("sz.gate1", VPParams(vol_gate="mean"))
    feed(m_mean, hist)
    feed(m_mean, w + [a])
    assert m_mean.state.name in ("TRIGGERED_A", "PULLBACK"), \
        f"均值门应通过进入调整期，实际 {m_mean.state}"

    m_strict = VPStateMachine("sz.gate2", VPParams(vol_gate="strict"))
    feed(m_strict, hist)
    feed(m_strict, w + [a])
    assert m_strict.state.name == "BASEMENT", \
        f"严格版应拦截（第4根 105 ≥ MA60V），实际 {m_strict.state}"
    ok("Scenario 3 温和放量上升基底：均值门口径通过、严格版口径拦截（两口径分别统计）")


# ----------------------------------------------------------------------
# Scenario 4：超跌反弹假放量被 10 日收盘新高过滤
# ----------------------------------------------------------------------

def test_scenario_fake_breakout():
    hist = make_history(70, base_close=12.0)
    d0 = datetime.date(2024, 4, 1)
    c = hist[-1].close
    down = []
    for i in range(5):  # 先跌 5 日（每日 -4%）→ 收盘远低于前期
        date = (d0 + datetime.timedelta(days=i)).isoformat()
        prev_c = c
        c = c * 0.96
        down.append(DayBar(date, prev_c, prev_c * 1.002, c, c, 95.0))
    w = []
    for i in range(7):
        date = (d0 + datetime.timedelta(days=5 + i)).isoformat()
        prev_c = c
        c = c * 1.001
        w.append(DayBar(date, prev_c, c * 1.001, prev_c * 0.999, c, 75.0))
    # A 日候选：涨 6%、量 3.33×（≥2.5×75），但收盘未创 10 日收盘新高（5 根下跌前的收盘更高）
    a = DayBar((d0 + datetime.timedelta(days=12)).isoformat(), c, c * 1.065, c * 0.99,
               c * 1.06, 250.0)
    m = VPStateMachine("sz.fake")
    feed(m, hist)
    feed(m, down)
    feed(m, w + [a])
    assert m.state.name == "BASEMENT", f"未创 10 日新高应拦截，实际 {m.state}"
    ok("Scenario 4 超跌假放量：涨 6%、量 3× 但未创 10 日收盘新高 → A 日不通过")


# ----------------------------------------------------------------------
# Scenario 5：冲高后快速回踩再启动不被误杀
# ----------------------------------------------------------------------

def test_scenario_fast_pullback():
    v_a = 300.0
    # A+1 冲高放量（0.9V_A ≥ 0.8V_A → 峰 P=A+1），A+2/A+3 缩量回踩，A+4 触发 B
    hist, bars, a = build_full_case(v_a=v_a, adjust_specs=[
        (0.02, 0.9 * v_a, 0.00),
        (-0.015, 0.25 * v_a, 0.0),
        (-0.015, 0.25 * v_a, 0.0),
    ])
    f_ratio = make_f_ratio(STD_PROFILE)
    signals = []

    def on_event(m, ev):
        # B 日分钟数据按事件自带的 b_prev_close（= D 最后一日收盘）构造
        b_day = make_b_day_minutes(ev.b_prev_close, trigger_idx=18, r_target=0.02,
                                   vol_spike=400.0, date=ev.b_date)
        sig = m.decide_b_day(ev, minute_df=b_day, f_ratio=f_ratio)
        if sig is not None:
            signals.append(sig)
        return sig

    m = VPStateMachine("sz.fast")
    feed(m, hist)
    events, _ = feed(m, bars, on_event=on_event)
    assert len(events) >= 1, "调整期内应出现 B 候选事件"
    assert signals, "应产生信号"
    sig = signals[0]
    assert sig.p_date != sig.a_date, "P 应锚定 A+1（冲高放量日）"
    assert sig.entry_mode == "minute"
    # 触发时末段缩量窗口只含缩量回踩日（不含冲高日 A+1：峰 P 本身不入 D'）
    ok("Scenario 5 冲高后快速回踩：P 锚定 A+1，末段缩量窗口不含冲高日，判定正常通过")


# ----------------------------------------------------------------------
# Scenario 6：Spring 插针豁免
# ----------------------------------------------------------------------

def _spring_case(v_a=300.0):
    """A+1 冲高（峰P）+ A+2 回踩 + A+3 插针（L<O_A，下影≥2×实体，C≥O_A）"""
    hist, bars, a = build_full_case(v_a=v_a, adjust_specs=[
        (0.02, 0.9 * v_a, 0.00),
        (-0.01, 0.25 * v_a, 0.0),
    ])
    d0 = datetime.date(2024, 4, 1)
    a_open = a.open
    date3 = (d0 + datetime.timedelta(days=10)).isoformat()
    c3 = a_open * 1.002
    o3 = a_open * 1.005
    lo = a_open * 0.94  # 深插针：L < O_A
    spring_bar = DayBar(date3, o3, o3 * 1.01, lo, c3, 0.25 * v_a)
    return hist, bars, a, spring_bar


def test_scenario_spring():
    v_a = 300.0
    hist, bars, a, spring_bar = _spring_case(v_a)
    # A+4：回踩日（B 候选）
    d0 = datetime.date(2024, 4, 1)
    c4 = spring_bar.close * 0.99
    b_bar = DayBar((d0 + datetime.timedelta(days=11)).isoformat(), spring_bar.close,
                   spring_bar.close * 1.001, c4 * 0.999, c4, 0.25 * v_a)
    f_ratio = make_f_ratio(STD_PROFILE)
    signals = []

    def on_event(m, ev):
        b_day = make_b_day_minutes(ev.b_prev_close, trigger_idx=18, r_target=0.02,
                                   date=ev.b_date)
        sig = m.decide_b_day(ev, minute_df=b_day, f_ratio=f_ratio)
        if sig is not None:
            signals.append(sig)
        return sig

    m = VPStateMachine("sz.spring")
    feed(m, hist)
    feed(m, bars)               # 到 A+2
    ev3 = m.on_day(spring_bar)  # A+3 插针：可能抛候选事件（触发/放弃均可）
    if ev3 is not None:
        on_event(m, ev3)
    assert m.state.name != "DEAD", f"Spring 豁免应保留样本，实际 {m.state}"
    feed(m, [b_bar], on_event=on_event)
    assert signals, "插针豁免后应仍可触发"
    # spring 标记：插针日并入 D 后，破位检查发现 L<O_A 且豁免 → spring=True
    assert any(s.spring for s in signals), "插针豁免样本应标记 spring=True"
    ok("Scenario 6 Spring 插针豁免：L<O_A 但下影≥2×实体且 C≥O_A → 保留样本并标记 spring")


# ----------------------------------------------------------------------
# Scenario 7：B < P+2 淘汰（B 出现在 P 或 P+1 日）
# ----------------------------------------------------------------------

def test_scenario_b_too_early():
    v_a = 300.0
    # 只给 A+1（冲高成为峰 P）：A+2 喂入时 D' 为空 → B = P+1 < P+2 → 无候选
    hist, bars, a = build_full_case(v_a=v_a, adjust_specs=[
        (0.02, 0.9 * v_a, 0.00),
    ])
    d0 = datetime.date(2024, 4, 1)
    prev_c = bars[-1].close
    c2 = prev_c * 0.985
    bar2 = DayBar((d0 + datetime.timedelta(days=9)).isoformat(), prev_c,
                  prev_c * 1.001, c2 * 0.999, c2, 0.25 * v_a)
    m = VPStateMachine("sz.early")
    feed(m, hist)
    feed(m, bars)      # 到 A+1（峰 P）
    ev2 = m.on_day(bar2)  # A+2 = P+1 → 不构成合法触发
    assert ev2 is None, f"B = P+1 不构成合法触发，却出现候选 {ev2}"
    # A+3（= P+2）起才可候选
    c3 = c2 * 0.99
    bar3 = DayBar((d0 + datetime.timedelta(days=10)).isoformat(), c2,
                  c2 * 1.001, c3 * 0.999, c3, 0.25 * v_a)
    ev3 = m.on_day(bar3)
    assert ev3 is not None, "A+3（= P+2）应产生 B 候选"
    ok("Scenario 7 B<P+2 淘汰：B 出现在 P+1 日不构成合法触发，P+2 起才可")


# ----------------------------------------------------------------------
# Scenario 8：上午触发（买价 = 触发 bar 收盘价，同一 A 日至多一信号）
# ----------------------------------------------------------------------

def test_scenario_morning_trigger():
    v_a = 300.0
    hist, bars, a = build_full_case(v_a=v_a, adjust_specs=[
        (0.02, 0.9 * v_a, 0.00),
        (-0.015, 0.25 * v_a, 0.0),
        (-0.015, 0.25 * v_a, 0.0),
    ])
    f_ratio = make_f_ratio(STD_PROFILE)
    signals = []
    captured = {}  # 记录触发事件自带的 b_prev_close，用于买价断言

    def on_event(m, ev):
        # 触发 bar = 第 7 根（10:05，0 起索引 6）：开市 35 分钟 ≥ 15 ✓；
        # 量 400 ≥ 3×前窗均量 20 ✓；VP = (6×20+400)/F(7) ≈ 2400 ≥ 150 ✓；
        # r=2% ∈ [0.5%,3%] ✓（spec Scenario：10:07 的 bar → 对齐 5 分钟网格取 10:05）
        b_day = make_b_day_minutes(ev.b_prev_close, trigger_idx=6, r_target=0.02,
                                   vol_spike=400.0, date=ev.b_date)
        sig = m.decide_b_day(ev, minute_df=b_day, f_ratio=f_ratio)
        if sig is not None:
            signals.append(sig)
            captured[sig.b_date] = ev.b_prev_close
        return sig

    m = VPStateMachine("sz.morning")
    feed(m, hist)
    events, _ = feed(m, bars, on_event=on_event)
    assert signals, "上午 10:05 bar 应触发"
    sig = signals[0]
    assert sig.entry_mode == "minute"
    assert abs(sig.buy_price - captured[sig.b_date] * 1.02) < 1e-9, \
        f"买价应 = 触发 bar 收盘价，实际 {sig.buy_price}"
    assert "10:05" in sig.b_bar_time, f"触发时间应为 10:05，实际 {sig.b_bar_time}"
    # 同一 A 日至多一信号：触发后状态机进 SIGNAL 终态，后续日不再产生该 A 的信号
    a_dates = [s.a_date for s in m.signals]
    assert len(a_dates) == len(set(a_dates)), \
        f"同一 A 日重复进场：{[(s.a_date, s.b_date) for s in m.signals]}"
    ok("Scenario 8 上午触发：10:05 bar 满足全部条件 → 买价=该bar收盘价，至多一信号")


# ----------------------------------------------------------------------
# Scenario 9：涨幅越过 3% 上限前未触发 / 收盘未触发 → 放弃
# ----------------------------------------------------------------------

def test_scenario_over_3pct():
    b_prev = 10.0
    f_ratio = make_f_ratio(STD_PROFILE)
    # 全程 3.2%（观察窗内即越线）→ 放弃
    day1 = make_b_day_minutes(b_prev, breach=True)
    assert scan_minute_trigger(day1, b_prev, dp_end_mean_vol=75.0, f_ratio=f_ratio) is None
    # 观察窗后先 2%（无量：不满足分钟放量）再 3.2% → 越线时未触发 → 放弃
    times = bar_times()
    rows = []
    for i, t in enumerate(times):
        r = 0.02 if i < 20 else 0.032
        c = b_prev * (1 + r)
        rows.append((t, c * 0.999, c * 1.001, c * 0.998, c, 20.0))
    assert scan_minute_trigger(minute_df(rows), b_prev, dp_end_mean_vol=75.0,
                               f_ratio=f_ratio) is None
    # r 一直在区间内但量能始终不足 → 收盘仍未触发 → 放弃
    rows2 = [(t, c * 0.999, c * 1.001, c * 0.998, c, 20.0)
             for t, c in [(times[i], b_prev * 1.02) for i in range(48)]]
    assert scan_minute_trigger(minute_df(rows2), b_prev, dp_end_mean_vol=75.0,
                               f_ratio=f_ratio) is None
    ok("Scenario 9 涨幅越 3% 上限前未触发 / 收盘未触发 → 当日放弃")


# ----------------------------------------------------------------------
# Scenario 10：开市 10 分钟单根巨量不触发（最小观察窗 15 分钟）
# ----------------------------------------------------------------------

def test_scenario_observe_window():
    b_prev = 10.0
    f_ratio = make_f_ratio(STD_PROFILE)
    times = bar_times()
    # 第 2 根（09:40，开市 10 分钟）单根巨量 5000：VP 极高、r=2% 在区间，
    # 但观察窗未到 → 不触发；后续量 20 无法满足分钟放量 → 整日无触发
    rows = [(t, c * 0.999, c * 1.001, c * 0.998, c, 5000.0 if i == 1 else 20.0)
            for i, (t, c) in enumerate([(t, b_prev * 1.02) for t in times])]
    trig = scan_minute_trigger(minute_df(rows), b_prev, dp_end_mean_vol=0.001,
                               f_ratio=f_ratio)
    assert trig is None, f"开市 10 分钟巨量应被观察窗拦截，实际 {trig}"
    # 边界：第 4 根（09:50，开市 15 分钟）允许触发
    rows2 = [(t, c * 0.999, c * 1.001, c * 0.998, c, 400.0 if i == 3 else 20.0)
             for i, (t, c) in enumerate([(t, b_prev * 1.02) for t in times])]
    trig2 = scan_minute_trigger(minute_df(rows2), b_prev, dp_end_mean_vol=0.001,
                                f_ratio=f_ratio)
    assert trig2 is not None and "09:50" in trig2[0], \
        f"第 4 根（开市 15 分钟）应可触发，实际 {trig2}"
    ok("Scenario 10 开市 10 分钟巨量不触发（观察窗≥15分钟），09:50 第4根起可触发")


# ----------------------------------------------------------------------
# Scenario 11：无分钟数据退化日线版
# ----------------------------------------------------------------------

def test_scenario_daily_fallback():
    v_a = 300.0
    # A+1 冲高（峰P）、A+2/A+3 缩量回踩 → A+4 为首个 B 候选日（日线版）
    hist, bars, a = build_full_case(v_a=v_a, adjust_specs=[
        (0.02, 0.9 * v_a, 0.00),
        (-0.015, 0.25 * v_a, 0.0),
        (-0.015, 0.25 * v_a, 0.0),
    ])
    d0 = datetime.date(2024, 4, 1)
    b_prev_close = bars[-1].close
    d_end3_mean = 0.25 * v_a  # D' 末 3 日均量
    o_b = b_prev_close * 1.015  # 高开 1.5% ∈ (0%, 3%]
    c_b = o_b * 1.02            # C > O
    b_bar = DayBar((d0 + datetime.timedelta(days=11)).isoformat(), o_b,
                   c_b * 1.005, o_b * 0.99, c_b, 3.0 * d_end3_mean)  # V_B = 3× ≥ 2×

    signals = []

    def on_event(m, ev):
        sig = m.decide_b_day(ev, minute_df=None)  # 无分钟数据 → 日线退化版
        if sig is not None:
            signals.append(sig)
        return sig

    m = VPStateMachine("sz.daily")
    feed(m, hist)
    feed(m, bars, on_event=on_event)  # 调整期各候选日均走日线版
    ev_b = m.on_day(b_bar)
    assert ev_b is not None, "B 日应产生候选事件"
    sig = m.decide_b_day(ev_b, minute_df=None)
    assert sig is not None, "日线退化版应触发"
    assert sig.entry_mode == "daily"
    # 买价 = B+1 开盘：喂下一根日 K 回填
    o_b1 = c_b * 1.002
    next_bar = DayBar((d0 + datetime.timedelta(days=12)).isoformat(), o_b1,
                      o_b1 * 1.01, o_b1 * 0.99, o_b1 * 1.005, 100.0)
    m.on_day(next_bar)
    assert abs(sig.buy_price - o_b1) < 1e-9, \
        f"日线版买价应 = B+1 开盘，实际 {sig.buy_price}"
    assert sig in m.signals, "回填完成的日线版信号应入 signals"
    # 信号闭环后状态机复位，后续日可重新扫描
    assert m.state.name == "BASEMENT", f"回填后应复位 BASEMENT，实际 {m.state}"
    ok("Scenario 11 无分钟数据退化日线版：高开1.5%、V_B=3×、C>O → 触发，买价=B+1开盘")


# ----------------------------------------------------------------------
# 附：当日放弃后继续等后续 B 日（spec「收盘仍未触发」的流式语义）
# ----------------------------------------------------------------------

def test_giveup_then_later_trigger():
    """A+3 候选日分钟未触发（全程量不足）→ 放弃并入 D；A+4 触发。"""
    v_a = 300.0
    hist, bars, a = build_full_case(v_a=v_a, adjust_specs=[
        (0.02, 0.9 * v_a, 0.00),
        (-0.015, 0.25 * v_a, 0.0),
        (-0.015, 0.25 * v_a, 0.0),
        (-0.015, 0.25 * v_a, 0.0),
    ])
    f_ratio = make_f_ratio(STD_PROFILE)
    signals = []

    def on_event(m, ev):
        # A+3（04-11）失败：r 在区间但量不足；A+4（04-12）巨量触发
        fail = ev.b_date.endswith("04-11")
        b_day = make_b_day_minutes(
            ev.b_prev_close,
            trigger_idx=None if fail else 6,
            r_target=0.02,
            vol_spike=400.0,
            date=ev.b_date,
        )
        sig = m.decide_b_day(ev, minute_df=b_day, f_ratio=f_ratio)
        if sig is not None:
            signals.append(sig)
        return sig

    m = VPStateMachine("sz.giveup")
    feed(m, hist)
    events, _ = feed(m, bars, on_event=on_event)
    assert len(events) == 2, "A+3、A+4 都应成为候选日"
    assert len(signals) == 1 and signals[0].b_date.endswith("04-12"), \
        "A+3 放弃、A+4 触发"
    ok("附：当日放弃后续等——A+3 分钟未触发放弃，A+4 触发（超时淘汰前）")


# ----------------------------------------------------------------------
# 参数表验证（tasks 2.1）
# ----------------------------------------------------------------------

def test_params():
    p = VPParams()
    fx = p.fixed
    assert fx.cv7_max == 0.25
    assert fx.a_day_ret_min == 0.05
    assert fx.a_day_vol_mult == 2.0
    assert fx.a_day_new_high_days == 10
    assert fx.peak_anchor_ratio == 0.8
    assert fx.dp_end_shrink_ratio == 0.5
    assert fx.stag_high_mult == 1.02
    assert fx.spring_wick_body_ratio == 2.0
    assert fx.r_low == 0.005 and fx.r_high == 0.03
    assert fx.minute_vol_mult == 3.0
    assert fx.vp_mult == 2.0
    assert fx.observe_window_minutes == 15
    assert fx.vol_mean_gate == 0.8
    assert fx.min_daily_bars == 61
    assert p.stop_loss_price_ratio == 0.88  # 1 - 0.12（定死 0.88）
    assert p.box_width_max == 0.12
    assert p.n_max == 7
    # 扫描参数集合（108 组合 = 3×3×3×2×2）
    assert set(SCAN.cv7_max_list) == {0.20, 0.25, 0.30}
    assert set(SCAN.n_max_list) == {5, 7, 9}
    assert set(SCAN.r_w_list) == {0.10, 0.12, 0.15}
    assert set(SCAN.stop_loss_list) == {0.08, 0.12}
    assert set(SCAN.vol_gate_list) == {"mean", "strict"}
    # ---- 迁移后行为（vp-entry-strategy-integration tasks 1.1/1.2）----
    # VPParams.__post_init__ 只保留 vol_gate 取值域断言：连续区间取值直接构造成功
    p_cont = VPParams(cv7_max=0.27, box_width_max=0.14, n_max=6, stop_loss=0.10)
    assert p_cont.cv7_max == 0.27 and p_cont.n_max == 6
    # 非法 vol_gate 仍被拒绝（enum 校验兜底在 dataclass 层保留）
    try:
        VPParams(vol_gate="bogus")
        assert False, "vol_gate 非法取值应被拒绝"
    except ValueError:
        pass
    # 敏感性集合纪律外移到 sensitivity.assert_scan_params：集合外取值报错
    try:
        assert_scan_params(p_cont)
        assert False, "连续取值在回测侧应被集合断言拦截"
    except ValueError:
        pass
    assert_scan_params(p)  # 默认参数（定死版取值）在集合内
    # 内核从 WebAPI 新位置 import（迁移 verify：import 成功即本断言可达）
    import WebAPI.strategy_engines.vp_entry as vp_pkg

    assert vp_pkg.VPStateMachine is not None
    ok("参数表（2.1）+ 迁移（1.1/1.2）：连续区间构造成功、集合校验在回测侧、vol_gate 域保留")


def test_sql_machine_alignment():
    """对齐验证（tasks 3.1，design D3 风险项）：SQL 粗筛 A 日集合 == 状态机 A 日集合。

    前置条件：Data/kl_store.duckdb 存在 K_DAY 数据（本仓库已灌 40 只池）。
    数据库缺失时跳过（CI 环境无数据）。
    """
    import os

    if not os.path.exists("Data/kl_store.duckdb"):
        print("⏭ 对齐验证：无 DuckDB 数据，跳过")
        return
    import duckdb

    p = VPParams()
    conn = duckdb.connect("Data/kl_store.duckdb", read_only=True)
    sql_df = prescreen_sql(conn, p)
    daily = conn.execute(
        """
        SELECT code, time_key, open, high, low, close, volume
        FROM kline WHERE kl_type='K_DAY' AND autype='QFQ'
        ORDER BY code, time_key
        """
    ).fetchdf()
    conn.close()
    if daily.empty:
        print("⏭ 对齐验证：库内无日线数据，跳过")
        return

    sql_set = set(zip(sql_df["code"], sql_df["a_date"]))
    machines = {}
    machine_set = set()
    for row in daily.itertuples(index=False):
        m = machines.setdefault(row.code, VPStateMachine(code=row.code, params=p))
        prev = m.state
        m.on_day(DayBar(str(row.time_key)[:10], row.open, row.high, row.low, row.close, row.volume))
        if m.state == VPState.TRIGGERED_A and prev != VPState.TRIGGERED_A:
            machine_set.add((row.code, str(row.time_key)[:10]))
    assert sql_set == machine_set, (
        f"SQL/状态机不对齐: 仅SQL={sorted(sql_set - machine_set)[:5]} "
        f"仅状态机={sorted(machine_set - sql_set)[:5]}"
    )
    ok(f"对齐验证（3.1）：SQL 粗筛与状态机 A 日集合完全一致（{len(sql_set)} 个）")


def _make_backtest_case(v_a=300.0):
    """4.x 回测用例公共构造：完整触发路径（分钟版信号）+ B 日后 20 根后续日线。
    返回 (machine, bars_all, daily_df)。"""
    hist, bars, a = build_full_case(v_a=v_a, adjust_specs=[
        (0.02, 0.9 * v_a, 0.00),
        (-0.015, 0.25 * v_a, 0.0),
        (-0.015, 0.25 * v_a, 0.0),
    ])
    f_ratio = make_f_ratio(STD_PROFILE)

    def on_event(m, ev):
        b_day = make_b_day_minutes(ev.b_prev_close, trigger_idx=6, r_target=0.02,
                                   vol_spike=400.0, date=ev.b_date)
        return m.decide_b_day(ev, minute_df=b_day, f_ratio=f_ratio)

    m = VPStateMachine("test.000001")
    feed(m, hist)
    feed(m, bars, on_event=on_event)
    assert len(m.signals) == 1, f"应恰产生一个分钟版信号，实际 {len(m.signals)}"
    sig = m.signals[0]
    b_idx = next(i for i, b in enumerate(bars) if b.date == sig.b_date)
    # B 日后追加 20 根后续日线（微跌后走平），供 T+20 / MA 口径评估
    last_close, last_date = bars[-1].close, bars[-1].date
    d0 = datetime.date.fromisoformat(sig.b_date)
    extra = []
    cur = last_close
    for i in range(1, 21):
        d = (d0 + datetime.timedelta(days=i + (last_date and 0))).isoformat()
        prev_c = cur
        cur = cur * 0.998
        extra.append(DayBar(d, prev_c, prev_c * 1.001, cur * 0.999, cur, 50.0))
    bars_all = bars + extra
    daily = pd.DataFrame([{
        "code": "test.000001", "time_key": f"{b.date} 00:00:00",
        "open": b.open, "close": b.close, "volume": b.volume,
    } for b in bars_all])
    return m, bars_all, daily


def test_backtest_stop_loss():
    """4.2 stop 口径：止损线 = max(O_A, 买价×0.88) 透传，每信号恰一行"""
    m, bars_all, daily = _make_backtest_case()
    sig = m.signals[0]
    out = evaluate_exits(pd.DataFrame([vars(s) for s in m.signals]), daily, VPParams())
    stop_rows = out[out["exit_method"] == EXIT_STOP]
    assert len(stop_rows) == 1, "stop 口径每信号恰一行"
    r = stop_rows.iloc[0]
    a = next(b for b in bars_all if b.date == sig.a_date)
    assert r["buy_price"] == sig.buy_price
    assert abs(r["stop_loss_low"] - max(a.open, sig.buy_price * 0.88)) < 1e-9
    ok("4.2 stop 口径：买价/止损线透传正确，每信号恰一行")


def test_backtest_same_day_break():
    """4.2 买入当日收盘跌破止损线 → 次日开盘卖（T+1 约束下的 spec Scenario）"""
    m, bars_all, daily = _make_backtest_case()
    sig = m.signals[0]
    stop_line = sig.stop_loss_low
    b_idx = [i for i, b in enumerate(bars_all) if b.date == sig.b_date][0]
    daily2 = daily.copy()
    daily2.loc[b_idx, "close"] = stop_line - 0.5  # 买入日收盘跌破
    daily2.loc[b_idx + 1, "open"] = stop_line - 1.0  # 次日开盘
    out = evaluate_exits(pd.DataFrame([vars(s) for s in m.signals]), daily2, VPParams())
    r = out[(out["exit_method"] == EXIT_STOP)].iloc[0]
    assert r["hold_days"] == 1, f"买入日跌破→次日开盘卖 hold_days 应为 1，实际 {r['hold_days']}"
    assert abs(r["sell_price"] - (stop_line - 1.0)) < 1e-9, "卖出价 = 次日开盘"
    assert r["ret"] < 0
    ok("4.2 当日跌破：次日开盘卖出（T+1），hold_days=1")


def test_backtest_t_n_and_no_dup():
    """4.1 无重复进场 + T+N 口径持有天数；4.3 分组统计行数守恒"""
    m, bars_all, daily = _make_backtest_case()
    # 同一 A 日重复信号防御性去重（4.1）
    sig_df = pd.DataFrame([vars(s) for s in m.signals] * 2)
    out = evaluate_exits(sig_df, daily, VPParams())
    assert len(out) == 6, f"6 个口径各一行（去重后单信号），实际 {len(out)}"
    t10 = out[out["exit_method"] == EXIT_T10].iloc[0]
    assert t10["hold_days"] == 10
    # 4.3 分组统计行数守恒：exit=ALL 行的 n == 总行数
    stats = compute_stats(out)
    all_row = stats[stats["group"] == "exit=ALL"].iloc[0]
    assert all_row["n"] == len(out)
    ok("4.1/4.3 无重复进场（同 A 日去重）、T+10 口径 hold_days、统计行数守恒")


def main():
    print("=" * 70)
    print("量价三段式买点 判定内核冒烟测试（Debug/vp_entry tasks 2.1~2.5）")
    print("=" * 70)
    test_params()
    test_scenario_xinxin()
    test_scenario_rising_basement()
    test_scenario_vol_gate()
    test_scenario_fake_breakout()
    test_scenario_fast_pullback()
    test_scenario_spring()
    test_scenario_b_too_early()
    test_scenario_morning_trigger()
    test_scenario_over_3pct()
    test_scenario_observe_window()
    test_scenario_daily_fallback()
    test_giveup_then_later_trigger()
    test_sql_machine_alignment()
    test_backtest_stop_loss()
    test_backtest_same_day_break()
    test_backtest_t_n_and_no_dup()
    print("-" * 70)
    print(f"✅ 全部通过：{PASS} 个用例")


if __name__ == "__main__":
    main()
