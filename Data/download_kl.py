# -*- coding: utf-8 -*-
"""
K 线灌数脚本：从 BaoStock 拉取原始 K 线 → 校验 → 幂等写入本地 DuckDB。

职责（对应 openspec 变更 persist-kl-to-duckdb）：
- 默认增量：断点 = 表内 max(time_key)，回看 N 个交易日自愈，二次运行只补尾部、无重复。
- 已是最新则跳过：库内水位已覆盖「按交易日历推算、此刻本应存在的最新 K 线」时
  直接跳过、不发请求，避免重复拉同一段数据触发数据源限频（见 --force / --bar-lag-minutes）。
- --full：全量重刷（先清空该 code/kl_type/autype 再重拉）。
- --begin/--end：区间重刷（只动 [begin, end]，其余历史不变）。指定任一端即进入该模式，
  不再走增量续拉：先按子区间删除旧行再重写（删除发生在该子区间拉取成功之后），
  使本地与数据源对齐；begin 缺省取库内最早一行，end 缺省取今天。
- 首次全历史回填分批（按 chunk-days 分块），中断后重启自动从已入库最新 K 线续传。
- 数据校验：OHLC 非法 / 时间乱序拒绝，异常跳变告警但保留。
- 缺口检测：按 exchange_calendars 交易日历检测日线缺失交易日。

用法示例：
    python Data/download_kl.py --code sz.000001 --kl-type K_DAY --autype QFQ
    python Data/download_kl.py --code sz.000001 --kl-type K_DAY --autype QFQ --full
    python Data/download_kl.py --code sz.000001 --kl-type K_DAY --autype QFQ --begin 2024-01-01 --end 2024-06-30
    python Data/download_kl.py --code sz.000001 --kl-type K_DAY --autype QFQ --force   # 强制请求
"""

import argparse
import logging
import sys
import time
from datetime import date, datetime

import pandas as pd

from ChanAnalyse.Common.CEnum import KL_TYPE
from ChanAnalyse.DataAPI.IngestUtil import (
    DEFAULT_BAR_LAG_MINUTES,
    DEFAULT_STALE_HOURS,
    EARLIEST,
    LOOKBACK_SESSIONS,
    expected_latest_time_key,
    get_calendar,
    iter_ingest_jobs,
    klu_to_row,
    load_config,
    parse_autype,
    parse_kl_type,
    validate,
)
from ChanAnalyse.DataAPI.KLineStore import KLineStore, DEFAULT_DB_PATH

log = logging.getLogger("download_kl")

# BaoStock 免费接口默认请求间隔（秒）。全量灌数每股一次请求，串行 sleep 避免触发限频。
# 0.5s（≈2 QPS）为稳妥值；更保守可 --sleep 1.0。
DEFAULT_REQUEST_INTERVAL = 0.5

# ---- 失败退避 / 重试 / 会话重连 ----
# 背景：2026-09-21 批量灌数在 21:16:03 被 BaoStock 掐断连接后，脚本对剩余
# 2 万+ 条任务零等待连打，11 秒内产生 20437 条秒失败。故失败路径必须：
#   1) 单次拉取指数退避重试，每次重试前重登会话（连接被掐断的主恢复手段）
#   2) 批量循环里失败任务同样退避，禁止秒级空转
#   3) 连续失败到阈值直接中止批量（幂等，重跑同一条命令即续跑）
DEFAULT_RETRY_ATTEMPTS = 3       # 单个 [begin,end] 拉取失败后的重试次数（不含首次）
BACKOFF_BASE_SECONDS = 5.0       # 首次退避时长
BACKOFF_MAX_SECONDS = 60.0       # 退避时长上限
SESSION_RESET_AFTER = 3          # 连续失败任务数达到该值 → 重登 BaoStock 会话
ABORT_AFTER = 10                 # 连续失败任务数达到该值 → 中止批量（避免空转烧完配置）

