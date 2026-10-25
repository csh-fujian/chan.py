# -*- coding: utf-8 -*-
"""
佐证轴 L2-3 与内核 `bsp1_qjt_hit` 同口径验证（chan-bsp-ladder-change tasks 6.2）

断言：同一数据、`bsp1_qjt=True` 下

    {WebAPI 佐证轴判为 L2-3 的点} ⊇ {内核 bsp1_qjt_hit=True 的点}

即 WebAPI 的佐证判定**不窄于**内核特征——内核认下的区间套命中，阶梯不会漏标。
反向放宽（L2-3 多于 qjt_hit）是允许且预期的，来源有二：

    a) 内核只对 `bsp1_list`（teat_bsp1 产出的候选）写 qjt 特征；
       佐证轴对全部未确认一买家族判定，覆盖面更宽。
    b) 内核 `bsp1_qjt` 可关闭（未开时特征恒缺）；佐证轴走同一窗口逻辑，
       与开关无关。脚本强制开启，故该差异不出现。

差异点（尤其 `qjt_hit=True` 但佐证轴非 L2-3）会逐条打印 `bi.idx` + 原因，
便于判断是否为真实口径缺口。

运行（项目根目录，离线读 Data/kl_store.duckdb）：
    .venv/Scripts/python.exe Debug/bsp_ladder_qjt_equiv.py
    .venv/Scripts/python.exe Debug/bsp_ladder_qjt_equiv.py --code sz.000001 --begin 2022-01-01

## 验证记录（2026-10-25，sz.000001 日线/30m/5m，起点 2018-01-01）

⊇ 在两级都成立，无遗漏。几处口径差异已确认且**不构成缺口**：

1. 比较必须在 `bsp1_list`（候选全集）上做。内核 `_cal_qjt_feature` 对
   `bsp1_list` 全量写特征，其中未成立、不进 `bsp_store_flat_dict` 的候选也带
   `bsp1_qjt_hit`（本次日线 14 个候选中只有 4 个落库，唯一命中点 bi=77 恰好
   不在落库集合里）。若在 `getSortedBspList()` 上比较会误报「遗漏」。
2. 佐证轴覆盖更宽：它对任一未确认一买家族点求值，与 `bsp1_qjt` 开关无关；
   内核只在开关开启且容器就绪时写特征。本次无放宽样本，属正常。
3. 子级确认滞后（chan-standard-bsp1 D8）只影响过程中翻转，终态一致——
   见 `Debug/bsp_ladder_step.py`。
"""

import argparse
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ChanAnalyse.Chan import CChan  # noqa: E402
from ChanAnalyse.ChanConfig import CChanConfig  # noqa: E402
from ChanAnalyse.Common.CEnum import AUTYPE, KL_TYPE  # noqa: E402
from ChanAnalyse.DataAPI.DuckDBAPI import CDuckDB  # noqa: E402
from WebAPI.bsp_ladder import (  # noqa: E402
    LADDER_L4,
    _c_window_bounds,
    _sub_time_span,
    cal_ladder,
    corroboration_axis,
    is_bsp1_family,
)
from WebAPI.bsp_sure import bsp_is_sure  # noqa: E402

CDuckDB.db_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Data", "kl_store.duckdb")


def run(code, lv_list, begin):
    cfg = CChanConfig({"trigger_step": False, "kl_data_check": False, "bsp1_qjt": True})
    return CChan(code=code, data_src="custom:DuckDBAPI.CDuckDB", lv_list=lv_list,
                 config=cfg, autype=AUTYPE.QFQ, begin_time=begin)


def kernel_hits(kl):
    """内核特征：`bsp1_list` 中 `bsp1_qjt_hit=True` 的笔索引。"""
    out = {}
    for bsp in getattr(kl.bs_point_lst, 'bsp1_list', []):
        feat = dict(bsp.features.items()) if bsp.features else {}
        if feat.get('bsp1_qjt_hit'):
            out[bsp.bi.idx] = feat.get('bsp1_qjt_sub_idx')
    return out


