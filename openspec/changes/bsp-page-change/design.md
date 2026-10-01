## Context

动机见 proposal.md。与方案相关的现状与约束：

- **页面**：`BspView.vue` 用单一 `klOptions` 数组同时驱动左侧周期列表与工具栏下拉（改一处即两边同步）；现值含 1/5/15 分钟（DuckDB 从未灌入 1 分钟数据）、缺月线（`K_MON` 已随全市场配置灌数）。结果列表 Tab 与「板块聚合」Tab 并存，后者聚合端点已实现但按裁定暂缓。
- **API**：`GET /api/bsp` 已有骨架但有三个缺陷——关键词过滤在分页之后执行且用过滤后的页长度覆盖 `total`；响应 `{items,...}` 与前端 `PageRes{list,...}` 不符；`BspRecord` 期望 `bsp_price/direction/current_price/change_pct/industries: string[]/bsp_date(ms)`，后端给的是 `price/is_buy/无现价/无涨跌幅/[{name}]/ISO 日期`。行业信息当前逐行 N+1 查询；`GET /api/bsp/{code}` 的 `kl_types IN` 为字符串拼接。
- **存储**：`bsp_index`/`chan_structure`/`chan_snapshot` 三表 DDL 与 DAO 已存在（`bsp_store.py`），但 `upsert_bsp_index` 零调用方、表为空——**词表可自由选定**。原始 K 线在 DuckDB（灌数进程持单写锁），操作态游标在 PG（`RecomputeCursor`）。`intraday_poll.py` 已有 `recompute_fn(code, kt, au)` 钩子，但当前实现只是全量现算打日志、不落库。
- **计算内核约束**：不修改 `CChan`/`CBiList`/`CSegListChan`/`CZSList`/`CBSPointList`，只复用 `trigger_step`/`trigger_load`/pickle 能力；外部推送实例必须 `trigger_step=True`（非 step 模式在构造时就全量 `load()`）。
- **Spike 实测结论**（迁移自 chan-stock-manage D3 硬门，已执行）：pickle 快照 + `trigger_load` 续算 == 从头全量重算，7 个合成种子 + 3 只真实日线 10/10 PASS；pickle 往返稳定；零新 K 线重入幂等。唯一例外：sh.603856 一笔 `is_sure=True` 的笔终点 1697→1746——但全量重算同样给出 1746（全量@1730 才是 1697），即算法在更多数据下的追溯修正，非续算偏差。
- **周期词表现状**（三种并存）：BspView `D`/`W`/`60m`/`30m`；KLineView 与 `chan_service.PERIOD_MAP` 用 `1d`/`1w`/`1M`/`60m`…；DuckDB/`RecomputeCursor` 用枚举名 `K_DAY`…。

## Goals / Non-Goals

**Goals:**

- 周期控件修正为 30→60→日→周→月，删除 1/5/15 分钟，左右同步。
- `GET /api/bsp` 按方案 C 语义真正可用：过滤下推、契约对齐、幂等可查。
- 水位驱动的补算引擎落地：启动/定时/灌数后/手动多入口，漏调自愈，三层幂等。
- 增量续算作为补算的计算路径（带等价性证据与全量回退）。
- 承接 chan-stock-manage 的 bsp-index 需求与 /bsp 页任务，成为其唯一维护方。

**Non-Goals:**

- 板块聚合的任何新增/修改（Tab 与端点保留现状，不验收）。
- 盘中实时补算的完整实装（仅预留 `recompute_fn` 钩子接线，语义延后）。
- 监控卖点检测、预警、选股器、绩效、认证等能力（它们是 `bsp_index` 的下游，留在 chan-stock-manage）。
- 1/5/15 分钟周期的任何支持；页面级「批量加入自选」（归 watchlist-page-change）与「加入监控」（归 chan-stock-manage）的需求变更。
- 修改 `CChan` 计算内核。

## Decisions

### D1. 周期词表：bsp 模块统一用 `30m`/`60m`/`D`/`W`/`M`，`bsp_index.kl_type` 存此词表

- **取值与顺序**：扩展 `BspView.klOptions` 为 `30分(30m) → 60分(60m) → 日线(D) → 周线(W) → 月线(M)`；删除 `1m/5m/15m`。单一数组继续同时渲染左侧列表与下拉，天然同步；mock `klTypes` 同步。
- **`bsp_index.kl_type` 存前端词表**（`D`/`W`/`M`/`60m`/`30m`）：表为空，无迁移负担；查询路径（router ← 页面）全程免转换。
- **桥接**：`chan_service.PERIOD_MAP` 现缺 `D`/`W`/`M` 键——新增三键映射到 `K_DAY`/`K_WEEK`/`K_MON`（保留 `1d`/`1w` 等旧键，K 线页不受影响）；引擎侧从 PG 词表 → `KL_TYPE` 走同一映射，DuckDB 枚举名只在 `RecomputeCursor` 边界出现。
- **备选（否决）**：存枚举名 `K_DAY`——查询时每次都要映射，且前端拿到还得再翻一层；存 K 线页词表 `1d`——同页两套值（左侧 `D` vs 表格 `1d`）更乱。
- **NestingDrawer 周期子集**：现硬编码 `D/60m/30m`，当记录周期为 `W`/`M` 时标签兜底显示原始值——对齐为与 `klOptions` 同集合，保持区间套子 tab 可切换。

