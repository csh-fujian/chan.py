// chan_seg.ts — 线段覆盖层（蓝系折线，line figure）
// design.md D5：自定义 overlay，createPointFigures 返回 line figure（两点折线）
//
// 实现方式同 chan_bi：overlay.points 按 [begin1, end1, begin2, end2, ...] 顺序注入。
// 绘制色取 palette（任务 6.3）：线段蓝随主题微调（明亮下加深保证对比）。
//
// kline-unsure-dashed：未确认段（虚段，is_sure=false）以同色虚线（dashedValue [6, 4]）
// + 减细线宽（2.2→1.4）绘制，确认段保持实线——段视觉权重高于笔，虚线+减细双信号弱化临时性。
import { registerOverlay, type OverlayFigure } from 'klinecharts'
import { getChanPalette } from './palette'

/** 线段 overlay 元数据（存于 extendData，与 points 顺序对齐，每条段占 2 个 point） */
export interface ChanSegMeta {
  /** 在 overlay.points / coordinates 中的起始索引（该段 begin 所在，end 为 startIndex + 1） */
  startIndex: number
  /** 是否已确认；false = 虚段（未确认），绘制为同色虚线 + 减细线宽 */
  isSure: boolean
}

let registered = false

/** 注册线段覆盖层。幂等，重复调用安全。 */
export function registerChanSeg(): void {
  if (registered) return
  registered = true

  registerOverlay({
    name: 'chan_seg',
    needDefaultPointFigure: false,
    needDefaultXAxisFigure: false,
    needDefaultYAxisFigure: false,
    createPointFigures: (params): OverlayFigure[] => {
      const { overlay, coordinates } = params
      if (!coordinates || coordinates.length < 2) return []

      // extendData 缺失（旧调用方/异常路径）→ 全实线，向后兼容
      const meta = overlay.extendData as ChanSegMeta[] | undefined
      const metaAt = (pairIndex: number): ChanSegMeta | undefined => {
        // 第 pairIndex 条段在 points 中的起点 = pairIndex * 2（每条段占 2 个 point）
        return meta?.find((m) => m.startIndex === pairIndex * 2)
      }

      const figures: OverlayFigure[] = []
      const segColor = getChanPalette().seg
      for (let i = 0; i + 1 < coordinates.length; i += 2) {
        const a = coordinates[i]
        const b = coordinates[i + 1]
        if (a == null || b == null) continue
        const isSure = metaAt(i / 2)?.isSure ?? true
        figures.push({
          type: 'line',
          attrs: { coordinates: [{ x: a.x, y: a.y }, { x: b.x, y: b.y }] },
          styles: {
            color: segColor,
            size: isSure ? 2.2 : 1.4,
            style: isSure ? 'solid' : 'dashed',
            smooth: false,
            // solid 时 dashedValue 为惰性字段，但必须存在（drawImp 合并线段缺失会崩溃）
            dashedValue: isSure ? [2, 2] : [6, 4],
          },
        })
      }
      return figures
    },
  })
}
