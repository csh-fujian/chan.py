# -*- coding: utf-8 -*-
"""
序列化模块 — 把 CChan 的计算结果序列化为 JSON，供前端消费。

遵循 design.md D2 定义的契约：
- 时间戳统一为毫秒 (CTime.ts * 1000)
- 笔/线段端点使用极值K线 (get_begin_klu/get_end_klu) + 极值价 (get_begin_val/get_end_val)
- 中枢使用 begin/end/low/high/mid
- 买卖点使用 klu 锚定K线 + is_buy + type
"""

import math
from typing import Any, Dict, List, Optional

from ChanAnalyse.Chan import CChan
from ChanAnalyse.Common.CEnum import BI_DIR, DATA_FIELD, KL_TYPE, MACD_ALGO
from ChanAnalyse.ZS.ZS import cfg_algos

from .chan_config_store import VOLUME_MACD_ALGOS


def _bival_to_str(bival: BI_DIR) -> str:
    """将 BI_DIR 枚举转换为前端字符串 "UP" 或 "DOWN"."""
    return "UP" if bival == BI_DIR.UP else "DOWN"


# ----------------------------------------------------------------------
# 最近元素背驰判定（chan-recent-divergence-mark design D2/D3/D4）
# ----------------------------------------------------------------------

def _last_divergence(cur, prev, algo, rate, is_seg: bool) -> Optional[bool]:
    """按单一力度算法比较「最近元素 vs 相邻同向前一元素」。

    返回 None 表示该算法上不可比（任一侧力度缺失或前值非正）。
    段级量能类算法（`CSeg.cal_macd_metric` 无分支，Seg.py 会抛异常）
    回退 `MACD_ALGO.PEAK`（与买卖点链路 `SEG_FALLBACK_MACD_ALGO` 同口径）。
    """
    if is_seg:
        algo_name = getattr(algo, "name", str(algo)).lower()
        if algo_name in VOLUME_MACD_ALGOS:
            algo = MACD_ALGO.PEAK
    cur_m = cur.cal_macd_metric(algo, is_reverse=False)
    prev_m = prev.cal_macd_metric(algo, is_reverse=False)
    if cur_m is None or prev_m is None or prev_m <= 0:
        return None
    # 力度本身为非正（如 SLOPE/AMP 在跌段为负、DIF 在零轴下为负）时
    # 「商 <= 阈值」的单调语义不再成立，判不可比
    if cur_m <= 0:
        return None
    return cur_m <= rate * prev_m


def cal_last_divergence(lst, seg_conf) -> Optional[bool]:
    """列表末尾元素相对相邻同向前一元素的背驰判定（口径 A）。

    参数:
        lst: `CBiList` / `CSegListComm`（或其 lst）——只看末尾两个同向元素
        seg_conf: 段级 `CPointConfig`（笔级传 None，走 `bs_conf` 形参的差异
            见调用方：本函数内部不区分级别，只按 `seg_conf is None` 决定
            是否启用段级量能回退）

    返回: True（背驰）/ False（不背驰）/ None（不适用或未计算）。

    - 判据：对 `seg_conf.macd_algos` 每一项都有
      `力度[末尾] <= divergence_rate * 力度[前一]`（AND，ZS.is_divergence 范式）
    - `divergence_rate = inf`（完全不看力度）→ None
    - 同向前一元素不存在（列表不足）、方向不交替、力度不可比 → None
    """
    if lst is None:
        return None
    items = list(lst)
    if len(items) < 3:
        return None
    cur = items[-1]
    prev = items[-3]  # 相邻同向前一元素（中间隔一条反向元素）
    # 结构上末尾元素应与 items[-3] 同向（与 items[-2] 反向）；防御性校验
    if cur.is_down() != prev.is_down():
        return None
    if seg_conf is None:
        return None
    rate = getattr(seg_conf, "divergence_rate", None)
    if rate is None:
        return None
    try:
        if math.isinf(float(rate)):
            return None
    except (TypeError, ValueError):
        return None
    algos = cfg_algos(seg_conf)
    if not algos:
        return None
    is_seg = seg_conf is not None and getattr(cur, "start_bi", None) is not None
    diverged: Optional[bool] = None
    for algo in algos:
        d = _last_divergence(cur, prev, algo, rate, is_seg)
        if d is None:
            return None
        if diverged is None:
            diverged = d
        elif not d:
            diverged = False
    return diverged


