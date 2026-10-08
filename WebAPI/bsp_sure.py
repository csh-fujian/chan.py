# -*- coding: utf-8 -*-
"""
买卖点确认状态推导（bsp-sure-annotation design D1/D5）。

口径：水位线 `bs_point_lst.last_sure_pos` —— 与 `CBSPointList.clear_store_end`
的回滚判定完全同源（`bi.get_end_klu().idx <= last_sure_pos` = 稳定不会撤销）。

明确不用 `bi.parent_seg.is_sure`（虚段回退时取值随重算摇摆，落库时点不可靠）。
`last_sure_pos` 为 `CBSPointList` 的水位惯例字段（update_last_pos 从最后一个
is_sure 线段倒推），计算内核升级时只需核对本模块单点。

集中放 WebAPI 层一处，incremental_engine（落库）与 serializer（/api/klines
序列化）复用，保证两条链路口径永不漂移。
"""

import logging

log = logging.getLogger("bsp_sure")


def bsp_is_sure(bsp, bs_point_lst) -> bool:
    """推导买卖点确认状态。

    Args:
        bsp: CBS_Point 实例（取其所在笔的终点 K 线索引）
        bs_point_lst: CBSPointList 实例（取水位线 last_sure_pos）

    Returns:
        True  = 依托已确认线段（笔终点 K 线索引 ≤ 水位线，稳定不会撤销）
        False = 依托虚段（未确认段，后续 K 线到来后可能移动/消失）

    `last_sure_pos` 缺失（None）/ ≤ 0 时按未确认处理并告警日志：
    `update_last_pos` 初始化为 -1，cal() 收尾必然刷新；落库时点读到
    非正值说明水位线尚未建立（极端部分状态），保守按未确认处理。
    """
    last_sure_pos = getattr(bs_point_lst, "last_sure_pos", None)
    if last_sure_pos is None or last_sure_pos <= 0:
        log.warning(
            "last_sure_pos 缺失或非正值 (%r)，买卖点按未确认处理", last_sure_pos
        )
        return False
    end_idx = bsp.bi.get_end_klu().idx
    return end_idx <= last_sure_pos
