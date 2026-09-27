# -*- coding: utf-8 -*-
"""
KLineStore 读写并发冒烟测试（无需联网）。

验证 DuckDB「读写互斥锁」下的并发策略（见 KLineStore 并发模型注释）：
1. 写方连续 upsert 持有独占锁的场景下，读方 read_only 查询能靠
   短连接 + 锁自旋重试穿插成功（成功率与最大等待有界）；
2. 只读连接拒绝写入；文件不存在时 read_only 回退建库；
3. 写方按操作开合连接时不会长期占锁（读方无需等满重试上限）。

运行: PYTHONPATH=. .venv/bin/python Debug/test_store_lock.py
"""

import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

WRITER = r"""
import sys, time, pandas as pd
sys.path.insert(0, %r)
from ChanAnalyse.DataAPI.KLineStore import KLineStore

db_path, seconds = sys.argv[1], float(sys.argv[2])
end = time.time() + seconds
n = 0
with KLineStore(db_path) as store:
    while time.time() < end:
        # 每次写入各开合一次短连接（与灌数一致的用法）
        df = pd.DataFrame([{
            "code": "sz.000001", "kl_type": "K_DAY", "autype": "QFQ",
            "time_key": "2026-01-01 00:00:00", "open": 1.0, "high": 1.0,
            "low": 1.0, "close": 1.0, "volume": 1.0, "turnover": 1.0,
            "turnover_rate": 1.0,
        }])
        store.upsert(df)
        n += 1
        time.sleep(0.05)
print("writes done", n, flush=True)
"""


def main() -> int:
    from ChanAnalyse.DataAPI.KLineStore import KLineStore

    failures = []

    def check(cond, msg):
        print(("PASS " if cond else "FAIL ") + msg)
        if not cond:
            failures.append(msg)

    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "conc.duckdb")

        # ---- 1. 写方连续写 6s，读方并发读 20 次 ----
        w = subprocess.Popen(
            [sys.executable, "-c", WRITER % str(ROOT), db, "6"],
            stdout=subprocess.PIPE, text=True,
        )
        time.sleep(0.5)  # 等写方建库完成

        ok, waits = 0, []
        for _ in range(20):
            t0 = time.time()
            try:
                with KLineStore(db, read_only=True) as store:
                    store.query("sz.000001", "K_DAY", "QFQ")
                ok += 1
                waits.append(round(time.time() - t0, 2))
            except Exception as e:
                waits.append(round(time.time() - t0, 2))
                print("  read error:", str(e).splitlines()[0][:100])
            time.sleep(0.1)
        w_out, _ = w.communicate()

        check(ok >= 18, f"写方连续写入时读方成功 {ok}/20（期望 ≥18）")
        check(max(waits) < 6.0, f"单次读最大等待 {max(waits)}s（期望 <6s 重试上限）")
        check("writes done" in w_out, f"写方完成写入（{w_out.strip()}）")

        # ---- 2. 只读连接拒绝写入 ----
        with KLineStore(db, read_only=True) as store:
            try:
                import pandas as pd
                store.upsert(pd.DataFrame([{"code": "x"}]))
                check(False, "只读连接应拒绝写入")
            except Exception:
                check(True, "只读连接拒绝写入")

        # ---- 3. read_only 遇缺失文件回退建库 ----
        db2 = str(Path(tmp) / "new.duckdb")
        with KLineStore(db2, read_only=True) as store:
            store.execute("SELECT 1")  # 可执行即连接有效
        check(Path(db2).exists(), "read_only 遇缺失文件回退建库")

    print()
    if failures:
        print(f"{len(failures)} FAILED")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
