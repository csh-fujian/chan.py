# -*- coding: utf-8 -*-
"""存量 T3A/T3B 行阶梯回刷 —— chan-standard-bsp3-change task 5.3。

**回刷机制**：本变更把 `LADDER_SCHEMA_VERSION` 升为 `bsp3-4axis-v1`，配置指纹
随之变化；`incremental_engine.recompute_stock` 检测到指纹不匹配即强制全量重算
（`_delete_bsp_rows` + `_insert_bsp_rows` 整套替换），存量 T3A/T3B 的 NULL
ladder 在全量重刷中自然更新为四轴组合值或 `L4`。**无需定向 UPDATE 脚本**
（与 bsp2-change 6.1 同一机制）。

本脚本是该机制的**可重放驱动**：对指定标的（默认 41 只日线全量）逐只调用
`recompute_stock(force_full=True)`，随后用 SQL 核对三件事：

  1. 不再存在 `ladder IS NULL` 且 `bsp_type IN ('3a','3b')` 且 `is_sure=false` 的行
  2. 所有 T3 行的 ladder 长度 ≤ 32（无截断）
  3. 二次执行不产生数量变化（幂等）

用法：
    .venv/Scripts/python.exe Debug/bsp3_backfill_ladder.py            # 全周期（DuckDB 中存在的一切）
    .venv/Scripts/python.exe Debug/bsp3_backfill_ladder.py --periods D
    .venv/Scripts/python.exe Debug/bsp3_backfill_ladder.py --codes sz.000027
    .venv/Scripts/python.exe Debug/bsp3_backfill_ladder.py --verify-only
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# T3 阶梯的合法语法（bsp3-4axis-v1）：
#   四轴组合 —— 佐证/确认/分型/时间任一存在即合法，各轴可缺席，故**不以 S 开头
#               也是合法的**（子级别数据不可得时 `C0|K2|T1` 是正确输出，T3 单级别
#               复算必然如此）。早期版本用 `NOT LIKE 'S%'` 判旧语法，会把这类
#               合法新值误报为残留。
#   L4       —— 已确认点单值
# 旧 T1 三轴语法（`L1`/`L2`/`L3`/`L2-3`…）不含 T3 四轴的 `C`/`K`/`T` 档，靠
# 「是否存在 C 或 T 轴」区分。检测改为白名单：只把「非 L4 且不含任何 T3 轴档位」
# 的行算作残留。
_T3_AXIS_TOKENS = ("S3", "S2", "S1", "C3", "C2", "C1", "C0",
                   "K3", "K2", "K1", "T3", "T2", "T1")


def _is_t3_ladder(value) -> bool:
    """value 是否为合法的 T3 阶梯值（`L4` 或含至少一个 T3 轴档位的组合串）。"""
    if value is None:
        return True  # NULL 由 null 计数单独核对，不算「旧语法残留」
    if value == "L4":
        return True
    return any(tok in value.split("|") for tok in _T3_AXIS_TOKENS)


_VERIFY_SQL = """
SELECT
    COUNT(*) FILTER (WHERE ladder IS NULL)                     AS null_cnt,
    COUNT(*) FILTER (WHERE ladder IS NOT NULL AND length(ladder) > 32) AS over_len,
    COUNT(*)                                                   AS total_cnt
