# -*- coding: utf-8 -*-
"""
力度指标模块 - 供 CBi 与 CSeg 共用的 MACD/RSI 力度算法

抽出本模块的原因：
    第一类买卖点的标准判据要求「笔级别」与「线段级别」使用同一套力度算法。
    历史上 `CBi.cal_macd_metric` 支持 12 种算法，而 `CSeg.cal_macd_metric`
    只支持 `slope` / `amp`，导致线段级别无法表达 DIF 背驰。

    本模块把「遍历 K 线并按方向累积」的逻辑集中到一处，`CBi` 与 `CSeg`
    只负责提供 K 线迭代器与起止边界，算法实现完全共享。

约定：
    - `klc_iter` 产出 `CKLine`，每个 `CKLine.lst` 是共享同一价格区间的 `CKLine_Unit` 列表
    - `begin_idx` / `end_idx` 为 `CKLine_Unit.idx` 的闭区间过滤，`None` 表示不过滤
    - 边界过滤用于把「合并 K 线区间」收窄到「起止极值 K 线之间」，
      避免把包含关系的多余 K 线计入力度
"""

from typing import Iterable, Optional


def cal_macd_area(klc_iter: Iterable, is_down: bool,
                  begin_idx: Optional[int] = None, end_idx: Optional[int] = None) -> float:
    """
    计算 MACD 同向柱面积

    只累加与要素方向同向的柱：
    - 下降要素：累加 `macd < 0` 的柱
    - 上升要素：累加 `macd > 0` 的柱

    缠论知识：面积背驰 —— 价格创新低但绿柱面积缩小
    """
    _s = 1e-7
    for klc in klc_iter:
        for klu in klc.lst:
            if begin_idx is not None and klu.idx < begin_idx:
                continue
            if end_idx is not None and klu.idx > end_idx:
                continue
            if (is_down and klu.macd.macd < 0) or (not is_down and klu.macd.macd > 0):
                _s += abs(klu.macd.macd)
    return _s


def cal_macd_peak(klc_iter: Iterable, is_down: bool,
                  begin_idx: Optional[int] = None, end_idx: Optional[int] = None) -> float:
    """
    计算 MACD 同向柱峰值（绝对值的最大值）

    缠论知识：峰值背驰 —— 价格创新低但绿柱最高点变矮
    """
    peak = 1e-7
    for klc in klc_iter:
        for klu in klc.lst:
            if begin_idx is not None and klu.idx < begin_idx:
                continue
            if end_idx is not None and klu.idx > end_idx:
                continue
            if abs(klu.macd.macd) > peak:
                if is_down and klu.macd.macd < 0:
                    peak = abs(klu.macd.macd)
                elif not is_down and klu.macd.macd > 0:
                    peak = abs(klu.macd.macd)
    return peak


def cal_macd_half_obverse(klc_iter: Iterable, ref_macd: float,
                          begin_idx: Optional[int] = None,
                          end_idx: Optional[int] = None) -> float:
    """
    正向半面积：从起止要素的起始端向结束端累加同向柱，遇到反向柱即停止

    参数:
        ref_macd: 参考方向的柱值（通常是起始 K 线的 macd），用其符号判定「同向」
    """
    _s = 1e-7
    for klc in klc_iter:
        for klu in klc.lst:
            if begin_idx is not None and klu.idx < begin_idx:
                continue
            if end_idx is not None and klu.idx > end_idx:
                continue
            if klu.macd.macd * ref_macd > 0:
                _s += abs(klu.macd.macd)
            else:
                break
        else:
            continue
        break
    return _s


def cal_macd_half_reverse(klc_re_iter: Iterable, ref_macd: float,
                          begin_idx: Optional[int] = None,
                          end_idx: Optional[int] = None) -> float:
    """
    反向半面积：从结束端向起始端累加同向柱，遇到反向柱即停止

    参数:
        klc_re_iter: 逆序产出的 K 线迭代器
        ref_macd: 参考方向的柱值（通常是结束 K 线的 macd）
    """
    _s = 1e-7
    for klc in klc_re_iter:
        for klu in reversed(klc.lst):
            if end_idx is not None and klu.idx > end_idx:
                continue
            if begin_idx is not None and klu.idx < begin_idx:
                continue
            if klu.macd.macd * ref_macd > 0:
                _s += abs(klu.macd.macd)
            else:
                break
        else:
            continue
        break
    return _s


