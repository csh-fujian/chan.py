# Design: stock-metadata-sync

## Context

动机见 proposal.md - Why。本设计的全部数据源结论来自探索模式对 **akshare 1.18.97**（`.venv`）的真实调用实测，关键约束：

- **东财按域名分区可用**：`datacenter-web.eastmoney.com`（财务三表、龙虎榜域）稳定通畅；`push2*/push2his`（行情网关：板块成分、个股信息、快照、日度资金流）对本 IP **间歇性掐连接**，同刻 curl 直连也被拒——是东财 WAF 行为，**非本地代理配置可修**。行业 M2M 必须运行时探测 + 降级。
- **环境代理陷阱**：`all_proxy=socks5://127.0.0.1:7890` 使 requests 的直连尝试报缺 pysocks；同步实现须清空代理变量或以 `proxies={}` 显式覆盖并对东财域名做重试。
- **项目存储分层**（已定）：K 线与技术指标 N 巨大 → DuckDB；结构化小 N → PG。K 线 OHLCV 历史不在本设计范围，快照不存历史即因于此。
- **既有 PG 结构**：`stock`/`stock_industry` 已存在并被消费（选股器 `JOIN stock_industry` 行业筛选、`bsp_store` 板块聚合、自选/监控/买卖点索引对 `stock.code` 的 FK 级联）——退市处理禁止物理删除的根因。
- **`WebAPI/stock_store.py` 现状**：`_ensure_tables` 惰性建表；`upsert_stock` 全字段覆盖会冲掉用户配置，必须新增按列所有权的写入路径；`WebAPI/init.sql` 为新库初始化脚本；无 Alembic。
- **前端现状**：无独立股票管理页（`chan-stock-manage` 的管理视图未落地），新菜单需新增 `menu:*` 权限种子；`v-permission="'manage'"` 指令可用。
- **1.18.97 相对 1.18.59 仅新增 4 函数**，其中 `stock_zh_a_spot_tx`（腾讯全市场快照）正补上 push2 快照不可用的缺口，北交所两融补齐三所（两融域已删，仅记录此事实）。

探索期已裁定并写入 spec 的删除项：退市名单、IPO、两融、资金流（日度+即时）、分红、龙虎榜、东财个股信息、同花顺财务、雪球、申万、新浪名单；`stock` 上的退市日期/状态/名单时点股本/B-H 股/入选指数/所属市场/多周期涨幅/量比/振幅/涨跌幅/成交量额等列。

## Goals / Non-Goals

**Goals:**

- 一条共享同步服务被批量脚本与 Web 接口同时调用，行为一致。
- 字段所有权在 DAO 层按列强制（身份/档案/快照/子表=同步所有；用户列=保护）。
- 四表收敛布局（合并 profile/snapshot 进 `stock`），存量库零手工迁移。
- 东财行情网关不可用时行业降级为巨潮单值，管道不中断。

**Non-Goals:**

- 不存退市名单/退市日期/上市状态列（名单缺失即退市信号）；不物理删除已退市档案。
- 不做两融、资金流、分红、龙虎榜等已砍域；调度采用轻量**到期检查**（脚本 `--loop` 常驻 或 后端内置定时循环），不引入外部任务队列/Redis/系统 cron 硬依赖（cron 仍是可选部署方式）。
- 不做元数据历史版本审计（快照仅存最新；财务/股东户数只存数据源当前可得的历史切片）。
- 不改动缠论计算与 DuckDB K 线存储；不修改 `stock-universe` 的 CRUD/导入语义。

## Decisions

### D1: 分域数据源矩阵（一域一主源，备源按可用性）