# 这类错误重试也不会成功（数据本身不存在），直接失败，不浪费退避时间
NON_RETRYABLE_MARKERS = ("指数是没有分钟级别数据",)


class BatchAborted(RuntimeError):
    """连续失败过多而主动中止批量灌数。

    results 携带中止前的逐条结果；入库幂等，重跑同一条命令即从断点续传。
    """

    def __init__(self, message: str, results: dict):
        super().__init__(message)
        self.results = results


# ---------------------------------------------------------------------------
# 拉取：复用 CBaoStock
# ---------------------------------------------------------------------------
def fetch_baostock(code, k_type, autype, begin, end):
    """拉取 [begin, end] 区间的 K 线，返回 CKLine_Unit 列表。"""
    from ChanAnalyse.DataAPI.BaoStockAPI import CBaoStock

    api = CBaoStock(code=code, k_type=k_type, begin_date=begin, end_date=end, autype=autype)
    return list(api.get_kl_data())


def relogin(reason: str) -> None:
    """强制重新登录 BaoStock 会话。

    连接被服务端掐断时 CBaoStock.is_connect 仍为真，do_init 不会重登，
    所以这里必须先置 None 再登录，并校验登录返回码。
    """
    from ChanAnalyse.DataAPI.BaoStockAPI import CBaoStock

    try:
        CBaoStock.do_close()  # 登出已失效的连接可能直接抛错，忽略即可
    except Exception as e:
        log.debug("登出旧会话失败（忽略）: %s", e)
    CBaoStock.is_connect = None
    CBaoStock.do_init()
    resp = CBaoStock.is_connect
    if resp is None or str(getattr(resp, "error_code", "0")) != "0":
        raise RuntimeError(
            "重新登录 BaoStock 失败: %s" % getattr(resp, "error_msg", resp)
        )
    log.info("已重新登录 BaoStock 会话（%s）", reason)


def fetch_with_retry(code, k_type, autype, begin, end, *, retries=DEFAULT_RETRY_ATTEMPTS):
    """拉取 [begin, end]，失败按指数退避重试，每次重试前重登会话。

    重试耗尽后抛出最后一次异常，由调用方决定记录还是中止。
    """
    delay = BACKOFF_BASE_SECONDS
    last_err = None
    for attempt in range(retries + 1):
        try:
            return fetch_baostock(code, k_type, autype, begin, end)
        except Exception as e:
            last_err = e
            msg = str(e)
            if attempt >= retries or any(m in msg for m in NON_RETRYABLE_MARKERS):
                break
            wait = min(delay, BACKOFF_MAX_SECONDS)
            log.warning(
                "[%s/%s] %s~%s 拉取失败（第 %d/%d 次），%.0fs 后重试并重登会话：%s",
                code, k_type.name, begin, end, attempt + 1, retries, wait, msg,
            )
            time.sleep(wait)
            delay = min(delay * 2, BACKOFF_MAX_SECONDS)
            try:
                relogin("%s/%s 第 %d 次重试" % (code, k_type.name, attempt + 1))
            except Exception as re_err:
                log.warning("重登会话失败（继续重试）：%s", re_err)
    raise last_err


# ---------------------------------------------------------------------------
# 缺口检测（仅日线及以上有意义）
# ---------------------------------------------------------------------------
def detect_gaps(store: KLineStore, code, kl_type, autype, cal):
    """返回 [begin, end] 范围内缺失的交易日列表（按交易日历判定，节假日不误判）。"""
    if kl_type.value < KL_TYPE.K_DAY.value:
        return []  # 分钟级不做「交易日」缺口检测
    df = store.query(code, kl_type.name, autype.name)
    if df.empty:
        return []
    dates = pd.DatetimeIndex(pd.to_datetime(df["time_key"].str[:10]).unique())
    sessions = cal.sessions_in_range(dates.min(), dates.max())
    missing = sessions.difference(dates)
    return [d.strftime("%Y-%m-%d") for d in missing]


