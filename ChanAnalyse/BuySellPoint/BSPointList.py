# -*- coding: utf-8 -*-
"""
买卖点列表模块 - 管理买卖点的计算、存储和检索

Java 开发者注意：
- Generic[LINE_TYPE, LINE_LIST_TYPE] 是 Python 多泛型参数，类似于 Java 的 <T, U>
- yield from 是生成器委托，类似于 Java 的 Stream.flatMap()
- Python 的 sorted(list, key=lambda) 类似于 Java 的 stream.sorted(Comparator.comparing())
- Python 的 := 海象运算符在表达式中赋值，Java 没有直接对应
- Python 的 Optional[T] 类似于 Java 的 @Nullable T
- TypeVar 可以绑定多个类型，用逗号分隔
"""

from typing import Dict, Generic, Iterable, List, Optional, Tuple, TypeVar
import copy

from ChanAnalyse.Bi.Bi import CBi
from ChanAnalyse.Bi.BiList import CBiList
from ChanAnalyse.Common.CEnum import BSP_TYPE
from ChanAnalyse.Common.func_util import has_overlap
from ChanAnalyse.Seg.Seg import CSeg
from ChanAnalyse.Seg.SegListComm import CSegListComm
from ChanAnalyse.ZS.ZS import CZS, _span_metric, any_span_supported, cfg_algos

from .BS_Point import CBS_Point
from .BSPointConfig import CBSPointConfig, CPointConfig
from .BSPJudgement import (
    back_to_zs,
    check_bsp1_standard,
    check_bsp2_standard,
    check_breakout,
    check_ele_end_in_zs,
    check_zs_peak_on_breakout,
    get_first_retrace,
)

LINE_TYPE = TypeVar('LINE_TYPE', CBi, CSeg[CBi])
LINE_LIST_TYPE = TypeVar('LINE_LIST_TYPE', CBiList, CSegListComm[CBi])


