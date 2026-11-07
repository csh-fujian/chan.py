# -*- coding: utf-8 -*-
"""配置系统冒烟自测 —— CChanConfig / CPointConfig 参数与后缀覆盖。

覆盖点：
  1. 默认值与档位预设（standard / legacy）的实际生效值
  2. 后缀覆盖（-buy / -sell / -seg / -segbuy / -segsell）分侧生效
  3. **字符串型参数的后缀覆盖**（回归 `set()` 的 exec 二次解释缺陷）
  4. 枚举白名单校验与未知 key 拒绝
  5. 预设 + 显式 key 的优先级

无需 PG / 网络 / DuckDB。

运行：  .venv/Scripts/python.exe Debug/test_chan_config.py
"""

import os
import sys

_DEBUG_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_DEBUG_DIR)
sys.path.insert(0, _REPO_ROOT)

from ChanAnalyse.ChanConfig import CChanConfig
from ChanAnalyse.Common.ChanException import CChanException
from ChanAnalyse.Common.CEnum import MACD_ALGO

_PASS = 0
_FAIL = 0


def check(label, cond, detail=""):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  [OK]   {label}")
    else:
        _FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


# ---------------------------------------------------------------------------
print("\n[1] 默认值（standard 档）")
b = CChanConfig({}).bs_point_conf.b_conf
check("divergence_rate = 0.9", b.divergence_rate == 0.9, b.divergence_rate)
check("min_zs_cnt = 2", b.min_zs_cnt == 2, b.min_zs_cnt)
check("bsp3b_mode = standard", b.bsp3b_mode == "standard", b.bsp3b_mode)
check("bsp1_force_scope = swing", b.bsp1_force_scope == "swing", b.bsp1_force_scope)
# chan-bsp1-extreme 3.1：默认力度算法由 PEAK 改为 FULL_AREA（legacy 档锁定 PEAK）
check("macd_algo = FULL_AREA", b.macd_algo is MACD_ALGO.FULL_AREA, b.macd_algo)
check("bs1_peak_strict = True", b.bs1_peak_strict is True, b.bs1_peak_strict)
check("target_types 全 6 类",
      [t.value for t in b.target_types] == ["1", "1p", "2", "2s", "3a", "3b"],
      [t.value for t in b.target_types])
check("线段级别 bsp1_only_multibi_zs 强制 False",
      CChanConfig({}).seg_bs_point_conf.b_conf.bsp1_only_multibi_zs is False)


# ---------------------------------------------------------------------------
print("\n[2] 档位预设 legacy")
lg = CChanConfig({"bsp_preset": "legacy"}).bs_point_conf.b_conf
check("divergence_rate = inf", lg.divergence_rate == float("inf"), lg.divergence_rate)
check("min_zs_cnt = 1", lg.min_zs_cnt == 1, lg.min_zs_cnt)
check("bsp1_trend = False", lg.bsp1_trend is False, lg.bsp1_trend)
check("bsp3b_mode = legacy", lg.bsp3b_mode == "legacy", lg.bsp3b_mode)
check("bsp2s_rate_mode = disp", lg.bsp2s_rate_mode == "disp", lg.bsp2s_rate_mode)
check("bsp1_zs_extend_to_seg_end = True", lg.bsp1_zs_extend_to_seg_end is True)
# chan-bsp1-extreme：档位等价的必要条件，两项都必须在 legacy 显式回退
check("macd_algo = PEAK（legacy 锁定）", lg.macd_algo is MACD_ALGO.PEAK, lg.macd_algo)
check("bs1_peak_strict = False（legacy 回退）",
      lg.bs1_peak_strict is False, lg.bs1_peak_strict)


# ---------------------------------------------------------------------------
print("\n[3] 预设 + 显式 key 的优先级（显式 key 覆盖预设）")
mixed = CChanConfig({"bsp_preset": "legacy", "bsp1_zero_axis": True}).bs_point_conf.b_conf
check("bsp1_zero_axis 被显式打开", mixed.bsp1_zero_axis is True, mixed.bsp1_zero_axis)
check("bsp1_trend 仍随预设为 False", mixed.bsp1_trend is False, mixed.bsp1_trend)
check("divergence_rate 仍随预设为 inf", mixed.divergence_rate == float("inf"))


