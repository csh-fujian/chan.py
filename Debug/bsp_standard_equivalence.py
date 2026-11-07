# -*- coding: utf-8 -*-
"""
买卖点标准口径的等价性与敏感性验证

用法（在项目根目录执行，离线读 Data/kl_store.duckdb，无需联网）：
    .venv/Scripts/python.exe Debug/bsp_standard_equivalence.py
    .venv/Scripts/python.exe Debug/bsp_standard_equivalence.py --quick

本脚本承担三件事：
    1. 等价性：`bsp_preset="legacy"` 必须逐笔逐类型复现改造前的输出
    2. 敏感性：一买四项判据各单独开关一次，观察六类数量变化
    3. 组合漏斗：从全关到全开的逐级递增，T1 数量必须单调不增

## 参数覆盖点清单（tasks 7.1）

`CChanConfig` 的取值规则是「默认 → 用户显式 key 覆盖」。任何调用方只要显式
写了下面这些 key，就会**静默压过新的默认档位**，使该入口完全不体现本次改造。
仓库内的覆盖点分布如下，处置方式见 tasks 7.2~7.7：

| 入口 | 显式 key | 处置 |
|---|---|---|
| `main.py` | `divergence_rate=inf` / `min_zs_cnt=0` / `bs1_peak=False` | 移除，改走默认档位 |
| `App/ashare_bsp_scanner_gui.py` | 同上三项 | 移除；若需「宁可多报」则改 `bsp_preset="legacy"` |
| `Debug/strategy_demo5.py` | 同上三项 | 改 `bsp_preset="legacy"` |
| `Debug/strategy_demo.py` / `demo2` / `demo4` | `divergence_rate=0.8` / `min_zs_cnt=1` | 保留并注释为历史口径 |
| `WebAPI/incremental_engine.py` | 无（仅 trigger_step / kl_data_check） | 加注释锁定该约束 |
| `WebAPI/chan_service.py` | 无 | 加注释锁定该约束 |

## 改造前基线（41 只日线，2019-01-01 起、QFQ）

    legacy 档（divergence_rate=inf, min_zs_cnt=1）
        笔级别  1:258  1p:69  2:318  2s:317  3a:61  3b:50
        线段级  1:37   1p:8   2:35   2s:15   3a:2   3b:6

    divergence_rate=0.9（其余默认）
        笔级别  1:134  1p:39  2:166  2s:157  3a:33  3b:33

## 降级路由与力度口径的期望值（chan-standard-bsp1-change）

    standard + 降级路由 + 单笔口径（bsp1_force_scope="bi"）
        笔级别  1:14   1p:53  2:12   2s:4   3a:1   3b:1
    standard + 降级路由 + 走势段口径（bsp1_force_scope="swing"，默认）
        笔级别  1:13   1p:52  2:12   2s:4   3a:1   3b:1

    降级漏斗（笔级别，单笔口径；五档均经 design D1-c 实测复核）
        bsp1_list 候选 573 → reason=='trend' 314 → 面积背驰 168
        → bs1_peak 通过 142 → 补全检后 53（= 降级点数）

    成因分布：41 只日线上 53 个降级点全部为 single_zs，no_trend 桶为 0。
    这是**数据特征**而非缺陷——该池内「有两中枢但未依次下移」且同时通过
    背驰/极值/全检的样本恰好不存在。合成序列验证见
    `Debug/bsp_downgrade_synth.py`（no_trend 分支已单独覆盖）。

    legacy 基线不受本变更影响（legacy 下 bsp1_trend=False → reason 永不为
    'trend' → 降级不触发；divergence_rate=inf → 不算 metric → 力度口径改动
    天然不生效）。

## 力度口径的锚点依赖传播（design D10）

走势段口径下 `3b` 会由 1 变 0，这不是缺陷：`sh.600016 bi=31` 原本是成立一买，
整段力度 r=1.746 > 0.9 判不背驰后不再是成立一买；同一线段内 bi=28 的 T3B
锚定的正是它，于是随之消失。与 `2/2s/3a` 的「完全不变」不同，`3b` 的表述是
「仅在所锚定一买因口径收紧而消失时连带变化」。

走势段口径相对单笔口径消失的 bsp1 点恰为 2 个：
    sh.600016 bi=31   ratio 0.837 → 1.746（离开段 3 笔，每笔都创新低，整段动能在增强）
    sz.000011 bi=44   ratio 0.026 → 0.913（c 段含 3 笔，单笔只看最后一笔判背驰）

线段级别（tasks 9.9）：走势段口径下 T1 保持 1（不变），降级 T1P 由 18 降到 17，
方向与笔级别一致（整段力度更严）。线段级不出现新增点/异常。
"""

import argparse
import collections
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb  # noqa: E402

from ChanAnalyse.Chan import CChan  # noqa: E402
from ChanAnalyse.ChanConfig import CChanConfig  # noqa: E402
from ChanAnalyse.Common.CEnum import AUTYPE, BSP_TYPE, KL_TYPE  # noqa: E402
from ChanAnalyse.BuySellPoint.BSPJudgement import check_bsp1_standard  # noqa: E402
from ChanAnalyse.BuySellPoint import BSPointList as bspointlist_mod  # noqa: E402
from ChanAnalyse.DataAPI.DuckDBAPI import CDuckDB  # noqa: E402

DB_PATH = Path(__file__).resolve().parent.parent / "Data" / "kl_store.duckdb"
CDuckDB.db_path = str(DB_PATH)

BSP_TYPES = [BSP_TYPE.T1, BSP_TYPE.T1P, BSP_TYPE.T2, BSP_TYPE.T2S, BSP_TYPE.T3A, BSP_TYPE.T3B]
TYPE_SHORT = {BSP_TYPE.T1: '1', BSP_TYPE.T1P: '1p', BSP_TYPE.T2: '2',
              BSP_TYPE.T2S: '2s', BSP_TYPE.T3A: '3a', BSP_TYPE.T3B: '3b'}

# 改造前基线，用于等价性对照
BASELINE_LEGACY = {'1': 258, '1p': 69, '2': 318, '2s': 317, '3a': 61, '3b': 50}
BASELINE_SEG_LEGACY = {'1': 37, '1p': 8, '2': 35, '2s': 15, '3a': 2, '3b': 6}

