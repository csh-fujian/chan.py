# Design: volume-price-entry-rule

## Context

规则量化定义见 specs/（entry-signal-rule 的 V3 公式为唯一判定依据，此处不复述公式）。本设计的约束环境：

- 仓库既有数据设施：`Data/kl_store.duckdb`（`kline` 表，主键 `(code, kl_type, autype, time_key)`，kl_type 存枚举 name 字符串），`ChanAnalyse/DataAPI/KLineStore.py` 幂等写入，`Data/download_kl.py` 灌数模式，`ChanAnalyse/DataAPI/MinuteAPI.py` 的 akshare 东财分钟接口。
- 仓库红线：不改 `CChan`/`CBiList`/`CSegListChan`/`CZSList`/`CBSPointList` 计算逻辑。本变更纯量价代数，天然不触碰。
- 参照先例：仓库无 pytest，`Debug/*_test*.py` 冒烟测试即测试载体；回测脚本类工具落在 `Debug/` 或 `Data/` 风格的独立脚本。

## Goals / Non-Goals

**Goals:**

- 可执行 V3 规则的信号判定内核，日线筛门 + 分钟触发两层
- 回测产出分组绩效报表 + 敏感性扫描 + 基准对照
- 灌一次数、本地任意次重跑的数据管道

**Non-Goals:**

- 不做实盘监控/盘中轮询（将来复用判定内核另立变更）
- 不做 Web 前端页面/API（绩效报表以 CSV/Markdown 落地即可）
- 不做缠论结合（不调用 CChan；与买卖点/区间套的关系留给将来）
- 不做 F(t) 混合估计（回测期逐股精确；实盘期再评估）

## Decisions

### D1 落点与模块形态：`Debug/vp_entry/` 独立目录

新建 `Debug/vp_entry/` 包，含 `signal_rule.py`（判定内核）、`backtest.py`（回测引擎）、`vp_volume.py`（虚拟量 F(t)/VP）、`run_backtest.py`（CLI 入口）+ `Debug/test_vp_entry.py`（冒烟测试，内存构造 K 线，风格对齐 `bi_test.py`）。

- 为什么不放 `ChanAnalyse/`：判定内核不依赖缠论计算，放核心库会模糊「不改计算逻辑」的边界。
- 为什么不放 `Data/`：灌数脚本与判定逻辑分离，Data/ 保持纯数据操作。
- 备选「放 WebAPI/」被否：本变更无后端交付物。

### D2 判定内核：流式状态机，与回测引擎解耦

状态机每喂一根日 K 线做 O(1) 状态更新：`IDLE → BASEMENT(蓄势期累积) → TRIGGERED_A(等待调整) → PULLBACK(峰P已锚定, 等B) → SIGNAL(B日触发) / DEAD`。判定内核只输出信号事件（含全部标签：spring、基底桶、drift、wick、盒时长），不涉及买价撮合与绩效计算——撮合与离场归 `backtest.py`。

- 理由：内核将来可被实盘监控直接复用（每日收盘喂一根日 K、候选股喂分钟流），回测只是它的第一个消费者。
- 备选「整体窗口回看式扫描」被否：向量化一次性扫描对回测更快，但会造出两套判定语义（回测一套、实盘一套），漂移风险大于收益。折衷：日线候选筛门（粗筛）用 SQL 向量化做，通过粗筛的候选再走状态机精判，两段共享同一份常量参数表。

### D3 日线筛门下推 DuckDB SQL

MA60V/CV7/区间盒/10 日新高全部用 DuckDB 窗口函数（`AVG(...) OVER`、`STDDEV_SAMP`、`MAX OVER ROWS BETWEEN`）在库内算完，只把通过粗筛的候选 (code, A日) 列表返回 Python。分钟触发与精判只对候选执行。

- 理由：400 万行在库内聚合比载入 pandas 快且省内存；粗筛漏斗（预计过滤至 <1% 行）使后续 Python 侧负载可忽略。
- 注意：DuckDB 的 `STDDEV_SAMP` 与 numpy `std`（默认 ddof=0）自由度不同——CV7 必须统一用 ddof=1 口径（SQL 侧天然 ddof=1，Python 侧显式传 ddof=1），否则两段判定不一致。这是一处容易踩的静默偏差点，冒烟测试要覆盖「SQL 粗筛与状态机精判对同一只股票给出相同候选集」。

### D4 分钟数据管道：候选股惰性灌入（源：BaoStock 5 分钟）

复用 `KLineStore` 幂等写入，新增 `K_5M` 灌取路径（`Data/download_kl.py` 增加 `--kl-type K_5M` 支持，**BaoStock 5 分钟源**，走 `CBaoStock` 同款 `query_history_k_data_plus(frequency='5')` 设施）。回测引擎首次遇到无分钟数据的候选股时触发灌入，之后全本地。**实测数据源依据（见 `Debug/vp_entry/data_availability.md`）**：东财分钟接口默认深度仅 31 个交易日且传 start_date 拉历史会触发限流封锁，BaoStock 5 分钟数据自 2020-01-02 起近 7 年完整可得（单股 78,624 根、秒级）——分钟版回测时间窗由此扩至 2020 年起。更早的样本自动落日线退化版（spec 已定义）。

- BaoStock 分钟 bar 时间戳从 09:35 起（每 bar 标记区间终点），「已开市 ≥ 15 分钟」观察窗与分钟放量窗口以 09:35 为第 1 根计数。
- 停牌日、bar 数不足的异常交易日，灌入时经 `IngestUtil` 校验路径剔除/标记。
- F(t) 剔除口径见 spec（停牌/缺数据日不入样本）。
- 批量灌数串行 + 间隔执行，避免触发数据源限流。

### D5 撮合假设与成本口径

- 分钟版买价 = 触发分钟收盘价，按成交额/成交量折算 VWAP 不可得时不追（5 分钟 bar 收盘价已含滑点缓冲）。
- 不计佣金印花税（A 股双边约 0.1%）——首版绩效含交易成本的口径留作报表开关，默认关。理由：先看毛超额是否存在；若无毛超额，成本口径无意义。
- T+1 约束：买入当日不可卖，止损触发统一次日开盘执行（spec 已定义当日尾盘判定规则）。

### D6 报表产物：CSV + Markdown 落 `Debug/vp_entry/reports/`

绩效主表、分组表（spring/基底桶/分钟vs日线/量能门版本）、敏感性曲线数据、基准对照分布，全部 CSV；人类可读汇总一份 Markdown。不做图（matplotlib 图留给将来需要时加，避免首版把时间花在可视化上）。

## Risks / Trade-offs

- [风险] 东财分钟接口限速/历史深度不足，分钟版样本可能过少 → 先跑数据可得性探测（tasks 第 1 项），样本 < 50 时以日线退化版为主口径出结论并明示局限
- [风险] CV7 的 SQL/Python 自由度口径静默不一致 → D3 的对齐冒烟测试硬性覆盖
- [风险] 参数扫描 108 组合产生多重比较假阳性 → 基准对照 95% 置信区间标注 + 悬崖参数标记双保险（spec 已定），报表头部明示「显著性未做族错误率校正」
- [风险] 信号稀疏（预估全市场一年几十~几百个）导致统计功效弱 → 分组维度报告效应量而非仅 p 值式叙述；结论措辞按「证据强度」分级
- [取舍] 不做实盘监控接入意味着将来需要一次小适配（喂数方式从批量改增量）→ 状态机流式设计（D2）已预留，适配成本可控

## Open Questions

（无——悬而未决的口径均已在 specs 中定死；执行期发现的细节问题按「先测量后设门」原则记入报表，不回改 spec。）
