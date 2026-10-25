# -*- coding: utf-8 -*-
"""
序列化模块 — 把 CChan 的计算结果序列化为 JSON，供前端消费。

遵循 design.md D2 定义的契约：
- 时间戳统一为毫秒 (CTime.ts * 1000)
- 笔/线段端点使用极值K线 (get_begin_klu/get_end_klu) + 极值价 (get_begin_val/get_end_val)
- 中枢使用 begin/end/low/high/mid
- 买卖点使用 klu 锚定K线 + is_buy + type
"""

from typing import Any, Dict, List

from ChanAnalyse.Chan import CChan
from ChanAnalyse.Common.CEnum import BI_DIR, DATA_FIELD, KL_TYPE


def _bival_to_str(bival: BI_DIR) -> str:
    """将 BI_DIR 枚举转换为前端字符串 "UP" 或 "DOWN"."""
    return "UP" if bival == BI_DIR.UP else "DOWN"


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


def _serialize_bi(bi_list) -> List[Dict[str, Any]]:
    """序列化笔列表."""
    result: List[Dict[str, Any]] = []
    for bi in bi_list:
        begin_klu = bi.get_begin_klu()
        end_klu = bi.get_end_klu()
        result.append({
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
        })
    return result


def _serialize_seg(seg_list) -> List[Dict[str, Any]]:
    """序列化线段列表（与笔同结构）."""
    result: List[Dict[str, Any]] = []
    for seg in seg_list:
        begin_klu = seg.get_begin_klu()
        end_klu = seg.get_end_klu()
        result.append({
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
        })
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
    """
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
        result.append({
            "t": int(bsp.klu.time.ts * 1000),
            "v": bsp.klu.low if bsp.is_buy else bsp.klu.high,
            "is_buy": bsp.is_buy,
            "types": [t.value for t in bsp.type],
            "is_sure": bsp_is_sure(bsp, bs_point_lst),
            "ladder": cal_ladder(
                bsp, bs_point_lst,
                bi_list=bi_list, sub_bsps=sub_bsps,
                kl_type=kl_type, sub_kl_type=sub_kl_type,
                sub_bs_point_lst=sub_bs_point_lst,
                sub_kl=sub_kl,
                bi_list_ref=bi_list,
                cfg=_cfg_for(bsp, bsp_cfg),
            ),
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

    return {
        "klines": _serialize_klines(kl_list),
        "bi": _serialize_bi(kl_list.bi_list),
        "seg": _serialize_seg(kl_list.seg_list),
        "zs": _serialize_zs(kl_list.zs_list),
        "seg_zs": _serialize_zs(kl_list.segzs_list),
        "bsp": _serialize_bsp(
            kl_list.bs_point_lst, kl_list=kl_list, sub_bsps=sub_bsps,
            kl_type=kl_type, sub_kl_type=sub_kl_type,
            sub_bs_point_lst=sub_bs_point_lst, sub_kl=sub_kl,
        ),
    }