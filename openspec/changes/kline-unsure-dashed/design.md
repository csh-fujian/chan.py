## Context

K 线页数据链路：`WebAPI/serializer.py`（D2 契约）已为每条 bi/seg 输出 `is_sure` 字段 → `Front/src/api/types.ts` 的 `Bi`/`Seg` 接口已声明该字段 → 但 `KLineChart.vue rebuildAllOverlays()` 构建 `chan_bi`/`chan_seg` overlay 时仅取 `{timestamp, value}` 组 points，`is_sure` 被丢弃；绘制端 `chan_bi.ts`/`chan_seg.ts` 的 `createPointFigures` 固定 `style: 'solid'`，无任何条件分支。

现有 overlay 的元数据传递先例：`chan_zs`/`chan_bsp` 均通过 `overlay.extendData` 携带结构化元数据（`ChanZsMeta` 的 `level`+`startIndex` 数组模式），绘制端按 meta 逐元素差异化样式。线型 API 方面，klinecharts 的 line figure `styles` 支持 `style: 'solid' | 'dashed'` 与 `dashedValue: [n, m]`；注意 `style: 'solid'` 时 `dashedValue` 为惰性字段（不生效但必须存在，`IndicatorView.drawImp` 合并线段时缺失会崩溃，现有代码各处 solid 线均带 `[2, 2]` 兜底）。

`chan_zs` 已有的虚线先例是按**级别**区分（笔中枢虚线框、段中枢实线框），与本次按**确认状态**区分是正交维度，不冲突。

## Goals / Non-Goals

**Goals:**

- 建点端把 bi/seg 的 `is_sure` 传递到绘制端（extendData 元数据模式）
- 绘制端按 `is_sure` 切换 line figure 的 `style` 与 `dashedValue`，未确认元素虚线
- mock 数据补 `is_sure: false` 样例，演示与开发模式下可见效果

**Non-Goals:**

- 不改后端序列化（`is_sure` 已在契约中，无 DDL/API 变更）
- 不改中枢/买卖点覆盖层（中枢的 `ZS` 类型无 `is_sure` 字段、买卖点确认问题归姊妹变更 `bsp-sure-annotation` 处理）
- 不改缠论计算内核（`CChan`/`CBiList`/`CSegListChan`）
- 不做未确认元素的交互增强（如 hover 提示确认进度）——纯视觉区分

## Decisions

### D1: 元数据传递走 extendData 数组（沿 ChanZsMeta 模式）

**决策**：`rebuildAllOverlays` 构建单个 `chan_bi`/`chan_seg` overlay 时，除 points 外在 `extendData` 挂一个与 points 顺序对齐的元数据数组（每条 bi/seg 一项，含 `startIndex` 与 `isSure`），绘制端两两配对折线时按 meta 索引取线型。

**理由**：与 `chan_zs`/`chan_bsp` 的既有模式同构，单 overlay 批量绘制性能最优（避免每条笔/段单独 createOverlay 的 N 次注册开销）；points 与 meta 的索引对齐关系简单可验证。

**备选**：每条未确认笔/段单独创建一个 overlay——被否，覆盖层数量随数据增长（日线千根 K 线数百笔），`createOverlay`/`removeOverlay` 调用次数线性膨胀，且主题切换时全量重建成本更高。

### D2: 未确认元素「同色虚线」，线宽差异仅线段减细

**决策**：未确认笔与确认笔同色（`palette.bi`），`style: 'dashed'` + `dashedValue: [4, 3]`；未确认段同色（`palette.seg`）、虚线 `[6, 4]`、线宽由 2.2 降至 1.4，确认段维持现状实线。

**理由**：同色保证结构归属感（仍是笔/仍是段），线型单独承载确认语义，与缠论软件惯例（虚段画虚线）一致；线段双信号（虚线+减细）是因为段本身的视觉权重高于笔，仅虚线在密集笔段交叠时辨识度不足。笔不加线宽差异，避免与相邻确认笔的视觉断裂。

**备选**：未确认元素整体降低透明度——被否，暗色主题下低透明度灰线几乎不可见（palette.bi 暗色 `#9BA1A8` 本就是弱色）。

### D3: 虚线规格与图例联动

**决策**：`design.css` 的 HTML 图例（`kline-chart-change` 任务 6.3 建立的图例色卡）若含笔/线段线样，需同步补「未确认=虚线」示意；若图例当前不含笔/段线样（仅颜色卡），则不改。

**理由**：图例是用户理解线型语义的唯一入口；虚线语义若不在图例中解释，新用户无从得知虚线=未确认。实施时先盘点图例现状再决定，避免过度设计。

### D4: mock 数据补样例的策略

**决策**：`mock/data/kline.ts` 的 bi/seg 数组把尾部 1~2 条改为 `is_sure: false`（模拟「最新视角下尾部未确认」的真实形态），不新增单独的演示开关。

**理由**：真实计算结果中未确认元素天然出现在序列尾部（确认前缀之后的残余），mock 按此形态构造最真实；尾部样例在所有周期/股票的 mock 上生效，无需切换。

## Risks / Trade-offs

- [Mock 与真实数据形态偏差] mock 的固定 `is_sure: false` 样例与真实计算动态变化不同 → 仅影响演示观感，不影响契约；标注在 mock 文件注释中说明
- [虚线在低分屏/缩放下辨识度不足] `dashedValue: [4, 3]` 在浏览器缩放 150%+ 时可能近似实线 → 实施后人工走查常用缩放档位，必要时加大 dash 间距
- [points 与 meta 索引错位] extendData 数组与 points 顺序强耦合，后续维护者改动建点逻辑时易引入错位 → meta 字段命名带 `startIndex`（同 ChanZsMeta 惯例），并在建点函数处留注释说明对齐关系

## Migration Plan

纯前端变更，随前端发版生效，无部署顺序依赖、无数据迁移。回滚 = revert 前端提交即可。
