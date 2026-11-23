# -*- coding: utf-8 -*-
"""形态检测冒烟测试（chan-pattern-buy-signal 任务 1.1~2.8 验证）。

内存构造 K 线序列（无需联网、无需 PG），逐形态断言命中与否。
运行：.venv/bin/python Debug/test_pattern_detector.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from WebAPI.pattern_detector import (  # noqa: E402
    detect_ascending_triangle, detect_box_breakout, detect_cup_handle,
    detect_head_shoulders, detect_low_flag, detect_rounding_bottom,
    detect_v_reversal, detect_w_bottom, extract_swing_points,
)
from WebAPI.pattern_meta import DETECT_PARAMS, PATTERN_META  # noqa: E402

P = {**DETECT_PARAMS}

_pass = 0
_fail = 0


def check(name, cond):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  [PASS] {name}")
    else:
        _fail += 1
        print(f"  [FAIL] {name}")


class C:
    """最小 K 线桩：detector 只用 .high/.low/.close/.idx 与量。"""

    def __init__(self, idx, high, low, close, vol=1000.0):
        self.idx = idx
        self.high = high
        self.low = low
        self.close = close
        self.trade_info = type("T", (), {"metric": {"volume": vol}})()


def mk_candles(prices, vols=None):
    """收盘价序列 → K 线桩列表（high/low 加固定毛刺，close 即价格）。"""
    out = []
    for i, p in enumerate(prices):
        vol = vols[i] if vols else 1000.0
        out.append(C(i, p * 1.01, p * 0.99, p, vol))
    return out


class Bi:
    """最小笔桩：端点交替（由价格极值序列构造）。"""

    def __init__(self, begin_idx, begin_val, end_idx, end_val, up):
        self._b = (begin_idx, begin_val)
        self._e = (end_idx, end_val)
        self._up = up

    def is_up(self):
        return self._up

    def get_begin_val(self):
        return self._b[1]

    def get_end_val(self):
        return self._e[1]

    def get_begin_klu(self):
        return C(self._b[0], self._b[1] * 1.01, self._b[1] * 0.99, self._b[1])

    def get_end_klu(self):
        return C(self._e[0], self._e[1] * 1.01, self._e[1] * 0.99, self._e[1])


def mk_bis(extremes):
    """极值序列 [(idx, price, is_high)] → 交替笔桩。"""
    bis = []
    for a, b in zip(extremes, extremes[1:]):
        bis.append(Bi(a[0], a[1], b[0], b[1], up=b[2]))
    return bis


# ---------------------------------------------------------------------------
# W底：价格走势 10→7(左底)→9(颈线)→7.1(右底)→突破9→11
# ---------------------------------------------------------------------------

def test_w_bottom():
    print("== W底 ==")
    prices = (
        [10 - 3.0 * (i / 20) for i in range(20)]           # 前置下跌 10→7
        + [7.0 + 0.1 * i for i in range(15)]               # 左底→颈线 7→8.5
        + [8.5 - 0.1 * i for i in range(14)]               # 颈线→右底 8.5→7.1
        + [7.1 + 0.2 * i for i in range(15)]               # 右底回升→突破 7.1→10
        + [10.0] * 5                                        # 站稳
    )
    # 量能：下跌恐慌放量 → 左底~右底缩量 → 突破段放量（突破 crossing 约 idx 63~64，
    # 量比基准是前 5 根（右底回升段低量），突破日给高量）
    vols = [1500.0] * 20 + [800.0] * 29 + [800.0] * 12 + [3000.0] * 3 + [1500.0] * 15
    vols = (vols + [1500.0] * len(prices))[:len(prices)]
    candles = mk_candles(prices, vols)
    # 极值点：(0,10,T)(19,7,F)(34,8.5,T)(48,7.1,F)(63,10,T)
    bis = mk_bis([(0, 10.0, True), (19, 7.0, False), (34, 8.5, True),
                  (48, 7.1, False), (63, 10.0, True)])
    points = extract_swing_points(bis)
    hits = detect_w_bottom(points, candles, P)
    check("W底命中", len(hits) >= 1)
    if hits:
        h = hits[0]
        check("参考线=颈线8.5", abs(h.ref_line[0] - 8.5) < 0.2)
        check("确认K线存在", h.breakout.confirmed)
        check("关键点含双底", {kp["role"] for kp in h.key_points} == {"left_bottom", "neck", "right_bottom"})
        check("置信分≥60", h.score >= 60)

    # 否定1：右底大幅破左底（7.1 → 6.5）
    bis2 = mk_bis([(0, 10.0, True), (19, 7.0, False), (34, 8.5, True),
                   (48, 6.5, False), (63, 10.0, True)])
    hits2 = detect_w_bottom(extract_swing_points(bis2), candles, P)
    check("右底大幅破左底不报", all(h.breakout.confirmed is False or h.key_points[2]["price"] > 6.8 for h in hits2) or len(hits2) == 0)

    # 否定2：突破无量（全程低量，突破日量比 < k → 否决，永不确认）
    vols3 = [600.0] * len(prices)
    candles3 = mk_candles(prices, vols3)
    hits3 = detect_w_bottom(extract_swing_points(bis), candles3, P)
    check("无量突破被否决/不确认", all(not h.breakout.confirmed or h.breakout.veto == "no_volume" for h in hits3))


# ---------------------------------------------------------------------------
# 头肩底
# ---------------------------------------------------------------------------

def test_head_shoulders():
    print("== 头肩底 ==")
    prices = (
        [10 - 0.15 * i for i in range(15)]                 # 10→7.75 下跌
        + [7.75 + 0.25 * i for i in range(8)]              # 左肩 7.75→9.5
        + [9.5 - 0.3 * i for i in range(12)]               # →头 6.9
        + [6.9 + 0.35 * i for i in range(10)]              # →右肩前峰 10.4→10.4? 调整
        + [10.4 - 0.2 * i for i in range(8)]               # 右肩 10.4→8.8
        + [8.8 + 0.3 * i for i in range(15)]               # 突破 8.8→13.3
        + [13.0] * 5
    )
    n = len(prices)
    # 量比基准 = 突破日前 5 根均量；突破 crossing 约在 idx 61，故 15..60 缩量、61 起放量
    vols = [1500.0] * 15 + [800.0] * (61 - 15) + [3000.0] * (n - 61)
    vols = (vols + [3000.0] * n)[:n]
    candles = mk_candles(prices, vols)
    # 极值：(0,10,T)(14,7.75,F)(22,9.5,T)(34,6.9,F)(44,10.4,T)(52,8.8,F)(67,13,T)
    bis = mk_bis([(0, 10.0, True), (14, 7.75, False), (22, 9.5, True),
                  (34, 6.9, False), (44, 10.4, True), (52, 8.8, False),
                  (67, 13.0, True)])
    points = extract_swing_points(bis)
    hits = detect_head_shoulders(points, candles, P)
    check("头肩底命中", len(hits) >= 1)
    if hits:
        h = hits[0]
        check("参考线≈颈线(两峰连线)", abs(h.ref_line[0] - 9.5) < 1.2)
        check("确认成立", h.breakout.confirmed)


# ---------------------------------------------------------------------------
# 箱体突破：9~10 箱体震荡 3 次
# ---------------------------------------------------------------------------

def test_box_breakout():
    print("== 箱体突破 ==")
    prices = (
        [12 - 0.15 * i for i in range(10)]                 # 12→10.5 下跌
        + [9.0 + (0.5 if i % 10 < 5 else -0.5) * (1 if i % 2 else 0) for i in range(0)]  # placeholder
    )
    prices = [12 - 0.15 * i for i in range(10)]
    # 箱体：9.2 与 10.2 之间来回 40 根
    for i in range(40):
        prices.append(9.7 + (0.5 if (i // 10) % 2 == 0 else -0.5))
    prices += [10.5 + 0.3 * i for i in range(12)]          # 突破 →14
    prices += [14.0] * 5
    vols = [1500.0] * 10 + [700.0] * 40 + [3000.0] * 12 + [1200.0] * 5
    candles = mk_candles(prices, vols)
    # 极值：(0,12,T)(9,10.5,F)(箱体四个来回点)(49,10.2→14,T)...
    extremes = [(0, 12.0, True), (9, 10.5, False),
                (14, 10.2, True), (19, 9.2, False), (24, 10.2, True),
                (29, 9.2, False), (34, 10.2, True), (39, 9.2, False),
                (44, 10.2, True), (49, 9.3, False), (65, 14.1, True)]
    bis = mk_bis(extremes)
    points = extract_swing_points(bis)
    hits = detect_box_breakout(points, candles, P)
    check("箱体突破命中", len(hits) >= 1)
    if hits:
        h = hits[0]
        check("参考线=上轨", abs(h.ref_line[0] - 10.2) < 0.3)


# ---------------------------------------------------------------------------
# 上升三角形
# ---------------------------------------------------------------------------

def test_ascending_triangle():
    print("== 上升三角形 ==")
    prices = [10 - 0.2 * i for i in range(10)]             # 下跌 10→8
    # 三角：顶 9.0 恒定，低点抬升 7.6→7.8→8.0→8.2
    lows = [7.6, 7.8, 8.0, 8.2]
    highs = [9.0, 9.0, 9.0]
    seq = []
    for i in range(4):
        seq.append(lows[i])
        if i < 3:
            seq.append(highs[i])
    # 展开为渐变序列
    prices2 = []
    cur = 8.0
    targets = []
    for i in range(4):
        targets.append((lows[i], True))
        if i < 3:
            targets.append((highs[i], False))
    for t, is_low in targets:
        step = (t - cur) / 6
        for _ in range(6):
            cur += step
            prices2.append(cur)
    prices += prices2
    prices += [9.3 + 0.3 * i for i in range(10)]           # 突破
    prices += [12.0] * 5
    n = len(prices)
    # 整理段量能递减（「三角形整理内部成交量逐步萎缩」）：800 → 递减到 400
    tri_vols = [800.0 - 10 * j for j in range(len(prices2))]
    vols = [1500.0] * 10 + tri_vols + [3000.0] * 10 + [1200.0] * 5
    vols = (vols + [1200.0] * n)[:n]
    candles = mk_candles(prices, vols)
    # 极值下标：10 起，每段 6 根
    ext = [(0, 10.0, True), (9, 8.0, False)]
    idx = 10
    for t, is_low in targets:
        idx += 6
        ext.append((idx, t, not is_low))  # 低点是笔终点=False?  is_high=False
    # 修正：低点 is_high=False，高点 True
    ext = [(0, 10.0, True), (9, 8.0, False)]
    idx = 10
    for t, is_low in targets:
        idx += 6
        ext.append((idx, t, not is_low))
    ext.append((idx + 30, 12.0, True))
    bis = mk_bis(ext)
    points = extract_swing_points(bis)
    hits = detect_ascending_triangle(points, candles, P)
    check("上升三角形命中", len(hits) >= 1)


# ---------------------------------------------------------------------------
# 低位旗形
# ---------------------------------------------------------------------------

def test_low_flag():
    print("== 低位旗形 ==")
    prices = [6 + 0.05 * i for i in range(10)]             # 低位爬升
    prices += [6.5 + 0.35 * i for i in range(10)]          # 旗杆 6.5→10
    # 旗面：向下倾斜 10→9.0（斜率 ≈ -0.005，落在通道斜率带内）
    flag = []
    for i in range(20):
        flag.append(10 - 0.05 * i + (0.25 if i % 2 == 0 else -0.25))
    prices += flag
    prices += [9.2 + 0.3 * i for i in range(10)]           # 突破 9.2→11.9
    prices += [11.9] * 5
    vols = [800.0] * 10 + [3000.0] * 10 + [600.0] * 20 + [3000.0] * 10 + [1200.0] * 5
    candles = mk_candles(prices, vols)
    # 旗面需要 ≥2 个低点与 ≥1 个高点（旗面内部小幅摆动）
    ext = [(0, 6.0, False), (19, 10.0, True), (26, 9.7, False), (30, 9.95, True),
           (38, 9.0, False), (48, 11.9, True)]
    bis = mk_bis(ext)
    points = extract_swing_points(bis)
    hits = detect_low_flag(points, candles, P)
    check("低位旗形命中", len(hits) >= 1)


# ---------------------------------------------------------------------------
# V型反转
# ---------------------------------------------------------------------------

def test_v_reversal():
    print("== V型反转 ==")
    prices = [12 - 0.25 * i for i in range(20)]            # 12→7 急跌
    prices += [7.0] * 2
    prices += [8.5 + 1.2 * i for i in range(4)]            # 放量长阳 7→12.1
    prices += [12.0] * 5
    vols = [1200.0] * 20 + [900.0] * 2 + [4000.0] * 4 + [1200.0] * 5
    candles = mk_candles(prices, vols)
    ext = [(0, 12.0, True), (21, 7.0, False), (27, 12.1, True)]
    bis = mk_bis(ext)
    points = extract_swing_points(bis)
    hits = detect_v_reversal(points, candles, P)
    check("V型反转命中", len(hits) >= 1)
    # 无量反弹否决
    vols2 = [1200.0] * 20 + [900.0] * 2 + [700.0] * 4 + [1200.0] * 5
    candles2 = mk_candles(prices, vols2)
    hits2 = detect_v_reversal(extract_swing_points(bis), candles2, P)
    check("无量反弹否决", all(not h.breakout.confirmed for h in hits2) or all(h.breakout.veto == "no_volume" for h in hits2 if h.breakout.confirmed))


# ---------------------------------------------------------------------------
# 圆弧底
# ---------------------------------------------------------------------------

def test_rounding_bottom():
    print("== 圆弧底 ==")
    import math
    prices = [11 - 0.1 * i for i in range(15)]             # 11→9.5 下跌
    # 锅底：抛物线 60 根，谷底 8.0 在中间
    arc = [8.0 + 1.5 * ((i - 30) / 30) ** 2 for i in range(61)]
    prices += arc
    prices += [9.5 + 0.15 * i for i in range(12)]          # 突破 9.5→11.3
    prices += [11.3] * 6
    n = len(prices)
    vols = [2000.0] * 15 + [600.0] * 61 + [3000.0] * 12 + [1200.0] * 6
    vols = (vols + [1200.0] * n)[:n]
    candles = mk_candles(prices, vols)
    hits = detect_rounding_bottom(candles, P)
    check("圆弧底命中", len(hits) >= 1)
    # V 型不命中：急跌急涨尖底
    prices_v = [10 - 0.3 * i for i in range(15)] + [5.5 + 0.3 * i for i in range(15)] + [10.0] * 30
    candles_v = mk_candles(prices_v)
    hits_v = detect_rounding_bottom(candles_v, P)
    check("V型尖底不报圆弧底", len(hits_v) == 0)


# ---------------------------------------------------------------------------
# 杯柄
# ---------------------------------------------------------------------------

def test_cup_handle():
    print("== 杯柄 ==")
    prices = [10.5] * 45                                    # 杯口平台（前窗 + 扫描起点余量）
    # 杯体：10.5 → 8.0（-24%）→ 10.5，圆滑 U（50 根）
    import math
    for i in range(50):
        t = i / 49
        prices.append(10.5 - 2.5 * math.sin(math.pi * t) ** 1.2)
    prices += [10.4 - 0.02 * i for i in range(8)]           # 柄部 10.4→10.26
    prices += [10.8 + 0.2 * i for i in range(10)]           # 突破
    prices += [12.5] * 38
    n = len(prices)
    vols = [1500.0] * 45 + [700.0] * 50 + [500.0] * 8 + [3000.0] * 10 + [3000.0] * 38
    vols = (vols + [3000.0] * n)[:n]
    candles = mk_candles(prices, vols)
    hits = detect_cup_handle(candles, P)
    check("杯柄命中", len(hits) >= 1)


# ---------------------------------------------------------------------------
# meta 覆盖（任务 1.2 验证）
# ---------------------------------------------------------------------------

def test_meta():
    print("== PATTERN_META ==")
    buy_keys = {"w_bottom", "head_shoulders", "box_breakout", "ascending_triangle",
                "low_flag", "v_reversal", "rounding_bottom", "cup_handle"}
    # chan-pattern-sell-signal：META 扩至 13 键，卖向 5 键带 direction='sell'
    sell_keys = {"dark_cloud_cover", "shooting_star", "hanging_man",
                 "high_engulfing", "high_engulfing_gap"}
    check("meta 覆盖买点 8 键", buy_keys <= set(PATTERN_META.keys()))
    check("meta 覆盖卖向 5 键", sell_keys <= set(PATTERN_META.keys())
          and all(PATTERN_META[k].get("direction") == "sell" for k in sell_keys))
    check("买点键无 direction 标记", all("direction" not in PATTERN_META[k] for k in buy_keys))
    check("每形态 cautions 非空", all(m["cautions"] for m in PATTERN_META.values()))
    check("买点形态评分三轴齐全", all(
        set(PATTERN_META[k]["scoring"].keys()) >= {"struct", "vol", "confirm"}
        for k in buy_keys))
    check("卖向形态评分为结构/量能/位置三轴", all(
        set(PATTERN_META[k]["scoring"].keys()) >= {"struct", "vol", "position"}
        for k in sell_keys))


if __name__ == "__main__":
    test_meta()
    test_w_bottom()
    test_head_shoulders()
    test_box_breakout()
    test_ascending_triangle()
    test_low_flag()
    test_v_reversal()
    test_rounding_bottom()
    test_cup_handle()
    print(f"\n结果: PASS={_pass} FAIL={_fail}")
    sys.exit(1 if _fail else 0)
