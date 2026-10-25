# -*- coding: utf-8 -*-
"""
区间套特征的命中资格与递归深度验证（chan-standard-bsp1-change tasks 10.5 / 10.6）

为什么用桩件而不是真实 K 线：命中资格的四条分支（同向已确认 / 仅候选 /
反向 / 窗口外）在真实数据上无法逐条构造——同一个交易日不可能既在 c 段内
又在 c 段外、同一位置也不可能既买又卖。真实数据只能给出「命中率是多少」，
无法证明「不该命中的确实没命中」。因此本脚本在**结构层**构造最小可辨识的
父/子两级对象，直接喂给 `CBSPointList._annotate_qjt`。

真实数据上的数量与命中率统计在 `Debug/bsp_standard_equivalence.py` 第 8 节。

运行（项目根目录）：
    .venv/Scripts/python.exe Debug/bsp_qjt_synth.py

任一断言失败 → 打印失败项并以非零码退出。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ChanAnalyse.BuySellPoint.BSPointConfig import CBSPointConfig  # noqa: E402
from ChanAnalyse.BuySellPoint.BSPointList import CBSPointList  # noqa: E402
from ChanAnalyse.ChanModel.Features import CFeatures  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        FAILURES.append(name)


# =============================================================================
# 桩件：只提供 _annotate_qjt / _c_window_of / _sub_time_span 实际读取的成员
# =============================================================================

class StubTime:
    def __init__(self, ts):
        self.ts = ts


class StubKlu:
    def __init__(self, ts):
        self.time = StubTime(ts)
        self.sub_kl_list = []


class StubKlc:
    def __init__(self, lst):
        self.lst = lst


class StubBi:
    def __init__(self, idx, end_ts, sub_ts=()):
        self.idx = idx
        self._klu = StubKlu(end_ts)
        # 该笔覆盖的原始 K 线；每根带若干子级 K 线（时间戳由 sub_ts 指定）
        klus = [StubKlu(end_ts)]
        klus[0].sub_kl_list = [StubKlu(t) for t in sub_ts]
        self.klc_lst = [StubKlc(klus)]
        self.parent_seg = None

    def get_end_klu(self):
        return self._klu


class StubZS:
    def __init__(self, end_bi_idx):
        self.end_bi = StubBi(end_bi_idx, 0)

    def get_bi_in(self):
        return StubBi(0, 0)


class StubSeg:
    def __init__(self, bi_list, zs_lst):
        self.bi_list = bi_list
        self.zs_lst = zs_lst
        self.end_bi = bi_list[-1]
        for bi in bi_list:
            bi.parent_seg = self


class StubPoint:
    """最小买卖点桩：`_annotate_qjt` 只需要 bi / is_buy / klu / features。"""

    def __init__(self, bi, is_buy):
        self.bi = bi
        self.is_buy = is_buy
        self.klu = bi.get_end_klu()
        self.features = CFeatures()

    def add_feat(self, inp1, inp2=None):
        self.features.add_feat(inp1, inp2)

    def feat(self, key, default=None):
        return dict(self.features.items()).get(key, default)


def make_lst(**conf_extra):
    conf = CBSPointConfig(**{
        "divergence_rate": 0.9, "min_zs_cnt": 2, "bsp1_only_multibi_zs": True,
        "max_bs2_rate": 0.9999, "macd_algo": "peak", "bs1_peak": True,
        "bs_type": "1,1p,2,2s,3a,3b", "bsp2_follow_1": True, "bsp3_follow_1": True,
        "bsp3_peak": False, "bsp2s_follow_2": False, "max_bsp2s_lv": None,
        "strict_bsp3": False, "bsp3a_max_zs_cnt": 1,
        "bsp1_trend": True, "bsp1_new_extreme": True, "bsp1_dif_div": True,
        "bsp1_zero_axis": True, "bsp1_qjt": True,
        **conf_extra,
    })
    conf.b_conf.parse_target_type()
    conf.s_conf.parse_target_type()
    return CBSPointList(conf)


def make_sub_lst(sure_points=(), candidates=(), sub_lst=None):
    """构造次级容器：sure_points 进 bsp1_sure_list，candidates 只进 bsp1_list。"""
    lst = make_lst()
    lst.bsp1_sure_list = list(sure_points)
    lst.bsp1_list = list(sure_points) + list(candidates)
    if sub_lst is not None:
        lst.sub_bs_point_lst = sub_lst
    return lst


def make_parent(c_window_ts, depth=1):
    """父级：线段由 bi 10~12 构成，中枢结束笔 bi=9 → c 窗口 = bi 10~12。

    c_window_ts 是这三笔各自携带的子级 K 线时间戳，形如 [(100,101),(102,103),...]。
    返回 (lst, parent_point)。
    """
    bi_list = [StubBi(10 + i, 0, sub_ts=ts) for i, ts in enumerate(c_window_ts)]
    seg = StubSeg(bi_list, [StubZS(9)])
    lst = make_lst(bsp1_qjt_depth=depth)
    # 父级候选点落在 bi=10（c 段首笔）
    point = StubPoint(bi_list[0], is_buy=True)
    lst.bsp1_list = [point]
    return lst, point, seg


def child_bi(idx, ts, deeper_ts=()):
    """子级一笔：klu 时间 = ts；deeper_ts 为它携带的次次级 K 线时间戳。"""
    return StubBi(idx, ts, sub_ts=deeper_ts)


def run(lst, seg, sub_lst):
    lst.sub_bs_point_lst = sub_lst
    lst._annotate_qjt()


# =============================================================================
# tasks 10.5：命中资格三条件
# =============================================================================

def case_hit_same_dir_sure():
    print("\n[10.5-①] 次级同向且已确认 → 命中")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)])
    sub = make_sub_lst(sure_points=[StubPoint(child_bi(50, 102), is_buy=True)])
    run(lst, seg, sub)
    check("bsp1_qjt_hit 为 True", point.feat('bsp1_qjt_hit') is True,
          f"实际 {point.feat('bsp1_qjt_hit')}")
    check("bsp1_qjt_sub_idx == 50", point.feat('bsp1_qjt_sub_idx') == 50,
          f"实际 {point.feat('bsp1_qjt_sub_idx')}")


def case_candidate_only():
    print("\n[10.5-②] 次级同向但仅在 bsp1_list 候选、未进 bsp1_sure_list → 不命中")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)])
    sub = make_sub_lst(candidates=[StubPoint(child_bi(50, 102), is_buy=True)])
    run(lst, seg, sub)
    check("候选不构成命中", point.feat('bsp1_qjt_hit') is False,
          f"实际 {point.feat('bsp1_qjt_hit')}")
    check("未写入 sub_idx", point.feat('bsp1_qjt_sub_idx') is None,
          f"实际 {point.feat('bsp1_qjt_sub_idx')}")


def case_reverse_dir():
    print("\n[10.5-③] 次级反向已确认 → 不命中")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)])
    sub = make_sub_lst(sure_points=[StubPoint(child_bi(50, 102), is_buy=False)])
    run(lst, seg, sub)
    check("方向相反不构成命中", point.feat('bsp1_qjt_hit') is False,
          f"实际 {point.feat('bsp1_qjt_hit')}")


def case_outside_window():
    print("\n[10.5-④] 次级区间外（c 段开始之前）的同向已确认 → 不命中")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)])
    # ts=99 落在 c 段（100~105）之前：属进入段衰竭，spec「窗口排除 c 段之前的衰竭」
    sub = make_sub_lst(sure_points=[StubPoint(child_bi(50, 99), is_buy=True)])
    run(lst, seg, sub)
    check("窗口外不构成命中", point.feat('bsp1_qjt_hit') is False,
          f"实际 {point.feat('bsp1_qjt_hit')}")

    print("\n[10.5-④b] 次级区间外（c 段结束之后）同样不命中")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)])
    sub = make_sub_lst(sure_points=[StubPoint(child_bi(51, 106), is_buy=True)])
    run(lst, seg, sub)
    check("窗口右边界外不构成命中", point.feat('bsp1_qjt_hit') is False,
          f"实际 {point.feat('bsp1_qjt_hit')}")


def case_window_matches_force_scope():
    print("\n[10.5-补充] 窗口边界恰为 zs.end_bi+1 ~ seg.end_bi（与力度口径同源）")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)])
    # bi=9（中枢结束笔）携带的子级时间戳不应进入窗口
    seg.bi_list.insert(0, StubBi(9, 0, sub_ts=(90,)))
    seg.bi_list[0].parent_seg = seg
    sub = make_sub_lst(sure_points=[StubPoint(child_bi(50, 90), is_buy=True)])
    run(lst, seg, sub)
    check("中枢结束笔不在 c 窗口内", point.feat('bsp1_qjt_hit') is False,
          f"实际 {point.feat('bsp1_qjt_hit')}")


def case_downgrade_not_eligible():
    print("\n[补充] 次级降级点（只进 bsp1_list 候选、不进 sure）不参与命中资格")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)])
    sub_sure = [StubPoint(child_bi(41, 98), is_buy=True)]      # 窗口外的成立点
    sub_dg = StubPoint(child_bi(50, 102), is_buy=True)
    sub_dg.add_feat({'bsp1_downgrade_reason': 'single_zs'})     # 降级点：仅候选
    sub = make_sub_lst(sure_points=sub_sure, candidates=[sub_dg])
    run(lst, seg, sub)
    check("降级点不被当作子级成立一买", point.feat('bsp1_qjt_hit') is False,
          f"实际 {point.feat('bsp1_qjt_hit')}")


# =============================================================================
# tasks 10.6：递归深度
# =============================================================================

def _deep_pair():
    """构造：本级 c 段(100~105) 内有子级点 bi=50@102；
    子级点自身的 c 段映射到次次级 200~205，其内存在（或不存在）同向点。"""
    sub_bi = [StubBi(50, 102, sub_ts=(200, 201)), StubBi(51, 103, sub_ts=(204, 205))]
    sub_seg = StubSeg(sub_bi, [StubZS(49)])
    sub_point = StubPoint(sub_bi[0], is_buy=True)
    return sub_point, sub_seg


def case_depth_one_ignores_deeper():
    print("\n[10.6] 深度 1：次次级存在同向点也不影响本级命中（只向直接次级递归一层）")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)], depth=1)
    sub_point, sub_seg = _deep_pair()
    deeper = make_sub_lst(sure_points=[StubPoint(child_bi(90, 202), is_buy=True)])
    sub = make_sub_lst(sure_points=[sub_point], sub_lst=deeper)
    run(lst, seg, sub)
    check("深度 1 命中直接次级点", point.feat('bsp1_qjt_hit') is True,
          f"实际 {point.feat('bsp1_qjt_hit')}")
    check("命中索引为直接次级笔 50", point.feat('bsp1_qjt_sub_idx') == 50,
          f"实际 {point.feat('bsp1_qjt_sub_idx')}")

    print("\n[10.6] 深度 1：次次级缺失同向点不影响本级命中（不递归即不惩罚）")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)], depth=1)
    sub_point, _ = _deep_pair()
    sub = make_sub_lst(sure_points=[sub_point],
                       sub_lst=make_sub_lst(sure_points=[]))
    run(lst, seg, sub)
    check("深度 1 仍命中", point.feat('bsp1_qjt_hit') is True,
          f"实际 {point.feat('bsp1_qjt_hit')}")

    print("\n[10.6] 深度 1：只有次次级有点、直接次级没有 → 不命中（不穿透）")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)], depth=1)
    deeper = make_sub_lst(sure_points=[StubPoint(child_bi(90, 202), is_buy=True)])
    sub = make_sub_lst(sure_points=[], sub_lst=deeper)
    run(lst, seg, sub)
    check("直接次级为空则不命中", point.feat('bsp1_qjt_hit') is False,
          f"实际 {point.feat('bsp1_qjt_hit')}")


def case_depth_two_requires_deeper():
    print("\n[10.6] 深度 2：次次级有同向点 → 命中")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)], depth=2)
    sub_point, _ = _deep_pair()
    deeper = make_sub_lst(sure_points=[StubPoint(child_bi(90, 202), is_buy=True)])
    sub = make_sub_lst(sure_points=[sub_point], sub_lst=deeper)
    run(lst, seg, sub)
    check("两级链均成立 → 命中", point.feat('bsp1_qjt_hit') is True,
          f"实际 {point.feat('bsp1_qjt_hit')}")

    print("\n[10.6] 深度 2：次次级无同向点 → 不命中（链断）")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)], depth=2)
    sub_point, _ = _deep_pair()
    deeper = make_sub_lst(sure_points=[StubPoint(child_bi(90, 999), is_buy=True)])
    sub = make_sub_lst(sure_points=[sub_point], sub_lst=deeper)
    run(lst, seg, sub)
    check("次次级窗口外 → 本级不命中", point.feat('bsp1_qjt_hit') is False,
          f"实际 {point.feat('bsp1_qjt_hit')}")

    print("\n[10.6] 深度 2：次次级容器缺失 → 退化为按已到达层数判定（不假阴性）")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)], depth=2)
    sub_point, _ = _deep_pair()
    sub = make_sub_lst(sure_points=[sub_point])       # 未挂 next 层容器
    run(lst, seg, sub)
    check("级别不足时不惩罚", point.feat('bsp1_qjt_hit') is True,
          f"实际 {point.feat('bsp1_qjt_hit')}")


# =============================================================================
# 开关与陈旧特征清理
# =============================================================================

def case_switch_off():
    print("\n[补充] bsp1_qjt=False → 不写任何特征字段")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)])
    lst.config.b_conf.bsp1_qjt = False
    lst.config.s_conf.bsp1_qjt = False
    sub = make_sub_lst(sure_points=[StubPoint(child_bi(50, 102), is_buy=True)])
    run(lst, seg, sub)
    fd = dict(point.features.items())
    check("无区间套特征字段", 'bsp1_qjt_hit' not in fd, f"实际 {fd}")


def case_stale_sub_idx_cleared():
    print("\n[补充] 由命中重算为不命中时，陈旧的 sub_idx 须同步摘除")
    lst, point, seg = make_parent([(100, 101), (102, 103), (104, 105)])
    sub = make_sub_lst(sure_points=[StubPoint(child_bi(50, 102), is_buy=True)])
    run(lst, seg, sub)
    check("首轮命中", point.feat('bsp1_qjt_hit') is True)
    run(lst, seg, make_sub_lst(sure_points=[]))          # 子级点被重算掉
    check("重算后 hit 变 False", point.feat('bsp1_qjt_hit') is False,
          f"实际 {point.feat('bsp1_qjt_hit')}")
    check("陈旧 sub_idx 已摘除", point.feat('bsp1_qjt_sub_idx') is None,
          f"实际 {point.feat('bsp1_qjt_sub_idx')}")


def main():
    print("=" * 78)
    print("区间套特征：命中资格与递归深度（tasks 10.5 / 10.6）")
    print("=" * 78)
    case_hit_same_dir_sure()
    case_candidate_only()
    case_reverse_dir()
    case_outside_window()
    case_window_matches_force_scope()
    case_downgrade_not_eligible()
    case_depth_one_ignores_deeper()
    case_depth_two_requires_deeper()
    case_switch_off()
    case_stale_sub_idx_cleared()
    print()
    if FAILURES:
        print(f"✗ {len(FAILURES)} 项失败：{FAILURES}")
        return 1
    print("✓ 全部用例通过")
    return 0


if __name__ == '__main__':
    sys.exit(main())
