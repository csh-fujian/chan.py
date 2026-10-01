## Context

`/system` 页前端（`SystemView.vue` + 对话框）已完整落地并由 MSW mock 驱动，但后端 `WebAPI/routers/system.py` 中 users/roles/permissions 全是 stub（返回空数组/假成功，未挂任何鉴权，存在越权隐患）。权限数据存在两套并行模型：运行中的 `chan_user` + `chan_user_permission`（按用户存权限，`auth.py` 登录/`me`/`require_manage` 读这套），与已建表种子但无人使用的 D16 RBAC `app_user`/`role`/`permission`/`role_permission`（按角色存权限）。需求侧：系统页与买卖点页需求散落在 chan-stock-manage 的 `auth`/`bsp-*` delta 与 design D16 表格中，部分口径与实现脱节。动机详见 proposal.md - Why。

## Goals / Non-Goals

**Goals:**
- `/system` 三模块（用户/角色/权限配置）从 stub 变为挂鉴权的真实现，落在 B 套 RBAC 表上。
- 权限配置"保存即生效"：运行时权限读取从 A 套切到 B 套。
- 买卖点页面需求按审计结论迁入本 change（监控/绩效部分），并补完 U5（归因接真 LLM）页面闭环。
- chan-stock-manage 与实现脱节的需求按迁移映射表裁剪。

**Non-Goals:**
- `bsp-index` 能力（查询/多级别/引擎，含 U6 日期条件）——2026-10-01 裁定整体归 `bsp-page-change`；卖点自动卖出（U4）——留 chan-stock-manage。
- 登录/JWT 签发机制本身（chan-stock-manage 任务 14.2 的机制部分）；本 change 只改其数据源与权限读取。
- 菜单权限控制、管理权限控制的前端守卫逻辑（`v-permission`/路由守卫已存在，属 chan-stock-manage `auth` 运行时需求）。
- 分页用户/角色列表（数据量为管理页级别，全量返回 + 前端条件过滤，量级增长后再引入分页）。

## Decisions

### D1. 数据模型：B 套 RBAC（`app_user`/`role`/`permission`/`role_permission`）

- 用户单角色（`app_user.role_id` FK），角色多权限（`role_permission` 多对多），与 design D16 既有设计一致；种子数据（admin/trader/viewer 三角色三用户 + 权限）已存在。
- 备选 A 套（`chan_user_permission` 按用户存权限）被否：权限配置页给角色勾选的权限在运行时读不到，页面形同虚设；且"角色的用户列表/绑定"与按用户存权限语义冲突。
- `chan_user`/`chan_user_permission` 表保留不删，作为回滚路径（见 Migration Plan）。

### D2. 系统页 API 契约

前缀 `/api/system`。**读接口**要求登录且具备 `menu:system` 权限；**写接口**全部挂 `require_manage`（校验 `manage` 权限位）。权限码判定在 D3 切换后读自 B 套。

| 方法 | 路径 | 参数 / 请求体 | 说明 |
|---|---|---|---|
| GET | `/users` | `username`（模糊）、`role`（角色 code 精确）、`status`（active/disabled）、`created_from`、`created_to`（日期，含端点） | 四条件 AND 组合，均可选；返回 `{id, username, nickname, role, role_name, status, created_at}[]`，不分页 |
| POST | `/users` | `{username, nickname, password, role}` | 用户名重复 → 409 |
| PUT | `/users/{id}` | `{nickname?, role?, status?}` | 改 `role` 即换角色（单角色） |
| DELETE | `/users/{id}` | — | admin 用户 → 403 |
| POST | `/users/{id}/reset-password` | `{password}`（管理员输入的新密码，非空校验） | 原密码失效；不由服务端生成随机密码，避免明文回传 |
| GET | `/roles` | `name`（模糊） | 返回 `{id, name, code, description, user_count, perms[], is_admin}[]`，`perms` 为该角色权限码集合 |
| GET | `/roles/{id}/users` | — | 角色下用户列表，字段同 GET `/users` |
| PUT | `/roles/{id}/users` | `{user_ids: []}` | **批量绑定**：覆盖式——这些用户的角色全部改为本角色（原角色自动解除）；`user_ids` 中的用户被移出原角色 |
| POST | `/roles` | `{name, code, description}` | code 重复 → 409 |
| PUT | `/roles/{id}` | `{name?, description?, perms?}` | `perms` 存在时全量替换角色权限；admin 角色携带 `perms` → 403（name/description 编辑允许，spec 对 admin 角色仅限定删除与权限两处保护） |
| DELETE | `/roles/{id}` | — | admin 角色 → 403；角色下仍有用户 → 409（提示先转移） |
| GET | `/permissions` | — | 返回 `{id, code, name, category}[]`；`type`（menu/button）在 API 层映射为前端分类：menu→`菜单`、`manage`→`管理` |
| GET | `/llm*` 等 | — | 不在本 change 范围，保持现状 |

