# -*- coding: utf-8 -*-
"""DuckDB 锁冲突识别的单元验证（chan-config-panel 4.7 副产物）。

背景：批量同步连续打开 73 次 DuckDB 连接，撞上其它进程持锁的窗口时必须
**等待重试**而不是直接失败。`_connect()` 原来只认 POSIX 的
`Could not set lock`，Windows 上的 `Cannot open file ... 另一个程序正在使用此文件`
会漏判。这里固定住跨平台的识别规则。

运行：
    .venv/Scripts/python.exe Debug/test_klstore_lock_retry.py
"""

import os
import sys

_DEBUG_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_DEBUG_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from ChanAnalyse.DataAPI.KLineStore import _is_lock_conflict  # noqa: E402

_PASS = 0
_FAIL = 0


def check(label, cond, detail=""):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  [OK]   {label}")
    else:
        _FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


def main():
    conflict = [
        'Could not set lock on file "x": Conflicting lock is held',
        'IO Error: Cannot open file "E:\\x\\kl_store.duckdb": '
        "另一个程序正在使用此文件，进程无法访问。",
        'IO Error: Cannot open file "E:\\x\\kl_store.duckdb": The process cannot '
        "access the file because it is being used by another process.",
        "Conflicting lock is held in /usr/bin/python (PID 1)",
    ]
    not_conflict = [
        "Catalog Error: Table with name foo does not exist!",
        "Binder Error: Referenced column not found",
        "Parser Error: syntax error at or near",
    ]

    print("[区分锁冲突与真实错误]")
    for msg in conflict:
        check(f"锁冲突应重试：{msg[:48]}...", _is_lock_conflict(Exception(msg)))
    for msg in not_conflict:
        check(f"非锁错误应立即抛：{msg[:48]}...", not _is_lock_conflict(Exception(msg)))

    print(f"\n{'=' * 46}\n合计: {_PASS} PASS, {_FAIL} FAIL\n{'=' * 46}")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
