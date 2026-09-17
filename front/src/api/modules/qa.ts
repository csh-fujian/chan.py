import client from '../client'
import type { QaRecord } from '../types'

export interface AskParams {
  question: string
  code?: string
  period?: string
}

/** 提问：大模型解答并落库，返回完整记录 */
export function askQuestion(params: AskParams) {
  return client.post<unknown, QaRecord>('/qa', params)
}

/** 获取问答记录列表（时间倒序） */
export function getQaRecords() {
  return client.get<unknown, QaRecord[]>('/qa')
}

/** 单条打星/取消收藏 */
export function starQaRecord(id: number, starred: boolean) {
  return client.patch<unknown, { success: boolean }>(`/qa/${id}/star`, { starred })
}

/** 批量打星 */
export function batchStarQa(ids: number[], starred: boolean) {
  return client.post<unknown, { success: boolean }>('/qa/star', { ids, starred })
}

/** 一键删除未打星记录 */
export function deleteUnstarredQa() {
  return client.delete<unknown, { success: boolean }>('/qa/unstarred')
}
