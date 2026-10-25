# -*- coding: utf-8 -*-
"""
买卖点标准判据 - 与层级无关的纯函数集合

抽出本模块的原因：
    `CBSPointList` 是泛型的，`bs_point_lst`（笔级别）与 `seg_bs_point_lst`
    （线段级别）实例化同一个类，元素类型分别是 `CBi` 与 `CSeg`。
    标准判据必须对两个层级**同构**，否则两个公开 API 会给出互相矛盾的结果。

    因此判据全部写成「要素 + 要素序列 + 中枢列表 + 配置」的纯函数，
    只依赖 `CBi` 与 `CSeg` 共有的接口：
        `idx` / `is_up()` / `is_down()` / `_low()` / `_high()` /
        `get_begin_klu()` / `get_end_klu()` / `amp()` / `cal_macd_metric()`

契约：
    每个 `check_*` 返回 `(ok: bool, info: dict)`。`info` 用于诊断与 feature_dict，
    调用方不应依赖其具体键名做判定。
"""

from typing import List, Optional, Sequence

from ChanAnalyse.Common.CEnum import MACD_ALGO


# =============================================================================
# 一买 / 一卖
# =============================================================================

def get_trend_zs_pair(zs_lst: Sequence, is_buy: bool, mode: str = "strict") -> Optional[tuple]:
    """
    从线段的中枢列表中找出「构成趋势的最后一对中枢」

    返回:
        (前一个中枢, 最后一个中枢) 或 None（不构成趋势）

    判定（买点，即下跌趋势）：
        strict  : `z2.high < z1.low`  —— 两个中枢完全不重叠
        overlap : `z2.high < z1.high and z2.low < z1.low` —— 依次下移但允许重叠

    卖点镜像。
    """
    multi = [zs for zs in zs_lst if not zs.is_one_bi_zs()]
    if len(multi) < 2:
        return None
    z1, z2 = multi[-2], multi[-1]
    if is_buy:
        if mode == "strict":
            ok = z2.high < z1.low
        else:
            ok = z2.high < z1.high and z2.low < z1.low
    else:
        if mode == "strict":
            ok = z2.low > z1.high
        else:
            ok = z2.low > z1.low and z2.high > z1.high
    return (z1, z2) if ok else None


def check_trend(ele, ele_list, zs_lst, is_buy: bool, mode: str = "strict"):
    """
    趋势前提：必须存在两个依次下移/上移的同级别中枢

    返回 (ok, info)，info 含 `zs_cnt`（多笔中枢数）与 `trend_pair`。
    """
    multi = [zs for zs in zs_lst if not zs.is_one_bi_zs()]
    pair = get_trend_zs_pair(zs_lst, is_buy, mode)
    return pair is not None, {'zs_cnt': len(multi), 'trend_zs_pair': pair}


def check_new_extreme(ele, ele_list, zs_lst, is_buy: bool,
                      mode: str = "trend_start"):
    """
    创趋势新低/新高

    `ele` 是待判定的离开要素（一买所在的那一笔/线段）。要求它的极值严格优于
    「趋势起点之后、到 `ele` 为止」的全部同向要素。

    起点口径（`mode`）：
        trend_start : 第一个趋势中枢的进入要素（默认，覆盖完整趋势）
        prev_zs_in  : 最后一个趋势中枢的进入要素（只与 b 段比）
        all         : 该线段内全部同向要素

    返回 (ok, info)，info 含 `ref_start_idx` 与 `worse_cnt`。
    """
    pair = get_trend_zs_pair(zs_lst, is_buy, "strict") or get_trend_zs_pair(zs_lst, is_buy, "overlap")
    if mode == "all" or pair is None:
        start_idx = 0
    elif mode == "prev_zs_in":
        z2 = pair[1]
        bi_in = z2.bi_in
        start_idx = bi_in.idx if bi_in is not None else 0
    else:  # trend_start
        z1 = pair[0]
        bi_in = z1.bi_in
        start_idx = bi_in.idx if bi_in is not None else 0

    same_dir = [e for e in ele_list
                if e.idx >= start_idx and e.idx < ele.idx and e.is_down() == is_buy]
    if is_buy:
        worse = [e.idx for e in same_dir if e._low() < ele._low()]
    else:
        worse = [e.idx for e in same_dir if e._high() > ele._high()]
    return len(worse) == 0, {'ref_start_idx': start_idx, 'worse_cnt': len(worse)}


