# -*- coding: utf-8 -*-
"""sh.600007 5m pickle RecursionError 的归因探针（只读，不写库）。

要回答的三件事：
  1. 失败是「对象图太深」还是「K 线根数太多」；
  2. 那条深链由什么对象构成；
  3. 5m 没有 1 分钟子级别数据是不是诱因。

方法：
  - **必须复刻 `CChan.chan_dump_pickle` 的清理步骤**（摘 pre/next、清 g_kl_iter），
    否则测到的是未清理的裸图——裸图里有 klu.pre/next 双向链和已耗尽的生成器，
    深度与真实 dump 路径无关。
  - C 实现的 `_pickle.Pickler` 在 3.12 有独立于 `sys.setrecursionlimit` 的 C 栈
    上限（`Py_C_RECURSION_LIMIT` ≈ 1500），所以同时用纯 Python
    `pickle._Pickler` 才量得出真实嵌套深度。
  - 加对照组：日线（回刷时成功）vs 5m（失败），判断差异是规模还是结构。

运行：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe Debug/diag_pickle_depth.py
"""

import io
import os
import pickle
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PURE_PICKLER = getattr(pickle, "_Pickler", None)


def _descr(obj):
    cls = type(obj)
    bits = []
    for attr in ("idx", "kl_type"):
        try:
            bits.append(f"{attr}={getattr(obj, attr)!r}")
        except Exception:
            pass
    try:
        if cls.__name__ == "CKLine_Unit":
            bits.append(f"time={obj.time}")
    except Exception:
        pass
    return cls.__name__ + ("(" + " ".join(bits) + ")" if bits else "")


def clean(chan):
    """复刻 chan_dump_pickle 的清理，返回恢复函数。"""
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
    saved_iter = chan.g_kl_iter
    chan.g_kl_iter = defaultdict(list)

    def restore():
        chan.g_kl_iter = saved_iter
    return restore


class TracingPickler(PURE_PICKLER):
    """纯 Python pickler + 嵌套深度追踪 + 最深路径。"""

    def __init__(self, f, protocol):
        super().__init__(f, protocol)
        self.depth = 0
        self.max_depth = 0
        self.path = []          # 当前路径
        self.deepest = []       # 最深时的路径副本

    def save(self, obj, save_persistent_id=True):
        self.depth += 1
        self.path.append(_descr(obj))
        if self.depth > self.max_depth:
            self.max_depth = self.depth
            self.deepest = list(self.path)
        try:
            return super().save(obj, save_persistent_id=save_persistent_id)
        finally:
            self.path.pop()
            self.depth -= 1


def measure(chan, label):
    kl = chan.kl_datas[chan.lv_list[0]]
    n_klu = sum(len(k.lst) for k in kl.lst)
    print(f"\n=== {label} ===")
    print(f"  原始K线={n_klu:,}  合并K线={len(kl.lst):,}  笔={len(kl.bi_list)}  "
          f"线段={len(kl.seg_list)}  中枢={len(kl.zs_list)}  "
          f"买卖点={len(kl.bs_point_lst.getSortedBspList())}")

    restore = clean(chan)
    try:
        # ① C pickler（就是 chan_dump_pickle 实际走的路）
        buf = io.BytesIO()
        old = sys.getrecursionlimit()
        sys.setrecursionlimit(0x100000)
        ok_c = True
        try:
            pickle.dump(chan, buf, protocol=pickle.HIGHEST_PROTOCOL)
        except RecursionError as e:
            ok_c = False
            print(f"  C pickler RecursionError: {e}")
        except Exception as e:
            ok_c = False
            print(f"  C pickler {type(e).__name__}: {e}")
        finally:
            sys.setrecursionlimit(old)
        if ok_c:
            print(f"  C pickler OK  bytes={len(buf.getvalue()):,}")

        # ② 纯 Python pickler（量真实嵌套深度）
        buf2 = io.BytesIO()
        p = TracingPickler(buf2, pickle.HIGHEST_PROTOCOL)
        old = sys.getrecursionlimit()
        sys.setrecursionlimit(0x100000)
        ok_py = True
        try:
            p.dump(chan)
        except RecursionError as e:
            ok_py = False
            print(f"  纯Python pickler RecursionError: {e}")
        except Exception as e:
            ok_py = False
            print(f"  纯Python pickler {type(e).__name__}: {e}")
        finally:
            sys.setrecursionlimit(old)
        print(f"  最大嵌套深度={p.max_depth}  纯Python可完成={ok_py}")
        if ok_py:
            print(f"  纯Python bytes={len(buf2.getvalue()):,}")
        return dict(n=n_klu, depth=p.max_depth, ok_c=ok_c, ok_py=ok_py,
                    deepest=p.deepest)
    finally:
        restore()


def main():
    from ChanAnalyse.Common.CEnum import KL_TYPE
    from WebAPI.incremental_engine import _compute_full

    cases = [
        ("sh.600007 5m（回刷时失败）", "sh.600007", KL_TYPE.K_5M),
        ("sh.600007 30m（回刷时成功）", "sh.600007", KL_TYPE.K_30M),
        ("sz.000001 D（回刷时成功）", "sz.000001", KL_TYPE.K_DAY),
    ]
    rows = []
    for label, code, kt in cases:
        chan = _compute_full(code, kt, "QFQ")
        if chan is None:
            print(f"\n=== {label} ===  DuckDB 无数据，跳过")
            continue
        r = measure(chan, label)
        r["label"] = label
        r["kt"] = kt.name
        rows.append(r)
        del chan

    print("\n" + "=" * 74)
    print("汇总：深度是否随 K 线根数增长")
    print("=" * 74)
    print(f"{'标的':<30}{'级别':<7}{'原始K线':>9}{'最大深度':>9}{'C可pickle':>11}")
    for r in rows:
        print(f"{r['label']:<30}{r['kt']:<7}{r['n']:>9,}{r['depth']:>9}{str(r['ok_c']):>11}")

    for r in rows:
        if r["deepest"]:
            print(f"\n最深路径片段（{r['label']}，深度 {r['depth']}，只显示尾部 18 层）：")
            for i, step in enumerate(r["deepest"][-18:], len(r["deepest"]) - 17):
                print(f"  {i:>4}. {step}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
