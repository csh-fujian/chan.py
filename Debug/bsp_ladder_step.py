# -*- coding: utf-8 -*-
"""
三轴阶梯在步进模式下的终态一致性（chan-bsp-ladder-change tasks 6.1）

断言三件事（承接 chan-standard-bsp1 的步进不变量）：

    1. 同一标的批量模式与逐根步进模式的 `bsp_store_dict` 六类数量完全一致
    2. **终态** `ladder` 组合值集合一致：全量（含 NULL/L4）与未确认集合逐项相等
    3. 三轴分档计数一致（进度轴 / 佐证轴 / 分型轴各档）

过程中的翻转是允许的：佐证轴的 L2-1→L2-2→L2-3、分型轴的 L3-1→L3-2→L3-3
会随子级确认与末端 K 线推进单调变强（它们回答「现在有什么证据」），
L4 也会在段确认时翻真。本脚本只比较**终态**，不比较中间快照。

运行（项目根目录，离线读 Data/kl_store.duckdb）：
    .venv/Scripts/python.exe Debug/bsp_ladder_step.py
    .venv/Scripts/python.exe Debug/bsp_ladder_step.py --code sz.000001 --begin 2024-01-01
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
from WebAPI.bsp_ladder import AXIS_SEPARATOR, LADDER_L4, cal_ladder  # noqa: E402
from WebAPI.chan_service import resolve_sub_level  # noqa: E402

CDuckDB.db_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Data", "kl_store.duckdb")

TYPE_SHORT = {BSP_TYPE.T1: '1', BSP_TYPE.T1P: '1p', BSP_TYPE.T2: '2',
              BSP_TYPE.T2S: '2s', BSP_TYPE.T3A: '3a', BSP_TYPE.T3B: '3b'}
TYPE_ORDER = ('1', '1p', '2', '2s', '3a', '3b')

# 三轴档位的取值形状（空格子串区分，避免 L1/L2 与 L2-1 混淆）
PROGRESS_PREFIX = ('L1', 'L2')
CORROB_PREFIX = ('L2-1', 'L2-2', 'L2-3')
FRACTAL_PREFIX = ('L3-1', 'L3-2', 'L3-3')


def config(step):
    return CChanConfig({"trigger_step": step, "kl_data_check": False})


def run_batch(code, lv_list, begin):
    return CChan(code=code, data_src="custom:DuckDBAPI.CDuckDB", lv_list=lv_list,
                 config=config(False), autype=AUTYPE.QFQ, begin_time=begin)


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


def sub_kl_of(chan, lv, code, begin, cache):
    """子级别 `CKLine_List`（佐证轴 / 分型轴数据源）。

    优先复用已在 `chan` 中加载的级别；否则独立全量计算一次并缓存——
    与落库链路 `incremental_engine._compute_sub_for_l1` 的「子级别独立计算」
    同语义（子级的快照/游标归它自己的重算周期管，这里只借结果）。
    """
    sub_lv = resolve_sub_level(lv)
    if sub_lv is None:
        return None
    if sub_lv in chan.kl_datas:
        return chan[sub_lv]
    if sub_lv not in cache:
        try:
            sub_chan = CChan(code=code, data_src="custom:DuckDBAPI.CDuckDB",
                             lv_list=[sub_lv], config=config(False),
                             autype=AUTYPE.QFQ, begin_time=begin)
            cache[sub_lv] = sub_chan[sub_lv]
        except Exception as exc:  # 无数据 / 计算失败 → 佐证轴缺席
            print(f"    （子级别 {sub_lv.name} 不可用：{exc}）")
            cache[sub_lv] = None
    return cache[sub_lv]


def ladders(chan, lv, code, begin, cache):
    """全量 ladder 取值计数 + 未确认集合。

    用与 `incremental_engine._extract_bsp_rows` **相同**的调用形态
    （同 sub 容器、同参数），保证落库值与本脚本值同源。
    """
    kl = chan[lv]
    sub_kl = sub_kl_of(chan, lv, code, begin, cache)
    sub_bsp_lst = sub_kl.bs_point_lst if sub_kl is not None else None
    counter = collections.Counter()
    unsure = set()
    for bsp in kl.bs_point_lst.getSortedBspList():
        ladder = cal_ladder(bsp, kl.bs_point_lst, sub_bs_point_lst=sub_bsp_lst, sub_kl=sub_kl)
        counter[ladder] += 1
        if ladder != LADDER_L4:
            unsure.add(ladder)
    return counter, unsure


def axis_counts(counter):
    """按三段取值形状切分出三轴各档计数（跨买卖点累加）。"""
    out = {p: 0 for p in PROGRESS_PREFIX + CORROB_PREFIX + FRACTAL_PREFIX}
    for ladder, n in counter.items():
        if not ladder or ladder == LADDER_L4:
            continue
        for axis in ladder.split(AXIS_SEPARATOR):
            if axis in out:
                out[axis] += n
    return out


def fmt(cnt):
    return "  ".join(f"{k}:{cnt.get(k, 0):3d}" for k in TYPE_ORDER)


def fmt_ladders(counter):
    if not counter:
        return "    （无买卖点）"
    parts = []
    for k in sorted(counter, key=lambda x: (x is None, x or '')):
        label = 'NULL' if k is None else k
        parts.append(f"{label}×{counter[k]}")
    return "    " + "  ".join(parts)


def compare(tag, a, b):
    if a == b:
        print(f"    ✓ {tag}一致")
        return True
    print(f"    ✗ {tag}不一致")
    if isinstance(a, collections.Counter):
        print(f"      仅批量 {dict(a - b)}   仅步进 {dict(b - a)}")
    else:
        print(f"      仅批量 {sorted(x for x in a - b if x)}   仅步进 {sorted(x for x in b - a if x)}")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--code', default='sz.000001')
    ap.add_argument('--begin', default='2024-01-01')
    args = ap.parse_args()

    lv_list = [KL_TYPE.K_DAY, KL_TYPE.K_30M]
    print(f"标的 {args.code}  级别 {[lv.name for lv in lv_list]}  起点 {args.begin}")

    print("\n批量模式：")
    batch = run_batch(args.code, lv_list, args.begin)
    print("\n步进模式：")
    step = run_step(args.code, lv_list, args.begin)

    ok = True
    cache = {}  # 子级别容器缓存（批量/步进共用，子级与模式无关）
    for lv in lv_list:
        print(f"\n  {lv.name}")
        cb, cs = counts(batch, lv), counts(step, lv)
        print(f"    批量 {fmt(cb)}")
        print(f"    步进 {fmt(cs)}")
        ok &= compare("六类数量", cb, cs)

        lb, ub = ladders(batch, lv, args.code, args.begin, cache)
        ls, us = ladders(step, lv, args.code, args.begin, cache)
        print("    批量 ladder：")
        print(fmt_ladders(lb))
        print("    步进 ladder：")
        print(fmt_ladders(ls))
        ok &= compare("终态 ladder 组合值集合（全量）", lb, ls)
        ok &= compare("终态 ladder 组合值集合（未确认）", ub, us)

        ab, as_ = axis_counts(lb), axis_counts(ls)
        print(f"    三轴分档 批量 {ab}")
        print(f"    三轴分档 步进 {as_}")
        ok &= compare("三轴分档计数", ab, as_)

    print()
    print("✓ 全部一致" if ok else "✗ 存在不一致")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
