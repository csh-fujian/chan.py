# -*- coding: utf-8 -*-
"""
download_kl 失败退避 / 重试 / 会话重连 冒烟测试（无需联网）。

覆盖 2026-09-21 事故的三个修复点：
1. 单次拉取失败 → 指数退避重试，每次重试前重登会话
2. 不可重试错误（如指数无分钟线）→ 立即失败，不空耗退避
3. 批量循环连续失败 → 退避 + 重登 + 达阈值抛 BatchAborted（不再秒级空转）

运行: PYTHONPATH=. .venv/bin/python Debug/test_download_retry.py
"""

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_download_kl():
    """按文件路径加载 Data/download_kl.py（它不在包里，不能直接 import）。"""
    path = ROOT / "Data" / "download_kl.py"
    spec = importlib.util.spec_from_file_location("download_kl", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["download_kl"] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    from ChanAnalyse.Common.CEnum import AUTYPE, KL_TYPE

    dk = load_download_kl()
    failures = []

    def check(cond, msg):
        print(("PASS " if cond else "FAIL ") + msg)
        if not cond:
            failures.append(msg)

    # ---- 1. 失败重试 + 指数退避 + 每次重试前重登 ----
    calls = {"fetch": 0, "relogin": 0, "sleeps": []}
    real_sleep = dk.time.sleep
    real_fetch = dk.fetch_baostock
    real_relogin = dk.relogin

    def flaky_fetch(*a, **k):
        calls["fetch"] += 1
        if calls["fetch"] <= 2:
            raise Exception("网络接收错误")
        return []

    dk.fetch_baostock = flaky_fetch
    dk.relogin = lambda reason: calls.__setitem__("relogin", calls["relogin"] + 1)
    dk.time.sleep = lambda s: calls["sleeps"].append(round(s, 3))
    try:
        out = dk.fetch_with_retry("sz.000001", KL_TYPE.K_5M, AUTYPE.QFQ,
                                  "2026-01-01", "2026-01-10", retries=3)
        check(out == [], "重试后成功返回 []")
        check(calls["fetch"] == 3, f"共尝试 3 次（实际 {calls['fetch']}）")
        check(calls["relogin"] == 2, f"每次重试前都重登会话（实际 {calls['relogin']}）")
        check(calls["sleeps"] == [5.0, 10.0],
              f"指数退避 5s→10s（实际 {calls['sleeps']}）")
    except Exception as e:
        check(False, f"重试路径抛异常: {e}")

    # ---- 2. 重试耗尽后抛出最后一次异常 ----
    calls.update(fetch=0, relogin=0, sleeps=[])

    def always_fail(*a, **k):
        calls["fetch"] += 1
        raise Exception("网络接收错误")

    dk.fetch_baostock = always_fail
    try:
        dk.fetch_with_retry("sz.000001", KL_TYPE.K_5M, AUTYPE.QFQ,
                            "2026-01-01", "2026-01-10", retries=2)
        check(False, "重试耗尽应抛异常")
    except Exception as e:
        check("网络接收错误" in str(e), f"重试耗尽后抛出原始异常（{e}）")
        check(calls["fetch"] == 3, f"retries=2 → 共 3 次尝试（实际 {calls['fetch']}）")
        check(calls["relogin"] == 2, f"2 次重试各重登一次（实际 {calls['relogin']}）")

    # ---- 3. 不可重试错误立即失败 ----
    calls.update(fetch=0, relogin=0, sleeps=[])

    def index_no_minute(*a, **k):
        calls["fetch"] += 1
        raise Exception("没有获取到数据，注意指数是没有分钟级别数据的！")

    dk.fetch_baostock = index_no_minute
    try:
        dk.fetch_with_retry("sh.000001", KL_TYPE.K_5M, AUTYPE.QFQ,
                            "2026-01-01", "2026-01-10", retries=3)
        check(False, "不可重试错误应立即抛出")
    except Exception:
        check(calls["fetch"] == 1, f"不可重试错误只打 1 次（实际 {calls['fetch']}）")
        check(calls["sleeps"] == [], "不可重试错误不退避")
        check(calls["relogin"] == 0, "不可重试错误不重登")

    # ---- 4. 批量循环：连续失败 → 退避 + 重登 + 达阈值中止 ----
    dk.fetch_baostock = real_fetch
    dk.relogin = real_relogin
    dk.time.sleep = real_sleep

    job_calls = {"n": 0, "relogin": 0, "sleeps": []}
    real_ingest = dk.ingest
    real_batch_sleep = dk.time.sleep

    def failing_ingest(*a, **k):
        job_calls["n"] += 1
        raise Exception("网络接收错误")

    def fake_relogin(reason):
        job_calls["relogin"] += 1

    class FakeStore:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_iter(cfg):
        for i in range(50):
            yield ("sz.%06d" % i, KL_TYPE.K_5M, AUTYPE.QFQ)

    # 打桩：不真的登录/登出 baostock
    import ChanAnalyse.DataAPI.BaoStockAPI as ba_mod

    real_cbao = ba_mod.CBaoStock
    ba_mod.CBaoStock = types.SimpleNamespace(do_init=lambda: None, do_close=lambda: None)

    dk.ingest = failing_ingest
    dk.relogin = fake_relogin
    dk.get_calendar = lambda: None
    dk.KLineStore = lambda *a, **k: FakeStore()
    dk.iter_ingest_jobs = fake_iter
    dk.time.sleep = lambda s: job_calls["sleeps"].append(round(s, 3))
    try:
        results = dk.ingest_from_config({"db_path": ":memory:", "retry_attempts": 1,
                                         "max_consecutive_failures": 5})
        check(False, "连续失败应抛 BatchAborted")
    except dk.BatchAborted as e:
        check(len(e.results) == 5, f"中止时保留了逐条结果（{len(e.results)} 条）")
        check(job_calls["n"] == 5, f"达到阈值即停，不烧完 50 个任务（实际 {job_calls['n']}）")
        check(job_calls["sleeps"] == [5.0, 10.0, 20.0, 5.0, 10.0],
              f"失败任务指数退避、重登后归零（实际 {job_calls['sleeps']}）")
        check(job_calls["relogin"] == 1,
              f"连续失败 3 次触发重登（实际 {job_calls['relogin']}）")
        check("重跑同一条命令" in str(e), "中止提示包含续跑指引")
    except Exception as e:
        check(False, f"抛出了非 BatchAborted 异常: {type(e).__name__}: {e}")
    finally:
        dk.ingest = real_ingest
        dk.relogin = real_relogin
        dk.time.sleep = real_batch_sleep
        ba_mod.CBaoStock = real_cbao

    # ---- 5. 批量循环：中途成功会清零连续失败计数 ----
    job_calls.update(n=0, relogin=0, sleeps=[])

    def mixed_ingest(*a, **k):
        job_calls["n"] += 1
        if job_calls["n"] % 3 == 0:
            raise Exception("网络接收错误")
        return 1

    dk.ingest = mixed_ingest
    try:
        results = dk.ingest_from_config({"db_path": ":memory:", "retry_attempts": 0,
                                         "max_consecutive_failures": 3})
        ok = sum(1 for r in results.values() if r["status"] == "ok")
        failed = sum(1 for r in results.values() if r["status"] == "failed")
        check(ok == 34 and failed == 16,
              f"偶发失败不中止（ok={ok} failed={failed}，期望 34/16）")
        check(job_calls["relogin"] == 0, "成功穿插时不会触发重登")
    except dk.BatchAborted as e:
        check(False, f"偶发失败不应中止: {e}")
    finally:
        dk.ingest = real_ingest
        dk.relogin = real_relogin
        dk.time.sleep = real_batch_sleep
        ba_mod.CBaoStock = real_cbao

    print()
    if failures:
        print(f"{len(failures)} FAILED")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
