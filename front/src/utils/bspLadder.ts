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

/** 进度轴：判据链推进程度（1~4 步 → L1，5~7 步 → L2） */
export const PROGRESS_LEVELS: readonly AxisInfo[] = [
  {
    kind: 'progress',
    axis: '判据链进度',
    name: '前半链',
    desc: '一买判据链 ①~④ 项内推进（趋势/突破/极值/力度背驰）',
  },
  {
    kind: 'progress',
    axis: '判据链进度',
    name: '后半链',
    desc: '一买判据链 ⑤~⑦ 项内推进（新低/DIF 背驰/零轴回抽），或七项全过只欠结构确认',
  },
]

/** 佐证轴：次级别结构佐证（结构映射窗口） */
export const CORROBORATION_LEVELS: readonly AxisInfo[] = [
  {
    kind: 'corroboration',
    axis: '子级佐证',
    name: '已确认子级点',
    desc: 'c 走势段映射的次级别区间内存在同向且已确认的一买',
  },
  {
    kind: 'corroboration',
    axis: '子级佐证',
    name: '子级候选',
    desc: '同区间内存在同向子级候选点，其判据链已推进到前半链',
  },
  {
    kind: 'corroboration',
    axis: '子级佐证',
    name: '子级分型',
    desc: '同区间内次级别末端形成同向分型（最早的微观信号）',
  },
]

/** 分型轴：本级末端分型强弱（实体口径，A 为前一合并 K 线） */
export const FRACTAL_LEVELS: readonly AxisInfo[] = [
  {
    kind: 'fractal',
    axis: '分型强弱',
    name: '强',
    desc: '第三根 K 线实体上沿收复前一合并 K 线实体上沿',
  },
  {
    kind: 'fractal',
    axis: '分型强弱',
    name: '中',
    desc: '第三根 K 线实体上沿收复前一根实体一半以上（含相等边界）',
  },
  {
    kind: 'fractal',
    axis: '分型强弱',
    name: '弱',
    desc: '未收复前一根实体一半，可能仅为下跌/上涨中继',
  },
]

/** L4 确认买卖点（语义不变） */
export const CONFIRMED_INFO: LadderInfo = {
  level: 'L4',
  kind: 'confirmed',
  axis: '确认买卖点',
  name: '已确认',
  desc: '依托线段已确认，信号定型，不再随重算漂移',
}

// ----------------------------------------------------------------------
// T2 五轴（P|S|C|K|T）与 T3 四轴（S|C|K|T）——前缀互不冲突
//
// 两套语法共用同一套轴字母，靠 bsp_type 路由区分（后端 cal_ladder 分派）：
//   T2/T2S  五轴：P 进度 → S 佐证 → C 确认 → K 分型 → T 时间
//   T3A/T3B 四轴：      S 佐证 → C 确认 → K 分型 → T 时间（无进度轴）
// 与 T1 三轴（L 编号）语法完全不同，解析时按段前缀识别，互不干扰。
// ----------------------------------------------------------------------

/** T2 五轴档位（P1/P2、S3/S2/S1、C3/C2/C1/C0、K3/K2/K1、T3/T2/T1） */
export const T2_AXIS_INFOS: LadderInfo[] = [
  { level: 'P1' as LadderLevel, kind: 'progress', axis: '判据链进度', name: '前半链', desc: '一买成立 / 回调存在 / 不破极值 三项内推进' },
  { level: 'P2' as LadderLevel, kind: 'progress', axis: '判据链进度', name: '后半链', desc: '回撤率与中枢关联检查推进，或五项全过只欠确认' },
  { level: 'S3' as LadderLevel, kind: 'corroboration', axis: '子级佐证', name: '已确认子级点', desc: '回调笔窗口内子级存在同向且已确认的买卖点' },
  { level: 'S2' as LadderLevel, kind: 'corroboration', axis: '子级佐证', name: '子级候选', desc: '同窗口内存在同向子级候选点，判据链已推进到前半链' },
  { level: 'S1' as LadderLevel, kind: 'corroboration', axis: '子级佐证', name: '子级分型', desc: '同窗口内子级末端形成同向分型（最早的微观信号）' },
  { level: 'C3' as LadderLevel, kind: 'confirm', axis: '事后确认', name: '已确认', desc: '后续笔突破一买后反向笔端点' },
  { level: 'C2' as LadderLevel, kind: 'confirm', axis: '事后确认', name: '收复', desc: '收复反向笔振幅一半以上' },
  { level: 'C1' as LadderLevel, kind: 'confirm', axis: '事后确认', name: '未确认（终态）', desc: '窗口走完未收复一半，降级不撤销' },
  { level: 'C0' as LadderLevel, kind: 'confirm', axis: '事后确认', name: '进行中', desc: '确认窗口数据不足（数据末端），非终态' },
  { level: 'K3' as LadderLevel, kind: 'fractal', axis: '分型强弱', name: '强', desc: '回调笔末端分型第三根 K 线实体收复前一根实体上沿' },
  { level: 'K2' as LadderLevel, kind: 'fractal', axis: '分型强弱', name: '中', desc: '收复前一根实体一半以上（含相等边界）' },
  { level: 'K1' as LadderLevel, kind: 'fractal', axis: '分型强弱', name: '弱', desc: '未收复前一根实体一半，可能仅为中继' },
  { level: 'T3' as LadderLevel, kind: 'time', axis: '回调速度', name: '强（急涨缓跌）', desc: '回调速度比 ≤ 强档阈值，回调衰竭' },
  { level: 'T2' as LadderLevel, kind: 'time', axis: '回调速度', name: '中（均衡）', desc: '回调速度比处于中档区间' },
  { level: 'T1' as LadderLevel, kind: 'time', axis: '回调速度', name: '弱（缓涨急跌）', desc: '回调速度比 > 弱档阈值，回调急促' },
]

