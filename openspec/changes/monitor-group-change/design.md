## Context

监控域现状：`monitor` 表（`WebAPI/monitor_store.py`）无分组字段；`GET /monitor` 仅支持 keyword，周期/盈亏为前端本地过滤；监控页左侧栏用 `TreeList` 渲染盈利/周期两组过滤；买卖点页「加入监控」弹窗（`BspView.vue`）已有时间选择与价格联动。自选股域已有完整 folder 分组实现（`watchlist_store.py` 的 `watchlist_folder`/`watchlist_item` + `routers/watchlist.py` 的 CRUD/reorder 端点 + `WatchlistView.vue` 的左侧树交互），构成本设计的模式参照。

## Goals / Non-Goals

**Goals:**

- 监控域获得与 watchlist 同构的分组能力（实体、排序、左侧栏管理、拖拽）
- 分组过滤走服务端查询参数（与已确认的「查询条件放后端」决策一致）
- 统计项与盈利走势在分组过滤下口径自洽（页面内联动）
- 存量监控记录零迁移归入「未分组」

**Non-Goals:**

- 不改动归因、自动卖出结算逻辑（`settle_monitor`/`end_monitor` 不触碰分组字段，分组随记录生命周期保留）
- 不做跨表多对多（一条监控记录只属一个分组）
- 不做分组级统计报表/分组维度对比页
- 不改动 `CChan` 计算流水线与 DuckDB 数据

## Decisions

### D1: 独立分组表 + 可空 FK，删除置 NULL（非 CASCADE）

`monitor_group(id, name, sort_order, created_at)`；`monitor.group_id INT NULL REFERENCES monitor_group(id) ON DELETE SET NULL`。

- **为什么**：重命名只改 1 行；分组删除后监控记录仍独立有价值（区别于 watchlist——自选股 item 离开分组即无意义，故 watchlist 用 item 级 CASCADE）。`ON DELETE SET NULL` 让删除语义由 DB 约束直接保证，DAO 无需两步事务。
- **备选**：`monitor.group_name VARCHAR` 方案被否——重命名要 UPDATE 全组行，且无排序承载列。
- 建表走 `_ensure_tables()` 惰性模式（`CREATE TABLE IF NOT EXISTS` + `ALTER TABLE monitor ADD COLUMN IF NOT EXISTS group_id`），存量记录 `group_id` 即 NULL = 未分组，零迁移。

### D2: 路由与 DAO 对齐 watchlist 模式

`routers/monitor.py` 新增：`GET/POST /monitor/groups`、`PATCH/DELETE /monitor/groups/{id}`、`PUT /monitor/groups/reorder`；`monitor_store.py` 新增对应 DAO（PG 不可达时沿用 fallback 降级惯例）。命名用 `groups`（而非 `folders`）贴合监控域语义；实现结构照抄 `watchlist_store.py`（名称查重、`sort_order` 末尾追加、reorder 批量 UPDATE）。

### D3: 过滤参数语义

`GET /monitor?group_id=<id>`（监控中）与 `GET /monitor/completed?group_id=<id>` 服务端过滤：

- `group_id` 缺省 = 不过滤（「全部」）
- `group_id=ungrouped`（哨兵字符串）= `WHERE group_id IS NULL`
- 数值 id = `WHERE group_id = <id>`

选哨兵字符串而非 `group_id=0` 或 `-1`：与 PG SERIAL 主键空间无碰撞风险，且不依赖「0/负数永远不合法」的隐含约定。周期/盈亏过滤维持前端本地实现不变（本变更只把分组维度搬到服务端，不重做已有过滤）。

### D4: 前端分组树放监控中 tab 左侧栏，两个 tab 各自维护分组过滤状态

复用 `TreeList` 渲染分组节点（全部/未分组 + 各分组，按 `sort_order` 排序）；管理动作（新建/重命名/删除/拖拽）仅挂监控中 tab 的分组树（已完成 tab 的分组树只读、仅过滤）。跨 tab 切回时监控中分组选择保持（组件内状态不重置，与周期/盈亏过滤现状一致）。

- **为什么不在已完成 tab 也放管理**：管理入口唯一化，避免两处写操作的状态同步复杂度；已完成记录的分组归属在监控中侧即可调整（或后续按需补充）。
- **备选**：管理入口放 BspView 弹窗被否——弹窗已有时间/价格联动职责，只承载「选择 + 快速新建」。

### D5: BspView 弹窗分组交互

弹窗内分组为 `el-select`（选项 = `getMonitorGroups()` 拉取 +「未分组」默认项），下拉尾部「新增分组」入口弹行内输入（校验规则同 D2 名称查重），新建成功即选中。`CreateMonitorPayload` 增加可选 `group_id?: number`，未传时后端写 NULL。

- 参照：BspView 已有 watchlist `getFolders` 的同构用法（加入自选股弹窗），交互模式零学习成本。

### D6: 统计与走势联动实现口径

监控中 tab 现状：列表数据 `getMonitorList` 全量返回后前端计算统计与 `summarySeries`。分组过滤后**列表即已按组返回**，统计项与盈利走势沿用现有前端聚合路径（对已过滤列表聚合），天然联动，无需新端点。

- **为什么**：当前 `getMonitorList` 无分页（`MonitorItem[]` 全量），服务端过滤 + 前端聚合是现状最小改动路径；后续若列表分页化，统计需随迁服务端，届时分组参数已就位。

### D7: 拖拽排序对齐 watchlist reorder 模式

分组树节点 drag & drop → 收集新顺序 → `PUT /monitor/groups/reorder {ids}` → 后端按数组序批量 `UPDATE sort_order`。前端复用 WatchlistView 的拖拽实现（draggable 容器内排序、虚拟节点「全部/未分组」不参与拖拽）。

## Risks / Trade-offs

- [惰性建表并发] 两个请求同时触发 `ALTER TABLE` → `IF NOT EXISTS` 幂等，PG DDL 锁串行化，风险低；沿用现状不做额外处理
- [「未分组」哨兵字符串被误当 id 传给数值参数] → 路由层显式校验：`group_id` 只接受正整数或字面 `ungrouped`，非法值 422
- [monitor 表体量大后分组过滤无索引] → 单用户量级监控记录有限，暂不加索引；若后续需要，`CREATE INDEX ON monitor(group_id)` 前向兼容
- [BspView 弹窗内新建分组与左侧栏管理入口的名称查重] → 查重都在服务端单一 DAO 完成两处入口行为一致
- [已完成 tab 分组树只读但分组仍可被删除] → 删除分组后已完成列表「未分组」项自动吸纳，无悬空引用（FK SET NULL 保证）

## Migration Plan

1. 后端先行：`monitor_store.py` 建表 + DAO + 路由端点上线（对存量前端无影响，新端点未被调用）
2. 前端跟进：监控页左侧栏分组树 → 查询参数 → BspView 弹窗
3. 回滚：前端回退即恢复全局视图；`monitor_group` 表与 `group_id` 列保留无害（无 NOT NULL 约束），DAO 层可整体摘除

## Open Questions

（无——三个悬而未决的产品问题已在探索阶段确认：已完成 tab 出分组过滤、查询条件放后端、分组需排序；弹窗分组可选/拖拽排序/统计联动三个默认推荐亦已确认。）
