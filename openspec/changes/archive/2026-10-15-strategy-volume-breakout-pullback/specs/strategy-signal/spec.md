## Purpose

放宽策略引擎与缠论计算内核的隔离约束：vol_breakout_pullback 的 B3/B4 判定需要消费缠论买点结论，引擎 SHALL 通过「只读 PG bsp_index + 按需触发增量补算」的间接链路获取，SHALL NOT 直接 import 缠论计算内核。本 delta 基于 strategy-signal-outcome 变更后的口径。

## MODIFIED Requirements

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
