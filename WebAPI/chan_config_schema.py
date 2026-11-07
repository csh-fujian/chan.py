# -*- coding: utf-8 -*-
"""
缠论参数元数据 — 参数清单、分类、控件类型与白话解释。

设计要点（design.md D2/D10/D11）：
- **默认值与合法取值不在本模块硬编码**：`default` 由 `_read_default()` 从
  `CChanConfig()` 实例实时反射读取。内核默认值调整（例如 `chan-bsp1-strict-extreme`
  把 `macd_algo` 默认改为 `full_area`）后本模块无需改动。
- `choices` 是展示用的取值清单，其正确性由 `Debug/test_chan_config_meta.py` 用
  构造期接受/拒绝探测校验（等价于 `_check_choice` 的白名单断言）。
- 三类分组按「改动会影响什么」划分，不按模块划分 —— 新手不知道「中枢配置」会怎么
  影响他看到的买卖点，但能理解「这个会重排整张结构」。
- 白话解释三段：`plain`（这是什么）/ `effect`（调大调小会发生什么）/ `scope`（影响哪些
  买卖点或结构）。只影响标注的参数必须在 `effect` 里写明「不会增减买卖点」。
"""

from typing import Any, Optional

from .chan_config_store import VOLUME_MACD_ALGOS

import logging

log = logging.getLogger("chan_config_schema")

# ---- 分组 ----
GROUP_BSP = "bsp_judgement"       # 影响买卖点成立性
GROUP_LADDER = "ladder_annotation"  # 只影响证据标注
GROUP_STRUCTURE = "structure"     # 改变笔/线段/中枢结构

GROUP_META = {
    GROUP_BSP: {
        "title": "买卖点判据",
        "hint": "改动会直接增减买卖点数量。调完看图上买卖点是变多还是变少。",
        "collapsed_by_default": False,
    },
    GROUP_LADDER: {
        "title": "证据阶梯标注",
        "hint": "只影响买卖点旁边的证据标签（如 C0/C3、T1/T3），不会增减任何买卖点。",
        "collapsed_by_default": False,
    },
    GROUP_STRUCTURE: {
        "title": "高级 · 结构算法",
        "hint": "改动会重排笔、线段与中枢，进而改变所有依赖这些结构的买卖点。非必要不建议调整。",
        "collapsed_by_default": True,
    },
}

# 力度算法的展示名（白话）
_MACD_ALGO_LABELS = {
    "peak": "柱子最高点（峰值）",
    "area": "同向柱子面积",
    "full_area": "整段柱子面积（推荐）",
    "diff": "柱体高度差",
    "diff_peak": "黄白线极值（DIF）",
    "slope": "走势斜率",
    "amp": "价格振幅",
    "amount": "成交额",
    "volumn": "成交量",
    "amount_avg": "平均成交额",
    "volumn_avg": "平均成交量",
    "turnrate_avg": "平均换手率",
    "rsi": "RSI 强弱指标",
}

# 买卖点类型的展示名
_BS_TYPE_LABELS = {
    "1": "一买/一卖（趋势背驰）",
    "1p": "盘整背驰",
    "2": "二买/二卖（回调不破）",
    "2s": "类二（中枢内回调）",
    "3a": "三买A（中枢在下一条线段）",
    "3b": "三买B（中枢在本线段）",
}


def _p(
    key: str,
    label: str,
    group: str,
    control: str,
    plain: str,
    effect: str,
    scope: str,
    *,
    subtype: str = "",
    choices: Optional[list] = None,
    choice_labels: Optional[dict] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    step: Optional[float] = None,
    allow_inf: bool = False,
    caveat: str = "",
    conditional: bool = False,
    visible_when: Optional[dict] = None,
    probe_choices: bool = False,
) -> dict:
    """构造一条参数元数据（`default` 由调用方统一反射填充）。

    `probe_choices=True` 时，`choices` 视为「候选池」——`build_schema()` 会用构造期
    探测剔除内核当前不接受的取值。这样内核新增口径（如 `level`）时选项自动跟上，
    而尚未落地的候选不会展示给用户。
    """
    return {
        "key": key,
        "label": label,
        "group": group,
        "subtype": subtype,
        "control": control,
        "choices": choices,
        "choice_labels": choice_labels,
        "min": min_value,
        "max": max_value,
        "step": step,
        "allow_inf": allow_inf,
        "caveat": caveat,
        "conditional": conditional,
        "visible_when": visible_when,
        "probe_choices": probe_choices,
        "plain": plain,
        "effect": effect,
        "scope": scope,
    }


# ----------------------------------------------------------------------
# 参数清单（56 项常驻 + 2 项条件项 = 58）
# ----------------------------------------------------------------------

