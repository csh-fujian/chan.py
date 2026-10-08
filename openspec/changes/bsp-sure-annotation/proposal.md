## Why

买卖点索引存在契约不对称：`chan_structure`（笔/段/中枢）落库时只保留 `is_sure=true` 的确认前缀，而 `bsp_index` 落库的是 `getSortedBspList()` 全集——包含基于虚段（未确认段）形成的买卖点。这些未确认买卖点在后续 K 线到来后可能消失（笔被合并、段被重画），但当前买卖点页面把它们与已确认买卖点无差别并列展示，用户无法区分「定型信号」与「预览信号」，存在误读风险（把可能消失的点当作回测/决策依据）。

用户已裁定策略：**保留全集入库 + 加 `is_sure` 列 + 前端标注**（方案 B），不丢信号、页面可见最新预览状态。

## What Changes

- `CBS_Point` 确认状态推导：`WebAPI/incremental_engine.py` 落库时从 `bsp.bi` 侧推导确认位（`bi.parent_seg.is_sure` 或水位线 `last_sure_pos` 口径），`bsp_index` 每行携带 `is_sure` 布尔值
- `bsp_index` 表加 `is_sure BOOLEAN` 列（`WebAPI/update.sql` 幂等 DDL 追加，按 CLAUDE.md 数据库变更规范）
- 查询 API：`GET /api/bsp` 响应行携带 `is_sure`；查询参数增可选 `sure` 过滤（`confirmed`/`preview`/缺省=全部）
- 前端买卖点页：未确认行加「未确认」视觉标签；查询表单增确认状态筛选
- K 线页 `/api/klines` 的 `bsp` 序列化同步携带 `is_sure`（对齐 `bi`/`seg` 已带该字段的契约）

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `bsp-index`: 「历史买卖点查询」「日终买卖点索引」需求变更——索引记录携带确认状态、查询支持按确认状态过滤

## Impact

- **后端**：`WebAPI/incremental_engine.py`（`_extract_bsp_rows` 推导 is_sure）、`WebAPI/bsp_store.py`（表 DDL + `query_bsp` 过滤）、`WebAPI/routers/bsp.py`（参数 + 响应字段）、`WebAPI/serializer.py`（`_serialize_bsp` 补字段）、`WebAPI/update.sql`（幂等 DDL）
- **前端**：`Front/src/api/modules/bsp.ts`（类型 + 参数）、`Front/src/views/bsp/BspView.vue`（标签 + 筛选）、`Front/src/api/types.ts`（`BspPoint`/`BspRecord` 补 `is_sure`）、`Front/src/mock/`（MSW handlers + 数据补样例）
- **不动计算内核**：`ChanAnalyse/BuySellPoint/` 不加字段（推导在 WebAPI 层做，遵守「不修改 CChan 计算逻辑」约定）
- **关联变更**：`bsp-page-change`（已完结）的索引与查询体系扩展；K 线页 bsp 覆盖层的展示增强归姊妹变更 `kline-unsure-dashed` 的后续范畴（本变更只补数据字段，不改 `chan_bsp.ts` 绘制）
