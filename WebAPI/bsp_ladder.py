# -*- coding: utf-8 -*-
"""
阶梯三轴推导（chan-bsp-ladder-change D1/D3/D5/D7）。

未确认的第一类买卖点家族（T1/T1P）候选点携带**三轴独立证据**：

    进度轴   L1（判据链 1~4 步）/ L2（5~7 步）
    佐证轴   L2-3（子级已确认买点）/ L2-2（子级候选部分达成）/ L2-1（子级末端分型）
    分型轴   L3-3 / L3-2 / L3-1（本级末端分型强弱）

三轴取值并入竖线分隔的单一字符串（轴顺序固定：进度 → 佐证 → 分型），
如 `L1|L2-3|L3-3`。`L4`（已确认）仍为单值；非一买类型与不可评估的点为 NULL。

## 为什么在本层推导

既有 spec 约束「级别判定 SHALL 在 WebAPI 层完成，不修改缠论计算内核」。
进度轴消费内核透出的 feature 事实（`bsp1_step_*` + `bsp1_standard_reason`），
佐证轴读内核已有的区间套窗口语义（与 `bsp1_qjt_hit` 同源），分型轴用
`fractal_strength` 的纯只读分级。三条链路都只读，不改成立性。

## 与内核 `bsp1_qjt` 的边界

内核特征是**特征**（随点持久，`bsp1_qjt_hit`），本模块的佐证轴是**阶梯标签**
（落库到 `bsp_index.ladder`，每次重算即时推导）。命中资格同口径：
同向、已确认、结构映射窗口内。原 WebAPI L1 时间窗共振已在本变更中退役。

## 落库/序列化双链路

`incremental_engine`（落库）与 `serializer`（/api/klines）共用本模块的同
一个函数，保证口径不漂移（与 `bsp_sure` 的既有模式一致）。
"""

import logging
from typing import Any, Dict, List, Optional

from ChanAnalyse.Common.CEnum import BSP_TYPE

from . import fractal_strength
from .bsp_progress import progress_axis

log = logging.getLogger("bsp_ladder")

# 已确认买卖点（水位线口径，语义不变）
LADDER_L4 = "L4"

# 三轴组合的分隔符。轴顺序固定：进度 → 佐证 → 分型。
AXIS_SEPARATOR = "|"

# 三轴阶梯只对第一类买卖点家族生效（chan-bsp-ladder-change 范围限定）。
# 其余类型改走各自的阶梯语法：T2/T2S 五轴（chan-standard-bsp2-change）、
# T3A/T3B 四轴（chan-standard-bsp3-change）；无匹配类型才返回 NULL。
_BSP1_FAMILY = (BSP_TYPE.T1, BSP_TYPE.T1P)


def is_bsp1_family(bsp) -> bool:
    """该买卖点是第一类买卖点家族（T1 / T1P，含降级 T1P）吗。"""
    try:
        return any(t in _BSP1_FAMILY for t in bsp.type)
    except Exception:
        return False


_BSP2_FAMILY = (BSP_TYPE.T2, BSP_TYPE.T2S)


def _is_bsp2_family(bsp) -> bool:
    """该买卖点是第二类买卖点家族（T2 / T2S）吗（chan-standard-bsp2-change）。"""
    try:
        return any(t in _BSP2_FAMILY for t in bsp.type)
    except Exception:
        return False


_BSP3_FAMILY = (BSP_TYPE.T3A, BSP_TYPE.T3B)


def _is_bsp3_family(bsp) -> bool:
    """该买卖点是第三类买卖点家族（T3A / T3B）吗（chan-standard-bsp3-change）。"""
    try:
        return any(t in _BSP3_FAMILY for t in bsp.type)
    except Exception:
        return False


# ----------------------------------------------------------------------
# 结构调整：c 走势段窗口（与内核 _c_window_of 同源）
# ----------------------------------------------------------------------

