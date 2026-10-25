# -*- coding: utf-8 -*-
"""
T2/T2S 五轴阶梯组装（chan-standard-bsp2-change design D1/D5/D7）。

五轴语法（axis 顺序固定：进度 → 佐证 → 确认 → 分型 → 时间）：
    组合形如 "P1|S3|K2|C3|T1"（各轴档位数字 1=低 3=高）
    已确认单值 "L4" 由上层 `cal_ladder` 的 L4 短路统一处理，本模块不管。

轴前缀（design D5）：
    P 进度轴   `bsp2_progress.progress_axis` → P1/P2
    S 佐证轴   T2 版 `corroboration_axis`（回调笔单笔窗口）→ S3/S2/S1
    K 确认轴   `bsp2_confirm.confirm_axis` → C3/C2/C1/C0（沿用 C 前缀标识确认）
    C 分型轴   `fractal_strength.fractal_of_bi`（复用，档位值沿用 L3-x 映射为 K3/K2/K1）
    T 时间轴   `bsp2_time_axis.time_axis` → T3/T2/T1

解析规则：按 `|` split，段首字母识别轴，未知段忽略（向前兼容）。

为什么独立语法不复用 T1 的 L 编号：L1/L2/L3/L4 在 T1 语法中已语义固化
（L2-x 佐证、L3-x 分型、L4 已确认），T2 复用会撞车；独立前缀 + bsp_type
路由，两套语法无歧义。分型轴的档位语义沿用 `fractal_strength` 的三档
划分，但前缀换 K 以保持 T2 语法的轴字母统一可识别。
"""

from typing import List, Optional

from . import fractal_strength
from .bsp2_confirm import confirm_axis
from .bsp2_progress import progress_axis
from .bsp2_time_axis import time_axis

# 轴顺序（design D5：固定，输出与解析都按此序）
AXIS_ORDER = ("P", "S", "C", "K", "T")
AXIS_SEPARATOR = "|"

# fractal_strength 档位（L3-x）→ T2 分型轴档位（K-x）
_FRACTAL_MAP = {"L3-3": "K3", "L3-2": "K2", "L3-1": "K1"}


def bsp2_ladder(bsp, bs_point_lst, bi_list, cfg, sub_bs_point_lst=None,
                sub_kl=None) -> Optional[str]:
    """推导 T2/T2S 候选点的五轴阶梯组合值。

    Args:
        bsp: CBS_Point 实例（T2 或 T2S）
        bs_point_lst: 本级别 CBSPointList（未使用，签名对齐既有轴函数）
        bi_list: 本级别笔列表（确认轴 / 时间轴输入）
        cfg: CPointConfig（窗口 / 阈值配置）
        sub_bs_point_lst: 子级别 CBSPointList（佐证轴数据源；None = 轴缺席）
        sub_kl: 子级别 CKLine_List（佐证轴 S1 档的数据源；None = 不做 S1）

    Returns:
        五轴组合字符串（各轴缺证据时该轴缺席，非全缺席），或 None（全轴缺席）。
    """
    axes: List[str] = []

    # 进度轴
    pa = progress_axis(bsp)
    if pa is not None:
        axes.append(pa)

    # 佐证轴（design D7：回调笔单笔窗口——T2 的结构单元就是回调笔，
    # 佐证问的是「回调位置上子级别有没有走出同向结构」，不是 T1 的「离开段」）
    if sub_bs_point_lst is not None:
        sa = _corroboration_axis_bsp2(bsp, sub_bs_point_lst, sub_kl=sub_kl)
        if sa is not None:
            axes.append(sa)

    # 确认轴
    if bi_list is not None:
        ca = confirm_axis(bsp, bi_list, cfg)
        if ca is not None:
            axes.append(ca)

    # 分型轴（回调笔末端分型强弱；买卖镜像由 is_buy 决定）
    try:
        fa = fractal_strength.fractal_of_bi(bsp.bi, is_buy=bool(bsp.is_buy))
    except Exception:
        fa = None
    if fa is not None:
        axes.append(_FRACTAL_MAP.get(fa, fa))

    # 时间轴
    if bi_list is not None:
        ta = time_axis(bsp, bi_list, cfg)
        if ta is not None:
            axes.append(ta)

    if not axes:
        return None
    return AXIS_SEPARATOR.join(axes)


def parse_bsp2_ladder(value: str) -> dict:
    """解析 T2 五轴组合值为 {轴前缀: 档位字符串} 字典。

    未知段前缀忽略（向前兼容：后续加轴不破坏旧值解析）。
    `L4` 单值不在本函数范围（上层类型路由已分流）。
    """
    result = {}
    if not value:
        return result
    for seg in value.split(AXIS_SEPARATOR):
        if not seg:
            continue
        prefix = seg[0]
        if prefix in AXIS_ORDER:
            result[prefix] = seg
    return result


# ----------------------------------------------------------------------
# 佐证轴（T2 版）：复用 bsp_ladder 的窗口映射与判定核心，仅窗口不同
# ----------------------------------------------------------------------

def _corroboration_axis_bsp2(bsp, sub_bs_point_lst, sub_kl=None) -> Optional[str]:
    """T2 佐证轴：回调笔单笔窗口映射到子级时间区间，三档判定。

    判定档位与 T1 的 `corroboration_axis` 同构（已确认 S3 / 候选 S2 /
    末端分型 S1），窗口从 c 走势段换成回调笔所在笔区间（design D7）。
    判定核心（窗口内命中、方向一致、进度档、分型）直接复用 bsp_ladder
    的既有函数——单点口径，避免 T2 版另立实现。
    """
    from .bsp_ladder import (
        _in_window_and_same_dir,
        _sub_has_fractal_in_window,
        _sub_progress_is_early,
        _sub_time_span,
    )

    bi = bsp.bi
    if bi is None:
        return None
    seg = getattr(bi, 'parent_seg', None)
    if seg is None:
        return None
    # 回调笔单笔窗口：区间就是这一笔（bsp2_bi.idx ~ bsp2_bi.idx）
    t_lo, t_hi = _sub_time_span(seg, bi.idx, bi.idx)
    if t_lo is None:
        return None

    is_buy = bool(bsp.is_buy)

    # ---- S3：窗口内子级已确认同向一买 ----
    for sub_bsp in getattr(sub_bs_point_lst, 'bsp1_sure_list', []):
        if _in_window_and_same_dir(sub_bsp, is_buy, t_lo, t_hi):
            return "S3"

    # ---- S2：窗口内子级同向候选点（进度轴 L1 档） ----
    for sub_bsp in getattr(sub_bs_point_lst, 'bsp1_list', []):
        if not _in_window_and_same_dir(sub_bsp, is_buy, t_lo, t_hi):
            continue
        if _sub_progress_is_early(sub_bsp):
            return "S2"

    # ---- S1：窗口内子级末端同向分型 ----
    if sub_kl is not None and _sub_has_fractal_in_window(sub_kl, is_buy, t_lo, t_hi):
        return "S1"
    return None
