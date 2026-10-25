# -*- coding: utf-8 -*-
"""pickle 深度与「数据长度 / 线段数」的定量关系（只读）。

上一轮已测出：嵌套深度 ≈ 10 × 线段数
  sh.600007 5m  385 段 → 3746 层（失败）
  sh.600007 30m  70 段 → 733 层（成功）
  sz.000001 D    59 段 → 611 层（成功）

本脚本回答两件事：
  ① 截断 5m 数据到不同长度时，线段数与深度怎么走 —— 找出「多长会爆」的分界；
  ② 摘除 `CBi.parent_seg` 后深度降到多少 —— 确认深链是否由
     `CSeg.eigen_fx → CEigen → CBi → parent_seg → CSeg(next)` 构成。

  PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe Debug/diag_pickle_growth.py
"""

import io
import os
import pickle
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CODE = "sh.600007"
PURE_PICKLER = getattr(pickle, "_Pickler", None)


class TracingPickler(PURE_PICKLER):
    def __init__(self, f, protocol):
        super().__init__(f, protocol)
        self.depth = 0
        self.max_depth = 0

    def save(self, obj, save_persistent_id=True):
        self.depth += 1
        if self.depth > self.max_depth:
            self.max_depth = self.depth
        try:
            return super().save(obj, save_persistent_id=save_persistent_id)
        finally:
            self.depth -= 1


def clean(chan):
    for kl_list in chan.kl_datas.values():
        for klc in kl_list.lst:
            for klu in klc.lst:
                klu.pre = None
                klu.next = None
            klc.set_pre(None)
            klc.set_next(None)
        for bi in kl_list.bi_list:
            bi.pre = None
            bi.next = None
        for seg in kl_list.seg_list:
            seg.pre = None
            seg.next = None
        lst = getattr(kl_list, "bs_point_lst", None)
        if lst is not None:
            lst.sub_bs_point_lst = None
    saved = chan.g_kl_iter
    chan.g_kl_iter = defaultdict(list)
    return saved


def depth_of(chan):
    """返回 (max_depth, c_pickler_ok)。调用方须已 clean。"""
    import io as _io
    buf = _io.BytesIO()
    ok = True
    try:
        pickle.dump(chan, buf, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        ok = False
    buf2 = _io.BytesIO()
    p = TracingPickler(buf2, pickle.HIGHEST_PROTOCOL)
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(0x100000)
    try:
        p.dump(chan)
    except RecursionError:
        pass
    finally:
        sys.setrecursionlimit(old)
    return p.max_depth, ok


def build(n_klu=None):
    from ChanAnalyse.Common.CEnum import KL_TYPE
    from WebAPI.incremental_engine import _load_klus, _make_chan

    kt = KL_TYPE.K_5M
    klus = _load_klus(CODE, kt, "QFQ")
    if n_klu:
        klus = klus[:n_klu]
    chan = _make_chan(CODE, kt, "QFQ")
    chan.trigger_load({kt: klus})
    return chan, kt, len(klus)


def main():
    rows = []
    for n in (10000, 20000, 30000, 45000, 60000, 78528):
        chan, kt, actual = build(n)
        kl = chan.kl_datas[kt]
        n_seg = len(kl.seg_list)
        n_bi = len(kl.bi_list)
        saved = clean(chan)
        d, ok = depth_of(chan)
        print(f"  K线={actual:>6,}  笔={n_bi:>5}  线段={n_seg:>4}  深度={d:>6}  "
              f"C可pickle={ok}")
        rows.append((actual, n_bi, n_seg, d, ok))

        # 只在全量那一次做根因探针：摘除 CBi.parent_seg
        if n == 78528:
            # 注意：保存的副本必须挂在**探针自己的局部变量**上。早先版本把原值
            # 存回 `bi._saved_parent_seg` 再置 None——原值是 CSeg，等于没摘，
            # 深度自然纹丝不动（得到一个假的「摘除无效」结论）。
            saved_refs = []
            for bi in kl.bi_list:
                if bi.parent_seg is not None:
                    saved_refs.append((bi, bi.parent_seg))
                    bi.parent_seg = None
            d2, ok2 = depth_of(chan)
            print(f"  [根因探针] 摘除 {len(saved_refs)} 个 CBi.parent_seg → 深度={d2}  "
                  f"C可pickle={ok2}")
            for bi, seg in saved_refs:
                bi.parent_seg = seg
        chan.g_kl_iter = saved
        del chan

    print("\n" + "=" * 70)
    print("深度 / 线段数 比值（看是否稳定）")
    print("=" * 70)
    for n, n_bi, n_seg, d, ok in rows:
        ratio = d / n_seg if n_seg else 0
        print(f"  K线={n:>6,}  线段={n_seg:>4}  深度={d:>6}  比值={ratio:>6.2f}  ok={ok}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
