## 1. ST 判定基础设施

- [x] 1.1 在 `WebAPI/stock_store.py` 新增 `is_st_name(name)`（`re.match(r"^\*?ST", (name or "").strip(), re.IGNORECASE)`）与常量 `ST_EXCLUDE_SQL`（**实施偏差见 1.4**），并验证：`python -c` 对 "ST某某"、"*ST某某"、"st某某"、" *ST 某"、"平安银行"、"中ST"、""、None 的结果分别为 True/True/True/True/False/False/False/False
- [x] 1.2 在 `stock_store.py` 新增 `exclude_st_codes(codes) -> list[str]`（`SELECT code, name FROM stock WHERE code = ANY(%s)`，保留无名与不在表中的代码，保持输入顺序）与 `get_stock_name(code) -> Optional[str]`，并新增异常类 `StockNameSourceUnavailable`（PG 连接不可用时抛出）；验证：PG 可用时对含 ST 代码的列表返回剔除结果，PG 断开时抛出该异常
- [x] 1.3 在 `ST_EXCLUDE_SQL` 定义处加一行注释说明 COALESCE 的原因（无名股票不得被前缀比较误排除）；验证：`grep -n "COALESCE" WebAPI/stock_store.py` 命中
- [x] 1.4 **（实施中新增）** `ST_EXCLUDE_SQL` 改为 `LEFT(UPPER(TRIM(COALESCE(s.name, ''))), 2) <> 'ST' AND LEFT(..., 3) <> '*ST'`，**不使用**原设计的 `NOT LIKE 'ST%'`：该片段被拼进带 params 的 `cur.execute(sql, params)`，psycopg2 会对整条 SQL 做 `%` 格式化，字面量 `%` 会被当作占位符抛 `ValueError`/`TypeError`。已实测两种写法在 psycopg2 语义下的行为差异。design.md D1 已同步修订。

## 2. 股票查询（GET /api/stocks）

- [x] 2.1 `stock_store.list_stocks` 的 `conditions` 始终追加 `ST_EXCLUDE_SQL`，COUNT 与 SELECT 共用同一 where；验证：断言生成的 SQL 片段，total 与 items 均不含 ST
- [x] 2.2 `_fallback_list_stocks` 改为抛出 `StockNameSourceUnavailable`（移除返回代码列表的兜底分支）；`list_stocks` 在 PG 不可用时同样失败关闭
- [x] 2.3 `WebAPI/routers/stocks.py` 的列表路由捕获 `StockNameSourceUnavailable` 并返回 503，detail 为「无法排除 ST 股票：名称来源不可用」

## 3. 前端 MSW mock 对齐

- [x] 3.1 `Front/src/mock/handlers/stock.ts` 的 `/api/stocks` 在 `matched` 过滤中追加 `!/^\*?ST/i.test(s.name.trim())`；同时把「无关键字直接返回 stocks」的分支并入统一 filter，使全量列表也排除 ST。
      **注意**：3.1 的验证标准是「`vite build` 通过、`vue-tsc -b` 无类型错误」，该标准对本次改动恒为真 —— 构建只做类型检查，不校验该 mock 的运行时返回是否含 ST。本次验证方式为：`npm run build` 通过（✓ built），加 node 实测正则对 7 个样例的判定（与后端 `is_st_name` 一致）。前端 `npm run dev` 下搜索页「ST 不出现在结果中」**未经端到端验证**。

## 4. 元数据目标池（meta_sync）

- [x] 4.1 `stock_store.list_pool_codes(enabled=None, exclude_st=False)` 新增参数，`exclude_st=True` 时追加 `ST_EXCLUDE_SQL` 条件（`FROM stock` 统一别名为 `s`）
- [x] 4.2 `WebAPI/meta_sync.py` 的 `_SyncCtx.pool_codes` 增加 `exclude_st` 形参并透传；验证：`grep -n "pool_codes" WebAPI/meta_sync.py` 所有调用点显式给出 `exclude_st`
- [x] 4.3 `due_domains` 对非 identity 域传 `exclude_st=True`，identity 域保持 `enabled=None` 且不排除 ST；`_sync_identity` 的 `candidates` 保持全集
- [x] 4.4 **（实施中补全）** 除 D3 点名的三处外，5 个逐股域 sync 函数（`_sync_profile` / `_sync_industry` / `_sync_snapshot` / `_sync_financial` / `_sync_holders`）的 `ctx.pool_codes` 调用也显式传 `exclude_st=True`，否则 due_domains 之外的直接抓取仍会命中 ST。design.md D3 未禁止，属 spec「逐股元数据目标池排除 ST」的必要补全。

