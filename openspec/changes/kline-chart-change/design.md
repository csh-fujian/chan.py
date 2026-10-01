## Context

见 proposal.md 了解动机。本变更的约束与现状（来自代码勘察与 klinecharts 9.8.12 源码验证）：

- 图表由 `Front/src/components/charts/KLineChart.vue` 创建：`initChart()` 中一次性 `setStyles`（硬编码暗色样式块），无 MA 指标、无主题机制；副图经 `createIndicator(name, false, {id: 'chan_sub_<name>'})` 创建，VOL 副图默认获得库内置 `VOL` 指标的 5/10/20 量均线。
- 缠论 overlay 在 `Front/src/components/chan/` 注册（`chan_bi/chan_seg/chan_zs/chan_bsp`），在 `applyResult()` 中按 `result.klines` + `ChanResult` 重建；`chan_bsp` 当前画 r=4 实心圆点 + 纯文字标签（买点 y+18 / 卖点 y-8，无 K 线感知）。
- 页面主题仅存在暗色 token（`design.css :root`），`element-overrides.css` 的 `html.dark` 块从未启用；主题需要覆盖全应用（含 ECharts：`views/bsp/NestingDrawer.vue` 等）。
- 监控数据已有 `GET /api/monitor` → `MonitorItem[]`/`CompletedItem[]`（`bsp_date`/`bsp_price`/`end_date`/`end_price`/`status`），前端尚无按 code 取用与绘点。
- 已验证的 klinecharts 9.8.12 能力（源码级）：
  - `createIndicator(v, isStack, {id})`：`id` 指向已存在 pane 时指标挂到该 pane（`candle_pane` 即主图）；`overrideIndicator(override, paneId)` 运行时改 `calcParams`/`styles`；`removeIndicator(paneId, name)` 移除。
  - 内置 `MA`：`calcParams` 默认 `[5,10,30,60]`，`regenerateFigures` 按参数动态生成线，线样式走指标 `styles.lines[]`（color/size/style/dashedValue 逐线可配）。内置 `VOL`：`calcParams [5,10,20]`，同机制。
  - `candle.type = CandleUpStroke`：`close > open → _createStrokeBar`（body `PolygonType.Stroke + borderColor`，即空心描边），否则 solid —— 正好是"涨红空心、跌绿实心"。
  - 指标柱样式 `bars[]` 为静态全局配置，但 figure 的 `styles(data, ...)` 回调可按 `kLineData` 逐柱返回 `{color, style, borderColor, ...}` —— 成交量柱逐柱空心/实心需自定义指标实现。
  - overlay：`registerOverlay` + `createPointFigures` 支持 `rect`/`line`/`circle` 图形与 `LineType.Dashed` 虚线；points 为 `{value, timestamp}` 自动换算坐标；`createOverlay(..., paneId)` 可挂在副图 pane。
  - 事件：`subscribeAction('onCrosshairChange', cb)` 可取十字光标所在 K 线数据；内置 candle tooltip 会随十字光标水平翻转位置，无法固定左上角。
- 进行中的 `chan-web-viewer`、`kline-page-change` 变更触碰同一批文件（`KLineChart.vue`、`KLineView.vue`、chan overlay），需协调实施顺序。

## Goals / Non-Goals

**Goals:**

- 主图均线与量均线的开箱默认 + 弹窗式增删改（量均线只改天数，主图均线可改颜色），配置持久化。
- 全应用明/暗主题及图表两套样式，切换即时生效并持久化。
- 买卖点/虚拟买卖点的标记体系重构：框型、间隙、虚线连接、左右排布。
- 主图/成交量/BOLL 副图统一红空心绿实心柱体；行情图例中文化并迁移至「标的」面板（随十字光标联动）。

**Non-Goals:**

- 不修改 `CChan` 计算流水线与 `WebAPI/` 后端；主题与图表配置仅存浏览器 localStorage。
- MACD 等动能类副图柱色不改（其红绿语义是柱体增减而非价格涨跌，现状已单独覆盖）。
- 按股票/周期独立的均线配置、配置云同步、图表设置云备份（backlog，参见 chan-web-viewer 范围边界）。
- 明亮主题的具体色值打磨（初版以暗色 token 镜像推导，视觉微调不改变行为契约）。

## Decisions

### D1. 均线配置：内置 MA/VOL + overrideIndicator + chartConfig store