# 本变更期望值（41 只日线，2019-01-01 起、QFQ）
#
# 这四条常量同时叠加了三件事，读数时请对照 `文档/一买一卖差异点说明.md`：
#   1. 极值严格优（chan-bsp1-extreme 1.1/1.2）——拦下 sh.600006 bi77、
#      sh.600026 bi25、sz.000007 bi55 三个「相等极值」降级候选
#   2. 力度算法 peak → full_area（3.1）——T1 由 13/14 增至 17/19
#   3. 走势段口径（bsp1_force_scope="swing"）——相对单笔口径的增删见
#      `EXPECTED_SWING_REMOVED` 与下方 default 口径的逐点差说明
#
# 仅第 1 项自身的效果见 `Debug/_probe*` 记录的「50/49」中间态；本文件断言的是
# 三项叠加后的终值，与 `文档/一买一卖差异点说明.md` §三 实测表、`Document/README.md`
# 的默认参数说明必须逐项一致。
BASELINE_STANDARD_BI = {'1': 19, '1p': 47, '2': 17, '2s': 7, '3a': 2, '3b': 3}
# swing 相对 bi：1 19→17、2 17→16、3b 3→1。3b 的 3→1 不是缺陷——两处 3b 消失
# 所锚定的一买（sh.600016 bi31、sh.600025 bi61）在走势段口径下不再是成立一买，
# 属锚点依赖的正确传播（design D10）。2 的 17→16 同理：sh.600025 bi63 的二买
# 锚定的一买在 swing 口径下消失。
#
# 注意：这里**不再断言**「2 / 2s / 3a 完全不变」。那是 chan-standard-bsp1-change
# 在 peak 力度口径下的结论，力度算法切到 full_area 后，成立一买集合改变，
# 二买/三买作为锚点依赖的下游类型必然随之变动——这是正确传播，不是回归。
BASELINE_STANDARD_SWING = {'1': 17, '1p': 47, '2': 16, '2s': 7, '3a': 2, '3b': 1}
# 走势段口径下相对单笔口径**消失**的 bsp1 点（逐笔对账用）。
#
# **这两条常量必须与第 7 节的 `ANCHOR_ERA_PIN` 同源**：第 7 节把
# `macd_algo` / `bs1_peak_strict` / `bsp1_new_extreme` 都 pin 回锚点时代取值，
# 比对基准 JSON 也是 peak 时代快照，所以增删集只能是 peak 时代的 2 个点。
# 曾经这里填的是 full_area 时代的 6 点格局（sh.600010 bi8、sh.600016 bi28、
# sh.600025 bi60/61/63），导致第 7 节误报「消失集不符预期」——那是常量与
# pin 口径脱节，不是开关接线故障。
#
# full_area（默认档）下的实际格局是：消失 6 个 = {('sh.600010', 8),
# ('sh.600016', 31), ('sh.600016', 28), ('sh.600025', 60), ('sh.600025', 61),
# ('sh.600025', 63)}、新增 1 个 = {('sh.600010', 65)}。该格局由第 5 节的
# `BASELINE_STANDARD_BI/SWING` 数量基线覆盖，本节不重复断言（基准 JSON 不是
# full_area 口径，拿它比会同时测三个变量）。
EXPECTED_SWING_REMOVED = {('sh.600016', 31), ('sz.000011', 44)}
# 走势段口径下相对单笔口径**新增**的 bsp1 点（peak 时代为空）
EXPECTED_SWING_ADDED = set()
# 第 7 节锚点 `Debug/bsp1_force_scope_baseline.json` 是 **peak 时代**的快照：
# 它由 chan-standard-bsp1-change 的 tasks 9.0 生成，早于 chan-bsp1-strict-extreme
# 的极值严格优（1.1/1.2）与力度默认切换（3.1）。第 7 节的语义是「只验证
# `bsp1_force_scope` 一个变量」——把另外两个变量也放进来，比对必然全飘，
# 而那既不说明开关接线有问题，也测不出窗口逻辑对不对。
#
# 因此第 7 节把这两个变量显式 pin 回锚点时代取值。实测证明这个 pin 是精确的：
# 在此口径下 `bi` 档与锚点 JSON **0 增 0 删 0 漂移**，`swing` 档恰为预期的
# 2 个消失点。若将来有人再改这三项的默认值，第 7 节不受影响（它测的是开关本身），
# 而第 5/6/6b 节的数值基线会立刻报错——职责分离。
ANCHOR_ERA_PIN = {"macd_algo": "peak", "bs1_peak_strict": False,
                  "bsp1_new_extreme": False}
# 第 7 节在 `ANCHOR_ERA_PIN` 下的数量基线（= peak 时代实测，与锚点 JSON 同源）。
#
# `1p` 是 53/52 而不是 50/49：后者是「极值严格优（`bs1_peak_strict=True`）之后」
# 的中间态。本节把 `bs1_peak_strict` pin 成 False（宽松），那 3 个「相等极值」的
# 降级候选重新放行，1p 回到锚点 JSON 的 53/52。三个点是
# `sh.600006 bi77` / `sh.600026 bi25` / `sz.000007 bi55`——正是 design D0 里
# 严格优拦下的同一批（用 `Debug/_probe_anchor_1p.py` 翻 `bs1_peak_strict` 可复现）。
# T1 在两口径下都是 14/13：这三点的趋势项本就不通过，只会以降级形态出现。
BASELINE_ANCHOR_BI = {'1': 14, '1p': 53, '2': 12, '2s': 4, '3a': 1, '3b': 1}
BASELINE_ANCHOR_SWING = {'1': 13, '1p': 52, '2': 12, '2s': 4, '3a': 1, '3b': 0}


def _assert_counts(label, got, exp):
    """逐类核对六类数量，返回是否一致（第 7 节的锚点口径断言用）。"""
    bad = {k: got.get(k, 0) - v for k, v in exp.items() if got.get(k, 0) != v}
    if bad:
        print(f'    ✗ {label} 与基线不一致：{bad}')
        print(f'      期望 {fmt(exp)}')
        print(f'      实测 {fmt(got)}')
        return False
    print(f'    ✓ {label} 与基线一致 {fmt(got)}')
    return True
# 降级漏斗（笔级别、单笔口径）：候选 → trend → 面积背驰 → bs1_peak → 补全检后
# 末档 = 标准档降级点数（T1P 47）。第 3 档 165 与 peak 时代的 168 差 3：full_area
# 让三个原本「面积不背驰」的候选变成背驰。首档 365 是本脚本口径（进入 treat_bsp1
# 的次数），与 JSON 候选口径不同，见断言处的说明。实测回写。
BASELINE_DOWNGRADE_FUNNEL = (365, 314, 165, 139, 47)


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
    """库内日线数据的最新 time_key 日期（YYYY-MM-DD）。

    逐笔基线必须 pin 到这个水位——`Data/kl_store.duckdb` 不进 git，
    后续灌数会改变笔的划分与 `bi.idx` 位移。
    """
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        row = con.execute(
            "select max(time_key) from kline where kl_type='K_DAY' and autype='QFQ'"
        ).fetchone()
    finally:
        con.close()
    return str(row[0])[:10] if row and row[0] else None


def build(code, **extra):
    conf = CChanConfig({"trigger_step": False, "kl_data_check": False, **extra})
    chan = CChan(code=code, data_src="custom:DuckDBAPI.CDuckDB", lv_list=[KL_TYPE.K_DAY],
                 config=conf, autype=AUTYPE.QFQ, begin_time="2019-01-01")
    return chan[KL_TYPE.K_DAY]


def build_pinned(code, watermark, **extra):
    """pin 到基线水位的构建（基线生成与比对都必须用这个）。"""
    conf = CChanConfig({"trigger_step": False, "kl_data_check": False, **extra})
    chan = CChan(code=code, data_src="custom:DuckDBAPI.CDuckDB", lv_list=[KL_TYPE.K_DAY],
                 config=conf, autype=AUTYPE.QFQ,
                 begin_time="2019-01-01", end_time=watermark)
    return chan[KL_TYPE.K_DAY]


def count_types(codes, seg_level=False, **extra):
    cnt = collections.Counter()
    for code in codes:
        try:
            kl = build(code, **extra)
        except Exception as exc:  # 单只股票失败不应中断整轮统计
            print(f"  [warn] {code}: {type(exc).__name__}: {exc}")
            continue
        bsp_lst = kl.seg_bs_point_lst if seg_level else kl.bs_point_lst
        for point in bsp_lst.bsp_iter():
            for bsp_type in point.type:
                if bsp_type in TYPE_SHORT:
                    cnt[TYPE_SHORT[bsp_type]] += 1
    return cnt


def fmt(cnt):
    return "  ".join(f"{k}:{cnt.get(k, 0):4d}" for k in ('1', '1p', '2', '2s', '3a', '3b'))