def check_dif_divergence(ele, zs, is_buy: bool):
    """
    DIF（黄白线）背驰：离开段的 DIF 极值相对进入段不创新低/新高

    买点：`min(DIF)` of ele > `min(DIF)` of bi_in
    卖点：`max(DIF)` of ele < `max(DIF)` of bi_in
    """
    bi_in = zs.bi_in
    if bi_in is None:
        return False, {'dif_in': None, 'dif_out': None}
    dif_in = bi_in.cal_macd_metric(MACD_ALGO.DIFF_PEAK, is_reverse=False)
    dif_out = ele.cal_macd_metric(MACD_ALGO.DIFF_PEAK, is_reverse=True)
    ok = dif_out > dif_in if is_buy else dif_out < dif_in
    return ok, {'dif_in': dif_in, 'dif_out': dif_out}


def check_zero_axis(ele, zs, is_buy: bool):
    """
    零轴回抽：进入段结束到离开段开始之间，DIF 曾穿越零轴

    买点要求期间出现过 `DIF > 0`；卖点要求出现过 `DIF < 0`。

    实现说明：离散数据上「穿越零轴」最稳的可判定形式就是「期间曾出现反号」。
    若要求「穿越后再穿回」，在 b 段结束与 c 段开始之间往往只有 1 根 K 线，
    判据会退化为几乎不可判定。
    """
    bi_in = zs.bi_in
    if bi_in is None:
        return False, {'zero_axis_hit': False}
    start_klu = bi_in.get_end_klu()
    end_klu = ele.get_begin_klu()
    hit = False
    cur = start_klu.next
    while cur is not None and cur.idx <= end_klu.idx:
        if cur.macd is not None:
            if (is_buy and cur.macd.DIF > 0) or (not is_buy and cur.macd.DIF < 0):
                hit = True
                break
        cur = cur.next
    return hit, {'zero_axis_hit': hit}


def check_bsp1_standard(ele, ele_list, zs_lst, cfg, is_buy: bool):
    """
    第一类买卖点的四项标准判据

    按「趋势 → 新低 → DIF 背驰 → 零轴」顺序短路，返回
    `(ok, reason, info)`。`reason` 为首个不通过的条件名，全部通过时为 None。

    注意：本函数只覆盖四项新增判据。`bs1_peak` 与面积背驰仍由
    `treat_bsp1` 走 `CZS.is_divergence` 的既有链路，不在此重复。
    """
    info = {}
    # 契约：trend 必须始终是第一个检查项（chan-standard-bsp1-change task 2.4）。
    # 降级路由依赖 reason=='trend' 表示「除趋势外其余判据状态未知、需补全检」
    # 这一语义（design D1-b）；若调整检查顺序，降级路由的触发条件随之失效。
    if cfg.bsp1_trend:
        ok, i = check_trend(ele, ele_list, zs_lst, is_buy, cfg.bsp1_trend_mode)
        info.update(i)
        if not ok:
            return False, 'trend', info
    if cfg.bsp1_new_extreme:
        ok, i = check_new_extreme(ele, ele_list, zs_lst, is_buy, cfg.bsp1_new_extreme_mode)
        info.update(i)
        if not ok:
            return False, 'new_extreme', info
    if cfg.bsp1_dif_div:
        last_zs = zs_lst[-1] if zs_lst else None
        if last_zs is None:
            return False, 'dif_div', info
        ok, i = check_dif_divergence(ele, last_zs, is_buy)
        info.update(i)
        if not ok:
            return False, 'dif_div', info
    if cfg.bsp1_zero_axis:
        last_zs = zs_lst[-1] if zs_lst else None
        if last_zs is None:
            return False, 'zero_axis', info
        ok, i = check_zero_axis(ele, last_zs, is_buy)
        info.update(i)
        if not ok:
            return False, 'zero_axis', info
    return True, None, info



# =============================================================================
# 二买 / 类二
# =============================================================================

def check_retrace_in_zs(ele, zs_lst):
    """
    二买回调是否与中枢区间关联

    规则：回调要素的高低区间与某个多笔中枢有交集即视为「落在中枢区间内」。
    """
    for zs in zs_lst:
        if zs.is_one_bi_zs():
            continue
        if ele._high() >= zs.low and ele._low() <= zs.high:
            return True
    return False


def check_ele_end_in_zs(ele, zs_lst):
    """
    类二的中枢前提：要素的**末端价格**必须落在某个多笔中枢的 `[low, high]` 内

    与 `check_retrace_in_zs` 的区别：这里看的是末端点而不是整笔区间。
    类二的理论定义是「中枢内的回抽点」，回抽点的位置（而非整笔跨度）才是判据对象。
    实测在 41 只日线上，整笔区间口径通过 151/157（几乎不过滤），
    末端价格口径通过 90/157，才能真正支撑「中枢是前提」的主张。
    """
    end_val = ele.get_end_val()
    for zs in zs_lst:
        if zs.is_one_bi_zs():
            continue
        if zs.low <= end_val <= zs.high:
            return True
    return False


