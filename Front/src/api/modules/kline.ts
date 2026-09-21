import client from '../client'
import type { ChanResult } from '../types'

/** 增量加载参数 */
export interface KLineParams {
  symbol: string
  period?: string
  /** 增量加载分页游标（毫秒），返回 ≤此时间戳的更早K线 */
  end?: number
}

/** 获取 K 线 + 缠论计算结果（design.md D2 序列化契约） */
export function getKLine(code: string, period: string = '1d', end?: number) {
  return client.get<unknown, ChanResult>('/klines', {
    params: { symbol: code, period, ...(end ? { end } : {}) },
  })
}
