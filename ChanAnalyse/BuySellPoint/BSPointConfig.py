# -*- coding: utf-8 -*-
"""
买卖点配置模块 - 买卖点计算的各项参数配置

Java 开发者注意：
- **args 是 Python 的关键字参数收集，类似于 Java 的 Map<String, Object>
  Java 对比：没有直接对应，通常用 Builder 模式实现
- exec() 是 Python 的动态执行函数，类似于 Java 的 ScriptEngine.eval()
  Java 对比：Java 没有直接对应的内置函数，需要用脚本引擎
- _parse_inf 用于处理无穷大值（float('inf')），使 eval() 能正确处理
"""

from typing import Dict, List, Optional

from ChanAnalyse.Common.CEnum import BSP_TYPE, MACD_ALGO
from ChanAnalyse.Common.ChanException import CChanException, ErrCode
from ChanAnalyse.Common.func_util import _parse_inf


class CBSPointConfig:
    """
    买卖点配置 - 包含买入和卖出两套配置

    属性说明：
    - b_conf: 买入配置
    - s_conf: 卖出配置

    买卖点类型：
    - T1: 第一类买卖点（中枢背驰）
    - T1P: 盘整背驰买卖点（无中枢的背驰）
    - T2: 第二类买卖点（回测中枢）
    - T2S: 类二买卖点（中枢内的二次回测）
    - T3A: 第三类买卖点（中枢之后）
    - T3B: 第三类买卖点（中枢之前）
    """

    def __init__(self, **args):
        """
        初始化买卖点配置

        Python 语法：**args 收集所有关键字参数
        Java 对比：类似于可变参数 Map<String, Object>
        """
        self.b_conf = CPointConfig(**args)
        self.s_conf = CPointConfig(**args)

    def GetBSConfig(self, is_buy):
        """
        获取买卖点配置

        参数:
            is_buy: True=买入配置，False=卖出配置

        返回:
            CPointConfig 配置对象
        """
        return self.b_conf if is_buy else self.s_conf