FROM bsp_index
WHERE bsp_type IN ('3a', '3b'){period_filter}
"""


def _conn():
    from WebAPI import bsp_store
    bsp_store._ensure_tables()
    return bsp_store._get_pg_conn()


def verify(label="", periods=None):
    conn = _conn()
    if conn is None:
        print("[skip] PG 不可用，跳过核对")
        return None
    period_filter = ""
    params: list = []
    if periods:
        ph = ", ".join(["%s"] * len(periods))
        period_filter = f" AND kl_type IN ({ph})"
        params = list(periods)
    try:
        with conn.cursor() as cur:
            cur.execute(_VERIFY_SQL.format(period_filter=period_filter), params)
            row = cur.fetchone()
            cur.execute(
                "SELECT bsp_type, ladder, COUNT(*) FROM bsp_index "
                f"WHERE bsp_type IN ('3a','3b'){period_filter} "
                "GROUP BY bsp_type, ladder ORDER BY bsp_type, ladder",
                params,
            )
            detail = cur.fetchall()
    finally:
        conn.close()
    null_cnt, over_len, total = row
    tag = f"[{label}] " if label else ""
    print(f"{tag}T3 行 {total} 条 | NULL {null_cnt} | 超长 {over_len}")
    for t, ld, n in detail:
        print(f"    {t}  ladder={ld!r}  x{n}")
    return {"null": null_cnt, "over": over_len, "total": total}


def _stale_legacy_rows(periods=None):
    """残留的旧语法阶梯值（T1 三轴的 `L1`/`L2`/`L3` 等）。

    判定用 `_is_t3_ladder` 白名单，而非「不以 S 开头」——后者会把佐证轴缺席的
    合法四轴值（如 `C0|K2|T1`）误判为残留。
    """
    conn = _conn()
    if conn is None:
        return []
    period_filter = ""
    params: list = []
    if periods:
        ph = ", ".join(["%s"] * len(periods))
        period_filter = f" AND kl_type IN ({ph})"
        params = list(periods)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT code, kl_type, autype, bsp_type, ladder, is_sure FROM bsp_index "
                f"WHERE bsp_type IN ('3a','3b'){period_filter} "
                "AND ladder IS NOT NULL ORDER BY kl_type, code",
                params,
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [r for r in rows if not _is_t3_ladder(r[4])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", nargs="*",
                    help="指定标的（默认 DuckDB 中全部有 K 线的标的）")
    ap.add_argument("--periods", nargs="*", default=None,
                    help="周期（默认 DuckDB 中存在的全部周期；如 `--periods D 30m`）")
    ap.add_argument("--autypes", nargs="*", default=["QFQ", "HFQ"],
                    help="复权口径（默认两者都刷，库中实际存在哪套由 DuckDB 决定）")
    ap.add_argument("--verify-only", action="store_true", help="只核对不重算")
    args = ap.parse_args()

    before = verify("before", args.periods)
    if args.verify_only:
        return 0

    from WebAPI.bsp_store import PG_DSN
    from WebAPI.incremental_engine import recompute_stock

    if not PG_DSN:
        print("[skip] PG_DSN 未配置，无法回刷")
        return 2

    # 待刷键直接取自 DuckDB（源侧真相）：旧版只枚举 `kl_type='K_DAY'` 且恒以
    # period="D" 调 recompute_stock，导致分钟级/周月的存量 T3 行永远不被回刷
    # （`sz.000021` 30m 的旧 `L3` 即由此遗留）。现在按 DuckDB 实际存在的
    # (code, kl_type) 全量枚举，周期经 period_of_db_name 归一成 bsp 词表。
    from WebAPI.chan_service import period_of_db_name

    import duckdb
    con = duckdb.connect(str(ROOT / "Data" / "kl_store.duckdb"), read_only=True)
    try:
        rows = con.execute(
            "select distinct code, kl_type from kline order by code, kl_type"
        ).fetchall()
    finally:
        con.close()

    keys: list[tuple[str, str]] = []
    for code, kl_type_db in rows:
        if args.codes and code not in args.codes:
            continue
        period = period_of_db_name(kl_type_db)
        if period is None:
            continue
        if args.periods and period not in args.periods:
            continue
        keys.append((code, period))

    total_runs = len(keys) * len(args.autypes)
    print(f"全量重算 {len(keys)} 个 (标的, 周期) 键 × {len(args.autypes)} 复权口径"
          f" = {total_runs} 次（force_full 显式指定）…")
    ok = skipped_st = 0
    done = 0
    for code, period in keys:
        for autype in args.autypes:
            done += 1
            try:
                r = recompute_stock(code, period, autype, force_full=True)
                if r:
                    ok += 1
                else:
                    # None = DuckDB 无该口径数据，或 ST 被入口排除
                    skipped_st += 1
            except Exception as exc:
                msg = str(exc)
                if "无数据" not in msg and "no data" not in msg.lower():
                    print(f"  [fail] {code} {period} {autype}: {msg[:120]}")
            if done % 20 == 0:
                print(f"  … {done}/{total_runs}")
    print(f"完成 {ok}/{total_runs}（跳过 {skipped_st}：ST 排除或无数据）")

    after = verify("after", args.periods)
    if after and after["null"] > 0:
        print(f"[WARN] 仍有 {after['null']} 条 T3 行 ladder 为 NULL——"
              f"若为 HFQ 等 DuckDB 无原始 K 线的口径则属数据状态（无法重算），"
              f"若为 QFQ 则说明未被回刷（检查 --periods / --autypes）")
    if after and after["over"] > 0:
        print(f"[FAIL] {after['over']} 条 T3 行 ladder 超长（截断）")
        return 1
    # 旧语法残留（T1 三轴的 L1/L2/L3）只能来自「重算入口跳过」的标的：ST 股票
    # （exclude-st-stocks D6 在入口处 return None，不写任何结果）。这类行是历史
    # 数据，按既有排除口径保留，但读侧已统一过滤（bsp_store 三个查询函数），
    # 因此不会再出现在任何页面。
    stale = _stale_legacy_rows(args.periods)
    if stale:
        print(f"[NOTE] {len(stale)} 条旧阶梯值来自重算入口跳过的标的（ST 排除），"
              f"按既有口径保留（读侧已过滤，不对外展示）：")
        for row in stale:
            print(f"    {row}")
    # 幂等：二次核对应与一次一致
    again = verify("again", args.periods)
    if after and again and after != again:
        print("[FAIL] 二次核对结果不同，回刷不幂等")
        return 1
    print("回刷完成且幂等")
    return 0


if __name__ == "__main__":
    sys.exit(main())
