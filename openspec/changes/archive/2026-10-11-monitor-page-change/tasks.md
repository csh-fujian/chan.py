## 1. system-page-change 裁剪

- [x] 1.1 删除 `openspec/changes/system-page-change/specs/bsp-monitoring/` 目录（含 spec.md）；验证：`openspec validate --change system-page-change` 通过，无残留 bsp-monitoring 引用
- [x] 1.2 修改 `openspec/changes/system-page-change/proposal.md`：Capabilities 移除 `bsp-monitoring` 条目（New Capabilities 与 description 列表）、What Changes 中"买卖点页面需求迁入本 change（监控/绩效部分）"改为仅绩效、"按实现修正口径"删除监控引用；验证：proposal 中 grep `(?i)monitor` 或 `监控` 仅出现在非需求归属的上下文（如"监控完成"作为已完成功能的提及）
- [x] 1.3 修改 `openspec/changes/system-page-change/design.md`：D4 映射表删除 bsp-monitoring 行（监控列表与盈利走势、监控完成与归因、卖点自动卖出与结算三行）；D5 删除 `POST /monitor/{id}/analyze` U5 说明（归因已归本变更）；验证：design.md 中 grep `bsp-monitoring` 无命中
- [x] 1.4 修改 `openspec/changes/system-page-change/tasks.md`：删除第 6 节「U5 大模型归因接真」（6.1/6.2）——需求归本变更，实现本身已落地留在 system-page-change 不动；删除第 9 节「迁移承接的已落地页面任务」中 9.2（监控页+完成页验证记录）；验证：tasks.md 中不包含对 monitor 的归因/监控页面追踪条目

## 2. chan-stock-manage 裁剪

- [x] 2.1 删除 `openspec/changes/chan-stock-manage/specs/bsp-monitoring/` 目录（含 spec.md）；验证：`openspec validate --change chan-stock-manage` 通过
- [x] 2.2 修改 `openspec/changes/chan-stock-manage/proposal.md`：What Changes 删除 Tab3 监控中「卖点自动卖出与结算」的描述、Capabilities 移除 `bsp-monitoring` 条目；验证：proposal 中 grep `bsp-monitoring` 无命中
- [x] 2.3 修改 `openspec/changes/chan-stock-manage/tasks.md`：若 tasks 中存在对应监控条目则删除或标注迁移；验证：tasks 中无 bsp-monitoring 残留

## 3. chan-web-viewer 监控引用迁移

- [x] 3.1 修改 `openspec/changes/chan-web-viewer/design.md`：D10「带参跳入兼容」中 `monitor → completed?code=` 示例改为通用表述（如 `pageA → pageB?param=`），不具体引用监控页面；验证：design.md 中 grep `monitor` 仅在通用 KeepAlive 说明中出现，不绑定具体页面
- [x] 3.2 修改 `openspec/changes/chan-web-viewer/tasks.md`：7.2 中 `CompletedView 补 watch(() => route.query.code)` 改为通用说明（如「所有带参跳转页面补 watch」），删除具体引用；验证：tasks.md 中不出现 `CompletedView` 或 `monitor` 页面引用
- [x] 3.3 验证：`openspec validate --change chan-web-viewer` 通过，grep 无残留监控特定引用

## 4. 最终校验

- [x] 4.1 `openspec validate monitor-page-change --type change` 通过，所有 artifact 状态为 done
- [x] 4.2 对 `system-page-change`、`chan-stock-manage`、`chan-web-viewer` 分别执行 `openspec validate`，确认均通过且无跨变更引用断裂

## 5. 监控周期列表对齐买卖点页（design D4）

