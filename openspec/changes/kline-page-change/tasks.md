## 1. K 线页布局：左侧面板 + 主图

- [x]  1.1 重构 `KLineView.vue` 为 `display:flex` 行布局：左侧可折叠面板（约 320px）+ 主图（flex:1），含「标的 / 股票信息 / 问答」三 Tab；验证：`npm run dev` 后 K 线页显示左侧面板与主图，主图占剩余宽度
- [x]  1.2 顶栏新增「加入自选 ★」与「AI 问答」按钮，点击展开面板并切换到对应 Tab；验证：点击后左侧面板展开且落在对应 Tab
- [x]  1.3 Tab 内容缓存：`kline-side__body` 的 `v-if` 链改为 `<component :is>` + `<KeepAlive>`（标的/股票信息/问答各一缓存槽）；验证：问答输入草稿与记录列表、标的分组列表与详情切走再切回仍在；换股后缓存 Tab 刷新为新股票信息（design D7）

## 2. 标的详情（行业/地区/概念）

- [x]  2.1 `types.ts`：`Stock` 增 `region`/`concepts`，新增 `StockProfile`；验证：`npm run build`（vue-tsc）通过
- [x]  2.2 `mock/data/stocks.ts` 为全部股票补 region/concepts；新增 `api/modules/stock.ts` 的 `getStockProfile`；新增 mock handler `GET /api/stocks/:code/profile`；验证：接口返回含全量行业/地区/概念
- [x]  2.3 「标的」Tab 渲染标的头部 + 行业/地区/概念全量 badge；验证：选择不同股票时面板更新，多行业/多概念全量展示不截断

## 3. 自选管理

- [x]  3.1 `api/modules/watchlist.ts` 新增 `renameFolder`；mock handler 新增 `PATCH /api/watchlist/folders/:id`；验证：重命名后 `getFolders` 返回新名称
- [x]  3.2 「标的」Tab 加入自选管理：分组列表逐组提供「加入自选」（支持就地新建分组并加入），已加入的分组逐个展示、可单独移出，状态行显示「已加入 N 个分组 / 尚未加入自选」；验证：加入后状态更新，移出后恢复
- [x]  3.3 「标的」Tab 分组管理：新建/重命名/删除分组入口；验证：三操作均生效并刷新自选状态

## 4. 大模型问答

- [x]  4.1 `types.ts` 新增 `QaRecord`；新增 `api/modules/qa.ts`（ask/list/star/batchStar/deleteUnstarred）；验证：vue-tsc 通过
- [x]  4.2 新增 `mock/data/qa.ts` 与 `mock/handlers/qa.ts`（模拟 LLM 延迟回答 + 内存记录）；验证：问答各接口可调用
- [x]  4.3 「问答」Tab：输入框 + 发送按钮 + 回答展示；验证：提交问题后展示回答
- [x]  4.4 问答记录列表（内容 + 时间，倒序）；点击记录弹窗展示提问与回答全文；验证：列表展示内容与时间，点击弹窗展示全文
- [x]  4.5 打星（单条 + 批量）+ 一键删除未打星；验证：打星后星标可见，批量打星全部生效，删除后未打星记录消失、已打星保留

## 5. 后端：QA 持久化与 LLM 接入（design D4/D5/D8）

- [x]  5.1 三表 + DAO + 鉴权路由：`WebAPI/init.sql` 增 `qa_record`（含 `user_id INTEGER NOT NULL REFERENCES chan_user(id)` 与 `(user_id, created_at)` 索引）、`user_setting`、`llm_provider`（D4/D8.1）；新建 `WebAPI/qa_store.py`（psycopg2 裸 SQL，对齐 `watchlist_store` 模式，PG 不可用返回 503、不内存回退）；`routers/qa.py` 原 5 路由真现并全部挂 `get_current_user`——ask 按当前用户写入 `user_id`，list/star/batch-star/delete-unstarred 按当前用户过滤（batch 按 `ids + user_id`）、打星校验归属；验证：重启后记录保留，用户 A 看不到用户 B 的记录，B 的批量打星/删除不影响 A。现状：`WebAPI/routers/qa.py` 仅 5 个 stub 路由（无表/DAO，ask 返回空 answer、list 返回 `[]`）；`auth.py get_current_user` 尚无业务路由使用
- [x]  5.2 系统提示词端点：`GET/PUT /api/qa/system-prompt` 读写 `user_setting(key='system_prompt')`，空值回退 D8.3 内置默认提示词常量；验证：PUT 后 GET 返回新值，A/B 互不影响
- [x]  5.3a 供应商预设 + `llm_client`：`llm_provider` DAO（active 唯一、事务内先清后置）、`WebAPI/llm_client.py` 的 `complete()`/`complete_stream()`（`requests` 调 OpenAI 兼容 `/chat/completions`）、`config.py` 增 `LLM_BASE_URL/LLM_API_KEY/LLM_MODEL/LLM_TIMEOUT`、测试连接端点（`manage` 权限）、列表 api_key 脱敏（尾 4 位）；验证：PG 激活预设 > env > 503 三级解析正确，切换预设后下一次提问即时走新配置
- [x]  5.3b ask SSE：`POST /api/qa` 改 `text/event-stream`（`delta`/`done`/`error` 三事件，D8.2）——读当前用户 system_prompt → 结构注入裁剪层（复用 `_compute_chan`+`serialize_chan`：最近 20 K 线/10 笔/3 段/2~3 中枢/5 买卖点，`is_sure=false` 标注未确认，失败静默跳过）→ `complete_stream` 消费；仅生成成功后落库才发 `done`，块间 30s 空闲超时，LLM 失败发 `error` 不落库；验证：`curl -N` 收到连续 `delta` 与最终 `done`、中途掐断不产生残缺记录、无 code 或周期无数据时正常降级

## 6. 前端：流式问答与配置管理 UI（design D8）

- [x]  6.1 提问携带上下文：`KLineView.vue` 给 `<QaPanel>` 补 `:code="code" :period` props（现 `<QaPanel v-else />` 无 props 为已知缺口），`askQuestion({question, code, period})`；验证：Network 中提问请求含当前股票与周期
- [x]  6.2 流式回答对话框：ask 改 `fetch` + `ReadableStream` 解析 SSE（axios 无法读流），弹窗内实时追加 `delta` 文本，`done` 更新最终回答并刷新记录列表，`error` 展示错误且不入列表；验证：发送后弹窗逐段出字、完成后列表出现该条、中断无残缺记录
- [x]  6.3 系统提示词对话框：问答 Tab「提示词」入口，GET/PUT `/api/qa/system-prompt`，展示/编辑/恢复默认；验证：修改后新提问按新提示词，跨会话仍在、按用户隔离
- [x]  6.4 mock 升级（`mock/handlers/qa.ts`）：记录按当前登录测试账号隔离 + SSE 假流式（分片延迟发 `delta`/`done`）；验证：mock 模式下流式对话框正常、测试账号间记录互不可见（原 4.2 的增量）
- [x]  6.5 `/system` 供应商管理 UI：预设列表（api_key 脱敏）/ 新增 / 激活 / 删除 / 测试连接，`manage` 权限显隐（对齐既有 RBAC 按钮约定）；验证：新增并激活后提问走新供应商，无权限账号看不到入口
