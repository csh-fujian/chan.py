# Proposal

## Why

K 线页当前只把买卖点作为背驰的「结果」呈现，用户无法在图上直接看到「最近一根笔/线段相对相邻同向段的力度是否衰减」。对盯盘用户而言，最近的背驰是最直接的转向提示，值得在结构线本体上直接标出，而不必等它演化为完整买卖点判据链。

## What Changes

- `/api/klines` 响应中每级 `bi[]` / `seg[]` 的**最后一个元素**新增 `is_divergence` 字段（`true` / `false` / `null`），表示「最近一笔/一段（含虚笔/虚段）相对相邻同向前一笔/段的力度是否背驰」。`null` = 不适用或未计算。
- 背驰判断口径：相邻同向前一元素直接比力度（笔 `bi[n-2]` vs `bi[n]`，段 `seg[-2]` vs `seg[-1]`），多指标 AND，阈值 `divergence_rate`。
- 判断依据完全复用缠论参数配置「是否背驰的技术指标」（`macd_algo`）与「背驰力度阈值」（`divergence_rate`），不新增配置项；改配置 → 重算后标注口径同步变化。
- `divergence_rate = inf`（完全不看力度对比）时该级别不计算、字段输出 `null`。
- 前端 K 线主图：被判为背驰的笔/线段在原线下垫一条更粗的半透明红色线（红色阴影/红晕效果），虚笔/虚段同样适用；非背驰元素渲染不变。
- 所有周期天然覆盖：字段在序列化层按级别计算，周期切换重新请求即得。
- 计算内核（`CChan`/`CBiList`/`CSegListChan`/`CZSList`/`CBSPointList`）零改动，只读 `CBi.cal_macd_metric` / `CSeg.cal_macd_metric` 既有接口。

## Capabilities

### New Capabilities

- `chan-divergence-visual`: K 线主图最近笔/线段的背驰判断与红色阴影标注契约——判断口径（相邻同向比较、多指标 AND、阈值与 inf 处理、量能类段级回退）、`/api/klines` 的 `is_divergence` 字段契约、前端红色阴影渲染与主题稳定性。

### Modified Capabilities

（无——既有 `chan-web-visualization` 的「缠论结构数据接口」需求未枚举字段级契约，新增可选字段不与其冲突；`kline-unsure-visual` 的线型语义不受影响。）

## Impact

- **后端**：`WebAPI/serializer.py`（`_serialize_bi` / `_serialize_seg` 末尾元素计算背驰，读取 `chan_config_store` 生效配置）；`Front` 无关的落库链路（`incremental_engine` / `bsp_store`）不受影响。
- **前端**：`Front/src/api/types.ts`（`Bi`/`Seg` 类型加可选字段）、`Front/src/components/charts/KLineChart.vue`（`biMeta`/`segMeta` 写入 `isDivergence`）、`Front/src/components/chan/chan_bi.ts` / `chan_seg.ts`（`createPointFigures` 垫红线）。
- **配置**：无 schema / DB 变更。
- **风险**：量能类指标（`volumn` 等）在段级别无 `cal_macd_metric` 分支，沿用买卖点链路的 `SEG_FALLBACK_MACD_ALGO`（`peak`）回退口径；红色与 A 股「红涨」色语义相近，靠「垫线阴影」形态而非纯色线条区分。
