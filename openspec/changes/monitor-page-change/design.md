## Context

监控页面（`/monitor` 与 `/monitor/completed`）的前后端代码已全部落地，由 MSW mock 驱动。但其 spec 级别需求散落在三处：

| 来源变更 | 持有需求 | 状态 |
|----------|----------|------|
| `system-page-change` | `bsp-monitoring`：监控列表与盈利走势、监控完成与归因（含 U5 LLM 真实现） | 变更中（已实现） |
| `chan-stock-manage` | `bsp-monitoring`：卖点自动卖出与结算（U4） | 变更中（未实现） |
| `chan-web-viewer` | design.md D10 KeepAlive 以监控页为联调样本、tasks 7.2 验证 CompletedView 带参跳转 | 变更中（已实现） |

此外 `kline-chart-change` 的 `kline-chart-appearance` spec 定义了「虚拟买卖点」标记——消费 `/api/monitor` 数据在 K 线图叠加，属于监控能力的**消费方**而非需求定义方，需求归属关系不变。

前端监控模块现状（均为已实现，见 `Front/src/views/monitor/`）：

- `MonitorView.vue`：监控中标的列表 + 盈利走势图 + 汇总卡 + 手动结束/详情跳转
- `CompletedView.vue`：完成标的列表 + 亏损归因面板 + 批量/单项 LLM 分析 + ViewAttribution 抽屉
- `SampleDrawer.vue`：归因详情抽屉（失败类别、输入摘要、盈亏）
- 5 个 API 端点（mock 完整）：`GET /api/monitor`、`GET /api/monitor/completed`、`GET /api/monitor/profit-series`、`POST /api/monitor/{id}/end`、`POST /api/monitor/{id}/analyze`

## Goals / Non-Goals

**Goals:**
- 将散落在 `system-page-change`、`chan-stock-manage`、`chan-web-viewer` 中的监控页面 spec 需求整合到本变更
- 从 `chan-web-viewer` 中移除监控页面 KeepAlive 联调引用（为最终删除 chan-web-viewer 铺路）
- 同步裁剪来源变更（删 spec 文件、proposal Capabilities、design/tasks 关联条目）

**Non-Goals:**
- 不新增/修改后端代码——监控页面已完整落地
- 不归档任一来源变更——仅做需求条目的跨变更迁移
- 不修改 `kline-chart-change`（其虚拟买卖点属于消费方行为，归属关系不变）
- 周期列表改造仅限前端展示层（`MonitorView` 筛选项与标签映射、mock 数据），不改后端监控接口契约

## Decisions

### D1. 需求归属：三条 Requirement 全部进入 `bsp-monitoring`

三条来自不同来源变更的 requirement 目标能力一致（`bsp-monitoring`），合并后三者由本变更统一维护，来源变更删除对应内容。

| Requirement | 来源 | 实现状态 | 本变更动作 |
|-------------|------|----------|-----------|
| 监控列表与盈利走势 | `system-page-change` | 已实现 | 迁入 spec |
| 监控完成与归因 | `system-page-change` | 已实现（U5 LLM 已接真） | 迁入 spec |
| 卖点自动卖出与结算 | `chan-stock-manage` | 未实现 | 迁入 spec |

- **备选**：将三条 requirement 分别留在原变更——否决，monitor-page-change 的定位就是监控页统一入口。

### D2. `chan-web-viewer` 监控内容迁移范围

`chan-web-viewer` 与监控相关的内容仅为 KeepAlive 联调引用（design.md D10 以 `monitor/completed?code=` 为带参跳转样本、tasks 7.2 验证 CompletedView 的 query.code watch），不涉及 spec requirement 层面。

- **迁移**：tasks 7.2 中的 `CompletedView` 带参跳转验证作为本变更 tasks 的已有功能验证条目
- **保留**：KeepAlive 的通用实现（`AppShell.vue` 的 `<KeepAlive>`、router 的 `scrollBehavior`、`scrollMemory`）仍在 `chan-web-viewer`——这些是跨页面通用能力，与监控页面无直接归属关系

### D3. `kline-chart-change` 不改动

