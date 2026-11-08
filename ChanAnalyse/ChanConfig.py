# -*- coding: utf-8 -*-
"""
ChanConfig 配置模块 - 管理缠论分析的所有配置参数

Java 开发者注意：
- Python 的 dict.get(k, default) 类似于 Java 的 map.getOrDefault(k, default)
- Python 的 exec() 是动态执行字符串代码，类似于 Java 的 ScriptEngine.eval()
  Java 对比：Java 没有直接的 exec()，需要借助 ScriptEngine 或反射
- Python 的 **args 是字典解包，类似于将 Map 展开为命名参数
  Java 对比：Java 没有直接对应，通常需要通过 Builder 模式逐参数设置
- Python 的 isinstance(v, str) 是类型检查，类似于 Java 的 v instanceof String
- Python 的 yield 是生成器函数，返回一个惰性迭代器
  Java 对比：Java 没有 yield 关键字，需要手动实现 Iterator 接口
- Python 的 | 在类型注解中表示联合类型（Python 3.10+）
  Java 对比：类似于 Java 的泛型通配符或方法重载
"""

from typing import List

from ChanAnalyse.Bi.BiConfig import CBiConfig
from ChanAnalyse.BuySellPoint.BSPointConfig import CBSPointConfig
from ChanAnalyse.Common.CEnum import TREND_TYPE
from ChanAnalyse.Common.ChanException import CChanException, ErrCode
from ChanAnalyse.Common.func_util import _parse_inf
from ChanAnalyse.Math.BOLL import BollModel
from ChanAnalyse.Math.Demark import CDemarkEngine
from ChanAnalyse.Math.KDJ import KDJ
from ChanAnalyse.Math.MACD import CMACD
from ChanAnalyse.Math.RSI import RSI
from ChanAnalyse.Math.TrendModel import CTrendModel
from ChanAnalyse.Seg.SegConfig import CSegConfig
from ChanAnalyse.ZS.ZSConfig import CZSConfig

# 买卖点档位预设
#
# 设计要点：预设只展开为一组「默认值」，用户的显式 key 仍在之后覆盖。
# 因此 `bsp_preset="legacy"` 可一键复现改造前的行为，
# 而 `bsp_preset="legacy"` + 单项 `bsp1_zero_axis=True` 只让该项生效。
#
# `legacy` 的目标是**逐笔逐类型**复现改造前输出，所以除了判据开关，
# 还必须把 `divergence_rate` / `min_zs_cnt` 以及类二、三买B 的口径一并回退。
_BSP_PRESETS = {
    "standard": {},
    "legacy": {
        "divergence_rate": float("inf"),
        "min_zs_cnt": 1,
        "bsp1_trend": False,
        "bsp1_new_extreme": False,
        "bsp1_dif_div": False,
        "bsp1_zero_axis": False,
        "bsp1_zs_extend_to_seg_end": True,
        "bsp2_retrace_zs": False,
        "bsp2s_require_zs": False,
        "bsp2s_rate_mode": "disp",
        "bsp3b_mode": "legacy",
        "bsp3_peak_on_breakout": False,
        # 降级路由：legacy 下 bsp1_trend=False，趋势判据关闭 → reason 永不为 'trend'，
        # 降级本来就不触发；显式写入是防御性的（防止将来单独放开 bsp1_trend 时口径意外变化）
        "bsp1_downgrade_to_pz": False,
        # 力度口径：legacy 下 divergence_rate=inf 走 >100 分支、根本不计算 metric，
        # 显式写 "bi" 是防御性的（防止将来单独放开背驰时口径意外变化）
        "bsp1_force_scope": "bi",
        # 力度算法：legacy 逐笔等价的必要条件（chan-bsp1-extreme）。默认档已改为
        # full_area，不显式写回 "peak" 就会偏离 258/69/318/317/61/50 基线。
        "macd_algo": "peak",
        # 极值严格性：legacy 用宽松口径。standard 档自 chan-bsp1-loose-extreme
        # 起同为 False（严格优不再是产品口径），此处保留显式写入，防止将来
        # 有人把 standard 改回严格时 legacy 跟着漂移。
        "bs1_peak_strict": False,
        # 区间套特征：默认已 False，显式写入防止将来单独调 legacy 判据开关时
        # 被特征字段污染等价性基线
        "bsp1_qjt": False,
    },
}