### D2. 方案 C：水位驱动的幂等补算（level-triggered）

```
                 +--------------------+
  startup ------>|                    |
  timer tick ---->|   catch_up()       |----> 补算单只 (code, kl_type, autype)
  灌数后通知 ---->|  （幂等、可重入）    |         |
  手动 API ------>+--------------------+         v
                                    读 DuckDB max(time_key)  (源水位)
                                    vs RecomputeCursor       (处理水位)
                                    src > cur ? 补算 : 跳过
                                                 |
                                                 v
                                    计算（D3 续算路径，失败回退全量）
                                    事务内: DELETE+INSERT 当前买卖点全集
                                          + upsert 结构/快照
                                          + 推进 RecomputeCursor
```

- **为什么不是定时任务 alone**：固定时刻服务未启动即永久漏算（用户问题 3）。水位对比是**电平触发**——无论错过多少次调度，下一次任何入口触发时自然补上；定时只是入口之一。
- **为什么不在灌数时算**：灌数进程持 DuckDB 单写锁，计算再抢锁会互相拖死；且灌数热路径不应背计算延迟。计算侧只读方式打开 DuckDB，写 PG。
- **日终为主、盘中预留**：主调度 = 收盘后日终批 + 低频 tick；`intraday_poll.recompute_fn` 钩子改为调用 `catch_up(code,…)`（语义从「现算打日志」升级为「补算落库」），是否开启盘中由配置决定，本变更不承诺盘中时效。
- **备选（否决）**：请求时现算——全市场现算数小时，交互不可用；灌数时同步算——锁与延迟问题；纯 cron——无法自愈。

### D3. 计算路径：pickle 快照 + `trigger_load` 续算，等价性硬门 + 全量回退

- 沿用 chan-stock-manage D3 机制：首次接入全量算（`trigger_step=True`）→ 结构落 `chan_structure`、买卖点参与 `bsp_index`、pickle 快照落 `chan_snapshot`；增量 = `chan_load_pickle` → `trigger_load` 新 K 线 → 只算未确认尾部（`last_sure_*` 游标 + `clear_store_end`）。
- **硬门按实测重述**：原门 2「sure 前缀在续算前后绝对不变」连全量重算都不满足（全量@N 相对全量@M 本就会追溯修正）；重述为**「续算的已确认前缀 == 全量重算的已确认前缀」**，由「续算 == 全量」整体等价蕴含（10/10 PASS）。
- **回退触发条件**：快照缺失/反序列化失败/等价性校验失败 → 该股票本次退化为全量重算（省的是「只算有变化的股票」，非「股内增量」）。spike 脚本留存为 `Debug/` 冒烟，供回归抽查。
- **不做的事**：不在生产路径上每次续算都再跑一遍全量做比对（成本翻倍）；等价性由 spike 证据 + 回退兑底。

### D4. 三层幂等（写入语义 = 整套替换）

1. **唯一键**：`(code,kl_type,autype,bsp_date,bsp_type,is_buy,time_key)` + `ON CONFLICT DO NOTHING`（防并发重复写）。
2. **每股票每周期事务内整套替换**：`DELETE` 该 `(code,kl_type,autype)` 旧行 → `INSERT` 当前 `bs_point_lst` 计算出的全集 → 同事务 `UPDATE recompute_cursor`。**必须替换而非只追加**——spike 已证明已确认笔的终点可被追溯修正，旧行可能不再成立；追加式写入会留下脏记录，游标推进后永不回头。
3. **游标与数据同事务**：失败一起回滚，杜绝「游标已走、数据没落」或反之。

`chan_structure`/`chan_snapshot` 走现有 upsert（整 JSONB/BYTEA 覆盖，天然替换语义）。`upsert_bsp_index` 的单行 DAO 保留作层 1，主写入改走替换批写。

### D5. `GET /api/bsp` 查询与契约

- **过滤下推**：`keyword`（编码/名称，`ILIKE` 匹配 `code`/`stock.name`）、`kl_type`、`bsp_type`、`direction`（`is_buy`）、可选 `date`（自 `system-page-change` U6 吸收：页面日期控件 + `BspQuery.date` 随请求发送，store 层 `query_bsp(date=)` 已支持直通透传）全部进同一 WHERE；`COUNT` 与分页共用它；`total` = 过滤后总数。
- **契约适配放 router 层**（store 返回原始行，router 映射为 `BspRecord`）：`bsp_price←price`、`direction←is_buy?'buy':'sell'`、`bsp_date→ms 时间戳`、`industries←stock_industry rank≤3 的名称数组`（单条 `array_agg`/窗口查询替代 N+1）、`id` 用行号或主键序号补位。
- **`current_price`/`change_pct`**：取该页股票在 DuckDB 的最新两根 K 线收盘价，按页批量一次查询（每页 ≤ page_size 只）；DuckDB 被灌数锁住打不开时降级为 `0`（前端显示 `--`），不阻塞列表。
- **`GET /api/bsp/{code}`**：`kl_types IN` 改为参数化占位符，消除拼接。
- **备选（否决）**：把现价/涨跌幅冗余进 `bsp_index`——买卖点价格与现价生命周期不同，冗余会产生第二套水位问题。

