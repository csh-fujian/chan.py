// bspLadder.ts — 买卖点确认阶梯三轴定义与工具（chan-bsp-ladder-change）
//
// 前端唯一词表：K 线图 hover 说明卡（kline-unsure-visual）与买卖点页「级别」列
// （bsp-page）共用，避免两处文案漂移。语义与后端 WebAPI/bsp_ladder.py 对齐。
//
// ## 三轴模型
//
// 未确认的第一类买卖点家族（1/1p）候选点携带三轴独立证据，落库为竖线分隔的
// 组合串（如 `L2|L2-3|L3-2`），轴顺序固定：进度 → 佐证 → 分型：
//
//   进度轴   L1 判据链前半链（1~4 步） / L2 后半链（5~7 步）
//   佐证轴   L2-3 子级已确认买点 / L2-2 子级候选部分达成 / L2-1 子级末端分型
//   分型轴   L3-3 强 / L3-2 中 / L3-1 弱
//
// `L4` = 已确认买卖点（单值，语义不变）；NULL = 未定级（非一买类型本次未接入，
// 或不可评估）。
//
// ## 与原四级阶梯的差异
//
// 旧定义（L1 小级别区间套 / L2 虚笔候选 / L3 背驰预警 / L4 确认）是**平行标签**，
// 与买卖点成立性判据链无结构关联。新定义是**递进式证据体系**：进度轴回答
// 「离成立还差几步」，佐证轴回答「子级是否同向共振」，分型轴回答「本级反转多强」。

export type ProgressLevel = 'L1' | 'L2'
export type CorroborationLevel = 'L2-3' | 'L2-2' | 'L2-1'
export type FractalLevel = 'L3-3' | 'L3-2' | 'L3-1'
export type LadderAxis = ProgressLevel | CorroborationLevel | FractalLevel
export type LadderLevel = LadderAxis | 'L4'

/** 轴标识：进度轴复用了 L1/L2 前缀，需靠取值形状区分 */
export type AxisKind = 'progress' | 'corroboration' | 'confirm' | 'fractal' | 'time'

export interface AxisInfo {
  /** 轴标识 */
  kind: AxisKind
  /** 轴名称 */
  axis: string
  /** 该档名称 */
  name: string
  /** 一句说明 */
  desc: string
}

export interface LadderInfo {
  /** 原始标签（如 `L1` / `L2-3` / `L4`） */
  level: LadderLevel
  /** 所属轴（L4 为 'confirmed'） */
  kind: AxisKind | 'confirmed'
  /** 轴名称（L4 为「确认买卖点」） */
  axis: string
  /** 该档名称 */
  name: string
  /** 一句说明 */
  desc: string
}

/** 进度轴：判据链推进程度（1~4 步 → L1，5~7 步 → L2）
 *
 *  `name` 是**用户读到的档位名**，必须是白话结论，不能是内部坐标系术语：
 *  旧文案「前半链 / 后半链」只说了「在 7 项里的哪一半」，用户既不知道有 7 项，
 *  也不知道过了后半链算好还是坏。改成「初步成形 / 接近成立」后，用户扫一眼
 *  就知道证据走到了哪一步。编号 L1/L2 仍显示在徽章上，作为辅助标识。
 *  `desc` 同步改写成「已经确认了什么、还差什么」。 */
export const PROGRESS_LEVELS: readonly AxisInfo[] = [
  {
    kind: 'progress',
    axis: '判据进度',
    name: '初步成形',
    desc: '趋势和突破已经确认，但这一段的力度还没有弱于前一段，买点还不成立',
  },
  {
    kind: 'progress',
    axis: '判据进度',
    name: '接近成立',
    desc: '趋势、突破、极值、力度背驰都已确认，正在检查新低 / 黄白线 / 零轴这些收尾条件',
  },
]

