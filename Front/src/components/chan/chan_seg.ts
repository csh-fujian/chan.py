// chan_seg.ts — 线段覆盖层（蓝系折线，line figure）
// design.md D5：自定义 overlay，createPointFigures 返回 line figure（两点折线）
//
// 实现方式同 chan_bi：overlay.points 按 [begin1, end1, begin2, end2, ...] 顺序注入。
// 绘制色取 palette（任务 6.3）：线段蓝随主题微调（明亮下加深保证对比）。
import { registerOverlay, type OverlayFigure } from 'klinecharts'
import { getChanPalette } from './palette'

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
      const { coordinates } = params
      if (!coordinates || coordinates.length < 2) return []

      const figures: OverlayFigure[] = []
      const segColor = getChanPalette().seg
      for (let i = 0; i + 1 < coordinates.length; i += 2) {
        const a = coordinates[i]
        const b = coordinates[i + 1]
        if (a == null || b == null) continue
        figures.push({
          type: 'line',
          attrs: { coordinates: [{ x: a.x, y: a.y }, { x: b.x, y: b.y }] },
          styles: {
            color: segColor,
            size: 2.2,
            style: 'solid',
            smooth: false,
            dashedValue: [2, 2],
          },
        })
      }
      return figures
    },
  })
}
