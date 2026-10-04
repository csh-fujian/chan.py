import type { MonitorItem, CompletedItem, AttributionRecord } from '@/api/types'
import { stocks } from './stocks'

const bspTypes = ['1B', '2B', '3B', '1S', '2S', 'L2B']
const klTypes = ['30m', '60m', 'D', 'W', 'M']
const attributions = [
  '本级别出现一买信号，次级别底背离确认，区间套共振明显，建议持有。',
  '二买点形成后价格突破中枢上沿，量能配合良好，趋势确立。',
  '三买点后出现回调，但未跌回中枢，属强势调整，继续持有。',
  '一卖信号触发，顶分型确认，建议减仓观望。',
  '中枢扩展后选择向上突破，线段级别买点成立。',
  '小级别背驰引发大级别转折，区间套买点有效。',
]

function rand(i: number) {
  return ((i * 9301 + 49297) % 233280) / 233280
}

// ---------------------------------------------------------------------------
// 来源字典（design D14）：GET /monitor/sources 的 mock 数据，
// distinct (source_type, instance_id) + 实例名，与真后端 list_monitor_sources 语义一致
// ---------------------------------------------------------------------------
export interface MonitorSourceMock {
  value: string
  label: string
  source_type: 'chan' | 'strategy' | 'watchlist'
  instance_id?: number
}

/** 策略实例 id（与 strategyMonitoring/strategyCompleted 的来源对应） */
const MOCK_STRATEGY_INSTANCE_ID = 5

export const monitorSources: MonitorSourceMock[] = [
  { value: 'chan', label: '缠论', source_type: 'chan' },
  { value: `strategy:${MOCK_STRATEGY_INSTANCE_ID}`, label: '放量首板回调 · 回调5日', source_type: 'strategy', instance_id: MOCK_STRATEGY_INSTANCE_ID },
  { value: 'watchlist', label: '自选', source_type: 'watchlist' },
]

// ---------------------------------------------------------------------------
// 监控分组（monitor-group-change）：预置 2 个分组 + 未分组记录混合，
// 供左侧栏分组树 / 弹窗下拉 / 列表 group_id 过滤联调
// ---------------------------------------------------------------------------
export interface MonitorGroupMock {
  id: number
  name: string
  sort_order: number
}

export const monitorGroups: MonitorGroupMock[] = [
  { id: 1, name: '短线', sort_order: 0 },
  { id: 2, name: '波段', sort_order: 1 },
]

let nextGroupId = 3

/** 创建分组：名称查重 + sort_order 末尾追加；非法/重名抛错（由 handler 转 4xx） */
export function createGroup(name: string): MonitorGroupMock {
  const n = name.trim()
  if (!n) throw new Error('分组名称不能为空')
  if (monitorGroups.some((g) => g.name === n)) throw new Error(`分组「${n}」已存在`)
  const g = { id: nextGroupId++, name: n, sort_order: monitorGroups.length }
  monitorGroups.push(g)
  return g
}

/** 重命名分组：查重 + 不存在报错 */
export function renameGroup(id: number, name: string) {
  const n = name.trim()
  if (!n) throw new Error('分组名称不能为空')
  const g = monitorGroups.find((x) => x.id === id)
  if (!g) throw new Error(`分组 ${id} 不存在`)
  if (monitorGroups.some((x) => x.id !== id && x.name === n)) throw new Error(`分组「${n}」已存在`)
  g.name = n
}

/** 删除分组：组内监控记录 group_id 置 null（归入「未分组」，D1 SET NULL 语义） */
export function removeGroup(id: number) {
  const idx = monitorGroups.findIndex((x) => x.id === id)
  if (idx < 0) throw new Error(`分组 ${id} 不存在`)
  monitorGroups.splice(idx, 1)
  monitorItems.forEach((r) => {
    if (r.group_id === id) r.group_id = null
  })
  completedItems.forEach((r) => {
    if (r.group_id === id) r.group_id = null
  })
}

/** 重排分组顺序：按 ids 全量覆盖（下标即新序），未列出的保持在末尾 */
export function reorderGroups(ids: number[]) {
  const byId = new Map(monitorGroups.map((g) => [g.id, g]))
  const next: MonitorGroupMock[] = []
  for (const id of ids) {
    const g = byId.get(id)
    if (g) {
      next.push(g)
      byId.delete(id)
    }
  }
  byId.forEach((g) => next.push(g))
  monitorGroups.splice(0, monitorGroups.length, ...next)
  monitorGroups.forEach((g, i) => (g.sort_order = i))
}

