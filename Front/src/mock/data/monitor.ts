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
}

/** 监控中 6 条 + sz.000001 样例 1 条 */
export const monitorItems: MonitorItem[] = [
  sz000001Monitoring,
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
    }
  }),
]

/** 完成 6 条 + sz.000001 样例 1 条 */
export const completedItems: CompletedItem[] = [
  sz000001Completed,
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
