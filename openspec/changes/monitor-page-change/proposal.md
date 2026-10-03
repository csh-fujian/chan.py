## Why

股票监控页面的需求目前散落在多个变更中：`system-page-change` 持有「监控列表与盈利走势」「监控完成与归因」两条核心 spec、`chan-stock-manage` 保留「卖点自动卖出与结算」的未实现需求；前端监控页面（`MonitorView`/`CompletedView`）已完整落地 5 个 mock API 端点。此外 `chan-web-viewer` 的 design.md D10（页面缓存 KeepAlive）以监控页为联调样本，tasks 7.2 亦引用监控完成页的 KeepAlive 行为。随着 `chan-web-viewer` 拆分为独立页面级变更，监控相关需求需要集中到 `monitor-page-change`，由该变更全权维护监控页面的 spec、设计决策与实现任务。

## What Changes

- **新建 `bsp-monitoring` 能力**，整合三条 spec requirement：
  - 监控列表与盈利走势（自 `system-page-change` 迁入，口径修正为百分比）
  - 监控完成与归因（自 `system-page-change` 迁入，含 U5 LLM 归因接真实现）
  - 卖点自动卖出与结算（自 `chan-stock-manage` 迁入，U4 未实现）
- **从 `chan-web-viewer` 中移除监控页面的 KeepAlive 联调引用**：design.md D10 中监控相关示例与 tasks 7.2 中对 `CompletedView` 的带参跳转验证迁移至本变更；chan-web-viewer 的 KeepAlive 通用能力（`AppShell.vue`/`router` 层）保留在该变更不动，本变更仅迁移监控页作为 KeepAlive 消费者侧的验证条目
- **同步裁剪来源变更**：`system-page-change` 的 `specs/bsp-monitoring/` 整体移除、proposal/design/tasks 同步删除监控条目；`chan-stock-manage` 的 `specs/bsp-monitoring/` 整体移除、proposal Capabilities/tasks 同步删除
- **不新增实现**：监控页面（`MonitorView`/`CompletedView`/`SampleDrawer`）与 5 个监控 API（`getMonitorList`/`getCompletedList`/`getProfitSeries`/`endMonitor`/`analyzeMonitor`）已存在，本变更不修改其代码

## Capabilities

### New Capabilities

- `bsp-monitoring`: 股票监控页面完整能力——监控列表与盈利走势（总体盈利百分比口径）、监控完成与大模型亏损归因分析（LLM 真实生成，盈利<5% 限定）、卖点自动卖出与结算（按监控周期缠论卖点检测触发自动结算）

### Modified Capabilities

<!-- 无：openspec/specs/ 下尚无 bsp-monitoring 已归档 spec；system-page-change 与 chan-stock-manage 均为未归档变更，在其中移除 delta 不构成对已归档 spec 的修改。 -->

## Impact

- **openspec 工件**：
  - 本变更新增 `specs/bsp-monitoring/spec.md`（三条 requirement）
  - `system-page-change` 删除 `specs/bsp-monitoring/`、proposal Capabilities 移除 `bsp-monitoring`、design/tasks 删除监控条目
  - `chan-stock-manage` 删除 `specs/bsp-monitoring/`、proposal Capabilities 移除 `bsp-monitoring`、tasks 删除对应条目
  - `chan-web-viewer` 的 design.md D10 与 tasks 7.2 中监控页面 KeepAlive 引用迁移至本变更
- **前端（现状记录，不修改）**：`Front/src/views/monitor/MonitorView.vue` + `CompletedView.vue` + `SampleDrawer.vue`、`Front/src/api/modules/monitor.ts`（5 端点）、`Front/src/mock/data|handlers/monitor.ts`
- **后端（现状记录，不修改）**：`WebAPI/routers/monitor.py`（5 端点，其中 `analyze` 已在 system-page-change U5 中接真 LLM）
- **不修改**：`CChan` 计算流水线；DuckDB K 线数据；PG 买卖点索引（归 bsp-page-change）