## 1. 后端：搜索与排序数据层

- [x] 1.1 `WebAPI/init.sql`：`watchlist_folder`、`watchlist_item` 各加 `sort_order INT NOT NULL DEFAULT 0` 列；验证：建库脚本可重复执行，列存在
- [x] 1.2 `WebAPI/watchlist_store.py`：`_ensure_tables()` 内 `ADD COLUMN IF NOT EXISTS` 兜底 + 存量回填 `sort_order = id`；验证：对已有数据的库执行后每行 sort_order 非空且等于 id
- [x] 1.3 `watchlist_store.py`：`list_folders`/`get_folder_stocks`/`_get_folder_codes` 改为 `ORDER BY sort_order, id`；验证：调整 sort_order 后查询顺序随之变化
- [x] 1.4 `watchlist_store.py`：`get_folder_stocks`/`_get_folder_codes` 增加 `q` 参数，JOIN `stock` 表按 code/name 子串过滤；验证：q='银行' 只返回匹配股票，q='' 返回全量
- [x] 1.5 `watchlist_store.py`：新增 `reorder_folders(ids)` 与 `reorder_folder_stocks(folder_id, codes)`（单事务全量覆盖 sort_order）+ 内存降级实现；验证：调用后顺序生效且幂等
- [x] 1.6 `WebAPI/routers/watchlist.py`：`GET /folders/{id}/stocks` 加可选 `q` 查询参数；新增 `PUT /folders/reorder` 与 `PUT /folders/{id}/stocks/reorder`；验证：curl 三种接口行为符合预期，缺参数返回 422

## 2. 前端：三项缺陷修复

- [x] 2.1 `WatchlistView.vue`：移除 `v-if="f.id !== 1"` 删除守卫（「全部」节点本在 v-for 外无删除按钮）；验证：新建的第一个文件夹（id=1）展示删除按钮，「全部」行无删除按钮，删除含股文件夹有二次确认
- [x] 2.2 `WatchlistView.vue`：`selectFolder` 内调用 `loadStocks()`；验证：左右侧切换文件夹时右侧表格立即刷新并可见网络请求
- [x] 2.3 搜索按钮 + 服务端查询：输入框旁加搜索按钮与回车触发，`getFolderStocks(id, q)` API 签名扩展，删除纯前端 `filteredStocks` 过滤（或仅保留为加载后本地兜底）；验证：输入关键字点按钮发出带 q 的请求，列表按后端结果过滤，清空后恢复全量
- [x] 2.4 重置按钮：搜索按钮旁加「重置」，点击清空输入框与 `activeQuery` 并重新加载当前视图全量列表；验证：过滤生效时点重置，输入框清空、发出不带 q 的请求、列表恢复全量（真实后端冒烟 6/6 PASS，脚本 `/tmp/e2e_reset_btn.py`）

## 3. 前端：重命名与激活刷新

- [x] 3.1 文件夹行加编辑按钮，对话框按 `mode: create|rename` 复用（空名拦截）；验证：重命名后左侧树显示新名称并提示成功，空名不发请求
- [x] 3.2 `WatchlistView.vue` 增加 `onActivated(() => reload())`，reload 携带当前 q 与选中文件夹；验证：在 K 线页加入自选后切回自选页，新数据可见；选中文件夹与搜索词保留

## 4. 前端：拖拽排序

- [x] 4.1 安装 `vuedraggable@next`（含 sortablejs）到 `Front/package.json`；验证：`npm install` 成功且 lockfile 更新
- [x] 4.2 文件夹树：draggable 包裹 v-for（「全部」节点在容器外），`delay=200` 长按，`onEnd` 乐观更新 + 调 `PUT /folders/reorder`，失败回滚；验证：长按拖拽换序并持久化，短按仍触发选中，刷新后顺序保持
- [x] 4.3 股票表格：sortablejs 挂 tbody（`row-key` + 拖拽 handle 图标），`onEnd` 乐观更新 + 调 `PUT /folders/{id}/stocks/reorder`，失败回滚；验证：行拖拽换序持久化，双击跳 K 线与行内按钮不受影响，文件夹间顺序独立
- [x] 4.4 mock 同步：`Front/src/mock/data|handlers/watchlist.ts` 支持 q 过滤与 reorder（本地序保持）；验证：`VITE_USE_MOCK=true` 下上述交互行为与真实后端一致

