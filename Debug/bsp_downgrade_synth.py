# -*- coding: utf-8 -*-
"""
降级路由的判定层验证（chan-standard-bsp1-change tasks 2.2 / 2.2a / 2.2b / 2.2c /
2.3 / 3.1 / 3.2）

为什么不用真实 K 线：降级路由是 `treat_bsp1` 内的**分支条件**，触发它需要
「有中枢 + 面积背驰成立 + 极值成立 + 仅趋势不通过 + 其余判据全过」五项同时
成立。用随机游走序列几乎不可能稳定命中（实测 12 个 seed 全部产出 0 个多笔
中枢），用它验证只会得到「没触发 = 通过」的空断言。

因此本脚本在**判定层**打桩：把 `check_bsp1_standard`、中枢的
`is_divergence` / `out_bi_is_peak` 替换为可控输入，直接验证路由分支的
每一条判定路径。真实数据上的数量断言（41 只日线：T1=14 / 降级 T1P=53）
在 `Debug/bsp_standard_equivalence.py` 的第 6 节完成。

运行（项目根目录）：
    .venv/Scripts/python.exe Debug/bsp_downgrade_synth.py

任一断言失败 → 打印失败项并以非零码退出。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ChanAnalyse.Common.CEnum import BSP_TYPE  # noqa: E402
from ChanAnalyse.BuySellPoint.BSPointConfig import CBSPointConfig  # noqa: E402
from ChanAnalyse.BuySellPoint import BSPointList as bl_mod  # noqa: E402
from ChanAnalyse.BuySellPoint.BSPointList import CBSPointList  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        FAILURES.append(name)


# =============================================================================
# 桩件
# =============================================================================

class StubKlu:
    idx = 0

    class time:
        ts = 0


class StubEle:
    """最小要素桩：供 CBS_Point 构造与 add_bs 的索引/方向/幅度使用。"""

    def __init__(self, idx, is_down=True):
        self.idx = idx
        self._down = is_down
        self.bsp = None

    def is_down(self):
        return self._down

    def is_up(self):
        return not self._down

    def amp(self):
        return 1.0

    def get_end_klu(self):
        return StubKlu()

    def _low(self):
        return 0.0

    def _high(self):
        return 1.0

    def get_begin_klu(self):
        return StubKlu()

    def get_end_val(self):
        return 0.0


class StubZS:
    """中枢桩：is_divergence / out_bi_is_peak 由用例指定。"""

    def __init__(self, diver=True, ratio=0.5, peak=True):
        self._diver = diver
        self._ratio = ratio
        self._peak = peak
        self.bi_in = StubEle(0)
        self.bi_out = StubEle(1)
        self.begin_bi = StubEle(0)
        self.end_bi = StubEle(1)

    def out_bi_is_peak(self, idx, strict=True):
        # `strict` 是 chan-bsp1-extreme 新增的极值严格性开关，由
        # `BSP_CONF.bs1_peak_strict` 传入。本桩件只验证降级路由的短路顺序，
        # 极值结果由用例直接指定，故忽略该参数（保留形参以免签名不匹配）。
        return self._peak, None

    def end_bi_break(self, end_bi=None):
        # 突破判定由用例间接控制（`is_divergence` 已返回预设结果）。
        # 桩件默认「已突破」，因为所有用例的前提都是离开笔跌破中枢。
        return True

    def get_bi_in(self):
        return self.bi_in

    def is_divergence(self, config, out_bi=None, **kw):
        return self._diver, self._ratio

    def is_one_bi_zs(self):
        return False


class StubSeg:
    def __init__(self, end_bi, zs_lst):
        self.end_bi = end_bi
        self.zs_lst = zs_lst
        self.bi_list = [end_bi]
        # `_cal_force_windows` 以 seg.start_bi.idx 作相对索引的基准
        self.start_bi = end_bi

    def is_down(self):
        return True

    def is_up(self):
        return False


class StandardRecorder:
    """替换 BSPointList 命名空间里的 check_bsp1_standard，按配置返回预设结果。

    同时记录每次调用的 (bsp1_trend, bsp1_new_extreme_mode)，用于验证
    D1-c 的窗口口径覆写只发生在重跑副本上、不污染首轮判定。
    """

    def __init__(self, first, rest=None):
        self.first = first          # (ok, reason, info) 首轮（用配置原样）
        self.rest = rest or (True, None, {})
        self.calls = []

    def __call__(self, ele, ele_list, zs_lst, cfg, is_buy, full_ele_list=None):
        # full_ele_list 是 chan-bsp1-extreme 为 `bsp1_new_extreme_mode="level"`
        # 新增的形参；本桩件不验证跨线段取值，仅保留形参以匹配签名。
        self.calls.append((cfg.bsp1_trend, cfg.bsp1_new_extreme_mode))
        # 关趋势的那次调用 = rest_ok 重跑
        if not cfg.bsp1_trend:
            return self.rest
        return self.first


def make_lst(**conf_extra):
    conf = CBSPointConfig(**{
        "divergence_rate": 0.9, "min_zs_cnt": 2, "bsp1_only_multibi_zs": True,
        "max_bs2_rate": 0.9999, "macd_algo": "peak", "bs1_peak": True,
        "bs_type": "1,1p,2,2s,3a,3b", "bsp2_follow_1": True, "bsp3_follow_1": True,
        "bsp3_peak": False, "bsp2s_follow_2": False, "max_bsp2s_lv": None,
        "strict_bsp3": False, "bsp3a_max_zs_cnt": 1,
        "bsp1_trend": True, "bsp1_new_extreme": True, "bsp1_dif_div": True,
        "bsp1_zero_axis": True, "bsp1_trend_mode": "strict",
        "bsp1_new_extreme_mode": "trend_start", "bsp1_zs_extend_to_seg_end": False,
        "bsp2_retrace_zs": False, "bsp2s_require_zs": True, "bsp2s_rate_mode": "amp",
        "bsp3b_mode": "standard", "bsp3_peak_on_breakout": True,
        "bsp3_follow_1_mode": "sure", "bsp1_downgrade_to_pz": True,
        "bsp_preset": "standard",
        **conf_extra,
    })
    # 必须调用：target_types 由 parse_target_type 从 bs_type 字符串解析，
    # 跳过它会让所有类型都不在 target_types 里，能落库的只剩 T1/T1P
    conf.b_conf.parse_target_type()
    conf.s_conf.parse_target_type()
    lst = CBSPointList(conf)
    return lst, conf


def run_treat(lst, zs, ele):
    """调用 treat_bsp1，返回该笔的买卖点对象（候选可能在 bsp1_dict 而非 store）。"""
    seg = StubSeg(ele, [zs])
    lst.treat_bsp1(seg, lst.config.GetBSConfig(True), True)
    return lst.bsp_store_flat_dict.get(ele.idx) or lst.bsp1_dict.get(ele.idx)


def features(bsp):
    return dict(bsp.features.items()) if bsp is not None else {}


# =============================================================================
# 用例
# =============================================================================

def case_single_zs_downgrade():
    print("\n[2.2 / 2.3] 单中枢 + 面积背驰 + 极值 + 仅趋势不过 + 其余全过 → 降级 single_zs")
    lst, _ = make_lst()
    rec = StandardRecorder(first=(False, 'trend', {'zs_cnt': 1}), rest=(True, None, {}))
    orig = bl_mod.check_bsp1_standard
    bl_mod.check_bsp1_standard = rec
    try:
        ele = StubEle(31)
        bsp = run_treat(lst, StubZS(), ele)
    finally:
        bl_mod.check_bsp1_standard = orig
    check("产出买卖点对象", bsp is not None)
    check("类型为 T1P（不是 T1）", bsp is not None and bsp.type == [BSP_TYPE.T1P],
          f"实际 {[t.value for t in bsp.type] if bsp else None}")
    fd = features(bsp)
    check("feature 带 bsp1_downgrade_reason=single_zs",
          fd.get('bsp1_downgrade_reason') == 'single_zs', f"实际 {fd.get('bsp1_downgrade_reason')}")
    check("落库可见（bsp_store_dict 收录，bsp_iter 能取到）",
          bsp is not None and bsp in lst.getSortedBspList())
    check("不进 bsp1_sure_dict（锚点隔离）", ele.idx not in lst.bsp1_sure_dict)
    check("不在 bsp1_sure_list", bsp not in lst.bsp1_sure_list)
    check("在 bsp1_list（候选口径）", bsp in lst.bsp1_list)
    check("重跑用了关趋势的副本配置", any(not t for t, _ in rec.calls), f"调用序列 {rec.calls}")


def case_two_zs_downgrade():
    print("\n[2.2] 两中枢重叠下移 + 其余全过 → 降级 no_trend")
    lst, _ = make_lst()
    rec = StandardRecorder(first=(False, 'trend', {'zs_cnt': 2}), rest=(True, None, {}))
    orig = bl_mod.check_bsp1_standard
    bl_mod.check_bsp1_standard = rec
    try:
        ele = StubEle(40)
        bsp = run_treat(lst, StubZS(), ele)
    finally:
        bl_mod.check_bsp1_standard = orig
    fd = features(bsp)
    check("降级成因为 no_trend", fd.get('bsp1_downgrade_reason') == 'no_trend',
          f"实际 {fd.get('bsp1_downgrade_reason')}")


def case_no_divergence():
    print("\n[2.2] 面积背驰不过 → 不降级，也不成立 T1")
    lst, _ = make_lst()
    rec = StandardRecorder(first=(False, 'trend', {'zs_cnt': 1}), rest=(True, None, {}))
    orig = bl_mod.check_bsp1_standard
    bl_mod.check_bsp1_standard = rec
    try:
        ele = StubEle(50)
        bsp = run_treat(lst, StubZS(diver=False), ele)
    finally:
        bl_mod.check_bsp1_standard = orig
    check("无降级点", bsp is None or not features(bsp).get('bsp1_downgrade_reason'),
          f"实际 {features(bsp).get('bsp1_downgrade_reason')}")
    check("不成立一买", ele.idx not in lst.bsp1_sure_dict)


def case_peak_fail():
    print("\n[2.2] 极值判据不过 → 不降级")
    lst, _ = make_lst()
    rec = StandardRecorder(first=(False, 'trend', {'zs_cnt': 1}), rest=(True, None, {}))
    orig = bl_mod.check_bsp1_standard
    bl_mod.check_bsp1_standard = rec
    try:
        ele = StubEle(60)
        bsp = run_treat(lst, StubZS(peak=False), ele)
    finally:
        bl_mod.check_bsp1_standard = orig
    check("极值不过不降级", bsp is None or not features(bsp).get('bsp1_downgrade_reason'))


def case_divergence_disabled():
    print("\n[2.2a] divergence_rate=200（背驰判据显式关闭）→ 空真不当作证据，降级为 0")
    lst, conf = make_lst(divergence_rate=200.0)
    rec = StandardRecorder(first=(False, 'trend', {'zs_cnt': 1}), rest=(True, None, {}))
    orig = bl_mod.check_bsp1_standard
    bl_mod.check_bsp1_standard = rec
    try:
        ele = StubEle(70)
        # 桩中枢照实返回 True——模拟 is_divergence 在 >100 时的空真
        bsp = run_treat(lst, StubZS(diver=True), ele)
    finally:
        bl_mod.check_bsp1_standard = orig
    check("空真 (is_divergence=True) 未被当作背驰证据",
          bsp is None or not features(bsp).get('bsp1_downgrade_reason'))
    # 注意：不降级不等于「不产出对象」——改造前行为是该点以 T1 候选登记，
    # 这里要断言的正是「仍是 T1 候选、没有 T1P 降级」
    check("→ 降级点为 0（仍按 T1 候选登记，非 T1P 降级）",
          bsp is not None and BSP_TYPE.T1P not in bsp.type,
          f"实际类型 {[t.value for t in bsp.type] if bsp else None}")


def case_rest_ok_required():
    print("\n[2.2b] 趋势不过 + 面积背驰过 + 极值过 + 新低不过 → 不降级（rest_ok 必要性）")
    lst, _ = make_lst()
    rec = StandardRecorder(first=(False, 'trend', {'zs_cnt': 1}),
                           rest=(False, 'new_extreme', {'ref_start_idx': 0, 'worse_cnt': 1}))
    orig = bl_mod.check_bsp1_standard
    bl_mod.check_bsp1_standard = rec
    try:
        ele = StubEle(80)
        bsp = run_treat(lst, StubZS(), ele)
    finally:
        bl_mod.check_bsp1_standard = orig
    check("仅靠 reason=='trend' 不够，补全检不过则不降级",
          bsp is None or not features(bsp).get('bsp1_downgrade_reason'))


def case_rest_ok_zero_axis_fail():
    print("\n[2.2b] 补全检在零轴判据失败 → 不降级")
    lst, _ = make_lst()
    rec = StandardRecorder(first=(False, 'trend', {'zs_cnt': 1}),
                           rest=(False, 'zero_axis', {}))
    orig = bl_mod.check_bsp1_standard
    bl_mod.check_bsp1_standard = rec
    try:
        ele = StubEle(90)
        bsp = run_treat(lst, StubZS(), ele)
    finally:
        bl_mod.check_bsp1_standard = orig
    check("零轴不过不降级", bsp is None or not features(bsp).get('bsp1_downgrade_reason'))


def case_d1c_window():
    print("\n[2.2c] D1-c 窗口口径：覆盖只发生在重跑副本，首轮用配置原值")
    lst, _ = make_lst(bsp1_new_extreme_mode="trend_start")
    rec = StandardRecorder(first=(False, 'trend', {'zs_cnt': 1}), rest=(True, None, {}))
    orig = bl_mod.check_bsp1_standard
    bl_mod.check_bsp1_standard = rec
    try:
        ele = StubEle(100)
        run_treat(lst, StubZS(), ele)
    finally:
        bl_mod.check_bsp1_standard = orig
    check("首轮调用用配置原值（trend=True, trend_start）",
          rec.calls[0] == (True, 'trend_start'), f"实际 {rec.calls[0] if rec.calls else None}")
    check("重跑调用关趋势且强制 mode='all'",
          any(t is False and m == 'all' for t, m in rec.calls), f"实际 {rec.calls}")


def case_trend_disabled_never_downgrades():
    print("\n[2.2] 趋势判据本已关闭（bsp1_trend=False）→ 无「趋势不达标」，降级永不触发")
    lst, _ = make_lst(bsp1_trend=False)
    # 趋势关闭时 standard_ok 就是全检结果；此处令其失败（reason 不会是 trend）
    rec = StandardRecorder(first=(False, 'dif_div', {'zs_cnt': 1}), rest=(True, None, {}))
    orig = bl_mod.check_bsp1_standard
    bl_mod.check_bsp1_standard = rec
    try:
        ele = StubEle(110)
        bsp = run_treat(lst, StubZS(), ele)
    finally:
        bl_mod.check_bsp1_standard = orig
    check("reason 不为 trend 时不降级",
          bsp is None or not features(bsp).get('bsp1_downgrade_reason'))
    check("且不做重复的补全检调用（只有 1 次）", len(rec.calls) <= 1, f"实际 {rec.calls}")


def case_switch_off():
    print("\n[1.x 行为] bsp1_downgrade_to_pz=False → 完全退回改造前（候选 T1，不降级）")
    lst, _ = make_lst(bsp1_downgrade_to_pz=False)
    rec = StandardRecorder(first=(False, 'trend', {'zs_cnt': 1}), rest=(True, None, {}))
    orig = bl_mod.check_bsp1_standard
    bl_mod.check_bsp1_standard = rec
    try:
        ele = StubEle(120)
        bsp = run_treat(lst, StubZS(), ele)
    finally:
        bl_mod.check_bsp1_standard = orig
    check("开关关闭无降级", bsp is None or not features(bsp).get('bsp1_downgrade_reason'))
    check("仍以 T1 候选登记", bsp is not None and bsp.type == [BSP_TYPE.T1])
    check("T1 候选不成立", ele.idx not in lst.bsp1_sure_dict)


def case_add_bs_protection():
    print("\n[3.1] 同笔先 T1 候选、后 T1P 降级 → 不得被升级为成立")
    lst, _ = make_lst()
    ele = StubEle(200)
    lst.add_bs(bs_type=BSP_TYPE.T1, bi=ele, relate_bsp1=None,
               is_target_bsp=False, feature_dict={'step': 't1_candidate'})
    lst.add_bs(bs_type=BSP_TYPE.T1P, bi=ele, relate_bsp1=None,
               is_target_bsp=False, feature_dict={'bsp1_downgrade_reason': 'single_zs'},
               is_downgrade=True)
    check("该笔不进 bsp1_sure_dict（降级不得升级）", ele.idx not in lst.bsp1_sure_dict)
    check("该笔不在 bsp1_sure_list", all(b.bi.idx != ele.idx for b in lst.bsp1_sure_list))
    check("两种类型都在同一对象上", lst.bsp_store_flat_dict[ele.idx].type == [BSP_TYPE.T1, BSP_TYPE.T1P])


def case_t1_upgrade_still_works():
    print("\n[3.2] 回归：T1 先候选后成立，升级路径必须仍然工作")
    lst, _ = make_lst()
    ele = StubEle(210)
    # 真实的升级路径要求该笔已有**落库**对象（候选本身不进 bsp_store_flat_dict）。
    # 典型场景：该笔先因其他类型（如 T2）落库，随后 T1 判定逐次收紧。
    lst.add_bs(bs_type=BSP_TYPE.T2, bi=ele, relate_bsp1=None,
               is_target_bsp=True, feature_dict={'step': 't2'})
    lst.add_bs(bs_type=BSP_TYPE.T1, bi=ele, relate_bsp1=None,
               is_target_bsp=False, feature_dict={'step': 't1_candidate'})
    check("第一步：T1 候选不进成立集合", ele.idx not in lst.bsp1_sure_dict)
    lst.add_bs(bs_type=BSP_TYPE.T1, bi=ele, relate_bsp1=None,
               is_target_bsp=True, feature_dict={'step': 'sure'})
    check("第二步：候选→成立，正确进 bsp1_sure_dict", ele.idx in lst.bsp1_sure_dict)
    check("并进 bsp1_sure_list", lst.bsp1_sure_list[-1].bi.idx == ele.idx)
    # 反向保护：同样的两步，但第二步是降级请求 → 不得升级
    lst2, _ = make_lst()
    ele2 = StubEle(211)
    lst2.add_bs(bs_type=BSP_TYPE.T2, bi=ele2, relate_bsp1=None,
                is_target_bsp=True, feature_dict={'step': 't2'})
    lst2.add_bs(bs_type=BSP_TYPE.T1, bi=ele2, relate_bsp1=None,
                is_target_bsp=False, feature_dict={'step': 't1_candidate'})
    lst2.add_bs(bs_type=BSP_TYPE.T1P, bi=ele2, relate_bsp1=None,
                is_target_bsp=False, feature_dict={'bsp1_downgrade_reason': 'single_zs'},
                is_downgrade=True)
    check("降级请求命中已落库笔时不升级", ele2.idx not in lst2.bsp1_sure_dict)


def main():
    print("=" * 78)
    print("降级路由判定层验证（chan-standard-bsp1-change）")
    print("=" * 78)
    case_single_zs_downgrade()
    case_two_zs_downgrade()
    case_no_divergence()
    case_peak_fail()
    case_divergence_disabled()
    case_rest_ok_required()
    case_rest_ok_zero_axis_fail()
    case_d1c_window()
    case_trend_disabled_never_downgrades()
    case_switch_off()
    case_add_bs_protection()
    case_t1_upgrade_still_works()
    print()
    if FAILURES:
        print(f"✗ {len(FAILURES)} 项失败：{FAILURES}")
        return 1
    print("✓ 全部断言通过")
    return 0


if __name__ == '__main__':
    sys.exit(main())
