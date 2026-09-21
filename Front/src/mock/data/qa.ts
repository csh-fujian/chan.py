import type { QaRecord } from '@/api/types'

let nextQaId = 100

/** 问答记录 mock（内存态，时间倒序展示由列表页处理） */
export const qaRecords: QaRecord[] = [
  {
    id: nextQaId++,
    question: '平安银行当前日线级别处于哪个买卖点区间？',
    answer:
      '从缠论视角看，sz.000001 日线级别当前处于一个中枢震荡后的第三类买点（T3A）附近。该买点形成于价格回抽中枢上沿不破后再度向上，配合成交量温和放大。建议结合 30 分钟级别确认背驰信号，若出现底背驰则可视为相对安全的介入点，止损参考中枢下沿。',
    starred: true,
    created_at: Date.now() - 1000 * 60 * 60 * 26,
  },
  {
    id: nextQaId++,
    question: '帮我解释一下线段与笔的区别',
    answer:
      '笔是缠论中最基础的走势单元，由相邻的顶分型与底分型连接而成，且顶底之间至少相隔一根独立 K 线。线段则是由至少三笔构成，且前三笔必须有重叠区间。笔反映短期多空力量的转换，线段反映的是更高级别的走势方向，稳定性更高，是构建中枢的基本材料。',
    starred: false,
    created_at: Date.now() - 1000 * 60 * 60 * 50,
  },
  {
    id: nextQaId++,
    question: '茅台周线级别的中枢在哪里？',
    answer:
      'sh.600519 周线级别在 1600–1800 元区间形成了较长时间的盘整中枢。当前价格处于中枢上沿附近，若放量有效突破并回踩确认，则有望开启新一轮上涨；若突破失败回落至中枢内部，则继续维持震荡格局，等待方向选择。',
    starred: false,
    created_at: Date.now() - 1000 * 60 * 60 * 74,
  },
]

/** 生成 mock 回答 */
function mockAnswer(question: string): string {
  const lower = question.toLowerCase()
  if (lower.includes('买') || lower.includes('卖')) {
    return (
      `针对「${question}」的缠论解读：买卖点的确认需要多级别联立。` +
      '建议先在日线级别寻找背驰，再到 30 分钟级别等待第三类买卖点的确认信号，' +
      '同时参考中枢区间与成交量变化，避免在未确认时追涨杀跌。'
    )
  }
  if (lower.includes('中枢')) {
    return (
      `针对「${question}」：中枢由至少三段次级别走势的重叠区间构成，是趋势中继或转折的关键。` +
      '判断中枢强弱可观察其延伸段数、离开段力度以及与成交量的配合。'
    )
  }
  if (lower.includes('笔') || lower.includes('段')) {
    return (
      `针对「${question}」：笔是顶底分型连接的最小走势单元，线段由至少三笔构成且前三笔重叠。` +
      '理解两者的包含关系与级别递进，是掌握缠论结构分析的基础。'
    )
  }
  return (
    `关于「${question}」，从缠论角度看：任何走势都由「走势类型—中枢—背驰」三级结构递归构成。` +
    '建议先明确分析级别，再结合分型、笔、线段、中枢与买卖点的层级关系进行综合研判。'
  )
}

/** 提问：生成回答并落库 */
export function askQa(question: string): QaRecord {
  const rec: QaRecord = {
    id: nextQaId++,
    question,
    answer: mockAnswer(question),
    starred: false,
    created_at: Date.now(),
  }
  qaRecords.unshift(rec)
  return rec
}

/** 获取记录列表（时间倒序） */
export function listQa(): QaRecord[] {
  return [...qaRecords].sort((a, b) => b.created_at - a.created_at)
}

/** 单条打星 */
export function starQa(id: number, starred: boolean) {
  const rec = qaRecords.find((r) => r.id === id)
  if (rec) rec.starred = starred
}

/** 批量打星 */
export function batchStarQa(ids: number[], starred: boolean) {
  for (const id of ids) {
    const rec = qaRecords.find((r) => r.id === id)
    if (rec) rec.starred = starred
  }
}

/** 一键删除未打星记录，返回删除条数 */
export function deleteUnstarredQa(): number {
  const before = qaRecords.length
  for (let i = qaRecords.length - 1; i >= 0; i--) {
    if (!qaRecords[i].starred) qaRecords.splice(i, 1)
  }
  return before - qaRecords.length
}
