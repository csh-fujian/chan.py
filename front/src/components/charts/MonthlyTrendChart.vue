<template>
  <div ref="el" class="monthly-trend-chart"></div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { useEcharts } from '@/composables/useEcharts'
import { getEchartsPalette } from '@/components/charts/echartsPalette'

export interface MonthlyTrendPoint {
  /** 月份（'YYYY-MM'） */
  month: string
  /** 月胜率（%，0-100） */
  winRate: number
  /** 月平均盈亏（%） */
  avgPnl: number
}

const props = defineProps<{
  data: MonthlyTrendPoint[]
}>()

const el = ref<HTMLElement | null>(null)
// 主题切换收口在 useEcharts：回调 render 以新调色板重建 option
const { setOption } = useEcharts(el, render)

function render() {
  if (!props.data || props.data.length === 0) return
  const p = getEchartsPalette()
  setOption({
    backgroundColor: 'transparent',
    grid: { left: 48, right: 52, top: 24, bottom: 32 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: p.tooltipBg,
      borderColor: p.tooltipBorder,
      textStyle: { color: p.tooltipText, fontSize: 12 },
    },
    xAxis: {
      type: 'category',
      data: props.data.map((d) => d.month),
      axisLine: { lineStyle: { color: p.axisLine } },
      axisLabel: { color: p.axisLabelDim, fontSize: 11, fontFamily: 'JetBrains Mono' },
      axisTick: { show: false },
    },
    // 双 y 轴（design D5）：左 = 胜率%（0-100），右 = 平均盈亏%
    yAxis: [
      {
        type: 'value',
        min: 0,
        max: 100,
        name: '胜率%',
        nameTextStyle: { color: p.axisLabelDim, fontSize: 11 },
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
      {
        type: 'value',
        name: '平均盈亏%',
        nameTextStyle: { color: p.axisLabelDim, fontSize: 11 },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: {
          color: p.axisLabelDim,
          fontSize: 11,
          fontFamily: 'JetBrains Mono',
          formatter: (v: number) => `${v >= 0 ? '+' : ''}${v}%`,
        },
      },
    ],
    visualMap: {
      show: false,
      type: 'piecewise',
      // 仅作用于右轴平均盈亏折线（seriesIndex: 1）分段着色：>0 红 / <0 绿。
      // 注意：必须含一个有限 value 段（value: 0）—— echarts 5.6 的 piecewise 若
      // pieces 仅有 gt/lte 两段（边界均为 ±Infinity），getVisualMeta 产出的 stops
      // 为空数组，LineView 渲染时 getVisualGradient 内 colorStopsInRange[0] 越界
      // 抛错并中断整个 mounted flush 队列（ProfitChart 已踩过的坑，同款规避）
      seriesIndex: 1,
      dimension: 1,
      pieces: [
        { lt: 0, color: p.fall },
        { value: 0, color: p.fall },
        { gt: 0, color: p.rise },
      ],
    },
    series: [
      {
        // 月胜率柱（左轴）：胜率语义色（≥50 红 / <50 绿）逐柱着色
        name: '胜率',
        type: 'bar',
        barWidth: 22,
        yAxisIndex: 0,
        data: props.data.map((d) => ({
          value: d.winRate,
          itemStyle: { color: d.winRate >= 50 ? p.rise : p.fall },
        })),
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { color: p.rise, type: 'dashed', width: 1 },
          label: {
            formatter: '50%',
            color: p.rise,
            fontSize: 11,
            fontFamily: 'JetBrains Mono',
          },
          data: [{ yAxis: 50 }],
        },
      },
      {
        // 月平均盈亏折线（右轴）：visualMap 分段红涨绿跌 + 0 轴参考线
        name: '平均盈亏',
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        showSymbol: true,
        yAxisIndex: 1,
        data: props.data.map((d) => [d.month, d.avgPnl]),
        lineStyle: { color: p.rise, width: 2.2 },
        itemStyle: { color: p.rise, borderColor: p.symbolBorder, borderWidth: 2 },
        emphasis: { focus: 'series' },
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { color: p.markLine, type: 'dashed' },
          label: { formatter: '0', color: p.axisLabelDim, fontSize: 10 },
          data: [{ yAxis: 0 }],
        },
      },
    ],
  })
}

onMounted(render)
watch(() => props.data, render, { deep: true })
</script>

<style scoped>
.monthly-trend-chart {
  height: 260px;
  width: 100%;
}
</style>
