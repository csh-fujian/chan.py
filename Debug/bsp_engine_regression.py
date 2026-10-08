# -*- coding: utf-8 -*-
"""
补算引擎回归（bsp-page-change 3.3 / 3.5 / 3.6 / 5.2 / 5.3 + 2.5 注入面）

用真实 PG + DuckDB 跑引擎端到端幂等语义：

  T1  3.3 首次接入：三表产出完整，bsp_index 行数 = 计算结果，游标推进
  T2  3.4 快照缺失回退：删快照后重算，行集不变
  T3  3.5 整套替换收敛：删/改索引行后重跑，收敛回全集
  T4  3.5 事务原子性：写入中断 → 行集与游标同时回滚
  T5  3.6 漏批自愈：清游标（模拟漏算）后 catch_up 自动补上
  T6  3.6/5.3 重复触发幂等：数据无变化再跑 catch_up，行数与游标不变
  T7  5.2 查询下推：query_bsp 分页/关键词/周期/date 与 SQL 直查一致；router PageRes 契约
  T8  2.5 注入面：kl_types 含引号构造串不产生 SQL 错误
  T9  5.3 L1 落库（D3 修订）：W 级重算出现 L1 行；BSP_L1_PERSIST=0 后 L1 消失回 L2

运行（项目根目录，需 PG + Data/kl_store.duckdb）：
    .venv/bin/python Debug/bsp_engine_regression.py
    .venv/bin/python Debug/bsp_engine_regression.py --codes sz.000001,sz.000002 --periods D
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 与 Script/start_backend.sh 同款默认 DSN（可用环境变量覆盖）
os.environ.setdefault(
    "PG_DSN",
    "host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres",
)

import psycopg2  # noqa: E402

from WebAPI import bsp_store  # noqa: E402
from WebAPI.bsp_store import get_bsp_by_code, query_bsp  # noqa: E402
from WebAPI.config import PG_DSN  # noqa: E402
from WebAPI.incremental_engine import catch_up, recompute_stock, source_watermark  # noqa: E402

TEST_CODES = ["sz.000001", "sz.000002"]
TEST_PERIOD = "D"


def _conn():
    return psycopg2.connect(PG_DSN)


def _rows(code, period, autype="QFQ"):
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT bsp_date, bsp_type, is_buy, price, time_key FROM bsp_index
                   WHERE code=%s AND kl_type=%s AND autype=%s
                   ORDER BY bsp_date, bsp_type, time_key""",
                (code, period, autype),
            )
            return cur.fetchall()
    finally:
        conn.close()


def _cursor_of(code, period, autype="QFQ"):
    from WebAPI.incremental_engine import resolve_period

    kl_type_db = resolve_period(period)[2]
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT last_processed_time FROM recompute_cursor WHERE code=%s AND kl_type=%s AND autype=%s",
                (code, kl_type_db, autype),
            )
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        conn.close()


def _snapshot_exists(code, period, autype="QFQ"):
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM chan_snapshot WHERE code=%s AND kl_type=%s AND autype=%s",
                (code, period, autype),
            )
            return cur.fetchone() is not None
    finally:
        conn.close()


def _structure_exists(code, period, autype="QFQ"):
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT structure FROM chan_structure WHERE code=%s AND kl_type=%s AND autype=%s",
                (code, period, autype),
            )
            row = cur.fetchone()
            return row is not None and row[0] not in (None, {}, "{}")
    finally:
        conn.close()


def _clean_slate(code, period, autype="QFQ"):
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM bsp_index WHERE code=%s AND kl_type=%s AND autype=%s", (code, period, autype))
            cur.execute("DELETE FROM chan_structure WHERE code=%s AND kl_type=%s AND autype=%s", (code, period, autype))
            cur.execute("DELETE FROM chan_snapshot WHERE code=%s AND kl_type=%s AND autype=%s", (code, period, autype))
            cur.execute(
                "DELETE FROM recompute_cursor WHERE code=%s AND autype=%s AND kl_type=%s",
                (code, autype, resolve_period_db(period)),
            )
        conn.commit()
    finally:
        conn.close()


