## Purpose

定义策略信号能力（策略定义 / 任务 / 信号）的可观察行为：注册表 schema 驱动（含参数说明与任务详情声明）的任务管理、信号归属任务、信号状态机与存储契约、策略引擎统一接口与水位调度、策略任务页的交互行为。本文件为对 `strategy-signal` 能力的增量修改（该能力现行 requirements 来自已完成未归档的 strategy-signal-page 变更，实例模型被任务模型整体替换）。

## MODIFIED Requirements

### Requirement: 策略定义注册表
系统 SHALL 维护策略定义注册表，每个策略定义 SHALL 声明：策略标识、显示名称、引擎标识、参数模式（params_schema：每个参数的类型/默认值/范围/**说明 desc**）、状态集合（states：该策略信号生命周期中可能出现的状态列表）、表格列声明（columns：信号列表页的私有列）、**任务详情声明（detail_schema：任务详情页的展示积木块组合，见 strategy-task 能力）**。策略定义 SHALL 由代码注册（随版本发布），用户 SHALL NOT 能增删策略定义。注册新策略定义时 detail_schema 为必填声明。

#### Scenario: 查看策略列表
- **WHEN** 用户打开策略任务页
- **THEN** 侧栏按策略大类分组展示全部已注册策略定义，每个定义下展示其任务节点

#### Scenario: 新策略接入零前端改动
- **WHEN** 后端注册一个新的策略定义（含 params_schema/states/columns/detail_schema 声明）
- **THEN** 前端策略任务页无需代码修改即可展示该策略：参数表单、状态标签、表格私有列、任务详情均由声明驱动渲染

#### Scenario: 参数说明悬浮
- **WHEN** 用户在任务创建表单中将鼠标悬浮于某参数名旁的说明图标
- **THEN** 展示该参数的说明文案（来自 params_schema 的 desc 声明）

### Requirement: 信号存储与状态机
每条信号 SHALL 至少包含：股票编码、**所属任务**、信号日期、方向（买/卖）、状态（state，取值域为所属策略定义声明的 states）、入场参考价、止损参考价、策略私有字段（payload）、**产生该信号的参数版本（params_version）**。信号状态 SHALL 按策略定义的生命周期演进（如 回调中 → 已触发/已失效 → 已启动）；**信号一旦进入「已加入监控」的终态，其状态 SHALL 冻结不再演进**。同一任务下信号的更新 SHALL 幂等（按任务 + 编码 + 信号键去重，重扫不产生重复行）。

#### Scenario: 增量扫描幂等
- **WHEN** 调度对某任务重复扫描同一批 K 线
- **THEN** 已存在的信号不重复插入，状态变化按最新扫描结果更新

#### Scenario: 状态冻结边界
- **WHEN** 一条信号已加入监控，之后引擎扫描发现其后续行情演进
- **THEN** 该信号的 state 不再变化；后续演进信息 SHALL NOT 反向写入该信号

#### Scenario: 信号携带参数版本
- **WHEN** 一个 params_version 为 2 的任务产生新信号
- **THEN** 该信号行记录 params_version=2，与 v1 时期的旧信号在列表中可区分

### Requirement: 策略引擎统一接口与调度
每个策略引擎 SHALL 实现统一扫描接口：输入待扫键集合与扫描水位，输出信号事件列表；引擎 SHALL 只读 DuckDB 原始 K 线数据，SHALL NOT 依赖 CChan 计算内核。系统 SHALL 按（**任务**, 编码）维护扫描水位，调度 SHALL 在日终（收盘后）自动触发 **persistent 任务**的增量扫描，并 SHALL 支持手动触发补算；test 任务只在用户启动/续跑时执行，不参与日终调度。

#### Scenario: 日终增量扫描
- **WHEN** 日终调度触发且当日有新增 K 线
- **THEN** 各 persistent 任务按水位增量扫描并更新信号，水位前移

#### Scenario: 手动补算
- **WHEN** 用户手动触发某任务补算
- **THEN** 系统从该任务当前水位继续扫描至最新数据

#### Scenario: 不触碰缠论内核
- **WHEN** 任意策略引擎运行
- **THEN** CChan/CBiList/CSegListChan/CZSList/CBSPointList 的计算逻辑与 bsp_index 表不被读写修改

### Requirement: 策略信号页交互
策略任务页 SHALL 为独立顶导页面（与 /bsp 买卖点页并存，/bsp 保持纯缠论语义）。页面左侧 SHALL 为策略树（策略大类分组 → 策略定义 → 任务节点，节点显示信号计数）；右侧 SHALL 提供筛选工具栏（股票搜索、状态、方向、日期范围）与服务端分页的信号列表；列表通用列 SHALL 包含：编码、名称、信号日期、状态、方向、入场参考价、止损参考价、行业；策略私有列按策略定义的 columns 声明动态渲染；状态列按 states 声明着色；信号行 SHALL 展示参数版本标识。行点击 SHALL 打开详情抽屉，展示该股票 K 线与信号标注；详情抽屉 SHALL 提供「加入监控」操作（监控记录任务维度来源，见 strategy-signal-downstream）。

#### Scenario: 切换实例
- **WHEN** 用户点击侧栏另一任务节点
- **THEN** 列表切换为该任务的信号集，筛选条件保留（原实例切换语义由任务节点承接）

#### Scenario: 私有列动态渲染
- **WHEN** 当前任务所属策略定义声明了私有列（如 首板日、回调天数）
- **THEN** 列表展示这些列，切换到其他策略任务时按其声明更换列集

#### Scenario: 筛选与分页
- **WHEN** 用户组合状态 + 方向 + 日期范围筛选并翻页
- **THEN** 请求携带筛选参数与分页参数，响应包含 list/total/page/page_size

#### Scenario: 详情抽屉加入监控
- **WHEN** 用户在信号详情抽屉点击「加入监控」
- **THEN** 以该信号的入场参考价与信号日期创建监控条目，监控记录信号来源为该策略任务（含任务名与参数版本）

## REMOVED Requirements

### Requirement: 策略实例不可变
**Reason**: 实例模型被任务模型（strategy_task）整体替代：不可变实例与「试错迭代、暂停编辑续跑、转正长期执行」的任务心智冲突，spec 级行为全部由 strategy-task 能力与新增「策略实例废弃与迁移」requirement 承接。
**Migration**: 任务创建（含参数校验/全量回算）走 strategy-task 能力的任务模型 requirement；存量实例数据迁移为等价任务（见「策略实例废弃与迁移」）；实例启停 API 由任务 status/mode 表达。原「参数非法被拒绝」「改参数不覆盖历史」「停用实例」场景语义分别由任务创建校验、任务编辑两种续跑语义（strategy-task）、任务暂停与 persistent 调度承接。

## ADDED Requirements

### Requirement: 策略实例废弃与迁移
原策略实例（strategy_instance）SHALL 废弃：系统 SHALL NOT 再提供实例创建/启停/删除入口，信号 SHALL 挂接任务而非实例。存量实例数据 SHALL 提供迁移（转为等价任务）或清理，迁移后其历史信号归属迁移出的任务。

#### Scenario: 创建任务替代创建实例
- **WHEN** 用户在某策略定义下新建执行单元
- **THEN** 创建的是带股票范围与任务形态的任务，而非不可变实例

#### Scenario: 停用实例入口下线
- **WHEN** 用户操作已迁移的存量任务
- **THEN** 不存在「实例启停」入口；任务用 status（含暂停）与 mode（test/persistent）表达生命周期

