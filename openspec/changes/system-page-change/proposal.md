## Why

`/system` 权限管理页的后端全是裸 stub（`WebAPI/routers/system.py` 的 users/roles/permissions 接口返回假数据，且未挂任何鉴权），前端用户/角色表格没有任何查询条件，角色-用户绑定与"角色下用户列表"完全不存在；权限配置页保存不落库，运行时权限读取仍走按用户存权限的旧模型（`chan_user_permission`），角色配了也不生效。同时，chan-stock-manage 中系统页与买卖点页的需求描述散落在 `auth`/`bsp-*` spec 与 design 表格里，部分口径已与实现脱节（盈利点数 vs 百分比、任务状态过期），需要抽出后系统化、细化并统一维护。

## What Changes

- **系统页三模块真实现（数据模型走 B 套 RBAC：`app_user`/`role`/`permission`/`role_permission`）**：
  - 用户管理：新增带用户名/角色/状态/创建时间四条件的查询接口，前端补查询条；增删改/重置密码/启停全部挂 `require_manage`，admin 用户受保护。
  - 角色管理：新增角色名查询接口、"角色下用户列表"接口、角色-用户批量绑定接口，角色页补查询条与用户抽屉。
  - 权限配置：`GET /permissions` 与 `PUT /roles/{id}`（落 `role_permission`）从 stub 变为真实现，admin 角色只读，种子补 `menu:kline`。
- **权限读取路径切换到 B 套**：`auth.py` 登录/`me`/`require_manage` 改读 `app_user` + `role_permission`，使权限配置保存即生效；写明切换前 `/system` 新建用户无法登录的过渡缺口。
- **买卖点页面需求迁入本 change（自 chan-stock-manage）**：`bsp-monitoring` 迁入"监控列表与盈利走势""监控完成与归因"两条（"卖点自动卖出与结算"未实现，按既定方案留 chan-stock-manage）；`bsp-performance` 两条件整体迁入。`bsp-index` 能力（查询/多级别/引擎）按 2026-10-01 裁定整体归 `bsp-page-change`，本 change 不再承接。
- **按实现修正口径**：总体盈利由"点数"改为"百分比"；过期任务状态在迁移中如实反映。
- **补完页面闭环的未实现需求**：U5 大模型归因从占位 stub 接真 `llm_client`。（原 U6 `GET /bsp` 日期条件已随 `bsp-index` 裁定迁移至 `bsp-page-change`。）
- **不迁不改**：登录认证、菜单权限控制、管理权限控制、admin 绝对权限等运行时需求留在 chan-stock-manage 的 `auth` capability（本 change 只承接其"用户与角色管理"的细化版）。

## Capabilities

### New Capabilities

- `system-management`: `/system` 权限管理页能力——用户管理（用户名/角色/状态/创建时间四条件查询、增删改、重置密码、启停、admin 保护）、角色管理（角色名查询、角色下用户列表、角色-用户绑定、增删改、admin 保护）、权限配置（权限清单查询、角色权限持久化、菜单权限与管理权限勾选、admin 角色不可改）。
- `bsp-monitoring`: 股票监控页面能力（自 chan-stock-manage 迁入并按实现修正口径）——监控列表与盈利走势、总体盈利（百分比）、监控完成与大模型亏损归因（含 U5 接真实现）；"卖点自动卖出与结算"仍由 chan-stock-manage 的同名 capability 承载。
- `bsp-performance`: 买卖点绩效统计能力（自 chan-stock-manage 迁入）——按类型与周期的胜率/盈亏比统计、样本明细。
<!-- bsp-index 能力（历史买卖点查询/板块聚合/多级别）已按 2026-10-01 裁定整体归 bsp-page-change，本 change 不贡献该能力；板块聚合按冲突裁定删除。 -->

### Modified Capabilities

<!-- 无：openspec/specs/ 下尚无本 change 涉及的能力（bsp-*/auth/watchlist 均未归档）；
     对 chan-stock-manage 的裁剪属于编辑另一未归档 change 的 delta，不构成对已归档 spec 的修改。 -->

## Impact

- **后端**：`WebAPI/routers/system.py`（stub → 真实现 + `require_manage`）、`WebAPI/auth.py`（权限读取切 B 套）、`WebAPI/routers/monitor.py`（`analyze` 接 `llm_client` 替换占位 stub）。
- **数据库**：`WebAPI/init.sql` — `role` 表补 `description` 列；`permission` 种子补 `menu:kline`；（`last_login` 前端列按实现口径移除，不加表字段）。
- **前端**：`Front/src/views/system/SystemView.vue`（用户/角色查询条、角色用户抽屉与绑定）、`Front/src/views/monitor/CompletedView.vue`（归因真数据）、`Front/src/api/modules/{system,monitor}.ts`、对应 MSW mock 同步。
- **openspec 工件**：`chan-stock-manage` 相应裁剪（`bsp-monitoring` 仅留"卖点自动卖出与结算"、`bsp-performance` 整体迁出、`auth` 删"用户与角色管理"、proposal/design D16/tasks 同步；`specs/bsp-index/` 整体删除——该能力已归 `bsp-page-change`）；自选底层需求按既定方案迁 `watchlist-page-change`（该 change 自行承接，不在本 change 范围内）。
- **不修改**：`CChan` 计算流水线；增量续算引擎与买卖点索引（归 `bsp-page-change`）。