def warn_gaps(store: KLineStore, code, kl_type, autype, cal) -> None:
    """检测并告警缺失交易日（同一 (code, kl_type, autype) 只查一次库）。"""
    gaps = detect_gaps(store, code, kl_type, autype, cal)
    if gaps:
        log.warning("[%s] 检测到 %d 个缺失交易日：%s", code, len(gaps), gaps[:10])


# ---------------------------------------------------------------------------
# 断点与分块
# ---------------------------------------------------------------------------
def session_lookback(time_key: str, n: int, cal) -> str:
    """返回 time_key 往前 n 个交易日（无日历则原样返回日期部分）。"""
    d = time_key[:10]
    if cal is None:
        return d
    try:
        back = cal.session_offset(pd.Timestamp(d), -n)
        return back.strftime("%Y-%m-%d")
    except Exception:
        return d


def chunk_range(start: str, stop: str, chunk_days):
    """把 [start, stop] 切成 (begin, end) 分块；chunk_days 为 None 则整段一次。"""
    if chunk_days is None:
        yield start, stop
        return
    cur = pd.Timestamp(start)
    end_ts = pd.Timestamp(stop)
    while cur <= end_ts:
        nxt = cur + pd.Timedelta(days=chunk_days)
        yield cur.strftime("%Y-%m-%d"), min(nxt, end_ts).strftime("%Y-%m-%d")
        cur = nxt + pd.Timedelta(days=1)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def ingest(code, k_type, autype, store: KLineStore, *, begin=None, end=None,
           full=False, chunk_days=None, cal=None, check_gaps=False,
           sleep=0.0, manage_auth=True, retries=DEFAULT_RETRY_ATTEMPTS,
           skip_fresh=True, bar_lag_minutes=DEFAULT_BAR_LAG_MINUTES,
           now=None, stats=None):
    """灌数主流程，返回写入行数。

    三种模式（优先级从高到低）：
    - full=True：全量重刷，先清空该 (code, kl_type, autype) 全部行，再从 begin/EARLIEST 拉到 end/今天；
    - 指定 begin 或 end：区间重刷，只处理 [begin/EARLIEST, end/今天]，按子区间删除旧行后重写；
    - 都不指定：增量续拉，水位已覆盖「此刻本应存在的最新 K 线」时直接跳过、不请求接口。

    sleep: 每次接口请求之间的间隔秒数（BaoStock 限频保护），<=0 则不额外等待。
    manage_auth: 是否在本函数内 do_init/do_close；批量灌数由外层登录一次复用。
    retries: 单次拉取失败的重试次数（指数退避 + 重登会话），见 fetch_with_retry。
    skip_fresh: 库内水位已覆盖「此刻本应存在的最新 K 线」时不请求接口（返回 0），
        避免重复拉同一段数据触发限频。区间重刷（指定 --begin/--end）时该判定不生效。
    bar_lag_minutes: 判定「本应存在」时对 now 回拨的分钟数（数据发布延迟），
        见 IngestUtil.expected_latest_time_key。
    now: 判定用的当前时间（缺省取系统时间），仅便于测试注入。
    stats: 可选 dict 出参，回填 {"skipped": bool, "range_refresh": bool,
        "watermark": str|None, "expected": str|None}。
    """
    kt_name, au_name = k_type.name, autype.name
    wm = store.max_time_key(code, kt_name, au_name)

    stop = end or date.today().strftime("%Y-%m-%d")
    refresh = False   # 区间重刷：拉到的子区间先把旧行删掉再写（镜像数据源）

    if full:
        deleted = store.delete(code, kt_name, au_name)
        log.info("--full：清空 %s/%s/%s 已有 %d 行", code, kt_name, au_name, deleted)
        start = begin or EARLIEST
    elif begin is not None or end is not None:
        # 显式区间重刷：只动 [start, stop]，其余历史不变（与 --full 的全清区分）。
        # start 缺省取库内最早一行（区间只覆盖已有历史），库内为空时才退到 EARLIEST。
        # min_time_key 是完整的 "YYYY-MM-DD HH:MM:SS"，而接口只要日期，故取日期部分。
        start = begin
        if start is None:
            earliest = store.min_time_key(code, kt_name, au_name)
            start = earliest[:10] if earliest else EARLIEST
        if start > stop:
            log.warning("[%s] %s/%s 区间为空（起始 %s 晚于结束 %s），无操作",
                        code, kt_name, au_name, start, stop)
            if stats is not None:
                stats.update(skipped=False, watermark=wm, expected=None, range_refresh=False)
            return 0
        refresh = True
        log.info("[%s] %s/%s 区间重刷 [%s, %s]：先按子区间删除旧行再重写，其余历史不变",
                 code, kt_name, au_name, start, stop)
    elif wm is None:
        start = begin or EARLIEST
    else:
        expected = None
        if skip_fresh:
            expected = expected_latest_time_key(
                k_type, cal, now=now, lag_minutes=bar_lag_minutes
            )
        if expected is not None and wm >= expected:
            # 已是最新：直接返回，不登录、不发请求（重复请求同一段数据会触发限频）
            log.info("[%s] %s/%s 水位 %s 已覆盖应有最新 K 线 %s，跳过接口请求",
                     code, kt_name, au_name, wm, expected)
            if stats is not None:
                stats.update(skipped=True, watermark=wm, expected=expected)
            if check_gaps and cal is not None:
                warn_gaps(store, code, k_type, autype, cal)
            return 0
        start = session_lookback(wm, LOOKBACK_SESSIONS, cal)

    if stats is not None:
        stats.update(skipped=False, watermark=wm, expected=None, range_refresh=refresh)

    from ChanAnalyse.DataAPI.BaoStockAPI import CBaoStock

    total = 0
    if manage_auth:
        CBaoStock.do_init()
    try:
        for c_begin, c_end in chunk_range(start, stop, chunk_days):
            klus = fetch_with_retry(code, k_type, autype, c_begin, c_end, retries=retries)
            if not klus:
                # 数据源已答复该子区间无数据：区间重刷下同步删掉本地旧行（镜像数据源）
                if refresh:
                    removed = store.delete(code, kt_name, au_name, c_begin, c_end)
                    if removed:
                        log.warning("[%s] %s-%s 数据源无数据，删除本地 %d 行",
                                    code, c_begin, c_end, removed)
                # 空结果也按间隔限速，避免无数据时秒级连打
                if sleep > 0:
                    time.sleep(sleep)
                continue
            df = pd.DataFrame([klu_to_row(k, code, k_type, autype) for k in klus])
            valid, rejected, warns = validate(df)
            for w in warns:
                log.warning("[%s] %s", code, w)
            if rejected:
                log.warning("[%s] 拒绝 %d 行非法数据", code, rejected)
            # 删除放在拉取成功之后：拉取失败（异常）不会丢数据，只有数据源已答复的子区间才删
            removed = store.delete(code, kt_name, au_name, c_begin, c_end) if refresh else 0
            if not valid.empty:
                store.upsert(valid)
                total += len(valid)
            log.info("[%s] %s-%s 拉取 %d 写入 %d%s", code, c_begin, c_end, len(klus), len(valid),
                     "（区间重刷，删除旧行 %d）" % removed if refresh else "")
            if sleep > 0:
                time.sleep(sleep)
    finally:
        if manage_auth:
            CBaoStock.do_close()

    if check_gaps and cal is not None:
        warn_gaps(store, code, k_type, autype, cal)
    return total


