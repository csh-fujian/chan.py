# Spec Delta

## Purpose

在 K 线主图上对每级别「最近一笔/最近一段」（含虚笔/虚段）做背驰判断并以前端红色阴影标注，判断口径复用缠论参数配置中的背驰技术指标与力度阈值。

## ADDED Requirements

### Requirement: 最近笔/段的背驰判断口径

系统 SHALL 对每级别 K 线序列的最后一个笔元素与最后一个线段元素（无论 `is_sure` 为 true 或 false）按「相邻同向前一元素直接比力度」判断背驰：笔与同向前一笔（隔一元素）比较，线段与同向前一线段比较。背驰力度 SHALL 按缠论参数配置生效值计算：`macd_algo` 多选时须全部指标同时满足背驰（AND 语义），阈值使用同一配置的 `divergence_rate`（判定为 背驰力度[最近元素] <= `divergence_rate` × 背驰力度[前一元素]）。

#### Scenario: 相邻同向笔比较
- **WHEN** 某级别笔序列为 [UP, DOWN, UP]（最近一笔为末位 UP，`bi[n-2]` 为同向 UP）
- **THEN** 系统将末位 UP 笔的力度与前一条 UP 笔比较，按阈值判定是否背驰

#### Scenario: 多指标 AND 语义
- **WHEN** 生效配置勾选了 `full_area` 与 `slope` 两个背驰技术指标，最近元素在 `full_area` 上背驰但在 `slope` 上不背驰
- **THEN** 系统判定该元素不背驰

### Requirement: 背驰字段的数据契约

`/api/klines` 响应中每级 `bi[]` 与 `seg[]` 数组的**最后一个元素** SHALL 携带 `is_divergence` 字段，取值为 `true`（判为背驰）、`false`（判为不背驰）或 `null`。`null` SHALL 用于：不适用（同向前一元素不存在、力度值为零/不可比）、或配置声明不判断。非末尾元素 SHALL NOT 携带该字段的判定值（不计算、不输出或输出 `null`）。周期切换后系统 SHALL 按新级别的序列重新计算该字段。

#### Scenario: 末尾元素携带判定值
- **WHEN** 某级别响应返回 10 个笔元素且最近一笔可判
- **THEN** 仅第 10 个元素携带非 `null` 的 `is_divergence`，其余元素该字段为 `null` 或不存在

#### Scenario: 无同向前一元素
- **WHEN** 某级别笔序列不足两条同向笔（如仅有 2 条笔）
- **THEN** 末尾元素的 `is_divergence` 为 `null`

### Requirement: 不判断力度时的处理

当生效配置的 `divergence_rate` 为无穷大（完全不看力度对比）时，系统 SHALL 对该请求的所有级别输出 `is_divergence: null`，前端 SHALL 不渲染任何背驰标注。

#### Scenario: 配置关闭力度对比
- **WHEN** 用户在缠论参数配置中将「背驰力度阈值」设为「不限」（inf）
- **THEN** 重算后的 `/api/klines` 响应中所有 `is_divergence` 为 `null`，K 线图上无背驰红线

### Requirement: 量能类指标的段级回退

当生效配置勾选的背驰技术指标含段级不支持项（成交量/成交额/换手率类）时，线段级背驰力度 SHALL 按买卖点链路既有的段级回退算法（`peak`）计算，笔级 SHALL 按原生算法计算。

#### Scenario: 勾选成交量指标
- **WHEN** 生效配置勾选 `volumn`（成交量），某级别线段序列足够判背驰
- **THEN** 线段级背驰按 `peak` 口径计算，笔级按成交量口径计算

### Requirement: 背驰的红色阴影渲染

K 线主图 SHALL 将 `is_divergence` 为 `true` 的笔/线段以红色阴影形式标注：在原结构线下垫一条更粗的半透明红色线，原笔/线段的结构色、线型（虚/实）与线宽语义保持不变。标注 SHALL 随数据刷新更新（新一次加载/重算后按最新判定重绘），且明暗主题切换 SHALL 不改变标注语义（仅允许阴影透明度/色值随主题微调以保证对比度）。

#### Scenario: 背驰笔渲染
- **WHEN** 某级别最近一笔 `is_divergence: true` 且为未确认虚笔
- **THEN** 该笔以原虚线型绘制，其下垫一条更粗的半透明红色阴影线

#### Scenario: 数据刷新后标注更新
- **WHEN** 新 K 线到来触发重新计算，最近一笔由背驰转为不背驰
- **THEN** 刷新后该笔下不再渲染红色阴影线