def _serialize_klines(kl_list) -> List[Dict[str, Any]]:
    """序列化所有原始 K 线为列表."""
    result: List[Dict[str, Any]] = []
    for klu in kl_list.klu_iter():
        volume = klu.trade_info.metric.get(DATA_FIELD.FIELD_VOLUME) or 0
        result.append({
            "timestamp": int(klu.time.ts * 1000),
            "open": klu.open,
            "high": klu.high,
            "low": klu.low,
            "close": klu.close,
            "volume": int(volume),
        })
    return result


def _serialize_bi(bi_list, b_conf=None) -> List[Dict[str, Any]]:
    """序列化笔列表.

    末尾元素携带 `is_divergence`（chan-recent-divergence-mark）：
    最近一笔（含虚笔）相对相邻同向前一笔的背驰判定（None = 不适用/不计算）。
    非末尾元素不写该键。
    """
    result: List[Dict[str, Any]] = []
    for bi in bi_list:
        begin_klu = bi.get_begin_klu()
        end_klu = bi.get_end_klu()
        item = {
            "begin": {
                "t": int(begin_klu.time.ts * 1000),
                "v": bi.get_begin_val(),
            },
            "end": {
                "t": int(end_klu.time.ts * 1000),
                "v": bi.get_end_val(),
            },
            "dir": _bival_to_str(bi.dir),
            "is_sure": bi.is_sure,
        }
        result.append(item)
    if result and b_conf is not None:
        result[-1]["is_divergence"] = cal_last_divergence(bi_list, b_conf)
    return result


def _serialize_seg(seg_list, seg_b_conf=None) -> List[Dict[str, Any]]:
    """序列化线段列表（与笔同结构）.

    末尾元素携带 `is_divergence`（chan-recent-divergence-mark）：
    最近一段（含虚段）相对相邻同向前一段的背驰判定（None = 不适用/不计算）。
    非末尾元素不写该键。段级量能类算法回退 `peak`（design D4）。
    """
    result: List[Dict[str, Any]] = []
    for seg in seg_list:
        begin_klu = seg.get_begin_klu()
        end_klu = seg.get_end_klu()
        item = {
            "begin": {
                "t": int(begin_klu.time.ts * 1000),
                "v": seg.get_begin_val(),
            },
            "end": {
                "t": int(end_klu.time.ts * 1000),
                "v": seg.get_end_val(),
            },
            "dir": "UP" if seg.is_up() else "DOWN",
            "is_sure": seg.is_sure,
        }
        result.append(item)
    if result and seg_b_conf is not None:
        result[-1]["is_divergence"] = cal_last_divergence(seg_list, seg_b_conf)
    return result


def _serialize_zs(zs_list) -> List[Dict[str, Any]]:
    """序列化中枢列表."""
    result: List[Dict[str, Any]] = []
    for zs in zs_list:
        result.append({
            "begin_t": int(zs.begin.time.ts * 1000),
            "end_t": int(zs.end.time.ts * 1000),
            "low": zs.low,
            "high": zs.high,
            "mid": zs.mid,
        })
    return result


