/**
 * 买卖点标签映射 — design.md D2
 * 前端做映射，不改后端枚举。
 * 原始枚举: '1','2','2s','3a','3b','1p'
 *
 * 3a / 3b 自 chan-standard-bsp 起语义分叉，不能共用一个标签：
 *   3a = 中枢在「下一条线段」内（离开后第一次回抽）
 *   3b = 中枢在「当前线段」内（离开后第一次回抽）
 * 两者都是标准三买，但形态位置不同，标签必须可区分，否则用户无法判断
 * 该信号依托的是哪个中枢。
 */

const TYPE_MAP: Record<string, { buy: string; sell: string }> = {
  '1': { buy: '1B', sell: '1S' },
  '2': { buy: '2B', sell: '2S' },
  '2s': { buy: 'L2B', sell: 'L2S' },
  '3a': { buy: '3B(后)', sell: '3S(后)' },
  '3b': { buy: '3B(内)', sell: '3S(内)' },
  '1p': { buy: 'PZ-B', sell: 'PZ-S' },
}

/** 将原始 types 数组转为标签数组 */
export function bspLabels(types: string[], isBuy: boolean): string[] {
  return types.map((t) => {
    const m = TYPE_MAP[t]
    if (!m) return t
    return isBuy ? m.buy : m.sell
  })
}

/** 单个标签 */
export function bspLabel(type: string, isBuy: boolean): string {
  const m = TYPE_MAP[type]
  if (!m) return type
  return isBuy ? m.buy : m.sell
}

/** 标签 → 原始枚举值反查表（'1B'→'1'、'PZ-S'→'1p'、'L2B'→'2s'） */
const LABEL_TO_RAW: Record<string, string> = (() => {
  const m: Record<string, string> = {}
  for (const [raw, v] of Object.entries(TYPE_MAP)) {
    m[v.buy] = raw
    m[v.sell] = raw
  }
  return m
})()

/** 标签反查原始枚举值；未匹配的标签原样返回。mock 侧介入点伪类型筛选用：
 *  BspRecord.bsp_type 是标签形态，家族集合是原始值形态，须先翻译再比对 */
export function rawTypeOf(label: string): string {
  return LABEL_TO_RAW[label] ?? label
}

/**
 * 介入点合成标签（chan-entry-point-candidate 5.2）：命中介入的买卖点标签
 * 追加「·介」后缀（如 `1B·介`）。介入点是买卖点上的独立信号层（不改
 * 成立性/数量），伪类型筛选与列表/图上展示共用同一合成规则。
 */
export function entrySuffixLabel(label: string, entry: boolean): string {
  return entry ? `${label}·介` : label
}

/** 所有买卖点类型标签（用于筛选下拉/图表轴） */
export const ALL_BSP_LABELS = [
  '1B', '2B', '3B(后)', '3B(内)', '1S', '2S', 'L2B', 'L2S', '3S(后)', '3S(内)', 'PZ-B', 'PZ-S',
]

/** 介入点伪类型筛选项（chan-entry-point-candidate 5.3：value 对应后端伪类型参数） */
export const ENTRY_PSEUDO_OPTIONS = [
  { label: '介入点（全部）', value: 'entry' },
  { label: '一买介入点', value: 'entry1' },
  { label: '二买介入点', value: 'entry2' },
  { label: '三买介入点', value: 'entry3' },
]
