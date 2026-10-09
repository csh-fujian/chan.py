## Context

- 股票名称来源：`stock.name`（PostgreSQL），由身份域同步（`WebAPI/meta_sync.py` `_sync_identity`，数据来自交易所名单）写入；`import_stocks`（`stock_store.py` ~L1227）也会写 name。
- 股票清单的主要消费者：`stock_store.list_stocks`（`GET /api/stocks`）、`stock_store.list_pool_codes`（元数据调度的目标池）、`routers/stocks.py` 的 `/export-config`、`main.py` 的 `GET /api/klines`（经 `chan_service.get_serialized_chan` → `custom:DuckDBAPI.CDuckDB`，只读 DuckDB，不依赖 PG）、`strategy_engines/scheduler.py`（`list_all_codes` / `scan_instance`）、`incremental_engine.py`（`list_stale_keys` / `catch_up` / `recompute_stock`）。
- 灌数侧：`Data/gen_stock_list.py` 直接从 BaoStock `query_all_stock` 拿到 `code_name`，生成 `Data/ingest_config.all_stocks.json`；`Data/ingest_config.minute.json` 为仓库内手工/外部维护的配置（`Script/sync_kl.sh` 消费），仓库中无生成器。
- 现有 `stock_store._fallback_list_stocks` 与 `export-config` 的 DuckDB 兜底只有代码、没有名称（name 被回填为 code），无法判定 ST。
- 计算侧 `CChan` 与其子模块不改动（CLAUDE.md 约定）；所有排除都发生在"选哪些代码进入计算"的入口。
- 见 proposal.md 的 Why / What Changes；行为契约见 specs/st-stock-exclusion/spec.md。

## Goals / Non-Goals

**Goals:**
- 一条判定规则（名称前缀 `ST` / `*ST`，大小写不敏感，去首尾空白）覆盖所有入口，判定函数与 SQL 谓词语义一致。
- 在"选代码"的单一汇聚点过滤，而不是在每个调用方分别判断，减少漏网。
- 身份域保持全市场同步，确保 ST 进入/退出可被识别。

**Non-Goals:**
- 不新增 `stock.is_st` 列或 `update.sql` DDL（名称派生即可，ST 状态是名称的函数，无需缓存）。
- 不删除存量 K 线 / 股票数据；不通过 `enabled=false` 表达 ST。
- 不改 `CChan` 计算逻辑。
- 不改 `App/ashare_bsp_scanner_gui.py`（已有 `contains('ST')` 剔除，行为更严，保持不动；统一为前缀规则作为后续可选项）。
- 不处理 `S*ST`、`SST` 等历史/退市风险类名称（需求只点名 ST 与 *ST）。

## Decisions

**D1 判定规则与谓词**
- Python：`stock_store.is_st_name(name)` = `re.match(r"^\*?ST", (name or "").strip(), re.IGNORECASE)`。
- SQL（PG）：`UPPER(TRIM(COALESCE(s.name, ''))) NOT LIKE 'ST%' AND UPPER(TRIM(COALESCE(s.name, ''))) NOT LIKE '*ST%'`，以常量 `ST_EXCLUDE_SQL` 形式在 `stock_store.py` 集中定义，别名 `s` 通过参数化或固定别名约定使用。
- 必须 `COALESCE`：`name` 为 NULL 时 `NOT LIKE` 结果为 NULL，会把无名股票误排除。规则定义为"无名不算 ST"（spec 中 "名称缺失" 场景）。
- 替代方案：`name_py` 或 `name` 上的 generated column / 新列。否决：需要 DDL 与回填，且判定是名称的纯函数，查询时派生成本可忽略（stock 表规模 ~5000 行）。

**D2 股票查询（`/api/stocks`）**
- `list_stocks` 的 `conditions` 始终追加 `ST_EXCLUDE_SQL`，COUNT 与 SELECT 共用同一 where，保证 total 与分页一致。
- `_fallback_list_stocks`（PG 不可用）：无法判定名称，改为抛出 `StockNameSourceUnavailable`，由路由映射为 503。理由：返回未过滤列表违反规则；兜底列表的 name 本就是 code，不可用于展示"名称"。替代方案：兜底仍返回代码列表。否决：静默违规。
- 前端 MSW mock `Front/src/mock/handlers/stock.ts` 的 `/api/stocks` 同样追加 `!/^\*?ST/i.test(s.name.trim())`，与真实契约一致。mock 数据当前无 ST，展示无变化。

**D3 元数据目标池（`meta_sync.py`）**
- `stock_store.list_pool_codes(enabled, exclude_st=False)` 新增参数；默认 False 保持调用方兼容。
- `_SyncCtx.pool_codes`（L724-728）接收 `exclude_st`；`due_domains`（L1419）对非 identity 域传 `exclude_st=True`；identity 域保持 `enabled=None, exclude_st=False`。
- `_sync_identity` 的 `candidates`（L824）保持全集，确保 ST 股票仍被身份同步更新名称。
- 已在池中的 ST 股票：其既有 profile/snapshot 等行保留（不删），仅不再刷新。

**D4 K 线灌数配置**
- `gen_stock_list.query_all_a_share` 返回后，用 `is_st_name(code_name)` 过滤（与 `is_a_share_stock` 同层，在 `main` 中 `stocks` 构造处），生成的 `ingest_config.all_stocks.json` 不含 ST。`--include-st` 不提供（需求不允许分析 ST）。
- `GET /api/stocks/export-config`：PG 路径 SQL 追加 `ST_EXCLUDE_SQL`；DuckDB 兜底路径无名称 → 503（同 D2）。
- `ingest_config.minute.json`：仓库无生成器，选择在消费端过滤——`Data/intraday_poll.py` 在加载配置后，用 `--pg-dsn` 查询名称，剔除 ST 代码并打印剔除清单；PG 不可达则退出并报错（与 D2 失败关闭一致）。替代方案：一次性改写 JSON 文件。否决：下一次外部重新生成会回退，且无法自动跟随摘帽/戴帽。
- `download_kl.py` 不改，只消费已过滤配置。注意：`download_kl` 的 `--config` 路径目前不做名称过滤，所以所有 ST 排除必须在生成/导出侧完成，这是有意的单一来源。

