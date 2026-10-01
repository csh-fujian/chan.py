// useChartLegend.ts — 行情图例数据源（kline-chart-change D7 / 任务 5.1、5.4）
// 数据流：
//   chart.subscribeAction('onCrosshairChange') → 悬停 bar（回调 data.kLineData）；
//   回调 data / kLineData 缺失（十字光标未命中）或容器 mouseleave → 回退最新一根。
//   （klinecharts 9.8.12 行为：crosshair 仅在 paneId 为字符串时派发 onCrosshairChange，
//     指针移出图表走 setCrosshair({}) 不触发回调 → 以容器 mouseleave 兜底复位。）
// prevClose 由本地序列推导（spec 计算契约）：applyResult 喂入 result.klines，
// 增量加载 mergeSeries 合入更早的 K 线；前一根 close 即前收，首根无前收 → null（图例显示 --）。
// 展示已迁移出主图左上角（任务 5.3）：渲染在 StockPanel.vue 头部（名称/代码下方）。
//
// 共享状态（任务 5.4）：全部状态提升为 composable 模块级单例（非持久化），
// 同一模块的多次 useChartLegend() 调用共享同一份可观察 state ——
//   写方：KLineChart.vue（attach/detach 订阅、setSeries/mergeSeries 喂数）；
//   读方：StockPanel.vue（只读 state 渲染）。
// 约束：单图表实例（KLineView 仅挂一个 KLineChart），多图表并行写会互相覆盖。
import { shallowRef } from 'vue'
import { ActionType, type Chart, type Crosshair } from 'klinecharts'

/** 图例所需最小 K 线形状（兼容 api.KLine 与 klinecharts.KLineData） */
export interface LegendKLine {
  timestamp: number
  open: number
  high: number
  low: number
  close: number
  volume?: number
}

/** 图例展示的一根 K 线（volume 缺失/非法时为 null，展示 --） */
export interface LegendBar {
  timestamp: number
  open: number
  high: number
  low: number
  close: number
  volume: number | null
}

export interface ChartLegendState {
  /** 当前展示的 K 线（悬停优先，无悬停回退最新一根） */
  bar: LegendBar
  /** 前收盘价（本地序列推导）；首根/未知 bar 为 null */
  prevClose: number | null
}

function toLegendBar(k: LegendKLine): LegendBar {
  return {
    timestamp: k.timestamp,
    open: k.open,
    high: k.high,
    low: k.low,
    close: k.close,
    volume: typeof k.volume === 'number' && Number.isFinite(k.volume) ? k.volume : null,
  }
}

// ---------------------------------------------------------------------------
// 模块级共享状态（任务 5.4）：KLineChart 写、StockPanel 读
// ---------------------------------------------------------------------------

/** 展示状态（null = 无数据，现价行回退 profile 报价、字段行隐藏） */
const state = shallowRef<ChartLegendState | null>(null)

/** 本地 K 线序列（时间升序）：setSeries 喂入 result.klines，增量加载 mergeSeries 合入 */
let series: LegendKLine[] = []
/** 悬停 bar（取自回调 kLineData）；null = 无悬停（回退最新一根） */
let hoveredBar: LegendKLine | null = null
let chart: Chart | null = null
let container: HTMLElement | null = null

export function useChartLegend() {
  /**
   * 解析展示状态：悬停 bar 优先，无悬停回退序列最新一根。
   * prevClose 按 timestamp 在本地序列定位前一根 close；首根/未收录 bar → null（显示 --）。
   */
  function resolve(): void {
    const bar = hoveredBar ?? series[series.length - 1]
    if (!bar) {
      state.value = null
      return
    }
    let prevClose: number | null = null
    const idx = series.findIndex((k) => k.timestamp === bar.timestamp)
    if (idx > 0) prevClose = series[idx - 1].close
    state.value = { bar: toLegendBar(bar), prevClose }
  }

  /** 全量替换序列（applyResult / 数据清空）；顺带清掉悬停态防止切换股票后串号 */
  function setSeries(klines: LegendKLine[]): void {
    series = klines
    hoveredBar = null
    resolve()
  }

  /** 合入增量加载的 K 线（loadDataCallback 返回的更早数据）；保留悬停态并重算前收 */
  function mergeSeries(klines: LegendKLine[]): void {
    if (klines.length === 0) return
    const seen = new Set(series.map((k) => k.timestamp))
    const fresh = klines.filter((k) => !seen.has(k.timestamp))
    if (fresh.length === 0) return
    series = [...fresh, ...series].sort((a, b) => a.timestamp - b.timestamp)
    resolve()
  }

  /** 十字光标回调：有 kLineData → 悬停该 bar；data / kLineData 缺失 → 回退最新 */
  function onCrosshairChange(data?: Crosshair): void {
    const kd = data?.kLineData
    if (!kd || !Number.isFinite(kd.timestamp)) {
      if (hoveredBar === null) return
      hoveredBar = null
      resolve()
      return
    }
    // 同一 bar 上平移无需重算
    if (hoveredBar?.timestamp === kd.timestamp) return
    hoveredBar = kd
    resolve()
  }

  /** 指针离开图表容器 → 回退最新（补足 klinecharts 移出时不派发回调的行为） */
  function onPointerLeave(): void {
    if (hoveredBar === null) return
    hoveredBar = null
    resolve()
  }

  /**
   * 挂载订阅：onCrosshairChange + 容器 mouseleave。
   * 须在 chart init 成功后调用；与 detach 成对（onBeforeUnmount 清理）。
   */
  function attach(chartInstance: Chart, containerEl: HTMLElement): void {
    detach()
    chart = chartInstance
    container = containerEl
    chart.subscribeAction(ActionType.OnCrosshairChange, onCrosshairChange)
    container.addEventListener('mouseleave', onPointerLeave)
  }

  /** 取消事件订阅与 DOM 监听（幂等） */
  function detach(): void {
    chart?.unsubscribeAction(ActionType.OnCrosshairChange, onCrosshairChange)
    container?.removeEventListener('mouseleave', onPointerLeave)
    chart = null
    container = null
  }

  return { state, setSeries, mergeSeries, attach, detach }
}
