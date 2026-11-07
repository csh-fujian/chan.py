# -*- coding: utf-8 -*-
"""
一买判据的三层卡点检查（chan-bsp1-strict-extreme tasks 4.1）

**只读脚本，不改内核。** 用途：把「基准案例判不出一买」的三层原因固化成可重复
的输出，防止后续变更把「第 3 关已修」误读成「该点已能判出一买」。

基准案例：`sz.000001`（平安银行）日线，2026-07-01 低点 9.7747，人工认定一买。

三层卡点（design.md Context）：
    第 1 关  线段归属      候选笔不是任何线段的终点笔        本变更不解决
    第 2 关  线段内中枢数  seg.zs_lst 只有 1 个（需 >= 2）   本变更不解决
    第 3 关  力度口径      PEAK 判不出，FULL_AREA 判得出      本变更解决

**第 3 关的观察区段按 design D3 规则 B 重建**（`[最后确认线段终点笔+1, 候选笔)`）
并用 D2 的 `shrink` 区间演化构建中枢 —— 这是唯一能复现 design.md 「2 中枢 +
c/b=0.8005」的口径。直接读现有 `seg.zs_lst` 会得到 1 个中枢、c/b≈58（因为线段边界
把中枢切碎了，正是第 2 关的成因），数字对不上不是 bug。

运行（项目根目录）：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe Debug/bsp1_three_gates.py

退出码：
    0  基准案例仍判不出一买（**预期**结果）
    1  基准案例判出了一买 —— 说明第 1、2 关的某道墙被后续变更拆掉了，
       此时必须更新 design.md 的三层卡点描述，本脚本的断言也要随之改写。
"""

import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ChanAnalyse.Chan import CChan  # noqa: E402
from ChanAnalyse.ChanConfig import CChanConfig  # noqa: E402
from ChanAnalyse.Common.CEnum import AUTYPE, KL_TYPE, MACD_ALGO  # noqa: E402
from ChanAnalyse.DataAPI.DuckDBAPI import CDuckDB  # noqa: E402
from ChanAnalyse.ZS.ZS import _span_metric  # noqa: E402

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "Data", "kl_store.duckdb")
CDuckDB.db_path = DB_PATH

CODE = "sz.000001"
TARGET_DATE = "2026-07-01"
TARGET_LOW = 9.7747
BEGIN_TIMES = ["2018-01-01", "2019-01-01", "2023-01-01", "2025-06-01"]


# =============================================================================
# 区段中枢（design D2 的 shrink 演化）：前三笔定区间，之后每笔取交集
# =============================================================================

class _ShrinkZS:
    """区段中枢：区间只收缩不扩张。交集为空则中枢结束。"""

    def __init__(self, bi_lst):
        self.bi_lst = list(bi_lst)
        self.low = max(b._low() for b in self.bi_lst)
        self.high = min(b._high() for b in self.bi_lst)
        self.begin_bi = self.bi_lst[0]
        self.end_bi = self.bi_lst[-1]

    def try_add(self, bi):
        lo = max(self.low, bi._low())
        hi = min(self.high, bi._high())
        if lo > hi:
            return False
        self.low, self.high = lo, hi
        self.end_bi = bi
        self.bi_lst.append(bi)
        return True


def build_region_zs(bis):
    """在笔序列上构建 shrink 区段中枢。"""
    out = []
    i = 0
    while i + 2 < len(bis):
        cur = _ShrinkZS(bis[i:i + 3])
        if cur.low > cur.high:
            i += 1
            continue
        j = i + 3
        while j < len(bis) and cur.try_add(bis[j]):
            j += 1
        out.append(cur)
        i = j if j > i + 3 else i + 1
    return out


# =============================================================================
# 工具
# =============================================================================

def _to_ord(s):
    y, m, d = s.replace("-", "/").split("/")
    return datetime.date(int(y), int(m), int(d)).toordinal()


def build(begin_time):
    conf = CChanConfig({"trigger_step": False, "kl_data_check": False})
    return CChan(code=CODE, data_src="custom:DuckDBAPI.CDuckDB",
                 lv_list=[KL_TYPE.K_DAY], config=conf, autype=AUTYPE.QFQ,
                 begin_time=begin_time)[KL_TYPE.K_DAY]


def find_candidate_bi(kl):
    """定位结束日最接近 TARGET_DATE 的下跌笔（不硬编码 idx，灌数推进后仍可用）。"""
    target = _to_ord(TARGET_DATE)
    best, best_gap = None, None
    for bi in kl.bi_list:
        if not bi.is_down():
            continue
        gap = abs(_to_ord(str(bi.get_end_klu().time)[:10]) - target)
        if best_gap is None or gap < best_gap:
            best, best_gap = bi, gap
    return best, best_gap


