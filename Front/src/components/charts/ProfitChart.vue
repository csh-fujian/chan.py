<template>
  <div ref="el" class="profit-chart"></div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { useEcharts } from '@/composables/useEcharts'
import { getEchartsPalette } from '@/components/charts/echartsPalette'

interface SeriesPoint {
  date: string
  value: number
}

const props = defineProps<{
  series: SeriesPoint[]
  /**
   * 收益曲线分段着色（monitor-page-change D8）：true 时按 y 值分段着色
   * —— 收益率 > 0 红（--rise）、< 0 绿（--fall），配 0 轴参考线；
   * 缺省 false 保持整条红系的既有口径（绩效等其他页面不受影响）。
   */
  splitColor?: boolean
}>()

const el = ref<HTMLElement | null>(null)
// 主题切换收口在 useEcharts：回调 render 以新调色板重建 option（任务 6.4）
const { setOption } = useEcharts(el, render)

function render() {
  if (!props.series || props.series.length === 0) return
  const p = getEchartsPalette()
  const values = props.series.map((pt) => pt.value)
  // 分段着色模式（D8）：>0 红 / <0 绿（visualMap 覆盖逐段线色）；缺省整条红系
  const split = props.splitColor === true
  const seriesOption: Record<string, unknown> = {
    type: 'line',
    smooth: true,
    symbol: 'circle',
    symbolSize: 6,
    showSymbol: false,
    data: values,
    // 收益曲线恒为红系（语义色，主题无关；spec「主题无关的语义色」）；
    // splitColor 模式下逐段着色由 visualMap 覆盖（D8 红涨绿跌）
    lineStyle: { color: p.rise, width: 2.2 },
    itemStyle: { color: p.rise, borderColor: p.symbolBorder, borderWidth: 2 },
    emphasis: { focus: 'series' },
    areaStyle: split
      ? {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(246,70,93,0.16)' },
              { offset: 1, color: 'rgba(46,189,133,0.10)' },
            ],
          },
        }
      : {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(246,70,93,0.22)' },
              { offset: 1, color: 'rgba(246,70,93,0)' },
            ],
          },
        },
    markLine: {
      silent: true,
      symbol: 'none',
      lineStyle: { color: p.markLine, type: 'dashed' },
      data: [{ yAxis: 0 }],
    },
  }
  const option: Record<string, unknown> = {
    backgroundColor: 'transparent',
    grid: { left: 48, right: 20, top: 20, bottom: 32 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: p.tooltipBg,
      borderColor: p.tooltipBorder,
      textStyle: { color: p.tooltipText, fontSize: 12 },
      valueFormatter: (v: number) => `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`,
    },
    xAxis: {
      type: 'category',
      data: props.series.map((pt) => pt.date),
      boundaryGap: false,
      axisLine: { lineStyle: { color: p.axisLine } },
      axisLabel: { color: p.axisLabelDim, fontSize: 11, fontFamily: 'JetBrains Mono' },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: p.splitLine, type: 'dashed' } },
      axisLabel: {
        color: p.axisLabelDim,
        fontSize: 11,
        fontFamily: 'JetBrains Mono',
        formatter: '{value}%',
      },
    },
    series: [seriesOption],
  }
  if (split) {
    // visualMap piecewise 分段着色（D8）：>0 红、<0 绿（=0 归入红段边界，不单独成段）
    option.visualMap = {
      show: false,
      type: 'piecewise',
      pieces: [
        { gt: 0, color: p.rise },
        { lte: 0, color: p.fall },
      ],
    }
  }
  setOption(option)
}

onMounted(render)
watch(() => props.series, render, { deep: true })
</script>

<style scoped>
.profit-chart {
  height: 280px;
  width: 100%;
}
</style>