# ---------------------------------------------------------------------------
print("\n[4] 后缀覆盖分侧生效")
c = CChanConfig({"macd_algo": "peak", "macd_algo-sell": "area"})
check("买侧 PEAK", c.bs_point_conf.b_conf.macd_algo is MACD_ALGO.PEAK)
check("卖侧 AREA", c.bs_point_conf.s_conf.macd_algo is MACD_ALGO.AREA)

c = CChanConfig({"divergence_rate": 0.9, "divergence_rate-sell": 0.5})
check("数值型：买 0.9 / 卖 0.5",
      c.bs_point_conf.b_conf.divergence_rate == 0.9
      and c.bs_point_conf.s_conf.divergence_rate == 0.5)

c = CChanConfig({"bsp1_qjt-seg": True})
check("线段后缀只影响线段级别",
      c.seg_bs_point_conf.b_conf.bsp1_qjt is True
      and c.seg_bs_point_conf.s_conf.bsp1_qjt is True
      and c.bs_point_conf.b_conf.bsp1_qjt is False)

c = CChanConfig({"bsp1_qjt-segbuy": True})
check("-segbuy 只影响线段买侧",
      c.seg_bs_point_conf.b_conf.bsp1_qjt is True
      and c.seg_bs_point_conf.s_conf.bsp1_qjt is False)


# ---------------------------------------------------------------------------
# 回归：set() 曾用 exec(f"self.{k} = {v}") 拼接赋值
#   - "legacy" → NameError: name 'legacy' is not defined
#   - "all"    → 静默绑定到内置函数 all（不报错但语义错误）
print("\n[5] 字符串型参数的后缀覆盖（exec 二次解释回归）")
_STR_PARAMS = [
    ("bsp1_trend_mode", "overlap"),
    ("bsp1_new_extreme_mode", "all"),      # 曾静默变成内置 all
    ("bsp2s_rate_mode", "disp"),
    ("bsp3b_mode", "legacy"),
    ("bsp3_follow_1_mode", "candidate"),
    ("bsp1_force_scope", "bi"),
    ("bsp2_confirm_level", "weak"),
    ("bsp3_confirm_level", "weak"),
]
for prop, val in _STR_PARAMS:
    try:
        cfg = CChanConfig({f"{prop}-sell": val})
        got = getattr(cfg.bs_point_conf.s_conf, prop)
        base = getattr(cfg.bs_point_conf.b_conf, prop)
        check(f"{prop}-sell = {val!r}",
              got == val and base != val, f"got={got!r} base={base!r}")
    except Exception as e:
        check(f"{prop}-sell = {val!r}", False, f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
print("\n[6] 校验：未知 key 与非法枚举值")
try:
    CChanConfig({"divergence_rat": 0.9})
    check("未知 key 抛 CChanException", False, "未抛异常")
except CChanException:
    check("未知 key 抛 CChanException", True)
except Exception as e:
    check("未知 key 抛 CChanException", False, f"抛了 {type(e).__name__}")

for bad in ({"bsp3b_mode": "xxx"}, {"bsp1_force_scope": "xxx"},
            {"bsp2s_rate_mode": "xxx"}, {"bsp1_trend_mode": "xxx"}):
    key = next(iter(bad))
    try:
        CChanConfig(bad)
        check(f"非法枚举 {key} 被拒", False, "未抛异常")
    except CChanException:
        check(f"非法枚举 {key} 被拒", True)

for bad in ({"bsp2_confirm_window": 3}, {"bsp3_confirm_window": 0},
            {"bsp1_qjt_depth": 0}):
    key = next(iter(bad))
    try:
        CChanConfig(bad)
        check(f"越界值 {key} 被拒", False, "未抛异常")
    except CChanException:
        check(f"越界值 {key} 被拒", True)

try:
    CChanConfig({"bsp3_time_axis_strong": 2.0, "bsp3_time_axis_weak": 1.0})
    check("时间轴 strong >= weak 被拒", False, "未抛异常")
except CChanException:
    check("时间轴 strong >= weak 被拒", True)


# ---------------------------------------------------------------------------
print(f"\n{'=' * 46}\n合计: {_PASS} PASS, {_FAIL} FAIL\n{'=' * 46}")
sys.exit(1 if _FAIL else 0)
