<template>
  <div class="kline-page">
    <!-- 顶栏工具栏 — design.md D9 -->
    <header class="topbar reveal">
      <!-- 折叠左侧面板（置于最左侧） -->
      <button class="btn btn--ghost btn--sm panel-toggle" :title="panelCollapsed ? '展开面板' : '折叠面板'" @click="panelCollapsed = !panelCollapsed">
        <el-icon><Expand v-if="panelCollapsed" /><Fold v-else /></el-icon>
      </button>

      <!-- 搜索框：el-autocomplete 远程下拉（D5 Enter 语义 / D6 300ms 本地防抖） -->
      <div class="code-field" @keydown.capture="onSearchKeydown">
        <el-autocomplete
          ref="acRef"
          v-model="codeInput"
          :fetch-suggestions="queryStocks"
          :trigger-on-focus="false"
          :debounce="0"
          placeholder="代码/名称/拼音 如 sz.000001"
          :prefix-icon="SearchIcon"
          size="default"
          @select="onSelectSuggestion"
        >
          <template #default="{ item }">
            <div class="sug-item" :class="{ 'sug-item--empty': item.placeholder }">
              <template v-if="item.placeholder">
                <span class="sug-item__empty">{{ item.name }}</span>
              </template>
              <template v-else>
                <span class="sug-item__code mono">{{ item.code }}</span>
                <span class="sug-item__name">{{ item.name }}</span>
              </template>
            </div>
          </template>
        </el-autocomplete>
      </div>
      <el-button type="primary" size="default" :loading="loading" @click="handleSearch">
        搜索
      </el-button>

      <!-- 周期选项与 DuckDB kl_type 对齐：K_5M/K_15M/K_30M/K_60M/K_DAY/K_WEEK/K_MON（无 1 分钟） -->
      <el-select v-model="period" size="default" class="period-select">
        <el-option label="5分钟" value="5m" />
        <el-option label="15分钟" value="15m" />
        <el-option label="30分钟" value="30m" />
        <el-option label="60分钟" value="60m" />
        <el-option label="日线" value="1d" />
        <el-option label="周线" value="1w" />
        <el-option label="月线" value="1M" />
      </el-select>

      <!-- 副图指标：自定义多选（缩略展示 + 悬浮查看全部） -->
      <el-popover
        v-model:visible="indicatorMenuVisible"
        trigger="click"
        placement="bottom-start"
        :width="220"
        :show-arrow="false"
      >
        <template #reference>
          <button class="indicator-trigger" type="button">
            <span class="indicator-trigger__label">副图指标</span>
            <el-tooltip
              v-if="subIndicators.length"
              :content="indicatorTooltip"
              placement="bottom"
              :disabled="subIndicators.length < 2"
            >
              <span class="indicator-trigger__val mono">{{ indicatorSummary }}</span>
            </el-tooltip>
            <el-icon class="indicator-trigger__chev"><ArrowDown /></el-icon>
          </button>
        </template>
        <div class="indicator-menu">
          <div
            v-for="opt in indicatorOptions"
            :key="opt.value"
            class="indicator-option"
            @click="toggleIndicator(opt.value)"
          >
            <span class="check-dot" :class="{ 'is-on': subIndicators.includes(opt.value) }" />
            <span>{{ opt.label }}</span>
          </div>
        </div>
      </el-popover>

      <!-- 均线配置 — kline-chart-change D2 -->
      <button class="btn btn--ghost btn--sm topbar-action" @click="maDialogVisible = true">
        <el-icon><TrendCharts /></el-icon> 均线
      </button>

      <span class="topbar__spacer" />

      <!-- 快捷入口：加入自选 / AI 问答 -->
      <button class="btn btn--ghost btn--sm topbar-action" @click="jumpTo('stock')">
        <el-icon><Star /></el-icon> 加入自选
      </button>
      <button class="btn btn--ghost btn--sm topbar-action" @click="jumpTo('qa')">
        <el-icon><ChatDotRound /></el-icon> AI 问答
      </button>

      <!-- 图例提示 — design.md D9 图例 -->
      <div class="tip legend-trigger">
        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="9" /><path d="M12 8v5M12 16.5v.01" />
        </svg>
        <div class="tip__bubble">
          <div class="legend-title">缠论图例</div>
          <div class="legend-row"><span class="sw"></span>笔（灰线）</div>
          <div class="legend-row"><span class="sw sw--seg"></span>线段（蓝线）</div>
          <div class="legend-row"><span class="sw sw--box"></span>笔中枢（灰框）</div>
          <div class="legend-row"><span class="sw sw--box sw--box2"></span>线段中枢（蓝框）</div>
          <div class="legend-row"><span class="dot dot--buy"></span>买点（1B/2B/L2B/3B）</div>
          <div class="legend-row"><span class="dot dot--sell"></span>卖点（1S/2S/L2S/3S）</div>
        </div>
      </div>
    </header>

    <!-- 主体：可折叠左侧面板 + 主图 — design.md D1 -->
    <div class="kline-body">
      <aside class="kline-side" :class="{ 'is-collapsed': panelCollapsed }">
        <div class="kline-side__tabs">
          <button class="tab" :class="{ 'is-active': activeTab === 'stock' }" @click="activeTab = 'stock'">标的</button>
          <button class="tab" :class="{ 'is-active': activeTab === 'meta' }" @click="activeTab = 'meta'">股票信息</button>
          <button class="tab" :class="{ 'is-active': activeTab === 'qa' }" @click="activeTab = 'qa'">问答</button>
        </div>
        <div class="kline-side__body">
          <!-- Tab 内容缓存（design D7 / 1.3）：组件 :is + KeepAlive，三个 Tab 各一缓存槽，
               首次切换才挂载、其后本地状态跨 Tab 保留；缓存实例经 :code/:period prop 更新换股刷新 -->
          <KeepAlive>
            <component :is="activeTabComponent" v-bind="activeTabProps" />
          </KeepAlive>
        </div>
      </aside>

      <section class="chart chart--grid main-chart reveal reveal--1">
        <div class="chart__tag">{{ code.toUpperCase() }} · {{ periodLabel }} · 前复权</div>
        <KLineChart ref="chartComp" :result="result" :code="code" :period="period" />
      </section>
    </div>

    <!-- 均线配置弹窗 — kline-chart-change 1.4 -->
    <MaConfigDialog v-model="maDialogVisible" />
  </div>
