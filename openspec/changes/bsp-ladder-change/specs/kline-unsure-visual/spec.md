## MODIFIED Requirements

> 本 delta 修改 `kline-unsure-visual` 能力的需求；该能力 spec 首次落地于未归档变更 `kline-unsure-dashed`。归档顺序约束：`kline-unsure-dashed` 先归档使 `openspec/specs/kline-unsure-visual` 存在，本变更其后归档时 MODIFIED delta 方可合并。

### Requirement: 买卖点标记确认阶梯悬浮提示

K 线主图买卖点覆盖层（`chan_bsp`）SHALL 支持鼠标悬浮交互：悬浮任一买卖点标记时展示 tooltip，内容至少包含该买卖点的当前确认阶梯级别（`L1`/`L2`/`L3`/`L4`）与四级阶梯说明（各级名称与仓位指引：L1 小级别区间套佐证、L2 虚笔候选—观察仓 1/4、L3 背驰预警—加仓至 1/2、L4 确认买卖点—满仓），当前级别 SHALL 在四级说明中被高亮标识。数据侧依赖 `/api/klines` 响应的 `bsp[].ladder` 字段。

#### Scenario: 悬浮展示级别与说明

- **WHEN** 用户鼠标悬浮 K 线主图上的任一买卖点标记
- **THEN** 出现 tooltip，标明该买卖点的当前级别（如 L3）并列出 L1-L4 四级说明与仓位指引，当前级别高亮

#### Scenario: 级别随数据刷新更新

- **WHEN** 数据重算后某买卖点的 `ladder` 发生变化（如 L2 → L4）
- **THEN** 刷新后悬浮同一标记的 tooltip 展示新级别

#### Scenario: 无级别数据时的兜底

- **WHEN** 响应中某买卖点缺少 `ladder` 字段（如降级或旧缓存）
- **THEN** tooltip 以未定级兜底展示，不报错、不阻断图表渲染