`kline-chart-change` 的 `kline-chart-appearance` spec 中「虚拟买卖点标记」需求消费 `/api/monitor` 数据绘制 K 线图上的监控标记。该需求是监控数据的**消费方**，非监控页面的需求定义。归属关系不变，不纳入本变更迁移范围。

### D4. 监控周期列表对齐买卖点页口径（2026-10-02 新增需求）

监控页左侧周期列表（`MonitorView.vue` 的 `klTypeItems`）现值为 `全部 → 日线 → 60分钟 → 30分钟`，与买卖点页已定稿口径（`bsp-page-change`：`30分 → 60分 → 日线 → 周线 → 月线`，无 1/5/15 分钟）不一致。对齐方案：

- **选项与顺序**：`klTypeItems` 改为 `全部周期 → 30分(30m) → 60分(60m) → 日线(D) → 周线(W) → 月线(M)`；聚合项「全部周期」保留置顶。
- **标签映射同步**：`MonitorView.vue` 与 `SampleDrawer.vue` 两处 `klType` 标签映射删除 `15m` 残留、补 `W: 周线`/`M: 月线`。
- **mock 数据**：`Front/src/mock/data/monitor.ts` 的 `klTypes` 从 `['15m','30m','60m','D']` 改为 `['30m','60m','D','W','M']`，使周线/月线记录可被过滤与展示验证。
- **不改后端**：周期过滤仍为前端行为（本条针对 D4 周期列表改造；列表字段契约补齐见 D5）。

### D5. 监控列表字段契约补齐（2026-10-02 新增：修复监控中列表不渲染 bug）

**Bug 根因**：前端 `MonitorView` 按 mock 富结构渲染（`industries`/`bsp_type`/`direction`/`bsp_price`/`bsp_date`/`max_profit`/`max_drawdown`/`change_pct`），而真实后端 `GET /api/monitor`（`_row_to_dict`）只返回 monitor 表原始列 + `name`/`current_price`/`current_pnl_pct`。渲染中 `row.max_profit.toFixed(2)` 等对 `undefined` 调方法抛 TypeError，整表渲染失败显示空白。

**修复 = 后端补齐 + 前端容错**（后端为主，字段语义对齐前端既有 `MonitorItem` 类型）：

- **`bsp_price` ← `entry_price`**：监控即以买卖点价格入场，同值换名。
- **`industries`**：按页股票批量查 `stock_industry`（rank≤3 名称数组，同 `bsp_store.get_industries_for_codes` 语义），查不到给 `[]`。
- **`current_price`/`change_pct`**：`_enrich_with_real_time_pnl` 已有 DuckDB 最新收盘价逻辑，扩展为取最新两根算涨跌幅；DuckDB 不可用时降级 `current_price=null`、`change_pct=0`。
- **`max_profit`/`max_drawdown`**：DuckDB 取该股票**日线**自 `monitor_start_time` 起的最高/最低收盘价相对 `entry_price` 的百分比（监控期间浮盈极值口径）；无数据时 0。
- **`bsp_type`/`direction`/`bsp_date`**：monitor 表未存买卖点上下文，从 `bsp_index` 按 `(code, kl_type)` 回查**监控开始时间前最近一条**买卖点（监控的语义起点）；查不到给兜底（`bsp_type=''`、`direction='buy'`、`bsp_date=monitor_start_time` 的 ms）。
- **前端容错**：`MonitorView`/`CompletedView` 数值列对 null/undefined 兜底显示 `--`（`max_profit`/`max_drawdown`/`current_price`/`change_pct`），不再裸调 `.toFixed()`。
- **`list_completed` 同步补齐**（`CompletedView` 消费同一套字段 + `end_price`/`profit` 由 `sold_price`/`pnl_pct` 映射）。

**否决备选**：仅前端容错（列表能渲染但买卖点/行业/极值列全空，页面失去意义）；改 monitor 表加列冗余买卖点上下文（写入路径要动 `create_monitor` 契约，且 bsp_index 回查已可覆盖）。

### D6. 监控单页整合：删除「完成」菜单与路由（2026-10-02 新增）