/** 佐证轴：次级别结构佐证（结构映射窗口）
 *
 *  旧文案「子级已确认点 / 子级候选 / 子级分型」是开发者口径（`子级`、`候选`
 *  都是内部术语）。改成「低一级已确认 / 低一级有苗头 / 低一级出现反转」，
 *  并点明「低一级」指的是更低的时间周期。 */
export const CORROBORATION_LEVELS: readonly AxisInfo[] = [
  {
    kind: 'corroboration',
    axis: '小级别印证',
    name: '小级别已见底',
    desc: '更小周期上已经出现并确认了同向买点，大级别与小级别方向一致（最有力的印证）',
  },
  {
    kind: 'corroboration',
    axis: '小级别印证',
    name: '小级别有苗头',
    desc: '更小周期上出现了同向买点候选，判据链已推进过半，但还没最终确认',
  },
  {
    kind: 'corroboration',
    axis: '小级别印证',
    name: '小级别刚转向',
    desc: '更小周期末端刚形成反转形态，是最早的微观信号，可靠性最低',
  },
]

/** 分型轴：本级末端分型强弱（实体口径，A 为前一合并 K 线） */
export const FRACTAL_LEVELS: readonly AxisInfo[] = [
  {
    kind: 'fractal',
    axis: '反转力度',
    name: '强',
    desc: '转折那根 K 线收复了前一根的整个实体，反转坚决',
  },
  {
    kind: 'fractal',
    axis: '反转力度',
    name: '中',
    desc: '转折那根 K 线收复了前一根实体的一半以上，反转成立但不算强势',
  },
  {
    kind: 'fractal',
    axis: '反转力度',
    name: '弱',
    desc: '没收复前一根实体的一半，可能只是下跌（上涨）途中的停顿，反转未必真',
  },
]

/** L4 确认买卖点（语义不变） */
export const CONFIRMED_INFO: LadderInfo = {
  level: 'L4',
  kind: 'confirmed',
  axis: '结论',
  name: '已成立',
  desc: '依托的线段已经走完并确认，这个买卖点定型，不会再随重算消失或变化',
}

/** 判定顺序脚注（tooltip 底部说明） */
export const LADDER_ORDER_NOTE =
  '各项独立评估：判据进度、小级别印证、事后确认、反转力度、回调速度；已成立 = 信号定型'

/**
 * 仓位指引 → 用「证据够不够」的措辞，不用「满仓 / 加仓」。
 *
 * 旧实现返回「满仓 / 加仓至 1/2 / 观察仓 1/4」，那是**仓位指令**，
 * 用户会当成操作建议直接执行。改为描述证据强度的短语，与实际回测结论
 * （未确认信号 T+10 胜率约 41.67%）的风险水平相符。
 *
 * 真正的「能不能买」结论统一由后端 `grade.advice` 给出（见 `bsp_grade.py`），
 * 本函数只用于 tooltip 行尾的简写标注。
 */
export function ladderPosition(parsed: ParsedLadder | null, isBuy: boolean): string {
  if (!parsed) return '证据不足'
  if (parsed.confirmed) return '已成立'
  // 进度轴在 T1 是 L1/L2、在 T2 是 P1/P2；两者都表示「判据链已过半」
  const p = parsed.progress as string | undefined
  if (p === 'L2' || p === 'P2') return '接近成立'
  return '初步成形'
}

// ----------------------------------------------------------------------
// 买卖点分级（chan-bsp-grading）—— 强度分与操作建议
// ----------------------------------------------------------------------

/** 后端 `grade` 字段结构（`WebAPI/bsp_grade.py:grade_bsp` 输出） */
export interface BspGrade {
  /** 0~100 强度分；已确认恒为 100 */
  score: number
  /** 强弱定性：很强 / 较强 / 一般 / 偏弱 / 很弱 */
  grade: string
  /** 操作建议（用户可读的一句话） */
  advice: string
  /** 是否已确认 */
  confirmed: boolean
  /** 卡在哪一步（未确认时才有；已确认为 null） */
  blocked_by?: string | null
  /** 免责声明 */
  disclaimer?: string
}