- `role_name` 通过角色表 join 得出；`user_count` 按绑定用户数聚合。
- admin 判定：用户所属角色 `is_admin=true`（或 code=`admin`），前端禁用按钮与后端 403 双侧执行。

### D3. 权限读取路径切换（权限配置生效闭环）

- `auth.py` 的 `_authenticate` / `get_current_user`：从 `app_user` 查用户（**按 username 解析**，见 Risks），密码校验用 bcrypt 对比 `app_user.password_hash`；权限码改为 `role → role_permission → permission.code` join；`is_admin=true` 的角色直接视为拥有全部权限（与种子全量授权互为兜底）。
- `require_manage` 语义不变（无 `manage` → 403），仅数据源切换；新增读接口守卫 `require_menu_system`（无 `menu:system` → 403）。
- 过渡缺口（已知、接受）：切换落地前，经 `/system` 在 `app_user` 新建的用户无法登录（登录还读 `chan_user`）；切换落地后，遗留在 `chan_user` 而 `app_user` 没有的用户无法登录。种子两表用户一致（admin/trader/viewer），开发阶段可接受；切换与系统页写接口在同一批任务内完成，缺口窗口最小化。

### D4. 需求迁移映射表（迁 / 删 / 留）

| 出处 | 需求 | 处置 |
|---|---|---|
| `auth` | 用户与角色管理 | **迁**：细化为 `system-management` 多条需求；chan-stock-manage 的 delta 删除该条 |
| `auth` | 用户认证 / 菜单权限控制 / 管理权限控制 / admin 绝对权限 | **留**（运行时行为）；本 change 不重复，仅在 `system-management` 承接其页面侧（admin 保护、管理接口校验） |
| `bsp-index` | 全部六条（持久化/增量续算/日终索引/历史查询/板块聚合/多级别） | **归 `bsp-page-change`**（2026-10-01 裁定整体迁出；板块聚合按冲突裁定删除，U6 日期条件随迁） |
| `bsp-monitoring` | 监控列表与盈利走势 | **迁**，口径修正：总体盈利点数 → 百分比（与实现一致，旧口径删除） |
| `bsp-monitoring` | 监控完成与归因 | **迁**，强化 U5：归因须真实生成、失败显式报错、盈利<5% 限定（覆盖原占位实现） |
| `bsp-monitoring` | 卖点自动卖出与结算（U4，未实现） | **留** chan-stock-manage |
| `bsp-performance` | 两条件 | **迁**（均已实现） |
| proposal Tab3 页面描述、tasks 8.4/10.x | 监控页/绩效页任务（已完成） | **迁** 至本 change tasks（标记已落地的验证项）；tasks 7.2、3.x、2.x 留 |
| proposal Tab2 页面描述、tasks 8.3/12.x | `/bsp` 页面任务（历史买卖点页/区间套） | **归 `bsp-page-change`**（2026-10-01 裁定） |
| design D16 `/system` 页面表格 | 系统页字段/模块描述 | **迁**：以本 change 的 `system-management` spec + 本 design D2 为准；D16 处加指向注记 |
| `watchlist` | 底层 3 条（文件夹分类/字段展示/批量加入） | **不属本 change**：按既定方案迁 `watchlist-page-change`，由其承接 |

### D5. U5 归因接真（U6 日期条件已迁 `bsp-page-change`）

- **U5**：`POST /monitor/{id}/analyze` 替换占位逻辑——读取已激活 LLM 供应商配置（`llm_store.resolve_llm_config`），组装归因 prompt 调 `llm_client.complete`，结果经 `save_attribution` 持久化；未配置 → 400「LLM 未配置」；供应商调用失败 → 502/错误透传，**不写占位记录**。后端校验标的最终盈利 < 5% 才执行（否则 400），与前端过滤双侧一致。归因 prompt 独立定义（复用 `llm_prompts.py` 机制，新增归因模板）。
- **U6**（原）：`GET /api/bsp` 日期参数与 `BspView` 日期控件已随 `bsp-index` 裁定迁移至 `bsp-page-change`（其 design D5/D7 与 tasks 第 1/2 组），本 change 不实现。

