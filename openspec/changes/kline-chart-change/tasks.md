## 1. 均线配置（D1/D2）

- [x] 1.1 新建 `Front/src/stores/chartConfig.ts`：`mainMA`（默认 5/10/20/60 + 四条互异颜色）、`volMA`（默认 5/10/20），localStorage 持久化；验证：devtools 中修改后刷新页面状态保持
- [x] 1.2 `KLineChart.vue` 主图 MA 接线：初始化时 `createIndicator({name:'MA', calcParams, styles.lines}, false, {id:'candle_pane'})`，watch chartConfig 变更走 `overrideIndicator(..., 'candle_pane')`、删空走 `removeIndicator`；验证：打开页面默认显示 5/10/20/60 四条均线，store 改动即时重绘
- [x] 1.3 量均线接线：对 `chan_sub_vol` pane `overrideIndicator({name:'VOL', calcParams: volMA}, 'chan_sub_vol')`；验证：改 `volMA` 后副图量均线集合立即变化
- [x] 1.4 新建 `Front/src/components/kline/MaConfigDialog.vue`（行式列表：天数输入 + 颜色选择 + 删除 + 新增行；校验天数 ≥1 整数、拒绝重复天数），并在 `KLineView.vue` 顶栏（副图指标 popover 之后）加配置按钮接线；验证：弹窗增删改颜色后主图即时生效，重复天数被拒绝并提示
- [x] 1.5 VOL pane 配置按钮浮层（按 `subIndicators` 顺序与 pane 高度计算右上角定位，resize/sync 后重算，VOL 隐藏则按钮隐藏）+ `VolConfigDialog.vue`（仅天数增删改、唯一校验）；验证：按钮始终贴合 VOL 副图右上角，操作后量均线更新
- [x] 1.6 均线配置回归：验证 spec「配置持久化与作用范围」全部场景——刷新后保持、切换股票与周期后一致生效

## 2. 柱体样式（D4）

- [x] 2.1 `KLineChart.vue` 主图 `candle.type` 改 `CandleType.CandleUpStroke`，`bar.upColor/upBorderColor` 红、`downColor/downBorderColor` 绿（色值先取语义常量，主题化留待任务组 6）；验证：主图上涨红空心、下跌绿实心、影线同色系
- [x] 2.2 注册同名自定义 `VOL` 指标（保留内置 `calcParams`/`regenerateFigures` 量均线逻辑，volume figure `styles(data,...)` 回调逐柱返回：上涨 `{style:'stroke', borderColor:红}`、下跌 `{style:'fill', color:绿}`）；验证：量柱涨红空心、跌绿实心，且 5/10/20 量均线仍正常计算显示
- [x] 2.3 新建 `sub_candle` overlay 并挂 `chan_sub_boll` pane：每根 K 线以 `[open,high,low,close]` 四点取坐标，画影线 line + 实体 rect（涨=Stroke 红边、跌=Fill 绿填充），随 `syncSubIndicators`/`applyResult` 同步创建与清除；验证：BOLL 副图显示与主图同规则的 K 线柱、BOLL 三线不受影响、蜡烛不被轴裁剪（若裁剪，按设计在 BOLL calc 附加不可见 hi/lo 极值线兜底）
- [x] 2.4 副图影响面回归：验证 MACD/RSI/KDJ 等其余副图指标与柱色语义保持不变

## 3. 缠论买卖点标记（D5）

- [x] 3.1 `KLineChart.vue` 创建 `chan_bsp` 时 extendData 携带该点所在 K 线 `high/low`；重写 `chan_bsp.ts` 绘制：标签改为 `rect` 圆角框包裹 `text`（买红系/卖绿系），卖点锚定 high 上方 gap、买点锚定 low 下方 gap，标记到 K 线端点画 `LineType.Dashed` 虚线（买红卖绿）；验证：卖点与上影线无重合、买点与下影线无重合，框与虚线颜色语义正确
- [x] 3.2 同 bar 多标记兜底偏移（多类型合并标签保留，同向多点垂直错位）；验证：同一 K 线存在多个买卖点时全部可见且互不遮挡

## 4. 虚拟买卖点（D6）

- [x] 4.1 监控数据接入：`code` 变化时取 `GET /api/monitor` 并按 code 过滤，`monitoring` → 买入点 `(bsp_date, bsp_price)`、`completed` → 买入点 + 卖出点 `(end_date, end_price)`；验证：三种状态（监控中/已完成/无记录）下数据映射正确，无记录不产生标记数据
- [x] 4.2 新建 `chan_vbsp` overlay：圆形框包裹标签（文案在实施中定稿）、与 K 线的上下外侧间隙、红/绿虚线连接，随 `applyResult` 重建；验证：spec「虚拟买卖点圆形框」与「虚线连接」场景全部通过
- [x] 4.3 共存左右排布：`applyResult` 检测同一 `time_key` 上缠论与虚拟标记共存，虚拟标记向左偏移、缠论标记居中偏右；验证：同 K 线共存时两标记左右并排、互不遮挡（spec「左右排布」场景）