# ---------------------------------------------------------------------------
# 配置驱动批量灌数 + 可观测
# ---------------------------------------------------------------------------
def ingest_from_config(cfg: dict) -> dict:
    """按配置文件批量灌数，逐条目失败隔离，返回每条目结果。

    登录/登出只做一次（复用 CBaoStock.is_connect 会话），每股之间按
    request_interval_seconds 限频 sleep，避免全量跑触发 BaoStock 限频。

    失败处理（针对 2026-09-21 被掐断连接后 11 秒秒失败 2 万条的事故）：
    - 任务失败同样指数退避，禁止零等待连打；
    - 连续失败 SESSION_RESET_AFTER 个任务 → 重登会话；
    - 连续失败达到 max_consecutive_failures → 抛 BatchAborted 中止批量
      （入库幂等，重跑同一条命令即从断点续传）。
    """
    from ChanAnalyse.DataAPI.BaoStockAPI import CBaoStock

    db_path = cfg.get("db_path", DEFAULT_DB_PATH)
    cal = get_calendar()
    sleep = cfg.get("request_interval_seconds", DEFAULT_REQUEST_INTERVAL)
    retries = cfg.get("retry_attempts", DEFAULT_RETRY_ATTEMPTS)
    abort_after = cfg.get("max_consecutive_failures", ABORT_AFTER)
    skip_fresh = cfg.get("skip_fresh", True)
    bar_lag_minutes = cfg.get("bar_lag_minutes", DEFAULT_BAR_LAG_MINUTES)
    results = {}
    fail_streak = 0   # 连续失败任务数：只有成功才清零，达到阈值中止批量
    backoff_level = 0  # 退避档位：成功或重登会话成功后清零
    CBaoStock.do_init()
    try:
        for code, kt, au in iter_ingest_jobs(cfg):
            key = (code, kt.name, au.name)
            try:
                # 每个任务单独开合连接：DuckDB 的读写锁是「读写互斥」（read_only
                # 连接也一样打不开），整批持锁会让后端在整个灌数期间读不到数据。
                # 按任务开合把独占锁窗口压缩到秒级，读方（KLineStore 锁重试）可穿插进来。
                job_stats = {}
                with KLineStore(db_path) as store:
                    n = ingest(
                        code, kt, au, store,
                        begin=cfg.get("begin"), end=cfg.get("end"),
                        full=cfg.get("full", False),
                        chunk_days=cfg.get("chunk_days"),
                        cal=cal,
                        check_gaps=cfg.get("check_gaps", False),
                        sleep=sleep,
                        manage_auth=False,
                        retries=retries,
                        skip_fresh=skip_fresh,
                        bar_lag_minutes=bar_lag_minutes,
                        stats=job_stats,
                    )
                if job_stats.get("skipped"):
                    # 已是最新：既不算失败也不重置退避档位（本身就没发请求）
                    results[key] = {"status": "skipped", "rows": 0}
                else:
                    results[key] = {"status": "ok", "rows": n}
                    log.info("[%s] 完成，写入 %d 行", code, n)
                fail_streak = 0
                backoff_level = 0
            except Exception as e:
                results[key] = {"status": "failed", "error": str(e)}
                fail_streak += 1
                backoff_level += 1
                log.error("[%s/%s/%s] 失败：%s", code, kt.name, au.name, e)

                # 失败也要退避：连接失效时剩余任务会以千级 QPS 秒失败
                wait = min(
                    BACKOFF_BASE_SECONDS * (2 ** (backoff_level - 1)),
                    BACKOFF_MAX_SECONDS,
                )
                log.warning(
                    "连续失败 %d 次，退避 %.0fs 后继续", fail_streak, wait
                )
                time.sleep(wait)

                if backoff_level >= SESSION_RESET_AFTER:
                    try:
                        relogin("连续失败 %d 次" % fail_streak)
                        backoff_level = 0
                    except Exception as re_err:
                        log.error("重登会话失败：%s", re_err)

                if fail_streak >= abort_after:
                    raise BatchAborted(
                        "连续失败 %d 次（阈值 %d），中止批量；"
                        "已入库数据有效，重跑同一条命令可从断点续传"
                        % (fail_streak, abort_after),
                        results,
                    )
    finally:
        try:
            CBaoStock.do_close()
        except Exception as e:
            log.debug("登出失败（忽略）: %s", e)
    return results


