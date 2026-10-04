import type { PerformanceStat, PerformanceSample } from '@/api/types'
import { stocks } from './stocks'

// 原始枚举口径（performance-page-change design D8/D9）：与真后端一致，
// bsp_type 为 '1'/'1p'/'2'/'2s'/'3a'/'3b'（方向由样本行 direction 字段承载）
const bspTypes = ['1', '2', '3a', '3b', '1p', '2s']
const klTypes = ['30m', '60m', 'D', 'W', 'M']

function rand(i: number) {
  return ((i * 9301 + 49297) % 233280) / 233280
}

/**
 * 归因摘要文本池（design D5/D6：约 30% 非空，模拟 LLM 归因，
 * 语义与 monitor 页归因记录一致）
 */
const attributionPool = [
  '入场后回踩不破前低，中枢支撑有效，趋势延续。',
  '次级别背驰确认后突破中枢上沿，量能配合良好，按计划持有至止盈。',
  '买卖点后分型被后续 K 线破坏，背驰判断失效，属信号在震荡结构下的失效情形。',
  '大级别趋势转入盘整延伸，小级别买点被震荡吞没，区间套共振条件未满足。',
  '突破后回跌进中枢，强势调整假设不成立，止损离场。',
]

/** 6 行统计（枚举口径 + kl_type 轮换 + 期望值反推：胜率×平均盈利 − 败率×|平均亏损|） */
export const performanceStats: PerformanceStat[] = bspTypes.map((t, i) => {
  const r = rand(i + 1)
  const klType = klTypes[i % klTypes.length]
  const samples = 20 + Math.floor(r * 80)
  const winRate = Math.floor(30 + r * 50)
  const avgPnl = +((winRate - 50) * 0.3 + (r - 0.5) * 2).toFixed(2)
  const avgWin = +(Math.abs(avgPnl) * 1.6 + 1).toFixed(2)
  const avgLoss = +(avgWin / (1 + r * 2)).toFixed(2)
  // 期望值 = 胜率(小数)×平均盈利 − 败率×|平均亏损|
  const expectancy = +((winRate / 100) * avgWin - (1 - winRate / 100) * avgLoss).toFixed(2)
  return {
    bsp_type: t,
    kl_type: klType,
    samples,
    win_rate: winRate,
    avg_pnl: avgPnl,
    profit_ratio: +((winRate / 100) * (1 + r)).toFixed(2),
    expectancy,
  }
})

/** 样本明细 40 条（枚举口径 + kl_type 轮换 + 来源三分支 + 归因摘要 + 分组轮换） */
export const performanceSamples: PerformanceSample[] = Array.from({ length: 40 }, (_, i) => {
  const stock = stocks[i % stocks.length]
  const r = rand(i + 1)
  const bspType = bspTypes[i % bspTypes.length]
  const direction: 'buy' | 'sell' = i % 3 === 0 ? 'buy' : i % 3 === 1 ? 'sell' : 'buy'
  const bspPrice = +(stock.price * (0.85 + r * 0.2)).toFixed(2)
  const endPrice = +(bspPrice * (1 + (direction === 'buy' ? 1 : -1) * (0.05 + r * 0.2))).toFixed(2)
  const profit = +(((endPrice - bspPrice) / bspPrice) * 100).toFixed(2)
  // 来源三分支（design D6）：chan 60% / strategy 25%（instance_id=5）/ watchlist 15%
  const sourceRoll = rand(i + 7)
  const sourceType: PerformanceSample['source_type'] =
    sourceRoll < 0.6 ? 'chan' : sourceRoll < 0.85 ? 'strategy' : 'watchlist'
  // 策略实例 id（与 monitorSources 字典 'strategy:5' 对应，handler instance_id 过滤用）
  const instanceId = sourceType === 'strategy' ? 5 : undefined
  // 归因摘要：约 30% 非空
  const attribution = r < 0.3 ? attributionPool[i % attributionPool.length] : ''
  // 分组归属（design D9）：约 60% 未分组（null），其余轮换 1/2（与 monitor mock 分组 id 对齐）
  const groupRoll = rand(i + 13)
  const groupId = groupRoll < 0.6 ? null : (i % 2) + 1
  return {
    id: i + 1,
    code: stock.code,
    name: stock.name,
    bsp_type: bspType,
    kl_type: klTypes[(i + 2) % klTypes.length],
    source_type: sourceType,
    strategy_label: sourceType === 'strategy' ? '放量首板回调 · 回调5日 · 已触发' : undefined,
    instance_id: instanceId,
    direction,
    bsp_price: bspPrice,
    end_price: endPrice,
    profit,
    bsp_date: Date.now() - Math.floor(r * 60 + 5) * 86400000,
    end_date: Date.now() - Math.floor(r * 5) * 86400000,
    hold_days: Math.floor(r * 30 + 2),
    attribution,
    group_id: groupId,
  }
})