def section(title):
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def check_equivalence(codes, seg_level, full=True):
    section("1. 等价性：legacy 档位复现改造前基线")
    baseline = BASELINE_SEG_LEGACY if seg_level else BASELINE_LEGACY
    level = "线段级别" if seg_level else "笔级别"
    cnt = count_types(codes, seg_level=seg_level, bsp_preset="legacy")
    print(f"{level} legacy: {fmt(cnt)}")
    if not full:
        print("（--quick 模式：基线与标的数绑定，跳过数值核对，仅打印）")
        return True
    print(f"{level} 基线  : " + "  ".join(f"{k}:{v:4d}" for k, v in baseline.items()))
    diff = {k: cnt.get(k, 0) - v for k, v in baseline.items()}
    bad = {k: v for k, v in diff.items() if v != 0}
    if bad:
        print(f"✗ 与基线不一致：{bad}")
        return False
    print("✓ 完全一致")
    return True


def check_sensitivity(codes):
    section("2. 敏感性：一买四项判据单独开关")
    print("基线为全关（legacy 的判据开关，但保留 0.9 阈值），逐个开启后观察变化：")
    base_extra = {"divergence_rate": 0.9, "min_zs_cnt": 2,
                  "bsp1_trend": False, "bsp1_new_extreme": False,
                  "bsp1_dif_div": False, "bsp1_zero_axis": False,
                  "bsp1_zs_extend_to_seg_end": False,
                  "bsp2s_require_zs": False, "bsp2s_rate_mode": "disp",
                  "bsp3b_mode": "legacy"}
    rows = [("全关（基线）", dict(base_extra))]
    for name in ("bsp1_trend", "bsp1_new_extreme", "bsp1_dif_div", "bsp1_zero_axis"):
        rows.append((f"+{name}", {**base_extra, name: True}))
    for label, extra in rows:
        cnt = count_types(codes, **extra)
        print(f"  {label:22s} {fmt(cnt)}")


def check_funnel(codes, seg_level):
    section("3. 组合漏斗：逐级递增，T1 数量应单调不增")
    level = "线段级别" if seg_level else "笔级别"
    steps = [
        ("div=inf（legacy 阈值）", {"divergence_rate": float("inf"), "min_zs_cnt": 1,
                                 "bsp1_trend": False, "bsp1_new_extreme": False,
                                 "bsp1_dif_div": False, "bsp1_zero_axis": False,
                                 "bsp1_zs_extend_to_seg_end": True}),
        ("div=0.9", {"divergence_rate": 0.9, "min_zs_cnt": 1,
                     "bsp1_trend": False, "bsp1_new_extreme": False,
                     "bsp1_dif_div": False, "bsp1_zero_axis": False,
                     "bsp1_zs_extend_to_seg_end": True}),
        ("+min_zs_cnt=2", {"divergence_rate": 0.9, "min_zs_cnt": 2,
                           "bsp1_trend": False, "bsp1_new_extreme": False,
                           "bsp1_dif_div": False, "bsp1_zero_axis": False,
                           "bsp1_zs_extend_to_seg_end": True}),
        ("+趋势", {"divergence_rate": 0.9, "min_zs_cnt": 2, "bsp1_trend": True,
                   "bsp1_new_extreme": False, "bsp1_dif_div": False,
                   "bsp1_zero_axis": False, "bsp1_zs_extend_to_seg_end": True}),
        ("+新低", {"divergence_rate": 0.9, "min_zs_cnt": 2, "bsp1_trend": True,
                   "bsp1_new_extreme": True, "bsp1_dif_div": False,
                   "bsp1_zero_axis": False, "bsp1_zs_extend_to_seg_end": True}),
        ("+DIF", {"divergence_rate": 0.9, "min_zs_cnt": 2, "bsp1_trend": True,
                  "bsp1_new_extreme": True, "bsp1_dif_div": True,
                  "bsp1_zero_axis": False, "bsp1_zs_extend_to_seg_end": True}),
        ("+零轴", {"divergence_rate": 0.9, "min_zs_cnt": 2, "bsp1_trend": True,
                  "bsp1_new_extreme": True, "bsp1_dif_div": True,
                  "bsp1_zero_axis": True, "bsp1_zs_extend_to_seg_end": True}),
        ("+放宽4.8（默认档）", {}),
    ]
    prev = None
    monotonic = True
    for label, extra in steps:
        cnt = count_types(codes, seg_level=seg_level, **extra)
        t1 = cnt.get('1', 0)
        mark = ""
        if prev is not None and t1 > prev:
            mark = "  ← 上升（仅 4.8 放宽允许）" if "放宽" in label else "  ← ✗ 违反单调"
            if "放宽" not in label:
                monotonic = False
        print(f"  {label:22s} {level} T1={t1:4d}{mark}")
        prev = t1
    return monotonic


def check_bsp2s_observability(codes):
    section("4. 类二 bsp2s_follow_2 的可观察性")

    print("该开关只在「二买失败率高」的阈值下才可能观察得到：")
    print("默认 max_bs2_rate=0.9999 时二买几乎全部成立，开关必然无差异——")
    print("这是正确行为，不是开关失效。下表用于确认这一点，勿误判为缺陷。")
    print()
    base = {"divergence_rate": 0.9, "min_zs_cnt": 2,
            "bsp2s_require_zs": False, "bsp2s_rate_mode": "disp"}
    same_at_default = []
    for rate in (0.9999, 0.8, 0.618, 0.5):
        cnt_off = count_types(codes, max_bs2_rate=rate, bsp2s_follow_2=False, **base)
        cnt_on = count_types(codes, max_bs2_rate=rate, bsp2s_follow_2=True, **base)
        off, on = cnt_off.get('2s', 0), cnt_on.get('2s', 0)
        flag = "相同（默认档，符合预期）" if off == on else "不同（开关生效）"
        print(f"  max_bs2_rate={rate:<7} 2 买:{cnt_off.get('2', 0):4d}  "
              f"follow=False → 2s:{off:4d}   follow=True → 2s:{on:4d}   {flag}")
        if off == on:
            same_at_default.append(rate)
        if on > off:
            print(f"    ✗ 开启后数量反而增加，语义反向")
            return False
    if 0.9999 not in same_at_default:
        print("  ✗ 默认阈值下开关不应有差异（二买几乎全成立）")
        return False
    return True


def _downgrade_of(kl):
    """收集降级点：[(bi.idx, reason, in_sure_dict)]。"""
    out = []
    for bsp in kl.bs_point_lst.bsp_iter():
        fd = dict(bsp.features.items())
        if fd.get('bsp1_downgrade_reason'):
            out.append((bsp.bi.idx, fd['bsp1_downgrade_reason'],
                        bsp.bi.idx in kl.bs_point_lst.bsp1_sure_dict))
    return out


def _scope_kw():
    """`bsp1_force_scope` 尚未引入时（tasks 9.0 之前）返回空 dict。

    基线必须先于 9.1 生成（否则自我循环），因此本脚本的前置小节必须在
    该配置项不存在时也能跑通——`ConfigWithCheck` 遇到未知 key 会直接抛。
    """
    try:
        CChanConfig({"bsp1_force_scope": "bi"})
        return {"bsp1_force_scope": "bi"}
    except Exception:
        return {}


