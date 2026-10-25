# -*- coding: utf-8 -*-
"""
bsp_ladder 三轴阶梯冒烟测试（chan-bsp-ladder-change 任务 3.1/3.2/3.3 验证）。

合成对象直测三条链路，不触真实 CChan/PG/DuckDB，纯内存：

    1. 进度轴   `bsp_progress.judged_steps` / `progress_axis`
                （feature 三布尔 × `bsp1_standard_reason` 闭集）
    2. 佐证轴   `bsp_ladder.corroboration_axis` 三档（L2-3/L2-2/L2-1）
                与互斥短路顺序
    3. 分型轴   `fractal_strength.classify_fx` 三档（含平边界、多根原始 K 线）
    4. 组合     `cal_ladder` 的 L4 短路 / 组合串序 / 非一买返回 None

运行（项目根目录）：
    .venv/Scripts/python.exe Debug/bsp_ladder_smoke.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ChanAnalyse.Common.CEnum import BSP_TYPE  # noqa: E402
from WebAPI import fractal_strength  # noqa: E402
from WebAPI.bsp_ladder import (  # noqa: E402
    AXIS_SEPARATOR,
    LADDER_L4,
    cal_ladder,
    corroboration_axis,
)
from WebAPI.bsp_progress import TOTAL_STEPS, judged_steps, progress_axis  # noqa: E402


# ----------------------------------------------------------------------
# 合成对象
# ----------------------------------------------------------------------

class _Time:
    def __init__(self, ts):
        self.ts = ts


class _Klu:
    def __init__(self, ts, sub_kl_list=(), o=None, c=None, idx=0):
        self.time = _Time(ts)
        self.sub_kl_list = list(sub_kl_list)
        self.idx = idx
        if o is not None:
            self.open = o
            self.close = c


class _Klc:
    """合并 K 线：lst 为原始 K 线；pre/next 为链表邻居（分型三根）。"""

    def __init__(self, units, pre=None, next=None):
        self.lst = list(units)
        self.pre = pre
        self.next = next


def _chain(*klcs):
    """把若干合并 K 线串成 pre/next 双向链表，返回中间那根。"""
    for i, k in enumerate(klcs):
        k.pre = klcs[i - 1] if i > 0 else None
        k.next = klcs[i + 1] if i + 1 < len(klcs) else None
    return klcs[len(klcs) // 2]


class _Bi:
    def __init__(self, idx, is_down, end_klu, klc_lst=None):
        self.idx = idx
        self.dir = 'down' if is_down else 'up'
        self._end = end_klu
        self.klc_lst = list(klc_lst or [])

    def get_end_klu(self):
        return self._end


class _Bsp:
    def __init__(self, bi, is_buy=True, bsp_type=(BSP_TYPE.T1,), feats=None, klu=None):
        self.bi = bi
        self.is_buy = is_buy
        self.type = list(bsp_type)
        self.klu = klu or bi.get_end_klu()
        self._feats = dict(feats or {})

    @property
    def features(self):
        return _Features(self._feats)


class _Features:
    def __init__(self, d):
        self._d = d

    def items(self):
        return self._d.items()

    def del_feat(self, k):
        self._d.pop(k, None)


class _BspList:
    def __init__(self, last_sure_pos, bsp1_list=None, bsp1_sure_list=None):
        self.last_sure_pos = last_sure_pos
        self.bsp1_list = list(bsp1_list or [])
        self.bsp1_sure_list = list(bsp1_sure_list or [])


# 完整判据链全过（①~⑦）的 feature
FEAT_ALL_PASS = {
    'bsp1_step_break': True,
    'bsp1_step_peak': True,
    'bsp1_step_diver': True,
    'bsp1_standard_reason': None,
}


def _feat(break_=True, peak=True, diver=True, reason=None):
    return {'bsp1_step_break': break_, 'bsp1_step_peak': peak,
            'bsp1_step_diver': diver, 'bsp1_standard_reason': reason}


# ----------------------------------------------------------------------
# 1. 进度轴
# ----------------------------------------------------------------------

def check_progress():
    r = []

    def case(name, feat, expect_steps, expect_axis):
        st = judged_steps(feat)
        ax = progress_axis(feat)
        r.append((f"progress {name}", st == expect_steps and ax == expect_axis, f"{st}/{ax}"))

    # reason 闭集 × feature 逐项不通
    case('trend fail', _feat(False, False, False, 'trend'), 0, 'L1')
    case('break fail', _feat(False, True, True, 'new_extreme'), 1, 'L1')
    case('peak fail', _feat(True, False, True, 'new_extreme'), 2, 'L1')
    case('diver fail', _feat(True, True, False, None), 3, 'L1')
    case('new_extreme', _feat(True, True, True, 'new_extreme'), 4, 'L1')
    case('dif_div', _feat(True, True, True, 'dif_div'), 5, 'L2')
    case('zero_axis', _feat(True, True, True, 'zero_axis'), 6, 'L2')
    case('all pass', FEAT_ALL_PASS, TOTAL_STEPS, 'L2')
    # 缺键（存量点）→ 不猜
    case('missing step keys', {'bsp1_standard_reason': None}, None, None)
    case('missing reason key',
         {'bsp1_step_break': True, 'bsp1_step_peak': True, 'bsp1_step_diver': True}, None, None)
    case('empty', None, None, None)
    return r


# ----------------------------------------------------------------------
# 2. 佐证轴
# ----------------------------------------------------------------------

def _build_parent():
    """父级结构：线段 seg 的 c 窗口 = 笔 idx 2..3；窗口内子级时间戳落在 [150, 190]。

    c 窗口口径与内核 `_c_window_of` 同源：`zs.end_bi.idx + 1 ~ seg.end_bi.idx`。
    """
    klu2 = _Klu(150, sub_kl_list=[_Klu(150), _Klu(170)])
    klu3 = _Klu(200, sub_kl_list=[_Klu(190)])
    # 窗口内每根父级 K 线的 klc.lst 是原始 K 线，它们的 sub_kl_list 挂子级 K 线。
    # `_sub_time_span` 沿 klc_lst → lst → sub_kl_list 取时间戳，mock 必须同构。
    bi2 = _Bi(2, True, klu2, klc_lst=[_Klc([klu2])])
    bi3 = _Bi(3, True, klu3, klc_lst=[_Klc([klu3])])
    bi0 = _Bi(0, True, _Klu(50))
    bi1 = _Bi(1, False, _Klu(80))

    zs = type('Zs', (), {})()
    zs.end_bi = bi1                       # c_start = 1 + 1 = 2

    seg = type('Seg', (), {})()
    seg.bi_list = [bi0, bi1, bi2, bi3]
    seg.zs_lst = [zs]
    seg.end_bi = bi3                      # c_end = 3

    bi2.parent_seg = seg

    # 买卖点所在笔终点的合并 K 线（分型三根完整；默认 C 收复超过 A 实体一半）
    a = _Klc([_Klu(0, o=20.0, c=19.0)])
    b = _Klc([_Klu(0, o=13.0, c=13.5, idx=5)])
    c = _Klc([_Klu(0, o=19.6, c=19.8)])
    _chain(a, b, c)
    return bi2, b


def check_corroboration():
    r = []
    bi, fx_klc = _build_parent()

    def mk_klu_bi(ts):
        return _Bi(9, True, _Klu(ts))

    def sub_point(ts, is_buy=True, feats=None):
        sub_bi = mk_klu_bi(ts)
        return _Bsp(sub_bi, is_buy=is_buy, feats=feats)

    # ---- L2-3：窗口内同向已确认（子级 bsp1_sure_list）----
    sub_lst = _BspList(0, bsp1_sure_list=[sub_point(170)])
    bsp = _Bsp(bi, is_buy=True, feats=FEAT_ALL_PASS, klu=fx_klc.lst[0])
    r.append(("corrob L2-3 sure in window",
              corroboration_axis(bsp, sub_lst) == 'L2-3',
              corroboration_axis(bsp, sub_lst)))

    # ---- 方向相反不算 ----
    sub_lst = _BspList(0, bsp1_sure_list=[sub_point(170, is_buy=False)])
    r.append(("corrob opposite dir no hit",
              corroboration_axis(bsp, sub_lst) is None,
              corroboration_axis(bsp, sub_lst)))

    # ---- 窗口外不算 ----
    sub_lst = _BspList(0, bsp1_sure_list=[sub_point(250)])
    r.append(("corrob out of window no hit",
              corroboration_axis(bsp, sub_lst) is None,
              corroboration_axis(bsp, sub_lst)))

    # ---- L2-2：子级候选（bsp1_list）且进度在 L1 ----
    cand = sub_point(170, feats=_feat(True, True, True, 'new_extreme'))
    sub_lst = _BspList(0, bsp1_list=[cand])
    r.append(("corrob L2-2 candidate L1",
              corroboration_axis(bsp, sub_lst) == 'L2-2',
              corroboration_axis(bsp, sub_lst)))

    # ---- 子级候选进度已到 L2 → 不算「部分达成」----
    cand_l2 = sub_point(170, feats=FEAT_ALL_PASS)
    sub_lst = _BspList(0, bsp1_list=[cand_l2])
    r.append(("corrob candidate L2 no hit",
              corroboration_axis(bsp, sub_lst) is None,
              corroboration_axis(bsp, sub_lst)))

    # ---- L2-3 优先于 L2-2（互斥短路）----
    sub_lst = _BspList(0, bsp1_list=[cand], bsp1_sure_list=[sub_point(150)])
    r.append(("corrob L2-3 over L2-2",
              corroboration_axis(bsp, sub_lst) == 'L2-3',
              corroboration_axis(bsp, sub_lst)))

    # ---- L2-1：仅子级末端分型（无已确认点、无候选点）----
    # 子级 CKLine_List：末端笔终点落在窗口内且形成底分型
    sa = _Klc([_Klu(0, o=20.0, c=19.0)])
    sb = _Klc([_Klu(0, o=15.0, c=15.5)])
    sc = _Klc([_Klu(0, o=16.0, c=17.5)])  # C_max=17.5 > A_max=20? 否；>= 19.5? 否 → 弱
    _chain(sa, sb, sc)
    sub_bi = _Bi(3, True, _Klu(180))
    sub_bi._end.klc = sb
    sub_kl = type('S', (), {})()
    sub_kl.bi_list = [sub_bi]
    sub_lst = _BspList(0)
    r.append(("corrob L2-1 fractal",
              corroboration_axis(bsp, sub_lst, sub_kl=sub_kl) == 'L2-1',
              corroboration_axis(bsp, sub_lst, sub_kl=sub_kl)))

    # ---- 子级容器缺失 → 佐证轴跳过 ----
    r.append(("corrob no sub container → None",
              corroboration_axis(bsp, None) is None,
              corroboration_axis(bsp, None)))
    return r


# ----------------------------------------------------------------------
# 3. 分型轴
# ----------------------------------------------------------------------

def check_fractal():
    r = []
    cf = fractal_strength.classify_fx

    def klc(o, c):
        return _Klc([_Klu(0, o=o, c=c)])

    A = klc(20.0, 19.0)   # a_min=19, a_max=20, 中线 19.5

    def case(name, c_klc, expect):
        got = cf(A, klc(15.0, 15.5), c_klc, True)
        r.append((f"fractal {name}", got == expect, got))

    case('buy strong  C_max>A_max', klc(21.0, 22.0), fractal_strength.FRACTAL_STRONG)
    case('buy medium  C_max=mid+', klc(19.6, 19.8), fractal_strength.FRACTAL_MEDIUM)
    case('buy medium  C_max==mid boundary', klc(19.5, 19.5), fractal_strength.FRACTAL_MEDIUM)
    case('buy medium  C_max==A_max boundary', klc(20.0, 20.0), fractal_strength.FRACTAL_MEDIUM)
    case('buy weak    C_max<mid', klc(16.0, 17.0), fractal_strength.FRACTAL_WEAK)

    # 多根原始 K 线聚合：实体边界取最大/最小
    multi = _Klc([_Klu(0, o=18.0, c=18.5), _Klu(0, o=20.5, c=20.0)])  # max=20.5
    r.append(("fractal multi-unit C_max=20.5 > A_max → strong",
              cf(A, klc(15.0, 15.5), multi, True) == fractal_strength.FRACTAL_STRONG,
              cf(A, klc(15.0, 15.5), multi, True)))

    # 卖点侧镜像
    A2 = klc(20.0, 19.0)   # 中线 19.5
    r.append(("fractal sell strong C_min<A_min",
              cf(A2, klc(15.0, 15.5), klc(17.0, 18.0), False) == fractal_strength.FRACTAL_STRONG,
              cf(A2, klc(15.0, 15.5), klc(17.0, 18.0), False)))
    r.append(("fractal sell medium C_min<=mid",
              cf(A2, klc(15.0, 15.5), klc(19.4, 19.6), False) == fractal_strength.FRACTAL_MEDIUM,
              cf(A2, klc(15.0, 15.5), klc(19.4, 19.6), False)))
    r.append(("fractal sell weak C_min>mid",
              cf(A2, klc(15.0, 15.5), klc(19.6, 20.5), False) == fractal_strength.FRACTAL_WEAK,
              cf(A2, klc(15.0, 15.5), klc(19.6, 20.5), False)))

    # 分型未形成（next 缺失）
    r.append(("fractal no next → None",
              cf(A, klc(15.0, 15.5), None, True) is None,
              cf(A, klc(15.0, 15.5), None, True)))
    # 实体不可评估（原始 K 线无 open/close）
    r.append(("fractal unreadable entity → None",
              cf(A, klc(15.0, 15.5), _Klc([_Klu(0)]), True) is None,
              cf(A, klc(15.0, 15.5), _Klc([_Klu(0)]), True)))
    return r


# ----------------------------------------------------------------------
# 4. 组合
# ----------------------------------------------------------------------

def check_ladder():
    r = []
    bi, fx_klc = _build_parent()

    # L4：水位线覆盖（end_idx <= last_sure_pos）
    bsp = _Bsp(bi, is_buy=True, feats=FEAT_ALL_PASS, klu=fx_klc.lst[0])
    r.append(("ladder L4 short-circuit",
              cal_ladder(bsp, _BspList(999)) == LADDER_L4,
              cal_ladder(bsp, _BspList(999))))

    # 三轴齐备：进度 L2 + 佐证 L2-3 + 分型 L3-2
    #   A_max=20, C_max=19.8 → 中
    a = _Klc([_Klu(0, o=20.0, c=19.0)])
    b = _Klc([_Klu(0, o=13.0, c=13.5)])
    c = _Klc([_Klu(0, o=19.6, c=19.8)])
    _chain(a, b, c)
    bi._end.klc = b
    bsp = _Bsp(bi, is_buy=True, feats=FEAT_ALL_PASS, klu=fx_klc.lst[0])
    sub_lst = _BspList(0, bsp1_sure_list=[_Bsp(_Bi(9, True, _Klu(170)), is_buy=True)])
    got = cal_ladder(bsp, _BspList(0), sub_bs_point_lst=sub_lst)
    expect = AXIS_SEPARATOR.join(['L2', 'L2-3', 'L3-2'])
    r.append(("ladder 3-axis order progress→corrob→fractal", got == expect, f"{got} vs {expect}"))

    # 佐证轴缺席（无子级容器）→ 两轴组合
    got = cal_ladder(bsp, _BspList(0))
    expect = AXIS_SEPARATOR.join(['L2', 'L3-2'])
    r.append(("ladder no sub → 2 axes", got == expect, f"{got} vs {expect}"))

    # 进度不可评估（缺 feature 键）→ 只剩佐证/分型
    bsp_no_feat = _Bsp(bi, is_buy=True, feats={}, klu=fx_klc.lst[0])
    got = cal_ladder(bsp_no_feat, _BspList(0))
    r.append(("ladder missing feature → no progress axis",
              got == 'L3-2', got))

    # 非一买家族 → None（本次不接入）
    bsp_t2 = _Bsp(bi, is_buy=True, bsp_type=(BSP_TYPE.T2,), feats=FEAT_ALL_PASS)
    r.append(("ladder non-bsp1 → None",
              cal_ladder(bsp_t2, _BspList(0)) is None,
              cal_ladder(bsp_t2, _BspList(0))))

    # 一切皆不可评估 → None
    bi_no_fx = _Bi(3, True, _Klu(180))
    bsp_bare = _Bsp(bi_no_fx, is_buy=True, feats={})
    r.append(("ladder nothing evaluable → None",
              cal_ladder(bsp_bare, _BspList(0)) is None,
              cal_ladder(bsp_bare, _BspList(0))))
    return r


def main():
    results = check_progress() + check_corroboration() + check_fractal() + check_ladder()
    ok = True
    for name, passed, val in results:
        print(f"[{'PASS' if passed else 'FAIL'}] {name}: {val}")
        ok = ok and passed
    print(f"\n== bsp_ladder 三轴冒烟: {sum(1 for _, p, _ in results if p)}/{len(results)} PASS ==")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