**D5 K 线分析接口（`GET /api/klines`）**
- 在 `main.get_klines` 调用 `_compute_chan` 之前检查：`stock_store.get_stock_name(symbol)` → 若 `is_st_name` 则 `HTTPException(404, detail="已排除：ST 股票")`。
- PG 不可达时：放行并记录 warning（而非 503）。理由：`/api/klines` 当前完全不依赖 PG（纯 DuckDB 计算 + 进程内缓存），让它因 PG 故障失败会引入新的运行时依赖。风险与缓解见下。
- 缓存：ST 请求在检查阶段即返回，不写入 `get_chan_cache()`，也不读取缓存。
- 404 vs 空结构：选择 404，因为 ST 不是"没有数据"，前端需要明确区分；空结构会被前端当作"无缠论结构"渲染，掩盖排除。

**D6 策略扫描与买卖点补算——在 choke point 过滤**
- `scheduler.scan_instance`：在 `codes` 解析之后（无论来自 `list_all_codes` 还是调用方显式传入）调用 `stock_store.exclude_st_codes(codes)`，显式传入的 ST 代码同样被剔除。`exclude_st_codes` 查询 `SELECT code, name FROM stock WHERE code = ANY(%s)`，无名或不在 stock 表的代码保留（与"名称缺失"规则一致）。
- `scheduler.list_all_codes`：DuckDB 枚举后同样经 `exclude_st_codes`。PG 不可达时现有 `except` 返回 `[]`，即失败关闭，且 `scan_instance` 本身依赖 PG 的 `get_scan_cursors`，无额外副作用。
- `incremental_engine.list_stale_keys`：结果列表按 `exclude_st_codes` 过滤（先过滤再 `limit`，保证 limit 语义是"有效键数"）。
- `incremental_engine.recompute_stock`：入口处再次判定（ST 直接返回 None 并 log.info）。理由：`recompute_stock` 也被 `POST /api/bsp/catch-up` 的单只路径与 CLI 间接调用，在最低层兜底避免漏网。代价：每次调用多一次 PG 点查，可接受（补算本身远重于此）。
- 需在实施中核对 `WebAPI/routers/bsp.py` 与 `routers/strategy.py` 是否还有直接调用 `recompute_stock` / `scan_instance` 的路径，并确认它们都经过上述 choke point。

**D7 存量数据与列表型读侧**
- 存量 DuckDB K 线与 PG 股票行保留（非破坏性；删除不可逆且 DuckDB 9.2GB 单文件不宜做大删改）。
- 用户自选（watchlist）、监控（monitor）、买卖点列表等"用户已显式加入"的集合：**不做读侧过滤**。理由：这些是用户的显式选择，静默隐藏会让用户困惑；ST 在这些页面点击进入图表时会收到 D5 的 404 + "已排除：ST 股票"，行为可解释。替代方案：列表层过滤存量 ST 行。否决：与 D5 的"显式可见的拒绝"不一致，且需要逐一覆盖 `get_stocks_with_daily_close` 等多个调用方。
- 策略信号表（`strategy_signal`）中的历史 ST 信号：保留，不新增。

## Risks / Trade-offs

- [PG 不可达时 `/api/klines` 放行 ST 分析] → 记录 warning；该路径纯计算、无外部写入，代价仅为多算少量 ST 股票。若后续需要严格排除，可改为 503，单点改动。
- [名称口径滞后：ST 状态在交易所名单中变化到身份同步执行之间存在时间差] → 身份域每日同步；时间差内 ST 股票仍可能被分析一个周期，属于可接受的最终一致。
- [BaoStock 名称与 PG 名称口径不一致（如 `code_name` 含空格/全角星号）] → `TRIM` 与 `UPPER` 处理空白与大小写；全角 `＊ST` 未覆盖，列为已知限制，若出现需补规则（Open Question 1）。
- [与进行中的 `stock-metadata-sync` 变更冲突] → 该变更的 pool/调度需求在其归档前不改；本变更对 `list_pool_codes` 增加参数，向后兼容。归档时需在 delta 中同步 "非身份域目标池排除 ST" 场景。
- [`ingest_config.minute.json` 在仓库外被重新生成] → D4 消费端过滤兜底，不依赖生成方。
- [`recompute_stock` 每次多一次 PG 查询] → 补算耗时以秒计，可忽略。

## Migration Plan

1. 先合入 `stock_store` 的判定函数与 SQL 常量（无行为变化，仅新增）。
2. 再合入各 choke point 的过滤（meta_sync、list_stocks、export-config、scheduler、incremental_engine、klines）。
3. 重新生成 `ingest_config.all_stocks.json`（`gen_stock_list.py`），并通过 `intraday_poll` 的过滤处理 minute 配置。
4. 不需要数据迁移，不需要 DDL。
- 回滚：revert 代码即可；存量数据未被改动，回滚后 ST 数据立即可再次被分析。

## Open Questions

1. 全角星号（`＊ST`）或其他非标准写法是否需要纳入判定——需对 BaoStock 实际名称做一次全量抽样后确认；在确认前按 ASCII 规则实现。
2. 是否需要为 `/api/klines` 的 PG 不可达分支改为失败关闭（见 Risks）。当前按放行实现，部署后如不满意可单点切换。
