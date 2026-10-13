# -*- coding: utf-8 -*-
"""
download_kl「--begin/--end 区间重刷」冒烟测试（无需联网，内存 DuckDB）。

修复的缺陷：此前库内已有数据时 --begin 被忽略（起点被换成回看窗口），
--begin 早于水位时甚至会以 begin > end 调接口 → 静默无操作。
现在约定：指定任一端即进入区间重刷 —— 只动 [start, stop]，先按子区间删除旧行再重写，
其余历史不变；未指定时才是增量续拉。

覆盖：
1. 拉取区间就是 [begin, end]（不再被回看窗口替换）
2. 区间内「数据源已不再返回」的行被删除（镜像数据源），区间外历史不动
3. 只给 --end：起点取库内最早一行
4. 数据源对该区间整体无数据 → 删除区间内旧行
5. begin 晚于 end → 不发请求、不删数据
6. stats 标记 range_refresh

运行: PYTHONPATH=. .venv/bin/python Debug/test_range_refresh.py
"""

import importlib.util
import sys
import types
from datetime import date
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


def main() -> int:
    from ChanAnalyse.Common.CEnum import AUTYPE, DATA_FIELD, KL_TYPE
    from ChanAnalyse.Common.CTime import CTime
    from ChanAnalyse.DataAPI.IngestUtil import klu_to_row
    from ChanAnalyse.DataAPI.KLineStore import KLineStore
    from ChanAnalyse.KLine.KLine_Unit import CKLine_Unit

    dk = load_download_kl()
    failures = []

    def check(cond, msg):
        print(("PASS " if cond else "FAIL ") + msg)
        if not cond:
            failures.append(msg)

    def bar(day: str, close=10.0):
        y, m, d = (int(x) for x in day.split("-"))
        return CKLine_Unit({
            DATA_FIELD.FIELD_TIME: CTime(y, m, d, 0, 0, 0, auto=False),
            DATA_FIELD.FIELD_OPEN: close,
            DATA_FIELD.FIELD_HIGH: close + 0.1,
            DATA_FIELD.FIELD_LOW: close - 0.1,
            DATA_FIELD.FIELD_CLOSE: close,
            DATA_FIELD.FIELD_VOLUME: 1000.0,
        })

    CODE, KT, AU = "sz.000001", KL_TYPE.K_DAY, AUTYPE.QFQ

    # 模拟数据源：只提供这几个交易日（故意不含 2024-01-04，模拟源端已无该行）
    SOURCE = {d: bar(d) for d in ("2023-12-29", "2024-01-02", "2024-01-03", "2024-06-03")}

    def new_store(local_days):
        """建一个内存库并写入 local_days（本地已有的历史）。"""
        store = KLineStore(":memory:")
        rows = [klu_to_row(bar(d), CODE, KT, AU) for d in local_days]
        store.upsert(pd.DataFrame(rows))
        return store

    def stored_days(store):
        df = store.query(CODE, KT.name, AU.name)
        return [t[:10] for t in df["time_key"]]

    def patch_fetch():
        calls = []

        def fake_fetch(code, k_type, autype, begin, end):
            calls.append((begin, end))
            return [b for d, b in sorted(SOURCE.items()) if begin <= d <= end]

        dk.fetch_baostock = fake_fetch
        return calls

    # 打桩 baostock 会话（区间重刷走 manage_auth=True 的登录路径）
    import ChanAnalyse.DataAPI.BaoStockAPI as ba_mod

    real_cbao, real_fetch = ba_mod.CBaoStock, dk.fetch_baostock
    ba_mod.CBaoStock = types.SimpleNamespace(do_init=lambda: None, do_close=lambda: None)
    try:
        LOCAL = ["2023-12-29", "2024-01-02", "2024-01-03", "2024-01-04", "2024-06-03"]

        # ---- 1 + 2. 拉取区间 = [begin, end]；区间内源端已无的行被删，区间外不动 ----
        calls = patch_fetch()
        store = new_store(LOCAL)
        stats = {}
        dk.ingest(CODE, KT, AU, store, begin="2024-01-03", end="2024-01-04", stats=stats)
        check(calls == [("2024-01-03", "2024-01-04")],
              f"按 --begin/--end 拉取，不被回看窗口替换（实际 {calls}）")
        days = stored_days(store)
        check("2024-01-04" not in days,
              f"区间内源端已无的行被删除（实际 {days}）")
        check(days == ["2023-12-29", "2024-01-02", "2024-01-03", "2024-06-03"],
              f"区间外历史不变（实际 {days}）")
        check(stats.get("range_refresh") is True and not stats.get("skipped"),
              "stats 标记 range_refresh（且不算 skipped）")

        # ---- 3. 只给 --end：起点取库内最早一行 ----
        calls = patch_fetch()
        store = new_store(LOCAL)
        dk.ingest(CODE, KT, AU, store, end="2024-01-03")
        check(calls == [("2023-12-29", "2024-01-03")],
              f"仅 --end 时起点为库内最早一行（实际 {calls}）")
        days = stored_days(store)
        check(days == ["2023-12-29", "2024-01-02", "2024-01-03", "2024-01-04", "2024-06-03"],
              f"仅 --end 时 end 之后的历史不受影响（实际 {days}）")

        # ---- 4. 数据源对该区间整体无数据 → 删除区间内旧行 ----
        calls = patch_fetch()
        store = new_store(["2024-03-01", "2024-06-03"])
        dk.ingest(CODE, KT, AU, store, begin="2024-03-01", end="2024-03-05")
        check(stored_days(store) == ["2024-06-03"],
              f"源端无数据的区间被清空（实际 {stored_days(store)}）")

        # ---- 5. begin 晚于 end → 不发请求、不删数据 ----
        calls = patch_fetch()
        store = new_store(LOCAL)
        dk.ingest(CODE, KT, AU, store, begin="2024-06-03", end="2024-01-03")
        check(calls == [], f"空区间不发请求（实际 {calls}）")
        check(stored_days(store) == LOCAL, "空区间不动数据")

        # ---- 6. 不指定 begin/end 时不进入区间重刷（增量路径不受影响） ----
        calls = patch_fetch()
        store = new_store(LOCAL)
        stats = {}
        today = date.today().strftime("%Y-%m-%d")
        dk.ingest(CODE, KT, AU, store, stats=stats)
        check(stats.get("range_refresh") is False, "增量续拉不标记 range_refresh")
        check(len(calls) == 1 and calls[0][1] == today,
              f"增量续拉以今天为终点（实际 {calls}）")
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