class CChanConfig:
    """
    缠论主配置类 - 集中管理所有子模块的配置参数

    参数:
        conf: 配置字典，key 为配置项名称，value 为配置值

    配置项包括：
    - 笔配置（bi_algo, bi_strict, bi_fx_check 等）
    - 线段配置（seg_algo, left_seg_method）
    - 中枢配置（zs_combine, zs_combine_mode, zs_algo 等）
    - 买卖点配置（divergence_rate, bs_type 等）
    - 指标配置（macd, rsi, kdj, boll, demark 等）
    - 数据校验配置（kl_data_check, max_kl_misalgin_cnt 等）

    缠论知识 - 配置参数对分析的影响：
    - bi_algo: 笔的算法选择，normal=标准笔，fx=分型笔
    - seg_algo: 线段算法，chan=特征序列法（默认），def=定义法，dyh=都业华法
    - zs_algo: 中枢算法，normal=标准中枢，over_seg=段内中枢，auto=自动
    - left_seg_method: 左侧线段处理方法，peak=峰值法，avg=平均法
    """

    def __init__(self, conf=None):
        if conf is None:
            conf = {}
        conf = ConfigWithCheck(conf)  # 包装为带校验的配置对象

        # ========== 笔配置 ==========
        self.bi_conf = CBiConfig(
            bi_algo=conf.get("bi_algo", "normal"),
            is_strict=conf.get("bi_strict", True),
            bi_fx_check=conf.get("bi_fx_check", "strict"),
            gap_as_kl=conf.get("gap_as_kl", False),
            bi_end_is_peak=conf.get('bi_end_is_peak', True),
            bi_allow_sub_peak=conf.get("bi_allow_sub_peak", True),
        )

        # ========== 线段配置 ==========
        self.seg_conf = CSegConfig(
            seg_algo=conf.get("seg_algo", "chan"),
            left_method=conf.get("left_seg_method", "peak"),
        )

        # ========== 中枢配置 ==========
        self.zs_conf = CZSConfig(
            need_combine=conf.get("zs_combine", True),
            zs_combine_mode=conf.get("zs_combine_mode", "zs"),
            one_bi_zs=conf.get("one_bi_zs", False),
            zs_algo=conf.get("zs_algo", "normal"),
        )

        # ========== 回放/步进模式 ==========
        self.trigger_step = conf.get("trigger_step", False)
        self.skip_step = conf.get("skip_step", 0)

        # ========== 数据校验配置 ==========
        self.kl_data_check = conf.get("kl_data_check", True)
        self.max_kl_misalgin_cnt = conf.get("max_kl_misalgin_cnt", 2)
        self.max_kl_inconsistent_cnt = conf.get("max_kl_inconsistent_cnt", 5)
        self.auto_skip_illegal_sub_lv = conf.get("auto_skip_illegal_sub_lv", False)
        self.print_warning = conf.get("print_warning", True)
        self.print_err_time = conf.get("print_err_time", True)

        # ========== 指标配置 ==========
        self.mean_metrics: List[int] = conf.get("mean_metrics", [])
        self.trend_metrics: List[int] = conf.get("trend_metrics", [])
        self.macd_config = conf.get("macd", {"fast": 12, "slow": 26, "signal": 9})
        self.cal_demark = conf.get("cal_demark", False)
        self.cal_rsi = conf.get("cal_rsi", False)
        self.cal_kdj = conf.get("cal_kdj", False)
        self.rsi_cycle = conf.get("rsi_cycle", 14)
        self.kdj_cycle = conf.get("kdj_cycle", 9)
        self.demark_config = conf.get("demark", {
            'demark_len': 9,
            'setup_bias': 4,
            'countdown_bias': 2,
            'max_countdown': 13,
            'tiaokong_st': True,
            'setup_cmp2close': True,
            'countdown_cmp2close': True,
        })
        self.boll_n = conf.get("boll_n", 20)

        # ========== 买卖点配置 ==========
        self.set_bsp_config(conf)

        # 校验：确保没有未识别的配置项
        conf.check()

    def GetMetricModel(self):
        """
        根据配置创建所有指标计算模型实例

        返回:
            List[指标模型] 包含 MACD、均线、趋势通道、布林带、Demark、RSI、KDJ 等

        每个指标模型都是可调用的，在 K 线更新时计算对应的指标值。

        Python 特性：列表推导式 extend 和 append 混合使用
        - res.extend(CTrendModel(...) for mean_T in ...) 是生成器表达式
          Java 对比：类似于 for (int mean_T : mean_metrics) res.add(new CTrendModel(...))
        """
        res: List[CMACD | CTrendModel | BollModel | CDemarkEngine | RSI | KDJ] = [
            CMACD(
                fastperiod=self.macd_config['fast'],
                slowperiod=self.macd_config['slow'],
                signalperiod=self.macd_config['signal'],
            )
        ]
        # 添加均线指标（如 5/10/20/60 日均线）
        res.extend(CTrendModel(TREND_TYPE.MEAN, mean_T) for mean_T in self.mean_metrics)

        # 添加趋势通道指标（MAX 和 MIN 成对出现）
        for trend_T in self.trend_metrics:
            res.append(CTrendModel(TREND_TYPE.MAX, trend_T))
            res.append(CTrendModel(TREND_TYPE.MIN, trend_T))
        res.append(BollModel(self.boll_n))
        if self.cal_demark:
            res.append(CDemarkEngine(
                demark_len=self.demark_config['demark_len'],
                setup_bias=self.demark_config['setup_bias'],
                countdown_bias=self.demark_config['countdown_bias'],
                max_countdown=self.demark_config['max_countdown'],
                tiaokong_st=self.demark_config['tiaokong_st'],
                setup_cmp2close=self.demark_config['setup_cmp2close'],
                countdown_cmp2close=self.demark_config['countdown_cmp2close'],
            ))
        if self.cal_rsi:
            res.append(RSI(self.rsi_cycle))
        if self.cal_kdj:
            res.append(KDJ(self.kdj_cycle))
        return res

    def set_bsp_config(self, conf):
        """
        设置买卖点配置

        参数:
            conf: 配置字典

        处理逻辑：
        1. 设置默认买卖点参数
        2. 创建笔级别的买卖点配置（bs_point_conf）和线段级别的买卖点配置（seg_bs_point_conf）
        3. 线段级别默认使用 slope 算法（而非 peak 算法）
        4. 通过后缀识别配置项的作用范围：
           - "-buy" 后缀 → 仅买入点
           - "-sell" 后缀 → 仅卖出点
           - "-segbuy" 后缀 → 仅线段买入点
           - "-segsell" 后缀 → 仅线段卖出点
           - "-seg" 后缀 → 线段买卖点通用
           - 无后缀 → 笔级别买卖点通用

        Python 特性：exec() 动态执行代码
        - exec(f"self.bs_point_conf.b_conf.set('{prop}', {v})") 在运行时动态构建方法调用
          Java 对比：需要使用反射机制 Reflection API 或动态代理
        """
        # 默认参数
        para_dict = {
            "divergence_rate": 0.9,
            "min_zs_cnt": 2,
            "bsp1_only_multibi_zs": True,
            "max_bs2_rate": 0.9999,
            # 力度算法（chan-bsp1-extreme）：整段柱体面积。单根峰值对「急跌赶底」
            # 钝感——跌幅大、时间短的 c 段单根柱子天然更深，即使整段动能已衰竭
            # 也会被判为不背驰。41 只日线横评见 design.md D1。
            "macd_algo": "full_area",
            "bs1_peak": True,
            # 极值严格性（chan-bsp1-loose-extreme）：standard 档已改为宽松口径，
            # 相等极值也算创新高/新低。严格优不再作为用户可配置项，
            # 仅保留 kernel 级能力供历史基线脚本显式 pin。
            "bs1_peak_strict": False,
            "bs_type": "1,1p,2,2s,3a,3b",
            "bsp2_follow_1": True,
            "bsp3_follow_1": True,
            "bsp3_peak": False,
            "bsp2s_follow_2": False,
            "max_bsp2s_lv": None,
            "strict_bsp3": False,
            "bsp3a_max_zs_cnt": 1,
            # 第一类买卖点标准判据
            "bsp1_trend": True,
            "bsp1_new_extreme": True,
            "bsp1_dif_div": True,
            "bsp1_zero_axis": True,
            "bsp1_trend_mode": "strict",
            "bsp1_new_extreme_mode": "trend_start",
            "bsp1_zs_extend_to_seg_end": False,
            # 第二类 / 类二标准判据
            "bsp2_retrace_zs": False,
            "bsp2s_require_zs": True,
            "bsp2s_rate_mode": "amp",
            # 第三类标准判据
            "bsp3b_mode": "standard",
            "bsp3_peak_on_breakout": True,
            "bsp3_follow_1_mode": "sure",
            # 降级路由（chan-standard-bsp1-change）
            "bsp1_downgrade_to_pz": True,
            # 一买力度口径（§4.4）：走势段（默认）/ 单笔
            "bsp1_force_scope": "swing",
            # 区间套特征（§4.6）：默认关闭，只写特征不改成立性
            "bsp1_qjt": False,
            "bsp1_qjt_depth": 1,
            # T2 阶梯五轴（chan-standard-bsp2-change）：确认窗口取 2 笔
            # 为实证定标（《文档/二买确认轴实证报告.md》0.1：窗口 2 把末端
            # 候选标 ongoing 而非误判 strong，比窗口 1 更保守且不误报）
            "bsp2_confirm_window": 2,
            "bsp2_time_axis_strong": 0.5,
            "bsp2_time_axis_weak": 1.0,
            "bsp2_confirm_level": "strong",
            # T3 阶梯四轴（chan-standard-bsp3-change）：确认轴 = 缠论要素 E
            # 的事后确认层（非成立判据）；窗口取 2 笔与 T2 同档（末端候选
            # 标 C0 而非误判终态，更保守）。时间轴阈值沿用 T2 门槛待实证校准。
            "bsp3_confirm_window": 2,
            "bsp3_confirm_level": "strong",
            "bsp3_time_axis_strong": 0.5,
            "bsp3_time_axis_weak": 1.0,
            # 档位预设
            "bsp_preset": "standard",
        }
        # 档位预设展开：先应用预设字典，再让用户显式 key 覆盖
        # 这样 `bsp_preset="legacy"` 能一键回退改造前的行为，
        # 而 `bsp_preset="legacy"` + 单项 `bsp1_zero_axis=True` 只让该项生效。
        preset_name = conf.get("bsp_preset", "standard")
        para_dict["bsp_preset"] = preset_name
        if preset_name not in _BSP_PRESETS:
            raise CChanException(
                f"unknown bsp_preset={preset_name!r}, should be one of "
                f"{', '.join(_BSP_PRESETS)}", ErrCode.PARA_ERROR)
        para_dict.update(_BSP_PRESETS[preset_name])

        # 从 conf 中提取参数，使用默认值填充
        args = {para: conf.get(para, default_value) for para, default_value in para_dict.items()}
        self.bs_point_conf = CBSPointConfig(**args)  # **args 将字典解包为关键字参数

        # 线段级别买卖点配置：算法与笔级别一致，且不要求多笔中枢
        # 历史实现把 macd_algo 硬编码为 slope，导致线段级别无法表达 DIF 背驰与
        # 零轴回抽，标准一买无法在线段级别落地。此处解除硬编码。
        self.seg_bs_point_conf = CBSPointConfig(**args)
        self.seg_bs_point_conf.b_conf.set("bsp1_only_multibi_zs", False)
        self.seg_bs_point_conf.s_conf.set("bsp1_only_multibi_zs", False)

        # 通过后缀识别配置项的作用范围
        for k, v in conf.items():
            if isinstance(v, str):
                v = f'"{v}"'  # 字符串值需要加引号，以便 exec 时作为字符串字面量
            elif isinstance(v, (list, tuple)):
                # 列表值（`macd_algo` 多选、`bs_type`）必须用 repr 落成字面量，
                # 否则 exec 会把 `['a','b']` 当成裸名字而 NameError
                v = repr(list(v))
            v = _parse_inf(v)  # 处理特殊值（如 "inf" → float("inf")）
            if k.endswith("-buy"):
                prop = k.replace("-buy", "")
                exec(f"self.bs_point_conf.b_conf.set('{prop}', {v})")
            elif k.endswith("-sell"):
                prop = k.replace("-sell", "")
                exec(f"self.bs_point_conf.s_conf.set('{prop}', {v})")
            elif k.endswith("-segbuy"):
                prop = k.replace("-segbuy", "")
                exec(f"self.seg_bs_point_conf.b_conf.set('{prop}', {v})")
            elif k.endswith("-segsell"):
                prop = k.replace("-segsell", "")
                exec(f"self.seg_bs_point_conf.s_conf.set('{prop}', {v})")
            elif k.endswith("-seg"):
                prop = k.replace("-seg", "")
                exec(f"self.seg_bs_point_conf.b_conf.set('{prop}', {v})")
                exec(f"self.seg_bs_point_conf.s_conf.set('{prop}', {v})")
            elif k in args:
                exec(f"self.bs_point_conf.b_conf.set({k}, {v})")
                exec(f"self.bs_point_conf.s_conf.set({k}, {v})")
            else:
                raise CChanException(f"unknown para = {k}", ErrCode.PARA_ERROR)

        # 解析买卖点类型字符串（如 "1,1p,2,2s,3a,3b"）
        self.bs_point_conf.b_conf.parse_target_type()
        self.bs_point_conf.s_conf.parse_target_type()
        self.seg_bs_point_conf.b_conf.parse_target_type()
        self.seg_bs_point_conf.s_conf.parse_target_type()


