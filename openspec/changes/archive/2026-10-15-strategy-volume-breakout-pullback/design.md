# Design: strategy-volume-breakout-pullback

## Context

现状：`VolBreakoutPullbackEngine`（WebAPI/strategy_engines/vol_breakout.py）纯量价逻辑——A 日识别、D' 缩量终局判定、B 日 = 窗口最低收盘日。本变更为 B 点引入五级确认（B1/B2/B3/B4/B）与 B 级事件独立绩效，其中 B3/B4 需消费缠论买点结论（PG bsp_index）、B2 需 30 分钟 MACD、B1 需日线 MACD——引擎从「纯日线量价」扩展为「日线 + 30 分钟 + 缠论结论消费」的复合判定。引擎协议的「不触碰缠论内核」约束随之放宽（spec delta 已定）。参见 proposal.md 的动机与实例验证（奕东电子 2025-07：B3 = 07-23 15:00 一类买点实测命中）。

现有基础设施（可直接复用）：

- `incremental_engine.recompute_stock(code, period, autype)`：单只 (code, kl_type) 缠论补算 + 整套替换落 PG（bsp_index/chan_structure/chan_snapshot/recompute_cursor）
- `Data/download_kl.py` 的灌数逻辑（BaoStock 拉取 → 校验 → 幂等写 DuckDB，带「已是最新不请求」水位短路）
- `bsp_index` 表：`(code, kl_type, autype, bsp_date, bsp_type, is_buy, price, time_key, is_sure, ladder)`，已有 30m/D 买点数据
- `strategy_signal` 表：唯一键 `(task_id, code, signal_date)`，frozen 冻结语义，行级绩效四字段
- `compute_outcome(entry_idx, entry_price, kl)`：绩效通用函数（5/10/15 + 加权判定 30%/50%/20%，2026-10-15 修订），引擎内复用即可

## Goals / Non-Goals

**Goals**：
- B 点分级判定的引擎实现（五级独立探测、窗口内逐日门、终局零 B 淘汰）
- B 级事件的持久化结构（多事件 × 独立绩效）与信号幂等演进
- 引擎消费缠论买点的间接链路（PG 只读 → 按需灌数 → 触发 recompute_stock → 回读）
- 前端 B 列弹窗 + A/B 列整合 + 删信号日期列
- 新默认参数（13/4/2.3）与 params_schema/columns 声明同步

**Non-Goals**：
- 不改 CChan/CBiList/CSegListChan/CZSList/CBSPointList 任何计算逻辑（缠论计算全部经增量续算引擎）
- 不做 B 级事件的全量回填/历史迁移（旧信号保持旧口径，见 Migration）
- 不做 30 分钟数据的批量补灌（用户自行补数；引擎只保证单只按需补算链路正确）
- 不改 strategy-signal 调度/水位框架（引擎接口 scan/scan_with_params 签名不变）

## Decisions

### D1：B 级事件用独立表 `strategy_signal_b_event`，不用 payload JSON

**选择：新表**。结构（`_ensure_tables` 惰性 DDL）：

```
strategy_signal_b_event
  id            serial PK
  signal_id     integer NOT NULL      -- FK → strategy_signal.id
  b_level       varchar(8) NOT NULL   -- 'B1'/'B2'/'B3'/'B4'/'B'
  b_time        varchar(19) NOT NULL  -- 'YYYY-MM-DD HH:MM:SS'（30m 判定带时间，日线判定 'YYYY-MM-DD 00:00:00'）
  b_kl_type     varchar(8) NOT NULL   -- 'D'（B1/B4）/ '30m'（B2/B3）/ 'D'（B，日线突破日）
  price         double precision      -- B 事件价格（日线=收盘；30m=该 bar 收盘）
  day_pct       double precision      -- 事件日涨幅（日线收盘/开盘-1；30m 为 bar 涨幅）
  ret_5d/ret_10d/ret_15d  double precision  -- 该事件独立绩效（compute_outcome 口径；2026-10-15 修订：原 ret_7d/14d/30d 列废弃不删，新列幂等加列，历史行不迁移、重扫自然覆盖）
  outcome       varchar(8)            -- success/failed/pending
  created_at    timestamptz DEFAULT now()
  UNIQUE (signal_id, b_level, b_time)
```

