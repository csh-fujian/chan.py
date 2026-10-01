## 1. 数据层（schema 与种子，design D6）

- [x] 1.1 `WebAPI/init.sql` 增量（幂等）：`role` 表补 `description` 列；`permission` 补 `menu:kline` 种子；三角色授权对齐 mock（admin 全量 9 项、trader 业务 menu 全部 7 项含 `menu:kline` **不含** `menu:system`、viewer 校正为 `menu:kline`+`menu:watchlist`；幂等清除存量库旧种子残留的 trader `menu:system` 与 viewer `menu:bsp` 授权）——验证：对存量库重跑 init.sql 无报错，查询确认列存在、9 项权限与三角色授权与 mock 一致。

## 2. 后端系统页 API（`routers/system.py` 按 design D2 替换 stub）

- [x] 2.1 用户条件查询 `GET /api/system/users`（username/role/status/created_from/created_to 四条件 AND，返回含 role_name/created_at，读守卫 `menu:system`）——验证：带 token 分别以全量、单条件、组合条件请求，结果集符合；无 `menu:system` 权限请求返回 403。
- [x] 2.2 用户管理操作：创建（用户名重复 409）、编辑、删除、重置密码（请求体新密码）、启停；写接口挂 `require_manage`；admin 用户删除/停用/改出 admin 角色均 403——验证：curl 逐场景返回码符合，admin 用户状态未被变更。
- [x] 2.3 角色查询 `GET /api/system/roles?name=`（模糊，返回 description/user_count/perms/is_admin）与角色下用户列表 `GET /api/system/roles/{id}/users`——验证：关键字命中/不命中、成员列表与绑定关系一致。
- [x] 2.4 角色-用户批量绑定 `PUT /api/system/roles/{id}/users`（覆盖式单角色语义）——验证：绑定后用户仅属于目标角色，原角色成员数相应减少。
- [x] 2.5 角色管理操作：创建（code 重复 409）、编辑、删除（admin 403、仍有用户 409）；`PUT /roles/{id}` 携带 `perms` 全量替换角色权限（admin 角色 403）——验证：curl 各场景返回码正确，保存后 `role_permission` 等于提交集合。
- [x] 2.6 权限清单 `GET /api/system/permissions`（type→category 映射，menu→菜单、manage→管理，含 `menu:kline` 共 9 项）——验证：返回项与种子一致，`menu:kline` 存在。

## 3. 权限读取切换到 B 套（`auth.py`，design D3）

- [x] 3.1 `_authenticate`/`get_current_user` 切 `app_user`：按 username 解析、bcrypt 校验 `password_hash`、权限经 `role → role_permission → permission` join、`is_admin` 直接全放行——验证：admin/trader/viewer 登录返回各自权限码（trader 含 `menu:kline`、admin 含 `manage`），错误密码 401，`chan_user` 中存在而 `app_user` 中不存在的用户登录被拒。
- [x] 3.2 `require_manage` 数据源切换 + 新增读守卫 `require_menu_system`——验证：viewer 调任一写接口 403；无 `menu:system` 的 trader 调用户/角色读接口 403，admin 全部通过。

## 4. 前端系统页（`SystemView.vue` + api + mock，design D7）

- [x] 4.1 用户查询条（用户名输入、角色下拉、状态下拉、创建时间日期区间、查询/重置）+ `getUsers` 查询参数 + MSW handler 四条件过滤——验证：`npm run dev` 下各条件与组合过滤生效，重置恢复全量。
- [x] 4.2 角色名查询条 + `getRoles({name})` + mock 过滤——验证：关键字过滤生效。
- [x] 4.3 角色行「用户」入口开抽屉：成员列表 + 待绑定用户多选 + 批量绑定（`getRoleUsers`/`bindRoleUsers` + mock handler）——验证：绑定后成员列表与角色 `user_count` 即时更新，被绑定用户出现在新角色下。
- [x] 4.4 移除用户表「最后登录」列；重置密码改为输入新密码对话框（对接 D2 `{password}` 契约）——验证：页面无 last_login 列，重置后原密码失效、新密码可登录。
- [x] 4.5 错误契约对接：用户名/code 重复、角色含用户、admin 保护的 409/403 在 UI 上给出明确提示（不再静默）——验证：触发各错误场景均有 toast/消息提示。

