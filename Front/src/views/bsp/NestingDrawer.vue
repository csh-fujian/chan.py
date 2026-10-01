<template>
  <el-drawer
    v-model="visibleRef"
    title="区间套"
    direction="rtl"
    size="560px"
    append-to-body
  >
    <template v-if="record">
      <div class="nesting-head">
        <div class="cell-stock">
          <span class="nm">{{ record.name }}</span>
          <span class="cd mono">{{ record.code }} · {{ klLabel(record.kl_type) }} {{ record.bsp_type }} {{ record.direction === 'buy' ? '买点' : '卖点' }}</span>
        </div>
      </div>

      <!-- ECharts 嵌套示意图 -->
      <div ref="chartEl" class="nesting-chart"></div>

      <!-- 周期子 tab -->
      <div class="mini-tabs">
        <button
          v-for="kl in klLevels"
          :key="kl.value"
          class="mtab"
          :class="{ 'is-active': activeKl === kl.value }"
          @click="activeKl = kl.value"
        >
          {{ kl.label }}
        </button>
      </div>

      <!-- 当前周期买卖点列表 -->
      <div class="nesting-list">
        <div
          v-for="(item, _idx) in currentItems"
          :key="_idx"
          class="nesting-item"
        >
          <span class="badge" :class="item.direction === 'buy' ? 'badge--rise' : 'badge--fall'">
            {{ item.type }}
          </span>
          <div class="meta">
            <span class="t">{{ klLabel(item.kl_type) }}{{ typeLabel(item.type) }}</span>
            <span class="s">{{ item.desc }}</span>
          </div>
          <span class="spacer"></span>
          <div class="meta" style="text-align: right">
            <span class="t num">{{ formatPrice(item.price) }}</span>
            <span class="s">{{ formatDate(item.date) }}</span>
          </div>
        </div>
        <EmptyState v-if="currentItems.length === 0" description="该周期暂无买卖点" />
      </div>
    </template>

    <template #footer>
      <el-button @click="visibleRef = false">关闭</el-button>
      <el-button type="primary" @click="onAddMonitor">加入监控</el-button>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts/core'
import { TreemapChart } from 'echarts/charts'
import EmptyState from '@/components/ui/EmptyState.vue'
import { useEcharts } from '@/composables/useEcharts'
import { getEchartsPalette } from '@/components/charts/echartsPalette'
import type { BspRecord } from '@/api/types'

// 注册 treemap（useEcharts 仅注册了 line/bar）
echarts.use([TreemapChart])

const props = defineProps<{
  visible: boolean
  record: BspRecord | null
}>()
const emit = defineEmits<{
  'update:visible': [v: boolean]
}>()

const visibleRef = ref(props.visible)
watch(() => props.visible, (v) => (visibleRef.value = v))
watch(visibleRef, (v) => emit('update:visible', v))

const chartEl = ref<HTMLElement | null>(null)
// 主题切换收口在 useEcharts：抽屉打开时以新调色板重建 option（任务 6.4）
const { setOption } = useEcharts(chartEl, () => {
  if (visibleRef.value && props.record) renderChart()
})

// 周期子集（design D1）：与 BspView.klOptions 同集合 — 30分/60分/日线/周线/月线
const KL_LABEL_MAP: Record<string, string> = {
  '30m': '30分',
  '60m': '60分',
  D: '日线',
  W: '周线',
  M: '月线',
}
const klLevels = [
  { label: '30分', value: '30m' },
  { label: '60分', value: '60m' },
  { label: '日线', value: 'D' },
  { label: '周线', value: 'W' },
  { label: '月线', value: 'M' },
]
const activeKl = ref('D')

// W/M 等周期显示中文标签（周线/月线），不再兜底显示原始值
function klLabel(v: string) {
  return KL_LABEL_MAP[v] || v
}

// 记录切换时定位到其自身周期的子 tab（W/M 记录打开即显示周线/月线）
watch(
  () => props.record,
  (r) => {
    activeKl.value = r && KL_LABEL_MAP[r.kl_type] ? r.kl_type : 'D'
  },
  { immediate: true },
)

