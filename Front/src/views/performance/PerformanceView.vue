<template>
  <div class="page-layout">
    <!-- 左侧菜单栏（唯一筛选入口，design D3/D9：五组筛选，分组树为二轮新增第五组） -->
    <Sidebar title="绩效">
      <TreeList
        group-label="方向"
        :items="directionItems"
        :active-key="activeDirection"
        @update:active-key="onDirectionChange"
      />
      <TreeList
        group-label="类型"
        :items="categoryItems"
        :active-key="activeCategory"
        @update:active-key="onCategoryChange"
      />
      <TreeList
        group-label="周期"
        :items="klTypeItems"
        :active-key="activeKl"
        @update:active-key="onKlChange"
      />
      <TreeList
        group-label="来源"
        :items="sourceItems"
        :active-key="activeSource"
        @update:active-key="onSourceChange"
      />
      <TreeList
        group-label="分组"
        :items="groupItems"
        :active-key="activeGroup"
        @update:active-key="onGroupChange"
      />
    </Sidebar>

    <!-- 右侧主面板 -->
    <div class="main-panel">
      <div class="perf-page">
        <!-- 顶部统计行（design D4：基于 filteredStats 联动） -->
        <div class="stat-row">
          <StatCard label="总样本" :value="String(totalSamples)" foot="全部买卖点记录" />
          <StatCard
            label="综合胜率"
            :value="overallWinRateStr"
            :trend="overallWinRate >= 50 ? 'up' : 'down'"
            foot="盈利样本占比"
          />
          <StatCard
            label="平均盈亏"
            :value="avgPnlStr"
            :trend="avgPnl >= 0 ? 'up' : 'down'"
            foot="所有样本均值"
          />
          <StatCard
            label="盈利比"
            :value="profitRatioStr"
            foot="平均盈利 / 平均亏损"
          />
        </div>

        <!-- 胜率柱状图（D4/D5：仅绘制有样本的类型，数据源 filteredStats） -->
        <Panel title="胜率对比" sub="按买卖点类型 · 横线为 50% 分界">
          <div class="chart chart--grid" style="height:220px">
            <WinRateChart :data="winRateChartData" />
          </div>
        </Panel>

        <!-- 月度趋势（design D5：胜率 + 平均盈亏双轴，按买卖点月份前端聚合） -->
        <Panel title="月度趋势" sub="胜率与平均盈亏 · 按买卖点月份聚合">
          <div class="chart chart--grid" style="height:260px">
            <MonthlyTrendChart :data="monthlyTrendData" />
          </div>
        </Panel>

        <!-- 绩效统计表 -->
        <Panel title="绩效统计" sub="按类型聚合" flush>
          <el-table
            v-loading="loading"
            :data="filteredStats"
            style="width: 100%"
            row-key="bsp_type"
            @row-click="onRowClick"
          >
            <el-table-column label="买卖点类型" width="120" align="center">
              <template #default="{ row }">
                <!-- 3a/3b 副语义（design D8）：中枢在一类之后/之前，回抽不进中枢 -->
                <!-- 聚合行不含方向维度（枚举混合买卖样本），badge 用中性样式，方向看侧栏/样本行 -->
                <el-tooltip
                  v-if="row.bsp_type === '3a' || row.bsp_type === '3b'"
                  :content="row.bsp_type === '3a'
                    ? '中枢在一类之后，回抽不进中枢'
                    : '中枢在一类之前，回抽不进中枢'"
                  placement="top"
                >
                  <span class="badge badge--default">
                    {{ displayLabel(row.bsp_type) }}
                  </span>
                </el-tooltip>
                <span v-else class="badge badge--default">
                  {{ displayLabel(row.bsp_type) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="周期" width="100" align="center">
              <template #default="{ row }">
                <span class="num">{{ klLabel(row.kl_type) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="样本数" width="130" align="right" class-name="col-num">
              <template #default="{ row }">
                <span class="num">{{ row.samples }}</span>
                <!-- 样本不足标记（design D5：样本数 < 5 统计意义有限） -->
                <el-tooltip
                  v-if="row.samples < SAMPLE_INSUFFICIENT_THRESHOLD"
                  content="样本数不足 5，统计意义有限"
                  placement="top"
                >
                  <span class="badge badge--warning sample-badge">样本不足</span>
                </el-tooltip>
              </template>
            </el-table-column>
            <el-table-column label="胜率%" width="100" align="right" class-name="col-num">
              <template #default="{ row }">
                <span class="num" :class="row.win_rate >= 50 ? 'text-rise' : 'text-fall'">
                  {{ row.win_rate.toFixed(1) }}%
                </span>
              </template>
            </el-table-column>
            <el-table-column label="平均盈亏%" width="120" align="right" class-name="col-num">
              <template #default="{ row }">
                <span class="num" :class="row.avg_pnl >= 0 ? 'text-rise' : 'text-fall'">
                  {{ row.avg_pnl >= 0 ? '+' : '' }}{{ row.avg_pnl.toFixed(2) }}%
                </span>
              </template>
            </el-table-column>
            <el-table-column label="盈亏比" width="100" align="right" class-name="col-num">
              <template #default="{ row }">
                <span class="num">{{ row.profit_ratio.toFixed(2) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="期望值%" width="110" align="right" class-name="col-num">
              <template #default="{ row }">
                <span class="num" :class="row.expectancy >= 0 ? 'text-rise' : 'text-fall'">
                  {{ row.expectancy >= 0 ? '+' : '' }}{{ row.expectancy.toFixed(2) }}%
                </span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100" align="right">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click.stop="onDrillDown(row)">
                  下钻
                </el-button>
              </template>
            </el-table-column>
            <template #empty>
              <EmptyState description="先在监控页积累结算样本" />
            </template>
          </el-table>
        </Panel>
      </div>
    </div>

    <!-- 样本明细抽屉（design D5：明细表 + 归因摘要 + 双击跳 K 线） -->
    <el-drawer
      v-model="drawerVisible"
      title="样本明细"
      direction="rtl"
      size="720px"
    >
      <template v-if="drawerBspType">
        <div class="cell-stock" style="margin-bottom:16px">
          <span class="nm" style="font-size:16px;font-weight:600">
            {{ drawerBspLabel }} 样本明细
          </span>
          <span class="cd">
            样本数 {{ drawerSamples.length }} ·
            胜率 {{ drawerWinRate.toFixed(1) }}% ·
            平均盈亏 {{ drawerAvgPnl >= 0 ? '+' : '' }}{{ drawerAvgPnl.toFixed(2) }}% ·
            期望值 {{ drawerExpectancy >= 0 ? '+' : '' }}{{ drawerExpectancy.toFixed(2) }}%
          </span>
        </div>

        <el-table
          v-loading="drawerLoading"
          :data="drawerSamples"
          style="width: 100%"
          size="small"
          @row-dblclick="onSampleDblClick"
        >
          <el-table-column label="标的" width="110">
            <template #default="{ row }">
              <div class="cell-stock">
                <span class="nm">{{ row.name }}</span>
                <span class="cd mono">{{ row.code }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="周期" width="80" align="center">
            <template #default="{ row }">
              <span class="num">{{ klLabel(row.kl_type) }}</span>
            </template>
          </el-table-column>
          <!-- 来源列（三分支，语义同 MonitorView 来源列） -->
          <el-table-column label="来源" width="120" align="center">
            <template #default="{ row }">
              <span
                v-if="row.source_type === 'strategy' && row.strategy_label"
                class="src-tag"
                :title="row.strategy_label"
              >
                {{ row.strategy_label }}
              </span>
              <span v-else-if="row.source_type === 'watchlist'" class="src-tag">自选</span>
              <span v-else class="src-chan">缠论</span>
            </template>
          </el-table-column>
          <el-table-column label="买卖点日期" width="110" align="center">
            <template #default="{ row }">
              <span class="num">{{ fmtDate(row.bsp_date) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="持有天数" width="90" align="right" class-name="col-num">
            <template #default="{ row }">
              <span class="num">{{ row.hold_days }}</span>
            </template>
          </el-table-column>
          <el-table-column label="买卖点价" width="90" align="right" class-name="col-num">
            <template #default="{ row }">
              <span class="num">{{ row.bsp_price.toFixed(2) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="结算价" width="90" align="right" class-name="col-num">
            <template #default="{ row }">
              <span class="num">{{ row.end_price.toFixed(2) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="收益率%" width="90" align="right" class-name="col-num">
            <template #default="{ row }">
              <span class="num" :class="row.profit >= 0 ? 'text-rise' : 'text-fall'">
                {{ row.profit >= 0 ? '+' : '' }}{{ row.profit.toFixed(2) }}%
              </span>
            </template>
          </el-table-column>
          <!-- 归因摘要（design D5：截断 + tooltip 全文，空显示 '-'） -->
          <el-table-column label="归因摘要" min-width="140">
            <template #default="{ row }">
              <el-tooltip
                v-if="row.attribution"
                :content="row.attribution"
                placement="top"
                :show-after="200"
              >
                <span class="attr-text">{{ truncate(row.attribution, 20) }}</span>
              </el-tooltip>
              <span v-else class="src-chan">-</span>
            </template>
          </el-table-column>
          <template #empty>
            <EmptyState description="暂无样本" />
          </template>
        </el-table>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import Sidebar from '@/components/layout/Sidebar.vue'
import TreeList from '@/components/ui/TreeList.vue'
import Panel from '@/components/ui/Panel.vue'
import StatCard from '@/components/ui/StatCard.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import WinRateChart from '@/components/charts/WinRateChart.vue'
import MonthlyTrendChart from '@/components/charts/MonthlyTrendChart.vue'
import { getPerformanceStats, getPerformanceSamples } from '@/api/modules/performance'
import { getMonitorSources, getMonitorGroups, type MonitorSource, type MonitorGroup } from '@/api/modules/monitor'
import type { PerformanceStat, PerformanceSample } from '@/api/types'
import { bspLabel } from '@/utils/bsp'

// ---- 数据 ----
const loading = ref(false)
const stats = ref<PerformanceStat[]>([])
const samples = ref<PerformanceSample[]>([])

// ---- 筛选（design D3/D9：侧栏唯一入口，五组：方向/类型/周期/来源/分组） ----
const activeDirection = ref('all')
const activeCategory = ref('all')
const activeKl = ref('all')
const activeSource = ref('all')
const activeGroup = ref('all')

// ---- 侧栏词表 ----
const directionItems = [
  { key: 'all', label: '全部方向' },
  { key: 'buy', label: '买点绩效' },
  { key: 'sell', label: '卖点绩效' },
]
// 类型词表（design D8：6 枚举精确匹配，不按 startsWith 粗分——
// '1p' 是无中枢的盘整背驰而非第一类，'2s' 是类二而非第二类，
// 信号强度差异大的枚举混算会污染「哪类买卖点靠谱」的复盘结论）
const categoryItems = [
  { key: 'all', label: '全部类型' },
  { key: '1', label: '第一类 (1B/1S)' },
  { key: '1p', label: '盘整背驰 (PZ-B/PZ-S)' },
  { key: '2', label: '第二类 (2B/2S)' },
  { key: '2s', label: '类二 (L2B/L2S)' },
  { key: '3a', label: '三类a (中枢后回抽)' },
  { key: '3b', label: '三类b (中枢前回抽)' },
]
// 周期词表（design D4 口径：全部/30m/60m/D/W/M，与买卖点页一致）
const klTypeItems = [
  { key: 'all', label: '全部周期' },
  { key: '30m', label: '30分钟' },
  { key: '60m', label: '60分钟' },
  { key: 'D', label: '日线' },
  { key: 'W', label: '周线' },
  { key: 'M', label: '月线' },
]

// 来源树（design D3/D4：字典来自 getMonitorSources，失败静默不影响列表）
const monitorSources = ref<MonitorSource[]>([])
const sourceItems = computed(() => [
  { key: 'all', label: '全部来源' },
  ...monitorSources.value.map((s) => ({ key: s.value, label: s.label })),
])

async function loadSources() {
  try {
    monitorSources.value = await getMonitorSources()
  } catch {
    // 来源字典加载失败时静默：树只保留「全部来源」，统计列表不受影响
  }
}

// 分组树（design D9：字典来自 getMonitorGroups，失败静默不影响列表；
// 选项 = 全部/未分组('ungrouped' 哨兵)/各分组，前端不硬编码分组名）
const monitorGroups = ref<MonitorGroup[]>([])
const groupItems = computed(() => [
  { key: 'all', label: '全部分组' },
  { key: 'ungrouped', label: '未分组' },
  ...monitorGroups.value.map((g) => ({ key: String(g.id), label: g.name })),
])

async function loadGroups() {
  try {
    monitorGroups.value = await getMonitorGroups()
  } catch {
    // 分组字典加载失败时静默：树只保留「全部分组/未分组」（与来源树同款处理）
  }
}

// ---- 筛选选中值 → 请求参数拆解（来源 + 分组合并为一个参数对象） ----
// 来源：'strategy:<id>' → source + instance_id；'chan'/'watchlist' → source 原值
// 分组：'ungrouped'/'<id>' → group_id 原值透传（后端哨兵语义），'all' → 不传
function filterParams(): { source?: string; instance_id?: number; group_id?: string } {
  const p: { source?: string; instance_id?: number; group_id?: string } = {}
  const v = activeSource.value
  if (v && v !== 'all') {
    if (v.startsWith('strategy:')) {
      const id = Number(v.slice('strategy:'.length))
      if (Number.isInteger(id) && id > 0) p.source = 'strategy'
      p.instance_id = id
    } else {
      p.source = v
    }
  }
  const g = activeGroup.value
  if (g && g !== 'all') p.group_id = g
  return p
}

// ---- 筛选变化 → 重新请求（stats/samples 均带来源/分组参数重拉，语义与真后端过滤一致） ----
function onDirectionChange(k: string) {
  activeDirection.value = k
}
function onCategoryChange(k: string) {
  activeCategory.value = k
}
function onKlChange(k: string) {
  activeKl.value = k
}
function onSourceChange(k: string) {
  activeSource.value = k
  loadAll()
}
function onGroupChange(k: string) {
  activeGroup.value = k
  loadAll()
}

// ---- 买卖点类型 ----
const SAMPLE_INSUFFICIENT_THRESHOLD = 5

// 方向判定：bsp_type 为原始枚举（'1'/'1p'/'2'/'2s'/'3a'/'3b'）不含 B/S 信息，
// 样本行方向以 direction 字段为准（真后端 completed 行契约）
function isBuy(bspType: string) {
  return bspType.includes('B')
}

function isSampleBuy(s: PerformanceSample) {
  return s.direction === 'buy'
}

// 展示名（design D8）：'3a'/'3b' 经 bspLabel 均映射 3B/3S（撞名），
// 加枚举尾缀区分；其余类型直接走 bspLabel
function displayLabel(bspType: string): string {
  const base = bspLabel(bspType, isBuy(bspType))
  if (bspType === '3a') return `${base}-a`
  if (bspType === '3b') return `${base}-b`
  return base
}

// ---- 统计表过滤（方向/类型/周期消费于本地，来源/分组已随请求过滤） ----
const filteredStats = computed(() => {
  let list = stats.value
  if (activeDirection.value === 'buy') {
    list = list.filter((r) => isBuy(r.bsp_type))
  } else if (activeDirection.value === 'sell') {
    list = list.filter((r) => !isBuy(r.bsp_type))
  }
  if (activeCategory.value !== 'all') {
    // 6 枚举精确匹配（design D8：不按 startsWith 粗分，避免 1p 混入第一类、2s 混入第二类）
    list = list.filter((r) => r.bsp_type === activeCategory.value)
  }
  if (activeKl.value !== 'all') {
    list = list.filter((r) => r.kl_type === activeKl.value)
  }
  return list
})

// ---- 胜率图数据（design D5：仅绘制有样本的类型，删除缺补 0 逻辑） ----
const winRateChartData = computed(() => {
  return filteredStats.value.map((r) => ({
    // name 用 displayLabel 映射后的展示名（3a/3b 加尾缀区分，无映射的原始枚举原样展示）
    name: displayLabel(r.bsp_type),
    winRate: r.win_rate,
  }))
})

// ---- 顶部统计（design D4：数据源改为 filteredStats） ----
const totalSamples = computed(() => {
  return filteredStats.value.reduce((acc, r) => acc + r.samples, 0)
})

const overallWinRate = computed(() => {
  const list = filteredStats.value
  const total = list.reduce((acc, r) => acc + r.samples, 0)
  if (total === 0) return 0
  const weighted = list.reduce((acc, r) => acc + r.samples * r.win_rate, 0)
  return +(weighted / total).toFixed(1)
})
const overallWinRateStr = computed(() => `${overallWinRate.value.toFixed(1)}%`)

const avgPnl = computed(() => {
  const list = filteredStats.value
  const total = list.reduce((acc, r) => acc + r.samples, 0)
  if (total === 0) return 0
  const weighted = list.reduce((acc, r) => acc + r.samples * r.avg_pnl, 0)
  return +(weighted / total).toFixed(2)
})
const avgPnlStr = computed(() => `${avgPnl.value >= 0 ? '+' : ''}${avgPnl.value.toFixed(2)}%`)

const profitRatio = computed(() => {
  const list = filteredStats.value
  if (list.length === 0) return 0
  const sum = list.reduce((acc, r) => acc + r.profit_ratio, 0)
  return +(sum / list.length).toFixed(2)
})
const profitRatioStr = computed(() => profitRatio.value.toFixed(2))

// ---- 筛选后样本（月度趋势数据源，与 filteredStats 同口径：方向/类型/周期本地过滤 + 来源/分组请求过滤） ----
const filteredSamples = computed(() => {
  let list = samples.value
  if (activeDirection.value === 'buy') {
    list = list.filter((s) => isSampleBuy(s))
  } else if (activeDirection.value === 'sell') {
    list = list.filter((s) => !isSampleBuy(s))
  }
  if (activeCategory.value !== 'all') {
    list = list.filter((s) => s.bsp_type === activeCategory.value)
  }
  if (activeKl.value !== 'all') {
    list = list.filter((s) => s.kl_type === activeKl.value)
  }
  return list
})

// ---- 月度趋势（design D5：按 bsp_date 月度前端聚合，样本量级小） ----
const monthlyTrendData = computed(() => {
  const groups = new Map<string, number[]>()
  for (const s of filteredSamples.value) {
    const d = new Date(s.bsp_date)
    const month = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
    const g = groups.get(month) ?? []
    g.push(s.profit)
    groups.set(month, g)
  }
  const rows: { month: string; winRate: number; avgPnl: number }[] = []
  groups.forEach((pnls, month) => {
    const wins = pnls.filter((p) => p > 0).length
    rows.push({
      month,
      winRate: +((wins / pnls.length) * 100).toFixed(1),
      avgPnl: +(pnls.reduce((a, b) => a + b, 0) / pnls.length).toFixed(2),
    })
  })
  // 按月份升序排列（时间轴从左到右）
  return rows.sort((a, b) => a.month.localeCompare(b.month))
})

// ---- 抽屉 ----
const drawerVisible = ref(false)
const drawerBspType = ref('')
const drawerSamples = ref<PerformanceSample[]>([])
const drawerLoading = ref(false)

const drawerBspLabel = computed(() => {
  // displayLabel：3a/3b 加枚举尾缀（design D8），找不到统计行时原始枚举兜底
  const row = stats.value.find((r) => r.bsp_type === drawerBspType.value)
  return row ? displayLabel(row.bsp_type) : drawerBspType.value
})

const drawerWinRate = computed(() => {
  const list = drawerSamples.value
  if (list.length === 0) return 0
  const wins = list.filter((s) => s.profit > 0).length
  return +((wins / list.length) * 100).toFixed(1)
})
const drawerAvgPnl = computed(() => {
  const list = drawerSamples.value
  if (list.length === 0) return 0
  const sum = list.reduce((acc, s) => acc + s.profit, 0)
  return +(sum / list.length).toFixed(2)
})
const drawerExpectancy = computed(() => {
  // 期望值 = 胜率(小数)×平均盈利 − 败率×|平均亏损|（与后端口径一致）
  const list = drawerSamples.value
  if (list.length === 0) return 0
  const wins = list.filter((s) => s.profit > 0)
  const losses = list.filter((s) => s.profit <= 0)
  const winRateDec = wins.length / list.length
  const avgWin = wins.length ? wins.reduce((a, s) => a + s.profit, 0) / wins.length : 0
  const avgLoss = losses.length
    ? Math.abs(losses.reduce((a, s) => a + s.profit, 0) / losses.length)
    : 0
  return +(winRateDec * avgWin - (1 - winRateDec) * avgLoss).toFixed(2)
})

async function onDrillDown(row: PerformanceStat) {
  drawerBspType.value = row.bsp_type
  drawerVisible.value = true
  drawerLoading.value = true
  try {
    // 抽屉带当前筛选参数（来源/分组请求过滤 + 类型/周期同分组下钻）
    const { source, instance_id, group_id } = filterParams()
    const list = await getPerformanceSamples(row.bsp_type, row.kl_type, source, instance_id, group_id)
    drawerSamples.value = list
  } catch {
    drawerSamples.value = []
  } finally {
    drawerLoading.value = false
  }
}

function onRowClick(row: PerformanceStat) {
  onDrillDown(row)
}

// ---- 双击样本行跳 K 线（design D5：period 映射对齐 monitor D12 的 KL_TO_KLINE_PERIOD） ----
const KL_TO_KLINE_PERIOD: Record<string, string> = {
  D: '1d',
  W: '1w',
  M: '1M',
  '30m': '30m',
  '60m': '60m',
}
const router = useRouter()

function onSampleDblClick(row: PerformanceSample) {
  const q: { code: string; period?: string } = { code: row.code }
  const period = row.kl_type ? KL_TO_KLINE_PERIOD[row.kl_type] : undefined
  if (period) q.period = period
  router.push({ name: 'kline', query: q })
}

// ---- 工具 ----
function fmtDate(ts: number) {
  const d = new Date(ts)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function klLabel(k: string) {
  const m: Record<string, string> = { '30m': '30分钟', '60m': '60分钟', D: '日线', W: '周线', M: '月线' }
  return m[k] || k
}

function truncate(text: string, max: number) {
  return text.length > max ? `${text.slice(0, max)}…` : text
}

// ---- 加载（stats/samples 均带来源/分组参数，Promise.all 模式） ----
async function loadAll() {
  loading.value = true
  try {
    const { source, instance_id, group_id } = filterParams()
    const [st, sp] = await Promise.all([
      getPerformanceStats(source, instance_id, group_id),
      getPerformanceSamples(undefined, undefined, source, instance_id, group_id),
    ])
    stats.value = st
    samples.value = sp
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadSources()
  loadGroups()
  loadAll()
})
</script>

<style scoped>
.perf-page {
  display: flex;
  flex-direction: column;
  gap: var(--sp-lg);
  flex: 1;
}
.stat-row {
  display: flex;
  gap: var(--sp-lg);
}
.stat-row > * {
  flex: 1;
}
.cell-stock {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}
.cell-stock .nm {
  color: var(--text-primary);
  font-size: 13px;
}
.cell-stock .cd {
  color: var(--text-disabled);
  font-size: 11px;
}
/* 样本不足 badge（design D5）：数字后内联，紧凑排布 */
.sample-badge {
  margin-left: 6px;
  font-size: 10px;
  line-height: 16px;
  padding: 0 4px;
  cursor: help;
}
/* 来源标签（语义同 MonitorView 来源列的 src-tag/src-chan，scope 内自带样式） */
.src-tag {
  display: inline-block;
  max-width: 100%;
  padding: 1px 6px;
  font-size: 10px;
  line-height: 16px;
  border-radius: var(--r-full);
  background: var(--accent-dim);
  color: var(--accent-hover);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.src-chan {
  font-size: 12px;
  color: var(--text-disabled);
}
/* 归因摘要截断文本 */
.attr-text {
  font-size: 12px;
  color: var(--text-secondary);
  cursor: help;
}
</style>
