import { http, HttpResponse, delay } from 'msw'
import { performanceStats, performanceSamples } from '../data/performance'

/**
 * stats handler（design D2/D6/D9）：消化 source / instance_id / group_id 过滤参数，
 * 语义对齐真后端 performance_store._filter_completed：
 * - source='chan'/'watchlist' → source_type 精确匹配（缺省视为 'chan'）
 * - source='strategy' 且 instance_id>0 → source_type==='strategy' && instance_id 匹配
 * - group_id='ungrouped' → group_id == null；正整数字符串 → 精确匹配
 * source 或 group_id 任一非空都走「样本过滤 + 按 (bsp_type, kl_type) 重聚合」路径（真后端同口径）
 */
export const performanceHandlers = [
  http.get('/api/performance/stats', async ({ request }) => {
    await delay(300)
    const url = new URL(request.url)
    const source = url.searchParams.get('source') || ''
    const instanceId = Number(url.searchParams.get('instance_id')) || 0
    const groupId = url.searchParams.get('group_id') || ''
    if (source || groupId) {
      // 来源/分组过滤均作用于底层样本，过滤后按 (bsp_type, kl_type) 重聚合（真后端同口径）
      const filtered = filterSamples(performanceSamples, source, instanceId, groupId)
      const groups = new Map<string, { samples: number; pnls: number[] }>()
      for (const s of filtered) {
        const key = `${s.bsp_type}|${s.kl_type}`
        const g = groups.get(key) ?? { samples: 0, pnls: [] }
        g.samples += 1
        g.pnls.push(s.profit)
        groups.set(key, g)
      }
      const rows: typeof performanceStats = []
      groups.forEach((g, key) => {
        const [bspType, klType] = key.split('|')
        const wins = g.pnls.filter((p) => p > 0)
        const losses = g.pnls.filter((p) => p <= 0)
        const winRateDec = g.samples ? wins.length / g.samples : 0
        const avgWin = wins.length ? wins.reduce((a, b) => a + b, 0) / wins.length : 0
        const avgLoss = losses.length
          ? Math.abs(losses.reduce((a, b) => a + b, 0) / losses.length)
          : 0
        rows.push({
          bsp_type: bspType,
          kl_type: klType,
          samples: g.samples,
          win_rate: +(winRateDec * 100).toFixed(1),
          avg_pnl: +(g.pnls.reduce((a, b) => a + b, 0) / g.samples).toFixed(2),
          profit_ratio: +(avgLoss > 0 ? avgWin / avgLoss : 0).toFixed(2),
          expectancy: +((winRateDec * avgWin - (1 - winRateDec) * avgLoss)).toFixed(2),
        })
      })
      return HttpResponse.json(rows.sort((a, b) => b.samples - a.samples))
    }
    return HttpResponse.json(performanceStats)
  }),

  http.get('/api/performance/samples', async ({ request }) => {
    await delay(300)
    const url = new URL(request.url)
    const bspType = url.searchParams.get('bsp_type') || ''
    const klType = url.searchParams.get('kl_type') || ''
    const source = url.searchParams.get('source') || ''
    const instanceId = Number(url.searchParams.get('instance_id')) || 0
    const groupId = url.searchParams.get('group_id') || ''
    let list = filterSamples(performanceSamples, source, instanceId, groupId)
    if (bspType) list = list.filter((s) => s.bsp_type === bspType)
    if (klType) list = list.filter((s) => s.kl_type === klType)
    return HttpResponse.json(list)
  }),
]

/**
 * 样本过滤（与真后端 _filter_completed 的 source/instance_id/group_id 分支一致）：
 * - source：非空时按 source_type 匹配（strategy 需 instance_id 联合）
 * - groupId：'ungrouped' → group_id == null；正整数字符串 → 精确匹配
 */
function filterSamples<
  T extends { source_type?: string; instance_id?: number; group_id?: number | null },
>(
  list: T[],
  source: string,
  instanceId: number,
  groupId: string,
): T[] {
  let result = list
  if (source) {
    if (source === 'strategy' && instanceId > 0) {
      result = result.filter((s) => s.source_type === 'strategy' && s.instance_id === instanceId)
    } else {
      result = result.filter((s) => (s.source_type ?? 'chan') === source)
    }
  }
  if (groupId === 'ungrouped') {
    result = result.filter((s) => s.group_id == null)
  } else if (groupId && /^\d+$/.test(groupId)) {
    const gid = Number(groupId)
    result = result.filter((s) => s.group_id === gid)
  }
  return result
}
