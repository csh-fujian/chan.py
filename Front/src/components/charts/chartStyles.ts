// chartStyles.ts — klinecharts 全局样式工厂（kline-chart-change D3 / 任务 6.3）
// getChartStyles(theme) 返回完整 setStyles 负载：
// - dark：KLineChart.vue 原硬编码暗色 setStyles 块逐字段迁移（值不变，外观零回归）；
// - light：浅背景 / 深色轴字 / 浅网格 / 对比度足够的十字光标；
// - 涨跌语义色（--rise 红 #F6465D / --fall 绿 #2EBD85）两套主题保持不变
//   （spec「主题无关的语义色」）。
import {
  LineType,
  CandleType,
  TooltipShowRule,
  TooltipShowType,
  type DeepPartial,
  type Styles,
} from 'klinecharts'

/** 主题名（与 stores/theme.ts ThemeName 对齐） */
export type ChartTheme = 'dark' | 'light'

/** 红涨绿跌 — design.css --rise / --fall（主题无关语义色） */
const RISE = '#F6465D'
const FALL = '#2EBD85'

/** 暗色主题：与原 KLineChart.vue setStyles 硬编码值逐字段一致 */
function darkStyles(): DeepPartial<Styles> {
  return {
    grid: {
      horizontal: { show: true, color: 'rgba(42, 48, 58, 0.55)', style: LineType.Solid, size: 1, dashedValue: [2, 2] },
      vertical: { show: true, color: 'rgba(42, 48, 58, 0.55)', style: LineType.Solid, size: 1, dashedValue: [2, 2] },
    },
    candle: {
      // 涨红空心（stroke 描边）、跌绿实心（kline-chart-change D4 / 任务 2.1）
      type: CandleType.CandleUpStroke,
      bar: {
        upColor: RISE,
        downColor: FALL,
        noChangeColor: '#9BA1A8',
        upBorderColor: RISE,
        downBorderColor: FALL,
        noChangeBorderColor: '#9BA1A8',
        upWickColor: RISE,
        downWickColor: FALL,
        noChangeWickColor: '#9BA1A8',
      },
      priceMark: {
        show: true,
        high: { show: true, color: '#9BA1A8' },
        low: { show: true, color: '#9BA1A8' },
      },
      tooltip: {
        // 禁用内置 canvas tooltip：读数由标的面板 HTML 图例承接（kline-chart-change D7/5.3）
        showRule: TooltipShowRule.None,
        showType: TooltipShowType.Standard,
      },
    },
    xAxis: {
      show: true,
      axisLine: { show: true, color: '#2A303A', size: 1 },
      tickText: { show: true, color: '#565D66', size: 11 },
      tickLine: { show: true, color: '#2A303A', size: 1 },
    },
    yAxis: {
      show: true,
      size: 100,
      axisLine: { show: true, color: '#2A303A', size: 1 },
      tickText: { show: true, color: '#565D66', size: 11, marginStart: 6 },
      tickLine: { show: true, color: '#2A303A', size: 1 },
    },
    separator: {
      // 副图分隔线：现值 = 库默认 #DDDDDD（原 setStyles 未显式设置，逐字段等值迁移）
      size: 1,
      color: '#DDDDDD',
      fill: true,
    },
    indicator: {
      tooltip: {
        // 副图指标 tooltip 图例文字（VOL/MACD 等），现值 = 库默认 #76808F
        text: { color: '#76808F' },
      },
    },
    crosshair: {
      show: true,
      horizontal: {
        show: true,
        line: { show: true, color: '#3B82F6', style: LineType.Dashed, size: 1, dashedValue: [4, 2] },
        text: { show: true, color: '#E6E8EB', backgroundColor: '#1C2128', size: 11, paddingLeft: 4, paddingRight: 4, paddingTop: 2, paddingBottom: 2, borderRadius: 2 },
      },
      vertical: {
        show: true,
        line: { show: true, color: '#3B82F6', style: LineType.Dashed, size: 1, dashedValue: [4, 2] },
        text: { show: true, color: '#E6E8EB', backgroundColor: '#1C2128', size: 11, paddingLeft: 4, paddingRight: 4, paddingTop: 2, paddingBottom: 2, borderRadius: 2 },
      },
    },
  }
}

/** 明亮主题：浅底 / 深轴字 / 浅网格 / 对比度足够的十字光标；涨跌语义色不变 */
function lightStyles(): DeepPartial<Styles> {
  return {
    grid: {
      horizontal: { show: true, color: '#DCE1E8', style: LineType.Solid, size: 1, dashedValue: [2, 2] },
      vertical: { show: true, color: '#DCE1E8', style: LineType.Solid, size: 1, dashedValue: [2, 2] },
    },
    candle: {
      type: CandleType.CandleUpStroke,
      bar: {
        upColor: RISE,
        downColor: FALL,
        noChangeColor: '#5C6673',
        upBorderColor: RISE,
        downBorderColor: FALL,
        noChangeBorderColor: '#5C6673',
        upWickColor: RISE,
        downWickColor: FALL,
        noChangeWickColor: '#5C6673',
      },
      priceMark: {
        show: true,
        high: { show: true, color: '#5C6673' },
        low: { show: true, color: '#5C6673' },
      },
      tooltip: {
        showRule: TooltipShowRule.None,
        showType: TooltipShowType.Standard,
      },
    },
    xAxis: {
      show: true,
      axisLine: { show: true, color: '#DCE1E8', size: 1 },
      tickText: { show: true, color: '#5C6673', size: 11 },
      tickLine: { show: true, color: '#DCE1E8', size: 1 },
    },
    yAxis: {
      show: true,
      size: 100,
      axisLine: { show: true, color: '#DCE1E8', size: 1 },
      tickText: { show: true, color: '#5C6673', size: 11, marginStart: 6 },
      tickLine: { show: true, color: '#DCE1E8', size: 1 },
    },
    separator: {
      // 明亮：分隔线与网格同色系浅线
      size: 1,
      color: '#DCE1E8',
      fill: true,
    },
    indicator: {
      tooltip: {
        text: { color: '#5C6673' },
      },
    },
    crosshair: {
      show: true,
      horizontal: {
        show: true,
        line: { show: true, color: '#3B82F6', style: LineType.Dashed, size: 1, dashedValue: [4, 2] },
        text: { show: true, color: '#1F242C', backgroundColor: '#EDF1F6', size: 11, paddingLeft: 4, paddingRight: 4, paddingTop: 2, paddingBottom: 2, borderRadius: 2 },
      },
      vertical: {
        show: true,
        line: { show: true, color: '#3B82F6', style: LineType.Dashed, size: 1, dashedValue: [4, 2] },
        text: { show: true, color: '#1F242C', backgroundColor: '#EDF1F6', size: 11, paddingLeft: 4, paddingRight: 4, paddingTop: 2, paddingBottom: 2, borderRadius: 2 },
      },
    },
  }
}

/**
 * 图表全局样式工厂：init 时与主题切换时各调用一次
 * （chart.setStyles(getChartStyles(theme))）。
 */
export function getChartStyles(theme: ChartTheme): DeepPartial<Styles> {
  return theme === 'light' ? lightStyles() : darkStyles()
}
