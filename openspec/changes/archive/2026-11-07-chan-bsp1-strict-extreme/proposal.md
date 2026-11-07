# Proposal

## Why

《文档/一买一卖差异点说明.md》§4.3 指控「c 段必须创**整个趋势**的新低」，修复载体 `check_new_extreme`（`bsp1_new_extreme` 判据）已覆盖「比较范围」维度，但复查发现**相等极值被放行**：`worse` 判定用严格 `<`（`BSPJudgement.py:100-102`），c 段低点**恰好等于**比较范围内前低时判据通过。理论上「回到前低」（双底/平低结构）不是「创出」新低——价格没有走出新的极端，b/c 力度对比失去意义，这类形态更接近中枢扩展而非一买。`ZS.out_bi_is_peak`（`ZS.py:372`，`bs1_peak` 判据）同样是严格 `<`，两条极值判据口径一致地放行相等，需要一起收紧。此外 §4.1 补充实证（55/66 的 T1 位置上全级别多笔中枢数多于线段内中枢数，趋势被线段边界切断）提示「新低比较范围是否越出线段」应成为可显式选择的口径，而非硬编码。

**2026-10-26 追加排查结论**：对基准案例 `sz.000001`（2026-07-01 低点 9.7747，人工认定一买）的
逐层定位显示，即使极值口径与中枢区段全部修正，**力度背驰的默认算法 `peak` 仍会否决该点**：
该点 c 段 13 个交易日跌 11.2%（b 段 27 个交易日跌 8.5%），单根柱体峰值更深但整段面积更小，
`peak` 判 `c/b=1.7880 > 0.9` 不背驰，`full_area` 判 `c/b=0.8005` 成立。41 只日线横评确认
这不是孤例：默认算法由 `peak` 改为 `full_area` 后 T1 成立数 13 → 17，6 个变动点经事后价格
验证全部为改善。因此本变更主体从「极值口径收紧」扩展为**一买判据的三项独立修正**：极值严格性、
力度默认算法、以及极值比较范围的口径化。

## What Changes

- **极值判定收紧为严格优**：`check_new_extreme` 的 `worse` 比较从 `<` 改为 `<=`（买点侧；卖点镜像 `>` 改为 `>=`），`ZS.out_bi_is_peak` 同步收紧，两条极值判据保持同一口径。相等极值不再通过。严格性由新增配置项 `bs1_peak_strict` 控制：`standard` 档默认 `True`，`_BSP_PRESETS["legacy"]` 显式写 `False` 回退到宽松口径——`bs1_peak` 在 legacy 档仍是开启的，没有这个开关就无法同时满足「严格优」与「legacy 逐笔等价」（实测无开关时 legacy 一买 258→255、T1P 69→69 但笔级 T2 318→315）。
- **新增 `bsp1_new_extreme_mode="level"` 口径**：比较列表从「该线段内笔」扩展为「该笔之前的全量同向笔」（跨线段），对应 §六 审计口径「该笔之前所有同向笔」。默认仍为 `trend_start`，`level` 为显式收紧选项。
- **力度背驰默认算法 `peak` → `full_area`**：`ChanConfig.py` 默认值改为整段柱体面积。单根峰值对「急跌赶底」形态钝感（跌幅大、时间短的分段单根柱子天然更深），整段面积与「b/c 两段动能对比」的缠论语义直接对应。`_BSP_PRESETS["legacy"]` 显式写回 `"macd_algo": "peak"` 以保持逐笔等价基线。
- **不改动**：`check_bsp1_standard` 的四项判据结构与短路顺序、`bsp1_trend`/`bsp1_dif_div`/`bsp1_zero_axis` 判据、降级路由（`chan-standard-bsp1-change`，其 D1-c 的 `mode="all"` 覆写语义不受影响——`all` 与 `level` 都是显式取值）、`check_dif_divergence`（基准案例上已验证通过，无需修改）。
- **不在本变更内**：观察区段（区段中枢构建器）与线段归属重构。排查确认它们是基准案例的第 1、2 关卡点，但影响 `CZSList` / `update_zs_in_seg` 架构，需独立 spec 与回归基线。本变更只把设计与实测结论固化在 `design.md`（D2/D3/D5），供后续变更复用。
- **BREAKING（行为）**：standard 档的六类数量全部变化，实测终值（41 只日线，2019-01-01 起、QFQ）：

  | 档位 | 1 | 1p | 2 | 2s | 3a | 3b |
  |---|---|---|---|---|---|---|
  | 改造前（peak，默认） | 13 | 52 | 12 | 4 | 1 | 0 |
  | 改造后（`bi` 口径） | 19 | 47 | 17 | 7 | 2 | 3 |
  | 改造后（`swing` 口径，默认） | 17 | 47 | 16 | 7 | 2 | 1 |

  两个方向叠加：极值收紧使 T1P 53→50（bi）/ 52→49（swing）；力度切换使 T1 13→17（swing）。`2`/`2s`/`3a`/`3b` 的变动不是回归——它们锚定在一买上，成立一买集合一变，下游类型必然随锚点传播（`sh.600025 bi63` 的 T2、`sh.600016 bi28` 与 `sh.600025 bi60` 的 T3B）。`bsp_index` 需全量回刷。