现状：顶部导航（`Topnav.vue`）有「监控」与「完成」两个菜单项，`/monitor` 与 `/monitor/completed` 两个路由、两个视图组件，页内另有 `el-radio-group` tab 切换。整合方案：

- **删除** `Topnav.vue` 的 `monitor-completed` 菜单项；**删除** `routes.ts` 的 `monitor/completed` 路由（`name: 'monitor-completed'`）。
- **整合**：`CompletedView.vue` 的内容（完成列表、统计卡、归因面板、批量/单项 LLM 分析、`SampleDrawer` 抽屉）并入 `MonitorView.vue`；「监控中/已完成」`el-radio-group` tab 移至页面顶部，切换时整体替换内容区（监控中内容 ↔ 已完成内容），**不走路由跳转**。
- **KeepAlive/带参跳入**：原「监控 → 完成（`?code=`）」跨页跳转变为页内 tab 切换 + 选中标的定位；`CompletedView` 原 `watch(() => route.query.code)` 逻辑改为页内状态~~（详情按钮直接切换 tab 并定位行）~~（该页内切 tab 定位链路已随 D13 删除查看详情按钮整体移除，已完成 tab 仅由顶部 tab 手动切换到达）。
- **归因相关状态**（`drawerVisible`/`drawerItem`/批量进度）随内容并入 `MonitorView`；`SampleDrawer.vue` 组件保留复用不合并。
- **备选否决**：保留两个路由仅去掉菜单项（tab 切换仍走路由，KeepAlive 缓存两份实例，状态割裂）。

### D7. 搜索框对齐 K 线页：下拉选择后精确查询（2026-10-02 新增）

现状：监控页搜索为 `el-input` 关键词模糊过滤（300ms 防抖）。K 线页（`kline-metadata-change` D5/D6）为 `el-autocomplete` 远程下拉 + Enter 语义 + 300ms 本地防抖。对齐方案：

- **复用 K 线页模式**：`el-autocomplete` + `searchStocks`（`api/modules/stock`）远程候选 + 300ms `setTimeout` 本地防抖 + 后发覆盖；候选项展示 code + 名称。
- **查询语义**：点选候选或回车后，按所选标的 code **精确过滤**监控列表（替换原关键词模糊过滤）；清空输入恢复全量。
- **过滤实现**：监控列表数据量小，仍为前端过滤（`filteredList` 中 keyword 条件改为精确 code 匹配），不加后端参数。

- **查询与重置按钮**（2026-10-02 增补）：搜索框旁提供「查询」「重置」两个按钮——查询=应用当前选中标的的精确过滤；重置=清空搜索输入与选中标的，恢复全量展示。仍为纯前端过滤，不加后端参数。
- **已完成 tab 同步改造**（2026-10-02 增补）：已完成 tab 的搜索框由 `el-input` 关键词模糊搜索替换为与监控中一致的 `el-autocomplete` 精确查询模式（含查询/重置按钮），两个 tab 共用同一套搜索状态与候选逻辑，按 tab 维度独立选中标的。

### D8. 买卖点时间 + 收益率列 + 走视图表着色（2026-10-02 新增）

- **买卖点时间列**：展示加入监控时选择的买卖点时间（模拟买入的入场时间，收益计算起点）。数据源沿用 D5 的 `bsp_date`（`bsp_index` 回查监控开始前最近一条买卖点；若加入监控入口显式携带所选买卖点时间则优先使用）。
- **收益率列**：`(当前价 − 买卖点价) / 买卖点价 × 100%`，即自买卖点时间起持有至当前的模拟买入累计涨跌；正=盈利（红）、负=亏损（绿）。后端 `_enrich_with_real_time_pnl` 已算 `current_pnl_pct`，前端补列展示并红涨绿跌着色（复用 `ChangeBadge`）。
- **盈利走势重定义**：「监控中」tab 的盈利走势改为由监控中列表各标的**收益率列**统计生成（如逐日聚合或均值曲线），替换现 mock `profit-series` 随机游走口径；单只走势模式保留。
- **着色**：ECharts 走势曲线按 y 值分段着色——收益率 > 0 红色、< 0 绿色（visualMap piecewise 或 splitLine 分段 series），0 轴参考线。
- **后端改动最小化**：`current_pnl_pct` 已存在；走势统计优先前端聚合（列表已含全部监控中标的收益率），不改 `/api/monitor` 契约。
- **口径 pin-down**（2026-10-02 增补）：「买卖点价格」统一语义为**股票加入监控时所选时间点的股价**（监控中/已完成两列表同口径；后端 `bsp_price←entry_price` 映射已满足）；监控中收益率 = 买卖点价格 vs 当前价涨跌幅（`current_pnl_pct`）；已完成收益率 = 买卖点价格 vs 转完成时价格涨跌幅（后端 `profit←pnl_pct`，即结算时锁定值，前端展示 `profit` 列）。

