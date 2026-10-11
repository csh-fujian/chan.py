# Design: strategy-signal-outcome

## Context

strategy-task-redesign（任务模型 + detail_schema 积木块）与 vp-entry-strategy-integration（enum 参数 + vp_entry 引擎）均已实施完成待归档。用户定义了信号绩效口径：匹配信号（有入场参考价的 triggered/running）按入场日 +7/+14/+30 日收益（基准 = entry_ref_price）判成功（**加权求和：7日×50% + 14日×30% + 30日×20%，总收益 > 5%；2026-10-12 修订，原「≥2 个时段正且 >8%」口径废弃**），任务详情只展示匹配信号 + 绩效列 + 准确率。同时 vol_breakout_pullback 需补冲高豁免（量能峰锚定，对齐 vp_entry 语义）。

## Goals / Non-Goals

**Goals:**
- 绩效字段为**策略引擎通用能力**（vol_breakout 与 vp_entry 都落）
- 任务详情 signals 块只展示匹配信号 + 绩效列 + 准确率 kv，且采用精简列布局（D12：合并单元格 price_pct 列型，删冗余列）
- vol_breakout 缩量判定改量能峰锚定（冲高豁免）
- 存量旧信号无绩效字段的兼容展示

**Non-Goals:**
- 不做参数寻优/反馈学习（strategy-optimization 变更）
- 不做动态出场（止损/止盈持有）口径——v1 固定 7/14/30 日窗口
- 不改 vp_entry 的状态追踪逻辑（只加绩效计算）
- 信号列表页（/signals 独立页）不加绩效列（proposal 已划出）

## Decisions

### D1. 绩效字段存 payload 还是独立列？

**独立列**。strategy_signal 加 `ret_7d / ret_14d / ret_30d (numeric, NULL) + outcome (varchar: 'success'/'failed'/'pending')`：

- kv 准确率统计要 `COUNT(*) FILTER (WHERE outcome=...)` + AVG——走列一条 SQL；走 payload 是全行拉回内存解析 JSONB
- signals 块排序/筛选（按成功率、按收益率）将来是自然诉求，payload key 无法索引
- 备选（payload 内嵌）被否决：读取路径每次解析，且「绩效」是跨策略通用语义而非策略私有字段，放 payload 语义错位

DDL 走 update.sql 幂等块（numeric NULL + varchar NULL，无约束）。

### D2. 匹配态集合如何声明？

**strategy_signal 行级判定，不新增声明字段**：detail API 侧 `state IN (triggered, running)` 过滤（状态值是两策略共同的匹配态命名）。不引入 params_schema 式的 matched_states 声明——当前两策略匹配态恰好同名（triggered/running），引入声明是为尚未存在的第三种命名习惯买单；若未来策略匹配态命名分叉，届时再提声明（向后兼容加法）。

> 取舍记录：这是「通用性换简单性」的决定。两策略 states 已用同名值，硬编码 `('triggered','running')` 常量在 store 层一处即可。

### D3. 绩效计算位置——引擎内 vs 落库后统一回填

**引擎内计算，随信号事件一起落库**：

- 引擎本就读该 code 全史日线（重算窗口与未来 30 日天然同源同价），入场日索引现成——零额外查询
- 备选（落库后 store 层按 signal_date 反查 DuckDB 回填）被否决：每信号一次查询、双数据源口径风险、frozen 判定复杂化
- 计算规则（两引擎共用，放 strategy_engines/__init__.py 或 util）：
  ```
  compute_outcome(entry_day_idx, entry_price, kl):
      rets = [kl[i+d].close/entry_price - 1 for d in (7,14,30) if i+d < n]
      # 判定改为加权求和（2026-10-12 修订，D13）：
      total = ret_7d*0.5 + ret_14d*0.3 + ret_30d*0.2
      outcome = 'success' if total > 0.05 else 'failed'
                （三时段不全 → 'pending'，数据不足——不得用归一化权重或按 0 计入）
  ```
- 加权权重（50%/30%/20%）与 5% 阈值为全策略统一口径（spec 定死），不做参数
- **顺带产出过程字段**（D10 消费）：close_7d/close_14d/close_30d、b_date——同一循环里现成

### D4. 入场日口径（各引擎自定义，绩效共用）

