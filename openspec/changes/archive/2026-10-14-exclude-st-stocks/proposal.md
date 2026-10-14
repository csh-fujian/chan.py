## Why

ST / *ST 股票按需求不进行分析。目前只有 `App/ashare_bsp_scanner_gui.py` 在扫描器里按名称剔除了 ST（`名称` 包含 `ST`），Web 后端的股票查询、元数据抓取、K 线灌数、盘中轮询与策略/买卖点计算仍然覆盖 ST 股票，白白消耗网络请求、灌数与计算资源。

## What Changes

统一规则：**股票名称以 `ST` 或 `*ST` 开头（大小写不敏感）即视为 ST 股票**，名称取自 `stock.name`（交易所身份域同步得到）。ST 判定为查询时派生，不新增存储列。

- **股票查询**：`GET /api/stocks`（`stock_store.list_stocks` 及其 DuckDB 兜底 `_fallback_list_stocks`）不再返回 ST 股票。Web 前端 MSW mock（`Front/src/mock/handlers/stock.ts`）同步对齐，使 mock 与真实后端契约一致。
- **股票数据获取（元数据）**：身份域（`identity`）仍对全市场执行，以便识别新名称与 ST 状态的进入/退出；profile / industry / snapshot / financial / holders 等逐股域的目标池排除 ST 股票。ST 股票摘牌或摘帽后，下一轮身份同步会使其自动回到/移出池子。
- **K 线数据获取**：灌数配置生成（`Data/gen_stock_list.py`）、`GET /api/stocks/export-config`、盘中轮询配置（`Data/intraday_poll.py` 使用的配置）均不包含 ST 股票，不再新拉取其 K 线。
- **分析计算**：
  - `GET /api/klines` 对 ST 股票直接返回 404（detail 注明「已排除：ST 股票」），不再计算缠论结构。**BREAKING**：前端对 ST 代码的 K 线请求会失败。
  - 策略扫描枚举（`strategy_engines/scheduler.py:list_all_codes`）与买卖点补算（`incremental_engine.catch_up` 的 code 来源）排除 ST 股票。
- **已存量数据**：DuckDB `kline` 表与 PG 中已有的 ST 行 **不删除**（非破坏性），只是停止新增与分析。用户显式加入的列表（自选、监控、买卖点等）不做读侧过滤，存量 ST 行保持可见，打开图表时由 K 线接口返回 404 并注明已排除；策略信号历史保留（见 design D7）。

明确不改动：
- `CChan` / `CBiList` / `CSegListChan` / `CZSList` / `CBSPointList` 计算逻辑（CLAUDE.md 约定）。
- `stock.enabled` 语义：ST 不通过置 `enabled=false` 实现，避免与人工启停、摘牌禁用语义混淆。
- 数据库结构：不新增列、不新增表，因此无需追加 `WebAPI/update.sql`。

## Capabilities

### New Capabilities
- `st-stock-exclusion`: ST / *ST 股票的判定规则，以及该规则在股票查询、元数据抓取、K 线灌数、K 线计算与策略/买卖点扫描各入口的排除行为。

### Modified Capabilities
- 无。现有主规范（`kline-persistence`、`stock-profile`、`kline-watchlist`、`ai-qa`）的需求条目不变；排除规则以独立能力的新增需求描述，各入口的实现细节在 design 中落实。
- 注意：`stock-metadata-sync`（进行中，尚未归档）的目标池调度需求与本变更相交。在其归档前，本变更不修改其 delta；归档后若 pool 规则冲突，需在该变更中同步。

## Impact

- **后端（WebAPI/）**：`stock_store.py`（list_stocks / _fallback_list_stocks / list_pool_codes 等）、`routers/stocks.py`（export-config）、`meta_sync.py`（pool_codes / due_domains）、`main.py`（/api/klines）、`strategy_engines/scheduler.py`（list_all_codes）、`incremental_engine.py`（catch_up 的 code 来源）。
- **数据脚本（Data/）**：`gen_stock_list.py`（生成灌数配置时剔除 ST）、`intraday_poll.py` 的配置来源；`download_kl.py` 本身不改，只消费已过滤的配置。
- **前端（Front/）**：仅 MSW mock 的 `/api/stocks` 搜索过滤；真实 API 层 `src/api/modules/stock.ts` 不变。mock 数据当前不含 ST 股票，前端展示无可见变化。
- **GUI 扫描器（App/）**：已有 ST 剔除逻辑，规则统一为前缀匹配属于可选对齐项，不影响主流程。
- **API 契约**：`/api/stocks` 结果集、`/api/klines` 对 ST 代码的返回、`/api/stocks/export-config` 返回集合均变化。
- **依赖 / 数据**：不新增依赖；DuckDB 与 PG 存量数据保持不变。
