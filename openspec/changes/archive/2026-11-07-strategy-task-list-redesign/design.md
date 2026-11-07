# 设计：策略信号页任务列表重设计

## Context

当前策略信号页（`Front/src/views/strategy/StrategySignalView.vue`）为「左侧策略任务树 + 右侧任务列表/信号列表 Tab」双栏布局。任务列表数据来自 `GET /api/strategy/definitions`（`get_definitions_with_tasks` 一次返回全部定义 + 任务树，任务节点仅拼 `signal_count`）。准确率只存在于任务详情接口的 `kv_payload`（`compute_outcome_kv_stats` 单任务聚合）。新建任务弹窗（`TaskDialog.vue`）由侧栏 + 按钮传入 `props.definition`（类型在打开前已确定）。前端为 MSW mock 驱动（`Front/src/mock/`），真实后端为 `WebAPI/`（FastAPI + PG）。

## Goals / Non-Goals

**Goals:**
- 任务列表成为信息密度更高的单一视图：查询条件 + 准确率/策略任务类型列
- 页面单列化（删侧栏），新建入口收敛到任务列表上方按钮
- 新建弹窗内完成类型选择（级联两级）→ 配置联动
- 前后端同源：真实后端与 MSW mock 同步支持 `accuracy`

**Non-Goals:**
- 不新增后端查询接口（任务列表查询条件为前端内存过滤，数据已全量在 `allTasks`）
- 不改任务详情的绩效统计口径（`compute_outcome_kv_stats` 单任务版保留，列表用新批量版）
- 不改信号列表视图的筛选与分页逻辑
- 不改缠论计算内核与策略引擎

## Decisions

### D1：accuracy 由列表数据源批量拼装（一条 GROUP BY SQL）

`get_definitions_with_tasks` 新增一条按 `task_id GROUP BY` 的聚合 SQL（与 `compute_outcome_kv_stats` 同口径：`COUNT(*) FILTER (WHERE outcome='success'/...)`，仅匹配态 `state IN ('triggered','running')` 入统计），一次算完全部任务的 `{task_id: accuracy}` 映射，拼到任务节点。

- 备选 A（每任务一次 `compute_outcome_kv_stats`）：N+1 查询，任务多时慢——弃。
- 备选 B（物化列/缓存）：需要维护失效时机，引入状态不一致风险——弃。
- 空结果兜底：无任何任务信号时 SQL 返回空集，全部任务 accuracy 为 null。

### D2：查询条件为纯前端内存过滤

任务列表数据已经由 `getStrategyDefinitions()` 全量拉到前端（`allTasks` computed），查询条件做成对 `allTasks` 的 computed 链过滤（策略类型 → `strategy_id`、任务名/分组 → `includes` 模糊、形态 → `mode`、创建时间 → `created_at` 区间、准确率 → 分档区间/null 判断）。不新增后端查询参数与接口。

- 备选（后端查询 + 服务端分页）：当前任务量级（数十级）不需要，且会引入接口变更——留待任务量增长后再演进。

### D3：准确率分档语义（已与用户确认）

- 80-100：`accuracy >= 0.8`
- 60-80：`0.6 <= accuracy < 0.8`
- 60 以下：`accuracy < 0.6`（且非 null）
- 无数据：`accuracy == null`——null 不命中任何数值档

### D4：布局改造——删侧栏 + 单列

删除 `<aside>` 策略任务树整块及其支撑逻辑（`groupedDefinitions`/`taskGroupsOf`/`onDefLabelClick`/`selectedDefId`），`page-layout` 改单列。原侧栏承担的两个能力迁移：
- 类型过滤 → 查询条件的策略任务类型级联
- 新建入口 → 任务列表上方「+ 新建策略任务」按钮

信号列表入口保持 `gotoSignals`（任务行点信号数跳信号 Tab）。默认选中任务的逻辑保留（信号 Tab 需要 `currentTaskId` 上下文）。

### D5：TaskDialog 改为 definitions 全量传入 + 弹窗内级联选择

`props.definition`（单个）改为 `props.definitions`（全量数组）。弹窗顶部加 `el-cascader`（两级：`group_name` → 定义名，叶子 value = definition id）。选中叶子后 `currentDefinition` computed 取对应定义，模板对现有「任务名/分组/策略参数/股票范围」区块加 `v-if="currentDefinition"` 联动展示。类型切换时参数值重置为新定义 default（分组/范围选择保留，spec scenario「切换类型重置表单」）。

- 备选（两个 el-select 联动）：交互多一步，弃。
- 备选（平铺卡片选）：策略定义增多后不扩展，弃。

### D6：mock 同步补 accuracy

`Front/src/mock/data/strategy.ts` 任务生成处补 `accuracy` 字段（按各任务信号 outcome 分布确定性计算，风格与现有 `kv` 聚合一致），MSW handler `/api/strategy/definitions` 透传。mock 任务数据构造让各分档（80+/60-80/60 以下/null）都有样本可筛。

### D7：策略任务类型列渲染

独立列 `group_name:name`（如「量价策略:放量启动回调」），数据由 `defNameOf` 类似查表（`definitions.find(d => d.id === row.strategy_id)`）取 `group_name` 与 `name` 拼接。任务名列删除策略名子文本。

## Risks / Trade-offs

- [任务量大时前端全量过滤性能] → 当前任务量级（每定义数十）computed 过滤开销可忽略；量级增长后再迁移服务端分页。
- [accuracy 聚合 SQL 对无信号表首次部署的影响] → `_ensure_tables()` 已保证表存在；空表返回空映射，无兼容问题。
- [删侧栏后信号 Tab 无任务上下文时的空态] → 保留默认选中第一个任务的逻辑（信号 Tab 进入前必有 `currentTaskId`）；删除当前任务后回退首个可用任务（现有逻辑保留）。
- [TaskDialog props 契约变更是破坏性改动] → 唯一调用方是 `StrategySignalView`，同变更内一并改，无外部消费者。

## Migration Plan

无数据迁移。后端 `get_definitions_with_tasks` 增字段为向后兼容（前端同版本消费）；前端布局变更为一次性切换。回滚 = git revert 前后端两个提交。

## Open Questions

（无——分档语义、级联交互、null 处理均已与用户确认）
