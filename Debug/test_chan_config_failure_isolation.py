# -*- coding: utf-8 -*-
"""单键失败隔离验证（chan-config-panel task 4.6）。

要求：一个键算失败时，其余键必须全部成功，且失败原因逐条列在
`summary.failed` 里（含 code / 周期 / 原因），不能整批中断。

做法：
    用一个很小的键范围（2 只股票 × 2 个周期）跑 `catch_up(force=True)`，
    并 monkeypatch `recompute_stock` 让其中一个键抛异常 —— 这样既验证了
    隔离语义，又不至于为了复现错误去改真实数据。

历史失败样本 `sh.600007 / 5m`（曾经的 pickle 递归溢出）在当前代码上已
能正常算完（64 行），所以这里改为构造式注入 —— 注入的失败与真实失败
走的是同一条 `except` 分支。

运行：
    .venv/Scripts/python.exe Debug/test_chan_config_failure_isolation.py
"""

import os
import sys

_DEBUG_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_DEBUG_DIR)
sys.path.insert(0, _REPO_ROOT)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

os.environ.setdefault(
    "PG_DSN", "host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres"
)

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
    from WebAPI import incremental_engine as ie

    # sz.000001 有 D/W/M/30m/5m 五个键，sz.000021 有 D/30m —— 共 7 个键，
    # 足够验证「一个挂掉其余照跑」。
    codes = ["sz.000001", "sz.000021"]
    periods = ["D", "W", "M", "30m", "5m"]

    keys = ie.list_stale_keys(codes=codes, periods=periods, force=True)
    print(f"待处理键（{len(codes)} 只 × {len(periods)} 周期，实际存在 {len(keys)} 个）：{keys}")
    if len(keys) < 3:
        print("!! 范围内键数 < 3，无法充分验证隔离语义")
        return 1

    # 挑一个真实存在的键注入失败
    poison_code, poison_period, _ = keys[0]
    real = ie.recompute_stock
    calls = []

    def flaky(code, period, **kw):
        calls.append((code, period))
        if code == poison_code and period == poison_period:
            raise RuntimeError("injected failure for isolation test")
        return real(code, period, **kw)

    ie.recompute_stock = flaky
    try:
        result = ie.catch_up(codes=codes, periods=periods, limit=0, force=True)
    finally:
        ie.recompute_stock = real

    print(f"\n扫描 {result['scanned']}，成功 {result['updated']}，失败 {len(result['failed'])}")
    check("扫描数与键数一致", result["scanned"] == len(keys),
          f"{result['scanned']} vs {len(keys)}")
    check("成功 + 失败 = 扫描数",
          result["updated"] + len(result["failed"]) == result["scanned"],
          f"{result['updated']} + {len(result['failed'])} != {result['scanned']}")
    check("失败恰好一个（注入的那个）", len(result["failed"]) == 1,
          str([f.get("code") for f in result["failed"]]))
    check("其余键全部成功", result["updated"] == len(keys) - 1,
          f"{result['updated']} vs {len(keys) - 1}")

    if result["failed"]:
        f = result["failed"][0]
        print(f"  失败明细：{f}")
        check("失败项含 code", f.get("code") == poison_code, str(f.get("code")))
        check("失败项含周期", f.get("kl_type") == poison_period, str(f.get("kl_type")))
        check("失败项含原因", "injected failure" in str(f.get("error")), str(f.get("error")))

    check("注入点之后的键仍被处理（循环未中断）",
          len(calls) == len(keys), f"{len(calls)} vs {len(keys)}")

    print(f"\n{'=' * 46}\n合计: {_PASS} PASS, {_FAIL} FAIL\n{'=' * 46}")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
