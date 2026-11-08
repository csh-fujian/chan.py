## 1. 后端：级别过滤与稳定标识（bsp-index）

- [x] 1.1 `WebAPI/bsp_store.py` 的 `query_bsp()` 新增 `ladder: str = ""` 参数，非空时向既有 WHERE 追加 `COALESCE(b.ladder, CASE WHEN b.is_sure THEN 'L4' ELSE 'L2' END) = %s`（`COUNT` 与分页共用该 WHERE），并在 docstring 写明与列表回显同口径；验证：直接用 psycopg2 调用 `query_bsp(ladder='L4')` 与不带该参数，确认 `total` 随过滤变化且分页结果全部为 L4。
- [x] 1.2 `WebAPI/routers/bsp.py` 的 `GET /api/bsp` 新增 `ladder: str = Query("")` 并透传 `query_bsp(..., ladder=ladder if ladder else "")`；验证：`curl "http://localhost:8000/api/bsp?ladder=L4&page=1&page_size=5"` 返回的每条记录 `ladder` 均为 `L4`，`total` 小于不带该参数时的 `total`。
- [x] 1.3 同上路由中把列表响应的 `id` 由 `(page - 1) * page_size + idx + 1` 行号占位改为由记录自身字段拼成的稳定字符串（`code`/`kl_type`/`autype`/`bsp_date`/`bsp_type`/`time_key`，`items` 已含这些字段，无需改 SQL）；验证：连续两次同条件查询同一页，各记录 `id` 完全一致；翻到第 2 页再回第 1 页，`id` 仍一致；同一页内 `id` 两两不同。
- [x] 1.4 验证存量行兜底参与过滤：对 `ladder` 为 NULL 且 `is_sure=true` 的记录，`ladder=L4` 查询能命中它；`is_sure=false` 的能被子 `L2` 命中，且 `ladder=L1`、`ladder=L3` 不返回任何存量行。若无存量行数据，临时 `UPDATE bsp_index SET ladder = NULL WHERE ...` 造一条后验证并复原。

## 2. 前端：API 契约

- [x] 2.1 `Front/src/api/types.ts` 中 `BspRecord.id` 由 `number` 改为 `string`，注释说明其为稳定复合键（与 `bsp_index` 唯一键同构）；`Front/src/api/modules/bsp.ts` 的 `BspQuery` 新增 `ladder?: string`；验证：`cd Front && npx vue-tsc -b` 无类型错误。
- [x] 2.2 `Front/src/mock/data/bsp.ts` 生成的 mock 记录补齐与真实接口同构的稳定字符串 `id`（避免 `VITE_USE_MOCK=true` 时表格出现重复 `row-key` 警告）；同时 `Front/src/mock/handlers/bsp.ts` 补上 `ladder` 过滤（mock 逐条件镜像真实接口，缺此条件会让 mock 模式静默忽略级别筛选）；验证：临时以 `VITE_USE_MOCK=true` 启动，打开买卖点页，控制台无重复 key 警告。

## 3. 前端：级别查询条件（bsp-page）

- [x] 3.1 `Front/src/views/bsp/BspView.vue` 工具栏在「买卖点类型」附近新增级别单选下拉，选项为「全部」与 L4 确认买卖点 / L3 背驰预警 / L1 区间套 / L2 虚笔候选（按下标顺序 L4→L3→L1→L2，不含「未定级」），宽度与「买卖点类型」对齐，变更即 `onQueryChange()` 重置分页并查询；验证：选中 L4 后列表每行级别列均为 L4，`total` 随之变化。
- [x] 3.2 同文件 `query` 初始值与 `onReset()` 中纳入 `ladder`（初值 `''`，重置回 `''`），确认左侧栏统计（`buy`/`sell`/`total` 三次请求）与列表口径一致；验证：选 L4 后左侧「买点/卖点」计数同步收窄；点「重置」后级别回「全部」且列表恢复。
- [x] 3.3 确认级别条件不影响「板块聚合」Tab：`loadAggregate()` 不携带 `ladder`；验证：选 L4 后切到板块聚合 Tab，聚合数值与未选级别时一致。

## 4. 前端：批量加入监控（bsp-page）

- [x] 4.1 把 `BspView.vue` 的 `onBatchMonitor()` 存根替换为打开批量弹窗：新增批量弹窗（标题含去重后条数），内含分组选择（复用既有 `getMonitorGroups` / `createMonitorGroup` 与下拉尾部行内新建）与只读目标清单（编码、名称、周期、买卖点时间、买卖点价格、方向）；验证：多选若干行后点「加入监控」，弹窗列出全部所选行的清单且字段正确，未选中时按钮仍禁用。
- [x] 4.2 实现提交前去重：按 `(code, kl_type)` 保留 `bsp_date` 最新的一条，时间打平时按级别强度（L4 > L3 > L1 > L2）取强者、再按 `time_key`/顺序取首；弹窗中提示去重前后数量；验证：构造同股同周期多行（如 30m 上 2B 与 3B）选中后打开弹窗，确认清单只剩最新一条且提示显示去重前后数量。
- [x] 4.3 实现提交循环：逐条按 `kl_type = row.kl_type`、`monitor_start_time = toDateTimeStr(row.bsp_date)`、`entry_price = getPriceAt(code, row.kl_type, time)` 调用 `createMonitor`（不传 `source_type`，沿用缺省来源）；取价失败回退 `row.bsp_price` 并计入失败；单条失败不中断；期间弹窗 `v-loading` 且禁用确认按钮；完成后按成功/失败数汇总提示，并清空选择集与 `已选` 计数；验证：批量提交后到监控页确认每条监控的周期与起始时间分别等于其来源行的周期与买卖点时间（抽查跨周期选择的多条），且结果列表选择集已清空。
- [x] 4.4 验证卖点行同口径：勾选一条卖点行批量加入监控，确认未被跳过或拦截，创建出的监控周期/时间与该行一致；确认行级「加入监控」按钮行为未受影响。
- [x] 4.5 验证选择集串行已修复：选中若干行后切换周期筛选（如日线 → 30分），确认 `已选` 计数与表格高亮落在同一批记录上，或随条件变更被清空，不再出现「计数不变但选中的是另一批股票」；同样验证翻页往返后选择正确。

## 5. 端到端冒烟

- [x] 5.1 全链路冒烟：打开买卖点页 → 按级别 L4 查询 → 翻页 → 跨页多选 → 批量加入监控（选分组）→ 到监控页核对每条监控的周期/起始时间/入场价与其来源行一致、分组归属正确 → 清理测试数据；验证：全流程无报错，监控列表数据与所选买卖点记录逐条对应。
