## Context

自选页现状（见 proposal.md - Why）：`WatchlistView.vue` 约 550 行单文件组件，数据加载仅在 `onMounted` 与增删改后的 `reload()`；搜索为前端 computed 过滤；删除按钮受 `v-if="f.id !== 1"` 守卫（PG 未播种默认文件夹，用户首建文件夹拿到 id=1 被误保护，已核实线上 `watchlist_folder` 表 id=1 即「银行」）；无重命名 UI（API `PATCH /watchlist/folders/{id}` 前后端均就绪）；无排序字段与拖拽能力；AppShell 的 KeepAlive 缓存所有页面。后端 `watchlist_store.py` psycopg2 裸 SQL + PG 不可达时内存降级，双表无 `sort_order`。

约束：不修改 `CChan` 计算流水线；沿用「PG 存业务元数据、裸 SQL DAO」约定；前端默认 mock（`VITE_USE_MOCK=false` 当前指向真实后端），mock handler 需与真实接口行为同步。

## Goals / Non-Goals

**Goals:**

- 修复三个缺陷（搜索不走后端、删除守卫误伤、切换不刷新），补齐两个能力（重命名 UI、拖拽排序持久化），确定缓存刷新策略。
- 排序方案在「有 PG」「PG 降级内存」两种模式下行为一致（顺序均被记住，降级模式仅进程内有效）。

**Non-Goals:**

- 不做跨页事件通知总线（见 D4）。
- 不改 `kline-watchlist`（K 线页集成）。`watchlist` 底层能力需求已自 chan-stock-manage 迁入本变更（见 D7），其已实现行为不变。
- 不做服务端分页（当前文件夹股票量级为几十，沿用全量返回 + 前端分页）。
- 不做移动端触摸拖拽适配（桌面端鼠标长按为主，SortableJS 默认兼容触摸）。

## Decisions

### D1. 搜索：`q` 参数进既有列表接口，按钮 + 回车双触发

`GET /watchlist/folders/{id}/stocks` 增加可选 `q` 参数；「全部」视图沿用前端跨文件夹聚合，但每个分片请求携带同一 `q`。匹配在 SQL 层做：`watchlist_item.code` 子串 OR `stock.name` 子串（JOIN `stock` 表，name 不在 item 表内）。

- 备选 A：独立 `GET /watchlist/search?q=` 端点——多一条路由、与「全部」聚合逻辑重复，否决。
- 备选 B：维持纯前端过滤——用户明确要求走后端，且「全部」视图本就全量拉取后过滤，掩盖了接口缺失，否决。
- UI：搜索按钮紧邻输入框（复用现有 `btn` 样式），`@keyup.enter` 同触发；保留输入防抖仅用于重置页码的旧行为移除，输入本身不再触发查询（显式触发，避免每键一请求）。

### D2. 排序：双表 `sort_order` 列 + 两个 reorder 端点

```sql
ALTER TABLE watchlist_folder ADD COLUMN IF NOT EXISTS sort_order INT NOT NULL DEFAULT 0;
ALTER TABLE watchlist_item   ADD COLUMN IF NOT EXISTS sort_order INT NOT NULL DEFAULT 0;
```

- 初始回填：存量行按 `sort_order = id`（folder）/ `sort_order = id`（item，其 SERIAL id 大致等价于 `added_at` 序）一次性 UPDATE；`init.sql` 同步加列，`watchlist_store._ensure_tables()` 内 `ADD COLUMN IF NOT EXISTS` 兜底（对齐既有惰性建表模式）。
- 查询序：`list_folders` 改 `ORDER BY sort_order, id`；`get_folder_stocks`/`_get_folder_codes` 改 `ORDER BY sort_order, id`。
- 接口：
  - `PUT /watchlist/folders/reorder`，body `{ids: [3,1,2]}`——一次事务全量覆盖 `sort_order`（下标即新序）。全量覆盖比分片增量简单且幂等；文件夹数量级 <100，无性能问题。
  - `PUT /watchlist/folders/{id}/stocks/reorder`，body `{codes: [...]}`——同文件夹内全量覆盖。
- 内存降级：`_WATCH_FOLDERS` 为每个 folder 增 `sort_order`，items 用 codes 数组天然序，reorder 直接重排 list。
- 备选：不加列，改按 `name` 或 `position` 浮点排序——name 不稳定、浮点需分配间隙，均否决。

### D3. 拖拽：vuedraggable@next（SortableJS），文件夹树长按 + 表格行拖

