# -*- coding: utf-8 -*-
"""
买卖点「用户可读结论」推导（chan-bsp-grading）。

把内部分档编号（`L1` / `L2` / `P1` / `P2` / `S3` / `C2` / `K3` / `T1` …）
翻译成普通用户能直接读懂的**三层信息**：

    强度分     0~100，纯数值，可横向比较不同买卖点的证据充分度
    强弱定性   很强 / 较强 / 一般 / 偏弱 / 很弱
    操作建议   能不能抄底买入、该用多大仓位

## 为什么需要这一层

内部阶梯是**开发者视角的坐标系**：`L2` 说的是「判据链 7 项里过了 5~7 项」，
普通用户既不知道有 7 项，也不知道「后半链」算好还是坏，更不知道能不能买。
`channel` 里把 `L2` 渲染成「判据链进度 · 后半链」，等于让用户自己解读编号。

本模块把同一个事实翻译成「证据够不够、能不能买」，编号降为辅助信息。

## 评分口径（三轴加权）

T1 家族（一买/一卖）三轴：

    进度轴 50 分   判据链走了多远（L1 前半 / L2 后半 / L4 全过）
    佐证轴 30 分   子级别是否同向共振（L2-1 分型 / L2-2 候选 / L2-3 已确认）
    分型轴 20 分   本级末端反转强度（L3-1 弱 / L3-2 中 / L3-3 强）

T2/T3 家族轴更多（五轴 / 四轴），按「进度 + 佐证 + 确认 + 分型 + 时间」
五轴均分后归一到 0~100。

**权重设计的依据**：进度轴决定「这条判据链走完没有」，是成立性的主证据，
权重最高；佐证轴是跨级别印证，权重次之；分型轴只反映最后一根 K 线的
反转力度，最容易被噪声左右，权重最低。

## 关于「是否推荐买入」

本模块给出的是**证据充分度**，不是投资建议。文案刻意避免「推荐买入」
这种断言式表述——项目自身的回测（`Debug/vp_entry/reports/final_conclusion.md`）
显示未确认信号的 T+10 胜率约 41.67%、均值 -0.82%，低于随机。把分数写成
「85 分，建议满仓」会让用户误以为是胜率承诺。

因此操作建议一律附带「证据够不够」的语义，并在 `DISCLAIMER` 里声明
不构成投资建议。
"""

from typing import Any, Dict, List, Mapping, Optional, Tuple

# ----------------------------------------------------------------------
# 定性档位
# ----------------------------------------------------------------------

# 强度分 → (定性, 操作建议)。顺序敏感：从高到低匹配第一个 score >= 下限的档。
# 文案原则：说「证据/确认」而不是「涨/跌」，避免被读成收益预测。
_GRADES: List[Tuple[int, str, str]] = [
    (80, "很强", "证据齐备，可按计划建仓"),
    (60, "较强", "结构成立，等最后确认再动手"),
    (40, "一般", "方向可能对，证据不足，先观察"),
    (20, "偏弱", "判据链还早，随时可能翻转"),
    (0, "很弱", "不建议抄底，信号太早期"),
]

# 卖点镜像文案（「建仓」→「离场」）
_GRADES_SELL: Dict[str, str] = {
    "很强": "证据齐备，可按计划减仓离场",
    "较强": "结构成立，等最后确认再离场",
    "一般": "方向可能对，证据不足，先观察",
    "偏弱": "判据链还早，随时可能翻转",
    "很弱": "不建议现在离场，信号太早期",
}

# 未确认点的分数上限。
#
# 「很强 / 证据齐备，可按计划建仓」是**已确认**才配得上的措辞。未确认的点
# 无论证据多齐，结构都可能随重算翻转——让它拿 80+ 会把「还差最后一步」
# 说成「可以买了」。所以按卡在哪一层封顶：
#
#   判据全过、只欠结构确认     ≤ 79（较强：等最后确认再动手）
#   被判据卡住（某项没过）     ≤ 59（一般：证据不足，先观察）
_CAP_PENDING_CONFIRM = 79
_CAP_BLOCKED = 59

# 判据全过时的分数地板。
#
# 整条判据链跑通本身就是最强的那一项证据，但佐证轴（30 分）和分型轴（20 分）
# 在「子级没有数据」「末端还没形成分型」时会各自计 0 —— 于是一个判据全过的
# 点可能只有 50 分，落到「一般 / 证据不足先观察」，与它自己的 `blocked_by`
# （「全部判据通过，只差最后的结构确认」）自相矛盾。
#
# 地板取 60（较强档的下限）：判据全过 ≡ 结构成立，只差确认，措辞必须与之同档。
# 上限仍是 `_CAP_PENDING_CONFIRM`，未确认点拿不到「很强」。
_FLOOR_JUDGED_PASSED = 60