class CBSPointList(Generic[LINE_TYPE, LINE_LIST_TYPE]):
    """
    买卖点列表 - 管理买卖点的计算和存储

    缠论知识 - 买卖点计算流程：
    1. 第一类买卖点（T1）：中枢背驰
       - 离开中枢的笔力度 < 进入中枢的笔力度
       - 出现背驰 → 第一类买卖点
    2. 第二类买卖点（T2）：回测中枢
       - 第一类买卖点后，反向笔回测中枢不破
       - 回撤率 < max_bs2_rate → 第二类买卖点
    3. 第三类买卖点（T3A/T3B）：突破中枢
       - 离开中枢的笔突破中枢后，回测不破中枢
       - T3A: 中枢之后形成
       - T3B: 中枢之前形成（盘整背驰）

    属性说明：
    - bsp_store_dict: 按类型存储买卖点的字典
    - bsp_store_flat_dict: 按笔索引存储买卖点的字典（去重）
    - bsp1_list: 第一类买卖点列表
    - bsp1_dict: 第一类买卖点字典（按笔索引）
    - config: 买卖点配置
    - last_sure_pos: 最后一个确认位置
    """

    def __init__(self, bs_point_config: CBSPointConfig):
        """
        初始化买卖点列表

        数据结构：
        - bsp_store_dict: {BSP_TYPE: ([buy_list], [sell_list])}
        - bsp_store_flat_dict: {bi_idx: CBS_Point}
        """
        self.bsp_store_dict: Dict[BSP_TYPE, Tuple[List[CBS_Point[LINE_TYPE]], List[CBS_Point[LINE_TYPE]]]] = {}
        self.bsp_store_flat_dict: Dict[int, CBS_Point[LINE_TYPE]] = {}

        self.bsp1_list: List[CBS_Point[LINE_TYPE]] = []
        self.bsp1_dict: Dict[int, CBS_Point[LINE_TYPE]] = {}
        # 已成立的一买：只收通过全部启用判据的点（`is_target_bsp=True`）。
        # `bsp1_list` 保持「结构性候选」语义不变，两者的差值就是未成立候选。
        self.bsp1_sure_list: List[CBS_Point[LINE_TYPE]] = []
        self.bsp1_sure_dict: Dict[int, CBS_Point[LINE_TYPE]] = {}

        self.config = bs_point_config
        self.last_sure_pos = -1
        self.last_sure_seg_idx = 0

    def store_add_bsp(self, bsp_type: BSP_TYPE, bsp: CBS_Point[LINE_TYPE]):
        """
        存储买卖点

        参数:
            bsp_type: 买卖点类型
            bsp: 买卖点对象

        存储结构：
        - bsp_store_dict[bsp_type][is_buy]: 按类型和买卖方向存储
        - bsp_store_flat_dict[bi.idx]: 按笔索引存储（用于去重）
        """
        if bsp_type not in self.bsp_store_dict:
            self.bsp_store_dict[bsp_type] = ([], [])
        if len(self.bsp_store_dict[bsp_type][bsp.is_buy]) > 0:
            assert self.bsp_store_dict[bsp_type][bsp.is_buy][-1].bi.idx < bsp.bi.idx, \
                f"{bsp_type}, {bsp.is_buy} {self.bsp_store_dict[bsp_type][bsp.is_buy][-1].bi.idx} {bsp.bi.idx}"
        self.bsp_store_dict[bsp_type][bsp.is_buy].append(bsp)
        self.bsp_store_flat_dict[bsp.bi.idx] = bsp

    def add_bsp1(self, bsp: CBS_Point[LINE_TYPE], is_sure: bool = True):
        """
        添加第一类买卖点

        参数:
            bsp: 买卖点对象
            is_sure: 是否已通过全部启用判据。为 False 时只进候选集合。

        `bsp1_list` 收全部结构性候选（含未成立），`bsp1_sure_list` 只收成立的点。
        下游的二买/三买跟随校验与 `relate_bsp1` 取值都走后者。
        """
        if len(self.bsp1_list) > 0:
            assert self.bsp1_list[-1].bi.idx < bsp.bi.idx
        self.bsp1_list.append(bsp)
        self.bsp1_dict[bsp.bi.idx] = bsp
        if is_sure:
            self.bsp1_sure_list.append(bsp)
            self.bsp1_sure_dict[bsp.bi.idx] = bsp

    def clear_store_end(self):
        """
        清理末尾失效的买卖点（增量更新时使用）

        当新数据到来后，末尾的买卖点可能失效，需要清理。
        清理所有类型中 last_sure_pos 之后的买卖点。

        同时清理买卖点对应的笔的 bsp 引用。
        """
        for bsp_list in self.bsp_store_dict.values():
            for is_buy in [True, False]:
                while len(bsp_list[is_buy]) > 0:
                    if bsp_list[is_buy][-1].bi.get_end_klu().idx <= self.last_sure_pos:
                        break
                    del self.bsp_store_flat_dict[bsp_list[is_buy][-1].bi.idx]
                    bsp_list[is_buy][-1].bi.bsp = None  # 清空笔的买卖点引用
                    bsp_list[is_buy].pop()

    def clear_bsp1_end(self):
        """清理末尾失效的第一类买卖点（含成立集合）"""
        while len(self.bsp1_list) > 0:
            if self.bsp1_list[-1].bi.get_end_klu().idx <= self.last_sure_pos:
                break
            bi_idx = self.bsp1_list[-1].bi.idx
            self.bsp1_dict.pop(bi_idx, None)
            self.bsp1_list.pop()
        while len(self.bsp1_sure_list) > 0:
            if self.bsp1_sure_list[-1].bi.get_end_klu().idx <= self.last_sure_pos:
                break
            bi_idx = self.bsp1_sure_list[-1].bi.idx
            self.bsp1_sure_dict.pop(bi_idx, None)
            self.bsp1_sure_list.pop()

    def bsp_iter(self) -> Iterable[CBS_Point[LINE_TYPE]]:
        """
        遍历所有买卖点（先买入后卖出）

        Python 语法：yield from 是生成器委托
        Java 对比：类似于 flatMap 后的迭代器
        """
        for bsp_list in self.bsp_store_dict.values():
            yield from bsp_list[True]   # 所有买入点
            yield from bsp_list[False]  # 所有卖出点

    def bsp_iter_v2(self) -> Iterable[CBS_Point[LINE_TYPE]]:
        """
        按笔索引降序遍历所有买卖点（最新的在前）

        算法：维护一个多路归并的索引列表，每次找最大的笔索引。
        类似于多路归并排序中的归并过程。

        Java 对比：类似于 PriorityQueue + 多路归并
        """
        list_indices = []
        for bsp_type, bsp_list in self.bsp_store_dict.items():
            if bsp_list[True]:
                list_indices.append([bsp_type, True, len(bsp_list[True]) - 1])
            if bsp_list[False]:
                list_indices.append([bsp_type, False, len(bsp_list[False]) - 1])

        while list_indices:
            max_idx = -1
            max_bi_idx = -1
            max_bsp = None

            # 找当前所有列表中笔索引最大的买卖点
            for i, (bsp_type, is_buy, idx) in enumerate(list_indices):
                if idx >= 0:
                    bsp = self.bsp_store_dict[bsp_type][is_buy][idx]
                    if bsp.bi.idx > max_bi_idx:
                        max_bi_idx = bsp.bi.idx
                        max_idx = i
                        max_bsp = bsp

            if max_bsp is None:
                break

            yield max_bsp
            list_indices[max_idx][2] -= 1
            if list_indices[max_idx][2] < 0:
                list_indices.pop(max_idx)

    def __len__(self):
        return len(self.bsp_store_flat_dict)

    def cal(self, bi_list: LINE_LIST_TYPE, seg_list: CSegListComm[LINE_TYPE]):
        """
        计算所有买卖点（核心入口方法）

        参数:
            bi_list: 笔列表（或线段列表）
            seg_list: 线段列表

        计算顺序：
        1. 清理末尾失效买卖点
        2. 计算第一类买卖点（cal_seg_bs1point）
        3. 计算第二类买卖点（cal_seg_bs2point）
        4. 计算第三类买卖点（cal_seg_bs3point）
        5. 更新最后确认位置
        """
        self.clear_store_end()
        self.clear_bsp1_end()
        self.cal_seg_bs1point(seg_list, bi_list)
        self.cal_seg_bs2point(seg_list, bi_list)
        self.cal_seg_bs3point(seg_list, bi_list)

        self.update_last_pos(seg_list)
        # 区间套特征注解必须放在最后：判定链路已全部结束，
        # 物理上不可能影响 is_target_bsp（design D7-q 的结构保证，不靠纪律）
        self._annotate_qjt()

    def _annotate_qjt(self):
        """区间套特征注解（chan-standard-bsp1-change design D7-q / D8，§4.6）。

        对 `bsp1_list` 家族（T1 与 T1P 候选）的每个点，取其 **c 走势段窗口**
        （与 `_cal_force_windows` 的 c 窗口同源：`zs.end_bi.idx + 1 ~ seg.end_bi.idx`），
        沿 `sub_kl_list` 映射到次级别的 K 线时间区间，查次级
        `bsp1_sure_list` 中**同向且已确认**的点。

        命中写 `feature_dict['bsp1_qjt_hit']=True` 与 `bsp1_qjt_sub_idx`；
        未命中写 `False`。`bsp1_qjt=False` 或无次级容器时直接返回。

        **这是特征不是判据**：本方法只写 feature，`is_target_bsp` 在此刻早已确定，
        不可能被改写。窗口排除 c 段之前的衰竭（进入段的背驰不算区间套命中）。

        命中资格镜像锚点隔离（D8）：只用次级 `bsp1_sure_list`（已确认），
        不用 `bsp1_list` 候选——否则父级 T1 会拿到「子级连趋势都没成立的点」背书。

        递归深度（`bsp1_qjt_depth`，默认 1）：深度 k 表示**链式确认 k 层**——
        第 1 层在直接次级找同向已确认一买；深度 > 1 时还要求该命中点自身在其
        c 段内也能找到下一层的同向已确认一买。某层容器缺失（如只有两个级别）
        时不惩罚，按已走到的层数判定命中。
        """
        conf = self.config.GetBSConfig(True)
        if not conf.bsp1_qjt:
            return
        sub_lst = getattr(self, 'sub_bs_point_lst', None)
        if sub_lst is None:
            return
        depth = conf.bsp1_qjt_depth
        for bsp in self.bsp1_list:
            feat = {'bsp1_qjt_hit': False}
            try:
                hit_idx = self._find_qjt_hit(bsp, sub_lst, depth)
                if hit_idx is not None:
                    feat['bsp1_qjt_hit'] = True
                    feat['bsp1_qjt_sub_idx'] = hit_idx
            except Exception:
                pass
            bsp.add_feat(feat)
            if not feat['bsp1_qjt_hit']:
                # 只补写不清理会让「先命中、后因重算不再命中」的点残留旧的
                # 次级索引，读到 hit=False 却带着 sub_idx 的组合。幂等删除。
                bsp.features.del_feat('bsp1_qjt_sub_idx')

    def _find_qjt_hit(self, bsp, sub_lst, depth):
        """在 `sub_lst` 的已确认一买中查找区间套命中，返回命中点的笔索引或 None。

        `depth > 1` 时逐层下钻：候选命中点自身还须在**它自己的** c 段窗口内
        找到下一层的同向已确认一买（`sub_lst.sub_bs_point_lst`）。下层容器缺失
        时退化为按已到达层数判定，避免「级别不够就全判不命中」的假阴性。
        """
        window = self._c_window_of(bsp)
        if window is None:
            return None
        t_lo, t_hi = window
        is_buy = bool(bsp.is_buy)
        deeper = getattr(sub_lst, 'sub_bs_point_lst', None) if depth > 1 else None
        for sub_bsp in sub_lst.bsp1_sure_list:
            try:
                if bool(sub_bsp.is_buy) != is_buy:
                    continue
                ts = sub_bsp.klu.time.ts
            except Exception:
                continue
            if not (t_lo <= ts <= t_hi):
                continue
            if depth <= 1 or deeper is None:
                return sub_bsp.bi.idx
            if self._find_qjt_hit(sub_bsp, deeper, depth - 1) is not None:
                return sub_bsp.bi.idx
        return None

    def _c_window_of(self, bsp):
        """取买卖点所在线段的 c 走势段时间窗口（映射到次级别时间轴）。

        c 段边界与 `_cal_force_windows` 完全同源：`zs.end_bi.idx + 1 ~ seg.end_bi.idx`
        （spec「窗口与力度口径共用同一定义」）。任一侧缺失时返回 None。
        """
        seg = getattr(bsp.bi, 'parent_seg', None)
        zs_lst = getattr(seg, 'zs_lst', None) if seg is not None else None
        if not zs_lst:
            return None
        zs = zs_lst[-1]
        t_lo, t_hi = self._sub_time_span(seg, zs.end_bi.idx + 1, seg.end_bi.idx)
        if t_lo is None:
            return None
        return t_lo, t_hi

    @staticmethod
    def _sub_time_span(seg, c_start_idx, c_end_idx):
        """把本级别线段的 c 窗口笔区间映射为次级别的时间区间 (t_lo, t_hi)。

        沿每笔的 K 线 `sub_kl_list` 收集子级 K 线时间戳。窗口内**没有任何子级**
        K 线时返回 (None, None)（如日线无 30m 子级数据）。
        """
        ts_list = []
        for bi in seg.bi_list:
            if bi.idx < c_start_idx or bi.idx > c_end_idx:
                continue
            for klc in bi.klc_lst:
                for klu in klc.lst:
                    for sub_klu in getattr(klu, 'sub_kl_list', ()):
                        try:
                            ts_list.append(sub_klu.time.ts)
                        except Exception:
                            continue
        if not ts_list:
            return None, None
        return min(ts_list), max(ts_list)

    def update_last_pos(self, seg_list: CSegListComm):
        """更新最后一个确认位置（用于增量更新）"""
        self.last_sure_pos = -1
        self.last_sure_seg_idx = 0
        seg_idx = len(seg_list)-1
        while seg_idx >= 0:
            seg = seg_list[seg_idx]
            if seg.is_sure:
                self.last_sure_pos = seg.end_bi.get_begin_klu().idx
                self.last_sure_seg_idx = seg.idx
                return
            seg_idx -= 1

    def seg_need_cal(self, seg: CSeg):
        """判断线段是否需要重新计算买卖点"""
        return seg.end_bi.get_end_klu().idx > self.last_sure_pos

    def add_bs(
        self,
        bs_type: BSP_TYPE,
        bi: LINE_TYPE,
        relate_bsp1: Optional[CBS_Point],
        is_target_bsp: bool = True,
        feature_dict=None,
        is_downgrade: bool = False,
    ):
        """
        添加买卖点

        参数:
            bs_type: 买卖点类型
            bi: 买卖点所在的笔
            relate_bsp1: 关联的第一类买卖点
            is_target_bsp: 是否是目标买卖点类型（配置中指定的）
            feature_dict: 特征数据
            is_downgrade: 是否为降级路由请求（趋势不达标但背驰链路成立的 T1P）。
                降级请求**落库但不作锚点**：写入 `bsp_store_dict`（因此 `bsp_iter` /
                `bsp_index` 可见），但不写入 `bsp1_sure_dict` / `bsp1_sure_list`
                （因此不被二买/三买当作锚点）。命中已有买卖点时只
                `add_another_bsp_prop` 后返回，不执行「候选→成立」的升级逻辑
                （design D2/D4）

        逻辑：
        1. 如果该笔已有买卖点，添加新类型
        2. 如果 bs_type 不在配置的目标类型中，不存储
        3. 如果是 T1 或 T1P，加入 bsp1 列表
        """
        is_buy = bi.is_down()
        if exist_bsp := self.bsp_store_flat_dict.get(bi.idx):
            # 该笔已有买卖点，添加新类型
            assert exist_bsp.is_buy == is_buy
            exist_bsp.add_another_bsp_prop(bs_type, relate_bsp1)
            if feature_dict is not None:
                exist_bsp.add_feat(feature_dict)
            # 该笔原先只是候选、本次被判定为成立时，补齐成立集合
            # 降级请求不得触发该升级（design D4「降级不得升级」保护）
            if not is_downgrade and is_target_bsp and bs_type in [BSP_TYPE.T1, BSP_TYPE.T1P] \
                    and bi.idx not in self.bsp1_sure_dict:
                self.bsp1_sure_list.append(exist_bsp)
                self.bsp1_sure_dict[exist_bsp.bi.idx] = exist_bsp
            return
        # 降级请求可能命中「仅候选」的既有 T1：候选只进 bsp1_dict，不在
        # bsp_store_flat_dict，上面的分支取不到它。此处补一条：在同一条候选对象上
        # 追加 T1P 类型并落库，但仍不进成立集合（锚点隔离不变）。
        if is_downgrade and (exist_candidate := self.bsp1_dict.get(bi.idx)) is not None:
            exist_candidate.add_another_bsp_prop(bs_type, relate_bsp1)
            if feature_dict is not None:
                exist_candidate.add_feat(feature_dict)
            self.store_add_bsp(bs_type, exist_candidate)
            return
        if bs_type not in self.config.GetBSConfig(is_buy).target_types:
            is_target_bsp = False

        if is_target_bsp or is_downgrade or bs_type in [BSP_TYPE.T1, BSP_TYPE.T1P]:
            bsp = CBS_Point[LINE_TYPE](
                bi=bi,
                is_buy=is_buy,
                bs_type=bs_type,
                relate_bsp1=relate_bsp1,
                feature_dict=feature_dict,
            )
        else:
            return
        # 降级点必须落库（否则下游 bsp_iter / bsp_index 看不到它），
        # 但它不作锚点——见下方 add_bsp1 的 is_sure 取值
        if is_target_bsp or is_downgrade:
            self.store_add_bsp(bs_type, bsp)
        else:
            bsp.bi.bsp = None
        if bs_type in [BSP_TYPE.T1, BSP_TYPE.T1P]:
            self.add_bsp1(bsp, is_sure=is_target_bsp and not is_downgrade)

    def cal_seg_bs1point(self, seg_list: CSegListComm[LINE_TYPE], bi_list: LINE_LIST_TYPE):
        """
        计算第一类买卖点

        遍历所有线段，对每个线段调用 cal_single_bs1point。
        """
        for seg in seg_list[self.last_sure_seg_idx:]:
            if not self.seg_need_cal(seg):
                continue
            self.cal_single_bs1point(seg, bi_list)

    def cal_single_bs1point(self, seg: CSeg[LINE_TYPE], bi_list: LINE_LIST_TYPE):
        """
        计算单个线段的第一类买卖点

        参数:
            seg: 线段
            bi_list: 笔列表

        两种情况：
        1. 有中枢且离开笔突破中枢：标准第一类买卖点（T1）
        2. 无中枢但有背驰：盘整背驰买卖点（T1P）

        缠论知识 - 第一类买卖点判断：
        - 中枢数量 >= min_zs_cnt
        - 离开笔 MACD 指标 < 进入笔 MACD 指标 * divergence_rate（背驰）
        """
        BSP_CONF = self.config.GetBSConfig(seg.is_down())
        zs_cnt = seg.get_multi_bi_zs_cnt() if BSP_CONF.bsp1_only_multibi_zs else len(seg.zs_lst)
        is_target_bsp = (BSP_CONF.min_zs_cnt <= 0 or zs_cnt >= BSP_CONF.min_zs_cnt)
        # 结构前提：必须有非一笔中枢（无中枢时走盘整背驰 T1P）
        has_struct_zs = len(seg.zs_lst) > 0 and not seg.zs_lst[-1].is_one_bi_zs()
        # 实现的过滤（非理论要求）：中枢须延伸到线段末笔且跨度 > 2。
        # 实测该条会把大量合格候选挤进 T1P，故改为可关闭，默认关闭。
        zs_extend_ok = has_struct_zs and (
            (seg.zs_lst[-1].bi_out and seg.zs_lst[-1].bi_out.idx >= seg.end_bi.idx)
            or seg.zs_lst[-1].bi_lst[-1].idx >= seg.end_bi.idx
        ) and seg.end_bi.idx - seg.zs_lst[-1].get_bi_in().idx > 2
        if has_struct_zs and (zs_extend_ok or not BSP_CONF.bsp1_zs_extend_to_seg_end):
            # 标准第一类买卖点：有中枢 + 背驰
            # 全量笔列表只在 `bsp1_new_extreme_mode="level"` 时被使用（跨线段取值），
            # 其余口径下 `check_new_extreme` 直接忽略它
            full_ele_list = getattr(bi_list, "bi_list", None)
            self.treat_bsp1(seg, BSP_CONF, is_target_bsp, full_ele_list=full_ele_list)
        else:
            # 盘整背驰：无中枢但最后一笔与前前笔背驰
            self.treat_pz_bsp1(seg, BSP_CONF, bi_list, is_target_bsp)

    def _cal_force_windows(self, seg: CSeg, zs: CZS, BSP_CONF: CPointConfig):
        """计算 b/c 两段的力度取值窗口（chan-standard-bsp1-change D7-a）。

        返回 `(b_window, c_window, effective)`：
            b_window: 进入段窗口（要素列表），None = 走单笔口径
            c_window: 离开段窗口（要素列表），None = 走单笔口径
            effective: `"swing"` / `"bi"` / `"bi_fallback"`（算法不支持区间取值）

        窗口边界（`bsp1_force_scope="swing"` 时）：
            b = 该线段内最后一个「结束于当前中枢开始之前」的非一笔中枢的
                end_bi.idx + 1 起（不存在则取线段首笔）→ zs.get_bi_in()
            c = zs.end_bi.idx + 1 → seg.end_bi.idx

        **索引陷阱（D7-b）**：`seg.bi_list` 是 `range(start_bi.idx, end_bi.idx+1)`
        的连续切片，`seg.bi_list[i]` 对应全局 `bi_list[seg.start_bi.idx + i]`。
        因此窗口切片必须用**线段内相对索引** `idx - seg.start_bi.idx`；
        直接用全局 `bi.idx` 会越界或错位。
        """
        if BSP_CONF.bsp1_force_scope == "bi":
            return None, None, "bi"
        if not any_span_supported(cfg_algos(BSP_CONF)):
            # 全部选中的指标都是成交量/换手率类，没有区间版本，退回单笔口径
            return None, None, "bi_fallback"

        base = seg.start_bi.idx
        bi_in = zs.get_bi_in()
        # --- b 窗口：上一中枢之后 ~ 进入笔 ---
        prev_zs = [z for z in seg.zs_lst if z.end_bi.idx < zs.begin_bi.idx]
        b_start_idx = (prev_zs[-1].end_bi.idx + 1) if prev_zs else seg.start_bi.idx
        b_lo = max(b_start_idx - base, 0)
        b_hi = bi_in.idx - base
        b_window = seg.bi_list[b_lo:b_hi + 1] if b_hi >= b_lo else None
        # --- c 窗口：离开笔之后 ~ 线段末笔 ---
        c_lo = zs.end_bi.idx + 1 - base
        c_hi = seg.end_bi.idx - base
        c_window = seg.bi_list[c_lo:c_hi + 1] if c_hi >= c_lo else None
        return b_window, c_window, "swing"

    def treat_bsp1(self, seg: CSeg[LINE_TYPE], BSP_CONF: CPointConfig, is_target_bsp: bool,
                   full_ele_list=None):
        """
        处理标准第一类买卖点（中枢背驰）

        参数:
            full_ele_list: 该级别全量要素列表（`bi_list.bi_list` / 线段级别传 None）。
                仅 `bsp1_new_extreme_mode="level"` 时用于跨线段取值；其余口径忽略，
                因此不传不会改变任何现有行为。

        判定顺序：
        1. 离开笔是否是极值（如果 bs1_peak=True）
        2. 中枢是否发生面积背驰（is_divergence）
        3. 四项标准判据：趋势前提、创趋势新低、DIF 背驰、零轴回抽

        第 3 步的每一项都由配置单独开关，默认全开；`bsp_preset="legacy"`
        会全部关闭并复现改造前行为。

        降级路由（chan-standard-bsp1-change）：当趋势前提不达标（reason=='trend'）
        但背驰链路本身成立（面积背驰实证 + 极值判据）且其余标准判据全检通过时，
        该点以 T1P 类型登记而非丢弃——见下方触发条件与 design.md D1/D2。
        降级点固定 is_target_bsp=False，绝不进入 bsp1_sure_dict / bsp1_sure_list，
        因此不会被 treat_bsp2 / treat_bsp3 当作一买锚点（锚点隔离，design D2/D4）。
        """
        is_buy = seg.is_down()
        last_zs = seg.zs_lst[-1]
        # 力度口径（chan-standard-bsp1-change D7 / §4.4）：
        # "swing"（默认）按走势段取值，"bi" 沿用改造前的单笔口径
        b_window, c_window, scope_effective = self._cal_force_windows(seg, last_zs, BSP_CONF)
        break_peak, _ = last_zs.out_bi_is_peak(seg.end_bi.idx, strict=BSP_CONF.bs1_peak_strict)
        # ② 突破中枢：`is_divergence` 内部会短路判定，这里单独取一次结果，
        # 供进度轴（chan-bsp-ladder-change D1）定位首个失败项。
        break_ok = last_zs.end_bi_break(seg.end_bi)
        # 背驰链路成立性（降级路由复用）：极值判据（bs1_peak=False 时放行）
        peak_ok = (not BSP_CONF.bs1_peak) or break_peak
        if not peak_ok:
            is_target_bsp = False
        is_diver, divergence_rate = last_zs.is_divergence(
            BSP_CONF, out_bi=seg.end_bi, b_window=b_window, c_window=c_window)
        # 背驰链路成立性（降级路由复用）：面积背驰
        divergence_ok = is_diver
        if not divergence_ok:
            is_target_bsp = False
        standard_ok, standard_reason, standard_info = check_bsp1_standard(
            seg.end_bi, seg.bi_list, seg.zs_lst, BSP_CONF, is_buy,
            full_ele_list=full_ele_list)
        if not standard_ok:
            is_target_bsp = False

        # ---- 降级路由（chan-standard-bsp1-change，design D1）----
        # 触发条件（全部满足才降级）：
        #   1. 开关开启：BSP_CONF.bsp1_downgrade_to_pz
        #   2. 趋势判据拦下：仅 reason=='trend' 不通过（入口，非充分条件）
        #   3. 背驰实证：diver_proven = is_diver and BSP_CONF.divergence_rate <= 100
        #      注意必须读配置阈值 BSP_CONF.divergence_rate，不是 is_divergence 返回的
        #      实测比率——divergence_rate > 100（显式关闭背驰）时 is_divergence
        #      无条件返回 True（空真，见 ZS.is_divergence 的 >100 分支），那是放行
        #      语义不是证据；两处 >100 魔数互为口径依赖，禁止任一侧单独改阈值。
        #   4. 极值判据：peak_ok
        #   5. 其余标准判据全检通过：rest_ok（D1-b：reason=='trend' 短路时后三项
        #      根本没跑，须以 bsp1_trend=False 重跑全检；D1-c：重跑时须强制
        #      bsp1_new_extreme_mode="all"，否则新低比较窗口随中枢形态漂移）
        downgrade = False
        if (BSP_CONF.bsp1_downgrade_to_pz
                and not standard_ok and standard_reason == 'trend'
                and divergence_ok and BSP_CONF.divergence_rate <= 100
                and peak_ok):
            if BSP_CONF.bsp1_trend:
                # D1-b/D1-c：副本配置关趋势 + 新低口径统一为 all，重跑其余判据
                rest_conf = copy.copy(BSP_CONF)
                rest_conf.bsp1_trend = False
                rest_conf.bsp1_new_extreme_mode = "all"
                rest_ok, _, _ = check_bsp1_standard(
                    seg.end_bi, seg.bi_list, seg.zs_lst, rest_conf, is_buy)
            else:
                # 趋势本已关闭时 standard_ok 即为全检结果，避免重复调用
                rest_ok = standard_ok
            if rest_ok:
                downgrade = True

        # ---- 判据链进度透出（chan-bsp-ladder-change D1）----
        # 统一七项序号：①趋势 ②突破 ③极值 ④力度背驰 ⑤新低 ⑥DIF ⑦零轴。
        # ②③④ 在本函数内先于标准判据链执行，故以逐项布尔透出；①⑤⑥⑦ 由
        # WebAPI 层依 `bsp1_standard_reason` 反推（design D1：反推表放 WebAPI，
        # 内核只提供事实）。这些键是内核 → WebAPI 的隐式契约，改动须同步
        # `WebAPI/bsp_ladder.py` 与 `文档/缠论策略.md`。
        feature_dict = {
            'divergence_rate': divergence_rate,
            'zs_cnt': len(seg.zs_lst),
            'bsp1_standard_reason': standard_reason,
            # ② 突破中枢：`is_divergence` 内部会短路判定，这里单独取一次结果
            'bsp1_step_break': break_ok,
            # ③ 极值判据（已含 bs1_peak=False 的放行语义）
            'bsp1_step_peak': peak_ok,
            # ④ 力度背驰（divergence_rate>100 时为放行空真，与既有语义一致）
            'bsp1_step_diver': divergence_ok,
        }
        # 成交量/换手率类算法在走势段档下退回单笔——标出来使差异可见（D7-c）
        if scope_effective == "bi_fallback":
            feature_dict['bsp1_force_scope_effective'] = "bi_fallback"
        feature_dict.update(standard_info)
        if downgrade:
            # 降级点以 T1P 登记但不作锚点（design D2）：固定 is_target_bsp=False，
            # 绝不进 bsp1_sure_dict / bsp1_sure_list
            feature_dict['bsp1_downgrade_reason'] = (
                'single_zs' if standard_info.get('zs_cnt', 0) < 2 else 'no_trend')
            self.add_bs(bs_type=BSP_TYPE.T1P, bi=seg.end_bi, relate_bsp1=None,
                        is_target_bsp=False, feature_dict=feature_dict,
                        is_downgrade=True)
            return
        self.add_bs(bs_type=BSP_TYPE.T1, bi=seg.end_bi, relate_bsp1=None,
                    is_target_bsp=is_target_bsp, feature_dict=feature_dict)

    def treat_pz_bsp1(self, seg: CSeg[LINE_TYPE], BSP_CONF: CPointConfig, bi_list: LINE_LIST_TYPE, is_target_bsp):
        """
        处理盘整背驰买卖点（T1P）

        判断逻辑：
        1. 最后两笔必须在同一线段内
        2. 最后两笔方向必须与线段方向一致
        3. 最后一笔必须创新高/新低
        4. 最后一笔的 MACD 指标 < 前前笔的 MACD 指标（背驰）

        与降级路由 T1P 的边界（chan-standard-bsp1-change task 2.5）：
        本函数处理的是**无结构中枢**的笔背驰（最后两笔同段同向、逐笔比较）；
        降级路由 T1P 处理的是**有中枢但趋势前提不达标**的点（离开笔 vs 进入笔，
        经 check_bsp1_standard 全检）。二者是两套完全不同的结构，只能并列、
        不能复用——复用会同时改变既有 T1P 的输出（design.md Context）。
        """
        last_bi = seg.end_bi
        pre_bi = bi_list[last_bi.idx-2]
        if last_bi.seg_idx != pre_bi.seg_idx:
            return
        if last_bi.dir != seg.dir:
            return
        if last_bi.is_down() and last_bi._low() > pre_bi._low():  # 没有创新低
            return
        if last_bi.is_up() and last_bi._high() < pre_bi._high():  # 没有创新高
            return

        # ---- 力度口径（chan-bsp-ladder-change D4）----
        # 与 T1 的 `bsp1_force_scope` 同构：默认 "swing" 按**走势段**取值，
        # "bi" 沿用改造前的单笔口径（legacy 档展开为 "bi"，保证旧行为可复现）。
        #
        # 有结构中枢时 T1 的 b/c 由「中枢」分隔；本路径无中枢，分隔物换成
        # **反向笔组**：线段内同向笔被反向笔天然分成若干组，末组（含 last_bi）
        # 是 c 段，倒数第二组是 b 段。仅一组时（线段内无反向笔）退回单笔。
        b_window, c_window, scope_effective = self._cal_pz_force_windows(seg, last_bi, BSP_CONF)
        is_diver, divergence_rate = self._pz_divergence(
            pre_bi, last_bi, b_window, c_window, BSP_CONF)
        if not is_diver:
            is_target_bsp = False
        feature_dict = {
            'divergence_rate': divergence_rate,
            'bsp1_bi_amp': last_bi.amp(),
        }
        # 成交量/换手率类算法在走势段档下退回单笔——标出来使差异可见（同 D7-c）
        if scope_effective == "bi_fallback":
            feature_dict['bsp1_force_scope_effective'] = "bi_fallback"
        self.add_bs(bs_type=BSP_TYPE.T1P, bi=last_bi, relate_bsp1=None, is_target_bsp=is_target_bsp, feature_dict=feature_dict)

    def _pz_divergence(self, pre_bi: LINE_TYPE, last_bi: LINE_TYPE,
                       b_window, c_window, BSP_CONF: CPointConfig):
        """盘整背驰路径的力度比较（支持多指标 AND）。

        与 `CZS.is_divergence` 同构，但比较的是**两根同向笔**而不是中枢的
        进入/离开笔。多指标时要求**每一项都满足**，返回的背驰率取各指标中
        的最大值（最不容易背驰的那一项）。

        `pre_bi` / `last_bi` 是两个取值窗口的兜底单笔：窗口为 None（`"bi"` 档，
        或全部指标都是量能类）时直接按它们算。
        """
        rates = []
        all_diverged = True
        # 兼容只暴露 `macd_algo` 的历史桩件/配置对象
        for algo in cfg_algos(BSP_CONF):
            if b_window is None and c_window is None:
                # 单笔口径（"bi" 档或算法不支持区间）：保持改造前行为
                in_metric = pre_bi.cal_macd_metric(algo, is_reverse=False)
                out_metric = last_bi.cal_macd_metric(algo, is_reverse=True)
            else:
                in_metric = _span_metric(
                    b_window, algo, is_reverse=False,
                    fallback=lambda a=algo: pre_bi.cal_macd_metric(a, is_reverse=False))
                out_metric = _span_metric(
                    c_window, algo, is_reverse=True,
                    fallback=lambda a=algo: last_bi.cal_macd_metric(a, is_reverse=True))
            rates.append(out_metric / (in_metric + 1e-7))
            if not out_metric <= BSP_CONF.divergence_rate * in_metric:
                all_diverged = False
        return all_diverged, (max(rates) if rates else None)

    def _cal_pz_force_windows(self, seg: CSeg, last_bi: LINE_TYPE, BSP_CONF: CPointConfig):
        """盘整背驰路径的 b/c 力度窗口（chan-bsp-ladder-change D4）。

        与 T1 的 `_cal_force_windows` 同构，但**分隔物从中枢换成反向笔组**：
        本路径的前提是无结构中枢，没有中枢可用来分隔进入段与离开段。

        返回 `(b_window, c_window, effective)`：
            b_window: 倒数第二个同向笔组（若不存在则 None → 退单笔）
            c_window: 末组同向笔（含 last_bi）
            effective: `"swing"` / `"bi"` / `"bi_fallback"`

        **索引注意**：`seg.bi_list` 是线段内连续切片，`seg.bi_list[i]` 对应
        全局 `bi_list[seg.start_bi.idx + i]`——因此按下标切片而非全局 idx。

        仅一组同向笔时（线段内没有反向笔）b 窗口为 None：此时「进入段」
        本身不存在，单笔口径是唯一自洽解释。
        """
        if BSP_CONF.bsp1_force_scope == "bi":
            return None, None, "bi"
        if not any_span_supported(cfg_algos(BSP_CONF)):
            # 全部选中的指标都是成交量/换手率类，没有区间版本，退回单笔口径
            return None, None, "bi_fallback"

        bi_lst = list(seg.bi_list)
        if not bi_lst:
            return None, None, "bi_fallback"

        # 从末尾向前收集同向（last_bi 方向）的连续笔 → c 段
        target_dir = last_bi.dir
        c_start = len(bi_lst) - 1
        while c_start - 1 >= 0 and bi_lst[c_start - 1].dir == target_dir:
            c_start -= 1
        c_window = bi_lst[c_start:]

        # 再向前跳过反向笔组，然后收集下一组同向笔 → b 段
        b_end = c_start - 1
        while b_end >= 0 and bi_lst[b_end].dir != target_dir:
            b_end -= 1
        if b_end < 0:
            # 线段内只有一组同向笔，b 段不存在 → 单笔口径
            return None, c_window, "swing"
        b_start = b_end
        while b_start - 1 >= 0 and bi_lst[b_start - 1].dir == target_dir:
            b_start -= 1
        b_window = bi_lst[b_start:b_end + 1]
        return b_window, c_window, "swing"

    def cal_seg_bs2point(self, seg_list: CSegListComm[LINE_TYPE], bi_list: LINE_LIST_TYPE):
        """
        计算第二类买卖点

        遍历线段，对每个线段调用 treat_bsp2。

        第二类买卖点：第一类买卖点后，回测中枢不破。
        """
        for seg in seg_list[self.last_sure_seg_idx:]:
            config = self.config.GetBSConfig(seg.is_down())
            if BSP_TYPE.T2 not in config.target_types and BSP_TYPE.T2S not in config.target_types:
                continue
            if not self.seg_need_cal(seg):
                continue
            self.treat_bsp2(seg, seg_list, bi_list)

    def treat_bsp2(self, seg: CSeg, seg_list: CSegListComm[LINE_TYPE], bi_list: LINE_LIST_TYPE):
        """
        处理第二类买卖点

        判断逻辑：
        1. 找到第一类买卖点后的反向笔（break_bi）
        2. 再往后一笔（bsp2_bi）回测中枢
        3. 回撤率 = bsp2_bi振幅 / break_bi振幅
        4. 回撤率 < max_bs2_rate → 第二类买卖点

        缠论知识 - 第二类买卖点：
        第一类买卖点后，价格反向运动形成 break_bi，
        然后再次反向（回测方向）形成 bsp2_bi。
        如果 bsp2_bi 的回撤幅度小于 break_bi 的一定比例，
        说明中枢支撑/压力有效，形成第二类买卖点。
        """
        if len(seg_list) > 1:
            BSP_CONF = self.config.GetBSConfig(seg.is_down())
            bsp1_bi = seg.end_bi
            real_bsp1 = self.bsp1_sure_dict.get(bsp1_bi.idx)
            if bsp1_bi.idx + 2 >= len(bi_list):
                return
            break_bi = bi_list[bsp1_bi.idx + 1]  # 第一类后的反向笔
            bsp2_bi = bi_list[bsp1_bi.idx + 2]   # 再反向的回测笔
        else:
            # 第一条线段（没有前面的线段）
            # 配置方向必须与其余分支一致：下线段取买侧配置。
            # 历史实现在此处写成 seg.is_up()，与同函数内的 treat_bsp2s 自相矛盾，
            # 一旦用户用 -buy/-sell 分别配置参数就会取错侧。
            BSP_CONF = self.config.GetBSConfig(seg.is_down())
            bsp1_bi, real_bsp1 = None, None
            if len(bi_list) == 1:
                return
            bsp2_bi = bi_list[1]
            break_bi = bi_list[0]

        if BSP_CONF.bsp2_follow_1 and (not bsp1_bi or bsp1_bi.idx not in self.bsp1_sure_dict):
            return

        # 判据抽到层级无关的纯函数：笔级别与线段级别同构
        bsp2_flag, bsp2_reason, feature_dict = check_bsp2_standard(
            bsp2_bi, break_bi, getattr(seg, "zs_lst", []), BSP_CONF)
        feature_dict['bsp2_reason'] = bsp2_reason
        if bsp2_flag:
            self.add_bs(bs_type=BSP_TYPE.T2, bi=bsp2_bi, relate_bsp1=real_bsp1, feature_dict=feature_dict)
        if BSP_TYPE.T2S not in self.config.GetBSConfig(seg.is_down()).target_types:
            return
        self.treat_bsp2s(seg_list, bi_list, bsp2_bi, break_bi, real_bsp1, BSP_CONF,
                         bsp2_ok=bsp2_flag)

    def treat_bsp2s(
        self,
        seg_list: CSegListComm,
        bi_list: LINE_LIST_TYPE,
        bsp2_bi: LINE_TYPE,
        break_bi: LINE_TYPE,
        real_bsp1: Optional[CBS_Point],
        BSP_CONF: CPointConfig,
        bsp2_ok: bool = True,
    ):
        """
        处理类二买卖点（T2S）

        类二买卖点：中枢内多次回测形成的买卖点。

        从 bsp2_bi 开始，每隔2笔（同向笔）检查：
        1. 是否在同一线段内
        2. 是否与前一回测笔有重叠区间
        3. 是否突破了 break_bi 的端点
        4. 回撤率是否不超过 max_bs2_rate（量纲由 bsp2s_rate_mode 决定）
        5. 末端价格是否落在某多笔中枢区间内（bsp2s_require_zs，默认开启）

        缠论知识 - 类二买卖点：
        中枢内可以多次回测，每次回测都可能形成类二买卖点。
        类二买卖点的级别比第二类买卖点低，但数量更多。

        参数:
            bsp2_ok: 该位置的二买是否成立。`bsp2s_follow_2` 开启且此处为 False
                时直接返回——历史实现把这个判断放在了「二买未命中」分支里，
                导致开关语义与文档相反（见 design D17）。
        """
        if BSP_CONF.bsp2s_follow_2 and not bsp2_ok:
            return

        bias = 2
        _low, _high = None, None
        while bsp2_bi.idx + bias < len(bi_list):
            bsp2s_bi = bi_list[bsp2_bi.idx + bias]
            assert bsp2s_bi.seg_idx is not None and bsp2_bi.seg_idx is not None
            if BSP_CONF.max_bsp2s_lv is not None and bias/2 > BSP_CONF.max_bsp2s_lv:
                break
            if bsp2s_bi.seg_idx != bsp2_bi.seg_idx and \
               (bsp2s_bi.seg_idx < len(seg_list)-1 or bsp2s_bi.seg_idx - bsp2_bi.seg_idx >= 2 or seg_list[bsp2_bi.seg_idx].is_sure):
                break
            if bias == 2:
                if not has_overlap(bsp2_bi._low(), bsp2_bi._high(), bsp2s_bi._low(), bsp2s_bi._high()):
                    break
                _low = max([bsp2_bi._low(), bsp2s_bi._low()])
                _high = min([bsp2_bi._high(), bsp2s_bi._high()])
            elif not has_overlap(_low, _high, bsp2s_bi._low(), bsp2s_bi._high()):
                break

            if bsp2s_break_bsp1(bsp2s_bi, break_bi):
                break
            if BSP_CONF.bsp2s_rate_mode == "amp":
                # 与二买同构：振幅之比。旧口径是「端点位移 / 参照笔振幅」，
                # 两者共用 max_bs2_rate 但量纲不同（design D16）。
                retrace_rate = bsp2s_bi.amp() / break_bi.amp()
            else:
                retrace_rate = abs(bsp2s_bi.get_end_val()-break_bi.get_end_val())/break_bi.amp()
            if retrace_rate > BSP_CONF.max_bs2_rate:
                break
            if BSP_CONF.bsp2s_require_zs:
                # 类二的理论定义是「中枢内的回抽」。判据对象是回抽点的**末端价格**：
                # 整笔区间口径在实测中只剔除 6/157，几乎不过滤（design D15）。
                seg_zs = getattr(bsp2s_bi, "parent_seg", None)
                if seg_zs is None or not check_ele_end_in_zs(bsp2s_bi, seg_zs.zs_lst):
                    break
            feature_dict = {
                'bsp2s_retrace_rate': retrace_rate,
                'bsp2s_break_bi_amp': break_bi.amp(),
                'bsp2s_bi_amp': bsp2s_bi.amp(),
                'bsp2s_lv': bias/2,
                'bsp2s_rate_mode': BSP_CONF.bsp2s_rate_mode,
            }
            self.add_bs(bs_type=BSP_TYPE.T2S, bi=bsp2s_bi, relate_bsp1=real_bsp1, feature_dict=feature_dict)
            bias += 2

    def cal_seg_bs3point(self, seg_list: CSegListComm[LINE_TYPE], bi_list: LINE_LIST_TYPE):
        """
        计算第三类买卖点

        遍历线段，对每个线段检查 T3A 和 T3B 类型。

        缠论知识 - 第三类买卖点：
        离开中枢的笔突破中枢后，回测不破中枢的区间。
        - T3A: 中枢之后形成（下一个线段中）
        - T3B: 中枢之前形成（同一线段中，盘整背驰后的第三类）
        """
        for seg in seg_list[self.last_sure_seg_idx:]:
            if not self.seg_need_cal(seg):
                continue
            config = self.config.GetBSConfig(seg.is_down())
            if BSP_TYPE.T3A not in config.target_types and BSP_TYPE.T3B not in config.target_types:
                continue
            if len(seg_list) > 1:
                bsp1_bi = seg.end_bi
                bsp1_bi_idx = bsp1_bi.idx
                BSP_CONF = self.config.GetBSConfig(seg.is_down())
                real_bsp1 = self.bsp1_sure_dict.get(bsp1_bi.idx)
                next_seg_idx = seg.idx+1
                next_seg = seg.next
            else:
                next_seg = seg
                next_seg_idx = seg.idx
                bsp1_bi, real_bsp1 = None, None
                bsp1_bi_idx = -1
                BSP_CONF = self.config.GetBSConfig(seg.is_up())
            # 一买跟随校验（design D20）：只用一买专用集合，不用
            # `bsp_store_flat_dict`——后者登记了全部类型，二买/类二也会让它通过。
            if BSP_CONF.bsp3_follow_1 and not self._bsp3_follow1_ok(bsp1_bi, BSP_CONF):
                continue
            if next_seg:
                self.treat_bsp3_after(seg_list, next_seg, BSP_CONF, bi_list, real_bsp1, bsp1_bi_idx, next_seg_idx)
            self.treat_bsp3_before(seg_list, seg, next_seg, bsp1_bi, BSP_CONF, bi_list, real_bsp1, next_seg_idx)

    def _bsp3_follow1_ok(self, bsp1_bi, BSP_CONF: CPointConfig) -> bool:
        """
        三买「必须跟随一买」的校验

        `bsp3_follow_1_mode="sure"`（默认）查已成立的一买集合；
        `"candidate"` 查全部结构性候选。两种都只查**一买专用**集合——
        历史实现查 `bsp_store_flat_dict`，该字典登记了全部类型，
        某笔只是二买也能通过校验。
        """
        if bsp1_bi is None:
            return False
        if BSP_CONF.bsp3_follow_1_mode == "sure":
            return bsp1_bi.idx in self.bsp1_sure_dict
        return bsp1_bi.idx in self.bsp1_dict

    def treat_bsp3_after(
        self,
        seg_list: CSegListComm[LINE_TYPE],
        next_seg: CSeg[LINE_TYPE],
        BSP_CONF: CPointConfig,
        bi_list: LINE_LIST_TYPE,
        real_bsp1,
        bsp1_bi_idx,
        next_seg_idx
    ):
        """
        处理第三类A买卖点（T3A：中枢之后）

        在下一条线段中找中枢后的回测笔：
        1. 遍历下一条线段中的所有多笔中枢
        2. 每个中枢的 bi_out 之后的第一笔如果回测不破中枢 → T3A
        3. bsp3a_max_zs_cnt 限制最多检查的中枢数量
        """
        first_zs = next_seg.get_first_multi_bi_zs()
        if first_zs is None:
            return
        if BSP_CONF.strict_bsp3 and first_zs.get_bi_in().idx != bsp1_bi_idx+1:
            return

        config = self.config.GetBSConfig(next_seg.is_down())
        bsp3a_max_zs_cnt = config.bsp3a_max_zs_cnt
        for zs_idx, zs in enumerate(next_seg.get_multi_bi_zs_lst()):
            if zs_idx >= bsp3a_max_zs_cnt:
                break
            if zs.bi_out is None or zs.bi_out.idx+1 >= len(bi_list):
                break
            bsp3_bi = bi_list[zs.bi_out.idx+1]
            if bsp3_bi.parent_seg is None:
                if next_seg.idx != len(seg_list)-1:
                    break
            elif bsp3_bi.parent_seg.idx != next_seg.idx:
                if len(bsp3_bi.parent_seg.bi_list) >= 3:
                    break
            if bsp3_bi.dir == next_seg.dir:
                break
            if bsp3_bi.seg_idx != next_seg_idx and next_seg_idx < len(seg_list)-2:
                break
            if bsp3_back2zs(bsp3_bi, zs):
                continue
            # 极值判据对象（design D19）：`bsp3_peak_on_breakout=True`（默认）判
            # **突破笔**是否冲破中枢内部极值，与 README 的语义一致；
            # `False` 保留历史行为（判回抽笔，且只在 T3A 生效）。
            if BSP_CONF.bsp3_peak:
                peak_ok = (check_zs_peak_on_breakout(zs)
                           if BSP_CONF.bsp3_peak_on_breakout
                           else bsp3_break_zspeak(bsp3_bi, zs))
                if not peak_ok:
                    continue
            feature_dict = {
                'bsp3_zs_height': (zs.high - zs.low)/zs.low,
                'bsp3_bi_amp': bsp3_bi.amp(),
                # 锚定中枢区间快照（chan-standard-bsp3-change D7）：确认轴的
                # 证伪线须以「判据链实际采纳的**这个**中枢」为基准，而不是
                # 「回抽笔所在线段的最后中枢」——两者不等价（差异点文档统计
                # 口径声明）。存数值而非对象引用，避免重算后中枢对象变化
                # 导致证伪基准漂移。**只读特征**，不参与任何成立判定。
                'bsp3_zs_low': zs.low,
                'bsp3_zs_high': zs.high,
            }
            self.add_bs(bs_type=BSP_TYPE.T3A, bi=bsp3_bi, relate_bsp1=real_bsp1, feature_dict=feature_dict)

    def treat_bsp3_before(
        self,
        seg_list: CSegListComm[LINE_TYPE],
        seg: CSeg[LINE_TYPE],
        next_seg: Optional[CSeg[LINE_TYPE]],
        bsp1_bi: Optional[LINE_TYPE],
        BSP_CONF: CPointConfig,
        bi_list: LINE_LIST_TYPE,
        real_bsp1,
        next_seg_idx
    ):
        """
        处理第三类B买卖点（T3B：中枢本线段内）

        中枢形成后，离开笔突破中枢、随后第一笔回抽不回到中枢区间 → T3B。

        `bsp3b_mode="standard"`（默认）按标准三买判定：
            1. 锚点为该线段内最后一个多笔中枢
            2. 离 开 笔方向必须正确并真正突破中枢
               （买：向上且高点 > 中枢上沿；卖：向下且低点 < 中枢下沿）
            3. 回抽笔是离开笔之后的**第一笔**反向要素
            4. 回抽笔不回到中枢区间

        `bsp3b_mode="legacy"` 保留历史行为：从一买笔 +2 起每隔 2 笔扫描、
        遇到回中枢的笔继续后扫。历史行为实测 11 个样本中 0 个是「第一次回抽」，
        且有 7 个与二买/类二落在同一笔，因此不是标准三买（design D18）。
        """
        cmp_zs = seg.get_final_multi_bi_zs()
        if cmp_zs is None:
            return
        if not bsp1_bi:
            return
        if BSP_CONF.strict_bsp3 and (cmp_zs.bi_out is None or cmp_zs.bi_out.idx != bsp1_bi.idx):
            return

        is_buy = seg.is_down()
        if BSP_CONF.bsp3b_mode == "legacy":
            self._treat_bsp3_before_legacy(seg_list, next_seg, BSP_CONF, cmp_zs, bi_list,
                                           real_bsp1, next_seg_idx, bsp1_bi)
            return

        # ---- 标准三买 ----
        # 买卖侧由中枢离开笔的实际方向决定：在一买所在的下跌线段内，
        # 中枢的离开笔通常仍向下，它构成的是三卖形态。把 is_buy 绑到
        # seg.is_down() 上会让该分支永远不成立（实测 58/58 全部 no_breakout）。
        breakout_ok, retrace_is_buy, _ = check_breakout(cmp_zs)
        if not breakout_ok:
            return
        bsp3_bi, retrace_ok = get_first_retrace(bi_list, cmp_zs, retrace_is_buy)
        if bsp3_bi is None:
            return
        if not retrace_ok:
            return
        if BSP_CONF.strict_bsp3 and bsp3_bi.seg_idx != next_seg_idx:
            return
        if next_seg is not None and bsp3_bi.idx > cal_bsp3_bi_end_idx(next_seg) and \
                next_seg_idx < len(seg_list) - 2:
            return
        if back_to_zs(bsp3_bi, cmp_zs):
            return
        if BSP_CONF.bsp3_peak and not check_zs_peak_on_breakout(cmp_zs):
            return
        feature_dict = {
            'bsp3_zs_height': (cmp_zs.high - cmp_zs.low)/cmp_zs.low,
            'bsp3_bi_amp': bsp3_bi.amp(),
            'bsp3b_mode': 'standard',
            # 锚定中枢区间快照（chan-standard-bsp3-change D7）：确认轴证伪线
            # 以此为准。**只读特征**，不参与任何成立判定。
            'bsp3_zs_low': cmp_zs.low,
            'bsp3_zs_high': cmp_zs.high,
        }
        self.add_bs(bs_type=BSP_TYPE.T3B, bi=bsp3_bi, relate_bsp1=real_bsp1, feature_dict=feature_dict)

    def _treat_bsp3_before_legacy(self, seg_list, next_seg, BSP_CONF, cmp_zs, bi_list,
                                  real_bsp1, next_seg_idx, bsp1_bi):
        """T3B 的历史实现（`bsp3b_mode="legacy"`）：逐笔后延扫描，遇回中枢继续。"""
        end_bi_idx = cal_bsp3_bi_end_idx(next_seg)
        for bsp3_bi in bi_list[bsp1_bi.idx+2::2]:  # 每隔2笔取一笔（同向笔）
            if bsp3_bi.idx > end_bi_idx:
                break
            assert bsp3_bi.seg_idx is not None
            if bsp3_bi.seg_idx != next_seg_idx and bsp3_bi.seg_idx < len(seg_list)-1:
                break
            if bsp3_back2zs(bsp3_bi, cmp_zs):
                continue
            feature_dict = {
                'bsp3_zs_height': (cmp_zs.high - cmp_zs.low)/cmp_zs.low,
                'bsp3_bi_amp': bsp3_bi.amp(),
                'bsp3b_mode': 'legacy',
            }
            self.add_bs(bs_type=BSP_TYPE.T3B, bi=bsp3_bi, relate_bsp1=real_bsp1, feature_dict=feature_dict)
            break  # 只取第一个满足条件的

    def getSortedBspList(self) -> List[CBS_Point[LINE_TYPE]]:
        """
        获取按笔索引排序的买卖点列表

        Python 语法：sorted(iterable, key=lambda ...)
        Java 对比：stream.sorted(Comparator.comparing(bsp -> bsp.bi.idx)).collect(toList())
        """
        return sorted(self.bsp_iter(), key=lambda bsp: bsp.bi.idx)

    def get_latest_bsp(self, number: int) -> List[CBS_Point[LINE_TYPE]]:
        """
        获取最新的 N 个买卖点（按笔索引降序）

        参数:
            number: 获取数量，0 表示获取全部

        返回:
            最新的买卖点列表
        """
        res = []
        for bsp in self.bsp_iter_v2():
            res.append(bsp)
            if number != 0 and len(res) >= number:
                break
        return res


