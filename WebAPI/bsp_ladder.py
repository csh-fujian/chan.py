# -*- coding: utf-8 -*-
"""
买卖点确认阶梯推导（bsp-ladder-change design D1/D2/D3）。

四级阶梯（单一 `ladder` 字段，判定顺序 L4 > L3 > L1 > L2）：

- L4 确认买卖点：`bsp_is_sure` == True（水位线口径，复用 bsp_sure）
- L3 背驰预警：未确认 且 所在笔与前方同向笔的力度对比触发背驰
- L1 小级别区间套：未确认 且 子级别存在同向买卖点共振（跨级别佐证）
- L2 虚笔候选：未确认 的其余情形（兜底）

同时成立时的裁定（D1）：L3 优先——背驰是本级别信息，L1 是跨级别佐证；
`cal_ladder` 返回主级别，`cal_l1_resonance` 单独暴露共振标记供 tooltip 副标记使用。

L3 背驰判定需要笔列表（前前笔查找）：`CBi` 不持有笔列表反向引用，
调用方（incremental_engine / serializer 均持有 kl 容器）SHALL 显式传
`bi_list`（`kl.bi_list`，CBiList 支持索引与 len）。

双链路差异（D3 修订）：落库链路（incremental_engine）与序列化链路（serializer）
均计算 L1（`BSP_L1_PERSIST` 开关可整体关闭落库链路的 L1）。子级别映射单级
直连（5m→30m→D→W→M 各看直接一级子级，无跨级传递），共振窗口按级别对
差异化（日级 ±5 自然日 / 分钟级 ±2 小时）。

L3 背驰口径（D2）：不 import CBSPointList 私有比较，重写只读比较——
「所在笔（力度出口）< 前方同向笔（力度入口）× DIVERGENCE_RATE」即预警。
参照内核语义（`ZS.is_divergence` / `treat_pz_bsp1` 的
`out_metric <= divergence_rate * in_metric`）。

与 bsp_sure.py 同模式：集中放 WebAPI 层一处，incremental_engine（落库）
与 serializer（/api/klines）复用，保证两条链路口径不漂移。
"""

import logging

from ChanAnalyse.Common.CEnum import KL_TYPE

from .bsp_sure import bsp_is_sure

log = logging.getLogger("bsp_ladder")

# L3 背驰预警阈值：出笔力度 / 入笔力度 <= 该值视为背驰（D2，可调常量）。
# 内核默认 divergence_rate=inf（保送），阶梯预警取保守固定阈值 0.9：
# 出笔力度明显弱于入笔才预警，避免把「力度持平」也标成背驰。
DIVERGENCE_RATE = 0.9

# L1 共振时间窗口（D3 修订二，按级别对差异化）：本级别买卖点前后该窗口内的
# 子级别同向买卖点视为共振。日线及以上（子级 30m/D/W）沿用自然日窗口 5 天；
# 分钟级（30m/60m ← 子级 5m）窗口收窄到 2 小时——5m 信号半衰期短，宽窗会把
# 无关的 5m 信号也算成共振，导致分钟级 L1 泛滥。
L1_WINDOW_SECONDS = {
    # 日线及以上：±5 自然日
    (KL_TYPE.K_DAY, KL_TYPE.K_30M): 5 * 86400,
    (KL_TYPE.K_WEEK, KL_TYPE.K_DAY): 5 * 86400,
    (KL_TYPE.K_MON, KL_TYPE.K_WEEK): 5 * 86400,
    # 分钟级：子级 5m，±2 小时
    (KL_TYPE.K_30M, KL_TYPE.K_5M): 2 * 3600,
    (KL_TYPE.K_60M, KL_TYPE.K_5M): 2 * 3600,
}

LADDER_L1 = "L1"
LADDER_L2 = "L2"
LADDER_L3 = "L3"
LADDER_L4 = "L4"


def _bi_metric(bi, macd_algo, is_reverse: bool):
    """笔力度指标（CBi.cal_macd_metric 只读转发，异常容错返回 None）。"""
    try:
        return bi.cal_macd_metric(macd_algo, is_reverse=is_reverse)
    except Exception:
        return None


def is_beichi_warning(bsp) -> bool:
    """L3 判定（无显式笔列表时）：尝试从买卖点所在笔反查笔列表后走 _beichi_with_list。

    CBS_Point.bsp.bi 不持有笔列表反向引用，本函数是尽力路径；
    调用方持有 bi_list 时应直接用 _beichi_with_list / 传参 cal_ladder(bi_list=...)。
    找不到笔列表 → 不预警（保守 False）。
    """
    bi_list = _bi_list_of(bsp)
    if not bi_list:
        return False
    return _beichi_with_list(bsp, bi_list)


def _default_macd_algo():
    """默认力度算法（与内核 CBSPointConfig 默认一致：peak）。"""
    from ChanAnalyse.Common.CEnum import MACD_ALGO

    return MACD_ALGO.PEAK


def _bi_list_of(bsp):
    """从买卖点反查笔列表。

    CBi 不持有笔列表反向引用；可走的只读路径只有 kl 容器的 bi_list。
    序列化链路（serializer）持有 kl 容器，应显式传 bi_list；
    本函数保留给无法显式传参的调用方，返回 None（保守）。
    """
    return None


