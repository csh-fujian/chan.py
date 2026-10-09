## 1. ST 判定基础设施

- [ ] 1.1 在 `WebAPI/stock_store.py` 新增 `is_st_name(name)`（`re.match(r"^\*?ST", (name or "").strip(), re.IGNORECASE)`）与常量 `ST_EXCLUDE_SQL`（`UPPER(TRIM(COALESCE(s.name, ''))) NOT LIKE 'ST%' AND ... NOT LIKE '*ST%'`），并验证：`python -c` 对 "ST某某"、"*ST某某"、"st某某"、" *ST 某"、"平安银行"、"中ST"、""、None 的结果分别为 True/True/True/True/False/False/False/False
- [ ] 1.2 在 `stock_store.py` 新增 `exclude_st_codes(codes) -> list[str]`（`SELECT code, name FROM stock WHERE code = ANY(%s)`，保留无名与不在表中的代码，保持输入顺序）与 `get_stock_name(code) -> Optional[str]`，并新增异常类 `StockNameSourceUnavailable`（PG 连接不可用时抛出）；验证：PG 可用时对含 ST 代码的列表返回剔除结果，PG 断开时抛出该异常
- [ ] 1.3 在 `ST_EXCLUDE_SQL` 定义处加一行注释说明 COALESCE 的原因（无名股票不得被 NOT LIKE 误排除）；验证：`grep -n "COALESCE" WebAPI/stock_store.py` 命中，且该注释不超过一行

## 2. 股票查询（GET /api/stocks）

- [ ] 2.1 `stock_store.list_stocks` 的 `conditions` 始终追加 `ST_EXCLUDE_SQL`，COUNT 与 SELECT 共用同一 where；验证：构造含 ST 行的测试库（或断言生成的 SQL 片段），total 与 items 均不含 ST
- [ ] 2.2 `_fallback_list_stocks` 改为在 PG 不可用时抛出 `StockNameSourceUnavailable`（移除返回代码列表的兜底分支）；验证：关闭 PG 调用接口，返回 503 而非 200
- [ ] 2.3 `WebAPI/routers/stocks.py` 的列表路由捕获 `StockNameSourceUnavailable` 并返回 503，detail 为「无法排除 ST 股票：名称来源不可用」；验证：`curl /api/stocks` 在 PG 不可达时状态码为 503

## 3. 前端 MSW mock 对齐

- [ ] 3.1 `Front/src/mock/handlers/stock.ts` 的 `/api/stocks` 搜索在 `matched` 过滤中追加 `!/^\*?ST/i.test(s.name.trim())`；验证：在 `Front` 执行 `npm run build` 通过（`vue-tsc -b` 无类型错误），且 `npm run dev` 下搜索页输入 "ST" 不返回 mock 中名称以 ST 开头的股票（mock 数据当前无 ST，可临时在 `src/mock/data/stocks.ts` 外用 handler 单测或手动在控制台验证）

## 4. 元数据目标池（meta_sync）

- [ ] 4.1 `stock_store.list_pool_codes(enabled=None, exclude_st=False)` 新增参数，`exclude_st=True` 时追加 `ST_EXCLUDE_SQL` 条件（注意 `FROM stock` 无别名时需统一别名为 `s`）；验证：两种参数组合的 SQL 生成正确，默认调用行为不变
- [ ] 4.2 `WebAPI/meta_sync.py` 的 `_SyncCtx.pool_codes`（约 L724-728）增加 `exclude_st` 形参并透传；验证：`grep -n "pool_codes" WebAPI/meta_sync.py` 所有调用点显式给出 `exclude_st`
- [ ] 4.3 `due_domains`（约 L1419）对非 identity 域传 `exclude_st=True`，identity 域保持 `enabled=None` 且不排除 ST；`_sync_identity` 的 `candidates`（约 L824）保持全集；验证：单测或断言 identity 候选集合仍包含 ST 代码，profile 等域候选集合不含 ST 代码

## 5. K 线灌数配置

