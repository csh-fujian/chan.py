## Why

`/bsp` 买卖点页存在三个缺陷：周期下拉与左侧列表顺序错误且包含 DuckDB 中并不存在的 1/5/15 分钟周期、缺少已灌数的月线；`GET /api/bsp` 只有骨架实现，关键词过滤在分页之后执行且覆盖 `total`，前后端契约不一致（`items` vs `list`、`BspRecord` 字段错位），全市场查询必须由离线预计算的买卖点索引支撑而引擎尚未存在；买卖点索引与增量续算引擎的需求原散落在 `chan-stock-manage`，与 `/bsp` 页相关的需求（含与本次实现冲突的板块聚合条款）需要统一迁入本变更，由本变更全权维护。

## What Changes

- **周期列表改造**：`BspView.vue` 单一 `klOptions` 源同时驱动左侧周期列表与工具栏下拉，统一为 `30分 → 60分 → 日 → 周 → 月` 顺序；**删除 1、5、15 分钟**（DuckDB 从未灌入 1 分钟数据）；**新增月线**（`K_MON` 已随全市场配置灌数）。mock 数据 `klTypes` 同步。
- **`GET /api/bsp` 可用化**：关键词过滤下推到 SQL（分页前、参与 `total` 计数）；补 `date` 日期条件（接口参数 + 页面日期控件，自 `system-page-change` U6 吸收）；修复前后端契约（响应 `items` → `list`、`BspRecord` 字段映射 `bsp_price`/`direction`/`bsp_date`(ms)/`industries: string[]`、补 `current_price`/`change_pct`）；行业信息由 N+1 查询改为单条 SQL；`GET /api/bsp/{code}` 的 `kl_types IN` 拼接改为参数化。
- **方案 C：水位驱动的幂等补算**：以 DuckDB `max(time_key)` 为源水位、PG `RecomputeCursor` 为处理水位，按 `(code, kl_type, autype)` 逐只对比触发补算；触发点 = 服务启动 / 定时 tick / 灌数后通知 / 手动 API（level-triggered，漏掉的调度自愈）。计算不进灌数进程（避开 DuckDB 单写锁），日终批量为主、盘中 `recompute_fn` 钩子预留。三层幂等：唯一键 + `ON CONFLICT DO NOTHING`；每股票事务内 `DELETE → INSERT` 整套替换（撤销被追溯修正的旧行）；`RecomputeCursor` 同事务推进。
- **增量续算引擎（自 `chan-stock-manage` 迁入）**：pickle 快照（`chan_dump_pickle`/`chan_load_pickle`）+ `trigger_load` 续算未确认尾部。spike 硬门已实测：续算 == 全量重算 10/10 PASS（7 合成种子 + 3 只真实日线）、pickle 往返稳定、零新 K 线重入幂等；「sure 前缀绝对不变」按字面连全量重算都无法满足，硬门重述为「续算的已确认前缀 == 全量重算的已确认前缀」，并保留按股票全量重算回退作保险。
- **结果列表 = 计算结果列表**：`/bsp` 结果表直接由 `bsp_index` 查询驱动，不做二次加工。
- **板块聚合暂缓**：`GET /api/bsp/aggregate` 端点与前端「板块聚合」Tab 保留现状、不开发不验收；`chan-stock-manage` 中「板块买卖点聚合」需求按冲突裁定删除，后续另行立项。
- **需求迁移**：`chan-stock-manage` 的 `bsp-index` 能力（除板块聚合）、增量续算引擎 D3/D4、`GET /api/bsp`/`/api/bsp/{code}`/历史买卖点页任务迁入本变更统一维护；同时清理该变更中残留的自选页面需求内容（需求本体已归 `watchlist-page-change`）。`system-page-change` 原占用的 `bsp-index` 三条（历史查询/板块聚合/多级别）与其 U6 日期条件按 2026-10-01 裁定撤回并并入本变更。

## Capabilities

### New Capabilities

- `bsp-index`: 买卖点索引与增量续算能力（自 `chan-stock-manage` 迁入并按方案 C 改写）——已确认缠论走势持久化、增量续算（等价性硬门 + 回退）、水位驱动的日终/补算买卖点索引、按周期/日期/类型/关键词的历史买卖点查询、多级别买卖点查询（区间套）。**不含**板块买卖点聚合（暂缓，冲突条款已删除）。
- `bsp-page`: `/bsp` 买卖点页面级行为——周期列表顺序与取值（30→60→日→周→月，无 1/5/15 分钟）、左右两侧周期控件同步、结果列表字段契约、关键词搜索、板块聚合 Tab 暂缓（保留现状不承诺）。

### Modified Capabilities

<!-- 无：主 specs 下既有能力的需求不因本变更改变。 -->

## Impact

- **前端**：`Front/src/views/bsp/BspView.vue`（`klOptions` 顺序/增删、结果表字段对齐）、`Front/src/mock/data/bsp.ts`（`klTypes` 同步）、`Front/src/api/types.ts` + `api/modules/bsp.ts`（契约对齐）、`Front/src/views/bsp/NestingDrawer.vue`（周期子集与标签兜底）。
- **后端**：`WebAPI/routers/bsp.py`（过滤下推、契约、参数化）、`WebAPI/bsp_store.py`（查询改写、整套替换写入）、新增 `WebAPI/incremental_engine.py` + 补算入口（复用 `RecomputeCursor`）、启动/定时触发接线。
- **数据库**：PG `bsp_index`（写入语义从只追加改为整套替换）、`chan_snapshot`、`chan_structure`、`recompute_cursor`；`bsp_index.kl_type` 取值确定为前端词表（`D`/`W`/`M`/`60m`/`30m`，表为空可自由选定）。
- **计算内核**：**不修改** `CChan`/`CBiList`/`CSegListChan`/`CZSList`/`CBSPointList`，仅复用 `trigger_step`/`trigger_load`/pickle 能力。
- **跨变更依赖**：`chan-stock-manage` 的监控卖点检测（7.2）、端到端冒烟（9.2）、选股器执行（11.2）、预警挂日终（13.2）消费本变更产出的 `bsp_index` 与补算流水线，需在该变更中留依赖注记；`system-page-change` 已撤下其 `bsp-index` 占用与 U6 任务（日期条件由本变更承接）。
- **数据源结论**（板块聚合暂缓的依据）：BaoStock 仅有单值证监会行业（84 类）；东财行业+概念 M2M 已由 `stock-metadata-sync` 接入，PG `stock_industry` 5571 行已就绪。