def bsp2s_break_bsp1(bsp2s_bi: LINE_TYPE, bsp2_break_bi: LINE_TYPE) -> bool:
    """
    判断类二买卖点是否突破了第一类买卖点后的反向笔

    返回:
        True 如果突破了（类二买卖点不再有效）
    """
    return (bsp2s_bi.is_down() and bsp2s_bi._low() < bsp2_break_bi._low()) or \
           (bsp2s_bi.is_up() and bsp2s_bi._high() > bsp2_break_bi._high())


def bsp3_back2zs(bsp3_bi: LINE_TYPE, zs: CZS) -> bool:
    """
    判断第三类买卖点是否回到了中枢区间内

    返回:
        True 如果回到了中枢区间（第三类买卖点不成立）
    """
    return (bsp3_bi.is_down() and bsp3_bi._low() < zs.high) or \
           (bsp3_bi.is_up() and bsp3_bi._high() > zs.low)


def bsp3_break_zspeak(bsp3_bi: LINE_TYPE, zs: CZS) -> bool:
    """
    判断第三类买卖点是否突破了中枢的极值区间

    返回:
        True 如果突破了中枢极值
    """
    return (bsp3_bi.is_down() and bsp3_bi._high() >= zs.peak_high) or \
           (bsp3_bi.is_up() and bsp3_bi._low() <= zs.peak_low)


def cal_bsp3_bi_end_idx(seg: Optional[CSeg[LINE_TYPE]]):
    """
    计算第三类B买卖点的结束笔索引

    返回:
        结束笔索引，如果找不到则返回 float("inf")
    """
    if not seg:
        return float("inf")
    if seg.get_multi_bi_zs_cnt() == 0 and seg.next is None:
        return float("inf")
    end_bi_idx = seg.end_bi.idx-1
    for zs in seg.zs_lst:
        if zs.is_one_bi_zs():
            continue
        if zs.bi_out is not None:
            end_bi_idx = zs.bi_out.idx
            break
    return end_bi_idx