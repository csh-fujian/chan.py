# Proposal: strategy-task-redesign

## Why

现行策略信号页（strategy-signal-page 变更落地）以「不可变实例」为原子单位：建实例即隐式对全 A 股扫描，无股票范围选择、无任务执行概念、无进度与暂停续跑，实例参数不可编辑导致试错迭代成本高（调参必须新建实例）。用户实际心智模型是「策略 + 任务」：选股范围可配的一次性测试任务，试跑满意后转成长期任务，且后续将不断新增策略类型，任务详情需按策略类型差异化展示。

## What Changes

- **`strategy_instance` 废弃，统一为 `strategy_task` 任务模型**（**BREAKING**）：
  - 任务字段：策略定义 id、用户命名 label、用户自定义分组 user_group、params、scope（股票范围）、mode（`test` 一次性测试 / `persistent` 长期任务）、status（pending/running/paused/done）、进度计数（scanned/total）、params_version
  - 任务可编辑：暂停后允许编辑，提供两种续法——「重新运行」（默认，清空该任务旧信号后全量重扫）与「剩余股票继续」（用新参数从当前进度续跑）；每次编辑 params_version +1，信号行携带版本标识，混合参数信号可归因
  - 转正：test 任务满意后转 persistent（mode 翻转 + 挂 EOD 日终调度）；persistent 任务范围可编辑（重新解析为快照），**参数冻结**（调参 = 复制任务重新测试）
- **股票范围（scope）模型**，三种来源 + 全量兜底：
  - 手动批量添加股票 / 从自选文件夹拷贝股票（快照语义，落库时固化，后续自选变化不影响任务）/ 关联 /bsp 页查询条件快照批量选股
  - 未选择股票 = 全量扫描所有 A 股（默认排除 ST 与 *ST）
- **逐股结果记录按范围分叉**（存储量约束）：显式范围任务逐股落 `strategy_task_stock_result`（每只股票的匹配/未匹配/失败结果）；全量范围任务不落逐股结果，只维护聚合计数；**两种范围的匹配成功记录都落 `strategy_signal`**（信号即匹配记录）
- **任务管理**：任务列表（任务信息、策略类型、分组、创建时间、创建人）+ 进度条展示执行进度 + 启动/暂停/续跑
- **注册表声明增强**：
  - `params_schema` 每个参数新增 `desc` 字段 → 前端参数名旁悬浮说明图标（el-tooltip）
  - 新增 `detail_schema` 声明（积木块：table / kv_summary / timeline / chart / per_stock_result）：新策略注册时**必须**声明其任务详情的展示形态，前端按声明渲染；`per_stock_result` 块仅在 scope 为显式范围（有逐股数据）时渲染，全量范围静默隐藏
- **策略寻优（参数反馈学习）为后续独立变更**，本变更仅在 proposal 层面预留方向：打分器（信号 → 质量）→ 优化实验（每轮 = 一个 test 任务）→ walk-forward 样本外验证。不在本变更实现任何寻优能力
- 前端页面按「任务为中心」重排信息架构：左侧策略大类 → 策略 → 任务树，右侧任务信号列表 / 任务详情 / 任务管理
- 不改动：CChan/CBiList/CSegListChan/CZSList/CBSPointList 计算逻辑、bsp_index 表结构、DuckDB 原始 K 线层（引擎仍纯读 DuckDB）；引擎统一接口与水位游标机制保留（`strategy_scan_cursor` 键从 instance_id 改指 task_id）

## Capabilities

### New Capabilities

- `strategy-task`: 策略任务模型与生命周期——任务 CRUD、用户分组、参数编辑与 params_version、两种续跑语义（重新运行/剩余继续）、test→persistent 转正与参数冻结、股票范围模型（三种来源快照 + 全量兜底排 ST）、逐股结果按范围分叉落库、任务执行进度与启停管理、detail_schema 积木块驱动的任务详情展示

### Modified Capabilities

- `strategy-signal`: 原实例不可变约定整体替换为任务模型（该能力现行 requirements 来自已完成未归档的 strategy-signal-page 变更，本变更改写其任务/实例相关 requirements：信号归属从 instance_id 改为 task_id、实例不可变改为任务可编辑 + 转正冻结、params_schema 声明加 desc、新增 detail_schema 声明要求）；strategy_instance 及关联 API 废弃（BREAKING）
- `strategy-signal-downstream`: monitor 联动字段从 instance_id 改为 task_id（BREAKING）；信号状态冻结语义保留、挂接对象变更
- `bsp-monitoring`: monitor 来源回查按 task_id 分叉（strategy 来源查 strategy_signal 的 task_id 维度），列表来源标签语义不变

## Impact

- **后端**：`WebAPI/strategy_store.py`（任务表/逐股结果表/迁移 instance→task）、`strategy_engines/`（注册表声明增强 desc/detail_schema、调度器挂 task 维度）、`routers/strategy.py`（任务 API 重写：创建/编辑/续跑/转正/进度/详情）、monitor_store.py 联动字段改造
- **数据库**：PG 新增 strategy_task、strategy_task_stock_result 表；strategy_signal 的 instance_id 列替换为 task_id + params_version（数据迁移：存量实例转任务或清理）；strategy_scan_cursor 键变更；DDL 追加 WebAPI/update.sql（幂等）
- **前端**：`Front/src/views/strategy/` 重构（任务树/任务列表/进度条/任务详情按 detail_schema 渲染/创建任务弹窗含范围选择与参数 tooltip）、api/modules/strategy.ts、mock handlers 同步
- **不改动**：缠论计算内核、bsp_index、/bsp 页面、DuckDB K 线层
- **后续变更**：strategy-optimization（寻优闭环，本变更不实现）
