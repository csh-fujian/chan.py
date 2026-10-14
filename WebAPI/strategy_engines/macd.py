# -*- coding: utf-8 -*-
"""
MACD 柱序列计算（strategy-volume-breakout-pullback design D2）。

B1（日线 MACD 转多头）与 B2（30 分钟柱面积底背离）只消费 MACD 柱序列。
本模块为引擎包内独立实现（标准 12/26/9 EMA），不 import ChanAnalyse 任何
模块——ChanAnalyse.Math.MACD 虽无依赖，但属 ChanAnalyse 包成员，import
它会破「引擎不 import CChan 任何模块」的协议字面。

性能：一次性批量计算整段序列（引擎拿到的是全历史 K 线列表，逐 bar 递推）。
"""

from typing import List


def macd_columns(
    closes: List[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> List[float]:
    """计算 MACD 柱序列（2 × (DIF − DEA)）。

    EMA 递推：EMA_today = (2×price + (N−1)×EMA_yesterday) / (N+1)
    与 ChanAnalyse.Math.MACD.CMACD 同口径（首值 EMA = 首价、DIF/DEA 从 0 起），
    数值序列一致性便于与既有绘图指标对账。

    返回与 closes 等长的柱值列表（柱 > 0 红柱，柱 < 0 绿柱）。
    """
    n = len(closes)
    if n == 0:
        return []
    columns: List[float] = []
    fast_ema = slow_ema = closes[0]
    dif = dea = 0.0
    columns.append(0.0)  # 首柱恒 0（EMA = 首价时 DIF = 0）
    for i in range(1, n):
        fast_ema = (2 * closes[i] + (fast - 1) * fast_ema) / (fast + 1)
        slow_ema = (2 * closes[i] + (slow - 1) * slow_ema) / (slow + 1)
        dif = fast_ema - slow_ema
        dea = (2 * dif + (signal - 1) * dea) / (signal + 1)
        columns.append(2 * (dif - dea))
    return columns
