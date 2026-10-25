# Proposal

## Why

《文档/一买一卖差异点说明.md》§4.3 指控「c 段必须创**整个趋势**的新低」，修复载体 `check_new_extreme`（`bsp1_new_extreme` 判据）已覆盖「比较范围」维度，但复查发现**相等极值被放行**：`worse` 判定用严格 `<`（`BSPJudgement.py:100-102`），c 段低点**恰好等于**比较范围内前低时判据通过。理论上「回到前低」（双底/平低结构）不是「创出」新低——价格没有走出新的极端，b/c 力度对比失去意义，这类形态更接近中枢扩展而非一买。`ZS.out_bi_is_peak`（`ZS.py:372`，`bs1_peak` 判据）同样是严格 `<`，两条极值判据口径一致地放行相等，需要一起收紧。此外 §4.1 补充实证（55/66 的 T1 位置上全级别多笔中枢数多于线段内中枢数，趋势被线段边界切断）提示「新低比较范围是否越出线段」应成为可显式选择的口径，而非硬编码。

## What Changes

- **极值判定收紧为严格优**：`check_new_extreme` 的 `worse` 比较从 `<` 改为 `<=`（买点侧；卖点镜像 `>` 改为 `>=`），`ZS.out_bi_is_peak` 同步收紧，两条极值判据保持同一口径。相等极值不再通过。
- **新增 `bsp1_new_extreme_mode="level"` 口径**：比较列表从「该线段内笔」扩展为「该笔之前的全量同向笔」（跨线段），对应 §六 审计口径「该笔之前所有同向笔」。默认仍为 `trend_start`，`level` 为显式收紧选项。
- **不改动**：`check_bsp1_standard` 的四项判据结构与短路顺序、`bsp1_trend`/`bsp1_dif_div`/`bsp1_zero_axis` 判据、降级路由（`chan-standard-bsp1-change`，其 D1-c 的 `mode="all"` 覆写语义不受影响——`all` 与 `level` 都是显式取值）。
- **BREAKING（行为）**：standard 档下 T1 数量（当前 14）与降级点数量会减少（复权数据中精确相等低点非罕见，缩幅须实测）；`bsp_index` 的 `1`/`1p` 行需回刷。
- **回退**：本变更属于判据语义修正，无独立开关；回退依赖档位机制——若 `legacy` 档等价基线受影响则说明实现有误（legacy 下 `bsp1_new_extreme=False`、`bs1_peak` 走旧链路，两条收紧路径都不生效，基线必须不变）。

## Capabilities

### New Capabilities

- `chan-bsp1-extreme`: 第一类买卖点极值判据的严格性契约——「创趋势新低/新高」的判定必须是严格优于（相等不通过）、两条极值判据（`bsp1_new_extreme` 与 `bs1_peak`）口径一致、比较范围的显式取值（trend_start / prev_zs_in / all / level）及各自语义。

### Modified Capabilities

（无——`bsp-index` 的收录口径不因判据收紧而改写 spec 行为，仅行数随重算变化。）

## Impact

- **核心库**：`ChanAnalyse/BuySellPoint/BSPJudgement.py`（`check_new_extreme` 的 `worse` 比较 + `mode` 分支扩展）、`ChanAnalyse/ZS/ZS.py`（`out_bi_is_peak` 同步收紧 + 口径互指注释）、`ChanAnalyse/BuySellPoint/BSPointList.py`（`cal_single_bs1point` 把全量 `bi_list` 传入 `check_bsp1_standard` 链路以支撑 `level` 模式）、`ChanAnalyse/BuySellPoint/BSPointConfig.py`（`bsp1_new_extreme_mode` 白名单加 `level`）。
- **判据链路耦合提示**：`chan-standard-bsp1-change`（进行中）的 D1-c 依赖 `check_new_extreme` 的 `mode` 参数语义；两变更有实现顺序约束（见该变更 tasks），须先落地降级路由再收紧极值，或合并排期。
- **下游数据**：PG `bsp_index` 全量回刷（`config_fingerprint` 因 `bsp1_new_extreme_mode` 取值集合扩展而变化，需确认是否加入 `FINGERPRINT_KEYS`——该 key 已在列则取值变化自然使指纹失效）。
- **文档**：`文档/一买一卖差异点说明.md` §4.3 回标从「已修复」改为「按 mode 收紧 + 严格优」；`文档/缠论策略.md`（判据变更同步约定）、`Document/README.md` 买卖点参数段补 `level` 模式与严格优语义。
- **验证**：`Debug/bsp_standard_equivalence.py` 的 standard 档基线数字更新（T1/降级点缩幅实测锁定）；legacy 基线必须不变（258/69/318/317/61/50）。
