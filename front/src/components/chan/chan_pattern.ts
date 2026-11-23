// chan_pattern.ts — 底部形态信号覆盖层（chan-pattern-buy-signal 任务 5.2/5.3）
//
// 每个形态信号绘制：
//  1. 参考线：struct_begin_idx → 确认 K 线的水平/斜虚线（突破压力位）
//  2. 关键点标记：小圆圈（左底/颈线/右底等）
//  3. 确认标签：确认 K 线下方形态名缩写 + 分数
//  4. 新信号徽标：is_new 时确认标签上方的醒目圆点（提示时效 M=5，由后端 is_new 判定）
//
// 点击确认标签 → 注入的 hover/onClick 钩子 → KLineChart 弹注意事项弹窗（任务 5.3）。
import { registerOverlay, type OverlayFigure } from 'klinecharts'
import { getChanPalette } from './palette'

/** 形态 overlay 元数据（存于 extendData） */
export interface ChanPatternMeta {
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
  /** 置信分 + 档位组成的标签文本（如「W底 88」） */
  label: string
}

/** 点击确认标签的回调钩子（KLineChart 注入 → 弹窗） */
export interface ChanPatternClickHooks {
  onPatternClick: (meta: ChanPatternMeta, x: number, y: number) => void
}

let hooks: ChanPatternClickHooks | null = null

/** 注入点击回调（KLineChart 挂载时设置，卸载时置 null） */
export function setChanPatternClickHooks(h: ChanPatternClickHooks | null): void {
  hooks = h
}

/** 每形态固定色相（同一图多形态并存时可辨） */
const TYPE_COLORS: Record<string, string> = {
  w_bottom: '#F0B90B',
  head_shoulders: '#C084FC',
  box_breakout: '#60A5FA',
  ascending_triangle: '#34D399',
  low_flag: '#F97316',
  v_reversal: '#EF4444',
  rounding_bottom: '#22D3EE',
  cup_handle: '#A3E635',
}

const LABEL_W = 52
const LABEL_H = 18
const BADGE_R = 5

let registered = false

/** 注册形态覆盖层。幂等，重复调用安全。 */
export function registerChanPattern(): void {
  if (registered) return
  registered = true

  registerOverlay({
    name: 'chan_pattern',
    needDefaultPointFigure: false,
    needDefaultXAxisFigure: false,
    needDefaultYAxisFigure: false,
    onClick: (params) => {
      // 命中标签/徽标区域时触发弹窗回调（klinecharts onClick 在 overlay 内触发）
      const meta = params?.overlay?.extendData as ChanPatternMeta | undefined
      if (meta && hooks) {
        hooks.onPatternClick(meta, params?.x ?? 0, params?.y ?? 0)
        return true // 阻止冒泡到 K 线
      }
      return false
    },
    createPointFigures: (params): OverlayFigure[] => {
      const { overlay, coordinates, bounding } = params
      const meta = overlay.extendData as ChanPatternMeta | undefined
      if (!meta || !coordinates || coordinates.length < 2) return []

      const pal = getChanPalette()
      const color = TYPE_COLORS[meta.type] ?? pal.buy ?? '#F0B90B'
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

      // 确认标签：参考线右端下方（买点语义 → 标在 K 线下方）
      const labelY = Math.min(p1.y + 14, (bounding?.height ?? 9999) - LABEL_H - 2)
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

      // 新信号徽标：标签右上角醒目圆点（is_new → 图表提示，spec「新确认信号醒目提示」）
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
          attrs: { x: p1.x + LABEL_W / 2, y: labelY + 3, text: '新' },
          styles: { style: 'fill', color: '#FFFFFF', size: 8 },
        })
      }
      return figures
    },
  })
}
