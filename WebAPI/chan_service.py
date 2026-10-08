# -*- coding: utf-8 -*-
"""
缠论计算服务 — /api/klines 与 QA 结构注入共用的计算链路。

从 main.py 最小化抽出（PERIOD_MAP / _resolve_kl_type / _resolve_data_src / _compute_chan），
main.py 的 /api/klines 行为保持不变；QA 结构注入（kline-page-change design D8.4）经
get_serialized_chan() 复用同一链路（_compute_chan + serialize_chan + chan_stable_prefix 缓存）。
"""

import os
from typing import Optional

from fastapi import HTTPException

from ChanAnalyse.Chan import CChan
from ChanAnalyse.ChanConfig import CChanConfig
from ChanAnalyse.Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE

from .cache import get_chan_cache
from .serializer import serialize_chan

# ---- 周期字符串 -> KL_TYPE 映射 ----
# 与 DuckDB kl_store 实际保存的 kl_type 对齐：K_5M/K_15M/K_30M/K_60M/K_DAY/K_WEEK/K_MON
# （"1m"/"1h" 为旧值别名，保留以兼容历史请求）
# bsp-page-change D1：bsp 模块词表 "D"/"W"/"M" 映射到 K_DAY/K_WEEK/K_MON（保留 "1d"/"1w"/"1M"
# 旧键，K 线页既有请求不受影响）
PERIOD_MAP: dict[str, KL_TYPE] = {
    "1m": KL_TYPE.K_1M,
    "5m": KL_TYPE.K_5M,
    "15m": KL_TYPE.K_15M,
    "30m": KL_TYPE.K_30M,
    "60m": KL_TYPE.K_60M,
    "1h": KL_TYPE.K_60M,
    "1d": KL_TYPE.K_DAY,
    "1w": KL_TYPE.K_WEEK,
    "1M": KL_TYPE.K_MON,
    "D": KL_TYPE.K_DAY,
    "W": KL_TYPE.K_WEEK,
    "M": KL_TYPE.K_MON,
}

# ---- 词表桥接（bsp-page-change design D1，引擎与 router 共用）----
# bsp 词表规范值（canonical）：30m/60m/D/W/M；旧别名（1d/1h/1M…）归一到规范值。
# 三套词表：页面/bsp_index 用 canonical（D…）、K 线页请求用 1d…（PERIOD_MAP 同收）、
# DuckDB/RecomputeCursor 用枚举名（K_DAY…）。枚举名只在 RecomputeCursor 边界出现。
PERIOD_CANONICAL: dict[KL_TYPE, str] = {
    KL_TYPE.K_1M: "1m",
    KL_TYPE.K_5M: "5m",
    KL_TYPE.K_15M: "15m",
    KL_TYPE.K_30M: "30m",
    KL_TYPE.K_60M: "60m",
    KL_TYPE.K_DAY: "D",
    KL_TYPE.K_WEEK: "W",
    KL_TYPE.K_MON: "M",
}


def resolve_period(period: str) -> tuple[str, KL_TYPE, str]:
    """周期词表桥接：任意 PERIOD_MAP 键 → (canonical 词表值, KL_TYPE, DuckDB 枚举名)。

    非法值沿用 _resolve_kl_type 的 400 行为。canonical 用于 bsp_index/chan_structure/
    chan_snapshot 的 kl_type 列；枚举名只用于 RecomputeCursor 与 DuckDB 边界。
    """
    kl_type = _resolve_kl_type(period)
    return PERIOD_CANONICAL[kl_type], kl_type, kl_type.name


def period_of_db_name(db_name: str) -> str | None:
    """DuckDB 枚举名（如 "K_DAY"）→ bsp canonical 词表（如 "D"）；未知返回 None。"""
    try:
        return PERIOD_CANONICAL[KL_TYPE[db_name]]
    except KeyError:
        return None


def _resolve_kl_type(period: str) -> KL_TYPE:
    """将前端周期字符串转换为 KL_TYPE 枚举，非法值抛出 400。"""
    kl_type = PERIOD_MAP.get(period)
    if kl_type is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported period: {period!r}. "
                f"Valid values: {list(PERIOD_MAP.keys())}"
            ),
        )
    return kl_type