/** group_id 过滤参数语义（design D3）：缺省不过滤 / 'ungrouped' → IS NULL / 数值 → 精确匹配 */
export function filterByGroupId<T extends { group_id: number | null }>(
  list: T[],
  groupId: string | null,
): T[] {
  if (!groupId) return list
  if (groupId === 'ungrouped') return list.filter((r) => r.group_id === null)
  const id = Number(groupId)
  if (!Number.isInteger(id) || id <= 0) return list
  return list.filter((r) => r.group_id === id)
}


/**
 * sz.000001（平安银行）样例监控行 —— K 线页默认股票，供图表虚拟买卖点联调
 *（kline-chart-change D6）。时间带时分（验证按日吸附到 bar）；日期落在 mock 日线
 * 序列（2026-07-01 起 120 根）内，且对齐笔端点 bar（下标 24/42/48，见 kline.ts
 * genBi/genBsp），便于观察与缠论买卖点的共存左右排布。
 */
const sz000001Monitoring: MonitorItem = {
  id: 9001,
  code: 'sz.000001',
  name: '平安银行',
  industries: ['银行'],
  bsp_type: '2B',
  direction: 'buy',
  bsp_price: 11.32,
  current_price: 11.85,
  bsp_date: new Date('2026-08-18T09:45:00').getTime(),
  kl_type: 'D',
  change_pct: 1.23,
  current_pnl_pct: +(((11.85 - 11.32) / 11.32) * 100).toFixed(2),
  max_profit: 4.68,
  max_drawdown: -1.12,
  status: 'monitoring',
  group_id: 1,
}

const sz000001Completed: CompletedItem = {
  id: 9002,
  code: 'sz.000001',
  name: '平安银行',
  industries: ['银行'],
  bsp_type: '2B',
  direction: 'buy',
  bsp_price: 11.58,
  current_price: 11.85,
  bsp_date: new Date('2026-07-25T14:30:00').getTime(),
  kl_type: 'D',
  change_pct: 0.86,
  current_pnl_pct: 7.6,
  max_profit: 8.12,
  max_drawdown: -2.05,
  status: 'completed',
  end_date: new Date('2026-08-12T10:05:00').getTime(),
  end_price: 12.46,
  profit: 7.6,
  attribution: '二买后放量突破中枢上沿，区间套共振，模拟持仓按计划止盈。',
  ai_analyzed: true,
  group_id: 1,
}

/**
 * 策略来源样例监控行（strategy-signal-page design D6 / 任务 6.1）：
 * source_type='strategy' + strategy_label（「策略名 · 实例名 · 状态」），
 * bsp_type 存信号 state 文案（mock 侧与后端 _fill_bsp_context 分叉语义一致），
 * 供监控列表「来源」列与类型列的两种渲染分支联调。
 */
const strategyMonitoring: MonitorItem = {
  id: 9003,
  code: 'sh.600036',
  name: '招商银行',
  industries: ['银行'],
  bsp_type: '已触发',
  direction: 'buy',
  bsp_price: 33.82,
  current_price: 35.67,
  bsp_date: new Date('2026-09-18T00:00:00').getTime(),
  kl_type: 'D',
  change_pct: 0.56,
  current_pnl_pct: +(((35.67 - 33.82) / 33.82) * 100).toFixed(2),
  max_profit: 5.47,
  max_drawdown: -1.36,
  status: 'monitoring',
  group_id: null,
  source_type: 'strategy',
  strategy_label: '放量首板回调 · 回调5日 · 已触发',
  instance_id: MOCK_STRATEGY_INSTANCE_ID,
}

