# -*- coding: utf-8 -*-
"""
二买/类二候选点确认轴与时间轴的前置实证（chan-standard-bsp2-change tasks 0.1~0.3）

用法（项目根目录，离线读 Data/kl_store.duckdb，无需联网）：
    .venv/Scripts/python.exe Debug/bsp2_confirm_stats.py
    .venv/Scripts/python.exe Debug/bsp2_confirm_stats.py --limit 10

产出三块统计（41 只日线，standard 档，水位 pin 到库内最新交易日）：
    0.1 确认轴三档占比 + 时点后移量：
        对每个 T2/T2S 候选点，取回调笔（该点所在笔）之后的窗口笔，
        判定「强确认=后续笔最高价突破 break_bi 高点 / 弱确认=收复其
        振幅一半以上 / 未动」。后移量 = 确认笔终点时间 - 候选点时间。
        break_bi 的取法与内核 treat_bsp2 同构：锚点（一买笔）之后的
        反向笔。锚点从 relate_bsp1 反查；无 relate_bsp1 时（首线段
        分支 / follow_1 关闭），退化为「回调笔的前一笔」。
    0.2 时间轴速度比三档（0.5/1.0）× 确认结果交叉表：
        v = (amp(bsp2_bi)/amp(break_bi)) / (klu_cnt(bsp2_bi)/klu_cnt(break_bi))
        强/弱档突破率差 < 10 个百分点时打印「判别力不足」标记。
    0.3 线段级别 T2 与笔级别 T2 的重合度（时间映射口径）：
        线段级 T2 的时间点若被某笔级 T2 的 ±3 根日线内命中即算重合。

判别档位口径与 tasks 1.2/1.3 的实现函数保持同构（纯函数，本脚本
只做统计不复用 WebAPI 代码——WebAPI 层函数在本变更后续任务才落地）。
"""

import argparse
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb  # noqa: E402

from ChanAnalyse.Chan import CChan  # noqa: E402
from ChanAnalyse.ChanConfig import CChanConfig  # noqa: E402
from ChanAnalyse.Common.CEnum import AUTYPE, BSP_TYPE, KL_TYPE  # noqa: E402
from ChanAnalyse.DataAPI.DuckDBAPI import CDuckDB  # noqa: E402

DB_PATH = Path(__file__).resolve().parent.parent / "Data" / "kl_store.duckdb"
CDuckDB.db_path = str(DB_PATH)

# 时间轴阈值（tasks 1.1 默认，0.2 任务检验其判别力）
T_STRONG, T_WEAK = 0.5, 1.0


def load_codes(limit=None):
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        rows = con.execute(
            "select distinct code from kline where kl_type='K_DAY' and autype='QFQ' order by 1"
        ).fetchall()
    finally:
        con.close()
    codes = [r[0] for r in rows]
    return codes[:limit] if limit else codes


def db_watermark():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        row = con.execute(
            "select max(time_key) from kline where kl_type='K_DAY' and autype='QFQ'"
        ).fetchone()
    finally:
        con.close()
    return str(row[0])[:10] if row and row[0] else None


def build(code, watermark, **extra):
    conf = CChanConfig({"trigger_step": False, "kl_data_check": False, **extra})
    return CChan(code=code, data_src="custom:DuckDBAPI.CDuckDB", lv_list=[KL_TYPE.K_DAY],
                 config=conf, autype=AUTYPE.QFQ,
                 begin_time="2019-01-01", end_time=watermark)


