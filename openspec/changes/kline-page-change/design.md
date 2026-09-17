## Context

前端为 Vue3 + Vite + TypeScript（`front/`），MSW mock 驱动（`VITE_USE_MOCK=true`），真实后端（FastAPI + PostgreSQL）尚未落地。K 线页 `KLineView.vue` 当前为「顶栏（代码搜索/周期/副图指标/图例）+ 主图」单列布局。自选已存在独立页面 `WatchlistView.vue`（文件夹树 + 股票表格，支持新建/删除文件夹、加/移/移动股票），但缺少「重命名分组」；`Stock` 类型仅含 `industries`，无地区/概念。无任何大模型问答能力。

## Goals / Non-Goals

**Goals:**
- K 线页新增可折叠左侧面板，用「标的 / 问答」两 Tab 收纳自选管理、标的详情、问答三块能力，主图占剩余宽度。
- 标的详情补全地区/概念字段并全量展示板块信息。
- 自选在 K 线页提供「加入/移出 + 分组管理（含重命名）」。
- 问答完整闭环：提问 → 解答 → 记录列表 → 详情弹窗 → 打星/批量打星/一键删除未打星 → PG 持久化。

**Non-Goals:**
- 不重做独立的 `/watchlist` 页面（其全量浏览仍在原页）。
- 不改 `CChan` 计算逻辑、不碰 K 线/缠论序列化契约。
- 不实现股票搜索联想（归 `chan-web-viewer` backlog）。

## Decisions

### D1. K 线页布局：可折叠左侧面板 + 主图（两 Tab）
`KLineView` 根容器由单列改为 `display:flex` 行布局：左侧面板（固定宽约 320px，可折叠）+ 主图（`flex:1`）。面板用两个 Tab：

- **标的**：标的头部（名称/编码/股价/涨跌幅）+ 行业/地区/概念 + 自选管理（加入/移出 + 分组管理）。
- **问答**：输入框 + 回答展示 + 记录列表（每条右侧带星星收藏图标，点击亮起/熄灭）+ 工具栏（批量打星 / 一键删除未打星）。

顶栏新增「加入自选 ★」按钮（展开面板并聚焦自选区）与「AI 问答」按钮（展开面板并切到问答 Tab）。理由：三块能力都与「当前股票」强相关，收纳为同一上下文面板比散落多入口更聚合；Tab 避免单列面板过长。

备选：三块能力分开放到独立路由/独立页面——被否，用户明确要求「在页面增加」并合理排版。

### D2. 标的详情数据模型与接口
`Stock` 扩展 `region: string` 与 `concepts: string[]`；新增 `StockProfile`（= Stock + 全量板块字段）。新增 `GET /api/stocks/:code/profile` 返回 `StockProfile`。mock 侧在 `stocks.ts` 补 region/concepts，新增 handler。展示时行业/概念全量渲染（复用 `IndustryBadges` 的 badge 样式，地区用单 badge）。

理由：现有 `findStock` 仅用于自选搜索，profile 需独立契约以承载「全量板块」；地区为单值、行业/概念为多值。

### D3. 自选管理：复用 + 新增「重命名」
复用既有自选 API（`getFolders`/`createFolder`/`deleteFolder`/`addStock`/`removeStock`/`moveStock`）。新增 `renameFolder(id, name)` → `PATCH /api/watchlist/folders/:id`。「是否已自选」由 `getFolders()` 返回的 `codes` 推导（无需新查询）；「移出自选」= 对该股票所属分组调用 `removeStock`。底层 `watchlist_folder`/`watchlist_item` schema 复用 `chan-stock-manage` D1 定义，不重复建表。

理由：最小改动补齐「编辑分组（重命名）」缺口，避免与既有 watchlist 能力重复定义 schema。

### D4. 问答 API 契约与 PG schema
新增 PG 表：

```sql
qa_record (
  id SERIAL PRIMARY KEY,
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  starred BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
```

API 契约：

- `POST /api/qa` body `{ question, code?, period? }` → 调 LLM 生成回答并落库，返回完整 `QaRecord`。
- `GET /api/qa` → `QaRecord[]`（按 `created_at` 倒序）。
- `PATCH /api/qa/:id/star` body `{ starred }` → 单条打星/取消。
- `POST /api/qa/star` body `{ ids: number[], starred }` → 批量打星。
- `DELETE /api/qa/unstarred` → 删除所有 `starred=false` 的记录。

DAO 用 psycopg2 裸 SQL（对齐 `RecomputeCursor` 与 `chan-stock-manage` 约定）。

### D5. LLM 供应商可插拔
提问输入 = 问题文本 + 可选当前股票/周期上下文（`code`/`period`）；输出 = 回答文本。后端抽 `llm_client.py` 定义 `complete(prompt) -> str`，供应商与模型待定（对齐 `chan-stock-manage` D7 的待定项）；先定义输入/输出契约，供应商可插拔。

### D6. 前端 mock-first，后端后置
前端先以 MSW 落地：新增 `qa`/`stock` handler 与 mock 数据，`qa` mock 用延迟 + 预设回答模拟 LLM；记录在 mock 内以内存数组模拟 PG（`VITE_USE_MOCK=true`）。真实后端（D4/D5 的 FastAPI + PG）在 `WebAPI/` 落地时接入，前端切 `VITE_USE_MOCK=false` 即用真实接口。

## Risks / Trade-offs

- [与 chan-stock-manage 的 watchlist 能力重叠] → 本变更只新增「重命名」+ K 线页集成，schema/模型复用其定义；归档时协调合并，避免冲突。
- [LLM 供应商与模型未定] → 契约先行、供应商可插拔，不影响前端与接口层开发。
- [问答落 PG 但 WebAPI 未落地] → 前端 mock-first 独立推进；后端任务标记为「依赖 WebAPI 落地」可后置。
- [左侧面板挤压主图宽度] → 面板可折叠，默认展开；窄屏下折叠后主图占满宽度。

## Open Questions

- LLM 供应商与模型选择（与 `chan-stock-manage` D7 同步决定）。
- 问答是否默认携带当前股票/周期作为上下文（当前假设：作为可选参数透传，不强制）。
