# Proposal: chan-pattern-sell-signal

## Why

`文档/买卖点走势图/卖点/` 提供 5 个经典顶部看跌形态（乌云盖顶、射击之星、高位吊颈线、高位阴包阳、高位穿头破脚阴线）的判据。`chan-pattern-buy-signal` 已建好形态信号的检测/落库/查询/可视化全链路，但只覆盖买向。卖点形态的市场语义与买点不同：买点是「发现机会」（全市场扫描有价值），卖点是「风控提示」（只对持仓/关注中的股票有意义）。本变更将 5 个顶部形态实现为可计算判据，复用同一条链路（同表加 `direction` 维度），K 线页独立 overlay 标识，列表查询默认收敛到关注范围（自选 ∪ 监控）。

## What Changes

- 新增 5 个顶部形态检测器（`WebAPI/pattern_detector.py` 扩展）：乌云盖顶、射击之星、高位吊颈线、高位阴包阳、高位穿头破脚阴线。与前 8 个多 K 线结构形态不同，这 5 个是 1~2 根 K 线的蜡烛图形态：判据 = 相邻 K 线实体/影线关系 + 高位上下文前置 + 量能佐证；确认点即形态 K 线收盘本身（无需突破确认引擎）。
- **阴包阳与穿头破脚共用一个检测器**（`detect_bearish_engulfing`）：内部按覆盖程度产出两种 `pattern_type`——普通吞没（`high_engulfing`）与穿头破脚（`high_engulfing_gap`，开盘价高于阳线最高价且收盘价低于阳线最低价），同一根 K 线只报穿头破脚（更强形态），置信分上穿头破脚高于普通吞没。
- `PATTERN_META`（`WebAPI/pattern_meta.py`）新增 5 项顶部形态元数据：名称、注意事项（弹窗展示）、置信分评分项（结构/量能/位置三轴）、避坑硬约束（非高位出现丢弃、量能不足降档）。
- `pattern_signal` 表加 `direction VARCHAR(4)` 列（惰性 DDL `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`，存量行回填 `'buy'`）：**同一张表**，唯一键不变（`pattern_type` 已区分买卖向）。`update-win.sql` / `update-mac.sql` 追加变更记录。
- 增量引擎落库扩展：`run_pattern_detection` 结果带 `direction`，`_extract_pattern_rows` / `upsert_pattern_rows` / `hit_to_row` 全链路透传。
- `routers/pattern.py`：`GET /api/pattern` 增加 `direction` 查询参数；**`direction=sell` 且未显式传 `code` 时，默认只返回关注范围（自选 ∪ 监控股票清单）的信号**——列表页不涌进全市场卖点噪音。显式传 `code`（K 线页单股查询）时不过滤。`GET /api/pattern/meta` 返回的 META 带 `direction`。
- `/api/klines` 的 `pattern[]` 每项带 `direction`。
- 前端新增**独立 overlay `chan_sell_pattern`**（第六个 overlay，`Front/src/components/chan/chan_sell_pattern.ts`，复制 `chan_pattern.ts` 改造）：独立注册、独立开关、独立点击 hooks，与笔/段/中枢/买卖点/买点形态五个 overlay 完全分割。顶部形态用独立色系（不与买点形态共用色板）。
- 买卖点页形态 Tab：查询条件增加「买/卖方向」筛选；卖向列表默认只展示关注股票的新卖点（最近 M 根确认），并显示「新卖点信号」提示徽标，语义同买点但作用域收敛到关注清单。
- 置信分体系沿用买点版 0~100 三轴设计，位置轴对卖点为「高位程度」镜像；分数边界沿用 `bsp_grade.py` 教训（地板分/否决项）。

## Capabilities

### New Capabilities
- `chan-pattern-sell-signal`: 顶部看跌形态（乌云盖顶、射击之星、高位吊颈线、高位阴包阳、高位穿头破脚阴线）的检测判据、置信分评分、元数据、落库（direction 维度）、查询接口（关注范围默认作用域）、K 线页独立 overlay 与新卖点提示。

### Modified Capabilities

（无——买点能力 `chan-pattern-signal` 仍在进行中变更里、未归档进主 specs，本变更不对其做 delta；两能力通过共享存储与接口实现，语义各自独立。买点变更归档后如需统一 `direction` 语义，另行处理。）

## Impact

- **后端**：`WebAPI/pattern_detector.py`（+5 检测器 + direction）、`WebAPI/pattern_meta.py`（+5 项 META）、`WebAPI/pattern_store.py`（direction 列惰性 DDL + 行字段扩展）、`WebAPI/routers/pattern.py`（direction 参数 + 关注范围过滤）、`WebAPI/incremental_engine.py`（落库透传）、`WebAPI/serializer.py`（pattern[] 带 direction）。
- **数据库**：`pattern_signal` 加列 `direction`（惰性 DDL 在 `pattern_store._ensure_tables()`，存量行回填 `'buy'`）；`update-win.sql` / `update-mac.sql` 变更记录。
- **前端**：`Front/src/components/chan/chan_sell_pattern.ts` 新 overlay + `index.ts` 注册；KLineChart 接入；`src/api/` pattern client 带 direction；BspView 形态 Tab 方向筛选。
- **缠论核心**：零改动（只读 `CKLine_Unit` 既有 OHLC/volume 属性与 `bi_list`）。
- **依赖**：无新增（复用买点版已引入的 numpy）。
- **风险**：蜡烛图形态（尤其实体比例阈值）对 A 股涨跌停/一字板需做剔除处理（一字板无实体波动，形态失真）；高位判定的窗口参数需真实数据调参；`direction` 列回填必须幂等（重复执行不重复改）。
