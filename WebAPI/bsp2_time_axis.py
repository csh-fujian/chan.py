# -*- coding: utf-8 -*-
"""
T2 时间轴（回调速度比）纯函数推导（chan-standard-bsp2-change design D4）。

判据：速度比
    v = (amp(bsp2_bi) / amp(break_bi)) / (klu_cnt(bsp2_bi) / klu_cnt(break_bi))
三档：
    T3（强）v <= bsp2_time_axis_strong（默认 0.5，急涨缓跌 = 回调衰竭）
    T2（中）strong < v <= weak（默认 1.0，均衡）
    T1（弱）v > weak（缓涨急跌 = 回调急促）

为什么用速度比而非原始时间比：回调深往往笔也长，原始时间比与判据④的
回撤率正相关，轴信息量被判据链吃掉；速度比把价格归一进去，去相关。

`klu_cnt` 取笔内原始 K 线根数（`CBi.get_klu_cnt`，K 线单元数），非合并
K 线组数——后者受包含关系处理影响，同一形态不同包含历史会得不同 bars；
K 线根数是行情固有属性，跨配置可比。

**这是纯函数模块**：不 import 内核计算类，可在 WebAPI 层双链路共用。
"""

from typing import Optional

# 时间轴档位
T_STRONG = "T3"   # 急涨缓跌（衰竭）
T_MID = "T2"      # 均衡
T_WEAK = "T1"     # 缓涨急跌（急促）


def time_axis(bsp, bi_list, cfg) -> Optional[str]:
    """推导 T2/T2S 候选点的时间轴档位。

    Args:
        bsp: CBS_Point 实例（其 bi 为回调笔 / 类二回抽笔）
        bi_list: 本级别笔列表
        cfg: CPointConfig（读 bsp2_time_axis_strong / bsp2_time_axis_weak）

    Returns:
        "T3" / "T2" / "T1"，或 None（速度比不可计算：分母为零或定位失败）。
    """
    bi = bsp.bi
    if bi is None or bi.idx < 1 or bi_list is None:
        return None
    # break_bi 定位：与 bsp2_confirm 同一口径（锚点+1，退化回调笔前一笔）
    anchor = getattr(bsp, "relate_bsp1", None)
    anchor_idx = anchor.bi.idx if anchor is not None and anchor.bi is not None else bi.idx - 2
    break_idx = anchor_idx + 1 if 0 <= anchor_idx + 1 < len(bi_list) else bi.idx - 1
    if break_idx < 0 or break_idx >= len(bi_list):
        return None
    break_bi = bi_list[break_idx]

    amp_break, amp_retrace = break_bi.amp(), bi.amp()
    n_break, n_retrace = break_bi.get_klu_cnt(), bi.get_klu_cnt()
    if amp_break <= 0 or n_break <= 0 or n_retrace <= 0:
        return None
    v = (amp_retrace / amp_break) / (n_retrace / n_break)

    strong = getattr(cfg, "bsp2_time_axis_strong", 0.5)
    weak = getattr(cfg, "bsp2_time_axis_weak", 1.0)
    if v <= strong:
        return T_STRONG
    if v <= weak:
        return T_MID
    return T_WEAK
