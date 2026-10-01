<template>
  <div ref="el" class="winrate-chart"></div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { useEcharts } from '@/composables/useEcharts'
import { getEchartsPalette } from '@/components/charts/echartsPalette'

interface BarItem {
  name: string
  winRate: number
}

const props = defineProps<{
  data: BarItem[]
}>()

const el = ref<HTMLElement | null>(null)
// 主题切换收口在 useEcharts：回调 render 以新调色板重建 option（任务 6.4）
const { setOption } = useEcharts(el, render)

function render() {
  if (!props.data || props.data.length === 0) return
  const p = getEchartsPalette()
  setOption({
    backgroundColor: 'transparent',
    grid: { left: 48, right: 20, top: 24, bottom: 32 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: p.tooltipBg,
      borderColor: p.tooltipBorder,
      textStyle: { color: p.tooltipText, fontSize: 12 },
      axisPointer: { type: 'shadow' },
      valueFormatter: (v: number) => `${v}%`,
    },
    xAxis: {
      type: 'category',
      data: props.data.map((d) => d.name),
      axisLine: { lineStyle: { color: p.axisLine } },
      axisLabel: { color: p.axisLabelStrong, fontSize: 12, fontFamily: 'JetBrains Mono' },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      max: 100,
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
        type: 'bar',
        barWidth: 38,
        // 胜率红绿柱为语义色（≥50 红 / <50 绿），两套主题保持不变
        data: props.data.map((d) => ({
          value: d.winRate,
          itemStyle: { color: d.winRate >= 50 ? p.rise : p.fall },
        })),
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { color: p.rise, type: 'dashed', width: 1.5 },
          label: {
            formatter: '50%',
            color: p.rise,
            fontSize: 11,
            fontFamily: 'JetBrains Mono',
          },
          data: [{ yAxis: 50 }],
        },
      },
    ],
  })
}

onMounted(render)
watch(() => props.data, render, { deep: true })
</script>

<style scoped>
.winrate-chart {
  height: 220px;
  width: 100%;
}
</style>