def explain(bsp, sub_bsps, sub_kl):
    """佐证轴非 L2-3 时给出原因分类，便于定位差口。"""
    if not is_bsp1_family(bsp):
        return '非一买家族'
    bounds = _c_window_bounds(bsp)
    if bounds is None:
        return 'c 窗口不可评估（无 parent_seg / 无中枢 / c 段为空）'
    c_start, c_end, seg = bounds
    t_lo, t_hi = _sub_time_span(seg, c_start, c_end)
    if t_lo is None:
        return '窗口内无子级 K 线（sub_kl_list 未挂载）'
    is_buy = bool(bsp.is_buy)
    same_dir = []
    for sub_bsp in getattr(sub_bsps, 'bsp1_sure_list', []):
        try:
            if bool(sub_bsp.is_buy) != is_buy:
                continue
            same_dir.append(sub_bsp.klu.time.ts)
        except Exception:
            continue
    if not same_dir:
        return '子级无同向已确认一买'
    if not any(t_lo <= ts <= t_hi for ts in same_dir):
        return f'子级同向已确认一买不在窗口 [{t_lo:.0f},{t_hi:.0f}] 内'
    return '窗口内有同向已确认一买但被判为非命中（口径缺口，须排查）'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--code', default='sz.000001')
    ap.add_argument('--begin', default='2018-01-01')
    args = ap.parse_args()

    # 三级同时加载，`load_iterator` 才会给每一级挂上各自的 sub_kl_list /
    # sub_bs_point_lst（只加载父子两级时，30M 的 sub 容器为空）
    lv_list = [KL_TYPE.K_DAY, KL_TYPE.K_30M, KL_TYPE.K_5M]
    print(f"标的 {args.code}  级别 {[lv.name for lv in lv_list]}  起点 {args.begin}"
          f"  bsp1_qjt=on")
    chan = run(args.code, lv_list, args.begin)

    ok = True
    for lv, sub_lv in ((KL_TYPE.K_DAY, KL_TYPE.K_30M),
                       (KL_TYPE.K_30M, KL_TYPE.K_5M)):
        print(f"\n  {lv.name} → {sub_lv.name}")
        kl = chan[lv]
        sub_kl = chan.kl_datas.get(sub_lv)
        sub_bsps = getattr(kl.bs_point_lst, 'sub_bs_point_lst', None)
        if sub_kl is None or sub_bsps is None:
            print("    子级别容器缺失 → 内核特征与佐证轴均不产出，跳过")
            continue

        kh = kernel_hits(kl)
        # 同口径比较必须在**同一候选全集**上做：内核 `_cal_qjt_feature` 对
        # `bsp1_list` 全量写特征，其中一部分候选并未成立（不进
        # `bsp_store_flat_dict`），落库阶梯也就不会覆盖它们。
        # 因此佐证轴也在 `bsp1_list` 上求值，而不是 `getSortedBspList()`。
        candidates = list(getattr(kl.bs_point_lst, 'bsp1_list', []))
        l23 = {}
        ladders = collections.Counter()
        for bsp in candidates:
            ladder = cal_ladder(bsp, kl.bs_point_lst,
                                sub_bs_point_lst=sub_bsps, sub_kl=sub_kl)
            ladders[ladder] += 1
            ca = corroboration_axis(bsp, sub_bsps, sub_kl=sub_kl)
            if ca == 'L2-3':
                l23[bsp.bi.idx] = ladder

        # 同一点集在落库视图（bsp_store_flat_dict）下的覆盖情况，仅作参考
        stored_idx = {b.bi.idx for b in kl.bs_point_lst.getSortedBspList()}
        stored_hits = sorted(set(kh) & stored_idx)

        print(f"    候选全集 bsp1_list：{len(candidates)} 个"
              f"（其中落库 {len([b for b in candidates if b.bi.idx in stored_idx])} 个）")
        print(f"    内核 bsp1_qjt_hit=True：{len(kh)} 个 {sorted(kh)}"
              f"（其中落库 {len(stored_hits)} 个）")
        print(f"    佐证轴 L2-3：{len(l23)} 个 {sorted(l23)}")
        print("    ladder 分布（候选全集）：" + "  ".join(
            f"{'NULL' if k is None else k}×{v}"
            for k, v in sorted(ladders.items(), key=lambda kv: (kv[0] is None, kv[0] or ''))))

        missing = sorted(set(kh) - set(l23))
        if missing:
            ok = False
            print(f"    ✗ 遗漏 {len(missing)} 个：{missing}")
            by_idx = {b.bi.idx: b for b in candidates}
            for idx in missing:
                bsp = by_idx.get(idx)
                if bsp is None:
                    print(f"      bi={idx}：不在 bsp1_list 中")
                    continue
                is_l4 = cal_ladder(bsp, kl.bs_point_lst,
                                   sub_bs_point_lst=sub_bsps, sub_kl=sub_kl) == LADDER_L4
                reason = '已确认（L4 短路，三轴不适用）' if is_l4 else explain(bsp, sub_bsps, sub_kl)
                print(f"      bi={idx}：{reason}")
        else:
            print("    ✓ 内核命中全部被佐证轴覆盖（⊇ 成立）")

        extra = sorted(set(l23) - set(kh))
        if extra:
            print(f"    · 佐证轴放宽 {len(extra)} 个（允许）：{extra}")

    ok &= check_ingest_path_window(args.code)
    print()
    print("✓ L2-3 不窄于 bsp1_qjt_hit" if ok else "✗ 存在内核命中而佐证轴未覆盖的点")
    return 0 if ok else 1


