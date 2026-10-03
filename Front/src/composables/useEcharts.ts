import { watch, onMounted, onBeforeUnmount, onActivated, type Ref } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  VisualMapComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useThemeStore } from '@/stores/theme'
import type { ThemeName } from '@/stores/theme'

// VisualMapComponent：ProfitChart splitColor 分段着色（monitor-page-change D8）所需
echarts.use([LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, VisualMapComponent, CanvasRenderer])

/**
 * ECharts composable — 实例非响应式（design.md D6 同款策略）
 * chart 实例不进 ref 的 reactive 包装，用 shallowRef 或 let 变量。
 *
 * 主题（kline-chart-change D3 / 任务 6.4）：主题 watch 统一收口在本 composable，
 * 各图表组件传入 onThemeChange（一般是其 render 函数，内部经 getEchartsPalette
 * 取新主题色重建 option）即可随主题切换刷新，避免每个使用点各写一份 watch。
 *
 * @param onThemeChange 主题切换回调（可选；不传则仅保持实例存活，由调用方自行处理）
 */
export function useEcharts(
  el: Ref<HTMLElement | null>,
  onThemeChange?: (theme: ThemeName) => void,
) {
  let chart: echarts.ECharts | null = null

  function init() {
    if (!el.value) return
    chart = echarts.init(el.value, undefined, { renderer: 'canvas' })
    return chart
  }

  function setOption(option: echarts.EChartsCoreOption) {
    if (!chart) init()
    chart?.setOption(option, true)
  }

  function resize() {
    chart?.resize()
  }

  function dispose() {
    chart?.dispose()
    chart = null
  }

  // 主题切换（kline-chart-change D3 / 任务 6.4）：watch 收口在 composable，
  // 回调由各图表组件传入（通常是 render —— 用 getEchartsPalette 重建 option）
  const themeStore = useThemeStore()
  watch(
    () => themeStore.theme,
    (t) => {
      if (!onThemeChange) return
      onThemeChange(t)
    },
  )

  onMounted(() => {
    init()
    window.addEventListener('resize', resize)
  })

  // 页面缓存复活（design.md D10）：缓存期间组件脱离文档，window resize 监听
  // 读到的容器尺寸失真；重新入文档后按实际尺寸重设一次
  onActivated(() => resize())

  onBeforeUnmount(() => {
    window.removeEventListener('resize', resize)
    dispose()
  })

  return { setOption, resize, dispose, getChart: () => chart }
}
