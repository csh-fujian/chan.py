// chan_sell_pattern.ts — 顶部看跌形态信号覆盖层（chan-pattern-sell-signal 任务 3.1）
//
// 与买点形态 chan_pattern 完全独立的第六个覆盖层（design D2）：
// 独立注册、独立开关、独立点击 hooks、独立色系（橙红警示色，不与买点形态共用色板）。
//
// 每个卖向形态信号绘制：
//  1. 参考线：结构起点 → 确认 K 线的虚线（T1/T2 实体边界）
//  2. 关键点标记：小圆圈（阳线收盘/阴线收盘/影线端点等）
//  3. 确认标签：确认 K 线上方形态名缩写 + 分数（卖点语义 → 标在 K 线上方，与买点下方区分）
//  4. 新卖点徽标：is_new 时标签上方的醒目圆点（提示时效 M=5，由后端 is_new 判定）
//
// 点击确认标签 → 注入的 hover/onClick 钩子 → KLineChart 弹注意事项弹窗。
import { registerOverlay, type OverlayFigure } from 'klinecharts'
import { getChanPalette } from './palette'

/** 卖点形态 overlay 元数据（存于 extendData） */
export interface ChanSellPatternMeta {
  /** 形态中文名（标签显示用缩写名） */
  name: string
  /** 形态类型键（点击回调透传） */
  type: string
  /** 在 overlay.points / coordinates 中的起始索引：
   *  [0]=结构起点(参考线左端) [1]=参考线右端(确认K线) [2..]=关键点 [n]=标签锚点(=参考线右端) */
  startIndex: number
  keyCount: number
  score: number
  qual: string
  invalid: boolean
  isNew: boolean
  /** 置信分 + 档位组成的标签文本（如「吊颈线 88」） */
  label: string
}

/** 点击确认标签的回调钩子（KLineChart 注入 → 弹窗） */
export interface ChanSellPatternClickHooks {
  onSellPatternClick: (meta: ChanSellPatternMeta, x: number, y: number) => void
}

let hooks: ChanSellPatternClickHooks | null = null

/** 注入点击回调（KLineChart 挂载时设置，卸载时置 null） */
export function setChanSellPatternClickHooks(h: ChanSellPatternClickHooks | null): void {
  hooks = h
}

/** 每形态固定色相——橙红警示色系（design D2：与买点形态绿色系/缠论标识色板不重叠） */
const SELL_TYPE_COLORS: Record<string, string> = {
  dark_cloud_cover: '#FB923C',   // 橙
  shooting_star: '#F87171',      // 亮红
  hanging_man: '#E879F9',        // 品红
  high_engulfing: '#F43F5E',     // 玫红
  high_engulfing_gap: '#DC2626', // 深红（最强形态）
}

const LABEL_W = 52
const LABEL_H = 18
const BADGE_R = 5

let registered = false

/** 注册卖点形态覆盖层（chan_sell_pattern）。幂等，重复调用安全。 */
export function registerChanSellPattern(): void {
  if (registered) return
  registered = true

  registerOverlay({
    name: 'chan_sell_pattern',
    needDefaultPointFigure: false,
    needDefaultXAxisFigure: false,
    needDefaultYAxisFigure: false,
    onClick: (params) => {
      const meta = params?.overlay?.extendData as ChanSellPatternMeta | undefined
      if (meta && hooks) {
        hooks.onSellPatternClick(meta, params?.x ?? 0, params?.y ?? 0)
        return true // 阻止冒泡到 K 线
      }
      return false
    },
    createPointFigures: (params): OverlayFigure[] => {
      const { overlay, coordinates, bounding } = params
      const meta = overlay.extendData as ChanSellPatternMeta | undefined
      if (!meta || !coordinates || coordinates.length < 2) return []

      const pal = getChanPalette()
      const color = SELL_TYPE_COLORS[meta.type] ?? pal.sell ?? '#F43F5E'
      const figures: OverlayFigure[] = []

      // [0] 结构起点 → [1] 确认 K 线：参考线（虚线）
      const p0 = coordinates[0]
      const p1 = coordinates[1]
      if (!p0 || !p1) return []
      figures.push({
        type: 'line',
        // klinecharts line figure 的字段名是 coordinates（不是 points）——
        // 用错字段会导致参考线画不出，且 hover 事件分发在 checkCoordinateOnLine
        // 处抛 TypeError，打断全部 overlay 的悬浮/点击命中
        attrs: { coordinates: [{ x: p0.x, y: p0.y }, { x: p1.x, y: p1.y }] },
        styles: {
          style: 'stroke',
          color,
          size: 1,
          dashedValue: [5, 4],
        },
      })

      // [2..2+keyCount) 关键点：小圆圈
      for (let i = 2; i < 2 + meta.keyCount && i < coordinates.length; i++) {
        const p = coordinates[i]
        if (!p) continue
        figures.push({
          type: 'circle',
          attrs: { x: p.x, y: p.y, r: 3 },
          styles: {
            style: 'stroke_fill',
            color: 'transparent',
            borderColor: color,
            borderSize: 1.5,
          },
        })
      }

      // 确认标签：参考线右端上方（卖点语义 → 标在 K 线上方，与买点标签下方区分）
      const labelY = Math.max(p1.y - 14 - LABEL_H, 2)
      figures.push({
        type: 'rect',
        attrs: { x: p1.x - LABEL_W / 2, y: labelY, width: LABEL_W, height: LABEL_H },
        styles: {
          style: 'stroke_fill',
          color: meta.invalid ? 'rgba(107,114,128,0.25)' : 'rgba(0,0,0,0.45)',
          borderColor: meta.invalid ? '#6B7280' : color,
          borderSize: 1,
          borderRadius: 3,
        },
      })
      figures.push({
        type: 'text',
        attrs: { x: p1.x, y: labelY + LABEL_H / 2, text: meta.label },
        styles: {
          style: 'fill',
          color: meta.invalid ? '#9CA3AF' : color,
          size: 10,
        },
      })

      // 新卖点徽标：标签右上角醒目圆点（spec「新卖点提示」）
      if (meta.isNew) {
        figures.push({
          type: 'circle',
          attrs: { x: p1.x + LABEL_W / 2, y: labelY, r: BADGE_R },
          styles: {
            style: 'stroke_fill',
            color: '#F6465D',
            borderColor: '#FFFFFF',
            borderSize: 1,
          },
        })
        figures.push({
          type: 'text',
          attrs: { x: p1.x + LABEL_W / 2, y: labelY + 3, text: '卖' },
          styles: { style: 'fill', color: '#FFFFFF', size: 8 },
        })
      }
      return figures
    },
  })
}
