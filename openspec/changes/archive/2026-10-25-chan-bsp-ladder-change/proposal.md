# Proposal: chan-bsp-ladder-change（确认阶梯三轴重构 + T1P 力度口径走势段化）

## Why

现行确认阶梯（`bsp-ladder-change` 归档产物）的 L1/L3 是两个**平行标签**：L1 是时间窗共振（±5 自然日）、L3 是「所在笔 vs 前前笔」的逐笔背驰预警，二者与买卖点成立性判据链没有结构关联，也不构成任何递进——用户无法从 `ladder` 读出「这个候选点离成立还差多远」。同时 `treat_pz_bsp1`（T1P）的背驰仍是**单笔对单笔**口径（前前笔 vs 末笔），与 T1 已完成的走势段口径（`bsp1_force_scope="swing"`，chan-standard-bsp1-change §4.4 修复）不一致，同一缺陷在两个类型上口径分裂。

用户（2026-10-25 探索会话）重定义了阶梯：把 ladder 从「佐证类型标签」改为**三轴证据体系**（本级判据链进度 / 子级结构佐证 / 本级分型强弱），沿结构映射窗口取缔时间窗，并要求分型强弱分档。经六轮问答收敛（进度两档 7/2 上取整、分型三档实体口径、多标签组合落库、非一买类型本次不动）。

## What Changes

- **阶梯三轴重构（BREAKING，T1/1p 家族）**：删除现有 L1/L2/L3 定义，未确认点改为三轴独立证据组合：
  - **进度轴**（单值）：判据链①~⑦顺序短路，进度 1~4 → `L1`，进度 5~7 → `L2`；七项全过但线段未确认 → `L2`（「只欠结构确认」）；线段确认 → `L4`（语义不变）
  - **佐证轴**（三档，结构映射窗口）：`L2-3` 子级同向**已确认**买点（现 `bsp1_qjt` 命中资格）/ `L2-2` 子级同向候选且子级进度在 L1 档 / `L2-1` 子级末端分型形成
  - **分型轴**（三档，买卖镜像，实体口径）：`L3-3` C 实体上沿 > A 实体上沿 / `L3-2` C 实体上沿收复 A 实体一半以上（含相等边界）/ `L3-1` 其余
  - 组合展示：多标签并集（如 `L1|L2-3|L3-3`），`bsp_index.ladder` 存组合字符串
- **非一买类型（T2/2s/3a/3b）阶梯置 NULL**（过渡期方案 A，探索会话推荐）：不跑旧口径，前端显示「未定级」，待后续变更逐类型接入
- **T1P 力度口径走势段化**：`treat_pz_bsp1` 的逐笔背驰改为走势段窗口（b/c 段按**反向笔组**分隔：末组含 `last_bi` 为 c，倒数第二组为 b），与 T1 的 `bsp1_force_scope` 同构；「面积背驰」表述统一更名「力度背驰」（跟随 `macd_algo` 配置）
- **区间套口径统一**：新佐证轴沿结构映射（c 走势段窗口），废弃 L1 时间窗（±5 自然日 / ±2 小时）；`cal_l1_resonance` 与 `L1_WINDOW_SECONDS` 退役
- **数据库扩容**：`bsp_index.ladder VARCHAR(2)` → `VARCHAR(16)`，走 `bsp_store._ensure_tables()` 惰性 DDL + `update-win.sql` 幂等追加（Windows 机器运行）；存量行全量回刷，旧 L1-L3 语义废弃，`ladder_of_legacy` 存量映射退役
- **范围限定**：仅 T1/1p 家族（笔级别 + 线段级别，泛型同构自动覆盖两层）；二买/类二/三买判据与锚点零改动；`chan-bsp1-qjt` 内核特征（`bsp1_qjt_hit`）保留不删，佐证轴 L2-3 直接复用其命中资格
- **两个待确认默认**（探索会话推荐项，提案内标注，可在 review 时推翻）：
  1. 非一买类型过渡 = 方案 A（置 NULL）
  2. 分型实体口径 = (a) 原始 K 线聚合（合并 K 线内全部 `max(open,close)` 取最大，不含影线）