def check_ingest_path_window(code):
    """落库链路（单级别父级 + 独立子级计算）与多级别加载的窗口口径对照。

    落库链路的父级 `CChan` 只 load 本级别，父级 K 线的 `sub_kl_list` 恒空，
    `_sub_time_span` 走 `_parent_bar_span` 回退。本段断言该回退**不会收窄**
    命中集：多级别（结构映射精确）判定为命中的点，落库链路也必须命中。
    """
    print("\n  落库链路窗口回退（单级别父级 + 独立子级）")
    from WebAPI import incremental_engine as ie
    from WebAPI.bsp_ladder import corroboration_axis

    lv = KL_TYPE.K_DAY
    begin = '2018-01-01'
    chan_ml = run(code, [KL_TYPE.K_DAY, KL_TYPE.K_30M], begin)
    # 落库链路形态：单级别父级（构造方式与 incremental_engine._compute_full 一致，
    # 但限定同一起点，否则两者的笔索引空间不同、无法按 bi.idx 对齐）
    klus = ie._load_klus(code, lv, 'QFQ', begin=begin)
    if not klus:
        print("    父级无数据，跳过")
        return True
    chan_sl = ie._make_chan(code, lv, 'QFQ')
    chan_sl.trigger_load({lv: klus})
    sub_result = ie._compute_sub_for_l1(code, lv, 'QFQ', 'D')
    if sub_result is None:
        print("    子级不可用，跳过")
        return True
    _, sub_bsps_sl, sub_kl_sl = sub_result

    ml_kl = chan_ml[lv]
    ml_sub = chan_ml.kl_datas.get(KL_TYPE.K_30M)
    ml_bsps = getattr(ml_kl.bs_point_lst, 'sub_bs_point_lst', None)
    if ml_bsps is None or ml_sub is None:
        print("    多级别容器缺失，跳过")
        return True

    sl_kl = chan_sl[lv]
    ml_hits, sl_hits = set(), set()
    for bsp in ml_kl.bs_point_lst.bsp1_list:
        if corroboration_axis(bsp, ml_bsps, sub_kl=ml_sub) == 'L2-3':
            ml_hits.add(bsp.bi.idx)
    for bsp in sl_kl.bs_point_lst.bsp1_list:
        if corroboration_axis(bsp, sub_bsps_sl, sub_kl=sub_kl_sl) == 'L2-3':
            sl_hits.add(bsp.bi.idx)

    print(f"    多级别（结构映射）：{len(ml_hits)} 个 {sorted(ml_hits)}")
    print(f"    落库链路（回退窗）：{len(sl_hits)} 个 {sorted(sl_hits)}")
    missing = sorted(ml_hits - sl_hits)
    if missing:
        print(f"    ✗ 回退口径收窄了命中集：{missing}")
        return False
    print("    ✓ 回退口径不收窄命中集")
    return True


if __name__ == '__main__':
    sys.exit(main())
