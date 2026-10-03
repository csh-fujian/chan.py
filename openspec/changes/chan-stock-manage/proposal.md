## Why

chan.py 已能计算缠论结构（分型/笔/线段/中枢/买卖点），K 线也已持久化到 DuckDB，但「选股 → 跟踪 → 复盘」这条链路上仍是断裂的：买卖点只现算、不落库，查询「某日全市场出现某买卖点的股票」得现算全市场（数小时）；没有自选分组、没有监控盈利跟踪、没有对亏损的归因复盘。需要一个股票管理 Web 页面，把「我的自选 / 历史买卖点 / 股票监控」串成闭环；买卖点索引与增量续算引擎已迁移至 `bsp-page-change`（由该变更落库并提供查询），本变更消费其结果让监控能按周期自动判定卖点。

## What Changes

<!-- 增量续算引擎需求已迁移至 bsp-page-change（方案 C 水位驱动幂等补算 + spike 硬门，2026-10-01）。 -->
- **Tab2 历史买卖点**：页面需求（周期列表、查询契约含日期条件、区间套数据入口）已迁移至 `bsp-page-change`（`bsp-page`/`bsp-index` 能力，由该变更统一维护；`system-page-change` 原占用的查询/多级别三条已按 2026-10-01 裁定撤回归入该变更）；本变更仅保留「查询结果多选 → 加入监控（含设置监控时间）」的监控侧对接与页面骨架。板块聚合按冲突裁定删除（暂缓，见 `bsp-page-change`）。
<!-- Tab1 我的自选：自选页面需求已迁移至 watchlist-page-change（watchlist/watchlist-page 能力，由该变更统一维护；本变更不再保留自选页面需求内容）。 -->
- **Tab3 股票监控**：`bsp-monitoring` 能力已于 2026-10-02 整体迁移至 `monitor-page-change`（含监控列表与盈利走势、监控完成与归因、卖点自动卖出与结算三需求）。
- **行业多对多**：股票可关联多个行业（不限额），页面展示最相关的前 3 个；行业数据落 PG。
- **分析增强**：条件选股器（可保存复用的选股策略）、预警提醒（价格/买卖点/监控卖点触发通知）；买卖点绩效统计的需求描述已迁移至 `system-page-change`（`bsp-performance` 能力），区间套（多级别买卖点查询）已迁移至 `bsp-page-change`（`bsp-index` 能力）。
- **多用户与权限**：多用户认证（登录/登出、JWT 会话），RBAC 权限控制（菜单权限 + 按钮权限），admin 角色拥有绝对权限；配套登录页。用户/角色管理与权限分配、`/system` 权限管理页的需求描述已迁移至 `system-page-change`（`system-management` 能力）。
- **存储分工**：原始 K 线继续落 DuckDB；缠论结论 / 买卖点索引 / 行业 / 自选 / 监控落 PG。
- **不修改** `CChan`/`CBiList`/`CSegListChan`/`CZSList`/`CBSPointList` 的计算逻辑；续算仅复用其 `trigger_step` 与 pickle 能力。

## Capabilities

### New Capabilities

<!-- bsp-index 能力已整体迁移至 bsp-page-change（引擎 + 查询 + 多级别，由该变更统一维护；板块聚合按冲突裁定删除，2026-10-01）。 -->
<!-- watchlist 能力已迁移至 watchlist-page-change（自选页面需求由该变更统一维护，2026-10-01）。 -->
- `stock-screener`: 条件选股能力。覆盖把周期/日期/买卖点类型/行业/指标阈值组合为可保存、可复用的选股策略并执行扫描。
- `alerts`: 预警提醒能力。覆盖价格触发、买卖点出现、监控卖点等事件的规则设置与触发通知。
- `auth`: 用户认证与 RBAC 权限能力。覆盖登录/登出、JWT 会话、菜单权限控制与管理权限控制（业务按钮全开放）、admin 绝对权限。（用户与角色管理已迁移至 `system-page-change` 的 `system-management` 能力，2026-10-01。）

### Modified Capabilities

- `stock-universe`: 行业从「可空单值」改为「多对多、不限额、展示前 3」，相应调整行业筛选与元数据模型。

## Impact

- **新增文件**：`WebAPI/`（在 stocks 路由基础上新增自选/监控路由）、`web/`（页面骨架）、PG schema 扩展（`stock_industry`/`watchlist_*`/`monitor*` 等表）、认证与权限（`auth_store.py` + `routers/{auth,system}.py` + `app_user`/`role`/`permission`/`role_permission` 表 + `/login`、`/system` 视图）。（`bsp` 路由、`chan_structure`/`bsp_index`/`chan_snapshot` 表与增量续算引擎——pickle 快照 + `trigger_load` 续算 + 日终买卖点索引——均归 `bsp-page-change`；`bsp-monitoring` spec 整体迁至 `monitor-page-change`；`bsp-performance` spec 整体迁至 `system-page-change`。）
- **修改文件**：`DataAPI/StockUniverse.py`（枚举逻辑 + 新增行业数据源接入）、`WebAPI/stock_store.py`（行业 M2M）、`Script/requirements.txt`（FastAPI/uvicorn，及 LLM SDK 待定）。
- **复用**：`persist-kl-to-duckdb` 的 DuckDB `kline`（原始 K 线源）；`chan-web-viewer` 的 FastAPI/uvicorn + Vue3+Vite+TS 栈；chan.py 的 `trigger_step`/`trigger_load`/`chan_dump_pickle`/`chan_load_pickle`（续算基底）。
- **依赖**：行业多标签数据源（东财/akshare）；LLM 供应商（待定，见 design Open Questions）；预警通知通道（先站内，webhook 后续）；认证依赖 JWT（python-jose）+ passlib[bcrypt]。
- **关联**：为 `chan-web-viewer` 的「搜索标的」backlog 提供行业/股票池基础；买卖点索引同时是后续策略/回测的选股数据源；区间套的多级别买卖点数据可被 `chan-web-viewer` 的 K 线图叠加消费。
