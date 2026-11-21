# -*- coding: utf-8 -*-
"""
介入点候选判定的合成验证（chan-entry-point-candidate tasks 2.2 / 2.3）

与 `bsp_qjt_synth.py` 同一思路：介入点判定的分支（方法1 最低层候选+分型、
方法2 家族命中、窗口右端外扩、必要条件水位拦截、开关矩阵、买卖镜像）
在真实数据上无法逐条构造，用结构层最小桩件直接喂给
`CBSPointList._annotate_entry_point` / `entry_point_result`。

真实数据等价基线（开关全关零变化、legacy 一致）在
`Debug/bsp_standard_equivalence.py` 第 8 节与 6.1 任务。

运行（项目根目录）：
    .venv/Scripts/python.exe Debug/entry_point_synth.py

任一断言失败 → 打印失败项并以非零码退出。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ChanAnalyse.BuySellPoint.BSPointList import (  # noqa: E402
    CBSPointList,
    entry_point_result,
)
from ChanAnalyse.BuySellPoint.BSPointConfig import CBSPointConfig  # noqa: E402
from ChanAnalyse.Common.CEnum import BSP_TYPE, FX_TYPE  # noqa: E402
from ChanAnalyse.ChanModel.Features import CFeatures  # noqa: E402

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

class StubTime:
    def __init__(self, ts):
        self.ts = ts


class StubKlu:
    def __init__(self, ts, klc=None, sub_ts=(), idx=None):
        self.time = StubTime(ts)
        self.klc = klc
        self.sub_kl_list = [StubKlu(t) for t in sub_ts]
        self.idx = idx


class StubKlc:
    def __init__(self, klu, fx=None, nxt=None):
        self.lst = [klu]
        self.fx = fx
        self.next = nxt
        self.pre = None
        klu.klc = self


class StubBi:
    def __init__(self, idx, end_ts, sub_ts=()):
        self.idx = idx
        self._klu = StubKlu(end_ts, sub_ts=sub_ts, idx=idx)
        klus = [StubKlu(end_ts, sub_ts=sub_ts)]
        self.klc_lst = [StubKlc(k) for k in klus]
        self.parent_seg = None

    def get_end_klu(self):
        return self._klu


class StubZS:
    def __init__(self, end_bi_idx):
        self.end_bi = StubBi(end_bi_idx, 0)


class StubSeg:
    def __init__(self, bi_list, zs_lst):
        self.bi_list = bi_list
        self.zs_lst = zs_lst
        self.end_bi = bi_list[-1]
        for bi in bi_list:
            bi.parent_seg = self


class StubPoint:
    """最小买卖点桩：type 是 BSP_TYPE 列表，模拟真实 CBS_Point。"""

    def __init__(self, bi, is_buy, types, fx=None, fx_next=True):
        self.bi = bi
        self.is_buy = is_buy
        self.klu = bi.get_end_klu()
        self.type = list(types)
        self.features = CFeatures()
        if fx is not None:
            # 分型：末端合并 K 线带 fx 类型与 next（fx_next 控制是否形成）
            klc = StubKlc(self.klu, fx=fx, nxt=(StubKlc(StubKlu(0)) if fx_next else None))
            self.klu.klc = klc

    def add_feat(self, inp1, inp2=None):
        self.features.add_feat(inp1, inp2)

    def feat(self, key, default=None):
        return dict(self.features.items()).get(key, default)


def make_conf(**extra):
    base = {
        "divergence_rate": 0.9, "min_zs_cnt": 2, "bsp1_only_multibi_zs": True,
        "max_bs2_rate": 0.9999, "macd_algo": "peak", "bs1_peak": True,
        "bs_type": "1,1p,2,2s,3a,3b", "bsp2_follow_1": True, "bsp3_follow_1": True,
        "bsp3_peak": False, "bsp2s_follow_2": False, "max_bsp2s_lv": None,
        "strict_bsp3": False, "bsp3a_max_zs_cnt": 1,
    }
    base.update(extra)
    conf = CBSPointConfig(**base)
    conf.b_conf.parse_target_type()
    conf.s_conf.parse_target_type()
    return conf


def make_lst(**conf_extra):
    return CBSPointList(make_conf(**conf_extra))


def make_parent(bi_ts, entry_conf, parent_types=(BSP_TYPE.T1,), is_buy=True, water=-1):
    """父级容器：线段 bi 10~12，中枢结束笔 bi=9（c 窗口 = bi 10~12）。"""
    bi_list = [StubBi(10 + i, 0, sub_ts=ts) for i, ts in enumerate(bi_ts)]
    seg = StubSeg(bi_list, [StubZS(9)])
    lst = make_lst(**entry_conf)
    lst.last_sure_pos = water
    point = StubPoint(bi_list[0], is_buy, parent_types)
    return lst, point, seg


def make_sub(sure=(), candidates=(), store=(), last_sure=-1, sub_lst=None):
    """次级容器：sure/candidates 进 bsp1 家族；store 是 (BSP_TYPE, StubPoint, is_buy) 列表。"""
    lst = make_lst()
    lst.last_sure_pos = last_sure
    lst.bsp1_sure_list = list(sure)
    lst.bsp1_list = list(sure) + list(candidates)
    for bsp_type, pt, is_buy in store:
        lst.bsp_store_dict.setdefault(bsp_type, {True: [], False: []})
        lst.bsp_store_dict[bsp_type][is_buy].append(pt)
    if sub_lst is not None:
        lst.sub_bs_point_lst = sub_lst
    return lst


# =============================================================================
# 一买（T1 家族）
# =============================================================================

def case_t1_method1_sure_hit():
    print("\n[1买·方法1] 次级同向已确认一买 → 命中 qjt")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)],
                                  {"bsp1_entry": True, "bsp1_entry_qjt": True})
    sub_pt = StubPoint(StubBi(50, 102), True, [BSP_TYPE.T1])
    sub = make_sub(sure=[sub_pt])
    hit, method, lv = entry_point_result(point, sub, lst.config.GetBSConfig(True), parent_lst=lst)
    check("hit=True", hit is True)
    check("method='qjt'", method == 'qjt')
    check("level=1", lv == 1)


def case_t1_method1_candidate_fractal():
    print("\n[1买·方法1] 次级仅候选一买，但末端底分型已形成 → 命中（D4 最低层放宽）")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)],
                                  {"bsp1_entry": True, "bsp1_entry_qjt": True})
    cand_bi = StubBi(50, 102)
    cand = StubPoint(cand_bi, True, [BSP_TYPE.T1], fx=FX_TYPE.BOTTOM, fx_next=True)
    sub = make_sub(candidates=[cand])
    hit, method, lv = entry_point_result(point, sub, lst.config.GetBSConfig(True), parent_lst=lst)
    check("候选+底分型 → hit=True", hit is True, f"实际 ({hit},{method},{lv})")

    print("\n[1买·方法1] 候选一买但分型未形成（无 next）→ 不命中")
    cand2 = StubPoint(StubBi(50, 102), True, [BSP_TYPE.T1], fx=FX_TYPE.BOTTOM, fx_next=False)
    sub = make_sub(candidates=[cand2])
    hit, method, lv = entry_point_result(point, sub, lst.config.GetBSConfig(True), parent_lst=lst)
    check("分型未形成 → hit=False", hit is False, f"实际 ({hit},{method},{lv})")


def case_t1_method2_aux_hit():
    print("\n[1买·方法2] 次级已成立 T2 → 命中 aux")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)],
                                  {"bsp1_entry": True, "bsp1_entry_aux": True})
    t2_pt = StubPoint(StubBi(60, 103), True, [BSP_TYPE.T2])
    sub = make_sub(store=[(BSP_TYPE.T2, t2_pt, True)])
    hit, method, lv = entry_point_result(point, sub, lst.config.GetBSConfig(True), parent_lst=lst)
    check("hit=True", hit is True, f"实际 ({hit},{method},{lv})")
    check("method='aux'", method == 'aux')


def case_t1_method2_right_open():
    print("\n[1买·方法2] 次级 T2 在本级别低点之后（确认滞后）→ 右端外扩后命中")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)],
                                  {"bsp1_entry": True, "bsp1_entry_aux": True})
    # t=108 > c 窗口右端 105：方法1 窗口不含它，方法2 右端至数据末端须命中
    t2_pt = StubPoint(StubBi(60, 108), True, [BSP_TYPE.T2])
    sub = make_sub(store=[(BSP_TYPE.T2, t2_pt, True)])
    hit, method, lv = entry_point_result(point, sub, lst.config.GetBSConfig(True), parent_lst=lst)
    check("右端外扩 → hit=True", hit is True, f"实际 ({hit},{method},{lv})")


def case_t1_method2_excludes_bsp1():
    print("\n[1买·方法2] 次级 T1 不算辅助确认（那是方法1 的领域）→ 不命中")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)],
                                  {"bsp1_entry": True, "bsp1_entry_aux": True})
    t1_pt = StubPoint(StubBi(50, 108), True, [BSP_TYPE.T1])
    sub = make_sub(store=[(BSP_TYPE.T1, t1_pt, True)])
    hit, method, lv = entry_point_result(point, sub, lst.config.GetBSConfig(True), parent_lst=lst)
    check("T1 不构成 aux → hit=False", hit is False, f"实际 ({hit},{method},{lv})")


def case_t1_both_miss():
    print("\n[1买] 双方法均未命中 → hit=False")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)],
                                  {"bsp1_entry": True, "bsp1_entry_qjt": True,
                                   "bsp1_entry_aux": True})
    sub = make_sub()
    hit, method, lv = entry_point_result(point, sub, lst.config.GetBSConfig(True), parent_lst=lst)
    check("hit=False", hit is False, f"实际 ({hit},{method},{lv})")


def case_t1_window_excludes_pre_c():
    print("\n[1买·窗口] 待确认段之前的次级信号不命中（窗口左端= c 段开始）")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)],
                                  {"bsp1_entry": True, "bsp1_entry_qjt": True})
    pre_pt = StubPoint(StubBi(50, 99), True, [BSP_TYPE.T1])
    sub = make_sub(sure=[pre_pt])
    hit, method, lv = entry_point_result(point, sub, lst.config.GetBSConfig(True), parent_lst=lst)
    check("c 段之前不命中", hit is False, f"实际 ({hit},{method},{lv})")


def case_t1_sell_mirror():
    print("\n[1卖·镜像] 次级同向已确认一卖 → 命中")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)],
                                  {"bsp1_entry": True, "bsp1_entry_qjt": True},
                                  parent_types=(BSP_TYPE.T1,), is_buy=False)
    sub_pt = StubPoint(StubBi(50, 102), False, [BSP_TYPE.T1])
    sub = make_sub(sure=[sub_pt])
    hit, method, lv = entry_point_result(point, sub, lst.config.GetBSConfig(False), parent_lst=lst)
    check("卖侧命中", hit is True and method == 'qjt', f"实际 ({hit},{method},{lv})")

    print("\n[1卖·镜像] 方法2：次级二卖（is_buy=False 的 T2）→ 命中 aux")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)],
                                  {"bsp1_entry": True, "bsp1_entry_aux": True},
                                  parent_types=(BSP_TYPE.T1,), is_buy=False)
    t2s_pt = StubPoint(StubBi(60, 103), False, [BSP_TYPE.T2])
    sub = make_sub(store=[(BSP_TYPE.T2, t2s_pt, False)])
    hit, method, lv = entry_point_result(point, sub, lst.config.GetBSConfig(False), parent_lst=lst)
    check("卖侧 aux 命中", hit is True and method == 'aux', f"实际 ({hit},{method},{lv})")


# =============================================================================
# 二买 / 三买（回落段 / 回抽段窗口）
# =============================================================================

def case_t2_method1():
    print("\n[2买·方法1] 次级在回落段内候选一买 + 底分型 → 命中")
    # 2买点落在 bi=10（锚），窗口 = bi 10 ~ seg.end_bi
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)],
                                  {"bsp2_entry": True, "bsp2_entry_qjt": True},
                                  parent_types=(BSP_TYPE.T2,))
    cand = StubPoint(StubBi(50, 103), True, [BSP_TYPE.T1], fx=FX_TYPE.BOTTOM, fx_next=True)
    sub = make_sub(candidates=[cand])
    hit, method, lv = entry_point_result(point, sub, lst.config.GetBSConfig(True), parent_lst=lst)
    check("2买方法1 命中", hit is True and method == 'qjt', f"实际 ({hit},{method},{lv})")


def case_t2_method2():
    print("\n[2买·方法2] 次级已成立三买（回落段范围内）→ 命中 aux")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)],
                                  {"bsp2_entry": True, "bsp2_entry_aux": True},
                                  parent_types=(BSP_TYPE.T2,))
    t3_pt = StubPoint(StubBi(60, 104), True, [BSP_TYPE.T3A])
    sub = make_sub(store=[(BSP_TYPE.T3A, t3_pt, True)])
    hit, method, lv = entry_point_result(point, sub, lst.config.GetBSConfig(True), parent_lst=lst)
    check("2买方法2 命中", hit is True and method == 'aux', f"实际 ({hit},{method},{lv})")


def case_t3_method1():
    print("\n[3买·方法1] 次级在回抽段内候选一买 + 底分型 → 命中")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)],
                                  {"bsp3_entry": True, "bsp3_entry_qjt": True},
                                  parent_types=(BSP_TYPE.T3A,))
    cand = StubPoint(StubBi(50, 102), True, [BSP_TYPE.T1], fx=FX_TYPE.BOTTOM, fx_next=True)
    sub = make_sub(candidates=[cand])
    hit, method, lv = entry_point_result(point, sub, lst.config.GetBSConfig(True), parent_lst=lst)
    check("3买方法1 命中", hit is True and method == 'qjt', f"实际 ({hit},{method},{lv})")


def case_t3_sell_mirror():
    print("\n[3卖·镜像] 次级同向候选一卖 + 顶分型 → 命中")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)],
                                  {"bsp3_entry": True, "bsp3_entry_qjt": True},
                                  parent_types=(BSP_TYPE.T3B,), is_buy=False)
    cand = StubPoint(StubBi(50, 102), False, [BSP_TYPE.T1], fx=FX_TYPE.TOP, fx_next=True)
    sub = make_sub(candidates=[cand])
    hit, method, lv = entry_point_result(point, sub, lst.config.GetBSConfig(False), parent_lst=lst)
    check("3卖方法1 命中", hit is True and method == 'qjt', f"实际 ({hit},{method},{lv})")


# =============================================================================
# 必要条件：水位拦截（design D7）
# =============================================================================

def case_waterline_blocks():
    print("\n[必要条件] 点已越过水位线（段已确认）→ 不判定介入点")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)],
                                  {"bsp1_entry": True, "bsp1_entry_qjt": True},
                                  water=999)  # 水位覆盖全部笔 → 已确认
    sub_pt = StubPoint(StubBi(50, 102), True, [BSP_TYPE.T1])
    sub = make_sub(sure=[sub_pt])
    # 传入父级容器（水位量纲）：make_lst 返回的 lst 是父级
    hit, method, lv = entry_point_result(point, sub, lst.config.GetBSConfig(True), parent_lst=lst)
    check("水位后不命中", hit is False, f"实际 ({hit},{method},{lv})")


# =============================================================================
# 开关矩阵
# =============================================================================

def case_switch_matrix():
    print("\n[开关] 总开关关闭 → 方法开关无效")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)],
                                  {"bsp1_entry": False, "bsp1_entry_qjt": True,
                                   "bsp1_entry_aux": True})
    sub_pt = StubPoint(StubBi(50, 102), True, [BSP_TYPE.T1])
    sub = make_sub(sure=[sub_pt])
    hit, method, lv = entry_point_result(point, sub, lst.config.GetBSConfig(True), parent_lst=lst)
    check("总开关关 → hit=False", hit is False, f"实际 ({hit},{method},{lv})")

    print("\n[开关] 方法1 关、方法2 开，仅方法1 条件满足 → 不命中")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)],
                                  {"bsp1_entry": True, "bsp1_entry_qjt": False,
                                   "bsp1_entry_aux": True})
    sub = make_sub(sure=[sub_pt])
    hit, method, lv = entry_point_result(point, sub, lst.config.GetBSConfig(True), parent_lst=lst)
    check("方法1 关 → 不命中", hit is False, f"实际 ({hit},{method},{lv})")

    print("\n[开关] 方法1 开、方法2 关，仅方法2 条件满足 → 不命中")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)],
                                  {"bsp1_entry": True, "bsp1_entry_qjt": True,
                                   "bsp1_entry_aux": False})
    t2_pt = StubPoint(StubBi(60, 103), True, [BSP_TYPE.T2])
    sub = make_sub(store=[(BSP_TYPE.T2, t2_pt, True)])
    hit, method, lv = entry_point_result(point, sub, lst.config.GetBSConfig(True), parent_lst=lst)
    check("方法2 关 → 不命中", hit is False, f"实际 ({hit},{method},{lv})")


def case_method_priority():
    print("\n[优先级] 双方法同时满足 → method 记 qjt（信息量更高）")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)],
                                  {"bsp1_entry": True, "bsp1_entry_qjt": True,
                                   "bsp1_entry_aux": True})
    sub_pt = StubPoint(StubBi(50, 102), True, [BSP_TYPE.T1])
    t2_pt = StubPoint(StubBi(60, 103), True, [BSP_TYPE.T2])
    sub = make_sub(sure=[sub_pt], store=[(BSP_TYPE.T2, t2_pt, True)])
    hit, method, lv = entry_point_result(point, sub, lst.config.GetBSConfig(True), parent_lst=lst)
    check("method='qjt'", hit is True and method == 'qjt', f"实际 ({hit},{method},{lv})")


def case_legacy_all_off():
    print("\n[legacy] 12 键全关 → 永不命中")
    conf = make_conf(bsp_preset="legacy")
    lst = CBSPointList(conf)
    point = StubPoint(StubBi(10, 0, sub_ts=(100,)), True, [BSP_TYPE.T1])
    sub_pt = StubPoint(StubBi(50, 100), True, [BSP_TYPE.T1])
    sub = make_sub(sure=[sub_pt])
    hit, method, lv = entry_point_result(point, sub, conf.GetBSConfig(True))
    check("legacy → hit=False", hit is False, f"实际 ({hit},{method},{lv})")


# =============================================================================
# 无子级容器 / 非目标类型
# =============================================================================

def case_no_sub():
    print("\n[降级] 无子级容器（sub_lst=None）→ 不命中不报错")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)],
                                  {"bsp1_entry": True, "bsp1_entry_qjt": True})
    hit, method, lv = entry_point_result(point, None, lst.config.GetBSConfig(True))
    check("None → hit=False", hit is False, f"实际 ({hit},{method},{lv})")


def main():
    print("=" * 78)
    print("介入点候选判定：合成验证（tasks 2.2 / 2.3）")
    print("=" * 78)
    case_t1_method1_sure_hit()
    case_t1_method1_candidate_fractal()
    case_t1_method2_aux_hit()
    case_t1_method2_right_open()
    case_t1_method2_excludes_bsp1()
    case_t1_both_miss()
    case_t1_window_excludes_pre_c()
    case_t1_sell_mirror()
    case_t2_method1()
    case_t2_method2()
    case_t3_method1()
    case_t3_sell_mirror()
    case_waterline_blocks()
    case_switch_matrix()
    case_method_priority()
    case_legacy_all_off()
    case_no_sub()
    print()
    synth_ok = not FAILURES
    if not synth_ok:
        print(f"✗ {len(FAILURES)} 项失败：{FAILURES}")
    else:
        print("✓ 合成用例全部通过")

    # ---- step 分支（tasks 2.3 验证）：真实数据批量 vs 步进终态 feature 一致 ----
    step_ok = run_step_consistency()

    print()
    if synth_ok and step_ok:
        print("✓ 全部用例通过（含批量/步进终态 feature 一致）")
        return 0
    print("✗ 存在失败")
    return 1


def run_step_consistency():
    """真实数据（DuckDB 离线）：介入点开全后批量与步进终态 feature 一致。

    介入点是暂时性语义（design D5），feature 在快照间允许翻转，故只比较
    **终态**的 `{bi.idx: (hit, method, level)}` 逐笔相等——模式与
    `bsp_qjt_step.py` 的 qjt 命中集合对账相同。需要 Data/kl_store.duckdb
    存在；缺库时跳过并提示（合成分支已覆盖判定分支）。
    """
    import collections
    from ChanAnalyse.Chan import CChan
    from ChanAnalyse.ChanConfig import CChanConfig
    from ChanAnalyse.Common.CEnum import AUTYPE, KL_TYPE
    from ChanAnalyse.DataAPI.DuckDBAPI import CDuckDB

    db = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "Data", "kl_store.duckdb")
    if not os.path.exists(db):
        print("\n[step] Data/kl_store.duckdb 不存在，跳过批量/步进对账（离线合成分支已覆盖判定分支）")
        return True
    CDuckDB.db_path = db

    print("\n[step] 批量 vs 步进：介入点终态 feature 一致性（sz.000001 日线+30分）")
    conf_tpl = {
        "kl_data_check": False,
        "bsp1_entry": True, "bsp1_entry_qjt": True, "bsp1_entry_qjt_depth": 2,
        "bsp1_entry_aux": True,
        "bsp2_entry": True, "bsp2_entry_qjt": True, "bsp2_entry_aux": True,
        "bsp3_entry": True, "bsp3_entry_qjt": True, "bsp3_entry_aux": True,
    }
    lv_list = [KL_TYPE.K_DAY, KL_TYPE.K_30M]

    def entry_state(chan):
        """全级别收集 {lv: {bi.idx: (hit, method, level)}}。"""
        out = {}
        for lv in lv_list:
            m = {}
            for bsp in chan[lv].bs_point_lst.bsp1_list:
                fd = dict(bsp.features.items())
                if 'entry_hit' in fd or 'entry_method' in fd:
                    m[bsp.bi.idx] = (bool(fd.get('entry_hit')), fd.get('entry_method'),
                                     fd.get('entry_level'))
            for bsp in chan[lv].bs_point_lst.bsp_store_flat_dict.values():
                fd = dict(bsp.features.items())
                if 'entry_hit' in fd or 'entry_method' in fd:
                    m.setdefault(bsp.bi.idx, (bool(fd.get('entry_hit')), fd.get('entry_method'),
                                              fd.get('entry_level')))
            out[lv] = m
        return out

    def run(step):
        conf = dict(conf_tpl, trigger_step=step)
        chan = CChan(code="sz.000001", data_src="custom:DuckDBAPI.CDuckDB",
                     lv_list=lv_list, config=CChanConfig(conf),
                     autype=AUTYPE.QFQ, begin_time="2022-01-01")
        if step:
            n = 0
            for _ in chan.step_load():
                n += 1
            print(f"    步进快照数：{n}")
        return chan

    try:
        batch = run(False)
        step = run(True)
    except Exception as e:
        print(f"    ✗ 运行失败：{e!r}（若为数据/网络原因请检查 DuckDB 库）")
        return False

    ok = True
    sb, ss = entry_state(batch), entry_state(step)
    for lv in lv_list:
        mb, ms = sb[lv], ss[lv]
        common = sorted(set(mb) & set(ms))
        only_b = sorted(set(mb) - set(ms))
        only_s = sorted(set(ms) - set(mb))
        diff = [k for k in common if mb[k] != ms[k]]
        print(f"  {lv.name}: 批量 {len(mb)} 项 / 步进 {len(ms)} 项  "
              f"仅批量 {only_b}  仅步进 {only_s}  值不同 {diff}")
        if only_b or only_s or diff:
            ok = False
            for k in diff[:5]:
                print(f"    bi={k}: 批量 {mb[k]} vs 步进 {ms[k]}")
        else:
            print(f"    ✓ 终态 feature 一致（{len(common)} 项）")
    return ok


if __name__ == '__main__':
    sys.exit(main())