</template>

<script setup lang="ts">
/**
 * KLineView.vue — K 线分析页
 * design.md D1：可折叠左侧面板（标的 / 股票信息 / 问答）+ 主图
 * design.md D7 / 1.3：面板 Tab 内容缓存（KeepAlive 三槽，换股经 prop 刷新）
 * design.md D6：切换代码/周期触发命令式重载
 * kline-metadata-change D5/D6：搜索框 el-autocomplete 远程下拉 + Enter 语义 + 300ms 本地防抖
 * design.md D10（2026-10-04 修订）：AppShell KeepAlive include 白名单按组件名匹配，
 *   故显式命名 KLineView（script setup 组件默认匿名，include 不命中即不缓存）
 */
defineOptions({ name: 'KLineView' })

import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Search, Star, ChatDotRound, Fold, Expand, ArrowDown, TrendCharts } from '@element-plus/icons-vue'
import { ElMessage, type AutocompleteInstance } from 'element-plus'
import KLineChart from '@/components/charts/KLineChart.vue'
import StockPanel from '@/components/kline/StockPanel.vue'
import StockMetaPanel from '@/components/kline/StockMetaPanel.vue'
import QaPanel from '@/components/kline/QaPanel.vue'
import MaConfigDialog from '@/components/kline/MaConfigDialog.vue'
import { getKLine } from '@/api/modules/kline'
import { searchStocks } from '@/api/modules/stock'
import type { ChanResult } from '@/api/types'

const route = useRoute()
const SearchIcon = Search