| 引擎 | 入场日 | 依据 |
|------|--------|------|
| vol_breakout | **窗口内最低收盘价出现日（回踩低点日，2026-10-11 修订：原为窗口结束日）** | entry_ref = 窗口最低收盘，B 日/入场日/买价三者同源同日；回调天数 = B 日 − A 日（实际值） |
| vp_entry 分钟版 | B 日 | 买价 = 触发分钟收盘价，当日即成交 |
| vp_entry 日线版 | B+1 日 | 买价 = B+1 开盘价，成交日在 B+1 |

> 修订动机：原口径下 B 日恒等于 A 日 + pullback_max_days，「回调天数」列恒等于参数值，无信息量；改低点日后 B 日随形态变化，绩效起算与买价同日。

### D5. upsert 与 frozen 语义扩展

`upsert_signal` 的 ON CONFLICT 更新列**加入 ret_7d/14d/30d + outcome**，但 WHERE frozen = FALSE 保护不变（frozen 行整体不覆盖——绩效与 state 同生共死）。**pending → 终态的推进**依赖引擎全史重算：水位门只挡「无新 K」的 code，有新 K 时全量重算会重放该信号并给出新绩效，幂等覆盖（frozen 除外）。

存量任务：旧行无绩效列值（NULL/'pending'），详情显示 '--'；用户可对任务 full 重扫（清信号重算）补全，或保持旧行不动——不强制迁移。

### D6. detail API 变化

- signals_page 数据源加 `state IN ('triggered','running')` 过滤（store query_signals 加参数 matched_only）
- 行结构透传 ret_7d/ret_14d/ret_30d/outcome
- kv 块新增通用统计（两策略 kv 都加）：准确率（success/(success+failed)）、成功数/失败数/待定数、平均三时段收益
- summary 块 matched 语义不变（matched 本来就是匹配信号计数）

### D7. 前端渲染

- BlockSignals 绩效列：**columns 声明扩展类型 `pct`**（涨跌百分比，正涨红负跌绿，NULL→'--'）与 `outcome`（badge：success 绿/failed 红/pending 灰）——声明驱动，两策略 columns 各自声明绩效列
- ~~**7/14/30 日价格列**：columns 现有 `float` 类型即可承载~~（D12 修订：价格+涨幅合并为 `price_pct` 列型单列展示，不再「价格列 + 相邻 pct 列」两列拆分）
- BlockKv：kv_payload 键（accuracy/success_cnt/failed_cnt/pending_cnt/avg_ret_7d/14/30d）由定义 kv items 声明，值由 detail API 聚合
- mock 同步：strategy.ts mock 数据补绩效字段样例（含 success/failed/pending 三态）
- 阈值口径在 UI 常量注释里说明（D13 加权求和规则），不做设置项
- **「成功判定」列头提示图标（D13）**：BlockSignals 的 outcome 列头加 QuestionFilled 悬浮 tooltip，内容为加权求和规则文案（与 spec 场景一致）；复用 TaskDialog 参数说明图标的既有交互模式
- **任务详情通用列裁剪（D12 修订，display 层取舍）**：BlockSignals 渲染任务详情时方向列与入场参考价列固定不渲染（量价策略信号恒为买方向；入场参考价与 B 日股价的价格分量同源重复）。**columns 声明不动**——策略信号页主列表（StrategySignalView）仍按完整声明渲染全部通用列，裁剪只发生在 BlockSignals 的模板层（按 key 黑名单跳过），避免两套 columns 声明分叉

### D10. A/B 点过程字段（payload，不做列）

任务详情信号列表要展示 **A 日时间/收盘价/涨幅、B 点时间/收盘价/当日涨跌幅、7/14/30 日收盘价与涨跌幅**。这些是**策略私有过程字段，走 payload**（引擎已有 first_board_date 等先例），不进独立列：

- 独立列留给「跨策略通用语义」（绩效四字段 + 将来的排序/筛选诉求）；A/B 点命名是量价策略私有词汇
- 展示层零成本：BlockSignals 的 columns 声明 `{key: 'a_close', type: 'price_pct'}` 直接从 row.payload 取值渲染（现有私有列机制本就走 payload）
- vol_breakout payload 增补：a_date（=signal_date，冗余免取）、a_close、a_pct（A 日涨幅）、**b_open/b_close（B 日开盘/收盘价，B 日当日涨跌幅 = b_close/b_open - 1 的数据源）**、b_date（窗口结束日）、close_7d/close_14d/close_30d（入场日后 7/14/30 日收盘价，越界为 null）
- vp_entry payload 增补：a_close、a_pct、**b_open/b_close**（分钟版 B 日/日线版 B+1，分钟版取日线对齐日 OHLC）、b_date（分钟版 B 日/日线版 B+1）、close_7d/14d/30d（B 点已有 b_bar_time/a_ret 等部分字段，按缺补齐）
- **b_date 是绩效回算的副产物**（compute_outcome 需要入场日索引），零额外计算
- 展示层消费（D12）：列声明以合并列（price_pct）直接消费 payload 的价格/涨幅两个字段（见 D12）