def collect_samples(codes, watermark):
    """遍历全部标的，产出候选样本列表。

    每个样本：
        code, kind('2'/'2s'), bi(bi 对象), bi_list, break_bi, sub_off(bi.idx - break_bi.idx)
    """
    samples = []
    for code in codes:
        try:
            kl = build(code, watermark)[KL_TYPE.K_DAY]
        except Exception as exc:
            print(f"  [warn] {code}: {type(exc).__name__}: {exc}")
            continue
        bi_list = kl.bi_list
        for point in kl.bs_point_lst.bsp_iter():
            for t in point.type:
                if t not in (BSP_TYPE.T2, BSP_TYPE.T2S):
                    continue
                bi = point.bi
                if bi is None or bi.idx < 1 or bi.idx + 1 >= len(bi_list):
                    continue
                # break_bi 定位：与内核 treat_bsp2 同构。
                # 内核路径是 bsp1_bi(锚点)+1；锚点能从 relate_bsp1 反查时用它，
                # 否则退化为回调笔前一笔（首线段分支 bsp2_bi=bi[1], break_bi=bi[0]
                # 的关系同样是「回調笔的前一笔」）。
                anchor = getattr(point, "relate_bsp1", None)
                anchor_idx = anchor.bi.idx if anchor is not None and anchor.bi is not None else bi.idx - 2
                bi_idx = anchor_idx + 1 if 0 <= anchor_idx + 1 < len(bi_list) else bi.idx - 1
                break_bi = bi_list[bi_idx]
                samples.append({
                    "code": code, "kind": '2' if t == BSP_TYPE.T2 else '2s',
                    "bi": bi, "bi_list": bi_list, "break_bi": break_bi,
                    "is_buy": point.is_buy,
                })
    return samples


def confirm_bucket(sample, window):
    """确认轴三档判定（与 tasks 1.2 实现同构的纯逻辑）。

    返回 (bucket, lag_days)。bucket ∈ {'strong', 'weak', 'none', 'ongoing'}。
    """
    bi, bi_list, break_bi = sample["bi"], sample["bi_list"], sample["break_bi"]
    is_buy = sample.get("is_buy", True)
    if is_buy:
        threshold_strong = break_bi.get_end_val()          # break_bi 高点（上升笔终点）
        threshold_weak = break_bi.get_begin_val() + 0.5 * break_bi.amp()
    else:
        threshold_strong = break_bi.get_end_val()          # 下降笔终点（低点）
        threshold_weak = break_bi.get_begin_val() - 0.5 * break_bi.amp()

    end_idx = min(bi.idx + window, len(bi_list) - 1)
    if bi.idx + window > len(bi_list) - 1:
        return 'ongoing', None  # 窗口不足（数据末端的候选，非终态）

    is_buy = sample.get("is_buy", True)
    lag_days = None
    for j in range(bi.idx + 1, end_idx + 1):
        cand = bi_list[j]
        # 买侧考察窗口内上升笔最高价；卖侧考察窗口内下降笔最低价
        if is_buy and cand.is_up():
            px = cand.get_end_val()
            if px >= threshold_strong:
                return 'strong', int(cand.get_end_klu().time.ts - bi.get_end_klu().time.ts) // 86400
            if lag_days is None and px >= threshold_weak:
                lag_days = int(cand.get_end_klu().time.ts - bi.get_end_klu().time.ts) // 86400
        elif (not is_buy) and cand.is_down():
            px = cand.get_end_val()
            if px <= threshold_strong:
                return 'strong', int(cand.get_end_klu().time.ts - bi.get_end_klu().time.ts) // 86400
            if lag_days is None and px <= threshold_weak:
                lag_days = int(cand.get_end_klu().time.ts - bi.get_end_klu().time.ts) // 86400
    if lag_days is not None:
        return 'weak', lag_days
    return 'none', None


