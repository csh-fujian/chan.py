# Tasks: strategy-task-redesign

## 1. 注册表与数据模型

- [x] 1.1 `strategy_engines/__init__.py`：`StrategyDefinition` 加 `detail_schema` 字段，vol_breakout_pullback 定义补 desc 与 detail_schema 声明（summary/per_stock/signals/kv），verify: import 后 `DEFINITIONS['vol_breakout_pullback'].detail_schema` 非空且每个 param 有 desc
- [x] 1.2 update.sql 追加幂等 DDL：strategy_task / strategy_task_stock_result 建表（IF NOT EXISTS），verify: 重复执行 update.sql 不报错
- [x] 1.3 update.sql 追加幂等迁移 DO 块：strategy_signal.instance_id→task_id + params_version、strategy_scan_cursor 键改、monitor.instance_id→task_id、存量实例转任务、drop 旧表旧列，verify: 对含存量实例数据的 PG 执行后 strategy_task 行数 = 原实例数、signal.task_id 全部非空、重复执行幂等
- [x] 1.4 strategy_store.py：惰性建表改为新表结构（不再建 strategy_instance），任务 CRUD（create/list/get/patch/start/pause/resume/promote/copy/delete）+ 逐股结果写入 + 进度推进，verify: 手动冒烟脚本对任务全生命周期（建→启→暂→改→续→转正→删）操作成功

## 2. 执行与调度

- [x] 2.1 scheduler.py 改造：`scan_instance` → `run_task`（读任务行、按 scope 枚举 code、'all' 走 ST 过滤、单 worker 循环逐 code 边界检查暂停、显式范围写逐股结果），verify: Debug 冒烟脚本跑一个 manual 范围任务，逐股结果行数 = 范围数，全量任务不落逐股结果
- [x] 2.2 重新运行/剩余继续语义：resume 路径 full 模式清信号+结果+水位重扫、remaining 模式从 progress 续跑新参数，verify: 冒烟脚本对 30/100 暂停任务分别走两路径，信号 params_version 与保留行为符合 spec
- [x] 2.3 app.py EOD 循环：只取 mode='persistent' 任务增量扫描（水位门不变），test 任务不参与，verify: 代码审查 + EOD 循环单测冒烟（mock 任务集）

## 3. API 层

- [x] 3.1 routers/strategy.py 重写：definitions 透出 desc/detail_schema；tasks CRUD/操作/详情端点（D6 全集）；信号查询参数 instance_id→task_id；删除实例端点，verify: 手动 curl/HTTP 冒烟覆盖每个端点正常 + 校验失败路径（422/404/409）
- [x] 3.2 转正与复制端点：promote（mode 翻转 + 纳入 EOD）、copy（继承参数与范围为 test），verify: 冒烟转正后任务出现在 persistent 调度集、复制出的任务参数/范围同源且可编辑
- [x] 3.3 monitor_store.py 联动：`_fill_bsp_context` strategy 分支按 task_id 回查、monitor 写入路径 task 维度，verify: 冒烟从策略任务信号加监控，监控列表来源标签显示「策略名 · 任务名 · 状态」

## 4. 前端

- [x] 4.1 api/modules/strategy.ts + types 重写（任务模型、detail_schema 类型），MSW mock handlers 同步（任务/逐股结果/进度/详情数据），verify: `npm run build` 通过且 mock 页面数据可加载
- [x] 4.2 页面信息架构重构：侧栏策略大类→策略→任务树（含 user_group 分组展示）、任务列表 Tab（基础信息/策略类型/分组/创建人/创建时间 + 进度条 + 启停/编辑/转正/复制/删除操作），verify: mock 模式页面全操作可走通
- [x] 4.3 创建任务弹窗：params_schema 驱动表单 + desc 悬浮 tooltip 图标 + 默认值 + 任务命名 + 分组新建/选择 + 股票范围三来源选择器（manual/watchlist 文件夹/bsp 查询条件）+ 全量兜底提示，verify: mock 下三种来源 + 全量四种创建路径均成功
- [x] 4.4 任务编辑与续跑弹窗：paused 编辑（参数/范围，persistent 仅范围）+ 重新运行（默认）/剩余继续选择，verify: mock 下编辑后两续法分支与进度表现正确
- [x] 4.5 任务详情页（detail_blocks 渲染器）：summary/per_stock/signals/kv/timeline 五个积木组件 + 按 detail_schema 声明渲染 + per_stock 在全量任务静默隐藏，verify: mock 两个不同 detail_schema 的任务详情风格不同、全量任务无逐股块
- [x] 4.6 信号列表改造：查询挂 task_id、信号行参数版本标识、监控来源标签文案改任务名，verify: mock 信号列表版本标签显示、加监控条目标签正确

## 5. 回归与收尾

- [x] 5.1 端到端冒烟：真 PG + DuckDB 环境跑通「创建 manual 范围任务→执行→暂停→编辑→剩余继续→转正→EOD 增量→信号加监控→monitor 列表回查」全链路，verify: Debug 脚本断言各环节状态与数据
- [x] 5.2 归档前置检查：归档 strategy-signal-page（使三个能力 spec 入主树），再校验本变更 validate 无 INFO（delta 均有目标），verify: `openspec validate strategy-task-redesign` 输出 valid 且无 archive 警告
