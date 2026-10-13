# -*- coding: utf-8 -*-
"""
download_kl「已是最新则不请求接口」冒烟测试（无需联网）。

覆盖：
1. expected_latest_time_key 的判定（分钟级/日线/周线/月线 × 盘中、收盘后、周末）
2. 水位已是最新 → ingest 不发请求、不登录会话、返回 0 且 stats["skipped"]=True
3. 水位落后 → 照常请求（起点仍是回看窗口）
4. --force（skip_fresh=False）→ 即便已是最新也请求
5. --begin/--end 显式区间 → 不跳过
6. 无法判定（expected 为 None，如无交易日历）→ 失败开放，照常请求
7. 批量模式把跳过的任务记为 status="skipped"，不计入失败

运行: PYTHONPATH=. .venv/bin/python Debug/test_skip_fresh.py
"""

import importlib.util
import sys
import types
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def load_download_kl():
    """按文件路径加载 Data/download_kl.py（它不在包里，不能直接 import）。"""
    path = ROOT / "Data" / "download_kl.py"
    spec = importlib.util.spec_from_file_location("download_kl", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["download_kl"] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeStore:
    """只实现 ingest 用到的接口的最小 store，wm 为水位。"""

    def __init__(self, wm=None):
        self._wm = wm
        self.upserted = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def max_time_key(self, *a):
        return self._wm

    def min_time_key(self, *a):
        return "2000-01-01 00:00:00"

    def delete(self, *a):
        return 0

    def upsert(self, df):
        self.upserted += len(df)
        return len(df)

    def query(self, *a, **k):
        return pd.DataFrame()


def main() -> int:
    from ChanAnalyse.Common.CEnum import AUTYPE, KL_TYPE
    from ChanAnalyse.DataAPI.IngestUtil import expected_latest_time_key

    dk = load_download_kl()
    failures = []

    def check(cond, msg):
        print(("PASS " if cond else "FAIL ") + msg)
        if not cond:
            failures.append(msg)

    def eq(actual, expected, msg):
        check(actual == expected, f"{msg}（期望 {expected}，实际 {actual}）")

    # ---- 1. expected_latest_time_key 判定表 ----
    # 2026-10-13 周二；10-09 周五 = 上一交易日/上一周最后交易日；09-30 = 上一月最后交易日
    cases = [
        ("2026-10-13 23:15", KL_TYPE.K_5M, "2026-10-13 15:00:00"),
        ("2026-10-13 23:15", KL_TYPE.K_60M, "2026-10-13 15:00:00"),
        ("2026-10-13 23:15", KL_TYPE.K_DAY, "2026-10-13 00:00:00"),
        ("2026-10-13 23:15", KL_TYPE.K_WEEK, "2026-10-09 00:00:00"),
        ("2026-10-13 23:15", KL_TYPE.K_MON, "2026-09-30 00:00:00"),
        ("2026-10-13 16:00", KL_TYPE.K_DAY, "2026-10-13 00:00:00"),   # 收盘后当日数据可见
        ("2026-10-13 15:10", KL_TYPE.K_DAY, "2026-10-12 00:00:00"),   # 回拨 30min 后当日尚未可见
        ("2026-10-13 15:10", KL_TYPE.K_5M, "2026-10-13 14:40:00"),    # 分钟级盘中/盘后按 bar 递推
        ("2026-10-13 10:32", KL_TYPE.K_5M, "2026-10-13 10:00:00"),
        ("2026-10-13 12:00", KL_TYPE.K_30M, "2026-10-13 11:30:00"),
        ("2026-10-13 09:32", KL_TYPE.K_5M, "2026-10-12 15:00:00"),    # 开盘不久：退到上一交易日
        ("2026-10-17 12:00", KL_TYPE.K_DAY, "2026-10-16 00:00:00"),   # 周六
        ("2026-10-17 12:00", KL_TYPE.K_WEEK, "2026-10-16 00:00:00"),
        ("2026-10-17 12:00", KL_TYPE.K_5M, "2026-10-16 15:00:00"),
        ("2026-10-16 16:00", KL_TYPE.K_WEEK, "2026-10-16 00:00:00"),  # 周五收盘后本周走完
        ("2026-10-30 16:00", KL_TYPE.K_MON, "2026-10-30 00:00:00"),   # 当月最后交易日收盘后
        ("2026-10-13 23:15", KL_TYPE.K_1S, None),                     # 秒级未支持 → 不判定
        ("2026-10-13 23:15", KL_TYPE.K_QUARTER, None),
    ]
    for ts, kt, want in cases:
        got = expected_latest_time_key(kt, now=datetime.fromisoformat(ts))
        eq(got, want, f"{ts} {kt.name} -> 应有最新 K 线")
    eq(expected_latest_time_key(KL_TYPE.K_DAY, now=datetime.fromisoformat("2026-10-13 23:15+08:00")),
       "2026-10-13 00:00:00", "带时区的 now 归一化为北京时间")
    eq(expected_latest_time_key(KL_TYPE.K_DAY, now=datetime.fromisoformat("2026-10-14 08:00+00:00")),
       "2026-10-14 00:00:00", "UTC now 按北京时间折算（16:00 → 当日已可见）")
    eq(expected_latest_time_key(KL_TYPE.K_DAY, now=datetime.fromisoformat("2026-10-13 23:15+00:00")),
       "2026-10-13 00:00:00", "UTC now 按北京时间折算（次日 07:15 → 当日尚未可见）")
    eq(expected_latest_time_key(KL_TYPE.K_DAY, lag_minutes=24 * 60,
                                now=datetime.fromisoformat("2026-10-13 23:15")),
       "2026-10-12 00:00:00", "调大 bar_lag_minutes 更保守")

    # ---- 打桩：BaoStock 登录/登出（不联网） ----
    import ChanAnalyse.DataAPI.BaoStockAPI as ba_mod

    real_cbao = ba_mod.CBaoStock
    auth_calls = {"init": 0, "close": 0}
    ba_mod.CBaoStock = types.SimpleNamespace(
        do_init=lambda: auth_calls.__setitem__("init", auth_calls["init"] + 1),
        do_close=lambda: auth_calls.__setitem__("close", auth_calls["close"] + 1),
    )
    real_fetch = dk.fetch_baostock

    def patch_fetch():
        """记录拉取次数/参数，且不返回任何数据。"""
        calls = []

        def fake_fetch(code, k_type, autype, begin, end):
            calls.append((k_type.name, begin, end))
            return []

        dk.fetch_baostock = fake_fetch
        return calls

    NOW = datetime.fromisoformat("2026-10-13 23:15")
    KL5, DAY = KL_TYPE.K_5M, KL_TYPE.K_DAY

    try:
        # ---- 2. 已是最新 → 不请求、不登录 ----
        for wm, kt in [("2026-10-13 15:00:00", KL5), ("2026-10-13 00:00:00", DAY)]:
            calls = patch_fetch()
            auth_calls.update(init=0, close=0)
            stats = {}
            n = dk.ingest("sz.301123", kt, AUTYPE.QFQ, FakeStore(wm),
                          cal=dk.get_calendar(), now=NOW, stats=stats)
            eq(n, 0, f"[{kt.name}] 已是最新返回写入 0 行")
            eq(len(calls), 0, f"[{kt.name}] 已是最新不发请求")
            eq(auth_calls["init"], 0, f"[{kt.name}] 已是最新不登录 BaoStock 会话")
            check(stats.get("skipped") is True, f"[{kt.name}] stats 标记 skipped")
            check(stats.get("watermark") == wm, f"[{kt.name}] stats 记录水位")

        # ---- 3. 水位落后 → 照常请求（起点为回看窗口起点之前） ----
        calls = patch_fetch()
        stats = {}
        dk.ingest("sz.301123", KL5, AUTYPE.QFQ, FakeStore("2026-10-09 15:00:00"),
                  cal=dk.get_calendar(), now=NOW, stats=stats)
        eq(len(calls), 1, "水位落后请求 1 次")
        check(not stats.get("skipped"), "水位落后不标记 skipped")
        check(len(calls) == 1 and calls[0][1] <= "2026-10-09",
              f"续拉起点落在回看窗口（实际 {calls[0][1] if calls else None}）")

        # ---- 4. --force → 已是最新也请求 ----
        calls = patch_fetch()
        stats = {}
        dk.ingest("sz.301123", KL5, AUTYPE.QFQ, FakeStore("2026-10-13 15:00:00"),
                  cal=dk.get_calendar(), now=NOW, skip_fresh=False, stats=stats)
        eq(len(calls), 1, "--force 时已是最新仍请求")
        check(not stats.get("skipped"), "--force 不标记 skipped")

        # ---- 5. --begin/--end 显式区间 → 不跳过 ----
        calls = patch_fetch()
        dk.ingest("sz.301123", KL5, AUTYPE.QFQ, FakeStore("2026-10-13 15:00:00"),
                  cal=dk.get_calendar(), now=NOW, begin="2026-10-01", end="2026-10-13")
        eq(len(calls), 1, "显式 --begin/--end 时已是最新仍请求")

        # ---- 6. 无法判定（expected=None）→ 失败开放，照常请求 ----
        real_expected = dk.expected_latest_time_key
        dk.expected_latest_time_key = lambda *a, **k: None
        calls = patch_fetch()
        dk.ingest("sz.301123", KL5, AUTYPE.QFQ, FakeStore("2026-10-13 15:00:00"),
                  cal=dk.get_calendar(), now=NOW)
        eq(len(calls), 1, "无法判定时不跳过（宁可多请求一次）")
        dk.expected_latest_time_key = real_expected

        # ---- 7. 批量模式：跳过记为 skipped，不计失败 ----
        calls = patch_fetch()
        real_store, real_iter = dk.KLineStore, dk.iter_ingest_jobs
        # 水位远在未来 → 任何 now 下都判为「已是最新」，测试与运行日期无关
        dk.KLineStore = lambda *a, **k: FakeStore("2999-01-01 00:00:00")
        dk.iter_ingest_jobs = lambda cfg: iter([
            ("sz.000001", KL_TYPE.K_DAY, AUTYPE.QFQ),
            ("sz.000002", KL_TYPE.K_WEEK, AUTYPE.QFQ),
        ])
        results = dk.ingest_from_config({"db_path": ":memory:"})
        eq(len(calls), 0, "批量模式跳过时不发任何请求")
        eq(sum(1 for r in results.values() if r["status"] == "skipped"), 2,
           "批量模式把跳过任务记为 status=skipped")
        eq(sum(1 for r in results.values() if r["status"] == "failed"), 0,
           "跳过的任务不算失败")
        dk.KLineStore, dk.iter_ingest_jobs = real_store, real_iter
    finally:
        dk.fetch_baostock = real_fetch
        ba_mod.CBaoStock = real_cbao

    print()
    if failures:
        print(f"{len(failures)} FAILED")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
