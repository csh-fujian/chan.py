## 1. 建点端：is_sure 元数据传递

- [x] 1.1 `KLineChart.vue` `rebuildAllOverlays()` 构建 `chan_bi` overlay 时，在 extendData 挂元数据数组（每条笔一项：`startIndex` 对齐 points 索引 + `isSure`），并留注释说明 points/meta 对齐关系；验证：console 打印 overlay extendData，条数与笔数一致且尾部未确认笔 `isSure=false`
- [x] 1.2 同上改造 `chan_seg` overlay 构建（每条段一项：`startIndex` + `isSure`）；验证：同 1.1，条数与段数一致

## 2. 绘制端：线型分支

- [x] 2.1 `chan_bi.ts` `createPointFigures` 按 meta 取线型：`isSure=true` → `style: 'solid'`（现状）；`isSure=false` → `style: 'dashed'` + `dashedValue: [4, 3]`，颜色不变（`palette.bi`）；验证：主图未确认笔为虚线、确认笔为实线，两者同色
- [x] 2.2 `chan_seg.ts` `createPointFigures` 同改造：`isSure=false` → `style: 'dashed'` + `dashedValue: [6, 4]` + `size` 2.2→1.4；验证：虚段为虚线且线宽小于确认段、同色
- [x] 2.3 图例盘点与联动（design D3）：检查 HTML 图例是否含笔/段线样，含则补「未确认=虚线」示意项；验证：图例能解释虚线语义（若图例无笔/段线样则记录不改）

## 3. Mock 数据

- [x] 3.1 `mock/data/kline.ts` 把 bi/seg 数组尾部 1~2 条改 `is_sure: false`（并注释说明模拟真实「尾部未确认」形态）；验证：mock 模式下 K 线页尾部笔/段显示虚线

## 4. 验证与收尾

- [x] 4.1 按 `specs/kline-unsure-visual` 逐 scenario 走查（未确认笔/段虚线、确认实线、主题切换语义不变、撤销元素消失）；验证：全部 scenario 通过
- [x] 4.2 `cd Front && npm run build` 无类型错误；浏览器缩放 100%/125%/150% 人工走查虚线辨识度（design 风险项）
- [x] 4.3 `openspec validate kline-unsure-dashed --strict` 通过
