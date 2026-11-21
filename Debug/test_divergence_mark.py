# -*- coding: utf-8 -*-
"""chan-recent-divergence-mark 任务 1.1 验证：背驰判定辅助函数四分支单测。

mock CBi 序列（不跑完整 CChan，只验证判定逻辑）：
  1. 正常判定（背驰成立 / 不成立）
  2. inf 阈值 → None
  3. 力度不可比（前值为 0 / 缺失）→ None
  4. 多指标 AND（一项不背驰 → False）
  5. 段级量能类回退 peak（不抛 unsupport macd_algo）
"""
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ChanAnalyse.Common.CEnum import MACD_ALGO  # noqa: E402
from WebAPI.serializer import cal_last_divergence  # noqa: E402


class FakeBi:
    """最小 CBi 桩：方向 + cal_macd_metric 查表。"""

    def __init__(self, is_down, metrics):
        self._down = is_down
        self._metrics = metrics  # {MACD_ALGO: value}

    def is_down(self):
        return self._down

    def cal_macd_metric(self, algo, is_reverse):
        return self._metrics.get(algo)


class FakeSeg(FakeBi):
    """段桩：带 start_bi 属性（is_seg 判定依据）。"""

    def __init__(self, is_down, metrics):
        super().__init__(is_down, metrics)
        self.start_bi = SimpleNamespace()


class FakeConf:
    def __init__(self, rate, algos):
        self.divergence_rate = rate
        self.macd_algos = algos


def test_normal():
    # 序列 UP, DOWN, UP；末尾 UP 力度 5 vs 相邻同向前一 UP（items[-3]）力度 10
    # → 5 <= 0.9*10 背驰。注意中间 DOWN 笔的力度不参与比较。
    lst = [FakeBi(False, {MACD_ALGO.PEAK: 10}),
           FakeBi(True, {MACD_ALGO.PEAK: 999}),  # 中间反向笔，力度应被忽略
           FakeBi(False, {MACD_ALGO.PEAK: 5})]
    assert cal_last_divergence(lst, FakeConf(0.9, [MACD_ALGO.PEAK])) is True
    # 力度 9.5 > 0.9*10 → 不背驰
    lst[2]._metrics[MACD_ALGO.PEAK] = 9.5
    assert cal_last_divergence(lst, FakeConf(0.9, [MACD_ALGO.PEAK])) is False
    # 阈值 1.0：5 <= 10 背驰
    lst[2]._metrics[MACD_ALGO.PEAK] = 5
    assert cal_last_divergence(lst, FakeConf(1.0, [MACD_ALGO.PEAK])) is True
    print("[OK] 正常判定")


def test_inf():
    lst = [FakeBi(False, {MACD_ALGO.PEAK: 10}),
           FakeBi(True, {MACD_ALGO.PEAK: 8}),
           FakeBi(False, {MACD_ALGO.PEAK: 5})]
    assert cal_last_divergence(lst, FakeConf(float("inf"), [MACD_ALGO.PEAK])) is None
    print("[OK] inf 阈值 → None")


def test_incomparable():
    # 前值 0 → None
    lst = [FakeBi(False, {MACD_ALGO.PEAK: 0}),
           FakeBi(True, {MACD_ALGO.PEAK: 8}),
           FakeBi(False, {MACD_ALGO.PEAK: 5})]
    assert cal_last_divergence(lst, FakeConf(0.9, [MACD_ALGO.PEAK])) is None
    # 缺失 → None
    lst[0]._metrics.pop(MACD_ALGO.PEAK)
    assert cal_last_divergence(lst, FakeConf(0.9, [MACD_ALGO.PEAK])) is None
    # 负力度（如 DIF 零轴下）→ None
    lst[0]._metrics[MACD_ALGO.PEAK] = -3
    assert cal_last_divergence(lst, FakeConf(0.9, [MACD_ALGO.PEAK])) is None
    # 不足 3 条 → None
    assert cal_last_divergence(lst[:2], FakeConf(0.9, [MACD_ALGO.PEAK])) is None
    # 同向相邻异常形态（末尾与 items[-3] 不同向）→ None
    bad = [FakeBi(False, {}), FakeBi(False, {}), FakeBi(True, {})]
    assert cal_last_divergence(bad, FakeConf(0.9, [MACD_ALGO.PEAK])) is None
    print("[OK] 不可比 → None")


def test_and():
    # 两指标都背驰 → True；一项不背驰 → False
    m_all = {MACD_ALGO.PEAK: 5, MACD_ALGO.SLOPE: 4}
    m_prev = {MACD_ALGO.PEAK: 10, MACD_ALGO.SLOPE: 8}
    lst = [FakeBi(False, dict(m_prev)),
           FakeBi(True, dict(m_prev)),
           FakeBi(False, dict(m_all))]
    assert cal_last_divergence(lst, FakeConf(0.9, [MACD_ALGO.PEAK, MACD_ALGO.SLOPE])) is True
    lst[2]._metrics[MACD_ALGO.SLOPE] = 7.5  # 7.5 > 0.9*8 不背驰
    assert cal_last_divergence(lst, FakeConf(0.9, [MACD_ALGO.PEAK, MACD_ALGO.SLOPE])) is False
    print("[OK] 多指标 AND")


def test_seg_fallback():
    # 段级量能类 VOLUMN：桩不实现它 → 回退 PEAK（不抛异常）
    m = {MACD_ALGO.VOLUMN: 999, MACD_ALGO.PEAK: 5}
    lst = [FakeSeg(False, {MACD_ALGO.PEAK: 10}),
           FakeSeg(True, {MACD_ALGO.PEAK: 8}),
           FakeSeg(False, m)]
    # VOLUMN 桩返回 999（证明走的是回退：如果直接用 VOLUMN 会判 999>9 不背驰）
    assert cal_last_divergence(lst, FakeConf(0.9, [MACD_ALGO.VOLUMN])) is True
    print("[OK] 段级量能回退 peak")


if __name__ == "__main__":
    test_normal()
    test_inf()
    test_incomparable()
    test_and()
    test_seg_fallback()
    print("全部通过")