| 域 | 主源 | 调用量 | 降级/备注 |
|----|------|--------|----------|
| 身份（code/name/ipo_date/exchange/board/industry_l1） | 交易所官网：`stock_info_sh_name_code`（主板A股/科创板A股等参数）、`stock_info_sz_name_code`、`stock_info_bj_name_code` | 3 次全市场 | **唯一权威**，巨潮身份字段忽略；A1 新浪名单只作校验不入库 |
| 公司档案（16 列） | 巨潮 `stock_profile_cninfo` | 逐股 ~5500 次 | 无备源；sleep 限频 |
| 行业 M2M | 东财 `stock_board_industry_name_em` + `stock_board_industry_cons_em`（push2，**运行时探测**） | ~86 板块 | 失败 → 巨潮档案单值（D4）；`industry_l1` 始终取自交易所名单 |
| 估值快照（8 列） | 腾讯 `stock_zh_a_spot_tx` | 1 次全市场 | 东财 `stock_zh_a_spot_em` 仅当 push2 探测通过时作备选 |
| 财务三表 | 东财 datacenter `stock_{balance,profit,cash_flow}_sheet_by_report_em` | 逐股×3 | 备选新浪 `stock_financial_report_sina`（150 列、nan 偏多）；同花顺弃（字符串/`False` 占位） |
| 股东户数 | 巨潮 `stock_zh_a_gdhs` | 1 次全市场（44 万行内过滤） | 剔除价量列后按近 1 年过滤落库 |

弃选记录：雪球（`KeyError 'data'`，可能需 token）、申万（层级树非 M2M 且接口报错）、`stock_individual_info_em`（push2）、新浪即时资金流（与快照重复 + 字符串单位）。

**统一代码规范（跨库唯一键，全域共用一个归一函数）**：交易数据在 `Data/kl_store.duckdb` 的 `kline.code` 为 `sz.000001` 格式，`stock.code`、各子表 FK、灌数配置、`CChan(code=...)` 参数全部对齐该格式，保证 PG↔DuckDB 等值 JOIN。

| 源 | 实测样例 | 归一规则 |
|----|---------|---------|
| 交易所名单 | `000001`、`920000`（裸码，且名单本身已分所） | 首位推断：`6`→`sh`，`0`/`3`→`sz`，`4`/`8`/`9`→`bj`；亦可用所属名单交叉校验 |
| 腾讯快照 | `sh688808` | 前缀 `sh/sz/bj` → `sh.688808` |
| 巨潮档案/股东户数 | `000001`（裸码，不分所） | 同首位推断规则 |
| 东财财务 | `SZ000001`（symbol 参数回显）、`000001.SZ`（SECUCODE） | 取前缀映射 / 剥离 `.XX` 后再推断 |

约束：归一在**写入前**完成，所有域（含 `stock_industry`/`stock_financial_report`/`stock_holder_num` 的 FK）只使用归一值；无法归一 → 计入 `failed` 拒绝落库（spec「跨库唯一键归一」场景）；A 股名单已排除 B 股（`20`/`90` 开头），首位推断不会误伤。

### D2: 四表布局 —— 合并 profile/snapshot，保留 industry

```
stock (1)──< stock_industry (N)        # 已有：M2M，三处消费方(JOIN)不动
stock (1)──< stock_financial_report    # 新：JSONB 复合主键 (code, statement_type, report_date)
stock (1)──< stock_holder_num          # 新：时序复合主键 (code, stat_date)
```

- **合并理由**：profile/snapshot 与 `stock` 天然 1:1；PG TOAST 自动外置 `main_business`/`intro` 等长文本，只要列表查询显式列名（现实现即如此）不拖慢热路径；少两张表 = 同步、FK、迁移全简化。
- **保留 `stock_industry` 理由**：选股器行业筛选、`bsp_store` 板块聚合、`stock-universe` 的 M2M 需求三者都 `JOIN` 此表；降级单值时每股 1 行结构兼容。
- **`stock` 列分组**（按所有权）：
  - 身份（交易所）：`code` PK、`name`、`exchange`、`ipo_date`、`board`、`industry_l1`；
  - 用户（保护）：`enabled`（仅名单缺失规则可改）、`kl_types`、`autypes`、`tags`、`notes`、`created_at`、`updated_at`；
  - 档案（巨潮 16）：`full_name`、`en_name`、`former_names`、`legal_person`、`reg_capital`、`found_date`、`website`、`email`、`phone`、`fax`、`reg_addr`、`office_addr`、`postal_code`、`main_business`、`business_scope`、`intro`；
  - 快照（腾讯 8）：`price`、`total_mv`、`float_mv`、`pe_ttm`、`pb`、`turnover_rate`、`main_net_inflow`、`snapshot_at`。