def main():
    print("=" * 78)
    print(f"一买三层卡点检查：{CODE} 基准点 {TARGET_DATE} low={TARGET_LOW}")
    print("=" * 78)

    if not os.path.exists(DB_PATH):
        print(f"DuckDB 数据文件不存在：{DB_PATH}")
        return 2

    conf = CChanConfig({"trigger_step": False, "kl_data_check": False})
    bsp_conf = conf.bs_point_conf.GetBSConfig(True)
    any_sure = False

    for begin in BEGIN_TIMES:
        kl = build(begin)
        cand, gap = find_candidate_bi(kl)
        print()
        print("-" * 78)
        print(f"begin_time={begin}")
        print("-" * 78)
        if cand is None:
            print("  [无法定位候选笔]")
            continue
        print(f"  候选笔 bi{cand.idx} DOWN  "
              f"{cand.get_begin_klu().time} → {cand.get_end_klu().time}  "
              f"low={cand._low():.4f}  (与目标相距 {gap} 天)")

        # ---- 第 1 关：线段归属 ----
        seg_end_idxs = sorted(s.end_bi.idx for s in kl.seg_list)
        seg = next((s for s in kl.seg_list
                    if s.start_bi.idx <= cand.idx <= s.end_bi.idx), None)
        in_seg_end = cand.idx in seg_end_idxs
        print(f"\n  [第 1 关] 线段终点笔集合 = {seg_end_idxs}")
        if seg is not None:
            print(f"            所属 seg{seg.idx} {seg.start_bi.idx}->{seg.end_bi.idx} "
                  f"{'DOWN' if seg.is_down() else 'UP'}")
        print(f"            候选笔 {'是' if in_seg_end else '不是'}线段终点笔 → "
              f"{'通过' if in_seg_end else '卡住'}")

        # ---- 第 2 关：线段内多笔中枢数 ----
        if seg is not None:
            multi = [zs for zs in seg.zs_lst if not zs.is_one_bi_zs()]
            zs_desc = ", ".join(f"[{zs.low:.4f}, {zs.high:.4f}] "
                                f"bi{zs.begin_bi.idx}-bi{zs.end_bi.idx}"
                                for zs in multi) or "（无）"
            print(f"\n  [第 2 关] seg.zs_lst 总数 = {len(seg.zs_lst)}  "
                  f"多笔中枢数 = {len(multi)}  （min_zs_cnt 默认 "
                  f"{bsp_conf.min_zs_cnt}）")
            print(f"            多笔中枢：{zs_desc}")
            print(f"            → {'通过' if len(multi) >= bsp_conf.min_zs_cnt else '卡住'}")

        # ---- 第 3 关：在 D3 规则 B 的观察区段上比力度 ----
        sure_segs = [s for s in kl.seg_list if s.is_sure]
        if sure_segs:
            last = sure_segs[-1]
            start = last.end_bi.idx + 1
            region = [b for b in kl.bi_list if start <= b.idx < cand.idx]
            region_zs = build_region_zs(region) if region else []
            print(f"\n  [第 3 关] 观察区段（D3 规则 B）= "
                  f"bi{start}..bi{region[-1].idx if region else '-'} "
                  f"（{len(region)} 笔），shrink 中枢数 = {len(region_zs)}")
            for z in region_zs:
                print(f"            [{z.low:.4f}, {z.high:.4f}] "
                      f"bi{z.begin_bi.idx}-bi{z.end_bi.idx}")
            if len(region_zs) >= 2:
                z1, z2 = region_zs[-2], region_zs[-1]
                trend_ok = z2.high < z1.low
                print(f"            趋势 strict：z2.high={z2.high:.4f} < "
                      f"z1.low={z1.low:.4f} → {trend_ok}")
                bi_in = kl.bi_list[z2.begin_bi.idx - 1]
                for algo in (MACD_ALGO.PEAK, MACD_ALGO.FULL_AREA):
                    b = _span_metric([bi_in], algo, is_reverse=False)
                    c = _span_metric([cand], algo, is_reverse=True)
                    ratio = c / b if b else float("nan")
                    verdict = "背驰" if ratio <= bsp_conf.divergence_rate else "不背驰"
                    mark = "  ← 本变更默认" if algo == MACD_ALGO.FULL_AREA else ""
                    print(f"            {algo.name:10s} b={b:.4f} (bi{bi_in.idx})  "
                          f"c={c:.4f} (bi{cand.idx})  c/b={ratio:.4f}  "
                          f"→ {verdict}{mark}")
            else:
                print(f"            区段中枢不足 2 个 → 第 2 关在此口径下也卡住")

        # ---- 结论 ----
        sure = list(kl.bs_point_lst.bsp1_sure_list)
        sure_hit = any(cand.idx == p.bi.idx for p in sure)
        any_sure = any_sure or sure_hit
        print(f"\n  [结论] bsp1_sure_list 共 {len(sure)} 个点；"
              f"候选笔{'在' if sure_hit else '不在'}其中 → "
              f"{'判出一买' if sure_hit else '判不出一买'}")

    print()
    print("=" * 78)
    if any_sure:
        print("✗ 基准案例在某起点下已判出一买 —— 第 1/2 关的墙被拆掉了。")
        print("  请更新 design.md 的三层卡点描述与本脚本的断言。")
        return 1
    print("✓ 基准案例在全部起点下仍判不出一买（本变更的预期结论）。")
    print("  第 1 关（线段归属）与第 2 关（线段中枢数）不在本次变更范围内，")
    print("  本变更只解决第 3 关（力度口径），因此该点仍然判不出。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
