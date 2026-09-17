## 1. K 线页布局：左侧面板 + 主图

- [ ] 1.1 重构 `KLineView.vue` 为 `display:flex` 行布局：左侧可折叠面板（约 320px）+ 主图（flex:1），含「标的 / 问答」两 Tab 骨架；验证：`npm run dev` 后 K 线页显示左侧面板与主图，主图占剩余宽度
- [ ] 1.2 顶栏新增「加入自选 ★」与「AI 问答」按钮，点击展开面板并切换到对应 Tab；验证：点击后左侧面板展开且落在对应 Tab

## 2. 标的详情（行业/地区/概念）

- [ ] 2.1 `types.ts`：`Stock` 增 `region`/`concepts`，新增 `StockProfile`；验证：`npm run build`（vue-tsc）通过
- [ ] 2.2 `mock/data/stocks.ts` 为全部股票补 region/concepts；新增 `api/modules/stock.ts` 的 `getStockProfile`；新增 mock handler `GET /api/stocks/:code/profile`；验证：接口返回含全量行业/地区/概念
- [ ] 2.3 「标的」Tab 渲染标的头部 + 行业/地区/概念全量 badge；验证：选择不同股票时面板更新，多行业/多概念全量展示不截断

## 3. 自选管理

- [ ] 3.1 `api/modules/watchlist.ts` 新增 `renameFolder`；mock handler 新增 `PATCH /api/watchlist/folders/:id`；验证：重命名后 `getFolders` 返回新名称
- [ ] 3.2 「标的」Tab 加入「加入自选/移出自选」：未自选显示分组选择 + 加入；已自选显示所属分组 + 移出；验证：加入后状态变已自选、移出后恢复
- [ ] 3.3 「标的」Tab 分组管理：新建/重命名/删除分组入口；验证：三操作均生效并刷新自选状态

## 4. 大模型问答

- [ ] 4.1 `types.ts` 新增 `QaRecord`；新增 `api/modules/qa.ts`（ask/list/star/batchStar/deleteUnstarred）；验证：vue-tsc 通过
- [ ] 4.2 新增 `mock/data/qa.ts` 与 `mock/handlers/qa.ts`（模拟 LLM 延迟回答 + 内存记录）；验证：问答各接口可调用
- [ ] 4.3 「问答」Tab：输入框 + 发送按钮 + 回答展示；验证：提交问题后展示回答
- [ ] 4.4 问答记录列表（内容 + 时间，倒序）；点击记录弹窗展示提问与回答全文；验证：列表展示内容与时间，点击弹窗展示全文
- [ ] 4.5 打星（单条 + 批量）+ 一键删除未打星；验证：打星后星标可见，批量打星全部生效，删除后未打星记录消失、已打星保留

## 5. 后端（依赖 WebAPI 落地，可后置）

- [ ] 5.1 PG 建 `qa_record` 表 + FastAPI `ai-qa` 路由（ask/list/star/batch-star/delete-unstarred），DAO 用 psycopg2 裸 SQL；验证：重启后记录保留
- [ ] 5.2 FastAPI 标的 profile 路由 + 自选重命名路由；验证：与前端 mock 契约一致
- [ ] 5.3 接入 LLM 供应商（可插拔 `complete(prompt)`）；验证：真实提问返回回答
