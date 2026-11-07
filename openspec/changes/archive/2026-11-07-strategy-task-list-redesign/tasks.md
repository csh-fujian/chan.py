# 任务清单：策略信号页任务列表重设计

## 1. 后端：任务列表数据源补准确率

- [x] 1.1 `WebAPI/strategy_store.py` 新增批量准确率聚合函数（一条 `GROUP BY task_id` SQL，口径对齐 `compute_outcome_kv_stats`：仅匹配态 `state IN ('triggered','running')`，`success/(success+failed)`，分母 0 → None），并用 `Debug/strategy_task_smoke.py` 风格脚本或 psql 抽查返回映射正确
- [x] 1.2 `get_definitions_with_tasks` 拼装任务节点 `accuracy` 字段（空映射兜底 null），调用 `GET /api/strategy/definitions` 验证响应任务节点含 accuracy

## 2. 前端类型与 mock

- [x] 2.1 `Front/src/api/types.ts` 的 `StrategyTask` 增加 `accuracy: number | null`，`npm run build`（vue-tsc）通过
- [x] 2.2 `Front/src/mock/data/strategy.ts` 任务数据补 accuracy（按各任务信号 outcome 分布确定性计算，覆盖 80-100/60-80/60 以下/null 四档样本），`Front/src/mock/handlers/strategy.ts` definitions handler 透传；`npm run dev` 下任务列表准确率列与分档筛选联调可见四档样本

## 3. 前端布局：删侧栏 + 查询条件 + 新列

- [x] 3.1 `StrategySignalView.vue` 删除左侧策略任务树 `<aside>` 及支撑逻辑（`groupedDefinitions`/`taskGroupsOf`/`onDefLabelClick`/`selectedDefId`），页面改单列布局；保留默认选中首个任务与删除任务回退逻辑，`npm run dev` 页面无侧栏、两 Tab 正常
- [x] 3.2 任务列表 Tab 顶部加「+ 新建策略任务」按钮（调 `openCreateTask`，后续接 TaskDialog 新契约），按钮可达新建弹窗
- [x] 3.3 任务列表加查询条件区（策略任务类型 el-cascader 两级 / 任务名 input / 分组 input / 形态 select / 创建时间 daterange / 准确率分档 select 含「无数据」档），实现 `allTasks` computed 链过滤（分档语义按 design D3：null 仅命中「无数据」），各条件组合过滤结果正确
- [x] 3.4 任务列表加「策略任务类型」列（`group_name:name` 查表拼接）与「准确率」列（null → '--'，否则百分比），删除任务名列策略名子文本，列渲染正确

## 4. 前端弹窗：TaskDialog 先选类型联动

- [x] 4.1 `TaskDialog.vue` props 从 `definition: StrategyDefinition | null` 改为 `definitions: StrategyDefinition[]`，弹窗顶部加策略任务类型 el-cascader（两级，叶子 value = definition id），选中后 `currentDefinition` computed 联动展示任务名/分组/参数/范围区块（未选类型不展示、提交不可用），`StrategySignalView.vue` 调用处同步改传法定义列表
- [x] 4.2 类型切换时参数重置为新定义 default（分组与范围选择保留），spec scenario「切换类型重置表单」手动验证通过；新建任务全流程（选类型 → 填参数 → 建范围 → 提交）联调成功

## 5. 收尾验证

- [x] 5.1 `npm run build`（vue-tsc + vite）通过；MSW mock 下完整走查：查询条件各档过滤、准确率列展示、新建弹窗类型联动、信号 Tab 从任务行信号数进入、加入监控链路不回归
