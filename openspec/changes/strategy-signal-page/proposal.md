# Proposal: strategy-signal-page

## Why

买卖点页（/bsp）与 bsp_index 表的语义深度绑定缠论（bsp_type 六类、多级别 kl_type、区间套），无法承载非缠论策略生成的信号。用户即将引入「放量首板突破 → 量价配合回调 ≤N 日 → 启动」类策略，且策略数量是开放的——需要一套策略抽象（注册表 + 可配参数实例 + 统一信号模型）和独立页面，并将策略信号接入监控等下游，而非把 bsp_index 污染成宽表。

## What Changes

- **新增策略信号能力**（新顶导页面 + PG 三表 + 策略引擎层）：
  - PG 新表 `strategy`（策略定义：engine 标识、params_schema、states 声明）、`strategy_instance`（用户配置的参数实例，**不可变**：改参 = 新实例，历史信号永不覆盖）、`strategy_signal`（信号挂实例，通用列 + state 状态机 + payload JSONB 策略私有字段）
  - 策略引擎统一接口 `scan(keys, watermark) -> SignalEvent[]`，读 DuckDB 原始 K 线，不走 CChan 计算内核（延续所有变更「不改缠论计算逻辑」的约定）
  - 调度仿 bsp catchup 水位模式，按 (instance, code) 记扫描水位；第一版 EOD 日终跑一次
  - 首个策略引擎：放量首板回调（参数：回调天数上限、放量倍数阈值等，由 params_schema 声明）
- **新增前端「策略信号」页**：侧栏 = 策略定义分组 + 实例节点（切换/启停）；表格列、状态标签、参数表单由注册表 schema 驱动动态渲染；行点击进详情抽屉（K 线 + 信号标注）；支持「加入监控」
- **监控接入策略信号（source 维度）**：monitor 表加 `source_type`（'chan' | 'strategy'）+ `instance_id` + `signal_date`；`_fill_bsp_context` 按 source 分叉回查；监控页 UI 加信号来源标签列；**BREAKING**（monitor 表结构变更，默认值 'chan' 保持旧行为兼容）
- **预警 / 绩效预留 source 维度**：两者后端均为 stub，仅在 API 契约设计中带 source 参数，不做实现
- **不联动约定**：信号已触发并加入监控后，信号 state 冻结不再演进；监控保持独立生命周期
- **命名区分**：选股器页（/screener）已有的 "Strategy" 是缠论买卖点过滤器，本变更的「策略引擎信号」是独立概念，前端类型与文案明确区分（如 `StrategyInstance` / `SignalRecord` vs screener 的 `Strategy`）

## Capabilities

### New Capabilities

- `strategy-signal`: 策略定义/实例/信号的存储与计算契约——注册表 schema、实例不可变约定、信号状态机、引擎统一接口与水位调度、策略信号页交互（侧栏实例树、动态列、详情抽屉、加入监控）
- `strategy-signal-downstream`: 策略信号对下游的接入契约——monitor source 维度与回查分叉、预警/绩效 API 的 source 参数预留、信号 state 冻结边界

### Modified Capabilities

- `bsp-monitoring`: 监控条目新增信号来源维度（source_type/instance_id/signal_date），列表补齐买卖点上下文的回查路径按来源分叉（chan 走 bsp_index，strategy 走 strategy_signal），UI 展示来源标签

## Impact

- **后端**：`WebAPI/` 新增 strategy_store.py、strategy 引擎模块、routers/strategy.py；monitor_store.py 的 `_fill_bsp_context` 与 monitor 建表/写入路径改造；app.py 调度注册
- **数据库**：PG 新增 3 张表；monitor 表加列（ALTER，带 DEFAULT 'chan'，旧行为不变）
- **前端**：`Front/src/` 新增 views/strategy/ 页面、api/modules/strategy.ts、mock handlers；monitor 页加来源标签；routes + 权限 `menu:strategy`
- **不改动**：CChan/CBiList/CSegListChan/CZSList/CBSPointList 计算逻辑、bsp_index 表结构、/bsp 页面交互、DuckDB 原始 K 线层
- **依赖**：无新外部依赖；引擎只读 DuckDB（复用 KLineStore 读取）
