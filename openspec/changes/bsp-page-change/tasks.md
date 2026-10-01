## 1. 前端周期列表与页面契约

- [ ] 1.1 修改 `BspView.vue` 的 `klOptions` 为 `30分(30m) → 60分(60m) → 日线(D) → 周线(W) → 月线(M)`，删除 `1m/5m/15m`；验证：下拉与左侧列表同序展示 5 项、无 1/5/15 分钟，选「月线」向后端发起 `kl_type=M` 查询（`npm run dev` 走查）
- [ ] 1.2 同步 `mock/data/bsp.ts` 的 `klTypes`，`NestingDrawer.vue` 周期子集对齐同一集合并修复 `W/M` 周期标签兜底；验证：mock 模式各周期可查询，区间套子 tab 对周线/月线记录显示中文标签而非原始值
- [ ] 1.3 核对 mock 数据与响应结构符合 `BspRecord`/`PageRes` 契约；验证：mock 模式下结果表各列无 `undefined`、分页 `total` 正确，`npm run build` 类型检查通过
- [ ] 1.4 日期条件（自 `system-page-change` U6 吸收）：`BspView` 查询表单加日期控件、`BspQuery.date` 随请求发送、MSW `bsp_list` 同步按 `date` 过滤——验证：选择日期后结果过滤生效，清空后恢复

## 2. 查询接口（GET /api/bsp）

- [x] 2.1 迁移：实现 `GET /api/bsp` 按 `kl_type`/`date`/`bsp_type`/`is_buy` 条件查询（chan-stock-manage #4.1，已完成）
- [x] 2.2 迁移：实现 `GET /api/bsp/{code}?kl_types=...` 多级别买卖点查询（chan-stock-manage #12.1，已完成）
- [ ] 2.3 修复过滤下推：`keyword`（编码/名称 `ILIKE`）与 `kl_type`/`bsp_type`/`direction`/`date` 全部进 SQL WHERE，`COUNT` 与分页共用同一条件；验证：关键词+组合条件查询的 `total` 等于全集匹配数，翻页不出现未匹配行，无命中时 `list=[]` 且 `total=0`
- [ ] 2.6 日期条件后端（自 `system-page-change` #5.1 吸收）：`GET /api/bsp` 增加 `date` 参数透传 `query_bsp(date=...)` 并入 2.3 同一 WHERE——验证：带 `date` 请求仅返回该日期命中记录，不带则行为不变
- [ ] 2.4 契约适配（router 层）：响应 `{items,...}` → `PageRes{list,...}`；字段映射 `bsp_price`/`direction`/`bsp_date`(ms)/`industries: string[]`（行业批量查询替代 N+1）；`current_price`/`change_pct` 按页批量取 DuckDB 最新两根 K 线、锁冲突时降级为 0；验证：`getBspList` 返回符合 `PageRes<BspRecord>`，前端列表渲染字段齐全，DuckDB 不可用时列表仍可展示
- [ ] 2.5 `get_bsp_by_code` 的 `kl_types IN` 拼接改为参数化占位符；验证：`kl_types` 传入含引号的构造串返回正常空结果/参数错误，不产生 SQL 错误

## 3. 补算引擎（方案 C）

- [x] 3.1 迁移：Spike 硬门验证——pickle 往返 + `trigger_load` 续算 == 从头全量重算（chan-stock-manage #3.1，已完成：7 合成种子 + 3 只真实日线 10/10 PASS；sure 前缀反例的裁定与回退见 design D3；比对脚本留存 `Debug/` 作回归）
- [ ] 3.2 `chan_service.PERIOD_MAP` 扩展 `D`/`W`/`M` 三键（映射 `K_DAY`/`K_WEEK`/`K_MON`，保留 `1d`/`1w` 等旧键）；验证：`30m/60m/D/W/M` 均解析到正确 `KL_TYPE`，非法值返回 400，K 线页既有周期请求不受影响
- [ ] 3.3 实现 `WebAPI/incremental_engine.py` 首次接入：DuckDB 全量 K 线 → `trigger_step=True` 全量计算 → 已确认结构落 `chan_structure`、买卖点落 `bsp_index`、pickle 快照落 `chan_snapshot`；验证：单只股票三表产出完整，`bsp_index` 行集与 `bs_point_lst` 一一对应
- [ ] 3.4 实现增量续算：读 `chan_snapshot` → `chan_load_pickle` → `trigger_load` 新 K 线 → 只算未确认尾部 → 落库并更新快照；快照缺失/损坏时回退该股票全量重算；验证：同一股票「续算」与「全量重算」的 `bsp_index` 行集一致（复用 3.1 比对脚本），删快照后自动回退且结果不变
- [ ] 3.5 实现整套替换写入（幂等层 2+3）：每 `(code,kl_type,autype)` 事务内 `DELETE` 旧行 → `INSERT` 当前买卖点全集 → 同事务推进 `RecomputeCursor`；验证：手工删/改索引行后重跑收敛回全集；人为中断事务时游标与数据同时回滚
- [ ] 3.6 实现 `catch_up` 水位补算入口：对比 DuckDB `max(time_key)` 与 `RecomputeCursor`，支持启动时、定时 tick、手动 API 触发（灌数后通知可选接 `intraday_poll.recompute_fn`）；验证：停掉定时造成漏批后重启，漏批股票被补上；数据无变化时重复触发不改变行数与游标
- [ ] 3.7 日终流水线：日终批量扫描当日有新增 K 线的股票执行 `catch_up`；验证：日终后当日新买卖点可查询、重复运行不产生重复行

## 4. 页面任务承接（自 chan-stock-manage 迁移）

- [x] 4.1 迁移：历史买卖点页——查询表单 + 结果表多选 + 加入自选/监控（chan-stock-manage #8.3，已完成；原描述中「板块聚合」字样随冲突裁定删除）
- [ ] 4.2 迁移：前端多级别买卖点叠加视图（或对接 `chan-web-viewer` K 线图）（chan-stock-manage #12.2，未完成；形态选择见 design Open Questions）；验证：多级别买卖点在页面可见

## 5. 验证与收尾

- [ ] 5.1 按 `specs/bsp-page` 逐 scenario 走查（周期顺序/左右同步/无 1/5/15/月线可查/字段齐全/关键词过滤/聚合 Tab 保留现状可访问）；验证：全部 scenario 通过（mock 模式）
- [ ] 5.2 真实端到端：引擎灌入索引 → 页面分页/关键词/周期查询；验证：抽样股票的页面结果与 `bsp_index` SQL 直查结果一致
- [ ] 5.3 幂等回归：对同一批股票连续执行两次 `catch_up`；验证：索引行数与游标均无变化（对应 spec「重复触发幂等」「游标与写入同事务」）
- [ ] 5.4 `openspec validate bsp-page-change --strict` 通过，`cd Front && npm run build` 无类型错误
