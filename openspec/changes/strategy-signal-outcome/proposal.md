# Proposal: strategy-signal-outcome

## Why

用户在任务详情中无法判断策略质量：信号状态（triggered/running/expired）只描述**形态判定**的终局，不回答「匹配信号买入后到底赚不赚钱」。用户已明确定义成功口径（2026-10-12 修订为加权求和）：**入场日后 7/14/30 日收益率按 50%/30%/20% 加权求和，总收益 > 5% 判成功，否则失败**（三时段齐全才判，数据不足为 pending）；要求任务详情只展示匹配信号（triggered/running），列出三时段涨跌幅与成功/失败判定，并在 kv 统计中给出准确率。

同时用户确认 vol_breakout_pullback（放量首板回调）需补齐一条既有缺口：首板后前 1-2 日放量冲高（直接冲高回落形态）不应计入缩量判定——该因子在 volume-price-entry-rule 中已定义（量能峰 P 锚定、缩量窗口从 P+1 起算），vol_breakout 未实现，导致 2024-02-21 这类信号被误杀。

## What Changes

1. **vol_breakout_pullback 冲高豁免**：回调窗口内放量冲高（直接冲高回落形态）不计入缩量判定——缩量判定窗口从「量能峰 P」（窗口内最后一个放量日）之后起算（对齐 vp_entry 的量能峰锚定语义），窗口其余条件（破位判定等）不变。
2. **vol_breakout_pullback 涨幅门槛参数化**：A 日涨幅门槛由硬编码 9.8%（近似涨停首板）改为可配参数 a_pct_min（默认 5%，对齐用户量价规则的涨幅口径；配置 9.8% 可还原近似首板语义）。
3. **信号绩效（outcome）通用能力**：引擎扫描时对每条匹配信号（state ∈ triggered/running）计算入场日后 +7/+14/+30 日收益率（买入基准价 = entry_ref_price，起算日 = 回调窗口低点日/vp_entry 的 B 日），按**加权求和**（7日×50% + 14日×30% + 30日×20%，总收益 > 5% 判成功；三时段不齐为数据不足）判定成功/失败，随信号落库（新增 ret_7d/ret_14d/ret_30d/outcome 字段，frozen 信号保持幂等不覆盖）。
4. **detail 信号列表只展示匹配信号与过程字段**：signals 块数据源过滤 state ∈ triggered/running（expired 不展示在任务详情）；列表新增：**A 日时间/收盘价/涨幅、B 点（买入点）时间/价格、7/14/30 日收盘价与涨跌幅（正涨红负跌绿）**、成功/失败判定。
5. **kv 块准确率统计**：detail API 聚合该任务匹配信号的 outcome 分布（准确率 = 成功数/匹配数、成功数/失败数、平均三时段收益），kv 块透出。
6. **前端 columns 类型体系**：涨跌幅列、价格列、日期列与成功/失败列由 columns 声明驱动渲染（新增百分比与成功/失败 badge 列型，向后兼容加法）。

## Capabilities

### MODIFIED: strategy-signal
- 信号状态语义澄清：匹配信号 = triggered/running（有入场参考价的信号）；expired 是策略放弃，不构成买入
- 信号行新增绩效字段（三时段收益率 + 成功判定）
- 任务详情信号列表只展示匹配信号 + A/B 点过程字段与绩效列
- kv 统计新增准确率

### ADDED: vol-breakout-pullback（引擎级成文）
- vol_breakout_pullback 判定规则首次 spec 级成文：A 日识别（涨幅门槛可配默认 5%）、量能峰锚定缩量判定（冲高豁免）、破位淘汰、状态演进、A/B 点字段口径与绩效起算
- （此前该策略仅以引擎近似实现存在，9.8% 硬编码近似首板，无 spec 成文）

## Impact

- **引擎**（WebAPI/strategy_engines/vol_breakout.py、vp_entry/engine.py）：扫描期计算绩效（需要窗口结束日后的未来 K 线——引擎本就读全史，天然可得）；vol_breakout 缩量逻辑修改 + 涨幅门槛参数化
- **参数 schema**：vol_breakout 新增 a_pct_min 参数（float，默认 5%）
- **存储**（WebAPI/strategy_store.py）：strategy_signal 加绩效独立列（DDL，design D1 决策）+ A/B 点过程字段随 payload
- **detail API**（WebAPI/routers/strategy.py）：signals 数据源过滤 + 绩效/过程字段透传 + kv 聚合
- **前端**（Front/src/views/strategy/detail_blocks/）：BlockSignals 绩效/过程列渲染、BlockKv 准确率项、mock 同步
- **不改**：CChan 计算内核、strategy_task 任务模型、scheduler 执行器、水位/幂等语义
- **风险**：已 frozen 的存量信号不含绩效字段（旧任务详情显示 '--'，与新任务并存）；vol_breakout 口径变化（冲高豁免 + 涨幅门槛默认 5%）会导致重扫后信号集变化——full 重跑即净，不做存量迁移

## Out of Scope

- 参数寻优/反馈学习（strategy-optimization 变更，已规划）
- vp_entry 的 B 日后状态追踪逻辑变化（仅新增绩效计算，状态机不动）
- 信号列表页（/signals 独立页）的绩效列——仅任务详情内展示
- 持有到止损/止盈的动态出场口径（v1 固定 7/14/30 日窗口）