/** 强度分 → 颜色档位（前端渲染用；与后端 `_GRADES` 的下限对齐） */
export function gradeTone(score: number): 'strong' | 'good' | 'mid' | 'weak' | 'poor' {
  if (score >= 80) return 'strong'
  if (score >= 60) return 'good'
  if (score >= 40) return 'mid'
  if (score >= 20) return 'weak'
  return 'poor'
}

/** 强度分 → 一句话的直观标签（分数过低与已确认时给更强的措辞） */
export function gradeSummary(g: BspGrade | null | undefined): string {
  if (!g) return '无评估'
  if (g.confirmed) return '已成立'
  return `${g.score} 分 · ${g.grade}`
}

// ----------------------------------------------------------------------
// T2 五轴（P|S|C|K|T）与 T3 四轴（S|C|K|T）——前缀互不冲突
//
// 两套语法共用同一套轴字母，靠 bsp_type 路由区分（后端 cal_ladder 分派）：
//   T2/T2S  五轴：P 进度 → S 佐证 → C 确认 → K 分型 → T 时间
//   T3A/T3B 四轴：      S 佐证 → C 确认 → K 分型 → T 时间（无进度轴）
// 与 T1 三轴（L 编号）语法完全不同，解析时按段前缀识别，互不干扰。
// ----------------------------------------------------------------------

/** T2 五轴档位（P1/P2、S3/S2/S1、C3/C2/C1/C0、K3/K2/K1、T3/T2/T1）
 *
 *  文案与 T1 同一原则：`name` 是用户能读的结论，`desc` 说清「已经确认了什么 /
 *  还差什么」，不出现「判据链」「轴」「c 走势段」这类内部术语。 */
export const T2_AXIS_INFOS: LadderInfo[] = [
  { level: 'P1' as LadderLevel, kind: 'progress', axis: '判据进度', name: '初步成形', desc: '一买成立、回调发生、没跌破一买低点，这三项已经过；回调幅度还没比对上' },
  { level: 'P2' as LadderLevel, kind: 'progress', axis: '判据进度', name: '接近成立', desc: '回调幅度和中枢关联也已确认，只差最后的价格确认' },
  { level: 'S3' as LadderLevel, kind: 'corroboration', axis: '小级别印证', name: '小级别已见底', desc: '回调期间更小周期已出现并确认同向买点（最有力的印证）' },
  { level: 'S2' as LadderLevel, kind: 'corroboration', axis: '小级别印证', name: '小级别有苗头', desc: '回调期间更小周期出现同向买点候选，判据已推进过半' },
  { level: 'S1' as LadderLevel, kind: 'corroboration', axis: '小级别印证', name: '小级别刚转向', desc: '回调期间更小周期末端刚形成反转形态（最早的微观信号）' },
  { level: 'C3' as LadderLevel, kind: 'confirm', axis: '事后确认', name: '已确认', desc: '回调之后价格重新突破，二买得到确认' },
  { level: 'C2' as LadderLevel, kind: 'confirm', axis: '事后确认', name: '收复大半', desc: '已经收复回调幅度的一半以上，但还没完全突破' },
  { level: 'C1' as LadderLevel, kind: 'confirm', axis: '事后确认', name: '确认失败', desc: '观察期走完仍未收复一半幅度，这个二买判定为失败（不会撤销，只降级标记）' },
  { level: 'C0' as LadderLevel, kind: 'confirm', axis: '事后确认', name: '还在观察', desc: '观察期数据还没走完（行情太新），不是最终结论' },
  { level: 'K3' as LadderLevel, kind: 'fractal', axis: '反转力度', name: '强', desc: '回调末端那根 K 线收复了前一根的整个实体，止跌坚决' },
  { level: 'K2' as LadderLevel, kind: 'fractal', axis: '反转力度', name: '中', desc: '回调末端收复了前一根实体的一半以上' },
  { level: 'K1' as LadderLevel, kind: 'fractal', axis: '反转力度', name: '弱', desc: '回调末端没收复前一根实体的一半，止跌不明显' },
  { level: 'T3' as LadderLevel, kind: 'time', axis: '回调速度', name: '缓跌（好）', desc: '回调又慢又浅，说明抛压在衰竭，是健康回调' },
  { level: 'T2' as LadderLevel, kind: 'time', axis: '回调速度', name: '均衡', desc: '回调的跌速与之前涨速大致相当' },
  { level: 'T1' as LadderLevel, kind: 'time', axis: '回调速度', name: '急跌（差）', desc: '回调又急又猛，跌速明显快于此前涨速，抛压还很重' },
]