/** T3 四轴档位（与 T2 同字母；Semantics 换判据对象）*/
export const T3_AXIS_INFOS: LadderInfo[] = [
  { level: 'S3' as LadderLevel, kind: 'corroboration', axis: '子级佐证', name: '已确认子级点', desc: '回抽笔窗口内子级存在同向且已确认的买卖点' },
  { level: 'S2' as LadderLevel, kind: 'corroboration', axis: '子级佐证', name: '子级候选', desc: '同窗口内存在同向子级候选点' },
  { level: 'S1' as LadderLevel, kind: 'corroboration', axis: '子级佐证', name: '子级分型', desc: '同窗口内子级末端形成同向分型' },
  { level: 'C3' as LadderLevel, kind: 'confirm', axis: '事后确认', name: '已确认', desc: '后续笔突破回抽笔端点，趋势延续成立' },
  { level: 'C2' as LadderLevel, kind: 'confirm', axis: '事后确认', name: '收复', desc: '收复回抽幅度一半以上' },
  { level: 'C1' as LadderLevel, kind: 'confirm', axis: '事后确认', name: '证伪（终态）', desc: '跌回锚定中枢区间或窗口走完未收复，假三买' },
  { level: 'C0' as LadderLevel, kind: 'confirm', axis: '事后确认', name: '进行中', desc: '确认窗口数据不足（数据末端），非终态' },
  { level: 'K3' as LadderLevel, kind: 'fractal', axis: '分型强弱', name: '强', desc: '回抽笔末端底/顶分型实体收复程度强' },
  { level: 'K2' as LadderLevel, kind: 'fractal', axis: '分型强弱', name: '中', desc: '收复前一根实体一半以上' },
  { level: 'K1' as LadderLevel, kind: 'fractal', axis: '分型强弱', name: '弱', desc: '未收复前一根实体一半，回抽动能仍强' },
  { level: 'T3' as LadderLevel, kind: 'time', axis: '回抽速度', name: '强（急涨缓跌）', desc: '回抽速度比 ≤ 强档阈值，回抽衰竭' },
  { level: 'T2' as LadderLevel, kind: 'time', axis: '回抽速度', name: '中（均衡）', desc: '回抽速度比处于中档区间' },
  { level: 'T1' as LadderLevel, kind: 'time', axis: '回抽速度', name: '弱（缓涨急跌）', desc: '回抽速度比 > 弱档阈值，回抽急促' },
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

/** 判定顺序脚注（tooltip 底部说明） */
export const LADDER_ORDER_NOTE =
  '轴独立：判据链进度、子级佐证、事后确认、分型强弱、回抽速度；L4 = 已确认'

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
 * 仓位指引：仅进度轴映射仓位（递进关系），佐证/分型轴是证据说明，不映射。
 *
 * 买点 = 建仓阶梯，卖点 = 退出阶梯（镜像文案）。
 */
export function ladderPosition(parsed: ParsedLadder | null, isBuy: boolean): string {
  if (!parsed) return '观察仓 1/4'
  if (parsed.confirmed) return isBuy ? '满仓' : '空仓'
  if (parsed.progress === 'L2') return isBuy ? '加仓至 1/2' : '减仓至 1/2'
  return isBuy ? '观察仓 1/4' : '减至 3/4'
}