const codeInput = ref('sz.000001')
const code = ref('sz.000001')
const period = ref('1d')
const loading = ref(false)
const result = ref<ChanResult | null>(null)
const subIndicators = ref<string[]>(['VOL', 'MACD'])

// 副图指标多选（自定义缩略展示）
const indicatorMenuVisible = ref(false)
// 均线配置弹窗（kline-chart-change 1.4）
const maDialogVisible = ref(false)
const indicatorOptions = [
  { label: '成交量 VOL', value: 'VOL' },
  { label: 'MACD', value: 'MACD' },
  { label: 'BOLL', value: 'BOLL' },
  { label: 'RSI', value: 'RSI' },
  { label: 'KDJ', value: 'KDJ' },
]
const indicatorSummary = computed(() => {
  const n = subIndicators.value.length
  if (n === 0) return ''
  const rest = n - 1
  return rest > 0 ? `${subIndicators.value[0]} +${rest}` : subIndicators.value[0]
})
const indicatorTooltip = computed(() =>
  subIndicators.value
    .map((v) => indicatorOptions.find((o) => o.value === v)?.label ?? v)
    .join('、'),
)

// 左侧面板状态（默认仍为「标的」）
const panelCollapsed = ref(false)
const activeTab = ref<'stock' | 'meta' | 'qa'>('stock')

// Tab → 组件映射（design D7 / 1.3）：KeepAlive 按组件类型各占一缓存槽
const tabComponentMap = {
  stock: StockPanel,
  meta: StockMetaPanel,
  qa: QaPanel,
} as const

const activeTabComponent = computed(() => tabComponentMap[activeTab.value])

/** 各 Tab 所需 props：问答 Tab 携带 code/period 用于提问上下文（6.1 / design D8.4） */
const activeTabProps = computed(() =>
  activeTab.value === 'qa'
    ? { code: code.value, period: period.value }
    : { code: code.value },
)

const chartComp = ref<InstanceType<typeof KLineChart> | null>(null)

const periodLabel = computed(() => {
  const m: Record<string, string> = {
    '5m': '5分钟', '15m': '15分钟', '30m': '30分钟', '60m': '60分钟',
    '1d': '日线', '1w': '周线', '1M': '月线',
  }
  return m[period.value] ?? period.value
})

/** URL query 合法周期集合（任务 4.3）：词表外值（如 bsp 词表 D/W/M 未映射前）回退默认，不触发误加载 */
const PERIOD_MAP: Record<string, boolean> = {
  '5m': true, '15m': true, '30m': true, '60m': true, '1d': true, '1w': true, '1M': true,
}

/** 快捷入口：切到指定 Tab 并展开面板 */
function jumpTo(tab: 'stock' | 'qa'): void {
  activeTab.value = tab
  panelCollapsed.value = false
}

/** 加载序号：快速连续切换周期/股票时丢弃过期响应，避免旧周期数据覆盖新周期 */
let loadSeq = 0

