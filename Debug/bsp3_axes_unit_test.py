# -*- coding: utf-8 -*-
"""T3 确认轴（缠论要素 E）单元验证 —— chan-standard-bsp3-change task 3.1。

用法：
    .venv/Scripts/python.exe Debug/bsp3_axes_unit_test.py

覆盖四档各自触发路径、买卖镜像、终态单向性（窗口外数据不可达）、
以及「缺锚定中枢 feature 时跳过证伪判定不猜」。

桩对象沿用 `Debug/bsp2_axes_unit_test.py` 的 StubBi / StubBsp 模式。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from WebAPI.bsp3_confirm import confirm_axis  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print(f"  [OK] {name}")
    else:
        print(f"  [FAIL] {name}  {detail}")
        FAILS.append(name)


class StubBi:
    """可控价格桩：方向由 is_down 决定，端点由 (lo, hi) 决定。"""

    def __init__(self, idx, lo, hi, is_down):
        self.idx = idx
        self.lo = lo
        self.hi = hi
        self._down = is_down
        self.seg_idx = 0

    def is_down(self):
        return self._down

    def is_up(self):
        return not self._down

    def amp(self):
        return abs(self.hi - self.lo)

    def _low(self):
        return self.lo

    def _high(self):
        return self.hi

    def get_begin_val(self):
        return self.hi if self._down else self.lo

    def get_end_val(self):
        return self.lo if self._down else self.hi


class StubBsp:
    def __init__(self, bi, is_buy=True, features=None):
        self.bi = bi
        self.is_buy = is_buy
        self.features = features or {}

    def items(self):  # features 用 dict，但保持与 CFeatures 一致的取值方式
        return self.features.items()


class StubFeat:
    """模拟 CFeatures：`.items()` 返回特征字典项。"""

    def __init__(self, d):
        self._d = d

    def items(self):
        return self._d.items()


class StubCfg:
    bsp3_confirm_window = 2
    bsp3_confirm_level = "strong"


class StubBspFeat(StubBsp):
    def __init__(self, bi, is_buy=True, feat=None):
        super().__init__(bi, is_buy)
        self.features = StubFeat(feat or {})


# ----------------------------------------------------------------------
# 买侧场景：中枢 [10.0, 11.0]，回抽笔 idx2（跌 13.0 → 11.4，起点 13.0）
# 回抽笔起点 13.0 = 确认阈值；收复线 = 13.0 - 0.5*1.6 = 12.2
# ----------------------------------------------------------------------
ZS = {"bsp3_zs_low": 10.0, "bsp3_zs_high": 11.0}


def buy_list(follow):
    lst = [
        StubBi(0, 10.0, 11.0, is_down=True),
        StubBi(1, 11.0, 13.0, is_down=False),   # 离开笔（向上突破）
        StubBi(2, 11.4, 13.0, is_down=True),    # 回抽笔（三买所在笔）
    ]
    for k, (lo, hi, dn) in enumerate(follow):
        lst.append(StubBi(3 + k, lo, hi, is_down=dn))
    return lst


def test_buy():
    print("\n[买侧]")
    # C3：窗口内上升笔高点 13.5 >= 13.0
    bl = buy_list([(11.5, 13.5, False), (11.6, 11.8, True)])
    check("突破回抽端点 → C3", confirm_axis(StubBspFeat(bl[2], True, ZS), bl, StubCfg()) == "C3")

    # C2：高点 12.5 >= 12.2 但 < 13.0
    bl = buy_list([(11.5, 12.5, False), (11.6, 11.8, True)])
    check("收复一半 → C2", confirm_axis(StubBspFeat(bl[2], True, ZS), bl, StubCfg()) == "C2")

    # C1：跌回中枢（低点 10.5 < 上沿 11.0）
    bl = buy_list([(10.5, 11.7, False), (10.6, 10.8, True)])
    check("跌回中枢 → C1 证伪", confirm_axis(StubBspFeat(bl[2], True, ZS), bl, StubCfg()) == "C1")

    # C1：窗口走完未收复一半（最高 11.8 < 12.2，且未跌回中枢）
    bl = buy_list([(11.5, 11.8, False), (11.6, 11.9, True)])
    check("未收复且未失守 → C1", confirm_axis(StubBspFeat(bl[2], True, ZS), bl, StubCfg()) == "C1")

    # C0：窗口 2 笔但数据只有 1 笔
    bl = buy_list([(11.5, 11.8, False)])
    check("窗口不足 → C0", confirm_axis(StubBspFeat(bl[2], True, ZS), bl, StubCfg()) == "C0")

    # 终态单向性：窗口 2 内 C1，窗口外第 3 笔创新高 14.5 → 仍 C1
    bl = buy_list([(11.5, 11.8, False), (11.6, 11.9, True), (11.7, 14.5, False)])
    check("窗口外新高不翻 → C1", confirm_axis(StubBspFeat(bl[2], True, ZS), bl, StubCfg()) == "C1")

    # weak 口径：收复一半即确认 → C3
    cfg = StubCfg()
    cfg.bsp3_confirm_level = "weak"
    bl = buy_list([(11.5, 12.5, False), (11.6, 11.8, True)])
    check("weak 口径 → C3", confirm_axis(StubBspFeat(bl[2], True, ZS), bl, cfg) == "C3")

    # 缺锚定中枢 feature：跳过证伪判定，只按价格档，不猜 → C1
    bl = buy_list([(11.5, 11.8, False), (11.6, 11.9, True)])
    check("缺 zs feature 不猜 → C1", confirm_axis(StubBspFeat(bl[2], True, {}), bl, StubCfg()) == "C1")


# ----------------------------------------------------------------------
# 卖侧镜像：中枢 [12.0, 13.0]，回抽笔（向上）起点 10.0
# 确认阈值 10.0（跌破）；收复线 = 10.0 + 0.5*2.0 = 11.0
# ----------------------------------------------------------------------
ZS_SELL = {"bsp3_zs_low": 12.0, "bsp3_zs_high": 13.0}


def sell_list(follow):
    lst = [
        StubBi(0, 12.0, 13.0, is_down=False),
        StubBi(1, 10.0, 12.0, is_down=True),    # 离开笔（向下突破）
        StubBi(2, 10.0, 12.0, is_down=False),   # 回抽笔（向上，三卖所在笔）
    ]
    for k, (lo, hi, dn) in enumerate(follow):
        lst.append(StubBi(3 + k, lo, hi, is_down=dn))
    return lst


def test_sell():
    print("\n[卖侧镜像]")
    # C3：窗口内下跌笔低点 9.5 <= 10.0
    bl = sell_list([(9.5, 11.5, True), (10.5, 11.2, False)])
    check("跌破回抽端点 → C3", confirm_axis(StubBspFeat(bl[2], False, ZS_SELL), bl, StubCfg()) == "C3")

    # C2：低点 10.6 <= 11.0 但 > 10.0
    bl = sell_list([(10.6, 11.5, True), (10.5, 11.2, False)])
    check("收复一半 → C2", confirm_axis(StubBspFeat(bl[2], False, ZS_SELL), bl, StubCfg()) == "C2")

    # C1：涨回中枢（高点 12.5 > 下沿 12.0）
    bl = sell_list([(10.8, 12.5, True), (11.0, 11.4, False)])
    check("涨回中枢 → C1 证伪", confirm_axis(StubBspFeat(bl[2], False, ZS_SELL), bl, StubCfg()) == "C1")

    # C0
    bl = sell_list([(10.6, 11.5, True)])
    check("窗口不足 → C0", confirm_axis(StubBspFeat(bl[2], False, ZS_SELL), bl, StubCfg()) == "C0")


if __name__ == "__main__":
    test_buy()
    test_sell()
    print()
    if FAILS:
        print(f"失败 {len(FAILS)} 项：{FAILS}")
        sys.exit(1)
    print("全部通过")
