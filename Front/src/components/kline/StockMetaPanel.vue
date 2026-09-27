<template>
  <div class="mp-panel" v-loading="loading">
    <!-- 面板级空态：404 暂无元数据 / 加载失败 -->
    <EmptyState v-if="showEmpty" :description="emptyDesc" />

    <template v-else-if="meta">
      <!-- A 公司档案 -->
      <section class="mp-section">
        <div class="mp-section__title">公司档案</div>
        <div class="mp-field">
          <span class="mp-label">公司全称</span>
          <span class="mp-value">{{ fmtText(meta.full_name) }}</span>
        </div>
        <div class="mp-field">
          <span class="mp-label">英文名称</span>
          <span class="mp-value">{{ fmtText(meta.en_name) }}</span>
        </div>
        <div class="mp-field">
          <span class="mp-label">曾用简称</span>
          <span class="mp-value">{{ fmtText(meta.former_names) }}</span>
        </div>
        <div class="mp-field">
          <span class="mp-label">交易所</span>
          <span class="mp-value">{{ fmtText(meta.exchange) }}</span>
        </div>
        <div class="mp-field">
          <span class="mp-label">上市板块</span>
          <span class="mp-value">{{ fmtText(meta.board) }}</span>
        </div>
        <div class="mp-field">
          <span class="mp-label">上市日期</span>
          <span class="mp-value">{{ fmtDate(meta.ipo_date) }}</span>
        </div>
        <div class="mp-field">
          <span class="mp-label">成立日期</span>
          <span class="mp-value">{{ fmtDate(meta.found_date) }}</span>
        </div>
        <div class="mp-field">
          <span class="mp-label">法人代表</span>
          <span class="mp-value">{{ fmtText(meta.legal_person) }}</span>
        </div>
        <div class="mp-field">
          <span class="mp-label">注册资本</span>
          <span class="mp-value">{{ fmtText(meta.reg_capital) }}</span>
        </div>
      </section>

      <!-- D 行情快照（快照缺失时数值占位、不展示数据时间；现价在「标的」tab，此处去重不展示） -->
      <section class="mp-section">
        <div class="mp-section__title">行情快照</div>
        <div class="mp-field">
          <span class="mp-label">总市值</span>
          <span class="mp-value">{{ snapNum(meta.total_mv, '亿') }}</span>
        </div>
        <div class="mp-field">
          <span class="mp-label">流通市值</span>
          <span class="mp-value">{{ snapNum(meta.float_mv, '亿') }}</span>
        </div>
        <div class="mp-field">
          <span class="mp-label">市盈率(TTM)</span>
          <span class="mp-value">{{ snapNum(meta.pe_ttm) }}</span>
        </div>
        <div class="mp-field">
          <span class="mp-label">市净率</span>
          <span class="mp-value">{{ snapNum(meta.pb) }}</span>
        </div>
        <div class="mp-field">
          <span class="mp-label">换手率</span>
          <span class="mp-value">{{ snapNum(meta.turnover_rate, '%') }}</span>
        </div>
        <div class="mp-field">
          <span class="mp-label">主力净流入</span>
          <span class="mp-value">{{ snapNum(meta.main_net_inflow, '万') }}</span>
        </div>
        <div class="mp-field">
          <span class="mp-label">数据时间</span>
          <span class="mp-value mp-value--time">{{ hasSnapshot ? fmtDateTime(meta.snapshot_at) : EMPTY }}</span>
        </div>
      </section>

      <!-- C 经营概况（经营范围 / 公司简介 默认折叠） -->
      <section class="mp-section">
        <div class="mp-section__title">经营概况</div>
        <div class="mp-field">
          <span class="mp-label">主营业务</span>
          <span class="mp-value">{{ fmtText(meta.main_business) }}</span>
        </div>
        <div class="mp-field">
          <span class="mp-label">经营范围</span>
          <span class="mp-value">
            <template v-if="fmtText(meta.business_scope) !== EMPTY">
              <div class="mp-long">
                <div class="mp-long__text" :class="{ 'is-clamped': !expandedScope && scopeLong }">
                  {{ meta.business_scope }}
                </div>
                <button v-if="scopeLong" class="mp-long__toggle" type="button" @click="expandedScope = !expandedScope">
                  {{ expandedScope ? '收起' : '展开' }}
                </button>
              </div>
            </template>
            <template v-else>{{ EMPTY }}</template>
          </span>
        </div>
        <div class="mp-field">
          <span class="mp-label">公司简介</span>
          <span class="mp-value">
            <template v-if="fmtText(meta.intro) !== EMPTY">
              <div class="mp-long">
                <div class="mp-long__text" :class="{ 'is-clamped': !expandedIntro && introLong }">
                  {{ meta.intro }}
                </div>
                <button v-if="introLong" class="mp-long__toggle" type="button" @click="expandedIntro = !expandedIntro">
                  {{ expandedIntro ? '收起' : '展开' }}
                </button>
              </div>
            </template>
            <template v-else>{{ EMPTY }}</template>
          </span>
        </div>
      </section>

      <!-- B 联系方式（官网 / 邮箱 可点击） -->
      <section class="mp-section">
        <div class="mp-section__title">联系方式</div>
        <div class="mp-field">
          <span class="mp-label">官网</span>
          <span class="mp-value">
            <a
              v-if="websiteHref"
              class="mp-link"
              :href="websiteHref"
              target="_blank"
              rel="noopener noreferrer"
            >{{ meta.website.trim() }}</a>
            <template v-else>{{ EMPTY }}</template>
          </span>
        </div>
        <div class="mp-field">
          <span class="mp-label">邮箱</span>
          <span class="mp-value">
            <a v-if="emailHref" class="mp-link" :href="emailHref">{{ meta.email.trim() }}</a>
            <template v-else>{{ EMPTY }}</template>
          </span>
        </div>
        <div class="mp-field">
          <span class="mp-label">电话</span>
          <span class="mp-value">{{ fmtText(meta.phone) }}</span>
        </div>
        <div class="mp-field">
          <span class="mp-label">传真</span>
          <span class="mp-value">{{ fmtText(meta.fax) }}</span>
        </div>
        <div class="mp-field">
          <span class="mp-label">注册地址</span>
          <span class="mp-value">{{ fmtText(meta.reg_addr) }}</span>
        </div>
        <div class="mp-field">
          <span class="mp-label">办公地址</span>
          <span class="mp-value">{{ fmtText(meta.office_addr) }}</span>
        </div>
        <div class="mp-field">
          <span class="mp-label">邮编</span>
          <span class="mp-value">{{ fmtText(meta.postal_code) }}</span>
        </div>
      </section>

      <!-- 股东户数（近 1 年趋势，序列为空 → 区块级空态） -->
      <section class="mp-section">
        <div class="mp-section__title">股东户数</div>
        <div v-if="hasHolders" ref="holderChartEl" class="mp-holder-chart"></div>
        <div v-else class="mp-empty">暂无数据</div>
      </section>

      <!-- 用户标签/备注（只读，编辑属既有股票管理能力） -->
      <section class="mp-section">
        <div class="mp-section__title">用户标签/备注</div>
        <div class="mp-field">
          <span class="mp-label">标签</span>
          <span class="mp-value">
            <template v-if="meta.tags.length">
              <span v-for="t in meta.tags" :key="t" class="badge badge--info">{{ t }}</span>
            </template>
            <template v-else>{{ EMPTY }}</template>
          </span>
        </div>
        <div class="mp-field">
          <span class="mp-label">备注</span>
          <span class="mp-value">{{ fmtText(meta.notes) }}</span>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
