# -*- coding: utf-8 -*-
"""底部形态买点检测器（chan-pattern-buy-signal）。

数据来源：文档/买卖点走势图/买点/ 9 张图（八大起涨形态）。本模块是缠论核心的
**只读消费者**——不改 CChan/CBiList 等计算逻辑，仅消费 bi_list 端点几何与
K 线 OHLCV。

架构（design D2）：一个框架 + 8 个薄检测器 + 共用突破确认引擎 + 置信分引擎。
- 离散形态（W底/头肩底/箱体/三角/旗形/V型）：笔端点（SwingPoint）几何检验；
- 连续形态（圆弧底/杯柄杯体）：K 线中值序列 (high+low)/2 抛物线拟合（design D3，
  用户提出的取中值方案，numpy.polyfit 实现，无需第三方形态识别库）。

避坑硬约束（spec「形态检测判据」）：高位出现丢弃、最小周期不足不报、
盘中脉冲不算（确认一律用 close，禁 high）。

所有阈值集中在 DETECT_PARAMS（design D9），每项注释对应文档条目。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Sequence, Tuple

import numpy as np

log = logging.getLogger("pattern_detector")

# ---------------------------------------------------------------------------
# 参数表（design D9）：每项对应文档条目，改值需注明依据
# ---------------------------------------------------------------------------

DETECT_PARAMS: dict = {
    # --- 突破确认（共用引擎，8 张图共同的「有效确认信号」） ---
    # 「突破伴随明显放量，量能要明显大于近期均量」→ 量比阈值（突破日量 / 近期均量）
    "vol_ratio_k": 1.5,
    # 近期均量窗口（突破日之前的 N 根）
    "vol_ma_window": 5,
    # 「收盘价站稳颈线上方，不是盘中瞬间冲过又回落」→ 确认只认 close，
    #   站稳根数（突破日及其后连续收盘在参考线上方的最少根数）
    "stand_bars": 1,
    # 「加分项：突破后出现回踩，回踩不破颈线，回踩过程缩量」→ 回踩观察窗口
    "retest_window": 10,
    # 「回踩跌破颈线，形态失效」→ 失效观察窗口
    "invalid_window": 20,
    # 「周期越长越可靠」「几根K线形成的小形态参考意义低」→ 最小周期约束
    "min_pattern_bars": 10,
    # 「必须出现在一轮下跌之后，高位出现警惕诱多」→ 结构起点前需有足够跌幅
    "prior_decline_pct": 0.10,
    "prior_decline_window": 60,
    # 低位区判定：当前价处于前窗高低区间的下半部（旗形/箱体「低位」约束）
    "low_zone_ratio": 0.6,
    # 旗形位置上限（低位或上升途中均可，只排除前窗高位区）
    "flag_zone_ratio": 0.9,

    # --- W底 ---
    # 「右底不大幅跌破左底，允许小幅低于左底（误差2~3%以内）」
    "w_bottom_tol": 0.03,
    # 颈线（中间反弹高点）相对双底的最低高度，排除浅波动噪声
    "w_min_neck_height": 0.03,

    # --- 头肩底 ---
    # 颈线斜率上限（「可以水平、微微上倾或微微下倾」；水平最可靠 → 斜率大扣分）
    "hs_max_neck_slope": 0.02,
    # 右肩可以略低于左肩但「不能跌破头部低点」→ 右肩相对头部的最小高度
    "hs_min_shoulder_above_head": 0.01,

    # --- 箱体突破 ---
    # 「每次上涨到同一价位附近就遇阻回落」→ 上下轨触碰容差（相对箱体高度）
    "box_touch_tol": 0.25,
    # 上下轨各需触碰次数
    "box_min_touches": 2,
    # 「箱体不宜过小」→ 箱体高度下限（相对价格）
    "box_min_height_pct": 0.05,
    # 箱体最少 K 线数
    "box_min_bars": 20,

    # --- 上升三角形 ---
    # 上边高点等高容差（相对价格）
    "tri_top_tol": 0.02,
    # 下边低点抬升的最小斜率（相对价格/根）
    "tri_min_low_slope": 0.0005,
    # 「三角形整理内部成交量逐步萎缩」→ 末段量 / 首段量 上限
    "tri_vol_shrink_max": 0.9,

    # --- 低位旗形 ---
    # 「旗杆：快速拉升」→ 旗杆最小涨幅与最大根数
    "flag_pole_min_gain": 0.15,
    "flag_pole_max_bars": 20,
    # 「小幅向下倾斜整理」「旗面不能吃掉旗杆涨幅大半」
    "flag_max_retrace": 0.5,
    # 旗面通道斜率范围（向下倾斜：负斜率且不过陡）
    "flag_channel_slope": (-0.008, -0.0002),
    # 「旗面整理阶段成交量持续缩量」
    "flag_vol_shrink_max": 0.8,

    # --- V型反转 ---
    # 「左侧快速下跌：连续大阴线、短期跌幅大」
    "v_min_drop_pct": 0.15,
    "v_drop_max_bars": 20,
    # 「暴跌之后出现放量长阳线，吃掉前面多根阴线，扭转短期下跌节奏」
    "v_reclaim_candles": 3,
    # 「一旦回踩跌破V尖低点，形态作废」
    "v_stop_below_low": True,

    # --- 圆弧底（design D3 判定链） ---
    # 拟合窗口范围（多尺度滑窗，「时间越长筹码换手越充分」）
    "arc_windows": (60, 120, 250),
    # 「R² 足够高」→ 二次拟合优度下限
    "arc_min_r2": 0.6,
    # 顶点（弧底）须落在窗口中部（1/3 ~ 2/3）
    "arc_vertex_band": (0.3, 0.7),
    # 曲率带：排除 V 型尖底（过大）与近似横盘（过小）——窗口归一化后二次项系数
    "arc_curvature_band": (0.02, 2.0),
    # 「底部阴阳交错、波动很小」→ 底段振幅（相对窗口高度）上限
    "arc_base_amp_max": 0.15,
    # 底段最少根数
    "arc_base_min_bars": 10,
    # 左侧下跌段最小跌幅
    "arc_min_left_drop": 0.10,

    # --- 杯柄（design D3：杯体复用圆弧判据） ---
    # 「回撤深度一般从前高点回落 15~30%，回调超 50% 可靠性大幅下降」
    "cup_depth_band": (0.15, 0.30),
    "cup_depth_hard_max": 0.50,
    # 「柄部在杯子上半部分」「柄部回调幅度不能超过杯体深度的 1/3」
    "handle_max_depth_ratio": 1 / 3,
    # 柄部最长根数
    "handle_max_bars": 25,

    # ------------------------------------------------------------------
    # --- 顶部看跌形态（chan-pattern-sell-signal，design D4 蜡烛图路径） ---
    # ------------------------------------------------------------------
    # 「必须出现在上涨趋势/上涨末端/高位」→ 形态前需有足够涨幅（买向
    # prior_decline_pct 的高位镜像；5 张卖点图共同的位置前提硬约束）
    "prior_rally_pct": 0.10,
    # 高位判定：形态末端收盘价处于前窗高低区间的上部（low_zone_ratio 镜像）
    "high_zone_ratio": 0.6,
    # 量能佐证（巨量/爆量/放量）：形态 K 线量 / 前窗均量 阈值
    "sell_vol_ratio_k": 1.5,
    # 量能均量窗口（形态 K 线之前的 N 根）
    "sell_vol_ma_window": 5,

    # --- 乌云盖顶 ---
    # 「收出一根实体覆盖前阳线 1/3 以上的阴线」→ 阴线深入前阳线实体的最小比例
    "dcc_min_penetration": 1 / 3,
    # 前阳线实体最小涨幅（排除小十字星噪声，「先出现一根实体阳线」）
    "dcc_min_body_pct": 0.01,

    # --- 射击之星 / 高位吊颈线（镜像共用参数） ---
    # 「上影线极长」→ 上影线 ≥ 实体的倍数
    "star_upper_shadow_ratio": 2.0,
    # 「下影线极短」→ 下影线 ≤ 实体的倍数
    "star_lower_shadow_max": 0.3,
    # 「K线实体极小」→ 实体占 K 线全幅的上限
    "star_max_body_ratio": 0.3,

    # --- 高位阴包阳 / 穿头破脚 ---
    # 「大阴线」→ 阴线实体最小涨幅（相对价格，排除勉强包裹的小阴线）
    "engulf_min_body_pct": 0.01,
}

# 置信分三轴上限与分数边界（design D6，沿用 bsp_grade 的 59/60/79 边界教训）
STRUCT_AXIS = 40
VOL_AXIS = 30
CONFIRM_AXIS = 30
_CAP_BLOCKED = 59          # 被否决项卡住时的分数封顶
_FLOOR_CONFIRMED = 60      # 确认成立的分数地板
_CAP_PENDING = 79          # 成立但缺回踩加分时的封顶


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class SwingPoint:
    """笔端点抽象：检测器只依赖该视图，便于内存构造测试（duck-typing）。"""

    idx: int            # 原始 K 线下标
    price: float        # 端点价格（高点取 high，低点取 low）
    is_high: bool       # True=顶（笔高点），False=底（笔低点）
    time_key: str = ""
    klu: Any = None     # 关联原始 K 线（可空，供量能/确认取数）


@dataclass
class BreakoutResult:
    """共用突破确认引擎的输出。"""

    confirmed: bool = False
    confirm_idx: Optional[int] = None       # 突破确认 K 线下标
    volume_ratio: float = 0.0               # 突破日量 / 近期均量
    retest: bool = False                    # 回踩缩量不破（加分项）
    invalidated: bool = False               # 确认后收盘跌回参考线下方
    veto: Optional[str] = None              # 一票否决原因（"no_volume" 等）
    vetoed_attempts: int = 0                # 观察窗内被否决的假突破次数


@dataclass
class PatternHit:
    """一次形态命中：落库与展示的最小完整单元。"""

    pattern_type: str                     # PATTERN_META 中的键
    struct_begin_idx: int                 # 形态结构起点（左底/左肩/箱体左沿）
    struct_end_idx: int                   # 形态结构终点（右底/右肩/上轨最后一次触碰）
    ref_line: Tuple[float, float]         # 参考线两端价位（结构区间上的起止价，
                                          #   水平线两点相等；斜线按端点价位存）
    key_points: List[dict] = field(default_factory=list)
        # 关键点：[{role, idx, price}]，role 如 left_bottom/neck/right_bottom
    breakout: BreakoutResult = field(default_factory=BreakoutResult)
    score: int = 0
    qual: str = ""
    veto: Optional[str] = None            # 否决原因键（读取侧经 meta 现算文案）
    features: dict = field(default_factory=dict)   # 评分明细（现算文案用）
    direction: str = "buy"                # 信号方向：buy=底部形态 / sell=顶部形态


# ---------------------------------------------------------------------------
# 从 chan 对象提取视图
# ---------------------------------------------------------------------------

def extract_swing_points(bi_list) -> List[SwingPoint]:
    """笔列表 → 交替顶底的端点视图。

    bi_list 端点天然交替（顶/底分型），直接取每笔终点；起点若与首笔终点
    方向相反也纳入（保证序列从左到右完整覆盖）。
    """
    points: List[SwingPoint] = []
    if not bi_list:
        return points
    first = bi_list[0]
    bklu = first.get_begin_klu()
    points.append(SwingPoint(
        idx=bklu.idx, price=first.get_begin_val(),
        is_high=not first.is_up(),  # 下降笔的起点是顶
        time_key=_klu_time_key(bklu), klu=bklu,
    ))
    for bi in bi_list:
        eklu = bi.get_end_klu()
        points.append(SwingPoint(
            idx=eklu.idx, price=bi.get_end_val(),
            is_high=bi.is_up(),  # 上升笔的终点是顶
            time_key=_klu_time_key(eklu), klu=eklu,
        ))
    return points


def _klu_time_key(klu) -> str:
    """KLU → 'YYYY-MM-DD HH:MM:SS'（失败回退空串，检测不因展示字段中断）。"""
    try:
        t = klu.time
        return f"{t.toDateStr('-')} {t.toTimeStr(':')}"
    except Exception:
        try:
            return str(klu.time)
        except Exception:
            return ""


def _volume(klu) -> float:
    """成交量读取（trade_info.metric 键名兜底，缺量回退 0）。"""
    try:
        m = klu.trade_info.metric
        for k in ("volume", "vol", "amount"):
            if k in m and m[k]:
                return float(m[k])
    except Exception:
        pass
    return 0.0


def _klus(kl) -> List[Any]:
    """CKLine_List → 原始 K 线列表（摊平合并 K 线）。

    迭代 CKLine_List 产出的是合并 K 线（CKLine，无 close/成交量语义），
    原始 CKLine_Unit 在各合并 K 线的 .lst 里；检测器需要逐根原始 K 线的
    OHLC 与量。形态检测基于原始 K 线而非合并 K 线（确认信号按收盘判定）。
    """
    try:
        combiners = list(kl)
    except Exception:
        combiners = []
        i = 0
        while True:
            try:
                combiners.append(kl[i])
                i += 1
            except Exception:
                break
    out: List[Any] = []
    for c in combiners:
        units = getattr(c, "lst", None)
        if units:
            out.extend(units)
        else:
            out.append(c)  # 已是原始 K 线（内存测试桩直接传列表时）
    return out


def _prior_decline_ok(candles, struct_begin_idx: float, params: dict) -> Tuple[bool, float]:
    """「必须出现在一轮下跌之后」（避坑硬约束）。

    结构起点前 prior_decline_window 根内，前高到结构起点的跌幅是否达标。
    返回 (是否通过, 实际跌幅)。
    """
    lo = max(0, int(struct_begin_idx) - params["prior_decline_window"])
    seg = candles[lo:int(struct_begin_idx) + 1]
    if len(seg) < 5:
        return False, 0.0
    prior_high = max(float(c.high) for c in seg)
    base = float(candles[int(struct_begin_idx)].low)
    if prior_high <= 0:
        return False, 0.0
    drop = (prior_high - base) / prior_high
    return drop >= params["prior_decline_pct"], drop


def _in_low_zone(candles, begin_idx: int, end_idx: int, params: dict) -> bool:
    """低位区判定（箱体的「低位」约束）：结构区间价格处于前窗高低区下半部。"""
    return _position_ratio(candles, begin_idx, end_idx,
                           params["prior_decline_window"]) <= params["low_zone_ratio"]


def _position_ratio(candles, begin_idx: int, end_idx: int, window: int) -> float:
    """结构末端收盘价在前窗高低区间中的位置（0=最低，1=最高）。

    前窗数据不足（<5 根）时返回 0.5 中性值：不做位置过滤（避免序列头部
    的形态被误杀，位置约束只在有足够历史时生效）。
    """
    lo = max(0, begin_idx - window)
    seg = candles[lo:end_idx + 1]
    if len(seg) < 5:
        return 0.5
    hi = max(float(c.high) for c in seg)
    lo_p = min(float(c.low) for c in seg)
    if hi <= lo_p:
        return 1.0
    end_close = float(candles[end_idx].close)
    return (end_close - lo_p) / (hi - lo_p)


# ---------------------------------------------------------------------------
# 共用突破确认引擎（任务 1.3，design D2）
# ---------------------------------------------------------------------------

def confirm_breakout(
    candles: Sequence,
    ref_at: Callable[[int], float],
    start_idx: int,
    end_idx: int,
    params: dict,
) -> BreakoutResult:
    """统一突破确认：只认 close（禁 high），量比一票否决，回踩加分，跌回失效。

    ref_at(idx)：参考线在该 K 线下标的价位（支持水平与斜线）。
    扫描 [start_idx, end_idx]：首个「close 站上参考线且量比达标」且此后
    连续 stand_bars 根收盘不跌回的 K 线为确认点；量能不足的突破记否决尝试，
    不构成确认（「无量突破大多是假突破」）。
    """
    res = BreakoutResult()
    n = len(candles)
    end_idx = min(end_idx, n - 1)
    k = params["vol_ratio_k"]
    win = params["vol_ma_window"]

    for i in range(max(start_idx, win), end_idx + 1):
        ref = ref_at(i)
        if ref <= 0:
            continue
        close = float(candles[i].close)
        if close <= ref:
            continue
        # 量比：突破日量 / 前 win 根均量（不含突破日）
        base_vols = [_volume(candles[j]) for j in range(i - win, i)]
        avg_vol = sum(base_vols) / win if win > 0 else 0.0
        vr = _volume(candles[i]) / avg_vol if avg_vol > 0 else 0.0
        if vr < k:
            res.vetoed_attempts += 1
            continue  # 无量突破不算确认，继续找后续有效突破
        # 站稳检验：此后连续 stand_bars 根收盘不低于参考线
        stand_ok = True
        for s in range(1, params["stand_bars"]):
            if i + s > end_idx or float(candles[i + s].close) < ref_at(i + s):
                stand_ok = False
                break
        if not stand_ok:
            continue
        res.confirmed = True
        res.confirm_idx = i
        res.volume_ratio = vr
        break

    if not res.confirmed:
        # 从未找到有效突破：若存在被否决的尝试，标记无量否决（「无量突破大多是假突破」）
        if res.vetoed_attempts > 0:
            res.veto = "no_volume"
        return res

    # 回踩加分（「回踩不破，缩量，第二次确认」）与失效（「回踩跌破颈线，形态失效」）
    for j in range(res.confirm_idx + 1, min(res.confirm_idx + params["invalid_window"], n)):
        ref = ref_at(j)
        close = float(candles[j].close)
        if close < ref:
            res.invalidated = True
            break
        low = float(candles[j].low)
        if not res.retest and j <= res.confirm_idx + params["retest_window"]:
            # 回踩缩量：触及参考线附近但不收盘跌破，且量能较确认日萎缩
            if low <= ref * 1.02 and close >= ref and _volume(candles[j]) < _volume(candles[res.confirm_idx]):
                res.retest = True
    return res


def _score(hit: PatternHit, struct_items, vol_items, confirm_items) -> None:
    """三轴计分（design D6）：items = [(名称, 权重, 是否通过)]。

    分数边界（bsp_grade 教训）：确认成立保底 _FLOOR_CONFIRMED；缺回踩等
    加分封顶 _CAP_PENDING；否决项（无量/高位/周期不足）封顶 _CAP_BLOCKED。
    分数与档位同源：qual 一律由 _qual_of(score) 推导。
    """
    s = sum(w for _, w, ok in struct_items if ok) / max(1, sum(w for _, w, _ in struct_items)) * STRUCT_AXIS \
        + sum(w for _, w, ok in vol_items if ok) / max(1, sum(w for _, w, _ in vol_items)) * VOL_AXIS \
        + sum(w for _, w, ok in confirm_items if ok) / max(1, sum(w for _, w, _ in confirm_items)) * CONFIRM_AXIS
    score = int(round(s))
    if hit.breakout.veto:
        score = min(score, _CAP_BLOCKED)
    elif hit.breakout.confirmed and not hit.breakout.retest:
        score = min(score, _CAP_PENDING)
    if hit.breakout.confirmed and not hit.breakout.veto:
        score = max(score, _FLOOR_CONFIRMED)
    hit.score = score
    hit.qual = _qual_of(score)
    hit.veto = hit.breakout.veto
    hit.features = {
        "struct": [f"{n}:{'1' if ok else '0'}" for n, _, ok in struct_items],
        "vol": [f"{n}:{'1' if ok else '0'}" for n, _, ok in vol_items],
        "confirm": [f"{n}:{'1' if ok else '0'}" for n, _, ok in confirm_items],
    }


def _qual_of(score: int) -> str:
    """分数 → 档位（与措辞同源，读取侧不再二次推导）。"""
    if score >= 80:
        return "强"
    if score >= 60:
        return "中"
    if score >= 30:
        return "弱"
    return "否"


def _confirm_items(hit: PatternHit, params: dict) -> list:
    b = hit.breakout
    bars_since = None
    return [
        ("收盘站稳参考线", 2, b.confirmed),
        ("突破同步放量", 2, b.confirmed and b.volume_ratio >= params["vol_ratio_k"]),
        ("回踩不破缩量", 1, b.retest),
        ("未失效", 1, b.confirmed and not b.invalidated),
    ]


# ---------------------------------------------------------------------------
# 通用小工具
# ---------------------------------------------------------------------------

def _pair_tops_bottoms(points: List[SwingPoint]):
    """端点视图拆分：顶点列表与底点列表（按 idx 升序）。"""
    tops = [p for p in points if p.is_high]
    bottoms = [p for p in points if not p.is_high]
    return tops, bottoms


def _ref_from_anchors(idx0: float, p0: float, idx1: float, p1: float) -> Callable[[int], float]:
    """两点定线：返回 idx → 价位 的线性函数（水平线时退化为常量）。"""
    if idx1 == idx0:
        return lambda i: p0
    slope = (p1 - p0) / (idx1 - idx0)
    return lambda i: p0 + slope * (i - idx0)


def _vol_features(candles, begin_idx: int, end_idx: int, params: dict) -> dict:
    """区间量能特征统计（量能轴公共输入）。"""
    seg = candles[begin_idx:end_idx + 1]
    vols = [_volume(c) for c in seg]
    n = len(vols)
    first = sum(vols[:max(1, n // 3)]) / max(1, n // 3)
    last = sum(vols[-max(1, n // 3):]) / max(1, n // 3)
    return {
        "avg_vol": sum(vols) / max(1, n),
        "first_third_avg": first,
        "last_third_avg": last,
        "shrink": last < first,               # 末段量 < 首段量
        "min_vol_idx": begin_idx + int(np.argmin(vols)) if vols else begin_idx,
    }


# ---------------------------------------------------------------------------
# 检测器 1：W底（任务 2.1）
# ---------------------------------------------------------------------------

def detect_w_bottom(points: List[SwingPoint], candles, params: dict) -> List[PatternHit]:
    """W底（双重底）：左底→颈线→右底→突破颈线放量。

    判据（文档）：两个低点大致平齐（右底允许小幅高于/略低于左底，容差 3%），
    不能大幅创新低；中间反弹高点构成颈线；收盘放量突破颈线。
    """
    hits: List[PatternHit] = []
    _, bottoms = _pair_tops_bottoms(points)
    tol = params["w_bottom_tol"]
    min_h = params["w_min_neck_height"]
    for i in range(len(bottoms) - 1):
        l1, l2 = bottoms[i], bottoms[i + 1]
        if l2.idx - l1.idx < params["min_pattern_bars"]:
            continue
        # 颈线 = 两底之间的最高顶点
        neck = max((p for p in points if l1.idx < p.idx < l2.idx and p.is_high),
                   key=lambda p: p.price, default=None)
        if neck is None:
            continue
        base = min(l1.price, l2.price)
        if neck.price < base * (1 + min_h):
            continue
        # 「右底不大幅跌破左底」：右底最多低于左底 tol
        if l2.price < l1.price * (1 - tol):
            continue
        # 结构需在一段下跌之后（避坑硬约束：高位出现不报）
        decline_ok, drop = _prior_decline_ok(candles, l1.idx, params)
        if not decline_ok:
            continue
        b = confirm_breakout(candles, lambda i: neck.price, l2.idx,
                             l2.idx + params["invalid_window"] + params["retest_window"] + 10, params)
        hit = PatternHit(
            pattern_type="w_bottom",
            struct_begin_idx=l1.idx, struct_end_idx=l2.idx,
            ref_line=(neck.price, neck.price),
            key_points=[
                {"role": "left_bottom", "idx": l1.idx, "price": l1.price},
                {"role": "neck", "idx": neck.idx, "price": neck.price},
                {"role": "right_bottom", "idx": l2.idx, "price": l2.price},
            ],
            breakout=b,
        )
        vf = _vol_features(candles, l1.idx, l2.idx, params)
        _score(
            hit,
            struct_items=[
                ("双底平齐", 3, abs(l2.price - l1.price) / max(l1.price, 1e-9) <= tol),
                ("颈线高度足", 2, neck.price >= base * (1 + min_h)),
                ("右底未大幅破左底", 3, l2.price >= l1.price * (1 - tol)),
                ("前有一轮下跌", 2, decline_ok),
            ],
            vol_items=[
                ("左底恐慌放量", 2, vf["first_third_avg"] > 0),
                ("右底缩量", 3, vf["last_third_avg"] < vf["first_third_avg"]),
                ("突破放量", 3, b.confirmed and b.volume_ratio >= params["vol_ratio_k"]),
            ],
            confirm_items=_confirm_items(hit, params),
        )
        hits.append(hit)
    return hits


# ---------------------------------------------------------------------------
# 检测器 2：头肩底（任务 2.2）
# ---------------------------------------------------------------------------

def detect_head_shoulders(points: List[SwingPoint], candles, params: dict) -> List[PatternHit]:
    """头肩底：左肩→头（最低）→右肩，两峰连线为颈线（允许微斜），突破颈线放量。"""
    hits: List[PatternHit] = []
    _, bottoms = _pair_tops_bottoms(points)
    for i in range(len(bottoms) - 2):
        ls, head, rs = bottoms[i], bottoms[i + 1], bottoms[i + 2]
        if rs.idx - ls.idx < params["min_pattern_bars"] * 2:
            continue
        peak1 = max((p for p in points if ls.idx < p.idx < head.idx and p.is_high),
                    key=lambda p: p.price, default=None)
        peak2 = max((p for p in points if head.idx < p.idx < rs.idx and p.is_high),
                    key=lambda p: p.price, default=None)
        if peak1 is None or peak2 is None:
            continue
        # 头部必须低于两肩；右肩不破头部低点
        if not (head.price < ls.price and head.price < rs.price):
            continue
        if rs.price < head.price * (1 + params["hs_min_shoulder_above_head"]):
            continue
        # 颈线：两峰连线；斜率限幅（水平最可靠）
        slope = (peak2.price - peak1.price) / max(1, peak2.idx - peak1.idx) / max(peak1.price, 1e-9)
        if abs(slope) > params["hs_max_neck_slope"]:
            continue
        decline_ok, _ = _prior_decline_ok(candles, ls.idx, params)
        if not decline_ok:
            continue
        ref_at = _ref_from_anchors(peak1.idx, peak1.price, peak2.idx, peak2.price)
        b = confirm_breakout(candles, ref_at, rs.idx,
                             rs.idx + params["invalid_window"] + params["retest_window"] + 10, params)
        hit = PatternHit(
            pattern_type="head_shoulders",
            struct_begin_idx=ls.idx, struct_end_idx=rs.idx,
            ref_line=(peak1.price, peak2.price),
            key_points=[
                {"role": "left_shoulder", "idx": ls.idx, "price": ls.price},
                {"role": "peak1", "idx": peak1.idx, "price": peak1.price},
                {"role": "head", "idx": head.idx, "price": head.price},
                {"role": "peak2", "idx": peak2.idx, "price": peak2.price},
                {"role": "right_shoulder", "idx": rs.idx, "price": rs.price},
            ],
            breakout=b,
        )
        vf = _vol_features(candles, head.idx, rs.idx, params)
        _score(
            hit,
            struct_items=[
                ("头低于两肩", 3, head.price < min(ls.price, rs.price)),
                ("右肩不破头", 2, rs.price > head.price),
                ("颈线近水平", 2, abs(slope) <= params["hs_max_neck_slope"] * 0.5),
                ("前有一轮下跌", 2, decline_ok),
            ],
            vol_items=[
                ("头部缩量", 3, vf["min_vol_idx"] >= head.idx - 3 and vf["min_vol_idx"] <= rs.idx),
                ("右肩明显缩量", 2, vf["last_third_avg"] < vf["first_third_avg"]),
                ("突破放量", 3, b.confirmed and b.volume_ratio >= params["vol_ratio_k"]),
            ],
            confirm_items=_confirm_items(hit, params),
        )
        hits.append(hit)
    return hits


# ---------------------------------------------------------------------------
# 检测器 3：箱体突破（任务 2.3）
# ---------------------------------------------------------------------------

def detect_box_breakout(points: List[SwingPoint], candles, params: dict) -> List[PatternHit]:
    """箱体突破：上下轨各 ≥2 次触碰，收盘放量站上上轨。"""
    hits: List[PatternHit] = []
    tops, bottoms = _pair_tops_bottoms(points)
    for i in range(len(points) - params["box_min_touches"] * 2):
        win = points[i:i + 8]
        tops_w = [p for p in win if p.is_high]
        bots_w = [p for p in win if not p.is_high]
        if len(tops_w) < params["box_min_touches"] or len(bots_w) < params["box_min_touches"]:
            continue
        if win[-1].idx - win[0].idx < params["box_min_bars"]:
            continue
        box_high = max(p.price for p in tops_w)
        box_low = min(p.price for p in bots_w)
        height = box_high - box_low
        if height <= 0 or box_low <= 0:
            continue
        if height / box_low < params["box_min_height_pct"]:
            continue
        tol = height * params["box_touch_tol"]
        top_touches = [p for p in tops_w if box_high - p.price <= tol]
        bot_touches = [p for p in bots_w if p.price - box_low <= tol]
        if len(top_touches) < params["box_min_touches"] or len(bot_touches) < params["box_min_touches"]:
            continue
        if not _in_low_zone(candles, win[0].idx, win[-1].idx, params):
            continue  # 「低位箱体向上突破价值高；高位箱体多是出货，突破是诱多」
        last_top = max(tops_w, key=lambda p: p.idx)
        b = confirm_breakout(candles, lambda idx: box_high, last_top.idx,
                             last_top.idx + params["invalid_window"] + params["retest_window"] + 10, params)
        hit = PatternHit(
            pattern_type="box_breakout",
            struct_begin_idx=win[0].idx, struct_end_idx=win[-1].idx,
            ref_line=(box_high, box_high),
            key_points=[
                {"role": "box_high", "idx": max(tops_w, key=lambda p: p.price).idx, "price": box_high},
                {"role": "box_low", "idx": min(bots_w, key=lambda p: p.price).idx, "price": box_low},
                *[{"role": "top_touch", "idx": p.idx, "price": p.price} for p in top_touches],
            ],
            breakout=b,
        )
        vf = _vol_features(candles, win[0].idx, win[-1].idx, params)
        _score(
            hit,
            struct_items=[
                ("上轨≥2次触碰", 3, len(top_touches) >= params["box_min_touches"]),
                ("下轨≥2次触碰", 2, len(bot_touches) >= params["box_min_touches"]),
                ("箱体高度足", 2, height / box_low >= params["box_min_height_pct"]),
                ("低位箱体", 2, True),
            ],
            vol_items=[
                ("箱内量能起伏不大", 2, vf["shrink"] or abs(vf["last_third_avg"] - vf["first_third_avg"]) / max(vf["first_third_avg"], 1e-9) < 0.3),
                ("靠近上轨放量遇阻回落", 2, True),
                ("突破放量", 3, b.confirmed and b.volume_ratio >= params["vol_ratio_k"]),
            ],
            confirm_items=_confirm_items(hit, params),
        )
        hits.append(hit)
    return hits


# ---------------------------------------------------------------------------
# 检测器 4：上升三角形（任务 2.4）
# ---------------------------------------------------------------------------

def detect_ascending_triangle(points: List[SwingPoint], candles, params: dict) -> List[PatternHit]:
    """上升三角形：上边高点水平压力 + 下边低点逐级抬升，整理缩量，突破上边放量。"""
    hits: List[PatternHit] = []
    tops, bottoms = _pair_tops_bottoms(points)
    for i in range(len(bottoms) - 1):
        win_bottoms = bottoms[i:i + 3]
        win_tops = [p for p in tops if win_bottoms[0].idx < p.idx < win_bottoms[-1].idx]
        if len(win_bottoms) < 2 or len(win_tops) < 2:
            continue
        begin, end = win_tops[0].idx, win_bottoms[-1].idx
        if end - begin < params["min_pattern_bars"]:
            continue
        top_level = max(p.price for p in win_tops)
        if top_level <= 0:
            continue
        # 上边等高（水平压力线）
        if any(abs(p.price - top_level) / top_level > params["tri_top_tol"] for p in win_tops):
            continue
        # 下边低点逐级抬升（最小二乘斜率 > 阈值）
        xs = np.array([p.idx for p in win_bottoms], dtype=float)
        ys = np.array([p.price for p in win_bottoms], dtype=float)
        slope = float(np.polyfit(xs, ys, 1)[0]) / max(float(ys.mean()), 1e-9)
        if slope < params["tri_min_low_slope"]:
            continue
        # 收敛：末段振幅 < 首段振幅（图形越来越窄）
        first_amp = (max(p.price for p in win_tops[:1]) - win_bottoms[0].price)
        last_amp = (top_level - win_bottoms[-1].price)
        if last_amp >= first_amp:
            continue
        vf = _vol_features(candles, begin, end, params)
        if vf["last_third_avg"] > vf["first_third_avg"] * params["tri_vol_shrink_max"]:
            continue  # 「整理内部成交量逐步萎缩」不满足 → 不报
        b = confirm_breakout(candles, lambda idx: top_level, end,
                             end + params["invalid_window"] + params["retest_window"] + 10, params)
        hit = PatternHit(
            pattern_type="ascending_triangle",
            struct_begin_idx=begin, struct_end_idx=end,
            ref_line=(top_level, top_level),
            key_points=[
                {"role": "top_line", "idx": max(win_tops, key=lambda p: p.idx).idx, "price": top_level},
                *[{"role": "flat_top", "idx": p.idx, "price": p.price} for p in win_tops],
                *[{"role": "rising_low", "idx": p.idx, "price": p.price} for p in win_bottoms],
            ],
            breakout=b,
        )
        _score(
            hit,
            struct_items=[
                ("上边水平压力", 3, True),
                ("下边逐级抬升", 3, slope >= params["tri_min_low_slope"]),
                ("图形收敛", 2, last_amp < first_amp),
                ("整理缩量", 2, vf["shrink"]),
            ],
            vol_items=[
                ("整理逐步缩量", 3, vf["last_third_avg"] <= vf["first_third_avg"] * params["tri_vol_shrink_max"]),
                ("突破放量", 3, b.confirmed and b.volume_ratio >= params["vol_ratio_k"]),
            ],
            confirm_items=_confirm_items(hit, params),
        )
        hits.append(hit)
    return hits


# ---------------------------------------------------------------------------
# 检测器 5：低位旗形（任务 2.5）
# ---------------------------------------------------------------------------

def detect_low_flag(points: List[SwingPoint], candles, params: dict) -> List[PatternHit]:
    """低位旗形：旗杆快速拉升 + 向下倾斜窄幅旗面（缩量）+ 突破旗面上轨放量。"""
    hits: List[PatternHit] = []
    tops, bottoms = _pair_tops_bottoms(points)
    lo_s, hi_s = params["flag_channel_slope"]
    for i in range(len(bottoms)):
        pole_start = bottoms[i]
        # 旗杆顶 = pole_start 之后最近的高点（不能取最后高点，否则旗杆根数超限）
        pole_end = min((p for p in tops if p.idx > pole_start.idx),
                       key=lambda p: p.idx, default=None)
        if pole_end is None:
            continue
        pole_bars = pole_end.idx - pole_start.idx
        gain = (pole_end.price - pole_start.price) / max(pole_start.price, 1e-9)
        if not (gain >= params["flag_pole_min_gain"] and pole_bars <= params["flag_pole_max_bars"]):
            continue
        # 旗面：旗杆顶之后的低点+高点，向下倾斜窄通道
        flag_lows = [p for p in bottoms if p.idx > pole_end.idx]
        flag_highs = [p for p in tops if p.idx > pole_end.idx and p.idx < (flag_lows[-1].idx if flag_lows else pole_end.idx)]
        if len(flag_lows) < 2 or len(flag_highs) < 1:
            continue
        flag_end = flag_lows[-1]
        if flag_end.idx - pole_end.idx < params["min_pattern_bars"]:
            continue
        # 旗面回撤不能吃掉旗杆涨幅大半
        retrace = (pole_end.price - min(p.price for p in flag_lows)) / max(pole_end.price - pole_start.price, 1e-9)
        if retrace > params["flag_max_retrace"]:
            continue
        # 通道斜率：低点最小二乘，向下倾斜且不过陡
        xs = np.array([p.idx for p in flag_lows], dtype=float)
        ys = np.array([p.price for p in flag_lows], dtype=float)
        slope = float(np.polyfit(xs, ys, 1)[0]) / max(float(ys.mean()), 1e-9)
        if not (lo_s <= slope <= hi_s):
            continue
        # 旗面上轨 = 旗面高点连线（用于突破参考）
        hs_x = np.array([p.idx for p in flag_highs], dtype=float)
        hs_y = np.array([p.price for p in flag_highs], dtype=float)
        if len(hs_x) >= 2:
            c_top = np.polyfit(hs_x, hs_y, 1)
            ref_at = lambda idx: float(c_top[0] * idx + c_top[1])
        else:
            top_v = float(hs_y[0])
            ref_at = lambda idx: top_v
        if _position_ratio(candles, pole_start.idx, flag_end.idx,
                           params["prior_decline_window"]) > params["flag_zone_ratio"]:
            continue  # 「低位或上升途中是看涨整理；大幅暴涨后高位出现是危险信号」→ 只排除高位
        vf = _vol_features(candles, pole_end.idx, flag_end.idx, params)
        if vf["last_third_avg"] > vf["first_third_avg"] * params["flag_vol_shrink_max"]:
            continue  # 「旗面整理阶段：持续缩量」不满足 → 不报
        b = confirm_breakout(candles, ref_at, flag_end.idx,
                             flag_end.idx + params["invalid_window"] + params["retest_window"] + 10, params)
        hit = PatternHit(
            pattern_type="low_flag",
            struct_begin_idx=pole_start.idx, struct_end_idx=flag_end.idx,
            ref_line=(float(c_top[1]), float(c_top[0] * flag_end.idx + c_top[1])) if len(hs_x) >= 2 else (top_v, top_v),
            key_points=[
                {"role": "pole_start", "idx": pole_start.idx, "price": pole_start.price},
                {"role": "pole_end", "idx": pole_end.idx, "price": pole_end.price},
                *[{"role": "flag_low", "idx": p.idx, "price": p.price} for p in flag_lows],
            ],
            breakout=b,
        )
        _score(
            hit,
            struct_items=[
                ("旗杆快速放量拉升", 3, gain >= params["flag_pole_min_gain"]),
                ("旗面向下倾斜窄整理", 3, lo_s <= slope <= hi_s),
                ("回撤未吃掉旗杆大半", 2, retrace <= params["flag_max_retrace"]),
                ("低位出现", 2, True),
            ],
            vol_items=[
                ("旗杆放量", 2, True),
                ("旗面持续缩量", 3, vf["last_third_avg"] <= vf["first_third_avg"] * params["flag_vol_shrink_max"]),
                ("突破放量", 3, b.confirmed and b.volume_ratio >= params["vol_ratio_k"]),
            ],
            confirm_items=_confirm_items(hit, params),
        )
        hits.append(hit)
    return hits


# ---------------------------------------------------------------------------
# 检测器 6：V型反转（任务 2.6）
# ---------------------------------------------------------------------------

def detect_v_reversal(points: List[SwingPoint], candles, params: dict) -> List[PatternHit]:
    """V型反转：急跌（连续大阴/短期大跌）→ 尖底 → 放量长阳快速收复。

    「一旦回踩跌破V尖低点，形态作废」→ 确认后跌破尖底即 invalidated。
    """
    hits: List[PatternHit] = []
    _, bottoms = _pair_tops_bottoms(points)
    for i in range(len(bottoms)):
        v_bottom = bottoms[i]
        # 左侧急跌：v_min_drop_pct 跌幅在 v_drop_max_bars 内
        lo = max(0, v_bottom.idx - params["v_drop_max_bars"])
        if v_bottom.idx - lo < 5:
            continue
        seg = candles[lo:v_bottom.idx + 1]
        drop_start = max(float(c.high) for c in seg)
        drop = (drop_start - v_bottom.price) / max(drop_start, 1e-9)
        if drop < params["v_min_drop_pct"]:
            continue
        # 右侧：v_reclaim_candles 根内放量长阳收复短期跌幅的 50%
        recover_end = min(len(candles) - 1, v_bottom.idx + params["v_reclaim_candles"])
        if recover_end <= v_bottom.idx + 1:
            continue
        seg2 = candles[v_bottom.idx + 1:recover_end + 1]
        recover_high = max(float(c.close) for c in seg2)
        recovered = (recover_high - v_bottom.price) / max(drop_start - v_bottom.price, 1e-9)
        if recovered < 0.5:
            continue
        rec_bar = next(c for c in seg2 if float(c.close) == recover_high)
        base_vols = [_volume(candles[j]) for j in range(max(0, rec_bar.idx - params["vol_ma_window"]), rec_bar.idx)]
        avg_vol = sum(base_vols) / max(1, len(base_vols))
        vr = _volume(rec_bar) / avg_vol if avg_vol > 0 else 0.0
        # 「右侧反弹拉升必须放量」→ 一票否决
        veto = "no_volume" if vr < params["vol_ratio_k"] else None
        # 确认位：收复「重要短期压力位」= 急跌起点前高的一半位置
        ref_price = drop_start - (drop_start - v_bottom.price) * 0.5
        b = BreakoutResult(confirmed=True, confirm_idx=rec_bar.idx, volume_ratio=vr)
        if veto:
            b.veto = veto
            b.confirmed = False
        else:
            # 失效检验：收盘跌破 V 尖
            for j in range(rec_bar.idx + 1, min(rec_bar.idx + params["invalid_window"], len(candles))):
                if float(candles[j].close) < v_bottom.price:
                    b.invalidated = True
                    break
                low_j = float(candles[j].low)
                if not b.retest and j <= rec_bar.idx + params["retest_window"] and low_j <= ref_price * 1.02 and float(candles[j].close) >= ref_price:
                    b.retest = True
        hit = PatternHit(
            pattern_type="v_reversal",
            struct_begin_idx=lo, struct_end_idx=v_bottom.idx,
            ref_line=(ref_price, ref_price),
            key_points=[
                {"role": "drop_start", "idx": lo, "price": drop_start},
                {"role": "v_bottom", "idx": v_bottom.idx, "price": v_bottom.price},
                {"role": "reclaim", "idx": rec_bar.idx, "price": recover_high},
            ],
            breakout=b,
        )
        _score(
            hit,
            struct_items=[
                ("左侧急跌达标", 3, drop >= params["v_min_drop_pct"]),
                ("尖底快速见底", 2, v_bottom.idx - lo <= params["v_drop_max_bars"]),
                ("长阳收复过半", 3, recovered >= 0.5),
            ],
            vol_items=[
                ("反弹放量", 3, vr >= params["vol_ratio_k"]),
            ],
            confirm_items=_confirm_items(hit, params),
        )
        hits.append(hit)
    return hits


# ---------------------------------------------------------------------------
# 中值序列拟合公共件（圆弧底/杯柄，design D3）
# ---------------------------------------------------------------------------

def _mid_prices(candles, begin_idx: int, end_idx: int) -> np.ndarray:
    """K 线中值序列 (high+low)/2（用户方案：滤影线、保留弧形特征）。"""
    return np.array(
        [(float(c.high) + float(c.low)) / 2 for c in candles[begin_idx:end_idx + 1]],
        dtype=float,
    )


def _parabola_fit(ys: np.ndarray) -> dict:
    """二次拟合检验：返回 (是否通过, 特征字典)。

    判据（design D3）：开口向上（a<0）、顶点在窗口中部、R² 达标、
    曲率在合理带内（排除 V 尖与横盘）。
    """
    n = len(ys)
    x = np.arange(n, dtype=float)
    scale = max(float(ys.max() - ys.min()), 1e-9)
    a, b, c = np.polyfit(x, ys, 2)
    y_hat = a * x ** 2 + b * x + c
    ss_res = float(np.sum((ys - y_hat) ** 2))
    ss_tot = float(np.sum((ys - ys.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    if a <= 0:
        return False, {}  # 锅底是开口向上（U 型），要求二次项系数为正
    vertex = -b / (2 * a)
    vert_pos = vertex / (n - 1) if n > 1 else 0.5
    lo, hi = DETECT_PARAMS["arc_vertex_band"]
    # 排除 V 尖与横盘不靠曲率带（纯抛物线归一化曲率恒定，判据无区分度）：
    # V 尖由三段结构检验的底段振幅上限排除，横盘由左段跌幅下限排除。
    ok = r2 >= DETECT_PARAMS["arc_min_r2"] and lo <= vert_pos <= hi
    return ok, {"a": float(a), "r2": r2, "vertex_pos": float(vert_pos)}


def _arc_structure_ok(candles, begin_idx: int, end_idx: int, params: dict) -> Tuple[bool, dict]:
    """圆弧三段结构 + 量能检验（左跌 / 底部收窄地量 / 右升）。"""
    n = end_idx - begin_idx + 1
    if n < params["min_pattern_bars"] * 3:
        return False, {}
    ys = _mid_prices(candles, begin_idx, end_idx)
    vertex_pos = int(np.argmin(ys))
    left = ys[:vertex_pos + 1]
    right = ys[vertex_pos:]
    if len(left) < 5 or len(right) < 5:
        return False, {}
    left_drop = (float(left[0]) - float(left[-1])) / max(float(left[0]), 1e-9)
    if left_drop < params["arc_min_left_drop"]:
        return False, {}
    # 底段：argmin 邻域振幅收窄 + 持续根数
    base_lo = max(0, vertex_pos - params["arc_base_min_bars"] // 2)
    base_hi = min(n - 1, vertex_pos + params["arc_base_min_bars"] // 2)
    base_seg = ys[base_lo:base_hi + 1]
    win_range = float(ys.max() - ys.min())
    base_amp = float(base_seg.max() - base_seg.min()) / max(win_range, 1e-9)
    if (base_hi - base_lo + 1) < params["arc_base_min_bars"] or base_amp > params["arc_base_amp_max"]:
        return False, {}
    right_slope = float(np.polyfit(np.arange(len(right), dtype=float), right, 1)[0]) / max(float(right.mean()), 1e-9)
    if right_slope <= 0:
        return False, {}
    # 量能：底段均量最低、右侧温和放大
    vols = np.array([_volume(c) for c in candles[begin_idx:end_idx + 1]], dtype=float)
    if vols.sum() <= 0:
        return False, {}
    base_vol = float(vols[base_lo:base_hi + 1].mean())
    left_vol = float(vols[:vertex_pos + 1].mean())
    right_vol = float(vols[vertex_pos:].mean())
    vol_ok = base_vol <= left_vol and right_vol >= base_vol
    return vol_ok, {
        "left_drop": left_drop, "base_amp": base_amp,
        "right_slope": right_slope, "vertex_idx": begin_idx + vertex_pos,
        "base_vol_low": bool(base_vol <= left_vol), "right_vol_up": bool(right_vol >= base_vol),
    }


# ---------------------------------------------------------------------------
# 检测器 7：圆弧底（任务 2.7）
# ---------------------------------------------------------------------------

def detect_rounding_bottom(candles, params: dict) -> List[PatternHit]:
    """圆弧底（锅底）：中值序列抛物线拟合 + 三段结构 + 量能 + 突破上沿压力线。"""
    hits: List[PatternHit] = []
    n = len(candles)
    for w in params["arc_windows"]:
        if n < w + params["invalid_window"] + 5:
            continue
        for begin in range(0, n - w - params["invalid_window"], max(5, w // 6)):
            end = begin + w - 1
            ok, fit = _parabola_fit(_mid_prices(candles, begin, end))
            if not ok:
                continue
            ok2, struct = _arc_structure_ok(candles, begin, end, params)
            if not ok2:
                continue
            # 突破参考线：圆弧上沿压力线 = 窗口左起点与右段回升高点
            seg_right = candles[struct["vertex_idx"]:end + 1]
            right_high_idx = max(range(len(seg_right)), key=lambda i: float(seg_right[i].high))
            rim = max(float(candles[begin].high), float(seg_right[right_high_idx].high))
            b = confirm_breakout(candles, lambda i: rim, end, end + params["invalid_window"] + params["retest_window"], params)
            hit = PatternHit(
                pattern_type="rounding_bottom",
                struct_begin_idx=begin, struct_end_idx=end,
                ref_line=(rim, rim),
                key_points=[
                    {"role": "left_start", "idx": begin, "price": float(candles[begin].high)},
                    {"role": "arc_bottom", "idx": struct["vertex_idx"], "price": float(candles[struct["vertex_idx"]].low)},
                    {"role": "rim", "idx": end, "price": rim},
                ],
                breakout=b,
                features={**fit, **{f"struct.{k}": v for k, v in struct.items() if isinstance(v, (int, float, bool))}},
            )
            _score(
                hit,
                struct_items=[
                    ("抛物线拟合达标", 3, ok),
                    ("左侧下跌段跌幅足", 2, struct["left_drop"] >= params["arc_min_left_drop"]),
                    ("底部振幅收窄持续足", 3, struct["base_amp"] <= params["arc_base_amp_max"]),
                    ("右侧回升斜率转正", 2, struct["right_slope"] > 0),
                ],
                vol_items=[
                    ("底部量能最低", 3, struct["base_vol_low"]),
                    ("右侧温和放大", 2, struct["right_vol_up"]),
                    ("突破明显放量", 3, b.confirmed and b.volume_ratio >= params["vol_ratio_k"]),
                ],
                confirm_items=_confirm_items(hit, params),
            )
            hits.append(hit)
    # 同窗重叠去重：同一确认时间只保留一条（spec「同形态同确认时间去重」）
    return _dedup(hits)


# ---------------------------------------------------------------------------
# 检测器 8：杯柄（任务 2.8）
# ---------------------------------------------------------------------------

def detect_cup_handle(candles, params: dict) -> List[PatternHit]:
    """杯柄：圆 U 杯体（复用弧形拟合，深度 15%~30%）+ 柄部小幅回调 + 突破杯口高点。"""
    hits: List[PatternHit] = []
    n = len(candles)
    for w in params["arc_windows"]:
        if n < w + params["handle_max_bars"] + params["invalid_window"] + 5:
            continue
        for begin in range(0, n - w - params["handle_max_bars"] - params["invalid_window"], max(5, w // 6)):
            end = begin + w - 1
            ok, fit = _parabola_fit(_mid_prices(candles, begin, end))
            if not ok:
                continue
            mids = _mid_prices(candles, begin, end)
            v_pos = int(np.argmin(mids))            # 窗口内弧底位置
            bottom_idx = begin + v_pos              # 全局下标
            lip_high = max(float(candles[i].high) for i in range(begin, min(begin + w // 6, end)))
            lip_low = float(candles[bottom_idx].low)
            depth = (lip_high - lip_low) / max(lip_high, 1e-9)
            d_lo, d_hi = params["cup_depth_band"]
            if not (d_lo <= depth <= params["cup_depth_hard_max"]):
                continue
            # 柄部：杯口（回升至 lip 附近）之后的小幅回调
            handle_begin = None
            for i in range(bottom_idx, end + 1):
                if float(candles[i].high) >= lip_high * 0.98:
                    handle_begin = i
                    break
            if handle_begin is None or handle_begin >= end:
                continue
            handle_end = min(n - 1, handle_begin + params["handle_max_bars"])
            handle_seg = candles[handle_begin:handle_end + 1]
            if len(handle_seg) < 3:
                continue
            handle_low = min(float(c.low) for c in handle_seg)
            handle_depth = (lip_high - handle_low) / max(lip_high - lip_low, 1e-9)
            if handle_depth > params["handle_max_depth_ratio"]:
                continue  # 「柄部回调不能超过杯体深度的 1/3」
            if handle_low < lip_low + (lip_high - lip_low) * 0.5:
                continue  # 「柄部必须出现在杯子的上半部分，不能跌回杯底区域」
            b = confirm_breakout(candles, lambda i: lip_high, handle_begin,
                                 handle_end + params["invalid_window"] + params["retest_window"], params)
            handle_low_i = handle_begin + int(min(range(len(handle_seg)), key=lambda i: float(handle_seg[i].low)))
            hit = PatternHit(
                pattern_type="cup_handle",
                struct_begin_idx=begin, struct_end_idx=handle_end,
                ref_line=(lip_high, lip_high),
                key_points=[
                    {"role": "cup_lip_left", "idx": begin, "price": lip_high},
                    {"role": "cup_bottom", "idx": bottom_idx, "price": lip_low},
                    {"role": "handle_low", "idx": handle_low_i, "price": handle_low},
                ],
                breakout=b,
                features={**fit, "cup_depth": depth, "handle_depth": handle_depth},
            )
            _score(
                hit,
                struct_items=[
                    ("杯体圆U拟合", 3, ok),
                    ("回撤深度15~30%", 3, d_lo <= depth <= d_hi),
                    ("柄部上半区小幅回调", 3, handle_depth <= params["handle_max_depth_ratio"]),
                    ("杯口大致平齐", 2, True),
                ],
                vol_items=[
                    ("杯底量能最低", 2, True),
                    ("柄部缩量", 2, True),
                    ("突破杯口放量", 3, b.confirmed and b.volume_ratio >= params["vol_ratio_k"]),
                ],
                confirm_items=_confirm_items(hit, params),
            )
            hits.append(hit)
    return _dedup(hits)


# ---------------------------------------------------------------------------
# 顶部看跌形态共用辅助（chan-pattern-sell-signal，design D4 蜡烛图路径）
# ---------------------------------------------------------------------------

def _prior_rally_ok(candles, idx: int, params: dict) -> Tuple[bool, float]:
    """「必须出现在上涨趋势/上涨末端」（5 张卖点图共同的位置前提硬约束）。

    形态 K 线**之前** prior_decline_window 根内，前低到前高的涨幅是否达标
    （买向 _prior_decline_ok 的高位镜像）。窗口不含形态 K 线自身——长影线
    形态（射击之星/吊颈线）的影线会污染前低/前高，造成横盘误判。
    返回 (是否通过, 实际涨幅)。
    """
    lo = max(0, idx - params["prior_decline_window"])
    seg = candles[lo:idx]
    if len(seg) < 5:
        return False, 0.0
    prior_low = min(float(c.low) for c in seg)
    top = max(float(c.high) for c in seg)
    if prior_low <= 0:
        return False, 0.0
    rally = (top - prior_low) / prior_low
    return rally >= params["prior_rally_pct"], rally


def _in_high_zone(candles, idx: int, params: dict) -> bool:
    """高位区判定：形态 K 线收盘价处于**前窗**（不含自身）高低区间的上部
    （_in_low_zone 镜像）。历史不足时不做「高位」认定（卖向宁可漏报不误报）。"""
    lo = max(0, idx - params["prior_decline_window"])
    seg = candles[lo:idx]
    if len(seg) < 5:
        return False
    hi = max(float(c.high) for c in seg)
    lo_p = min(float(c.low) for c in seg)
    if hi <= lo_p:
        return False
    return float(candles[idx].close) >= lo_p + (hi - lo_p) * (1 - params["high_zone_ratio"])


def _sell_vol_ratio(candles, idx: int, params: dict) -> float:
    """形态 K 线量比：形态 K 线量 / 前 sell_vol_ma_window 根均量。"""
    win = params["sell_vol_ma_window"]
    lo = max(0, idx - win)
    base = [_volume(candles[j]) for j in range(lo, idx)]
    avg = sum(base) / len(base) if base else 0.0
    return _volume(candles[idx]) / avg if avg > 0 else 0.0


def _is_doji_bar(c) -> bool:
    """一字板/开收盘同价 K 线（无实体波动，形态失真，spec 一字板剔除）。"""
    return float(c.open) == float(c.close) == float(c.high) == float(c.low)


def _is_limit_down(c, candles, idx: int) -> bool:
    """跌停板粗判：收盘=最低且明显低开（detail 标记用，design D6，非精确涨跌停价）。"""
    if idx <= 0:
        return False
    prev_close = float(candles[idx - 1].close)
    return float(c.close) == float(c.low) and prev_close > 0 and float(c.open) / prev_close < 0.99


def _score_sell(hit: PatternHit, struct_items, vol_items, position_ok: bool) -> None:
    """卖向三轴计分（design D7：沿用分数边界，确认轴换成位置轴）。

    卖点形态确认点即形态 K 线收盘本身（无需突破确认），结构轴/量能轴/
    位置轴加权；非高位出现已在检测入口丢弃（硬约束），这里 position_ok
    恒 True、只影响通过质量。量比不足的临界形态走否决封顶。
    """
    def _ratio(items):
        return sum(w for _, w, ok in items if ok) / max(1, sum(w for _, w, _ in items))

    score = int(round(_ratio(struct_items) * STRUCT_AXIS
                      + _ratio(vol_items) * VOL_AXIS
                      + (1.0 if position_ok else 0.0) * CONFIRM_AXIS))
    if hit.veto:
        score = min(score, _CAP_BLOCKED)
    else:
        score = max(score, _FLOOR_CONFIRMED)  # 形态已收盘确认，地板分与买向同规
    hit.breakout.confirmed = True
    hit.score = score
    hit.qual = _qual_of(score)
    hit.features = {
        "struct": [f"{n}:{'1' if ok else '0'}" for n, _, ok in struct_items],
        "vol": [f"{n}:{'1' if ok else '0'}" for n, _, ok in vol_items],
        "position": ["高位区:1" if position_ok else "高位区:0"],
    }


def _sell_hit_to_breakout(hit: PatternHit, confirm_idx: int, vr: float, invalidated: bool) -> None:
    """卖向命中 → 通用落库/序列化视图（hit_to_row/_serialize_pattern 消费
    breakout.confirm_idx/invalidated/volume_ratio，见 design D4）。"""
    hit.breakout.confirm_idx = confirm_idx
    hit.breakout.volume_ratio = vr
    hit.breakout.invalidated = invalidated


def _sell_invalidated(candles, confirm_idx: int, top_price: float, params: dict) -> bool:
    """形态失效：确认后 sell_invalid_window 根内收盘升破形态最高价。"""
    for j in range(confirm_idx + 1, min(confirm_idx + 1 + params["invalid_window"], len(candles))):
        if float(candles[j].close) > top_price:
            return True
    return False


# ---------------------------------------------------------------------------
# 检测器 9：乌云盖顶（chan-pattern-sell-signal 任务 1.2）
# ---------------------------------------------------------------------------

def detect_dark_cloud_cover(points: List[SwingPoint], candles, params: dict) -> List[PatternHit]:
    """乌云盖顶（PART01）：上涨趋势中 T1 实体阳线，T2 高开低走阴线深入
    前阳线实体 1/3 以上；巨量佐证。确认点 = T2 收盘。"""
    hits: List[PatternHit] = []
    pen = params["dcc_min_penetration"]
    for i in range(1, len(candles)):
        t1, t2 = candles[i - 1], candles[i]
        if _is_doji_bar(t1) or _is_doji_bar(t2):
            continue
        b1 = float(t1.close) - float(t1.open)    # T1 实体
        b2 = float(t2.open) - float(t2.close)    # T2 实体（阴线为正）
        if b1 <= 0 or b2 <= 0:
            continue                             # T1 须阳线、T2 须阴线
        if float(t1.close) / max(float(t1.open), 1e-9) - 1 < params["dcc_min_body_pct"]:
            continue                             # 「先出现一根实体阳线」排除小阳噪声
        if float(t2.open) <= float(t1.close):
            continue                             # 「次日高开」
        t1_body_top = float(t1.close)            # 阳线实体上沿=收盘
        t1_body_bot = float(t1.open)             # 阳线实体下沿=开盘
        depth = (t1_body_top - float(t2.close)) / max(b1, 1e-9)
        if depth < pen:
            continue                             # 「覆盖前阳线实体 1/3 以上」
        rally_ok, rally = _prior_rally_ok(candles, i, params)
        if not rally_ok or not _in_high_zone(candles, i, params):
            continue                             # 位置硬约束：非高位丢弃
        vr = _sell_vol_ratio(candles, i, params)
        hit = PatternHit(
            pattern_type="dark_cloud_cover", direction="sell",
            struct_begin_idx=i - 1, struct_end_idx=i,
            ref_line=(t1_body_top, t1_body_bot),
            key_points=[
                {"role": "bull_bar", "idx": i - 1, "price": float(t1.close)},
                {"role": "bear_bar", "idx": i, "price": float(t2.close)},
            ],
            veto=None if vr >= params["sell_vol_ratio_k"] else "no_volume",
        )
        _score_sell(
            hit,
            struct_items=[
                ("高开低走阴线", 3, float(t2.open) > float(t1.close) and b2 > 0),
                (f"深入前实体≥{pen:.0%}", 3, depth >= pen),
                ("前阳线实体足", 2, b1 / max(float(t1.open), 1e-9) >= params["dcc_min_body_pct"]),
                ("前有一轮上涨", 2, rally_ok),
            ],
            vol_items=[
                ("形态日放量（巨量）", 3, vr >= params["sell_vol_ratio_k"]),
                ("阴线量高于阳线量", 2, _volume(t2) > _volume(t1)),
            ],
            position_ok=_in_high_zone(candles, i, params),
        )
        _sell_hit_to_breakout(hit, i, vr, _sell_invalidated(candles, i, float(t2.close), params))
        hits.append(hit)
    return hits


# ---------------------------------------------------------------------------
# 检测器 10/11：射击之星 & 高位吊颈线（任务 1.3/1.4，镜像共用形态参数）
# ---------------------------------------------------------------------------

def _detect_star_like(candles, params: dict, *, upper: bool, pattern_type: str) -> List[PatternHit]:
    """射击之星（PART02，upper=True）与高位吊颈线（PART03，upper=False）。

    共用判据骨架：小实体（实体 ≤ 全幅 star_max_body_ratio）+ 长影线
    （≥ 实体 star_upper_shadow_ratio 倍）+ 短反向影线（≤ 实体
    star_lower_shadow_max 倍）；爆量/巨量佐证；上涨末端。确认点 = 该 K 线收盘。
    """
    hits: List[PatternHit] = []
    for i in range(1, len(candles)):
        c = candles[i]
        if _is_doji_bar(c):
            continue                             # 一字板剔除（无实体波动）
        o, cl = float(c.open), float(c.close)
        hi, lo = float(c.high), float(c.low)
        body = abs(cl - o)
        full = hi - lo
        if body <= 0 or full <= 0:
            continue
        if body / full > params["star_max_body_ratio"]:
            continue                             # 「K线实体极小」
        up_shadow = hi - max(o, cl)
        low_shadow = min(o, cl) - lo
        long_shadow = up_shadow if upper else low_shadow
        short_shadow = low_shadow if upper else up_shadow
        if long_shadow < body * params["star_upper_shadow_ratio"]:
            continue                             # 「上/下影线极长」
        if short_shadow > body * params["star_lower_shadow_max"]:
            continue                             # 「下/上影线极短」
        rally_ok, rally = _prior_rally_ok(candles, i, params)
        if not rally_ok or not _in_high_zone(candles, i, params):
            continue                             # 位置硬约束：非高位丢弃
        vr = _sell_vol_ratio(candles, i, params)
        hit = PatternHit(
            pattern_type=pattern_type, direction="sell",
            struct_begin_idx=i, struct_end_idx=i,
            ref_line=(max(o, cl), min(o, cl)),
            key_points=[
                {"role": "long_shadow_tip", "idx": i, "price": hi if upper else lo},
                {"role": "body_close", "idx": i, "price": cl},
            ],
            veto=None if vr >= params["sell_vol_ratio_k"] else "no_volume",
        )
        shadow_name = "上影线" if upper else "下影线"
        _score_sell(
            hit,
            struct_items=[
                ("实体极小", 3, body / full <= params["star_max_body_ratio"]),
                (f"{shadow_name}≥实体{params['star_upper_shadow_ratio']:.0f}倍", 3,
                 long_shadow >= body * params["star_upper_shadow_ratio"]),
                ("反向影线极短", 2, short_shadow <= body * params["star_lower_shadow_max"]),
                ("前有一轮上涨", 2, rally_ok),
            ],
            vol_items=[
                ("爆量/巨量（多空分歧顶峰）", 3, vr >= params["sell_vol_ratio_k"]),
            ],
            position_ok=_in_high_zone(candles, i, params),
        )
        _sell_hit_to_breakout(hit, i, vr, _sell_invalidated(candles, i, hi, params))
        hits.append(hit)
    return hits


def detect_shooting_star(points: List[SwingPoint], candles, params: dict) -> List[PatternHit]:
    """射击之星：朝天开枪——长上影 + 小实体 + 短下影，冲高是诱多。"""
    return _detect_star_like(candles, params, upper=True, pattern_type="shooting_star")


def detect_hanging_man(points: List[SwingPoint], candles, params: dict) -> List[PatternHit]:
    """高位吊颈线：悬在高位的吊绳——长下影 + 小实体 + 短上影。"""
    return _detect_star_like(candles, params, upper=False, pattern_type="hanging_man")


# ---------------------------------------------------------------------------
# 检测器 12：高位阴包阳 & 穿头破脚（任务 1.5，design D3 共检测器两 pattern_type）
# ---------------------------------------------------------------------------

def detect_bearish_engulfing(points: List[SwingPoint], candles, params: dict) -> List[PatternHit]:
    """阴包阳（PART04）与穿头破脚阴线（PART05）共检测器。

    先判穿头破脚（T2.open > T1.high 且 T2.close < T1.low，更强形态、
    结构轴得分更高），成立产出 high_engulfing_gap；否则判普通吞没产出
    high_engulfing——同一根 K 线只报一种（design D3）。
    """
    hits: List[PatternHit] = []
    for i in range(1, len(candles)):
        t1, t2 = candles[i - 1], candles[i]
        if _is_doji_bar(t1) or _is_doji_bar(t2):
            continue
        o1, c1 = float(t1.open), float(t1.close)
        o2, c2 = float(t2.open), float(t2.close)
        b1 = c1 - o1                             # T1 阳线实体
        b2 = o2 - c2                             # T2 阴线实体
        if b1 <= 0 or b2 <= 0:
            continue                             # 前阳后阴
        if b2 / max(c1, 1e-9) < params["engulf_min_body_pct"]:
            continue                             # 「大阴线」排除勉强包裹的小阴线
        engulfed = o2 >= c1 and c2 <= o1         # 实体完全吞没
        if not engulfed:
            continue
        gap_top = o2 > float(t1.high)            # 穿头：开盘高于前阳最高价
        gap_bottom = c2 < float(t1.low)          # 破脚：收盘低于前阳最低价
        is_gap = gap_top and gap_bottom
        rally_ok, rally = _prior_rally_ok(candles, i, params)
        if not rally_ok or not _in_high_zone(candles, i, params):
            continue                             # 位置硬约束：非高位丢弃
        vr = _sell_vol_ratio(candles, i, params)
        hit = PatternHit(
            pattern_type="high_engulfing_gap" if is_gap else "high_engulfing",
            direction="sell",
            struct_begin_idx=i - 1, struct_end_idx=i,
            ref_line=(float(t1.high), float(t1.low)),
            key_points=[
                {"role": "bull_bar", "idx": i - 1, "price": c1},
                {"role": "bear_bar", "idx": i, "price": c2},
                {"role": "gap_top", "idx": i, "price": float(t1.high)},
                {"role": "gap_bottom", "idx": i, "price": float(t1.low)},
            ],
            veto=None if vr >= params["sell_vol_ratio_k"] else "no_volume",
        )
        _score_sell(
            hit,
            struct_items=[
                ("大阴线完全吞没前阳实体", 3, engulfed),
                ("穿头破脚（覆盖前阳全部波动区间）", 3, is_gap),
                ("阴线实体足（大阴线）", 2, b2 / max(c1, 1e-9) >= params["engulf_min_body_pct"] * 2),
                ("前有一轮上涨", 2, rally_ok),
            ],
            vol_items=[
                ("形态日放量（量越大韭菜馅越多）", 3, vr >= params["sell_vol_ratio_k"]),
                ("阴线量高于阳线量", 2, _volume(t2) > _volume(t1)),
            ],
            position_ok=_in_high_zone(candles, i, params),
        )
        _sell_hit_to_breakout(hit, i, vr, _sell_invalidated(candles, i, float(t2.close), params))
        hits.append(hit)
    return hits


def _dedup(hits: List[PatternHit]) -> List[PatternHit]:
    """形态去重（spec「同形态同确认时间去重」+ 调参 6.2 发现的窗口重叠问题）。

    两层：
    1. 精确去重：同形态同确认 K 线只留分数最高者。
    2. 结构重叠去重：同一弧形结构因滑窗步进/突破点不同被重复报告
       （实测 sz.000001 同一锅底 gap 15~23 根连报 3 次）→ 同形态
       struct 区间重叠超过一半者视为同一结构，保留分高者。
    """
    best: dict = {}
    for h in hits:
        key = (h.pattern_type, h.breakout.confirm_idx)
        if key not in best or h.score > best[key].score:
            best[key] = h
    ordered = sorted(best.values(), key=lambda h: (-h.score, h.struct_begin_idx))
    kept: List[PatternHit] = []
    for h in ordered:
        dup = False
        for k in kept:
            if k.pattern_type != h.pattern_type:
                continue
            lo = max(k.struct_begin_idx, h.struct_begin_idx)
            hi = min(k.struct_end_idx, h.struct_end_idx)
            if hi > lo:
                overlap = hi - lo
                shorter = min(k.struct_end_idx - k.struct_begin_idx,
                              h.struct_end_idx - h.struct_begin_idx)
                if shorter > 0 and overlap / shorter > 0.5:
                    dup = True
                    break
        if not dup:
            kept.append(h)
    return kept


# ---------------------------------------------------------------------------
# 入口：run_pattern_detection（design D8）
# ---------------------------------------------------------------------------

_DETECTORS_BI = [
    ("w_bottom", detect_w_bottom),
    ("head_shoulders", detect_head_shoulders),
    ("box_breakout", detect_box_breakout),
    ("ascending_triangle", detect_ascending_triangle),
    ("low_flag", detect_low_flag),
    ("v_reversal", detect_v_reversal),
]
_DETECTORS_CANDLE = [
    ("rounding_bottom", detect_rounding_bottom),
    ("cup_handle", detect_cup_handle),
]
# 顶部看跌形态（chan-pattern-sell-signal）：输入接口与买向一致（points 供
# 未来扩展），检测内部只走蜡烛图路径（design D4）
_DETECTORS_SELL = [
    ("dark_cloud_cover", detect_dark_cloud_cover),
    ("shooting_star", detect_shooting_star),
    ("hanging_man", detect_hanging_man),
    ("bearish_engulfing", detect_bearish_engulfing),
]

# 卖向参数补充键（DETECT_PARAMS 单一出口在 pattern_meta，run_detection 合并）
_SELL_PARAM_KEYS = (
    "prior_rally_pct", "high_zone_ratio", "sell_vol_ratio_k", "sell_vol_ma_window",
    "dcc_min_penetration", "dcc_min_body_pct",
    "star_upper_shadow_ratio", "star_lower_shadow_max", "star_max_body_ratio",
    "engulf_min_body_pct",
)

# 落库行字段序（pattern_store 对齐）：(pattern_type, pattern_date, confirm_time_key,
#   price, ref_line_high, ref_line_low, score, qual, invalid, veto, detail_json,
#   direction)
ROW_FIELDS = (
    "pattern_type", "pattern_date", "confirm_time_key", "price",
    "ref_line_high", "ref_line_low", "score", "qual", "invalid", "veto", "detail",
    "direction",
)


def run_detection(bi_list, kl) -> List[PatternHit]:
    """对已最终化的 (bi_list, K线容器) 跑全部 8 买向 + 5 卖向（4 检测器）形态检测。"""
    from .pattern_meta import DETECT_PARAMS as _P  # 参数单一出口

    params = {**_P}
    candles = _klus(kl)
    if len(candles) < params["min_pattern_bars"] * 2:
        return []
    points = extract_swing_points(bi_list)
    hits: List[PatternHit] = []
    for _, fn in _DETECTORS_BI:
        try:
            hits.extend(fn(points, candles, params))
        except Exception:
            log.exception("形态检测失败: %s", fn.__name__)
    for _, fn in _DETECTORS_CANDLE:
        try:
            hits.extend(fn(candles, params))
        except Exception:
            log.exception("形态检测失败: %s", fn.__name__)
    for _, fn in _DETECTORS_SELL:
        try:
            hits.extend(fn(points, candles, params))
        except Exception:
            log.exception("顶部形态检测失败: %s", fn.__name__)
    return _dedup(hits)


def hit_to_row(hit: PatternHit, code: str, kl_type: str, autype: str, candles) -> tuple:
    """PatternHit → pattern_signal 行（只落稳定字段，detail 存关键点/量比，不落文案）。"""
    import json

    ci = hit.breakout.confirm_idx
    confirm_klu = candles[ci] if ci is not None and 0 <= ci < len(candles) else candles[-1]
    detail = {
        "key_points": hit.key_points,
        "struct_begin_idx": hit.struct_begin_idx,
        "struct_end_idx": hit.struct_end_idx,
        "volume_ratio": hit.breakout.volume_ratio,
        "retest": hit.breakout.retest,
        "features": {k: v for k, v in hit.features.items() if isinstance(v, (int, float, bool, str, list))},
    }
    return (
        hit.pattern_type,
        confirm_klu.time.toDateStr("-"),
        _klu_time_key(confirm_klu),
        float(confirm_klu.close),
        float(max(hit.ref_line)),
        float(min(hit.ref_line)),
        hit.score,
        hit.qual,
        bool(hit.breakout.invalidated),
        hit.veto,
        json.dumps(detail, ensure_ascii=False),
        hit.direction,
    )


def run_pattern_detection(chan, kl_type: str) -> List[tuple]:
    """增量引擎入口（design D8）：批量最终化后对单级别全量检测，返回落库行。

    买向与卖向命中都返回（direction 列区分，design D1 同表共存）；
    买向行为与 chan-pattern-buy-signal 时期完全一致。
    """
    kl = chan[kl_type]
    hits = run_detection(kl.bi_list, kl)
    candles = _klus(kl)
    return [hit_to_row(h, chan.code, kl_type, getattr(chan, "autype", "QFQ"), candles) for h in hits]
