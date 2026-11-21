# -*- coding: utf-8 -*-
"""验证一买四项标准判据之间**没有**先后依赖（bsp1_new_extreme 不依赖 bsp1_trend）。

目的：回答「关闭『一买要求先有趋势』后，『一买要求创新低』是否还能生效」。
用最小桩对象直接调 `check_bsp1_standard`，绕开 CChan 全链路。

运行：  .venv/Scripts/python.exe Debug/test_bsp1_gate_independence.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from ChanAnalyse.BuySellPoint.BSPJudgement import check_bsp1_standard  # noqa: E402

_PASS = 0
_FAIL = 0


def check(name, cond, detail=""):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  [OK]   {name}")
    else:
        _FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


class Ele:
    """笔/线段桩：只要 idx / is_down / _low / _high 就能参与判据。"""

    def __init__(self, idx, low, high=None):
        self.idx = idx
        self._lo = low
        self._hi = high if high is not None else low + 0.3

    def is_down(self):
        return True          # 本用例全部是买点（下跌）

    def is_up(self):
        return False

    def _low(self):
        return self._lo

    def _high(self):
        return self._hi

    def get_end_val(self):
        return self._lo


class Zs:
    """中枢桩：多笔中枢（is_one_bi_zs=False），带 high/low 供趋势判据比较。"""

    def __init__(self, low, high, bi_in=None):
        self.low = low
        self.high = high
        self.bi_in = bi_in

    def is_one_bi_zs(self):
        return False


class Cfg:
    """判据开关桩（模拟 CPointConfig 的那几个字段）。"""

    def __init__(self, trend, new_extreme, dif_div=False, zero_axis=False,
                 trend_mode="strict", new_extreme_mode="trend_start"):
        self.bsp1_trend = trend
        self.bsp1_new_extreme = new_extreme
        self.bsp1_dif_div = dif_div
        self.bsp1_zero_axis = zero_axis
        self.bsp1_trend_mode = trend_mode
        self.bsp1_new_extreme_mode = new_extreme_mode


# ---------------------------------------------------------------------------
# 走势构造：
#   bi1 跌到 10.2（z1 进入）  z1=[10.1, 10.5]
#   bi2 跌到 10.0, bi3 涨, bi4 跌到 10.1, bi5 涨      ← z1 内部
#   bi6 跌到 8.8（z2 进入 / b 段）
#   bi7 涨, bi8 跌到 9.3, bi9 涨                      ← z2=[9.3, 9.5]
#   bi10 候选：低点由用例给定
# ---------------------------------------------------------------------------
bi1 = Ele(1, 10.2)
bi2 = Ele(2, 10.0)
z1 = Zs(10.1, 10.5, bi_in=bi1)
ele_list_down = [bi1, bi2, Ele(4, 10.1), Ele(6, 8.8), Ele(8, 9.3)]
zs_lst = [z1, Zs(9.3, 9.5, bi_in=Ele(6, 8.8))]

print("=" * 60)
print(">>> 一买判据独立性验证（bsp1_new_extreme 不依赖 bsp1_trend）")
print("=" * 60)

print("\n[1] 趋势关 + 新低关：放行所有候选（判据都不参与）")
for low in (8.5, 9.0, 9.4):
    ok, reason, info = check_bsp1_standard(
        Ele(10, low), ele_list_down, zs_lst, Cfg(False, False), True)
    check(f"c 段低点 {low} → 通过", ok and reason is None, f"ok={ok} reason={reason}")

print("\n[2] 趋势关 + 新低开：新低判据**单独生效**，仍在筛点")
# 趋势最低 = b 段 8.8。当前口径为**宽松优**（chan-bsp1-loose-extreme）：
# 相等极值算创新低，必须严格高于 8.8 才被拦下。
for low, want in ((8.5, True), (8.8, True), (8.9, False), (9.4, False)):
    ok, reason, info = check_bsp1_standard(
        Ele(10, low), ele_list_down, zs_lst, Cfg(False, True), True)
    tag = "通过" if want else "拦下"
    check(f"c 段低点 {low} → 应{tag}",
          ok == want and (want or reason == "new_extreme"),
          f"ok={ok} reason={reason} worse={info.get('worse_cnt')}")
check("拦截原因名为 new_extreme（不是 trend）",
      check_bsp1_standard(Ele(10, 9.4), ele_list_down, zs_lst,
                          Cfg(False, True), True)[1] == "new_extreme")

print("\n[3] 趋势开 + 新低关：趋势判据单独生效")
ok, reason, info = check_bsp1_standard(
    Ele(10, 9.4), ele_list_down, zs_lst, Cfg(True, False), True)
check("两中枢依次下移 → 趋势通过", ok and reason is None, f"ok={ok} reason={reason}")
# 中枢区间重叠（不构成趋势）
zs_overlap = [Zs(10.0, 10.5, bi_in=bi1), Zs(9.8, 10.3, bi_in=Ele(6, 9.9))]
ok, reason, _ = check_bsp1_standard(
    Ele(10, 9.4), ele_list_down, zs_overlap, Cfg(True, False), True)
check("中枢区间重叠 → reason=trend", (not ok) and reason == "trend", f"reason={reason}")

print("\n[4] 两项都开：短路顺序为 trend → new_extreme")
# 重叠中枢 + 未创新低：两者都不通过时，先报 trend（顺序契约）
ok, reason, _ = check_bsp1_standard(
    Ele(10, 9.4), ele_list_down, zs_overlap, Cfg(True, True), True)
check("都不通过时先报 trend", (not ok) and reason == "trend", f"reason={reason}")
# 趋势通过但未创新低：报 new_extreme
ok, reason, _ = check_bsp1_standard(
    Ele(10, 9.0), ele_list_down, zs_lst, Cfg(True, True), True)
check("趋势通过但未创新低 → 报 new_extreme",
      (not ok) and reason == "new_extreme", f"reason={reason}")

print("\n" + "=" * 60)
print(f"合计: {_PASS} PASS, {_FAIL} FAIL")
print("=" * 60)
sys.exit(1 if _FAIL else 0)