const strategyCompleted: CompletedItem = {
  id: 9004,
  code: 'sh.600519',
  name: '贵州茅台',
  industries: ['白酒', '食品饮料'],
  bsp_type: '已失效',
  direction: 'buy',
  bsp_price: 1720.4,
  current_price: 1685.5,
  bsp_date: new Date('2026-09-01T00:00:00').getTime(),
  kl_type: 'D',
  change_pct: -0.45,
  current_pnl_pct: -2.03,
  max_profit: 1.32,
  max_drawdown: -3.68,
  status: 'completed',
  end_date: new Date('2026-09-25T00:00:00').getTime(),
  end_price: 1685.5,
  profit: -2.03,
  attribution: '放量首板后回调幅度超限，第 5 日未触发介入条件，信号按参数失效。',
  ai_analyzed: false,
  group_id: null,
  source_type: 'strategy',
  strategy_label: '放量首板回调 · 回调5日 · 已失效',
  instance_id: MOCK_STRATEGY_INSTANCE_ID,
}

/**
 * 自选来源样例（已完成，watchlist-page-change 任务 7.2）：source_type='watchlist'，
 * 已完成 tab 来源列显示「自选」，供两个 tab 的来源列渲染分支联调。
 */
const watchlistCompleted: CompletedItem = {
  id: 9006,
  code: 'sz.000651',
  name: '格力电器',
  industries: ['家电'],
  bsp_type: '1B',
  direction: 'buy',
  bsp_price: 36.5,
  current_price: 38.92,
  bsp_date: new Date('2026-08-05T00:00:00').getTime(),
  kl_type: 'D',
  change_pct: -0.56,
  current_pnl_pct: 6.63,
  max_profit: 8.21,
  max_drawdown: -1.75,
  status: 'completed',
  end_date: new Date('2026-09-20T00:00:00').getTime(),
  end_price: 38.92,
  profit: 6.63,
  attribution: '自选人工挑选入场，一买后中枢上移持有至目标位止盈。',
  ai_analyzed: false,
  group_id: null,
  source_type: 'watchlist',
}

/**
 * 自选来源样例（design D14：自选页「加入监控」通道）：source_type='watchlist'，
 * 来源列显示「自选」，供来源下拉过滤联调。
 */
const watchlistMonitoring: MonitorItem = {
  id: 9005,
  code: 'sz.000858',
  name: '五粮液',
  industries: ['白酒', '食品饮料'],
  bsp_type: '2B',
  direction: 'buy',
  bsp_price: 148.6,
  current_price: 152.3,
  bsp_date: new Date('2026-09-22T00:00:00').getTime(),
  kl_type: 'D',
  change_pct: 1.08,
  current_pnl_pct: +(((152.3 - 148.6) / 148.6) * 100).toFixed(2),
  max_profit: 3.12,
  max_drawdown: -0.86,
  status: 'monitoring',
  group_id: null,
  source_type: 'watchlist',
}

/** 监控中 6 条 + sz.000001 样例 1 条 + 策略来源 1 条 + 自选来源 1 条 */
export const monitorItems: MonitorItem[] = [
  sz000001Monitoring,
  strategyMonitoring,
  watchlistMonitoring,
  ...Array.from({ length: 6 }, (_, i): MonitorItem => {
    const stock = stocks[i + 3]
    const r = rand(i + 1)
    const bspType = bspTypes[i % bspTypes.length]
    const direction = bspType.includes('B') ? 'buy' : 'sell'
    const bspPrice = +(stock.price * (0.9 + r * 0.15)).toFixed(2)
    return {
      id: i + 1,
      code: stock.code,
      name: stock.name,
      industries: stock.industries,
      bsp_type: bspType,
      direction: direction as 'buy' | 'sell',
      bsp_price: bspPrice,
      current_price: stock.price,
      bsp_date: Date.now() - Math.floor(r * 20) * 86400000,
      kl_type: klTypes[i % klTypes.length],
      change_pct: +((r - 0.5) * 8).toFixed(2),
      // 收益率（design D8）：与 max_profit 同口径（买卖点价 → 当前价累计涨跌）
      current_pnl_pct: +(((stock.price - bspPrice) / bspPrice) * 100).toFixed(2),
      max_profit: +((stock.price - bspPrice) / bspPrice * 100).toFixed(2),
      max_drawdown: +(r * -5).toFixed(2),
      status: 'monitoring',
      // 分组归属（monitor-group-change）：前 2 条入组 1/2，其余未分组，
      // 与已完成列表分组分布对齐，供两个 tab 的分组过滤联调
      group_id: i < 2 ? i + 1 : null,
    }
  }),
]

