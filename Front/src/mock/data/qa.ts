import type { QaRecord } from '@/api/types'
import { DEFAULT_SYSTEM_PROMPT } from './qaDefaultPrompt'
import { activeLlmProvider } from './system'

export { DEFAULT_SYSTEM_PROMPT }

/** mock 记录带 user_id，模拟 PG 按用户隔离（design D4） */
export interface MockQaRecord extends QaRecord {
  user_id: number
}

let nextQaId = 100

/** 问答记录 mock（内存态，按 user_id 分桶，测试账号互不可见） */
export const qaRecords: MockQaRecord[] = [
  // admin(1) — 原有演示记录
  {
    id: nextQaId++,
    user_id: 1,
    question: '平安银行当前日线级别处于哪个买卖点区间？',
    answer:
      '从缠论视角看，sz.000001 日线级别当前处于一个中枢震荡后的第三类买点（T3A）附近。该买点形成于价格回抽中枢上沿不破后再度向上，配合成交量温和放大。建议结合 30 分钟级别确认背驰信号，若出现底背驰则可视为相对安全的介入点，止损参考中枢下沿。',
    starred: true,
    created_at: Date.now() - 1000 * 60 * 60 * 26,
  },
  {
    id: nextQaId++,
    user_id: 1,
    question: '帮我解释一下线段与笔的区别',
    answer:
      '笔是缠论中最基础的走势单元，由相邻的顶分型与底分型连接而成，且顶底之间至少相隔一根独立 K 线。线段则是由至少三笔构成，且前三笔必须有重叠区间。笔反映短期多空力量的转换，线段反映的是更高级别的走势方向，稳定性更高，是构建中枢的基本材料。',
    starred: false,
    created_at: Date.now() - 1000 * 60 * 60 * 50,
  },
  {
    id: nextQaId++,
    user_id: 1,
    question: '茅台周线级别的中枢在哪里？',
    answer:
      'sh.600519 周线级别在 1600–1800 元区间形成了较长时间的盘整中枢。当前价格处于中枢上沿附近，若放量有效突破并回踩确认，则有望开启新一轮上涨；若突破失败回落至中枢内部，则继续维持震荡格局，等待方向选择。',
    starred: false,
    created_at: Date.now() - 1000 * 60 * 60 * 74,
  },
  // trader(2) / viewer(3) — 用于验证按用户隔离
  {
    id: nextQaId++,
    user_id: 2,
    question: '什么是第三类买点？',
    answer:
      '第三类买点指价格向上离开中枢后回抽不回中枢区间（回踩中枢上沿之上）的确认点，是趋势延续类买点。实战中需结合次级别回抽结束信号与量能确认，并以中枢上沿作为止损参考。',
    starred: true,
    created_at: Date.now() - 1000 * 60 * 60 * 30,
  },
  {
    id: nextQaId++,
    user_id: 3,
    question: '如何判断背驰？',
    answer:
      '背驰的判定要结合走势形态（盘整背驰/趋势背驰）与动力学指标衰竭（MACD 面积或柱体收缩、成交量缩量）双重视角，严格区分背驰与盘整背驰。',
    starred: false,
    created_at: Date.now() - 1000 * 60 * 60 * 12,
  },
]

/** 系统提示词按用户存储（key 缺省/空串 = 使用内置默认，design D8.3） */
const systemPrompts = new Map<number, string>()

export function getSystemPromptFor(userId: number): string {
  return systemPrompts.get(userId) || DEFAULT_SYSTEM_PROMPT
}

export function setSystemPromptFor(userId: number, prompt: string): void {
  systemPrompts.set(userId, prompt)
}

/** 是否使用了自定义提示词（mock 回答里标注，便于验证 6.3） */
function isCustomPrompt(userId: number): boolean {
  return !!systemPrompts.get(userId)
}

export interface AskContext {
  question: string
  code?: string
  period?: string
}

const PERIOD_LABELS: Record<string, string> = {
  '5m': '5分钟', '15m': '15分钟', '30m': '30分钟', '60m': '60分钟',
  '1d': '日线', '1w': '周线', '1M': '月线',
}

