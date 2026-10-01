## 1. 共享枚举与行业数据源

- [ ] 1.1 抽 `DataAPI/StockUniverse.py`，迁入 `is_a_share_stock`/`query_all_a_share`/`latest_trading_day`，`Debug/gen_stock_list.py` 改为调用共享模块；验证：`PYTHONPATH=. python Debug/gen_stock_list.py --limit 20` 输出与重构前等价（A 股过滤、交易所分布一致）。
- [ ] 1.2 接入多行业数据源（东财/akshare），返回每只股票的行业与概念标签及顺序；验证：对样本股票能返回 ≥1 个行业标签，且标签顺序可作 rank 依据。
- [ ] 1.3 新增共享的灌数配置拼装函数（`to_ingest_config`）；验证：生成 JSON 与 `Debug/ingest_config.example.json` 同构、可被 `IngestUtil.load_config` 读取。

## 2. 存储层（PG schema + DAO）

- [x] 2.1 实现 `WebAPI/stock_store.py`：`stock` 表 DDL（去单值 industry）+ 幂等 upsert/`list`/`get`/`delete` + `stock_industry` 表（多对多，`rank`/`is_primary`）；验证：建表成功，同 `code` 二次 upsert 不重复，行业多对多读写、按 `rank` 取前 3。
- [x] 2.2 实现 `WebAPI/bsp_store.py`：`chan_structure`(JSONB)/`bsp_index`/`chan_snapshot`(BYTEA) 三表 DDL + DAO；验证：结构 JSONB 往返无损，`bsp_index` 幂等写入去重，快照 BYTEA 存取成功。
- [x] 2.3 实现 `WebAPI/watchlist_store.py` + `WebAPI/monitor_store.py`：`watchlist_folder`/`watchlist_item`、`monitor` 表 DDL + DAO；验证：文件夹增删、monitor 状态流转 `monitoring → completed` 正确。

## 3. 增量续算引擎

（需求与任务已整体迁移至 `bsp-page-change`（`bsp-index` 能力 + 其 tasks 第 3 组「补算引擎（方案 C）」，2026-10-01；原 3.1 spike 已完成并作为其硬门证据）。）

## 4. 买卖点索引查询与聚合

> 需求已迁移至 `bsp-page-change`（`bsp-index` 能力，2026-10-01，含日期条件与分页细化；`system-page-change` 原占用的查询三条已裁定撤回归入该变更）；以下为已完成的历史实现记录。

- [x] 4.1 实现 `GET /api/bsp`：按 `kl_type`/`date`/`bsp_type`/`is_buy` 查询命中股票；验证：条件过滤返回正确股票集合。
- （4.2 `GET /api/bsp/aggregate` 板块聚合：需求按冲突裁定删除（暂缓），端点保留现状不验收——见 `bsp-page-change` design D6。）

## 5. 后端 stocks 路由（沿用）

- [x] 5.1 建 `WebAPI/app.py` + `config.py` 骨架并挂载各 router；验证：`uvicorn` 启动后 `GET /docs` 可达。
- [x] 5.2 实现 `routers/stocks.py` CRUD（列表/详情/upsert/编辑/删除 + `q`/`exchange`/`industry`/`enabled` 筛选分页）；验证：增删改查与筛选分页正确，行业筛选走多对多匹配。
- [x] 5.3 实现 `POST /api/stocks/import`：全市场枚举 + 行业填充 + 去重 upsert；验证：返回 `{imported, skipped}`，已存在 code 不被覆盖，指数/B 股/基金被排除。
- [x] 5.4 实现 `GET /api/stocks/status`：read-only DuckDB `max(time_key)` + `RecomputeCursor` 水位 + 日历/停更阈值；验证：返回 `last_time_key`/`gap`/`stale`。
- [x] 5.5 实现 `GET /api/stocks/export-config`：启用标的展开为 `stocks` 数组套灌数骨架；验证：输出可被 `download_kl.py --config` 消费。

## 7. 监控、卖点检测与 LLM 归因

> 需求拆分（2026-10-01）：监控列表/盈利展示与 LLM 归因的需求已迁移至 `system-page-change`（`bsp-monitoring` 能力，归因接真为其任务 6.x）；本节保留卖点自动卖出（U4）与已完成的加入监控实现。

- [x] 7.1 实现 `routers/monitor.py` 加入监控：记录周期、监控时间、买入价（买点 `klu.low`）；监控列表返回基本信息 + 盈利走势 + 总体盈利（百分比）；验证：加入监控后列表与盈利计算正确。
- [ ] 7.2 卖点检测：续算时检查监控周期是否出现卖点（`is_buy=False`），任一卖点即自动卖出（卖出价 `klu.high`）→ 结算 `pnl_pct` → `status=completed`；验证：出现卖点的监控股票被自动结算并转完成页。**依赖 `bsp-page-change`：卖点检测挂在其补算入口（其 tasks 3.6/3.7）的续算回调上，需其先行落地。**