def cal_macd_diff(klc_iter: Iterable,
                  begin_idx: Optional[int] = None, end_idx: Optional[int] = None) -> float:
    """
    MACD 柱最大值与最小值之差（柱体波动幅度）

    注意：该算法的历史语义是「柱体 max - min」，与名称 `diff` 不符。
    为保证存量配置语义不漂移，这里保持原行为；真正的黄白线极值见 `cal_macd_diff_peak`。
    """
    _max, _min = float("-inf"), float("inf")
    for klc in klc_iter:
        for klu in klc.lst:
            if begin_idx is not None and klu.idx < begin_idx:
                continue
            if end_idx is not None and klu.idx > end_idx:
                continue
            macd = klu.macd.macd
            if macd > _max:
                _max = macd
            if macd < _min:
                _min = macd
    if _max == float("-inf") or _min == float("inf"):
        return 0.0
    return _max - _min


def cal_macd_diff_peak(klc_iter: Iterable, is_down: bool,
                       begin_idx: Optional[int] = None,
                       end_idx: Optional[int] = None) -> float:
    """
    计算 DIF（黄白线）在区间内的极值

    - 下降要素（买点方向）：取区间内 `min(DIF)`，越低说明空头动能越强
    - 上升要素（卖点方向）：取区间内 `max(DIF)`

    与 `cal_macd_diff` 的区别：本算法看的是 DIF 线本身，而不是柱体。
    缠论原文的「黄白线背驰」判据需要的是前者。

    返回值的符号保留原始语义，调用方与 `divergence_rate` 阈值比较时
    应使用绝对值或直接比较两侧极值。
    """
    vals = []
    for klc in klc_iter:
        for klu in klc.lst:
            if begin_idx is not None and klu.idx < begin_idx:
                continue
            if end_idx is not None and klu.idx > end_idx:
                continue
            vals.append(klu.macd.DIF)
    if not vals:
        return 0.0
    return min(vals) if is_down else max(vals)


def cal_rsi(klc_iter: Iterable, is_down: bool,
            begin_idx: Optional[int] = None, end_idx: Optional[int] = None) -> float:
    """
    计算 RSI 极值

    - 下降要素：返回 `10000 / min(rsi)`，RSI 越超卖值越大
    - 上升要素：返回 `max(rsi)`，RSI 越超买值越大

    缠论知识：RSI 背驰 —— 价格创新低但 RSI 未同步创新低
    """
    rsi_lst = []
    for klc in klc_iter:
        for klu in klc.lst:
            if begin_idx is not None and klu.idx < begin_idx:
                continue
            if end_idx is not None and klu.idx > end_idx:
                continue
            rsi_lst.append(klu.rsi)
    if not rsi_lst:
        return 0.0
    return 10000.0 / (min(rsi_lst) + 1e-7) if is_down else max(rsi_lst)


def cal_macd_slope(begin_klu, end_klu, is_up: bool) -> float:
    """
    斜率：价格变化率 / K 线数量

    上升要素：(结束高点 - 起始低点) / 结束高点 / K 线数
    下降要素：(起始高点 - 结束低点) / 起始高点 / K 线数
    """
    if is_up:
        return (end_klu.high - begin_klu.low) / end_klu.high / (end_klu.idx - begin_klu.idx + 1)
    else:
        return (begin_klu.high - end_klu.low) / begin_klu.high / (end_klu.idx - begin_klu.idx + 1)


def cal_macd_amp(begin_klu, end_klu, is_up: bool) -> float:
    """
    振幅：价格涨跌幅

    下降要素：(起始高点 - 结束低点) / 起始高点
    上升要素：(结束高点 - 起始低点) / 起始低点
    """
    if not is_up:
        return (begin_klu.high - end_klu.low) / begin_klu.high
    else:
        return (end_klu.high - begin_klu.low) / begin_klu.low
