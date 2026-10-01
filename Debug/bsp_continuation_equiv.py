# -*- coding: utf-8 -*-
"""
增量续算等价性回归（bsp-page-change 3.4 / design D3 等价性硬门）

验证「pickle 快照 + trigger_load 续算 == 从头全量重算」：
同一股票、同一数据末端，两条路径产出的 bsp_index 行集（及已确认结构）完全一致。

覆盖：
  - 合成种子（内存构造 K 线，无需联网/PG/DuckDB）
  - 真实股票（DuckDB 只读，默认 sz.000001 日线 + sz.000002 日线）
  - 零新 K 线重入（续算批次为空时结果不变，幂等）

运行（项目根目录）：
    .venv/bin/python Debug/bsp_continuation_equiv.py
    .venv/bin/python Debug/bsp_continuation_equiv.py --codes sz.000001 --period D

任一 case 不一致 → 打印行集 diff 并以非零码退出。
"""

import argparse
import datetime
import os
import random
import sys

# 项目根目录入 sys.path（可从任意目录直接运行）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 本回归纯内存/只读 DuckDB，断开 PG（config 在 import 时读取 env）
os.environ["PG_DSN"] = ""

from ChanAnalyse.Common.CEnum import DATA_FIELD, KL_TYPE  # noqa: E402
from ChanAnalyse.Common.CTime import CTime  # noqa: E402
from ChanAnalyse.DataAPI.KLineStore import ctime_to_str  # noqa: E402
from ChanAnalyse.KLine.KLine_Unit import CKLine_Unit  # noqa: E402

from WebAPI.incremental_engine import (  # noqa: E402
    _dump_pickle_bytes,
    _extract_bsp_rows,
    _extract_structure,
    _load_klus,
    _load_pickle_chan,
    _make_chan,
    resolve_period,
)

SPLIT_RATIO = 0.65
AUTYPE = "QFQ"


def make_klu(year, month, day, o, h, l, c):
    """构造一根日线 CKLine_Unit（与 Debug/bi_test.py 同法）。"""
    return CKLine_Unit({
        DATA_FIELD.FIELD_TIME: CTime(year, month, day, 0, 0),
        DATA_FIELD.FIELD_OPEN: float(o),
        DATA_FIELD.FIELD_HIGH: float(h),
        DATA_FIELD.FIELD_LOW: float(l),
        DATA_FIELD.FIELD_CLOSE: float(c),
    })


def synth_klus(seed: int, n: int = 420):
    """合成种子：随机游走日线序列（每个 seed 可复现，独立构造避免共享对象状态）。"""
    rng = random.Random(seed)
    klus = []
    price = 10.0 + (seed % 7) * 3.0
    base = datetime.date(2020, 1, 1)
    prev_close = price
    for i in range(n):
        # 带趋势切换的随机游走，形成足够多顶底分型/笔/买卖点
        drift = rng.choice([-0.35, -0.2, -0.05, 0.05, 0.2, 0.35])
        close = max(1.0, prev_close + drift + rng.uniform(-0.4, 0.4))
        o = prev_close
        h = max(o, close) + rng.uniform(0.05, 0.5)
        l = min(o, close) - rng.uniform(0.05, 0.5)
        d = base + datetime.timedelta(days=i)
        klus.append(make_klu(d.year, d.month, d.day, o, h, l, close))
        prev_close = close
    return klus


def build_klus(code: str, kl_type, synthetic_seed: int | None = None):
    if synthetic_seed is not None:
        return synth_klus(synthetic_seed)
    return _load_klus(code, kl_type, AUTYPE)


def run_case(name: str, code: str, kl_type, synthetic_seed: int | None = None) -> bool:
    """单个等价性 case：全量 vs 续算（含 零新K线 重入）。"""
    klus_full = build_klus(code, kl_type, synthetic_seed)
    if len(klus_full) < 60:
        print(f"[SKIP] {name}: K 线过少 ({len(klus_full)})")
        return True

    # ---- 路径 A：从头全量重算（trigger_step=True + trigger_load 全量）----
    chan_full = _make_chan(code, kl_type, AUTYPE)
    chan_full.trigger_load({kl_type: klus_full})
    full_rows = _extract_bsp_rows(chan_full, kl_type)
    full_struct = _extract_structure(chan_full, kl_type)

    # ---- 路径 B：前段计算 → pickle 快照 → 恢复 → 仅喂新 K 线续算 ----
    klus_c = build_klus(code, kl_type, synthetic_seed)
    split = max(30, int(len(klus_c) * SPLIT_RATIO))
    cursor = ctime_to_str(klus_c[split - 1].time)

    chan_a = _make_chan(code, kl_type, AUTYPE)
    chan_a.trigger_load({kl_type: klus_c[:split]})
    blob = _dump_pickle_bytes(chan_a)

    chan_b = _load_pickle_chan(blob)
    new_klus = [k for k in klus_c[split:] if ctime_to_str(k.time) > cursor]
    chan_b.trigger_load({kl_type: new_klus})
    cont_rows = _extract_bsp_rows(chan_b, kl_type)
    cont_struct = _extract_structure(chan_b, kl_type)

    ok = True
    if full_rows != cont_rows:
        ok = False
        print(f"[FAIL] {name}: bsp 行集不一致 full={len(full_rows)} cont={len(cont_rows)}")
        only_full = [r for r in full_rows if r not in cont_rows]
        only_cont = [r for r in cont_rows if r not in full_rows]
        for r in only_full[:5]:
            print(f"    only-full: {r}")
        for r in only_cont[:5]:
            print(f"    only-cont: {r}")
    if full_struct != cont_struct:
        ok = False
        print(f"[FAIL] {name}: 已确认结构不一致 "
              f"(bi {len(full_struct['bi'])}/{len(cont_struct['bi'])}, "
              f"seg {len(full_struct['seg'])}/{len(cont_struct['seg'])}, "
              f"zs {len(full_struct['zs'])}/{len(cont_struct['zs'])})")

    # ---- 零新 K 线重入：再续算一次空批次，结果应不变（幂等）----
    chan_b.trigger_load({kl_type: []})
    again_rows = _extract_bsp_rows(chan_b, kl_type)
    if again_rows != cont_rows:
        ok = False
        print(f"[FAIL] {name}: 零新K线重入后行集变化 ({len(cont_rows)} -> {len(again_rows)})")

    if ok:
        print(f"[PASS] {name}: full={len(full_rows)} rows, cont={len(cont_rows)} rows, "
              f"split={split}/{len(klus_c)}, zero-new reentry OK")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="增量续算 == 全量重算 等价性回归")
    ap.add_argument("--codes", default="sz.000001,sz.000002", help="真实股票（逗号分隔）")
    ap.add_argument("--period", default="D", help="真实股票周期（bsp 词表）")
    ap.add_argument("--seeds", type=int, default=7, help="合成种子个数")
    ap.add_argument("--skip-real", action="store_true", help="只跑合成种子")
    args = ap.parse_args()

    _, kl_type, _ = resolve_period(args.period)
    results = []

    for seed in range(args.seeds):
        results.append(run_case(f"synthetic#{seed}", f"SYNTH{seed:03d}", kl_type, synthetic_seed=seed))

    if not args.skip_real:
        for code in [c.strip() for c in args.codes.split(",") if c.strip()]:
            try:
                results.append(run_case(f"real:{code} {args.period}", code, kl_type))
            except Exception as e:
                print(f"[FAIL] real:{code}: {e}")
                results.append(False)

    passed = sum(1 for r in results if r)
    print(f"\n== 续算等价性: {passed}/{len(results)} PASS ==")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