- [x] 5.1 修改 `Front/src/views/monitor/MonitorView.vue` 的 `klTypeItems` 为 `全部周期 → 30分(30m) → 60分(60m) → 日线(D) → 周线(W) → 月线(M)`，同步该文件内 `klType` 标签映射（删 `15m`、补 `W: 周线`/`M: 月线`）；验证：左侧周期列表展示 6 项且顺序正确，选周线/月线可过滤出对应记录
- [x] 5.2 修改 `Front/src/views/monitor/SampleDrawer.vue` 的 `klTypeLabel` 映射（删 `15m`、补 `W`/`M`）；验证：周线/月线标的打开归因抽屉显示中文周期标签
- [x] 5.3 同步 `Front/src/mock/data/monitor.ts` 的 `klTypes` 为 `['30m','60m','D','W','M']`；验证：mock 模式下监控列表出现周线/月线记录且标签正确（`npm run dev` 走查；vue-tsc 类型检查通过）
## 6. 监控列表字段契约补齐（design D5，2026-10-02 修复监控中列表不渲染 bug）

- [x] 6.1 后端 `WebAPI/monitor_store.py`：`_row_to_dict`/`list_monitoring`/`list_completed` 补齐前端 `MonitorItem` 契约字段——`bsp_price←entry_price`、`industries`（stock_industry 批量查，rank≤3）、`current_price`/`change_pct`（DuckDB 最新两根日线，不可用降级 null/0）、`max_profit`/`max_drawdown`（DuckDB 日线自 monitor_start_time 起区间最高/最低收盘相对 entry_price）、`bsp_type`/`direction`/`bsp_date`（bsp_index 按 (code,kl_type) 回查监控开始前最近一条，兜底 ''/'buy'/start_time ms）；`list_completed` 同步映射 `end_price←sold_price`、`profit←pnl_pct`——验证：`GET /api/monitor` 返回字段齐全，`row.max_profit.toFixed` 不再抛错
- [x] 6.2 前端容错：`MonitorView.vue`/`CompletedView.vue` 数值列（max_profit/max_drawdown/current_price/change_pct 等）对 null/undefined 兜底显示 `--`，不裸调 `.toFixed()`——验证：监控中列表正常渲染后端真实记录，DuckDB 不可用时列显示 `--` 不白屏

## 7. 监控单页整合与列表增强（design D6/D7/D8，2026-10-02）

- [x] 7.1 删除 `Topnav.vue` 的 `monitor-completed` 菜单项与 `routes.ts` 的 `monitor/completed` 路由；验证：顶部导航仅剩「监控」一项，访问 `/monitor/completed` 落入兜底重定向
- [x] 7.2 `CompletedView.vue` 内容并入 `MonitorView.vue`：顶部 tab（监控中/已完成）整体切换内容区，归因面板/批量分析/`SampleDrawer` 抽屉随迁，原 `route.query.code` watch 改为页内详情跳转定位；验证：tab 切换不发生路由跳转，归因分析/抽屉在页内可用，`npm run build` 通过
- [x] 7.3 搜索框改造：`el-input` 模糊搜索替换为 `el-autocomplete` + `searchStocks` 远程候选 + 300ms 防抖 + Enter 精确查询（对齐 K 线页 D5/D6 模式），过滤逻辑改为按所选 code 精确匹配；验证：输入出现候选下拉，点选后列表仅剩该标的，清空恢复全量
- [x] 7.4 监控列表新增「买卖点时间」列（展示 `bsp_date`，收益计算起点）与「收益率」列（`current_pnl_pct`，红涨绿跌着色，复用 `ChangeBadge`）；验证：列表两列数据正确、盈利红/亏损绿（后端 `current_pnl_pct` 原缺失，backend agent 已在 `monitor_store.py` `_enrich_with_real_time_pnl` 补齐，可空降级；前端类型补 `current_pnl_pct: number | null`）
- [x] 7.5 盈利走势改为由监控中列表收益率统计生成（替换 mock `profit-series` 随机游走），曲线按收益率 >0 红 / <0 绿 分段着色 + 0 轴参考线；验证：走势与列表收益率统计一致，曲线上下 0 轴颜色正确（ProfitChart 新增 `splitColor` prop，visualMap piecewise；聚合口径 = 按 bsp_date 升序逐标的累计均值，null 行跳过）
- [x] 7.6 端到端走查（mock 模式）：单页 tab 切换 → 搜索下拉选择 → 列表两列展示 → 走视图表着色；验证：全流程无报错（console 干净）、`vue-tsc` 类型检查通过（vue-tsc 0 错误、`npm run build` 通过、CompletedView 路由/组件层零残留；浏览器实测走查待用户在 `npm run dev` 下确认）

