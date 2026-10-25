# -*- coding: utf-8 -*-
"""T3 阶梯翻转与终态单向性验收 —— chan-standard-bsp3-change task 5.1。

用法：
    .venv/Scripts/python.exe Debug/bsp3_flip_test.py

落库是 DELETE→INSERT 全集替换（`persist_full_set`），没有逐行 UPDATE，
所以「翻转」语义的正确性完全落在判据函数的**纯度**上（bsp2-change D2 的
同一结论）。本脚本用可控桩序列直接驱动 `confirm_axis` / `time_axis`，
断言：

  ① C0 → C3 翻转（数据补齐后转终态）
  ② C1 终态后补数据不翻回
  ③ 时间轴可双向翻转（回抽笔延长 → 强档降中/弱档）
  ④ ladder 组合串随重算收敛，终态轴段保持不变
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from WebAPI.bsp3_confirm import confirm_axis          # noqa: E402
from WebAPI.bsp3_ladder import bsp3_ladder           # noqa: E402
from WebAPI.bsp3_time_axis import time_axis          # noqa: E402

FAILS = []


def check(name, got, want):
    if got == want:
        print(f"  [OK] {name} = {got}")
    else:
        print(f"  [FAIL] {name}: got {got!r}, want {want!r}")
        FAILS.append(name)


class Bi:
    def __init__(self, idx, lo, hi, down, kluc=5):
        self.idx, self.lo, self.hi, self._down = idx, lo, hi, down
        self._kluc = kluc
        self.seg_idx = 0

    def is_down(self):
        return self._down

    def is_up(self):
        return not self._down

    def amp(self):
        return abs(self.hi - self.lo)

    def _low(self):
        return self.lo

    def _high(self):
        return self.hi

    def get_begin_val(self):
        return self.hi if self._down else self.lo

    def get_end_val(self):
        return self.lo if self._down else self.hi

    def get_klu_cnt(self):
        return self._kluc


class Feat:
    def __init__(self, d):
        self._d = d

    def items(self):
        return self._d.items()


class Bsp:
    def __init__(self, bi, buy=True, feat=None):
        self.bi, self.is_buy = bi, buy
        self.features = Feat(feat or {})


class Cfg:
    bsp3_confirm_window = 2
    bsp3_confirm_level = "strong"
    bsp3_time_axis_strong = 0.5
    bsp3_time_axis_weak = 1.0


ZS = {"bsp3_zs_low": 10.0, "bsp3_zs_high": 11.0}


def base():
    """中枢 [10,11]；离开笔 idx1（11→13）；回抽笔 idx2（13→11.4）。"""
    return [
        Bi(0, 10.0, 11.0, True),
        Bi(1, 11.0, 13.0, False),
        Bi(2, 11.4, 13.0, True),
    ]


def test_flip_0_to_3():
    print("\n[① C0 → C3 翻转]")
    b = base()
    check("数据不足为 C0", confirm_axis(Bsp(b[2], True, ZS), b, Cfg()), "C0")
    b2 = b + [Bi(3, 11.5, 13.6, False), Bi(4, 11.6, 12.0, True)]
    check("补齐后翻 C3", confirm_axis(Bsp(b2[2], True, ZS), b2, Cfg()), "C3")


def test_terminal_c1_no_flip():
    print("\n[② C1 终态不翻回]")
    b = base() + [Bi(3, 11.5, 11.8, False), Bi(4, 11.6, 11.9, True)]
    check("窗口内未动 → C1", confirm_axis(Bsp(b[2], True, ZS), b, Cfg()), "C1")
    b2 = b + [Bi(5, 11.7, 14.5, False), Bi(6, 11.8, 12.0, True)]
    check("窗口外新高仍 C1", confirm_axis(Bsp(b2[2], True, ZS), b2, Cfg()), "C1")


def test_time_axis_bidirectional():
    print("\n[③ 时间轴双向翻转]")
    # 速度比 v = (amp回抽/amp突破) / (n回抽/n突破)
    # 突破笔：amp=2（11→13），10 根 K 线
    # 回抽笔浅而慢：amp=0.2，2 根 → v = 0.1/0.2 = 0.5 → 强档 T3（衰竭）
    b = [
        Bi(0, 10.0, 11.0, True),
        Bi(1, 11.0, 13.0, False, kluc=10),
        Bi(2, 12.8, 13.0, True, kluc=2),
    ]
    check("急涨缓跌 → T3", time_axis(Bsp(b[2], True), b, Cfg()), "T3")
    # 同一笔回抽幅度加深（浅回抽 → 深回抽，价格延伸）：amp=1.6，仍 2 根
    # → v = 0.8/0.2 = 4.0 > 1.0 → 弱档 T1（急促）
    b2 = list(b)
    b2[2] = Bi(2, 11.4, 13.0, True, kluc=2)
    check("回抽加深 → 降档 T1", time_axis(Bsp(b2[2], True), b2, Cfg()), "T1")
    # 反向：再由深回抽回到中等幅度 → 可翻回中间档（双向）
    b3 = list(b)
    b3[2] = Bi(2, 12.0, 13.0, True, kluc=2)   # amp=1.0 → v = 0.5/0.2 = 2.5 → T1
    b3[1] = Bi(1, 11.0, 13.0, False, kluc=2)  # 突破笔同为 2 根 → v = 0.5/1.0 = 0.5 → T3
    check("突破笔缩短 → 可翻回强档", time_axis(Bsp(b3[2], True), b3, Cfg()), "T3")


def test_ladder_converges():
    print("\n[④ 组合串收敛且无 P 轴]")
    b = base() + [Bi(3, 11.5, 13.6, False), Bi(4, 11.6, 12.0, True)]
    bsp = Bsp(b[2], True, ZS)
    out1 = bsp3_ladder(bsp, None, b, Cfg())
    out2 = bsp3_ladder(Bsp(b[2], True, ZS), None, b, Cfg())
    check("两次推导一致", out1, out2)
    prefixes = [seg[0] for seg in out1.split("|")]
    check("无 P 轴", "P" in prefixes, False)
    check("含确认轴 C", any(p == "C" for p in prefixes), True)


if __name__ == "__main__":
    test_flip_0_to_3()
    test_terminal_c1_no_flip()
    test_time_axis_bidirectional()
    test_ladder_converges()
    print()
    if FAILS:
        print(f"失败 {len(FAILS)} 项：{FAILS}")
        sys.exit(1)
    print("全部通过")
