## 1. DDL 与推导函数

- [x] 1.1 `WebAPI/update.sql` 追加幂等加列：`bsp_index` 加 `is_sure BOOLEAN NOT NULL DEFAULT TRUE`（DO 块判 `pg_attribute`，带执行时间注释）；验证：重复执行两次 update.sql 无报错，`\d bsp_index` 确认列存在
- [x] 1.2 `WebAPI/bsp_store.py` `_ensure_tables` 建表语句同步补 `is_sure` 列；验证：删测试库重建后表结构与 update.sql 路径一致
- [x] 1.3 确认推导工具函数（design D1/D5）：输入 `bsp` + `bs_point_lst`，按 `bsp.bi.get_end_klu().idx <= last_sure_pos` 返回布尔；`last_sure_pos` 缺失/≤0 时按未确认处理并告警日志；验证：构造已确认/未确认两个 bsp 断言返回值正确

## 2. 落库与序列化

- [x] 2.1 `incremental_engine.py _extract_bsp_rows` 每行追加 `is_sure`（调 1.3 工具函数），行元组变 6 元；`persist_full_set`/`_insert_bsp_rows` INSERT 列同步；验证：对真实股票跑 `recompute_stock`，SQL 直查 `bsp_index` 确认尾部买卖点 `is_sure=false`、历史确认点 `is_sure=true`
- [x] 2.2 `serializer.py _serialize_bsp` 每点补 `"is_sure"` 字段（复用 1.3 工具函数）；验证：`/api/klines` 响应的 `bsp[]` 各点含 `is_sure`，与 `bi[]/seg[]` 契约对齐

## 3. 查询 API

- [x] 3.1 `bsp_store.py query_bsp` 增 `is_sure: Optional[bool] = None` 参数，下推进同一 WHERE（`b.is_sure = %s`），COUNT 与分页共用；验证：`is_sure=True` 只回确认行、`None` 回全部，`total` 与过滤后行数一致
- [x] 3.2 `routers/bsp.py bsp_list` 增 `sure: str = Query("")` 参数（`confirmed|preview` → `Optional[bool]`，非法值 400），响应行字典补 `is_sure`；验证：`?sure=confirmed`/`?sure=preview`/缺省三态各自返回正确子集，`?sure=xx` 返回 400
- [x] 3.3 `bsp_store.get_bsp_by_code`（多级别查询）响应同步携带 `is_sure`（若该路径复用行字典则随 3.1 自动生效，确认即可）；验证：`GET /api/bsp/{code}?kl_types=...` 各点含 `is_sure`

## 4. 前端

- [x] 4.1 `Front/src/api/types.ts` `BspPoint`/`BspRecord` 补 `is_sure: boolean`；`api/modules/bsp.ts` `getBspList` 参数增 `sure?: string`；验证：`npm run build` 类型通过
- [x] 4.2 `BspView.vue` 结果表未确认行渲染灰色「未确认」el-tag（design D4，列位置按列宽裕量定）；验证：mock 模式下未确认行可见标签、确认行无标签
- [x] 4.3 `BspView.vue` 查询表单增「确认状态」下拉（全部/已确认/未确认，默认全部），选择后带 `sure` 参数请求并重置分页；验证：三种取值各自返回对应子集，切回「全部」恢复全集
- [x] 4.4 mock 同步：`mock/data` 买卖点数据补 `is_sure` 字段（含 `false` 样例），MSW handlers 的列表查询响应支持 `sure` 过滤；验证：mock 模式下 4.2/4.3 的三条验证各自通过

## 5. 验证与收尾

- [x] 5.1 按 `specs/bsp-index` 逐 scenario 走查（确认状态过滤/记录携带确认状态/日终索引/确认状态随重算收敛）；验证：全部 scenario 通过
- [x] 5.2 幂等与收敛回归：对同一股票连续两次 `catch_up`，第二次行数与 `is_sure` 分布不变；把某尾部未确认点依托的段确认后（追加 K 线触发重算）再补算，该点 `is_sure` 翻转为 `true`；验证：SQL 直查断言两步
- [x] 5.3 `openspec validate bsp-sure-annotation --strict` 通过，`cd Front && npm run build` 无类型错误