主图 MA 以 `createIndicator({name:'MA', calcParams:[5,10,20,60], styles:{lines:[…]}} , false, {id:'candle_pane'})` 挂主图，配置变更走 `overrideIndicator(..., 'candle_pane')`（`regenerateFigures` 自动按新参数重建线），删空时 `removeIndicator('candle_pane','MA')`；VOL 同理作用于 `chan_sub_vol`。配置状态放新 Pinia store（如 `stores/chartConfig.ts`，localStorage 持久化）：`mainMA: {days, color}[]`（默认 5/10/20/60 + 四色）、`volMA: {days}[]`（默认 5/10/20）。`KLineChart.vue` watch store 后调用 override，切换股票/周期由 `applyResult` 统一重放。

**备选**：自研均线计算与绘制 —— 放弃，库指标已支持参数化与逐线配色，自研只增加维护面。配置存组件 local state —— 放弃，不满足刷新持久与跨周期一致。

### D2. 配置入口：顶栏按钮 + 弹窗组件；量均线按钮为 VOL pane 上的 HTML 浮层

- 主图均线配置：`KLineView.vue` 顶栏（副图指标 popover 之后）加按钮，弹出新组件 `components/kline/MaConfigDialog.vue`（`el-dialog`，行式列表：天数输入 + `el-color-picker` + 删除，尾行新增；校验天数 ≥1 整数且不重复）。
- 量均线配置：因 pane 是 canvas，按钮实现为**图表容器内绝对定位的 HTML 浮层**，按 `subIndicators` 顺序与 pane 高度（130px）+ resize 计算 VOL pane 右上角位置，VOL 不在副图列表时隐藏；点击打开 `VolConfigDialog`（仅天数增删改，同样校验唯一）。

**备选**：量均线配置合并进顶栏同一弹窗 —— 放弃，需求明确要求按钮位于成交量副图内。用 KLineChart pane 自绘按钮 —— 放弃，库无 pane 内 DOM 注入点，事件命中实现复杂。

### D3. 主题：`data-theme` 属性 + CSS token 双主题 + 图表样式工厂 + overlay 调色板

- 新 `stores/theme.ts`（`theme: 'dark' | 'light'`，localStorage 持久化），`Topnav.vue` 全局切换入口；应用时设 `document.documentElement.dataset.theme`。
- `design.css` 将现有 `:root` 值迁到 `:root[data-theme='dark']`，新增 `:root[data-theme='light']` 覆盖（背景/文字/边框/面板 token）；`element-overrides.css` 删除死代码 `html.dark`，Element Plus 明亮态用其默认浅色变量 + 必要的 `--el-*` 覆盖，暗色态维持现有覆盖。全站组件只消费 token，排查并替换散落硬编码 hex（含 `KLineChart.vue` 的 `UP_COLOR` 常量、chan overlay 调色板）。
- 图表侧：把现有 `setStyles` 暗色块重构为**样式工厂** `getChartStyles(theme)`（暗色 = 现状逐字段迁移；明亮 = 浅背景、深色轴字、浅网格、对比度足够的十字光标，涨跌语义色不变），主题切换时 `chart.setStyles(getChartStyles(t))`；overlay 颜色抽到 `components/chan/palette.ts`（按 theme 返回语义色），切换后 `clearChanOverlays + 重建`（与 `applyResult` 同路径）。
- ECharts：现有使用点（`NestingDrawer.vue` 等）watch 主题 store，按 `init(el, themeName)` 重建或 `setOption` 刷新配色。

**备选**：跟随 Element Plus 的 `html.dark` class —— 放弃，现项目未使用且 KLineChart/overlay 不受其影响，双轨更乱；CSS `prefers-color-scheme` 自动 —— 放弃，需求是显式用户切换且要持久化。

### D4. 柱体样式：CandleUpStroke + 自定义 VOL 指标 + BOLL 副图蜡烛 overlay

