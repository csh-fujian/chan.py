# -*- coding: utf-8 -*-
"""T3 家族成立点集合基线快照（chan-standard-bsp3-change 任务 3.2 / 7.3 护栏）。

用途：对 41 只日线重算，输出全部 T3A/T3B 成立点的 `(code, type, bi_idx, is_buy)`
指纹集合。改造前后各跑一次，比对哈希：**必须逐点一致**——Part B 的全部改动
只允许改变 ladder 标注，不允许改变三买成立性。

用法：
    .venv/Scripts/python.exe Debug/bsp3_equivalence_baseline.py [--write 名称]

不带 --write 只打印哈希与统计；带 --write 落盘 `Debug/bsp3_baseline_<名称>.json`
供改造后比对（`--compare 名称`）。
"""

import argparse
import hashlib
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

DB_PATH = str(ROOT / "Data" / "kl_store.duckdb")


def all_codes():
    import duckdb
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        rows = con.execute(
            "select distinct code from kline where kl_type='K_DAY' order by code"
        ).fetchall()
    finally:
        con.close()
    return [r[0] for r in rows]


def collect(codes, check_feat=True):
    """返回 (指纹列表, 统计字典)。指纹 = (code, 类型, 笔号, 是否买)。"""
    CDuckDB.db_path = DB_PATH
    points = []
    stats = {}
    for code in codes:
        conf = CChanConfig({
            "trigger_step": False,
            "kl_data_check": False,
            "divergence_rate": 0.9,
        })
        try:
            chan = CChan(code=code, data_src="custom:DuckDBAPI.CDuckDB",
                         lv_list=[KL_TYPE.K_DAY], config=conf,
                         autype=AUTYPE.QFQ, begin_time="2019-01-01")
        except Exception as exc:
            print(f"  [skip] {code}: {exc}")
            continue
        kl = chan[KL_TYPE.K_DAY]
        cnt = {"3a": 0, "3b": 0}
        for bsp in kl.bs_point_lst.bsp_iter():
            types = [t for t in bsp.type if t in (BSP_TYPE.T3A, BSP_TYPE.T3B)]
            if not types:
                continue
            for t in types:
                points.append([code, t.value, int(bsp.bi.idx), bool(bsp.is_buy)])
                cnt[t.value] += 1
                # 3.2 新增的两个只读 feature 必须存在（生成改造前基线时关闭该断言）
                if check_feat:
                    feat = dict(bsp.features.items())
                    if "bsp3_zs_low" not in feat or "bsp3_zs_high" not in feat:
                        raise AssertionError(
                            f"{code} {t.value} bi#{bsp.bi.idx} 缺少 bsp3_zs_low/high 特征"
                        )
        stats[code] = cnt
    points.sort()
    return points, stats


def fingerprint(points):
    raw = json.dumps(points, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", metavar="NAME", help="落盘基线快照")
    ap.add_argument("--compare", metavar="NAME", help="与已落盘基线比对")
    ap.add_argument("--no-feat-check", action="store_true",
                    help="不校验 bsp3_zs_low/high 特征（生成改造前基线用）")
    args = ap.parse_args()

    codes = all_codes()
    print(f"标的数：{len(codes)}")
    points, stats = collect(codes, check_feat=not args.no_feat_check)
    fp = fingerprint(points)
    total = {"3a": sum(s["3a"] for s in stats.values()),
             "3b": sum(s["3b"] for s in stats.values())}
    print(f"T3 成立点总数：{len(points)}  {total}")
    print(f"指纹：{fp}")

    out_dir = ROOT / "Debug"
    if args.write:
        snap = out_dir / f"bsp3_baseline_{args.write}.json"
        snap.write_text(json.dumps({"fingerprint": fp, "total": total,
                                    "points": points}, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        print(f"已写入 {snap.name}")

    if args.compare:
        snap = out_dir / f"bsp3_baseline_{args.compare}.json"
        if not snap.exists():
            print(f"基线不存在：{snap}")
            return 2
        base = json.loads(snap.read_text(encoding="utf-8"))
        if base["fingerprint"] == fp and base["points"] == points:
            print(f"[OK] 与基线 {args.compare} 逐点一致（{base['fingerprint']}）")
            return 0
        cur, old = set(map(tuple, points)), set(map(tuple, base["points"]))
        print(f"[FAIL] 与基线不一致（now={fp} base={base['fingerprint']}）")
        for p in sorted(cur - old):
            print("  新增：", p)
        for p in sorted(old - cur):
            print("  消失：", p)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
