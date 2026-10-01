// echartsPalette.ts — ECharts 调色板（kline-chart-change D3 / 任务 6.4）
// getEchartsPalette(theme) 集中提供 ProfitChart / WinRateChart / StockMetaPanel /
// NestingDrawer 的 option 配色，替换各组件内散落的硬编码 hex。
//
// 设计要点（spec「主题无关的语义色」+ design.md D3 ECharts 段）：
// - 语义色（rise 红涨 / fall 绿跌 / accent 主色）两套主题**不变**；
//   胜率、收益等序列的红绿语义同理保持不变。
// - 主题色（tooltip 底/边/字、轴线、轴文字、分割线、markLine、符号描边、图内标签字）
//   随主题切换，取值对应 design.css 双主题 token（canvas 无法直接读 CSS 变量，
//   与 chartStyles.ts / chan/palette.ts 同款做法）。
// - 主题切换由 useEcharts 统一 watch，回调各组件 render 重建 option 后 setOption 刷新。

/** 主题名（与 stores/theme.ts ThemeName / chartStyles.ts ChartTheme 对齐） */
export type EchartsTheme = 'dark' | 'light'

/** ECharts 配色集合 */
export interface EchartsPalette {
  // ---- 语义色（主题无关）----
  /** 上涨 / 收益红 — design.css --rise */
  rise: string
  /** 下跌 / 胜率低绿 — design.css --fall */
  fall: string
  /** 强调主色 — design.css --accent-base */
  accent: string

  // ---- 主题色（随主题）----
  /** tooltip 背景 — --bg-surface */
  tooltipBg: string
  /** tooltip 边框 — --border-base */
  tooltipBorder: string
  /** tooltip 文字 — --text-primary */
  tooltipText: string
  /** 轴线 — --border-base */
  axisLine: string
  /** 强调轴文字（分类轴）— --text-secondary */
  axisLabelStrong: string
  /** 弱化轴文字（数值轴） */
  axisLabelDim: string
  /** 网格 / 分割虚线 — --chart-grid-line 系 */
  splitLine: string
  /** markLine 参考线 — --border-strong */
  markLine: string
  /** 折线符号描边（图底留白圈）— --bg-chart */
  symbolBorder: string
  /** 图内标签文字（treemap 等）— --text-primary */
  labelText: string
}

/** 语义色常量（主题无关，spec 红涨绿跌） */
const RISE = '#F6465D'
const FALL = '#2EBD85'
const ACCENT = '#3B82F6'

const DARK: EchartsPalette = {
  rise: RISE,
  fall: FALL,
  accent: ACCENT,

  tooltipBg: '#161B22', // --bg-surface
  tooltipBorder: '#2A303A', // --border-base
  tooltipText: '#E6E8EB', // --text-primary
  axisLine: '#2A303A', // --border-base
  axisLabelStrong: '#9BA1A8', // --text-secondary
  axisLabelDim: '#565D66', // --text-disabled
  splitLine: 'rgba(42, 48, 58, 0.5)', // --chart-grid-line 系
  markLine: '#3A424E', // --border-strong
  symbolBorder: '#0A0D12', // --bg-chart
  labelText: '#E6E8EB', // --text-primary
}

const LIGHT: EchartsPalette = {
  rise: RISE,
  fall: FALL,
  accent: ACCENT,

  tooltipBg: '#FFFFFF', // --bg-surface
  tooltipBorder: '#DCE1E8', // --border-base
  tooltipText: '#1F242C', // --text-primary
  axisLine: '#DCE1E8', // --border-base
  axisLabelStrong: '#5C6673', // --text-secondary
  // 浅底轴字：比 --text-disabled(#A0A8B4) 略深，保证明亮背景下清晰可读
  axisLabelDim: '#8A929E',
  splitLine: 'rgba(206, 214, 224, 0.85)', // --chart-grid-line
  markLine: '#B8C0CC', // --border-strong
  symbolBorder: '#FFFFFF', // --bg-chart
  labelText: '#1F242C', // --text-primary
}

/**
 * 读取当前 DOM 主题（<html data-theme>）。
 * 组件 render 里调用 getEchartsPalette() 即可获得实时主题色；
 * 属性缺失 = 暗色（与 design.css 默认一致）。
 */
export function currentEchartsTheme(): EchartsTheme {
  return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'
}

/**
 * 取指定主题的 ECharts 调色板；缺省参数 = 当前 DOM 主题。
 * 主题切换后组件重建 option 时调用，即可拿到新主题的完整配色。
 */
export function getEchartsPalette(
  theme: EchartsTheme = currentEchartsTheme(),
): EchartsPalette {
  return theme === 'light' ? LIGHT : DARK
}
