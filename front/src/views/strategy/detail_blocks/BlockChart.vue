<template>
  <div class="block-chart">
    <!-- 图表块（design D5 v1：date_histogram 信号日期分布，ECharts 柱状图） -->
    <div ref="chartEl" class="chart-el" v-loading="loading"></div>
    <div v-if="!loading && isEmpty" class="chart-empty">暂无信号数据</div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount, nextTick } from 'vue'
import { useEcharts } from '@/composables/useEcharts'
import { getEchartsPalette } from '@/components/charts/echartsPalette'
import type { StrategySignalRow } from '@/api/types'

/**
 * chart 块（design D5 v1 支持 date_histogram）：信号日期分布柱状图。
 * v1 类型全集外的扩展块：声明 {"type":"chart"} 即渲染，无声明不加载。
 */
const props = defineProps<{
  signals: StrategySignalRow[]
}>()

const chartEl = ref<HTMLElement | null>(null)
const loading = ref(true)

/** 信号按日期聚合计数（升序） */
const histogram = computed(() => {
  const counts = new Map<string, number>()
  for (const s of props.signals) {
    counts.set(s.signal_date, (counts.get(s.signal_date) || 0) + 1)
  }
  return Array.from(counts.entries()).sort((a, b) => (a[0] < b[0] ? -1 : 1))
})

const isEmpty = computed(() => histogram.value.length === 0)

const { setOption, dispose } = useEcharts(chartEl, () => renderChart())

function renderChart() {
  if (!chartEl.value) return
  const rows = histogram.value
  if (rows.length === 0) return
  const p = getEchartsPalette()
  setOption({
    backgroundColor: 'transparent',
    grid: { left: 36, right: 12, top: 20, bottom: 28 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: p.tooltipBg,
      borderColor: p.tooltipBorder,
      textStyle: { color: p.tooltipText, fontSize: 12 },
    },
    xAxis: {
      type: 'category',
      data: rows.map((r) => r[0]),
      axisLine: { lineStyle: { color: p.axisLine } },
      axisLabel: { color: p.axisLabelDim, fontSize: 10, fontFamily: 'JetBrains Mono' },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: p.splitLine, type: 'dashed' } },
      axisLabel: { color: p.axisLabelDim, fontSize: 10 },
    },
    series: [
      {
        type: 'bar',
        data: rows.map((r) => r[1]),
        barMaxWidth: 18,
        itemStyle: { color: p.accent, borderRadius: [2, 2, 0, 0] },
      },
    ],
  } as never)
}

// 信号集变化后渲染
watch(
  () => props.signals,
  async () => {
    loading.value = true
    await nextTick()
    renderChart()
    loading.value = false
  },
  { immediate: true, deep: false },
)

onBeforeUnmount(dispose)
</script>

<style scoped>
.chart-el {
  width: 100%;
  height: 200px;
}
.chart-empty {
  text-align: center;
  font-size: 12px;
  color: var(--text-disabled);
  padding: var(--sp-lg) 0;
}
</style>
