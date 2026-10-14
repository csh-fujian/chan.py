# strategy-signal Specification

## Purpose
定义策略信号能力（策略定义 / 任务 / 信号）的可观察行为：注册表 schema 驱动（含参数说明与任务详情声明）的任务管理、信号归属任务、信号状态机与存储契约、策略引擎统一接口与水位调度、策略任务页的交互行为。

## Requirements

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

### Requirement: 策略实例废弃与迁移
原策略实例（strategy_instance）SHALL 废弃：系统 SHALL NOT 再提供实例创建/启停/删除入口，信号 SHALL 挂接任务而非实例。存量实例数据 SHALL 提供迁移（转为等价任务）或清理，迁移后其历史信号归属迁移出的任务。

#### Scenario: 创建任务替代创建实例
- **WHEN** 用户在某策略定义下新建执行单元
- **THEN** 创建的是带股票范围与任务形态的任务，而非不可变实例

#### Scenario: 停用实例入口下线
- **WHEN** 用户操作已迁移的存量任务
- **THEN** 不存在「实例启停」入口；任务用 status（含暂停）与 mode（test/persistent）表达生命周期


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
每个策略引擎 SHALL 实现统一扫描接口：输入待扫键集合与扫描水位，输出信号事件列表；引擎 SHALL 只读 DuckDB 原始 K 线数据。系统 SHALL 按（**任务**, 编码）维护扫描水位，调度 SHALL 在日终（收盘后）自动触发 **persistent 任务**的增量扫描，并 SHALL 支持手动触发补算；test 任务只在用户启动/续跑时执行，不参与日终调度。

**引擎消费缠论结论的许可（B3/B4 判定链路）**：需要缠论买点结论的策略引擎（如 vol_breakout_pullback 的 B3/B4）SHALL 经由间接链路获取——先只读查询 PG bsp_index；无数据时触发数据补齐（DuckDB K 线缺失则调灌数接口补全，再调增量续算引擎将缠论结论落 PG bsp_index）后回读。引擎 SHALL NOT 直接 import CChan/CBiList/CSegListChan/CZSList/CBSPointList 运行缠论计算；引擎对 bsp_index 的访问 SHALL 限于只读，SHALL NOT 修改或删除 bsp_index 既有行（写入仅经增量续算引擎的整套替换语义）。

#### Scenario: 日终增量扫描
- **WHEN** 日终调度触发且当日有新增 K 线
- **THEN** 各 persistent 任务按水位增量扫描并更新信号，水位前移

#### Scenario: 手动补算
- **WHEN** 用户手动触发某任务补算
- **THEN** 系统从该任务当前水位继续扫描至最新数据

#### Scenario: 不触碰缠论内核
- **WHEN** 任意策略引擎运行
- **THEN** CChan/CBiList/CSegListChan/CZSList/CBSPointList 的计算逻辑不被引擎 import 或执行；引擎可只读 PG bsp_index 消费既有缠论买点结论，并可触发增量续算引擎补算，但 SHALL NOT 直接修改或删除 bsp_index 表内数据（写入仅经增量续算引擎的整套替换语义）

#### Scenario: 引擎触发缠论补算
- **WHEN** vol_breakout_pullback 引擎扫描某股票，B3 判定需要 30 分钟缠论买点，而 PG bsp_index 无该 (code, 30m) 数据
- **THEN** 引擎经补算链路（灌数 → 增量续算引擎 → bsp_index 落库）后回读结论；补算产生的 bsp_index 写入遵循增量续算引擎的整套替换语义，引擎自身不写入

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
