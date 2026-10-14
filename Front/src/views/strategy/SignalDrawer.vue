<template>
  <el-drawer
    v-model="visibleRef"
    title="信号详情"
    direction="rtl"
    size="560px"
    append-to-body
  >
    <template v-if="signal">
      <!-- 头部：名称/编码 + 状态 badge + 方向 -->
      <div class="drawer-head">
        <div class="cell-stock">
          <span class="nm">{{ signal.name }}</span>
          <span class="cd mono">{{ signal.code }}</span>
        </div>
        <span class="spacer"></span>
        <span class="badge" :class="stateBadgeClass">{{ stateLabel }}</span>
        <span class="badge" :class="signal.is_buy ? 'badge--rise' : 'badge--fall'">
          {{ signal.is_buy ? '买' : '卖' }}
        </span>
        <!-- 参数版本标识（spec：信号标注产生它的参数版本） -->
        <span class="badge badge--accent mono">参数 v{{ signal.params_version }}</span>
      </div>

      <!-- 信号信息卡：通用字段 + columns 声明驱动的私有字段 -->
      <div class="signal-card">
        <div class="info-row">
          <label>信号日期</label>
          <span class="num">{{ signal.signal_date }}</span>
        </div>
        <div class="info-row">
          <label>入场参考价</label>
          <span class="num">{{ formatPrice(signal.entry_ref_price) }}</span>
        </div>
        <div class="info-row">
          <label>止损参考价</label>
          <span class="num">{{ formatPrice(signal.stop_ref_price) }}</span>
        </div>
        <div v-for="col in privateColumns" :key="col.key" class="info-row">
          <label>{{ col.label }}</label>
          <!-- price_pct 合并列（D12 兜底）：价格 | 涨跌幅 双值渲染 -->
          <span v-if="col.type === 'price_pct'" class="num">
            {{ formatPayload(colValue(signal, col.priceKey || ''), 'float') }}
            <span class="pp-sep">|</span>
            {{ formatPayload(colValue(signal, col.pctKey || ''), 'pct') }}
          </span>
          <span v-else class="num">{{ formatPayload(colValue(signal, col.key), col.type) }}</span>
        </div>
      </div>

      <!-- K 线图（design Open Question：ECharts 简单标记形态）——
           最近 60 日收盘价折线 + 信号日竖线标记（markLine） -->
      <div v-loading="klineLoading" class="signal-chart"></div>
    </template>

    <template #footer>
      <el-button @click="visibleRef = false">关闭</el-button>
      <el-button type="primary" :loading="adding" @click="onAddMonitor">加入监控</el-button>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import EmptyState from '@/components/ui/EmptyState.vue'
import { useEcharts } from '@/composables/useEcharts'
import { getEchartsPalette } from '@/components/charts/echartsPalette'
import { getKLine } from '@/api/modules/kline'
import { createMonitor } from '@/api/modules/monitor'
import type { StrategySignalRow, StrategyDefinition, StrategyColumnDecl, StrategyTask, KLine } from '@/api/types'

/**
 * 信号详情抽屉（strategy-task-redesign 4.6 改造）：
 * - 信息卡：通用字段 + columns 声明驱动的私有字段 + 参数版本标识
 * - K 线图：ECharts 最近 60 日收盘价折线 + 信号日 markLine 竖线
 *   （design Open Question 允许简单标记形态，暂不做 chan 覆盖层集成）
 * - footer「加入监控」：携带 source_type='strategy' + task_id + signal_date
 *   （strategy-task-redesign：来源维度从 instance_id 改 task_id，BREAKING）
 */
const props = defineProps<{
  visible: boolean
  signal: StrategySignalRow | null
  definition: StrategyDefinition | null
  /** 当前选中任务（加监控时随信号来源携带；null 时禁用提交并提示） */
  task: StrategyTask | null
}>()
const emit = defineEmits<{
  'update:visible': [v: boolean]
}>()

const visibleRef = ref(props.visible)
watch(() => props.visible, (v) => (visibleRef.value = v))
watch(visibleRef, (v) => emit('update:visible', v))