- **已删列**（防止实现时加回）：`total_share`/`float_share`（时点值语义错位，市值列与股东户数表已覆盖）、B/H 四列、`market`（与 `board` 重复）、`index_members`（无消费方）、`out_date`/`status`（B 域已删）、快照的 `change_pct`（与 DuckDB 算出的涨跌幅重复）/`amplitude`/`volume_ratio`/`state`/`stock_type`。
- **备选（弃）**：独立 `stock_profile`/`stock_snapshot` 表——1:1 合并无收益，仅增 JOIN。

### D3: 退市 = 名单缺失判定，不物理删除

- 判定：`stock` 中存在、三所名单并集中不存在 → 本轮同步置 `enabled=false`，停更来源字段；新代码只从名单建档，退市股自然不再出现。
- 不存退市日期/状态列：B 域（`stock_info_*_delist`）已删，交易所在市名单本身即边界。
- **不物理删除**：`watchlist_item`/`monitor`/`bsp_index` 对 `stock(code)` FK 级联，删档会连用户自选；手动清理保留为人工操作（超出本变更）。
- 备选（弃）：拉 B 名单落表判定——违反"退市信息不记录"；物理删除——破坏 FK。

### D4: 财务三表 —— 86 列裁剪 + 65 期策略 + JSONB 单表

- **列**：221 → ~86：报告元数据 9（SECUCODE/CODE/简称/ORG_TYPE/REPORT_DATE/TYPE/NAME/NOTICE_DATE/CURRENCY）+ 资产负债通用 ~34 + 利润 ~24 + 现金流 ~19；剔除银行保险专属（存放央行/拆借/贵金属…）与重复子项 ~135 列。
- **期数**：119 → ~65：**年报全历史（~37）+ 近 10 年中报与全部季报（~28）**。
- **形态**：三表合一 `stock_financial_report`，`statement_type ∈ {balance, income, cashflow}`，科目存 `data JSONB`——列集随报表类型不同，JSONB 免去宽表空列；复合 PK `(code, statement_type, report_date)` upsert 幂等，`notice_date` 随行存防未来函数。
- **量级**：~109 万行、压缩后约 0.5 GB（对比全量 196 万行/2–3 GB）。
- 备选（弃）：三张物理表（列名冲突少但 JOIN 多）；展平 86 列宽表（三表列集不同，空列膨胀）；全量 119 期 221 列（用户已裁剪）。

### D5: 同步服务 + 脚本 + Web 共用一条核心路径

- **`stock_store` 新增按域写入**：`apply_identity` / `apply_profile` / `apply_industries` / `apply_snapshot` / `upsert_financial` / `upsert_holder_num`，每个函数的 `UPDATE ... SET` **只含该域列**（身份函数不得触碰档案/用户列；`enabled` 仅在名单缺失分支更新）；行业沿用既有 `upsert_industries` 先删后插。
- **`WebAPI/meta_sync.py` 服务层**：数据源抓取（含 push2 探测、代理陷阱处理、sleep 限频）、字段规范化校验（关键字段缺失跳过）、逐标的失败隔离、汇总 `{created, updated, disabled, skipped, degraded, failed[]}`；`sync(codes=None, domains=None)`。
- **脚本 `Data/sync_stock_meta.py`**：`--code`（可多次）、`--domain`（identity/profile/industry/snapshot/financial/holders，可多选）、`--force`（无视到期间隔，手动默认开启）、`--loop`（常驻循环：按 D8 频率矩阵只执行到期域）、`--sleep`、`--verbose`；PG_DSN 缺失明确报错；失败非空退出码 1；财务全历史回填经 `--domain financial --no-force` 可按水位续跑（见 D9）。
- **Web**：`POST /api/stocks/sync`（body `{code?, domains?, force?}`，force 默认 true）——有 `code` 同步返回；全市场走 `BackgroundTasks`，`running` 时拒绝重入；`GET /api/stocks/sync/status` 读 PG `sync_job` 最近记录 + 内存 `running` 标志，返回 `{running, started_at, finished_at, last_summary}`——**重启后仍可查最近汇总**；后端启动时注册小时级到期检查协程，发现到期域即以后台任务执行（与手动共用防重入）。
- 备选：服务层放 `ChanAnalyse/DataAPI/`——它依赖 Web 层 PG DAO 与业务所有权语义，不属计算内核；PG job 表 + worker——单用户管理操作引入常驻组件过重；接口内阻塞全市场——~90+ 网络请求会超时。

