# Tasks: stock-metadata-sync

## 1. 存储层（四表 + 运维表 + 按域所有权写入）

- [x] 1.1 `WebAPI/init.sql`：`stock` 扩为四组列（身份 6 + 用户 7 + 档案 16 + 快照 8，**不含**已删列：时点股本/B-H/market/index_members/out_date/status/多周期涨幅等）；新建 `stock_financial_report`（复合 PK `code+statement_type+report_date`，`data JSONB`）与 `stock_holder_num`（复合 PK `code+stat_date`）；`updated_at` 触发器改为仅响应用户列变更。验证：全新库执行 init.sql 得四表且 `\d stock` 无已删列、触发器对快照列更新不触发。
- [x] 1.2 `stock_store._ensure_tables` 幂等演进：`ALTER TABLE stock ADD COLUMN IF NOT EXISTS ...` 补齐缺失列 + `CREATE TABLE IF NOT EXISTS` 两子表。验证：在旧版 `stock` 表（缺档案/快照列）的存量库触发后，`\d stock` 列齐全且两子表存在，重复执行无报错。
- [x] 1.3 `stock_store` 新增按域写入函数 `apply_identity` / `apply_profile` / `apply_industries` / `apply_snapshot` / `upsert_financial` / `upsert_holder_num`，各函数 `SET` 仅含本域列；身份域含「三所名单均缺失 → `enabled=false`」分支；`apply_identity`/`apply_profile` 对静态字段集合（`ipo_date`/`found_date`）仅在目标列 IS NULL 时写入。验证：手测改好 `tags/notes/kl_types` 后跑各域写入——用户列原值保留、本域列刷新、身份域对名单缺失 code 置 `enabled=false` 且不删行；重复调用行数不增；已有 `ipo_date` 的行被同步两次后值不变。
- [x] 1.4 `init.sql` + `_ensure_tables` 新增运维表：`sync_watermark(code, domain, synced_at)` 复合 PK、`sync_job(id, domains, scope, force, status, started_at, finished_at, summary JSONB)`。验证：建表幂等；插入/更新水位后查询 `due` 判定（缺失或超间隔=到期）正确。

## 2. 同步服务层（`WebAPI/meta_sync.py`）

- [x] 2.1 实现全域共用的 code 归一函数 + 身份域抓取：归一规则（带前缀 `sh688808` 直接映射；`SZ000001`/`000001.SZ` 剥后缀；裸码首位推断 `6`→`sh`、`0`/`3`→`sz`、`4`/`8`/`9`→`bj`；无法归一拒绝并入 `failed`）；三所名单（`stock_info_sh_name_code` 多板块参数 / `stock_info_sz_name_code` / `stock_info_bj_name_code`）→ `sz.000001` 格式 + 交易所/板块/门类映射；**任一所拉取失败即中止本轮禁用判定**（fail-closed）。验证：混格式样例（`000001`/`sh688808`/`SZ000001`/`000001.SZ`/`920000`）归一后分别为 `sz.000001`/`sh.688808`/`sz.000001`/`sz.000001`/`bj.920000`；三所并集落库、简称与上市日期等于交易所值；模拟单所失败时无任何 `enabled=false` 发生。
- [x] 2.2 实现档案域抓取（巨潮 `stock_profile_cninfo` 逐股，16 列，sleep 限频）：验证：`sz.000001` 档案 16 列落库且 `name/ipo_date/exchange` 未被触碰；连续两只失败一只时另一只照常成功且入 `failed` 明细。
- [x] 2.3 实现行业域：push2 最小请求探测（每次运行一次）→ 通过则东财板块成分循环构建 M2M（稳定序、首行主行业）→ 失败则巨潮单值降级（`degraded` 计入汇总）；`industry_l1` 始终取自身份域结果。验证：探测失败路径下每股单行 `rank=0` 且汇总 `degraded=true`、退出码仍为 0；`GET /api/stocks?industry=...` 筛选可用。
- [x] 2.4 实现快照域（腾讯 `stock_zh_a_spot_tx` 1 次全市场 → 8 列 + `snapshot_at`，并处理 `all_proxy` socks 陷阱）：验证：快照行数=股票池数、仅 8 列被写入（无涨跌幅/量比/振幅/成交量额）、含 `pe_ttm/pb/main_net_inflow`。
- [x] 2.5 实现财务域（东财 datacenter 三表逐股，86 列白名单映射 + 期数策略「年报全历史+近10年中报季报」+ 复合 PK upsert；新浪备源列名映射兜底）：验证：任一股票三表落库且 `data` 仅含白名单键、无 1995 年季报但有 1995 年报；重复执行行数不变；`notice_date` 存在。
- [x] 2.6 实现股东户数域（`stock_zh_a_gdhs` 单次全市场 → 内存过滤近 1 年、剔除价量列 → upsert）：验证：表中无最新价/涨跌幅/总市值列、`stat_date` 全部在近 1 年内，重复执行幂等。
- [x] 2.7 实现编排 `sync(codes=None, domains=None, force=True) -> {created, updated, disabled, skipped, degraded, failed: [(code, domain, error)]}`：逐条目失败隔离、域间互不阻塞；到期判定（`sync_watermark` + D8 间隔矩阵，force 跳过间隔）、单元成功即写水位、`sync_job` 行生命周期（running→interrupted/done）与汇总持久化；频率矩阵常量（identity/snapshot=1d、industry=7d、holders=15d、profile/financial=30d、静态字段集合）。验证：篡改水位使财务到期/未到期，`force=False` 时分别执行/跳过且未到期不发网络请求；单域失败不影响其他域汇总计数；任务中断后 `sync_job.status=interrupted`、部分汇总可查。

