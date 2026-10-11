## 1. 后端：分组实体与存储

- [x] 1.1 `WebAPI/monitor_store.py`：`_ensure_tables` 新增 `monitor_group` 表（id/name/sort_order/created_at）与 `monitor.group_id` 可空列（`ON DELETE SET NULL` FK），启动后确认 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 对存量库幂等生效
- [x] 1.2 `WebAPI/monitor_store.py`：新增分组 DAO——`create_group`（名称查重 + sort_order 末尾追加）、`list_groups`（按 sort_order 排序，含每组 monitoring/completed 计数）、`rename_group`、`delete_group`、`reorder_groups`，PG 不可达时沿用 fallback 降级惯例；用 psql 或临时脚本对每个函数做增删改查冒烟
- [x] 1.3 `WebAPI/routers/monitor.py`：新增 `GET/POST /monitor/groups`、`PATCH/DELETE /monitor/groups/{id}`、`PUT /monitor/groups/reorder` 端点（名称非法/重名返回 4xx 明确 detail）；curl 验证全生命周期（建→列→改→排→删）

## 2. 后端：监控接口扩展分组

- [x] 2.1 `WebAPI/monitor_store.py`：`create_monitor` 接受可选 `group_id`（写 NULL 当未传），`list_monitoring`/`list_completed` 接受 `group_id` 过滤参数（缺省不过滤 / `ungrouped` 哨兵 → `IS NULL` / 数值 → 精确匹配）
- [x] 2.2 `WebAPI/routers/monitor.py`：`POST /monitor` 透传可选 `group_id`（校验存在性，不存在 4xx）；`GET /monitor`、`GET /monitor/completed` 新增 `group_id` query 参数（非法值 422）；curl 三种参数形态各验一次列表过滤结果

## 3. 前端：API 层与类型

- [x] 3.1 `front/src/api/modules/monitor.ts`：新增 `MonitorGroup` 类型与 `getMonitorGroups/createMonitorGroup/renameMonitorGroup/deleteMonitorGroup/reorderMonitorGroups` 五个函数；`CreateMonitorPayload` 增加可选 `group_id?: number`；`getMonitorList/getCompletedList` 增加可选 `group_id` 参数；`npm run build`（vue-tsc）通过
- [x] 3.2 `front/src/mock/`：MSW handlers 与数据补分组端点（含名称查重、删除置未分组、reorder 持久化的内存模拟）与列表 `group_id` 过滤；dev 模式下 mock 全流程可走通

## 4. 前端：监控页左侧栏分组树与管理

- [x] 4.1 `MonitorView.vue`：监控中 tab 左侧栏新增分组过滤树（TreeList：全部/未分组 + 各分组按 sort_order），选中即带 `group_id` 调 `getMonitorList` 重查；跨 tab 切回分组选择保持；`ungrouped` 哨兵正确传递
- [x] 4.2 `MonitorView.vue`：分组树管理动作——hover 重命名/删除图标、模式化新建/重命名弹窗（对齐 WatchlistView D6 模式）、删除前 ElMessageBox 确认（含组内记录数提示）、失败错误提示；完成后分组树与下拉数据同步刷新
- [x] 4.3 `MonitorView.vue`：分组拖拽排序（复用 WatchlistView draggable 实现，全部/未分组虚拟节点不参与拖拽），落 `PUT /monitor/groups/reorder`；拖拽后顺序持久化（刷新页面验证）
- [x] 4.4 `MonitorView.vue`：已完成 tab 左侧栏新增只读分组过滤树（同 4.1 过滤逻辑、无管理动作），选中带 `group_id` 调 `getCompletedList`
- [x] 4.5 统计与走势联动验证：选中分组后总体盈利/当前胜率/涨幅最大与盈利走势图按该组列表数据计算；选「全部」恢复全局口径；人工核对数值与该组列表行一致

## 5. 前端：买卖点页加入监控弹窗

- [x] 5.1 `BspView.vue`：加入监控弹窗新增分组 `el-select`（默认「未分组」）+ 下拉尾部「新增分组」行内输入（成功即选中，重名/非法报后端 detail）；提交携带 `group_id`；加入后在监控页对应分组下可见该记录（端到端手验）

## 6. 端到端验证

- [x] 6.1 mock 模式全链路手验：BspView 加入选组/新建组/不选组三种加入 → 监控页分组过滤（监控中+已完成）→ 重命名/删除（组内记录归未分组）→ 拖拽排序刷新保持 → 统计/走势联动口径
- [x] 6.2 真后端联调（PG 可达时）：curl/页面走同链路，重点验证存量 monitor 记录归「未分组」、`ungrouped` 过滤、FK 置 NULL 删除语义
