// chan_bi.ts — 笔覆盖层（灰系折线，line figure）
// design.md D5：自定义 overlay，createPointFigures 返回 line figure（两点折线）
//
// 实现方式：overlay.points 按 [begin1, end1, begin2, end2, ...] 顺序注入，
// klinecharts 自动将 points 转为 coordinates，createPointFigures 把相邻坐标配对成 line。
// 绘制色取 palette（任务 6.3）：笔色随主题（暗色浅灰 / 明亮压深），绘制时实时读取。
//
// kline-unsure-dashed：未确认笔（is_sure=false）以同色虚线绘制（dashedValue [4, 3]），
// 确认笔保持实线——颜色不变，线型单独承载确认语义。无 extendData 时全实线（向后兼容）。
import { registerOverlay, type OverlayFigure } from 'klinecharts'
import { getChanPalette, divergenceColor } from './palette'

/** 笔 overlay 元数据（存于 extendData，与 points 顺序对齐，每条笔占 2 个 point） */
export interface ChanBiMeta {
  /** 在 overlay.points / coordinates 中的起始索引（该笔 begin 所在，end 为 startIndex + 1） */
  startIndex: number
  /** 是否已确认；false = 未确认（虚笔），绘制为同色虚线 */
  isSure: boolean
  /** 末尾笔背驰判定（chan-recent-divergence-mark）；true 时原线下垫红色阴影线。
   *  仅最后一个元素携带；undefined/null = 不标注 */
  isDivergence?: boolean | null
}

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
      const { overlay, coordinates } = params
      if (!coordinates || coordinates.length < 2) return []

      // extendData 缺失（旧调用方/异常路径）→ 全实线，向后兼容
      const meta = overlay.extendData as ChanBiMeta[] | undefined
      const metaAt = (pairIndex: number): ChanBiMeta | undefined => {
        // 第 pairIndex 条笔在 points 中的起点 = pairIndex * 2（每条笔占 2 个 point）
        return meta?.find((m) => m.startIndex === pairIndex * 2)
      }

      const figures: OverlayFigure[] = []
      const biColor = getChanPalette().bi
      // points 按 [begin, end, begin, end, ...] 顺序，两两配对
      for (let i = 0; i + 1 < coordinates.length; i += 2) {
        const a = coordinates[i]
        const b = coordinates[i + 1]
        if (a == null || b == null) continue
        const meta = metaAt(i / 2)
        const isSure = meta?.isSure ?? true
        // 背驰标注（chan-recent-divergence-mark design D5）：isDivergence=true 时
        // 在原始灰线之下垫**两层**红线（外层 5px 淡 / 内层 3.25px 浓），
        // 两层 alpha 叠出外发光过渡，而非单层半透明色带 —— 后者在暗底上
        // 与蜡烛涨红难区分（前端视觉走查结论）。虚笔时阴影层用实线：
        // 虚线语义单独留给「未确认」，两种语义正交。
        if (meta?.isDivergence === true) {
          const coords = [{ x: a.x, y: a.y }, { x: b.x, y: b.y }]
          for (const [size, layer] of [[5, 'outer'], [3.25, 'inner']] as const) {
            figures.push({
              type: 'line',
              attrs: { coordinates: coords },
              styles: {
                color: divergenceColor(layer),
                size,
                style: 'solid',
                smooth: false,
                dashedValue: [2, 2],
              },
            })
          }
        }
        figures.push({
          type: 'line',
          attrs: { coordinates: [{ x: a.x, y: a.y }, { x: b.x, y: b.y }] },
          styles: {
            color: biColor,
            size: 1.4,
            style: isSure ? 'solid' : 'dashed',
            smooth: false,
            // solid 时 dashedValue 为惰性字段，但必须存在（drawImp 合并线段缺失会崩溃）
            dashedValue: isSure ? [2, 2] : [4, 3],
          },
        })
      }
      return figures
    },
  })
}
