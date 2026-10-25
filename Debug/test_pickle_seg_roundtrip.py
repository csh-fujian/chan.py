# -*- coding: utf-8 -*-
"""pickle 深链修复的验收（只读计算，不写 PG）。

覆盖三件事：

  1. **原失败对象可序列化**：`sh.600007 5m`（385 段，修复前 3746 层 → 爆）
  2. **round-trip 无损**：dump → load 后 parent_seg 全部重建且指向正确，
     笔/线段/中枢/买卖点数量与计算完毕的对象逐项相同
  3. **旧快照向后兼容**：`parent_seg` 完整序列化的旧格式加载后，
     幂等重建不改变结果

运行：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe Debug/test_pickle_seg_roundtrip.py
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


def snapshot(chan, kt):
    """把可比较的量抽成 dict（不依赖对象身份）。"""
    kl = chan.kl_datas[kt]
    return {
        'klu': sum(len(k.lst) for k in kl.lst),
        'klc': len(kl.lst),
        'bi': len(kl.bi_list),
        'seg': len(kl.seg_list),
        'segseg': len(kl.segseg_list),
        'zs': len(kl.zs_list),
        'bsp': len(kl.bs_point_lst.getSortedBspList()),
        'seg_bsp': len(kl.seg_bs_point_lst.getSortedBspList()),
    }


def check_parent_links(chan, kt, label):
    """parent_seg 全部就位，且与所属容器的成员关系互相对得上。"""
    kl = chan.kl_datas[kt]
    bi_null = 0
    bi_bad = 0
    for bi in kl.bi_list:
        ps = bi.parent_seg
        if ps is None:
            bi_null += 1
            continue
        if not any(x is bi for x in ps.bi_list):
            bi_bad += 1
    seg_null = 0
    seg_bad = 0
    for seg in kl.seg_list:
        ps = seg.parent_seg
        if ps is None:
            seg_null += 1
            continue
        if not any(x is seg for x in ps.bi_list):
            seg_bad += 1
    check(f"{label}: 所有笔的 parent_seg 已就位", bi_null == 0, f"{bi_null} 个为 None")
    check(f"{label}: 笔的 parent_seg 反查一致", bi_bad == 0, f"{bi_bad} 个不一致")
    check(f"{label}: 所有线段的 parent_seg 已就位", seg_null == 0, f"{seg_null} 个为 None")
    check(f"{label}: 线段的 parent_seg 反查一致", seg_bad == 0, f"{seg_bad} 个不一致")


def roundtrip_case(code, kt, label):
    from WebAPI.incremental_engine import _compute_full

    print(f"\n=== {label} ===")
    chan = _compute_full(code, kt, "QFQ")
    if chan is None:
        print("  DuckDB 无数据，跳过")
        return
    before = snapshot(chan, kt)
    check_parent_links(chan, kt, f"{label} 导出前")

    fd, path = tempfile.mkstemp(suffix=".chanpkl")
    os.close(fd)
    try:
        chan.chan_dump_pickle(path)
        size = os.path.getsize(path)
        print(f"  dump 成功  bytes={size:,}")

        # 导出后内存对象必须完好（pre/next、parent_seg 都恢复了）
        check_parent_links(chan, kt, f"{label} 导出后内存对象")
        check(f"{label}: 导出后 pre/next 已恢复",
              chan.kl_datas[kt].bi_list[5].pre is chan.kl_datas[kt].bi_list[4])

        loaded = type(chan).chan_load_pickle(path)
        after = snapshot(loaded, kt)
        check(f"{label}: round-trip 数量逐项一致", before == after,
              f"前 {before} / 后 {after}")
        check_parent_links(loaded, kt, f"{label} 加载后")
        check(f"{label}: 加载后 pre/next 已恢复",
              loaded.kl_datas[kt].bi_list[5].pre is loaded.kl_datas[kt].bi_list[4])
        # parent_seg 必须指向**加载后**的对象，而不是序列化前的原对象
        seg0 = loaded.kl_datas[kt].seg_list[0]
        check(f"{label}: parent_seg 指向加载后的对象（非旧对象）",
              seg0.bi_list[0].parent_seg is seg0)
    finally:
        if os.path.exists(path):
            os.remove(path)
    del chan


def legacy_compat_case():
    """旧快照（parent_seg 完整序列化）加载后幂等重建。"""
    import pickle
    from ChanAnalyse.Common.CEnum import KL_TYPE
    from WebAPI.incremental_engine import _compute_full

    print("\n=== 旧快照向后兼容 ===")
    kt = KL_TYPE.K_DAY
    chan = _compute_full("sz.000001", kt, "QFQ")
    kl = chan.kl_datas[kt]
    before = [id(bi.parent_seg) for bi in kl.bi_list]

    # 模拟旧格式：直接 pickle 一棵含 parent_seg 的图（不做任何摘除）
    fd, path = tempfile.mkstemp(suffix=".chanpkl")
    os.close(fd)
    saved_iter = chan.g_kl_iter
    from collections import defaultdict
    chan.g_kl_iter = defaultdict(list)
    try:
        # pre/next 仍要摘（否则会与旧版本一样爆），但 parent_seg 保留
        for klu in (u for k in kl.lst for u in k.lst):
            klu.pre = klu.next = None
        for k in kl.lst:
            k.set_pre(None)
            k.set_next(None)
        for bi in kl.bi_list:
            bi.pre = bi.next = None
        for s in kl.seg_list:
            s.pre = s.next = None
        with open(path, "wb") as f:
            pickle.dump(chan, f)
        legacy_ok = True
    except RecursionError:
        legacy_ok = False
    finally:
        chan.g_kl_iter = saved_iter

    check("旧格式快照可生成", legacy_ok)
    if legacy_ok:
        loaded = type(chan).chan_load_pickle(path)
        lkl = loaded.kl_datas[kt]
        ok = all(
            bi.parent_seg is not None and any(x is bi for x in bi.parent_seg.bi_list)
            for bi in lkl.bi_list
        )
        check("旧快照加载后 parent_seg 指向正确", ok)
        check("旧快照加载后数量一致", len(lkl.bi_list) == len(kl.bi_list))
        # 幂等：再调一次 restore 不应改变任何东西
        loaded.chan_pickle_restore()
        ok2 = all(
            bi.parent_seg is not None and any(x is bi for x in bi.parent_seg.bi_list)
            for bi in lkl.bi_list
        )
        check("重复 restore 幂等", ok2)
    os.remove(path)
    del chan


def main():
    from ChanAnalyse.Common.CEnum import KL_TYPE

    print("=" * 78)
    print("pickle 深链（parent_seg）修复验收")
    print("=" * 78)
    roundtrip_case("sh.600007", KL_TYPE.K_5M, "sh.600007 5m（修复前 RecursionError）")
    roundtrip_case("sh.600007", KL_TYPE.K_30M, "sh.600007 30m（对照组）")
    roundtrip_case("sz.000001", KL_TYPE.K_DAY, "sz.000001 日线（对照组）")
    legacy_compat_case()

    print()
    if FAILURES:
        print(f"✗ {len(FAILURES)} 项失败：{FAILURES}")
        return 1
    print("✓ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