/** T3 四轴档位（与 T2 同字母；判据对象换成「回抽」）*/
export const T3_AXIS_INFOS: LadderInfo[] = [
  { level: 'S3' as LadderLevel, kind: 'corroboration', axis: '小级别印证', name: '小级别已见底', desc: '回抽期间更小周期已出现并确认同向买卖点（最有力的印证）' },
  { level: 'S2' as LadderLevel, kind: 'corroboration', axis: '小级别印证', name: '小级别有苗头', desc: '回抽期间更小周期出现同向买卖点候选' },
  { level: 'S1' as LadderLevel, kind: 'corroboration', axis: '小级别印证', name: '小级别刚转向', desc: '回抽期间更小周期末端刚形成反转形态（最早的微观信号）' },
  { level: 'C3' as LadderLevel, kind: 'confirm', axis: '事后确认', name: '已确认', desc: '回抽之后价格继续突破，三买得到确认，趋势延续成立' },
  { level: 'C2' as LadderLevel, kind: 'confirm', axis: '事后确认', name: '收复大半', desc: '已经收复回抽幅度的一半以上，但还没完全突破' },
  { level: 'C1' as LadderLevel, kind: 'confirm', axis: '事后确认', name: '判定失败', desc: '价格跌回中枢区间，或观察期走完仍未收复，这个三买是假的' },
  { level: 'C0' as LadderLevel, kind: 'confirm', axis: '事后确认', name: '还在观察', desc: '观察期数据还没走完（行情太新），不是最终结论' },
  { level: 'K3' as LadderLevel, kind: 'fractal', axis: '反转力度', name: '强', desc: '回抽末端那根 K 线收复了前一根的整个实体，反转坚决' },
  { level: 'K2' as LadderLevel, kind: 'fractal', axis: '反转力度', name: '中', desc: '回抽末端收复了前一根实体的一半以上' },
  { level: 'K1' as LadderLevel, kind: 'fractal', axis: '反转力度', name: '弱', desc: '回抽末端没收复前一根实体的一半，回抽动能仍强' },
  { level: 'T3' as LadderLevel, kind: 'time', axis: '回抽速度', name: '缓跌（好）', desc: '回抽又慢又浅，说明抛压在衰竭，是健康回抽' },
  { level: 'T2' as LadderLevel, kind: 'time', axis: '回抽速度', name: '均衡', desc: '回抽的跌速与之前涨速大致相当' },
  { level: 'T1' as LadderLevel, kind: 'time', axis: '回抽速度', name: '急跌（差）', desc: '回抽又急又猛，跌速明显快于此前涨速，抛压还很重' },
]

/** 全部档位索引（T1 三轴 + T2 五轴 + T3 四轴；同名字符串以后者覆盖，语义一致） */
const AXIS_MAP: Record<string, LadderInfo> = Object.fromEntries(
  [
    ...[...PROGRESS_LEVELS, ...CORROBORATION_LEVELS, ...FRACTAL_LEVELS].map((a, i) => {
      const level =
        a.kind === 'progress'
          ? (i === 0 ? 'L1' : 'L2')
          : a.kind === 'corroboration'
            ? (['L2-3', 'L2-2', 'L2-1'] as const)[i - PROGRESS_LEVELS.length]
            : (['L3-3', 'L3-2', 'L3-1'] as const)[i - PROGRESS_LEVELS.length - CORROBORATION_LEVELS.length]
      return [level, { level, kind: a.kind, axis: a.axis, name: a.name, desc: a.desc }] as const
    }),
    ...T3_AXIS_INFOS.map((a) => [a.level, a] as const),
    ...T2_AXIS_INFOS.map((a) => [a.level, a] as const),
  ],
)