def _resolve_data_src(period: str) -> str:
    """
    确定数据源。

    优先使用 DuckDB 离线源；如果 DuckDB 文件不存在，对日线使用 BaoStock 兜底。
    其他周期在 DuckDB 缺失时报错。
    """
    from ChanAnalyse.DataAPI.KLineStore import DEFAULT_DB_PATH

    if os.path.exists(DEFAULT_DB_PATH):
        return "custom:DuckDBAPI.CDuckDB"

    if period == "1d":
        return DATA_SRC.BAO_STOCK

    raise HTTPException(
        status_code=404,
        detail=(
            f"DuckDB file {DEFAULT_DB_PATH!r} not found, "
            f"and BaoStock fallback only supports daily ('1d') period."
        ),
    )


# ---- L1 区间套子级别映射（bsp-ladder-change design D3 修订二）----
# 本级别 → 共振判定的直接子级别（单级直连，无跨级传递）：
# 5m→(30m 的子级)、30m→5m、D→30m、W→D、M→W。
# 语义约束：每个级别只看**直接一级**子级别的买卖点做共振判定，不递归——
# 5m 信号只佐证 30m 的 L1，不会经 30m 传递影响 D/W/M 的判定。
# 5m 自身无子级（最低级别）；60m 不在用户指定链（5m→30m→D→W→M）中，
# 按 30m 同档处理配 5m。
SUB_LEVEL_MAP: dict[KL_TYPE, KL_TYPE] = {
    KL_TYPE.K_30M: KL_TYPE.K_5M,
    KL_TYPE.K_60M: KL_TYPE.K_5M,
    KL_TYPE.K_DAY: KL_TYPE.K_30M,
    KL_TYPE.K_WEEK: KL_TYPE.K_DAY,
    KL_TYPE.K_MON: KL_TYPE.K_WEEK,
}


def resolve_sub_level(kl_type: KL_TYPE) -> Optional[KL_TYPE]:
    """L1 共振子级别解析（单级直连）：30m/60m→5m、D→30m、W→D、M→W；
    5m 及以下无子级返回 None。不做跨级传递（D 的 L1 只看 30m，不看 5m）。
    """
    return SUB_LEVEL_MAP.get(kl_type)


def _compute_chan(symbol: str, kl_type: KL_TYPE, data_src: str) -> CChan:
    """创建 CChan 实例并执行完整计算。"""
    config = CChanConfig(
        conf={"trigger_step": False, "kl_data_check": False},
    )
    chan = CChan(
        code=symbol,
        data_src=data_src,
        lv_list=[kl_type],
        config=config,
        autype=AUTYPE.QFQ,
    )
    return chan


def compute_sub_chan(symbol: str, kl_type: KL_TYPE) -> Optional[CChan]:
    """L1 区间套子级别计算（bsp-ladder-change D3）。

    对日线及以上级别额外计算子级别（D→30m / W→D / M→W）CChan，供
    serializer 的 L1 共振判定。子级别失败（数据缺失/计算异常）返回 None，
    调用方降级为不计算 L1（未确认行落 L2），不阻断主级别响应。

    计算复用 chan_stable_prefix 缓存（get_serialized_chan 同款链路），
    同一 (symbol, sub_kl_type) 重复请求不重算序列化（缓存命中返回缓存）。
    """
    sub_kl_type = resolve_sub_level(kl_type)
    if sub_kl_type is None:
        return None
    try:
        period = PERIOD_CANONICAL[sub_kl_type]
        data_src = _resolve_data_src(period)
        return _compute_chan(symbol, sub_kl_type, data_src)
    except Exception:
        return None


def get_serialized_chan(symbol: str, period: str) -> dict:
    """
    复用 /api/klines 计算链路取序列化缠论结构（QA 结构注入用，design D8.4）。

    _resolve_kl_type 同款周期解析 → _compute_chan + serialize_chan（含 chan_stable_prefix
    缓存写入）。调用方需自行容错（结构注入失败静默跳过）。
    """
    kl_type = _resolve_kl_type(period)
    data_src = _resolve_data_src(period)
    chan = _compute_chan(symbol, kl_type, data_src)
    result = serialize_chan(chan, kl_type)
    get_chan_cache().set(symbol, kl_type, result)
    return result
