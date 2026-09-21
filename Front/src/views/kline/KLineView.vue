<template>
  <div class="kline-page">
    <!-- 顶栏工具栏 — design.md D9 -->
    <header class="topbar reveal">
      <!-- 折叠左侧面板（置于最左侧） -->
      <button class="btn btn--ghost btn--sm panel-toggle" :title="panelCollapsed ? '展开面板' : '折叠面板'" @click="panelCollapsed = !panelCollapsed">
        <el-icon><Expand v-if="panelCollapsed" /><Fold v-else /></el-icon>
      </button>

      <el-input
        v-model="codeInput"
        class="code-field"
        placeholder="股票代码 如 sz.000001"
        :prefix-icon="SearchIcon"
        size="default"
        @keyup.enter="handleSearch"
      />
      <el-button type="primary" size="default" :loading="loading" @click="handleSearch">
        搜索
      </el-button>

      <el-select v-model="period" size="default" class="period-select" @change="handleSearch">
        <el-option label="1分钟" value="1m" />
        <el-option label="5分钟" value="5m" />
        <el-option label="1小时" value="1h" />
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
          <button class="tab" :class="{ 'is-active': activeTab === 'qa' }" @click="activeTab = 'qa'">问答</button>
        </div>
        <div class="kline-side__body">
          <StockPanel v-if="activeTab === 'stock'" :code="code" />
          <QaPanel v-else />
        </div>
      </aside>

      <section class="chart chart--grid main-chart reveal reveal--1">
        <div class="chart__tag">{{ code.toUpperCase() }} · {{ periodLabel }} · 前复权</div>
        <KLineChart ref="chartComp" :result="result" :code="code" :period="period" />
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * KLineView.vue — K 线分析页
 * design.md D1：可折叠左侧面板（标的 / 问答）+ 主图
 * design.md D6：切换代码/周期触发命令式重载
 */
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Search, Star, ChatDotRound, Fold, Expand, ArrowDown } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import KLineChart from '@/components/charts/KLineChart.vue'
import StockPanel from '@/components/kline/StockPanel.vue'
import QaPanel from '@/components/kline/QaPanel.vue'
import { getKLine } from '@/api/modules/kline'
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

// 左侧面板状态
const panelCollapsed = ref(false)
const activeTab = ref<'stock' | 'qa'>('stock')

const chartComp = ref<InstanceType<typeof KLineChart> | null>(null)

const periodLabel = computed(() => {
  const m: Record<string, string> = {
    '1m': '1分钟', '5m': '5分钟', '1h': '1小时', '1d': '日线', '1w': '周线', '1M': '月线',
  }
  return m[period.value] ?? period.value
})

/** 快捷入口：切到指定 Tab 并展开面板 */
function jumpTo(tab: 'stock' | 'qa'): void {
  activeTab.value = tab
  panelCollapsed.value = false
}

/** 加载 K 线 + 缠论数据 */
async function load(): Promise<void> {
  loading.value = true
  try {
    const res = await getKLine(code.value, period.value)
    result.value = res
  } catch (e) {
    ElMessage.error('加载 K 线数据失败')
    result.value = null
  } finally {
    loading.value = false
  }
}

/** 搜索 — 切换代码/周期触发重载 */
function handleSearch(): void {
  const c = codeInput.value.trim()
  if (!c) {
    ElMessage.warning('请输入股票代码')
    return
  }
  code.value = c
  load()
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
  // 从 URL query 参数读取股票代码（从其他页面跳转）
  const qCode = route.query.code
  if (qCode && typeof qCode === 'string' && qCode.trim()) {
    code.value = qCode.trim()
    codeInput.value = code.value
  }
  load()
})

// 周期切换触发重载
watch(period, () => load())

// 数据加载后同步副图指标
watch(result, () => {
  if (result.value) {
    chartComp.value?.syncSubIndicators(subIndicators.value)
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
  background: rgba(59, 130, 246, 0.12);
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
