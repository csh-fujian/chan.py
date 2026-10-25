# -*- coding: utf-8 -*-
"""
T2 确认轴（事后价格确认）纯函数推导（chan-standard-bsp2-change design D3）。

判据：候选回调笔结束后，窗口内后续笔的价格行为分三档：
    C3（已确认）   后续笔突破 break_bi 端点（买侧高点 / 卖侧低点）
    C2（收复）     收复 break_bi 振幅一半以上
    C1（未动）     窗口走完仍未收复一半（终态降级）
    C0（进行中）   窗口不足（数据末端的候选，非终态——不是 C1）

两级阈值口径由 `bsp2_confirm_level` 决定：
    strong（默认）C3 = 突破 break_bi 端点
    weak          C3 = 收复一半以上即算确认（阈值整体放低一档）

终态单向性（design D2）：窗口只考察固定几笔，窗口外的新高不进判据输入，
因此窗口走完后无论重算多少次，推导结果恒定——「不回退」靠判据的时间
确定性，不靠存储层锁。

**这是纯函数模块**：不 import 内核计算类，输入只有 bsp / bi_list / cfg，
可在 WebAPI 层被落库链路与序列化链路共用（与 bsp_progress 同一模式）。
"""

from typing import Optional, Tuple

# 确认轴档位（spec chan-bsp2-confirm 三档 + 进行中瞬时态）
C_CONFIRMED = "C3"   # 已确认（突破 / weak 口径下的收复）
C_RECOVER = "C2"     # 收复一半以上
C_NONE = "C1"        # 窗口走完未动（终态降级）
C_ONGOING = "C0"     # 窗口不足（非终态）


def _thresholds(break_bi, is_buy: bool, level: str) -> Tuple[float, float]:
    """两级阈值：返回 (确认阈值, 收复阈值)。

    买侧看高点、卖侧看低点；break_bi 是一买后的反向笔（买侧为上升笔，
    其终点即回调前波段高点）。
    """
    end_val = break_bi.get_end_val()
    begin_val = break_bi.get_begin_val()
    half = begin_val + 0.5 * break_bi.amp() if is_buy else begin_val - 0.5 * break_bi.amp()
    if level == "weak":
        # weak 口径：确认阈值即收复一半
        return half, half
    return end_val, half


def confirm_axis(bsp, bi_list, cfg) -> Optional[str]:
    """推导 T2/T2S 候选点的确认轴档位。

    Args:
        bsp: CBS_Point 实例（其 bi 为回调笔 / 类二回抽笔）
        bi_list: 本级别笔列表
        cfg: CPointConfig（读 bsp2_confirm_window / bsp2_confirm_level）

    Returns:
        "C3" / "C2" / "C1" / "C0"，或 None（定位失败：无回调笔前序可参照）。
    """
    bi = bsp.bi
    if bi is None or bi.idx < 1 or bi_list is None:
        return None
    # break_bi 定位：与内核 treat_bsp2 同构——锚点（一买笔）+1；
    # 锚点从 relate_bsp1 反查，无锚点时退化为回调笔前一笔（首线段分支
    # 的 bsp2_bi=bi[1], break_bi=bi[0] 关系同样是「回調笔的前一笔」）。
    anchor = getattr(bsp, "relate_bsp1", None)
    anchor_idx = anchor.bi.idx if anchor is not None and anchor.bi is not None else bi.idx - 2
    break_idx = anchor_idx + 1 if 0 <= anchor_idx + 1 < len(bi_list) else bi.idx - 1
    if break_idx < 0 or break_idx >= len(bi_list):
        return None
    break_bi = bi_list[break_idx]

    window = getattr(cfg, "bsp2_confirm_window", 2)
    level = getattr(cfg, "bsp2_confirm_level", "strong")
    threshold_confirm, threshold_recover = _thresholds(break_bi, bool(bsp.is_buy), level)

    # 边界断言（design D2）：窗口外数据不进输入——end_idx 封顶于窗口，
    # 循环上界即 end_idx，窗口外笔物理上不可达。
    end_idx = bi.idx + window
    if end_idx > len(bi_list) - 1:
        return C_ONGOING

    is_buy = bool(bsp.is_buy)
    recovered = False
    for j in range(bi.idx + 1, end_idx + 1):
        cand = bi_list[j]
        # 买侧考察窗口内上升笔最高价；卖侧考察窗口内下降笔最低价
        if (is_buy and cand.is_up()) or ((not is_buy) and cand.is_down()):
            px = cand.get_end_val()
            if is_buy and px >= threshold_confirm:
                return C_CONFIRMED
            if (not is_buy) and px <= threshold_confirm:
                return C_CONFIRMED
            if not recovered:
                if is_buy and px >= threshold_recover:
                    recovered = True
                elif (not is_buy) and px <= threshold_recover:
                    recovered = True
    if recovered:
        return C_RECOVER
    return C_NONE
