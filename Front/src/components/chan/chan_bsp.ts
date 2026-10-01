// chan_bsp.ts — 买卖点覆盖层（圆角矩形框标签 + K 线外间隙 + 虚线连接）
// kline-chart-change D5 / 任务 3.1、3.2：
// - 标签画法（需求「矩形框」）：rect（圆角 + stroke_fill 半透明底）包裹 text，
//   买红系 / 卖绿系；替代旧圆点 + 裸文字。同点多类型仍合并为一个标签。
// - 间隙（需求「标记与 K 线的间隙」）：卖点标记锚定所在 K 线 high 上方、买点锚定
//   low 下方，留 BSP_MARKER_GAP（10px，spec 8~12px）可见间隙，不与实体/影线重叠。
// - 连接（需求「虚线连接」）：标记近侧边中点 → K 线 high/low 端点画 Dashed 虚线，
//   买红 / 卖绿。
// - 同 bar 同向多标记（任务 3.2）：stackIndex 沿远离 K 线方向垂直错位
//   （标记高 + STACK_GAP），全部可见且互不遮挡；多类型合并标签仍只算一个标记。
// - 共存左右排布（任务 4.3）：extendData.xOffset 按像素平移标记中心
//   （虚拟标记左移 / 缠论标记右移，由 KLineChart.rebuildBspOverlays 统一计算）。
//
// 坐标换算（沿用 chan_*.ts 模式）：overlay.points 每点 {value, timestamp} 由
// klinecharts 换算成 coordinates（timestamp→x、value→y）；所在 K 线 high/low 随
// extendData 携带，经 createPointFigures 参数的 yAxis.convertToPixel（value→y）
// 得到影线端点像素，间隙与虚线均以该端点为基准。
import { registerOverlay, utils, type OverlayFigure } from 'klinecharts'
import { bspLabels } from '@/utils/bsp'
import { getChanPalette } from './palette'

/** 买卖点 overlay 元数据（存于 extendData） */
export interface ChanBspMeta {
  isBuy: boolean
  types: string[]
  /** 在 overlay.points / coordinates 中的索引 */
  pointIndex: number
  /** 所在 K 线 high（价位，配合 yAxis.convertToPixel 换算卖点锚点） */
  high: number
  /** 所在 K 线 low（价位，配合 yAxis.convertToPixel 换算买点锚点） */
  low: number
  /** 同 bar 同向多标记的垂直堆叠序号（0 = 基准，任务 3.2） */
  stackIndex: number
  /** 共存左右排布的 x 偏移（px；0 = 居中，任务 4.3） */
  xOffset: number
}

/** 买点颜色 — design.css --rise；卖点 — --fall；框底半透明 — 均取 palette（任务 6.3，语义色主题不变） */

/** 标记边缘与 K 线 high/low 的可见间隙（px，spec 要求 8~12） */
export const BSP_MARKER_GAP = 10
/** 同 bar 同向多标记垂直错位的附加间隙（px） */
const STACK_GAP = 4
const FONT_SIZE = 11
const FONT_WEIGHT = '600'
const FONT_FAMILY = 'JetBrains Mono, monospace'
const PAD_X = 6
const PAD_Y = 3
/** 框高 = 字号 + 上下 padding，与文本量宽无关 */
const BOX_HEIGHT = FONT_SIZE + PAD_Y * 2

/** 标签文案（多类型合并为一个标签，绘制端与布局端共用，保证框宽一致） */
export function chanBspLabel(types: string[], isBuy: boolean): string {
  const labels = bspLabels(types, isBuy)
  return labels.length > 0 ? labels.join('/') : isBuy ? 'B' : 'S'
}

/** 测量标签矩形框尺寸（构建期算共存 xOffset、绘制期画框共用） */
export function bspBoxSize(label: string): { width: number; height: number } {
  return {
    width: Math.ceil(utils.calcTextWidth(label, FONT_SIZE, FONT_WEIGHT, FONT_FAMILY)) + PAD_X * 2,
    height: BOX_HEIGHT,
  }
}

let registered = false

/** 注册买卖点覆盖层。幂等，重复调用安全。 */
export function registerChanBsp(): void {
  if (registered) return
  registered = true

  registerOverlay({
    name: 'chan_bsp',
    needDefaultPointFigure: false,
    needDefaultXAxisFigure: false,
    needDefaultYAxisFigure: false,
    createPointFigures: (params): OverlayFigure[] => {
      const { overlay, coordinates, yAxis } = params
      const meta = overlay.extendData as ChanBspMeta[] | undefined
      if (!meta || meta.length === 0 || !coordinates || coordinates.length === 0) return []
      if (!yAxis) return []

      // 先收集虚线，再收集框体：堆叠标记的连接线从下方框体后穿过，不遮挡标签
      const lineFigures: OverlayFigure[] = []
      const boxFigures: OverlayFigure[] = []
      const pal = getChanPalette()

      meta.forEach((m) => {
        const c = coordinates[m.pointIndex]
        if (!c) return

        const color = m.isBuy ? pal.buy : pal.sell
        const fill = m.isBuy ? pal.buyFill : pal.sellFill
        const label = chanBspLabel(m.types, m.isBuy)
        const { width, height } = bspBoxSize(label)

        // 值→y：所在 K 线 high/low 的像素端点（y 轴向下增长，high 的 y 更小）
        const highY = yAxis.convertToPixel(m.high)
        const lowY = yAxis.convertToPixel(m.low)

        // 同向多标记沿远离 K 线方向错位（任务 3.2）
        const stackOffset = m.stackIndex * (height + STACK_GAP)
        // 标记中心 x：共存时按 xOffset 平移（任务 4.3）
        const cx = c.x + m.xOffset

        // 卖点锚定 high 上方、买点锚定 low 下方，与影线端点留出 GAP 间隙
        let boxTop: number
        if (m.isBuy) {
          boxTop = lowY + BSP_MARKER_GAP + stackOffset
        } else {
          boxTop = highY - BSP_MARKER_GAP - stackOffset - height
        }
        const boxBottom = boxTop + height

        // 虚线连接：标记近侧边中点 → K 线 high/low 端点（买红卖绿）
        const anchorY = m.isBuy ? lowY : highY
        const edgeY = m.isBuy ? boxTop : boxBottom
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

        // 圆角矩形框：stroke_fill 半透明底 + 同色描边
        boxFigures.push({
          type: 'rect',
          attrs: {
            x: cx - width / 2,
            y: boxTop,
            width,
            height,
          },
          styles: {
            style: 'stroke_fill',
            color: fill,
            borderColor: color,
            borderSize: 1,
            borderStyle: 'solid',
            borderDashedValue: [2, 2],
            borderRadius: 3,
          },
        })

        // 文字标签居中于框内
        boxFigures.push({
          type: 'text',
          attrs: {
            x: cx,
            y: boxTop + height / 2,
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
      return [...lineFigures, ...boxFigures]
    },
  })
}
