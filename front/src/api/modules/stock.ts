import client from '../client'
import type { Stock, StockProfile } from '../types'

/** 获取标的详情（完整行业/地区/概念，全量展示） */
export function getStockProfile(code: string) {
  return client.get<unknown, StockProfile>(`/stocks/${code}/profile`)
}

/** 搜索股票（名称/编码，防抖由调用方负责） */
export function searchStocks(q: string) {
  return client.get<unknown, Stock[]>('/stocks', { params: { q, page_size: 30 } })
}

/** 获取所有行业列表 */
export function getIndustries() {
  return client.get<unknown, string[]>('/stocks/industries')
}