### D6: 限频、失败隔离与环境陷阱

- 巨潮逐股 sleep（默认 0.3–0.5s 可配）；东财 datacenter 逐股 sleep；腾讯/交易所全市场接口单次调用。
- 逐条目 try/except，失败入 `failed: [(code, domain, error)]`，汇总与退出码对齐 `download_kl.py` 风格。
- **代理陷阱**：请求前若检测到 `all_proxy` 为 socks 且未装 pysocks，则在进程内清空相关代理变量（或对直连域显式 `proxies={}`），并对东财 push2 域做 2–3 次退避重试后判定降级。
- push2 探测：同步开始时以最小请求探测一次，结果缓存本次运行内复用（避免逐股反复撞 WAF）。

### D7: 存储结构演进 —— init.sql + 幂等 ALTER/CREATE

- 新库：`WebAPI/init.sql` 直接建全四表（含 `stock` 全部四组列）。
- 存量库：`_ensure_tables` 内 `ALTER TABLE stock ADD COLUMN IF NOT EXISTS ...`（缺失的档案/快照/身份新列）+ `CREATE TABLE IF NOT EXISTS` 两个子表——幂等，脚本与接口共用入口。
- `updated_at` 触发器改为仅响应用户列变更（避免快照高频刷新污染更新时间戳）——实现细节，通过 `WHEN (OLD.* IS DISTINCT FROM NEW.*)` 限定用户列比较。
- 备选：Alembic——项目从未引入，为四表引迁移框架过重，弃。

### D8: 刷新频率矩阵与静态字段（到期 = 水位 + 间隔）

| 域/字段 | 频率 | 依据 |
|---------|------|------|
| 身份名单（identity） | **每天** | 新股上市、更名、名单缺失禁用判定需日频；仅 3 次请求 |
| 估值快照（snapshot） | **每天** | 当日行情值，1 次全市场 |
| 行业（industry） | **7 天** | 板块成分慢变；7 天窗口覆盖新股行业归属 |
| 股东户数（holders） | **15 天** | 季报频次；全市场单次请求成本极低，15 天抓披露高峰 |
| 公司档案（profile） | **1 个月** | 字段慢变；逐股 ~5500 次请求，月频摊薄限频压力 |
| 财务三表（financial） | **1 个月** | 财报季（4/8/10 月末披露潮）月频窗口全覆盖；单次逐股×3 成本高，首次全历史后仅按月重拉 |
| **静态字段**（`ipo_date`、`found_date` 等代码标记为 never 的字段） | **一次全量，永不覆盖** | 从不更新：`apply_*` 写入前检查目标列 IS NULL 才写，已有值直接跳过——"接口数据从不更新 → 一次全量执行完毕"在列级实现（这些字段搭乘月频档案调用零额外成本） |

- 到期判定：`due(domain) = 水位缺失 OR now - synced_at >= interval`；**手动触发 `force=true` 跳过间隔判断**（仍受续传保护——本次任务内已完成单元不重复）。
- 备选（弃）：域级"静态则永不调接口"——不存在整域从不更新的接口（身份有新股、快照逐日变化），列级 static 集合才是正确粒度。

### D9: 断点续传 —— 单元水位即进度，无额外状态机

