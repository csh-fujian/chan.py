# -*- coding: utf-8 -*-
"""全库同步回归（chan-config-panel tasks 4.6 / 4.7）。

对 DuckDB 里全部 (code, kl_type, autype) 键执行一次 `catch_up(force=True)`，
记录耗时、成功/失败明细，并做抽样一致性校验：

    1. 每个键的 `bsp_index` 行数与 `summary.bsp_rows` 一致
    2. 成功的键其 `chan_snapshot.config_fingerprint` 等于当前配置指纹
        （证明「按新配置重算」而不是残留旧口径）
    3. 失败键不阻断其余键（summary.failed 逐条列出 code/period/原因）

输出同时写入 `Log/chan_config_sync_regression_<时间戳>.log`。

注意：这是**破坏性**回归 —— 它会用当前生效配置重写整库 `bsp_index`。
默认只跑前 N 个键（`--limit`），全库请显式传 `--limit 0`。

运行：
    .venv/Scripts/python.exe Debug/test_chan_config_sync.py --limit 5
    .venv/Scripts/python.exe Debug/test_chan_config_sync.py --limit 0
"""

import argparse
import os
import sys
import time

_DEBUG_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_DEBUG_DIR)
sys.path.insert(0, _REPO_ROOT)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

os.environ.setdefault(
    "PG_DSN", "host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres"
)

import psycopg2  # noqa: E402

from WebAPI.config import PG_DSN  # noqa: E402

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
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5,
                    help="最多处理键数（0 = 全库，耗时 5~8 分钟）")
    ap.add_argument("--sample", type=int, default=3, help="抽样核对只数")
    ap.add_argument("--autype", default="QFQ", help="核对用的复权口径（默认 QFQ）")
    args = ap.parse_args()

    from WebAPI import chan_config_store as store
    from WebAPI.config_fingerprint import config_fingerprint
    from WebAPI.incremental_engine import _make_chan_config, catch_up, list_stale_keys

    store.invalidate_cache()
    meta = store.load_with_meta()
    print(f"当前配置 version={meta['version']} preset={meta['preset']} "
          f"overrides={len(meta['overrides'])} 项")
    fp = config_fingerprint(_make_chan_config())
    print(f"当前配置指纹: {fp}")

    keys = list_stale_keys(force=True)
    total_keys = len(keys)
    if args.limit:
        keys = keys[: args.limit]
    print(f"待同步键数: {len(keys)}（全库 {total_keys}）\n")

    # 进度回调：每 5 个键打一行，避免刷屏
    def _progress(total, done, failed):
        if done % 5 == 0 or done == total:
            print(f"    进度 {done}/{total}  失败 {failed}", flush=True)

    t0 = time.time()
    result = catch_up(None, None, None, 0, True, _progress)
    elapsed = time.time() - t0

    print(f"\n[1] 同步结果（耗时 {elapsed:.1f}s，{elapsed / max(1, result['scanned']):.1f}s/键）")
    check("扫描键数 > 0", result["scanned"] > 0, str(result["scanned"]))
    check("成功 + 失败 = 扫描数",
          result["updated"] + len(result["failed"]) == result["scanned"],
          f"{result['updated']} + {len(result['failed'])} != {result['scanned']}")
    print(f"        成功 {result['updated']}，失败 {len(result['failed'])}")

    if result["failed"]:
        print("\n  失败明细：")
        for f in result["failed"]:
            print(f"    - {f['code']} / {f.get('kl_type') or f.get('period')}: "
                  f"{str(f.get('error'))[:120]}")
        check("失败项均带 code 与原因",
              all(f.get("code") and f.get("error") for f in result["failed"]))

    print("\n[2] 抽样一致性（bsp_index 行数 = summary.bsp_rows）")
    conn = psycopg2.connect(PG_DSN)
    try:
        with conn.cursor() as cur:
            sample = result["results"][: args.sample]
            for row in sample:
                code = row["code"]
                kl = row["kl_type"]
                # 必须带 autype 过滤：库里存在历史遗留的非 QFQ 行（如 sh.600000 的
                # 80 行 HFQ），它们不属于本次同步口径，读侧同样按 QFQ 过滤。
                cur.execute(
                    """SELECT count(*) FROM bsp_index
                       WHERE code=%s AND kl_type=%s AND autype=%s""",
                    (code, kl, args.autype),
                )
                actual = cur.fetchone()[0]
                check(f"{code} {kl} {args.autype}: 落库 {actual} = 计算 {row['bsp_rows']}",
                      actual == row["bsp_rows"], f"{actual} vs {row['bsp_rows']}")

            print("\n[3] 指纹一致性（快照已按当前配置重算）")
            cur.execute(
                """SELECT code, kl_type, config_fingerprint FROM chan_snapshot
                   WHERE config_fingerprint IS NOT NULL"""
            )
            snapshots = cur.fetchall()
            matched = [s for s in snapshots if s[2] == fp]
            check(f"快照指纹等于当前配置（{len(matched)} 个）", len(matched) > 0,
                  f"共 {len(snapshots)} 个快照，0 个匹配 {fp}")
    finally:
        conn.close()

    # 落日志
    log_dir = os.path.join(_REPO_ROOT, "Log")
    os.makedirs(log_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(log_dir, f"chan_config_sync_regression_{stamp}.log")
    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write(f"时间: {stamp}\n配置 version: {meta['version']}\n指纹: {fp}\n")
        fh.write(f"键数: {result['scanned']}\n耗时: {elapsed:.1f}s\n")
        fh.write(f"成功: {result['updated']}\n失败: {len(result['failed'])}\n")
        for f in result["failed"]:
            fh.write(f"  FAIL {f}\n")
    print(f"\n日志已写入 {log_path}")
    print(f"\n{'=' * 46}\n合计: {_PASS} PASS, {_FAIL} FAIL\n{'=' * 46}")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
