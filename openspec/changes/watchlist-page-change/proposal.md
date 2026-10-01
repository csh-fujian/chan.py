## Why

自选页（`/watchlist`）已能增删文件夹与股票，但存在四个缺陷：搜索框无搜索按钮且纯前端过滤（不请求后端）；新建的第一个文件夹因 `id !== 1` 硬编码守卫而丢失删除按钮；切换文件夹不触发右侧列表重新加载；页面被 KeepAlive 缓存后，其它页面（K 线 / 历史买卖点 / 选股器）新增的自选无法在返回时体现。同时页面缺少两项基础能力：文件夹重命名入口（API 已就绪仅差 UI）、文件夹与文件夹内股票的拖拽排序（schema、接口、前端均不具备）。

## What Changes

- **搜索按钮 + 服务端查询**：搜索框旁增加搜索按钮（回车同效），查询经后端接口过滤（按编码/名称匹配），不再仅靠前端 computed 过滤。
- **修复删除按钮守卫**：移除前端 `f.id !== 1` 硬编码——仅「全部」虚拟节点不提供删除，用户创建的文件夹一律可删。
- **切换文件夹即刷新**：选中文件夹（含「全部」）立即请求后端拉取右侧股票列表。
- **文件夹重命名**：文件夹行增加编辑按钮，复用既有 `PATCH /watchlist/folders/{id}`（API/后端已就绪）。
- **拖拽排序（持久化）**：文件夹树支持长按拖拽排序，文件夹内股票支持行拖拽排序；两张表新增 `sort_order` 列，新增 reorder 接口保存顺序。
- **缓存刷新策略**：保留 KeepAlive 缓存，页面 `onActivated` 时重新拉取文件夹与股票列表，保证跨页新增自选可见；不引入跨页事件通知机制。
- **需求迁移（自 chan-stock-manage）**：该变更的 `watchlist` 底层能力需求（文件夹分类、字段展示、批量加入自选）整体迁入本变更统一维护；其中「批量加入默认以日期作文件夹名、可改」条款与实际实现冲突且未实现，按裁定删除（见 design.md D7），批量加入按实际实现改写为「选择目标文件夹」。

## Capabilities

### New Capabilities

- `watchlist-page`: 自选页面级交互——搜索（服务端查询）、文件夹切换即时刷新、文件夹删除/重命名、文件夹与股票拖拽排序持久化、页面缓存下的激活刷新。
- `watchlist`: 我的自选列表底层能力（自 chan-stock-manage 迁入）——文件夹分类与切换、股票字段（名称/编码/股价/行业≤3）展示、查询结果多选批量加入自选。

### Modified Capabilities

<!-- 无：本变更新增 watchlist-page 能力，并整体承接 chan-stock-manage 草拟的 watchlist 底层能力需求（其需求内容已从该变更删除）。 -->

## Impact

- **前端**：`Front/src/views/watchlist/WatchlistView.vue`（搜索按钮、删除守卫修复、切换刷新、重命名 UI、拖拽、onActivated）；`Front/src/api/modules/watchlist.ts`（`q` 参数、reorder 接口）；`Front/package.json`（新增 `vuedraggable`/`sortablejs`）；`Front/src/mock/handlers/watchlist.ts` + `Front/src/mock/data/watchlist.ts`（搜索与排序 mock 同步）。
- **后端**：`WebAPI/routers/watchlist.py`（`q` 查询参数、两个 reorder 端点）；`WebAPI/watchlist_store.py`（`sort_order` 列迁移、按序查询、reorder DAO）；`WebAPI/init.sql`（两表补 `sort_order` 列）。
- **数据库**：`watchlist_folder`、`watchlist_item` 各增 `sort_order` 列（存量数据按 `id`/`added_at` 回填初值）。
- **不修改**：`CChan` 计算流水线；`kline-watchlist`（K 线页自选集成）。`watchlist` 底层能力需求已自 `chan-stock-manage` 迁入本变更（见 Capabilities），其已实现行为不变。
