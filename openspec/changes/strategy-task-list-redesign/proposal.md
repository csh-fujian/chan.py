# 变更提案：策略信号页任务列表重设计

## Why

策略信号页当前的任务列表无任何查询条件（全量平铺），且任务「策略任务类型」（策略大类:策略名分层结构）与「准确率」信息在列表层不可见——准确率只存在于任务详情的绩效统计块里，用户要逐个点开详情才能比较任务好坏。同时左侧策略任务树与右侧任务列表功能重叠（树承担了类型过滤与新建入口），排版冗余。本次把任务列表升级为带查询条件与准确率/类型列的信息密度更高的单一视图，并简化页面布局。

## What Changes

- 任务列表增加查询条件：策略任务类型（级联两级：策略大类 → 策略定义）、任务名（模糊）、分组（模糊）、形态（长期/测试）、创建时间（日期区间）、准确率分档（80-100、60-80、60 以下、无数据）
- 任务列表增加列：准确率（null → '--'）、策略任务类型（`group_name : name` 分层展示）
- 任务名列下的策略名子文本删除（由独立的策略任务类型列承接，避免重复）
- **BREAKING**（页面结构）：删除左侧策略任务树侧栏；页面改为单列布局
- 任务列表上方增加「新建策略任务」按钮，替代原侧栏策略名旁的 + 入口
- 新建任务弹窗增加第一步：先选策略任务类型（级联两级），选中后联动展示该定义的参数表单、分组与股票范围配置
- 后端任务列表数据源（`get_definitions_with_tasks`）为每个任务节点拼装 `accuracy` 字段（口径与任务详情绩效统计一致：success/(success+failed)，分母 0 → null）
- 前端查询条件为内存过滤（任务列表数据已全量在前端，不新增后端查询接口）
- mock 数据与 MSW handler 同步补 `accuracy` 字段

## Capabilities

### New Capabilities

（无——本次全部为既有能力的规格变更）

### Modified Capabilities

- `strategy-signal`：「策略信号页交互」需求变更——删除左侧策略树布局要求，页面改为单列；任务列表增加查询条件与准确率/策略任务类型列。
- `strategy-task`：任务列表数据源需求变更——任务节点数据 SHALL 携带准确率字段（后端批量聚合拼装）；新建任务弹窗交互需求变更（先选类型联动配置）。

## Impact

- 后端 `WebAPI/strategy_store.py`：`get_definitions_with_tasks` 增加准确率批量聚合（一条 GROUP BY task_id SQL，复用 `compute_outcome_kv_stats` 口径），任务节点拼 `accuracy`
- 前端 `Front/src/api/types.ts`：`StrategyTask` 增加 `accuracy: number | null`
- 前端 `Front/src/views/strategy/StrategySignalView.vue`：删侧栏、加查询条件区、加两列、新建按钮
- 前端 `Front/src/views/strategy/TaskDialog.vue`：加策略任务类型级联选择联动
- 前端 `Front/src/mock/data/strategy.ts` 与 `Front/src/mock/handlers/strategy.ts`：mock 任务补 accuracy
- 不改 `CChan`/`CBiList`/`CSegListChan`/`CZSList`/`CBSPointList` 计算内核