def check_downgrade_switch(codes, full=True):
    """6. 降级路由对照：开/关只差 `1p`，其余五类逐类一致（tasks 5.1 / 5.2a / 5.4）。"""
    section("6. 降级路由对照（tasks 5.1）")
    kw = dict(bsp_preset="standard", **_scope_kw())
    if "bsp1_force_scope" not in kw:
        print("  （bsp1_force_scope 尚未引入，按单笔口径对照）")
    cnt_off = count_types(codes, bsp1_downgrade_to_pz=False, **kw)
    cnt_on = count_types(codes, bsp1_downgrade_to_pz=True, **kw)
    print(f"  降级关闭 : {fmt(cnt_off)}")
    print(f"  降级开启 : {fmt(cnt_on)}")
    print(f"  差异     : 1p {cnt_off.get('1p', 0)} → {cnt_on.get('1p', 0)}（其余五类须为 0 差异）")

    ok = True
    for k in ('1', '2', '2s', '3a', '3b'):
        d = cnt_on.get(k, 0) - cnt_off.get(k, 0)
        if d != 0:
            print(f"  ✗ 类型 {k} 出现差异 {d:+d}（应只增 1p）")
            ok = False
    if ok:
        print("  ✓ 除 1p 外五类逐类一致")

    # ---- 5.2a：背驰关闭时降级不触发 ----
    print()
    print("  背驰关闭对照（divergence_rate=200，bsp1_trend 保持 True）：")
    cnt_div_off_on = count_types(codes, bsp_preset="standard", **_scope_kw(),
                                 divergence_rate=200.0, bsp1_downgrade_to_pz=True)
    cnt_div_off_off = count_types(codes, bsp_preset="standard", **_scope_kw(),
                                  divergence_rate=200.0, bsp1_downgrade_to_pz=False)
    print(f"    div=200 降级开 : {fmt(cnt_div_off_on)}")
    print(f"    div=200 降级关 : {fmt(cnt_div_off_off)}")
    if cnt_div_off_on.get('1p', 0) == cnt_div_off_off.get('1p', 0):
        print("    ✓ divergence_rate>100 时降级不触发（1p 与关闭时相同）")
    else:
        print("    ✗ divergence_rate>100 时仍产生降级点——空真陷阱未被规避")
        ok = False

    # ---- 5.4：成因分布 ----
    print()
    print("  成因分布（tasks 5.4）：")
    dist = collections.Counter()
    dg_total = 0
    viol = 0
    for code in codes:
        try:
            kl = build(code, **kw)
        except Exception:
            continue
        for idx, reason, in_sure in _downgrade_of(kl):
            dist[reason] += 1
            dg_total += 1
            if in_sure:
                viol += 1
    for reason in ('single_zs', 'no_trend'):
        n = dist.get(reason, 0)
        note = "" if n > 0 else "  （数据特征：本池内该成因的合格样本不存在，非缺陷）"
        print(f"    {reason:10s} {n:4d}{note}")
    print(f"    合计       {dg_total:4d}  违规进 bsp1_sure_dict：{viol}")
    if sum(dist.values()) != dg_total:
        print("  ✗ 两桶之和不等于降级点总数")
        ok = False
    if viol != 0:
        print("  ✗ 降级点进入了 bsp1_sure_dict（锚点隔离失效）")
        ok = False
    if dg_total == 0:
        print("  ✗ 降级点总数为 0——开关未生效或数据不匹配")
        ok = False

    # ---- 5.2：数值基线 ----
    if full:
        print()
        print("  数值基线对照（笔级别、单笔口径）：")
        print(f"    期望 {fmt(BASELINE_STANDARD_BI)}")
        print(f"    实测 {fmt(cnt_on)}")
        bad = {k: cnt_on.get(k, 0) - v for k, v in BASELINE_STANDARD_BI.items()
               if cnt_on.get(k, 0) != v}
        if bad:
            print(f"    ✗ 与基线不一致：{bad}（若数据水位已推进，请更新基线常量）")
            ok = False
        else:
            print("    ✓ 与基线完全一致")
    else:
        print("  （--quick 模式：跳过数值基线核对）")
    return ok


def check_downgrade_funnel(codes, full=True):
    """6b. 降级漏斗五档（tasks 5.2b）：候选 → trend → 面积背驰 → bs1_peak → 补全检。"""
    section("6b. 降级漏斗（tasks 5.2b）")
    funnel = collections.Counter()
    orig = bspointlist_mod.CBSPointList.treat_bsp1

    def probe(self, seg, BSP_CONF, is_target_bsp, full_ele_list=None):
        # `full_ele_list` 是 chan-bsp1-extreme 为 `bsp1_new_extreme_mode="level"`
        # 新增的形参；必须跟随 `treat_bsp1` 的签名，否则 monkey-patch 会因
        # 关键字不匹配抛 TypeError，而外层的 `except Exception: continue`
        # 会把它静默吞成「漏斗全 0」——那看起来像数据问题，实则是签名失配。
        if seg.start_bi.__class__.__name__ != 'CBi':
            return orig(self, seg, BSP_CONF, is_target_bsp,
                        full_ele_list=full_ele_list)
        funnel['1_候选'] += 1
        last_zs = seg.zs_lst[-1]
        bp, _ = last_zs.out_bi_is_peak(seg.end_bi.idx, strict=BSP_CONF.bs1_peak_strict)
        peak_ok = (not BSP_CONF.bs1_peak) or bp
        is_diver, _ = last_zs.is_divergence(BSP_CONF, out_bi=seg.end_bi)
        _, reason, _ = check_bsp1_standard(seg.end_bi, seg.bi_list, seg.zs_lst,
                                           BSP_CONF, seg.is_down())
        if reason == 'trend':
            funnel['2_趋势拦下'] += 1
            if is_diver:
                funnel['3_面积背驰'] += 1
            if is_diver and peak_ok:
                funnel['4_bs1_peak'] += 1
            if is_diver and peak_ok:
                rc = copy.copy(BSP_CONF)
                rc.bsp1_trend = False
                rc.bsp1_new_extreme_mode = "all"
                rest_ok, _, _ = check_bsp1_standard(seg.end_bi, seg.bi_list, seg.zs_lst,
                                                    rc, seg.is_down())
                if rest_ok:
                    funnel['5_补全检'] += 1
        return orig(self, seg, BSP_CONF, is_target_bsp, full_ele_list=full_ele_list)

    bspointlist_mod.CBSPointList.treat_bsp1 = probe
    try:
        for code in codes:
            try:
                build(code, bsp_preset="standard", **_scope_kw())
            except Exception:
                continue
    finally:
        bspointlist_mod.CBSPointList.treat_bsp1 = orig

    keys = ['1_候选', '2_趋势拦下', '3_面积背驰', '4_bs1_peak', '5_补全检']
    for k in keys:
        print(f"  {k:12s} {funnel.get(k, 0):5d}")
    if not full:
        print("  （--quick 模式：跳过漏斗断言）")
        return True
    actual = tuple(funnel.get(k, 0) for k in keys)
    exp = BASELINE_DOWNGRADE_FUNNEL
    # 首档「候选」口径与基线不同（基线含 treat_pz_bsp1 路径），只对后四档断言
    if actual[1:] != exp[1:]:
        print(f"  ✗ 漏斗后四档 {actual[1:]} ≠ 基线 {exp[1:]}")
        return False
    print(f"  ✓ 漏斗后四档与基线一致 {actual[1:]}（末档 = 降级点数 {exp[4]}）")
    print(f"  （首档候选口径：本脚本统计进入 treat_bsp1 的次数 {actual[0]}；"
          f"基线 {exp[0]} 为 bsp1_list 候选总数，含 treat_pz_bsp1 路径，二者定义不同）")
    return True


BASELINE_JSON = Path(__file__).resolve().parent / "bsp1_force_scope_baseline.json"


def dump_points(kl):
    """导出一个级别的 bsp1 点：[(bi.idx, types, sure, diver, ratio)]。

    只收 T1 / T1P（bsp1 家族）——力度口径改造只影响这两类。
    """
    sure_set = set(kl.bs_point_lst.bsp1_sure_dict.keys())
    out = []
    for bsp in kl.bs_point_lst.bsp_iter():
        bs1_types = sorted(t.value for t in bsp.type
                           if t in (BSP_TYPE.T1, BSP_TYPE.T1P))
        if not bs1_types:
            continue
        fd = dict(bsp.features.items())
        ratio = fd.get('divergence_rate')
        out.append({
            "bi": bsp.bi.idx,
            "types": bs1_types,
            "sure": bsp.bi.idx in sure_set,
            "diver": fd.get('bsp1_standard_reason') is None,
            "ratio": None if ratio is None else round(float(ratio), 9),
        })
    return out