def _c_window_bounds(bsp):
    """买卖点所在线段的 c 走势段笔区间 `(c_start_idx, c_end_idx)`。

    与内核 `CBSPointList._c_window_of` / `_cal_force_windows` 的 c 窗口同源：
    `zs.end_bi.idx + 1 ~ seg.end_bi.idx`。窗口定义是单一事实源（spec
    「窗口与力度口径共用同一定义」），本模块不另立口径。

    返回 None 表示不可评估（无 parent_seg / 无中枢 / c 段为空）。
    """
    seg = getattr(bsp.bi, 'parent_seg', None)
    if seg is None:
        return None
    zs_lst = getattr(seg, 'zs_lst', None)
    if not zs_lst:
        return None
    try:
        zs = zs_lst[-1]
        # c 段 = 离开中枢之后到线段末笔
        c_start = zs.end_bi.idx + 1
        c_end = seg.end_bi.idx
        if c_end < c_start:
            return None
        return c_start, c_end, seg
    except Exception:
        return None


def _sub_time_span(seg, c_start_idx: int, c_end_idx: int):
    """把本级别 c 窗口笔区间映射为次级别的时间区间 `(t_lo, t_hi)`。

    **首选口径**：沿每笔的 K 线 `sub_kl_list` 收集子级 K 线时间戳，与内核
    `CBSPointList._sub_time_span` 完全同源。这要求父级 `CChan` 是多级别加载的
    （`load_iterator` 才会挂 `sub_kl_list`）。

    **回退口径**（本模块新增）：落库链路的父级 `CChan` 是**单级别**的
    （`incremental_engine._compute_full` 只 load 本级别，子级别由
    `_compute_sub_for_l1` 独立计算），此时 `sub_kl_list` 恒空。若直接返回
    `(None, None)`，佐证轴在生产落库路径上会**永远缺席**——三轴只剩两轴。
    因此无子级时间戳时改用**父级 K 线自身的时间轴**近似：左端取窗口首根
    父级 K 线的时刻（不晚于其内含的任何子级 K 线），右端取窗口末根时刻
    **外扩一个父级周期**（覆盖该根内含的子级 K 线）。

    这是**时间区间**的近似，不是窗口定义的近似——c 窗口边界仍是
    `zs.end_bi.idx + 1 ~ seg.end_bi.idx` 的结构映射（唯一事实源）。外扩只会
    放大命中集，不会收窄，故仍满足「WebAPI 判定不窄于内核特征」。
    """
    ts_list: List[float] = []
    parent_ts: List[float] = []
    try:
        for bi in seg.bi_list:
            if bi.idx < c_start_idx or bi.idx > c_end_idx:
                continue
            for klc in bi.klc_lst:
                for klu in klc.lst:
                    try:
                        parent_ts.append(klu.time.ts)
                    except Exception:
                        pass
                    for sub_klu in getattr(klu, 'sub_kl_list', ()):
                        try:
                            ts_list.append(sub_klu.time.ts)
                        except Exception:
                            continue
    except Exception:
        return None, None
    if ts_list:
        return min(ts_list), max(ts_list)
    return _parent_bar_span(parent_ts)


