# -*- coding: utf-8 -*-
"""
bsp_ladder 四级推导冒烟测试（bsp-ladder-change 任务 1.1 验证）。

合成对象直测 cal_ladder / cal_l1_resonance / ladder_of_legacy 的四条路径：
L4（水位线确认）、L3（前前笔力度背驰）、L1（子级别同向共振）、L2（兜底）。
不触真实 CChan/PG/DuckDB，纯内存。

运行（项目根目录）：
    .venv/bin/python Debug/bsp_ladder_smoke.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from WebAPI.bsp_ladder import (
    DIVERGENCE_RATE,
    cal_l1_resonance,
    cal_ladder,
    ladder_of_legacy,
)


class _FakeKlu:
    def __init__(self, ts, low=10.0, high=11.0):
        self.ts = ts
        self.low = low
        self.high = high


class _FakeTime:
    def __init__(self, ts):
        self.ts = ts


# klu.time 为 CTime（含 .ts）；_FakeKlu 直接挂 time 属性
def _klu(ts):
    klu = _FakeKlu(ts)
    klu.time = _FakeTime(ts)
    return klu


class _FakeBi:
    """合成笔：idx / dir / 力度指标可控。"""

    def __init__(self, idx, is_down, in_metric=10.0, out_metric=9.0):
        self.idx = idx
        self.dir = "down" if is_down else "up"
        self._in = in_metric
        self._out = out_metric

    def cal_macd_metric(self, macd_algo, is_reverse=False):
        return self._out if is_reverse else self._in


class _FakeBsp:
    def __init__(self, bi, is_buy=True, klu=None):
        self.bi = bi
        self.is_buy = is_buy
        self.klu = klu or _klu(1000000)


class _FakeBspList:
    def __init__(self, last_sure_pos):
        self.last_sure_pos = last_sure_pos


def _bi_in_range(bsp, fake_list):
    """bypass: bsp_is_sure 走 bsp.bi.get_end_klu().idx —— 合成 bi 挂 get_end_klu。"""
    return bsp.bi.get_end_klu().idx <= fake_list.last_sure_pos


# 给 _FakeBi 挂 get_end_klu（bsp_is_sure 的接口面）
def _attach_end_klu(bi, idx):
    end = type("E", (), {})()
    end.idx = idx
    bi.get_end_klu = lambda: end
    return bi


def main() -> int:
    results = []

    # ---- L4：is_sure=True → L4 ----
    bi = _attach_end_klu(_FakeBi(4, True), 10)
    bsp = _FakeBsp(bi)
    lst = _FakeBspList(last_sure_pos=12)
    r = cal_ladder(bsp, lst, bi_list=[_FakeBi(0, True), _FakeBi(1, False), _FakeBi(2, True), _FakeBi(3, False), bi])
    results.append(("L4 sure", r == "L4", r))

    # ---- L3：未确认 + 出笔力度 <= 0.9 × 入笔力度 ----
    bi = _attach_end_klu(_FakeBi(4, True), 10)
    bsp = _FakeBsp(bi)
    lst = _FakeBspList(last_sure_pos=5)  # end_idx=10 > 5 → 未确认
    # 前前笔 idx=2 同向 down；出笔 8.0 <= 0.9*10=9.0 → 背驰
    bi2 = _FakeBi(2, True, in_metric=10.0, out_metric=10.0)
    bi4 = _FakeBi(4, True, in_metric=10.0, out_metric=8.0)
    bi4 = _attach_end_klu(bi4, 10)
    bsp = _FakeBsp(bi4)
    bi_list = [_FakeBi(0, True), _FakeBi(1, False), bi2, _FakeBi(3, False), bi4]
    r = cal_ladder(bsp, lst, bi_list=bi_list, sub_bsps=[])  # sub 空也给，L3 应先命中
    results.append(("L3 beichi", r == "L3", r))

    # ---- L3 不触发：出笔力度 9.5 > 0.9*10 → 无背驰 → 走 L1/L2 ----
    bi4b = _attach_end_klu(_FakeBi(4, True, out_metric=9.5), 10)
    bsp_b = _FakeBsp(bi4b)
    bi_list_b = [_FakeBi(0, True), _FakeBi(1, False), bi2, _FakeBi(3, False), bi4b]
    r = cal_ladder(bsp_b, lst, bi_list=bi_list_b)
    results.append(("no-beichi falls L2", r == "L2", r))

    # ---- L1：无背驰 + 子级别同向买点在窗口内 → L1 ----
    sub = type("S", (), {})()
    sub.is_buy = True
    sub.klu = _klu(1000000 + 2 * 86400)  # 2 天后，窗口内
    r = cal_ladder(bsp_b, lst, bi_list=bi_list_b, sub_bsps=[sub])
    results.append(("L1 resonance", r == "L1", r))

    # ---- L1 反向不共振：子级别卖点（反向）不算 ----
    sub2 = type("S", (), {})()
    sub2.is_buy = False
    sub2.klu = _klu(1000000)
    r = cal_l1_resonance(bsp_b, [sub2])
    results.append(("L1 opposite-dir no resonance", r is False, r))

    # ---- L1 窗口外不共振：15 天前 ----
    sub3 = type("S", (), {})()
    sub3.is_buy = True
    sub3.klu = _klu(1000000 - 15 * 86400)
    r = cal_l1_resonance(bsp_b, [sub3])
    results.append(("L1 out-of-window no resonance", r is False, r))

    # ---- sub_bsps=None → 不计算 L1（落库链路 D3）→ L2 ----
    r = cal_ladder(bsp_b, lst, bi_list=bi_list_b, sub_bsps=None)
    results.append(("sub=None falls L2 (ingest path)", r == "L2", r))

    # ---- L1 佐证须子级 L4（D3 修订三）：子级点 is_sure=False → 不共振 ----
    # sub_sure：子级买点在窗口内但未确认（end_idx=10 > 子级水位线 5）
    sub_sure = type("S", (), {})()
    sub_sure.is_buy = True
    sub_sure.klu = _klu(1000000 + 2 * 86400)
    sub_sure.bi = _attach_end_klu(_FakeBi(4, True), 10)
    sub_lst_unsure = _FakeBspList(last_sure_pos=5)
    r = cal_l1_resonance(bsp_b, [sub_sure], sub_bs_point_lst=sub_lst_unsure)
    results.append(("L1 sub-unsure no resonance", r is False, r))

    # ---- L1 佐证子级 L4 成立：子级点 is_sure=True（end_idx <= 水位线）→ 共振 ----
    sub_lst_sure = _FakeBspList(last_sure_pos=12)
    r = cal_l1_resonance(bsp_b, [sub_sure], sub_bs_point_lst=sub_lst_sure)
    results.append(("L1 sub-L4 resonance", r is True, r))

    # ---- L1 佐证窗口键按级别对（D3 修订二）：分钟级窄窗 2h，3h 外不共振 ----
    from ChanAnalyse.Common.CEnum import KL_TYPE

    sub_5m = type("S", (), {})()
    sub_5m.is_buy = True
    sub_5m.klu = _klu(1000000 + 3 * 3600)  # 3 小时后，超出 30m←5m 的 ±2h 窗
    sub_5m.bi = _attach_end_klu(_FakeBi(4, True), 10)
    r = cal_l1_resonance(
        bsp_b, [sub_5m],
        kl_type=KL_TYPE.K_30M, sub_kl_type=KL_TYPE.K_5M,
        sub_bs_point_lst=sub_lst_sure,
    )
    results.append(("L1 minute-window 3h out no resonance", r is False, r))
    sub_5m.klu = _klu(1000000 + 3600)  # 1 小时后，窗内
    r = cal_l1_resonance(
        bsp_b, [sub_5m],
        kl_type=KL_TYPE.K_30M, sub_kl_type=KL_TYPE.K_5M,
        sub_bs_point_lst=sub_lst_sure,
    )
    results.append(("L1 minute-window 1h in resonance", r is True, r))

    # ---- L3 优先于 L1（同时成立）----
    bi4c = _attach_end_klu(_FakeBi(4, True, out_metric=8.0), 10)
    bsp_c = _FakeBsp(bi4c)
    bi_list_c = [_FakeBi(0, True), _FakeBi(1, False), bi2, _FakeBi(3, False), bi4c]
    r = cal_ladder(bsp_c, lst, bi_list=bi_list_c, sub_bsps=[sub])
    results.append(("L3 priority over L1", r == "L3", r))

    # ---- 前前笔方向不一致 → 不背驰 ----
    bi_up_pre = _FakeBi(2, False, in_metric=10.0, out_metric=10.0)
    bi_list_d = [_FakeBi(0, True), _FakeBi(1, False), bi_up_pre, _FakeBi(3, False), bi4c]
    r = cal_ladder(bsp_c, lst, bi_list=bi_list_d)
    results.append(("pre-bi dir mismatch no beichi", r == "L2", r))

    # ---- idx 不足（idx=1，无前前笔）→ 不背驰 ----
    bi1 = _attach_end_klu(_FakeBi(1, True, out_metric=1.0), 10)
    bsp_e = _FakeBsp(bi1)
    r = cal_ladder(bsp_e, lst, bi_list=[_FakeBi(0, True), bi1])
    results.append(("no pre-pre bi no beichi", r == "L2", r))

    # ---- 存量兜底映射 ----
    results.append(("legacy true→L4", ladder_of_legacy(True) == "L4", ladder_of_legacy(True)))
    results.append(("legacy false→L2", ladder_of_legacy(False) == "L2", ladder_of_legacy(False)))

    # ---- 阈值常量暴露（可调性）----
    results.append(("threshold sane", 0 < DIVERGENCE_RATE <= 1, DIVERGENCE_RATE))

    ok = True
    for name, passed, val in results:
        print(f"[{'PASS' if passed else 'FAIL'}] {name}: {val}")
        ok = ok and passed
    print(f"\n== bsp_ladder 冒烟: {sum(1 for _, p, _ in results if p)}/{len(results)} PASS ==")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
