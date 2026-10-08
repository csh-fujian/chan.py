## Why

K 线主图的缠论覆盖层（笔、线段）当前全部以实线绘制，无法区分「已确认」与「未确认（虚笔/虚段）」元素。后端序列化契约中 `Bi`/`Seg` 已携带 `is_sure` 字段（`serializer.py` D2 契约），但前端建点端 `KLineChart.vue rebuildAllOverlays()` 在构建 overlay points 时丢弃了该字段，绘制端 `chan_bi.ts`/`chan_seg.ts` 固定 `style: 'solid'`。用户在盘后回看或盘中查看时，无法感知哪些笔/段是尚未确认、后续可能被重画的临时结构，存在误读风险。

## What Changes

- K 线主图笔覆盖层（`chan_bi`）：未确认笔（`is_sure=false`）以同色虚线绘制（`dashedValue: [4, 3]`），确认笔保持实线
- K 线主图线段覆盖层（`chan_seg`）：未确认段（虚段，`is_sure=false`）以同色虚线、减细线宽绘制，确认段保持实线
- 建点端 `KLineChart.vue`：构建 bi/seg overlay 时把每条元素的 `is_sure` 写入 extendData（沿 `ChanZsMeta` 的 `startIndex` 数组模式），不再丢弃
- 序列化契约确认：后端 `/api/klines` 已输出 `bi[].is_sure`/`seg[].is_sure`（现状已满足，无后端改动），mock 数据补充 `is_sure: false` 样例供演示

## Capabilities

### New Capabilities

- `kline-unsure-visual`: K 线主图缠论笔/线段的确认状态可视化契约——未确认元素虚线、确认元素实线的渲染规则

### Modified Capabilities

（无——`kline-chart-appearance` spec 的需求未变更，本变更是新增能力面，不修改其既有 Requirement）

## Impact

- **前端**：`Front/src/components/charts/KLineChart.vue`（建点端，bi/seg points 构建）、`Front/src/components/chan/chan_bi.ts`、`Front/src/components/chan/chan_seg.ts`（绘制端线型分支）、`Front/src/mock/data/kline.ts`（mock 补未确认样例）、`Front/src/styles/design.css`（图例若需同步虚线规格）
- **后端**：无改动（`serializer.py` 已输出 `is_sure`，数据契约不变）
- **关联变更**：与 `kline-chart-change`（已完结）的 overlay 体系同构扩展；不触碰 `CChan`/`CBiList`/`CSegListChan` 计算逻辑