### D6. 板块聚合：只冻结、不删除

端点与 Tab 原样保留（删功能超出授权范围且无收益），本变更不写聚合相关验收任务；`chan-stock-manage` 的聚合需求/任务/D4 聚合句按冲突裁定删除，将来要做时以新需求立入本变更。

### D7. 页面查询参数与词表对齐

页面 `BspQuery` 为 `page/page_size/keyword/bsp_type/direction/kl_type/date`，其中 `kl_type` 取 D1 词表值（含空串 = 全部）；`direction` 空串不参与过滤；`date` 为空串/undefined 时不参与过滤（日期控件自 `system-page-change` U6 吸收）。mock handlers 与 `VITE_USE_MOCK` 场景同步新契约（含 `date` 过滤），保证无后端时页面字段仍正确。

### D8. `/bsp` 页面布局与操作归属（自 chan-stock-manage D13/D14/D15 迁入）

- **查询表单**：`周期 | 日期 | 买卖点类型 | 方向 | 关键词` +「查询」「重置」按钮；与结果表同页，服务端分页。
- **结果表**（一行 = 一条买卖点记录，多选框驱动批量操作）：`选择框 | 编码 | 名称 | 股价 | 涨跌幅 | 行业(≤3) | 买卖点类型 | 方向 | 买卖点价格 | 当前价格 | 买卖点日期 | 周期 | 操作(区间套)`。
- **工具条操作归属**：「批量加入自选」归 `watchlist-page-change`（弹窗选择目标文件夹，按 code 去重）；「加入监控」归 `chan-stock-manage`（弹窗周期默认 = 查询周期、监控时间可设，落 `monitor` 表）——本变更只负责把查询结果列表做对，两个按钮的既有实现不动。
- **区间套 Drawer**（`NestingDrawer.vue`）：行内「区间套」按钮/双击打开，按周期子 tab 展示该股票多级别买卖点；周期子集与 `klOptions` 对齐（D1），标签兜底修复一并验收。
- **板块聚合 Tab**：按 D6 冻结现状，不进验收。

## Risks / Trade-offs

- [续算等价性仅在抽样数据上验证过] → 回退路径覆盖快照异常；spike 脚本留作 `Debug/` 回归，扩样本属后续。
- [首次全市场接入成本高（5000+ 只 × 全量计算）] → 分批跑、游标天然断点可续；安排日终/夜间窗口；只算有新数据的股票是稳态成本。
- [灌数持锁期间补算读不到 DuckDB] → 补算失败不推游标，下一触发点自动重试（电平触发自愈）；绝不在灌数进程内计算。
- [追溯修正导致历史 bsp 行消失，下游（选股器/预警）读到的集合变化] → 这是「索引 = 当前正确结果」的语义；下游按当前索引读取，设计注记写明该依赖。
- [DuckDB 现价查询的降级使 `current_price=0`] → 前端对 0 显示占位；不把现价当买卖点正确性的一部分。
- [词表三套并存，桥接点遗漏即 400] → 统一走 `PERIOD_MAP` 扩展，引擎与 router 共用；冒烟覆盖 `D/W/M/60m/30m` 各一。

## Migration Plan

1. **前端周期 + 契约对齐**（不依赖引擎，mock 即可验证）→ bug 立即消失。
2. **router/store 查询修复与契约适配** → 端点可用（表可为空）。
3. **引擎首次接入**：单只冒烟 → 分批全量灌入 `bsp_index`/`chan_structure`/`chan_snapshot`。
4. **`catch_up` 接线**：startup + 定时 tick + 手动 API；（可选）`intraday_poll.recompute_fn` 切换。
5. **chan-stock-manage 侧注记**跨变更依赖；`openspec validate` 双变更通过。

回滚：关掉调度入口即可（引擎只写 PG，不影响现有读路径）；已写入的 `bsp_index` 数据对旧查询仍合法；前端契约改动与后端同步发布，不支持新旧混跑的中间态（同仓单体部署，天然同发）。

## Open Questions

- 12.2「前端多级别买卖点叠加视图」的形态：页内在 K 线上叠加，还是复用/跳转 `chan-web-viewer` 的 K 线页？两种形态任务量差异大，但不改变本设计与 spec，待实现该任务前定。
- 盘中补算的时效目标（若未来要求分钟级）：决定 `recompute_fn` 的触发频率与去抖，届时只动调度参数，不动 D2/D4 语义。