- 依赖：`vuedraggable`（Vue 3 版，v4 `vuedraggable@next`）封装 SortableJS；表格行拖拽用其底层 `sortablejs` 挂到 `el-table` 的 tbody（Element Plus 官方推荐做法，配 `row-key`）。
- 文件夹树：`<draggable :delay="200" :delay-on-touch-only="false" :touch-start-threshold="4">` 包裹用户文件夹 v-for；「全部」节点渲染在 draggable 容器之外，天然不参与拖拽。`delay=200ms` 即「长按」阈值；普通点击因未达 delay 不进入拖拽，点击选中不受影响（SortableJS `delay` 机制）。
- 股票表格：行拖拽 handle 不设（整行可拖）会与行内按钮/双击跳转冲突，故设 `handle` 为行首单元格小拖拽图标（新增），双击跳 K 线等既有交互保留。
- `onEnd` 回调：本地先重排数组（乐观更新，UI 即时响应），成功后调 reorder 接口；失败则回滚本地序并 toast。
- 备选：`el-table` 官方无行拖拽；`react-dnd` 等与 Vue 不兼容，否决。

### D4. 缓存刷新：KeepAlive 保留 + `onActivated` 全量刷新

`WatchlistView` 增加 `onActivated(() => reload())`，`reload()` 复用现有「loadFolders → loadStocks」并带当前 `q`。选中文件夹、搜索关键字作为组件响应式状态被缓存自然保留，刷新仅重拉数据。

- 为何不做跨页通知（用户第 6 条疑问）：通知机制只覆盖「通过既有加自选入口」的变更，漏掉直接调 API、另一标签页、批量导入等路径；且需在 7 处调用点埋事件。`onActivated` 在页面重新可见这一唯一汇聚点兜底，天然覆盖所有变更来源，成本约 3 行。**结论：不引入通知机制。**
- 为何不整页剔除缓存：会丢失选中文件夹、搜索词、滚动位置，且与项目 `design.md D10` 的页面缓存约定不一致（KLineView/CompletedView 均为「缓存 + 激活时按需刷新」先例）。
- 「全部」视图刷新 = 按文件夹数 N 次带 `q` 的请求并发聚合，N < 10 可接受；后续如需可加聚合端点，不在本次范围。

### D5. 删除守卫：移除 `f.id !== 1`，「全部」以渲染位置隔离

「全部」节点本就是独立渲染分支（不在 `v-for` 内），删除按钮仅存在于文件夹 v-for 中——移除 `v-if="f.id !== 1"` 即达成「仅全部不可删」。删除确认框保留现有「含 N 只股票一并移出」提示。无需后端改动（`DELETE /folders/{id}` 已级联）。

### D6. 重命名 UI：复用新建对话框，模式化单 dialog

单一「文件夹对话框」组件状态 `mode: 'create' | 'rename'` + `editingId`，避免两份近似 dialog；校验（非空、重名提示可选）与现有新建逻辑一致。

### D7. 需求迁移：chan-stock-manage 的自选需求并入本变更

chan-stock-manage 的 `specs/watchlist` 三项需求整体迁入本变更 `specs/watchlist`，由本变更统一维护；该变更侧同步删除能力声明与需求表述。逐条判断：

- **自选文件夹分类**：已实现、与本次无冲突 → 原样迁移。
- **自选股票字段展示**（名称/编码/股价/行业≤3）：已实现（`stock_store.get_top_industries(code, 3)` + `IndustryBadges` 渲染）、无冲突 → 原样迁移。
- **批量加入自选**：「多选批量加入」已实现（历史买卖点页/选股器弹窗，按 code 去重入夹）→ 迁移；原「加入时默认以日期作为文件夹名称并允许修改」条款**与已上线交互冲突且全链路无实现**——实际为「弹窗选择已有目标文件夹」，无新建文件夹流程（BspView / Screener 均如此）→ 按裁定从旧变更删除、不迁入。若需该 UX 须另立新需求。
- 附带订正：chan-stock-manage 任务 6.1 原文括注「默认日期作文件夹名、可改」与实现不符，已随迁移订正为实际行为。

### D8. 来源「自选」：复用 monitor.source_type 扩第三取值，不新增列

`monitor.source_type` 已存在（strategy-signal-page design D6，VARCHAR DEFAULT 'chan'，现取值 `'chan'|'strategy'`，语义为信号来源维度）。本变更是其第三个取值 `'watchlist'`：

- `create_monitor` 白名单 `("chan", "strategy")` 放行 `"watchlist"`；无 DDL（列已在，纯白名单放行，`update.sql` 无需改动）。
- 监控页来源列（`MonitorView.vue`，strategy-signal-page 任务 6.1）：`strategy` → 策略标签、`watchlist` → 「自选」、`chan`/缺省 → 「缠论」。`strategy_label` 填充逻辑不动（watchlist 来源不产生该字段）。
- **为什么**：语义自洽——BspView 记录源自缠论买卖点（'chan'），自选页记录是用户人工挑选无信号驱动（'watchlist'），strategy 是策略信号；三值共用一列一列语义链完整。
- **备选**：新增 `source_page` 之类的「加入入口页」字段——多一列、与 source_type 语义重叠（strategy 也是一种入口），否决。

### D9. 弹窗交互：复用 BspView 模式，三处差异单独设计

弹窗要素与 [BspView 加入监控弹窗]（级别/时间/分组/价格联动/快速新建分组）同构，差异三处：

