#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票元数据批量同步脚本：AKShare 多数据源分域拉取 → 幂等写入 PG（openspec 变更 stock-metadata-sync）。

职责：
- 分域同步：identity（交易所名单）/ profile（巨潮档案）/ industry（行业 M2M 降级）
  / snapshot（腾讯快照）/ financial（东财财务三表）/ holders（股东户数）。
- 断点续传：单元 = (code, domain)，成功即持久化水位；中断后重跑自动从未完成单元继续。
- 频率矩阵：identity/snapshot=1d、industry=7d、holders=15d、profile/financial=30d；
  --no-force 按水位增量执行，--force（默认）无视间隔强制刷新（仍走断点续传）。
- 失败隔离：单只标的失败不影响其余；failed 非空退出码 1。

用法示例：
    PYTHONPATH=. python Data/sync_stock_meta.py --domain identity
    PYTHONPATH=. python Data/sync_stock_meta.py --domain financial --no-force   # 全历史回填可断点续跑
    PYTHONPATH=. python Data/sync_stock_meta.py --code sz.000001               # 单只全域
    PYTHONPATH=. python Data/sync_stock_meta.py --loop                         # 常驻：每小时只跑到期域

环境要求：PG_DSN（如 postgresql://postgres:postgres@localhost:5432/chan）；
无需 PYTHONPATH（脚本开头自动把项目根插入 sys.path，上面示例中的 PYTHONPATH=. 可省略）；
环境存在 all_proxy=socks5://... 且未装 pysocks 时由 meta_sync 内部清代理变量处理。
"""

import argparse
import logging
import os
import sys
import time

# 允许直接运行本脚本（免 PYTHONPATH）：把项目根插入 sys.path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from WebAPI.config import PG_DSN
from WebAPI.meta_sync import DOMAINS, due_domains, sync

log = logging.getLogger("sync_stock_meta")

# 常驻循环的检查间隔（秒）
LOOP_INTERVAL_SECONDS = 3600


def print_summary(summary: dict) -> None:
    """打印汇总：created/updated/disabled/skipped/degraded + failed 前 N 条。"""
    failed = summary.get("failed", [])
    print(
        "sync summary: "
        f"created={summary.get('created', 0)} "
        f"updated={summary.get('updated', 0)} "
        f"disabled={summary.get('disabled', 0)} "
        f"skipped={summary.get('skipped', 0)} "
        f"degraded={summary.get('degraded', False)} "
        f"failed={len(failed)} "
        f"domains_run={summary.get('domains_run', [])}"
    )
    for item in failed[:10]:
        print(f"  [FAILED] {item[0]} / {item[1]}: {item[2]}")
    if len(failed) > 10:
        print(f"  ... and {len(failed) - 10} more failures")


def run_loop(args) -> int:
    """常驻循环：每小时醒来，只跑到期域（force=False），Ctrl+C 优雅退出。"""
    log.info(
        "loop mode: check due domains every %d s (domains=%s)",
        LOOP_INTERVAL_SECONDS,
        args.domain or "all",
    )
    try:
        while True:
            due = due_domains(domains=args.domain)
            if due:
                log.info("due domains: %s", due)
                summary = sync(
                    codes=args.code,
                    domains=due,
                    force=False,
                    sleep=args.sleep,
                    verbose=args.verbose,
                )
                print_summary(summary)
            else:
                log.info("no due domains, sleep %d s", LOOP_INTERVAL_SECONDS)
            time.sleep(LOOP_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        log.info("loop interrupted, exit")
        return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="同步股票多域元数据到 PG（AKShare 数据源）")
    p.add_argument(
        "--code",
        action="append",
        help="股票代码（可多次，如 sz.000001 / 000001 / SZ000001；缺省=全市场）",
    )
    p.add_argument(
        "--domain",
        action="append",
        choices=list(DOMAINS),
        help="同步域（可多次；缺省=全部）：identity/profile/industry/snapshot/financial/holders",
    )
    force_group = p.add_mutually_exclusive_group()
    force_group.add_argument(
        "--force",
        dest="force",
        action="store_true",
        default=True,
        help="无视到期间隔强制刷新（默认；仍走断点续传）",
    )
    force_group.add_argument(
        "--no-force",
        dest="force",
        action="store_false",
        help="按水位/间隔增量执行（未到期单元跳过且不发网络请求）",
    )
    p.add_argument(
        "--loop",
        action="store_true",
        help="常驻循环：每小时检查一次，只执行到期域（force=False）",
    )
    p.add_argument(
        "--sleep",
        type=float,
        default=0.4,
        help="逐股请求间隔秒数（限频保护，默认 0.4）",
    )
    p.add_argument("--verbose", action="store_true", help="打印 DEBUG 日志")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not PG_DSN:
        print(
            "ERROR: PG_DSN 未配置。请设置环境变量 PG_DSN，例如：\n"
            "  export PG_DSN='postgresql://postgres:postgres@localhost:5432/chan'",
            file=sys.stderr,
        )
        return 2

    if args.loop:
        return run_loop(args)

    summary = sync(
        codes=args.code,
        domains=args.domain,
        force=args.force,
        sleep=args.sleep,
        verbose=args.verbose,
    )
    print_summary(summary)
    return 1 if summary.get("failed") else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted: partial summary persisted to sync_job", file=sys.stderr)
        sys.exit(130)
