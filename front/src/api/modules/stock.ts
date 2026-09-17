import client from '../client'
import type { StockProfile } from '../types'

/** 获取标的详情（完整行业/地区/概念，全量展示） */
export function getStockProfile(code: string) {
  return client.get<unknown, StockProfile>(`/stocks/${code}/profile`)
}