def _serialize_bsp(bs_point_lst, kl_list=None, sub_bsps=None, kl_type=None,
                   sub_kl_type=None, sub_bs_point_lst=None, sub_kl=None) -> List[Dict[str, Any]]:
    """序列化买卖点列表.

    is_sure：确认状态（bsp-sure-annotation D5），口径与 bsp_index 落库一致
    （水位线推导，复用 WebAPI/bsp_sure.py 公共工具函数），与 bi/seg 的 is_sure
    契约对齐。

    ladder：三轴阶梯（chan-bsp-ladder-change D1/D3）——本链路（/api/klines，
    单股请求）按需计算佐证轴：sub_bs_point_lst 为子级别买卖点容器
    （None = 无子级别/不计算），sub_kl 为子级别 CKLine_List（L2-1 分型档）。
    kl_list / kl_type / sub_kl_type 保留为旧签名兼容参数。

    entry：介入点候选（chan-entry-point-candidate 4.4）——**多级别链路读内核
    feature**（`_annotate_entry_point` 已在 cal()/refresh 收尾写入），与落库
    链路（`_extract_bsp_rows` 调共享核心）口径同源（design D6 双链路约定）。
    feature 缺失（开关全关 / 无子级）时 entry=False、method/level 为 None。
    """
    from .bsp_grade import grade_from_feature
    from .bsp_ladder import cal_ladder
    from .bsp_sure import bsp_is_sure

    bi_list = kl_list.bi_list if kl_list is not None else None
    # T2 五轴（chan-standard-bsp2-change D1/D3）：确认轴/时间轴需要
    # 本级别笔列表与配置。零改动覆盖：cal_ladder 类型分派后 T2 自动
    # 走五轴，参数从既有签名成员透传。
    bsp_cfg = None
    try:
        bsp_cfg = bs_point_lst.config
    except Exception:
        bsp_cfg = None
    result: List[Dict[str, Any]] = []
    for bsp in bs_point_lst.getSortedBspList():
        feats = dict(bsp.features.items()) if getattr(bsp, "features", None) else {}
        is_sure = bsp_is_sure(bsp, bs_point_lst)
        ladder = cal_ladder(
            bsp, bs_point_lst,
            bi_list=bi_list, sub_bsps=sub_bsps,
            kl_type=kl_type, sub_kl_type=sub_kl_type,
            sub_bs_point_lst=sub_bs_point_lst,
            sub_kl=sub_kl,
            bi_list_ref=bi_list,
            cfg=_cfg_for(bsp, bsp_cfg),
        )
        # 用户可读结论（chan-bsp-grading）：把 `L2` 这类内部编号翻译成
        # 强度分 / 强弱 / 操作建议 / 卡在哪一步。前端 tooltip 与列表直接用，
        # 不在前端重复推导口径 —— 与 ladder 同源，改一处两边同步。
        grade = grade_from_feature(feats, ladder, bool(bsp.is_buy), is_sure)
        result.append({
            "t": int(bsp.klu.time.ts * 1000),
            "v": bsp.klu.low if bsp.is_buy else bsp.klu.high,
            "is_buy": bsp.is_buy,
            "types": [t.value for t in bsp.type],
            "is_sure": is_sure,
            "ladder": ladder,
            # 介入点候选（chan-entry-point-candidate D6）：读内核 feature。
            # feature 只在介入开全部家族开关时由 `_annotate_entry_point` 写入。
            "entry": bool(feats.get("entry_hit", False)),
            "entry_method": feats.get("entry_method"),
            "entry_level": feats.get("entry_level"),
            # chan-bsp-grading：score 0~100 / grade 强弱 / advice 操作建议 /
            # blocked_by 卡在哪一步 / disclaimer 免责声明
            "grade": grade,
        })
    return result


def _cfg_for(bsp, bsp_cfg):
    """按买卖侧取 CPointConfig（与落库链路 `_extract_bsp_rows` 同一口径）。"""
    if bsp_cfg is None:
        return None
    try:
        return bsp_cfg.GetBSConfig(bool(bsp.is_buy))
    except Exception:
        return None


