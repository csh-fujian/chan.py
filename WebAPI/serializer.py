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

from Chan import CChan
from Common.CEnum import BI_DIR, DATA_FIELD, KL_TYPE


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


def _serialize_bsp(bs_point_lst) -> List[Dict[str, Any]]:
    """序列化买卖点列表."""
    result: List[Dict[str, Any]] = []
    for bsp in bs_point_lst.getSortedBspList():
        result.append({
            "t": int(bsp.klu.time.ts * 1000),
            "v": bsp.klu.low if bsp.is_buy else bsp.klu.high,
            "is_buy": bsp.is_buy,
            "types": [t.value for t in bsp.type],
        })
    return result


def serialize_chan(chan: CChan, kl_type: KL_TYPE) -> Dict[str, Any]:
    """
    将 CChan 指定级别的计算结果序列化为 JSON 字典。

    参数:
        chan: 已完成计算的 CChan 实例
        kl_type: 要导出的 K 线级别

    返回:
        包含 klines/bi/seg/zs/seg_zs/bsp 的字典，符合 design.md D2 契约。
    """
    kl_list = chan[kl_type]

    return {
        "klines": _serialize_klines(kl_list),
        "bi": _serialize_bi(kl_list.bi_list),
        "seg": _serialize_seg(kl_list.seg_list),
        "zs": _serialize_zs(kl_list.zs_list),
        "seg_zs": _serialize_zs(kl_list.segzs_list),
        "bsp": _serialize_bsp(kl_list.bs_point_lst),
    }