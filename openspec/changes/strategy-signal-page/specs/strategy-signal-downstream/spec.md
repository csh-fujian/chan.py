## Purpose

定义策略信号对下游系统（监控、预警、绩效）的接入契约：信号来源维度、回查路径分叉、stub 阶段 API 的 source 参数预留，以及信号与监控的生命周期边界。

## ADDED Requirements

### Requirement: 监控信号来源维度
监控条目 SHALL 记录信号来源：`source_type`（'chan' 或 'strategy'）；来源为策略时 SHALL 同时记录所属实例与信号日期。存量监控条目 SHALL 默认 'chan'，行为不变。监控创建接口 SHALL 接受来源字段；从策略信号页发起的加监控 SHALL 携带 strategy 来源。

#### Scenario: 存量数据兼容
- **WHEN** 变更上线后查询历史监控条目
- **THEN** 其 source_type 均为 'chan'，列表展示与计算行为与变更前一致

#### Scenario: 策略信号加监控
- **WHEN** 从策略信号页对一条信号发起加监控
- **THEN** 创建的监控条目 source_type='strategy'，并记录该信号的实例与信号日期

### Requirement: 买卖点上下文回查分叉
监控列表补齐信号上下文（类型/方向/日期）时 SHALL 按来源分叉：'chan' 走 bsp_index 回查（现状路径不变）；'strategy' 走策略信号回查（按实例 + 信号日期定位，取该信号的 state、方向、入场参考价）。查不到时 SHALL 使用兜底值（与现状兜底策略一致）。

#### Scenario: 缠论监控回查不变
- **WHEN** source_type='chan' 的监控条目列表加载
- **THEN** 买卖点上下文仍按 bsp_index 在 monitor_start_time 前最近一条回查

#### Scenario: 策略监控回查
- **WHEN** source_type='strategy' 的监控条目列表加载
- **THEN** 上下文来自 strategy_signal 定位到的信号行（状态、方向、入场参考价），非 bsp_index

### Requirement: 监控列表来源展示
监控列表 SHALL 展示信号来源标签列：缠论来源显示买卖点类型语义（现状），策略来源显示「策略名 · 实例名 · 状态」。来源列 SHALL NOT 改变现有列布局的其余部分。

#### Scenario: 来源标签区分
- **WHEN** 监控列表同时存在 chan 与 strategy 来源条目
- **THEN** 来源列分别显示如「缠论 ·2类买」与「首板回调 ·回调5日 ·已触发」

### Requirement: 预警与绩效 source 预留
预警规则与绩效统计的 API 契约 SHALL 预留 source 维度参数（可按信号来源过滤/分组），实现均为 stub 状态，本变更 SHALL NOT 交付其具体实现。

#### Scenario: 绩效按实例维度预留
- **WHEN** 绩效 API 被调用并携带 strategy 实例过滤参数
- **THEN** stub 返回空集，参数被接受不报错（契约已预留）

### Requirement: 信号与监控生命周期隔离
监控条目 SHALL 保持独立生命周期：策略信号状态冻结（不因监控内事件演进），监控 SHALL NOT 反向更新信号；卖点结算、监控结束等事件 SHALL NOT 写回 strategy_signal。

#### Scenario: 监控事件不回写信号
- **WHEN** 一条策略来源的监控完成卖出结算
- **THEN** 对应 strategy_signal 行的任何字段不变
