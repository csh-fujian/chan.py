## Why

买卖点系统已有确认状态维度（`is_sure`，`bsp-sure-annotation`），但只有一个二元切面（确认/未确认），用户在 K 线页与买卖点页无法回答「这个买点现在是哪个确认阶段、离定型还有多远」。本变更把「确认阶梯」补全为四级的单一语义维度：L1（小级别区间套佐证）→ L2（虚笔候选，分型成立）→ L3（背驰预警）→ L4（确认买卖点），并为每级挂上仓位指引（1/4 观察仓 / 1/2 / 满仓），让页面同时回答「在哪一级、该配多少仓」。

背景：K 线页 `chan_bsp` 覆盖层目前不区分确认状态（后端 `is_sure` 已下发但前端构造 `ChanBspMeta` 时丢弃，查证于 2026-10-08 会话）；买卖点页有未确认灰 tag 但无级别维度；L1/L3 的判定原料（小级别买卖点流、笔 MACD 力度）计算内核均已内建但未被落库/展示链路使用。

## What Changes

- **级别推导（WebAPI 层，不动计算内核）**：买卖点每条记录新增单一 `ladder` 字段（`L1`~`L4`），按已确认状态 + 背驰指标 + 小级别共振推导：
  - **L4 确认买卖点**：`is_sure=true`（水位线口径不变）
  - **L3 背驰预警**：`is_sure=false` 且所在笔 MACD 力度对比触发背驰（复用 `CBi.cal_macd_metric`）
  - **L2 虚笔候选**：`is_sure=false` 且依托虚笔/虚段成立（分型已确认、笔未定型）
  - **L1 小级别区间套**：本级别买卖点 + 指定子级别（日线→30 分钟）同向买卖点共振——作为独立佐证标记，不独立成信号记录
  - 仓位指引为级别的展示属性（L1/L2→1/4 观察仓、L3→1/2、L4→满仓），不参与判定
- **K 线主图 hover**：鼠标悬浮买卖点标记（`chan_bsp`）时展示 tooltip：当前级别（L1-L4）+ 各级说明 + 仓位指引
- **买卖点页新增「级别」列**：结果表展示每条记录的 `L1`-`L4` 级别信息
- **落库与序列化扩展**：`bsp_index` 加 `ladder` 列（幂等 DDL）；`/api/klines` 与 `GET /api/bsp` 响应携带 `ladder`
- **mock 数据同步**：MSW handlers + 数据补 `ladder` 样例

## Capabilities

### New Capabilities

（无——级别推导是买卖点索引的维度扩展，归入既有 `bsp-index`；页面行为归入 `bsp-page`）

### Modified Capabilities

- `bsp-index`（delta 落于未归档变更 `bsp-page-change` 首次定义的路径，与 `bsp-sure-annotation` 同模式）：「历史买卖点查询」「日终买卖点索引」需求变更——索引每行携带确认阶梯级别（L1-L4 单一字段），查询响应携带该字段
- `bsp-page`（同上）：「查询与结果列表」需求变更——结果表新增「级别」列，展示 L1-L4 与仓位指引
- `kline-unsure-visual`（`kline-unsure-dashed` 首次定义）：买卖点标记的确认状态可视化——悬浮买卖点图标展示当前级别与四级说明（tooltip）

## Impact

- **后端**：`WebAPI/bsp_sure.py` 或同级新增级别推导函数（L4 复用 `bsp_is_sure`；L3 用 `CBi.cal_macd_metric`；L1 用小级别 `CChan` 计算）、`WebAPI/incremental_engine.py`（`_extract_bsp_rows` 落库带 `ladder`）、`WebAPI/bsp_store.py`（DDL + 查询投影）、`WebAPI/routers/bsp.py`（响应字段）、`WebAPI/serializer.py`（`_serialize_bsp` 补字段 + L1 小级别计算接线）、`WebAPI/chan_service.py`（小级别计算入口，`lv_list` 支持子级别）、`WebAPI/update.sql`（幂等 DDL）
- **前端**：`Front/src/components/charts/KLineChart.vue`（`ChanBspMeta` 补 `ladder`，不再丢弃）、`Front/src/components/chan/chan_bsp.ts`（hover tooltip）、`Front/src/views/bsp/BspView.vue`（级别列）、`Front/src/api/types.ts` + `api/modules/bsp.ts`（契约）、`Front/src/mock/data/bsp.ts` + `kline.ts`（样例）
- **数据库**：PG `bsp_index` 加 `ladder VARCHAR(2)` 列（幂等 DDL，遵循 CLAUDE.md DDL 规范）
- **计算内核**：**不修改** `CChan`/`CBSPointList`/`CBiList`——L2/L3/L4 推导全部在 WebAPI 层复用现有 API（`is_sure`、`cal_macd_metric`、多级别 `lv_list`）
- **关联变更**：`bsp-page-change`（已完结，delta 承接方）、`kline-unsure-dashed`（已完结，`kline-unsure-visual` 的可视化语义在此扩展）；`regression-testing-change`（回测口径的分级触发设计与此四级语义对齐，不互相依赖）