### D11. 涨幅门槛参数化（a_pct_min）

- vol_breakout 引擎 `_LIMIT_UP_PCT = 0.098` 硬编码改为 params_schema 参数 `a_pct_min`（float，[0.03, 0.15]，默认 0.05）
- 语义变化：A 日从「近似涨停首板」放宽为「放量启动日」——与 vp_entry 的 A 日口径（≥5%）对齐；策略显示名与 desc 文案同步改（「放量首板回调」→「放量启动回调」，group 不变）
- **存量任务兼容**：旧任务 params 无 a_pct_min 键 → 引擎 `merged = {**default, **params}` 落到默认 0.05，行为变化（原 9.8%）。spec 是 source of truth，旧行为不保留；需要首板口径的用户显式配 9.8%
- 冒烟：a_pct_min=0.098 时平安银行信号集与旧口径一致（回归锚点）

### D8. vol_breakout 冲高豁免（量能峰锚定）

- 缩量判定窗口从「i+1 … window_end」改为「P+1 … window_end」，P = 窗口内最后一个量 ≥ A 日量 × 0.8 的日（若全窗口无放量日则 P = A 日）
- **entry_ref（D' 最低收盘）与破位判定（全窗口收盘 < A 日开盘 → expired）不变**——只豁免缩量，不豁免破位
- 0.8 锚定阈值定死（对齐 vp_entry「0.8×V_A 锚定阈值定死」先例），volume_shrink_max 仍是可配参数
- **无新参数**（不加热高豁免天数参数）：vp_entry 语义即「P = 最后放量日」，冲高只要在 P 之前一律豁免，比「前 2 日」更通用
- 风险：存量 vol_breakout 任务的信号集会变化（原来 expired 的部分会变 triggered）——full 重扫后自然演进，旧 expired 行无法被 upsert 复判（upsert 只覆盖已有键，不删行）。**delete-then-insert 不做**：full 重跑（resume rerun=full）已清信号表，用户重跑即净
- 引擎纯函数冒烟：构造冲高回落 K 线序列断言 triggered

### D9. vp_entry 绩效计算

- 分钟版：入场日 = B 日，entry_ref = 触发分钟收盘价（买价）→ ret 按 B+7/B+14/B+30 日线收盘算
- 日线版：入场日 = B+1 日，entry_ref = B+1 开盘价
- 复用 D3 的 compute_outcome；B 日索引在重放状态时已有（D3 追踪逻辑同一段循环）

### D12. 列合并渲染（price_pct 列型）与详情列精简（2026-10-11 修订）

任务详情信号列表列过多难读，列布局收紧为「合并单元格」模式：