DISCLAIMER = "证据充分度，不构成投资建议"

# 「判据卡在哪一步」无从得知时的哨兵值。区别于 None（= 判据全过只欠确认）：
# 读取侧（`routers/bsp.py::_grade_of`）只有落库的分数、没有 feature，只能按这个
# 哨兵推回「当初被判据拦下了」，再由它给出「无法定位卡在哪一步」的说明句。
BLOCKED_UNKNOWN = "unknown"

# ----------------------------------------------------------------------
# 三轴分值表（T1 家族）
# ----------------------------------------------------------------------

# 进度轴：50 分制
_PROGRESS_SCORE = {
    "L1": 20.0,   # 前半链：趋势/突破这类前置项过了，力度还没比赢
    "L2": 50.0,   # 后半链：核心判据全过，在查新低/DIF/零轴细节
    "P1": 20.0,   # T2 前半链
    "P2": 50.0,   # T2 后半链
    "L4": 50.0,   # 已确认单独处理，这里给满分由调用方短路
}

# 佐证轴：30 分制
_CORROBORATION_SCORE = {
    "L2-3": 30.0,  # 子级已确认同向一买（最强印证）
    "L2-2": 20.0,  # 子级候选部分达成
    "L2-1": 10.0,  # 子级末端分型（最弱的微观信号）
    "S3": 30.0,    # T2/T3：子级已确认同向点
    "S2": 20.0,
    "S1": 10.0,
}

# 分型轴：20 分制
_FRACTAL_SCORE = {
    "L3-3": 20.0,
    "L3-2": 14.0,
    "L3-1": 7.0,
    "K3": 20.0,
    "K2": 14.0,
    "K1": 7.0,
}

# 确认轴（T2/T3 专有）：事后确认进展
_CONFIRM_SCORE = {
    "C3": 20.0,
    "C2": 13.0,
    "C1": 0.0,   # 证伪终态
    "C0": 5.0,   # 进行中（数据末端，非终态）
}

# 时间轴（T2/T3 专有）：回调/回抽速度
_TIME_SCORE = {
    "T3": 15.0,  # 回调衰竭（最好）
    "T2": 9.0,
    "T1": 3.0,   # 回调急促
}


# ----------------------------------------------------------------------
# 是否已确认
# ----------------------------------------------------------------------

def _is_confirmed(ladder: Optional[str]) -> bool:
    return ladder == "L4"


def grade_for_score(score: int, is_buy: bool = True) -> Tuple[str, str]:
    """按强度分反查（定性, 操作建议）。

    单独抽出来是因为读取侧（`routers/bsp.py::_grade_of`）会拿库里存的分数
    覆盖现算分数 —— 覆盖后必须用**同一个函数**重算定性，否则会出现
    「20 分显示成一般」这种分数与措辞对不上的情况。
    """
    score = int(score)
    grade, advice_buy = _GRADES[-1][1], _GRADES[-1][2]
    for lower, g, adv in _GRADES:
        if score >= lower:
            grade, advice_buy = g, adv
            break
    return grade, (advice_buy if is_buy else _GRADES_SELL.get(grade, advice_buy))


# ----------------------------------------------------------------------
# 解析组合串
# ----------------------------------------------------------------------

def _split_axes(ladder: Optional[str]) -> List[str]:
    if not ladder:
        return []
    return [s.strip() for s in ladder.split("|") if s.strip()]


def _pick(axes: List[str], table: Mapping[str, float], default: float = 0.0) -> float:
    """轴列表里第一个命中该分值表的档位给它自己的分，都命中不了给 default。

    用「第一个命中」而不是「求和」：一个轴上只会有一个档位（如进度轴不是
    L1 就是 L2），求和会把重复档位（脏数据）算成两次。
    """
    for a in axes:
        if a in table:
            return table[a]
    return default


# ----------------------------------------------------------------------
# 主入口
# ----------------------------------------------------------------------

