# Tasks

## 1. 极值判据严格化

- [x] 1.1 `ChanAnalyse/BuySellPoint/BSPJudgement.py` 的 `check_new_extreme`：`worse` 比较改为严格优（买点 `e._low() <= ele._low()`、卖点 `e._high() >= ele._high()` 均计入 worse）。验证：`Debug/bsp1_extreme_strict_synth.py` 的 `test_new_extreme_equal`（内存桩件构造相等极值，不联网）6/6 通过。
- [x] 1.2 `ChanAnalyse/ZS/ZS.py` 的 `out_bi_is_peak` 同步改为严格优，严格性由新增参数 `strict` 承载。验证：`Debug/bsp1_extreme_strict_synth.py` 的 `test_out_bi_is_peak_equal` 6/6 通过（含 `strict=False` 的 legacy 回退用例）；`grep -n "严格优\|strict" ChanAnalyse/ZS/ZS.py` 命中注释与签名。
- [x] 1.2a **（实施中发现，1.2 的直接前提）** 新增配置项 `bs1_peak_strict`：`BSPointConfig` 增加字段、`ChanConfig` 默认 `True` 且 `_BSP_PRESETS["legacy"]` 显式 `False`、`BSPointList.treat_bsp1` 调用 `out_bi_is_peak` 时传入该值、`WebAPI/config_fingerprint.py` 的 `FINGERPRINT_KEYS` 收录。**为什么必需**：`bs1_peak` 在 legacy 档仍是开启的，无此开关时严格优会连带改变 legacy 基线（实测一买 258→255、二买 318→315、类二 317→314、三买A 61→59）。验证：`CChanConfig({}).bs_point_conf.b_conf.bs1_peak_strict is True`、`CChanConfig({"bsp_preset": "legacy"}).bs_point_conf.b_conf.bs1_peak_strict is False`，且 legacy 两侧基线 258/69/318/317/61/50 与 37/8/35/15/2/6 逐项复原。
- [x] 1.3 回归 legacy 等价基线。验证：`Debug/bsp_standard_equivalence.py` 第 1 节「笔级别」与「线段级别」均输出 `✓ 完全一致`（258/69/318/317/61/50 与 37/8/35/15/2/6）。

## 2. 极值比较范围口径化

- [x] 2.1 `ChanAnalyse/BuySellPoint/BSPointConfig.py`：`bsp1_new_extreme_mode` 白名单加 `level`，非法取值仍在构造期抛异常。验证：`CChanConfig({"bsp1_new_extreme_mode": "level"})` 构造成功、`"bogus"` 抛 `CChanException`（实测 `bsp1_new_extreme_mode='bogus' 非法，可选值：trend_start, prev_zs_in, all, level`）。
- [x] 2.2 `ChanAnalyse/BuySellPoint/BSPJudgement.py` 的 `check_new_extreme` 增加 `level` 分支：比较列表取「该笔之前的全量同向笔」（跨线段，不受 `ele_list` 的线段边界限制）。新增 `full_ele_list` 参数；未提供时退回 `all` 并在 info 的 `new_extreme_mode_effective` 标明实际口径（不静默降级）。验证：`Debug/bsp1_extreme_strict_synth.py` 的 `test_level_mode` 3/3 通过（`level` 的 `worse_cnt` 大于 `all`）。
- [x] 2.3 `ChanAnalyse/BuySellPoint/BSPointList.py` 的 `cal_single_bs1point` / `check_bsp1_standard` 链路把全量笔列表传入以支撑 `level`（`cal_single_bs1point` 取 `getattr(bi_list, "bi_list", None)`；线段级别传入 None，`level` 自动退回 `all`）。验证：现有 41 只样本在默认 `trend_start` 下输出与 2.2 之前逐笔一致（`level` 是纯增量，不改默认行为）——由 1.3 的完整回归第 1 节两侧 `✓ 完全一致` 佐证。
- [x] 2.4 更新 `WebAPI/config_fingerprint.py` 注释确认 `bsp1_new_extreme_mode` 已入 `FINGERPRINT_KEYS`，并收录新增的 `bs1_peak_strict`。验证：以 `trend_start` 与 `level` 各算一次指纹（`bbdb3a8fce3c3120` vs `ae6521748cea8adf`）不相等；`bs1_peak_strict` 取值变化同样改变指纹。