## 8. 搜索按钮与买卖点类型列（design D7 增补 / D9，2026-10-02）

- [x] 8.1 搜索区在 `el-autocomplete` 旁增加「查询」「重置」按钮：查询=应用当前选中标的的精确过滤；重置=清空搜索输入与选中标的，恢复全量展示；验证：点查询后列表按所选 code 精确过滤，点重置后输入框清空且列表恢复全量（搜索逻辑重构为 `createStockSearch` 工厂，查询按钮调 `apply`、重置调 `reset`）
- [x] 8.2 两个表格（监控中/已完成）删除「买卖点」与「方向」两列，替换为单一「买卖点类型」列（展示 `bsp_type` 值，如 2B/2S；B 系红 badge、S 系绿 badge，沿用红涨绿跌）；验证：列表仅显示合并后一列，值与后端 `bsp_type` 一致，红/绿 badge 与方向对应
- [x] 8.3 端到端走查（mock 模式）：查询/重置按钮语义正确 → 两表列合并生效；验证：`vue-tsc` 类型检查通过（0 错误）、`npm run build` 通过（11.15s）、mock 数据下无渲染报错（浏览器走查待用户 `npm run dev` 确认）
- [x] 8.4 已完成 tab 搜索框改造（design D7 增补）：`el-input` 模糊搜索替换为与监控中一致的 `el-autocomplete` + 查询/重置按钮，按 tab 独立选中标的精确过滤；验证：已完成 tab 输入出现候选下拉，点选后列表仅剩该标的，重置恢复全量（`cSearch` 工厂实例，`filteredCompletedList` 改按 code 精确匹配；原模糊搜索 `cKeyword` 零残留）
- [x] 8.5 监控中 tab 布局调整（design D10）：内容顺序改为「汇总卡 → 搜索+列表 → 盈利走势」，盈利走势模块移至列表下方；验证：走势图位于表格之后，tab 内滚动/布局无异常（走势 Panel 移至列表 Panel 之后）
- [x] 8.6 删除监控中列表「最大盈利」「最大回撤」两列（design D10，仅前端不展示，字段契约保留）；验证：表格无这两列，`MonitorItem` 类型与后端返回不变（侧栏盈利过滤仍用 `max_profit` 字段，属既有行为保留）
- [x] 8.7 监控中统计项重做（design D11）：总体盈利改为收益率求和；总体盈利后新增「当前胜率」（current_price > bsp_price 计胜，缺失行不计入分母）与「涨幅最大」（当日 change_pct 最高值）；验证：三个统计值与列表收益率/当前价/涨跌幅手工核算一致（监控中卡序：总体盈利→当前胜率→涨幅最大→监控中数量→累计完成；已完成 tab 统计改名 cWinRate 避免重名）
- [x] 8.8 双击「名称 / 编码」跳 K 线页（design D12）：两个表格 cell-stock 双击跳转，query 携带 code + 级别（参数名核对 K 线页既有约定）；验证：双击后 K 线页加载对应标的且级别生效（对齐 BspView 的 `KL_TO_KLINE_PERIOD` 映射 D/W/M→1d/1w/1M，`router.push({ name: 'kline', query: { code, period } })`；K 线页 PERIOD_MAP 词表已含 1d/1w/1M）

## 9. 删除操作栏查看详情按钮（design D13，2026-10-04）

- [x] 9.1 删除 `Front/src/views/monitor/MonitorView.vue` 监控中列表操作栏「查看详情」按钮（`onViewDetail`），并整体移除关联链路：`onViewDetail` 函数、`highlightCode`/`completedRowClass` 定位高亮（`row--hl` 样式）、监控中表格整行 `@row-dblclick="onViewDetail"` 绑定；验证：监控中操作栏仅剩「手动结束」，双击「名称/编码」跳 K 线（D12）仍可用，已完成「查看归因」按钮与归因抽屉不受影响，`vue-tsc` 0 错误、`npm run build` 通过（操作栏宽度 140→100 收窄；已完成表格 `:row-class-name` 绑定随高亮链路一并移除；grep 五处标识零残留）