/** 组合的解析结果（T1 三轴 / T2 五轴 / T3 四轴共用） */
export interface ParsedLadder {
  /** 是否已确认（L4） */
  confirmed: boolean
  /** 进度轴（T1: L1/L2；T2: P1/P2），无则 undefined */
  progress?: LadderLevel
  /** 佐证轴（T1: L2-x；T2/T3: S3/S2/S1），无则 undefined */
  corroboration?: LadderLevel
  /** 确认轴（T2/T3: C3/C2/C1/C0），无则 undefined */
  confirm?: LadderLevel
  /** 分型轴（T1: L3-x；T2/T3: K3/K2/K1），无则 undefined */
  fractal?: LadderLevel
  /** 时间轴（T2/T3: T3/T2/T1），无则 undefined */
  time?: LadderLevel
  /** 全部轴标签（按组合串原序） */
  axes: LadderLevel[]
}

/**
 * 解析 ladder 组合串。
 *
 * @param raw 后端返回值：`'L4'` / `'L1|L2-3|L3-2'` / `null` / `undefined`
 * @returns 已确认时 `{ confirmed: true, axes: ['L4'] }`；
 *          组合值按轴归位；NULL/非法值返回 `null`（调用方兜底「未定级」）
 */
export function parseLadder(raw: string | null | undefined): ParsedLadder | null {
  if (!raw) return null
  const trimmed = raw.trim()
  if (!trimmed) return null
  if (trimmed === 'L4') {
    return { confirmed: true, axes: ['L4'] }
  }
  const parts = trimmed.split('|').map((s) => s.trim()).filter(Boolean)
  if (!parts.length) return null
  const result: ParsedLadder = { confirmed: false, axes: [] }
  for (const p of parts) {
    const info = AXIS_MAP[p]
    if (!info) {
      // 非法档位（版本不匹配 / 脏数据）：跳过该轴，不整条判失败
      continue
    }
    const level = p as LadderLevel
    if (info.kind === 'progress' && !result.progress) result.progress = level
    else if (info.kind === 'corroboration' && !result.corroboration) result.corroboration = level
    else if (info.kind === 'confirm' && !result.confirm) result.confirm = level
    else if (info.kind === 'fractal' && !result.fractal) result.fractal = level
    else if (info.kind === 'time' && !result.time) result.time = level
    result.axes.push(level)
  }
  if (!result.axes.length) return null
  return result
}

/** 是否为合法阶梯值（`L4` 或组合串中至少一档合法） */
export function isLadder(v: unknown): v is string {
  if (typeof v !== 'string') return false
  return parseLadder(v) !== null
}

/** 取单档定义；L4 返回确认说明，非法值返回 null（调用方兜底「未定级」） */
export function ladderInfo(v: string | null | undefined): LadderInfo | null {
  if (!v) return null
  if (v === 'L4') return CONFIRMED_INFO
  return AXIS_MAP[v] ?? null
}

/** 取整条阶梯的全部档位定义（组合串逐档展开；非法档跳过） */
export function ladderInfos(raw: string | null | undefined): LadderInfo[] {
  const parsed = parseLadder(raw)
  if (!parsed) return []
  return parsed.axes.map((l) => ladderInfo(l)).filter((x): x is LadderInfo => x !== null)
}

/**
 * 强度分 → 颜色档位（前端渲染用；与后端 `_GRADES` 的下限对齐）
 */
