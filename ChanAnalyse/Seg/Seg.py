# -*- coding: utf-8 -*-
"""
线段模块 - 表示缠论中的"线段"，由多笔构成

Java 开发者注意：
- Generic[LINE_TYPE] 是 Python 泛型，类似于 Java 的 <LINE_TYPE>
- Self 是 Python 3.11+ 的类型注解，表示当前类自身
- Optional[Self] 类似于 Java 的 @Nullable Self
- Python 的 assert 默认启用，类似于 Java 的 assert 但需要 -ea 参数
- Python 的生成器表达式 (zs for zs in ... if ...) 类似于 Java 的 Stream.filter()
"""

from typing import Generic, List, Optional, Self, TypeVar

from ChanAnalyse.Bi.Bi import CBi
from ChanAnalyse.Common.CEnum import BI_DIR, MACD_ALGO, TREND_LINE_SIDE
from ChanAnalyse.Common.ChanException import CChanException, ErrCode
from ChanAnalyse.KLine.KLine_Unit import CKLine_Unit
from ChanAnalyse.Math.Metric import (
    cal_macd_amp,
    cal_macd_area,
    cal_macd_diff,
    cal_macd_diff_peak,
    cal_macd_half_obverse,
    cal_macd_half_reverse,
    cal_macd_peak,
    cal_macd_slope,
    cal_rsi,
)
from ChanAnalyse.Math.TrendLine import CTrendLine

from .EigenFX import CEigenFX

LINE_TYPE = TypeVar('LINE_TYPE', CBi, "CSeg")
# Python 语法：TypeVar 可以有 bound 约束，这里用 CBi | "CSeg" 表示两个可能的类型
# Java 对比：<T extends CBi | CSeg>，但 Java 泛型不支持联合类型