PARAMS: list[dict] = [
    # ================= 买卖点判据 · 通用（7）=================
    _p("bsp_preset", "档位预设", GROUP_BSP, "preset",
       "整套买卖点规则的档位开关。standard 是当前推荐口径，legacy 一键回到改造前的老口径。",
       "切换档位会把这一组里所有参数一次性改成该档位的预设值。自己单独改过的项会保留你的取值，不会被档位覆盖。",
       "全部买卖点类型",
       choices=["standard", "legacy"],
       choice_labels={"standard": "标准档（推荐）", "legacy": "旧档（回退用）"}),
    _p("bs_type", "计算哪几类买卖点", GROUP_BSP, "multi",
       "告诉系统只计算哪几类买卖点。关掉的类型不会出现在图上。",
       "勾得越少算得越快。全部关掉就等于不输出任何买卖点。",
       "全部买卖点类型",
       subtype="通用",
       choices=["1", "1p", "2", "2s", "3a", "3b"],
       choice_labels=_BS_TYPE_LABELS),
    _p("divergence_rate", "背驰力度阈值", GROUP_BSP, "number",
       "离开的那一段和进入的那一段做力气对比。后一段的力气要比前一段小到什么程度才算「背驰」。",
       "调小 = 更严格，要求后一段力气明显更小，买卖点变少。调大 = 更宽松，买卖点变多。填 inf 表示完全不看力气对比。",
       "一买/一卖、盘整背驰",
       subtype="通用",
       min_value=0, allow_inf=True,
       caveat="填 inf 等价于关闭力度约束，买卖点会明显增多。"),
    _p("min_zs_cnt", "至少几个中枢才算趋势", GROUP_BSP, "integer",
       "一买/一卖要求先有一段下跌或上涨趋势。这项定义要有几个中枢才算「趋势」。",
       "调小到 1 = 只要一个中枢就算趋势，一买变多（等于放宽）。调大到 3 或更大 = 要求更长趋势，一买明显变少。",
       "一买/一卖",
       subtype="通用",
       min_value=1, step=1),
    _p("bsp1_only_multibi_zs", "只认多笔中枢", GROUP_BSP, "bool",
       "中枢是由几根笔组成的。只有一根笔构成的中枢通常不可靠。这项决定一买是否排除这种单笔中枢。",
       "开启 = 一买只在由多根笔组成的中枢附近产生，更可靠但更少。关闭 = 单笔中枢也算，一买变多。",
       "一买/一卖",
       subtype="通用",
       caveat="线段级别的同类开关由系统固定为关闭，本项只影响笔级别。"),
    _p("macd_algo", "力气对比用什么算法", GROUP_BSP, "select",
       "判断两段走势谁力气大时，用哪个指标来量「力气」。这是影响买卖点数量最明显的一项。",
       "不同算法对同一段走势会给出不同结论：选柱子面积类偏重整段动能，选峰值类偏重单根柱子，选振幅类只看涨跌幅。换一项后建议先看图上买卖点的增减是否符合预期。",
       "一买/一卖、盘整背驰",
       subtype="通用",
       choices=list(_MACD_ALGO_LABELS.keys()),
       choice_labels=_MACD_ALGO_LABELS),
    _p("bs1_peak", "一买要求价格创新极值", GROUP_BSP, "bool",
       "要求一买出现时的价格必须是这一段下跌里的最低点（卖点则是最高点）。",
       "开启 = 位置不够极端的不算一买，更严格。关闭 = 只要力气背驰就认，一买变多。",
       "一买/一卖",
       subtype="通用"),
    _p("bs1_peak_strict", "极值比较要严格", GROUP_BSP, "bool",
       "判断「是不是新的最低点」时，遇到和之前【完全相等】的低点怎么算。",
       "开启 = 相等不算创新低（双底、双顶会被拦下，更严格，这是默认）。"
       "关闭 = 相等也算创新低（改造前的宽松口径，回退档用）。",
       "一买/一卖",
       subtype="通用",
       caveat="关闭后与「创新低」判据的严格性不再一致，但回退档下那条判据本就关闭，不会冲突。"),

    # ================= 买卖点判据 · 类型跟随（4）=================
    _p("bsp2_follow_1", "二买必须跟在一买之后", GROUP_BSP, "bool",
       "二买通常被理解成「一买之后的第一次回调低点」。这项决定二买是否必须有个一买在前面。",
       "开启 = 没有一买就不出二买。关闭 = 允许没有一买也单独出二买（俗称小转大的场景），二买变多。",
       "二买/二卖",
       subtype="类型跟随"),
    _p("bsp3_follow_1", "三买必须跟在一买之后", GROUP_BSP, "bool",
       "三买通常发生在「离开中枢后回抽不回中枢」的位置。这项决定是否要求前面先有一买。",
       "开启 = 没有一买就不出三买。关闭 = 允许单独出三买，三买变多。",
       "三买/三卖",
       subtype="类型跟随"),
    _p("bsp3_follow_1_mode", "三买查哪种一买", GROUP_BSP, "select",
       "当要求「三买必须跟在一买之后」时，用来判断前面那个一买算不算数：要求严格成立的一买，还是结构性候选也算。",
       "选「已成立」更严格，三买更少。选「候选也算」更宽松，三买更多。",
       "三买/三卖",
       subtype="类型跟随",
       choices=["sure", "candidate"],
       choice_labels={"sure": "已成立的一买（严格）", "candidate": "结构性候选也算（宽松）"}),
    _p("bsp2s_follow_2", "类二必须跟在二买之后", GROUP_BSP, "bool",
       "类二是中枢内部的回调低点。这项决定类二是否必须有一个已成立的二买在前面。",
       "开启 = 没有二买就不出类二，更严格。关闭 = 允许单独出类二，类二变多。",
       "类二（2s）",
       subtype="类型跟随"),

    # ================= 买卖点判据 · 一买（11）=================
    _p("bsp1_trend", "一买要求先有趋势", GROUP_BSP, "bool",
       "真正的一买被理解为「一段下跌趋势走到尽头」。这项决定是否要求先有趋势（至少两个依次下移的中枢）。",
       "开启 = 只认趋势末端的一买，更符合教科书定义，一买较少。关闭 = 只要背驰就认，退化为盘整背驰口径，一买明显变多。",
       "一买/一卖",
       subtype="一买判据"),
    _p("bsp1_trend_mode", "趋势怎么判定", GROUP_BSP, "select",
       "判断「两个中枢是不是依次下移」时，用严格口径还是允许区间有重叠。",
       "选「严格」要求两个中枢的区间完全不重叠，趋势更明确，一买更少。选「允许重叠」放宽，一买更多。",
       "一买/一卖",
       subtype="一买判据",
       choices=["strict", "overlap"],
       choice_labels={"strict": "严格（区间不重叠）", "overlap": "允许区间重叠"}),
    _p("bsp1_new_extreme", "一买要求创新低", GROUP_BSP, "bool",
       "要求一买出现时的价格低于这一整段趋势里的所有前低（卖点则是新高）。",
       "开启 = 没创出趋势新低的不算一买，更严格。关闭 = 只要比前一个中枢更极端就算，一买变多。",
       "一买/一卖",
       subtype="一买判据"),
    _p("bsp1_new_extreme_mode", "新低跟谁比", GROUP_BSP, "select",
       "判断「是不是创新低」时，前面那些低点取哪些来比较。",
       "选「从趋势起点比」只看这段趋势内的低点，较宽松。选「跟上一中枢的进入段比」范围更小，更容易通过。选「跟全部历史比」要求比历史上所有同向低点都低，更严格、一买更少。选「跨线段全量同向笔」最严格。",
       "一买/一卖",
       subtype="一买判据",
       choices=["trend_start", "prev_zs_in", "all", "level"],
       choice_labels={
           "trend_start": "从趋势起点开始比",
           "prev_zs_in": "跟上一中枢的进入段比",
           "all": "跟线段内全部历史比",
           "level": "跟本级别全部同向笔比（跨线段，最严格）",
       },
       caveat="无论选哪一项，比较本身都是严格优（相等极值不算创新低/新高）。",
       # 候选池按构造期探测收敛：内核尚未支持的取值不会展示给用户，
       # 内核新增口径时选项自动跟上，无需改本文件。
       probe_choices=True),
    _p("bsp1_dif_div", "要求黄白线同步背驰", GROUP_BSP, "bool",
       "除了柱子，还要求指标的黄白线（DIF）也同步表现出力气衰竭。",
       "开启 = 多一道校验，一买更少也更可靠。关闭 = 只看柱子，一买变多。",
       "一买/一卖",
       subtype="一买判据"),
    _p("bsp1_zero_axis", "要求回抽过零轴", GROUP_BSP, "bool",
       "要求下跌段和最后的杀跌段之间，黄白线曾经回到零轴上方（说明中途有过像样的反弹）。",
       "开启 = 中间没有反弹过的不算一买，更严格。关闭 = 一买变多。",
       "一买/一卖",
       subtype="一买判据"),
    _p("bsp1_zs_extend_to_seg_end", "中枢必须延伸到线段末尾", GROUP_BSP, "bool",
       "一条旧规则：要求判断用的中枢一直延伸到这条线段的最后一根笔。",
       "开启 = 大量一买会被否定（这是老口径的严格条件）。当前推荐关闭。",
       "一买/一卖",
       subtype="一买判据",
       caveat="这是历史遗留条件，standard 档默认关闭，仅 legacy 档开启。"),
    _p("bsp1_downgrade_to_pz", "不满足趋势就降级登记", GROUP_BSP, "bool",
       "力气背驰成立、但前面没有形成趋势的候选点，是直接丢掉，还是登记成「盘整背驰」保留下来。",
       "开启 = 这些点会以盘整背驰的身份出现在图上（不会被当成一买，也不会被二买三买引用）。关闭 = 直接丢掉。",
       "盘整背驰（1p）",
       subtype="一买判据"),
    _p("bsp1_force_scope", "力气对比取多长的区间", GROUP_BSP, "select",
       "比较「离开段」和「进入段」的力气时，是只取那一根笔，还是取一整段走势。",
       "选「整段走势」把前后若干笔合起来算，更贴近缠论原意、也更稳定。选「单笔」是改造前的老口径，对急跌赶底的形态容易判不出来。",
       "一买/一卖、盘整背驰",
       subtype="一买判据",
       choices=["swing", "bi"],
       choice_labels={"swing": "整段走势（推荐）", "bi": "单根笔（老口径）"},
       caveat="选成交量、成交额、换手率类算法时，没有整段版本，会自动退回单根笔并在特征里标注。"),
    _p("bsp1_qjt", "计算区间套特征", GROUP_BSP, "bool",
       "额外记录「更低级别上同方向是否也有个已确认的一买」。这只写进特征备查，不参与任何判断。",
       "开启或关闭都不会增减任何一个买卖点，只会多算一个附加字段（也更慢）。",
       "不影响买卖点数量",
       subtype="一买判据",
       caveat="这是特征不是判据：调它不会改变图上任何买卖点。"),
    _p("bsp1_qjt_depth", "区间套递归几层", GROUP_BSP, "integer",
       "上一条开启时，往下级找几层。层数越多越慢，而且多层会放大不同计算方式之间的差异。",
       "调大耗时会成倍增加，建议保持 1。",
       "不影响买卖点数量",
       subtype="一买判据",
       min_value=1, step=1),

    # ================= 买卖点判据 · 二买 / 类二（5）=================
    _p("max_bs2_rate", "二买回调幅度的上限", GROUP_BSP, "number",
       "二买是一买之后的回调低点。这项限制回调能有多深 —— 回调太深就说明一买可能失效了。",
       "调小 = 只认浅浅的回调，二买变少。调到接近 1 = 允许很深的回调，二买变多。",
       "二买/二卖",
       subtype="二买 / 类二",
       min_value=0, max_value=1, step=0.0001),
    _p("max_bsp2s_lv", "类二最多到第几层", GROUP_BSP, "integer",
       "限制类二买卖点最多出现在第几层结构上。留空表示不限制。",
       "填数字 = 超过这一层的类二不输出，类二变少。留空 = 不限制。",
       "类二（2s）",
       subtype="二买 / 类二",
       min_value=0, step=1),
    _p("bsp2_retrace_zs", "二买回调要和中枢有关联", GROUP_BSP, "bool",
       "要求二买的回调笔和某个中枢的价格区间有交集，而不是随便一跌就算。",
       "开启 = 二买更少但更贴近结构。关闭 = 沿用「单笔回调」的简化口径，二买更多。",
       "二买/二卖",
       subtype="二买 / 类二"),
    _p("bsp2s_require_zs", "类二要求价格落在中枢内", GROUP_BSP, "bool",
       "要求类二出现时的价格落在一个由多根笔组成的中枢区间里。",
       "开启 = 不在中枢里的不算类二，更少更可靠。关闭 = 类二变多。",
       "类二（2s）",
       subtype="二买 / 类二"),
    _p("bsp2s_rate_mode", "类二回调幅度怎么量", GROUP_BSP, "select",
       "衡量类二回调深度的方式：按涨跌幅算，还是按价格位移算。",
       "选「振幅」按高低点之差占价格的比例算，更常用。选「位移」是改造前的老算法，对同一段回调会给出不同深浅结论。",
       "类二（2s）",
       subtype="二买 / 类二",
       choices=["amp", "disp"],
       choice_labels={"amp": "涨跌幅（振幅）", "disp": "价格位移（老口径）"}),

    # ================= 买卖点判据 · 三买（5）=================
    _p("bsp3_peak", "三买要求突破中枢内极值", GROUP_BSP, "bool",
       "要求离开中枢的那一下必须真正冲过中枢内部的最高点（买点方向为向上突破）。",
       "开启 = 突破不够有力的不算三买，更严格。关闭（当前默认）= 三买更多。",
       "三买/三卖",
       subtype="三买判据"),
    _p("bsp3_peak_on_breakout", "上一条判哪根笔", GROUP_BSP, "select",
       "上一条开启后，判断「有没有突破极值」时看的是冲出去的那根笔，还是回抽回来的那根笔。",
       "选「判突破笔」符合常规理解。选「判回抽笔」是历史行为，且只对三买A 生效，三买B 不受影响。",
       "三买/三卖",
       subtype="三买判据",
       choices=["True", "False"],
       choice_labels={"True": "判突破笔（冲出中枢那根）", "False": "判回抽笔（历史行为）"}),
    _p("bsp3b_mode", "三买B 用哪种扫描", GROUP_BSP, "select",
       "三买B（中枢在本线段内）有两种找法：标准法只认「冲出中枢后的第一次回抽」，历史法是每隔两根笔扫一遍。",
       "选「标准」更符合三买的定义，三买B 更少。选「历史」更宽松，会出现已经回过中枢后再出的点。",
       "三买B（3b）",
       subtype="三买判据",
       choices=["standard", "legacy"],
       choice_labels={"standard": "标准（第一次回抽）", "legacy": "历史扫描（宽松）"}),
    _p("strict_bsp3", "三买必须紧挨着一买", GROUP_BSP, "bool",
       "要求三买用到的中枢必须紧挨在一买旁边，中间不能隔别的东西。",
       "开启 = 三买更少更严格。关闭 = 三买变多。",
       "三买/三卖",
       subtype="三买判据",
       caveat="三买A 与三买B 的「紧邻」判定条件不同（中枢位置不同，这是结构性必然），不可统一。"),
    _p("bsp3a_max_zs_cnt", "三买A 最多看几个中枢", GROUP_BSP, "integer",
       "三买A 会在下一条线段里找中枢。这项限制最多检查前面几个。",
       "调大 = 检查范围更广，三买A 可能变多，但更慢。最小为 1。",
       "三买A（3a）",
       subtype="三买判据",
       min_value=1, step=1),

    # ================= 证据阶梯标注（8）=================
    _p("bsp2_confirm_window", "二买确认看几根笔", GROUP_LADDER, "select",
       "给二买打「确认」标签时，往后看几根笔来判断走势有没有延续。",
       "调大（2 根）会把末端候选标成「还没确认」而不误判为强，更保守。调到 1 会把末端候选更早标成强。这个数字只影响标签怎么打，不会增减任何买卖点。",
       "不影响买卖点数量",
       subtype="T2 阶梯（二买）",
       choices=[1, 2],
       choice_labels={1: "看 1 根笔", 2: "看 2 根笔（推荐）"},
       caveat="这是特征不是判据：调它不会改变图上任何买卖点。"),
    _p("bsp2_confirm_level", "二买确认的标准", GROUP_LADDER, "select",
       "判断「确认了」的门槛：要真正突破前一根笔的端点才算，还是收复一半就算。",
       "选「突破端点才算」更严格，确认标签更少出现。选「收复一半就算」更宽松。这个选择只影响标签内容，不会增减任何买卖点。",
       "不影响买卖点数量",
       subtype="T2 阶梯（二买）",
       choices=["strong", "weak"],
       choice_labels={"strong": "突破端点才算（严格）", "weak": "收复一半就算（宽松）"},
       caveat="这是特征不是判据：调它不会改变图上任何买卖点。"),
    _p("bsp2_time_axis_strong", "二买「回调衰竭」的快慢线", GROUP_LADDER, "number",
       "比较回调笔和前面突破笔的速度（按每根笔的幅度比）。速度足够慢，说明下跌在衰竭。低于这个值算「很慢」。",
       "调大 = 更容易被判成「很慢」。这个数值只影响标签里打 T3 还是 T2，不会增减任何买卖点。必须小于下面的弱档线。",
       "不影响买卖点数量",
       subtype="T2 阶梯（二买）",
       min_value=0, step=0.1,
       caveat="必须严格小于弱档线，否则保存会被拒绝。这是特征不是判据。"),
    _p("bsp2_time_axis_weak", "二买「回调急促」的快慢线", GROUP_LADDER, "number",
       "速度高于这个值算「急促」（下跌还很猛）。介于强弱两条线之间算中性。",
       "调小 = 更多情况被判成「急促」。这个数值只影响标签内容，不会增减任何买卖点。必须大于上面的强档线。",
       "不影响买卖点数量",
       subtype="T2 阶梯（二买）",
       min_value=0, step=0.1,
       caveat="必须严格大于强档线，否则保存会被拒绝。这是特征不是判据。"),
    _p("bsp3_confirm_window", "三买确认看几根笔", GROUP_LADDER, "select",
       "给三买打「确认」标签时，往后看几根笔来判断回抽之后走势有没有延续。",
       "调大（2 根）会把末端候选标成「窗口不足」，更保守。调到 1 会更早给出确认标签。这个数字只影响标签怎么打，不会增减任何买卖点。",
       "不影响买卖点数量",
       subtype="T3 阶梯（三买）",
       choices=[1, 2],
       choice_labels={1: "看 1 根笔", 2: "看 2 根笔（推荐）"},
       caveat="这是特征不是判据：调它不会改变图上任何买卖点。"),
    _p("bsp3_confirm_level", "三买确认的标准", GROUP_LADDER, "select",
       "判断「确认了」的门槛：要突破回抽笔的端点才算，还是收复回抽幅度一半就算。",
       "选「突破回抽笔端点」更严格，确认标签更少出现。选「收复一半」更宽松。这个选择只影响标签内容，不会增减任何买卖点。",
       "不影响买卖点数量",
       subtype="T3 阶梯（三买）",
       choices=["strong", "weak"],
       choice_labels={"strong": "突破回抽笔端点（严格）", "weak": "收复一半（宽松）"},
       caveat="这是特征不是判据：调它不会改变图上任何买卖点。"),
    _p("bsp3_time_axis_strong", "三买「回抽衰竭」的快慢线", GROUP_LADDER, "number",
       "比较回抽笔和突破笔的速度。速度足够慢说明回抽在衰竭。低于这个值算「很慢」。",
       "调大 = 更容易被判成「很慢」。这个数值只影响标签内容，不会增减任何买卖点。必须小于弱档线。",
       "不影响买卖点数量",
       subtype="T3 阶梯（三买）",
       min_value=0, step=0.1,
       caveat="必须严格小于弱档线，否则保存会被拒绝。这是特征不是判据。"),
    _p("bsp3_time_axis_weak", "三买「回抽急促」的快慢线", GROUP_LADDER, "number",
       "速度高于这个值算「回抽急促」。介于两条线之间算中性。",
       "调小 = 更多情况被判成「急促」。这个数值只影响标签内容，不会增减任何买卖点。必须大于强档线。",
       "不影响买卖点数量",
       subtype="T3 阶梯（三买）",
       min_value=0, step=0.1,
       caveat="必须严格大于强档线，否则保存会被拒绝。这是特征不是判据。"),

    # ================= 高级 · 结构（15）=================
    _p("bi_algo", "笔的算法", GROUP_STRUCTURE, "select",
       "决定怎么把相邻的高低点连成一根「笔」。",
       "选「标准」会检查够不够 K 线数量，笔更少更稳。选「只看分型」跳过数量检查，笔会明显变多、变碎。",
       "全部结构 → 全部买卖点",
       subtype="笔",
       choices=["normal", "fx"],
       choice_labels={"normal": "标准（检查 K 线数量）", "fx": "只看分型（更碎）"}),
    _p("bi_strict", "笔的严格模式", GROUP_STRUCTURE, "bool",
       "一根笔至少要包含几根合并后的 K 线。",
       "开启 = 至少 4 根，笔更少更可靠。关闭 = 放宽到 3 根，笔变多。",
       "全部结构 → 全部买卖点",
       subtype="笔"),
    _p("bi_fx_check", "顶底分型的严格程度", GROUP_STRUCTURE, "select",
       "判断一个高点是「顶」、低点是「底」时，要比较几根 K 线。越严格，认定的转折越少。",
       "选得越严格 → 笔越少。这是影响笔数量最明显的一项，改动后整张图的结构都会重排。",
       "全部结构 → 全部买卖点",
       subtype="笔",
       choices=["loss", "half", "strict", "totally"],
       choice_labels={
           "loss": "宽松（只比中间一根）",
           "half": "半严格",
           "strict": "严格（当前默认）",
           "totally": "最严格",
       }),
    _p("gap_as_kl", "跳空缺口算一根 K 线", GROUP_STRUCTURE, "bool",
       "开盘直接跳过一段价格时，是否把这个缺口当成一根 K 线来凑数量。",
       "开启 = 缺口帮笔更容易成立，笔变多。关闭 = 笔变少。",
       "全部结构 → 全部买卖点",
       subtype="笔"),
    _p("bi_end_is_peak", "笔的端点必须是极值", GROUP_STRUCTURE, "bool",
       "要求一根笔的结束点必须是区间内的最高或最低，中间不能有更高的点越过它。",
       "开启 = 结构更干净，笔更少。关闭 = 允许端点不是最极端的，笔变多。",
       "全部结构 → 全部买卖点",
       subtype="笔"),
    _p("bi_allow_sub_peak", "允许次高点作为端点", GROUP_STRUCTURE, "bool",
       "是否允许用「第二高」或「第二低」的点作为笔的端点。",
       "开启 = 笔变多（当前默认）。关闭 = 端点必须严格创新高/新低，笔变少。",
       "全部结构 → 全部买卖点",
       subtype="笔"),
    _p("seg_algo", "线段的算法", GROUP_STRUCTURE, "select",
       "决定怎么把若干笔合成一条直线段。",
       "只有「特征序列法」在维护中，另外两种已废弃，选中会打弃用警告，且结果可能与标准口径不一致。",
       "全部结构 → 全部买卖点",
       subtype="线段",
       choices=["chan", "1+1", "break"],
       choice_labels={"chan": "特征序列法（唯一维护中）", "1+1": "1+1 终结法（已废弃）",
                      "break": "线段破坏法（已废弃）"},
       caveat="非 chan 的两种算法已弃用，仅用于历史对照。"),
    _p("left_seg_method", "末尾未确认的笔怎么处理", GROUP_STRUCTURE, "select",
       "最后一段线段还没被后面的走势确认时，剩下的笔怎么归拢成一条「临时线段」。",
       "选「找极值笔」以最后那个高低点切一刀。选「全部合并」把所有剩下的笔并成一条。只影响最后一个未确认段。",
       "末尾的未确认买卖点",
       subtype="线段",
       choices=["peak", "all"],
       choice_labels={"peak": "找极值笔（当前默认）", "all": "全部合并为一段"}),
    _p("zs_combine", "合并相邻中枢", GROUP_STRUCTURE, "bool",
       "两个相邻中枢的价格区间有重叠时，是否把它们并成一个更大的中枢。",
       "开启 = 中枢更少更大（当前默认）。关闭 = 中枢更多更碎，依赖中枢数量的买卖点会明显变化。",
       "全部结构 → 全部买卖点",
       subtype="中枢"),
    _p("zs_combine_mode", "中枢怎么算重叠", GROUP_STRUCTURE, "select",
       "判断两个中枢能不能合并时，用中枢本身的区间，还是用包含极值的更宽区间。",
       "选「中枢区间」要求本体重叠才合并。选「极值区间」更宽松，中枢更容易合并、数量更少更大。",
       "全部结构 → 全部买卖点",
       subtype="中枢",
       choices=["zs", "peak"],
       choice_labels={"zs": "中枢区间重叠（当前默认）", "peak": "极值区间重叠（更宽松）"}),
    _p("one_bi_zs", "允许一根笔构成中枢", GROUP_STRUCTURE, "bool",
       "正常情况下至少要三根笔才能构成一个中枢。这项决定是否放开成一根笔也算。",
       "开启 = 会出现大量单笔中枢，买卖点里「多笔中枢」相关的判据会大量失效。强烈建议保持关闭。",
       "全部结构 → 全部买卖点",
       subtype="中枢",
       caveat="开启后「多笔中枢」判据大面积失效，属于高风险改动。"),
    _p("zs_algo", "中枢的算法", GROUP_STRUCTURE, "select",
       "决定在中枢怎么划分范围。",
       "「标准」按线段内计算（当前默认）。「跨线段」允许中枢跨越线段边界。「自动」按有没有已确认线段自动切换。",
       "全部结构 → 全部买卖点",
       subtype="中枢",
       choices=["normal", "over_seg", "auto"],
       choice_labels={"normal": "标准（线段内）", "over_seg": "跨线段", "auto": "自动选择"}),
    _p("macd.fast", "MACD 快线周期", GROUP_STRUCTURE, "integer",
       "MACD 指标里短周期的那条线算几根 K 线。",
       "调小 = 反应更快、更敏感，柱子波动更大，力气对比的数值随之变化。改它会间接改变一买的判定。",
       "笔与线段的力度数值 → 一买/一卖、盘整背驰",
       subtype="MACD",
       min_value=1, step=1),
    _p("macd.slow", "MACD 慢线周期", GROUP_STRUCTURE, "integer",
       "MACD 指标里长周期的那条线算几根 K 线。",
       "调大 = 更平滑、更迟钝。改它同样会间接改变力气对比的结果。",
       "笔与线段的力度数值 → 一买/一卖、盘整背驰",
       subtype="MACD",
       min_value=1, step=1),
    _p("macd.signal", "MACD 信号线周期", GROUP_STRUCTURE, "integer",
       "MACD 里对快慢线差值再做一次平滑的周期。",
       "调大 = 更平滑。调小 = 更灵敏。主要影响柱子的形状，改它会轻微改变力气对比的数值。",
       "笔与线段的力度数值 → 一买/一卖、盘整背驰",
       subtype="MACD",
       min_value=1, step=1),

    # ================= 条件项（仅 macd_algo=rsi 时出现）=================
    _p("cal_rsi", "计算 RSI 指标", GROUP_STRUCTURE, "bool",
       "力度对比选用 RSI 时，必须先让系统为每根 K 线算出 RSI 值。",
       "选 RSI 作为力度算法时本项会被自动打开，关闭它会导致计算失败。",
       "只在使用 RSI 算法时相关",
       subtype="RSI",
       conditional=True,
       visible_when={"macd_algo": "rsi"},
       caveat="选 RSI 算法时系统强制开启，无需手动调整。"),
    _p("rsi_cycle", "RSI 周期", GROUP_STRUCTURE, "integer",
       "RSI 指标回看多少根 K 线来算强弱。",
       "调小 = 更敏感。调大 = 更平滑。只在使用 RSI 作为力度算法时生效。",
       "只在使用 RSI 算法时相关",
       subtype="RSI",
       min_value=1, step=1,
       conditional=True,
       visible_when={"macd_algo": "rsi"}),
]


