// chan_vbsp.ts — 虚拟（模拟交易）买卖点覆盖层（圆形框标签 + K 线外间隙 + 虚线连接）
// kline-chart-change D6 / 任务 4.2：
// - 圆形框（需求「虚拟买卖点圆形框」）：circle + 内嵌 text，区分缠论 chan_bsp 的
//   矩形框。标签文案定稿「买」/「卖」（design.md Open Questions 收敛：单字入圆框
//   最紧凑，且与缠论 1B/2S 等拉丁标签天然区分）。
// - 间隙 / 虚线连接规则与 chan_bsp 一致：卖点锚定所在 K 线 high 上方、买点锚定
//   low 下方（BSP_MARKER_GAP），红/绿虚线连到 K 线 high/low 端点。
// - 同 bar 同向多点垂直错位、共存左右排布的 xOffset 平移，机制同 chan_bsp
//   （任务 3.2 / 4.3，由 KLineChart.rebuildBspOverlays 统一计算）。
//
// 坐标换算：points {value, timestamp} → coordinates（timestamp→x），
// K 线 high/low 随 extendData 携带，经 yAxis.convertToPixel（value→y）取锚点。
import { registerOverlay, utils, type OverlayFigure } from 'klinecharts'
import { getChanPalette } from './palette'

/** 虚拟买卖点 overlay 元数据（存于 extendData） */
export interface ChanVBspMeta {
  isBuy: boolean
  /** 在 overlay.points / coordinates 中的索引 */
  pointIndex: number
  /** 所在 K 线 high（价位，配合 yAxis.convertToPixel 换算卖点锚点） */
  high: number
  /** 所在 K 线 low（价位，配合 yAxis.convertToPixel 换算买点锚点） */
  low: number
  /** 同 bar 同向多标记的垂直堆叠序号（0 = 基准） */
  stackIndex: number
  /** 共存左右排布的 x 偏移（px；0 = 居中，任务 4.3） */
  xOffset: number
}

/** 买/卖标记色与圆框底 — 取 palette（任务 6.3，语义色主题不变） */

/** 圆框边缘与 K 线 high/low 的可见间隙（px，与 chan_bsp 同规格） */
const VBSP_MARKER_GAP = 10
/** 同 bar 同向多标记垂直错位的附加间隙（px） */
const STACK_GAP = 4
const FONT_SIZE = 12
const FONT_WEIGHT = '600'
const FONT_FAMILY = 'JetBrains Mono, monospace'
/** 圆框半径下限（单字标签时刚好容纳） */
const MIN_RADIUS = 11
/** 文字到圆框的内边距 */
const PAD_R = 6

/** 圆框内标签文案（设计定稿：模拟买 / 模拟卖 各取单字） */
export function vBspLabel(isBuy: boolean): string {
  return isBuy ? '买' : '卖'
}

/** 圆框半径（按标签量宽，绘制端与布局端共用） */
export function vBspRadius(isBuy: boolean): number {
  const halfText = utils.calcTextWidth(vBspLabel(isBuy), FONT_SIZE, FONT_WEIGHT, FONT_FAMILY) / 2
  return Math.max(MIN_RADIUS, Math.ceil(halfText) + PAD_R)
}

let registered = false

/** 注册虚拟买卖点覆盖层。幂等，重复调用安全。 */
export function registerChanVBsp(): void {
  if (registered) return
  registered = true

  registerOverlay({
    name: 'chan_vbsp',
    needDefaultPointFigure: false,
    needDefaultXAxisFigure: false,
    needDefaultYAxisFigure: false,
    createPointFigures: (params): OverlayFigure[] => {
      const { overlay, coordinates, yAxis } = params
      const meta = overlay.extendData as ChanVBspMeta[] | undefined
      if (!meta || meta.length === 0 || !coordinates || coordinates.length === 0) return []
      if (!yAxis) return []

      // 先收集虚线，再收集圆框：堆叠标记的连接线从下方圆框后穿过，不遮挡标签
      const lineFigures: OverlayFigure[] = []
      const circleFigures: OverlayFigure[] = []
      const pal = getChanPalette()

      meta.forEach((m) => {
        const c = coordinates[m.pointIndex]
        if (!c) return

        const color = m.isBuy ? pal.buy : pal.sell
        const fill = m.isBuy ? pal.buyFill : pal.sellFill
        const label = vBspLabel(m.isBuy)
        const r = vBspRadius(m.isBuy)

        // 值→y：所在 K 线 high/low 的像素端点
        const highY = yAxis.convertToPixel(m.high)
        const lowY = yAxis.convertToPixel(m.low)

        // 同向多标记沿远离 K 线方向错位
        const stackOffset = m.stackIndex * (r * 2 + STACK_GAP)
        // 标记中心 x：共存时按 xOffset 平移（虚拟左移，任务 4.3）
        const cx = c.x + m.xOffset

        // 卖点圆框底缘贴 high 上方 GAP、买点圆框顶缘贴 low 下方 GAP
        let cy: number
        if (m.isBuy) {
          cy = lowY + VBSP_MARKER_GAP + stackOffset + r
        } else {
          cy = highY - VBSP_MARKER_GAP - stackOffset - r
        }

        // 虚线连接：圆框近侧边缘 → K 线 high/low 端点（买红卖绿）
        const anchorY = m.isBuy ? lowY : highY
        const edgeY = m.isBuy ? cy - r : cy + r
        lineFigures.push({
          type: 'line',
          attrs: {
            coordinates: [
              { x: cx, y: edgeY },
              { x: c.x, y: anchorY },
            ],
          },
          styles: {
            color,
            size: 1,
            style: 'dashed',
            smooth: false,
            dashedValue: [3, 3],
          },
        })

        // 圆形框：stroke_fill 半透明底 + 同色描边
        circleFigures.push({
          type: 'circle',
          attrs: { x: cx, y: cy, r },
          styles: {
            style: 'stroke_fill',
            color: fill,
            borderColor: color,
            borderSize: 1,
            borderStyle: 'solid',
            borderDashedValue: [2, 2],
          },
        })

        // 文字标签居中于圆框内
        circleFigures.push({
          type: 'text',
          attrs: {
            x: cx,
            y: cy,
            text: label,
            align: 'center',
            baseline: 'middle',
          },
          styles: {
            style: 'fill',
            color,
            size: FONT_SIZE,
            weight: FONT_WEIGHT,
            family: FONT_FAMILY,
            backgroundColor: 'transparent',
            borderColor: 'transparent',
            borderSize: 0,
            borderStyle: 'solid',
            borderDashedValue: [2, 2],
            borderRadius: 0,
            paddingLeft: 0,
            paddingRight: 0,
            paddingTop: 0,
            paddingBottom: 0,
          },
        })
      })
      return [...lineFigures, ...circleFigures]
    },
  })
}