**理由**：B 事件是「一信号多行 + 独立绩效四字段」的第一级实体，与 strategy_signal 行级绩效四字段同构——JSON 塞 payload 会导致弹窗查询要解析 JSON、绩效统计要 jsonb 函数遍历，且每事件四绩效字段在 JSON 里无法建索引/直查。信号列表页只取「最早 B 事件」（一次 `MIN(b_time)` 或 `ORDER BY b_time LIMIT 1` 索引扫），弹窗按 signal_id 查全部。**备选（否决）**：payload JSON `b_events: [...]`——写入简单但查询/统计/演进覆盖全要应用层遍历，且 frozen 语义要单独实现。

**信号级绩效口径**：strategy_signal.ret_* 取最早 B 事件的独立绩效（信号行冗余存一份，kv 统计/列表列直接读信号行，不打到 b_event 表）。

### D2：引擎内嵌 MACD 计算（B1/B2），不引 CChan 依赖

B1（日线）与 B2（30m）只需 MACD 柱序列。**选择：在 strategy_engines 包内新增 `macd.py`**，实现标准 MACD（12/26/9 EMA，输出柱值序列）——参照 `ChanAnalyse/Math/MACD.py` 的纯计算语义但独立成文件（约 30 行）。**理由**：引擎协议禁止 import CChan 模块（含 ChanAnalyse.Math——它属于 ChanAnalyse 包）；`ChanAnalyse.Math.MACD.CMACD` 虽无依赖，但 import 路径上仍是 ChanAnalyse 包成员，为保持「引擎不 import CChan 任何模块」的字面干净，内嵌实现。**备选（否决）**：`from ChanAnalyse.Math.MACD import CMACD`——省 30 行但破协议字面。

B2 的「两笔同向下跌 + 柱面积背离」判定：不引入笔结构计算（那是 CChan 的活），用简化锚定——30m 收盘序列上，在回调窗口内识别两个局部低点（相邻低点间隔 ≥ 8 根 30m bar 且其间存在 ≥ 4 根 bar 的反弹），分别计算两段下跌区间的 MACD 绿柱面积和（负柱绝对值累加），第二段价格创新低而面积 < 第一段面积 → 背离，背离确认日（第二段低点日）记 B2。这是「柱面积背离」的可执行化，非笔级严格背驰——严格笔结构需 CChan，属于 Non-Goal。

### D3：缠论买点消费链路（B3/B4）——只读 PG + 按需补算，进程内调用

```
引擎扫描 code（日线窗口确定后）
  |
  v
查 PG bsp_index (code, '30m'/'D', is_buy=TRUE)
  |-- 命中且覆盖窗口时间范围 --> 直接用
  |-- 无数据/为空 -->
  |     查 DuckDB kline (code, K_30M/K_DAY)
  |       |-- 无 --> 调灌数函数（复用 Data/download_kl.py 的拉取+写入逻辑，
  |       |          函数级复用，不 subprocess）
  |     调 incremental_engine.recompute_stock(code, '30m'/'D', autype='QFQ')
  |       （recompute 内部 ST 过滤/无数据返回 None——引擎按「无缠论数据」
  |         降级处理，见 D5）
  v
窗口时间范围内的 bsp_index 买点行 --> B3/B4 事件
```

**进程内直调而非 HTTP/CLI**：引擎与 incremental_engine 同属 WebAPI 包，直接函数调用零网络开销；recompute_stock 是幂等的整套替换，并发安全由 PG 事务保证。**备选（否决）**：走 HTTP 调自身的 /recompute 接口——多一层网络与鉴权，无收益。

**量级控制**：补算只在「PG 无该 (code, period) 数据」时触发一次（有行即不触发——哪怕行集不含窗口内买点，说明缠论已算过该股，无买点是真的无买点）；全量任务首扫会集中触发大量补算，每只 30m 全历史缠论计算约数秒——**全量范围任务首扫耗时显著上升，可接受**（用户已知 30m 覆盖目前仅 3 只，补算是一次性成本）。

### D4：B 事件时间口径与窗口判定对齐

