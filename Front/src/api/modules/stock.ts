import client from '../client'
import type { Stock, StockProfile, StockMeta } from '../types'

/** 获取标的详情（完整行业/地区/概念，全量展示） */
export function getStockProfile(code: string) {
  return client.get<unknown, StockProfile>(`/stocks/${code}/profile`)
}

/** 获取股票元数据（档案/快照/经营/联系方式/股东户数/tags/notes，K 线页「股票信息」tab） */
export function getStockMeta(code: string) {
  return client.get<unknown, StockMeta>(`/stocks/${code}/meta`)
}

/** 搜索股票（名称/编码，防抖由调用方负责） */
export function searchStocks(q: string) {
  return client.get<unknown, Stock[]>('/stocks', { params: { q, page_size: 30 } })
}

/** 获取所有行业列表 */
export function getIndustries() {
  return client.get<unknown, string[]>('/stocks/industries')
}