## Capabilities

### New Capabilities

- `bsp-ladder-progress`: 确认阶梯三轴体系——进度轴（判据链两档划分与全过未确认归属）、佐证轴（结构映射窗口、三档强度、子级递归资格）、分型轴（实体口径三档、买卖镜像）、三轴组合的落库与展示契约、非一买类型的 NULL 过渡语义

### Modified Capabilities

- `bsp-index`: 索引行 `ladder` 字段从单一 `L1`/`L2`/`L3`/`L4` 改为三轴组合值（`L4` 保留），级别判定语义重写；存量行回刷与旧语义废弃条款
- `bsp-page`: 「级别」列从单徽章改为多标签组合展示（最多三个并列徽章 + 各轴说明），L4 行为不变，NULL 过渡期「未定级」展示
- `kline-unsure-visual`: K 线 hover tooltip 的四级阶梯说明改为三轴说明（进度/佐证/分型），当前已达成轴高亮，依赖 `/api/klines` 的 `bsp[].ladder` 组合值
- `chan-bsp1-qjt`: 「与 WebAPI L1 共振的边界」条款重写——L1 共振被本变更退役删除，边界条款从「L1 SHALL 保留」改为「佐证轴 L2-3 复用本特征命中资格」；内核特征本身零行为改动

## Impact

- **核心库**：`ChanAnalyse/BuySellPoint/BSPointList.py`（`treat_pz_bsp1` 走势段窗口计算，约 30 行；判据链进度信息透出——`check_bsp1_standard` 已返回 `reason`，需暴露「通过步数」计数）；`ChanAnalyse/BuySellPoint/BSPJudgement.py`（判据链进度计数函数，只读推导）；分型强弱分级（只读函数，输入三根合并 K 线，WebAPI 层调用，不改 `CKLine_Combiner.update_fx`）
- **WebAPI**：`bsp_ladder.py` 整体重写（`cal_ladder` → 三轴推导；`cal_l1_resonance`/`L1_WINDOW_SECONDS`/`is_beichi_warning` 退役）；`bsp_store.py`（`ladder` 列扩容 + `ladder_of_legacy` 退役 + `DIRECTIONAL_LABELS` 不动）；`incremental_engine.py`/`serializer.py`（ladder 组合值推导调用）；`update-win.sql` 幂等追加 `ALTER TABLE ... TYPE VARCHAR(16)`
- **前端**：`front/src/utils/bspLadder.ts` 词表重写（三轴定义 + 组合解析）；`BspView.vue` 级别列多徽章；`KLineChart.vue`/`chan_bsp.ts` tooltip 三轴说明；`api/types.ts` 类型更新；MSW mock 数据补组合值样本
- **数据库**：`bsp_index` 全量回刷（`config_fingerprint` 语义变化——ladder 口径不属于 `FINGERPRINT_KEYS` 的配置项，但落库结果整套替换机制天然覆盖；旧 L1-L3 行不可增量迁移，必须全量）
- **文档**：`文档/缠论策略.md`（判据变更同步约定——T1P 力度口径 + ladder 章节）、`Document/README.md` 买卖点参数段、`WebAPI/bsp_ladder.py` 模块 docstring 边界说明（与 `chan-bsp1-qjt` 的新边界）
- **验证**：`Debug/bsp_standard_equivalence.py` 增加 T1P 走势段口径对照行；新增 ladder 三轴分布统计（41 只日线基线）；步进与批量终态一致性断言（佐证轴子级滞后翻转不改变成立性——沿用 chan-standard-bsp1-change D8 的不变量）
- **BREAKING（下游数据）**：`bsp_index.ladder` 全量回刷；前端旧词表无法解读新值（版本同步发布）