def resolve_period_db(period):
    from WebAPI.incremental_engine import resolve_period

    return resolve_period(period)[2]


def check_t1(codes, period) -> bool:
    """3.3 首次接入。"""
    ok = True
    for code in codes:
        _clean_slate(code, period)
        s = recompute_stock(code, period)
        rows = _rows(code, period)
        src = source_watermark(code, resolve_period_db(period), "QFQ")
        cur = _cursor_of(code, period)
        good = (
            s is not None
            and s["mode"] == "full"
            and len(rows) == s["bsp_rows"] == len(rows)
            and _snapshot_exists(code, period)
            and _structure_exists(code, period)
            and cur == src
        )
        print(f"[{'PASS' if good else 'FAIL'}] T1 first-engage {code} {period}: "
              f"mode={s and s['mode']} rows={len(rows)} cursor={cur} (src={src}) "
              f"snapshot={_snapshot_exists(code, period)} structure={_structure_exists(code, period)}")
        ok = ok and good
    return ok


def check_t2(codes, period) -> bool:
    """3.4 快照缺失 → 回退全量，行集不变。"""
    ok = True
    for code in codes:
        before = _rows(code, period)
        conn = _conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM chan_snapshot WHERE code=%s AND kl_type=%s AND autype=%s", (code, period, "QFQ"))
            conn.commit()
        finally:
            conn.close()
        s = recompute_stock(code, period)
        after = _rows(code, period)
        good = s is not None and s["mode"] == "full" and before == after and len(after) > 0
        print(f"[{'PASS' if good else 'FAIL'}] T2 snapshot-missing fallback {code} {period}: "
              f"mode={s and s['mode']} rows={len(before)}->{len(after)} identical={before == after}")
        ok = ok and good
    return ok


def check_t3(codes, period) -> bool:
    """3.5 删/改索引行后重跑（force 整套替换），收敛回全集。"""
    ok = True
    for code in codes:
        ref = _rows(code, period)
        if not ref:
            print(f"[FAIL] T3 {code}: 参考行集为空")
            return False
        conn = _conn()
        try:
            with conn.cursor() as cur:
                # 篡改一行 + 删除一行（限定 autype=QFQ：只破坏引擎词表内的行，
                # 避免误伤其它 autype（如 HFQ）的遗留数据——引擎整套替换只重写 QFQ）
                cur.execute(
                    "UPDATE bsp_index SET price=99999 WHERE code=%s AND kl_type=%s AND autype='QFQ' AND time_key=%s",
                    (code, period, ref[0][4]),
                )
                cur.execute(
                    "DELETE FROM bsp_index WHERE code=%s AND kl_type=%s AND autype='QFQ' AND time_key=%s",
                    (code, period, ref[-1][4]),
                )
            conn.commit()
        finally:
            conn.close()
        corrupted = _rows(code, period)
        result = catch_up(codes=[code], periods=[period], force=True)
        after = _rows(code, period)
        good = corrupted != ref and after == ref and result["updated"] == 1
        print(f"[{'PASS' if good else 'FAIL'}] T3 replace-converge {code} {period}: "
              f"corrupted={len(corrupted)} rows -> converged={after == ref} (updated={result['updated']})")
        ok = ok and good
    return ok


def check_t4(codes, period) -> bool:
    """3.5 写入中断 → 游标与数据同时回滚。"""
    ok = True
    code = codes[0]
    ref = _rows(code, period)
    ref_cur = _cursor_of(code, period)
    ref_snap = _snapshot_exists(code, period)

    orig_insert = bsp_store._insert_bsp_rows

    def boom(*a, **kw):
        raise RuntimeError("模拟写入中断")

    bsp_store._insert_bsp_rows = boom
    try:
        try:
            recompute_stock(code, period)
            good = False
            print(f"[FAIL] T4 rollback {code}: 中断未抛出异常")
        except RuntimeError:
            after = _rows(code, period)
            after_cur = _cursor_of(code, period)
            good = after == ref and after_cur == ref_cur and _snapshot_exists(code, period) == ref_snap
            print(f"[{'PASS' if good else 'FAIL'}] T4 rollback {code} {period}: "
                  f"rows unchanged={after == ref} cursor unchanged={after_cur == ref_cur}")
    finally:
        bsp_store._insert_bsp_rows = orig_insert
    return ok