## 5. 验收

- [ ] 5.1 端到端冒烟（真实后端）：按本变更全部 spec 逐场景走查——`watchlist-page`：按钮/回车搜索、切换刷新、新建即 id=1 可删、全部不可删、重命名、文件夹与股票双拖拽持久化、跨页新增回页可见；`watchlist`（迁移）：字段展示（名称/编码/股价/行业≤3）、查询结果多选批量加入自选（选择目标文件夹、按 code 去重）；验证：全部场景通过，`npm run build` 无类型错误
  > 进展（2026-10-01）：E2E 实跑 PASS 65 / FAIL 0 / BLOCKED 1（脚本 `/tmp/e2e_watchlist.py`），`npm run build` 通过；仅「查询结果多选批量加入自选（UI）」场景被 BspView `items`/`list` 契约缺陷阻塞（归属 `bsp-page-change` 任务 2.4，经用户裁定：待其修复后回来补验该场景再勾选本条）。

## 6. 需求迁移（自 chan-stock-manage）

- [x] 6.1 迁移 `specs/watchlist` 三项需求至本变更（批量加入按实现改写为「选择目标文件夹」，冲突的「默认日期作文件夹名」条款删除），同步更新 proposal/design/tasks
- [x] 6.2 删除 chan-stock-manage 的自选页面需求内容（`specs/watchlist/`、proposal 能力声明与 Tab1/Tab2 冲突表述、design 冲突交互描述、任务 6.1 失实括注），两变更均通过 `openspec validate`

## 7. 自选加入监控（行级 + 批量，来源「自选」）

- [x] 7.1 `WebAPI/monitor_store.py`：`create_monitor` 的 `source_type` 白名单放行 `'watchlist'`（纯校验放行，无 DDL）；`WebAPI/routers/monitor.py`：`POST /monitor` body 的 `source_type` 同步放行（非白名单值落 `'chan'` 现状不变）；验证：带 `source_type='watchlist'` 提交后 monitor 行 source_type 落 'watchlist'，不传仍落 'chan'，'xxx' 非法值仍落 'chan'，`GET /monitor` 返回该字段
- [x] 7.2 `Front/src/api/modules/monitor.ts`：`CreateMonitorPayload` 增加可选 `source_type?: 'chan' | 'strategy' | 'watchlist'`；`Front/src/views/monitor/MonitorView.vue`：来源列 `watchlist` → 显示「自选」（`src-tag` 样式，`strategy_label` 逻辑不动）；`Front/src/mock/handlers|data/monitor.ts`：`source_type` 落库与返回同步支持；验证：`npm run build` 通过，mock 模式下 watchlist 来源记录显示「自选」
- [x] 7.3 `Front/src/views/watchlist/WatchlistView.vue`：行级「加入监控」按钮 + 弹窗（级别下拉 30m/60m/D/W/M 默认日线、时间默认「此刻」+「此刻」按钮、分组选择/快速新建同 BspView、价格初始 = 行股价 + `getPriceAt` 防抖联动、取价失败保留当前价并提示）；提交携带 `source_type='watchlist'`；验证：行级加入后监控页对应分组下可见、来源列「自选」
- [x] 7.4 `Front/src/views/watchlist/WatchlistView.vue`：多选批量「加入监控」（弹窗统一参数，提交前端循环 `POST /monitor` 逐只 `getPriceAt`、取价失败按行股价提交并计入提示、单只失败不中断、汇总「成功 X / 失败 Y」）；验证：mock 下批量 3 只（含 1 只取价失败路径）提交后全部入监控、汇总提示正确
- [x] 7.5 端到端验证（双模式）：mock 全链路（行级/批量/分组新建/默认日线/取价失败兜底）+ 真后端（PG 可达时）同链路，重点核对 `source_type='watchlist'` 落库与监控页来源列显示；`npm run build` 无类型错误