def cmd_dump_baseline(codes, watermark):
    """tasks 9.0：导出逐笔基线 JSON（幂等）。

    必须以 `bsp_preset="standard"` 生成——此时 `bsp1_force_scope` 尚不存在，
    传它会因 `ConfigWithCheck` 白名单抛异常。这就是 9.0 必须先于 9.1 的原因。
    """
    payload = {
        "watermark": watermark,
        "config": {"begin_time": "2019-01-01", "end_time": watermark,
                   "autype": "QFQ", "kl_type": "K_DAY", "bsp_preset": "standard"},
        "codes": [],
        "points": [],
    }
    for code in codes:
        try:
            kl = build_pinned(code, watermark, bsp_preset="standard")
        except Exception as exc:
            print(f"  [warn] {code}: {type(exc).__name__}: {exc}")
            continue
        payload["codes"].append(code)
        for p in dump_points(kl):
            payload["points"].append({"code": code, **p})
    text = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True)
    old = BASELINE_JSON.read_text(encoding="utf-8") if BASELINE_JSON.exists() else None
    BASELINE_JSON.write_text(text, encoding="utf-8")
    print(f"已写入 {BASELINE_JSON}")
    print(f"  水位 {watermark}，标的 {len(payload['codes'])}，逐笔点 {len(payload['points'])}")
    if old is not None:
        print("  ✓ 与上次生成结果一致（幂等）" if old == text else "  内容已变化")
    return True


def load_baseline():
    """读基线 JSON，并校验库水位。水位不一致时返回 (None, 原因)。"""
    if not BASELINE_JSON.exists():
        return None, f"基线文件不存在：{BASELINE_JSON}（先跑 --dump-baseline）"
    payload = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))
    cur = db_watermark()
    wm = payload.get("watermark")
    if cur != wm:
        return None, (f"库已推进到 {cur}，基线为 {wm}——请重新生成基线"
                      f"（.venv/Scripts/python.exe Debug/bsp_standard_equivalence.py --dump-baseline）")
    return payload, None


def compare_against_baseline(payload, scope_kw, label):
    """逐笔比对当前代码的输出与基线 JSON。返回 (ok, 差异清单)。"""
    base = {(p["code"], p["bi"]): p for p in payload["points"]}
    cur = {}
    for code in payload["codes"]:
        kl = build_pinned(code, payload["watermark"], bsp_preset="standard", **scope_kw)
        for p in dump_points(kl):
            cur[(code, p["bi"])] = p
    added = sorted(set(cur) - set(base))
    removed = sorted(set(base) - set(cur))
    drift = []
    for key in sorted(set(cur) & set(base)):
        b, c = base[key], cur[key]
        if b["types"] != c["types"] or b["sure"] != c["sure"] or b["diver"] != c["diver"]:
            drift.append((key, b, c))
        elif b["ratio"] is not None and c["ratio"] is not None:
            if abs(b["ratio"] - c["ratio"]) > 1e-9 * max(1.0, abs(b["ratio"])):
                drift.append((key, b, c))
    ok = not added and not removed and not drift
    print(f"  {label}: 新增 {len(added)}  消失 {len(removed)}  漂移 {len(drift)}")
    for key in added[:5]:
        print(f"    + {key} {cur[key]}")
    for key in removed[:5]:
        print(f"    - {key} {base[key]}")
    for key, b, c in drift[:5]:
        print(f"    ~ {key}: {b} → {c}")
    return ok, drift


