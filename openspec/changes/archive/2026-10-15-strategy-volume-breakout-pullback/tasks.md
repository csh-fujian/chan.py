## 1. 引擎基础：MACD 计算与 B 级数据来源

- [x] 1.1 在 `WebAPI/strategy_engines/` 新增 `macd.py`（标准 12/26/9 MACD 柱序列计算，约 30 行纯函数），并用构造序列（已知金叉/绿柱递减形态）直测输出正确性 —— Debug 冒烟脚本或内联断言
- [x] 1.2 在 `WebAPI/strategy_engines/` 新增 `bsp_reader.py`：只读查询 PG bsp_index（code + kl_type + is_buy），无数据时走补算链路（查 DuckDB K 线存在性 → 无则调灌数函数复用 `Data/download_kl.py` 的拉取写入逻辑 → 调 `incremental_engine.recompute_stock` → 回读）；补算失败返回空集（D5 降级）。用 sz.301123 实测：命中既有 30m 一类买点 2025-07-23 15:00；用无数据 code 验证补算链路触发与降级
- [x] 1.3 引擎扫描路径接入 30m K 线读取（DuckDB K_30M 只读，水位门对日线窗口不变），验证 B2/B3 判定可拿到 30m bar 序列

## 2. 引擎判定重写

- [x] 2.1 重写 `_scan_series` 逐日门：破位门（保留）+ 涨幅门（B 确认前日涨幅 > 4% → expired）+ 量能趋势门（A+3 起 3 日均量 > 前 3 日均量 × 1.1 → expired）；删除 D' 缩量终局判定与量能峰 P 锚定。Debug 冒烟脚本构造三个门各自触发/通过的序列验证状态
- [x] 2.2 实现 B1（日线 MACD 绿柱绝对值连续 3 根递减或金叉，严格口径）与 B2（30m 局部低点锚定的两段下跌柱面积背离，间隔 ≥ 8 bar、反弹 ≥ 4 bar）探测，B 事件在窗口内逐日打标；验证 B1 缺席不拦截 B3（独立探测）
- [x] 2.3 实现 B3/B4 探测（bsp_reader 返回的窗口内买点行 → 事件，is_sure 不过滤）与 B（放量突破：收盘 > 窗口此前最高收盘 且 量 ≥ A 日量 × 0.4）；验证突破无量不算 B
- [x] 2.4 终局与换锚：窗口走完 ≥1 B 事件 → triggered（无 B）/ running（有 B）；零 B → expired；回调天数 = 最早 B 事件日 − A 日，< pullback_min_days → expired；B 事件不越窗（窗口末日之后不判定）。用奕东电子 sz.301123 2025-07-08 A 日 + yddz-1 参数（窗口 12 天）验证：B3 @ 2025-07-23 15:00、回调天数 11、state=triggered（B 突破日 07-28 在 12 天窗口外，running 须窗口内出现 B 事件）
- [x] 2.5 B 事件独立绩效：每事件 compute_outcome（基准 = 事件价格）；信号级绩效取最早事件。验证一条多事件信号（如 B3 + B）各绩效独立、信号级 = 最早事件口径
- [x] 2.6 `_default_params`/params_schema 同步：pullback_max_days 13、volume_ratio_min 2.3、**新增 pullback_pct_max(0.04)/volume_trend_ratio(1.1)/breakout_vol_ratio(0.4) 三个可配参数（含白话 desc）**、删 volume_shrink_max；store 层 normalize 旧任务 params 残留的 volume_shrink_max 键静默剔除（编辑旧任务不 422），旧任务缺新三键时 merge 默认值

## 3. 存储层

