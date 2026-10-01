import client from '../client'
import type { MonitorItem, CompletedItem, PageRes, AnalyzeResult } from '@/api/types'

/** 监控列表（keyword 可选） */
export function getMonitorList(keyword?: string) {
  return client.get<unknown, MonitorItem[]>('/monitor', { params: { keyword } })
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
