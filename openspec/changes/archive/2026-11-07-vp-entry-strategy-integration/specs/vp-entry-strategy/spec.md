## Purpose

定义量价三段式买点策略（vp_entry）作为策略引擎接入任务体系的可观察行为：引擎扫描行为（日线退化兜底、B 日分钟级触发优先）、B 日后状态追踪状态机、策略定义声明（参数/状态/列/详情统计）、信号字段映射口径。

## ADDED Requirements

### Requirement: vp_entry 引擎扫描行为
vp_entry 策略引擎 SHALL 从 DuckDB 全历史日线逐日喂入量价三段式判定状态机（蓄势期 → A 日放量启动 → 调整期 → B 日触发）；B 日候选 SHALL 懒加载分钟数据（K_5M）：有分钟数据时 SHALL 按分钟级触发判定（涨幅区间 + 分钟放量 + 虚拟全天量口径），无分钟数据时 SHALL 退化日线版判定（高开区间 + 全日放量）。引擎 SHALL 每次扫描重算全历史信号集并按唯一键幂等 upsert，已冻结（加入监控）信号 SHALL NOT 被覆盖；引擎 SHALL 只读 DuckDB，SHALL NOT 依赖 CChan 计算内核。同任务同股同 B 日 SHALL 至多一条信号。

#### Scenario: 分钟版触发
- **WHEN** B 日候选判定时该股当日存在 K_5M 分钟数据
- **THEN** 按分钟级触发判定（触发分钟收盘价为买价），信号记录触发方式为分钟版

#### Scenario: 日线退化版兜底
- **WHEN** B 日候选判定时该股当日无分钟数据
- **THEN** 退化日线版判定（买价 = B+1 日开盘价，次日回填），信号记录触发方式为日线版

#### Scenario: 重扫幂等
- **WHEN** 任务重复扫描同一股同一批 K 线
- **THEN** 既有信号不重复插入，状态按最新扫描结果更新，frozen 信号不变

#### Scenario: 不触碰缠论内核
- **WHEN** vp_entry 引擎运行
- **THEN** CChan/CBiList/CSegListChan/CZSList/CBSPointList 计算逻辑与 bsp_index 不被读写修改

### Requirement: vp_entry 信号状态追踪
vp_entry 信号 SHALL 在 B 日触发后按后续日 K 推进状态：初始状态为 `triggered`；后续日收盘价上破 B 日最高价 SHALL 演进为 `running`；后续日收盘价跌破止损参考低点 SHALL 演进为 `expired`；未发生演进 SHALL 保持原状态。入场参考价 SHALL 为信号买价（分钟版 = 触发分钟收盘价，日线版 = B+1 日开盘价），止损参考价 SHALL 为信号止损参考低点。信号日期 SHALL 为 B 日。

#### Scenario: 启动确认
- **WHEN** 一条 triggered 信号后续某日收盘价上破该信号 B 日最高价
- **THEN** 该信号状态演进为 running

#### Scenario: 破止损淘汰
- **WHEN** 一条 triggered 信号后续某日收盘价跌破其止损参考低点
- **THEN** 该信号状态演进为 expired

#### Scenario: 信号字段口径
- **WHEN** 一条 vp_entry 信号落库
- **THEN** signal_date 为 B 日，entry_ref_price 为买价口径（分钟版/日线版各自取值），stop_ref_price 为止损参考低点

### Requirement: vp_entry 策略定义声明
vp_entry 策略定义 SHALL 由代码注册，声明：分组归属（量价策略大类）、参数模式（5 个可配参数：蓄势期 CV7 门限、区间盒宽上限、调整期超时天数、止损容忍、量能门口径——量能门口径为 enum 参数 mean/strict）、状态集合（triggered/running/expired）、信号列表私有列（A 日、量能峰日、触发方式、放量倍数、Spring 标记、净漂移桶、影线盒宽、蓄势天数）、任务详情积木（summary、per_stock、signals、kv-基底特征统计）。可配参数 SHALL 声明连续取值区间与默认值（默认值取定死版取值）；离散敏感性集合约束 SHALL NOT 进入任务参数声明（保留在回测侧）。任务详情 kv 统计 SHALL 包含：信号总数、分钟版/日线版占比、Spring 豁免占比、净漂移三桶分布、平均影线盒宽、平均蓄势天数、平均 A 日涨幅、当前存活信号数（triggered 未演进）。

#### Scenario: 创建 vp_entry 任务
- **WHEN** 用户在 vp_entry 策略定义下创建任务并填写合法参数（如 CV7 门限 0.22、量能门口径 strict）
- **THEN** 系统按 params_schema 校验通过后创建任务，枚举参数值必须在声明的选项集内

#### Scenario: 任务详情差异化展示
- **WHEN** 用户查看一个 vp_entry 任务的详情
- **THEN** 详情按声明渲染：汇总面板（进度/匹配数/参数版本）、逐股结果（显式范围）、信号表格（含 A日/触发方式/Spring 等私有列）、基底特征统计（分钟版占比、三桶漂移分布等 kv 项）

#### Scenario: 运行中查看详情
- **WHEN** 任务执行中用户打开任务详情
- **THEN** 汇总面板/逐股结果/信号列表展示当前已扫部分的数据，随执行进度刷新

#### Scenario: 任务侧参数自由配置
- **WHEN** 用户在声明的连续区间内配置 CV7 门限（如 0.27，不在回测敏感性集合 {0.20,0.25,0.30} 内）
- **THEN** 任务创建与执行正常，不受回测侧离散集合约束
