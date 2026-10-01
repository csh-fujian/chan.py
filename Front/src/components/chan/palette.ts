// palette.ts — 缠论覆盖层调色板（kline-chart-change D3 / 任务 6.3）
// getChanPalette(theme) 集中提供 chan_bi / chan_seg / chan_zs / chan_bsp / chan_vbsp
// 与 subCandleOverlay / volIndicator 的绘制色，替换各文件内散落的本地色值常量。
//
// 设计要点（spec「主题无关的语义色」+ design.md D3）：
// - 语义色（rise 红涨 / fall 绿跌 / buy 红系 / sell 绿系）两套主题**不变**；
// - 结构色（笔灰线、中枢半透明框底/描边、平盘中性灰）**随主题**调整：
//   暗色下浅灰、明亮下压深，半透明填充在浅底下提高对比避免「看不清」；
// - overlay 在 createPointFigures 绘制时经 currentTheme() 取当前主题色，
//   主题切换后 KLineChart 清除并重建 overlay（rebuildAllOverlays）保证立即重绘。

/** 主题名（与 stores/theme.ts ThemeName / chartStyles.ts ChartTheme 对齐） */
export type ChanTheme = 'dark' | 'light'

/** 缠论覆盖层绘制色集合 */
export interface ChanPalette {
  // ---- 语义色（主题无关，spec 红涨绿跌 / 买红卖绿）----
  /** 上涨 — design.css --rise */
  rise: string
  /** 下跌 — design.css --fall */
  fall: string
  /** 买点标记色（红系） */
  buy: string
  /** 卖点标记色（绿系） */
  sell: string
  /** 买点框底（半透明红） */
  buyFill: string
  /** 卖点框底（半透明绿） */
  sellFill: string

  // ---- 结构色（随主题）----
  /** 笔折线 */
  bi: string
  /** 线段折线 */
  seg: string
  /** 平盘 / 无变化中性色 */
  neutral: string
  /** 笔中枢框底 */
  zsBiFill: string
  /** 笔中枢描边 */
  zsBiBorder: string
  /** 线段中枢框底 */
  zsSegFill: string
  /** 线段中枢描边 */
  zsSegBorder: string
}

/** 语义色常量（主题无关） */
const RISE = '#F6465D'
const FALL = '#2EBD85'

const DARK: ChanPalette = {
  rise: RISE,
  fall: FALL,
  buy: RISE,
  sell: FALL,
  buyFill: 'rgba(246, 70, 93, 0.16)',
  sellFill: 'rgba(46, 189, 133, 0.16)',

  bi: '#9BA1A8',
  seg: '#3B82F6',
  neutral: '#9BA1A8',
  zsBiFill: 'rgba(155, 161, 168, 0.10)',
  zsBiBorder: 'rgba(155, 161, 168, 0.55)',
  zsSegFill: 'rgba(59, 130, 246, 0.09)',
  zsSegBorder: 'rgba(59, 130, 246, 0.65)',
}

const LIGHT: ChanPalette = {
  rise: RISE,
  fall: FALL,
  buy: RISE,
  sell: FALL,
  // 浅底下略收框底 alpha，保持标签可读
  buyFill: 'rgba(246, 70, 93, 0.12)',
  sellFill: 'rgba(46, 189, 133, 0.12)',

  // 浅底灰线压深（对齐 design.css 亮色 --text-secondary，与 HTML 图例色卡一致）
  bi: '#5C6673',
  // 线段蓝 = --accent-base（主题不变；浅底 2.2px 实线对比度足够，与图例色卡一致）
  seg: '#3B82F6',
  neutral: '#5C6673',
  // 半透明填充在浅底下提高 alpha / 换更深色基，避免白底不可见
  zsBiFill: 'rgba(107, 114, 128, 0.12)',
  zsBiBorder: 'rgba(107, 114, 128, 0.50)',
  zsSegFill: 'rgba(37, 99, 235, 0.08)',
  zsSegBorder: 'rgba(37, 99, 235, 0.55)',
}

/**
 * 读取当前 DOM 主题（<html data-theme>）。
 * 绘制回调里调用：与 theme store 的 applyThemeAttr 天然同步；
 * 属性缺失 = 暗色（与 design.css 默认一致）。
 */
export function currentTheme(): ChanTheme {
  return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'
}

/**
 * 取指定主题的缠论调色板；缺省参数 = 当前 DOM 主题。
 * overlay 绘制时调用 getChanPalette() 即可获得实时主题色。
 */
export function getChanPalette(theme: ChanTheme = currentTheme()): ChanPalette {
  return theme === 'light' ? LIGHT : DARK
}
