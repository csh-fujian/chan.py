# -*- coding: utf-8 -*-
"""
分型强弱分级（chan-bsp-ladder-change D2 / task 3.1）。

阶梯的**分型轴**：候选点所在笔末端分型的反转强度，分三档
`L3-3`（强）/ `L3-2`（中）/ `L3-1`（弱）。

判据（买点侧底分型，三根合并 K 线 A=pre / B=fx / C=next）：

    L3-3:  C_max >  A_max
    L3-2:  C_max >= (A_max + A_min) / 2      （含 C_max == A_max 的平边界）
    L3-1:  其余（未收复 A 实体一半）

卖点侧顶分型镜像（用实体**下沿** `X_min` 比较，方向相反）：

    L3-3:  C_min <  A_min
    L3-2:  C_min <= (A_max + A_min) / 2
    L3-1:  其余

**实体口径（design D2 口径 (a)，待确认默认）**：
    `X_max = max(open, close)` 对合并 K 线内**全部原始 K 线**取最大，
    `X_min = min(open, close)` 取最小。即实体边界不含影线。
    若改为口径 (b)（直接用合并 K 线 `high`/`low`），只改本模块的
    `_entity_bounds` 一处即可，判据与接口不变。

**参照物是 A（前一合并 K 线），不是 B（分型核心）**：
    A 实体位于分型左侧高位，C 要收复 A 实体一半所需的反弹幅度明显大于
    收复 B 实体一半，因此 L3-2 门槛更严、分档更保守。这是探索会话确认的
    口径（2026-10-25）。

本模块是**纯只读函数**：不 import 内核计算类，输入三根合并 K 线即可工作，
可在 WebAPI 层被 ladder 推导调用（与「级别判定在 WebAPI 层完成、不修改
缠论计算内核」的 spec 约束一致）。
"""

from typing import Any, Optional, Tuple

# 分型轴标签
FRACTAL_STRONG = "L3-3"
FRACTAL_MEDIUM = "L3-2"
FRACTAL_WEAK = "L3-1"


def _entity_bounds(klc) -> Optional[Tuple[float, float]]:
    """取合并 K 线的实体边界 (min(open,close) 的最小, max(open,close) 的最大)。

    口径 (a)：遍历合并 K 线持有**全部原始 K 线**（`klc.lst`），对每根的
    `max(open, close)` 取最大、`min(open, close)` 取最小。

    原始元素可能不是 `CKLine_Unit`（线段级别的特征序列合并器里是 `CBi`），
    此时没有 open/close——返回 None，调用方按「不可评估」处理。
    """
    raw = getattr(klc, 'lst', None)
    if not raw:
        return None
    highs, lows = [], []
    for unit in raw:
        o = getattr(unit, 'open', None)
        c = getattr(unit, 'close', None)
        if o is None or c is None:
            return None
        highs.append(max(o, c))
        lows.append(min(o, c))
    if not highs:
        return None
    return min(lows), max(highs)


def classify_fx(pre, fx, nxt, is_buy: bool) -> Optional[str]:
    """分型强弱分级。

    Args:
        pre: 分型前一根合并 K 线（A）
        fx:  分型核心合并 K 线（B）
        nxt: 分型后一根合并 K 线（C）
        is_buy: True = 底分型（买点侧），False = 顶分型（卖点侧）

    Returns:
        `L3-3` / `L3-2` / `L3-1`；任一根缺失或实体不可评估时返回 None
        （分型未形成 → 分型轴不携带标签）。

    `fx` 只用于确认分型存在性（三根都要在），不参与实体比较——判据只比
    A 与 C 的实体边界。这是用户定义的原样实现（2026-10-25 探索会话）。
    """
    if pre is None or fx is None or nxt is None:
        return None
    a = _entity_bounds(pre)
    c = _entity_bounds(nxt)
    if a is None or c is None:
        return None
    a_min, a_max = a
    c_min, c_max = c

    if is_buy:
        # 底分型：看 C 的实体上沿对 A 实体上沿的收复程度
        if c_max > a_max:
            return FRACTAL_STRONG
        if c_max >= (a_max + a_min) / 2:
            return FRACTAL_MEDIUM
        return FRACTAL_WEAK
    else:
        # 顶分型镜像：看 C 的实体下沿对 A 实体下沿的跌破程度
        if c_min < a_min:
            return FRACTAL_STRONG
        if c_min <= (a_max + a_min) / 2:
            return FRACTAL_MEDIUM
        return FRACTAL_WEAK


def fractal_of_bi(bi, is_buy: Optional[bool] = None) -> Optional[str]:
    """买卖点所在笔的**末端分型**强弱（便捷封装）。

    分型三根：笔终点 K 线所属的合并 K 线为 `fx`（B），其 `pre`/`next`
    通过合并 K 线链表取。末端分型尚未形成（`next` 不存在，或该合并 K 线
    的 fx 类型不是底/顶）时返回 None。

    Args:
        bi: CBi / CSeg（取 `get_end_klu()` 反查所属合并 K 线）
        is_buy: 方向；None 时用 `bi.is_down()`（买点用底分型）

    Returns:
        `L3-3` / `L3-2` / `L3-1` / None
    """
    if is_buy is None:
        try:
            is_buy = bool(bi.is_down())
        except Exception:
            return None
    try:
        klu = bi.get_end_klu()
        klc = klu.klc
    except Exception:
        return None
    if klc is None:
        return None
    try:
        pre = klc.pre
        nxt = klc.next
    except Exception:
        return None
    return classify_fx(pre, klc, nxt, is_buy)