- **主图**：`candle.type` 改为 `CandleType.CandleUpStroke`，`bar.upColor/upBorderColor` = 红、`downColor/downBorderColor` = 绿（wick 取对应 border 系），主题工厂两套各配一次。
- **成交量**：注册**同名覆盖** `registerIndicator` 替换内置 `VOL`：保留 `calcParams`+`regenerateFigures` 量均线逻辑，volume figure 的 `styles(data,...)` 回调逐柱返回 —— 上涨柱 `{style:'stroke', borderColor:红, borderSize:1, color:红}`（空心），下跌柱 `{style:'fill', color:绿}`（实心），`bars[0]` 仅作默认兜底。
- **BOLL 副图 K 线柱**：新建 overlay（如 `sub_candle`）挂到 `chan_sub_boll` pane：points 按每根 K 线 `[open, high, low, close]` 四点（`{value, timestamp}`）取坐标，`createPointFigures` 内按 4 点一组画影线 `line` + 实体 `rect`（上涨：`PolygonType.Stroke` + 红边；下跌：`Fill` + 绿填充），宽度由相邻点 x 差推导 barSpace。BOLL 三条线保持库内置指标不动；overlay 随 `syncSubIndicators`/`applyResult` 同步创建/清除。

**备选**：BOLL 用自定义指标合并蜡烛 —— 放弃，指标 figure 类型不支持任意图形（仅 line/bar/rect/circle 且无 OHLC 属性组）；`CandleDownStroke` 手动切换 —— 放弃，语义相反且无法逐 pane 差异化。MACD 柱不改（Non-Goal）。

### D5. 缠论买卖点重绘：`chan_bsp` 矩形框 + K 线外间隙 + 虚线连接

`applyResult` 创建 `chan_bsp` 时，extendData 除现有 meta 外携带该点所在 K 线的 `high/low`（直接取自 `result.klines`）。`createPointFigures` 重写：

- 卖点：标记锚定 `high` 坐标上方 gap（如 8~12px）；买点：`low` 下方同 gap —— 保证与实体/影线无重叠（需求 4）。
- 标签画法（需求 6）：`rect`（圆角 + stroke_fill 底）包裹 `text` 类型标签，买红系卖绿系；替代现圆点+裸文字。
- 连接线（需求 7）：标记边缘到该 K 线 high/low 端点画 `line` figure，`LineType.Dashed`，买红卖绿。
- 同点多类型仍合并为一个标签（现有 `types[]` join 逻辑保留）。

**备选**：把间隙做成固定 y 偏移 —— 放弃，未验证与影线长度的关系，仍可能重叠；必须按 bar 的 high/low 计算。

### D6. 虚拟买卖点：独立 overlay `chan_vbsp`，数据取自 `/api/monitor`

- 数据流：`KLineChart.vue`（或 `KLineView`）在 `code` 变化时请求 `GET /api/monitor`，前端按 `code` 过滤（量小，不加后端参数；mock handler 保持不变）。`status==='monitoring'` → 买入点 `(bsp_date, bsp_price)`；`completed` → 买入点 + 卖出点 `(end_date, end_price)`。
- 渲染：新 `registerOverlay('chan_vbsp')`，与 `chan_bsp` 同规则做 K 线外间隙 + 红/绿虚线连接，标签用**圆形框**（`circle` + 内嵌 `text`）区分缠论矩形框（需求 6/7）。
- 左右排布（需求 5）：`applyResult` 同时握有 bsp 与 monitor 数据，构建 overlay 前检测同一 `time_key` 上是否共存 —— 共存时虚拟标记 x 向左偏移半个标记宽 + 2px、缠论标记保持 bar 中心偏右，保证并排不遮挡。

**备选**：合并进 `chan_bsp` overlay —— 放弃，两者数据源、生命周期（monitor 独立刷新）与框型不同，分开更清晰；后端新增标记接口 —— 放弃，`/api/monitor` 已含全部字段，本变更不动后端。

### D7. 行情图例：迁移至「标的」面板，共享状态驱动

`candle.tooltip.showRule` 置 `None`（内置 tooltip 仍禁用）。图例不再挂主图左上角，展示移至 `StockPanel.vue` 头部（名称/代码下方）：第一行现价行沿用现有 `sp-quote` 视觉（大号价格 + `ChangeBadge` 涨跌徽章），其后 时间/今开/最高/最低/量能 5 行沿用图例中文标签行样式与 CSS token。