class ConfigWithCheck:
    """
    带校验的配置包装器

    功能：
    1. 记录哪些配置项已被读取
    2. 在最后检查是否有未识别的配置项（防止拼写错误）

    Python 特性：
    - self.conf.get(k, default_value) 类似于 Java 的 Map.getOrDefault
    - del self.conf[k] 删除字典中的键，类似于 Java 的 Map.remove(k)
    - yield 生成器，惰性返回数据
      Java 对比：Java 没有 yield，需要手动实现迭代器
    """

    def __init__(self, conf):
        self.conf = conf

    def get(self, k, default_value=None):
        """
        获取配置值并标记为已读取

        参数:
            k: 配置键
            default_value: 默认值

        返回:
            配置值或默认值

        读取后从字典中删除该键，这样最后剩下的就是未被识别的配置项。
        """
        res = self.conf.get(k, default_value)
        if k in self.conf:
            del self.conf[k]
        return res

    def items(self):
        """
        迭代所有配置项并标记为已读取

        用于 set_bsp_config 中遍历所有自定义配置项
        """
        visit_keys = set()
        for k, v in self.conf.items():
            yield k, v
            visit_keys.add(k)
        for k in visit_keys:
            del self.conf[k]

    def check(self):
        """
        检查是否有未识别的配置项

        如果配置字典中还有剩余的键，说明用户传入了不存在的配置项
        （可能是拼写错误），抛出异常提醒。
        """
        if len(self.conf) > 0:
            invalid_key_lst = ",".join(list(self.conf.keys()))
            raise CChanException(f"invalid CChanConfig: {invalid_key_lst}", ErrCode.PARA_ERROR)