### D6. Schema 与种子修正（随本 change 落地）

- `role` 表补 `description VARCHAR NOT NULL DEFAULT ''`（前端 RoleDialog 契约，当前列缺失）。
- `permission` 种子补 `menu:kline`（mock 有、DB 缺）；并为既有角色补授权对齐 mock：admin 全量 9 项、trader 业务 menu 全部 7 项（含新 `menu:kline`，**不含** `menu:system`——`/system` 读仅 admin 可达，mock trader 描述亦为「无系统管理权限」）、viewer 校正为 `['menu:kline','menu:watchlist']`；幂等 `ON CONFLICT DO NOTHING`，并幂等清除存量库旧种子残留（trader 的 `menu:system`、viewer 的 `menu:bsp`，见 Migration Plan 步骤 1「viewer 授权校正」）。
- `last_login`：前端用户表"最后登录"列**删除**（无任何数据源支撑，按"实现口径优先"处理），不新增表字段。
- `chan_user` 的明文密码与登录路径随 D3 退出运行时，不迁移历史口令（种子 bcrypt 哈希已存在）。

### D7. Mock 与前端同步

- `Front/src/mock/data|handlers/system.ts`：`getUsers` 支持四条件过滤、`getRoles` 支持 `name` 过滤、新增 `GET /roles/{id}/users` 与 `PUT /roles/{id}/users` handler、`Permission.category` 与后端映射一致；`bsp`/`monitor` mock 同步 D5 行为。
- `SystemView.vue`：用户表上方加查询条（用户名输入、角色下拉、状态下拉、创建时间日期区间、查询/重置）；角色表加角色名查询；角色行加"用户"操作开抽屉（成员列表 + 待绑定用户多选 + 绑定提交）；移除"最后登录"列；重置密码改为输入新密码的对话框。
- `api/modules/system.ts`：`getUsers/getRoles` 增加查询参数；新增 `getRoleUsers/bindRoleUsers`。

## Risks / Trade-offs

- [切换瞬间的会话兼容：token 载荷中的 `user_id` 是 `chan_user` 的 id，切到 `app_user` 后按 id 查会错位] → `get_current_user` 改为**按 token 中的 username 解析** `app_user`；username 在两套种子里一致（admin/trader/viewer），切换后旧会话仍可用；`app_user` 中不存在的 username（遗留 chan_user 用户）按未登录处理，强制其经 `/system` 重建。
- [双表过渡期数据分裂：`/system` 写 `app_user`，切换前登录读 `chan_user`] → D3 已知缺口，切换任务与系统页写接口同批完成；`chan_user` 不删作回滚。
- [角色删除的 FK 行为：`app_user.role_id REFERENCES role(id)` 无级联] → 业务层先查 `user_count` 返回 409，不依赖数据库报错。
- [归因接真引入外部 LLM 依赖（成本/稳定性）] → 仅手动触发、失败显式报错不落库、结果为参考信息不进交易决策（沿用 chan-stock-manage 既有风险结论）。
- [用户查询无分页] → 管理页数据量小（三用户种子 + 增长缓慢）；接口契约为数组，若量级增长需引入分页属破坏性变更，届时走新 delta。
- [两个 change 向同一 capability（`bsp-monitoring`）贡献 delta] → 本 change 与 chan-stock-manage 的 requirement 名称集合互斥（映射表 D4 已切分）；Purpose 文本两边保持一致，任一先归档不产生 Purpose 冲突。`bsp-index` 已整体归 `bsp-page-change`，本 change 不再与其重叠。

## Migration Plan

1. `init.sql` 增量（幂等）：`role.description` 加列、`menu:kline` 权限与三角色授权补种子、viewer 授权校正。
2. 后端：`routers/system.py` 按 D2 逐组替换 stub（users → roles → permissions），全部挂守卫。
3. `auth.py` 按 D3 切数据源（与步骤 2 同批合并落地，缩小缺口窗口）。
4. 前端：查询条、角色用户抽屉、last_login 移除、重置密码对话框；归因真数据展示；mock 同步。
5. openspec 裁剪：chan-stock-manage 按 D4 映射表同步（proposal/design D16/tasks/specs）；watchlist 底层需求迁 `watchlist-page-change`。
6. 回滚：`auth.py` 读取路径单点 revert 即回 `chan_user`（A 套）；`app_user` 侧新增数据保留无害。

## Open Questions

无（用户列表分页策略已在 Non-Goals 定为"量级增长后再立 delta"；密码重置契约已在 D2 定为管理员输入新密码）。
