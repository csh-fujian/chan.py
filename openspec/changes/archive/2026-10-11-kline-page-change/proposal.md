## Why

K 线分析页目前只有「看」的能力：能展示 K 线与缠论结构，但用户无法就地管理自选、看不到股票的完整板块归属（行业/地区/概念，且行业常被截断为前 3 个）、也没有向大模型提问的入口。要让 K 线页从「看图」升级为「看图 + 自选管理 + 板块识别 + 问答」的一体化分析工作台，需要在页面上补齐这三块能力并给出合理的排版。

## What Changes

- **自选管理**：在 K 线页对当前股票快速「加入自选 / 移出自选」，选择或新建目标分组；分组支持新建、重命名、删除。
- **标的详情**：展示当前股票所属的**全部**行业、地区、概念（全量，不截断），补足现有仅「行业 ≤ 3」的展示缺口。
- **大模型问答**：输入框提问 → 大模型**流式**解答（弹窗实时展示增量与最终回答）；**系统提示词按用户可配置**（内置默认提示词，可修改/恢复默认）；提问自动注入当前股票的**缠论结构上下文**（结构不可得时静默降级）；LLM **供应商预设可切换**（cc-switch 式，管理员在 /system 管理，激活即时生效）；生成问答记录列表（**按用户隔离**，展示内容与时间）；点击记录弹窗展示提问与回答全文；支持单条/批量打星（收藏标识）、一键删除未打星记录；问答内容持久化到 PG（含 `user_id`）。
- **页面排版**：K 线页新增可折叠左侧面板，以「标的 / 问答」两个 Tab 收纳上述能力（后续 `kline-metadata-change` 追加「股票信息」Tab），Tab 切换带内容缓存——切回时内容仍在；主图占剩余宽度。

## Capabilities

### New Capabilities

- `kline-watchlist`: 在 K 线页面对当前股票进行自选管理（加入/移出自选）与自选分组管理（新建/重命名/删除）。
- `stock-profile`: 展示股票所属的全部行业、地区、概念信息（全量展示）。
- `ai-qa`: 大模型问答能力。覆盖提问解答、问答记录列表、问答详情弹窗、打星/批量打星、一键删除未打星，以及问答内容的 PG 持久化。

### Modified Capabilities

<!-- 无：自选底层的分组/股票持久化模型已由 chan-stock-manage 的 watchlist 能力定义，本变更仅在其上新增「重命名分组」操作与 K 线页集成，不重复定义其 schema。 -->

## Impact

- **修改前端文件**：`front/src/views/kline/KLineView.vue`（左侧面板 + 自选/问答入口）、`front/src/api/types.ts`（新增 `StockProfile`/`QaRecord`，`Stock` 增 `region`/`concepts`）、`front/src/api/modules/watchlist.ts`（新增 `renameFolder`）、`front/src/mock/data/stocks.ts`（补 region/concepts）、`front/src/mock/handlers/*`（新增 profile/qa/rename handler）。
- **新增前端文件**：标的详情组件、问答面板组件（含记录列表/详情弹窗、流式回答对话框、系统提示词对话框）、`front/src/api/modules/stock.ts`、`front/src/api/modules/qa.ts`、`front/src/mock/data/qa.ts`、`front/src/mock/handlers/qa.ts`、系统管理页供应商预设管理组件。
- **后端（WebAPI 已落地，QA/LLM 部分待实现）**：`ai-qa` 路由（鉴权 + SSE 流式 + 系统提示词端点）+ `qa_record`/`user_setting`/`llm_provider` PG 表 + `WebAPI/llm_client.py`（OpenAI 兼容，供应商预设切换）、标的 profile 路由、自选重命名路由。
- **复用**：既有自选 API（folders/stocks CRUD）、`chan-stock-manage` 定义的 `watchlist_folder`/`watchlist_item`/`stock_industry` 模型、`chan-web-viewer` 的 FastAPI 栈。
- **不修改**：`CChan` 及其计算流水线；本变更主体为前端，后端部分与既有 WebAPI 规划协调落地。
