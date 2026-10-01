// subCandleOverlay.ts — BOLL 副图 K 线柱覆盖层（红空心 / 绿实心，与主图一致）
// kline-chart-change D4 / 任务 2.3：BOLL 副图显示状态下叠加 K 线柱。
//
// 实现方式（design.md D4）：overlay 挂 chan_sub_boll pane，points 按每根 K 线
// [open, high, low, close] 四个 {value, timestamp} 注入（同 timestamp → 同 x），
// klinecharts 自动换算 coordinates；createPointFigures 按 4 点一组：
// - 影线：两段 line（high→实体顶、实体底→low，跳过零长段），与主图
//   _createStrokeBar/_createSolidBar 的影线分段一致，空心实体内不穿影线；
// - 实体：rect，宽 = barSpace.gapBar（与主图蜡烛同宽）、居中于 bar 的 x；
//   上涨 → PolygonType.Stroke + 红边（空心），下跌 → PolygonType.Fill + 绿（实心），
//   平盘按下跌实心兜底。
// 涨跌方向由 extendData 携带的每根 {open, close} 判定（不依赖像素坐标）。
import {
  registerOverlay,
  PolygonType,
  type OverlayCreate,
  type OverlayFigure,
  type KLineData,
} from 'klinecharts'
import { getChanPalette } from '@/components/chan/palette'

/** 涨跌色取 palette（任务 6.3）：红涨绿跌语义色两套主题不变，绘制时实时读取 */

/** 每根 K 线的实体方向元数据（extendData，与 points 的 4 点一组对齐） */
export interface SubCandleBarMeta {
  open: number
  close: number
}

let registered = false

/** 注册 sub_candle 覆盖层。幂等，重复调用安全。须在 init() 之前调用。 */
export function registerSubCandleOverlay(): void {
  if (registered) return
  registered = true

  registerOverlay({
    name: 'sub_candle',
    needDefaultPointFigure: false,
    needDefaultXAxisFigure: false,
    needDefaultYAxisFigure: false,
    createPointFigures: (params): OverlayFigure[] => {
      const { overlay, coordinates, barSpace } = params
      const metas = overlay.extendData as SubCandleBarMeta[] | undefined
      if (!metas || metas.length === 0 || !coordinates || coordinates.length < 4) return []

      const figures: OverlayFigure[] = []
      const pal = getChanPalette()
      // points/coordinates 按 [open, high, low, close] 四点一组
      for (let i = 0, bar = 0; i + 3 < coordinates.length; i += 4, bar++) {
        const cOpen = coordinates[i]
        const cHigh = coordinates[i + 1]
        const cLow = coordinates[i + 2]
        const cClose = coordinates[i + 3]
        const meta = metas[bar]
        if (!cOpen || !cHigh || !cLow || !cClose || !meta) continue

        const rising = meta.close > meta.open
        // 平盘（close === open）按实心兜底
        const color = rising ? pal.rise : pal.fall

        // 实体上下沿（y 轴向下增长，value 越大 y 越小）
        const bodyTop = Math.min(cOpen.y, cClose.y)
        const bodyBottom = Math.max(cOpen.y, cClose.y)

        // 影线两段：high→实体顶、实体底→low（零长段跳过），空心实体内不穿影线
        if (cHigh.y < bodyTop) {
          figures.push({
            type: 'line',
            attrs: {
              coordinates: [
                { x: cHigh.x, y: cHigh.y },
                { x: cHigh.x, y: bodyTop },
              ],
            },
            styles: {
              color,
              size: 1,
              style: 'solid',
              smooth: false,
              dashedValue: [2, 2],
            },
          })
        }
        if (cLow.y > bodyBottom) {
          figures.push({
            type: 'line',
            attrs: {
              coordinates: [
                { x: cLow.x, y: bodyBottom },
                { x: cLow.x, y: cLow.y },
              ],
            },
            styles: {
              color,
              size: 1,
              style: 'solid',
              smooth: false,
              dashedValue: [2, 2],
            },
          })
        }

        // 实体：宽 gapBar、居中 bar x（与主图蜡烛同宽）
        const bodyWidth = barSpace.gapBar
        const bodyHeight = Math.max(1, bodyBottom - bodyTop)
        if (rising) {
          // 上涨：红空心
          figures.push({
            type: 'rect',
            attrs: {
              x: cOpen.x - barSpace.halfGapBar,
              y: bodyTop,
              width: bodyWidth,
              height: bodyHeight,
            },
            styles: {
              style: PolygonType.Stroke,
              color: pal.rise,
              borderColor: pal.rise,
              borderSize: 1,
              borderStyle: 'solid',
              borderDashedValue: [2, 2],
            },
          })
        } else {
          // 下跌 / 平盘：绿实心
          figures.push({
            type: 'rect',
            attrs: {
              x: cOpen.x - barSpace.halfGapBar,
              y: bodyTop,
              width: bodyWidth,
              height: bodyHeight,
            },
            styles: {
              style: PolygonType.Fill,
              color: pal.fall,
            },
          })
        }
      }
      return figures
    },
  })
}

/**
 * 构造 sub_candle overlay 创建参数（挂 BOLL 副图 pane）。
 * points 按每根 K 线 [open, high, low, close] 四点注入；
 * extendData 携带每根 {open, close} 供实体方向判定。
 */
export function buildSubCandleOverlay(klines: KLineData[]): OverlayCreate {
  const points: Array<{ timestamp: number; value: number }> = []
  const metas: SubCandleBarMeta[] = []
  for (const k of klines) {
    points.push({ timestamp: k.timestamp, value: k.open })
    points.push({ timestamp: k.timestamp, value: k.high })
    points.push({ timestamp: k.timestamp, value: k.low })
    points.push({ timestamp: k.timestamp, value: k.close })
    metas.push({ open: k.open, close: k.close })
  }
  return {
    name: 'sub_candle',
    lock: true,
    points,
    extendData: metas,
  }
}