def cal_l1_resonance(bsp, sub_bsps, kl_type=None, sub_kl_type=None, sub_bs_point_lst=None) -> bool:
    """L1 判定：子级别同向**已确认**买卖点共振（单级直连，无跨级传递）。

    Args:
        bsp: 本级别 CBS_Point
        sub_bsps: 子级别买卖点列表（CBS_Point 或已抽取的 (is_buy, klu) 对）；
                  None/空列表 = 无子级别数据（5m 无子级、或计算失败）→ False
        kl_type: 本级别 KL_TYPE（窗口差异化查找键；None = 用日级默认窗）
        sub_kl_type: 子级别 KL_TYPE（与 kl_type 配对；None = 用日级默认窗）
        sub_bs_point_lst: 子级别 CBSPointList（子级点确认过滤用；None = 不过滤，
                          旧调用方兼容）

    共振口径（D3 修订三）：子级别存在**同向**（买点对买点）且**已确认**
    （子级点自身 is_sure=true，即子级 L4）的买卖点，且其 klu 时间落在
    本级别买卖点 klu 时间 ± 窗口内。确认过滤用子级别自己的水位线
    （bsp_is_sure）判定，不递归计算子级点的 ladder——否则形成 5m→30m→D
    级联传递，违反单级直连约束。

    窗口按级别对差异化：日级及以上（子级 30m/D/W）±5 自然日（D2 初版容差），
    分钟级（30m/60m ← 5m）±2 小时（D3 修订二收窄，防止 5m 宽窗共振泛滥）。
    """
    if not sub_bsps:
        return False
    try:
        t0 = bsp.klu.time.ts
    except Exception:
        return False
    window = _l1_window_of(kl_type, sub_kl_type)
    for sub in sub_bsps:
        try:
            sub_klu = sub.klu
            sub_is_buy = sub.is_buy
        except AttributeError:
            # 已抽取的元组形态 (is_buy, klu)
            sub_is_buy, sub_klu = sub
        if bool(sub_is_buy) != bool(bsp.is_buy):
            continue
        # 子级点须自身已确认（子级 L4）才可作佐证（D3 修订三）：
        # 未确认的子级点（L1/L2/L3）会随重算漂移/消失，用影子证明身体。
        if sub_bs_point_lst is not None and not bsp_is_sure(sub, sub_bs_point_lst):
            continue
        try:
            if abs(sub_klu.time.ts - t0) <= window:
                return True
        except Exception:
            continue
    return False


def _l1_window_of(kl_type, sub_kl_type) -> int:
    """级别对 → 共振窗口秒数；未匹配/未传键回退日级默认窗（±5 自然日，保守）。"""
    key = (kl_type, sub_kl_type) if kl_type is not None else None
    if key in L1_WINDOW_SECONDS:
        return L1_WINDOW_SECONDS[key]
    # 旧调用方未传级别键（如 serializer 未改）→ 日级默认窗口
    return 5 * 86400


def cal_ladder(bsp, bs_point_lst, bi_list=None, sub_bsps=None, kl_type=None, sub_kl_type=None, sub_bs_point_lst=None) -> str:
    """四级阶梯推导（D1 判定顺序 L4 > L3 > L1 > L2）。

    Args:
        bsp: CBS_Point 实例
        bs_point_lst: CBSPointList 实例（L4 水位线口径）
        bi_list: 笔列表（L3 前前笔查找；缺省尝试 bsp.bi.bi_list 属性）
        sub_bsps: 子级别买卖点列表（L1 共振；None = 不计算 L1）
        kl_type: 本级别 KL_TYPE（L1 窗口差异化键；None = 日级默认窗）
        sub_kl_type: 子级别 KL_TYPE（与 kl_type 配对；None = 日级默认窗）
        sub_bs_point_lst: 子级别 CBSPointList（子级点确认过滤；None = 不过滤，
                          旧调用方兼容）

    Returns:
        "L1" | "L2" | "L3" | "L4"
    """
    if bsp_is_sure(bsp, bs_point_lst):
        return LADDER_L4
    if bi_list is not None:
        if _beichi_with_list(bsp, bi_list):
            return LADDER_L3
    if sub_bsps is not None and cal_l1_resonance(
        bsp, sub_bsps,
        kl_type=kl_type, sub_kl_type=sub_kl_type, sub_bs_point_lst=sub_bs_point_lst,
    ):
        return LADDER_L1
    return LADDER_L2


def _beichi_with_list(bsp, bi_list) -> bool:
    """带显式 bi_list 的 L3 判定（与 is_beichi_warning 同口径）。"""
    bi = bsp.bi
    pre_idx = bi.idx - 2
    if pre_idx < 0 or pre_idx >= len(bi_list):
        return False
    pre_bi = bi_list[pre_idx]
    if pre_bi.dir != bi.dir:
        return False
    macd_algo = _default_macd_algo()
    in_metric = _bi_metric(pre_bi, macd_algo, is_reverse=False)
    out_metric = _bi_metric(bi, macd_algo, is_reverse=True)
    if in_metric is None or out_metric is None:
        return False
    return out_metric <= DIVERGENCE_RATE * in_metric


def ladder_of_legacy(is_sure: bool) -> str:
    """存量行兜底映射（D4）：`bsp_index.ladder` 为 NULL 的旧数据按 is_sure
    映射（true → L4，false → L2），语义保守；下一次整套替换写入后收敛。
    """
    return LADDER_L4 if is_sure else LADDER_L2
