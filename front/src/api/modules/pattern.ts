import client from '../client'
import type { PageRes } from '@/api/types'

/**
 * 形态信号 API（chan-pattern-buy-signal 任务 5.1）。
 * 后端 routers/pattern.py；文案（name/cautions/scoring）由后端按当前口径现算返回。
 */

/** 形态类型键（对齐 WebAPI/pattern_meta.PATTERN_META）：买向 8 + 卖向 5 */
export type PatternType =
  | 'w_bottom'
  | 'head_shoulders'
  | 'box_breakout'
  | 'ascending_triangle'
  | 'low_flag'
  | 'v_reversal'
  | 'rounding_bottom'
  | 'cup_handle'
  // 顶部看跌形态（chan-pattern-sell-signal）
  | 'dark_cloud_cover'
  | 'shooting_star'
  | 'hanging_man'
  | 'high_engulfing'
  | 'high_engulfing_gap'

/** 信号方向：buy=底部形态 / sell=顶部形态 */
export type PatternDirection = 'buy' | 'sell'

/** 形态信号行（GET /api/pattern 返回） */
export interface PatternRecord {
  code: string
  kl_type: string
  autype: string
  pattern_type: PatternType
  /** 现算中文名（如「W底（双重底）」） */
  name: string
  /** 注意事项（弹窗展示，后端现算） */
  cautions: string[]
  /** 评分项文案（三轴，弹窗展示） */
  scoring: {
    struct?: { item: string; weight: number }[]
    vol?: { item: string; weight: number }[]
    confirm?: { item: string; weight: number }[]
    position?: { item: string; weight: number }[]
  }
  /** 信号方向（sell-signal）：buy=底部形态 / sell=顶部形态 */
  direction: PatternDirection
  pattern_date: string
  confirm_time_key: string
  price: number | null
  ref_line_high: number | null
  ref_line_low: number | null
  /** 置信分 0~100；null = 未评估的存量行（前端显示「未评估」，不猜分） */
  score: number | null
  qual: string | null
  invalid: boolean
  /** 一票否决原因键；veto_text 为现算白话 */
  veto: string | null
  veto_text: string | null
  detail: {
    key_points?: { role: string; idx: number; price: number }[]
    volume_ratio?: number
    retest?: boolean
  }
}

/** 形态查询参数 */
export interface PatternQuery {
  page: number
  page_size: number
  pattern_type?: string
  kl_type?: string
  date_from?: string | null
  date_to?: string | null
  code?: string
  keyword?: string
  /** 失效状态三态：'' 全部 / 'true' 仅失效 / 'false' 仅有效 */
  invalid?: string
  score_min?: number | null
  /** 方向过滤（sell-signal）：'' 全部 / 'buy' 买向 / 'sell' 卖向；
   *  sell 且未传 code 时后端默认只返回关注范围（自选 ∪ 监控）信号 */
  direction?: string
}

/** 分页查询形态信号 */
export function getPatternList(query: PatternQuery) {
  return client.get<unknown, PageRes<PatternRecord>>('/pattern', { params: query })
}

/** 形态元数据（GET /api/pattern/meta） */
export interface PatternMetaItem {
  name: string
  brief: string
  confirm_desc: string
  cautions: string[]
  market_logic: string[]
  scoring: {
    struct: { item: string; weight: number }[]
    vol: { item: string; weight: number }[]
    confirm: { item: string; weight: number }[]
  }
}

export function getPatternMeta() {
  return client.get<unknown, { patterns: Record<string, PatternMetaItem>; veto_text: Record<string, string> }>(
    '/pattern/meta',
  )
}

/** 形态类型清单（筛选下拉）——带 direction 供前端按买/卖分组（sell-signal 任务 3.3） */
export interface PatternTypeItem {
  value: PatternType
  label: string
  brief: string
  direction?: 'buy' | 'sell'
}

export function getPatternTypes() {
  return client.get<unknown, PatternTypeItem[]>('/pattern/types')
}

/** K 线页 overlay 数据（/api/klines 响应的 pattern[] 字段） */
export interface KlinePatternItem {
  type: PatternType
  /** 信号方向：buy=底部形态 / sell=顶部形态（sell-signal 任务 3.3） */
  direction: 'buy' | 'sell'

  name: string
  confirm_idx: number
  confirm_time: string
  price: number
  ref_line_high: number
  ref_line_low: number
  key_points: { role: string; idx: number; price: number }[]
  struct_begin_idx: number
  struct_end_idx: number
  score: number
  qual: string
  invalid: boolean
  veto: string | null
  volume_ratio: number
  /** 确认时间在最近 M 根（M=5）内且未失效 → 图表醒目提示 */
  is_new: boolean
  cautions: string[]
}
