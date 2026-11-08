# -*- coding: utf-8 -*-
"""
一买极值判据的比较口径验证（原 chan-bsp1-strict-extreme，现 chan-bsp1-loose-extreme）

为什么用桩件而非真实 K 线：**相等极值是不确定事件**。真实行情里「c 段低点与
某前低精确相等」出现频率极低且不可控，用真实数据验证只会得到「没命中
= 通过」的空断言。本脚本直接在判定层构造要素序列，精确控制每一个低点。

**口径已从「严格优」反转为「宽松」**：`standard` 档的 `bs1_peak_strict` 现在
是 `False`，相等极值算创新高/新低（双底、双顶放行）。历史严格优仍可通过
`sout_bi_is_peak(..., strict=True)` 显式复现，脚本保留该分支作对照。

覆盖：
    1.1  `check_new_extreme` 相等极值**放行**（买/卖镜像），更高/未创新低仍拦下
    1.2  `CZS.out_bi_is_peak` 默认宽松、`strict=True` 时严格优
    2.2  `mode="level"` 跨线段取值，`worse_cnt` 大于 `all`

运行（项目根目录）：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe Debug/bsp1_extreme_strict_synth.py

任一断言失败 → 打印失败项并以非零码退出。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ChanAnalyse.BuySellPoint.BSPJudgement import check_new_extreme, get_trend_zs_pair  # noqa: E402
from ChanAnalyse.ZS.ZS import CZS  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        FAILURES.append(name)


# =============================================================================
# 桩件
# =============================================================================

class StubEle:
    """最小要素桩：只有判据用到的 idx / 方向 / 高低点。

    与 `CBi` / `CSeg` 的公共接口对齐（`idx` / `is_down()` / `_low()` / `_high()`），
    这是 `BSPJudgement` 全部纯函数契约要求的字段。
    """

    def __init__(self, idx, low, high, is_down=True):
        self.idx = idx
        self._lo = low
        self._hi = high
        self._down = is_down

    def _low(self):
        return self._lo

    def _high(self):
        return self._hi

    def is_down(self):
        return self._down

    def is_up(self):
        return not self._down

    def get_end_val(self):
        """`out_bi_is_peak` 用它算峰值率，桩件取末端价即可。"""
        return self._lo if self._down else self._hi


class StubZS:
    """最小中枢桩：判据只用 low / high / bi_in。"""

    def __init__(self, low, high, bi_in=None, begin_idx=0, end_idx=0):
        self.low = low
        self.high = high
        self.bi_in = bi_in
        self.begin_bi = StubEle(begin_idx, low, high)
        self.end_bi = StubEle(end_idx, low, high)

    def is_one_bi_zs(self):
        return self.begin_bi.idx == self.end_bi.idx


def zs_pair():
    """构造一对依次下移的中枢，供 `trend_start` 模式定位起点。

    z1 = [10.70, 11.09]，z2 = [10.10, 10.55]，满足 strict（10.55 < 10.70）。
    z1.bi_in 的 idx 即 `trend_start` 的比较起点。
    """
    bi_in1 = StubEle(0, 10.60, 11.20, is_down=True)
    bi_in2 = StubEle(5, 10.50, 11.00, is_down=True)
    z1 = StubZS(10.7042, 11.0926, bi_in=bi_in1, begin_idx=1, end_idx=3)
    z2 = StubZS(10.1074, 10.5527, bi_in=bi_in2, begin_idx=6, end_idx=8)
    return z1, z2


# =============================================================================
# 1.1 相等极值放行（宽松口径，chan-bsp1-loose-extreme）
# =============================================================================

def test_new_extreme_equal():
    print("\n[1.1] check_new_extreme 宽松口径（相等极值也算创新极值）")
    z1, z2 = zs_pair()
    zs_lst = [z1, z2]

    # 前序同向笔：bi10 的低点是 10.0601
    prior = [
        StubEle(10, 10.0601, 10.7232, is_down=True),
        StubEle(11, 10.0601, 11.0075, is_down=False),
    ]

    # 情形 A：c 段低点 == 前低 10.0601 → 放行（宽松口径的核心语义）
    ele_equal = StubEle(12, 10.0601, 11.0000, is_down=True)
    ok, info = check_new_extreme(ele_equal, prior + [ele_equal], zs_lst,
                                 is_buy=True, mode="trend_start")
    check("买点：c 段低点精确等于前低 → ok=True（双底放行）",
          ok is True, f"实际 ok={ok}, info={info}")
    check("买点：相等点不计入 worse_cnt",
          info['worse_cnt'] == 0, f"worse_cnt={info['worse_cnt']}")

    # 情形 B：c 段低点严格更低 → 通过
    ele_lower = StubEle(12, 9.7747, 11.0000, is_down=True)
    ok2, info2 = check_new_extreme(ele_lower, prior + [ele_lower], zs_lst,
                                   is_buy=True, mode="trend_start")
    check("买点：c 段低点严格更低 → ok=True",
          ok2 is True, f"实际 ok={ok2}, info={info2}")
    check("买点：严格更低时 worse_cnt==0",
          info2['worse_cnt'] == 0, f"worse_cnt={info2['worse_cnt']}")

    # 情形 C：c 段低点**更高**（未创新低）→ 仍被拦下，宽松不等于不判
    ele_higher = StubEle(12, 10.2000, 11.0000, is_down=True)
    ok_hi, info_hi = check_new_extreme(ele_higher, prior + [ele_higher], zs_lst,
                                       is_buy=True, mode="trend_start")
    check("买点：c 段低点高于前低 → ok=False（未创新低仍拦下）",
          ok_hi is False, f"实际 ok={ok_hi}, info={info_hi}")

    # 情形 D：卖点镜像，c 段高点 == 前高 → 放行
    prior_up = [
        StubEle(10, 10.0000, 11.0075, is_down=False),
        StubEle(11, 9.8000, 10.5000, is_down=True),
    ]
    ele_up_equal = StubEle(12, 10.2000, 11.0075, is_down=False)
    ok3, info3 = check_new_extreme(ele_up_equal, prior_up + [ele_up_equal], zs_lst,
                                   is_buy=False, mode="trend_start")
    check("卖点：c 段高点精确等于前高 → ok=True（双顶放行）",
          ok3 is True, f"实际 ok={ok3}, info={info3}")

    # 情形 E：卖点 c 段高点严格更高 → 通过
    ele_up_higher = StubEle(12, 10.2000, 11.5000, is_down=False)
    ok4, _ = check_new_extreme(ele_up_higher, prior_up + [ele_up_higher], zs_lst,
                               is_buy=False, mode="trend_start")
    check("卖点：c 段高点严格更高 → ok=True", ok4 is True, f"实际 ok={ok4}")


# =============================================================================
# 1.2 out_bi_is_peak 同一口径
# =============================================================================

def test_out_bi_is_peak_equal():
    print("\n[1.2] CZS.out_bi_is_peak 宽松口径（默认相等也算创新极值）")

    zs = CZS(lst=None, is_sure=True)
    # 手工装配：中枢内 bi10 低点 10.0601，离开笔 bi12 低点与之相等
    bi10 = StubEle(10, 10.0601, 10.7232, is_down=True)
    bi_out_equal = StubEle(12, 10.0601, 11.0000, is_down=True)

    zs._CZS__low = 10.1074
    zs._CZS__high = 10.5527
    zs._CZS__peak_low = 10.0601
    zs._CZS__peak_high = 10.7232
    zs._CZS__bi_lst = [bi10]
    zs._CZS__bi_out = bi_out_equal
    zs._CZS__begin_bi = bi10
    zs._CZS__end_bi = bi10

    ok, _ = zs.out_bi_is_peak(12)
    check("离开笔低点 == 中枢内笔低点 → 默认 is_peak=True（宽松）",
          ok is True, f"实际 {ok}")

    # 历史严格优口径仍可通过显式 strict=True 复现（仅供基线对照）
    ok_strict, _ = zs.out_bi_is_peak(12, strict=True)
    check("同上，strict=True（历史严格优）→ is_peak=False",
          ok_strict is False, f"实际 {ok_strict}")

    # 离开笔严格更低 → 通过
    bi_out_lower = StubEle(12, 9.7747, 11.0000, is_down=True)
    zs._CZS__bi_out = bi_out_lower
    ok2, _ = zs.out_bi_is_peak(12)
    check("离开笔低点严格更低 → is_peak=True", ok2 is True, f"实际 {ok2}")

    # 离开笔更高（未创新低）→ 宽松口径下仍应拦下
    bi_out_higher = StubEle(12, 10.2000, 11.0000, is_down=True)
    zs._CZS__bi_out = bi_out_higher
    ok_hi, _ = zs.out_bi_is_peak(12)
    check("离开笔低点高于中枢内笔低点 → is_peak=False", ok_hi is False, f"实际 {ok_hi}")

    # 卖点镜像
    bi_up_peak = StubEle(10, 10.0000, 11.0075, is_down=False)
    bi_out_up_equal = StubEle(12, 10.2000, 11.0075, is_down=False)
    zs._CZS__bi_lst = [bi_up_peak]
    zs._CZS__bi_out = bi_out_up_equal
    ok3, _ = zs.out_bi_is_peak(12)
    check("卖点：离开笔高点 == 中枢内笔高点 → 默认 is_peak=True", ok3 is True,
          f"实际 {ok3}")

    ok3_strict, _ = zs.out_bi_is_peak(12, strict=True)
    check("卖点：同上，strict=True → is_peak=False",
          ok3_strict is False, f"实际 {ok3_strict}")

    bi_out_up_higher = StubEle(12, 10.2000, 11.5000, is_down=False)
    zs._CZS__bi_out = bi_out_up_higher
    ok4, _ = zs.out_bi_is_peak(12)
    check("卖点：离开笔高点严格更高 → is_peak=True", ok4 is True, f"实际 {ok4}")


# =============================================================================
# 2.2 level 模式跨线段
# =============================================================================

def test_level_mode():
    print("\n[2.2] mode=level 跨线段取值")

    z1, z2 = zs_pair()
    zs_lst = [z1, z2]

    # 该点所在线段的笔（ele_list 只含线段内），另有一段更早的笔在 ele_list 之外
    seg_ele_list = [
        StubEle(10, 10.0601, 10.7232, is_down=True),
    ]
    # 全量笔列表：更早的线段里有一个更低的低点 9.4262
    full_ele_list = [
        StubEle(5, 9.4262, 10.7934, is_down=True),     # 上一线段
        StubEle(9, 9.9659, 10.8293, is_down=True),     # 上一线段
    ] + seg_ele_list

    ele = StubEle(12, 9.7747, 11.0000, is_down=True)

    # all 只看 ele_list 内部 → 只有 bi10（10.0601 < 9.7747 不成立）→ 通过
    ok_all, info_all = check_new_extreme(ele, seg_ele_list + [ele], zs_lst,
                                         is_buy=True, mode="all")
    # level 看全量 → 多了 9.4262 这个更低点 → 不通过
    ok_level, info_level = check_new_extreme(ele, full_ele_list + [ele], zs_lst,
                                             is_buy=True, mode="level")

    check("all 模式：只看线段内 → 通过", ok_all is True, f"实际 ok={ok_all}, {info_all}")
    check("level 模式：跨线段看到更早低点 → 不通过",
          ok_level is False, f"实际 ok={ok_level}, {info_level}")
    check("level 的 worse_cnt 大于 all",
          info_level['worse_cnt'] > info_all['worse_cnt'],
          f"level={info_level['worse_cnt']} vs all={info_all['worse_cnt']}")


def main():
    test_new_extreme_equal()
    test_out_bi_is_peak_equal()
    test_level_mode()

    print()
    if FAILURES:
        print(f"✗ {len(FAILURES)} 项失败：{FAILURES}")
        return 1
    print("✓ 全部断言通过")
    return 0


if __name__ == '__main__':
    sys.exit(main())