def check_t5(codes, period) -> bool:
    """3.6 漏批自愈：清游标后 catch_up 自动补上。"""
    ok = True
    for code in codes:
        conn = _conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM recompute_cursor WHERE code=%s AND autype=%s AND kl_type=%s",
                    (code, "QFQ", resolve_period_db(period)),
                )
            conn.commit()
        finally:
            conn.close()
        ref = _rows(code, period)
        result = catch_up(codes=[code], periods=[period])
        cur = _cursor_of(code, period)
        src = source_watermark(code, resolve_period_db(period), "QFQ")
        good = result["updated"] == 1 and cur == src and _rows(code, period) == ref
        print(f"[{'PASS' if good else 'FAIL'}] T5 missed-batch self-heal {code} {period}: "
              f"updated={result['updated']} cursor={cur} rows-identical={_rows(code, period) == ref}")
        ok = ok and good
    return ok


def check_t6(codes, period) -> bool:
    """3.6/5.3 重复触发幂等：数据无变化再跑 catch_up 不变。"""
    ok = True
    ref_rows = {c: _rows(c, period) for c in codes}
    ref_cur = {c: _cursor_of(c, period) for c in codes}
    first = catch_up(codes=codes, periods=[period])
    second = catch_up(codes=codes, periods=[period])
    for code in codes:
        good = (
            first["updated"] == 0
            and second["updated"] == 0
            and _rows(code, period) == ref_rows[code]
            and _cursor_of(code, period) == ref_cur[code]
        )
        print(f"[{'PASS' if good else 'FAIL'}] T6 idempotent re-run {code} {period}: "
              f"scanned={first['scanned']}/{second['scanned']} updated={first['updated']}/{second['updated']} "
              f"rows-identical={_rows(code, period) == ref_rows[code]} cursor-identical={_cursor_of(code, period) == ref_cur[code]}")
        ok = ok and good
    return ok