/**
 * StockMetaPanel.vue — K 线页「股票信息」tab（kline-stock-metadata）
 * 分组顺序：A 公司档案 → D 行情快照 → C 经营概况 → B 联系方式 → 股东户数 → 用户标签/备注
 * 去重（与「标的」tab）：不展示名称/代码/现价/涨跌幅/行业 badge/industry_l1
 */
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { useEcharts } from '@/composables/useEcharts'
import { getStockMeta } from '@/api/modules/stock'
import type { StockMeta, StockHolderPoint } from '@/api/types'

const props = defineProps<{ code: string }>()

const EMPTY = '--'
const LONG_TEXT_MIN = 60

const meta = ref<StockMeta | null>(null)
const loading = ref(false)
const notFound = ref(false)
const loadFailed = ref(false)

const showEmpty = computed(() => !loading.value && (notFound.value || loadFailed.value))
const emptyDesc = computed(() => (notFound.value ? '暂无元数据' : '元数据加载失败'))

// ---- 加载 ----
let loadSeq = 0

async function loadMeta(): Promise<void> {
  const code = props.code
  const seq = ++loadSeq
  loading.value = true
  meta.value = null
  notFound.value = false
  loadFailed.value = false
  try {
    const data = await getStockMeta(code)
    if (seq !== loadSeq) return // 过期响应丢弃（后发覆盖）
    if (!data || !Array.isArray(data.holders)) {
      throw new Error(`[StockMetaPanel.loadMeta] meta 契约异常: code=${code}`)
    }
    meta.value = data
    renderHolderChart()
  } catch (e) {
    if (seq !== loadSeq) return
    const status = (e as { response?: { status?: number } })?.response?.status
    if (status === 404) {
      notFound.value = true
    } else {
      loadFailed.value = true
      console.warn('[StockMetaPanel.loadMeta] 元数据加载失败', {
        code,
        error: e instanceof Error ? e.message : String(e),
      })
    }
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

// ---- 空值 / 格式化 ----
function fmtText(v: string | null | undefined): string {
  if (v === null || v === undefined) return EMPTY
  const s = String(v).trim()
  return s === '' ? EMPTY : s
}

function fmtNum(v: number | null | undefined, unit = ''): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return EMPTY
  const s = v.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
  return unit ? `${s} ${unit}` : s
}

/** 快照缺失（snapshot_at 空）时整组数值占位 */
function snapNum(v: number | null | undefined, unit = ''): string {
  return hasSnapshot.value ? fmtNum(v, unit) : EMPTY
}

function fmtDate(v: string | null | undefined): string {
  const s = fmtText(v)
  if (s === EMPTY) return s
  return s.length >= 10 ? s.slice(0, 10) : s
}

function fmtDateTime(v: string | null | undefined): string {
  const s = (v ?? '').trim()
  if (!s) return EMPTY
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

const hasSnapshot = computed(() => !!((meta.value?.snapshot_at ?? '').trim()))
const hasHolders = computed(() => (meta.value?.holders.length ?? 0) > 0)

// ---- 官网 / 邮箱链接 ----
const websiteHref = computed(() => {
  const s = (meta.value?.website ?? '').trim()
  if (!s) return ''
  return /^https?:\/\//i.test(s) ? s : `https://${s}`
})
const emailHref = computed(() => {
  const s = (meta.value?.email ?? '').trim()
  return s ? `mailto:${s}` : ''
})

// ---- 长文本折叠 ----
const expandedScope = ref(false)
const expandedIntro = ref(false)
const scopeLong = computed(() => (meta.value?.business_scope ?? '').length >= LONG_TEXT_MIN)
const introLong = computed(() => (meta.value?.intro ?? '').length >= LONG_TEXT_MIN)

// ---- 股东户数趋势（ECharts，沿用 useEcharts 惯例）----
const holderChartEl = ref<HTMLElement | null>(null)
const { setOption, dispose } = useEcharts(holderChartEl)

function holderOption(pts: StockHolderPoint[]) {
  // 源单位原样展示（holder_num 为户数）
  return {
    backgroundColor: 'transparent',
    grid: { left: 6, right: 6, top: 14, bottom: 22, containLabel: true },
    tooltip: {
      trigger: 'axis' as const,
      // 以下颜色对应 design.css 令牌（canvas 无法读 CSS 变量）
      backgroundColor: '#161B22', // --bg-surface
      borderColor: '#2A303A', // --border-base
      textStyle: { color: '#E6E8EB', fontSize: 11 }, // --text-primary
      valueFormatter: (v: unknown) =>
        typeof v === 'number' ? v.toLocaleString('zh-CN') : String(v ?? ''),
    },
    xAxis: {
      type: 'category' as const,
      data: pts.map((p) => (p.stat_date.length >= 10 ? p.stat_date.slice(5) : p.stat_date)),
      boundaryGap: false,
      axisLine: { lineStyle: { color: '#2A303A' } },
      axisTick: { show: false },
      axisLabel: { color: '#565D66', fontSize: 10 }, // --text-disabled
    },
    yAxis: {
      type: 'value' as const,
      scale: true,
      splitLine: { lineStyle: { color: '#2A303A', type: 'dashed' as const } },
      axisLabel: {
        color: '#565D66',
        fontSize: 10,
        formatter: (v: number) =>
          Math.abs(v) >= 10000 ? `${(v / 10000).toFixed(1)}万` : String(v),
      },
    },
    series: [
      {
        name: '股东户数',
        type: 'line' as const,
        data: pts.map((p) => p.holder_num),
        smooth: true,
        symbol: 'circle',
        symbolSize: 4,
        lineStyle: { color: '#3B82F6', width: 1.5 }, // --accent-base
        itemStyle: { color: '#3B82F6' },
        areaStyle: { color: 'rgba(59, 130, 246, 0.12)' }, // --accent-glow
      },
    ],
  }
}

/**
 * 渲染户数趋势。切换股票会重建图表 DOM（v-if），
 * 先 dispose 旧实例再挂到当前 DOM，避免实例绑在已卸载节点上。
 */
async function renderHolderChart(): Promise<void> {
  await nextTick()
  const pts = meta.value?.holders ?? []
  dispose()
  if (!pts.length) return
  if (!holderChartEl.value) {
    console.warn('[StockMetaPanel.renderHolderChart] 图表容器未挂载，跳过渲染', {
      code: props.code,
      points: pts.length,
    })
    return
  }
  setOption(holderOption(pts))
}

// ---- 生命周期 ----
watch(() => props.code, loadMeta, { immediate: true })

onMounted(() => {
  // meta 早于挂载就绪时（同 code 重复进入）兜底补画
  if (meta.value?.holders.length) renderHolderChart()
})
</script>

<style scoped>
.mp-panel {
  padding: var(--sp-lg);
  display: flex;
  flex-direction: column;
  gap: var(--sp-lg);
  min-height: 0;
}

.mp-section {
  display: flex;
  flex-direction: column;
  gap: var(--sp-md);
}
.mp-section__title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  letter-spacing: 0.04em;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border-base);
}

.mp-field {
  display: flex;
  gap: var(--sp-md);
  align-items: baseline;
}
.mp-label {
  width: 80px;
  flex-shrink: 0;
  font-size: 11px;
  color: var(--text-disabled);
  line-height: 1.5;
}
.mp-value {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  color: var(--text-primary);
  line-height: 1.5;
  word-break: break-all;
}
.mp-value--time {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 12px;
}

.mp-link {
  color: var(--accent-hover);
  text-decoration: underline;
  text-underline-offset: 2px;
  cursor: pointer;
}
.mp-link:hover {
  color: var(--accent-base);
}

/* 长文本折叠（经营范围 / 公司简介） */
.mp-long {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.mp-long__text {
  white-space: pre-wrap;
}
.mp-long__text.is-clamped {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.mp-long__toggle {
  align-self: flex-start;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--accent-hover);
  font-size: 12px;
  cursor: pointer;
}
.mp-long__toggle:hover {
  color: var(--accent-base);
}

/* 股东户数趋势 */
.mp-holder-chart {
  width: 100%;
  height: 140px;
}
.mp-empty {
  font-size: 12px;
  color: var(--text-disabled);
  padding: var(--sp-md) 0;
}
</style>