/** 加载 K 线 + 缠论数据 */
async function load(): Promise<void> {
  const seq = ++loadSeq
  loading.value = true
  try {
    const res = await getKLine(code.value, period.value)
    if (seq !== loadSeq) return
    result.value = res
  } catch (e) {
    if (seq !== loadSeq) return
    ElMessage.error('加载 K 线数据失败')
    result.value = null
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

/** 搜索 — 切换代码/周期触发重载 */
function handleSearch(): void {
  cancelSuggest()
  arrowBrowsed.value = false
  acRef.value?.close()
  const c = codeInput.value.trim()
  if (!c) {
    ElMessage.warning('请输入股票代码')
    return
  }
  code.value = c
  load()
}

// ---------------------------------------------------------------------------
// 股票搜索下拉（kline-stock-search）：300ms 本地防抖 + 后发覆盖 + Enter 语义
// ---------------------------------------------------------------------------
interface StockSuggestion {
  /** el-autocomplete valueKey 默认取 value；点选后回填输入框 */
  value: string
  code: string
  name: string
  /** 无匹配候选的空态提示项，不参与加载 */
  placeholder?: boolean
}

const acRef = ref<AutocompleteInstance | null>(null)
/** 用户是否用 ↑↓ 浏览过候选（D5 Enter 分流标志，输入内容变化时重置） */
const arrowBrowsed = ref(false)
let suggestTimer: ReturnType<typeof setTimeout> | null = null
let suggestSeq = 0

/** 取消在途/待发的搜索请求（后发覆盖的作废通道） */
function cancelSuggest(): void {
  if (suggestTimer !== null) {
    clearTimeout(suggestTimer)
    suggestTimer = null
  }
  suggestSeq++
}

/**
 * 远程搜索候选（D6：300ms 本地 setTimeout 防抖，不引 lodash）。
 * 空输入不请求并收起下拉；过期响应丢弃，只采纳最后一次 query 的结果。
 */
function queryStocks(q: string, cb: (items: StockSuggestion[]) => void): void {
  if (suggestTimer !== null) {
    clearTimeout(suggestTimer)
    suggestTimer = null
  }
  const query = q.trim()
  if (!query) {
    cancelSuggest()
    cb([])
    return
  }
  // 请求发出前先收起旧候选，避免加载态闪烁；结果到达后再展开
  cb([])
  suggestTimer = setTimeout(async () => {
    suggestTimer = null
    const seq = ++suggestSeq
    try {
      const list = await searchStocks(query)
      if (seq !== suggestSeq) return // 过期响应丢弃（后发覆盖）
      if (!list.length) {
        // 无匹配候选：下拉空态提示，不阻断手动输入加载（4.4）
        cb([{ value: query, code: '', name: '无匹配候选', placeholder: true }])
        return
      }
      cb(list.map((s) => ({ value: s.code, code: s.code, name: s.name })))
    } catch (e) {
      if (seq !== suggestSeq) return
      console.warn('[KLineView.queryStocks] 股票搜索失败', {
        query,
        error: e instanceof Error ? e.message : String(e),
      })
      cb([])
    }
  }, 300)
}

/** 点选候选（鼠标任何时候）：同步输入框为 code 并精确加载 */
function onSelectSuggestion(item: StockSuggestion): void {
  cancelSuggest()
  arrowBrowsed.value = false
  acRef.value?.close()
  if (item.placeholder) {
    // 空态提示项：仅收起下拉，不发起加载
    return
  }
  codeInput.value = item.code
  code.value = item.code
  load()
}

/**
 * Enter 语义（D5，捕获阶段拦截，防 autocomplete 默认回车劫持）：
 * - 未用 ↑↓ 浏览过候选 → Enter 按输入框原值走既有 handleSearch()
 * - 用 ↑↓ 浏览过且有高亮项 → 交给 autocomplete 选中高亮项
 */
function onSearchKeydown(e: KeyboardEvent): void {
  // IME 组合确认的 Enter（如中文「平安」上屏）不触发搜索
  if (e.isComposing || e.keyCode === 229) return
  if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
    arrowBrowsed.value = true
    return // 继续传播，由 autocomplete 移动高亮
  }
  if (e.key !== 'Enter') return
  const ac = acRef.value
  const highlighted = ac?.highlightedIndex ?? -1
  const count = ac?.suggestions?.length ?? 0
  if (arrowBrowsed.value && highlighted >= 0 && highlighted < count) {
    return // 交给 autocomplete 选中高亮候选
  }
  e.preventDefault()
  e.stopPropagation()
  handleSearch()
}

/** 副图指标增删（自定义多选） */
function toggleIndicator(value: string): void {
  const i = subIndicators.value.indexOf(value)
  if (i >= 0) {
    subIndicators.value.splice(i, 1)
  } else {
    if (subIndicators.value.length >= 5) {
      ElMessage.warning('副图指标最多 5 个')
      return
    }
    subIndicators.value.push(value)
  }
  chartComp.value?.syncSubIndicators(subIndicators.value)
}

onMounted(() => {
  // 从 URL query 参数读取股票代码与周期（从其他页面跳转，如买卖点页双击行）
  const qCode = route.query.code
  if (qCode && typeof qCode === 'string' && qCode.trim()) {
    code.value = qCode.trim()
    codeInput.value = code.value
  }
  const qPeriod = route.query.period
  if (qPeriod && typeof qPeriod === 'string' && PERIOD_MAP[qPeriod]) {
    period.value = qPeriod
  }
  load()
})

// 页面缓存（design.md D10）：本页被 KeepAlive 缓存后，onMounted 不再执行，
// 带参跳入（自选 → kline?code=）需经此 watch 按新代码加载；
// query 缺省（普通切回）或与当前一致时保持缓存原样，不触发重载
watch(
  () => route.query,
  (q) => {
    const qCode = q.code
    if (typeof qCode === 'string' && qCode.trim()) {
      const c = qCode.trim()
      // 输入框始终同步为 URL 中的代码（即使与当前已加载代码一致）
      if (c !== codeInput.value) codeInput.value = c
      // 仅代码变化才触发重载；与当前一致时保持缓存数据原样
      if (c !== code.value) {
        code.value = c
        load()
      }
    }
    // 周期变化（如买卖点页双击行带 period 跳入）：合法才应用，经 watch(period) 触发重载
    const qPeriod = q.period
    if (typeof qPeriod === 'string' && PERIOD_MAP[qPeriod] && qPeriod !== period.value) {
      period.value = qPeriod
    }
  },
)

// 周期切换触发重载
watch(period, () => load())

// 输入内容变化 → 重置 ↑↓ 浏览标志（D5）
watch(codeInput, () => {
  arrowBrowsed.value = false
})

// 数据加载后同步副图指标
watch(result, () => {
  if (result.value) {
    chartComp.value?.syncSubIndicators(subIndicators.value)
  }
})

onBeforeUnmount(() => {
  if (suggestTimer !== null) {
    clearTimeout(suggestTimer)
    suggestTimer = null
  }
})
</script>

<style scoped>
.kline-page {
  display: flex;
  flex-direction: column;
  /* AppShell content 区有 topnav(52px) + content padding(24px*2)，填满剩余视口 */
  height: calc(100vh - var(--topnav-h) - var(--sp-2xl) * 2);
  min-height: 520px;
  gap: var(--sp-sm);
}

.topbar {
  display: flex;
  align-items: center;
  gap: var(--sp-md);
  height: var(--topbar-h);
  padding: 0 var(--sp-lg);
  border-bottom: 1px solid var(--border-base);
  background: var(--bg-surface);
  flex-shrink: 0;
  position: relative;
  z-index: 20;
}
.topbar .topbar__spacer { flex: 1; }

.code-field {
  width: 220px;
}
.code-field :deep(.el-autocomplete) {
  width: 100%;
}
.code-field :deep(.el-input__wrapper) {
  background: var(--bg-surface);
  box-shadow: 0 0 0 1px var(--border-base) inset;
}
.code-field :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--accent-base) inset, 0 0 14px var(--accent-glow);
}
.code-field :deep(.el-input__inner) {
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--text-primary);
}

