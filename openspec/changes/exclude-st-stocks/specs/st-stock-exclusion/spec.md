## Purpose
定义 ST / *ST 股票的统一判定规则，以及该规则在股票查询、股票数据获取（元数据）、K 线灌数、K 线分析计算与策略/买卖点扫描各入口的排除行为，使 ST 股票不再消耗网络请求、灌数与计算资源。

## ADDED Requirements

### Requirement: ST 股票判定规则
系统 SHALL 以股票名称判定 ST 股票：名称去除首尾空白后，以 `ST` 或 `*ST` 开头（大小写不敏感）的股票即为 ST 股票。判定 SHALL 基于交易所身份同步得到的股票名称，且 SHALL NOT 依赖 `stock.enabled` 字段或新增存储列。

#### Scenario: 名称以 ST 开头
- **WHEN** 股票名称为 "ST某某" 或 "st某某"
- **THEN** 该股票被判定为 ST 股票

#### Scenario: 名称以 *ST 开头
- **WHEN** 股票名称为 "*ST某某"
- **THEN** 该股票被判定为 ST 股票

#### Scenario: 名称仅包含 ST 但不以其开头
- **WHEN** 股票名称中间含有 "ST" 字样但不以 "ST" 或 "*ST" 开头
- **THEN** 该股票不被判定为 ST 股票

#### Scenario: 名称缺失
- **WHEN** 某股票尚无名称记录（名称为空）
- **THEN** 该股票不被判定为 ST 股票，并按其余规则正常处理

### Requirement: 股票查询排除 ST
系统 SHALL 在股票查询接口（`GET /api/stocks`）的结果集、总数与分页中排除 ST 股票，且 SHALL 对所有查询参数（关键字、交易所、行业、启用状态）保持一致的排除行为。

#### Scenario: 关键字搜索不返回 ST 股票
- **WHEN** 用户以关键字搜索股票，且匹配项中包含 ST 股票
- **THEN** 返回结果与 total 均不包含该 ST 股票

#### Scenario: 无搜索条件的全量列表
- **WHEN** 用户不带任何筛选条件请求股票列表
- **THEN** 结果不包含任何 ST 股票，分页 total 仅统计非 ST 股票

#### Scenario: 股票查询的名称来源不可用
- **WHEN** 股票查询需要按名称判定 ST 而名称来源（PostgreSQL 股票表）不可用
- **THEN** 系统返回 503 并说明无法排除 ST 股票，而不返回未过滤的列表

### Requirement: 身份域仍对全市场同步
系统 SHALL 对全市场（包括 ST 股票）执行交易所身份域同步，以便识别新股、更名、以及股票进入或退出 ST 状态。

#### Scenario: 股票被标记为 ST
- **WHEN** 身份同步发现某股票名称变为 "ST" 开头
- **THEN** 该股票在下一轮其余元数据域调度中被排除，且身份记录被更新

#### Scenario: 股票摘帽
- **WHEN** 某 ST 股票名称恢复为非 ST 名称并被身份同步更新
- **THEN** 该股票在之后的元数据域调度中恢复纳入目标池

### Requirement: 逐股元数据目标池排除 ST
系统 SHALL 在 profile、industry、snapshot、financial、holders 等逐股元数据域的目标池中排除 ST 股票，使 ST 股票不再触发这些域的网络抓取。

#### Scenario: 元数据调度不抓取 ST 股票
- **WHEN** 元数据调度计算某一非身份域的待同步股票集合
- **THEN** 集合中不包含 ST 股票

#### Scenario: 启用状态与 ST 排除叠加
- **WHEN** 某股票未启用（enabled 为 false）且为非 ST 股票
- **THEN** 该股票仍按原有的启用状态规则被排除，且其 ST 状态不影响该判断

### Requirement: K 线灌数配置排除 ST
系统 SHALL 在生成与导出的 K 线灌数配置中排除 ST 股票，包括全市场灌数配置、`GET /api/stocks/export-config` 的返回结果，以及盘中轮询配置的生效集合。

#### Scenario: 生成全市场灌数配置
- **WHEN** 运行全市场股票枚举脚本生成灌数配置
- **THEN** 生成的配置文件不包含 ST 股票条目

#### Scenario: 导出灌数配置
- **WHEN** 请求 `GET /api/stocks/export-config`
- **THEN** 返回列表不包含 ST 股票

#### Scenario: 盘中轮询只轮询非 ST 股票
- **WHEN** 盘中轮询进程加载配置并启动
- **THEN** 配置中的 ST 股票不被轮询，且不新增其分钟级 K 线

#### Scenario: 灌数不新增 ST 股票 K 线
- **WHEN** 灌数进程执行一轮拉取
- **THEN** 其拉取的股票集合中不包含 ST 股票

### Requirement: K 线分析接口拒绝 ST 股票
系统 SHALL 对 ST 股票的 K 线分析请求（`GET /api/klines`）拒绝计算缠论结构，并 SHALL 返回 404，`detail` 注明 ST 股票已被排除。

#### Scenario: 请求 ST 股票的 K 线
- **WHEN** 客户端请求某 ST 股票任一周期的 K 线与缠论结构
- **THEN** 系统返回 404，且不执行缠论计算

#### Scenario: 请求非 ST 股票的 K 线
- **WHEN** 客户端请求非 ST 股票的 K 线
- **THEN** 行为与排除规则引入前一致

### Requirement: 策略扫描与买卖点补算排除 ST
系统 SHALL 在策略扫描的代码枚举与买卖点水位补算（catch-up / 日终流水线）的代码来源中排除 ST 股票。

#### Scenario: 策略全量扫描
- **WHEN** 调度对某策略实例执行全市场扫描
- **THEN** 扫描的代码集合不包含 ST 股票

#### Scenario: 买卖点补算
- **WHEN** 运行买卖点水位补算或日终流水线
- **THEN** 补算的代码集合不包含 ST 股票，且 ST 股票的买卖点结果不被新增或更新

### Requirement: 存量 ST 数据保留
系统 SHALL NOT 因本规则删除已存在于 DuckDB K 线表或 PostgreSQL 股票表中的 ST 股票数据；存量数据 SHALL 保持原样，仅停止对其新增与分析。

#### Scenario: 规则生效后已有 ST 数据
- **WHEN** 规则生效前已存在某 ST 股票的 K 线或元数据
- **THEN** 这些数据仍保留在存储中，且不被删除或改写

#### Scenario: 存量 ST 数据不再增长
- **WHEN** 规则生效后日终或盘中流程运行
- **THEN** 存量 ST 股票的 K 线不再新增

### Requirement: 依赖名称来源不可用时的降级
系统 SHALL 在股票名称来源（PostgreSQL 股票表）不可用、无法判定 ST 状态时，对生成灌数配置、导出灌数配置、策略扫描与买卖点补算等批量入口失败关闭（不输出未经过滤的集合），并 SHALL 记录告警。

#### Scenario: 名称来源不可用时导出配置
- **WHEN** 请求 `GET /api/stocks/export-config` 且名称来源不可用
- **THEN** 系统返回 503 并说明无法排除 ST 股票，而不返回未过滤的列表

#### Scenario: 名称来源不可用时批量补算
- **WHEN** 运行买卖点水位补算且名称来源不可用
- **THEN** 补算失败并报告错误，不对任何股票写入结果