- B1/B4（日线）：b_time = 日线交易日 `YYYY-MM-DD 00:00:00`，判定日 = 窗口内某交易日
- B2/B3（30m）：b_time = 30m bar 时间戳 `YYYY-MM-DD HH:MM:SS`，判定范围 = 窗口首交易日 00:00 至 窗口末交易日 23:59（含当日全部 30m bar——窗口末日的尾盘 bar 仍属窗口内）
- B（日线突破）：b_time = 突破日 `YYYY-MM-DD 00:00:00`
- 回调天数（最早 B 事件日 − A 日）按**交易日**计：30m 事件折算到所属交易日，与 A 日做交易日差
- 窗口内 B3 买点要求 `is_buy=TRUE`（bsp_index 已有方向列）；is_sure 不作过滤（未确认买点也是买点，回顾性判定下信号重扫会自然演进）

### D5：数据缺失处理语义（补算链路为强语义）

用户已明确：PG bsp_index 查不到该 (code, 周期) 数据时，**必须**走「调 K 线数据接口获取数据 → 缠论计算 → 入库 → 回读」的补算链路（D3），这是数据准备的既定流程，不是可选项。降级**仅在链路本身失败时**发生：

- 灌数接口调用失败（BaoStock 限频/网络不可达）或 recompute_stock 失败（PG 不可用、ST 股跳过、计算异常）：该 code 的 B2/B3（或 B4）**本次扫描记为不可判**（不打标、不报错、不淘汰信号），B1/B4/B 仍可独立使信号成立
- 下次扫描（水位前移）时补算链路**再次尝试**——失败是暂态的，数据补齐后 B2/B3 自动补标
- 调度日志按 code 记录补算失败原因，供用户排查（哪些股票的 30m 数据没补上）

**理由**：缺数据 ≠ 形态无效（五级独立探测语义）；链路失败属于基础设施暂态故障，淘汰信号会把「数据没到」与「形态不好」混为一谈。**备选（否决）**：链路失败判 expired 或直接报错终止任务——前者误杀，后者让全量任务因单只股票的接口故障而整体失败。

### D6：状态机映射与旧字段清理

```
旧                          新
watching          -->   watching（窗口未走完，不变）
triggered(缩量+未破位) --> triggered（窗口走完，有 B1~B4，无 B）
running(突破高点)  -->   running（窗口内出现 B 事件——放量突破）
expired(破位/缩量不足) --> expired（破位门/涨幅门/量能趋势门/零B/回调天数不足）
payload.b_date 等单值字段 --> 废弃，b_event 表行替代
payload.pullback_days     --> 换锚（最早 B 事件日 − A 日）
volume_shrink_max 参数    --> 从 params_schema 删除（D' 缩量判定废弃）
```

**payload 保留字段**：a_date/a_close/a_pct/volume_ratio/first_board_date（历史列消费兼容）；新增 `earliest_b_level`（最早事件等级，列表 B 列快速渲染用）与 `b_count`（事件总数）。5/10/15 日股价过程字段（close_5d 等）按信号级绩效口径保留（2026-10-15 修订：原 close_7d/14d/30d 键随绩效窗口切换更名）。

### D7：前端展示（B 列弹窗 + A/B 列整合）

- **columns 声明**：`a_date`/`a_price` 两列合并为 `a_col`（price_pct 列型含日期）；新增 `b_col`（price_pct 列型 + 新列型标记 `popup: 'b_events'`，值取 payload.earliest B 事件）；删「信号日期」由 BlockSignals display 层黑名单裁剪（通用列，与「方向/入场参考价」同机制）
- **B 列弹窗**：BlockSignals 新增弹窗组件（el-dialog + el-table），行数据 = detail API 返回的 b_events 数组（该信号的 b_event 表行集合，随 signals_page 每行嵌入——列表页 20 行 × 平均 2~4 事件，嵌入 payload 体积可控）
- **B 等级悬浮 tooltip**（2026-10-15 修订）：弹窗表格等级列的 Bx 标记加 el-tooltip，内容为该级触发逻辑白话（B1 = 日线 MACD 柱绿柱连续 3 根缩短或金叉；B2 = 30 分钟 MACD 柱面积底背离；B3 = 30 分钟缠论任意等级买点；B4 = 日线缠论任意等级买点；B = 放量突破回调期高点），文案与 spec「B 点分级判定」五级规则一致
- **kv 块**（2026-10-15 修订）：删「数据不足数」(pending_cnt) 统计项（两策略一致）；平均收益项随绩效窗口改为 5/10/15 日（avg_ret_5d/avg_ret_10d/avg_ret_15d）
- **绩效列**（2026-10-15 修订）：columns 声明 close_7d_price/close_14d_price/close_30d_price → close_5d_price/close_10d_price/close_15d_price（label 5/10/15日股价，priceKey/pctKey 同步指向新 payload 键）
- **30m 事件时间展示**：b_time 含非零时间部分时展示完整 `YYYY-MM-DD HH:MM`，零时间（日线）只展示日期
- **mock 同步**（front/src/mock/data/strategy.ts）：volBreakoutDef 的 params_schema/columns/kv items 与后端对齐（修既有漂移 pullback_days→pullback_max_days 等），mock 信号生成器产出 b_events 数组（B 事件绩效字段随窗口 5/10/15 更名）