def check_bsp2_standard(retrace_ele, break_ele, zs_lst, cfg, seg=None):
    """
    第二类买卖点的标准判据

    只覆盖增量部分——「一买之后第一次反向回调」的时序骨架与「不破一买极值」
    的价格约束由既有链路保证（后者由 `max_bs2_rate <= 1` 在数学上自动成立），
    此处不重复实现。

    判据：
        1. 回调幅度比 `retrace = amp(retrace_ele) / amp(break_ele)` 不超过阈值
        2. 若 `bsp2_retrace_zs` 开启，回调要素须与某多笔中枢有区间交集

    返回 `(ok, reason, info)`。
    """
    info = {}
    break_amp = break_ele.amp() if break_ele is not None else 0.0
    if break_amp <= 0:
        return False, 'zero_break_amp', info
    retrace = retrace_ele.amp() / break_amp
    info['bsp2_retrace_rate'] = retrace
    info['bsp2_break_bi_amp'] = break_amp
    info['bsp2_bi_amp'] = retrace_ele.amp()
    if retrace > cfg.max_bs2_rate:
        return False, 'retrace_rate', info
    if cfg.bsp2_retrace_zs:
        if not check_retrace_in_zs(retrace_ele, zs_lst):
            return False, 'retrace_not_in_zs', info
    return True, None, info


# =============================================================================
# 三买 / 三卖
# =============================================================================

def check_breakout(zs):
    """
    中枢的离开笔是否方向正确地突破了中枢

    返回 `(ok, is_buy, info)`：
        - 离开笔向上且高点 > 中枢上沿 → 向上突破，对应三买（`is_buy=True`）
        - 离开笔向下且低点 < 中枢下沿 → 向下突破，对应三卖（`is_buy=False`）

    **买卖侧由离开笔的实际方向决定，不由所在线段的方向决定**。
    在一买所在的下跌线段内，中枢的离开笔通常仍向下（趋势延续），
    此时它构成的是三卖形态而非三买；把 `is_buy` 绑到 `seg.is_down()` 上
    会让该分支永远不成立。
    """
    out = zs.bi_out
    if out is None:
        return False, True, {'has_bi_out': False}
    if out.is_up() and out._high() > zs.high:
        return True, True, {'bi_out_idx': out.idx, 'dir': 'up'}
    if out.is_down() and out._low() < zs.low:
        return True, False, {'bi_out_idx': out.idx, 'dir': 'down'}
    return False, out.is_up(), {'bi_out_idx': out.idx, 'dir': None}


def get_first_retrace(ele_list, zs, is_buy: bool):
    """
    取中枢离开笔之后的第一笔反向要素

    `is_buy` 必须来自 `check_breakout` 的返回值（离开笔方向），
    不能由所在线段方向推导。

    返回 (retrace_ele, ok)。`ok=False` 表示越界或方向不对——
    方向不对意味着离开笔之后还有一笔同向笔，说明离开尚未完成，
    此时不应产出第三类买卖点。
    """
    out = zs.bi_out
    if out is None or out.idx + 1 >= len(ele_list):
        return None, False
    ele = ele_list[out.idx + 1]
    ok = ele.is_down() if is_buy else ele.is_up()
    return ele, ok


def back_to_zs(ele, zs) -> bool:
    """
    回抽要素是否重新进入中枢区间

    买点回抽笔（向下）要求 `low >= zs.high`；卖点回抽笔（向上）要求 `high <= zs.low`。
    返回 True 表示「回到了中枢」，即三买不成立。
    """
    return (ele.is_down() and ele._low() < zs.high) or \
           (ele.is_up() and ele._high() > zs.low)


def check_zs_peak_on_breakout(zs) -> bool:
    """
    突破笔（中枢离开笔）是否突破了中枢内部的最高/最低点

    买：离开笔（向上）的高点 >= 中枢区间内所有笔的最高点
    卖：离开笔（向下）的低点 <= 中枢区间内所有笔的最低点

    历史实现的判据对象是「回抽笔」，与 `Document/README.md` 的
    「突破笔是不是必须突破中枢里面最高/最低的」描述不符。
    """
    out = zs.bi_out
    if out is None:
        return False
    if out.is_up():
        return out._high() >= zs.peak_high
    return out._low() <= zs.peak_low
