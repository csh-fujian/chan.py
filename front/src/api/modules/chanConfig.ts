import client from '../client'
import type {
  ChanConfigSaveInput,
  ChanConfigSaveResult,
  ChanConfigSchema,
  ChanConfigState,
  ChanSyncStatus,
} from '../types'

/** 读取当前生效配置 + 版本号 + 档位（menu:kline） */
export function getChanConfig() {
  return client.get<unknown, ChanConfigState>('/chan-config')
}

/** 读取参数元数据（分组 / 控件 / 白话解释 / 内核默认值） */
export function getChanConfigSchema() {
  return client.get<unknown, ChanConfigSchema>('/chan-config/schema')
}

/** 保存配置；非法值后端返回 422（detail 含可定位的 param） */
export function saveChanConfig(body: ChanConfigSaveInput) {
  return client.put<unknown, ChanConfigSaveResult>('/chan-config', body)
}

/** 触发单只股票的后台重算（保存后刷新该股票的 PG 索引） */
export function recomputeStock(code: string, period: string, autype = 'QFQ') {
  return client.post<unknown, { accepted: boolean; code: string; period: string }>(
    '/chan-config/recompute',
    { code, period, autype },
  )
}

/** 启动全库批量同步（已有任务在跑返回 409） */
export function startChanSync() {
  return client.post<unknown, { started: boolean; job_id: number; config_version: number }>(
    '/chan-config/sync',
  )
}

/** 查询最近一次同步任务进度 */
export function getChanSyncStatus() {
  return client.get<unknown, ChanSyncStatus>('/chan-config/sync/status')
}