## 5. 行情图例（D7，展示位置迁移至标的面板）

- [x] 5.1 新建图例组件挂图表容器左上：布局为 第一行收盘金额（大号字体、固定红色）、第二行涨跌幅度（百分比格式 xx%、涨红跌绿、首根无前收显示 `--`），其后 时间/今开/最高/最低/量能 中文标签；数据经 `subscribeAction('onCrosshairChange')` 取悬停 K 线、空值回退最新，`prevClose` 由 `result.klines` 本地推导；同时 `candle.tooltip.showRule` 置 `None`；验证：悬停切换读数、无悬停回退最新、涨跌幅度计算/格式/着色正确、内置 tooltip 不再重复显示
- [x] 5.2 图例样式全部走 CSS token（为任务组 6 主题化就绪）；验证：暗色主题下与现有观感一致、无硬编码色残留于该组件
- [x] 5.3 展示迁移：移除主图左上角图例挂载，`ChartLegend.vue` 改造为挂 `StockPanel.vue` 头部（名称/代码下方）——第一行保留现价行视觉（大号价格 + `ChangeBadge` 涨跌徽章，数据改为当前展示 K 线的收盘价与涨跌幅），其后 时间/今开/最高/最低/量能 5 行；验证：主图左上角不再显示图例，标的头部显示完整字段、明暗主题下样式正确
- [x] 5.4 光标联动与共享状态：`useChartLegend` 的 `state` 提升为共享可观察，`KLineChart.vue` 写、`StockPanel.vue` 读；现价行与 5 行统一随 `onCrosshairChange` 刷新、无悬停回退最新一根、首根无前收显示 `--`、K 线未就绪时现价行回退 profile 报价；验证：移动光标标的面板同步刷新、移出回退最新、切换股票/周期不串号、内置 candle tooltip 仍不显示

## 6. 明暗主题（D3，触面最广最后合入）

- [x] 6.1 `design.css` 现有 `:root` 迁至 `[data-theme='dark']` 并新增 `[data-theme='light']` token 集；`element-overrides.css` 删除死代码 `html.dark`；全量盘点替换散落硬编码 hex/rgba（grep `#[0-9A-Fa-f]{3,8}`，语义色豁免）；验证：切 `data-theme` 后页面 UI（顶栏/侧栏/各视图/弹窗）整套换肤、无暗色残留
- [x] 6.2 新建 `Front/src/stores/theme.ts`（`dark|light`，localStorage 持久化，`document.documentElement.dataset.theme` 应用）+ `Topnav.vue` 全局切换入口；验证：任意页面切换立即全局生效，刷新后保持所选主题
- [x] 6.3 `getChartStyles(theme)` 样式工厂（暗色=现有 setStyles 逐字段迁移，明亮=浅底/深轴字/浅网格，涨跌语义色不变），切换时 `setStyles`；overlay 颜色抽到 `components/chan/palette.ts` 按 theme 取色，切换后 clear + 重建全部 chan overlay；验证：主图/副图/缠论标记随主题即时切换，红涨绿跌、买红卖绿语义不变，无元素残留另一主题
- [x] 6.4 ECharts 使用点主题适配（`views/bsp/NestingDrawer.vue` 及盘点出的其余实例，watch theme 后重建或 setOption 刷新）；验证：切换主题后 ECharts 配色跟随、坐标文字可读
- [x] 6.5 明亮主题全站走查清单（11 个视图 + 全部弹窗 + 新图例 + MA/VOL/BOLL 柱与标记在浅底下的可读性）；验证：逐项勾检通过，对比度满足可读

## 7. 整体回归与协调

- [x] 7.1 按三个 spec 的 scenario 逐条走查（`kline-indicator-config` / `kline-theme` / `kline-chart-appearance`），记录通过/不通过；验证：全部 scenario 通过或列出偏差
- [x] 7.2 构建与类型检查：`cd Front && npm run build`（vue-tsc -b && vite build）通过；验证：无 TS 错误、无新增告警
- [x] 7.3 文件冲突检查：确认 `chan-web-viewer` / `kline-page-change` 对 `KLineView.vue`、`KLineChart.vue`、chan overlay 的改动状态，按最小 diff 协调；验证：`git status/diff` 中未覆盖对方已有功能，冲突项逐条记录
- [x] 7.4 手动端到端冒烟：加载股票 → 切周期 → 加副图 → 配均线 → 切主题 → 查监控标记与买卖点标记；验证：全流程无报错（console 干净）、视觉符合 spec
