// chan_bi.ts — 笔覆盖层（灰系折线，line figure）
// design.md D5：自定义 overlay，createPointFigures 返回 line figure（两点折线）
//
// 实现方式：overlay.points 按 [begin1, end1, begin2, end2, ...] 顺序注入，
// klinecharts 自动将 points 转为 coordinates，createPointFigures 把相邻坐标配对成 line。
// 绘制色取 palette（任务 6.3）：笔色随主题（暗色浅灰 / 明亮压深），绘制时实时读取。
import { registerOverlay, type OverlayFigure } from 'klinecharts'
import { getChanPalette } from './palette'

let registered = false

/** 注册笔覆盖层。幂等，重复调用安全。 */
export function registerChanBi(): void {
  if (registered) return
  registered = true

  registerOverlay({
    name: 'chan_bi',
    needDefaultPointFigure: false,
    needDefaultXAxisFigure: false,
    needDefaultYAxisFigure: false,
    createPointFigures: (params): OverlayFigure[] => {
      const { coordinates } = params
      if (!coordinates || coordinates.length < 2) return []

      const figures: OverlayFigure[] = []
      const biColor = getChanPalette().bi
      // points 按 [begin, end, begin, end, ...] 顺序，两两配对
      for (let i = 0; i + 1 < coordinates.length; i += 2) {
        const a = coordinates[i]
        const b = coordinates[i + 1]
        if (a == null || b == null) continue
        figures.push({
          type: 'line',
          attrs: { coordinates: [{ x: a.x, y: a.y }, { x: b.x, y: b.y }] },
          styles: {
            color: biColor,
            size: 1.4,
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
