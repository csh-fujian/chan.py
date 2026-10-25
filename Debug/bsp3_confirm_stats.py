# -*- coding: utf-8 -*-
"""T3 确认轴 / 时间轴实证统计 —— chan-standard-bsp3-change task 6.1。

回答 design 的三个待定项：
    1. 确认窗口长度（1 笔 vs 2 笔）：C3 占比与「时点后移量」差异
    2. 时间轴三档 × 确认结果的交叉判别力（阈值 0.5 / 1.0 是否有效）
    3. 佐证轴命中率（子级数据可得时）

用法：
    .venv/Scripts/python.exe Debug/bsp3_confirm_stats.py [--window 1 2]

输出：控制台表格 + `Debug/bsp3_confirm_stats.json`（结论回填 design 用）。
"""

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ChanAnalyse.Chan import CChan                     # noqa: E402
from ChanAnalyse.ChanConfig import CChanConfig          # noqa: E402
from ChanAnalyse.Common.CEnum import AUTYPE, BSP_TYPE, KL_TYPE  # noqa: E402
from ChanAnalyse.DataAPI.DuckDBAPI import CDuckDB      # noqa: E402
from WebAPI.bsp3_confirm import confirm_axis           # noqa: E402
from WebAPI.bsp3_time_axis import time_axis            # noqa: E402

DB_PATH = str(ROOT / "Data" / "kl_store.duckdb")


def codes():
    import duckdb
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        return [r[0] for r in con.execute(
            "select distinct code from kline where kl_type='K_DAY' order by code"
        ).fetchall()]
    finally:
        con.close()


def sample(window):
    """返回 [(code, bsp_type, is_buy, confirm, time)] —— 对每个 T3 成立点推导两轴。"""
    CDuckDB.db_path = DB_PATH
    out = []
    for code in codes():
        conf = CChanConfig({
            "trigger_step": False, "kl_data_check": False,
            "divergence_rate": 0.9, "bsp3_confirm_window": window,
        })
        try:
            chan = CChan(code=code, data_src="custom:DuckDBAPI.CDuckDB",
                         lv_list=[KL_TYPE.K_DAY], config=conf,
                         autype=AUTYPE.QFQ, begin_time="2019-01-01")
        except Exception:
            continue
        kl = chan[KL_TYPE.K_DAY]
        cfg = kl.bs_point_lst.config.GetBSConfig(True)
        for bsp in kl.bs_point_lst.bsp_iter():
            t3 = [t for t in bsp.type if t in (BSP_TYPE.T3A, BSP_TYPE.T3B)]
            if not t3:
                continue
            cfg_side = kl.bs_point_lst.config.GetBSConfig(bool(bsp.is_buy))
            out.append((
                code,
                t3[0].value,
                bool(bsp.is_buy),
                confirm_axis(bsp, kl.bi_list, cfg_side),
                time_axis(bsp, kl.bi_list, cfg_side),
            ))
    return out


def report(rows, window):
    total = len(rows)
    c_cnt = collections.Counter(r[3] for r in rows)
    t_cnt = collections.Counter(r[4] for r in rows)
    print(f"\n=== 窗口 {window} 笔：{total} 个 T3 成立点 ===")
    print("确认轴分布：", dict(sorted(c_cnt.items(), key=lambda kv: str(kv[0]))))
    print("时间轴分布：", dict(sorted(t_cnt.items(), key=lambda kv: str(kv[0]))))

    # 交叉判别力：时间轴档位 × 是否确认（C3）
    cross = collections.defaultdict(lambda: [0, 0])
    for _c, _t, _b, c, t in rows:
        if t is None or c is None:
            continue
        cross[t][0 if c == "C3" else 1] += 1
    print("时间轴 × 确认（C3 / 非C3）：")
    for t in ("T3", "T2", "T1"):
        if t in cross:
            hit, miss = cross[t]
            rate = hit / (hit + miss) if hit + miss else 0
            print(f"    {t}: C3 {hit} / 非C3 {miss}  → C3 率 {rate:.1%}")
    return {
        "window": window,
        "total": total,
        "confirm": dict(c_cnt),
        "time": dict(t_cnt),
        "cross": {k: v for k, v in cross.items()},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", nargs="*", type=int, default=[1, 2])
    args = ap.parse_args()

    result = {}
    for w in args.window:
        rows = sample(w)
        result[f"window_{w}"] = report(rows, w)

    out = ROOT / "Debug" / "bsp3_confirm_stats.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n结论已写入 {out.name}")
    print("回填指引：若窗口 1/2 的 C3 占比差异 < 10 个百分点，维持默认 2（末端候选"
          "标 C0 更保守）；若时间轴 T3 档的 C3 率不显著高于 T1 档，时间轴降级为纯 feature。")


if __name__ == "__main__":
    main()