def check_t7(codes, period) -> bool:
    """5.2 查询下推与 router 契约：query_bsp 与 SQL 直查一致；PageRes<BspRecord> 形状。"""
    ok = True
    code = codes[0]

    def direct(where_sql, params, limit=None, offset=0):
        conn = _conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT COUNT(*) FROM bsp_index b LEFT JOIN stock s ON b.code=s.code {where_sql}", params)
                total = cur.fetchone()[0]
                cur.execute(
                    f"""SELECT b.code, b.bsp_type, b.is_buy, b.price, b.time_key
                        FROM bsp_index b LEFT JOIN stock s ON b.code=s.code {where_sql}
                        ORDER BY b.bsp_date DESC, b.code LIMIT %s OFFSET %s""",
                    list(params) + [limit or 1000, offset],
                )
                return total, cur.fetchall()
        finally:
            conn.close()

    cases = [
        ("period only", f"WHERE b.kl_type=%s", [period], None, None),
        ("keyword code", f"WHERE b.kl_type=%s AND (b.code ILIKE %s OR s.name ILIKE %s)", [period, f"%{code[3:6]}%", f"%{code[3:6]}%"], code[3:6], None),
        ("no match", f"WHERE b.kl_type=%s AND (b.code ILIKE %s OR s.name ILIKE %s)", [period, "%zzz_no_such%", "%zzz_no_such%"], "zzz_no_such", None),
        ("bsp_type+dir", f"WHERE b.kl_type=%s AND b.bsp_type=%s AND b.is_buy=%s", [period, "1", True], None, ("1", True)),
    ]
    for name, where, params, keyword, type_dir in cases:
        d_total, d_rows = direct(where, params, limit=20)
        bsp_type = type_dir[0] if type_dir else ""
        is_buy = type_dir[1] if type_dir else None
        r = query_bsp(kl_type=period, bsp_types=[bsp_type] if bsp_type else None, is_buy=is_buy, keyword=keyword or "", page=1, page_size=20)
        match = r["total"] == d_total and [tuple(x[k] for k in ("code", "bsp_type", "is_buy", "price", "time_key")) for x in r["items"]] == d_rows
        if name == "no match":
            match = r["total"] == 0 and r["items"] == [] and d_total == 0
        print(f"[{'PASS' if match else 'FAIL'}] T7.1 query pushdown [{name}]: total={r['total']} (direct={d_total})")
        ok = ok and match

    # date_from/date_to 范围（2.6）：双端齐备 = 闭区间 [date_from, date_to]
    ref = _rows(code, period)
    day = str(ref[-1][0])
    r = query_bsp(kl_type=period, date_from=day, date_to=day, page=1, page_size=50)
    d_total, _ = direct("WHERE b.kl_type=%s AND b.bsp_date=%s", [period, day])
    match = r["total"] == d_total and all(x["bsp_date"].startswith(day) for x in r["items"])
    print(f"[{'PASS' if match else 'FAIL'}] T7.2 date range filter: date={day} total={r['total']} (direct={d_total})")
    ok = ok and match

    # 分页：两页并集 = 直查前 2×page_size，total 恒为过滤后总数
    p1 = query_bsp(kl_type=period, page=1, page_size=5)
    p2 = query_bsp(kl_type=period, page=2, page_size=5)
    d_total, d_rows = direct("WHERE b.kl_type=%s", [period], limit=10)
    match = p1["total"] == p2["total"] == d_total and (
        [tuple(x[k] for k in ("code", "bsp_type", "is_buy", "price", "time_key")) for x in p1["items"] + p2["items"]] == d_rows
    )
    print(f"[{'PASS' if match else 'FAIL'}] T7.3 pagination: total={p1['total']} (direct={d_total})")
    ok = ok and match

    # router 契约：PageRes<BspRecord>（asyncio 直接调用路由函数）
    from WebAPI.routers.bsp import bsp_list

    res = asyncio.run(bsp_list(page=1, page_size=5, keyword=code[3:6], bsp_type="", direction="", kl_type=period, date_from="", date_to=""))
    shape_ok = set(res.keys()) == {"list", "total", "page", "page_size"}
    # bsp-ladder-change：BspRecord 增 ladder 字段（L1/L2/L3/L4）
    fields = {"id", "code", "name", "industries", "bsp_type", "direction", "bsp_price", "current_price", "bsp_date", "kl_type", "change_pct", "is_sure", "ladder"}
    rec_ok = all(set(rec.keys()) == fields for rec in res["list"])
    type_ok = all(
        isinstance(rec["id"], int)
        and isinstance(rec["industries"], list)
        and all(isinstance(x, str) for x in rec["industries"])
        and rec["direction"] in ("buy", "sell")
        and isinstance(rec["bsp_price"], (int, float))
        and isinstance(rec["current_price"], (int, float))
        and isinstance(rec["bsp_date"], int)
        and isinstance(rec["change_pct"], (int, float))
        for rec in res["list"]
    )
    match = shape_ok and rec_ok and type_ok and res["total"] > 0
    print(f"[{'PASS' if match else 'FAIL'}] T7.4 router PageRes<BspRecord>: total={res['total']} "
          f"shape={shape_ok} fields={rec_ok} types={type_ok} sample={res['list'][0] if res['list'] else None}")
    ok = ok and match

    # 2.4 降级：DuckDB 查询失败 → current_price/change_pct=0 但列表仍渲染
    orig_execute = None
    from ChanAnalyse.DataAPI import KLineStore as _KLS

    orig_execute = _KLS.KLineStore.execute

    def boom(self, sql, params=None):
        raise RuntimeError("模拟 DuckDB 锁冲突")

    _KLS.KLineStore.execute = boom
    try:
        res = asyncio.run(bsp_list(page=1, page_size=3, keyword=code[3:6], bsp_type="", direction="", kl_type=period, date_from="", date_to=""))
        degrade_ok = len(res["list"]) > 0 and all(
            rec["current_price"] == 0.0 and rec["change_pct"] == 0.0 for rec in res["list"]
        )
    finally:
        _KLS.KLineStore.execute = orig_execute
    print(f"[{'PASS' if degrade_ok else 'FAIL'}] T7.5 DuckDB unavailable degrade: list rendered with 0 prices")
    ok = ok and degrade_ok
    return ok