## 3. 批量脚本

- [x] 3.1 新建 `Data/sync_stock_meta.py`：`--code`（可多次）、`--domain`（identity/profile/industry/snapshot/financial/holders，可多选）、`--force`/`--no-force`（默认 force）、`--loop`（常驻：每小时醒来只跑到期域）、`--sleep`、`--verbose`；`PG_DSN` 缺失明确报错退出；打印汇总（含 `disabled/degraded` 与失败前 N 条），失败非空退出码 1。验证：`--domain identity` 秒级完成且三所名单落库；`--domain financial --no-force` 全历史回填可断点重跑（续传见 6.2）；构造失败退出码 1；`--loop` 启动后未到期域零请求（连续满足 `chan-stock-manage` 任务 9.1 验收）。

## 4. Web 接口

- [x] 4.1 `POST /api/stocks/sync`（body `{code?, domains?, force?}`，force 默认 true）：`code` → 同步执行返回汇总；全市场 → `BackgroundTasks` 后台执行（写 `sync_job` 行），`running` 时拒绝重入；静态路由置于 `/{code}` 之前。验证：curl 单只返回含 `created/updated` 汇总且用户字段未变；`force=false` 时未到期域被跳过；全市场期间二次触发被拒；路由不被 `/{code}` 遮蔽。
- [x] 4.2 `GET /api/stocks/sync/status` → `{running, started_at, finished_at, last_summary}`：`running` 取内存标志，时间与汇总取 PG `sync_job` 最近一行；孤儿 `running`（进程重启遗留）按 `interrupted` 处理。验证：后台任务执行中 `running=true`；完成后返回最近汇总（含 `degraded` 与失败明细）；**重启后服务仍能查到上次汇总**，再次触发从水位续跑。
- [x] 4.3 后端内置到期检查调度：启动时注册小时级循环，按频率矩阵（1d/7d/15d/30d）对各域做 `due` 判定，到期即以 `force=false` 后台任务执行，与手动触发共用 `running` 防重入。验证：篡改水位使快照域到期 → 一小时内自动执行且写新水位；未到期时循环零请求；手动任务运行中调度不并发。

## 5. 前端入口

- [ ] 5.1 `Front/src/api/modules/stock.ts` + `types.ts`：`syncStockMeta(code?)`、`getSyncMetaStatus()` 及汇总类型。验证：`npm run build`（vue-tsc）通过。
- [ ] 5.2 自选页 `WatchlistView.vue` 工具栏加「同步元数据」按钮：`v-permission="'manage'"` 控显隐；触发后轮询 status 展示进行中与最终汇总（含降级/失败计数），股票行操作支持单只同步。验证：`npm run dev` 下 admin 可见可触发、看到进行中与汇总；`viewer` 不可见。

## 6. 端到端验收

- [ ] 6.1 按域顺序全量跑通：`identity → profile → industry → snapshot → financial → holders`，然后验证：① 手工改的 `tags/notes/enabled/kl_types` 二次同步后原值保留（名单内）；② 从名单移除的测试 code 被置 `enabled=false` 且行仍在、无退市日期列；③ `sz.000001` 财务三表年报全历史+近10年季报、`data` 白名单键、股东户数近1年；④ 快照 8 列刷新、`pe_ttm/pb` 有值；⑤ push2 探测失败时行业单值降级且汇总 `degraded`；⑥ 选股器/自选页行业筛选与展示正常；⑦ **`stock.code` 与 DuckDB `kline.code` 跨库 JOIN 匹配率 100%**（抽样沪深北各若干只，含子表 FK 全部为 `sz.000001` 格式、无异构码残留）。
- [ ] 6.2 断点续传与频率矩阵验收：① 财务全历史回填进行到约一半 `Ctrl+C`/kill，重跑 `--domain financial --no-force` —— 已完成股票被跳过（对比水位与请求数），最终行数与一次性跑完一致；② `ipo_date`/`found_date` 首次全量后人为改值再同步 → 值不被覆盖；③ 快照水位改到 25 小时前 → 调度自动执行，改到 1 小时前 → 跳过且零网络请求；④ 行业/股东户数/档案/财务分别验证 7d/15d/30d 到期边界；⑤ 后台任务 running 时 kill 服务再启动 → `sync_job.status=interrupted`、状态接口可见部分汇总、重新触发续跑。
