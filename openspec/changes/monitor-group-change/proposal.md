## Why

监控页目前只有「盈利/亏损 + 周期」两个侧栏过滤维度，且两个 tab 的统计项与盈利走势均为全局口径；被监控标的增多后，用户无法按自己的组织方式（策略、板块、批次等）切分监控集合。买卖点页「加入监控」弹窗也不承载分组信息，监控记录加入后无法再归类。项目内自选股（watchlist）已有成熟的 folder 分组模式，监控域缺少同等能力。

## What Changes

- **新增监控分组实体**：PG 新建 `monitor_group` 表（id、name、sort_order），`monitor` 表新增可空 `group_id` FK；删除分组将组内记录 `group_id` 置 NULL（保留监控记录，区别于 watchlist 的 CASCADE 语义）。
- **加入监控携带分组**：买卖点页「加入监控」弹窗新增分组选择（可选，默认未分组）与快速新建分组入口；`POST /api/monitor` 接受可选 `group_id`。
- **分组管理入口**：监控页左侧栏新增分组树（对齐 WatchlistView 模式：hover 重命名/删除图标 + 模式化新建/重命名弹窗 + ElMessageBox 删除确认），支持拖拽排序（reorder 接口）。
- **分组过滤**：`GET /api/monitor` 与 `GET /api/monitor/completed` 新增 `group_id` 服务端查询参数（含「未分组」与「全部」语义）；监控中与已完成两个 tab 的左侧栏均提供分组过滤。
- **统计与走势联动**：选中分组后，监控中 tab 的统计项（总体盈利/胜率/涨幅最大）与盈利走势图按该组数据计算；监控页本地过滤维度（周期/盈亏）与分组过滤正交共存。

## Capabilities

### New Capabilities

- `monitor-grouping`: 监控分组全生命周期——分组实体与排序、加入监控时选择/新建分组、监控页左侧栏分组管理与拖拽排序、监控中/已完成两个 tab 的分组过滤、统计项与盈利走势的分组联动口径。

### Modified Capabilities

<!-- 无：openspec/specs/ 下尚无已归档的监控相关 spec（bsp-monitoring 的 spec 尚在
     monitor-page-change 变更内未归档）；对未归档变更内 spec 的扩展不构成对
     已归档 spec 的修改，故以独立新能力 monitor-grouping 承载本变更全部需求增量。 -->

## Impact

- **PG schema**：`WebAPI/monitor_store.py` 惰性建表新增 `monitor_group` 表 + `monitor.group_id` 列（`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`），存量记录 `group_id` 为 NULL 即「未分组」，无需数据迁移。
- **后端**：`WebAPI/routers/monitor.py` 新增分组 CRUD + reorder 端点（复用 `watchlist.py` 的路由模式），`GET /monitor`、`GET /monitor/completed`、`POST /monitor` 扩展参数。
- **前端**：`front/src/views/monitor/MonitorView.vue`（左侧栏分组树 + 过滤 + 统计/走势联动）、`front/src/views/bsp/BspView.vue`（加入监控弹窗分组选择）、`front/src/api/modules/monitor.ts`（新端点与类型）。
- **不修改**：`CChan` 计算流水线；DuckDB K 线数据；归因/自动卖出结算逻辑（`settle_monitor`/`end_monitor` 不触碰分组字段）。
- **相邻变更**：与 `watchlist-page-change`（进行中）无文件交集；`monitor-page-change` 已完成归档在案，本变更为其后续增量，不复用其变更目录。