1. **级别**：BspView 随行 `kl_type` 不可选；自选页无买卖点上下文 → 新增级别下拉（30m/60m/D/W/M，词表同 `klOptions`），默认日线。级别或时间变化 → 300ms 防抖 `getPriceAt(code, 级别, 时间)` 取价（沿用 BspView D12 联动）。
2. **时间默认**：BspView 默认行 `bsp_date`；自选页默认「此刻」（`toDateTimeStr(Date.now())`），提供「此刻」按钮同 BspView。
3. **价格初始值**：BspView 为行 `bsp_price`；自选页为列表行股价（`Stock.price`）。取价失败兜底即「保留当前价格并提示」（当前价格 = 初始行股价或上次联动成功值），与 BspView 语义一致。

### D10. 批量加入：前端逐只循环既有 POST /api/monitor，不新增批量端点

- 弹窗对所选 N 只股票统一参数（级别/时间/分组），提交时前端循环调既有 `POST /api/monitor`（携带 `source_type='watchlist'`）。
- **为什么**：单条端点的去重语义、分组校验、错误 detail 完全复用；N 为用户手工多选（几到几十），循环成本可忽略。批量端点要新事务边界与部分失败协议，收益不成比例。
- 价格：提交前逐只 `getPriceAt`；取价失败的股票按行股价提交并计入「取价失败提示」（不阻塞整体）。
- 部分失败：单只失败（4xx detail）继续后续，完成汇总「成功 X / 失败 Y」；批量弹窗不逐只展示价格（N 行价格表过重），失败明细靠汇总提示。

### D11. 前端 API 层：`CreateMonitorPayload.source_type` 可选透传

`Front/src/api/modules/monitor.ts` 的 `CreateMonitorPayload` 增加可选 `source_type?: 'chan' | 'strategy' | 'watchlist'`；WatchlistView 提交时传 `'watchlist'`。BspView 不传（后端缺省 'chan'，行为不变）。mock handlers（monitor.ts）同步支持 `source_type` 落库与列表返回。

## Risks / Trade-offs

- [存量库无 `sort_order` 概念，迁移瞬间旧版本代码仍按旧序查询] → `ADD COLUMN DEFAULT 0` 对旧 SQL（`ORDER BY id`/`added_at`）无影响；新序在首次 reorder 前保持旧序，回填 `sort_order=id` 保证新旧序一致，可平滑共存。
- [拖拽与既有交互（行双击跳 K 线、行内按钮）冲突] → 股票行拖拽限定 handle；文件夹靠 `delay` 区分点击与拖拽；验收场景「短按不触发拖拽」覆盖。
- [「全部」视图搜索 = N 次并发请求，文件夹多时首屏变慢] → 量级可控（文件夹 <100、股票几十）；design 已标注后续可加聚合端点的演进方向，不阻塞本次。
- [PG 降级内存模式下排序、删除仅进程内有效，重启丢失] → 与既有降级语义一致（本就无持久化），不新增承诺。
- [乐观更新后接口失败导致本地序与服务端不一致] → `onEnd` 失败回滚本地数组并提示；用户重拖可自愈。
- [vuedraggable 社区版维护平淡] → 其底层 SortableJS 仍活跃；接口面小（一个列表拖拽 + 一个 tbody 拖拽），替换成本可控。
- [自选页级别无对应 DuckDB K 线数据（如 30m/60m 未灌数）导致 `getPriceAt` 失败] → D9 兜底：保留当前价格（行股价）并提示；用户可换级别或接受行股价提交（spec「价格口径与取价失败」场景覆盖）。
- [批量循环中用户切换页面/参数状态被并发修改] → 提交期间禁用弹窗操作（loading 态），循环为串行 await 无共享可变状态。
- [`source_type` 三值下 mock 与真后端行为漂移] → mock handlers 与真后端同步放行 `'watchlist'`（写入即返回），端到端任务 7.3 双模式各验一次来源列显示。

## Migration Plan

1. 后端先行：`_ensure_tables` 加列 + 存量回填 + reorder 端点 + `q` 参数（旧接口向后兼容，新参数可选）。
2. 前端随后：修复三项缺陷 → 重命名 UI → 拖拽（依赖新增）→ `onActivated`。
3. 加入监控增量：后端 `source_type` 白名单放行（纯参数校验，无 DDL，对旧调用零影响）→ 前端 API 层 → WatchlistView 弹窗（行级 → 批量）→ mock 同步。
4. 回滚：新列与新端点对旧前端无影响，回滚前端即回到旧行为；`sort_order` 列保留无害；`source_type='watchlist'` 记录在旧前端显示「缠论」（缺省分支），无破坏性。

## Open Questions

- 无（问题 2「仅守护全部」与问题 5「sort_order 方案」已由用户确认；搜索的触发方式、长按时长、拖拽 handle 属实现细节，不改 specs 与任务拆分）。
