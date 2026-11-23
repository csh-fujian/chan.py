# Spec Delta

## Purpose

将 5 个经典顶部看跌形态（乌云盖顶、射击之星、高位吊颈线、高位阴包阳、高位穿头破脚阴线）实现为可计算的卖点信号：蜡烛图形态判据检测、置信分评分、与买点形态共表落库（direction 维度）、查询接口（卖向默认收敛到关注范围）、K 线页独立 overlay 标识与新卖点提示。

## ADDED Requirements

### Requirement: 顶部形态检测判据
系统 SHALL 对全量已加载的 K 线检测 5 种顶部看跌形态，每种形态的判据 MUST 以其文档（`文档/买卖点走势图/卖点/`）的形态特征为依据，且位置前提（上涨趋势/高位）MUST 作为硬约束生效（非高位出现一律丢弃），量能佐证（巨量/爆量/放量）MUST 进入置信分评分。

#### Scenario: 乌云盖顶成立
- **WHEN** 上涨趋势后，T1 为实体阳线，T2 高开低走收阴线，且 T2 阴线实体向下覆盖 T1 阳线实体的 1/3 以上
- **THEN** 系统报告一次乌云盖顶命中，确认时间为 T2 收盘时间，参考价位含 T1/T2 实体边界

#### Scenario: 覆盖不足 1/3 不报
- **WHEN** T2 阴线实体向下覆盖 T1 阳线实体不足 1/3
- **THEN** 系统不报告乌云盖顶

#### Scenario: 射击之星成立
- **WHEN** 上涨末端出现一根 K 线：实体极小、上影线极长（≥ 实体倍数阈值）、下影线极短，且成交量放大（爆量）
- **THEN** 系统报告一次射击之星命中，确认时间为该 K 线收盘时间

#### Scenario: 高位吊颈线成立
- **WHEN** 上涨末端出现一根 K 线：实体极小、下影线极长（≥ 实体倍数阈值）、上影线极短，且成交量放大
- **THEN** 系统报告一次高位吊颈线命中（射击之星的镜像判据）

#### Scenario: 高位阴包阳成立
- **WHEN** 上涨趋势中 T1 收阳线，T2 高开低走收大阴线，且 T2 阴线实体从开盘到收盘完全包裹 T1 阳线实体
- **THEN** 系统报告一次高位阴包阳命中

#### Scenario: 高位穿头破脚阴线成立且优先于阴包阳
- **WHEN** 满足阴包阳条件，且 T2 开盘价高于 T1 最高价（穿头）、收盘价低于 T1 最低价（破脚），完全覆盖 T1 全部波动区间
- **THEN** 系统报告高位穿头破脚阴线（更强形态、置信分更高），同一根 K 线 SHALL NOT 同时报告阴包阳

#### Scenario: 非高位出现丢弃
- **WHEN** 任一顶部形态的结构出现在非高位区间（结构前无上涨趋势）
- **THEN** 系统丢弃该匹配，不落库

#### Scenario: 一字板剔除
- **WHEN** 形态 K 线为涨跌停一字板（开盘=收盘=最高=最低，无实体波动）
- **THEN** 系统不将该 K 线判定为形态 K 线（一字板形态失真）

### Requirement: 置信分评分
系统 SHALL 为每个顶部形态命中计算 0~100 置信分，按结构轴/量能轴/位置轴加权，含一票否决项（非高位出现、无量佐证的临界形态）；落库只存总分与档位，评分明细现算。

#### Scenario: 穿头破脚分数高于普通吞没
- **WHEN** 同一结构分别满足穿头破脚与普通阴包阳判据
- **THEN** 穿头破脚的结构轴得分高于普通阴包阳

#### Scenario: 量能不足降档
- **WHEN** 形态成立但形态 K 线量比低于阈值
- **THEN** 量能轴计 0 分或低分，总档位下降，且 detail 中记录量比

### Requirement: 卖点信号落库与 direction 维度
系统 SHALL 将顶部形态命中写入 `pattern_signal` 表（与买点形态同表），每行带 `direction='sell'`；买点形态存量与新增行 `direction='buy'`；写入 MUST 幂等（唯一键冲突时覆盖更新），加列与回填 MUST 幂等可重复执行。

#### Scenario: 卖向信号落库
- **WHEN** 增量引擎对某股票某周期完成形态检测
- **THEN** 顶部形态行以 `direction='sell'` 写入 `pattern_signal`，唯一键 `(code, kl_type, autype, pattern_type, confirm_time_key)` 冲突时覆盖

#### Scenario: direction 加列幂等
- **WHEN** store 模块在已有存量数据的表上重复执行惰性 DDL
- **THEN** `direction` 列只添加一次，存量行回填 `'buy'` 且重复执行不产生副作用

### Requirement: 卖向查询的关注范围默认作用域
`GET /api/pattern` SHALL 支持 `direction` 查询参数；当 `direction=sell` 且未显式指定 `code` 时，SHALL 默认只返回关注范围（自选 ∪ 监控股票清单）内的信号；显式指定 `code` 时 SHALL 返回该股票信号（K 线页单股查询不受关注范围限制）；`direction=buy` 或不传时的行为 MUST 保持与买点版一致。

#### Scenario: 列表查询只返回关注股票的卖点
- **WHEN** 请求 `GET /api/pattern?direction=sell` 且未传 `code`，信号表中存在非关注股票的卖点信号
- **THEN** 响应只包含自选或监控清单内股票的卖点信号

#### Scenario: K 线页单股查询不受限
- **WHEN** 请求 `GET /api/pattern?direction=sell&code=sz.000001`（该股不在自选/监控中）
- **THEN** 响应返回该股票的卖点信号

#### Scenario: 买向查询行为不变
- **WHEN** 请求 `GET /api/pattern?direction=buy` 或不传 direction
- **THEN** 返回结果与买点版查询语义一致（含全部股票）

### Requirement: K 线页独立卖点 overlay
K 线页 SHALL 提供顶部形态独立 overlay（第六个覆盖层），与缠论四标识（笔/段/中枢/买卖点）及买点形态 overlay 完全分割：独立注册、独立开关、独立点击交互；顶部形态用独立色系，不与买点形态共用色板。

#### Scenario: 独立开关控制
- **WHEN** 用户关闭卖点形态 overlay 开关而开启买点形态 overlay
- **THEN** 图上只显示买点形态标识，卖点形态标识不渲染

#### Scenario: 卖点标识点击交互
- **WHEN** 用户点击图上卖点形态标识
- **THEN** 弹出该形态的注意事项与置信分明细（META 来自 `/api/pattern/meta`）

### Requirement: 新卖点提示
对关注范围内（自选 ∪ 监控）的股票，确认时间在最近 M 根 K 线内的顶部形态信号 SHALL 显示「新卖点信号」提示徽标；非关注股票的卖点 SHALL NOT 触发提示。

#### Scenario: 关注股票新卖点提示
- **WHEN** 自选/监控股票的最新确认卖点信号在最近 M 根内
- **THEN** 买卖点页形态 Tab 该行显示「新卖点信号」徽标

#### Scenario: 非关注股票不提示
- **WHEN** 非自选且非监控的股票出现新卖点信号
- **THEN** 买卖点页形态 Tab（默认关注范围查询）不展示该行，无提示
