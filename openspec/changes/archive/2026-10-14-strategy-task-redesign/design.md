# Design: strategy-task-redesign

## Context

strategy-signal-page 变更已全部落地：PG `strategy`/`strategy_instance`/`strategy_signal`/`strategy_scan_cursor` 四表（strategy_store.py 惰性建表 + 代码注册表 `_sync_definitions` 同步）、引擎协议 `scan(code, kl_type_db, autype, watermark)`（strategy_engines/__init__.py）、调度器 `scan_instance`（scheduler.py，DuckDB 日线全量枚举 code）、路由（routers/strategy.py，含 BackgroundTasks 全量回算）、前端 `Front/src/views/strategy/` 三组件 + MSW mock、monitor 的 source_type/instance_id 联动（monitor_store.py `_fill_bsp_context` 分叉）。本变更把「不可变实例」替换为「任务」模型。约束（延续全部既有变更约定）：不改缠论计算内核与 bsp_index；引擎纯读 DuckDB；PG 存结论与元数据。

**归档顺序约束**：`strategy-signal` / `strategy-signal-downstream` / `bsp-monitoring` 三个能力的主树 spec 尚不存在（strategy-signal-page 完成未归档）。本变更归档前 MUST 先归档 strategy-signal-page，否则 MODIFIED delta 无归档目标（validate 已给出此提示）。

## Goals / Non-Goals

**Goals:**
- 任务模型落地：创建（范围选择三种来源 + 全量兜底）、执行（进度/暂停/续跑两种语义）、转正（test→persistent + 参数冻结）、复制调参
- 存量实例数据平滑迁移为任务
- detail_schema 积木块渲染体系（新策略注册即获得差异化任务详情）
- 监控联动从 instance_id 迁到 task_id

**Non-Goals:**
- 不实现策略寻优（打分器/优化实验/walk-forward）——后续 strategy-optimization 变更，本变更仅保证寻优轮次能以 test 任务形态存在（任务模型天然支持）
- 不做盘中实时扫描（维持 EOD + 手动触发）
- 不做用户级分组权限（user_group 是纯组织性标签，非权限边界）
- 不做多任务并行执行引擎（单 worker 串行跑任务队列即可，见 D6）

## Decisions

### D1. 表模型：strategy_task 取代 strategy_instance

```
strategy_task
  id SERIAL PK
  strategy_id VARCHAR FK -> strategy(id)
  label VARCHAR NOT NULL            -- 用户命名
  user_group VARCHAR DEFAULT ''     -- 用户自定义分组（无独立分组表）
  params JSONB NOT NULL             -- 当前生效参数
  params_version INT NOT NULL DEFAULT 1
  scope_type VARCHAR NOT NULL       -- 'manual' | 'watchlist' | 'bsp_query' | 'all'
  scope_codes JSONB                 -- 显式范围: 固化快照 code 列表; 'all': NULL
  mode VARCHAR NOT NULL DEFAULT 'test'   -- 'test' | 'persistent'
  status VARCHAR NOT NULL DEFAULT 'pending'  -- pending/running/paused/done
  progress_scanned INT NOT NULL DEFAULT 0
  progress_total INT NOT NULL DEFAULT 0
  created_by VARCHAR               -- 创建人
  created_at, updated_at TIMESTAMPTZ

strategy_task_stock_result
  id BIGSERIAL PK
  task_id INT FK -> strategy_task(id) ON DELETE CASCADE
  code VARCHAR NOT NULL
  matched BOOLEAN NOT NULL          -- 是否命中策略
  run_status VARCHAR NOT NULL       -- 'ok' | 'failed'
  message TEXT                      -- 失败原因 / 摘要
  signal_date DATE                  -- matched 时冗余信号日期
  params_version INT NOT NULL
  executed_at TIMESTAMPTZ
  UNIQUE (task_id, code)

strategy_signal
  instance_id INT  ->  task_id INT FK（列替换，BREAKING）
  + params_version INT NOT NULL
  其余列不变; UNIQUE(task_id, code, signal_date)

strategy_scan_cursor: instance_id 列 -> task_id
```

- **user_group 不建独立表**：分组是任务行上的一个字符串标签，新建分组 = 输入新字符串。备选（分组表 + FK）被否决：分组无自身属性、无排序/权限需求，独立表徒增 JOIN 与删除级联复杂度。
- **scope 用 scope_type + scope_codes 快照**：watchlist / bsp_query 来源只在创建时解析一次（D3），运行期只看固化后的 code 列表，来源类型仅作展示回溯。
- **stock_result 的 UNIQUE(task_id, code)**：重跑同一只股票 = 覆盖该行（最新一次执行结果），不追加历史——逐股结果是「当前一轮的运行快照」而非执行日志。

