---
name: vue-chart-patterns
description: Chart patterns for Vue 3 web applications using klinecharts (K-line) and ECharts (statistical charts). Use when implementing trading charts, statistical visualizations, or chart interactions.
---

# Vue Chart Patterns

## Problem Statement

K-line (candlestick) charts and statistical visualizations are core to financial/trading applications. Proper integration with Vue 3's reactivity system and lifecycle, plus performance optimization for real-time data, is critical.

---

## Tech Stack

- **K-line charts**: klinecharts 9.8
- **Statistical charts**: ECharts 5.5
- **Wrapper**: `vue-echarts` (official) for ECharts; klinecharts can be used directly

---

## Pattern: ECharts Integration with vue-echarts

```vue
<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart, PieChart } from 'echarts/charts'
import {
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent,
} from 'echarts/components'
import type { EChartsOption } from 'echarts'

// Register required components (tree-shaking)
use([
  CanvasRenderer,
  LineChart,
  BarChart,
  PieChart,
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent,
])

const props = defineProps<{
  data: Array<{ name: string; value: number }>
  title?: string
  loading?: boolean
}>()

const option = computed<EChartsOption>(() => ({
  title: { text: props.title },
  tooltip: {},
  xAxis: { type: 'category', data: props.data.map(d => d.name) },
  yAxis: { type: 'value' },
  series: [{ data: props.data.map(d => d.value), type: 'bar' }],
}))

// Resize observer for responsive charts
import { useResizeObserver } from '@vueuse/core'
const chartRef = ref<InstanceType<typeof VChart> | null>(null)
</script>

<template>
  <VChart
    ref="chartRef"
    :option="option"
    :loading="loading"
    autoresize
    class="h-[400px]"
  />
</template>
```

**Key points:**
- Always use `use()` to register only needed components (tree-shaking reduces bundle size)
- Use `computed` for reactive chart options
- `autoresize` prop handles window resize automatically
- Set explicit height on the container (ECharts requires a fixed height)

---

## Pattern: Reactive Data Updates

**Problem:** Chart needs to update smoothly when data changes without full re-render.

```vue
<script setup lang="ts">
import { ref, watch, shallowRef } from 'vue'
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'

const props = defineProps<{
  timeSeries: Array<{ timestamp: number; value: number }>
}>()

const option = shallowRef<EChartsOption>({})

// Watch data changes and update chart incrementally
watch(
  () => props.timeSeries,
  (newData) => {
    option.value = {
      xAxis: { type: 'time' },
      yAxis: { type: 'value' },
      series: [{
        type: 'line',
        data: newData.map(d => [d.timestamp, d.value]),
        smooth: true,
      }],
    }
  },
  { deep: false }
)
</script>

<template>
  <VChart :option="option" autoresize class="h-[400px]" />
</template>
```

**Performance tips:**
- Use `shallowRef` for chart options to avoid deep reactivity overhead on large data arrays
- Set `deep: false` on watchers for large datasets
- Use ECharts' `appendData` for real-time streaming (avoids full re-render)

---

## Pattern: K-line Chart with klinecharts

```vue
<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { init, dispose } from 'klinecharts'
import type { Chart, KLineData } from 'klinecharts'

const chartContainer = ref<HTMLDivElement>()
let chart: Chart | null = null

const props = defineProps<{
  symbol: string
  klineData: KLineData[]
  theme?: 'light' | 'dark'
}>()

// Initialize chart on mount
onMounted(() => {
  if (!chartContainer.value) return

  chart = init(chartContainer.value, {
    styles: {
      grid: { horizontal: { color: '#e0e0e0' } },
      candle: {
        type: 'candle_solid',
        bar: {
          upColor: '#ef5350',    // Chinese-style red for up
          downColor: '#26a69a',   // Green for down
        },
      },
    },
  })

  // Load initial data
  if (props.klineData.length > 0) {
    chart.applyNewData(props.klineData)
  }
})

// Update data reactively
watch(
  () => props.klineData,
  (newData) => {
    if (newData.length > 0) {
      chart?.applyNewData(newData)
    }
  }
)

// Real-time price updates (use updateData for last candle)
function updateLastCandle(lastCandle: KLineData) {
  chart?.updateData(lastCandle)
}

// Cleanup
onBeforeUnmount(() => {
  if (chart) {
    dispose(chartContainer.value!)
    chart = null
  }
})
</script>

<template>
  <div class="flex flex-col h-full">
    <div v-if="symbol" class="text-lg font-bold px-4 py-2">
      {{ symbol }}
    </div>
    <div ref="chartContainer" class="flex-1 min-h-0" />
  </div>
</template>
```

**Key points for klinecharts:**
- `init()` creates the chart instance; always pair with `dispose()` on unmount
- `applyNewData()` replaces all candles; `updateData()` updates only the last one (for real-time)
- klinecharts has a rich API: `createIndicator()` for MA/MACD/RSI, `setStyles()` for theming
- The container div must have a fixed height (use `flex-1 min-h-0` in a flex layout)

---

## Pattern: Adding Technical Indicators

```typescript
// After chart is initialized
import { MAIndicator, MACDIndicator, RSIIndicator } from 'klinecharts'

// Add MA indicator
const maIndicator = chart.createIndicator('MA', false, {
  id: 'candle_pane',
  MAIndicator: { params: { days: [5, 10, 20, 60] } },
})

// Add RSI indicator
const rsiIndicator = chart.createIndicator('RSI', true, {
  id: 'rsi_pane',
  height: 120,
})

// Remove indicator
chart.removeIndicator('MA')
```

