# -*- coding: utf-8 -*-
"""
T3 时间轴（回抽速度比）纯函数推导（chan-standard-bsp3-change design D6）。

判据：速度比
    v = (amp(bsp3_bi) / amp(break_bi)) / (klu_cnt(bsp3_bi) / klu_cnt(break_bi))
三档：
    T3（强）v <= bsp3_time_axis_strong（默认 0.5，急涨缓跌 = 回抽衰竭）
    T2（中）strong < v <= weak（默认 1.0，均衡）
    T1（弱）v > weak（缓涨急跌 = 回抽急促）

与 T2 时间轴（`bsp2_time_axis`）同构但**参照笔不同**：T2 的参照是
`break_bi`（一买后的反向笔），T3 的参照是**突破笔**（中枢的离开笔）——
三买问的是「突破之后的回抽有多弱」，不是「一买之后的反向有多弱」。

速度比而非原始时间比：回抽深往往笔也长，原始时间比与「回抽幅度」正相关，
轴信息量被吃掉；速度比把价格归一进去，去相关（同 T2 design D4 的论证）。
`klu_cnt` 取笔内原始 K 线根数（行情固有属性，跨配置可比），非合并 K 线组数。

**这是纯函数模块**：不 import 内核计算类，可在 WebAPI 层双链路共用。
"""

from typing import Optional

# 时间轴档位（与 T2 同套字母，语义一致）
T_STRONG = "T3"   # 急涨缓跌（衰竭）
T_MID = "T2"      # 均衡
T_WEAK = "T1"     # 缓涨急跌（急促）


def _breakout_bi(bsp, bi_list):
    """定位三买的**突破笔**（中枢的离开笔）与回抽笔。

    回抽笔是 `bsp.bi`（三买所在笔）；突破笔是它前一笔（标准档判据链
    `get_first_retrace` 强制「离开笔 + 1」即回抽笔）。用 `bsp3_bi.idx - 1`
    定位而非 feature：与内核判据链同源，且 T3A/T3B 两条分支的回抽笔都
    紧跟在离开笔之后。

    返回 (break_bi, retrace_bi)，任一定位失败返回 (None, None)。
    """
    bi = bsp.bi
    if bi is None or bi_list is None or bi.idx < 1:
        return None, None
    if bi.idx >= len(bi_list):
        return None, None
    break_bi = bi_list[bi.idx - 1]
    return break_bi, bi


def time_axis(bsp, bi_list, cfg) -> Optional[str]:
    """推导 T3A/T3B 候选点的时间轴档位。

    Args:
        bsp: CBS_Point 实例（其 bi 为三买的回抽笔）
        bi_list: 本级别笔列表
        cfg: CPointConfig（读 bsp3_time_axis_strong / bsp3_time_axis_weak）

    Returns:
        "T3" / "T2" / "T1"，或 None（速度比不可计算：分母为零或定位失败）。
    """
    break_bi, retrace_bi = _breakout_bi(bsp, bi_list)
    if break_bi is None:
        return None

    amp_break, amp_retrace = break_bi.amp(), retrace_bi.amp()
    n_break, n_retrace = break_bi.get_klu_cnt(), retrace_bi.get_klu_cnt()
    if amp_break <= 0 or n_break <= 0 or n_retrace <= 0:
        return None
    v = (amp_retrace / amp_break) / (n_retrace / n_break)

    strong = getattr(cfg, "bsp3_time_axis_strong", 0.5)
    weak = getattr(cfg, "bsp3_time_axis_weak", 1.0)
    if v <= strong:
        return T_STRONG
    if v <= weak:
        return T_MID
    return T_WEAK