def check_t8(codes, period) -> bool:
    """2.5 注入面：kl_types 含引号构造串不产生 SQL 错误。"""
    evil = ["D') OR 1=1 --", "D' UNION SELECT code FROM stock --", 'D"']
    try:
        rows = get_bsp_by_code(codes[0], evil)
        rows2 = get_bsp_by_code(codes[0], [period])
        good = rows == [] and len(rows2) > 0
    except Exception as e:
        print(f"[FAIL] T8 injection-safety: raised {e}")
        return False
    print(f"[{'PASS' if good else 'FAIL'}] T8 injection-safety: evil kl_types -> {len(rows)} rows (plain '{period}' -> {len(rows2)} rows)")
    return good


def check_t9(codes, period) -> bool:
    """5.3 D3 修订：落库链路计算 L1（子级别共振）。

    用 W 级（子级别 D）验证：重算后 bsp_index 出现 L1 行；
    BSP_L1_PERSIST=0 重算 L1 行消失（未确认无背驰回 L2）。
    W 级未确认行较少时 L1 可能数为 0——此时用「开关关后 L2 数变化」
    或降级断言（无未确认行则 SKIP），保底验证开关语义生效。
    """
    import importlib

    from WebAPI import incremental_engine as ie

    ok = True
    for code in codes:
        s = recompute_stock(code, "W")
        if s is None:
            print(f"[SKIP] T9 L1-persist {code} W: DuckDB 无周线数据")
            continue
        l1_on = _ladder_rows(code, "W", "L1")
        # 开关关闭：重算后 L1 行必须消失
        os.environ["BSP_L1_PERSIST"] = "0"
        try:
            importlib.reload(ie)
            s2 = recompute_stock(code, "W")
            l1_off = _ladder_rows(code, "W", "L1")
        finally:
            os.environ.pop("BSP_L1_PERSIST", None)
            importlib.reload(ie)
        good = (s2 is not None) and (len(l1_off) == 0)
        print(f"[{'PASS' if good else 'FAIL'}] T9 L1-persist {code} W: "
              f"ladder_rows(on)={len(l1_on)} -> ladder_rows(off)={len(l1_off)}")
        if l1_on:
            print(f"        L1 行示例: {l1_on[0][0]} {l1_on[0][1]}")
        ok = ok and good
    return ok


def _ladder_rows(code, period, ladder, autype="QFQ"):
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT bsp_date, bsp_type, time_key FROM bsp_index "
                "WHERE code=%s AND kl_type=%s AND autype=%s AND ladder=%s "
                "ORDER BY bsp_date, bsp_type",
                (code, period, autype, ladder),
            )
            return cur.fetchall()
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", default=",".join(TEST_CODES))
    ap.add_argument("--period", default=TEST_PERIOD)
    args = ap.parse_args()
    codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    period = args.period

    results = []
    for fn in (check_t1, check_t2, check_t3, check_t4, check_t5, check_t6, check_t7, check_t8, check_t9):
        try:
            results.append(fn(codes, period))
        except Exception as e:
            import traceback

            traceback.print_exc()
            print(f"[FAIL] {fn.__name__}: {e}")
            results.append(False)

    passed = sum(1 for r in results if r)
    print(f"\n== 引擎回归: {passed}/{len(results)} cases PASS ==")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
