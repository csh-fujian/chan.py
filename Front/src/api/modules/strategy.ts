import client from '../client'
import type { StrategyDefinition, StrategyInstance, StrategySignalRow, PageRes } from '@/api/types'

/**
 * 策略信号 API（strategy-signal-page design D5 / 后端契约）：
 * - 定义层只读（GET /strategy/definitions，含实例树 + 信号计数）
 * - 实例不可变：创建（422 校验错误）/ 启停 / 删除 / 手动补算
 * - 信号查询：按实例分页 + 状态/方向/日期范围/关键词筛选
 */

/** 策略定义列表（侧栏策略树数据源：定义分组 → 实例节点 + 计数） */
export function getStrategyDefinitions() {
  return client.get<unknown, StrategyDefinition[]>('/strategy/definitions')
}

/** 新建实例请求体（params 按 params_schema 校验，非法值 422 + detail） */
export interface CreateInstancePayload {
  strategy_id: string
  label: string
  params: Record<string, number>
}

/** 新建参数实例（design D2：创建即全量回算；实例不可变，改参数 = 新建） */
export function createInstance(payload: CreateInstancePayload) {
  return client.post<unknown, StrategyInstance>('/strategy/instances', payload)
}

/** 删除实例（级联删除其信号，UI 侧先确认） */
export function deleteInstance(id: number) {
  return client.delete<unknown, { success: boolean }>(`/strategy/instances/${id}`)
}

/** 启停实例（停用后调度不再增量扫描，已产生信号仍可查询） */
export function setInstanceEnabled(id: number, enabled: boolean) {
  return client.patch<unknown, { success: boolean }>(`/strategy/instances/${id}/enabled`, { enabled })
}

/** 手动补算（异步执行：从当前水位增量扫描至最新数据，幂等） */
export function scanInstance(id: number) {
  return client.post<unknown, { success: boolean; message?: string }>(`/strategy/instances/${id}/scan`)
}

/** 信号查询参数（instance_id 必传：信号按实例隔离；其余为可选筛选） */
export interface StrategySignalQuery {
  instance_id: number
  page: number
  page_size: number
  /** 状态筛选（取值域 = 所属定义 states；空 = 不过滤） */
  state?: string
  /** 方向筛选（buy/sell；空 = 不过滤） */
  direction?: 'buy' | 'sell' | ''
  /** 日期范围起点（YYYY-MM-DD，闭区间；空 = 不过滤） */
  date_from?: string | null
  /** 日期范围终点（YYYY-MM-DD，闭区间；空 = 不过滤） */
  date_to?: string | null
  /** 关键词（编码/名称模糊匹配；选中候选后为精确 code） */
  keyword?: string
}

/** 信号列表（服务端分页 + 全筛选） */
export function getStrategySignals(query: StrategySignalQuery) {
  return client.get<unknown, PageRes<StrategySignalRow>>('/strategy/signals', { params: query })
}