/** 完成 6 条 + sz.000001 样例 1 条 + 策略来源 1 条 + 自选来源 1 条 */
export const completedItems: CompletedItem[] = [
  sz000001Completed,
  strategyCompleted,
  watchlistCompleted,
  ...Array.from({ length: 6 }, (_, i): CompletedItem => {
    const stock = stocks[i + 10]
    const r = rand(i + 100)
    const bspType = bspTypes[(i + 2) % bspTypes.length]
    const direction = bspType.includes('B') ? 'buy' : 'sell'
    const bspPrice = +(stock.price * (0.85 + r * 0.2)).toFixed(2)
    const endPrice = +(bspPrice * (1 + (direction === 'buy' ? 1 : -1) * (0.05 + r * 0.15))).toFixed(2)
    const profit = +(((endPrice - bspPrice) / bspPrice) * 100).toFixed(2)
    return {
      id: i + 100,
      code: stock.code,
      name: stock.name,
      industries: stock.industries,
      bsp_type: bspType,
      direction: direction as 'buy' | 'sell',
      bsp_price: bspPrice,
      current_price: stock.price,
      bsp_date: Date.now() - Math.floor(r * 40 + 10) * 86400000,
      kl_type: klTypes[i % klTypes.length],
      change_pct: +((r - 0.5) * 6).toFixed(2),
      current_pnl_pct: profit,
      max_profit: +(Math.abs(profit) + r * 3).toFixed(2),
      max_drawdown: +(r * -4).toFixed(2),
      status: 'completed',
      end_date: Date.now() - Math.floor(r * 5) * 86400000,
      end_price: endPrice,
      profit,
      attribution: attributions[i % attributions.length],
      ai_analyzed: i % 2 === 0,
      // 分组归属（monitor-group-change）：前 2 条入组 1/2，其余未分组，供已完成 tab 过滤验证
      group_id: i < 2 ? i + 1 : null,
    }
  }),
]

/** 14 日盈利时序 */
export function getProfitSeries(): { date: string; value: number }[] {
  const series: { date: string; value: number }[] = []
  let v = 0
  for (let i = 13; i >= 0; i--) {
    const r = rand(i + 200)
    v += (r - 0.45) * 3
    const d = new Date(Date.now() - i * 86400000)
    series.push({
      date: `${d.getMonth() + 1}/${d.getDate()}`,
      value: +v.toFixed(2),
    })
  }
  return series
}

// ---------------------------------------------------------------------------
// 归因生成（design D5：真实结构，不返回占位；成功才落库）
// ---------------------------------------------------------------------------
let nextAttrId = 100

const lossReasonTemplates = [
  {
    reason_type: '缠论失效',
    text: '买卖点后次级别走势未形成确认笔，本级别分型被后续K线破坏，背驰判断失效，属缠论信号在该行情结构下的失效情形。',
  },
  {
    reason_type: '计算逻辑错误',
    text: '特征序列包含处理在该段震荡中合并了本应保留的端点，中枢区间取值偏移，导致买卖点定位偏差，属计算逻辑层面的问题。',
  },
  {
    reason_type: '缠论失效',
    text: '买入后大级别（日线）趋势转入盘整延伸，小级别买点被大级别震荡吞没，区间套共振条件未满足，信号本身失效。',
  },
]

/**
 * 为监控完成标的生成归因记录（模拟 LLM 生成文本），并同步更新标的的
 * attribution / ai_analyzed —— 与真后端 save_attribution 持久化后的行为一致。
 */
export function generateAttribution(item: CompletedItem): AttributionRecord {
  const tpl = lossReasonTemplates[item.id % lossReasonTemplates.length]
  const evidence =
    `【${tpl.reason_type}】标的 ${item.code} ${item.name}（${item.kl_type}）于 ` +
    `${new Date(item.bsp_date).toLocaleDateString('zh-CN')} 出现 ${item.bsp_type}，` +
    `买入价 ${item.bsp_price}，卖出价 ${item.end_price}，最终盈利 ${item.profit.toFixed(2)}%。` +
    `${tpl.text}`
  const record: AttributionRecord = {
    id: nextAttrId++,
    monitor_id: item.id,
    reason_type: tpl.reason_type,
    evidence,
    created_at: Date.now(),
  }
  item.ai_analyzed = true
  item.attribution = evidence
  return record
}