def grade_bsp(ladder: Optional[str], is_buy: bool = True,
              is_sure: bool = False,
              blocked_reason: Optional[str] = BLOCKED_UNKNOWN,
              family: str = "bsp1") -> Dict[str, Any]:
    """把阶梯组合串翻译成用户可读的结果。

    Args:
        ladder: 后端 `cal_ladder` 的输出（`'L4'` / `'L2|L2-3|L3-3'` / None）
        is_buy: 买卖方向（决定操作建议的措辞）
        is_sure: 是否已确认（来自 `bsp_is_sure`；与 ladder == 'L4' 互为印证，
                 任一为真即按已确认处理——两者理论同源，但不能假设一定同步）
        blocked_reason: 短路原因（`bsp1_standard_reason` / `bsp2_reason`）。
                 `None` = 判据全过只欠确认；非 None = 被判据卡住；
                 缺省 `"unknown"` = 调用方没传，无法区分（按「被卡住」从严处理）
        family: `'bsp1'` / `'bsp2'`，决定短路原因的措辞表

    Returns:
        {
            "score": 0~100 整数,
            "grade": "很强" / "较强" / "一般" / "偏弱" / "很弱",
            "advice": 操作建议（用户可读的一句话）,
            "blocked_by": 卡在哪一步（已确认或无法判定时为 None）,
            "confirmed": 是否已确认,
            "disclaimer": 免责声明,
        }

    **未定级**（ladder 为 None 且未确认）返回 score=0、grade=很弱：
    这种情况是「非一买类型未接入阶梯」或「存量数据缺 feature」，
    对用户而言就是「没有任何证据」，不应给中等分。

    **分数封顶**：未确认的点按「卡在哪一层」封顶（见 `_CAP_*` 常量），
    避免把「还差最后一步」显示成「可以买了」。

    `blocked_by` 恒存在（已确认 / 无法判定时为 None 或说明句）——
    前端按「有没有这句话」决定是否渲染告警行，键缺失会让调用方 KeyError。
    """
    confirmed = is_sure or _is_confirmed(ladder)

    if confirmed:
        # 已确认是最高档：证据链走完且结构定型，不再评分
        return {
            "score": 100,
            "grade": "很强",
            "advice": ("已确认成立，可按计划建仓" if is_buy
                       else "已确认成立，可按计划减仓离场"),
            "blocked_by": None,
            "confirmed": True,
            "disclaimer": DISCLAIMER,
        }

    axes = _split_axes(ladder)
    if not axes:
        return {
            "score": 0,
            "grade": "很弱",
            "advice": "无阶梯数据，无法评估证据充分度",
            "blocked_by": "没有阶梯数据，无法判断卡在哪一步",
            "confirmed": False,
            "disclaimer": DISCLAIMER,
        }

    # ---- 按家族选权重 ----
    # 含 C/K/S/T 前缀 = T2/T3 家族（五轴/四轴）；否则按 T1 三轴。
    # 注意：T1 的进度轴叫 L1/L2，而 T1 的佐证轴是 L2-3 这类带横线的值，
    # 所以前缀判断只能看首字母是否在 C/K/T 里，不能看 L。
    is_wide_family = any(a[:1] in ("C", "K", "T") for a in axes)

    if is_wide_family:
        # 五轴：进度 30 + 佐证 20 + 确认 20 + 分型 15 + 时间 15 = 100
        progress = _pick(axes, {"P1": 12.0, "P2": 30.0}, 0.0)
        corr = _pick(axes, {"S3": 20.0, "S2": 13.0, "S1": 6.0}, 0.0)
        confirm = _pick(axes, _CONFIRM_SCORE, 0.0)
        fractal = _pick(axes, {"K3": 15.0, "K2": 10.0, "K1": 5.0}, 0.0)
        time_pt = _pick(axes, _TIME_SCORE, 0.0)
        raw = progress + corr + confirm + fractal + time_pt
    else:
        # T1 三轴：进度 50 + 佐证 30 + 分型 20 = 100
        progress = _pick(axes, _PROGRESS_SCORE, 0.0)
        corr = _pick(axes, _CORROBORATION_SCORE, 0.0)
        fractal = _pick(axes, _FRACTAL_SCORE, 0.0)
        raw = progress + corr + fractal

    # ---- 未确认点的分数封顶 ----
    # blocked_reason None → 判据全过只欠确认；否则被判据卡住。
    # 缺省 "unknown" 走「被卡住」分支（从严）：没传原因时宁可低估，
    # 不要把「不知道卡在哪」显示成「只差最后一步」。
    blocked = blocked_reason is not None
    if not blocked:
        # 判据全过：加地板分，避免佐证轴/分型轴无数据把分数拖进「证据不足」档
        raw = max(raw, _FLOOR_JUDGED_PASSED)
    cap = _CAP_BLOCKED if blocked else _CAP_PENDING_CONFIRM
    score = min(int(round(max(0.0, min(100.0, raw)))), cap)

    grade, advice = grade_for_score(score, is_buy)

    if not blocked:
        blocked_by: Optional[str] = reason_text(None, family)
    elif blocked_reason == BLOCKED_UNKNOWN:
        blocked_by = "无法判断卡在哪一步"
    else:
        blocked_by = reason_text(blocked_reason, family)

    return {
        "score": score,
        "grade": grade,
        "advice": advice,
        "blocked_by": blocked_by,
        "confirmed": False,
        "disclaimer": DISCLAIMER,
    }


