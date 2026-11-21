# -*- coding: utf-8 -*-
"""
介入点落库冒烟（chan-entry-point-candidate tasks 4.2）

链路：`incremental_engine.recompute_stock`（单级别 trigger_step CChan +
`_compute_sub_for_l1` 旁路子级）→ `_extract_bsp_rows`（调用共享核心
`entry_point_result`）→ `persist_full_set` → PG `bsp_index` 介入三列。

断言：
    1. 开关全关（默认配置）：行写入成功，entry_point 全 FALSE（等价性）
    2. 介入开关开启：行写入成功，entry 列合法（TRUE 行必须有 method）
    3. 增量刷新：再次 recompute 后行集合与介入列可重复再现（幂等）

环境：需要 PG_DSN 与 DuckDB 数据（Windows 本机 PG12，库 chan）。
运行：
    PG_DSN="host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres" \
        .venv/Scripts/python.exe Debug/test_entry_persist.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PG_DSN = os.environ.get("PG_DSN", "host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres")
os.environ["PG_DSN"] = PG_DSN

import psycopg2  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        FAILURES.append(name)


def fetch_entry_rows(code, kl_type_canonical):
    conn = psycopg2.connect(PG_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT bsp_date, bsp_type, is_buy, time_key, entry_point, entry_method, entry_level
                     FROM bsp_index
                    WHERE code = %s AND kl_type = %s AND autype = 'QFQ'
                    ORDER BY bsp_date""",
                (code, kl_type_canonical),
            )
            return cur.fetchall()
    finally:
        conn.close()


def main():
    from WebAPI import incremental_engine
    from WebAPI.chan_config_store import save, load

    code = "sz.000001"
    canonical = "D"

    # ---- 1. 默认（开关全关）----
    print("\n[1] 默认配置（介入全关）recompute")
    save({}, "standard", updated_by="entry-persist-test")
    r = incremental_engine.recompute_stock(code, "D")
    check("recompute 返回非 None", r is not None, str(r))
    if r is None:
        print("✗ 无法继续（DuckDB 无数据？）")
        return 1
    rows = fetch_entry_rows(code, canonical)
    check("行数 > 0", len(rows) > 0, f"实际 {len(rows)}")
    all_off = all(not r[4] for r in rows)
    check("entry_point 全 FALSE（等价性）", all_off,
          f"异常行 {[r for r in rows if r[4]][:3]}")

    # ---- 2. 介入开启（1买方法1+方法2）----
    print("\n[2] 介入开启（bsp1_entry + qjt + aux）recompute")
    save({"bsp1_entry": True, "bsp1_entry_qjt": True, "bsp1_entry_aux": True,
          "bsp1_entry_qjt_depth": 2},
         "standard", updated_by="entry-persist-test")
    r2 = incremental_engine.recompute_stock(code, "D")
    check("recompute 返回非 None", r2 is not None, str(r2))
    rows2 = fetch_entry_rows(code, canonical)
    # 指纹变化应触发全量重算
    check("mode=full（指纹变化强制全量）", r2 and r2.get("mode") == "full", str(r2))
    # 行集合（不含介入列）与关态一致——介入不改成立性
    keyset_off = [(r[0], r[1], r[2], r[3]) for r in rows]
    keyset_on = [(r[0], r[1], r[2], r[3]) for r in rows2]
    check("行集合不变（介入不改成立性）", keyset_off == keyset_on,
          f"off={len(keyset_off)} on={len(keyset_on)}")
    hits = [r for r in rows2 if r[4]]
    print(f"    介入命中 {len(hits)} 行：{[(r[3], r[5], r[6]) for r in hits][:5]}")
    valid = all(r[5] in ("qjt", "aux") for r in hits)
    check("命中行 method 合法（qjt/aux）", valid,
          str([r for r in hits if r[5] not in ("qjt", "aux")][:3]))
    qjt_rows = [r for r in hits if r[5] == "qjt"]
    check("qjt 行 level >= 1", all(isinstance(r[6], int) and r[6] >= 1 for r in qjt_rows),
          str(qjt_rows[:3]))

    # ---- 3. 幂等重算 ----
    print("\n[3] 同配置再次 recompute（幂等）")
    r3 = incremental_engine.recompute_stock(code, "D")
    rows3 = fetch_entry_rows(code, canonical)
    check("介入列可重复再现", rows2 == rows3,
          f"diff: {set(rows2) ^ set(rows3)}")

    # ---- 收尾：恢复默认配置 ----
    save({}, "standard", updated_by="entry-persist-test")

    print()
    if FAILURES:
        print(f"✗ {len(FAILURES)} 项失败：{FAILURES}")
        return 1
    print("✓ 全部用例通过")
    return 0


if __name__ == '__main__':
    sys.exit(main())
