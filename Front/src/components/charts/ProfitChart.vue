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
}>()

const el = ref<HTMLElement | null>(null)
// 主题切换收口在 useEcharts：回调 render 以新调色板重建 option（任务 6.4）
const { setOption } = useEcharts(el, render)

function render() {
  if (!props.series || props.series.length === 0) return
  const p = getEchartsPalette()
  setOption({
    backgroundColor: 'transparent',
    grid: { left: 48, right: 20, top: 20, bottom: 32 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: p.tooltipBg,
      borderColor: p.tooltipBorder,
      textStyle: { color: p.tooltipText, fontSize: 12 },
      valueFormatter: (v: number) => `+${v.toFixed(2)}%`,
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
    series: [
      {
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        showSymbol: false,
        data: props.series.map((pt) => pt.value),
        // 收益曲线恒为红系（语义色，主题无关；spec「主题无关的语义色」）
        lineStyle: { color: p.rise, width: 2.2 },
        itemStyle: { color: p.rise, borderColor: p.symbolBorder, borderWidth: 2 },
        emphasis: { focus: 'series' },
        areaStyle: {
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
      },
    ],
  })
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