## 3. 力度默认算法切换为整段柱体面积

- [x] 3.1 `ChanAnalyse/ChanConfig.py`：`macd_algo` 默认值 `"peak"` → `"full_area"`；`_BSP_PRESETS["legacy"]` 显式加 `"macd_algo": "peak"`。验证：`CChanConfig({})` 的 `bs_point_conf.GetBSConfig(True).macd_algo.name == "FULL_AREA"`，`CChanConfig({"bsp_preset": "legacy"})` 的为 `"PEAK"`。
- [x] 3.2 跑 41 只日线横评并锁定新基线。验证：T1 成立笔数由 13 变为 17；六个变动点（sh.600020/2020-02-04、sz.000020/2021-02-05、sz.000025/2026-07-09 新增买；sh.600018/2024-10-08、sh.600029/2026-02-09 新增卖；sh.600028/2020-09-28 剔除买）方向全部符合 design.md D1 表。
  → `Debug/bsp_standard_equivalence.py` 第 5 节实测 `standard` 档 17/47/16/7/2/1（走势段）、`standard`+`bi` 19/47/17/7/2/3，与 `BASELINE_STANDARD_SWING` / `BASELINE_STANDARD_BI` 逐类一致；`legacy` 258/69/318/317/61/50 不变。六个变动点已用逐点探针按日期逐一确认，方向全部符合 design D1 表。
- [x] 3.3 事后价格验证签核。验证：五个新增点各自 20 个交易日内的极值波动与其买卖方向一致（买点正收益、卖点负收益），被剔除的 sh.600028 极值波动（+3.39%）显著小于其余五点。
  → 独立复核脚本 `Debug/_pv_check.py`（只读 DuckDB，不跑缠论计算）：以买点当日收盘价为基准取之后 20 个交易日的高/低点，六项与 design.md D1 表逐一吻合（+9.23% / +14.32% / +22.20% / −12.22% / −26.66% / +3.39%）。表中此前的 +2.87% 是未复算的旧值，已按实测更正为 +3.39%，结论方向不变。
- [x] 3.4 legacy 档在力度切换后仍逐笔等价。验证：legacy 基线 258/69/318/317/61/50 在本任务完成后仍逐项不变（与 1.3 的基线对照，确认 3.1 的显式锁定生效）。
  → 3.1 生效后重跑 `Debug/bsp_standard_equivalence.py`：笔级别 `✓ 完全一致`（258/69/318/317/61/50）、线段级别 `✓ 完全一致`（37/8/35/15/2/6）。

## 4. 基准案例卡点断言（防误判验收）

- [x] 4.1 固化三层卡点的可重复检查脚本（只读，不改内核）：`Debug/bsp1_three_gates.py`。验证：脚本输出 `sz.000001` 在 `begin_time` 取 2018/2019/2023/2025-06 四次的「线段终点笔集合、候选笔是否在其中、所属线段内多笔中枢数、D3 规则 B 观察区段上的 `full_area` c/b」，前三次结果与 design.md Context 逐项一致（第 1 关不通过、第 2 关 = 1、第 3 关 `PEAK c/b=1.7880` / `FULL_AREA c/b=0.8005`）；退出码 0 表示基准案例仍判不出一买。
- [x] 4.2 在 tasks 验收说明中标注「本变更不改第 1、2 关」。验证：`grep -n "第 1 关\|第 2 关" openspec/changes/chan-bsp1-strict-extreme/tasks.md` 可见该说明；`Debug/bsp1_three_gates.py` 对 2026-07-01 在四个起点下均输出「判不出一买」且退出码 0，确认没有误报为已修复。

