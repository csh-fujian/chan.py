# -*- coding: utf-8 -*-
"""monitor-group-change 后端冒烟验证（任务组 1/2）。

直接调 monitor_store DAO（真实 PG，127.0.0.1:5432/chan），不触碰 settle/end/归因逻辑。
用后即删（临时验证脚本）。

运行: PYTHONPATH=. PG_DSN="host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres" \
      .venv/Scripts/python.exe Debug/monitor_group_smoke.py
"""

import sys
import traceback

sys.path.insert(0, ".")

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

    print("== 1. 建表幂等：连续 _ensure_tables 两次 ==")
    ms._ensure_tables()
    ms._ensure_tables()
    print("  [PASS] 两次调用无异常")

    import psycopg2

    conn = psycopg2.connect("host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres")
    cur = conn.cursor()
    cur.execute("SELECT to_regclass('monitor_group')")
    check("monitor_group 表存在", cur.fetchone()[0] is not None)
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='monitor' AND column_name='group_id'"
    )
    check("monitor.group_id 列存在", cur.fetchone() is not None)
    # FK ON DELETE SET NULL 确认
    cur.execute(
        """
        SELECT confdeltype FROM pg_constraint
        WHERE conrelid = 'monitor'::regclass AND conname LIKE '%group_id%'
        """
    )
    row = cur.fetchone()
    # pg_constraint.confdeltype: a=NO ACTION, c=CASCADE, n=SET NULL, r=RESTRICT
    check("FK ON DELETE SET NULL", row is not None and row[0] == "n", f"confdeltype={row[0] if row else None}")
    conn.close()

    # 清理冒烟遗留数据（分组表，不动 monitor 既有记录）
    conn = psycopg2.connect("host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres")
    conn.autocommit = True
    conn.cursor().execute("DELETE FROM monitor_group")
    conn.close()

    print("== 2. 分组 DAO 全生命周期 ==")
    g1 = ms.create_group(" 冒烟组A ")
    check("create_group 去空白建组", g1 is not None and g1["name"] == "冒烟组A", f"id={g1['id']}, sort={g1['sort_order']}")
    g2 = ms.create_group("冒烟组B")
    check("第二个组 sort_order 追加末尾", g2["sort_order"] == g1["sort_order"] + 1)

    groups = ms.list_groups()
    check("list_groups 返回 2 组", len(groups) == 2, f"{[(g['name'], g['sort_order']) for g in groups]}")
    check("list_groups 含计数字段", all("monitoring_count" in g and "completed_count" in g for g in groups))

    ok = ms.rename_group(g1["id"], "冒烟组A改")
    check("rename_group 成功", ok is True)
    check("rename 后名称生效", ms.get_group(g1["id"])["name"] == "冒烟组A改")

    ok = ms.reorder_groups([g2["id"], g1["id"]])
    check("reorder_groups 成功", ok is True)
    groups = ms.list_groups()
    check("reorder 后顺序 = [B, A]", [g["name"] for g in groups] == ["冒烟组B", "冒烟组A改"],
          f"排序: {[(g['name'], g['sort_order']) for g in groups]}")

    print("== 3. 名称查重 ==")
    check("重名 create 返回 None", ms.create_group("冒烟组B") is None)
    check("空名 create 返回 None", ms.create_group("   ") is None)
    check("重名 rename 返回 False", ms.rename_group(g1["id"], "冒烟组B") is False)
    check("不存在的分组 rename 返回 False", ms.rename_group(99999, "随便") is False)

    print("== 4. create_monitor 带/不带 group_id ==")
    m1 = ms.create_monitor("sz.000001", "K_DAY", 10.5, "2024-01-01 00:00:00", group_id=g1["id"])
    check("带 group_id 创建成功", m1 is not None and m1["id"] > 0, f"monitor id={m1['id']}")
    m2 = ms.create_monitor("sz.000002", "K_DAY", 12.5, "2024-01-02 00:00:00")
    check("不带 group_id 创建成功", m2 is not None)

    conn = psycopg2.connect("host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres")
    cur = conn.cursor()
    cur.execute("SELECT group_id FROM monitor WHERE id=%s", (m1["id"],))
    check("m1.group_id 正确落库", cur.fetchone()[0] == g1["id"])
    cur.execute("SELECT group_id FROM monitor WHERE id=%s", (m2["id"],))
    check("m2.group_id 为 NULL", cur.fetchone()[0] is None)
    conn.close()

    # 计数验证
    groups = ms.list_groups()
    ga = [g for g in groups if g["id"] == g1["id"]][0]
    check("list_groups 计数=1", ga["monitoring_count"] == 1 and ga["completed_count"] == 0,
          f"monitoring={ga['monitoring_count']}, completed={ga['completed_count']}")

    print("== 5. list_monitoring 三种 group_id 形态 ==")
    all_items = ms.list_monitoring()
    ga_items = ms.list_monitoring(group_id=g1["id"])
    ungrouped_items = ms.list_monitoring(group_id="ungrouped")
    check("缺省不过滤（含组内+未分组+存量 NULL）", len(all_items) >= len(ga_items) + len(ungrouped_items),
          f"all={len(all_items)}, groupA={len(ga_items)}, ungrouped={len(ungrouped_items)}")
    check("数值过滤只含组 A 记录", {it["id"] for it in ga_items} == {m1["id"]},
          f"ids={[it['id'] for it in ga_items]}")
    check("ungrouped 不含组 A 记录", m1["id"] not in {it["id"] for it in ungrouped_items})
    check("m2 在 ungrouped 中", m2["id"] in {it["id"] for it in ungrouped_items})

    print("== 6. list_completed 三种形态（构造一条已完成记录） ==")
    conn = psycopg2.connect("host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres")
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(
        "UPDATE monitor SET status='completed', sold_price=11, pnl_pct=4.76 WHERE id=%s",
        (m1["id"],),
    )
    conn.close()

    comp_all = ms.list_completed()
    comp_ga = ms.list_completed(group_id=g1["id"])
    comp_ung = ms.list_completed(group_id="ungrouped")
    check("completed 数值过滤含 m1", m1["id"] in {it["id"] for it in comp_ga},
          f"groupA completed={[it['id'] for it in comp_ga]}")
    check("completed ungrouped 不含 m1", m1["id"] not in {it["id"] for it in comp_ung},
          f"ungrouped completed={len(comp_ung)} 条")
    check("completed 缺省含 m1", m1["id"] in {it["id"] for it in comp_all}, f"all completed={len(comp_all)} 条")

    print("== 7. delete_group：组内记录 group_id 置 NULL ==")
    ok = ms.delete_group(g1["id"])
    check("delete_group 成功", ok is True)
    conn = psycopg2.connect("host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres")
    cur = conn.cursor()
    cur.execute("SELECT group_id FROM monitor WHERE id=%s", (m1["id"],))
    check("删除后 m1.group_id 为 NULL", cur.fetchone()[0] is None)
    conn.close()
    check("删除不存在分组返回 False", ms.delete_group(99999) is False)

    print("== 8. 路由层 _parse_group_id_param 校验 ==")
    from WebAPI.routers import monitor as mr
    from fastapi import HTTPException

    for valid in ["ungrouped", "1", "42"]:
        check(f"'{valid}' 通过", mr._parse_group_id_param(valid) == valid)
    for invalid in ["0", "-1", "abc", "1.5", " Ungrouped "]:
        try:
            mr._parse_group_id_param(invalid)
            check(f"'{invalid}' 应被拒绝", False)
        except HTTPException as e:
            check(f"'{invalid}' 被拒 422", e.status_code == 422)

    # 清理冒烟数据
    conn = psycopg2.connect("host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres")
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("DELETE FROM monitor WHERE id IN (%s, %s)", (m1["id"], m2["id"]))
    cur.execute("DELETE FROM monitor_group")
    conn.close()
    print("== 冒烟数据已清理 ==")

    print(f"\n结果: PASS={PASS}, FAIL={FAIL}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(2)