/** 生成 mock 回答（含 code/period 上下文标注，模拟 design D8.4 结构注入） */
export function mockAnswer(ctx: AskContext, userId: number): string {
  const { question, code, period } = ctx
  const lower = question.toLowerCase()
  let body: string
  if (lower.includes('买') || lower.includes('卖')) {
    body =
      `针对「${question}」的缠论解读：买卖点的确认需要多级别联立。` +
      '建议先在日线级别寻找背驰，再到 30 分钟级别等待第三类买卖点的确认信号，' +
      '同时参考中枢区间与成交量变化，避免在未确认时追涨杀跌。'
  } else if (lower.includes('中枢')) {
    body =
      `针对「${question}」：中枢由至少三段次级别走势的重叠区间构成，是趋势中继或转折的关键。` +
      '判断中枢强弱可观察其延伸段数、离开段力度以及与成交量的配合。'
  } else if (lower.includes('笔') || lower.includes('段')) {
    body =
      `针对「${question}」：笔是顶底分型连接的最小走势单元，线段由至少三笔构成且前三笔重叠。` +
      '理解两者的包含关系与级别递进，是掌握缠论结构分析的基础。'
  } else {
    body =
      `关于「${question}」，从缠论角度看：任何走势都由「走势类型—中枢—背驰」三级结构递归构成。` +
      '建议先明确分析级别，再结合分型、笔、线段、中枢与买卖点的层级关系进行综合研判。'
  }

  // mock 注脚：直观呈现 code/period 已传入（D8.4 注入）、提示词来源与激活供应商
  const notes: string[] = []
  if (code) {
    const periodLabel = (period && PERIOD_LABELS[period]) || period || '当前周期'
    notes.push(`已注入 ${code} · ${periodLabel} 缠论结构上下文`)
  } else {
    notes.push('未携带股票上下文，按纯文本问答')
  }
  notes.push(isCustomPrompt(userId) ? '自定义系统提示词' : '默认系统提示词')
  notes.push(`供应商 ${activeProviderLabel()}`)
  return `${body}\n\n（mock：${notes.join(' · ')}）`
}

/** 激活供应商标注（无激活预设时提示未配置） */
function activeProviderLabel(): string {
  const p = activeLlmProvider()
  return p ? `${p.name} / ${p.model}` : 'LLM 未配置'
}

/** 提问：生成回答并落库（仅在流式完成时由 handler 调用，中断不落库） */
export function askQa(userId: number, ctx: AskContext): MockQaRecord {
  const rec: MockQaRecord = {
    id: nextQaId++,
    user_id: userId,
    question: ctx.question,
    answer: mockAnswer(ctx, userId),
    starred: false,
    created_at: Date.now(),
  }
  qaRecords.push(rec)
  return rec
}

/** 对外契约视图（QaRecord 不含 user_id） */
export function toQaRecord(rec: MockQaRecord): QaRecord {
  const { id, question, answer, starred, created_at } = rec
  return { id, question, answer, starred, created_at }
}

/** 获取记录列表（本人，时间倒序） */
export function listQa(userId: number): QaRecord[] {
  return qaRecords
    .filter((r) => r.user_id === userId)
    .sort((a, b) => b.created_at - a.created_at)
    .map(toQaRecord)
}

/** 单条打星（仅本人） */
export function starQa(userId: number, id: number, starred: boolean) {
  const rec = qaRecords.find((r) => r.id === id && r.user_id === userId)
  if (rec) rec.starred = starred
}

/** 批量打星（仅本人，design D4：批量按 ids + user_id 过滤） */
export function batchStarQa(userId: number, ids: number[], starred: boolean) {
  for (const id of ids) {
    starQa(userId, id, starred)
  }
}

/** 一键删除未打星记录（仅本人），返回删除条数 */
export function deleteUnstarredQa(userId: number): number {
  let count = 0
  for (let i = qaRecords.length - 1; i >= 0; i--) {
    const r = qaRecords[i]
    if (r.user_id === userId && !r.starred) {
      qaRecords.splice(i, 1)
      count++
    }
  }
  return count
}
