# -*- coding: utf-8 -*-
"""strategy-signal-page 后端端到端冒烟验证（任务 7.1，任务组 1/2/3/4 + 3.3）。

直接调 strategy_store / strategy_engines / monitor_store DAO（真实 PG
127.0.0.1:5432/chan + 只读 DuckDB Data/kl_store.duckdb），不触碰 CChan。
用后即删（临时验证脚本：实例级联删信号、测试 monitor 行删除）。

运行: PYTHONPATH=. PG_DSN="host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres" \
      .venv/Scripts/python.exe Debug/strategy_signal_smoke.py
"""

import sys
import traceback

sys.path.insert(0, ".")

PG_DSN = "host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres"

PASS = 0
FAIL = 0


def check(desc: str, cond: bool, extra: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {desc}" + (f" ({extra})" if extra else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {desc}" + (f" ({extra})" if extra else ""))


def main():
    from WebAPI import monitor_store as ms
    from WebAPI import strategy_store as ss
    from WebAPI.strategy_engines import get_definition, validate_params
    from WebAPI.strategy_engines.scheduler import scan_instance

    print("== 1. 建表幂等：连续 _ensure_tables 两次 ==")
    ss._ensure_tables()
    ss._ensure_tables()
    print("  [PASS] 两次调用无异常")

    import psycopg2

    conn = psycopg2.connect(PG_DSN)
    cur = conn.cursor()
    for t in ["strategy", "strategy_instance", "strategy_signal", "strategy_scan_cursor"]:
        cur.execute("SELECT to_regclass(%s)", (t,))
        check(f"{t} 表存在", cur.fetchone()[0] is not None)
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='monitor' AND column_name='source_type'"
    )
    check("monitor.source_type 列存在", cur.fetchone() is not None)
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='monitor' AND column_name='instance_id'"
    )
    check("monitor.instance_id 列存在", cur.fetchone() is not None)
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='monitor' AND column_name='signal_date'"
    )
    check("monitor.signal_date 列存在", cur.fetchone() is not None)
    conn.close()

    print("== 2. 注册表与 params 校验 ==")
    d = get_definition("vol_breakout_pullback")
    check("定义存在", d is not None and d.id == "vol_breakout_pullback")
    check("states 4 态", [s["value"] for s in d.states] == ["watching", "triggered", "expired", "running"])
    check("columns 3 列", [c["key"] for c in d.columns] == ["first_board_date", "pullback_days", "volume_ratio"])
    _, errs = validate_params(d, {"pullback_max_days": 0})
    check("非法参数 pullback_max_days=0 被拒", len(errs) > 0, f"errs={errs}")
    _, errs = validate_params(d, {"unknown_param": 1})
    check("未知参数被拒", len(errs) > 0, f"errs={errs}")
    norm, errs = validate_params(d, None)
    check("缺省参数取默认值", errs == [] and norm["pullback_max_days"] == 5 and norm["volume_ratio_min"] == 2.0)

    # 清理可能的历史冒烟遗留（同 label 实例）
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    conn.cursor().execute(
        "DELETE FROM strategy_instance WHERE label LIKE '冒烟%%'"
    )
    conn.close()

    print("== 3. 建实例 + 全量回算（真实 DuckDB） ==")
    try:
        ss.create_instance("vol_breakout_pullback", "冒烟实例", {"pullback_max_days": 0})
        check("非法参数建实例抛 ValueError", False)
    except ValueError as e:
        check("非法参数建实例抛 ValueError", "不能小于" in str(e), str(e))

    inst = ss.create_instance("vol_breakout_pullback", "冒烟实例-默认参数")
    check("默认参数建实例成功", inst is not None and inst["id"] > 0,
          f"id={inst['id']}, params={inst['params']}")
    instance_id = inst["id"]

    # 取 DuckDB 真实存在的日线 code
    from ChanAnalyse.DataAPI.KLineStore import KLineStore

    with KLineStore("Data/kl_store.duckdb", read_only=True) as store:
        rows = store.execute(
            "SELECT DISTINCT code FROM kline WHERE kl_type='K_DAY' ORDER BY code LIMIT 1"
        )
    if not rows:
        print("  [SKIP] DuckDB 无 K_DAY 数据，跳过扫描段")
    else:
        code = rows[0][0]
        result = scan_instance(instance_id, codes=[code])
        check("scan_instance 全量回算执行", result["scanned"] >= 1 and result["failed"] == [],
              f"code={code}, scanned={result['scanned']}, updated={result['updated']}")
        wm = ss.get_scan_cursor(instance_id, code)
        check("水位已写", wm is not None and len(wm) >= 10, f"watermark={wm}")

        page = ss.query_signals(instance_id, page=1, page_size=50)
        total_first = page["total"]
        check("查询契约字段齐全", set(page.keys()) == {"items", "total", "page", "page_size"},
              f"total={total_first}")
        if page["items"]:
            row = page["items"][0]
            check("行字段齐全", set(row.keys()) >= {
                "id", "code", "name", "signal_date", "state", "is_buy",
                "entry_ref_price", "stop_ref_price", "payload", "frozen"},
                  f"keys={sorted(row.keys())}")
            check("signal_date 格式 YYYY-MM-DD", len(row["signal_date"]) == 10, row["signal_date"])
            check("state 在定义域内", row["state"] in {"watching", "triggered", "expired", "running"},
                  row["state"])
            check("payload 含私有字段", "first_board_date" in row["payload"] and "volume_ratio" in row["payload"],
                  str(row["payload"]))
        # 信号数 > 0 或无信号均不报错（两种情况都合法）
        print(f"  [INFO] {code} 全量信号数 = {total_first}")

        # 二次 scan 幂等（信号数不变）
        result2 = scan_instance(instance_id, codes=[code])
        page2 = ss.query_signals(instance_id, page=1, page_size=50)
        check("二次 scan 幂等（信号数不变）", page2["total"] == total_first,
              f"first={total_first}, second={page2['total']}")
        check("二次 scan 无失败", result2["failed"] == [])

        # 筛选/分页字段验证
        page3 = ss.query_signals(instance_id, page=1, page_size=1)
        check("分页生效", page3["page_size"] == 1 and len(page3["items"]) <= 1,
              f"items={len(page3['items'])}, total={page3['total']}")
        states_seen = {it["state"] for it in page["items"]}
        if states_seen:
            st = list(states_seen)[0]
            page_f = ss.query_signals(instance_id, state=st)
            check("state 筛选生效", all(it["state"] == st for it in page_f["items"]) or page_f["total"] == 0,
                  f"state={st}, total={page_f['total']}")
        page_dir = ss.query_signals(instance_id, direction="buy")
        check("direction 筛选生效", all(it["is_buy"] for it in page_dir["items"]),
              f"total={page_dir['total']}")

        counts = ss.get_instance_signal_counts()
        check("按实例计数包含本实例", counts.get(instance_id) == total_first,
              f"counts={counts.get(instance_id)}")
        defs = ss.get_definitions_with_instances()
        dv = [x for x in defs if x["id"] == "vol_breakout_pullback"]
        check("definitions 树含实例+计数", dv and any(
            i["id"] == instance_id and i["signal_count"] == total_first
            for i in dv[0]["instances"]), f"tree={dv[0]['instances'] if dv else None}")

        print("== 4. upsert 冻结（design D8） ==")
        if page["items"]:
            sig = page["items"][0]
            ok = ss.freeze_signal(instance_id, sig["code"], sig["signal_date"])
            check("freeze_signal 命中", ok is True)
            # 冻结后再 upsert 同一信号（模拟 state 演进），state 不变
            ev = dict(sig)
            ev["state"] = "running" if sig["state"] != "running" else "triggered"
            ev["payload"] = sig["payload"]
            ss.upsert_signal(instance_id, ev)
            after = ss.query_signals(
                instance_id, state=ev["state"], page=1, page_size=100
            )
            check("frozen 行不被 upsert 更新",
                  all(it["code"] != sig["code"] for it in after["items"]),
                  f"state={sig['state']} 冻结后仍非 {ev['state']}")
            page_after = [it for it in ss.query_signals(instance_id, page=1, page_size=200)["items"]
                          if it["code"] == sig["code"]]
            check("frozen 标志已置位", page_after and page_after[0]["frozen"] is True)
        else:
            print("  [SKIP] 无信号，跳过冻结段")

        print("== 5. monitor strategy 来源（design D6/D8） ==")
        if page["items"]:
            sig = page["items"][0]
            entry = sig["entry_ref_price"] or 10.5
            m = ms.create_monitor(
                sig["code"], "K_DAY", entry, f"{sig['signal_date']} 00:00:00",
                source_type="strategy", instance_id=instance_id,
                signal_date=sig["signal_date"],
            )
            check("strategy 来源建监控成功", m is not None and m["id"] > 0,
                  f"monitor id={m['id']}")
            check("来源字段落库", m["source_type"] == "strategy"
                  and m["instance_id"] == instance_id
                  and m["signal_date"] == sig["signal_date"])

            # 信号已冻结（同事务置位）
            sigs = [it for it in ss.query_signals(instance_id, page=1, page_size=200)["items"]
                    if it["code"] == sig["code"]]
            check("加监控同事务冻结信号", sigs and sigs[0]["frozen"] is True)

            # _fill_bsp_context 走 strategy 路径
            items = ms.list_monitoring(keyword=sig["code"])
            mine = [it for it in items if it["id"] == m["id"]]
            check("list_monitoring 含 strategy 条目", len(mine) == 1)
            if mine:
                it = mine[0]
                check("上下文 bsp_type=state", it["bsp_type"] == sig["state"],
                      f"bsp_type={it['bsp_type']}, state={sig['state']}")
                check("上下文 direction=buy", it["direction"] == "buy")
                check("上下文 bsp_price=entry_ref", it.get("bsp_price") == sig["entry_ref_price"]
                      if sig["entry_ref_price"] else True,
                      f"bsp_price={it.get('bsp_price')}, entry_ref={sig['entry_ref_price']}")
            # 清理测试 monitor 行
            conn = psycopg2.connect(PG_DSN)
            conn.autocommit = True
            conn.cursor().execute("DELETE FROM monitor WHERE id = %s", (m["id"],))
            conn.close()
        else:
            print("  [SKIP] 无信号，跳过 monitor 来源段")

        print("== 6. 存量 monitor 兼容（chan 兜底） ==")
        conn = psycopg2.connect(PG_DSN)
        conn.autocommit = True
        c2 = conn.cursor()
        c2.execute(
            "SELECT source_type FROM monitor ORDER BY id DESC LIMIT 1"
        )
        conn.close()
        items = ms.list_monitoring()
        check("list_monitoring 正常返回（旧数据兜底 chan）", isinstance(items, list),
              f"count={len(items)}")
    # ---- skip 段结束 ----

    print("== 7. 清理：删除实例级联删信号 ==")
    conn = psycopg2.connect(PG_DSN)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM strategy_signal WHERE instance_id = %s", (instance_id,))
    before = cur.fetchone()[0]
    conn.close()
    ok = ss.delete_instance(instance_id)
    check("delete_instance 成功", ok is True)
    conn = psycopg2.connect(PG_DSN)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM strategy_signal WHERE instance_id = %s", (instance_id,))
    check("级联删信号无残留", cur.fetchone()[0] == 0, f"before={before}")
    cur.execute("SELECT COUNT(*) FROM strategy_scan_cursor WHERE instance_id = %s", (instance_id,))
    check("级联删游标无残留", cur.fetchone()[0] == 0)
    conn.close()
    check("删除后 get_instance 为 None", ss.get_instance(instance_id) is None)

    print(f"\n结果: PASS={PASS}, FAIL={FAIL}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(2)