// ---- 状态着色（states 声明的 color 映射 badge 样式类，参照 design.css 现有 badge 类） ----
const stateDecl = computed(() => {
  if (!props.definition || !props.signal) return null
  return props.definition.states.find((s) => s.value === props.signal!.state) || null
})
const stateLabel = computed(() => stateDecl.value?.label || props.signal?.state || '')
const COLOR_CLASS: Record<string, string> = {
  info: 'badge--info',
  warning: 'badge--warning',
  danger: 'badge--rise',
  success: 'badge--fall',
}
const stateBadgeClass = computed(() => COLOR_CLASS[stateDecl.value?.color || 'info'] || 'badge--info')

// ---- 私有字段（columns 声明驱动） ----
const privateColumns = computed<StrategyColumnDecl[]>(() => props.definition?.columns || [])

function formatPayload(v: number | string | null | undefined, type: StrategyColumnDecl['type']): string {
  if (v == null || v === '') return '--'
  if (type === 'float') return Number(v).toFixed(2)
  // pct/price_pct 涨幅分量 / outcome 兜底（strategy-signal-outcome D7/D12）：
  // pct 小数转百分比文本、outcome 中文标签，保证不显示裸小数
  if (type === 'pct' || type === 'price_pct') {
    const n = Number(v)
    if (!Number.isFinite(n)) return '--'
    return `${n > 0 ? '+' : ''}${(n * 100).toFixed(1)}%`
  }
  if (type === 'outcome') {
    const LABELS: Record<string, string> = { success: '成功', failed: '失败', pending: '待定' }
    return LABELS[String(v)] || '--'
  }
  return String(v)
}

/** 列取值兜底（strategy-signal-outcome 5.1/D12）：先 payload[key]，无键回退
 *  行级字段（ret_5d 等绩效列与 entry_ref_price 不在 payload）——price_pct
 *  合并列的价格/涨幅分量取值同此双路径 */
function colValue(row: StrategySignalRow, key: string): number | string | null | undefined {
  const pv = row.payload?.[key]
  if (pv !== undefined) return Array.isArray(pv) ? undefined : pv
  return row[key as keyof StrategySignalRow] as number | string | null | undefined
}

function formatPrice(v: number | null | undefined) {
  if (v == null) return '--'
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

// ---- K 线图（ECharts 收盘价折线 + 信号日竖线标记） ----
const chartEl = ref<HTMLElement | null>(null)
const { setOption } = useEcharts(chartEl, () => {
  if (visibleRef.value && props.signal) renderChart()
})

const klineLoading = ref(false)
const klines = ref<KLine[]>([])
let loadSeq = 0

/** 本地时区 YYYY-MM-DD（与 signal_date 同格式比较） */
function tsToDateStr(ts: number): string {
  const d = new Date(ts)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

async function loadKlines(code: string) {
  const seq = ++loadSeq
  klineLoading.value = true
  try {
    const res = await getKLine(code, '1d')
    if (seq !== loadSeq) return // 过期响应丢弃
    klines.value = res.klines || []
    await nextTick()
    renderChart()
  } catch (e) {
    if (seq !== loadSeq) return
    console.warn('[SignalDrawer] K 线加载失败，图表置空', { code, error: e })
    klines.value = []
  } finally {
    if (seq === loadSeq) klineLoading.value = false
  }
}

function renderChart() {
  if (!chartEl.value) return
  const rows = klines.value.slice(-60)
  if (rows.length === 0) return
  const p = getEchartsPalette()
  const dates = rows.map((k) => tsToDateStr(k.timestamp))
  const closes = rows.map((k) => k.close)
  // 信号日竖线标记：取不晚于 signal_date 的最近一个交易日（闭区间语义）
  const signalDate = props.signal?.signal_date || ''
  let markIdx = -1
  for (let i = rows.length - 1; i >= 0; i--) {
    if (dates[i] <= signalDate) {
      markIdx = i
      break
    }
  }
  const series: Record<string, unknown> = {
    type: 'line',
    smooth: true,
    symbol: 'circle',
    symbolSize: 4,
    showSymbol: false,
    data: closes,
    lineStyle: { color: p.accent, width: 2 },
    itemStyle: { color: p.accent, borderColor: p.symbolBorder, borderWidth: 1 },
    areaStyle: {
      color: {
        type: 'linear',
        x: 0, y: 0, x2: 0, y2: 1,
        colorStops: [
          { offset: 0, color: 'rgba(59,130,246,0.18)' },
          { offset: 1, color: 'rgba(59,130,246,0)' },
        ],
      },
    },
  }
  if (markIdx >= 0) {
    series.markLine = {
      silent: true,
      symbol: 'none',
      lineStyle: { color: p.rise, type: 'dashed', width: 1.5 },
      label: {
        show: true,
        formatter: '信号日',
        color: p.rise,
        fontSize: 10,
        position: 'insideEndTop',
      },
      data: [{ xAxis: markIdx }],
    }
  }
  setOption({
    backgroundColor: 'transparent',
    grid: { left: 52, right: 16, top: 24, bottom: 32 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: p.tooltipBg,
      borderColor: p.tooltipBorder,
      textStyle: { color: p.tooltipText, fontSize: 12 },
      valueFormatter: (v: number) => v.toFixed(2),
    },
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: false,
      axisLine: { lineStyle: { color: p.axisLine } },
      axisLabel: { color: p.axisLabelDim, fontSize: 10, fontFamily: 'JetBrains Mono' },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: p.splitLine, type: 'dashed' } },
      axisLabel: { color: p.axisLabelDim, fontSize: 10, fontFamily: 'JetBrains Mono' },
    },
    series: [series],
  } as never)
}