def report_status(store: KLineStore, cfg: dict) -> list:
    """返回每条目的数据水位（最新 time_key），用于状态可查。"""
    rows = []
    for code, kt, au in iter_ingest_jobs(cfg):
        wm = store.max_time_key(code, kt.name, au.name)
        rows.append((code, kt.name, au.name, wm))
    return rows


def check_staleness(store: KLineStore, cfg: dict, now=None, thresholds=None) -> list:
    """停更告警：水位在阈值时长内未推进（或无数据）则告警。

    阈值按级别粒度区分：分钟级默认 0.5h，日线及以上默认 48h（覆盖周末/长假），
    可用 thresholds 覆盖，形如 {"intraday": 0.5, "day": 48.0}。
    """
    now = now or datetime.now()
    thresholds = thresholds or DEFAULT_STALE_HOURS
    alerts = []
    for code, kt, au in iter_ingest_jobs(cfg):
        wm = store.max_time_key(code, kt.name, au.name)
        if wm is None:
            alerts.append({"code": code, "kl_type": kt.name, "autype": au.name,
                           "latest": None, "reason": "no-data"})
            continue
        age_h = (now - datetime.strptime(wm, "%Y-%m-%d %H:%M:%S")).total_seconds() / 3600
        limit = thresholds["intraday"] if kt.value < KL_TYPE.K_DAY.value else thresholds["day"]
        if age_h > limit:
            alerts.append({"code": code, "kl_type": kt.name, "autype": au.name,
                           "latest": wm, "age_hours": round(age_h, 2), "reason": "stale"})
    return alerts


