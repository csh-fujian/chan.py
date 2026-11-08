## Why

买卖点页的查询表单能筛周期、买卖点类型、方向、日期范围与确认状态，唯独筛不了列表里的「级别」列（确认阶梯 L1–L4）——用户看得到每行的级别徽章，却无法「只看 L4 确认买卖点」，只能靠肉眼翻页。同时页面上「加入监控」按钮是个存根（`BspView.onBatchMonitor` 只弹一句「演示」提示），多选后无法真正批量建监控，与自选页已落地的批量加入监控能力不对等。

## What Changes

- 买卖点页工具栏新增「级别」查询条件（单选，取值 全部 / L4 / L3 / L1 / L2），与既有筛选条件并列，参与服务端过滤与分页；「重置」恢复为全部。
- 后端历史买卖点查询接口新增级别过滤，按确认阶梯级别（`ladder`，取值 `L1`/`L2`/`L3`/`L4`）过滤；存量 `ladder` 为 NULL 的行按其 `is_sure` 兜底映射后再匹配（`true` → `L4`，`false` → `L2`），与列表回显口径一致。
- 买卖点页「加入监控」按钮由存根改为真实批量实现：选中的每条买卖点记录按其**自身上下文**加入监控（`kl_type` 取该行周期、监控起始时间取该行买卖点时间、入场价取该时间点该周期的收盘价，取价失败兜底该行买卖点价格），分组由弹窗统一选择。与同页既有行级「加入监控」同口径（含卖点行）。
- 批量提交按 `(code, kl_type)` 去重后逐条串行提交，单条失败不中断，完成后汇总成功/失败数；提交成功后清空选择集。
- **BREAKING**（前端内部契约）：买卖点列表记录的标识由「行号占位」改为稳定复合键，`BspRecord.id` 类型由 `number` 变为 `string`。修复多选在切换筛选条件后按行号命中、把上一个筛选的股票误标为选中的问题。

## Capabilities

### New Capabilities

（无。本次改动全部落在既有能力的既有需求上。）

### Modified Capabilities

- `bsp-index`: 「历史买卖点查询」需求新增级别（`ladder`）过滤条件；新增「记录标识稳定」要求（列表记录的标识在分页与条件切换间保持不变）。
- `bsp-page`: 「查询与结果列表」需求新增级别查询条件；新增「批量加入监控」需求（页面此前只有行级加入监控）。

## Impact

**后端**

- `WebAPI/routers/bsp.py`：`GET /api/bsp` 新增 `ladder` 查询参数并透传；列表响应 `id` 由 `(page-1)*page_size+idx+1` 行号占位改为稳定复合键。
- `WebAPI/bsp_store.py`：`query_bsp()` 新增级别过滤条件，条件需以 `COALESCE(b.ladder, CASE WHEN b.is_sure THEN 'L4' ELSE 'L2' END)` 形式下推（复用 `bsp_ladder.ladder_of_legacy` 的映射语义），COUNT 与分页共用同一 WHERE。
- 无 DDL 变更：`bsp_index.ladder` 列已存在，本次仅读取；`update-mac.sql`/`update-win.sql` 无需追加。

**前端**

- `Front/src/api/types.ts`：`BspRecord.id` 类型 `number` → `string`。
- `Front/src/api/modules/bsp.ts`：`BspQuery` 新增 `ladder?: string`。
- `Front/src/views/bsp/BspView.vue`：工具栏新增级别下拉；`onBatchMonitor` 存根替换为真实批量实现（复用弹窗、分组行内新建、`getPriceAt` 取价联动等既有设施）。
- `Front/src/mock/data/bsp.ts`：mock 记录补齐与真实接口一致的稳定标识（`VITE_USE_MOCK=false`，仅为保持一致避免成为陷阱）。

**接口消费者**

`BspRecord` 的消费方仅 `BspView.vue`（用作表格 `row-key`）与 `NestingDrawer.vue`（只用 `code` 等字段、不读 `id`），无其他页面消费，类型变更影响面受控。

**不在本次范围**

- 板块聚合 Tab 不带级别筛选（其能力需求为「保留现状」，聚合接口无查询参数）。
- 级别下拉不提供「未定级」选项：存量 NULL 行经兜底映射后必为 `L4` 或 `L2`，不存在未定级桶。
- 不改变 `CChan`/`CBiList`/`CSegListChan`/`CZSList`/`CBSPointList` 的计算逻辑；不改变确认阶梯（`ladder`）的判定算法。
- 不新增「统一参数覆盖」能力：批量一律按各行自身上下文提交。
