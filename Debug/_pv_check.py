# -*- coding: utf-8 -*-
"""独立复核 design.md D1「事后价格验证」表的 20 日极值。

只读 DuckDB，不跑缠论计算：以买点当日收盘价为基准，取之后 20 个交易日
（不含当日）的最高价/最低价，与 design 表中「20日极值」列对照。

运行： .venv/Scripts/python.exe Debug/_pv_check.py
"""

import os
import sys

import duckdb

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB = os.path.join(_REPO, "Data", "kl_store.duckdb")

# (code, date, 方向, design 表里的 20日极值)
CASES = [
    ("sh.600020", "2020-02-04", "buy", "+9.23%"),
    ("sz.000020", "2021-02-05", "buy", "+14.32%"),
    ("sz.000025", "2026-07-09", "buy", "+22.20%"),
    ("sh.600018", "2024-10-08", "sell", "-12.22%"),
    ("sh.600029", "2026-02-09", "sell", "-26.66%"),
    ("sh.600028", "2020-09-28", "buy", "+3.39%"),
]

con = duckdb.connect(_DB, read_only=True)
print(f"{'代码':<12}{'日期':<12}{'方向':<6}{'基准收盘':>10}{'20日极值':>12}"
      f"{'design':>10}{'差':>8}")
print("-" * 72)
bad = 0
for code, date, side, expect in CASES:
    rows = con.execute(
        "SELECT time_key, close, high, low FROM kline "
        "WHERE code = ? AND kl_type = 'K_DAY' AND autype = 'QFQ' "
        "AND time_key >= ? ORDER BY time_key",
        [code, date],
    ).fetchall()
    if not rows:
        print(f"{code:<12}{date:<12}{side:<6}  无数据")
        bad += 1
        continue
    tk0, c0, _, _ = rows[0]
    if tk0[:10] != date:
        print(f"{code:<12}{date:<12}{side:<6}  当日无 K 线（首条 {tk0[:10]}）")
        bad += 1
        continue
    win = rows[1:21]
    if side == "buy":
        ext = (max(r[2] for r in win) / c0 - 1) * 100
    else:
        ext = (min(r[3] for r in win) / c0 - 1) * 100
    exp = float(expect.rstrip("%"))
    diff = ext - exp
    flag = "" if abs(diff) < 0.02 else "  <-- 不一致"
    if flag:
        bad += 1
    print(f"{code:<12}{date:<12}{side:<6}{c0:>10.4f}{ext:>11.2f}%"
          f"{exp:>9.2f}%{diff:>+7.2f}{flag}")

con.close()
print("-" * 72)
print(f"{'✓ 全部与 design 一致' if not bad else f'✗ {bad} 项不一致'}")
sys.exit(1 if bad else 0)