class CPointConfig:
    """
    买卖点参数配置

    属性说明：
    - divergence_rate: 背驰率阈值（<1 表示离开笔力度小于进入笔）
    - min_zs_cnt: 最小中枢数量（用于第一类买卖点）
    - bsp1_only_multibi_zs: 是否只考虑多笔中枢
    - max_bs2_rate: 第二类买卖点的最大回撤率
    - macd_algo: 背驰判断的 MACD 算法
    - bs1_peak: 第一类买卖点是否要求极值
    - target_types: 目标买卖点类型列表
    - bsp2_follow_1: 第二类买卖点是否必须跟随第一类
    - bsp3_follow_1: 第三类买卖点是否必须跟随第一类
    - bsp3_peak: 第三类买卖点是否要求极值
    - bsp2s_follow_2: 类二买卖点是否必须跟随第二类
    - max_bsp2s_lv: 类二买卖点的最大层级
    - strict_bsp3: 严格第三类买卖点模式
    - bsp3a_max_zs_cnt: 第三类A买卖点最多检查的中枢数（下一条线段内）
    - bsp1_trend: 第一类买卖点是否要求趋势前提（两中枢依次下移/上移）
    - bsp1_new_extreme: 第一类买卖点是否要求离开段创趋势新低/新高
    - bsp1_dif_div: 第一类买卖点是否要求 DIF（黄白线）背驰
    - bsp1_zero_axis: 第一类买卖点是否要求 b/c 段之间 DIF 回抽过零轴
    - bsp1_trend_mode: 趋势判定口径（strict/overlap）
    - bsp1_new_extreme_mode: 新低比较起点口径（trend_start/prev_zs_in/all）
    - bsp1_zs_extend_to_seg_end: 是否仍要求中枢延伸到线段末笔（历史 4.8 条件）
    - bsp2_retrace_zs: 二买回调是否要求与中枢区间关联
    - bsp2s_require_zs: 类二是否要求末端价格落在中枢区间内
    - bsp2s_rate_mode: 类二回撤率量纲（amp/disp）
    - bsp3b_mode: 三买B 判定档位（standard/legacy）
    - bsp3_peak_on_breakout: bsp3_peak 判据对象是否为突破笔（True）/回抽笔（False）
    - bsp3_follow_1_mode: 三买跟随一买的口径（sure/candidate）
    - bsp1_downgrade_to_pz: 趋势前提不达标但背驰链路成立时是否降级为 T1P 登记（而非丢弃）；
      降级点固定 is_target_bsp=False，不进 bsp1_sure_dict，不作二买/三买锚点
    - bsp1_force_scope: 一买力度比较的取值窗口口径。`"swing"`（默认）= 走势段——
      b 窗口为「上一中枢结束笔+1 ~ 中枢进入笔」、c 窗口为「离开笔 ~ 线段末笔」，
      整段聚合力度；`"bi"` = 单笔——沿用改造前的 `get_bi_in()` / `out_bi` 单笔比较。
      注意：成交量/换手率类算法（volumn/amount/volumn_avg/amount_avg/turnrate_avg）
      没有区间版本，在 `"swing"` 档下自动退回单笔口径并在 feature 标
      `bsp1_force_scope_effective="bi_fallback"`
    - bsp1_qjt: 区间套特征开关（默认 False）。开启后为一买候选点计算「c 走势段内
      是否存在次级别同向已确认一买」，结果写入 feature_dict 的 `bsp1_qjt_hit` /
      `bsp1_qjt_sub_idx`。**这是特征不是判据**——不改 is_target_bsp，不改变任何
      买卖点的成立性与数量
    - bsp1_qjt_depth: 区间套递归深度（默认 1 层）。多层会成倍放大「子级确认滞后」
      导致的步进/批量口径分叉，默认收敛一层
    - bsp2_confirm_window: T2 确认轴的考察窗口笔数（1/2，默认 2——实证定标，
      《文档/二买确认轴实证报告.md》0.1）。窗口只决定考察范围，不影响终态语义
    - bsp2_time_axis_strong: T2 时间轴速度比的强档阈值（默认 0.5，v<=该值为强档
      「急涨缓跌」）。方向假设未获实证支持（报告 0.2），阈值维持默认待复验
    - bsp2_time_axis_weak: T2 时间轴速度比的弱档阈值（默认 1.0，v>该值为弱档
      「缓涨急跌」）
    - bsp2_confirm_level: 确认轴阈值口径。strong = 后续笔突破 break_bi 端点
      （默认）；weak = 收复 break_bi 振幅一半以上即算确认
    - bsp3_confirm_window: T3 确认轴的考察窗口笔数（1/2，默认 2）。三买确认轴
      评估缠论要素 E「回抽结束后趋势延续」——**事后确认层，不是成立判据**
      （chan-standard-bsp3-change D5：做成判据会引入未来函数、信号后移）
    - bsp3_confirm_level: T3 确认轴阈值口径。strong = 后续笔突破回抽笔端点
      （默认）；weak = 收复回抽幅度一半以上即算确认
    - bsp3_time_axis_strong / bsp3_time_axis_weak: T3 时间轴速度比阈值
      （默认 0.5 / 1.0，与 T2 同门槛；实证后校准）
    - bsp_preset: 档位预设名（standard/legacy），仅用于文档与诊断，不参与判定
    """

    def __init__(self,
                 divergence_rate,
                 min_zs_cnt,
                 bsp1_only_multibi_zs,
                 max_bs2_rate,
                 macd_algo,
                 bs1_peak,
                 bs_type,
                 bsp2_follow_1,
                 bsp3_follow_1,
                 bsp3_peak,
                 bsp2s_follow_2,
                 max_bsp2s_lv,
                 strict_bsp3,
                 bsp3a_max_zs_cnt,
                 bsp1_trend=False,
                 bsp1_new_extreme=False,
                 bsp1_dif_div=False,
                 bsp1_zero_axis=False,
                 bsp1_trend_mode="strict",
                 bsp1_new_extreme_mode="trend_start",
                 bsp1_zs_extend_to_seg_end=True,
                 bsp2_retrace_zs=False,
                 bsp2s_require_zs=True,
                 bsp2s_rate_mode="amp",
                 bsp3b_mode="standard",
                 bsp3_peak_on_breakout=True,
                 bsp3_follow_1_mode="sure",
                 bsp1_downgrade_to_pz=True,
                 bsp1_force_scope="swing",
                 bsp1_qjt=False,
                 bsp1_qjt_depth=1,
                 bsp2_confirm_window=2,
                 bsp2_time_axis_strong=0.5,
                 bsp2_time_axis_weak=1.0,
                 bsp2_confirm_level="strong",
                 bsp3_confirm_window=2,
                 bsp3_confirm_level="strong",
                 bsp3_time_axis_strong=0.5,
                 bsp3_time_axis_weak=1.0,
                 bsp_preset="standard",
                 ):
        self.divergence_rate = divergence_rate
        self.min_zs_cnt = min_zs_cnt
        self.bsp1_only_multibi_zs = bsp1_only_multibi_zs
        self.max_bs2_rate = max_bs2_rate
        assert self.max_bs2_rate <= 1
        self.SetMacdAlgo(macd_algo)
        self.bs1_peak = bs1_peak
        self.tmp_target_types = bs_type
        self.target_types: List[BSP_TYPE] = []
        self.bsp2_follow_1 = bsp2_follow_1
        self.bsp3_follow_1 = bsp3_follow_1
        self.bsp3_peak = bsp3_peak
        self.bsp2s_follow_2 = bsp2s_follow_2
        self.max_bsp2s_lv: Optional[int] = max_bsp2s_lv
        self.strict_bsp3 = strict_bsp3
        self.bsp3a_max_zs_cnt = bsp3a_max_zs_cnt
        assert self.bsp3a_max_zs_cnt >= 1

        # ---- 第一类买卖点标准判据开关 ----
        self.bsp1_trend = bsp1_trend
        self.bsp1_new_extreme = bsp1_new_extreme
        self.bsp1_dif_div = bsp1_dif_div
        self.bsp1_zero_axis = bsp1_zero_axis
        self.bsp1_trend_mode = self._check_choice(
            "bsp1_trend_mode", bsp1_trend_mode, ("strict", "overlap"))
        self.bsp1_new_extreme_mode = self._check_choice(
            "bsp1_new_extreme_mode", bsp1_new_extreme_mode, ("trend_start", "prev_zs_in", "all"))
        self.bsp1_zs_extend_to_seg_end = bsp1_zs_extend_to_seg_end

        # ---- 第二类 / 类二标准判据开关 ----
        self.bsp2_retrace_zs = bsp2_retrace_zs
        self.bsp2s_require_zs = bsp2s_require_zs
        self.bsp2s_rate_mode = self._check_choice(
            "bsp2s_rate_mode", bsp2s_rate_mode, ("amp", "disp"))

        # ---- 第三类标准判据开关 ----
        self.bsp3b_mode = self._check_choice(
            "bsp3b_mode", bsp3b_mode, ("standard", "legacy"))
        self.bsp3_peak_on_breakout = bsp3_peak_on_breakout
        self.bsp3_follow_1_mode = self._check_choice(
            "bsp3_follow_1_mode", bsp3_follow_1_mode, ("sure", "candidate"))

        # ---- 降级路由：趋势不达标但背驰链路成立时以 T1P 登记（chan-standard-bsp1-change）----
        self.bsp1_downgrade_to_pz = bsp1_downgrade_to_pz

        # ---- 一买力度口径：走势段（默认）/ 单笔（§4.4 修复）----
        # 非法值在构造期即抛异常，不静默回退——否则「看起来配了但不生效」
        self.bsp1_force_scope = self._check_choice(
            "bsp1_force_scope", bsp1_force_scope, ("bi", "swing"))

        # ---- 区间套特征（§4.6）：默认关闭，只写特征不改成立性 ----
        self.bsp1_qjt = bsp1_qjt
        if not isinstance(bsp1_qjt_depth, int) or isinstance(bsp1_qjt_depth, bool) \
                or bsp1_qjt_depth < 1:
            raise CChanException(
                f"bsp1_qjt_depth={bsp1_qjt_depth!r} 非法，必须是 >= 1 的整数",
                ErrCode.PARA_ERROR)
        self.bsp1_qjt_depth = bsp1_qjt_depth

        # ---- T2 阶梯五轴（chan-standard-bsp2-change）----
        # 确认窗口：1 或 2 笔。实证（报告 0.1）定默认 2。
        if bsp2_confirm_window not in (1, 2):
            raise CChanException(
                f"bsp2_confirm_window={bsp2_confirm_window!r} 非法，可选值：1, 2",
                ErrCode.PARA_ERROR)
        self.bsp2_confirm_window = bsp2_confirm_window
        # 时间轴阈值：强档线必须低于弱档线（否则档位划分无意义）
        if not (0 < bsp2_time_axis_strong < bsp2_time_axis_weak):
            raise CChanException(
                f"bsp2_time_axis 阈值非法：strong={bsp2_time_axis_strong!r} "
                f"必须为正且小于 weak={bsp2_time_axis_weak!r}", ErrCode.PARA_ERROR)
        self.bsp2_time_axis_strong = bsp2_time_axis_strong
        self.bsp2_time_axis_weak = bsp2_time_axis_weak
        # 确认轴阈值口径：strong（破 break_bi 端点）/ weak（收复一半）
        self.bsp2_confirm_level = self._check_choice(
            "bsp2_confirm_level", bsp2_confirm_level, ("strong", "weak"))

        # ---- T3 阶梯四轴（chan-standard-bsp3-change）----
        # 确认窗口：1 或 2 笔。与 T2 同档默认 2（末端候选标 C0 而非误判终态）
        if bsp3_confirm_window not in (1, 2):
            raise CChanException(
                f"bsp3_confirm_window={bsp3_confirm_window!r} 非法，可选值：1, 2",
                ErrCode.PARA_ERROR)
        self.bsp3_confirm_window = bsp3_confirm_window
        # 时间轴阈值：强档线必须低于弱档线（否则档位划分无意义）
        if not (0 < bsp3_time_axis_strong < bsp3_time_axis_weak):
            raise CChanException(
                f"bsp3_time_axis 阈值非法：strong={bsp3_time_axis_strong!r} "
                f"必须为正且小于 weak={bsp3_time_axis_weak!r}", ErrCode.PARA_ERROR)
        self.bsp3_time_axis_strong = bsp3_time_axis_strong
        self.bsp3_time_axis_weak = bsp3_time_axis_weak
        # 确认轴阈值口径：strong（突破回抽笔端点）/ weak（收复一半即算确认）
        self.bsp3_confirm_level = self._check_choice(
            "bsp3_confirm_level", bsp3_confirm_level, ("strong", "weak"))

        # 仅用于诊断与文档标注，不参与任何判定
        self.bsp_preset = bsp_preset

    @staticmethod
    def _check_choice(name, value, choices):
        """
        枚举型配置的取值白名单校验

        放在配置对象构造期而非判定期，使错误在 `CChanConfig(...)` 时立即暴露，
        而不是等到计算到某个股票的第 N 个线段才抛异常。
        """
        if value not in choices:
            raise CChanException(
                f"{name}={value!r} 非法，可选值：{', '.join(choices)}", ErrCode.PARA_ERROR)
        return value

    def parse_target_type(self):
        """
        解析目标买卖点类型

        将字符串配置（如 "1,2,3a"）转换为 BSP_TYPE 枚举列表。
        仅在运行时调用一次。

        Python 语法：字典推导式 {x.value: x for x in BSP_TYPE}
        Java 对比：stream.collect(Collectors.toMap(BSP_TYPE::getValue, Function.identity()))
        """
        _d: Dict[str, BSP_TYPE] = {x.value: x for x in BSP_TYPE}
        if isinstance(self.tmp_target_types, str):
            self.tmp_target_types = [t.strip() for t in self.tmp_target_types.split(",")]
        for target_t in self.tmp_target_types:
            assert target_t in ['1', '2', '3a', '2s', '1p', '3b']
        self.target_types = [_d[_type] for _type in self.tmp_target_types]

    def SetMacdAlgo(self, macd_algo):
        """设置 MACD 算法（字符串 → 枚举）"""
        _d = {
            "area": MACD_ALGO.AREA,
            "peak": MACD_ALGO.PEAK,
            "full_area": MACD_ALGO.FULL_AREA,
            "diff": MACD_ALGO.DIFF,
            "slope": MACD_ALGO.SLOPE,
            "amp": MACD_ALGO.AMP,
            "amount": MACD_ALGO.AMOUNT,
            "volumn": MACD_ALGO.VOLUMN,
            "amount_avg": MACD_ALGO.AMOUNT_AVG,
            "volumn_avg": MACD_ALGO.VOLUMN_AVG,
            "turnrate_avg": MACD_ALGO.TURNRATE_AVG,
            "rsi": MACD_ALGO.RSI,
            "diff_peak": MACD_ALGO.DIFF_PEAK,
        }
        self.macd_algo = _d[macd_algo]

    def set(self, k, v):
        """动态设置属性（用于运行时配置，后缀覆盖 -buy/-sell/-seg… 走此路径）。

        直接 `setattr` 而非 exec 拼字符串：`CChanConfig.set_bsp_config` 的调用方
        已经决定了值的 Python 形态（字符串会自带引号、inf 走 `_parse_inf`），
        这里再拼一次会双重解释——历史上 `set("bsp3b_mode", '"legacy"')` 的引号
        在内层 exec 里被剥掉，得到 `self.bsp3b_mode = legacy` → NameError；
        `"all"` 更危险，会静默绑定到 Python 内置函数 `all` 而不报错。
        """
        v = _parse_inf(v)
        if k == "macd_algo":
            self.SetMacdAlgo(v)
        else:
            setattr(self, k, v)