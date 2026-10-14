# Tasks: strategy-signal-outcome

## 1. 存储与通用绩效计算

- [x] 1.1 update.sql 幂等块：strategy_signal 加列 ret_7d/ret_14d/ret_30d (numeric NULL) + outcome (varchar NULL)，verify: 重复执行不报错、旧行列值为 NULL
- [x] 1.2 `strategy_engines/__init__.py` 加通用 `compute_outcome(entry_idx, entry_price, kl)`（+7/+14/+30 收盘收益、≥2 时段 >8% 判 success、可得 <2 判 pending；顺带产出 close_7d/14d/30d 过程字段），verify: 构造序列断言 success/failed/pending 三态
- [x] 1.3 `strategy_store.upsert_signal` 扩列写入绩效四字段（frozen 保护不变），verify: 冒烟重扫幂等、frozen 行绩效不覆盖

## 2. vol_breakout 冲高豁免 + 涨幅参数 + 绩效

- [x] 2.1 `vol_breakout.py` 缩量判定改量能峰锚定（P = 窗口内最后量 ≥ A 日量 × 0.8 的日，缩量窗口 D' = P+1…window_end；破位/entry_ref 口径不变），verify: 纯函数冒烟构造冲高回落序列断言由 expired 变 triggered；持续放量出货仍 expired
- [x] 2.2 涨幅门槛参数化：`_LIMIT_UP_PCT` 硬编码改 params_schema 参数 a_pct_min（float [0.03, 0.15] 默认 0.05，含 desc），策略名/文案同步（放量启动回调），verify: a_pct_min=0.098 时平安银行信号数与旧口径一致（回归锚点）；默认 5% 时信号数增加
- [x] 2.3 vol_breakout 事件附绩效字段（入场日 = window_end，复用 compute_outcome）与 A/B 点过程字段（payload：a_close/a_pct/b_date/close_7d/14d/30d），verify: 对平安银行真实数据重扫，2024-02-21 信号状态演进 + 绩效与过程字段落库
- [x] 2.4 vol_breakout columns 声明加：A 日（date）/A 日收盘、涨幅（pct）/B 点时间（date）/B 点价格（float）/7/14/30 日收盘（float）与涨跌幅（pct）/成功判定（outcome）列，verify: DEFINITIONS 声明完整

## 3. vp_entry 绩效与过程字段

- [x] 3.1 `vp_entry/engine.py` 信号附绩效（分钟版入场日 = B 日，日线版 = B+1 日，entry_ref 既有买价口径）与 A/B 点过程字段（payload 按缺补齐 a_close/a_pct/b_date/close_*），verify: 冒烟对分钟版/日线版各断言绩效与过程字段落库
- [x] 3.2 vp_entry columns/kv 声明加绩效列与准确率统计项，verify: DEFINITIONS 声明完整

## 4. detail API 与 store 聚合

- [x] 4.1 `query_signals` 加 matched_only 过滤（state IN triggered/running）+ 行透传绩效四字段，verify: SQL 冒烟 expired 行被过滤
- [x] 4.2 detail API：signals_page 数据源改 matched_only；kv 准确率统计（accuracy/success_cnt/failed_cnt/pending_cnt/avg 三时段）进 kv_payload 通用块，verify: 冒烟断言准确率 = success/(success+failed)、pending 不入分母
- [x] 4.3 重跑 Debug/strategy_task_smoke.py 全绿（既有 106 断言回归 + 新增形状断言），verify: 0 失败

## 5. 前端

- [x] 5.1 types + BlockSignals 支持 pct 列型（涨跌百分比、正涨红负跌绿、NULL '--'）与 outcome 列型（success/failed/pending badge），verify: `npm run build` 通过
- [x] 5.2 mock 数据补绩效与 A/B 点过程字段样例（三态各若干）+ kv 准确率项 + 新 columns 声明，verify: mock 模式任务详情匹配信号列表含 A/B 点与绩效列、准确率可见
- [x] 5.3 kv 块文案：8% / 两时段口径注释进 BlockKv 常量（非设置项），verify: build 通过

## 6. 详情列布局精简返工（D12 修订，2026-10-11 用户反馈：列过多难读）

> 1-5 已实施（15/15），本组为对已实施代码的返工对齐：删除首板日/方向/入场参考列、价格+涨幅合并为 price_pct 列、kv 删三个形态统计项。

