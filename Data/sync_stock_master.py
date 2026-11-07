#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票主数据回填：DuckDB 已灌 K 线的标的 → PG `stock` 表。

职责（交互性修复）：
K 线页搜索下拉走 `GET /api/stocks` → `stock_store.list_stocks()`（读 PG `stock` 表），
而灌数链路（`Data/download_kl.py`）只写 DuckDB。新灌的标的若不在 PG 里，
DuckDB 能算出 K 线，但搜索下拉搜不到 —— 本脚本补上这一步。

数据来源：
- 标的集合（灌了哪些）：DuckDB `kline` 表的 `distinct code`，附带各自的 kl_type/autype；
- 名称/上市日/类型：BaoStock `query_stock_basic`（指数也能查到，stock_type=2）。

写入语义：
- 行不存在 → 新建（`ensure_stock_row`）；
- 行已存在 → **不覆盖**身份字段，只把 kl_types/autypes 做幂等并集（`sync_kl_types`）。
  个股身份（名称/板块/行业）的真源是 meta_sync 的 identity 域，不能被灌数链路反向覆盖。
- 指数写入 `board='指数'`，并被 `list_pool_codes(exclude_index=True)` 排除在逐股
  元数据域之外（指数没有巨潮档案/财务三表/股东户数）。

用法示例：
    PYTHONPATH=. python Data/sync_stock_master.py                  # 全量回填 DuckDB 内全部标的
    PYTHONPATH=. python Data/sync_stock_master.py --dry-run        # 只打印将要写入什么
    PYTHONPATH=. python Data/sync_stock_master.py --code sh.000001 # 只处理指定代码
    PYTHONPATH=. python Data/sync_stock_master.py --no-baostock    # 不联网，名称留空

