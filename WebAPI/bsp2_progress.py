# -*- coding: utf-8 -*-
"""
T2 判据链进度轴纯函数推导（chan-standard-bsp2-change design D8）。

判据链五项（顺序短路）：
    ① 一买成立（relate_bsp1 非空 = 锚点在 bsp1_sure_dict 命中）
    ② 回调笔存在（时序骨架——失败时内核根本不产生候选点）
    ③ 不破一买极值（max_bs2_rate<=1 数学恒过）
    ④ 回撤率 <= max_bs2_rate
    ⑤ 可选中枢关联（bsp2_retrace_zs 开启时计入）

两档：已过项 <= ceil(5/2)=3 → P1，> 3 → P2；判据全过但线段未确认 → P2。

证据源：`CBS_Point.features` 的 `bsp2_reason`（`check_bsp2_standard` 透出的
短路原因：None=全过 / 'retrace_rate' / 'retrace_not_in_zs' / 'zero_break_amp'）
与 `relate_bsp1` 是否非空。

注意（design D8）：②③失败时内核不产生候选点（无 T2 点可标），所以进度轴
实际可见的最低进度是 ④/⑤ 短路处——P1 档只由「回撤率未过」情形产生。
这是进度轴「判据链走到哪」语义的自然结果，不是缺陷。

**这是纯函数模块**：不 import 内核计算类，只消费 feature 字典与 bsp 属性。
"""

from typing import Optional

# 进度轴档位
P_LOW = "P1"   # 判据链前半（已过 <= 3 项）
P_HIGH = "P2"  # 判据链后半 / 全过未确认

# 判据链总项数与两档分界（ceil(5/2) = 3）
_TOTAL_STEPS = 5
_SPLIT = 3

# bsp2_reason 短路原因 → 已通过项数（在该处短路意味着此前的项已过）
_REASON_TO_STEPS = {
    'retrace_rate': 3,      # ④ 未过 → ①②③ 已过
    'retrace_not_in_zs': 4,  # ⑤ 未过 → ①~④ 已过
    'zero_break_amp': 2,     # 幅度为零（break_bi 无效）→ ①② 已过（防御分支）
}


def progress_axis(bsp) -> Optional[str]:
    """推导 T2/T2S 候选点的进度轴档位。

    Args:
        bsp: CBS_Point 实例（读 features['bsp2_reason'] 与 relate_bsp1）

    Returns:
        "P1" / "P2"，或 None（缺关键 feature，无法评估——不猜）。
    """
    try:
        feat = dict(bsp.features.items())
    except Exception:
        return None
    if 'bsp2_reason' not in feat:
        # 存量点（本变更前的落库/快照）不带 reason → 不写进度轴（D1：不猜）
        return None

    reason = feat.get('bsp2_reason')
    if reason is None:
        # 判据全过（候选点必然如此——内核只在全过后 add_bs）
        return P_HIGH
    steps = _REASON_TO_STEPS.get(reason, _SPLIT)
    return P_LOW if steps <= _SPLIT else P_HIGH
