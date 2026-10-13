# -*- coding: utf-8 -*-
"""
灌数公共工具 - CKLine_Unit 与 DataFrame 行之间的转换、数据校验、交易日历。

日线灌数脚本（Data/download_kl.py）与盘中轮询引擎（Data/intraday_poll.py）
共用这里的转换/校验逻辑，避免重复实现。

另提供「已是最新就不请求接口」的判定（expected_latest_time_key）：按交易日历推算
此刻本应存在的最新 K 线，供灌数脚本跳过冗余的接口请求（避免触发数据源限频）。
"""

import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from ChanAnalyse.Common.CEnum import AUTYPE, KL_TYPE
from .KLineStore import ctime_to_str

log = logging.getLogger("ingest")

EARLIEST = "1990-12-19"           # A 股最早交易日附近，作为首次全量回填的起始
LOOKBACK_SESSIONS = 3             # 增量续拉的回看交易日数（自愈窗口）
JUMP_THRESHOLD = 0.20             # 单根涨跌幅告警阈值（可配，仅告警不拒绝）
DEFAULT_STALE_HOURS = {"intraday": 0.5, "day": 48.0}  # 停更告警阈值（小时）

# A 股交易时段（与 Data/intraday_poll.py 的 trading_sessions 默认值一致）
TRADING_SESSIONS = (("09:30", "11:30"), ("13:00", "15:00"))

# 各分钟级别一根 bar 的分钟数；未列出的级别（含秒级）不做 bar 边界判定 → 不跳过请求
BAR_MINUTES = {
    KL_TYPE.K_1M: 1,
    KL_TYPE.K_3M: 3,
    KL_TYPE.K_5M: 5,
    KL_TYPE.K_10M: 10,
    KL_TYPE.K_15M: 15,
    KL_TYPE.K_30M: 30,
    KL_TYPE.K_60M: 60,
}

# bar 收盘 → 数据在数据源可见的延迟（分钟）：判定「本应存在的最新 K 线」时先把 now 回拨
# 该时长，避免数据尚未发布时被误判为「有新数据」而空跑请求。数据源发布更晚时（如
# 日线要等到晚上）可调大，代价是最新一根 bar 晚一轮才入库。
DEFAULT_BAR_LAG_MINUTES = 30

_BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def parse_kl_type(s: str) -> KL_TYPE:
    return KL_TYPE[s.upper()]


def parse_autype(s: str) -> AUTYPE:
    return AUTYPE[s.upper()]


def klu_to_row(klu, code: str, k_type: KL_TYPE, autype: AUTYPE) -> dict:
    """把一根 CKLine_Unit 转成 kline 表的一行（缺交易信息的列留空，由 upsert 补 NULL）。"""
    d = {
        "code": code,
        "kl_type": k_type.name,
        "autype": autype.name,
        "time_key": ctime_to_str(klu.time),
        "open": klu.open,
        "high": klu.high,
        "low": klu.low,
        "close": klu.close,
    }
    # trade_info.metric 键为 "volume"/"turnover"/"turnover_rate"，与表列名一致
    for k, v in klu.trade_info.metric.items():
        if v is not None:
            d[k] = v
    return d


