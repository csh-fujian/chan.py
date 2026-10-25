# -*- coding: utf-8 -*-
"""
买卖点模块 - 表示缠论中的买卖点

Java 开发者注意：
- Generic[LINE_TYPE] 是 Python 泛型，类似于 Java 的 <LINE_TYPE>
- Union[str, Dict, CFeatures] 类似于 Java 中的方法重载（不同参数类型）
- Optional[T] 类似于 Java 的 @Nullable T
"""

from typing import Dict, Generic, List, Optional, TypeVar, Union

from ChanAnalyse.Bi.Bi import CBi
from ChanAnalyse.ChanModel.Features import CFeatures
from ChanAnalyse.Common.CEnum import BSP_TYPE
from ChanAnalyse.Seg.Seg import CSeg

LINE_TYPE = TypeVar('LINE_TYPE', CBi, CSeg)

# 同笔多类型时选取主类型的优先序（信号强度由高到低）。
# 一类点是趋势转折，信息量最高；类二数量最多、级别最低。
_PRIMARY_TYPE_PRIORITY = (
    BSP_TYPE.T1,
    BSP_TYPE.T1P,
    BSP_TYPE.T2,
    BSP_TYPE.T3A,
    BSP_TYPE.T3B,
    BSP_TYPE.T2S,
)


class CBS_Point(Generic[LINE_TYPE]):
    """
    买卖点 - 缠论中的交易信号

    缠论知识 - 买卖点分类：
    1. 第一类买卖点（T1）：中枢背驰后形成，是最重要的买卖点
    2. 第二类买卖点（T2）：回测中枢不破，确认第一类买卖点
    3. 第三类买卖点（T3A/T3B）：突破中枢后回测不破中枢，确认趋势延续
    4. 盘整背驰买卖点（T1P）：无中枢情况下的背驰买卖点
    5. 类二买卖点（T2S）：中枢内多次回测形成的买卖点

    属性说明：
    - bi: 买卖点所在的笔（或线段）
    - klu: 买卖点所在的K线
    - is_buy: True=买入点，False=卖出点
    - type: 买卖点类型列表（一个点可能同时是多种类型）
    - relate_bsp1: 关联的第一类买卖点
    - features: 买卖点的特征数据
    - is_segbsp: 是否是线段级别的买卖点
    """

    def __init__(self, bi: LINE_TYPE, is_buy, bs_type: BSP_TYPE, relate_bsp1: Optional['CBS_Point'], feature_dict=None):
        """
        初始化买卖点

        参数:
            bi: 买卖点所在的笔（或线段）
            is_buy: True=买入，False=卖出
            bs_type: 买卖点类型
            relate_bsp1: 关联的第一类买卖点（用于二/三类买卖点）
            feature_dict: 特征数据字典
        """
        self.bi: LINE_TYPE = bi
        self.klu = bi.get_end_klu()
        self.is_buy = is_buy
        self.type: List[BSP_TYPE] = [bs_type]
        self.relate_bsp1 = relate_bsp1

        self.bi.bsp = self  # 设置反向引用
        self.features = CFeatures(feature_dict)

        self.is_segbsp = False

        self.init_common_feature()

    def add_type(self, bs_type: BSP_TYPE):
        """
        添加买卖点类型（一个点可以同时是多种类型）

        例如：一个点可以同时是 T1 和 T1P。

        **幂等**：同一笔的同一类型只登记一次。步进模式下未确认线段会被反复
        重算，`add_bs` 每轮都会命中既有对象并走到这里；若不去重，`type` 会
        累积成 `[T3B, T3B, ...]`（实测 30m 单笔累积到 45 个），任何按 `type`
        遍历的统计（`count_types`、`bsp_index` 落库）都会被放大数十倍，
        使步进与批量的数量出现假性分歧。
        """
        if bs_type not in self.type:
            self.type.append(bs_type)

    def type2str(self):
        """买卖点类型转换为字符串，格式如 '1,2,3a'"""
        return ",".join([x.value for x in self.type])

    @property
    def primary_type(self) -> BSP_TYPE:
        """
        主类型 —— 同一笔属于多个类型时的确定性去重键

        一个价格位置可以同时是多种类型（如二买与三买B 落在同一笔）。下游
        `bsp_index` 若按类型分行写入，同一笔会产生多行，绩效统计的分母被放大。
        本属性按固定的「信号强度」优先序从 `type` 中取一个作为主类型，
        `type` 列表本身保持全部类型不变。

        优先序：T1 > T1P > T2 > T3A > T3B > T2S。
        理由：一类点是趋势转折，信息量最高；类二数量最多、级别最低。
        """
        for candidate in _PRIMARY_TYPE_PRIORITY:
            if candidate in self.type:
                return candidate
        return self.type[0]

    def add_another_bsp_prop(self, bs_type: BSP_TYPE, relate_bsp1):
        """
        添加另一个买卖点属性（同一位置被识别为多种类型）

        参数:
            bs_type: 新类型
            relate_bsp1: 关联的第一类买卖点

        关于 `relate_bsp1` 的保留策略（chan-standard-bsp）：同一笔上不同类型的
        买卖点**允许锚定不同的一买**。标准化后的三买尤其如此——T3A 依托「本线段
        末笔之前」的中枢、T3B 依托「本线段内」的中枢，两者可以落在同一笔上但
        对应的中枢与一买不同。此时保留**先登记**的那个（判定顺序 T3A 先于 T3B），
        不做覆盖，也不断言失败。

        历史实现是 `assert self.relate_bsp1.klu.idx == relate_bsp1.klu.idx`：
        在默认档 + `min_zs_cnt=1`（文档宣传支持的单项覆盖）下会真实触发，
        使整只股票的线段级别买卖点计算崩溃。`relate_bsp1` 在仓库内无下游
        消费方，断言无守护价值，改为保留先登记者。
        """
        self.add_type(bs_type)
        if self.relate_bsp1 is None:
            self.relate_bsp1 = relate_bsp1

    def add_feat(self, inp1: Union[str, Dict[str, float], Dict[str, Optional[float]], 'CFeatures'], inp2: Optional[float] = None):
        """
        添加特征数据

        参数:
            inp1: 特征名（str）/ 特征字典 / CFeatures 对象
            inp2: 特征值（当 inp1 是 str 时）
        """
        self.features.add_feat(inp1, inp2)

    def init_common_feature(self):
        """
        初始化通用特征

        添加所有买卖点都有的特征：笔的振幅
        """
        self.add_feat({
            'bsp_bi_amp': self.bi.amp(),
        })