## 5. K 线灌数配置

- [x] 5.1 `Data/gen_stock_list.py`：在 `query_all_a_share` 返回后、`--limit` 截断**之前**用 `is_st_name(code_name)` 过滤。
      **偏差**：未从 `stock_store` 导入，改为脚本内复制等价正则并注明来源。理由：`stock_store` 模块底部无条件执行 `_ensure_tables()`（连 PG + 跑全套 DDL），一个纯 BaoStock 枚举脚本不应被引入 DB 连接与建表副作用。
- [x] 5.2 重新生成 `Data/ingest_config.all_stocks.json`。结果：A 股个股 5225 只 → 剔除 ST 198 只 → **保留 5027 只**（sh 2237 / sz 2790），`kl_types` 为 `K_DAY,K_WEEK,K_MON`，无重复代码；被剔除名称抽查全部为真实 ST/*ST（如 `ST明诚`/`*ST尔雅`/`ST太重`），名称含 ST 但被保留的为 0（无过虑/漏虑）。
      **执行方式**：本机到 BaoStock `baostock.com:10030` 直连超时，改经本地代理（ClashX `127.0.0.1:7890`，SOCKS5）连通。注意该代理链路**不稳定**：实测同样查询一次返回完整 7416 行、下一次在 4000 行处被截断且 `error_code=10001001`。因此本次未直接调用 `query_all_a_share`（它在流被截断时会**静默返回部分列表**），而是按「消费完循环后 `error_code` 仍为 `'0'`」作为完整性判据重试到成功才落盘，避免写出截断的股票池。
      原始 40 只版本已备份到 `/tmp/ingest_config.all_stocks.json.bak-40stocks`。
      **成因校正**：曾怀疑 40 只版本是被 `vp_entry_pool` 的生成器覆盖所致；比对后**证伪** —— 40 只版本全为 `sh.600xxx`，而 `vp_entry_pool.json` 的 40 只全为 `sz.000xxx`，两者**代码集合不相交**（仅文件体积巧合相同）。40 只版本的特征（`sh.600xxx` 前缀、仅 `K_DAY`）与「默认参数运行 `gen_stock_list.py` 时枚举流被截断」完全吻合，故成因判定为 **9.1 的静默截断**。
- [x] 5.3 `WebAPI/routers/stocks.py` 的 `/export-config` PG 路径 SQL 追加 `ST_EXCLUDE_SQL`；DuckDB 兜底路径改为返回 503
- [x] 5.4 `Data/intraday_poll.py`：配置加载后、`iter_intraday_jobs` 之前用 `--pg-dsn` 查询名称并剔除 ST 代码，打印被剔除清单；PG 不可达（含未提供 `--pg-dsn`）则非零退出

## 6. K 线分析接口（GET /api/klines）

- [x] 6.1 `WebAPI/main.py` 的 `get_klines` 在 `_compute_chan` 之前调用 `get_stock_name(symbol)`；若 `is_st_name` 为真则 `HTTPException(404, detail="已排除：ST 股票")`，且不读写 `get_chan_cache()`
- [x] 6.2 PG 不可达分支：捕获 `StockNameSourceUnavailable` 后记录 warning 并放行（不返回 503）

## 7. 策略扫描与买卖点补算

- [x] 7.1 `WebAPI/strategy_engines/scheduler.py`：`list_all_codes` 枚举后经 `exclude_st_codes`；`_task_codes` 在解析出 codes 之后（含显式传入的 `scope_codes`）再次过滤
- [x] 7.2 `WebAPI/incremental_engine.py` 的 `list_stale_keys`：在 limit 截断前对结果键按 `exclude_st_codes` 过滤
- [x] 7.3 `incremental_engine.recompute_stock` 入口处判定：ST 代码直接 `log.info` 并返回 None
- [x] 7.4 核对 `WebAPI/routers/bsp.py` 与 `WebAPI/routers/strategy.py`：两者均无直接调用，只经 `catch_up` / `run_task`，已落在 choke point 内，无需补守卫
- [x] 7.5 **（实施中新增）** 收敛重复实现：`scheduler.py` 原有的本地 `_filter_st_codes` / `_is_st_name`（来自 `chan-stock-manage` 变更，依赖 `scope_resolver.get_stock_names`）改为委托 `stock_store.exclude_st_codes` / `is_st_name`，符号名保留以兼容 `Debug/strategy_task_smoke.py`。
      ⚠ **行为变化**：旧实现 PG 失败时「降级为全量放行」，新实现按 spec 失败关闭。副作用见下方「遗留问题」。

## 8. 回归与冒烟测试

- [x] 8.1 新增 `Debug/test_st_exclusion.py`（脚本式冒烟，无 pytest）：覆盖 1.1 判定表、2.1 SQL 片段、2.2 失败关闭、4.1 开关、4.3 候选集合、6.1 404 分支、6.2 放行分支；验证：`.venv/bin/python Debug/test_st_exclusion.py` → 29 PASS / 0 FAIL
- [x] 8.2 运行既有冒烟测试不回归：`Debug/bi_test.py`（✅ 3 笔识别正确，退出码 0）与 `Debug/test_e2e_duckdb.py`（✅ all 8 checks passed）
- [x] 8.3 确认计算内核未改动：`git diff --stat -- ChanAnalyse/` 为空 ✅
- [x] 8.4 确认未新增 DDL：`git diff -- WebAPI/init.sql WebAPI/update.sql` 为空 ✅
- [x] 8.5 端到端抽样：在真实 PG+DuckDB 环境对 `GET /api/stocks?q=ST`、`GET /api/stocks/export-config`、`GET /api/klines?symbol=<ST代码>` 各发一次请求。
      **已执行**（`PG_DSN=postgresql://postgres:postgres@127.0.0.1:5432/chan`，`stock` 表 5571 行 / 202 只 ST；DuckDB `Data/kl_store.duckdb` 11GB）。结果：
      - `GET /api/stocks?q=ST` → 200，57 条，含 ST 字样的名称 0 条（越界 0）。
      - `GET /api/stocks`（全量）→ 200，`total=5369` **恰等于** PG 非 ST 数（5571−202），列表无 ST。
      - `GET /api/stocks/export-config` → 200，导出 5369 条（**裸数组**，非 `{stocks:[...]}` 包装），与 ST 集合交集为空。
      - `GET /api/klines?symbol=sh.600053`（`*ST九鼎`）→ **404 `已排除：ST 股票`**（在任何缓存读写/计算之前返回）。
      - `GET /api/klines?symbol=sz.000001`（平安银行，非 ST 对照）→ 200，正常返回缠论结构（bi=391/seg=59/zs=39/bsp=83/klines=8664），确认排除规则不误伤。
      - 注：`/api/stocks*` 与 `/api/klines` 无鉴权依赖；应用侧 DSN 取自环境变量 `PG_DSN`（`WebAPI/config.py` L8，导入时读取），须在导入前设置，否则 `_get_pg_conn()` 返回 None → 503。

## 9. 复核后补做项（用户确认）

- [x] 9.1 `Data/gen_stock_list.py` 的 `query_all_a_share` 增加**枚举完整性守卫**：循环结束后校验 `rs.error_code == '0'`，否则抛 `RuntimeError`（含 error_code/error_msg/已读行数）。
      背景：D4「已知风险」所指 —— 流被服务端截断时 `while rs.error_code == "0" and rs.next()` 条件恰好为假而退出，函数静默返回**部分**列表并写出「股票不全」的配置，正是本次事故的成因。
      验证：假 BaoStock 结果集模拟截断（读完把 error_code 翻成 `10001001`）→ 抛 `RuntimeError`；正常流 → 正常返回全部，不误报。
- [x] 9.2 名称来源不可用时**策略任务状态复位**（遗留问题 1）：`routers/strategy._run_task_background` 捕获 `StockNameSourceUnavailable` 后把任务复位为 `paused`；`scheduler.run_eod_tasks` 同类异常也复位 `paused`（其他异常仍复位 `done`，原行为不变）。
      **取舍说明**：规范（`strategy-task-redesign` spec L8）把任务状态域钉死为 `pending/running/paused/done`，**无 `failed`**。故未新增 `failed` 状态（需动 CHECK 约束 + `update.sql` DDL + 前端，且跨变更），而是复位为**可续跑**的 `paused` —— 该故障（PG 不可用）是可重试的环境问题，扫描一行都没跑，`done` 会误导为「已扫完」。
      验证：`Debug/test_st_exclusion.py` 7.6 段 4 条断言（后台路径/其他异常/EOD 两分支）。
- [x] 9.3 `Data/ingest_config.minute.json` 与 `Data/ingest_config.vp_entry_pool.json` **脱管**：追加 `.gitignore` + `git rm --cached`（文件保留在磁盘）。二者与 `all_stocks.json` 同属各机器本地维护、规模不一的产物。
- [x] 9.4 **清洗 `Data/ingest_config.minute.json` 的 ST 条目**：用 PG 名称过滤，**5220 → 5021**（剔除 199 只 ST/*ST，sh 2237 / sz 2784，`kl_types` 全部 `K_5M,K_15M,K_30M,K_60M`），残留 ST = 0。原文件备份 `/tmp/ingest_config.minute.json.bak-with-st`。
      注：D4 原决定「否决一次性改写 JSON，改在消费端过滤」的理由（外部重新生成会回退）在 9.3 脱管后减弱 —— 仓库副本不再被外部覆盖；消费端 `intraday_poll.py` 的过滤（5.4）仍保留为兜底。
      附：`vp_entry_pool.json` 同样含 2 只 ST，**已一并清洗**（`sz.000010 *ST美丽`、`sz.000016 *ST康佳A`，40 → 38 只，sh 20 / sz 18）。原文件备份 `/tmp/ingest_config.vp_entry_pool.json.bak-with-st`。

## 10. 附带修复（**不属本变更范围**，另行记录）

- [x] 10.1 **删除死模块** `WebAPI/strategy_engines/scope_resolver.py`（遗留问题 2）。该模块仅导出 `get_stock_names`，7.5 收敛后已无任何引用（全仓 `grep` 仅命中其自身定义），整文件删除而非仅删函数。验证：`import WebAPI.strategy_engines.scheduler / routers.strategy / monitor_store` 均 OK。
- [x] 10.2 **`monitor` 表补 `updated_at` 列**（本会话发现的既有缺陷，与 ST 无关）。现象：`monitor` 由 `monitor_store._ensure_tables()` 惰性建表、建表语句不含 `updated_at`；而 `init.sql` 无条件 `DROP`+`CREATE` 挂 `trg_monitor_updated_at BEFORE UPDATE` 触发器（触发器写 `NEW.updated_at`）。表已存在时 `init.sql` 的 `CREATE TABLE IF NOT EXISTS` 为 no-op → 「有触发器、无列」，任何 `UPDATE monitor` 报 `record "new" has no field "updated_at"`（`Debug/strategy_task_smoke.py` 的 monitor 结算段即因此失败）。
      修复：按「惰性 DDL 才是 schema 契约」，在 `monitor_store._ensure_tables()` 增加 `ALTER TABLE monitor ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`；并在 `WebAPI/update-mac.sql` 追加幂等记录（macOS 机器，含执行时间注释）。`update-win.sql` 不动（变更发生在 mac）。
      验证：`Debug/strategy_task_smoke.py` → **112 通过 / 0 失败**（修复前在 monitor 结算段报 `UndefinedColumn`）。

## 遗留问题（需你决策）

**全部已闭环**（原 4 项 + 复核新增 2 项）：

1. ~~PG 不可用时策略任务卡在 `running`~~ → **已处理（9.2）**：复位为 `paused`（非 `failed`，规范无该状态，见 9.2 取舍说明）。
2. ~~`scope_resolver.py::get_stock_names` 成为死代码~~ → **已处理（10.1）**：整模块删除。
3. ~~`all_stocks.json` 脱管导致 5.2 验证标准失效~~ → **已由 8.5 的真实端到端验证取代**（不再依赖 `git diff --stat`）。
4. ~~`vp_entry_pool.json` / `minute.json` 仍是跟踪产物~~ → **已脱管（9.3）**；两份文件内的 ST 均已清洗（9.4）。
5. ~~`vp_entry_pool.json` 内 2 只 ST 是否清洗~~ → **已清洗（9.4 附）**。
6. ~~`monitor` 表缺 `updated_at`（既有缺陷）~~ → **已修复（10.2）**：惰性 DDL 补列 + `update-mac.sql` 记录。

