import type { BspRecord, BspAggregate } from '@/api/types'
import type { BspIndexRow } from '@/api/modules/bsp'
import { stocks } from './stocks'

// 与 utils/bsp.ts 的 ALL_BSP_LABELS 同集合（chan-standard-bsp：3a/3b 语义分叉后
// 不再共用一个「3B」标签，mock 侧也须拆开，否则筛选下拉选不到任何记录）
const bspTypes = ['1B', '2B', '3B(后)', '3B(内)', '1S', '2S', 'L2B', 'L2S', '3S(后)', '3S(内)', 'PZ-B', 'PZ-S']
// 周期词表（design D1）：与 BspView.klOptions 同集合 — 30m/60m/D/W/M，无 1/5/15 分钟
const klTypes = ['30m', '60m', 'D', 'W', 'M']

function rand(seed: number) {
  return ((seed * 9301 + 49297) % 233280) / 233280
}

/** 生成 60 条买卖点记录
 * is_sure（bsp-sure-annotation 4.4）：真实形态中未确认点天然聚在索引尾部
 * （依托尾部虚段），按此形态构造——最后 6 条 is_sure=false，其余 true；
 * 未确认行日期贴近当前（尾部 = 最新），保证默认「最近三个交易日」范围内可见
 * ladder（chan-bsp-ladder-change）：确认 → 'L4'；未确认的一买家族在**三轴组合值**
 * 轮转（进度轴 L1/L2 + 佐证轴 L2-x + 分型轴 L3-x），非一买类型为 null（「未定级」）。
 * 覆盖形状：三轴齐备、两轴、单轴、NULL 四种，保证前端各分支都能被 mock 驱动。 */
const UNSURE_LADDERS = [
  'L2|L2-3|L3-3',
  'L1|L3-2',
  'L2|L3-1',
  'L1',
  'L1|L2-1|L3-1',
] as const
let unsureIdx = 0

/** 一买家族类型（1 / 1p / PZ）——只有它们携带三轴组合值 */
function isBsp1Family(type: string): boolean {
  return type.startsWith('1') || type.startsWith('PZ')
}

export const bspRecords: BspRecord[] = Array.from({ length: 60 }, (_, i) => {
  const stock = stocks[i % stocks.length]
  const r = rand(i + 1)
  const bspType = bspTypes[i % bspTypes.length]
  const direction = bspType.includes('B') ? 'buy' : 'sell'
  const basePrice = stock.price
  // 尾部 6 条未确认（预览信号），其余已确认
  const isSure = i < 54
  // 已确认行分布在近 30 天；未确认行贴近当前（0~1 天，尾部预览形态）
  const daysAgo = isSure ? Math.floor(r * 30) : Math.floor(r * 2)
  const bspDate = Date.now() - daysAgo * 86400000
  const klType = klTypes[i % klTypes.length]
  // id 稳定复合键（bsp-page-level-filter-and-batch-monitor D4）：真实接口由记录自身
  // 业务字段拼成（含 autype/time_key），此处按同一形状用 mock 可得字段拼，避免用
  // 行号占位在切换筛选后串行。mock 无 autype/time_key，故以其索引位串 i 兜底区分。
  const id = `${stock.code}|${klType}|QFQ|${bspDate}|${bspType}|${direction === 'buy' ? 'B' : 'S'}|${i}`
  return {
    id,
    code: stock.code,
    name: stock.name,
    industries: stock.industries,
    bsp_type: bspType,
    direction: direction as 'buy' | 'sell',
    bsp_price: +(basePrice * (0.9 + r * 0.2)).toFixed(2),
    current_price: stock.price,
    bsp_date: bspDate,
    kl_type: klType,
    change_pct: +((r - 0.5) * 10).toFixed(2),
    is_sure: isSure,
    // 已确认 → L4；未确认的一买家族 → 三轴组合轮转；非一买类型 → null（未定级）
    ladder: isSure
      ? 'L4'
      : isBsp1Family(bspType)
        ? UNSURE_LADDERS[unsureIdx++ % UNSURE_LADDERS.length]
        : null,
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
        // 每周期尾部 2 条未确认（bsp-sure-annotation 4.4，形态对齐真实索引的尾部预览）
        is_sure: j < counts[kl] - 2,
        // 三轴阶梯（chan-bsp-ladder-change）：确认 → L4；未确认一买家族 → 组合轮转；
        // 非一买类型 → null（未定级）
        ladder:
          j < counts[kl] - 2
            ? 'L4'
            : isBsp1Family(raw)
              ? UNSURE_LADDERS[i % UNSURE_LADDERS.length]
              : null,
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