- **`sync_watermark(code, domain, synced_at)`**（复合 PK）：单元 = `(code, domain)`，成功即单条 upsert 提交（逐单元事务），进程死掉最多丢当前正在跑的一个单元。
- **续传 = 到期判定的副产品**：重跑时单元已写水位且在有效期内 → 天然跳过；中断的财务全历史回填（`--no-force`/定时模式）重跑即从半途继续。`force` 手动全量在**单次任务内**记录任务开始时间 `started_at`，单元 `synced_at >= started_at` 同样跳过——保证 force 重跑也是续传而非重做。
- **`sync_job(id, domains, scope, force, status[running/interrupted/done/failed], started_at, finished_at, summary JSONB)`**：Web 后台任务与脚本长任务各写一行；状态与汇总持久化，服务重启后 `status=running` 无人认领 → 置 `interrupted`，下次触发按上述规则续跑；status 端点读最近一行。
- 备选（弃）：断点文件/日志扫描——Web 与脚本共享不了；内存进度字典——重启即失忆（原 D5 的纯内存方案被本决策取代）；按 `kline` 水位类比按数据时间续拉——档案/快照接口无内建水位，单元完成标记才是通用进度。

## Risks / Trade-offs

- [push2 被东财长期拉黑] → 行业长期停在巨潮单值，M2M 名存实亡 → spec 已定义降级为合法状态；缓解：未来可换同花顺板块成分或其他源，只动 `meta_sync` 抓取层。
- [巨潮逐股 ~5500 次（档案+股东户数过滤）被限流] → sleep 可调 + 失败隔离 + 断点靠幂等重跑；档案域允许部分失败不阻塞名单域。
- [财务三表回填耗时/体量] → 已裁剪至 86 列 65 期；`--domain financial` 独立执行；新浪备源在东财 datacenter 异常时兜底（列名映射层）。
- [同笔更新污染 `updated_at` / 快照高频刷新与用户编辑同行锁竞争] → 触发器限定用户列；单机小规模行锁可忽略。
- [名单缺失误判（接口抖动返回不全）] → 三所名单任一整体拉取失败即中止本轮禁用逻辑（fail-closed：拿不全名单就不做禁用判定），仅在三所全部成功时执行。
- [股东户数 `stock_zh_a_gdhs` 返回 44 万行全市场全期] → 拉取一次后内存按 `code+近1年` 过滤，落库量 ~2.2 万行/年。
- [B/H、入选指数等"以后可能要"的字段被删] → 加列成本低，确需时再提案，不在本期预留。
- [到期调度与手动触发并发双跑] → 共用同一 `running` 内存标志 + `sync_job` 行级状态，防重入已覆盖两条路径；cron 用户与内置调度同时启用 → 文档注明二选一（内置到期检查为默认，cron 为可选替代）。
- [水位写入与单元数据不在同一事务（跨 PG 连接：数据源→PG 单元表）] → 单元提交顺序固定为"先写数据表事务成功、再写水位"；崩溃最坏结果 = 数据已写水位缺失 → 重跑幂等覆盖，无数据损坏。

## Migration Plan

1. 合并代码（init.sql 四表 + 两张运维表 + `_ensure_tables` 幂等扩展）→ 重启后端即完成存量库演进。
2. 首次全量按域执行（各域 `--no-force` 水位续跑，可反复中断重启）：`identity`（3 次请求，秒级）→ `profile`（逐股，限频跑）→ `industry`（探测+板块循环/降级）→ `snapshot`（1 次）→ `financial`（全历史，最长任务，中断即续）→ `holders`（近 1 年）；静态字段在首个全量周期写入后即被锁死。
3. 日常运行二选一：**默认**启用后端内置到期检查（每小时检查，日频域到点自动跑）；或部署侧用脚本 `--loop` / cron 替代（文档注明勿双开）。
4. 回滚：代码回退即可；新增列/子表/水位表留着无害（旧代码不读不写），无需 DDL 回滚。

## Open Questions

- 行业 M2M 的 rank 排序按东财板块遍历稳定序实现（确定性满足"展示前 3 + 主行业"）；是否需要按板块热度/市值加权贴近"真实相关度"，待 M2M 实际落库后由用户看展示效果再定，不影响本期任务拆分。