# ----------------------------------------------------------------------
# 默认值反射（design D2：不硬编码）
# ----------------------------------------------------------------------

# 配置 key → 内核对象上的属性路径。默认值与 key 同名的项不必列出。
_ATTR_PATH = {
    "bi_strict": ("bi_conf", "is_strict"),
    "bi_algo": ("bi_conf", "bi_algo"),
    "bi_fx_check": ("bi_conf", "bi_fx_check"),
    "gap_as_kl": ("bi_conf", "gap_as_kl"),
    "bi_end_is_peak": ("bi_conf", "bi_end_is_peak"),
    "bi_allow_sub_peak": ("bi_conf", "bi_allow_sub_peak"),
    "seg_algo": ("seg_conf", "seg_algo"),
    "left_seg_method": ("seg_conf", "left_method"),
    "zs_combine": ("zs_conf", "need_combine"),
    "zs_combine_mode": ("zs_conf", "zs_combine_mode"),
    "one_bi_zs": ("zs_conf", "one_bi_zs"),
    "zs_algo": ("zs_conf", "zs_algo"),
    "macd_algo": ("bs_point_conf", "b_conf", "macd_algo"),
    "cal_rsi": (None, "cal_rsi"),
    "rsi_cycle": (None, "rsi_cycle"),
    "macd.fast": ("macd_config", "fast"),
    "macd.slow": ("macd_config", "slow"),
    "macd.signal": ("macd_config", "signal"),
}