def main(argv=None):
    p = argparse.ArgumentParser(description="拉取原始 K 线并幂等写入 DuckDB")
    p.add_argument("--code", help="股票代码，如 sz.000001（配置文件模式可省略）")
    p.add_argument("--kl-type", help="K 线级别，如 K_DAY/K_60M/K_5M")
    p.add_argument("--autype", default="QFQ", help="复权类型 QFQ/HFQ/NONE")
    p.add_argument("--begin", help="起始日期 YYYY-MM-DD；与 --end 一起进入区间重刷"
                                   "（该区间删除后重写，其余历史不变；缺省取库内最早一行）")
    p.add_argument("--end", help="结束日期 YYYY-MM-DD（默认今天）；单独指定即重刷"
                                 "「库内最早一行 ~ 该日期」")
    p.add_argument("--full", action="store_true", help="全量重刷（清空后重拉）")
    p.add_argument("--chunk-days", type=int, default=None, help="首次回填分块大小（天）")
    p.add_argument("--check-gaps", action="store_true", help="灌数后检测缺失交易日")
    p.add_argument("--db-path", default=DEFAULT_DB_PATH, help="DuckDB 库路径")
    p.add_argument("--config", help="JSON 配置文件路径，驱动批量灌数")
    p.add_argument("--code-prefix", help="批量模式按代码前缀过滤（如 sz. 只跑深市）")
    p.add_argument("--status", action="store_true", help="打印每股票数据水位后退出")
    p.add_argument("--check-stale", action="store_true", help="检查停更并告警后退出")
    p.add_argument("--sleep", type=float, default=None,
                   help="接口请求间隔秒数（限频保护，默认 %.1f）" % DEFAULT_REQUEST_INTERVAL)
    p.add_argument("--retries", type=int, default=None,
                   help="单次拉取失败的重试次数（指数退避+重登会话，默认 %d）" % DEFAULT_RETRY_ATTEMPTS)
    p.add_argument("--abort-after", type=int, default=None,
                   help="连续失败任务数达到该值则中止批量（默认 %d）" % ABORT_AFTER)
    p.add_argument("--force", action="store_true",
                   help="忽略「已是最新」判定，总是请求接口（默认已是最新则跳过）")
    p.add_argument("--bar-lag-minutes", type=int, default=None,
                   help="判定「本应存在的最新 K 线」时对当前时间回拨的分钟数"
                        "（数据源发布延迟，默认 %d；调大更保守、最新一根 bar 晚一轮入库）"
                        % DEFAULT_BAR_LAG_MINUTES)
    p.add_argument("--verbose", action="store_true", help="打印 DEBUG 日志")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # --status / --check-stale 优先于批量灌数：二者只读，不应触发拉取
    if args.status:
        if not args.config and (not args.code or not args.kl_type):
            p.error("--status 需 --config 或 --code + --kl-type")
        cfg = load_config(args.config) if args.config else {"stocks": [{"code": args.code, "kl_types": [args.kl_type], "autypes": [args.autype]}]}
        if args.code_prefix:
            cfg["code_prefix"] = args.code_prefix
        with KLineStore(args.db_path, read_only=True) as store:
            for code, kt_name, au_name, wm in report_status(store, cfg):
                print(f"{code}\t{kt_name}\t{au_name}\t{wm}")
        return 0

    if args.check_stale:
        if not args.config and (not args.code or not args.kl_type):
            p.error("--check-stale 需 --config 或 --code + --kl-type")
        cfg = load_config(args.config) if args.config else {"stocks": [{"code": args.code, "kl_types": [args.kl_type], "autypes": [args.autype]}]}
        if args.code_prefix:
            cfg["code_prefix"] = args.code_prefix
        with KLineStore(args.db_path, read_only=True) as store:
            alerts = check_staleness(store, cfg)
        for a in alerts:
            print(f"[STALE] {a}")
        print(f"stale alerts: {len(alerts)}")
        return 1 if alerts else 0

    if args.config:
        cfg = load_config(args.config)
        if args.code_prefix:
            cfg["code_prefix"] = args.code_prefix
        if args.sleep is not None:
            cfg["request_interval_seconds"] = args.sleep
        if args.retries is not None:
            cfg["retry_attempts"] = args.retries
        if args.abort_after is not None:
            cfg["max_consecutive_failures"] = args.abort_after
        if args.bar_lag_minutes is not None:
            cfg["bar_lag_minutes"] = args.bar_lag_minutes
        if args.force:
            cfg["skip_fresh"] = False
        if args.full:
            cfg["full"] = True
        aborted = None
        try:
            results = ingest_from_config(cfg)
        except BatchAborted as e:
            results = e.results
            aborted = str(e)
            log.error("批量中止：%s", e)
        ok = sum(1 for r in results.values() if r["status"] == "ok")
        skipped = sum(1 for r in results.values() if r["status"] == "skipped")
        failed = sum(1 for r in results.values() if r["status"] == "failed")
        print(f"batch ingest done: {ok} ok, {skipped} skipped（已是最新，未请求接口）, "
              f"{failed} failed" + (f"（已中止：{aborted}）" if aborted else ""))
        return 0 if failed == 0 and aborted is None else 1

    if not args.code or not args.kl_type:
        p.error("单股模式需 --code 与 --kl-type（或改用 --config）")

    k_type = parse_kl_type(args.kl_type)
    autype = parse_autype(args.autype)
    cal = get_calendar()

    stats = {}
    with KLineStore(args.db_path) as store:
        n = ingest(
            args.code, k_type, autype, store,
            begin=args.begin, end=args.end, full=args.full,
            chunk_days=args.chunk_days, cal=cal, check_gaps=args.check_gaps,
            sleep=args.sleep if args.sleep is not None else DEFAULT_REQUEST_INTERVAL,
            retries=args.retries if args.retries is not None else DEFAULT_RETRY_ATTEMPTS,
            skip_fresh=not args.force,
            bar_lag_minutes=(args.bar_lag_minutes if args.bar_lag_minutes is not None
                             else DEFAULT_BAR_LAG_MINUTES),
            stats=stats,
        )
    if stats.get("skipped"):
        print(f"skip: {args.code} {k_type.name} {autype.name} 已是最新"
              f"（水位 {stats['watermark']} ≥ 应有 {stats['expected']}），未请求接口")
    else:
        print(f"done: wrote {n} rows for {args.code} {k_type.name} {autype.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