// 抽屉打开（visible && signal）时拉 K 线并渲染；关闭时清状态
watch(
  [visibleRef, () => props.signal],
  ([v, s]) => {
    if (v && s) {
      loadKlines(s.code)
    } else if (!v) {
      klines.value = []
      loadSeq++
    }
  },
)

// ---- 加入监控（design D6：携带 strategy 来源字段；strategy-task-redesign：任务维度） ----
const adding = ref(false)

async function onAddMonitor() {
  const s = props.signal
  if (!s) {
    console.warn('[SignalDrawer] 无上下文信号，忽略提交', { visible: visibleRef.value })
    return
  }
  if (props.task == null) {
    ElMessage.warning('当前无选中任务，无法标记策略来源')
    return
  }
  adding.value = true
  try {
    await createMonitor({
      code: s.code,
      kl_type: 'D',
      entry_price: s.entry_ref_price,
      monitor_start_time: `${s.signal_date} 00:00:00`,
      // 策略来源（strategy-signal-downstream spec）：随信号携带任务与信号日期
      source_type: 'strategy',
      task_id: props.task.id,
      signal_date: s.signal_date,
    })
    ElMessage.success(`已将「${s.name}」加入监控`)
    visibleRef.value = false
  } catch {
    // 失败已由拦截器统一提示，保留抽屉供重试
  } finally {
    adding.value = false
  }
}
</script>

<style scoped>
.drawer-head {
  display: flex;
  align-items: center;
  gap: var(--sp-sm);
  margin-bottom: var(--sp-lg);
}
.cell-stock {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}
.cell-stock .nm {
  color: var(--text-primary);
  font-size: 16px;
  font-weight: 600;
}
.cell-stock .cd {
  color: var(--text-disabled);
  font-size: 12px;
}
.signal-card {
  display: flex;
  flex-direction: column;
  gap: var(--sp-sm);
  padding: var(--sp-md);
  border: 1px solid var(--border-base);
  border-radius: var(--r-md);
  margin-bottom: var(--sp-lg);
}
.info-row {
  display: flex;
  align-items: center;
  font-size: 13px;
}
.info-row label {
  width: 96px;
  flex-shrink: 0;
  color: var(--text-secondary);
}
.info-row .num {
  color: var(--text-primary);
}
/* price_pct 合并列两值分隔符（D12：弱化分隔符视觉层级） */
.pp-sep {
  color: var(--text-disabled);
  margin: 0 2px;
}
.signal-chart {
  width: 100%;
  height: 260px;
}
</style>