def check_force_scope_compat(full=True):
    """7. 力度口径对照（tasks 9.3a / 9.4 / 9.7 / 9.8）。

    三个层次的断言：
      9.3a  开关已存在但 ZS.py 未改 → `"bi"` 档必须逐笔等于基线（0 增 0 删 0 漂移）
      9.4   签名改造后默认行为不变 → 同一比对仍须全绿
      9.7   走势段口径相对基线的增删集与翻转点清单

    **本节只测 `bsp1_force_scope` 一个变量**：锚点 JSON 是 peak 时代快照，因此
    另外两个后来改变默认行为的变量（`macd_algo` / 极值严格性）由 `ANCHOR_ERA_PIN`
    显式 pin 回锚点取值。不 pin 的话本节会同时测三个变量，比对全飘，
    既不能证明开关接线正确，也测不出窗口逻辑——详见 `ANCHOR_ERA_PIN` 的注释。
    """
    section("7. 力度口径对照（tasks 9.3a / 9.4 / 9.7 / 9.8）")
    payload, err = load_baseline()
    if payload is None:
        print(f"  ⚠ 跳过逐笔断言：{err}")
        print("  （这是明确提示，不是静默放过）")
        return False

    print(f"  基线水位 {payload['watermark']}，逐笔点 {len(payload['points'])}")
    print(f"  锚点时代 pin：{ANCHOR_ERA_PIN}")
    ok_bi, _ = compare_against_baseline(
        payload, {"bsp1_force_scope": "bi", **ANCHOR_ERA_PIN},
        'bsp1_force_scope="bi"（应 == 基线）')
    if ok_bi:
        print('    ✓ "bi" 档逐笔等于基线——开关本身不改变任何输出')
    else:
        print('    ✗ "bi" 档与基线不一致——故障在开关接线或签名改造，与窗口逻辑无关')

    # swing 档相对基线**预期**有变化（这是改造的目的），所以它的 ok_sw 不能
    # 直接作为失败判据——真正的判据是下面的逐笔对账（增删集恰为预期）
    compare_against_baseline(
        payload, {"bsp1_force_scope": "swing", **ANCHOR_ERA_PIN},
        'bsp1_force_scope="swing"（默认档）')
    ok_sw = True

    # ---- 逐笔对账：增删集必须恰为 EXPECTED_SWING_ADDED / _REMOVED ----
    base = {(p["code"], p["bi"]): p for p in payload["points"]}
    cur = {}
    for code in payload["codes"]:
        kl = build_pinned(code, payload["watermark"], bsp_preset="standard",
                          bsp1_force_scope="swing", **ANCHOR_ERA_PIN)
        for p in dump_points(kl):
            cur[(code, p["bi"])] = p
    added = set(cur) - set(base)
    removed = set(base) - set(cur)
    print()
    print("  逐笔对账（swing 相对 bi 口径）：")
    if not added:
        print("    ✓ 新增集为空")
    elif added == EXPECTED_SWING_ADDED:
        print(f"    ✓ 新增集恰为预期的 {len(added)} 个点：{sorted(added)}")
    else:
        print(f"    ✗ 新增集不符预期：{sorted(added)}")
        print(f"      预期：{sorted(EXPECTED_SWING_ADDED)}")
        ok_sw = False
    if removed == EXPECTED_SWING_REMOVED:
        print(f"    ✓ 消失集恰为预期的 {len(removed)} 个点")
        for code, bi_idx in sorted(removed):
            b = base[(code, bi_idx)]
            print(f"      {code} bi={bi_idx}: ratio {b['ratio']} → "
                  f"{cur.get((code, bi_idx), {}).get('ratio', '（点已消失）')}")
    else:
        print(f"    ✗ 消失集不符预期：{sorted(removed)}")
        print(f"      预期：{sorted(EXPECTED_SWING_REMOVED)}")
        ok_sw = False

    # ---- 数量对照 ----
    # 数量断言同样 pin 回锚点口径：本节测的是 `bsp1_force_scope` 一个变量，
    # 用 `BASELINE_STANDARD_BI/SWING` 那组（full_area 时代）常量会串味。
    print()
    print("  六类数量对照（两档位，锚点口径）：")
    codes_all = load_codes()
    cnt_bi = count_types(codes_all, bsp_preset="standard", bsp1_force_scope="bi",
                         **ANCHOR_ERA_PIN)
    cnt_sw = count_types(codes_all, bsp_preset="standard", bsp1_force_scope="swing",
                         **ANCHOR_ERA_PIN)
    print(f'    "bi"   : {fmt(cnt_bi)}')
    print(f'    "swing": {fmt(cnt_sw)}')

    # ---- 锚点口径下的数量基线（peak 时代，与第 5/6 节无关）----
    ok_sw &= _assert_counts('"bi" 档（锚点口径）', cnt_bi, BASELINE_ANCHOR_BI)
    ok_sw &= _assert_counts('"swing" 档（锚点口径）', cnt_sw, BASELINE_ANCHOR_SWING)

    # 2 / 2s / 3a 在**锚点口径下**必须完全不变；3b 允许因锚点传播而变（design D10）。
    # 注意：这条「三类不变」是 peak 力度的性质。切到 full_area 后成立一买集合改变，
    # 二买/三买作为锚点依赖的下游类型必然随之变动——那不是回归，见第 5 节的
    # BASELINE_STANDARD_SWING 注释。正因如此，本节的断言必须 pin 锚点口径。
    for k in ('2', '2s', '3a'):
        if cnt_bi.get(k, 0) != cnt_sw.get(k, 0):
            print(f'    ✗ 类型 {k} 在两档间不同 {cnt_bi.get(k,0)} vs {cnt_sw.get(k,0)}'
                  f'（这三类必须完全不变）')
            ok_sw = False
    if cnt_bi.get('2', 0) == cnt_sw.get('2', 0) and cnt_bi.get('2s', 0) == cnt_sw.get('2s', 0) \
            and cnt_bi.get('3a', 0) == cnt_sw.get('3a', 0):
        print('    ✓ 2 / 2s / 3a 数量完全相同')

    d3b = cnt_sw.get('3b', 0) - cnt_bi.get('3b', 0)
    if d3b == 0:
        print('    ✓ 3b 无变化')
    elif d3b < 0:
        print(f'    · 3b {cnt_bi.get("3b",0)} → {cnt_sw.get("3b",0)}：锚点依赖传播'
              f'（design D10）——所锚定的成立一买在走势段口径下消失')
        print('      验证：这些 3b 的 relate_bsp1 必须落在消失集中')
        unexplained = []
        for code in codes_all:
            kl_bi = build(code, bsp_preset="standard", bsp1_force_scope="bi",
                          **ANCHOR_ERA_PIN)
            have = {b.bi.idx for b in kl_bi.bs_point_lst.bsp_iter()
                    if BSP_TYPE.T3B in b.type}
            kl_sw = build(code, bsp_preset="standard", bsp1_force_scope="swing",
                          **ANCHOR_ERA_PIN)
            still = {b.bi.idx for b in kl_sw.bs_point_lst.bsp_iter()
                     if BSP_TYPE.T3B in b.type}
            for lost in have - still:
                bsp_bi = next(b for b in kl_bi.bs_point_lst.bsp_iter() if b.bi.idx == lost)
                anchor = bsp_bi.relate_bsp1.bi.idx if bsp_bi.relate_bsp1 else None
                explained = (code, anchor) in removed
                print(f'      {code} bi={lost} 锚定一买 bi={anchor} '
                      f'{"（在消失集中 ✓）" if explained else "（不在消失集 ✗）"}')
                if not explained:
                    unexplained.append((code, lost, anchor))
        if unexplained:
            print(f'    ✗ {len(unexplained)} 个 3b 消失无法由一买消失解释')
            ok_sw = False
    else:
        print(f'    · 3b 增加 {d3b:+d}——需要说明来源')

    # 数量基线已在上面用 `_assert_counts` 按锚点口径断言过，此处不再重复。
    # 这里只剩一个 `--quick` 模式的说明位，避免读者以为「没见到基线对照」是漏了。
    if not full:
        print("  （--quick 模式：上面的数量基线核对仍以全量口径执行）")
    return ok_bi and ok_sw


def check_no_preset_leak(codes):
    """8.4 回归：legacy → standard → legacy 三跑，验证无跨档位串味。

    串味的典型来源是进程级可变状态（模块级缓存、类属性、`@make_cache` 绑到
    错误对象的缓存、配置对象被就地改写）。本检查在**同一个进程**里交替跑三
    次，第 1 次与第 3 次的输出必须完全一致，且第 2 次必须等于 standard 的
    独立输出——三者任一不成立即说明档位之间存在状态残留。

    注意：`CChanConfig` 的预设展开是「构造时一次性」的，理论上不应有残留；
    本用例守的是回归——将来若有人把预设写回全局/类属性，这里会立刻失败。
    """
    section("5. 档位隔离：legacy → standard → legacy 三跑（tasks 8.4）")
    runs = []
    for label in ("legacy#1", "standard", "legacy#2"):
        preset = "standard" if label == "standard" else "legacy"
        cnt = count_types(codes, bsp_preset=preset)
        runs.append((label, cnt))
        print(f"  {label:11s}: {fmt(cnt)}")

    ok = True
    first, second, third = runs[0][1], runs[1][1], runs[2][1]
    if first != third:
        print("  ✗ legacy 首跑与末跑不一致——档位间存在状态残留")
        print(f"    差异：{ {k: third.get(k, 0) - first.get(k, 0) for k in set(first) | set(third) if first.get(k, 0) != third.get(k, 0)} }")
        ok = False
    else:
        print("  ✓ legacy 首跑 == legacy 末跑（无跨档位串味）")

    # standard 夹在两次 legacy 之间，必须与其独立跑结果一致（首跑末跑都不是它）
    expect_std = count_types(codes, bsp_preset="standard")
    if second != expect_std:
        print("  ✗ 夹在两次 legacy 之间的 standard 与其独立输出不一致")
        print(f"    差异：{ {k: second.get(k, 0) - expect_std.get(k, 0) for k in set(second) | set(expect_std) if second.get(k, 0) != expect_std.get(k, 0)} }")
        ok = False
    else:
        print(f"  ✓ standard（夹跑）== standard（独立跑）: {fmt(expect_std)}")

    if first == second:
        print("  ✗ 两个档位输出完全相同——说明预设未生效，本次用例失去意义")
        ok = False
    else:
        changed = sum(abs(second.get(k, 0) - first.get(k, 0)) for k in ('1', '1p', '2', '2s', '3a', '3b'))
        print(f"  ✓ 两档位确有差异（逐类型绝对差合计 {changed}），用例有效")
    return ok