- **columns 声明新增类型 `price_pct`**：单列渲染「价格 | 涨跌幅」双值（如 `9.81 | +6.2%`）。价格分量取列 key 的 `*_close`/`*_price` 类字段，涨幅分量取配套 `a_pct/ret_*/` 涨幅字段——列声明为 `{key: 'a_price', label: 'A日股价', type: 'price_pct', priceKey: 'a_close', pctKey: 'a_pct'}`（双 key 显式声明，渲染层零猜测）
- 合并后的四列（替代原 8 列）：**A日股价**（a_close | a_pct）、**B日股价**（b_close | B 日当日涨跌幅）、**7/14/30日股价**（close_* | ret_*，涨幅相对入场参考价）
- **B 日股价的涨幅分量 = B 日当日涨跌（收盘/开盘 - 1）**，非相对入场参考价——用户选定口径；引擎 payload 补 b_open/b_close（D10），渲染层算 `b_close/b_open - 1`（或引擎直出 b_day_pct，见 tasks 返工任务）
- 涨幅分量沿用 pct 渲染规则：正涨红、负跌绿、数据不足 '--'
- **删列**：first_board_date（与 a_date 重复）；方向、入场参考价两通用列按 D7 的 BlockSignals 模板黑名单裁剪
- **kv 精简（用户追加）**：vol_breakout detail_schema kv items 删 first_board_date_hist / avg_volume_ratio / avg_pullback_days 三个形态统计项（首板日分布、平均放量倍数、平均回调天数）——策略摘要聚焦绩效准确率统计，形态统计不再展示；Front mock 的对应声明与 volKvPayload 值同步删除
- 影响面：两策略 columns 声明返工（8 列 → 4 合并列）、BlockSignals 渲染分支、mock 数据、StrategySignalView/SignalDrawer 兜底分支同步
- **B 日重定义（用户追加，2026-10-11）**：B 日从「窗口结束日」改为「窗口内最低收盘价出现日」（实际回踩低点日）——回调天数 = B 日 − A 日为实际值；绩效起算跟随 B 日（D4 已同步）；engine 记录最低收盘出现索引 `min_close_idx`（现循环只记价格，需顺带记索引）。已入库旧信号按旧口径冻结，full 重扫后自然换新
- **params_schema 白话化 + 前端输入精度（用户追加，2026-10-11）**：
  - 所有参数 desc 重写为普通用户可读的白话（调高/调低后果 + 正反例），删除「首板口径」「量价规则口径」等演化历史术语
  - **前端 float 输入精度缺陷**：TaskDialog 对 float 参数硬编码 `precision=1/step=0.1`，导致 a_pct_min（default 0.05，范围 [0.03,0.15]）被舍入为 0.1 且只能拨 0.1 档——修法：params_schema 声明加可选 `precision`/`step` 字段（缺省按 default 小数位推导，如 0.05 → precision 2/step 0.01），TaskDialog/TaskEditDialog 按声明渲染（后端 validate_params 未知键需放行这两个展示元数据键，同 desc 先例）

### D13. 成功判定改加权求和口径（2026-10-12 用户修订）

原「两时段 >8%」口径废弃，改**加权求和**：

- **总收益 = ret_7d × 0.5 + ret_14d × 0.3 + ret_30d × 0.2；总收益 > 0.05 → success，否则 failed**
- 「为正收益」条件被 >5% 阈值包含（>5% 必为正），不再单列
- **三时段齐全才判**（用户选定）：任一时段越界未来 → pending，不入准确率分母——不做权重归一化（隐式假设）、不按 0 计入（悲观假设），口径无隐式语义
- 落点：compute_outcome 判定分支重写（OUTCOME_THRESHOLD 语义改为总收益阈值 0.05；新增 OUTCOME_WEIGHTS = (0.5, 0.3, 0.2) 常量）+ BlockKv SUCCESS_CRITERION 常量 + BlockSignals outcome 列头 tooltip 文案
- **行为影响**：同一组 ret 三态判定会迁移（如 +10%/+1%/+1% 旧「两时段 >8%」判 failed、新加权总收益 5.5% 判 success）——这正是用户目的（更平滑的强度度量，短时段权重高贴合「快涨即离场」操作习惯）
- 存量已判定信号不迁移：full 重扫自然换新（同 D11/D12 先例）；kv 准确率统计读 outcome 列，无需改聚合逻辑

## Risks / Trade-offs

- [口径加权/5% 阈值是拍板值，用户可能想调] → spec 定死；调权重/阈值属于 strategy-optimization 的参数寻优范围，届时再开
- [pending 信号的准确率分母排除可能让早期任务准确率样本很少] → kv 同时给 success/failed/pending 三个计数，用户可见样本量
- [vol_breakout 语义变化导致存量任务信号集口径漂移] → 不做数据迁移，full 重扫即净；旧任务不动则旧行为保留
- [7/14/30 日越界（近月信号）pending 占比高] → 详情 '--' + pending 计数透出，用户可区分「没数据」与「失败」
- [加权口径下「三时段齐全才判」使 pending 期从 14 日延至 30 日] → 近月信号判定延后，但避免归一化/按 0 计的隐式偏移（用户选定）

## Migration Plan

1. 归档 strategy-task-redesign 与 vp-entry-strategy-integration（前置：本变更 MODIFIED requirement 基于二者归档后的主树版本）
2. DDL：strategy_signal 加 4 列（update.sql 幂等块）
3. compute_outcome 通用函数 + vol_breakout 量能峰改造 + vp_entry 绩效 → 引擎冒烟
4. store：upsert 扩列 + query_signals matched_only + kv 准确率聚合 → PG 冒烟
5. detail API 过滤/透传 + 前端 pct/outcome 列型 + mock → build 通过
6. 回滚：DDL 列可 NULL 无约束（不破坏旧行）；引擎/前端改动按文件回退