**Available indicators:** MA, EMA, BOLL, MACD, RSI, KDJ, DMI, OBV, etc.

---

## Pattern: Chart with Time Range Selector

```vue
<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import type { Chart } from 'klinecharts'

type Period = '1m' | '5m' | '15m' | '30m' | '1h' | '4h' | '1d' | '1w'
const currentPeriod = ref<Period>('1d')
const periods: { label: string; value: Period }[] = [
  { label: '1分', value: '1m' },
  { label: '5分', value: '5m' },
  { label: '15分', value: '15m' },
  { label: '30分', value: '30m' },
  { label: '1时', value: '1h' },
  { label: '4时', value: '4h' },
  { label: '日线', value: '1d' },
  { label: '周线', value: '1w' },
]

const emit = defineEmits<{
  changePeriod: [period: Period]
}>()

function selectPeriod(period: Period) {
  currentPeriod.value = period
  emit('changePeriod', period)
}
</script>

<template>
  <div class="flex gap-2 p-2">
    <el-radio-group
      v-model="currentPeriod"
      size="small"
      @change="(v: Period) => emit('changePeriod', v)"
    >
      <el-radio-button
        v-for="p in periods"
        :key="p.value"
        :value="p.value"
      >
        {{ p.label }}
      </el-radio-button>
    </el-radio-group>
  </div>
</template>
```

---

## Pattern: ECharts Performance Best Practices

### 1. Lazy Loading Components

```typescript
// Only register what you need — NEVER import ALL echarts!
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
// Register one chart type at a time
use([CanvasRenderer, LineChart])
```

### 2. Large Dataset Handling

```typescript
// For 10K+ data points on a line chart
const option = computed(() => ({
  series: [{
    type: 'line',
    sampling: 'lttb',   // Largest Triangle Three Buckets downsampling
    large: true,          // Enable large data mode
    largeThreshold: 2000, // Threshold for large mode
    data: timeSeries.value,
  }],
}))
```

### 3. Avoid Re-rendering Entire Chart

```typescript
// Use setOption with notMerge: false for incremental updates
chart.value?.setOption(newOption, { notMerge: false })

// For streaming data, use appendData
chart.value?.appendData({ seriesIndex: 0, data: [newPoints] })
```

---

## Pattern: Responsive Multi-Chart Layout

```vue
<template>
  <div class="flex flex-col h-screen">
    <!-- K-line chart: 70% height -->
    <div ref="klineContainer" class="h-[70%] min-h-0" />
    
    <!-- Volume or indicator: 30% height -->
    <div class="flex gap-4 h-[30%] min-h-0 p-2">
      <VChart :option="indicatorOption" autoresize class="flex-1" />
      <VChart :option="comparisonOption" autoresize class="flex-1" />
    </div>
  </div>
</template>
```

**Layout rule:** Always use `min-h-0` on flex children to allow them to shrink below their content size.

---

## Pattern: Dark Mode Chart Theming

```typescript
// ECharts dark theme
const darkTheme = {
  backgroundColor: '#1a1a2e',
  textStyle: { color: '#e0e0e0' },
  title: { textStyle: { color: '#e0e0e0' } },
  legend: { textStyle: { color: '#e0e0e0' } },
  grid: { borderColor: '#333' },
  xAxis: { axisLine: { lineStyle: { color: '#555' } } },
  yAxis: { splitLine: { lineStyle: { color: '#2a2a3e' } } },
}

// klinecharts dark theme
chart?.setStyles({
  grid: {
    horizontal: { color: '#2a2a3e' },
    vertical: { color: '#2a2a3e' },
  },
  candle: {
    bar: {
      upColor: '#ef5350',
      downColor: '#26a69a',
      noChangeColor: '#888888',
    },
  },
  xAxis: { tickText: { color: '#888' } },
  yAxis: { tickText: { color: '#888' } },
})
```

---

## Common Issues

| Issue | Solution |
|-------|----------|
| Chart not showing | Container needs explicit height; check if component registered with `use()` |
| Chart blank after route change | klinecharts needs `dispose()` on unmount to prevent leaks |
| Real-time updates causing lag | Use `updateData()` (not `applyNewData()`) for last candle; use `shallowRef` for options |
| ECharts bundle too large | Import only needed components via `echarts/core` tree-shaking |
| Chart not responsive | Use `autoresize` prop or `useResizeObserver` from VueUse |
| Memory leak on klinecharts | Always call `dispose(container)` in `onBeforeUnmount` |
| Dark mode flicker | Store theme in Pinia, use `computed` to generate themed options |

---

## Chart Testing

```typescript
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import PriceChart from '@/components/PriceChart.vue'

// Mock klinecharts (it uses canvas/DOM APIs unavailable in jsdom)
vi.mock('klinecharts', () => ({
  init: vi.fn(() => ({
    applyNewData: vi.fn(),
    updateData: vi.fn(),
    createIndicator: vi.fn(),
    setStyles: vi.fn(),
  })),
  dispose: vi.fn(),
}))

describe('PriceChart', () => {
  it('renders chart container', () => {
    const wrapper = mount(PriceChart, {
      props: { symbol: 'BTC/USDT', klineData: [] },
    })
    expect(wrapper.find('[ref="chartContainer"]').exists()).toBe(true)
  })
})
```