# -*- coding: utf-8 -*-
"""
T3 确认轴（缠论要素 E：回抽后趋势延续）纯函数推导
（chan-standard-bsp3-change design D5/D7）。

**要素 E 是事后确认层，不是成立判据**：三买照常在回抽笔端点输出（进场点位
不变），本模块只在输出后评估「这个买点事后被证实还是证伪」。做成成立判据
会引入未来函数、使信号后移 1~2 笔，永远买在确认笔高位（design D5 路径 a
已否决）。

判据：回抽笔结束后，确认窗口内后续笔的价格行为分四档：
    C3（已确认）   后续笔突破回抽笔端点（买侧起点高点 / 卖侧起点低点）
    C2（收复）     收复回抽幅度一半以上（未达端点）
    C1（证伪终态） 后续笔跌回**锚定中枢区间**（买侧低点 < ZG / 卖侧高点 > ZD），
                   或窗口走完未收复一半
    C0（进行中）   窗口数据不足（数据末端的候选，非终态）

C1 / C3 均为终态。终态单向性（spec「确认窗口的时间确定性」）靠**判据输入的
时间封顶**实现：窗口只考察固定的 N 笔，窗口外的新高不进输入，故重算结果
恒定——不靠存储层锁。

**证伪线基准（design D7）**：取登记时锚定的那个中枢区间（`bsp3_zs_low` /
`bsp3_zs_high` 两个只读 feature 快照），不是「回抽笔所在线段的最后中枢」。
两者不等价，混用会得出错误结论（《三买三卖差异点说明.md》统计口径声明）。

**这是纯函数模块**：不 import 内核计算类，输入只有 bsp / bi_list / cfg，
可在 WebAPI 层被落库链路与序列化链路共用（与 `bsp2_confirm` 同一模式）。
"""

from typing import Optional, Tuple

# 确认轴档位（与 bsp2 确认轴同套字母，语义一致）
C_CONFIRMED = "C3"   # 已确认（突破回抽笔端点）
C_RECOVER = "C2"     # 收复回抽幅度一半以上
C_NONE = "C1"        # 证伪终态（跌回中枢 / 窗口走完未收复一半）
C_ONGOING = "C0"     # 窗口不足（非终态）

# 回抽笔端点相对锚定中枢的兜底：feature 缺失时用中枢区间自身推端点
_FEAT_ZS_LOW = "bsp3_zs_low"
_FEAT_ZS_HIGH = "bsp3_zs_high"


def _zs_bounds(bsp) -> Tuple[Optional[float], Optional[float]]:
    """取登记时锚定的中枢区间 `(low, high)`（design D7）。

    feature 缺失（旧快照 / 非标准档写入）时返回 `(None, None)`，
    调用方据此跳过证伪判定（不猜）。
    """
    try:
        feat = dict(bsp.features.items())
    except Exception:
        return None, None
    return feat.get(_FEAT_ZS_LOW), feat.get(_FEAT_ZS_HIGH)


def _thresholds(bsp, is_buy: bool, level: str) -> Tuple[float, float]:
    """两级阈值：返回 (确认阈值, 收复阈值)。

    买侧参照回抽笔（下降笔）的起点高点，卖侧参照起点低点——回抽笔的起点
    就是离开笔的终点，即「突破后的极值」。`weak` 口径把确认阈值降到收复线。
    """
    bi = bsp.bi
    begin_val = bi.get_begin_val()
    if is_buy:
        confirm = begin_val
        recover = begin_val - 0.5 * bi.amp()
    else:
        confirm = begin_val
        recover = begin_val + 0.5 * bi.amp()
    if level == "weak":
        return recover, recover
    return confirm, recover


def confirm_axis(bsp, bi_list, cfg) -> Optional[str]:
    """推导 T3A/T3B 候选点的确认轴档位（缠论要素 E）。

    Args:
        bsp: CBS_Point 实例（其 bi 为三买的**回抽笔**）
        bi_list: 本级别笔列表
        cfg: CPointConfig（读 `bsp3_confirm_window` / `bsp3_confirm_level`）

    Returns:
        "C3" / "C2" / "C1" / "C0"，或 None（定位失败：无回抽笔 / 笔列表缺失）。
    """
    bi = bsp.bi
    if bi is None or bi_list is None or bi.idx < 0:
        return None

    is_buy = bool(bsp.is_buy)
    window = getattr(cfg, "bsp3_confirm_window", 2)
    level = getattr(cfg, "bsp3_confirm_level", "strong")
    threshold_confirm, threshold_recover = _thresholds(bsp, is_buy, level)
    zs_low, zs_high = _zs_bounds(bsp)

    # 窗口封顶：窗口外数据物理上不可达（终态单向性的结构保证）
    end_idx = bi.idx + window
    if end_idx > len(bi_list) - 1:
        return C_ONGOING

    recovered = False
    for j in range(bi.idx + 1, end_idx + 1):
        cand = bi_list[j]
        try:
            in_window = cand.seg_idx == bi.seg_idx
        except Exception:
            in_window = True

        # ---- 证伪：跌回锚定中枢区间（design D7）----
        if zs_low is not None and zs_high is not None:
            if is_buy and cand._low() < zs_high:
                # 仅当该笔确实回到中枢内部（不能是中枢下沿之下的一次深跌后
                # 又被判为延续）。买侧：低点低于上沿即视为失守。
                return C_NONE
            if (not is_buy) and cand._high() > zs_low:
                return C_NONE

        # ---- 确认 / 收复：只看同向（顺突破方向）的笔 ----
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

        if not in_window:
            break

    if recovered:
        return C_RECOVER
    return C_NONE
