# -*- coding: utf-8 -*-
"""增量续算的语义等价性：快照恢复后继续算 == 一次性全量算。

这是 parent_seg 修复的**语义**验收（上一支脚本只验证了结构完整性）。
`parent_seg` 是 `BSPointList.treat_bsp1` / `treat_bsp3` 的真实输入，
若重建后的指向与导出前不一致，买卖点就会漂移。

做法：
  取某级别的 K 线序列，切在 80% 处：
    路径 A：前 80% 全量算 → dump → load → 推送后 20%  → 结果 R1
    路径 B：全量一次性算                            → 结果 R2
  断言 R1 == R2（六类数量 + 逐点 (bi.idx, 主类型, is_buy) 集合）

运行：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe Debug/test_pickle_incremental_equiv.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        FAILURES.append(name)


def result_of(chan, kt):
    """买卖点结果的规范形式：六类数量 + 逐点集合。"""
    from collections import Counter

    kl = chan.kl_datas[kt]
    lst = kl.bs_point_lst
    counts = Counter()
    points = set()
    for bsp in lst.getSortedBspList():
        for t in bsp.type:
            counts[t.value] += 1
        points.add((bsp.bi.idx, bsp.primary_type.value, bool(bsp.is_buy)))
    return dict(sorted(counts.items())), points


def run_case(code, kt, label):
    from WebAPI.incremental_engine import _compute_full, _load_klus, _make_chan

    print(f"\n=== {label} ===")
    klus = _load_klus(code, kt, "QFQ")
    if not klus:
        print("  DuckDB 无数据，跳过")
        return
    cut = int(len(klus) * 0.8)
    print(f"  K线总数={len(klus):,}  切分点={cut:,}")

    # 路径 B：一次性全量
    chan_b = _make_chan(code, kt, "QFQ")
    chan_b.trigger_load({kt: klus})
    cnt_b, pts_b = result_of(chan_b, kt)

    # 路径 A：前段全量 → 快照 round-trip → 增量推送后段
    chan_a = _make_chan(code, kt, "QFQ")
    chan_a.trigger_load({kt: klus[:cut]})
    fd, path = tempfile.mkstemp(suffix=".chanpkl")
    os.close(fd)
    try:
        chan_a.chan_dump_pickle(path)
        restored = type(chan_a).chan_load_pickle(path)
        restored.trigger_load({kt: klus[cut:]})
        cnt_a, pts_a = result_of(restored, kt)
    finally:
        os.remove(path)

    check(f"{label}: 六类数量一致", cnt_a == cnt_b, f"增量 {cnt_a} / 全量 {cnt_b}")
    check(f"{label}: 逐点集合一致", pts_a == pts_b,
          f"缺 {sorted(pts_b - pts_a)[:5]} / 多 {sorted(pts_a - pts_b)[:5]}")
    del chan_b, chan_a


def main():
    from ChanAnalyse.Common.CEnum import KL_TYPE

    print("=" * 78)
    print("快照恢复 → 增量续算 与 全量计算 的语义等价性")
    print("=" * 78)
    run_case("sh.600007", KL_TYPE.K_5M, "sh.600007 5m（深链原爆点）")
    run_case("sh.600007", KL_TYPE.K_30M, "sh.600007 30m")
    run_case("sz.000001", KL_TYPE.K_DAY, "sz.000001 日线")

    print()
    if FAILURES:
        print(f"✗ {len(FAILURES)} 项失败：{FAILURES}")
        return 1
    print("✓ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
