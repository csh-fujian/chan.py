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

/**
 * 搜索股票（名称/编码/拼音首字母，防抖由调用方负责）。
 * 真实后端 `GET /api/stocks` 已按分页对象 `{items, total, page, page_size}` 返回
 * （`stock_store.list_stocks`），而 mock 返回裸数组——这里统一归一成 `Stock[]`，
 * 否则对象形态会让下拉走「无匹配候选」分支，后端明明有命中也不渲染。
 */
export async function searchStocks(q: string): Promise<Stock[]> {
  const res = await client.get<unknown, Stock[] | { items?: Stock[]; list?: Stock[] }>('/stocks', {
    params: { q, page_size: 30 },
  })
  if (Array.isArray(res)) return res
  const items = res?.items ?? res?.list
  return Array.isArray(items) ? items : []
}

/** 获取所有行业列表 */
export function getIndustries() {
  return client.get<unknown, string[]>('/stocks/industries')
}