def _enum_to_str(v: Any) -> Any:
    """枚举 → 小写字符串（与配置字典的写法一致）。"""
    if hasattr(v, "name") and hasattr(v, "value"):
        return v.name.lower()
    return v


def _read_default(conf, key: str) -> Any:
    """从 `CChanConfig` 实例读某个配置 key 的默认值。

    取值路径统一由 `_ATTR_PATH` 描述；`None` 作为首段表示「直接在 CChanConfig 上」。
    """
    if key == "bs_type":
        b = conf.bs_point_conf.b_conf
        tmp = b.tmp_target_types
        if isinstance(tmp, str):
            return [t.strip() for t in tmp.split(",") if t.strip()]
        return [t.value if hasattr(t, "value") else str(t) for t in (tmp or [])]

    path = _ATTR_PATH.get(key)
    if path is None:
        # 未登记 = 买卖点配置项，属性在 `bs_point_conf.b_conf` 上（与 key 同名）
        b_conf = conf.bs_point_conf.b_conf
        if not hasattr(b_conf, key):
            raise KeyError(f"未登记默认值取值路径的配置项: {key}")
        return _enum_to_str(getattr(b_conf, key))

    if path[0] is None:
        obj = conf
        rest = path[1:]
    else:
        obj = conf
        rest = path
    for part in rest:
        obj = obj[part] if isinstance(obj, dict) else getattr(obj, part)
    return _enum_to_str(obj)


