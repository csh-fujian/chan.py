## Purpose

定义放量启动回调（vol_breakout_pullback）策略引擎的信号判定行为：A 日（放量启动）识别、回调窗口的量能与破位判定（含冲高豁免）、状态演进与绩效追踪（A/B 点字段与 7/14/30 日绩效展示）。首个引擎级成文能力（此前该策略仅在 strategy-signal 引擎协议下以近似实现存在，判定规则未 spec 级成文）。

## ADDED Requirements

### Requirement: 放量首板识别
系统 SHALL 识别放量启动日（A 日）：某交易日成交量 ≥ 前 20 日均量 × volume_ratio_min（放量倍数阈值，默认 2.0），且当日收盘涨幅 ≥ a_pct_min（**涨幅门槛，可配参数，默认 5%**）。次新股（上市不足 20 日）SHALL NOT 参与判定。识别出的 A 日 SHALL 作为信号日期，同一 (任务, 编码, A 日) 只产生一条信号。

#### Scenario: 放量启动日命中
- **WHEN** 某日量比为 3.0 且收盘涨幅 6%（≥ a_pct_min 默认 5%）
- **THEN** 该日被识别为放量启动日，进入回调窗口观察

#### Scenario: 涨幅不足不算 A 日
- **WHEN** 某日量比 3.0 但收盘涨幅 3%（< a_pct_min）
- **THEN** 该日不构成 A 日，不产生信号

#### Scenario: 涨幅门槛可配
- **WHEN** 用户创建任务时将 a_pct_min 配置为 9.8%（模拟近似涨停首板口径）
- **THEN** 涨幅 3% 的日子不构成 A 日；任务详情参数区展示 a_pct_min=9.8%

### Requirement: 回调窗口量能判定与冲高豁免
A 日后 SHALL 观察回调窗口（pullback_max_days 个交易日，默认 7）。窗口内 SHALL 以量能峰 P 锚定：**P = 窗口内最后一个量 ≥ A 日量 × 0.8 的交易日（若窗口内均无放量日则 P = A 日）**。缩量判定 SHALL 只作用于 P 之后的回调日（D' = {P+1, …, 窗口末}）：每个回调日量 < A 日量 × volume_shrink_max（默认 0.8）SHALL 视为缩量满足。**A 日后放量冲高（量 ≥ A 日量 × 0.8）SHALL NOT 直接判定缩量失败**——冲高回落形态由 P 锚定后的末段缩量兜底。破位判定 SHALL 作用于窗口全程：任一回调日收盘 < A 日开盘价 SHALL 直接判 expired（回调破位）。

窗口走完且未破位、且 D' 全程缩量 → triggered；D' 缩量不满足 → expired。triggered 后任一日收盘 > 窗口内最高收盘价 → running。

#### Scenario: 冲高回落不被误杀
- **WHEN** A 日次日量 4.92 亿（量比 A 日 97%），之后连续 6 日缩量至 A 日量 30% 且收盘未破 A 日开盘
- **THEN** 量能峰 P 锚定于次日（冲高日），缩量判定从 P+1 日起算并满足 → 信号 triggered

#### Scenario: 持续放量出货淘汰
- **WHEN** 窗口后半段（P 之后）多日量维持在 A 日量 80% 以上
- **THEN** 缩量判定失败 → 信号 expired

#### Scenario: 回调破位淘汰
- **WHEN** 窗口内某日收盘 < A 日开盘价
- **THEN** 信号 expired，不给出入场价

#### Scenario: 突破回调高点确认启动
- **WHEN** 一条 triggered 信号后续某日收盘 > 回调窗口内最高收盘价
- **THEN** 信号演进为 running

### Requirement: vol_breakout 信号字段口径
入场参考价 SHALL 为回调窗口（A 日后 pullback_max_days 个交易日内）的最低收盘价（triggered/running 态），止损参考价 SHALL 为 A 日最低价。watching 态（窗口未走完、数据边界）SHALL NOT 给出入场价/止损价。**入场日（B 日 + 绩效起算日）SHALL 为窗口内最低收盘价出现的交易日（实际回踩低点日，回调天数 = B 日 − A 日的交易日数）**。绩效字段（三时段收益率 + 成功判定）按 strategy-signal 能力的统一口径计算。

**任务详情的信号列表 SHALL 展示以下合并列（price_pct 列型）**：A日（时间）+ A日股价（A 日收盘价 | A 日涨幅）；B日（时间）+ B日股价（B 日收盘价 | B 日当日涨跌幅 = B 日收盘/开盘 - 1）；7/14/30日股价（该日收盘价 | 相对入场参考价涨跌幅）。**SHALL NOT 展示**：首板日列（与 A 日列重复）、方向列、入场参考价列（与 B 日股价的价格分量重复）。数据不足的合并单元格涨幅部分显示为空。**回调天数 SHALL 为实际值（B 日 − A 日），SHALL NOT 恒等于回调窗口参数值。**策略摘要（kv 块）SHALL NOT 展示首板日分布、平均放量倍数、平均回调天数（形态统计项删除，仅保留绩效准确率统计）。

#### Scenario: 信号字段取值
- **WHEN** 一条 triggered 信号落库
- **THEN** entry_ref_price = 缩量窗口最低收盘价，stop_ref_price = A 日最低价，signal_date = A 日

#### Scenario: 绩效起算
- **WHEN** 一条 triggered 信号的窗口最低收盘价出现日（B 日）为 T
- **THEN** +7/+14/+30 日收益率按 T+7/T+14/T+30 日收盘价 / entry_ref_price - 1 计算

#### Scenario: 详情信号列表字段展示
- **WHEN** 任务详情的信号列表渲染一条匹配信号
- **THEN** 该行以合并单元格展示 A日股价、B日股价（当日涨跌）、7/14/30日股价与成功判定；不含首板日、方向、入场参考列

#### Scenario: B 点口径
- **WHEN** 一条 triggered 信号展示 B 日股价列
- **THEN** 价格分量 = B 日收盘价（入场参考价同源），涨幅分量 = B 日收盘价 / B 日开盘价 - 1（当日涨跌）；B 日 = 窗口内最低收盘价出现的交易日

#### Scenario: 回调天数为实际值
- **WHEN** A 日为 T0、窗口内最低收盘价出现在 T0 后第 4 个交易日（B 日）
- **THEN** 回调天数 = 4（B 日 − A 日的交易日数），不恒等于 pullback_max_days 参数值

#### Scenario: 参数说明白话化
- **WHEN** 用户在任务创建表单悬浮 a_pct_min 参数的说明图标
- **THEN** 说明文案为面向普通用户的白话（调高/调低的后果与正反例），SHALL NOT 出现「首板口径」「量价规则口径」等策略演化历史术语