## 8. 前端三 Tab + 监控完成页

- [x] 8.1 建 `web/` 骨架 + 路由 `/watchlist`、`/bsp`、`/monitor`、`/monitor/completed` + Element Plus + ECharts；验证：`npm run dev` 后各路由可访问。
- （8.2 自选页页面需求已随 Tab1 迁移至 `watchlist-page-change`，2026-10-01；8.3 历史买卖点页迁移至 `bsp-page-change` tasks 第 4 组；8.4 监控页+完成页迁移至 `system-page-change` tasks 第 9 组。）

## 9. 初始化与端到端

- [ ] 9.1 提供从 `Debug/ingest_config.all_stocks.json` 灌入初始股票池 + 行业填充的脚本；验证：股票池与 `stock_industry` 有数据。
- [ ] 9.2 端到端冒烟：灌数 → 建买卖点索引 → 查买卖点 → 加自选 → 监控 → 卖点结算；验证：全链路无报错、数据在各表正确落地。（LLM 归因步骤随需求迁移至 `system-page-change` 任务 8 端到端覆盖。**依赖 `bsp-page-change`：「建买卖点索引」由其补算引擎产出（其 tasks 3.x），需其先行落地。**）

## 10. 买卖点绩效统计

（需求与任务已迁移至 `system-page-change`（`bsp-performance` 能力 + 其 tasks 第 9 组），2026-10-01。）

## 11. 条件选股器

- [x] 11.1 实现 `screener` 表 + 策略 CRUD（条件 JSONB）；验证：策略保存、复用、编辑、删除正确。
- [ ] 11.2 实现 `POST /api/screeners/{id}/run`：翻译条件执行扫描（bsp_index + stock + stock_industry + DuckDB 指标）；验证：返回满足全部条件的股票。**依赖 `bsp-page-change`：扫描读取其维护的 `bsp_index`（含词表约定 `D`/`W`/`M`/`60m`/`30m`）。**

## 12. 区间套（多级别买卖点）

> 需求已迁移至 `bsp-page-change`（`bsp-index` 能力，2026-10-01；`system-page-change` 原占用已裁定撤回归入该变更）；以下为已完成的历史实现记录。

- [x] 12.1 实现 `GET /api/bsp/{code}?kl_types=...`：返回该股票多周期买卖点；验证：多级别买卖点返回正确。
- [x] 12.2 前端多级别买卖点视图：`Front/src/views/bsp/NestingDrawer.vue`（挂 `BspView`）已落地，按周期子 tab 展示多级别买卖点；验证：多级别买卖点可见。（叠加形态的后续增强见 `bsp-page-change` tasks 4.2。）

## 13. 预警提醒

- [x] 13.1 实现 `alert` 表 + 规则 CRUD（`price`/`bsp`/`monitor_sell`）；验证：规则保存并生效。
- [ ] 13.2 在日终流水线挂触发检查 + 站内通知；验证：满足条件的规则生成通知。**依赖 `bsp-page-change`：日终流水线即其补算入口（其 tasks 3.7），预警检查挂在其后。**

## 14. 用户认证与 RBAC 权限

- [x] 14.1 建 `app_user`/`role`/`permission`/`role_permission` 表 + 种子权限（`menu:*` 7 项 + 单一 `manage`）+ 内置 admin 角色；验证：建表成功、admin 存在且 `is_admin=true`。（`menu:kline` 第 8 项菜单权限由 `system-page-change` 任务 1.1 补种子。）
- [ ] 14.2 实现 `auth_store.py` + JWT 登录（`POST /api/auth/login`、`GET /api/auth/me`、`POST /api/auth/logout`，passlib[bcrypt]）；验证：登录返回 token、错误密码 401、`/me` 返回权限 code 列表。**数据模型按 B 套（`app_user`/`role`/`permission`/`role_permission`）；权限读取路径切换（按 username 解析、经角色 join 权限）由 `system-page-change` design D3 承接，见其 tasks 3.x。**
- [ ] 14.3 实现依赖注入 `get_current_user` + `require_perm(code)`（admin 放行、无权限 403）并挂到业务路由；验证：无权限接口返回 403。**`require_manage`/读守卫的数据源切换与新增由 `system-page-change` tasks 3.x 承接；本条保留登录态校验与业务路由挂载。**
- [x] 14.4 前端 `/login` + `pinia` auth store + 路由守卫 + `v-permission` 指令 + 动态菜单；验证：未登录跳登录、无权限菜单/按钮隐藏、直接访问无权限路由进 403。
- [x] 14.5 实现 `/system` 权限管理页（用户管理、角色管理、角色-权限配置）；验证：用户/角色 CRUD 与权限分配生效。（`/system` 页面需求已迁移至 `system-page-change` 的 `system-management` 能力，查询条件/角色绑定等增强由其承接；本条为已落地记录。）