function typeLabel(t: string) {
  const map: Record<string, string> = {
    '1B': '第一类买点',
    '2B': '第二类买点',
    '3B': '第三类买点',
    '1S': '第一类卖点',
    '2S': '第二类卖点',
    '3S': '第三类卖点',
    'L2B': '类二买点',
    'L2S': '类二卖点',
    'PZ-B': '盘整买点',
    'PZ-S': '盘整卖点',
  }
  return map[t] || t
}
function formatPrice(v: number) {
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
function formatDate(ts: number) {
  const d = new Date(ts)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

interface NestItem {
  kl_type: string
  type: string
  direction: 'buy' | 'sell'
  price: number
  date: number
  desc: string
}

// 基于 record 生成多级别买卖点 mock（每个周期子 tab 一条，记录自身周期用真实数据）
const allItems = computed<NestItem[]>(() => {
  if (!props.record) return []
  const r = props.record
  const base = r.bsp_price
  const date = r.bsp_date
  const dir = r.direction
  const t = r.bsp_type
  const descs = ['大级别背驰后确认', '回抽不创新低', '中枢上移后回调不破', '次级别区间套确认', '本级别结构完成']
  return klLevels.map((kl, idx) => {
    const isSelf = kl.value === r.kl_type
    return {
      kl_type: kl.value,
      type: isSelf ? t : dir === 'buy' ? (idx % 2 === 0 ? '2B' : '3B') : idx % 2 === 0 ? '2S' : '3S',
      direction: dir,
      price: isSelf ? base : +(base * (1 + (idx - 2) * 0.01)).toFixed(2),
      date: isSelf ? date : date + idx * 3600000,
      desc: isSelf ? '本级别买卖点（记录本体）' : descs[idx] || '次级别结构确认',
    }
  })
})

const currentItems = computed(() => allItems.value.filter((i) => i.kl_type === activeKl.value))

// 绘制嵌套示意图
watch(
  [visibleRef, () => props.record],
  ([v]) => {
    if (!v || !props.record) return
    nextTick(() => {
      renderChart()
    })
  },
  { immediate: true },
)

function renderChart() {
  if (!chartEl.value) return
  const items = allItems.value
  if (items.length === 0) return
  const pal = getEchartsPalette()

  // 嵌套矩形：大级别在外，小级别在内
  // 买红卖绿为语义色（主题不变，spec「主题无关的语义色」），仅标签/tooltip 随主题
  const data = items.map((it) => ({
    value: 1,
    itemStyle: {
      color: it.direction === 'buy' ? 'rgba(246, 70, 93, 0.18)' : 'rgba(46, 189, 133, 0.18)',
      borderColor: it.direction === 'buy' ? 'rgba(246, 70, 93, 0.7)' : 'rgba(46, 189, 133, 0.7)',
      borderWidth: 1.5,
    },
    label: {
      show: true,
      formatter: `${klLabel(it.kl_type)} ${it.type}\n${formatPrice(it.price)}`,
      color: pal.labelText,
      fontSize: 11,
      fontFamily: 'JetBrains Mono, monospace',
    },
  }))

  setOption({
    tooltip: {
      trigger: 'item',
      backgroundColor: pal.tooltipBg,
      borderColor: pal.tooltipBorder,
      textStyle: { color: pal.tooltipText, fontSize: 12 },
      formatter: (p: any) => {
        const it = items[p.dataIndex]
        return `${klLabel(it.kl_type)} ${it.type}<br/>价格: ${formatPrice(it.price)}<br/>日期: ${formatDate(it.date)}<br/>${it.desc}`
      },
    },
    series: [
      {
        type: 'treemap',
        data,
        width: '100%',
        height: 180,
        roam: false,
        nodeClick: false,
        breadcrumb: { show: false },
        label: { position: 'insideTopLeft', distanceToParent: 8 },
        upperLabel: { show: false },
        itemStyle: { gapWidth: 6 },
        levels: [
          {
            color: ['rgba(246, 70, 93, 0.18)', 'rgba(46, 189, 133, 0.18)'],
            colorMappingBy: 'value',
          },
        ],
      },
    ],
  } as any)
}

function onAddMonitor() {
  if (!props.record) return
  ElMessage.success(`已将「${props.record.name}」加入监控（演示）`)
  visibleRef.value = false
}
</script>

<style scoped>
.nesting-head {
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
.nesting-chart {
  width: 100%;
  height: 200px;
  margin-bottom: var(--sp-lg);
}
.mini-tabs {
  display: flex;
  gap: 4px;
  margin-bottom: var(--sp-lg);
}
.mtab {
  padding: 6px 14px;
  font-size: 12px;
  border-radius: var(--r-md);
  color: var(--text-secondary);
  border: 1px solid transparent;
  cursor: pointer;
  background: transparent;
}
.mtab.is-active {
  color: var(--text-primary);
  background: var(--bg-surface-hover);
  border-color: var(--border-base);
}
.mtab:hover {
  color: var(--text-primary);
}
.nesting-list {
  display: flex;
  flex-direction: column;
}
.nesting-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 0;
  border-bottom: 1px solid var(--border-base);
}
.nesting-item:last-child {
  border-bottom: none;
}
.nesting-item .meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.nesting-item .meta .t {
  font-size: 13px;
  color: var(--text-primary);
}
.nesting-item .meta .s {
  font-size: 11px;
  color: var(--text-disabled);
}
</style>