def validate(df: pd.DataFrame):
    """结构化校验 + 跳变告警。

    返回 (valid_df, rejected_count, warnings)。
    - 拒绝：OHLC 关系非法（high < max(open,close)、low > min(open,close)、
      high < low、价格非负不满足）；时间乱序（time_key 相对运行最大值回退）。
    - 告警但保留：单根涨跌幅超阈值（如除权除息导致的真实跳空）。
    """
    warnings = []

    bad = (
        (df["high"] < df[["open", "close"]].max(axis=1))
        | (df["low"] > df[["open", "close"]].min(axis=1))
        | (df["high"] < df["low"])
        | ((df[["open", "high", "low", "close"]] < 0).any(axis=1))
    )
    rejected = int(bad.sum())
    valid = df[~bad].reset_index(drop=True)

    # 时间乱序：任何 time_key < 已见最大值的行视为乱序拒绝；重复（相等）交给 upsert 去重
    drop_idx = []
    cur_max = None
    for i, t in enumerate(valid["time_key"]):
        if cur_max is not None and t < cur_max:
            drop_idx.append(i)
        else:
            cur_max = t
    if drop_idx:
        warnings.append(f"时间乱序 {len(drop_idx)} 行被拒绝")
        valid = valid.drop(index=drop_idx).reset_index(drop=True)
        rejected += len(drop_idx)

    # 异常跳变告警（保留）
    prev_close = None
    for t, c in zip(valid["time_key"], valid["close"]):
        if prev_close is not None and prev_close > 0:
            pct = abs(c / prev_close - 1)
            if pct > JUMP_THRESHOLD:
                warnings.append(f"异常跳变 {t}: {pct:.2%}（保留，疑似除权除息）")
        prev_close = c

    return valid, rejected, warnings


def get_calendar():
    """返回 A 股交易日历（exchange_calendars），不可用时返回 None。"""
    try:
        import exchange_calendars as xcals
        return xcals.get_calendar("XSHG")
    except Exception as e:
        log.warning("交易日历不可用：%s", e)
        return None


# ---------------------------------------------------------------------------
# 「已是最新」判定：跳过冗余接口请求
# ---------------------------------------------------------------------------
def _hm_to_minutes(hm: str) -> int:
    """把 "HH:MM" 转为自 00:00 起的分钟数。"""
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


def _to_beijing(now=None) -> datetime:
    """把 now 归一化为北京时间（naive 视为北京时间，与本模块其它时间处理一致）。"""
    if now is None:
        return datetime.now(_BEIJING_TZ)
    if now.tzinfo is None:
        return now.replace(tzinfo=_BEIJING_TZ)
    return now.astimezone(_BEIJING_TZ)


def _fmt_bar(session, minute_of_day: int) -> str:
    """拼出 time_key 字符串（与 KLineStore.ctime_to_str 的输出格式一致）。"""
    h, m = divmod(minute_of_day, 60)
    return f"{session:%Y-%m-%d} {h:02d}:{m:02d}:00"