### D2. 续跑两种语义的落地

- **重新运行（默认）**：单事务内 `DELETE strategy_signal WHERE task_id=?` + `DELETE strategy_task_stock_result WHERE task_id=?` + `DELETE strategy_scan_cursor WHERE task_id=?` + `progress_scanned=0`，再以新参数重扫。旧信号**物理删除**（spec 明确「清空后重扫」，与原「实例不可变保留历史」相反——历史保真需求已由「复制任务」路径承接）。
- **剩余股票继续**：不动已扫部分，进度计数不变，调度从 progress 处续。旧参数信号（params_version 旧值）与新参数信号共存，靠信号行 params_version 区分。
- 编辑提交入口：`PATCH /api/strategy/tasks/{id}`（校验状态为 paused、test 任务参数可改/persistent 参数拒绝改范围除外），服务端 params_version+1 由「保存时检测 params 是否变化」驱动。
- 水位处理细节：重新运行清空水位（全量重扫）；剩余继续保留水位但仅对未扫 code 有意义（已扫 code 的水位同样保留，不重扫）。

### D3. 范围快照的三种来源解析

- `manual`：前端多选/搜索添加，直接传 code 列表
- `watchlist`：前端传 `folder_id`，后端从 PG watchlist 表读该文件夹股票 → 固化为 scope_codes（创建时点快照，此后文件夹变化无关）
- `bsp_query`：前端传 /bsp 页当前查询条件（bsp_type/kl_type/is_sure 等既有查询参数），后端调用 bsp_store 既有查询函数取 code 列表 → 固化
- `all`：scope_codes 为 NULL；执行时枚举 DuckDB 全量 code，并按股票元数据（stock_store）过滤 ST/*ST（名称前缀匹配）
- 备选（范围保存为动态引用，如 watchlist 文件夹 id 持续联动）被否决：spec 明确「拷贝语义」；动态引用会让任务结果随自选变化漂移，无法归因。

### D4. 执行模型：单 worker 任务队列 + 乐观进度

- 后台执行器维持**单并发**（一个 asyncio 后台循环逐个取 status='running' 的任务执行），执行单位 = 「从当前进度起扫 N 只 code、写结果/信号、推进 progress_scanned、循环」；每只 code 后 commit 进度，进度对前端可见（前端轮询任务列表，间隔 3s）
- 暂停 = 任务行置 status='paused'，执行器在每个 code 边界检查任务状态，下一边界停止
- 备选（多 worker 并行 / Celery 式任务框架）被否决：扫描是 DuckDB 只读 + PG 写，单进程串行已够用（全量 A 股约 5000 键 × 引擎毫秒级），并行会引入 DuckDB 并发读与进度写入竞争，收益不成比例
- EOD 调度：日终循环只取 mode='persistent' 的任务做增量扫描（水位门逻辑不变）；test 任务只在用户启动时执行
- 与现有 scheduler.py 的关系：`scan_instance` 改造为 `run_task`（读任务行替代读实例行），核心扫描循环（水位门 + 引擎 + upsert + 水位推进）原样保留

### D5. detail_schema 积木块

```python
detail_schema: list[dict]  # 声明式积木块序列
# 积木块类型（v1 全集）:
#   {"type": "summary"}     -- 汇总面板: 进度/总数/匹配数/失败数
#   {"type": "signals"}     -- 该任务信号表格（复用信号列表列声明）
#   {"type": "per_stock"}   -- 逐股结果表格（scope 为 all 时静默隐藏）
#   {"type": "kv"}          -- 键值摘要块, items: [{key,label,from_payload|from_task}]
#   {"type": "timeline"}    -- 时间线: 信号日期序列 + 状态演进
#   {"type": "chart"}       -- 信号日期分布图 / 匹配率走势（ECharts, v1 可仅支持 date_histogram）
```

- 渲染器是**前端一组通用积木组件**（`Front/src/views/strategy/detail_blocks/`），按 type 映射到组件，块 props 来自声明字段。新策略组合既有积木 → 零前端改动；需要新积木类型时才动前端（注册新组件 + 类型扩展，向后兼容）
- vol_breakout_pullback 的 v1 声明：`[summary, per_stock, signals, kv(首板统计: 首板日分布/平均放量倍数/平均回调天数)]`
- 备选（每策略一个 Vue 组件、由注册表映射组件名）被否决：违背「零前端改动接入」目标，且组件代码不可由后端声明驱动
- detail API：`GET /api/strategy/tasks/{id}/detail` 返回 `{task, summary, per_stock?, signals_page, definition.detail_schema}`，前端按声明渲染；per_stock 块的数据在 scope='all' 时后端直接不返回，前端隐藏逻辑与后端一致

### D6. 注册表与 API 改造面

- `StrategyDefinition` dataclass 加 `detail_schema: list[dict]` 字段；params_schema 每项加 `desc` 键；`validate_params` 不变（desc 是展示元数据不参与校验）
- API 重写（routers/strategy.py）：
  - `GET /api/strategy/definitions`（加 detail_schema/params desc 透出）
  - `POST /api/strategy/tasks`（创建：范围解析三种来源 + params 校验）
  - `GET /api/strategy/tasks?strategy_id&user_group&status`（任务列表 + 进度）
  - `PATCH /api/strategy/tasks/{id}`（编辑：paused 才可编辑；test 可改参数/范围，persistent 仅范围）
  - `POST /api/strategy/tasks/{id}/start|pause`、`/resume`（body 带 `rerun: full|remaining`）
  - `POST /api/strategy/tasks/{id}/promote`（转正）、`/copy`（复制）
  - `GET /api/strategy/tasks/{id}/detail`
  - 信号查询从 `instance_id` 参数改为 `task_id`
  - 实例相关端点全部删除（BREAKING）
- monitor_store：`_fill_bsp_context` 的 strategy 分支从 instance_id 改按 task_id 回查；monitor 表 instance_id 列替换为 task_id（存量 'strategy' 来源行需要迁移，见 Migration）

### D7. 存量迁移

- `strategy_instance` → `strategy_task`：每实例生成一个任务（label/params 原样、scope_type='all'、mode='persistent'、status='done'、created_by 取实例创建信息），`strategy_signal.instance_id`、`strategy_scan_cursor.instance_id`、`monitor.instance_id` 按映射改指 task_id，之后 drop 旧列/旧表
- 迁移以幂等 SQL 写入 WebAPI/update.sql（DO 块判断列存在才执行），代码启动时不再建 strategy_instance 表（新装环境无此表）
- 存量实例信号默认 params_version=1
- 若迁移失败：保留 strategy_instance 表与数据，仅 API 层已切换（回滚 = 恢复旧代码；数据双轨期靠迁移脚本对齐）

## Risks / Trade-offs

- [重新运行物理删信号，历史不可恢复] → spec 已确认此语义；需要历史时先复制任务；删除在同一事务内，失败不产生半清空状态
- [暂停的「下一个 code 边界」粒度：暂停响应最长延迟一只股票的扫描时间] → 单键扫描毫秒级，可接受
- [params_version 混合信号的统计口径（绩效/信号列表聚合）含糊] → 信号列表显式展示版本标签；寻优变更落地时按版本分组统计
- [单 worker 队列在多任务同时 running 时排队等待] → 任务列表展示 queued 状态（status='running' 但执行器未取到）；用户可暂停让位
- [scope='all' 的 ST 过滤依赖股票名称元数据新鲜度] → 过滤在执行时实时读 stock_store；名称缺失的股票放行（宁多勿漏）
- [detail_schema 积木 v1 类型集合可能不够表达未来策略] → 积木体系设计为开放扩展（新增 type + 组件向后兼容），寻优等后续变更可加块类型
- [monitor 表二次 BREAKING（instance_id→task_id）] → 存量 strategy 来源监控条目量级小（该功能刚上线），迁移脚本直接改写

## Migration Plan

1. 归档 strategy-signal-page（前置：本变更的 MODIFIED delta 需要主树 spec 存在）
2. update.sql 追加幂等 DDL + 数据迁移（strategy_task / strategy_task_stock_result 建表、strategy_signal.instance_id→task_id、cursor 键改、monitor 列改、实例数据转任务、drop 旧表旧列）
3. 后端：注册表字段扩展 → strategy_store 任务 CRUD/迁移 → scheduler 改 run_task + 单 worker 执行器 → 路由重写 → monitor_store 联动改造
4. 前端：api/types + mock 重写 → 任务树/任务列表/进度条 → 创建任务弹窗（范围选择三来源 + 参数 tooltip）→ 任务详情 detail_blocks 渲染器 → monitor 来源标签文案改任务名
5. 回滚：后端回退代码后旧表已 drop，依赖 update.sql 中保留的迁移逆写说明（或从备份恢复）；前端页面为独立路由可整体隐藏

## Open Questions

- 任务详情的 chart 积木 v1 是否必须（还是 v1 只做 summary/per_stock/signals/kv/timeline，chart 留待有真实诉求的策略）——实现阶段按工作量决策，不影响其他块
- 任务列表是否需要服务端排序/筛选参数全集（user_group/status 过滤）——v1 按前端本地过滤即可，接口预留 query 参数
- 进度轮询 vs WebSocket 推送——v1 轮询（3s），前端已有轮询模式（monitor 页）；推送留待系统页统一升级
