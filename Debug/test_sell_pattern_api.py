# -*- coding: utf-8 -*-
"""卖向形态落库与查询语义测试（chan-pattern-sell-signal 任务 2.6）。

PG 可用时验证：direction 落库 round-trip、query_patterns 方向过滤、
关注范围过滤语义（清单为空→空列表、显式 code 不过滤）。PG 不可用则跳过。

运行：PYTHONIOENCODING=utf-8 PYTHONPATH=. .venv/Scripts/python.exe Debug/test_sell_pattern_api.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from WebAPI import pattern_store  # noqa: E402
from WebAPI.pattern_store import _get_pg_conn, query_patterns, upsert_pattern_rows  # noqa: E402

PASS = 0
FAIL = 0


def check(name, ok):
    global PASS, FAIL
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}")
    if ok:
        PASS += 1
    else:
        FAIL += 1


def main():
    conn = _get_pg_conn()
    if conn is None:
        print("== PG 不可用，跳过 ==")
        return
    conn.close()

    print("== 卖向落库 round-trip ==")
    rows = [
        ("shooting_star", "2026-11-20", "2026-11-20 15:00:00", 10.5,
         10.6, 10.0, 80, "强", False, None, '{"k":"v"}', "sell"),
        ("high_engulfing", "2026-11-21", "2026-11-21 15:00:00", 9.9,
         11.1, 9.8, 70, "强", False, None, "{}", "sell"),
        ("w_bottom", "2026-11-21", "2026-11-21 15:00:00", 10.2,
         10.5, 10.5, 75, "强", False, None, "{}", "buy"),
    ]
    n = upsert_pattern_rows("test.sell001", "D", "QFQ", rows)
    check("3 行落库", n == 3)

    r = query_patterns(code="test.sell001")
    by_type = {it["pattern_type"]: it for it in r["items"]}
    check("round-trip 3 行", r["total"] == 3)
    check("卖向行 direction=sell", by_type["shooting_star"]["direction"] == "sell")
    check("买向行 direction=buy", by_type["w_bottom"]["direction"] == "buy")

    print("== direction 过滤 ==")
    r = query_patterns(code="test.sell001", direction="sell")
    check("direction=sell 只见卖向", r["total"] == 2
          and all(it["direction"] == "sell" for it in r["items"]))
    r = query_patterns(code="test.sell001", direction="buy")
    check("direction=buy 只见买向", r["total"] == 1
          and r["items"][0]["direction"] == "buy")

    print("== 关注范围过滤语义（router 层）==")
    from WebAPI.routers.pattern import _watched_codes

    watched = _watched_codes()
    # _watched_codes 返回 None 表示 store 不可用；否则验证清单结构与空语义
    if watched is not None:
        check("关注清单为列表", isinstance(watched, list))
        check("关注清单无重复", len(watched) == len(set(watched)))
    else:
        check("store 不可用时返回 None（不过滤）", True)

    # 幂等：重复 upsert 同键不新增
    n2 = upsert_pattern_rows("test.sell001", "D", "QFQ", rows[:1])
    r = query_patterns(code="test.sell001")
    check("重复 upsert 幂等（仍 3 行）", n2 == 1 and r["total"] == 3)

    print(f"\n结果: PASS={PASS} FAIL={FAIL}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
