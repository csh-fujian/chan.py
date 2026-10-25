# -*- coding: utf-8 -*-
"""
T3A/T3B 四轴阶梯组装（chan-standard-bsp3-change design D6）。

四轴语法（axis 顺序固定：佐证 → 确认 → 分型 → 时间）：
    组合形如 "S3|C2|K3|T1"（各轴档位数字 1=低 3=高）
    已确认单值 "L4" 由上层 `cal_ladder` 的 L4 短路统一处理，本模块不管。

轴前缀（design D6）：
    S 佐证轴   回抽笔单笔窗口映射到子级时间区间 → S3/S2/S1
    C 确认轴   `bsp3_confirm.confirm_axis`（缠论要素 E）→ C3/C2/C1/C0
    K 分型轴   `fractal_strength.fractal_of_bi` 直用，L3-x 映射为 K3/K2/K1
    T 时间轴   `bsp3_time_axis.time_axis`（回抽速度比）→ T3/T2/T1

**为什么没有进度轴 P**（design D6）：T2 的进度轴语义是「判据链推进到第几步」，
可分步推进；T3 判据链（中枢锚定 → 突破方向 → 第一次回抽 → 不回中枢）在
回抽笔端点**一次性全部可判**，成立即全链通过，没有「推进到一半」的中间态。
硬造 P 轴只会输出恒 P1，无信息量。

解析规则：按 `|` split，段首字母识别轴，未知段忽略（向前兼容）。

**这是只读推导模块**：不 import 内核计算类，不改变任何买卖点的成立性
（spec `chan-bsp3-ladder`「成立判据零改动」）。
"""

from typing import List, Optional

from . import fractal_strength
from .bsp3_confirm import confirm_axis
from .bsp3_time_axis import time_axis

# 轴顺序（design D6：固定，输出与解析都按此序）
AXIS_ORDER = ("S", "C", "K", "T")

# fractal_strength 档位（L3-x）→ T3 分型轴档位（K-x）
_FRACTAL_MAP = {"L3-3": "K3", "L3-2": "K2", "L3-1": "K1"}


def bsp3_ladder(bsp, bs_point_lst, bi_list, cfg, sub_bs_point_lst=None,
                sub_kl=None) -> Optional[str]:
    """推导 T3A/T3B 候选点的四轴阶梯组合值。

    Args:
        bsp: CBS_Point 实例（T3A 或 T3B）
        bs_point_lst: 本级别 CBSPointList（未使用，签名对齐既有轴函数）
        bi_list: 本级别笔列表（确认轴 / 时间轴输入）
        cfg: CPointConfig（窗口 / 阈值配置）
        sub_bs_point_lst: 子级别 CBSPointList（佐证轴数据源；None = 轴缺席）
        sub_kl: 子级别 CKLine_List（佐证轴 S1 档的数据源；None = 不做 S1）

    Returns:
        四轴组合字符串（各轴缺证据时该轴缺席，非全缺席），或 None（全轴缺席）。
    """
    axes: List[str] = []

    # 佐证轴（回抽笔单笔窗口：T3 的结构单元就是回抽笔——问「回抽位置上
    # 子级别有没有走出同向结构」，即区间套精确定位，design D6）
    if sub_bs_point_lst is not None:
        sa = _corroboration_axis_bsp3(bsp, sub_bs_point_lst, sub_kl=sub_kl)
        if sa is not None:
            axes.append(sa)

    # 确认轴（缠论要素 E：事后价格确认，design D5）
    if bi_list is not None:
        ca = confirm_axis(bsp, bi_list, cfg)
        if ca is not None:
            axes.append(ca)

    # 分型轴（回抽笔末端分型强弱；买卖镜像由 is_buy 决定）
    try:
        fa = fractal_strength.fractal_of_bi(bsp.bi, is_buy=bool(bsp.is_buy))
    except Exception:
        fa = None
    if fa is not None:
        axes.append(_FRACTAL_MAP.get(fa, fa))

    # 时间轴（回抽速度比）
    if bi_list is not None:
        ta = time_axis(bsp, bi_list, cfg)
        if ta is not None:
            axes.append(ta)

    if not axes:
        return None
    return "|".join(axes)


def parse_bsp3_ladder(value: str) -> dict:
    """解析 T3 四轴组合值为 {轴前缀: 档位字符串} 字典。

    未知段前缀忽略（向前兼容：后续加轴不破坏旧值解析）。
    `L4` 单值不在本函数范围（上层类型路由已分流）。
    """
    result = {}
    if not value:
        return result
    for seg in value.split("|"):
        if not seg:
            continue
        prefix = seg[0]
        if prefix in AXIS_ORDER:
            result[prefix] = seg
    return result


# ----------------------------------------------------------------------
# 佐证轴（T3 版）：复用 bsp_ladder 的窗口映射与判定核心，仅窗口不同
# ----------------------------------------------------------------------

def _corroboration_axis_bsp3(bsp, sub_bs_point_lst, sub_kl=None) -> Optional[str]:
    """T3 佐证轴：回抽笔单笔窗口映射到子级时间区间，三档判定。

    判定档位与 T1/T2 的佐证轴同构（已确认 S3 / 候选 S2 / 末端分型 S1），
    窗口为**回抽笔**所在笔区间——比 T1 的 c 走势段更短、比 T2 的回调笔
    语义更精确（三买的回抽本身就是待确认的那一段，区间套在此处定位
    最低误差买点）。判定核心直接复用 bsp_ladder 的既有函数——单点口径。
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
    # 回抽笔单笔窗口：区间就是这一笔（bsp3_bi.idx ~ bsp3_bi.idx）
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
