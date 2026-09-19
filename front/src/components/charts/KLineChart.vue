<template>
  <div class="kline-chart-wrap">
    <div ref="chartRef" class="kline-chart-el" />
    <div v-if="loading" class="kline-chart-loading">
      <span>加载中…</span>
    </div>
    <div v-else-if="empty" class="kline-chart-empty">
      <span>无数据</span>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * KLineChart.vue — K 线 + 缠论 overlay 渲染
 * design.md D6：chart 实例非响应式，onMounted init，watch 命令式重载。
 */
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import {
  init,
  dispose,
  type Chart,
  type KLineData,
  LineType,
  CandleType,
  TooltipShowRule,
  TooltipShowType,
  LoadDataType,
} from 'klinecharts'
import type { ChanResult } from '@/api/types'
import { registerAllChanOverlays } from '@/components/chan'
import { getKLine } from '@/api/modules/kline'

const props = defineProps<{
  result: ChanResult | null
  code?: string
  period?: string
}>()

const chartRef = ref<HTMLDivElement | null>(null)
const loading = ref(false)
const empty = ref(false)

// chart 实例非响应式（design.md D6）
let chart: Chart | null = null
let resizeObserver: ResizeObserver | null = null
/** 首屏数据是否已加载完毕，在此之前跳过增量加载 */
let initialLoadDone = false

/** 副图指标 pane id 前缀 */
const PANE_PREFIX = 'chan_sub_'
/** 当前已创建的副图指标 → paneId 映射 */
const subPaneMap = new Map<string, string>()

/** 红涨绿跌 — design.css --rise / --fall */
const UP_COLOR = '#F6465D'
const DOWN_COLOR = '#2EBD85'

/** 应用 K 线数据 + 缠论覆盖层 */
function applyResult(result: ChanResult): void {
  if (!chart) return

  // 标记首屏加载中，阻止 applyNewData 触发的 Backward 增量回调
  initialLoadDone = false

  const klines: KLineData[] = result.klines.map((k) => ({
    timestamp: k.timestamp,
    open: k.open,
    high: k.high,
    low: k.low,
    close: k.close,
    volume: k.volume,
  }))
  chart.applyNewData(klines)

  // applyNewData 后首屏加载完成，后续增量加载可正常触发
  initialLoadDone = true

  // 先移除旧覆盖层，再重建
  chart.removeOverlay('chan_bi')
  chart.removeOverlay('chan_seg')
  chart.removeOverlay('chan_zs')
  chart.removeOverlay('chan_bsp')

  // 笔覆盖层：points 按 [begin, end, begin, end, ...] 顺序；lock=true 禁止拖动
  if (result.bi.length > 0) {
    const biPoints: Array<{ timestamp: number; value: number }> = []
    for (const b of result.bi) {
      biPoints.push({ timestamp: b.begin.t, value: b.begin.v })
      biPoints.push({ timestamp: b.end.t, value: b.end.v })
    }
    chart.createOverlay({ name: 'chan_bi', lock: true, points: biPoints })
  }

  // 线段覆盖层：同笔结构；lock=true 禁止拖动
  if (result.seg.length > 0) {
    const segPoints: Array<{ timestamp: number; value: number }> = []
    for (const s of result.seg) {
      segPoints.push({ timestamp: s.begin.t, value: s.begin.v })
      segPoints.push({ timestamp: s.end.t, value: s.end.v })
    }
    chart.createOverlay({ name: 'chan_seg', lock: true, points: segPoints })
  }

  // 中枢覆盖层：每个中枢 4 个角点，extendData 存 meta；lock=true 禁止拖动
  const allZs = [
    ...result.zs.map((z) => ({ z, level: 'bi' as const })),
    ...result.seg_zs.map((z) => ({ z, level: 'seg' as const })),
  ]
  if (allZs.length > 0) {
    const zsPoints: Array<{ timestamp: number; value: number }> = []
    const zsMeta: Array<{ level: 'bi' | 'seg'; startIndex: number }> = []
    allZs.forEach(({ z, level }) => {
      const startIndex = zsPoints.length
      // 4 角：左上(begin,high) 右上(end,high) 右下(end,low) 左下(begin,low)
      zsPoints.push({ timestamp: z.begin_t, value: z.high })
      zsPoints.push({ timestamp: z.end_t, value: z.high })
      zsPoints.push({ timestamp: z.end_t, value: z.low })
      zsPoints.push({ timestamp: z.begin_t, value: z.low })
      zsMeta.push({ level, startIndex })
    })
    chart.createOverlay({
      name: 'chan_zs',
      lock: true,
      points: zsPoints,
      extendData: zsMeta,
    })
  }

  // 买卖点覆盖层：每个买卖点 1 个点，extendData 存 meta；lock=true 禁止拖动
  if (result.bsp.length > 0) {
    const bspPoints: Array<{ timestamp: number; value: number }> = []
    const bspMeta: Array<{ isBuy: boolean; types: string[]; pointIndex: number }> = []
    result.bsp.forEach((b, i) => {
      bspPoints.push({ timestamp: b.t, value: b.v })
      bspMeta.push({ isBuy: b.is_buy, types: b.types, pointIndex: i })
    })
    chart.createOverlay({
      name: 'chan_bsp',
      lock: true,
      points: bspPoints,
      extendData: bspMeta,
    })
  }
}

