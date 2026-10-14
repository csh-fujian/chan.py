# Proposal: stock-metadata-sync

## Why

股票结构化信息目前没有自动同步管道：PG `stock` 表的 `name`/`exchange` 依赖手工录入，`stock_industry` 行业多对多只能手工导入，公司档案、估值快照、财务三表、股东户数等展示与分析材料完全没有落库；BaoStock `query_stock_basic` 只在 `CChan` 内存中用一下即丢。选股器的行业筛选、自选页展示、三买质量评估与大模型分析都缺持续新鲜的结构化数据。经探索模式实测（akshare 1.18.97 逐接口真实调用），确定以 **AKShare 为唯一工具库、多数据源分域接入**的同步管道。

## What Changes

- **多域元数据同步管道**：新增批量脚本与 Web 刷新入口，从多个 AKShare 数据源分域拉取并幂等落 PG：
  - **身份**（A2/A3/A4 交易所官网名单，**唯一权威源**）：代码、简称、上市日期、交易所、板块、行业门类；各源异构代码格式（裸码 `000001`、腾讯 `sh688808`、东财 `SZ000001`/`000001.SZ`）SHALL 统一归一为与 DuckDB `kline.code` 一致的 `sz.000001` 格式，作为 PG↔DuckDB 跨库匹配的唯一键；
  - **公司档案**（巨潮 `stock_profile_cninfo`，剔除身份字段后的 16 列）：公司全称、英文名、曾用简称、法人、注册资金、成立日期、联系方式、地址、主营/经营范围/简介；
  - **行业**（东财板块成分 M2M，运行时探测 push2 → 不通降级巨潮单值）落 `stock_industry`；
  - **估值快照**（腾讯 `stock_zh_a_spot_tx`，8 列）：最新价、总/流通市值、PE-TTM、PB、换手率、主力净流入；
  - **财务三表**（东财 datacenter，JSONB）：221 列裁剪至 86 列、119 期减至约 65 期（年报全历史 + 近 10 年中报/季报）；
  - **股东户数**（巨潮）：近 1 年回填 + 季度增量时序。
- **四表布局**：`stock`（身份+用户+档案+快照四组合并，长文本走 TOAST）、`stock_industry`（已有，M2M）、`stock_financial_report`（新）、`stock_holder_num`（新）；配套 `sync_watermark`（单元水位）与 `sync_job`（任务记录）两张运维表。删除原设计中的 `stock_profile`、`stock_snapshot` 独立表。
- **断点续传**：以 `(code, domain)` 为执行单元，单元成功即持久化水位；脚本与 Web 接口中断（进程退出/重启）后再次执行自动从未完成单元继续，已完成且未到期单元被跳过；任务汇总持久化，服务重启后仍可查询最近一次结果。
- **刷新频率与调度**：代码内置静态字段判定（`ipo_date`/`found_date` 等从不更新的数据首次全量写入后永不覆盖）；按域设定频率——身份/快照**每天**（定时增量）、行业 **7 天**、股东户数 **15 天**、档案/财务三表 **1 个月**；到期判定基于水位，支持脚本循环模式与后端定时检查自动执行每日到期域；手动触发无视间隔强制刷新（仍走断点续传）。
- **退市规则**：退市股票不建档、不记录退市名单；存量股票在三所名单中均缺失时同步自动置 `enabled=false`，**不物理删除**（自选/监控/买卖点索引有 FK 级联）。
- **字段所有权**：身份/档案/快照/子表列由同步所有、每次刷新；`enabled`（仅名单缺失规则可改）/`kl_types`/`autypes`/`tags`/`notes` 为用户字段，同步其余路径不得触碰。
- **明确删除的域**（探索期逐域评估后砍掉，不建表）：退市名单、IPO 摘要、融资融券（整域）、资金流日度历史与即时（整域）、分红送配（整域）、龙虎榜（整域）、东财个股信息、同花顺财务、雪球、申万、新浪名单。
- **不修改** `CChan`/`CBiList`/`CSegListChan`/`CZSList`/`CBSPointList` 计算逻辑；不改动 DuckDB K 线存储（K 线与技术指标 N 巨大，按项目分层归 DuckDB）。

## Capabilities

### New Capabilities

- `stock-metadata-sync`: 股票结构化信息同步能力。覆盖分域数据源解析与字段所有权、幂等落库、退市名单缺失判定、行业 M2M 探测降级、财务三表裁剪回填、股东户数时序、批量脚本与 Web 手动刷新触发、同步结果可观测。

### Modified Capabilities

（无。`openspec/specs/` 下暂无既有能力的需求发生 spec 级变化。）

注：`chan-stock-manage` 中尚未归档的 `stock-universe` delta（持久化/CRUD/手工批量导入/行业 M2M 展示）不被本变更修改；本变更为其 `stock`/`stock_industry` 表提供自动化填充管道，且行业 M2M 的落点与消费方（选股器行业筛选、买卖点板块聚合）保持该 delta 原语义。

## Impact

- **新增文件**：`Data/sync_stock_meta.py`（批量同步脚本）；本变更规划产物。
- **修改文件**：`WebAPI/stock_store.py`（四表建表/迁移 + 按列所有权的同步写入）、`WebAPI/routers/stocks.py`（`POST /api/stocks/sync` + 状态查询）、`WebAPI/init.sql`（四表结构）、`Front/src/api/modules/stock.ts` 与自选视图（同步按钮 + 结果反馈）、`Script/requirements.txt`（列入 akshare，当前仅在 `.venv` 手工安装）。
- **数据源依赖**（均经实测）：交易所官网（上交所/深交所/北交所名单，1 次/所）、巨潮（逐股档案与股东户数）、东财 `datacenter-web`（财务三表，已验证通）、东财 `push2*`（行业板块成分，**间歇性被 WAF 掐断，需运行时探测+降级**）、腾讯（全市场快照）。
- **存储**：PostgreSQL；财务三表约 109 万行 JSONB（压缩后约 0.5 GB），股东户数约 2.2 万行/年；新增 `sync_watermark`/`sync_job` 运维表。
- **调度执行**：每日增量域由脚本 cron 或 `--loop` 常驻模式、或后端内置到期检查定时执行；低频域按 7/15/30 天矩阵到期自动运行。
- **运行环境**：脚本需 `PYTHONPATH=.` 与 `PG_DSN`；环境存在 `all_proxy=socks5://...`（requests 直连需清空或装 pysocks），同步实现需处理该陷阱。