- [x] 3.1 `strategy_store._ensure_tables` 新增 `strategy_signal_b_event` 表（D1 结构：signal_id/b_level/b_time/b_kl_type/price/day_pct/ret_*/outcome，UNIQUE(signal_id, b_level, b_time)）；按机器追加 `WebAPI/update-win.sql`（本机 Windows）幂等 DDL 记录
- [x] 3.2 信号 upsert 路径扩展：engine 事件 → signal 行 + b_event 行集合写入（幂等：frozen 信号跳过，UNIQUE 冲突更新绩效）；信号行 ret_*/outcome 取最早 B 事件绩效冗余落列
- [x] 3.3 detail API 的 signals_page 行嵌入 b_events 摘要（earliest_b_level/b_count 进 payload，全量 b_event 集合走单信号详情接口返回）；验证 frozen 信号重扫 b_event 不覆盖

## 4. 前端

- [x] 4.1 columns 声明变更（a_col 整合、b_col price_pct + popup 标记、删信号日期列走 BlockSignals 黑名单）；mock 数据对齐（volBreakoutDef params_schema/columns 修漂移 + b_events 生成器）
- [x] 4.2 B 列弹窗组件（el-dialog + el-table：等级/时间/价格/涨幅/独立绩效），30m 事件展示日期+时间、日线只展示日期；旧口径信号（无 b_events）弹窗提示「旧口径信号」
- [x] 4.3 `npm run build`（vue-tsc + vite）通过；`npx vue-tsc -b` 无类型错误

## 5. 端到端验证

- [x] 5.1 重启后端后走真实链路：创建任务（默认参数 13/4/2.3）扫 sz.301123，核对信号行 state/回调天数/B 事件与手工推演一致；任务详情 B 列弹窗展示 2025-07-23 15:00 B3 事件
- [x] 5.2 冒烟：旧任务（params 含 volume_shrink_max）编辑不报 422；旧信号行（payload 无 b_events）详情页不崩（旧口径提示）
- [x] 5.3 `openspec validate strategy-volume-breakout-pullback --strict` 保持通过；spec delta 与实现一致性走查（逐 scenario 对照）

## 6. 2026-10-15 修订（绩效窗口 5/10/15 + kv 删数据不足数 + B 等级 tooltip）

- [x] 6.1 全局绩效口径切换（`WebAPI/strategy_engines/__init__.py`）：`OUTCOME_HORIZONS=(7,14,30)→(5,10,15)`、`OUTCOME_WEIGHTS=(0.5,0.3,0.2)→(0.3,0.5,0.2)`（阈值 0.05 不变）；两策略 columns 声明 close_7d_price→close_5d_price 等三列更名（label 5/10/15日股价）；kv items 删 pending_cnt、avg_ret_7d/14d/30d→avg_ret_5d/10d/15d；`compute_outcome_kv_stats` 聚合键同步。验证：5日权重 30%、10日 50%、15日 20% 加权，> 5% 判成功
- [x] 6.2 引擎与存储字段切换：`vol_breakout.py`/`vp_entry` 引擎 payload 过程字段 close_7d→close_5d 等更名；`strategy_store.py` `_ensure_tables` 幂等加列 strategy_signal.ret_5d/ret_10d/ret_15d 与 strategy_signal_b_event.ret_5d/ret_10d/ret_15d（旧列 ret_7d 等废弃不删）；upsert/查询/get_b_events_for_signals 列名同步；`WebAPI/update-win.sql` 追加幂等 DDL。验证：重扫信号绩效按 5/10/15 落新列（后端三冒烟全绿：outcome 81 / task 113 / vp_entry 46；顺带修 vol_breakout payload 丢 b_open 的回归——B 级分级重构时 _mk_event* 未带 open 键）
- [x] 6.3 前端：B 弹窗等级 Bx 标记加 el-tooltip（触发逻辑白话，文案与 spec 五级规则一致）；绩效列 priceKey/pctKey 对齐新键；BlockKv 渲染随 items 声明自动切换；mock 数据同步（volBreakoutDef columns/kv、genSignals 的 b_events 绩效字段 5/10/15）。验证：`npm run build` 通过
- [x] 6.4 端到端验证：重启后端，重扫既有任务核对绩效列 5/10/15、kv 块无「数据不足数」、B 弹窗等级悬浮出 tooltip；`openspec validate strategy-volume-breakout-pullback --strict` 保持通过