def bar_close_minutes(k_type: KL_TYPE, sessions=TRADING_SESSIONS):
    """返回一个交易日内各 bar 的收盘时刻（自 00:00 起的分钟数）。

    分钟级在交易时段内按 bar 长度递推（5 分钟线 → 09:35/09:40/…/11:30、13:05/…/15:00）；
    日线及以上、以及未在 BAR_MINUTES 登记的级别返回 None（不做 bar 边界判定）。
    """
    size = BAR_MINUTES.get(k_type)
    if size is None:
        return None
    out = []
    for start_hm, end_hm in sessions:
        start, end = _hm_to_minutes(start_hm), _hm_to_minutes(end_hm)
        out.extend(start + k * size for k in range(1, (end - start) // size + 1))
    return out


def _visible_session(cal, cutoff, *, intraday: bool):
    """返回最新一个「当日 K 线已可见」的交易日。

    - 非交易日：取此前最近的交易日；
    - 交易日：收盘之后当日数据可见；分钟级在开盘之后即认为当日 bar 陆续可见；
      否则（盘中且非分钟级、或开盘前）退到上一交易日。
    """
    d = pd.Timestamp(cutoff.date())
    cur = cutoff.hour * 60 + cutoff.minute
    if cal.is_session(d):
        if intraday and cur >= _hm_to_minutes(TRADING_SESSIONS[0][0]):
            return d
        if cur >= _hm_to_minutes(TRADING_SESSIONS[-1][1]):
            return d
        return cal.previous_session(d)
    return cal.date_to_session(d, direction="previous")


def _last_period_session(cal, session, freq: str):
    """session 所在周期（W=周 / M=月）的最后一个交易日；该周期尚未走完则返回上一周期的最后一个交易日。"""
    sessions = cal.sessions
    per = sessions.to_period(freq)
    cur = per[sessions.get_loc(session)]
    same = sessions[per == cur]
    if len(same) and same[-1] == session:
        return session
    before = sessions[per < cur]
    return before[-1] if len(before) else None


def _expected_intraday_key(cal, k_type: KL_TYPE, session, cutoff):
    """分钟级：当日可见就取当日内最后一根已收盘 bar，否则取该交易日最后一根 bar（15:00）。"""
    closes = bar_close_minutes(k_type)
    if closes is None:
        return None
    if cutoff.date() == session.date():
        cur = cutoff.hour * 60 + cutoff.minute
        done = [c for c in closes if c <= cur]
        if done:
            return _fmt_bar(session, done[-1])
        session = cal.previous_session(session)  # 开盘不久，当日尚无已收盘 bar
    return _fmt_bar(session, closes[-1])


def expected_latest_time_key(k_type: KL_TYPE, cal=None, now=None,
                             lag_minutes: int = DEFAULT_BAR_LAG_MINUTES):
    """推算「此刻本应有数据」的最新 K 线 time_key，用于跳过无谓的接口请求。

    判定链：now 回拨 lag_minutes（数据源发布延迟）→ 最新一个「数据已可见」的交易日
    → 按级别取该日对应的最后一根 bar：

    - 分钟级：当日可见（盘中或收盘后）取当日内最后一根已收盘 bar，否则取该交易日 15:00；
    - 日线：该交易日 00:00:00；
    - 周线/月线：该交易日所在周/月已走完则取本周/月最后交易日，否则退回上一周/月
      （BaoStock 的周线/月线 bar 只在周/月走完后才出现，与库内实测一致）。

    返回 "YYYY-MM-DD HH:MM:SS"。无法判定时（无交易日历、超出日历覆盖范围、未支持的级别）
    返回 None —— 调用方此时应照常请求接口：失败开放，宁可多请求一次也不漏数据。
    """
    if cal is None:
        cal = get_calendar()
    if cal is None:
        return None

    now = _to_beijing(now)
    cutoff = now - timedelta(minutes=max(int(lag_minutes), 0))
    try:
        if k_type.value < KL_TYPE.K_DAY.value:
            session = _visible_session(cal, cutoff, intraday=True)
            return _expected_intraday_key(cal, k_type, session, cutoff) if session is not None else None
        session = _visible_session(cal, cutoff, intraday=False)
        if session is None:
            return None
        if k_type is KL_TYPE.K_DAY:
            return f"{session:%Y-%m-%d} 00:00:00"
        if k_type is KL_TYPE.K_WEEK:
            last = _last_period_session(cal, session, "W")
        elif k_type is KL_TYPE.K_MON:
            last = _last_period_session(cal, session, "M")
        else:
            return None  # 季线/年线等未支持：不判定、不跳过
        return f"{last:%Y-%m-%d} 00:00:00" if last is not None else None
    except Exception as e:
        log.debug("推算应有最新 K 线失败（%s @ %s），按未判定处理：%s", k_type.name, now, e)
        return None


def load_config(path: str) -> dict:
    """读取 JSON 配置文件（schema 见 Data/ingest_config.example.json）。"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def iter_ingest_jobs(cfg: dict):
    """按配置文件展开为 (code, KL_TYPE, AUTYPE) 三元组，供批量灌数/状态遍历。

    可选 cfg["code_prefix"]（如 "sz."）：只保留该前缀的股票，用于按市场分跑。
    """
    defaults = cfg.get("defaults", {})
    default_autype = defaults.get("autype", "QFQ")
    prefix = cfg.get("code_prefix")
    for s in cfg.get("stocks", []):
        code = s["code"]
        if prefix and not code.startswith(prefix):
            continue
        for kt in s.get("kl_types", ["K_DAY"]):
            for au in s.get("autypes", [default_autype]):
                yield code, parse_kl_type(kt), parse_autype(au)