环境要求：PG_DSN（如 host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres）。
"""

import argparse
import logging
import os
import sys
from datetime import datetime

# 允许直接运行本脚本（免 PYTHONPATH）
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from ChanAnalyse.DataAPI.KLineStore import DEFAULT_DB_PATH, KLineStore

log = logging.getLogger("sync_stock_master")

# 交易所前缀 → stock.exchange 取值（与 meta_sync.EXCHANGE_* 一致）
_EXCHANGE_NAME = {"sh": "上交所", "sz": "深交所", "bj": "北交所"}

# 代码前缀 → 板块。与 Data/gen_stock_list.py 的 _A_SHARE_PREFIX 语义一致，
# 另加指数（由 stock_store.is_index_code 判定，优先于本表）。
_BOARD_PREFIX = {
    "sh": (("600", "主板"), ("601", "主板"), ("603", "主板"), ("605", "主板"),
           ("688", "科创板"), ("689", "科创板")),
    "sz": (("000", "主板"), ("001", "主板"), ("002", "主板"), ("003", "主板"),
           ("300", "创业板"), ("301", "创业板"), ("302", "创业板")),
    "bj": (("", "北交所"),),  # 北交所前缀内均为股票
}


def exchange_of(code: str) -> str:
    """code 前缀 → 交易所中文名；无法识别返回空串。"""
    return _EXCHANGE_NAME.get(code.split(".", 1)[0].lower(), "")


def board_of(code: str) -> str:
    """code → 板块名；指数返回 '指数'，无法识别返回空串。"""
    from WebAPI.stock_store import INDEX_BOARD, is_index_code

    if is_index_code(code):
        return INDEX_BOARD
    exch, _, num = code.partition(".")
    for prefix, board in _BOARD_PREFIX.get(exch.lower(), ()):
        if not prefix or num.startswith(prefix):
            return board
    return ""


# BaoStock 返回的指数名称带口径后缀，如
#   「深证成份指数(价格)」「创业板指数(价格)」「上证50指数」
# 搜索场景下这些后缀只是噪声（用户搜「深证成指」「创业板指」）。逐条精确替换而非
# 正则模糊删除：后缀形态是有限的已知集合，模糊删会误伤真实基金/B股名称里的括号。
_INDEX_NAME_SUFFIXES = ("(价格)", "（价格）", "(全收益)", "（全收益）")

# 交易所口径的简称 → 搜索友好的名称（BaoStock 全称太长，用户实际按简称搜）
_INDEX_NAME_ALIAS = {
    "sh.000001": "上证指数",
    "sh.000010": "上证180",
    "sh.000016": "上证50",
    "sh.000300": "沪深300",
    "sh.000852": "中证1000",
    "sh.000905": "中证500",
    "sh.000688": "科创50",
    "sh.000015": "上证红利",
    "sz.399001": "深证成指",
    "sz.399006": "创业板指",
    "sz.399005": "中小100",
    "sz.399004": "深证100",
    "sz.399008": "中小300",
    "sz.399673": "创业板50",
    "bj.899050": "北证50",
}


def normalize_index_name(code: str, name: str) -> str:
    """把 BaoStock 指数全称规范成搜索友好名称。

    先取已知简称（_INDEX_NAME_ALIAS），否则剥掉口径后缀。空输入原样返回。
    """
    if not name:
        return name
    alias = _INDEX_NAME_ALIAS.get(code)
    if alias:
        return alias
    for suffix in _INDEX_NAME_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def list_duckdb_targets(db_path: str) -> dict[str, dict]:
    """返回 {code: {"kl_types": set, "autypes": set}}，取自 DuckDB kline 表。"""
    with KLineStore(db_path, read_only=True) as store:
        rows = store.execute(
            "SELECT DISTINCT code, kl_type, autype FROM kline ORDER BY code, kl_type, autype"
        )
    targets: dict[str, dict] = {}
    for code, kl_type, autype in rows:
        item = targets.setdefault(code, {"kl_types": set(), "autypes": set()})
        item["kl_types"].add(kl_type)
        item["autypes"].add(autype)
    return targets


def fetch_baostock_basics(codes: list[str]) -> dict[str, dict]:
    """从 BaoStock 批量取 {code: {name, ipo_date, is_index}}；失败返回空 dict。

    指数与个股都走 query_stock_basic（指数查到 stock_type='2'）。查不到的代码
    （如北证 899 系列、科创 000688）不进入返回值，由调用方回退到「名称=代码」。
    """
    if not codes:
        return {}
    try:
        import baostock as bs
    except ImportError:
        log.warning("baostock 未安装，跳过名称回填（名称将写为代码）")
        return {}

    out: dict[str, dict] = {}
    lg = bs.login()
    if getattr(lg, "error_code", "0") != "0":
        log.warning("BaoStock 登录失败：%s", getattr(lg, "error_msg", lg))
        return {}
    try:
        for code in codes:
            try:
                rs = bs.query_stock_basic(code=code)
                if rs.error_code != "0":
                    log.debug("[%s] query_stock_basic 失败：%s", code, rs.error_msg)
                    continue
                row = rs.get_row_data()
                if not row:
                    continue
                # 返回值：code, code_name, ipoDate, outDate, stock_type, status
                _code, code_name, ipo_date, _out_date, stock_type, _status = row
                out[code] = {
                    "name": code_name or "",
                    "ipo_date": ipo_date or None,
                    "is_index": stock_type == "2",
                }
            except Exception as e:
                log.debug("[%s] 取基本信息异常：%s", code, e)
    finally:
        try:
            bs.logout()
        except Exception:
            pass
    return out


def sync_one(
    code: str,
    kl_types: list[str],
    autypes: list[str],
    basics: dict,
    *,
    dry_run: bool = False,
) -> str:
    """同步单只标的主数据，返回 'created' | 'exists' | 'dry-run' | 'no-pg' | 'error'。"""
    from WebAPI import stock_store

    info = basics.get(code, {})
    name = info.get("name") or code
    board = board_of(code)
    # BaoStock 的 stock_type 是更权威的指数判据；本地前缀判定兜底（BaoStock 查不到时）
    if info.get("is_index") and board != stock_store.INDEX_BOARD:
        board = stock_store.INDEX_BOARD
    is_index = board == stock_store.INDEX_BOARD
    if is_index:
        name = normalize_index_name(code, name)

    if dry_run:
        print(
            f"[DRY] {code}\t{name}\t{exchange_of(code)}\t{board}\t"
            f"{sorted(kl_types)}\t{sorted(autypes)}"
        )
        return "dry-run"

    try:
        outcome = stock_store.ensure_stock_row(
            code=code,
            name=name,
            exchange=exchange_of(code),
            board=board,
            ipo_date=info.get("ipo_date"),
            kl_types=sorted(kl_types),
            autypes=sorted(autypes),
            # 指数被排除出 identity 域，BaoStock 是其名称唯一来源 → 允许修正；
            # 个股身份以 identity 域为真源，此处绝不覆盖
            overwrite_name=is_index,
        )
        if outcome in ("created", "exists"):
            # 已是「存在」时也要并集更新级别：先灌 K_DAY 后灌 K_5M 不应丢掉前者
            stock_store.sync_kl_types(code, sorted(kl_types), sorted(autypes))
        return outcome
    except Exception as e:
        log.error("[%s] 写 PG 失败：%s", code, e)
        return "error"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="把 DuckDB 已灌 K 线的标的回填到 PG stock 表（K 线页搜索下拉依赖）"
    )
    p.add_argument("--db-path", default=DEFAULT_DB_PATH, help="DuckDB 库路径")
    p.add_argument("--code", action="append", default=None,
                   help="只处理指定代码（可多次，如 sh.000001）")
    p.add_argument("--no-baostock", action="store_true",
                   help="不联网取名称/上市日（名称写为代码）")
    p.add_argument("--dry-run", action="store_true", help="只打印将写入的内容，不改库")
    p.add_argument("--verbose", action="store_true", help="打印 DEBUG 日志")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # 与 Script/sync_kl.sh、Data/download_kl.py 共用同一套「关闭」语义；
    # dry-run 不落库，无需 PG
    dsn = os.environ.get("PG_DSN", "").strip()
    if not args.dry_run and (not dsn or dsn.lower() in ("none", "off", "0")):
        print(
            "未配置 PG_DSN（或已设为 none），不会写入任何数据。请设置 PG_DSN，例如："
            "\n  set PG_DSN=host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres"
        )
        return 2

    targets = list_duckdb_targets(args.db_path)
    if args.code:
        wanted = [c.strip() for c in args.code if c.strip()]
        missing = [c for c in wanted if c not in targets]
        for c in missing:
            log.warning("[%s] DuckDB 内没有该标的的 K 线，跳过", c)
        targets = {c: targets[c] for c in wanted if c in targets}

    if not targets:
        print("DuckDB 内没有可同步的标的")
        return 1

    codes = sorted(targets)
    basics = {} if args.no_baostock else fetch_baostock_basics(codes)

    counts = {"created": 0, "exists": 0, "dry-run": 0, "no-pg": 0, "error": 0}
    for code in codes:
        outcome = sync_one(
            code,
            sorted(targets[code]["kl_types"]),
            sorted(targets[code]["autypes"]),
            basics,
            dry_run=args.dry_run,
        )
        counts[outcome] = counts.get(outcome, 0) + 1

    if counts.get("no-pg"):
        print(
            "PG 不可达（PG_DSN 未配置或连接失败），未写入任何数据。"
            "请设置 PG_DSN，例如："
            "\n  set PG_DSN=host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres"
        )
        return 1

    print(
        f"sync done: {len(codes)} 个标的 — "
        f"created={counts['created']} exists={counts['exists']} "
        f"dry-run={counts['dry-run']} error={counts['error']}"
    )
    return 0 if counts["error"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
