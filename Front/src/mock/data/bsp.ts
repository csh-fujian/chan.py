import type { BspRecord, BspAggregate } from '@/api/types'
import type { BspIndexRow } from '@/api/modules/bsp'
import { stocks } from './stocks'

const bspTypes = ['1B', '2B', '3B', '1S', '2S', 'L2B', 'L2S', 'PZ-B', 'PZ-S']
// 周期词表（design D1）：与 BspView.klOptions 同集合 — 30m/60m/D/W/M，无 1/5/15 分钟
const klTypes = ['30m', '60m', 'D', 'W', 'M']

function rand(seed: number) {
  return ((seed * 9301 + 49297) % 233280) / 233280
}

/** 生成 60 条买卖点记录 */
export const bspRecords: BspRecord[] = Array.from({ length: 60 }, (_, i) => {
  const stock = stocks[i % stocks.length]
  const r = rand(i + 1)
  const bspType = bspTypes[i % bspTypes.length]
  const direction = bspType.includes('B') ? 'buy' : 'sell'
  const basePrice = stock.price
  return {
    id: i + 1,
    code: stock.code,
    name: stock.name,
    industries: stock.industries,
    bsp_type: bspType,
    direction: direction as 'buy' | 'sell',
    bsp_price: +(basePrice * (0.9 + r * 0.2)).toFixed(2),
    current_price: stock.price,
    bsp_date: Date.now() - Math.floor(r * 30) * 86400000,
    kl_type: klTypes[i % klTypes.length],
    change_pct: +((r - 0.5) * 10).toFixed(2),
  }
})

/** 指定股票的多级别买卖点（区间套）索引行，风格与 bspRecords 一致 */
export function getBspByCode(code: string, klTypesFilter?: string[]): BspIndexRow[] {
  const stock = stocks.find((s) => s.code === code)
  if (!stock) return []

  // 原始枚举词表（对齐 CEnum.BSP_TYPE.value），与 BspRecord 的标签化形态区分
  const rawTypes = ['1', '2', '2s', '3a', '3b', '1p']
  const rows: BspIndexRow[] = []
  let i = 0
  for (const kl of klTypes) {
    // 30分/60分 6~8 条、日线 5~7 条、周线 3~4 条、月线 2~3 条（由 code 散列决定）
    const klSeed = [...code].reduce((a, c) => a + c.charCodeAt(0), 0)
    const counts: Record<string, number> = {
      '30m': 6 + (klSeed % 3),
      '60m': 6 + ((klSeed + 1) % 3),
      D: 5 + (klSeed % 3),
      W: 3 + (klSeed % 2),
      M: 2 + (klSeed % 2),
    }
    for (let j = 0; j < counts[kl]; j++) {
      const r = rand(klSeed + i + 1)
      const raw = rawTypes[i % rawTypes.length]
      const isBuy = !rawTypes[i % rawTypes.length].includes('s') && i % 2 === 0
      const klDay: Record<string, number> = { '30m': 1, '60m': 1, D: 1, W: 7, M: 30 }
      const daysAgo = Math.floor(r * 90) * klDay[kl] + j
      const d = new Date(Date.now() - daysAgo * 86400000)
      rows.push({
        code,
        kl_type: kl,
        autype: 'QFQ',
        bsp_date: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`,
        bsp_type: raw,
        is_buy: isBuy,
        price: +(stock.price * (0.88 + r * 0.24)).toFixed(2),
        time_key: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} 00:00:00`,
      })
      i++
    }
  }
  return klTypesFilter && klTypesFilter.length > 0
    ? rows.filter((r) => klTypesFilter.includes(r.kl_type))
    : rows
}

/** 板块聚合 */
export function getBspAggregate(): BspAggregate[] {  const map = new Map<string, BspAggregate>()
  for (const r of bspRecords) {
    for (const ind of r.industries) {
      if (!map.has(ind)) {
        map.set(ind, { industry: ind, total: 0, buy_count: 0, sell_count: 0 })
      }
      const a = map.get(ind)!
      a.total++
      if (r.direction === 'buy') a.buy_count++
      else a.sell_count++
    }
  }
  return Array.from(map.values()).sort((a, b) => b.total - a.total)
}
