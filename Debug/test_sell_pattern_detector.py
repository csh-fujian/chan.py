# -*- coding: utf-8 -*-
"""顶部看跌形态检测器冒烟测试（chan-pattern-sell-signal 任务 1.8）。

内存构造 K 线（duck-typing，无需联网/PG），覆盖 spec「顶部形态检测判据」
的场景：5 形态各一个成立样例、判据不足不报、非高位丢弃、一字板剔除。

运行：PYTHONIOENCODING=utf-8 PYTHONPATH=. .venv/Scripts/python.exe Debug/test_sell_pattern_detector.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from WebAPI.pattern_detector import (  # noqa: E402
    DETECT_PARAMS, detect_bearish_engulfing, detect_dark_cloud_cover,
    detect_hanging_man, detect_shooting_star, run_detection,
)
from WebAPI.pattern_meta import PATTERN_META  # noqa: E402

PATTERN_SELL_TYPES = {k for k, v in PATTERN_META.items() if v.get("direction") == "sell"}


class FakeTime:
    def toDateStr(self, sep="-"):
        return "2026-01-01"

    def toTimeStr(self, sep=":"):
        return "10:00:00"

    def __str__(self):
        return "2026-01-01 10:00:00"


class Bar2:
    """测试 K 线桩：OHLCV duck-typing（pattern_detector 只访问这些属性）。"""

    def __init__(self, o, h, l, c, v=1000.0):
        self.open, self.high, self.low, self.close = o, h, l, c
        self.time = FakeTime()
        self.trade_info = type("TI", (), {"metric": {"volume": v}})()


def _mk(closes, vols=None, spread=0.5):
    """由收盘价序列构造 K 线：open=前收盘、high/low 含 spread 抖动。

    vols 缺省一律 1000 均量（形态日放量由调用方单独追加 Bar2）。
    """
    vols = vols or [1000.0] * len(closes)
    out = []
    prev = closes[0]
    for i, c in enumerate(closes):
        o = prev
        out.append(Bar2(o, max(o, c) + spread, min(o, c) - spread, c, vols[i]))
        prev = c
    return out


def _rally_bars(n=40, base=8.0, top=10.0):
    """前置上涨趋势（8→10，涨幅 25% > prior_rally_pct），无量变化。"""
    closes = [base + (top - base) * i / (n - 1) for i in range(n)]
    return closes, _mk(closes)


def test_dark_cloud_cover():
    P = DETECT_PARAMS
    # 上涨至 10.0 后：T1 阳 10.0→11.0（+10%），T2 高开 11.2 收 10.3（深入前实体 70%）
    closes, bars = _rally_bars()
    bars += [Bar2(10.0, 11.2, 9.9, 11.0, v=1000.0),
             Bar2(11.2, 11.3, 10.2, 10.3, v=3000.0)]
    hits = detect_dark_cloud_cover([], bars, P)
    assert len(hits) == 1, f"乌云盖顶应命中 1 次，实际 {len(hits)}"
    h = hits[0]
    assert h.direction == "sell" and h.pattern_type == "dark_cloud_cover"
    assert h.breakout.confirm_idx == len(bars) - 1
    assert h.score > 0 and h.qual
    assert h.breakout.volume_ratio >= P["sell_vol_ratio_k"]
    print("  [ok] 乌云盖顶成立样例：score", h.score, h.qual)

    # 覆盖不足 1/3 → 不报：T2 收 10.9（深度 10%）
    closes, bars2 = _rally_bars()
    bars2 += [Bar2(10.0, 11.2, 9.9, 11.0, v=1000.0),
              Bar2(11.2, 11.3, 10.8, 10.9, v=3000.0)]
    assert not detect_dark_cloud_cover([], bars2, P), "覆盖不足1/3不应命中"
    print("  [ok] 覆盖不足1/3不报")
    return True


def test_shooting_star():
    P = DETECT_PARAMS
    # 上涨至 10.0 后：小实体长上影 o=10.1 c=10.0（实体0.1）hi=11.2（上影1.1=11倍）lo=9.98（下影0.02）
    closes, bars = _rally_bars()
    bars.append(Bar2(10.1, 11.2, 9.98, 10.0, v=3000.0))
    hits = detect_shooting_star([], bars, P)
    assert len(hits) == 1, f"射击之星应命中 1 次，实际 {len(hits)}"
    h = hits[0]
    assert h.direction == "sell" and h.breakout.confirm_idx == len(bars) - 1
    print("  [ok] 射击之星成立样例：score", h.score, h.qual)

    # 无量佐证 → 否决 no_volume + 分数封顶 59
    closes, bars2 = _rally_bars()
    bars2.append(Bar2(10.1, 11.2, 9.98, 10.0, v=200.0))
    h2 = detect_shooting_star([], bars2, P)
    assert len(h2) == 1 and h2[0].veto == "no_volume", "无量应标记 no_volume 否决"
    assert h2[0].score <= 59, f"否决封顶 59，实际 {h2[0].score}"
    print("  [ok] 无量否决封顶：score", h2[0].score)
    return True


def test_hanging_man():
    P = DETECT_PARAMS
    # 镜像：小实体长下影 o=10.1 c=10.0（实体0.1）lo=8.9（下影1.1=11倍）hi=10.12（上影0.02）
    closes, bars = _rally_bars()
    bars.append(Bar2(10.1, 10.12, 8.9, 10.0, v=3000.0))
    hits = detect_hanging_man([], bars, P)
    assert len(hits) == 1, f"吊颈线应命中 1 次，实际 {len(hits)}"
    h = hits[0]
    assert h.direction == "sell" and h.pattern_type == "hanging_man"
    print("  [ok] 高位吊颈线成立样例：score", h.score, h.qual)
    return True


def test_bearish_engulfing():
    P = DETECT_PARAMS
    # 上涨至 10.0 后：T1 阳 10.0→11.0，T2 高开 11.1 收 9.9 → 完全吞没（普通吞没）
    closes, bars = _rally_bars()
    bars += [Bar2(10.0, 11.1, 9.9, 11.0, v=1000.0),
             Bar2(11.1, 11.2, 9.8, 9.9, v=3000.0)]
    hits = detect_bearish_engulfing([], bars, P)
    assert len(hits) == 1, f"阴包阳应命中 1 次，实际 {len(hits)}"
    h = hits[0]
    assert h.pattern_type == "high_engulfing", f"普通吞没类型，实际 {h.pattern_type}"
    print("  [ok] 高位阴包阳成立样例：score", h.score, h.qual)

    # 穿头破脚：T2 开 11.6（>T1.high=11.1）收 9.4（<T1.low=9.9），同 K 线只报 gap
    closes, bars3 = _rally_bars()
    bars3 += [Bar2(10.0, 11.1, 9.9, 11.0, v=1000.0),
              Bar2(11.6, 11.6, 9.4, 9.4, v=3000.0)]
    hits3 = detect_bearish_engulfing([], bars3, P)
    assert len(hits3) == 1 and hits3[0].pattern_type == "high_engulfing_gap", \
        f"应报穿头破脚，实际 {[x.pattern_type for x in hits3]}"
    assert hits3[0].score >= h.score, "穿头破脚分数应不低于普通吞没"
    print("  [ok] 高位穿头破脚成立且优先：score", hits3[0].score)
    return True


def test_position_filter():
    P = DETECT_PARAMS
    # 非高位（横盘、无前置上涨）出现同样 K 线 → 丢弃
    closes = [10.0 + 0.01 * (i % 3) for i in range(40)]
    bars = _mk(closes, spread=0.05)
    bars.append(Bar2(10.1, 10.12, 8.9, 10.0, v=3000.0))   # 长下影
    assert not detect_hanging_man([], bars, P), "非高位不应命中吊颈线"
    bars2 = _mk(closes, spread=0.05)
    bars2.append(Bar2(10.1, 11.2, 9.98, 10.0, v=3000.0))  # 长上影
    assert not detect_shooting_star([], bars2, P), "非高位不应命中射击之星"
    bars3 = _mk(closes, spread=0.05)
    bars3 += [Bar2(10.0, 10.2, 9.9, 11.0, v=1000.0),
              Bar2(11.1, 11.2, 9.8, 9.9, v=3000.0)]
    assert not detect_bearish_engulfing([], bars3, P), "非高位不应命中阴包阳"
    print("  [ok] 非高位丢弃")
    return True


def test_doji_excluded():
    P = DETECT_PARAMS
    # 一字板（o=h=l=c）不作为形态 K 线
    closes, bars = _rally_bars()
    bars.append(Bar2(11.0, 11.0, 11.0, 11.0, v=3000.0))
    assert not detect_hanging_man([], bars, P), "一字板不应命中"
    assert not detect_shooting_star([], bars, P), "一字板不应命中"
    assert not detect_dark_cloud_cover([], bars, P), "一字板不应命中"
    assert not detect_bearish_engulfing([], bars, P), "一字板不应命中"
    print("  [ok] 一字板剔除")
    return True


def test_run_detection_integration():
    # run_detection 统一出口：卖向命中带 direction='sell'
    closes, bars = _rally_bars()
    bars += [Bar2(10.0, 11.1, 9.9, 11.0, v=1000.0),
             Bar2(11.1, 11.2, 9.8, 9.9, v=3000.0)]  # 阴包阳

    kl = bars  # _klus 对原始列表桩直接透传（兜底分支）

    class FakeKL:
        bi_list = []

        def __iter__(self):
            return iter(bars)

    hits = run_detection(FakeKL().bi_list, FakeKL())
    sell = [h for h in hits if h.direction == "sell"]
    assert sell, "run_detection 应产出卖向命中"
    for h in sell:
        assert h.pattern_type in PATTERN_SELL_TYPES, f"未知卖向类型 {h.pattern_type}"
    buy = [h for h in hits if h.direction == "buy"]
    for h in buy:
        assert h.pattern_type not in PATTERN_SELL_TYPES
    print("  [ok] run_detection 卖向接线：", [h.pattern_type for h in sell])
    return True


def main():
    print("== 顶部看跌形态检测器冒烟 ==")
    test_dark_cloud_cover()
    test_shooting_star()
    test_hanging_man()
    test_bearish_engulfing()
    test_position_filter()
    test_doji_excluded()
    test_run_detection_integration()
    print("== 全部通过 ==")


if __name__ == "__main__":
    main()