def check_qjt_contrast(codes, full=True):
    """第 8 节：区间套特征对照（tasks 10.9）。

    两件事：
      1. **不改成立性**：`bsp1_qjt=True` 与 `False` 下六类数量逐类完全一致
         （spec「特征不改成立性」）
      2. **命中统计**：命中数 / 候选数 / 命中率，并按「父级候选本身是否已成立」
         分桶（仅作展示——父级是否是成立一买与它能否命中区间套无关）。

    资格校验的对象是**子级**：每个命中点的 `bsp1_qjt_sub_idx` 必须落在子级
    `bsp1_sure_dict` 中。落在子级 `bsp1_list` 候选（含降级点）里即为缺陷——
    说明命中资格取了候选口径。

    命中数为 0 时打印「数据特征或映射未覆盖」而非判失败：本仓库只有少数
    标的同时有日线与 30m 数据，区间套的可用样本本就极少，0 命中是合理的
    数据特征，不能当作映射失效的证据。映射失效的证明在
    `Debug/bsp_qjt_synth.py`（构造多级结构逐条断言）。
    """
    section("8. 区间套特征对照（tasks 10.9）")
    cnt_off = count_types(codes, bsp_preset="standard")
    cnt_on = count_types(codes, bsp_preset="standard", bsp1_qjt=True)
    print(f"  qjt 关闭 : {fmt(cnt_off)}")
    print(f"  qjt 开启 : {fmt(cnt_on)}")
    ok = True
    diff = {k: cnt_on.get(k, 0) - cnt_off.get(k, 0) for k in ('1', '1p', '2', '2s', '3a', '3b')
            if cnt_on.get(k, 0) != cnt_off.get(k, 0)}
    if diff:
        print(f"  ✗ 六类数量出现差异 {diff}——区间套特征影响了成立性")
        ok = False
    else:
        print("  ✓ 六类数量逐类完全一致（特征不改成立性）")

    # ---- 命中统计（需要多级别，只对有次级数据的标的） ----
    print()
    print("  命中统计（多级别标的，日线级看 30m）：")
    multi = _qjt_multi_level_codes()
    if not multi:
        print("    （库内没有同时具备日线与 30m 数据的标的——本池无法给出统计）")
        return ok
    tot_cand = tot_hit = 0
    bkt = collections.Counter()
    rows = []
    bad_eligibility = []
    for code in multi:
        try:
            chan = _build_multi(code, bsp1_qjt=True)
        except Exception as exc:
            print(f"    [warn] {code}: {type(exc).__name__}: {exc}")
            continue
        lst = chan[KL_TYPE.K_DAY].bs_point_lst
        sub = getattr(lst, 'sub_bs_point_lst', None)
        sub_sure = set(sub.bsp1_sure_dict.keys()) if sub is not None else set()
        cand = len(lst.bsp1_list)
        sure_idx = set(lst.bsp1_sure_dict.keys())
        hits = []
        for bsp in lst.bsp1_list:
            fd = dict(bsp.features.items())
            if not fd.get('bsp1_qjt_hit'):
                continue
            sub_idx = fd.get('bsp1_qjt_sub_idx')
            hits.append(bsp.bi.idx)
            bkt['父级已成立' if bsp.bi.idx in sure_idx else '父级未成立候选'] += 1
            if sub_idx not in sub_sure:
                bad_eligibility.append((code, bsp.bi.idx, sub_idx))
        tot_cand += cand
        tot_hit += len(hits)
        rows.append((code, cand, len(hits), hits))
    for code, cand, hit, hits in rows:
        rate = f"{hit / cand * 100:5.1f}%" if cand else "  n/a"
        print(f"    {code:12s} 候选 {cand:3d}  命中 {hit:3d}  命中率 {rate}  {hits}")

    print()
    if tot_cand:
        print(f"    合计：候选 {tot_cand}  命中 {tot_hit}（{tot_hit / tot_cand * 100:.1f}%）")
    else:
        print("    合计：无候选")
    print(f"    父级分桶：{dict(bkt) if bkt else '无命中'}"
          "（父级是否成立与能否命中无关，仅作展示）")
    if bad_eligibility:
        print(f"  ✗ {len(bad_eligibility)} 个命中的子级点不在子级成立集合中：{bad_eligibility}")
        print("     命中资格取了候选口径——否则父级会拿到「子级趋势都不成立」的点背书")
        ok = False
    elif tot_hit:
        print("  ✓ 全部命中点的子级索引均落在子级 bsp1_sure_dict 中（命中资格正确）")
    if tot_hit == 0:
        print("    （命中数为 0：数据特征或映射未覆盖——本池多级别标的本就少，"
              "映射正确性由 Debug/bsp_qjt_synth.py 逐条断言）")
    return ok


def _qjt_multi_level_codes():
    """库内同时具备日线与 30m 数据的标的。"""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        rows = con.execute(
            "select distinct d.code from kline d join kline m on d.code = m.code "
            "where d.kl_type='K_DAY' and d.autype='QFQ' "
            "and m.kl_type='K_30M' and m.autype='QFQ' order by 1"
        ).fetchall()
    finally:
        con.close()
    return [r[0] for r in rows]


def _build_multi(code, **extra):
    conf = CChanConfig({"trigger_step": False, "kl_data_check": False, **extra})
    return CChan(code=code, data_src="custom:DuckDBAPI.CDuckDB",
                 lv_list=[KL_TYPE.K_DAY, KL_TYPE.K_30M],
                 config=conf, autype=AUTYPE.QFQ, begin_time="2020-01-01")


def check_pz_force_scope(codes, full=True):
    """第 10 节：T1P 力度口径走势段化对照（chan-bsp-ladder-change task 2.2）。

    无结构中枢路径（`treat_pz_bsp1`）的 b/c 窗口从「前前笔 vs 末笔」的
    单笔口径升级为「反向笔组分隔的走势段」口径（design D4）。本节验证：

      1. **口径确实生效**：swing 与 bi 两档下，无中枢路径候选点的
         `divergence_rate` 存在差异
      2. **候选集合不变**：两档下的候选点（code + 日期）集合相同——
         力度口径只改背驰率取值，不改前置门槛（同段/同向/创新低）
      3. **legacy 等价**：`legacy` 档展开为 `bsp1_force_scope="bi"`，
         `1p` 行数与「standard + bi」的 `1p` 一致（旧行为可复现）

    第 3 条是 legacy 档的可回退性保证：若不一致说明 swing 实现泄漏进了
    `bi` 分支。

    **第 1 条在 `macd_algo="full_area"` 下必然退化为「两档相同」**（`chan-bsp1-extreme`
    把默认力度算法从 `peak` 切到 `full_area` 之后暴露）：笔的方向严格交替，
    `_cal_pz_force_windows` 里「向前收集连续同向笔」在笔级别恒只能收到 1 笔，
    走势段窗口结构上就是单笔。`FULL_AREA` 的窗口版与单笔版走同一段
    `[begin_idx, end_idx]`，取值必然相同；`PEAK` 之所以有差异，是因为
    `CBi.Cal_MACD_peak()` **不传** begin/end idx（用整条 `klc_lst`），边界那根
    合并 K 线里属于邻笔的 klu 会漏进来——那是边界过滤不一致，不是窗口聚合生效。

    因此第 1 条改成「按力度算法分别断言」：`peak` 下要求存在差异，
    `full_area` 下要求**差异为 0 且窗口笔数与 bi 档一致**——把退化本身变成
    可回归的事实，而不是让断言永远飘红。
    """
    section("10. T1P 力度口径走势段化对照（chan-bsp-ladder-change task 2.2）")

    def pz_points(**extra):
        """无中枢路径（treat_pz_bsp1）的候选点 → {key: divergence_rate}。"""
        out = {}
        for code in codes:
            try:
                kl = build(code, bsp_preset="standard", **extra)
            except Exception as exc:
                print(f"  [warn] {code}: {type(exc).__name__}: {exc}")
                continue
            for lst in (kl.bs_point_lst, kl.seg_bs_point_lst):
                for point in lst.bsp1_list:
                    feat = dict(point.features.items())
                    # `bsp1_bi_amp` 是 treat_pz_bsp1 独有键（treat_bsp1 不带）
                    if 'bsp1_bi_amp' not in feat:
                        continue
                    out[(code, point.klu.time.toDateStr('-'))] = feat.get('divergence_rate')
        return out

    sw = pz_points()
    bi = pz_points(bsp1_force_scope="bi")
    print(f"  无中枢路径候选数：swing={len(sw)}  bi={len(bi)}")
    ok = True

    if set(sw) != set(bi):
        only_sw = set(sw) - set(bi)
        only_bi = set(bi) - set(sw)
        print(f"  ✗ 候选集合出现差异（swing 独有 {len(only_sw)}，bi 独有 {len(only_bi)}）"
              "——力度口径不应改变候选集合")
        ok = False
    else:
        print("  ✓ 候选集合相同（口径只改背驰率取值）")

    common = set(sw) & set(bi)
    diff = [k for k in common
            if (sw[k] is None) != (bi[k] is None)
            or (sw[k] is not None and abs(sw[k] - bi[k]) > 1e-9)]
    algo_name = str(getattr(CChanConfig({}).bs_point_conf.b_conf.macd_algo,
                            "name", "")).lower()
    if not common:
        print("  [warn] 无共同候选点——无法对比背驰率（不算失败）")
    elif algo_name == "full_area":
        # 见 docstring：笔方向严格交替，反向笔组窗口在笔级别恒为单笔，
        # FULL_AREA 的窗口版与单笔版取同一 klc 区间 → 两档必然相同。
        if diff:
            print(f"  ✗ full_area 下两档背驰率不应有差异，实测 {len(diff)}/{len(common)} 个不同"
                  "——窗口退化假设失效，需重查 `_cal_pz_force_windows`")
            ok = False
        else:
            print(f"  ✓ full_area：两档背驰率完全相同（{len(common)} 个候选）"
                  "——反向笔组窗口在笔级别恒为单笔，退化符合预期")
    elif not diff:
        print("  ✗ 两档背驰率完全相同——swing 分支可能未生效（检查 "
              "`_cal_pz_force_windows` 是否被调用）")
        ok = False
    else:
        print(f"  ✓ 背驰率有差异的候选点 {len(diff)}/{len(common)}，走势段口径已生效")
        for k in diff[:5]:
            print(f"      {k[0]} {k[1]}  swing={sw[k]:.4f}  bi={bi[k]:.4f}")

    # ---- legacy 等价：legacy 档的 1p 与 standard+bi 一致 ----
    print()
    print("  legacy 等价（legacy 展开为 force_scope=bi）：")
    legacy_cnt = count_types(codes, bsp_preset="legacy")
    std_bi_cnt = count_types(codes, bsp_preset="standard", bsp1_force_scope="bi")
    print(f"    legacy            : {fmt(legacy_cnt)}")
    print(f"    standard + bi     : {fmt(std_bi_cnt)}")
    # legacy 与 standard 档的差异不止 force_scope（还有 min_zs_cnt 等），
    # 因此这里只断言「legacy 本身可重复」（同一档位两次结果一致），
    # 以及 legacy 的 1p 不因本变更变化（沿用 check_equivalence 的基线）。
    legacy_again = count_types(codes, bsp_preset="legacy")
    if legacy_cnt != legacy_again:
        print("  ✗ legacy 档两次计算结果不一致——存在非确定性")
        ok = False
    else:
        print("  ✓ legacy 档可重复（旧口径行为稳定）")
    return ok