/* 搜索候选下拉项：code + 名称（插槽内容带本组件 scope，可直接写 scoped 样式） */
.sug-item {
  display: flex;
  align-items: center;
  gap: var(--sp-sm);
  padding: 2px 0;
}
.sug-item__code {
  width: 84px;
  flex-shrink: 0;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 12px;
  color: var(--accent-hover);
}
.sug-item__name {
  font-size: 13px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sug-item__empty {
  font-size: 12px;
  color: var(--text-disabled);
}

.period-select {
  width: 110px;
}
.period-select :deep(.el-select__wrapper) {
  background: var(--bg-surface);
  box-shadow: 0 0 0 1px var(--border-base) inset;
}
.period-select :deep(.el-select__wrapper.is-focused) {
  box-shadow: 0 0 0 1px var(--accent-base) inset, 0 0 14px var(--accent-glow);
}

/* 副图指标自定义多选触发器 */
.indicator-trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 10px;
  background: var(--bg-surface);
  border: 1px solid var(--border-base);
  border-radius: var(--r-md);
  color: var(--text-primary);
  font-size: 13px;
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
  white-space: nowrap;
}
.indicator-trigger:hover {
  border-color: var(--border-strong);
}
.indicator-trigger__label {
  color: var(--text-secondary);
}
.indicator-trigger__val {
  color: var(--accent-hover);
  font-family: var(--font-mono);
  font-size: 12px;
  max-width: 96px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.indicator-trigger__chev {
  width: 14px;
  height: 14px;
  color: var(--text-disabled);
}

.indicator-menu {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.indicator-option {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border-radius: var(--r-sm);
  cursor: pointer;
  font-size: 13px;
  color: var(--text-primary);
  transition: background 0.12s ease;
}
.indicator-option:hover {
  background: var(--bg-surface-hover);
}

/* 顶栏快捷入口 */
.topbar-action {
  gap: 5px;
}
.topbar-action :deep(.el-icon) {
  width: 14px;
  height: 14px;
}
.panel-toggle {
  width: 28px;
  padding: 0;
}
.panel-toggle :deep(.el-icon) {
  width: 15px;
  height: 15px;
}

/* 图例 */
.legend-trigger {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border-radius: var(--r-md);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}
.legend-trigger:hover {
  background: var(--bg-surface-hover);
  color: var(--text-primary);
}
.legend-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-secondary);
  padding: 3px 0;
}
.legend-row .sw {
  width: 16px;
  height: 0;
  border-top: 2px solid var(--text-secondary);
}
.legend-row .sw--seg {
  border-color: var(--accent-base);
  border-top-width: 3px;
}
.legend-row .sw--box {
  width: 16px;
  height: 9px;
  border: 1px dashed var(--text-secondary);
  border-top: none;
  border-radius: 1px;
}
.legend-row .sw--box2 {
  border-color: var(--accent-base);
  border-style: solid;
  background: var(--accent-dim);
}
.legend-row .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.legend-row .dot--buy { background: var(--rise); }
.legend-row .dot--sell { background: var(--fall); }
.legend-title {
  font-size: 11px;
  color: var(--text-disabled);
  letter-spacing: 0.08em;
  margin-bottom: 4px;
}

