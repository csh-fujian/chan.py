import client from '../client'
import type { BspRecord, BspAggregate, PageRes } from '@/api/types'

/** 买卖点查询参数 */
export interface BspQuery {
  page: number
  page_size: number
  keyword?: string
  bsp_type?: string
  direction?: 'buy' | 'sell' | ''
  kl_type?: string
  /** 日期范围起点（YYYY-MM-DD）；与 date_to 双端齐备按闭区间匹配，只传一端单边过滤，空则不过滤 */
  date_from?: string | null
  /** 日期范围终点（YYYY-MM-DD）；与 date_from 双端齐备按闭区间匹配，只传一端单边过滤，空则不过滤 */
  date_to?: string | null
}

/** 买卖点列表（服务端分页） */
export function getBspList(query: BspQuery) {
  return client.get<unknown, PageRes<BspRecord>>('/bsp', { params: query })
}

/** 按时间取价响应（design D12） */
export interface PriceAtResult {
  price: number
  time_key: string
}

/** 取该股票指定周期上不晚于 time 的最近一根 K 线收盘价（design D12，监控弹窗价格联动） */
export function getPriceAt(code: string, klType: string, time: string) {
  return client.get<unknown, PriceAtResult>('/bsp/price-at', {
    params: { code, kl_type: klType, time },
  })
}

/** 板块聚合 */
export function getBspAggregate() {
  return client.get<unknown, BspAggregate[]>('/bsp/aggregate')
}

/**
 * bsp_index 原始行（bsp-page-change 4.2：GET /api/bsp/{code} 返回）
 * 字段对齐后端 get_bsp_by_code：bsp_date 为 ISO 日期字符串（YYYY-MM-DD），
 * bsp_type 为 CEnum.BSP_TYPE.value 原始值（'1'/'2'/'2s'/'3a'/'3b'/'1p'），
 * 与 BspRecord（bsp_date ms 时间戳、标签化 bsp_type）不同，调用方需做映射。
 */
export interface BspIndexRow {
  code: string
  kl_type: string
  autype: string
  bsp_date: string
  bsp_type: string
  is_buy: boolean
  price: number
  time_key: string
}

/** 指定股票的多级别买卖点（区间套），kl_types 过滤周期集合 */
export function getBspByCode(code: string, klTypes?: string[]) {
  const params: { kl_types?: string } = {}
  if (klTypes && klTypes.length > 0) {
    params.kl_types = klTypes.join(',')
  }
  return client.get<unknown, BspIndexRow[]>(`/bsp/${encodeURIComponent(code)}`, { params })
}