def probe_choice(key: str, value: Any) -> bool:
    """用构造期探测判断某个 `(key, value)` 组合内核是否接受。

    这是元数据与内核保持一致的唯一手段：合法取值不在本模块复制一份白名单，
    而是直接问内核。内核改动（新增/移除枚举取值）后本函数的结果自动跟随。
    """
    from ChanAnalyse.ChanConfig import CChanConfig

    try:
        CChanConfig({key: value})
        return True
    except Exception:
        return False


def _collapse_choices(spec: dict) -> list:
    """按构造期探测把 `choices` 候选池收敛为内核当前接受的取值。

    保持候选池原有顺序；若探测把所有候选都剔除（极端情况），原样返回候选池，
    避免界面出现空下拉（此时保存会被后端 422 拦住，不会静默写坏配置）。
    """
    if not spec.get("probe_choices"):
        return spec["choices"] or []
    accepted = [v for v in spec["choices"] if probe_choice(spec["key"], v)]
    return accepted or list(spec["choices"])


def build_schema(conf=None) -> dict:
    """生成前端消费的完整元数据。

    参数：
        conf: `CChanConfig` 实例；缺省时新建一个（即「内核默认」）。

    返回：
        `{"groups": [...], "params": [...], "presets": [...], "counts": {...},
           "kernel_defaults": {key: 值}, "preset_baselines": {档位: {key: 值}}}`

    每个 param 含 `default`（**当前生效口径**下该项的值）与 `caveat`。
    `probe_choices=True` 的参数，其 `choices` 已按内核构造期探测收敛。

    三份默认值语义不同，**别混用**：
        - `params[].default` —— 传入 `conf`（即当前已保存配置）反射出的值。
          界面上「这一项现在是多少」用它；用户改过配置后它会跟着变。
        - `kernel_defaults` —— **内核出厂默认**（`CChanConfig()` 空构造），
          永远不随用户配置漂移。此时 `bsp_preset=standard`，预设展开为空，
          因此它等价于「standard 档的基线」。
        - `preset_baselines[档位]` —— 该档位**预设展开后**的默认值
          （`CChanConfig({"bsp_preset": 档位})`）。`legacy` 与 `standard`
          在 `min_zs_cnt` / `bsp1_trend` / `macd_algo` 等十几项上不同。

    前端判断「某项是否被用户显式改过」、以及「恢复默认恢复到什么」，必须用
    `preset_baselines[当前档位]`（缺失时退回 `kernel_defaults`）：
        - 用 `params[].default` 会漂移 —— 用户改 A 项保存后它等于 A 的新值，
          下次只改 B 项保存时 A 被判成「没改过」而踢出 overrides → A 的改动
          静默丢失。
        - 用 `kernel_defaults` 会吃掉档位 —— legacy 档下预设展开的那些项
          （如 `min_zs_cnt=1`）会被当成用户覆盖写进 overrides，从此不再跟随
          档位切换，档位机制形同虚设。
    """
    from ChanAnalyse.ChanConfig import CChanConfig, _BSP_PRESETS

    conf = conf or CChanConfig()

    params = []
    for spec in PARAMS:
        item = dict(spec)
        item["default"] = _read_default(conf, spec["key"])
        if spec.get("probe_choices"):
            item["choices"] = _collapse_choices(spec)
            item["choice_labels"] = {
                k: v for k, v in (spec.get("choice_labels") or {}).items()
                if k in item["choices"]
            }
        if spec["key"] == "macd_algo" and item["choices"]:
            item["choice_caveats"] = {
                algo: (
                    "线段级别没有量能版本，系统会在线段级别自动改用峰值算法"
                    if algo in VOLUME_MACD_ALGOS
                    else "系统会自动开启 RSI 指标计算"
                    if algo == "rsi"
                    else ""
                )
                for algo in item["choices"]
            }
        params.append(item)

    # 各档位展开后的默认值（含内核默认本身）
    preset_baselines = {}
    for preset_name in _BSP_PRESETS:
        try:
            preset_conf = CChanConfig({"bsp_preset": preset_name})
            preset_baselines[preset_name] = {
                spec["key"]: _read_default(preset_conf, spec["key"])
                for spec in PARAMS
            }
        except Exception:      # 某档位反射失败时跳过，前端会退回 kernel_defaults
            log.warning("档位 %s 的默认值反射失败，跳过", preset_name)

    # 内核出厂默认 = standard 档基线（standard 预设展开为空）
    kernel_defaults = preset_baselines.get("standard") or {
        p["key"]: p["default"] for p in params
    }

    groups = []
    for gid, gm in GROUP_META.items():
        members = [p for p in params if p["group"] == gid and not p["conditional"]]
        groups.append({
            "id": gid,
            "title": gm["title"],
            "hint": gm["hint"],
            "collapsed_by_default": gm["collapsed_by_default"],
            "count": len(members),
        })

    return {
        "groups": groups,
        "params": params,
        "presets": sorted(_BSP_PRESETS.keys()),
        "counts": {
            "total": len(params),
            "unconditional": sum(1 for p in params if not p["conditional"]),
            "conditional": sum(1 for p in params if p["conditional"]),
        },
        "kernel_defaults": kernel_defaults,
        "preset_baselines": preset_baselines,
    }