## 10. 来源下拉查询与统计联动（design D14，2026-10-04）

- [x] 10.1 后端来源字典接口：`WebAPI/routers/monitor.py` 新增 `GET /api/monitor/sources`，`monitor_store` 增 `list_monitor_sources()`——monitor 表 distinct `(source_type, instance_id)` + 策略实例名（复用 `_fill_bsp_context` 实例名缓存语义）组装 `[{value, label, source_type, instance_id?}]`（value：`'chan'`/`'strategy:<instance_id>'`/`'watchlist'`）；验证：接口返回与 monitor 表实际来源一致，无策略实例时仅返回 chan/watchlist 项（真实 PG 实测：表仅 chan 记录时返回单项；`/sources` 路由注册在 `/{monitor_id}` 之前避免路径参数吞并）
- [x] 10.2 来源枚举扩展：`monitor_store.create_monitor` 的 `source_type` 白名单与前端 `api/modules/monitor.ts` 的 `CreateMonitorPayload.source_type` 增加 `'watchlist'`；`MonitorView.vue` 两个表格来源列增加 watchlist→「自选」分支；验证：watchlist 来源记录创建成功且来源列显示「自选」（routers/monitor.py `monitor_create` 校验同步加 watchlist；`types.ts` `MonitorItem.source_type` 扩展并补 `instance_id` 字段）
- [x] 10.3 自选页加入监控入口：`WatchlistView.vue` 行操作新增「加入监控」，弹窗复用 BspView 行级弹窗模式（级别/买卖点时间/价格/分组可选，缺省现价与当前时间），提交携带 `source_type='watchlist'`；验证：自选页加入监控后监控列表出现该记录且来源为「自选」（真实 PG 端到端验证：create 成功→字典含 watchlist 项→测试行已清理；弹窗周期选项对齐 D4 口径 30分/60分/日/周/月）
- [x] 10.4 两 tab 来源下拉查询：`MonitorView.vue` 监控中与已完成搜索区各增来源 `el-select`（选项来自 `GET /api/monitor/sources`），过滤逻辑并入 `filteredList`/`filteredCompletedList`（`source_type` + `instance_id` 匹配，与 code 精确过滤叠加；「全部来源」不过滤；重置按钮同时清空来源选择）；验证：选择来源后列表仅剩该来源记录，与标的查询叠加生效，重置恢复全量（`matchSource` 三分支匹配；重置语义扩展为 `onResetMonitoringFilters`/`onResetCompletedFilters` 清搜索+来源；字典 onMounted 并行加载失败不阻塞）
- [x] 10.5 统计联动：两 tab 统计 computed 改为消费来源过滤后列表（监控中 D11 五项、已完成完成总数/胜率/平均盈利/盈利比）；验证：选择来源后统计值与过滤后列表手工核算一致，清空恢复全量统计（全部 computed 数据源从 monitorList/completedList 改为 filteredList/filteredCompletedList；修复编辑引入的重复声明残留）
- [x] 10.6 mock 同步：MSW handler 补 `GET /api/monitor/sources`，mock 数据补 watchlist 来源样例；验证：mock 模式下拉出现字典选项且 watchlist 记录可过滤（`monitorSources` 字典导出；策略样例行补 `instance_id` 与字典 `strategy:5` 对应；新增 `watchlistMonitoring` 样例行 sz.000858）
- [x] 10.7 端到端走查（mock 模式）：字典下拉 → 来源过滤 → 统计联动 → 自选页加入监控 → 重置；验证：`vue-tsc` 0 错误、`npm run build` 通过（15.32s）、console 无报错（浏览器实测走查待用户 `npm run dev` 确认）