def time_axis_bucket(sample):
    """时间轴速度比三档（与 tasks 1.3 实现同构）。返回档位名或 None。"""
    bi, break_bi = sample["bi"], sample["break_bi"]
    a_b, a_r = break_bi.amp(), bi.amp()
    n_b, n_r = break_bi.get_klu_cnt(), bi.get_klu_cnt()
    if a_b <= 0 or n_b <= 0 or n_r <= 0:
        return None
    v = (a_r / a_b) / (n_r / n_b)
    if v <= T_STRONG:
        return 'strong'
    if v <= T_WEAK:
        return 'mid'
    return 'weak'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="只统计前 N 只（调试）")
    args = parser.parse_args()

    watermark = db_watermark()
    codes = load_codes(args.limit)
    print(f"标的 {len(codes)} 只，水位 {watermark}")

    samples = collect_samples(codes, watermark)
    print(f"T2/T2S 候选样本 {len(samples)} 个（笔级别）")

    # ---- 0.1 确认轴三档 + 后移量（窗口 1 与 2 各统计一遍） ----
    for window in (1, 2):
        buckets = collections.Counter()
        lags = collections.defaultdict(list)
        for s in samples:
            b, lag = confirm_bucket(s, window)
            buckets[(s["kind"], b)] += 1
            if lag is not None:
                lags[(s["kind"], b)].append(lag)
        print(f"\n== 窗口 = {window} 笔 ==")
        for kind in ('2', '2s'):
            total = sum(v for (k, _), v in buckets.items() if k == kind)
            print(f"  T{kind} 总数 {total}:")
            for b in ('strong', 'weak', 'none', 'ongoing'):
                n = buckets.get((kind, b), 0)
                pct = f"{100 * n / total:.0f}%" if total else "-"
                lagtxt = ""
                lv = lags.get((kind, b))
                if lv:
                    lagtxt = f"  后移 {min(lv)}~{max(lv)} 天 (中位 {sorted(lv)[len(lv)//2]})"
                print(f"    {b:8s} {n:3d}  ({pct}){lagtxt}")

    # ---- 0.2 时间轴 × 确认结果交叉表（窗口取 2，与后续默认候选一致） ----
    print("\n== 时间轴速度比 (0.5/1.0) × 窗口2确认结果 ==")
    cross = collections.Counter()
    unclassified = 0
    for s in samples:
        tb = time_axis_bucket(s)
        if tb is None:
            unclassified += 1
            continue
        cb, _ = confirm_bucket(s, 2)
        cross[(tb, cb)] += 1
    for tb in ('strong', 'mid', 'weak'):
        n = sum(v for (t, _), v in cross.items() if t == tb)
        br = cross.get((tb, 'strong'), 0)
        print(f"  时间轴{tb:6s} n={n:3d}  强确认率 {100 * br / n:.0f}%" if n else
              f"  时间轴{tb:6s} n=0")
    if unclassified:
        print(f"  （{unclassified} 个样本速度比不可计算，未计入交叉表）")
    brk = []
    for tb in ('strong', 'weak'):
        n = sum(v for (t, _), v in cross.items() if t == tb)
        if n:
            brk.append(cross.get((tb, 'strong'), 0) / n)
    if len(brk) == 2:
        gap = (brk[0] - brk[1]) * 100
        print(f"  强/弱档强确认率差 {gap:.1f} 个百分点" +
              ("  ⚠ 判别力不足，建议降级为 feature" if abs(gap) < 10 else "  ✓ 达到判别力标准"))

    # ---- 0.3 线段/笔级别 T2 重合度 ----
    print("\n== 线段级 T2 × 笔级 T2 重合度（±3 自然日窗口） ==")
    seg_times, bi_times = [], []
    for code in codes:
        try:
            kl = build(code, watermark)[KL_TYPE.K_DAY]
        except Exception:
            continue
        for point in kl.seg_bs_point_lst.bsp_iter():
            if any(t == BSP_TYPE.T2 for t in point.type):
                seg_times.append((code, point.klu.time.ts))
        for point in kl.bs_point_lst.bsp_iter():
            if any(t == BSP_TYPE.T2 for t in point.type):
                bi_times.append((code, point.klu.time.ts))
    matched = 0
    bi_by_code = collections.defaultdict(list)
    for c, ts in bi_times:
        bi_by_code[c].append(ts)
    for c, ts in seg_times:
        if any(abs(ts - t) <= 3 * 86400 for t in bi_by_code.get(c, ())):
            matched += 1
    rate = 100 * matched / len(seg_times) if seg_times else 0
    print(f"  线段级 T2: {len(seg_times)} 个；笔级 T2: {len(bi_times)} 个；"
          f"±3日内重合 {matched}（重合率 {rate:.0f}%）")
    if seg_times:
        if rate >= 90:
            print("  → 重合度高，维持 seg_bs_point_lst 零暴露现状（design OQ2 结论）")
        else:
            print("  → 重合度低，线段级信息有增量，暴露方案另立变更评估（design OQ2 结论）")


if __name__ == "__main__":
    main()
