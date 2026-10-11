# Proposal: vp-entry-strategy-integration

## Why

volume-price-entry-rule 变更已交付一套完整且经回测验证的量价三段式买点判定内核（`Debug/vp_entry/`，V3 规则：蓄势期 → A 日放量启动 → 调整期缩量回踩 → B 日分钟级触发），但它只活在回测工作台里，无法被策略任务体系消费——用户不能像放量首板策略那样为它建任务、跑范围扫描、看进度与差异化详情。需要把该判定内核注册为策略引擎，接入 strategy-task-redesign 落地的任务模型。

## What Changes

- **判定内核迁移**：`Debug/vp_entry/` 的判定内核（signal_rule / minute_trigger / vp_volume / params）迁至 `WebAPI/strategy_engines/vp_entry/`；Debug 侧 backtest / sensitivity / run_backtest 改从新位置 import，回测功能零损失（entry-backtest capability 不改动）
- **新策略引擎 `VpEntryEngine`**：实现现有 `StrategyEngine` 协议（scan / scan_with_params），读 DuckDB 全史日线逐日喂入 `VPStateMachine`；B 日候选懒加载分钟数据（`K_5M` 有则分钟版触发 + F(t) 虚拟量，无则日线退化版），每次扫全史重算 + 唯一键 upsert 幂等（复用 vol_breakout 引擎模式与水位门语义）
- **B 日后状态追踪（引擎适配层新增）**：信号产生后按后续日 K 推进状态——`triggered`（B 日触发）→ `running`（close 上破 B 日最高价）/ `expired`（close 跌破止损参考低点）→ 无演进保持；已 frozen 信号不被覆盖（沿用既有 upsert 约束）。entry_ref_price = 买价（分钟版触发分钟收盘 / 日线版 B+1 开盘），stop_ref_price = stop_loss_low
- **注册策略定义 `vp_entry`**：states 四态（triggered/running/expired，加说明性空态）、columns 私有列（A日/P日/触发日、entry_mode 分钟/日线、spring 标记、drift 桶、放量比等 SignalEvent 基底特征）、detail_schema（summary / per_stock / signals / kv-基底特征统计）
- **params_schema 通用扩展：新增 `enum` 参数类型**（`{key,label,type:'enum',options:[{value,label}],default,desc}`）——后端 `validate_params` 类型校验 + 前端 TaskDialog 渲染 el-select；这是声明体系的通用能力增强（本策略的 vol_gate 需要，未来任何带口径开关的策略复用）
- **参数取值域放开**：5 个可扫描参数在任务侧声明连续区间（cv7_max 0.15~0.35 / box_width_max 0.08~0.18 / n_max 4~10 / stop_loss 0.05~0.15 / vol_gate enum mean|strict），默认值取定死版取值；离散敏感性集合约束保留在回测侧（sensitivity.py），适配层组装参数绕开 `VPParams` 的离散校验（连续区间组装）
- signal_date 用 B 日；唯一键 (task_id, code, B日) 语义成立（同股同日只一条 VP 信号）
- **不整合** entry-backtest capability（回测/敏感性归后续 strategy-optimization 变更领地）；不改动缠论计算内核、bsp_index、DuckDB 原始 K 线层

## Capabilities

### New Capabilities

- `vp-entry-strategy`: 量价三段式买点作为策略引擎接入任务体系的契约——VpEntryEngine 扫描行为（日线退化版兜底、B 日分钟级触发优先）、B 日后状态追踪状态机（triggered→running/expired）、vp_entry 策略定义声明（states/columns/detail_schema/params）、信号字段映射（signal_date=B 日、买价/止损参考价口径）

### Modified Capabilities

- `strategy-signal`: 策略定义注册表的 params_schema 声明新增 enum 类型（options 枚举集校验，前后端声明驱动渲染扩展）——注册表声明能力的类型体系扩展

## Impact

- **后端**：`WebAPI/strategy_engines/vp_entry/`（判定内核迁入 + 新引擎适配层）、`strategy_engines/__init__.py`（vp_entry 定义注册 + validate_params enum 支持）、`strategy_store.py`（params 校验路径透传 enum）、scheduler 无改动（引擎协议已兼容）
- **迁移**：`Debug/vp_entry/` 判定内核四文件移位，backtest/sensitivity/run_backtest/test_vp_entry 的 import 路径更新；`Data/` 与 DuckDB 数据不动
- **前端**：`Front/src` types（params_schema enum 类型）、TaskDialog（el-select 渲染 enum 参数）、mock（vp_entry 定义 + 枚举参数样例）——detail_blocks / 任务页零改动（声明驱动）
- **不改动**：entry-backtest capability、CChan 计算内核、bsp_index、monitor 联动（strategy 来源回查走既有 task_id 路径，新策略自动接入）
- **依赖**：无新外部依赖；引擎只读 DuckDB（复用 KLineStore，分钟数据读 K_5M 表）