### D9. 「方向」与「买卖点」列合并为「买卖点类型」列（2026-10-02 新增）

现状：监控中/已完成两个表格各有「买卖点」列（显示 `bsp_type`，如 2B）与「方向」列（显示 买/卖）。`bsp_type` 尾字母 B/S 本身已携带方向语义（B=买、S=卖），两列信息重叠。合并方案：

- **展示层合并**：删除「买卖点」与「方向」两列，替换为单一「买卖点类型」列，直接展示 `bsp_type` 值（如 2B、2S、3B、1S）；B 系（买）红 badge、S 系（卖）绿 badge，沿用红涨绿跌。
- **数据契约不变**：后端仍返回 `bsp_type` 与 `direction` 两个字段，仅前端表格展示层合并，不改 `/api/monitor` 契约与 `MonitorItem` 类型。
- **同步范围**：监控中与已完成两个表格同步合并。
- **备选否决**：后端合并为单字段（改契约，且 `direction` 在归因/统计等其他消费处仍被使用）。

### D10. 布局与列裁剪（2026-10-02 新增）

- **盈利走势下移**：监控中 tab 内容顺序调整为「汇总统计卡 → 搜索 + 列表 → 盈利走势」，盈利走势模块移至列表下方。
- **删除两列**：监控中列表删除「最大盈利」（`max_profit`）与「最大回撤」（`max_drawdown`）两列。仅前端不展示，**字段契约保留**——后端仍返回这两个字段（`MonitorItem` 类型不动），归因抽屉等其他消费处不受影响；mock 数据字段保留。

### D11. 监控中统计项重做（2026-10-02 新增）

现状：汇总卡为「总体盈利（加权平均）+ 监控中数量 + 累计完成」。重做方案（卡顺序即展示顺序）：

- **总体盈利（%）**：口径从加权平均改为**监控中列表收益率列的求和**（`Σ current_pnl_pct`；null 行跳过）。
- **当前胜率**（新增，位于总体盈利后）：`当前价 > 买卖点价格` 的标的计为胜；胜率 = 胜数 / 参与统计总数。`current_price` 或 `bsp_price` 缺失（null）的行不计入分子分母。
- **涨幅最大**（新增）：监控中列表当日涨跌幅（`change_pct`）的最高值（对应标的与数值一并展示，如 `+5.23%`）。
- 监控中数量 / 累计完成两卡保留在后续位置。

### D12. 双击名称/编码跳转 K 线页（2026-10-02 新增）

- **跳转语义**：监控中与已完成两个表格「名称 / 编码」列的值支持**双击**跳转到 K 线页面，并携带该行的「级别」（`kl_type`）值，K 线页按该级别加载。
- **实现要点**：`cell-stock` 容器加 `@dblclick` 跳转（query 带 `code` + 级别参数）；实施时核对 K 线页路由的既有参数约定（参数名以 `Front/src/router/routes.ts` 与 K 线页读取逻辑为准）。
- **备选否决**：单击跳转（与点选候选/文本选择冲突，双击为终端惯例）。

### D13. 删除监控中列表操作栏「查看详情」按钮（2026-10-04 新增）