# ----------------------------------------------------------------------
# 短路原因 → 用户可读的一句话
# ----------------------------------------------------------------------

# 一买判据链的短路原因（内核 `bsp1_standard_reason`）
_BSP1_REASON_TEXT = {
    "trend": "趋势前提没满足（中枢数量不够，或中枢没有依次下移）",
    "new_extreme": "没有创出这段趋势的新低（买点）/ 新高（卖点）",
    "dif_div": "黄白线（DIF）没有同步背驰",
    "zero_axis": "没有回抽过零轴",
}

# 二买判据链的短路原因（内核 `bsp2_reason`）
_BSP2_REASON_TEXT = {
    "retrace_rate": "回调幅度太大，超过了允许的上限",
    "retrace_not_in_zs": "回调没有回到中枢附近",
    "zero_break_amp": "反向笔幅度为零，无法度量回调",
}


def reason_text(reason: Optional[str], family: str = "bsp1") -> str:
    """把短路原因翻译成普通用户能懂的一句话。

    Args:
        reason: `bsp1_standard_reason` / `bsp2_reason` 的值（None = 全过）
        family: `'bsp1'` / `'bsp2'`

    Returns:
        用户可读的原因；None（全过）返回「全部判据通过，只差线段确认」。
        未知原因原样返回，便于排查而不至于静默丢信息。
    """
    if reason is None:
        return "全部判据通过，只差最后的结构确认"
    table = _BSP2_REASON_TEXT if family == "bsp2" else _BSP1_REASON_TEXT
    return table.get(reason, str(reason))


# ----------------------------------------------------------------------
# 从 feature 直接推导（方便后端序列化一次性拼装）
# ----------------------------------------------------------------------

def grade_from_feature(feature: Optional[Mapping[str, Any]],
                       ladder: Optional[str], is_buy: bool,
                       is_sure: bool) -> Dict[str, Any]:
    """在 `grade_bsp` 基础上按「有没有判据明细」细化 `blocked_by`。

    前端要在 tooltip 顶部显示「⚠ 未成立 + 卡在哪一步」，光有分数不够——
    用户需要知道**为什么**没成立。

    **无法判定时不说「全部通过」**：没有短路原因键的点（非一买/二买家族、
    存量点），我们并不知道它卡在哪，说「全部判据通过」是假的。
    """
    feat = feature or {}
    family = "bsp2" if "bsp2_reason" in feat else "bsp1"
    has_reason_key = ("bsp2_reason" if family == "bsp2"
                      else "bsp1_standard_reason") in feat
    reason = feat.get("bsp2_reason") if family == "bsp2" \
        else feat.get("bsp1_standard_reason")

    if has_reason_key:
        # 有短路原因键：None = 判据全过（只欠结构确认），否则是具体哪一项没过
        blocked_reason = reason
    else:
        # 无该键（存量点 / 非本家族）：无法判定卡在哪，按「被卡住」从严处理
        blocked_reason = BLOCKED_UNKNOWN

    out = grade_bsp(ladder, is_buy=is_buy, is_sure=is_sure,
                    blocked_reason=blocked_reason, family=family)

    # 三轴全零时 `grade_bsp` 给的是「没有阶梯数据」的通用说法，
    # 这里能说清楚是「数据不足」还是「判据没过」，优先用更具体的。
    if not out["confirmed"] and not ladder and not feat:
        out["blocked_by"] = "数据不足，无法判断卡在哪一步"
    elif not out["confirmed"] and blocked_reason == BLOCKED_UNKNOWN:
        # 有 ladder 却无短路原因键：二买/三买等家族没有一买那条七步判据链，
        # 它们本就按多轴综合评估，不存在「卡在第几步」这个说法。
        out["blocked_by"] = (
            "该类型买卖点不适用逐步判据，按各轴评估结果综合判断"
            if ladder else "数据不足，无法判断卡在哪一步"
        )
    return out