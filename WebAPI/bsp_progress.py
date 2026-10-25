# -*- coding: utf-8 -*-
"""
一买判据链进度推导（chan-bsp-ladder-change D1）。

把内核透出的「已判定项」事实 + 标准判据链的短路原因，拼成一买判据链的
顺序进度（0~7，= 已通过的最大序号），供阶梯进度轴分档使用
（1~4 → L1，5~7 → L2）。

统一七项序号：

    ①趋势前提  ②突破中枢  ③极值判据  ④力度背驰
    ⑤创趋势新低  ⑥DIF 背驰  ⑦零轴回抽

前四项的原始判定分散在两处：
    - ②③④ 由 `treat_bsp1` 直接计算（`is_divergence` 内部也判②，会短路），
      内核以逐项布尔透出到 feature：
      `bsp1_step_break` / `bsp1_step_peak` / `bsp1_step_diver`
    - ① 在 `check_bsp1_standard` 内，失败时 `bsp1_standard_reason == 'trend'`
    - ⑤⑥⑦ 同样由 `bsp1_standard_reason` 反映（依次为 new_extreme /
      dif_div / zero_axis），全部通过时 reason 为 None 或不存在该键

**这是纯函数模块**：不 import 内核计算类，只消费已落库的 feature 字典，
因此可以在 WebAPI 层被落库链路与序列化链路共用（D7 单点口径）。
"""

from typing import Any, Dict, Mapping, Optional

# 判据链总项数（①~⑦）
TOTAL_STEPS = 7
# 进度轴分档线：1~4 → L1（前半链），5~7 → L2（后半链）。
# 依据 chan-bsp-ladder-change：ceil(7/2) = 4。
PROGRESS_SPLIT = 4

# 标准判据链短路原因 → 已通过项数。
#
# 注意这里只映射「⑤⑥⑦ 三档」，① 单独处理（`trend` 是 0，意味着前四项
# 根本没跑）。`standard_ok=True` 时 reason 为 None，进度直接取 TOTAL_STEPS。
_STANDARD_REASON_TO_STEPS = {
    'new_extreme': 4,   # ⑤ 未过 → ①②③④ 已过
    'dif_div': 5,       # ⑥ 未过 → ①~⑤ 已过
    'zero_axis': 6,     # ⑦ 未过 → ①~⑥ 已过
}


def judged_steps(feature: Optional[Mapping[str, Any]],
                 is_buy: bool = True) -> Optional[int]:
    """从买卖点 feature 推导一买判据链进度（0~7）。

    Args:
        feature: `CBS_Point.features` 的字典形式（`dict(bsp.features.items())`
                 或直接读落库前的 `feature_dict`）。缺关键键时返回 None。
        is_buy: 方向（当前口径买卖对称，保留参数以便后续按方向分化）。

    Returns:
        0~7 的整数；无法评估时返回 None。

    **缺键语义**：只有本变更之后的候选点才携带三个 step 布尔。存量点
    （本变更前的快照/缓存）缺键时返回 None → 调用方不写进度轴标签，
    而不是猜测一个值。这与「存量旧阶梯值不可解读」的迁移语义一致。
    """
    if not feature:
        return None
    # 三项目内核事实缺任一即无法评估（D1：不猜）
    if not all(k in feature for k in ('bsp1_step_break', 'bsp1_step_peak', 'bsp1_step_diver')):
        return None
    if 'bsp1_standard_reason' not in feature:
        return None

    reason = feature.get('bsp1_standard_reason')

    # ① 趋势：标准链首项即失败 → 前四项都没跑，进度 0
    if reason == 'trend':
        return 0

    step = 1  # ① 已过
    # ② 突破中枢
    if not feature['bsp1_step_break']:
        return step
    step = 2
    # ③ 极值判据
    if not feature['bsp1_step_peak']:
        return step
    step = 3
    # ④ 力度背驰
    if not feature['bsp1_step_diver']:
        return step
    step = 4
    # ⑤⑥⑦：reason 为 None 表示全过
    if reason is None:
        return TOTAL_STEPS
    return _STANDARD_REASON_TO_STEPS.get(reason, step)


def progress_axis(feature: Optional[Mapping[str, Any]]) -> Optional[str]:
    """进度轴标签：'L1'（前半链 1~4）/ 'L2'（后半链 5~7）/ None（不可评估）。

    七项全过但所在线段未确认的点也落 L2（chan-bsp-ladder-change：
    「只欠结构确认」）。该情形在 `bsp_is_sure` 判定为 False 后才走到这里，
    故此处不需要再区分确认状态。
    """
    steps = judged_steps(feature)
    if steps is None:
        return None
    # 0 表示①趋势未过 —— 仍在第一档（前半链尚未开始）
    if steps <= PROGRESS_SPLIT:
        return 'L1'
    return 'L2'