- [x] 6.1 两策略 columns 声明返工（`WebAPI/strategy_engines/__init__.py`）：删 first_board_date 列；a_close+a_pct / b_close+b_day_pct / close_7d+ret_7d / close_14d+ret_14d / close_30d+ret_30d 五组两列合并为 price_pct 单列（声明 priceKey/pctKey 双 key），verify: DEFINITIONS 两策略无 first_board_date/独立收盘列/独立涨幅列，合并列共 4 类价格列 + outcome
- [x] 6.2 引擎 payload 补 b_open/b_close + B 日当日涨跌幅字段（`vol_breakout.py` 与 `vp_entry/engine.py`：B 日 OHLC 落 payload，b_day_pct = b_close/b_open - 1 由引擎直出），verify: 冒烟断言 triggered 信号 payload 含 b_open/b_close/b_day_pct
- [x] 6.3 BlockSignals 支持 price_pct 列型渲染（价格 | 涨跌幅双值单元格，涨跌正红负绿、数据不足 '--'）+ 模板按 key 黑名单裁剪方向/入场参考价两通用列（columns 声明不动，display 层裁剪），verify: `npm run build` 通过
- [x] 6.4 mock 同步（`Front/src/mock/data/strategy.ts`）：columns 声明改 price_pct 合并列 + 样例数据补 b_open/b_day_pct + **kv 删三个形态统计项**（vol 策略声明 first_board_date_hist/avg_volume_ratio/avg_pullback_days 与 volKvPayload 对应值删除），verify: build 通过 + mock 模式任务详情列数减少、kv 无首板日分布/平均放量倍数/平均回调天数
- [x] 6.5 后端 kv 声明同步删除三项（`WebAPI/strategy_engines/__init__.py` detail_schema kv items 删 first_board_date_hist/avg_volume_ratio/avg_pullback_days），verify: 冒烟断言 detail kv 块无该三键
- [x] 6.6 StrategySignalView/SignalDrawer 兜底渲染分支同步 price_pct（主列表仍全列渲染，仅格式化函数扩展），verify: build 通过
- [x] 6.7 全回归：`Debug/strategy_task_smoke.py` + `Debug/strategy_outcome_smoke.py` + `Debug/vp_entry_engine_smoke.py` + 前端 build 全绿（既有断言中涉及被删列/被删 kv 键的需同步改），verify: 0 失败
- [x] 6.8 B 日重定义（`vol_breakout.py`：`_scan_series` 窗口循环顺带记录最低收盘出现索引 min_close_idx；b_date/入场日/绩效起算改用该索引，payload pullback_days = min_close_idx - i（实际回调天数），entry_ref 数值不变），verify: 冒烟构造低点出现在窗口中段的序列，断言 pullback_days < pullback_max_days 且 ret_7d 从低点日起算
- [x] 6.9 params_schema 白话化 + 前端输入精度（两策略 desc 全部重写为普通用户白话带正反例；params_schema 加可选 precision/step 声明字段，validate_params 对这两个展示元数据键放行；TaskDialog/TaskEditDialog 的 el-input-number 按 precision/step 渲染，缺省按 default 小数位推导——修 a_pct_min 只能拨 0.1 档的缺陷），verify: 后端冒烟 a_pct_min=0.05 校验通过 + 前端 build 通过 + mock 模式任务创建表单 a_pct_min 可输入 0.05

## 7. 成功判定加权求和返工（D13 修订，2026-10-12 用户反馈）

> 6.x 已实施（24/24），本组为口径返工：原「两时段 >8%」判定废弃，改加权求和（7日×50% + 14日×30% + 30日×20%，总收益 > 5%）；三时段齐全才判，任一缺 → pending。外加 outcome 列头 tooltip。

- [x] 7.1 `strategy_engines/__init__.py` compute_outcome 判定分支重写（OUTCOME_THRESHOLD 语义改为总收益阈值 0.05；新增 OUTCOME_WEIGHTS = (0.5, 0.3, 0.2) 常量；三时段任一为 None → pending，不做归一化/按 0 计；返回值结构不变），verify: 构造三序列断言——(+10%,+2%,+9%) 总收益 7.4% → success、(+4%,+2%,-1%) 总收益 2.4% → failed、(+10%,None,-3%) → pending
- [x] 7.2 冒烟脚本同步：`Debug/strategy_outcome_smoke.py` / `vp_entry_engine_smoke.py` / `strategy_task_smoke.py` 旧「两时段」断言按新口径修正（含 (+10%,+1%,+1%) 总收益 5.5% → success 的口径迁移断言），verify: 三个冒烟全绿
- [x] 7.3 前端 tooltip：BlockSignals 的 outcome 列头加 QuestionFilled 悬浮 tooltip（复用 TaskDialog 参数说明图标交互），文案 = 加权求和规则白话；BlockKv 的 SUCCESS_CRITERION 常量改新口径注释，verify: `npm run build` 通过
- [x] 7.4 mock 样例 outcome 值按新口径换算（success/failed 样例重算，三态分布保持），verify: build 通过 + mock 模式成功判定列与悬浮提示可见
- [x] 7.5 全回归：后端三冒烟 + 前端 build 全绿，verify: 0 失败

## 8. 绩效窗口 5/10/15 修订（2026-10-15 用户反馈）

> 8.x 为 2026-10-15 口径修订：绩效窗口 7/14/30 → 5/10/15、权重 50/30/20 → 30/50/20（阈值 5% 不变）、kv 块删数据不足数。实现统一由 strategy-volume-breakout-pullback 变更的 tasks 6.x 落地（该变更同步 apply），本组任务为其验收锚点。

- [x] 8.1 OUTCOME_HORIZONS=(5,10,15)、OUTCOME_WEIGHTS=(0.3,0.5,0.2)（`WebAPI/strategy_engines/__init__.py`），verify: 构造 (+10%,+2%,+9%) 总收益 10%×30%+2%×50%+9%×20%=5.8% → success、(+4%,+2%,-1%) 总收益 2.0% → failed、(+10%,None,+9%) → pending
- [x] 8.2 绩效列与 kv 键切换：strategy_signal 与 strategy_signal_b_event 幂等加列 ret_5d/ret_10d/ret_15d（旧列废弃不删）、payload close_5d/close_10d/close_15d、两策略 columns/kv items（删 pending_cnt、avg_ret_5d/10d/15d）与前端渲染/mock 同步，verify: 重扫任务绩效按 5/10/15 落库、kv 无数据不足数、build 通过