def serialize_chan(chan: CChan, kl_type: KL_TYPE, sub_chan: CChan = None, sub_kl_type: KL_TYPE = None) -> Dict[str, Any]:
    """
    将 CChan 指定级别的计算结果序列化为 JSON 字典。

    参数:
        chan: 已完成计算的 CChan 实例
        kl_type: 要导出的 K 线级别
        sub_chan: 子级别 CChan 实例（bsp-ladder-change D3：/api/klines 链路
            按需计算佐证轴；None = 不评估佐证轴）
        sub_kl_type: 子级别 K 线级别（与 sub_chan 配对）

    返回:
        包含 klines/bi/seg/zs/seg_zs/bsp 的字典，符合 design.md D2 契约。
    """
    kl_list = chan[kl_type]

    # 背驰判定配置（chan-recent-divergence-mark design D2）：
    # 笔级取 bs_point_lst.config 的买侧；段级取 seg_bs_point_lst.config，
    # 容器/属性缺失时回退笔级配置。
    b_conf = None
    seg_b_conf = None
    try:
        b_conf = kl_list.bs_point_lst.config.b_conf
    except Exception:
        b_conf = None
    try:
        seg_b_conf = kl_list.seg_bs_point_lst.config.b_conf
    except Exception:
        seg_b_conf = b_conf

    sub_bsps = None
    sub_bs_point_lst = None
    sub_kl = None
    if sub_chan is not None and sub_kl_type is not None:
        try:
            sub_kl = sub_chan[sub_kl_type]
            sub_bs_point_lst = sub_kl.bs_point_lst
            sub_bsps = list(sub_bs_point_lst.getSortedBspList())
        except Exception:
            sub_bsps = None  # 子级别计算失败 → 不做佐证轴
            sub_bs_point_lst = None
            sub_kl = None

    # 介入点候选（chan-entry-point-candidate D6）：本链路主级别是**单级别**
    # CChan（`_compute_chan`，子级别由 `compute_sub_chan` 旁路独立计算），
    # `cal()` 收尾时 `sub_bs_point_lst` 尚未挂载，内核 `_annotate_entry_point`
    # 因此从不写 feature。此处补挂只读引用并补跑注解（与 `CChan._refresh_qjt`
    # 的收尾同构），使序列化链路与落库链路的判定输入同口径。
    # 注解失败降级为无介入标记（entry 恒 False），不阻断序列化。
    if sub_bs_point_lst is not None:
        try:
            kl_list.bs_point_lst.attach_sub_bspoint_and_annotate(sub_bs_point_lst)
        except Exception:
            pass

    return {
        "klines": _serialize_klines(kl_list),
        "bi": _serialize_bi(kl_list.bi_list, b_conf=b_conf),
        "seg": _serialize_seg(kl_list.seg_list, seg_b_conf=seg_b_conf),
        "zs": _serialize_zs(kl_list.zs_list),
        "seg_zs": _serialize_zs(kl_list.segzs_list),
        "bsp": _serialize_bsp(
            kl_list.bs_point_lst, kl_list=kl_list, sub_bsps=sub_bsps,
            kl_type=kl_type, sub_kl_type=sub_kl_type,
            sub_bs_point_lst=sub_bs_point_lst, sub_kl=sub_kl,
        ),
        "pattern": _serialize_pattern(kl_list),
    }

# ---------------------------------------------------------------------------
# 形态信号序列化（chan-pattern-buy-signal 任务 4.2）
# ---------------------------------------------------------------------------

# 「新信号」时效：确认时间在最近 M 根 K 线内的信号显示醒目提示（design D5）。
# 检测窗口不受此限制——M 只控制提示时效。
PATTERN_NEW_BARS = 5


def _serialize_pattern(kl_list) -> list:
    """对当前 chan 的 (bi_list, K线) 现算形态检测 → pattern[]（降级路径：
    无 PG/无落库也能展示）。失败返回空数组，不阻断 klines 响应。"""
    try:
        from .pattern_detector import run_detection, _klus
        from .pattern_meta import PATTERN_META

        candles = _klus(kl_list)
        n = len(candles)
        if n == 0:
            return []
        hits = run_detection(kl_list.bi_list, kl_list)
        new_boundary = n - PATTERN_NEW_BARS  # confirm_idx >= 此值 → is_new
        out = []
        for h in hits:
            if not h.breakout.confirmed or h.breakout.confirm_idx is None:
                continue  # 未确认的候选不上图（spec：确认信号才提示）
            meta = PATTERN_META.get(h.pattern_type, {})
            ci = h.breakout.confirm_idx
            out.append({
                "type": h.pattern_type,
                "direction": h.direction,
                "name": meta.get("name", h.pattern_type),
                "confirm_idx": ci,
                "confirm_time": candles[ci].time.toDateStr("-") if ci < n else "",
                "price": float(candles[ci].close) if ci < n else 0.0,
                "ref_line_high": float(max(h.ref_line)),
                "ref_line_low": float(min(h.ref_line)),
                "key_points": h.key_points,
                "struct_begin_idx": h.struct_begin_idx,
                "struct_end_idx": h.struct_end_idx,
                "score": h.score,
                "qual": h.qual,
                "invalid": bool(h.breakout.invalidated),
                "veto": h.veto,
                "volume_ratio": h.breakout.volume_ratio,
                "is_new": ci >= new_boundary and not h.breakout.invalidated,
                "cautions": meta.get("cautions", []),
            })
        return out
    except Exception:
        import logging

        logging.getLogger("serializer").exception("形态序列化失败（返回空）")
        return []
