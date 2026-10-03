import client from '../client'
import type { MonitorItem, CompletedItem, PageRes, AnalyzeResult } from '@/api/types'

/** 监控列表（keyword 可选） */
export function getMonitorList(keyword?: string) {
  return client.get<unknown, MonitorItem[]>('/monitor', { params: { keyword } })
}

/** 行级加入监控（bsp-page-change 4.5 / design D8 修订）：POST /api/monitor
 *  code 为股票编码；kl_type 直接传 bsp 词表值（'D'/'W'/'M'/'30m'/'60m'，与
 *  bsp_index 词表一致，monitor 表 VARCHAR 原样存储）；monitor_start_time 为
 *  'YYYY-MM-DD HH:mm:ss' 字符串（monitor_store 存 VARCHAR，DuckDB time_key
 *  字符串比较与 LLM prompt 均可直接消费）。 */
export interface CreateMonitorPayload {
  code: string
  kl_type: string
  entry_price: number
  monitor_start_time: string
}

export function createMonitor(payload: CreateMonitorPayload) {
  return client.post<unknown, Record<string, unknown>>('/monitor', payload)
}

/** 监控完成列表（keyword 可选） */
export function getCompletedList(keyword?: string) {
  return client.get<unknown, CompletedItem[]>('/monitor/completed', { params: { keyword } })
}

/** 盈利走势时序 */
export function getProfitSeries() {
  return client.get<unknown, { date: string; value: number }[]>('/monitor/profit-series')
}

/** 手动结束监控 */
export function endMonitor(id: number) {
  return client.post<unknown, { success: boolean; id: number }>(`/monitor/${id}/end`)
}

/** 大模型归因分析（design D5：真实生成；失败返回 400/5xx 错误体，不写占位） */
export function analyzeMonitor(id: number) {
  return client.post<unknown, AnalyzeResult>(`/monitor/${id}/analyze`)
}