数据流：`useChartLegend` 采集逻辑不变——`subscribeAction('onCrosshairChange')` 取悬停 K 线、容器 `mouseleave` 兜底回退最新一根、`prevClose` 由数据序列本地推导、`setSeries` 切换股票时清悬停防串号——仅将 `state` 提升为共享可观察（composable 模块级单例或轻量 Pinia store，非持久化）：`KLineChart.vue` 负责 attach/detach 写入，`StockPanel.vue` 只读渲染。涨跌幅度 = `(close-prevClose)/prevClose*100`，首根显示 `--`；`state` 为 null（K 线未就绪）时现价行回退 profile 报价、字段行显示占位（无需改数据源）。

**备选**：emit 上抛 `KLineView` 再 props 下传 —— 放弃，采集与展示可直接经共享状态解耦，无需 KLineView 介入图例数据管道；`candle.tooltip.custom` 回调 —— 放弃，位置随十字光标水平翻转、TooltipLegend 网格无法表达大号价格/徽章的异形排版，且无法跨组件渲染到标的面板；副图（VOL/MACD）的指标图例保持库内置不动。

### D8. 需求确认结论（写入实施说明）

- klinecharts **支持**主图均线任意天数增删与逐线颜色（`MA.calcParams` + `styles.lines[]`）。
- klinecharts **支持**成交量均线天数增删改（`VOL.calcParams` + `overrideIndicator`）。
- 主图空心/实心由 `CandleUpStroke` 原生支持；成交量逐柱空心需自定义 VOL 指标；BOLL 蜡烛用 overlay 实现。

## Risks / Trade-offs

- **BOLL 副图坐标轴可能不含蜡烛极值导致裁剪** → 实施时先验证 overlay `{value, timestamp}` 点是否参与 pane 轴自动缩放；若不参与，在自定义 BOLL calc 中附加不可见的 hi/lo 极值线（`figure` 透明色）撑开量程。
- **亮色主题遗漏硬编码色** → 实施任务包含全量 hex 盘点（grep `#[0-9A-Fa-f]{3,8}` 与 `rgba(`）+ 逐视图走查清单；语义色（红涨绿跌）显式豁免。
- **同名 `registerIndicator('VOL')` 覆盖依赖库扩展点** → klinecharts 版本已在 package.json 锁 `^9.8.10`（实际 9.8.12），升级时回归量均线与柱体样式；自定义实现仅改 `styles` 回调，`calc`/`regenerateFigures` 沿用内置逻辑减少分叉。
- **与进行中变更的文件冲突**（chan-web-viewer / kline-page-change 同改 `KLineView.vue`、`KLineChart.vue`）→ 实施前确认两变更状态，按最小 diff 拆分提交，冲突处以本变更新增行为为准、保留对方新增功能。
- **多标记同 bar 拥挤**（1 个缠论点 + 虚拟点，或多类型买卖点）→ 左右偏移解决虚拟/缠论共存；同向多点垂直堆叠偏移作为实施兜底（不改数据、只改绘制偏移）。
- **图例跨组件展示** → 采集在 `KLineChart.vue`、展示在 `StockPanel.vue`，共享状态须与生命周期对齐：`KLineChart` 卸载时 detach、切换股票/周期时清悬停防串号；hover/latest 两态与数据未就绪回退均须覆盖（spec 场景已含），否则丢失十字光标读数能力。
- **量均线按钮的绝对定位在 pane 高度/顺序变化时漂移** → 位置计算复用 `syncSubIndicators` 后的布局状态并绑定 resize，VOL 隐藏即隐藏按钮。

## Migration Plan

纯前端行为变更，无数据库/后端迁移。上线即生效：新增 localStorage 键（主题偏好、图表配置），无历史数据需转换；默认值保证首次打开 = 现状暗色 + 默认均线。回滚 = revert 前端提交（旧版忽略新 localStorage 键）。建议实施顺序：D1/D2（均线配置）→ D4（柱体）→ D5/D6（标记）→ D7（图例）→ D3（主题，触面最广最后合入），每步独立可回归。

## Open Questions

- 明亮主题的精确色板（背景层级、网格、轴线灰阶）：初版按暗色 token 镜像推导，视觉打磨在实施中确认，不改变行为契约。
- 虚拟买卖点圆形框内标签文案（「买」/「卖」 vs 来源买卖点类型如 1B）：spec 仅约束圆形框与位置，文案在实施时定稿。
- `bsp_date`（日级时间戳）在 1/5/15 分钟周期下的落点粒度：按时间轴映射即可用，是否吸附到所在分钟 bar 由实施时体验决定。