## 5. U6 日期条件（已迁出）

（U6 `GET /api/bsp` 日期条件已随 `bsp-index` 裁定迁移至 `bsp-page-change` tasks 第 2 组/第 1 组，2026-10-01；本变更无此任务。）

## 6. U5 大模型归因接真

- [x] 6.1 `llm_prompts.py` 新增归因 prompt；`POST /monitor/{id}/analyze` 接 `resolve_llm_config` + `llm_client.complete`：盈利 ≥5% → 400、LLM 未配置 → 400、调用失败 → 错误透传且不落库，成功才 `save_attribution`——验证：三种失败场景返回对应错误且无占位记录；配置 LLM 后返回真实归因并持久化。
- [x] 6.2 `CompletedView` 归因动作对接真实返回与错误提示，mock `analyze` 同步（未配置/失败不再返回占位成功）——验证：页面触发分析展示真实结果，失败展示明确错误。

## 7. openspec 工件同步裁剪（design D4 映射表）

- [x] 7.1 chan-stock-manage specs 裁剪：删 `specs/bsp-performance/`；`specs/bsp-monitoring/` 仅留「卖点自动卖出与结算」；`specs/bsp-index/` 整体删除（2026-10-01 裁定：能力已整体归 `bsp-page-change`，由该变更的迁移任务负责执行）；`specs/auth/` 删「用户与角色管理」——验证：`openspec validate --change chan-stock-manage` 通过，剩余 requirement 名集合与 D4 映射表一致。
- [x] 7.2 chan-stock-manage 正文同步：proposal Capabilities 收窄、design D16 `/system` 表格加"由 system-page-change 维护"指向注记、tasks 移除/标注迁出条目（8.4/10.x 页面任务迁出至本 change，8.3/12.x 归 `bsp-page-change`，14.2/14.3 标注数据模型按 B 套）——验证：grep `openspec/changes/chan-stock-manage` 无指向已迁需求的残留描述。
- [x] 7.3 watchlist 底层 3 条需求迁 `watchlist-page-change`（其 spec 补入文件夹分类/字段展示/批量加入三条、proposal 更新"不修改底层需求"声明），并从 chan-stock-manage 删 `specs/watchlist/` 及 proposal/tasks 对应条目——验证：两 change 合并视角下 watchlist 需求不重不漏，`openspec validate` 两 change 均通过。

## 8. 端到端验证

- [ ] 8.1 真后端冒烟（`VITE_USE_MOCK=false`）：admin 登录 → 四条件查询 → 新建用户并分配角色 → 该用户登录（权限随角色）→ 角色绑定/权限配置保存即生效（菜单显隐与写接口 403/放行随之变化）→ 归因走一遍——验证：全流程无报错、权限变化即时可观察。
- [ ] 8.2 mock 对齐验证（`VITE_USE_MOCK=true`）：8.1 同场景在 mock 下行为一致——验证：契约级行为无分叉。

## 9. 迁移承接的已落地页面任务（自 chan-stock-manage 迁入，仅存验证记录）

- [x] 9.1 历史买卖点页（原 cSM 8.3；页面需求已归 `bsp-page-change`，此处仅存历史验证记录）：查询表单 + 结果表多选 + 加入自选/监控；验证：查询→加入自选→加入监控全流程可用。（板块聚合按冲突裁定不再验收；日期查询控件由 `bsp-page-change` 承接。）
- [x] 9.2 监控页 + 完成页（原 cSM 8.4）：监控列表 + 盈利走势折线 + 总体盈利 + 归因按钮 + 失败原因列表/详情；验证：监控→结算→归因全流程可用。（归因由占位改为真实生成见任务 6.x。）
- [x] 9.3 买卖点绩效统计（原 cSM 10.1/10.2）：`GET /api/bsp/performance` 聚合胜率/盈亏比/样本数 + 样本明细下钻；验证：统计结果与样本明细吻合。