- [ ] 5.1 `Data/gen_stock_list.py`：在 `query_all_a_share` 返回后、`main` 构造 `stocks` 前用 `is_st_name(code_name)` 过滤（从 `stock_store` 导入判定函数，或在脚本内复制等价正则并注明来源——优先导入以保证单一来源）；验证：`PYTHONPATH=. python Data/gen_stock_list.py --limit 20` 输出配置中无 ST 名称
- [ ] 5.2 重新生成 `Data/ingest_config.all_stocks.json`（需 BaoStock 网络）；验证：`git diff --stat Data/ingest_config.all_stocks.json` 显示仅删除行为主，且配置中股票数 = 原数量 − 当期 ST 数量
- [ ] 5.3 `WebAPI/routers/stocks.py` 的 `/export-config` PG 路径 SQL 改为 `WHERE enabled = TRUE AND <ST_EXCLUDE_SQL>`；DuckDB 兜底路径改为抛出/返回 503（与 2.3 一致）；验证：PG 可用时返回不含 ST；PG 不可用时 503
- [ ] 5.4 `Data/intraday_poll.py`：配置加载后（`main` 中，`iter_intraday_jobs` 之前）用 `--pg-dsn` 查询名称并剔除 ST 代码，打印被剔除清单；PG 不可达则非零退出；验证：用包含一只 ST 代码的临时配置运行 `--once`，日志显示剔除且 DuckDB 中该代码无新增分钟行

## 6. K 线分析接口（GET /api/klines）

- [ ] 6.1 `WebAPI/main.py` 的 `get_klines` 在 `_compute_chan` 之前调用 `get_stock_name(symbol)`；若 `is_st_name` 为真则 `HTTPException(404, detail="已排除：ST 股票")`，且不读写 `get_chan_cache()`；验证：请求 ST 代码返回 404 且 detail 正确，请求非 ST 代码行为与改动前一致（对比响应 JSON 相等）
- [ ] 6.2 PG 不可达分支：捕获 `StockNameSourceUnavailable` 后记录 warning 并放行（不返回 503）；验证：断开 PG 后请求非 ST 代码仍返回 200，日志含 warning

## 7. 策略扫描与买卖点补算

- [ ] 7.1 `WebAPI/strategy_engines/scheduler.py`：`list_all_codes` 枚举后经 `exclude_st_codes`；`scan_instance` 在 `codes` 解析之后（含显式传入）再次经 `exclude_st_codes`；验证：`scan_instance` 对包含 ST 代码的显式 codes 列表，返回的 `scanned` 不计入 ST 代码，strategy_signal 表无新增 ST 行
- [ ] 7.2 `WebAPI/incremental_engine.py` 的 `list_stale_keys`：在 limit 截断前对结果键按 `exclude_st_codes` 过滤；验证：构造含 ST 键的 stale 列表，`--limit` 后的键数等于有效非 ST 键数
- [ ] 7.3 `incremental_engine.recompute_stock` 入口处判定：ST 代码直接 `log.info` 并返回 None；验证：`PYTHONPATH=. python -m WebAPI.incremental_engine --catch-up --codes <ST代码>` 输出 scanned=0 或全部 skip，且 chan_structure/bsp_index 无新行
- [ ] 7.4 核对 `WebAPI/routers/bsp.py` 与 `WebAPI/routers/strategy.py` 中所有直接调用 `recompute_stock` / `scan_instance` / `list_stale_keys` 的路径，确认均经过上述 choke point；验证：`grep -rn "recompute_stock\|scan_instance\|list_stale_keys" WebAPI` 输出的每个调用点都在 choke point 内或已在本任务中补充守卫

## 8. 回归与冒烟测试

- [ ] 8.1 新增 `Debug/test_st_exclusion.py`（脚本式冒烟，遵循仓库 `Debug/*_test*.py` 约定，无 pytest）：覆盖 1.1 的判定表、2.1 的 SQL 片段、4.3 的候选集合断言、6.1 的 404 分支（用 FastAPI TestClient 与桩 `get_stock_name`）；验证：`.venv/bin/python Debug/test_st_exclusion.py` 全部 PASS
- [ ] 8.2 运行既有冒烟测试不回归：`.venv/bin/python Debug/bi_test.py` 与 `.venv/bin/python Debug/test_e2e_duckdb.py` 均通过；验证：退出码为 0
- [ ] 8.3 确认计算内核未改动：`git diff --stat -- ChanAnalyse/` 为空；验证：命令输出为空
- [ ] 8.4 确认未新增 DDL：`git diff -- WebAPI/init.sql WebAPI/update.sql` 为空；验证：命令输出为空
- [ ] 8.5 端到端抽样：在真实 PG+DuckDB 环境对 `GET /api/stocks?q=ST`、`GET /api/stocks/export-config`、`GET /api/klines?symbol=<ST代码>` 各发一次请求并记录结果；验证：三者分别为不含 ST 的列表、不含 ST 的配置、404 "已排除：ST 股票"
