# -*- coding: utf-8 -*-
"""
bsp2_confirm / bsp2_time_axis / bsp2_progress 纯函数单元验证
（chan-standard-bsp2-change tasks 1.2 / 1.3 / 1.4）

用法：
    .venv/Scripts/python.exe Debug/bsp2_axes_unit_test.py

桩对象仿 `Debug/bsp_downgrade_synth.py` 的 StubEle 模式：最小要素桩，
价格可控，供确认轴/时间轴/进度轴三组纯函数做五场景覆盖。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from WebAPI.bsp2_confirm import confirm_axis  # noqa: E402
from WebAPI.bsp2_time_axis import time_axis  # noqa: E402
from WebAPI.bsp2_progress import progress_axis  # noqa: E402


class StubKlu:
    def __init__(self, idx=0):
        self.idx = idx


class StubBi:
    """可控价格桩：方向由 is_down 决定，幅度/端点由 (lo, hi) 决定。"""

    def __init__(self, idx, lo, hi, is_down, klu_cnt=5):
        self.idx = idx
        self.lo = lo
        self.hi = hi
        self._down = is_down
        self._kluc = klu_cnt
        self.bsp = None

    def is_down(self):
        return self._down

    def is_up(self):
        return not self._down

    def amp(self):
        return abs(self.hi - self.lo)

    def get_end_val(self):
        return self.lo if self._down else self.hi

    def get_begin_val(self):
        return self.hi if self._down else self.lo

    def get_klu_cnt(self):
        return self._kluc

    def get_end_klu(self):
        return StubKlu(self.idx)


class StubBsp:
    def __init__(self, bi, is_buy=True, relate_bsp1=None, features=None):
        self.bi = bi
        self.is_buy = is_buy
        self.relate_bsp1 = relate_bsp1
        self.features = features or {}


class StubCfg:
    bsp2_confirm_window = 2
    bsp2_confirm_level = "strong"
    bsp2_time_axis_strong = 0.5
    bsp2_time_axis_weak = 1.0


# ----------------------------------------------------------------------
# 1.2 确认轴五场景（买侧：一买 10.0 → break_bi 10.0→13.0 → 回调 13.0→11.4）
# ----------------------------------------------------------------------

def bi_list_buy(follow_bis):
    """买侧笔列表：idx0 一买(跌 10.6→10.0)、idx1 break(涨 10.0→13.0)、
    idx2 回调(跌 13.0→11.4)，follow_bis 为窗口内后续 (lo, hi, is_down, kluc)。"""
    lst = [
        StubBi(0, 10.0, 10.6, is_down=True),
        StubBi(1, 10.0, 13.0, is_down=False),   # break_bi
        StubBi(2, 11.4, 13.0, is_down=True),    # bsp2_bi（回调笔）
    ]
    for k, (lo, hi, dn, kc) in enumerate(follow_bis):
        lst.append(StubBi(3 + k, lo, hi, is_down=dn, klu_cnt=kc))
    return lst


def anchor():
    """relate_bsp1 桩：锚点笔 idx=0（一买在 idx0，break=idx1）。"""
    return StubBsp(StubBi(0, 10.0, 10.6, is_down=True), is_buy=True)


def test_confirm_axis():
    # 场景1 突破：窗口内上升笔高点 13.5 >= 13.0 → C3
    bl = bi_list_buy([(11.0, 13.5, False, 4), (11.0, 11.2, True, 4)])
    assert confirm_axis(StubBsp(bl[2], True, anchor()), bl, StubCfg()) == "C3"

    # 场景2 收复一半：高点 12.0 >= 11.5（收复线）但 < 13.0 → C2
    bl = bi_list_buy([(11.0, 12.0, False, 4), (11.0, 11.2, True, 4)])
    assert confirm_axis(StubBsp(bl[2], True, anchor()), bl, StubCfg()) == "C2"

    # 场景3 未动（终态）：窗口 2 笔走完，最高 11.2 < 11.5 → C1
    bl = bi_list_buy([(11.0, 11.2, False, 4), (11.0, 11.3, True, 4)])
    assert confirm_axis(StubBsp(bl[2], True, anchor()), bl, StubCfg()) == "C1"

    # 场景4 进行中：窗口 2 但数据只到回调笔后 1 笔 → C0
    bl = bi_list_buy([(11.0, 11.2, False, 4)])
    assert confirm_axis(StubBsp(bl[2], True, anchor()), bl, StubCfg()) == "C0"

    # 场景5 窗口外新高不翻：窗口 2 内未动（C1），窗口外第 3 笔才突破 → 仍 C1
    bl = bi_list_buy([(11.0, 11.2, False, 4), (11.0, 11.3, True, 4), (11.0, 14.0, False, 4)])
    assert confirm_axis(StubBsp(bl[2], True, anchor()), bl, StubCfg()) == "C1"

    # 场景5b weak 口径：收复一半即算确认 → C3
    cfg = StubCfg()
    cfg.bsp2_confirm_level = "weak"
    bl = bi_list_buy([(11.0, 12.0, False, 4), (11.0, 11.2, True, 4)])
    assert confirm_axis(StubBsp(bl[2], True, anchor()), bl, cfg) == "C3"

    # 卖侧镜像：一卖 13.0 → break(跌 13.0→11.0) → 反弹回调 11.0→12.0，窗口内下跌笔低点 10.5 <= 11.0 → C3
    sl = [
        StubBi(0, 13.0, 13.6, is_down=False),
        StubBi(1, 11.0, 13.0, is_down=True),    # break_bi 卖侧为下跌笔，终点 11.0
        StubBi(2, 11.0, 12.0, is_down=False),   # 回调（反弹）笔
        StubBi(3, 10.5, 12.0, is_down=True),
        StubBi(4, 11.5, 12.5, is_down=False),
    ]
    assert confirm_axis(StubBsp(sl[2], False, StubBsp(sl[0], is_buy=False)), sl, StubCfg()) == "C3"
    print("1.2 确认轴五场景 ✓（含 weak 口径与卖侧镜像）")


# ----------------------------------------------------------------------
# 卖侧 _thresholds 的镜像正确性（买卖对称的守护断言）
# ----------------------------------------------------------------------

def test_sell_thresholds():
    from WebAPI.bsp2_confirm import _thresholds
    bi = StubBi(1, 11.0, 13.0, is_down=True)  # 卖侧 break_bi：跌 13.0→11.0
    t_conf, t_rec = _thresholds(bi, False, "strong")
    assert t_conf == 11.0 and t_rec == 12.0, (t_conf, t_rec)
    print("卖侧阈值镜像 ✓（确认 11.0 / 收复 12.0）")


# ----------------------------------------------------------------------
# 1.3 时间轴（design D4 数值例 + 去相关）
# ----------------------------------------------------------------------

def test_time_axis():
    # break_bi：5 根 K 线、amp 3.0（10.0→13.0）
    # A：8 根 K 线、amp 1.6 → 0.533/1.60 = 0.33 → 强档（衰竭）
    # B：3 根 K 线、amp 1.6 → 0.533/0.60 = 0.89 → 中档
    # C：2 根 K 线、amp 2.0 → 0.667/0.40 = 1.67 → 弱档（急促）
    #   A 与 B 回撤率相同（1.6/3.0），仅时间比不同 → 档位不同（去相关验证）
    for klu_cnt, amp, expect in ((8, 1.6, "T3"), (3, 1.6, "T2"), (2, 2.0, "T1")):
        bl = [
            StubBi(0, 10.0, 10.6, is_down=True),
            StubBi(1, 10.0, 13.0, is_down=False, klu_cnt=5),   # break_bi
            StubBi(2, 13.0 - amp, 13.0, is_down=True, klu_cnt=klu_cnt),  # 回调笔
        ]
        got = time_axis(StubBsp(bl[2], True, anchor()), bl, StubCfg())
        assert got == expect, f"klu_cnt={klu_cnt} amp={amp}: expect {expect}, got {got}"

    # 速度比不可计算：break_bi amp=0 → None
    bl = [StubBi(0, 10.0, 10.6, True), StubBi(1, 13.0, 13.0, False, 5), StubBi(2, 11.4, 13.0, True)]
    assert time_axis(StubBsp(bl[2], True, anchor()), bl, StubCfg()) is None
    print("1.3 时间轴三档 + 去相关 + 不可计算 ✓")


# ----------------------------------------------------------------------
# 1.4 进度轴（回撤率短路→P1 / 全过未确认→P2 / 缺键→None）
# ----------------------------------------------------------------------

def test_progress_axis():
    bl = bi_list_buy([(11.0, 12.0, False, 4), (11.0, 11.2, True, 4)])

    # 全过未确认：reason=None → P2
    bsp = StubBsp(bl[2], True, anchor(), features={'bsp2_reason': None})
    assert progress_axis(bsp) == "P2", progress_axis(bsp)

    # 回撤率短路：reason='retrace_rate'（3 项已过 <= 3）→ P1
    bsp = StubBsp(bl[2], True, anchor(), features={'bsp2_reason': 'retrace_rate'})
    assert progress_axis(bsp) == "P1", progress_axis(bsp)

    # 中枢关联短路：reason='retrace_not_in_zs'（4 项已过 > 3）→ P2
    bsp = StubBsp(bl[2], True, anchor(), features={'bsp2_reason': 'retrace_not_in_zs'})
    assert progress_axis(bsp) == "P2", progress_axis(bsp)

    # 缺关键键（存量点）：无 bsp2_reason → None（不猜）
    bsp = StubBsp(bl[2], True, anchor(), features={'bsp2_retrace_rate': 0.5})
    assert progress_axis(bsp) is None
    print("1.4 进度轴三场景 ✓")


# ----------------------------------------------------------------------
# 4.2 翻转专项：终态单向 / 时间轴降档 / L4 不受影响
# ----------------------------------------------------------------------

def test_flip_semantics():
    # ① 确认轴：窗口内未动(C1)→窗口内后段突破→翻转为 C3 后，再把窗口外
    #    数据延长也不降档（窗口外新高不进输入）；且窗口走完的 C1 是终态
    bl = bi_list_buy([(11.0, 11.2, False, 4), (11.0, 11.3, True, 4)])
    bsp = StubBsp(bl[2], True, anchor(), features={'bsp2_reason': None})
    assert confirm_axis(bsp, bl, StubCfg()) == "C1"  # 未动（终态）
    # 延长窗口外第 3 笔大涨：C1 不变（终态不翻）
    bl.append(StubBi(5, 11.0, 14.0, False, 4))
    assert confirm_axis(bsp, bl, StubCfg()) == "C1"
    # ② 时间轴降档：回调笔从 8 根延长到 10 根（速度比 0.33→0.42 仍强档），
    #    再到 16 根（0.533/3.2=0.17？不——重新算：amp 同、根数增多 → v 变小）。
    #    降档方向是「根数减少」：4 根（0.533/0.8=0.67 → 中档）
    bl2 = [
        StubBi(0, 10.0, 10.6, is_down=True),
        StubBi(1, 10.0, 13.0, is_down=False, klu_cnt=5),
        StubBi(2, 11.4, 13.0, is_down=True, klu_cnt=8),   # 强档 T3
    ]
    bsp2 = StubBsp(bl2[2], True, anchor(), features={'bsp2_reason': None})
    assert time_axis(bsp2, bl2, StubCfg()) == "T3"
    # 回调笔延长（根数 8→20）：amp 不变、时间比变大 → v 变小，仍 T3？
    # v = 0.533/(20/5)=0.13 → 仍强档。降档用「amp 变大」：根数不变、amp 增大
    bl2[2] = StubBi(2, 10.5, 13.0, is_down=True, klu_cnt=8)  # amp 2.5
    bsp2 = StubBsp(bl2[2], True, anchor(), features={'bsp2_reason': None})
    # v = (2.5/3.0)/(8/5) = 0.52 → 中档 T2（强→中降档）
    assert time_axis(bsp2, bl2, StubCfg()) == "T2"
    print("4.2 ①确认轴终态 + ②时间轴降档 ✓")

    # ③ L4 短路：已确认点不再走任何轴（轴证据变化不影响单值）
    from WebAPI.bsp_ladder import cal_ladder
    from ChanAnalyse.Common.CEnum import BSP_TYPE

    class StubLstSure:
        last_sure_pos = 10 ** 9

    bl3 = bi_list_buy([(11.0, 13.5, False, 4), (11.0, 11.2, True, 4)])
    bsp3 = StubBsp(bl3[2], True, anchor(), features={'bsp2_reason': None})
    bsp3.type = [BSP_TYPE.T2]
    assert cal_ladder(bsp3, StubLstSure(), bi_list_ref=bl3, cfg=StubCfg()) == "L4"
    # 轴证据变化（回调笔延长时间轴降档）不影响 L4
    bl3[2] = StubBi(2, 10.5, 13.0, is_down=True, klu_cnt=8)
    bsp3b = StubBsp(bl3[2], True, anchor(), features={'bsp2_reason': None})
    bsp3b.type = [BSP_TYPE.T2]
    assert cal_ladder(bsp3b, StubLstSure(), bi_list_ref=bl3, cfg=StubCfg()) == "L4"
    print("4.2 ③ L4 不受轴证据变化影响 ✓")

    # 补充：未确认点的翻转路径（C1 → 后续笔补进来 → C3）
    bl4 = bi_list_buy([(11.0, 11.2, False, 4), (11.0, 11.3, True, 4)])
    bsp4 = StubBsp(bl4[2], True, anchor(), features={'bsp2_reason': None})
    # 上面 bl4 已经是 C1（两笔未动）——直接验证 C1→C3 需要窗口内笔突破，
    # 这与「终态不翻」矛盾？不：C1 的前提是窗口走完。窗口未走完时是 C0，
    # C0 → C3 是合法翻转（ongoing → confirmed）
    bl5 = bi_list_buy([(11.0, 11.2, False, 4)])  # 只有 1 根后续笔 → C0
    bsp5 = StubBsp(bl5[2], True, anchor(), features={'bsp2_reason': None})
    assert confirm_axis(bsp5, bl5, StubCfg()) == "C0"
    bl5.append(StubBi(4, 11.0, 13.5, False, 4))  # 第 2 根突破 → C3
    assert confirm_axis(bsp5, bl5, StubCfg()) == "C3"
    print("4.2 补充 C0→C3 窗口内翻转 ✓")


if __name__ == "__main__":
    test_confirm_axis()
    test_sell_thresholds()
    test_time_axis()
    test_progress_axis()
    test_flip_semantics()
    print("\n全部通过")
