## Why

放量启动回调策略的 B 点当前是「回调窗口内最低收盘价出现日」——纯统计锚点，不含企稳/反转确认，作为买入决策依据先天不足（用户实测：奕东电子 2025-07-08 A 日，引擎 B 日 07-16/07-23，而实际可判定的买点 07-23 30 分钟缠论一类买点、07-25 量能枯竭企稳、07-28 放量反转确认均未利用）。本变更把 B 点重构为**分级确认型买点**（B1~B4 + B），用 MACD 多头转换、30 分钟 MACD 底背离、缠论买点（读 PG bsp_index）等独立判据分级打标，使 B 点真正成为可操作的买入参考。

## What Changes

- **B 点分级判定（核心重构）**：B 点不再是窗口最低收盘日，改为五条独立规则在回调窗口内打标：
  - B1 = 日线 MACD 转多头（绿柱绝对值连续 3 根递减，或柱值由负转正）
  - B2 = 30 分钟 MACD 柱面积底背离（严格口径：需窗口内两笔同向下跌，价创新低、下跌笔柱面积和不创新低）
  - B3 = 30 分钟缠论任意等级买点（读 PG bsp_index）
  - B4 = 日线缠论任意等级买点（读 PG bsp_index）
  - B = 放量突破回调期高点（收盘 > 窗口最高收盘 且 当日量 ≥ A 日量 × breakout_vol_ratio，可配参数，默认 0.4）
  - 五条规则**独立探测、互不前置**；等级标签仅表达确认强度（B1 < B2 < B3 < B4 < B）
- **回调窗口逐日门重构**：原「D' 缩量终局判定」废弃，改为三道逐日门（任一触发 → expired）：
  - 破位门（保留）：窗口内任一日收盘 < A 日开盘
  - 涨幅门（新增）：B1~B 尚无任何确认时，任一日收盘涨幅 > pullback_pct_max（可配参数，默认 4%）
  - 量能趋势门（新增）：A+3 日起，3 日均量 > 前 3 日均量 × volume_trend_ratio（可配参数，默认 1.1，允许小幅抖动，连续放量抬升淘汰）
- **终局判定重构**：窗口走完时，≥1 个 B 级事件 → 信号成立（triggered/running）；零 B 事件 → expired（当前区间策略无效）。窗口内未走完前保持 watching。
- **B 级事件独立绩效**：每个 B 事件独立计算 5/10/15 日收益 + 成功判定（方案 gamma），信号列表 B 列点击弹窗分级展示各 B 事件详情；信号级绩效仍按最早 B 事件起算。
- **回调天数换锚**：统计量锚点改为「最早 B 级事件日 − A 日」；`pullback_min_days` 过滤语义同步换锚（最早 B 事件距 A 日 < 下限 → expired），所有 B 级事件必须落在窗口内。
- **引擎数据来源扩展**：引擎读缠论买点时先读 PG bsp_index（只读）；该 (code, kl_type) 无数据时，检查 DuckDB K 线存在性 → 无则调灌数接口补全 → 调缠论增量补算（incremental_engine.recompute_stock）落 PG → 再读 bsp_index。**BREAKING**：strategy-signal 能力「不触碰缠论内核」requirement 的约束由「引擎不读写 bsp_index」放宽为「引擎只读 bsp_index、按需触发补算，不直接 import CChan 计算模块」。
- **信号列表展示变更**：A 日列整合为 `[日期 | 价格 | 涨幅]` 单列（删「信号日期」列，与 A 日冲突）；B 日列同构封装 `[时间 | 价格 | 涨幅]`，B 级事件来自 30 分钟判定的展示「日期+时间」，B 列可点击弹出多 B 事件详情表格。
- **参数默认值调整**：回调天数上限 pullback_max_days 5→13、启动放量倍数下限 volume_ratio_min 2.0→2.3（回调天数下限 pullback_min_days 保持 4，换锚后保留）；**新增三个可配参数**：涨幅门阈值 pullback_pct_max（默认 0.04）、量能趋势门倍数 volume_trend_ratio（默认 1.1）、突破量比 breakout_vol_ratio（默认 0.4）。
- **2026-10-15 修订**（全局绩效口径联动 strategy-signal-outcome）：绩效窗口 7/14/30 → **5/10/15 日**（全局统一，含 vp_entry）；成功判定权重调整为 **5日×30% + 10日×50% + 15日×20%**（阈值 > 5% 不变）；策略摘要（kv 块）删除「数据不足数」统计项（两策略一致）；B 日弹窗等级 Bx 悬浮 tooltip 展示该级触发逻辑（文案取 B 点分级判定规则）。

## Capabilities

### New Capabilities

（无——本变更不引入全新能力域，全部在既有能力上做 requirement 级修改。）

### Modified Capabilities

- `vol-breakout-pullback`：重写「回调窗口量能判定与冲高豁免」requirement（量能趋势门 + 涨幅门取代 D' 缩量终局判定）；新增「B 点分级判定」requirement（B1~B4+B 五级独立探测、窗口边界、回调天数换锚）；修改「信号字段口径」requirement（B 事件独立绩效、payload 结构、A/B 列整合、删信号日期列）；修改「放量首板识别」requirement（默认参数调整 2.3/13）。
- `strategy-signal`：修改「策略引擎统一接口与调度」requirement——「不触碰缠论内核」场景的约束放宽（引擎 SHALL 只读 PG bsp_index + 按需触发缠论补算，SHALL NOT 直接 import CChan 计算模块运行缠论计算）。

## Impact

- **引擎**：`WebAPI/strategy_engines/vol_breakout.py`（判定主体重写：逐日门、B 级探测、独立绩效）、`__init__.py`（params_schema 默认值、columns 声明变更）、新增 MACD/背离计算依赖（B1/B2 需 30m 与日线 MACD——可内嵌纯计算实现，无 CChan 依赖）。
- **数据链路**：引擎新增 PG bsp_index 只读查询 + DuckDB K 线存在性检查 + 按需调 `WebAPI/incremental_engine.recompute_stock`（触发灌数调 `Data/download_kl.py` 逻辑或复用其函数）。
- **存储**：B 级事件落库（多事件 × 独立绩效，倾向新表 `strategy_signal_b_event`，结构在 design.md 定）；`strategy_signal` 表 payload 结构变化（b_date/b_close 等旧字段让位 B 事件集合）。
- **前端**：`Front/` 策略信号页信号列表（A/B 整合列渲染、B 列弹窗、删信号日期列）、`front/src/mock/data/strategy.ts`（mock 定义与参数漂移需同步对齐）；B 列弹窗等级 Bx 悬浮 tooltip 展示触发逻辑（2026-10-15 修订）。
- **兼容性**：旧任务重扫后 B 日/回调天数/绩效口径全部变化（不可比）；旧信号行 payload 缺 B 事件集合，详情页需容错（展示为「旧口径信号」或触发重扫）。