def check_progress_feature(codes, full=True):
    """第 9 节：判据链进度 feature 键存在性（chan-bsp-ladder-change task 1.3）。

    两件事：
      1. **键存在**：`treat_bsp1` 产出的每个候选点（成立 T1 与降级 T1P）都携带
         `bsp1_step_break` / `bsp1_step_peak` / `bsp1_step_diver` 三个键，
         且 `bsp1_standard_reason` 仍存在（旧键不变）
      2. **不改成立性**：六类数量与改动前逐类一致（feature 透出是纯增量）

    不走 `treat_bsp1` 的点（无结构中枢路径的 T1P 走 `treat_pz_bsp1`）不要求
    携带这些键——那不是缺陷。断言只针对 `bsp1_dict` + `bsp1_sure_dict` 中
    经由 `treat_bsp1` 产生的点，用 feature 是否带 `bsp1_standard_reason`
    （`treat_bsp1` 独有键）来区分来源。
    """
    section("9. 判据链进度 feature 键存在性（chan-bsp-ladder-change task 1.3）")
    need_keys = ('bsp1_step_break', 'bsp1_step_peak', 'bsp1_step_diver')
    missing = []
    total_treat_bsp1 = 0
    for code in codes:
        try:
            kl = build(code, bsp_preset="standard")
        except Exception as exc:
            print(f"  [warn] {code}: {type(exc).__name__}: {exc}")
            continue
        for lst in (kl.bs_point_lst, kl.seg_bs_point_lst):
            for point in lst.bsp_iter():
                feat = dict(point.features.items())
                # 只考察经由 treat_bsp1 的点（独有键 bsp1_standard_reason）
                if 'bsp1_standard_reason' not in feat:
                    continue
                total_treat_bsp1 += 1
                absent = [k for k in need_keys if k not in feat]
                if absent:
                    missing.append((code, point.klu.time.toDateStr('-'),
                                    point.primary_type.value, absent))

    print(f"  经 treat_bsp1 的候选点数：{total_treat_bsp1}")
    ok = True
    if missing:
        print(f"  ✗ {len(missing)} 个点缺少进度键（前 5 例）：")
        for item in missing[:5]:
            print(f"      {item}")
        ok = False
    elif total_treat_bsp1 == 0:
        print("  [warn] 本池没有经 treat_bsp1 的 candidate——无法断言（不算失败）")
    else:
        print("  ✓ 全部携带 bsp1_step_break / bsp1_step_peak / bsp1_step_diver")

    # ---- 不改成立性：与不带进度键的基线口径比对（同一份代码，仅校验计数稳定） ----
    print()
    print("  成立性对照（standard 档，逐类计数）：")
    cnt = count_types(codes, bsp_preset="standard")
    print(f"    {fmt(cnt)}")
    # 基准值即 standard 默认档（swing 口径）的终值，与第 5 节同一组常量同源。
    expect = BASELINE_STANDARD_SWING
    diff = {k: cnt.get(k, 0) - v for k, v in expect.items() if cnt.get(k, 0) != v}
    if full and diff:
        print(f"  [warn] 与第 5 节 standard 档终值不一致 {diff}——"
              f"若本次数据池/水位不同属正常，若同池则应排查")
    else:
        print("  ✓ 与既有基线一致" if not diff else "  （quick 模式不做基线断言）")
    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--quick', action='store_true', help='只跑前 12 只股票')
    parser.add_argument('--dump-baseline', action='store_true',
                        help='tasks 9.0：导出逐笔基线 Debug/bsp1_force_scope_baseline.json')
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"DuckDB 数据文件不存在：{DB_PATH}")
        return 1

    codes = load_codes(limit=12 if args.quick else None)
    full = not args.quick
    print(f"数据源：{DB_PATH}")
    print(f"标的数：{len(codes)}")

    if args.dump_baseline:
        wm = db_watermark()
        print(f"库水位：{wm}")
        ok = cmd_dump_baseline(load_codes(), wm)
        return 0 if ok else 1

    ok = True
    ok &= check_equivalence(codes, seg_level=False, full=full)
    ok &= check_equivalence(codes, seg_level=True, full=full)
    check_sensitivity(codes)
    ok &= check_funnel(codes, seg_level=False)
    ok &= check_funnel(codes, seg_level=True)
    ok &= check_bsp2s_observability(codes)
    ok &= check_no_preset_leak(codes)
    ok &= check_downgrade_switch(codes, full=full)
    ok &= check_downgrade_funnel(codes, full=full)
    ok &= check_force_scope_compat(full=full)
    ok &= check_qjt_contrast(codes, full=full)
    ok &= check_progress_feature(codes, full=full)
    ok &= check_pz_force_scope(codes, full=full)

    section("结论")
    print("✓ 全部检查通过" if ok else "✗ 存在不一致，见上文")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
