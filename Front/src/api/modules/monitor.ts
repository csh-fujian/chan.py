import client from '../client'
import type { MonitorItem, CompletedItem, PageRes, AnalyzeResult } from '@/api/types'

/** 监控分组（monitor-group-change design D1：id/name/sort_order + 组内计数） */
export interface MonitorGroup {
  id: number
  name: string
  /** 显示顺序（GET /monitor/groups 已按 sort_order 升序返回） */
  sort_order: number
  /** 组内监控中记录数（服务端聚合返回） */
  monitoring_count: number
  /** 组内已完成记录数（服务端聚合返回） */
  completed_count: number
}

/** 获取监控分组列表（按 sort_order 升序） */
export function getMonitorGroups() {
  return client.get<unknown, MonitorGroup[]>('/monitor/groups')
}

/** 新建监控分组（名称查重在后端：重名/空名返回 4xx detail） */
export function createMonitorGroup(name: string) {
  return client.post<unknown, MonitorGroup>('/monitor/groups', { name })
}

/** 重命名监控分组 */
export function renameMonitorGroup(id: number, name: string) {
  return client.patch<unknown, { success: boolean }>(`/monitor/groups/${id}`, { name })
}

/** 删除监控分组（组内监控记录 group_id 置 null，归入「未分组」） */
export function deleteMonitorGroup(id: number) {
  return client.delete<unknown, { success: boolean }>(`/monitor/groups/${id}`)
}

/** 重排分组顺序（全量覆盖 sort_order，ids 下标即新序） */
export function reorderMonitorGroups(ids: number[]) {
  return client.put<unknown, { success: boolean }>('/monitor/groups/reorder', { ids })
}

/** 来源字典项（design D14：GET /monitor/sources，来源下拉消费，前端不硬编码策略实例） */
export interface MonitorSource {
  /** 过滤键：'chan' / 'strategy:<instance_id>' / 'watchlist' */
  value: string
  /** 下拉展示名：缠论 / 策略名·实例名 / 自选 */
  label: string
  source_type: 'chan' | 'strategy' | 'watchlist'
  /** source_type='strategy' 时的实例 id */
  instance_id?: number
}

/** 来源字典（design D14）：monitor 表 distinct 来源 + 策略实例名 */
export function getMonitorSources() {
  return client.get<unknown, MonitorSource[]>('/monitor/sources')
}

/**
 * 监控列表（keyword 可选；group_id 可选：'ungrouped' 哨兵 → 未分组，
 * 数值 id 字符串 → 精确匹配，缺省不过滤，design D3）
 */
export function getMonitorList(keyword?: string, group_id?: string) {
  return client.get<unknown, MonitorItem[]>('/monitor', {
    params: { keyword, group_id },
  })
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
  /** 可选分组归属（monitor-group-change D5：未传时后端写 NULL = 未分组） */
  group_id?: number
  /** 信号来源（strategy-signal-page design D6 + D14 / watchlist-page-change design D11）：
   *  'chan'（缺省，BspView 不传后端落 'chan'，行为不变）、'strategy' 或
   *  'watchlist'（自选页加入监控，提交显式携带） */
  source_type?: 'chan' | 'strategy' | 'watchlist'
  /** 策略来源所属实例（source_type='strategy' 时随信号携带） */
  instance_id?: number
  /** 策略信号的信号日期（source_type='strategy' 时随信号携带，YYYY-MM-DD） */
  signal_date?: string
}

export function createMonitor(payload: CreateMonitorPayload) {
  return client.post<unknown, Record<string, unknown>>('/monitor', payload)
}

/**
 * 监控完成列表（keyword 可选；group_id 可选，语义同 getMonitorList，
 * monitor-group-change design D3：'ungrouped' → IS NULL / 数值 → 精确匹配）
 */
export function getCompletedList(keyword?: string, group_id?: string) {
  return client.get<unknown, CompletedItem[]>('/monitor/completed', {
    params: { keyword, group_id },
  })
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