- **回退**：极值部分属判据语义修正，档位回退由 `bs1_peak_strict` 承载（`legacy` 档显式 `False`）；力度部分可单项覆盖 `macd_algo` 回退。整体回退依赖档位机制——`legacy` 档下 `bsp1_new_extreme=False`、`bs1_peak` 走宽松极值链路、`macd_algo="peak"` 显式锁定，三条路径都不生效，基线必须不变（实测 258/69/318/317/61/50 与 37/8/35/15/2/6 均不变）。

## Capabilities

### New Capabilities

- `chan-bsp1-extreme`: 第一类买卖点极值判据与力度判据的严格性契约——「创趋势新低/新高」的判定必须是严格优于（相等不通过）、两条极值判据（`bsp1_new_extreme` 与 `bs1_peak`）口径一致、比较范围的显式取值（trend_start / prev_zs_in / all / level）及各自语义、力度背驰默认算法为整段柱体面积、档位回退的逐笔等价保证。

### Modified Capabilities

（无——`bsp-index` 的收录口径不因判据收紧或默认算法切换而改写 spec 行为，仅行数随重算变化。）

## Impact

- **核心库**：`ChanAnalyse/BuySellPoint/BSPJudgement.py`（`check_new_extreme` 的 `worse` 比较 + `mode` 分支扩展）、`ChanAnalyse/ZS/ZS.py`（`out_bi_is_peak` 增加 `strict` 参数 + 口径互指注释）、`ChanAnalyse/BuySellPoint/BSPointList.py`（`cal_single_bs1point` 把全量 `bi_list` 传入 `check_bsp1_standard` 链路以支撑 `level` 模式；`treat_bsp1` 按 `bs1_peak_strict` 传入极值严格性）、`ChanAnalyse/BuySellPoint/BSPointConfig.py`（`bsp1_new_extreme_mode` 白名单加 `level`、新增 `bs1_peak_strict`）、`ChanAnalyse/ChanConfig.py`（`macd_algo` 默认值 + `bs1_peak_strict` 默认值 + `legacy` 档显式锁定两项）。
- **指纹**：`WebAPI/config_fingerprint.py` 的 `FINGERPRINT_KEYS` 加入 `bs1_peak_strict`（`macd_algo` 与 `bsp1_new_extreme_mode` 本已在列）。
- **判据链路耦合提示**：`chan-standard-bsp1-change`（进行中）的 D1-c 依赖 `check_new_extreme` 的 `mode` 参数语义；两变更有实现顺序约束（见该变更 tasks），须先落地降级路由再收紧极值，或合并排期。
- **下游数据**：PG `bsp_index` 全量回刷（`macd_algo` 与 `bsp1_new_extreme_mode` 均已在 `WebAPI/config_fingerprint.py` 的 `FINGERPRINT_KEYS` 中，取值变化自然使指纹失效并触发重算，无需改指纹逻辑）。
- **文档**：`文档/一买一卖差异点说明.md` §4.3 回标从「已修复」改为「按 mode 收紧 + 严格优」，§三 实证表 T1 13→17；`文档/缠论策略.md`（判据变更同步约定）、`Document/README.md` 买卖点参数段补 `level` 模式、严格优语义与新的默认力度算法。
- **验证**：`Debug/bsp_standard_equivalence.py` 的 standard 档基线数字更新（T1 净值实测锁定）；legacy 基线必须不变（258/69/318/317/61/50）。

### 基准案例的三层卡点（供后续变更引用）

排查确认 `sz.000001` 2026-07-01 判不出一买有三层卡点，本变更只解决第 3 关：

| 关卡 | 内容 | 本变更是否解决 |
|---|---|---|
| 第 1 关 | 候选笔不是任何线段的终点笔（`cal_seg_bs1point` 只遍历 `seg.end_bi`） | 否 |
| 第 2 关 | 线段内中枢数 = 1（`min_zs_cnt=2` 直接否决，力度判据走不到） | 否 |
| 第 3 关 | 力度背驰：`peak` 判 `c/b=1.7880` 不成立，`full_area` 判 `0.8005` 成立 | **是** |

因此本变更完成后基准案例**仍判不出一买**，验收标准以 41 只样本的横评结果为准。