- **删除范围**：`MonitorView.vue` 监控中列表操作栏的「查看详情」按钮及 `onViewDetail` 页内切 tab 定位链路整体移除——含 `highlightCode` 高亮状态、`completedRowClass` 的 `row--hl` 定位样式、监控中表格整行 `@row-dblclick="onViewDetail"` 绑定。
- **操作栏收敛**：监控中表格操作栏仅剩「手动结束」（`status === 'monitoring'` 行）；已完成表格操作栏仍为「查看归因」。
- **不受影响**：双击「名称/编码」跳 K 线（D12，`cell-stock` 的 `@dblclick`）保留；失败原因汇总面板与已完成列表的归因抽屉入口（`SampleDrawer`，`onViewAttrDetail`）保留——spec「查看归因详情」requirement 不受本决策影响。
- **tab 到达方式**：已完成 tab 仅由顶部「监控中/已完成」tab 手动切换到达，无页内跨 tab 定位捷径。
- **备选否决**：仅删按钮保留整行双击定位（按钮删了功能还在，删得不彻底）。

### D14. 来源下拉查询 + 字典接口 + 统计联动（2026-10-04 新增）

现状：来源列已展示 `source_type` 两级（chan→「缠论」、strategy→策略标签 `strategy_label`），但无来源查询条件；两 tab 统计卡基于全量列表计算；自选页无「加入监控」入口。

- **字典接口**：后端新增 `GET /api/monitor/sources`，返回 `[{value, label, source_type, instance_id?}]`——value 为过滤键（`'chan'` / `'strategy:<instance_id>'` / `'watchlist'`），label 为展示名。数据源为 monitor 表 distinct `(source_type, instance_id)` + 策略实例名（复用 `_fill_bsp_context` 的实例名缓存语义），前端下拉消费，SHALL NOT 硬编码策略实例。
- **来源枚举扩展**：`monitor_store.create_monitor` 的 `source_type` 白名单与前端 `CreateMonitorPayload` 增加 `'watchlist'`；来源列三分支：chan/缺省→「缠论」、strategy→策略标签、watchlist→「自选」。
- **自选页加入监控入口**：`WatchlistView` 行操作新增「加入监控」，弹窗复用 BspView 行级弹窗模式（级别/买卖点时间/价格/分组可选），缺省现价与当前时间，提交携带 `source_type='watchlist'`。
- **过滤实现**：沿用 D7 前端过滤模式（列表数据已在内存）——来源过滤为 `source_type`（+ `instance_id`）匹配，与 code 精确过滤可叠加；「全部来源」即不过滤。查询/重置按钮语义扩展：重置同时清空来源选择。
- **统计联动**：两 tab 统计 computed 改为消费来源过滤后的列表（监控中 tab 为 D11 五项统计、已完成 tab 为完成总数/胜率/平均盈利/盈利比），来源选择变化即重算，清空恢复全量。
- **mock**：MSW handler 补 `GET /api/monitor/sources` 与 watchlist 来源样例数据。
- **备选否决**：前端从列表数据提取来源选项（仅覆盖当前 tab 已加载列表，两 tab 选项不一致，且与「字典结构」诉求不符）。

## Risks / Trade-offs

- **[来源变更的 openspec validate 可能报错]** → 裁剪后重新 validate，确保无残留引用
- **[迁移遗漏]** → tasks 中显式列出每个来源变更的删除项，grep 确认零残留

## Migration Plan

1. **创建** `monitor-page-change` 的 proposal / spec / design / tasks
2. **裁剪** `system-page-change`：删除 `specs/bsp-monitoring/`、proposal Capabilities 中 `bsp-monitoring` 条目、design D4 映射表中监控行、tasks 中监控相关条目
3. **裁剪** `chan-stock-manage`：删除 `specs/bsp-monitoring/`（最后一条 requirement）、proposal Capabilities 中 `bsp-monitoring` 条目、tasks 对应条目
4. **裁剪** `chan-web-viewer`：design.md D10 中移除 `monitor`/`CompletedView` 示例，tasks 7.2 中移除 CompletedView 验证条目（本变更承接）
5. **验证**：`openspec validate` 对所有受影响变更通过

## Open Questions

- 无。三个来源变更的需求切分边界已明确，迁移为纯工件操作，不涉及实现。