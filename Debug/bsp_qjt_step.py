# -*- coding: utf-8 -*-
"""
区间套特征在步进模式下的终态一致性（chan-standard-bsp1-change tasks 10.7）

断言两件事：
    1. 同一标的批量模式与逐根步进模式的 `bsp_store_dict` 六类数量完全一致
       （承接 tasks 4.3 的不变量，`bsp1_qjt=True` 下再确认一次）
    2. 终态**区间套命中集合**一致：`{bi.idx : sub_idx}` 逐笔相等

`bsp1_qjt_hit` 在快照之间由 False 翻 True 是允许的（子级确认滞后，design D8），
因此本脚本只比较**终态**，不比较中间快照。

运行（项目根目录，离线读 Data/kl_store.duckdb）：
    .venv/Scripts/python.exe Debug/bsp_qjt_step.py
    .venv/Scripts/python.exe Debug/bsp_qjt_step.py --code sz.000001 --begin 2024-01-01
"""

import argparse
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ChanAnalyse.Chan import CChan  # noqa: E402
from ChanAnalyse.ChanConfig import CChanConfig  # noqa: E402
from ChanAnalyse.Common.CEnum import AUTYPE, BSP_TYPE, KL_TYPE  # noqa: E402
from ChanAnalyse.DataAPI.DuckDBAPI import CDuckDB  # noqa: E402

CDuckDB.db_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Data", "kl_store.duckdb")

TYPE_SHORT = {BSP_TYPE.T1: '1', BSP_TYPE.T1P: '1p', BSP_TYPE.T2: '2',
              BSP_TYPE.T2S: '2s', BSP_TYPE.T3A: '3a', BSP_TYPE.T3B: '3b'}


def config(step):
    return CChanConfig({"trigger_step": step, "kl_data_check": False, "bsp1_qjt": True})


def run_batch(code, lv_list, begin):
    chan = CChan(code=code, data_src="custom:DuckDBAPI.CDuckDB", lv_list=lv_list,
                 config=config(False), autype=AUTYPE.QFQ, begin_time=begin)
    return chan


def run_step(code, lv_list, begin):
    # trigger_step=True 时构造函数不加载，须由 step_load 逐根推进
    chan = CChan(code=code, data_src="custom:DuckDBAPI.CDuckDB", lv_list=lv_list,
                 config=config(True), autype=AUTYPE.QFQ, begin_time=begin)
    n = 0
    for _ in chan.step_load():
        n += 1
    print(f"    步进快照数：{n}")
    return chan


def counts(chan, lv):
    cnt = collections.Counter()
    for bsp in chan[lv].bs_point_lst.bsp_store_flat_dict.values():
        for t in bsp.type:
            if t in TYPE_SHORT:
                cnt[TYPE_SHORT[t]] += 1
    return cnt


def hits(chan, lv):
    out = {}
    for bsp in chan[lv].bs_point_lst.bsp1_list:
        fd = dict(bsp.features.items())
        if fd.get('bsp1_qjt_hit'):
            out[bsp.bi.idx] = fd.get('bsp1_qjt_sub_idx')
    return out


def fmt(cnt):
    return "  ".join(f"{k}:{cnt.get(k, 0):3d}" for k in ('1', '1p', '2', '2s', '3a', '3b'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--code', default='sz.000001')
    ap.add_argument('--begin', default='2022-01-01')
    args = ap.parse_args()

    lv_list = [KL_TYPE.K_DAY, KL_TYPE.K_30M]
    print(f"标的 {args.code}  级别 {[lv.name for lv in lv_list]}  起点 {args.begin}")

    print("\n批量模式：")
    batch = run_batch(args.code, lv_list, args.begin)
    print("\n步进模式：")
    step = run_step(args.code, lv_list, args.begin)

    ok = True
    for lv in lv_list:
        cb, cs = counts(batch, lv), counts(step, lv)
        hb, hs = hits(batch, lv), hits(step, lv)
        print(f"\n  {lv.name}")
        print(f"    批量 {fmt(cb)}")
        print(f"    步进 {fmt(cs)}")
        if cb == cs:
            print("    ✓ 六类数量一致")
        else:
            print(f"    ✗ 六类数量不一致：批独有 {cb - cs}  步进独有 {cs - cb}")
            ok = False
        print(f"    批量命中 {len(hb)} 个：{hb}")
        print(f"    步进命中 {len(hs)} 个：{hs}")
        if hb == hs:
            print("    ✓ 终态命中集合一致")
        else:
            print(f"    ✗ 命中集合不一致：仅批量 {sorted(set(hb) - set(hs))}  "
                  f"仅步进 {sorted(set(hs) - set(hb))}")
            for k in sorted(set(hb) & set(hs)):
                if hb[k] != hs[k]:
                    print(f"      bi={k} 命中索引不同：{hb[k]} vs {hs[k]}")
            ok = False

    print()
    print("✓ 全部一致" if ok else "✗ 存在不一致")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