/* 主体：左面板 + 主图 */
.kline-body {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: var(--sp-sm);
}

.kline-side {
  width: 320px;
  flex-shrink: 0;
  background: var(--bg-surface);
  border: 1px solid var(--border-base);
  border-radius: var(--r-md);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: width 0.24s cubic-bezier(0.22, 1, 0.36, 1), border-color 0.24s ease;
}
.kline-side.is-collapsed {
  width: 0;
  border-width: 0;
}

.kline-side__tabs {
  display: flex;
  gap: 2px;
  border-bottom: 1px solid var(--border-base);
  padding: 0 var(--sp-sm);
  flex-shrink: 0;
}
.kline-side__tabs .tab {
  flex: 1;
  text-align: center;
  padding: 11px 0;
}
.kline-side__tabs .tab::after {
  left: 30%;
  right: 30%;
}
.kline-side__body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

/* 主图区 */
.main-chart {
  flex: 1;
  min-width: 0;
  min-height: 320px;
  position: relative;
  overflow: hidden;
}
.chart__tag {
  position: absolute;
  top: 10px;
  right: 14px;
  left: auto;
  font-size: 12px;
  color: var(--text-secondary);
  font-family: var(--font-mono);
  letter-spacing: 0.04em;
  pointer-events: none;
  z-index: 5;
  white-space: nowrap;
  padding: 2px 8px;
  background: color-mix(in srgb, var(--bg-chart) 88%, transparent);
  border-radius: var(--r-sm);
}
</style>