/** 初始化 chart 实例 */
function initChart(): void {
  if (!chartRef.value) return
  // 注册覆盖层（须在 init 之前）
  registerAllChanOverlays()
  chart = init(chartRef.value)
  if (!chart) return

  // 暗色主题 + 红涨绿跌
  chart.setStyles({
    grid: {
      horizontal: { show: true, color: 'rgba(42, 48, 58, 0.55)', style: LineType.Solid, size: 1, dashedValue: [2, 2] },
      vertical: { show: true, color: 'rgba(42, 48, 58, 0.55)', style: LineType.Solid, size: 1, dashedValue: [2, 2] },
    },
    candle: {
      type: CandleType.CandleSolid,
      bar: {
        upColor: UP_COLOR,
        downColor: DOWN_COLOR,
        noChangeColor: '#9BA1A8',
        upBorderColor: UP_COLOR,
        downBorderColor: DOWN_COLOR,
        noChangeBorderColor: '#9BA1A8',
        upWickColor: UP_COLOR,
        downWickColor: DOWN_COLOR,
        noChangeWickColor: '#9BA1A8',
      },
      priceMark: {
        show: true,
        high: { show: true, color: '#9BA1A8' },
        low: { show: true, color: '#9BA1A8' },
      },
      tooltip: {
        showRule: TooltipShowRule.Always,
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
  })

  // 增量加载 data loader（任务5.3：拖到最早端触发 getBars('backward')）
  // design.md D4: 缠论全量返回，增量加载只针对 K 线
  chart.setLoadDataCallback(async ({ type, data, callback }) => {
    // 首屏加载期间不触发增量加载，避免 applyNewData 导致的重复请求
    if (!initialLoadDone) return
    // 只有向前/向后滚动才触发增量加载，初始化时不触发
    if (type === LoadDataType.Init) return
    if (!props.code || !props.period) return
    try {
      // 使用当前数据中最早的 timestamp 作为分页游标
      const earliest = data?.timestamp ?? 0
      const result = await getKLine(props.code, props.period, earliest)
      if (!result.klines || result.klines.length === 0) {
        callback([])
        return
      }
      const extra: KLineData[] = result.klines.map((k) => ({
        timestamp: k.timestamp,
        open: k.open,
        high: k.high,
        low: k.low,
        close: k.close,
        volume: k.volume,
      }))
      callback(extra)
    } catch {
      callback([])
    }
  })
}

/** 添加副图指标（VOL/MACD/BOLL/RSI/KDJ） */
function addSubIndicator(name: string): void {
  if (!chart) return
  if (subPaneMap.has(name)) return
  const paneId = `${PANE_PREFIX}${name.toLowerCase()}`
  chart.createIndicator(name, false, { id: paneId, height: 130 })
  subPaneMap.set(name, paneId)
}

/** 移除副图指标 */
function removeSubIndicator(name: string): void {
  if (!chart) return
  const paneId = subPaneMap.get(name)
  if (!paneId) return
  chart.removeIndicator(paneId)
  subPaneMap.delete(name)
}

/** 同步副图指标列表（增删） */
function syncSubIndicators(names: string[]): void {
  // 移除不在新列表中的
  for (const key of Array.from(subPaneMap.keys())) {
    if (!names.includes(key)) removeSubIndicator(key)
  }
  // 添加新出现的
  for (const name of names) {
    if (!subPaneMap.has(name)) addSubIndicator(name)
  }
}

onMounted(() => {
  initChart()
  if (props.result) {
    applyResult(props.result)
  }
  // 容器尺寸变化时自动重绘（折叠左侧面板 / 窗口缩放）
  if (chartRef.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => chart?.resize())
    resizeObserver.observe(chartRef.value)
  }
})

watch(
  () => props.result,
  (result) => {
    if (!chart) return
    if (!result) {
      empty.value = true
      loading.value = false
      initialLoadDone = false // 切换股票期间禁止增量加载
      return
    }
    loading.value = false
    empty.value = result.klines.length === 0
    applyResult(result)
  },
)

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  if (chart) {
    dispose(chart)
    chart = null
  }
})

defineExpose({
  resize: () => chart?.resize(),
  addSubIndicator,
  removeSubIndicator,
  syncSubIndicators,
})
</script>

<style scoped>
.kline-chart-wrap {
  position: relative;
  width: 100%;
  height: 100%;
  background: var(--bg-chart);
  border-radius: var(--r-md);
  overflow: hidden;
}
.kline-chart-el {
  width: 100%;
  height: 100%;
}
.kline-chart-loading,
.kline-chart-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-disabled);
  font-size: 13px;
  background: var(--bg-chart);
  z-index: 2;
}
</style>