def _parent_bar_span(parent_ts: List[float]):
    """父级 K 线时间轴 → 子级时间区间（`_sub_time_span` 的回退口径）。

    右端外扩一个父级周期的估计值（相邻父级 K 线时间差的中位数），
    单根 K 线时退化为不外扩。
    """
    if not parent_ts:
        return None, None
    t_lo, t_hi = min(parent_ts), max(parent_ts)
    if len(parent_ts) < 2:
        return t_lo, t_hi
    ordered = sorted(set(parent_ts))
    deltas = [b - a for a, b in zip(ordered, ordered[1:]) if b > a]
    if not deltas:
        return t_lo, t_hi
    deltas.sort()
    period = deltas[len(deltas) // 2]
    return t_lo, t_hi + period


# ----------------------------------------------------------------------
# 佐证轴：子级结构佐证（D3）
# ----------------------------------------------------------------------

def corroboration_axis(bsp, sub_bs_point_lst, sub_kl=None) -> Optional[str]:
    """佐证轴三档，互斥取最高命中档。

    判定顺序（强 → 弱，命中即返回）：

        L2-3  c 窗口映射的次级别区间内，存在**同向且已确认**的一买
              （子级 `bsp1_sure_list`；与内核 `bsp1_qjt_hit` 同口径）
        L2-2  同区间内存在**同向子级候选点**，且该候选点的进度轴在 L1 档
        L2-1  同区间内次级别末端形成**同向分型**

    Args:
        bsp: 本级别候选点
        sub_bs_point_lst: 子级别 `CBSPointList`；None = 无子级数据 → 不做佐证
        sub_kl: 子级别 `CKLine_List`（L2-1 档的数据源）；None = 不做 L2-1

    Returns:
        `L2-3` / `L2-2` / `L2-1` / None（无子级数据或窗口不可映射）
    """
    if sub_bs_point_lst is None:
        return None
    bounds = _c_window_bounds(bsp)
    if bounds is None:
        return None
    c_start, c_end, seg = bounds
    t_lo, t_hi = _sub_time_span(seg, c_start, c_end)
    if t_lo is None:
        return None

    is_buy = bool(bsp.is_buy)

    # ---- L2-3：子级已确认同向一买（与内核 bsp1_qjt_hit 同口径）----
    for sub_bsp in getattr(sub_bs_point_lst, 'bsp1_sure_list', []):
        if not _in_window_and_same_dir(sub_bsp, is_buy, t_lo, t_hi):
            continue
        return "L2-3"

    # ---- L2-2：子级同向候选点，且其进度轴在 L1 档 ----
    for sub_bsp in getattr(sub_bs_point_lst, 'bsp1_list', []):
        if not _in_window_and_same_dir(sub_bsp, is_buy, t_lo, t_hi):
            continue
        if _sub_progress_is_early(sub_bsp):
            return "L2-2"

    # ---- L2-1：子级末端同向分型 ----
    if sub_kl is not None and _sub_has_fractal_in_window(sub_kl, is_buy, t_lo, t_hi):
        return "L2-1"
    return None


def _in_window_and_same_dir(candidate, is_buy: bool, t_lo: float, t_hi: float) -> bool:
    """候选点在时间窗口内且方向一致。"""
    try:
        if bool(candidate.is_buy) != is_buy:
            return False
        ts = candidate.klu.time.ts
    except Exception:
        return False
    return t_lo <= ts <= t_hi


def _sub_progress_is_early(sub_bsp) -> bool:
    """子级候选点的进度轴是否在 L1 档（判据链前半段）。

    缺进度 feature 的存量点不算「部分达成」——不猜（与 `bsp_progress` 的
    缺键语义一致）。
    """
    try:
        feat = dict(sub_bsp.features.items())
    except Exception:
        return False
    return progress_axis(feat) == "L1"


def _sub_has_fractal_in_window(sub_kl, is_buy: bool, t_lo: float, t_hi: float) -> bool:
    """子级在窗口内是否存在同向分型。

    取子级笔列表中末端落在窗口内的笔，用 `fractal_strength.fractal_of_bi`
    评估其末端分型；方向一致（买点看底分型）且分型形成即命中。
    """
    try:
        bi_list = sub_kl.bi_list
    except Exception:
        return False
    try:
        for bi in reversed(list(bi_list)):
            try:
                ts = bi.get_end_klu().time.ts
            except Exception:
                continue
            if ts > t_hi:
                continue
            if ts < t_lo:
                break
            if fractal_strength.fractal_of_bi(bi, is_buy=is_buy) is not None:
                return True
    except Exception:
        return False
    return False


# ----------------------------------------------------------------------
# 三轴组合
# ----------------------------------------------------------------------

def cal_ladder(bsp, bs_point_lst, bi_list=None, sub_bsps=None,
               kl_type=None, sub_kl_type=None, sub_bs_point_lst=None,
               sub_kl=None, bi_list_ref=None, cfg=None) -> Optional[str]:
    """确认阶梯推导（chan-bsp-ladder-change D1/D3；chan-standard-bsp2-change D1 分派）。

    Args:
        bsp: CBS_Point 实例
        bs_point_lst: 本级别 CBSPointList（L4 水位线口径）
        bi_list: 保留参数（旧签名兼容；进度轴改读 feature，不再需要前前笔）
        sub_bsps: 保留参数（旧签名兼容；佐证轴改读 sub_bs_point_lst）
        kl_type / sub_kl_type: 保留参数（旧签名兼容；时间窗口径已退役）
        sub_bs_point_lst: 子级别 CBSPointList（佐证轴数据源；None = 不做佐证）
        sub_kl: 子级别 CKLine_List（L2-1 分型档需要；None = 不做 L2-1）
        bi_list_ref: 本级别笔列表（T2 五轴的确认轴/时间轴输入；
            chan-standard-bsp2-change 新增；None = T2 的这两轴缺席）
        cfg: CPointConfig（T2 确认窗口/时间轴阈值；None = 用默认值）

    Returns:
        T1 家族：`"L4"` / 三轴组合字符串（如 `"L1|L2-3|L3-3"`） / None
        T2/T2S：`"L4"` / 五轴组合字符串（如 `"P1|S3|C2|K3|T1"`） / None
        T3A/T3B：`"L4"` / 四轴组合字符串（如 `"S3|C2|K3|T1"`，无进度轴） / None

    **L4 优先短路**：已确认点不再携带轴标签（全类型语义不变，
    分派在 L4 短路**之后**——chan-standard-bsp2-change design D1）。
    **非一买家族分派**：T2/T2S 走 `bsp2_ladder`（五轴，P|S|C|K|T 语法）；
    T3A/T3B 走 `bsp3_ladder`（四轴，S|C|K|T 语法，无进度轴——
    chan-standard-bsp3-change design D6）。
    """
    from .bsp_sure import bsp_is_sure

    # ---- L4：已确认（水位线口径，全类型语义不变）----
    try:
        if bsp_is_sure(bsp, bs_point_lst):
            return LADDER_L4
    except Exception:
        log.debug("bsp_is_sure 失败，按未确认处理", exc_info=True)

    # ---- 非一买家族分派（chan-standard-bsp2-change D1）----
    if not is_bsp1_family(bsp):
        # T2/T2S：五轴阶梯（独立 P|S|C|K|T 语法）
        if _is_bsp2_family(bsp):
            from .bsp2_ladder import bsp2_ladder
            # 佐证轴的子级 K 线：与 T1 同一挂载回退（落库链路）
            sub_kl_eff = sub_kl or getattr(sub_bs_point_lst, '_sub_kl_for_fractal', None) \
                if sub_bs_point_lst is not None else None
            return bsp2_ladder(bsp, bs_point_lst, bi_list_ref, cfg,
                               sub_bs_point_lst=sub_bs_point_lst,
                               sub_kl=sub_kl_eff)
        # T3A/T3B：四轴阶梯（S|C|K|T 语法，chan-standard-bsp3-change）
        if _is_bsp3_family(bsp):
            from .bsp3_ladder import bsp3_ladder
            sub_kl_eff3 = sub_kl or getattr(sub_bs_point_lst, '_sub_kl_for_fractal', None) \
                if sub_bs_point_lst is not None else None
            return bsp3_ladder(bsp, bs_point_lst, bi_list_ref, cfg,
                               sub_bs_point_lst=sub_bs_point_lst,
                               sub_kl=sub_kl_eff3)
        return None

    # ---- 三轴 ----
    try:
        feat = dict(bsp.features.items())
    except Exception:
        feat = {}

    axes: List[str] = []

    # 进度轴
    pa = progress_axis(feat)
    if pa is not None:
        axes.append(pa)

    # 佐证轴（依赖子级容器）
    if sub_bs_point_lst is not None:
        # L2-1 需要子级 CKLine_List：优先用显式传入的 sub_kl，
        # 否则从 sub_bs_point_lst 上取临时挂载的引用（落库链路的挂载点）
        sub_kl_eff = sub_kl or getattr(sub_bs_point_lst, '_sub_kl_for_fractal', None)
        ca = corroboration_axis(bsp, sub_bs_point_lst, sub_kl=sub_kl_eff)
        if ca is not None:
            axes.append(ca)

    # 分型轴
    try:
        fa = fractal_strength.fractal_of_bi(bsp.bi, is_buy=bool(bsp.is_buy))
    except Exception:
        fa = None
    if fa is not None:
        axes.append(fa)

    if not axes:
        return None
    return AXIS_SEPARATOR.join(axes)
