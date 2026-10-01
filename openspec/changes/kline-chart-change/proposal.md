## Why

K 线页是核心分析界面，但图表当前不可配置：主图没有均线、成交量均线固定为库默认、无主题切换；缠论买卖点标记紧贴 K 线导致视觉重合、缺少模拟交易（监控）的买卖标记；柱体样式与行情图例仍是库默认形态（英文标签、无涨幅），不满足中文分析工作流与视觉辨识需求。

## What Changes

- **主图均线**：默认叠加 5/10/20/60 日均线；顶栏新增均线配置按钮，弹窗中可自定义增加、删除任意天数均线，并逐条修改颜色（已确认 klinecharts 9.8.12 的 `MA` 指标 `calcParams` 与 `lines[]` 样式支持该能力）。
- **成交量均线配置**：成交量副图内新增配置按钮，弹窗中可增加、删除、修改量能移动均线天数（默认 5/10/20，与 klinecharts `VOL` 指标默认一致）。
- **全应用主题切换**：支持黑夜（当前状态，默认）与明亮两种主题，覆盖页面 UI（顶栏、侧栏、各视图、弹窗）与图表（主图、副图、缠论 overlay、ECharts）；切换入口全局可用并持久化。
- **买卖点间隙与连接线**：缠论买卖点标记与 K 线之间增加间隙（不再与蜡烛重叠），并以虚线连接标记与对应 K 线——买点红色虚线、卖点绿色虚线。
- **模拟交易标记（虚拟买卖点）**：股票被加入监控（模拟买入）后，主图在对应位置显示买入标记；已完成监控的显示模拟卖出标记。虚拟买卖点用圆形框包裹，与同位置的缠论买卖点标记呈左右结构、互不重叠。
- **缠论买卖点框型**：缠论买卖点标签用矩形框包裹（替代当前纯文字+小圆点形态）。
- **柱体样式统一**：主图蜡烛、成交量柱、BOLL 副图新增的 K 线柱统一为上涨红色空心柱、下跌绿色实心柱（已确认 `CandleType.CandleUpStroke` 满足主图语义；成交量与 BOLL 柱需自定义绘制）。
- **行情图例迁移至标的面板**：主图左上角图例移除，改在「标的」tab 面板头部（名称/代码下方）展示——第一行保留现价行视觉（大号价格 + 涨跌幅度徽章，百分比格式、涨红跌绿），其后按 时间/今开/最高/最低/量能 中文展示（映射：time-时间、open-今开、high-最高、low-最低、volume-量能）；整块随主图十字光标联动（悬停显示该 K 线、无悬停回退最新一根），涨跌幅度按（收盘价 − 前收盘价）/ 前收盘价 × 100% 计算，首根无前收显示 `--`。

## Capabilities

### New Capabilities

- `kline-indicator-config`: 主图移动均线与成交量移动均线的用户配置能力。覆盖默认均线值、配置入口（顶栏按钮/副图内按钮）、配置弹窗（增删天数、逐线改色）、应用后图表即时生效与重载后保持。
- `kline-theme`: 全应用明/暗主题切换能力。覆盖两套主题的视觉定义范围（页面 UI + 主图/副图/缠论 overlay/ECharts）、切换入口、默认主题、切换持久化与刷新后生效。
- `kline-chart-appearance`: K 线图表渲染外观能力。覆盖缠论买卖点的矩形框形态与 K 线间隙、红/绿虚线连接、模拟买卖点的圆形框标记与左右排布、主图/成交量/BOLL 副图的红空心绿实心柱体、行情图例的中文标签与重排布局，及其在「标的」面板的展示与十字光标联动。

### Modified Capabilities

<!-- 无：openspec/specs/ 下现有四个能力（kline-persistence / kline-watchlist / stock-profile / ai-qa）的需求不因本变更改变。chan-web-visualization 尚在 chan-web-viewer 变更中未归档为正式 spec，本变更不修改该变更的文件，但其「K 线渲染 / 缠论结构叠加渲染 / 买卖点类型标签」条目与本变更有展示层交集，chan-web-viewer 归档时需按本变更结果同步。 -->

## Impact

- **前端（主要改动面）**：
  - `Front/src/components/charts/KLineChart.vue`：主图 MA 创建/参数覆盖、VOL 参数覆盖、明暗两套 `setStyles` 样式、柱体样式（`CandleUpStroke` 等）、图例数据采集与共享状态输出（展示位于 StockPanel 头部）、接入监控数据绘制虚拟买卖点。
  - `Front/src/components/kline/StockPanel.vue`、`Front/src/components/kline/ChartLegend.vue`、`Front/src/composables/useChartLegend.ts`：行情图例展示（现价行 + 字段行）、光标联动与共享状态。
  - `Front/src/components/chan/*.ts`（`chan_bsp.ts` 及注册入口）：买卖点矩形框/圆形框、K 线间隙与虚线连接、标记颜色主题感知。
  - `Front/src/views/kline/KLineView.vue`：顶栏均线配置按钮与弹窗入口、副图内配置按钮挂载。
  - 新增：均线配置弹窗组件、主题 store（Pinia）、BOLL 副图 K 线柱绘制（自定义 overlay 或指标）。
  - `Front/src/styles/design.css`、`Front/src/styles/element-overrides.css`：亮色主题 token 体系（含当前未启用的 `html.dark` 死代码处置）。
  - 全局布局 `Front/src/components/layout/Topnav.vue`：主题切换入口。
- **ECharts 视图**：`Front/src/views/bsp/NestingDrawer.vue` 等使用 ECharts 的图表随主题切换。
- **数据/mock**：虚拟买卖点复用 `GET /api/monitor`（`MonitorItem`/`CompletedItem` 的 `bsp_date`/`bsp_price`/`end_date`/`end_price`）；mock handler 可能增加按 `code` 过滤参数。主题偏好存 localStorage，无需后端。
- **不修改**：`CChan` 计算流水线、`WebAPI/` 后端、DuckDB 持久化。
- **与进行中变更的协调**：`chan-web-viewer`、`kline-page-change` 同样改 `KLineChart.vue` / `KLineView.vue` / chan overlay，实施时注意顺序与冲突。