> **验收边界（本变更不改第 1、2 关）**：基准案例 `sz.000001` 2026-07-01 的三层卡点中，
> 第 1 关（候选笔不是任何线段终点笔）与第 2 关（线段内 `seg.zs_lst` 只有 1 个多笔中枢，
> `min_zs_cnt=2` 直接否决）**不在本变更范围内**，它们在本次改动完成后仍然卡住，
> 该点也仍然判不出一买。本变更只把第 3 关（力度口径 `peak` → `full_area`）落地。
> `Debug/bsp1_three_gates.py` 的退出码 0 就是这一结论的机器可读形式——
> 它输出「判不出一买」是**预期**，不是失败。

> **回归脚本的两处连带修正（实施中发现，非本变更的判据改动）**：
> 1. `Debug/bsp_standard_equivalence.py` 第 7 节的 `BASELINE_ANCHOR_BI/SWING` 与
>    `EXPECTED_SWING_REMOVED/ADDED` 原本填的是「严格优之后 / full_area 时代」的数值，
>    而该节用 `ANCHOR_ERA_PIN` 把三项都 pin 回了锚点时代。修正后 `1p` 为 53/52
>    （差的那 3 个点正是 design D0 点名的 `sh.600006 bi77`、`sh.600026 bi25`、
>    `sz.000007 bi55`），消失集为锚点时代的 2 个点。**这是测试常量与 pin 口径脱节，
>    不是内核行为回归**——`bi` 档逐笔与锚点 JSON 始终 0 增 0 删 0 漂移。
> 2. 第 10 节断言「swing 与 bi 两档 T1P 背驰率必须不同」在 `full_area` 下永远不成立：
>    笔与线段方向严格交替，`_cal_pz_force_windows` 的「收集连续同向笔」恒只收到 1 笔，
>    262 次调用全部 `b=1, c=1`。`peak` 下曾有的差异来自 `CBi.Cal_MACD_peak()` 不传
>    `begin_idx`/`end_idx` 的边界泄漏，非窗口聚合生效。断言已改为按算法分别判定，
>    事实记录在 `文档/缠论策略.md`。

## 5. 文档同步

- [x] 5.1 `文档/一买一卖差异点说明.md`：§4.3 回标改为「按 mode 收紧 + 严格优」；§三 实证表 standard 档 T1 由 13 更新为 17（并注明这是极值收紧与力度切换叠加后的净值）。验证：文档内两处数字与 `Debug/bsp_standard_equivalence.py` 实测输出一致。
  → 该文件只有三节（无 §4.3），对应内容落在 §二 的「创趋势新低」行：已写明「比较采用**严格优**」且口径「可由 `bsp1_new_extreme_mode` 收紧到 `level`」。§三 实测表已改为 17/47/16/7/2/1（standard 走势段）、19/47/17/7/2/3（`bi` 档），并补「两项各自的效果」与「锚点依赖传播」两张表；数字与 design.md「实测终值」表逐项一致。
- [x] 5.2 `文档/缠论策略.md`：同步判据变更（极值严格优、`level` 口径、力度默认算法）。验证（项目约定：ChanAnalyse 计算逻辑变更须同步本文件）：`grep -n "full_area\|严格优\|level" 文档/缠论策略.md` 三处均有命中。
- [x] 5.3 `Document/README.md` 买卖点参数段补 `bsp1_new_extreme_mode="level"` 与新的默认 `macd_algo`。验证：README 参数表与 `ChanConfig.py` 的实际默认值逐项对照一致。

## Workflow follow-up

- 合并前需确认 `chan-standard-bsp1-change`（进行中）的 D1-c 语义未被 `level` 破坏：该变更依赖 `reason=='trend'` 的降级路由，`level` 只影响 `bsp1_new_extreme` 分支，不改 `bsp1_trend` 短路顺序。
- 归档后需回刷 PG `bsp_index` / `bsp_snapshot`：`macd_algo` 与 `bsp1_new_extreme_mode` 均在 `FINGERPRINT_KEYS` 中，取值变化会自然触发全量重算，无需手工改指纹。