### D8：默认参数与 schema 变更

params_schema：`pullback_max_days` default 5→**13**、`volume_ratio_min` default 2.0→**2.3**、`pullback_min_days` default 4（不变，语义换锚）；**删除** `volume_shrink_max**（D' 缩量判定废弃）。引擎 `_default_params()` 同步。旧任务 params 里的 `volume_shrink_max` 键：validate_params 未知键报错——**旧任务编辑时需剔除该键**（patchTask 路径在引擎 merge 前过滤已删除参数键，normalize 时静默丢弃，不报 422）。

**三个阈值参数化（用户要求全部做参数设置）**，加入 params_schema：

```
pullback_pct_max    涨幅门阈值     float  default 0.04   min 0.02  max 0.10  precision 2 step 0.01
volume_trend_ratio  量能趋势门倍数 float  default 1.1    min 1.05  max 2.0   precision 2 step 0.05
breakout_vol_ratio  突破量比       float  default 0.4    min 0.2   max 1.0   precision 1 step 0.1
```

三个参数进 `_default_params()` 与引擎判定；desc 按白话口径写（调高/调低后果与正反例）。旧任务 params 无这三键时 merge 默认值（与 a_pct_min 先例同机制）。

## Risks / Trade-offs

- **[全量任务首扫触发大量 30m 补算 → 单次任务执行时间从分钟级升到小时级]** → 补算结果幂等落 PG，一次性成本；调度方日志按 code 输出补算耗时，可观测；用户已知数据覆盖现状（仅 3 只有 30m 数据）
- **[B2 简化背离判定（非笔级严格背驰）与缠论教材口径有偏差]** → spec 已声明口径（两笔同向下跌以局部低点锚定）；若实测误报多，后续可在 spec 层调锚定参数，不影响架构
- **[旧信号与新口径不可比（B 日/回调天数/绩效全部换锚）]** → 不迁移；任务详情按 params_version 区分新旧信号；旧信号 payload 无 b_events 时 B 列弹窗显示「旧口径信号（无 B 事件明细）」
- **[信号列表页 20 行嵌 b_events 数组的 payload 体积膨胀]** → 事件字段精简（等级/时间/价格/绩效四元组）；弹窗数据按需在 detail API 返回，主列表 signals_page 不嵌（D7 修正：主列表只嵌 earliest 摘要，弹窗数据走 signal 详情接口）——见 tasks 拆分
- **[recompute_stock 依赖 PG 可用与灌数接口外呼（BaoStock 限频）]** → 补算失败按 D5 降级（B2/B3 不可判，不阻塞扫描）；限频由灌数函数既有的「已是最新不请求」短路与重试逻辑兜底

## Migration Plan

1. 引擎重写 + b_event 表惰性 DDL 上线（`_ensure_tables` 自动建表，update-*.sql 记录 DDL 追加）
2. params_schema 默认值变更发布（新任务 13/4/2.3；validate_params 对 volume_shrink_max 未知键的处理：注册表已删该键，旧任务 params 残留键在 store 层 normalize 时静默剔除）
3. 旧任务不强制重扫：用户手动「重新运行」时按新口径产出（resume full 清空重扫，天然切新口径）；正在 watching 的旧任务下次增量扫描按新引擎逻辑演进（B 列从零打标）
4. 前端 columns 声明驱动的列变更随定义发布自动生效；mock 数据同步对齐
5. 回滚：引擎与 schema 变更同 commit 回滚即可；b_event 表无破坏性写入（只增不改 signal 旧字段），回滚后表留存无副作用

## Open Questions

（无——探索阶段已全部定案：B 等级语义、独立探测、绩效 gamma 方案、窗口边界、参数去留、数据降级策略、时间口径。）