class CSeg(Generic[LINE_TYPE]):
    """
    线段 - 由至少三笔重叠构成

    缠论知识 - 线段的定义：
    线段由至少三笔构成，且必须有重叠区间。
    线段是比笔更高一级的走势结构，用于构建中枢。

    两个层次的线段：
    1. 笔的线段（LINE_TYPE = CBi）：由笔构成
    2. 线段的线段（LINE_TYPE = CSeg[CBi]）：由线段构成，更高层次

    属性说明：
    - idx: 线段索引
    - start_bi/end_bi: 起始/结束笔（或线段）
    - is_sure: 是否确认
    - dir: 方向（UP/DOWN）
    - zs_lst: 线段内的中枢列表
    - eigen_fx: 特征序列分型（仅特征序列法使用）
    - bi_list: 线段包含的笔列表
    - support_trend_line/resistance_trend_line: 支撑/阻力趋势线
    - ele_inside_is_sure: 线段内部元素是否已确认
    """

    def __init__(self, idx: int, start_bi: LINE_TYPE, end_bi: LINE_TYPE, is_sure=True, seg_dir=None, reason="normal"):
        """
        初始化线段

        参数:
            idx: 线段索引
            start_bi: 起始笔
            end_bi: 结束笔
            is_sure: 是否确认
            seg_dir: 线段方向（如果为None，则从end_bi推断）
            reason: 创建原因（用于调试追踪）

        约束：
        - 确认线段：start_bi 和 end_bi 方向必须一致
        - 线段长度（笔数）必须 >= 3
        """
        assert start_bi.idx == 0 or start_bi.dir == end_bi.dir or not is_sure, \
            f"{start_bi.idx} {end_bi.idx} {start_bi.dir} {end_bi.dir}"
        self.idx = idx
        self.start_bi = start_bi
        self.end_bi = end_bi
        self.is_sure = is_sure
        self.used_to_be_sure = is_sure
        self.dir = end_bi.dir if seg_dir is None else seg_dir

        from ChanAnalyse.ZS.ZS import CZS
        self.zs_lst: List[CZS[LINE_TYPE]] = []

        self.eigen_fx: Optional[CEigenFX] = None
        self.seg_idx = None  # 线段的线段使用
        self.parent_seg: Optional[CSeg] = None  # 属于哪个线段
        self.pre: Optional[Self] = None
        self.next: Optional[Self] = None

        from ChanAnalyse.BuySellPoint.BS_Point import CBS_Point
        self.bsp: Optional[CBS_Point] = None  # 尾部是不是买卖点

        self.bi_list: List[LINE_TYPE] = []  # 仅通过 self.update_bi_list 来更新
        self.reason = reason
        self.support_trend_line = None
        self.resistance_trend_line = None
        if end_bi.idx - start_bi.idx < 2:
            self.is_sure = False  # 笔数不足3笔，不能确认
        self.check()

        self.ele_inside_is_sure = False

    def set_seg_idx(self, idx):
        """设置线段的线段索引"""
        self.seg_idx = idx

    def check(self):
        """
        校验线段的合法性
        检查：
        - 下降线段：起始点 > 结束点
        - 上升线段：起始点 < 结束点
        - 线段长度 >= 3笔
        """
        if not self.is_sure:
            return
        if self.is_down():
            if self.start_bi.get_begin_val() < self.end_bi.get_end_val():
                raise CChanException(f"下降线段起始点应该高于结束点! idx={self.idx}", ErrCode.SEG_END_VALUE_ERR)
        elif self.start_bi.get_begin_val() > self.end_bi.get_end_val():
            raise CChanException(f"上升线段起始点应该低于结束点! idx={self.idx}", ErrCode.SEG_END_VALUE_ERR)
        if self.end_bi.idx - self.start_bi.idx < 2:
            raise CChanException(f"线段({self.start_bi.idx}-{self.end_bi.idx})长度不能小于2! idx={self.idx}", ErrCode.SEG_LEN_ERR)

    def __str__(self):
        """字符串表示，格式如 '0->5: BI_DIR.UP  True'"""
        return f"{self.start_bi.idx}->{self.end_bi.idx}: {self.dir}  {self.is_sure}"

    def add_zs(self, zs):
        """添加中枢到线段（中枢是反序加入的，所以插到列表前面）"""
        self.zs_lst = [zs] + self.zs_lst

    def cal_klu_slope(self):
        """
        计算线段基于原始K线的斜率
        斜率 = (结束值 - 起始值) / (K线数量) / 起始值
        用于衡量线段的力度
        """
        assert self.end_bi.idx >= self.start_bi.idx
        return (self.get_end_val()-self.get_begin_val())/(self.get_end_klu().idx-self.get_begin_klu().idx)/self.get_begin_val()

    def cal_amp(self):
        """
        计算线段的振幅
        振幅 = (结束值 - 起始值) / 起始值
        """
        return (self.get_end_val()-self.get_begin_val())/self.get_begin_val()

    def cal_bi_cnt(self):
        """线段包含的笔数量"""
        return self.end_bi.idx-self.start_bi.idx+1

    def clear_zs_lst(self):
        """清空中枢列表"""
        self.zs_lst = []

    def _low(self):
        """
        线段的最低点
        - 下降线段：结束笔的最低点
        - 上升线段：起始笔的最低点
        """
        return self.end_bi.get_end_klu().low if self.is_down() else self.start_bi.get_begin_klu().low

    def _high(self):
        """
        线段的最高点
        - 上升线段：结束笔的最高点
        - 下降线段：起始笔的最高点
        """
        return self.end_bi.get_end_klu().high if self.is_up() else self.start_bi.get_begin_klu().high

    def is_down(self):
        return self.dir == BI_DIR.DOWN

    def is_up(self):
        return self.dir == BI_DIR.UP

    def get_end_val(self):
        return self.end_bi.get_end_val()

    def get_begin_val(self):
        return self.start_bi.get_begin_val()

    @property
    def is_used_to_be_sure(self) -> bool:
        """线段是否曾经被确认过（包括当前确认状态）"""
        return self.is_sure or self.used_to_be_sure

    def amp(self):
        """线段振幅（绝对值）"""
        return abs(self.get_end_val() - self.get_begin_val())

    def get_end_klu(self) -> CKLine_Unit:
        """获取线段结束点所在的原始K线"""
        return self.end_bi.get_end_klu()

    def get_begin_klu(self) -> CKLine_Unit:
        """获取线段起始点所在的原始K线"""
        return self.start_bi.get_begin_klu()

    def get_klu_cnt(self):
        """线段包含的原始K线数量"""
        return self.get_end_klu().idx - self.get_begin_klu().idx + 1

    @property
    def klc_lst(self):
        """
        线段包含的合并K线的迭代器（从起始笔的第一根到结束笔的最后一根）

        与 `bi_list` 的区别：`bi_list` 是要素列表（笔），`klc_lst` 是 K 线序列，
        用于计算需要逐根 K 线累积的力度指标（面积、峰值、DIF 极值、RSI）。

        实现方式：从首笔的 `begin_klc` 沿 `next` 链向后走，直到越过末笔的
        `end_klc`。不能简单地拼接各笔的 `klc_lst`——相邻笔共享端点所在的合并
        K 线，拼接会重复计入。
        """
        if not self.bi_list:
            return
        end_idx = self.bi_list[-1].end_klc.idx
        klc = self.bi_list[0].begin_klc
        while klc is not None:
            yield klc
            if klc.idx >= end_idx:
                return
            klc = klc.next

    @property
    def klc_lst_re(self):
        """线段包含的合并K线的逆序迭代器"""
        if not self.bi_list:
            return
        begin_idx = self.bi_list[0].begin_klc.idx
        klc = self.bi_list[-1].end_klc
        while klc is not None:
            yield klc
            if klc.idx <= begin_idx:
                return
            klc = klc.pre

    def cal_macd_metric(self, macd_algo, is_reverse):
        """
        计算线段的 MACD 背驰指标

        支持与 `CBi` 一致的算法集合：`area` / `full_area` / `peak` / `diff` /
        `diff_peak` / `slope` / `amp` / `rsi`。

        `is_reverse` 只影响 `area`（半面积）：`True` 表示从结束端反向累积。

        历史说明：本方法原先只支持 `slope` / `amp`，且 `CChanConfig` 把线段级别的
        `macd_algo` 硬编码为 `slope`。改造后线段级别可以表达 DIF 背驰与零轴回抽，
        这是「次级别走势类型」落在线段级别的前提。
        """
        if macd_algo == MACD_ALGO.AREA:
            return self.Cal_MACD_half(is_reverse)
        elif macd_algo == MACD_ALGO.PEAK:
            return self.Cal_MACD_peak()
        elif macd_algo == MACD_ALGO.FULL_AREA:
            return self.Cal_MACD_area()
        elif macd_algo == MACD_ALGO.DIFF:
            return self.Cal_MACD_diff()
        elif macd_algo == MACD_ALGO.DIFF_PEAK:
            return self.Cal_MACD_diff_peak()
        elif macd_algo == MACD_ALGO.SLOPE:
            return self.Cal_MACD_slope()
        elif macd_algo == MACD_ALGO.AMP:
            return self.Cal_MACD_amp()
        elif macd_algo == MACD_ALGO.RSI:
            return self.Cal_Rsi()
        else:
            raise CChanException(
                f"unsupport macd_algo={macd_algo} of Seg, "
                f"should be one of area/full_area/peak/diff/diff_peak/slope/amp/rsi",
                ErrCode.PARA_ERROR)

    def Cal_MACD_area(self):
        """线段 MACD 全面积（只累加与线段同向的柱）"""
        return cal_macd_area(self.klc_lst, self.is_down(),
                             begin_idx=self.get_begin_klu().idx, end_idx=self.get_end_klu().idx)

    def Cal_MACD_peak(self):
        """线段 MACD 同向柱峰值"""
        return cal_macd_peak(self.klc_lst, self.is_down(),
                             begin_idx=self.get_begin_klu().idx, end_idx=self.get_end_klu().idx)

    def Cal_MACD_diff(self):
        """线段区间内 MACD 柱的 max - min（历史语义，与 `diff_peak` 不同）"""
        return cal_macd_diff(self.klc_lst,
                             begin_idx=self.get_begin_klu().idx, end_idx=self.get_end_klu().idx)

    def Cal_MACD_diff_peak(self):
        """线段区间内 DIF（黄白线）极值：下降取 min、上升取 max"""
        return cal_macd_diff_peak(self.klc_lst, self.is_down(),
                                  begin_idx=self.get_begin_klu().idx, end_idx=self.get_end_klu().idx)

    def Cal_Rsi(self):
        """线段 RSI 极值"""
        return cal_rsi(self.klc_lst, self.is_down(),
                       begin_idx=self.get_begin_klu().idx, end_idx=self.get_end_klu().idx)

    def Cal_MACD_half(self, is_reverse):
        """线段 MACD 半面积"""
        if is_reverse:
            return cal_macd_half_reverse(self.klc_lst_re, self.get_end_klu().macd.macd)
        else:
            return cal_macd_half_obverse(self.klc_lst, self.get_begin_klu().macd.macd)

    def Cal_MACD_slope(self):
        """
        计算线段的斜率指标
        上升线段：(结束高点 - 起始低点) / 结束高点 / K线数量
        下降线段：(起始高点 - 结束低点) / 起始高点 / K线数量
        """
        return cal_macd_slope(self.get_begin_klu(), self.get_end_klu(), self.is_up())

    def Cal_MACD_amp(self):
        """
        计算线段的振幅指标
        下降线段：(起始高点 - 结束低点) / 起始高点
        上升线段：(结束高点 - 起始低点) / 起始低点
        """
        return cal_macd_amp(self.get_begin_klu(), self.get_end_klu(), self.is_up())

    def update_bi_list(self, bi_lst, idx1, idx2):
        """
        更新线段包含的笔列表

        参数:
            bi_lst: 完整的笔列表
            idx1: 起始笔索引
            idx2: 结束笔索引

        设置每笔的 parent_seg 引用，并计算趋势线（如果笔数>=3）
        """
        for bi_idx in range(idx1, idx2+1):
            bi_lst[bi_idx].parent_seg = self
            self.bi_list.append(bi_lst[bi_idx])
        if len(self.bi_list) >= 3:
            self.support_trend_line = CTrendLine(self.bi_list, TREND_LINE_SIDE.INSIDE)
            self.resistance_trend_line = CTrendLine(self.bi_list, TREND_LINE_SIDE.OUTSIDE)

    def get_first_multi_bi_zs(self):
        """
        获取第一个多笔中枢（非一笔中枢）

        Python 语法：next(iter, None) 获取迭代器的第一个元素，空则返回 None
        Java 对比：类似于 stream.findFirst().orElse(null)
        """
        return next((zs for zs in self.zs_lst if not zs.is_one_bi_zs()), None)

    def get_multi_bi_zs_lst(self):
        """
        获取所有多笔中枢列表

        Python 语法：列表推导式 [zs for zs in ... if ...]
        Java 对比：类似于 stream.filter().collect(Collectors.toList())
        """
        return [zs for zs in self.zs_lst if not zs.is_one_bi_zs()]

    def get_final_multi_bi_zs(self):
        """
        获取最后一个多笔中枢（从后往前找）

        缠论知识：最后一个中枢用于判断第三类买卖点
        """
        zs_idx = len(self.zs_lst) - 1
        while zs_idx >= 0:
            zs = self.zs_lst[zs_idx]
            if not zs.is_one_bi_zs():
                return zs
            zs_idx -= 1
        return None

    def get_multi_bi_zs_cnt(self):
        """
        获取多笔中枢的数量

        Python 语法：sum(condition for item in iterable)
        利用了 True/False 在算术运算中等于 1/0 的特性
        Java 对比：stream.filter().count()
        """
        return sum(not zs.is_one_bi_zs() for zs in self.zs_lst)