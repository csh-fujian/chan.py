<template>
  <div class="page-layout">
    <!-- 左侧菜单栏：随顶部 tab 切换分组（design D6 单页整合，不走路由） -->
    <Sidebar title="监控">
      <TreeList
        group-label="状态"
        :items="statusItems"
        :active-key="tabMode"
        @update:active-key="onTabChange"
      />
      <!-- 监控中 tab：盈利 / 周期过滤 -->
      <template v-if="tabMode === 'monitoring'">
        <TreeList
          group-label="盈利"
          :items="profitItems"
          :active-key="activeProfit"
          @update:active-key="onProfitChange"
        />
        <TreeList
          group-label="周期"
          :items="klTypeItems"
          :active-key="activeKl"
          @update:active-key="onKlChange"
        />
      </template>
      <!-- 已完成 tab：归因 / 失败原因过滤 -->
      <template v-else>
        <TreeList
          group-label="归因"
          :items="attrItems"
          :active-key="activeAttr"
          @update:active-key="onAttrChange"
        />
        <TreeList
          group-label="失败原因"
          :items="reasonItems"
          :active-key="activeReason"
          @update:active-key="onReasonChange"
        />
      </template>
    </Sidebar>

    <!-- 右侧主面板 -->
    <div class="main-panel">
      <div class="monitor-page">
        <!-- 顶部 tab（design D6）：整体切换内容区，不走路由跳转 -->
        <div class="tabbar reveal">
          <el-radio-group v-model="tabMode" @change="onTabChange">
            <el-radio-button value="monitoring">监控中</el-radio-button>
            <el-radio-button value="completed">已完成</el-radio-button>
          </el-radio-group>
        </div>

        <!-- ==================== 监控中 tab ==================== -->
        <template v-if="tabMode === 'monitoring'">
          <!-- 汇总卡（design D11：总体盈利=收益率求和；新增当前胜率/涨幅最大） -->
          <div class="stat-row">
            <StatCard
              label="总体盈利（%）"
              :value="totalProfitStr"
              :foot="`${monitorList.length} 只监控中 · 收益率求和`"
              :trend="totalProfit >= 0 ? 'up' : 'down'"
              accent
            />
            <StatCard
              label="当前胜率"
              :value="winRateStr"
              :trend="winRate >= 50 ? 'up' : 'down'"
              :foot="`${winCount} 胜 / ${winTotal} 只参与统计`"
            />
            <StatCard
              label="涨幅最大"
              :value="maxChangeStr"
              :trend="(maxChange?.change_pct ?? 0) >= 0 ? 'up' : 'down'"
              :foot="maxChange ? `${maxChange.name} (${maxChange.code}) · ${klLabel(maxChange.kl_type)}` : '暂无数据'"
            />
            <StatCard
              label="监控中数量"
              :value="String(monitorList.length)"
              foot="实时跟踪"
            />
            <StatCard
              label="累计完成"
              :value="String(completedCount)"
              foot="历史已结算监控"
            />
          </div>

          <!-- 搜索（design D7：对齐 K 线页 el-autocomplete 远程候选 + Enter 精确查询 + 查询/重置按钮） + 表格 -->
          <div class="toolbar reveal reveal--4">
            <div class="code-field" @keydown.capture="mSearch.onKeydown">
              <el-autocomplete
                :ref="(i: any) => (mSearch.acRef.value = i)"
                v-model="mSearch.input.value"
                :fetch-suggestions="mSearch.query"
                :trigger-on-focus="false"
                :debounce="0"
                placeholder="代码/名称/拼音 如 sz.000001"
                :prefix-icon="Search"
                clearable
                @input="mSearch.onInput"
                @select="mSearch.onSelect"
                @clear="mSearch.onClear"
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
            <el-button type="primary" @click="mSearch.apply">查询</el-button>
            <el-button @click="mSearch.reset">重置</el-button>
          </div>

          <Panel flush>
            <el-table
              v-loading="loading"
              :data="pagedList"
              style="width: 100%"
              row-key="id"
              @row-dblclick="onViewDetail"
            >
              <el-table-column label="名称 / 编码" min-width="150">
                <template #default="{ row }">
                  <div
                    class="cell-stock cell-stock--link"
                    title="双击跳转 K 线"
                    @dblclick="onGoKline(row)"
                  >
                    <span class="nm">{{ row.name }}</span>
                    <span class="cd mono">{{ row.code }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="行业" min-width="120">
                <template #default="{ row }">
                  <IndustryBadges :industries="row.industries" />
                </template>
              </el-table-column>
              <!-- 买卖点类型（design D9：原「买卖点」+「方向」两列合并，展示 bsp_type 值，B 系红 / S 系绿） -->
              <el-table-column label="买卖点类型" width="100" align="center">
                <template #default="{ row }">
                  <span class="badge" :class="row.direction === 'buy' ? 'badge--rise' : 'badge--fall'">
                    {{ bspLabel(row.bsp_type, row.direction === 'buy') }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="买卖点价格" width="110" align="right" class-name="col-num">
                <template #default="{ row }">
                  <span class="num">{{ fmtPrice(row.bsp_price) }}</span>
                </template>
              </el-table-column>
              <!-- 买卖点时间（design D8）：收益计算起点，ms → YYYY-MM-DD HH:mm -->
              <el-table-column label="买卖点时间" width="140" align="center">
                <template #default="{ row }">
                  <span class="num">{{ fmtDateTime(row.bsp_date) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="当前价" width="110" align="right" class-name="col-num">
                <template #default="{ row }">
                  <span class="num">{{ fmtPrice(row.current_price) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="涨跌幅" width="100" align="right" class-name="col-num">
                <template #default="{ row }">
                  <ChangeBadge :value="row.change_pct" />
                </template>
              </el-table-column>
              <!-- 收益率（design D8）：current_pnl_pct 自买卖点起累计涨跌，红涨绿跌 -->
              <el-table-column label="收益率" width="100" align="right" class-name="col-num">
                <template #default="{ row }">
                  <ChangeBadge v-if="row.current_pnl_pct != null" :value="row.current_pnl_pct" />
                  <span v-else class="num">--</span>
                </template>
              </el-table-column>
              <el-table-column label="级别" width="80" align="center">
                <template #default="{ row }">
                  <span class="num">{{ klLabel(row.kl_type) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="140" align="right" fixed="right">
                <template #default="{ row }">
                  <el-button
                    v-if="row.status === 'monitoring'"
                    link
                    type="danger"
                    size="small"
                    :loading="endingId === row.id"
                    @click="onEnd(row)"
                  >
                    手动结束
                  </el-button>
                  <el-button link type="primary" size="small" @click="onViewDetail(row)">
                    查看详情
                  </el-button>
                </template>
              </el-table-column>
              <template #empty>
                <EmptyState description="暂无监控记录" />
              </template>
            </el-table>

            <div v-if="filteredList.length > pageSize" class="pager-wrap">
              <el-pagination
                v-model:current-page="page"
                :page-size="pageSize"
                :total="filteredList.length"
                layout="prev, pager, next, total"
                background
                small
              />
            </div>
          </Panel>

          <!-- 盈利走势图（design D10：移至列表下方；D8：由监控中列表各标的收益率前端聚合，红涨绿跌分段着色） -->
          <Panel title="盈利走势" sub="监控中标的收益率均值 · 按买卖点时间聚合">
            <template #head>
              <SegControl v-model="profitSeg" :items="segItems" />
            </template>
            <div class="chart chart--grid" style="height:280px">
              <template v-if="profitSeg === 'summary'">
                <ProfitChart :series="summarySeries" split-color />
              </template>
              <template v-else>
                <div class="single-stock-toolbar">
                  <el-select
                    v-model="singleStockId"
                    placeholder="选择标的"
                    filterable
                    size="small"
                    style="width: 200px"
                  >
                    <el-option
                      v-for="r in monitorList"
                      :key="r.id"
                      :label="`${r.name} (${r.code})`"
                      :value="r.id"
                    />
                  </el-select>
                </div>
                <ProfitChart v-if="singleStockId" :series="singleStockSeries" split-color />
                <EmptyState v-else description="请选择标的查看单只走势" />
              </template>
            </div>
          </Panel>
        </template>

        <!-- ==================== 已完成 tab（原 CompletedView 并入，design D6） ==================== -->
        <template v-else>
          <!-- 顶部统计卡片行 -->
          <div class="stat-row">
            <StatCard label="完成总数" :value="String(completedList.length)" foot="历史已结算" />
            <StatCard
              label="胜率"
              :value="cWinRateStr"
              :trend="cWinRate >= 50 ? 'up' : 'down'"
              foot="盈利占比"
            />
            <StatCard
              label="平均盈利"
              :value="avgProfitStr"
              :trend="avgProfit >= 0 ? 'up' : 'down'"
              foot="所有完成标的"
            />
            <StatCard
              label="盈利比"
              :value="profitRatioStr"
              foot="平均盈利 / 平均亏损"
            />
          </div>

          <!-- 操作工具条（D7 增补：已完成搜索同款 el-autocomplete + 查询/重置） -->
          <div class="toolbar reveal reveal--1">
            <div class="code-field" @keydown.capture="cSearch.onKeydown">
              <el-autocomplete
                :ref="(i: any) => (cSearch.acRef.value = i)"
                v-model="cSearch.input.value"
                :fetch-suggestions="cSearch.query"
                :trigger-on-focus="false"
                :debounce="0"
                placeholder="代码/名称/拼音 如 sz.000001"
                :prefix-icon="Search"
                clearable
                @input="cSearch.onInput"
                @select="cSearch.onSelect"
                @clear="cSearch.onClear"
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
            <el-button type="primary" @click="cSearch.apply">查询</el-button>
            <el-button @click="cSearch.reset">重置</el-button>
            <span class="spacer"></span>
            <el-button
              type="primary"
              :loading="batchAnalyzing"
              :disabled="pendingItems.length === 0"
              @click="onBatchAnalyze"
            >
              大模型分析
            </el-button>
            <div v-if="batchAnalyzing" class="progress-hint">
              <span class="lbl">正在对盈利 &lt; 5% 的 {{ pendingItems.length }} 只标的做亏损归因…</span>
              <div class="progress">
                <div class="progress__bar" :style="{ width: batchProgress + '%' }"></div>
              </div>
            </div>
          </div>

          <!-- 完成列表表格 -->
          <Panel title="监控完成记录" sub="已结算卖出" flush>
            <el-table
              v-loading="loading"
              :data="pagedCompletedList"
              style="width: 100%"
              row-key="id"
              :row-class-name="completedRowClass"
            >
              <el-table-column label="名称 / 编码" min-width="150">
                <template #default="{ row }">
                  <div
                    class="cell-stock cell-stock--link"
                    title="双击跳转 K 线"
                    @dblclick="onGoKline(row)"
                  >
                    <span class="nm">{{ row.name }}</span>
                    <span class="cd mono">{{ row.code }}</span>
                  </div>
                </template>
              </el-table-column>
              <!-- 买卖点类型（design D9：原「买卖点」+「方向」两列合并，展示 bsp_type 值，B 系红 / S 系绿） -->
              <el-table-column label="买卖点类型" width="100" align="center">
                <template #default="{ row }">
                  <span class="badge" :class="row.direction === 'buy' ? 'badge--rise' : 'badge--fall'">
                    {{ bspLabel(row.bsp_type, row.direction === 'buy') }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="买卖点价格" width="110" align="right" class-name="col-num">
                <template #default="{ row }">
                  <span class="num">{{ fmtPrice(row.bsp_price) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="结束价格" width="110" align="right" class-name="col-num">
                <template #default="{ row }">
                  <span class="num">{{ fmtPrice(row.end_price) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="收益率" width="100" align="right" class-name="col-num">
                <template #default="{ row }">
                  <span class="num" :class="(row.profit ?? 0) >= 0 ? 'text-rise' : 'text-fall'">
                    {{ fmtPct(row.profit, true) }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="买卖点日期" width="120" align="center">
                <template #default="{ row }">
                  <span class="num">{{ fmtDate(row.bsp_date) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="结束日期" width="120" align="center">
                <template #default="{ row }">
                  <span class="num">{{ fmtDate(row.end_date) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="归因" min-width="160">
                <template #default="{ row }">
                  <span v-if="row.ai_analyzed" class="badge badge--accent">已归因</span>
                  <span v-else class="badge badge--disabled">未归因</span>
                </template>
              </el-table-column>
              <el-table-column label="AI分析" width="100" align="center">
                <template #default="{ row }">
                  <el-button
                    link
                    type="primary"
                    size="small"
                    :loading="analyzingId === row.id"
                    @click="onAnalyze(row)"
                  >
                    {{ row.ai_analyzed ? '重新分析' : '大模型分析' }}
                  </el-button>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="100" align="right" fixed="right">
                <template #default="{ row }">
                  <el-button link type="primary" size="small" @click="onViewAttrDetail(row)">
                    查看归因
                  </el-button>
                </template>
              </el-table-column>
              <template #empty>
                <EmptyState description="暂无完成记录" />
              </template>
            </el-table>

            <div v-if="filteredCompletedList.length > cPageSize" class="pager-wrap">
              <el-pagination
                v-model:current-page="cPage"
                :page-size="cPageSize"
                :total="filteredCompletedList.length"
                layout="prev, pager, next, total"
                background
                small
              />
            </div>
          </Panel>

          <!-- 失败原因汇总 -->
          <Panel title="失败原因汇总" sub="盈利 < 5% 的标的 · 大模型归因">
            <div class="sum-list">
              <div v-for="item in lossItems" :key="item.id" class="sum-item">
                <span class="badge" :class="reasonBadgeClass(item)">{{ reasonCategory(item) }}</span>
                <div class="cell-stock" style="min-width:150px">
                  <span class="nm">{{ item.name }}</span>
                  <span class="cd mono">{{ item.code }}</span>
                </div>
                <div class="reason">
                  <span class="t">{{ item.attribution }}</span>
                  <span class="s">证据：{{ reasonCategory(item) }} · {{ fmtDate(item.end_date) }}</span>
                </div>
                <span class="spacer"></span>
                <span class="num text-fall">{{ fmtPct(item.profit, true) }}</span>
                <el-button link type="primary" size="small" @click="onViewAttrDetail(item)">
                  查看详情
                </el-button>
              </div>
              <EmptyState v-if="lossItems.length === 0" description="暂无亏损归因记录" />
            </div>
          </Panel>
        </template>
      </div>
    </div>

    <!-- 归因详情抽屉（design D6：SampleDrawer 保留复用） -->
    <SampleDrawer v-model="drawerVisible" :item="drawerItem" />
  </div>
</template>

<script setup lang="ts">
/**
 * MonitorView.vue — 监控单页（design D6/D7/D8，monitor-page-change 任务组 7）
 * - D6：CompletedView 并入为「已完成」tab，顶部 el-radio-group 整体切换内容区，
 *   不走路由；归因抽屉/批量分析随迁；原 route.query.code 带参逻辑改为页内
 *   「查看详情」切 tab 并定位高亮行。
 * - D7：搜索框对齐 K 线页（el-autocomplete + searchStocks 远程候选 +
 *   300ms setTimeout 本地防抖 + 后发覆盖 + Enter 语义），点选/回车按 code 精确过滤。
 * - D8：监控中列表新增「买卖点时间」（bsp_date）与「收益率」（current_pnl_pct）
 *   两列；盈利走势改为由列表各标的收益率前端聚合（替换 mock profit-series
 *   随机游走），曲线 >0 红 / <0 绿分段着色 + 0 轴参考线。
 */
import { ref, reactive, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type AutocompleteInstance } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import Sidebar from '@/components/layout/Sidebar.vue'
import TreeList from '@/components/ui/TreeList.vue'
import Panel from '@/components/ui/Panel.vue'
import StatCard from '@/components/ui/StatCard.vue'
import SegControl from '@/components/ui/SegControl.vue'
import ChangeBadge from '@/components/ui/ChangeBadge.vue'
import IndustryBadges from '@/components/ui/IndustryBadges.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import ProfitChart from '@/components/charts/ProfitChart.vue'
import SampleDrawer from './SampleDrawer.vue'
import { usePagination } from '@/composables/usePagination'
import { getMonitorList, getCompletedList, endMonitor, analyzeMonitor } from '@/api/modules/monitor'
import { searchStocks } from '@/api/modules/stock'
import { bspLabel } from '@/utils/bsp'
import type { MonitorItem, CompletedItem, AnalyzeResult } from '@/api/types'

// ---- 数据 ----
const loading = ref(false)
const monitorList = ref<MonitorItem[]>([])
const completedList = ref<CompletedItem[]>([])
const completedCount = ref(0)

// ---- 顶部 tab（design D6：单页双 tab，不走路由） ----
const tabMode = ref<'monitoring' | 'completed'>('monitoring')

function onTabChange(v: string | number | boolean) {
  const val = String(v)
  if (val !== 'monitoring' && val !== 'completed') return
  tabMode.value = val
  if (val === 'monitoring') page.value = 1
  else cPage.value = 1
}

// ---- 监控中 tab 侧栏过滤 ----
const activeProfit = ref('all')
const activeKl = ref('all')

const statusItems = [
  { key: 'monitoring', label: '监控中', count: 0 },
  { key: 'completed', label: '已完成', count: 0 },
]
const profitItems = [
  { key: 'all', label: '全部' },
  { key: 'profit', label: '盈利' },
  { key: 'loss', label: '亏损' },
]
const klTypeItems = [
  { key: 'all', label: '全部周期' },
  { key: '30m', label: '30分钟' },
  { key: '60m', label: '60分钟' },
  { key: 'D', label: '日线' },
  { key: 'W', label: '周线' },
  { key: 'M', label: '月线' },
]

function onProfitChange(k: string) {
  activeProfit.value = k
  page.value = 1
}
function onKlChange(k: string) {
  activeKl.value = k
  page.value = 1
}

// ---- 已完成 tab 侧栏过滤 ----
const activeAttr = ref('all')
const activeReason = ref('all')

const attrItems = [
  { key: 'all', label: '全部' },
  { key: 'analyzed', label: '已归因' },
  { key: 'pending', label: '未归因' },
]
const reasonItems = [
  { key: 'all', label: '全部' },
  { key: 'theory', label: '缠论失效' },
  { key: 'logic', label: '计算逻辑错误' },
]

function onAttrChange(k: string) {
  activeAttr.value = k
  cPage.value = 1
}
function onReasonChange(k: string) {
  activeReason.value = k
  cPage.value = 1
}

// ---- 分页（两个 tab 各一份页码状态） ----
const { page, pageSize, setTotal } = usePagination(20)
const { page: cPage, pageSize: cPageSize } = usePagination(20)

// ---------------------------------------------------------------------------
// 搜索（design D7：对齐 K 线页 el-autocomplete 远程候选 + 300ms 防抖 + Enter 语义；
// 查询/重置按钮；D7 增补：已完成 tab 同款搜索，两 tab 各一份实例）
// ---------------------------------------------------------------------------
interface StockSuggestion {
  /** el-autocomplete valueKey 默认取 value；点选后回填输入框 */
  value: string
  code: string
  name: string
  /** 无匹配候选的空态提示项，不参与过滤 */
  placeholder?: boolean
}

/** 按 code 精确过滤的搜索器实例（监控中/已完成共用逻辑，各自独立状态与页码重置回调） */
interface StockSearch {
  acRef: ReturnType<typeof ref<AutocompleteInstance | null>>
  input: ReturnType<typeof ref<string>>
  selectedCode: ReturnType<typeof ref<string>>
  /** 用户是否用 ↑↓ 浏览过候选（Enter 分流标志，输入内容变化时重置） */
  arrowBrowsed: ReturnType<typeof ref<boolean>>
  /** 查询按钮（D7 增补）：应用当前输入/选中标的的精确过滤 */
  apply: () => void
  /** 重置按钮（D7 增补）：清空输入与选中，恢复全量 */
  reset: () => void
  onInput: (q: string) => void
  query: (q: string, cb: (items: StockSuggestion[]) => void) => void
  onSelect: (item: StockSuggestion) => void
  onKeydown: (e: KeyboardEvent) => void
  onClear: () => void
  dispose: () => void
}

function createStockSearch(onResetPage: () => void): StockSearch {
  const s = reactive({
    timer: null as ReturnType<typeof setTimeout> | null,
    seq: 0,
  })
  const acRef = ref<AutocompleteInstance | null>(null)
  const arrowBrowsed = ref(false)
  const input = ref('')
  /** 精确过滤的标的 code（点选/回车/查询按钮后生效；重置恢复全量） */
  const selectedCode = ref('')

  /** 取消在途/待发的搜索请求（后发覆盖的作废通道） */
  function cancel(): void {
    if (s.timer !== null) {
      clearTimeout(s.timer)
      s.timer = null
    }
    s.seq++
  }

  function reset(): void {
    cancel()
    input.value = ''
    selectedCode.value = ''
    arrowBrowsed.value = false
    acRef.value?.close()
    onResetPage()
  }

  /** 远程搜索候选（D7：300ms 本地 setTimeout 防抖，不引 lodash；过期响应丢弃） */
  function query(q: string, cb: (items: StockSuggestion[]) => void): void {
    if (s.timer !== null) {
      clearTimeout(s.timer)
      s.timer = null
    }
    const text = q.trim()
    if (!text) {
      cancel()
      cb([])
      return
    }
    // 请求发出前先收起旧候选，避免加载态闪烁
    cb([])
    s.timer = setTimeout(async () => {
      s.timer = null
      const seq = ++s.seq
      try {
        const list = await searchStocks(text)
        if (seq !== s.seq) return // 过期响应丢弃（后发覆盖）
        if (!list.length) {
          cb([{ value: text, code: '', name: '无匹配候选', placeholder: true }])
          return
        }
        cb(list.map((st) => ({ value: st.code, code: st.code, name: st.name })))
      } catch (e) {
        if (seq !== s.seq) return
        console.warn('[MonitorView.queryStocks] 股票搜索失败', {
          query: text,
          error: e instanceof Error ? e.message : String(e),
        })
        cb([])
      }
    }, 300)
  }

  function apply(): void {
    cancel()
    arrowBrowsed.value = false
    const v = input.value.trim()
    if (!v) {
      selectedCode.value = ''
    } else {
      selectedCode.value = v
    }
    onResetPage()
  }

  function onInput(q: string): void {
    // 输入变化即重置 Enter 分流标志；已选标的在输入变化时先行失效（回到全量，待点选/回车/查询）
    arrowBrowsed.value = false
    if (selectedCode.value && q.trim() !== selectedCode.value) {
      selectedCode.value = ''
    }
  }

  /** 点选候选：输入框回填 code，按 code 精确过滤（D7） */
  function onSelect(item: StockSuggestion): void {
    cancel()
    arrowBrowsed.value = false
    acRef.value?.close()
    if (item.placeholder) return // 空态提示项：仅收起下拉
    input.value = item.code
    selectedCode.value = item.code
    onResetPage()
  }

  /** Enter 语义（D7，捕获阶段拦截防 autocomplete 默认回车劫持）：
   *  未用 ↑↓ 浏览 → 按输入框原值精确匹配 code；浏览过且有高亮项 → 交给 autocomplete 选中 */
  function onKeydown(e: KeyboardEvent): void {
    // IME 组合确认的 Enter（如中文「平安」上屏）不触发查询
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
    apply()
  }

  /** 清空输入：恢复全量列表 */
  function onClear(): void {
    reset()
  }

  function dispose(): void {
    cancel()
  }

  return { acRef, input, selectedCode, arrowBrowsed, apply, reset, onInput, query, onSelect, onKeydown, onClear, dispose }
}

/** 监控中 tab 搜索实例 */
const mSearch = createStockSearch(() => {
  page.value = 1
})
/** 已完成 tab 搜索实例（design D7 增补：与监控中同款，独立选中标的） */
const cSearch = createStockSearch(() => {
  cPage.value = 1
})

// ---- 监控中过滤（D7：keyword 条件改为所选 code 精确匹配） ----
const filteredList = computed<MonitorItem[]>(() => {
  let list = monitorList.value
  if (mSearch.selectedCode.value) {
    list = list.filter((r) => r.code === mSearch.selectedCode.value)
  }
  if (activeKl.value !== 'all') {
    list = list.filter((r) => r.kl_type === activeKl.value)
  }
  if (activeProfit.value === 'profit') {
    list = list.filter((r) => (r.max_profit ?? 0) >= 0)
  } else if (activeProfit.value === 'loss') {
    list = list.filter((r) => (r.max_profit ?? 0) < 0)
  }
  return list
})

const pagedList = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredList.value.slice(start, start + pageSize.value)
})

// ---- 已完成过滤（D7 增补：与监控中同款，按所选 code 精确匹配） ----
const filteredCompletedList = computed(() => {
  let list = completedList.value
  if (cSearch.selectedCode.value) {
    list = list.filter((r) => r.code === cSearch.selectedCode.value)
  }
  if (activeAttr.value === 'analyzed') {
    list = list.filter((r) => r.ai_analyzed)
  } else if (activeAttr.value === 'pending') {
    list = list.filter((r) => !r.ai_analyzed)
  }
  if (activeReason.value !== 'all') {
    list = list.filter((r) => reasonCategory(r) === (activeReason.value === 'theory' ? '缠论失效' : '计算逻辑错误'))
  }
  return list
})

const pagedCompletedList = computed(() => {
  const start = (cPage.value - 1) * cPageSize.value
  return filteredCompletedList.value.slice(start, start + cPageSize.value)
})

// ---- 汇总（监控中 tab，design D11：收益率求和 + 当前胜率 + 涨幅最大） ----
const totalProfit = computed(() => {
  // 收益率列求和（null 行跳过）
  const sum = monitorList.value.reduce((acc, r) => acc + (r.current_pnl_pct ?? 0), 0)
  return +sum.toFixed(2)
})
const totalProfitStr = computed(() => `${totalProfit.value >= 0 ? '+' : ''}${totalProfit.value.toFixed(2)}%`)

/** 当前胜率（D11）：current_price > bsp_price 计胜；两者任一缺失的行不计入分母 */
const winCount = computed(() =>
  monitorList.value.filter((r) => r.current_price != null && r.bsp_price != null && r.current_price > r.bsp_price).length,
)
const winTotal = computed(() =>
  monitorList.value.filter((r) => r.current_price != null && r.bsp_price != null).length,
)
const winRate = computed(() => {
  if (winTotal.value === 0) return 0
  return +((winCount.value / winTotal.value) * 100).toFixed(1)
})
const winRateStr = computed(() => `${winRate.value.toFixed(1)}%`)

/** 涨幅最大（D11）：当日涨跌幅（change_pct）最高值，含标的与级别 */
const maxChange = computed<MonitorItem | null>(() => {
  const rows = monitorList.value.filter((r) => r.change_pct != null)
  if (rows.length === 0) return null
  return rows.reduce((best, r) => (r.change_pct > best.change_pct ? r : best))
})
const maxChangeStr = computed(() =>
  maxChange.value ? `${maxChange.value.change_pct >= 0 ? '+' : ''}${maxChange.value.change_pct.toFixed(2)}%` : '--',
)

// ---- 已完成统计（改名 c 前缀，与监控中 D11 统计区分） ----
const cWinRate = computed(() => {
  const list = completedList.value
  if (list.length === 0) return 0
  const wins = list.filter((r) => r.profit > 0).length
  return +((wins / list.length) * 100).toFixed(1)
})
const cWinRateStr = computed(() => `${cWinRate.value.toFixed(1)}%`)

const avgProfit = computed(() => {
  const list = completedList.value
  if (list.length === 0) return 0
  const sum = list.reduce((acc, r) => acc + r.profit, 0)
  return +(sum / list.length).toFixed(2)
})
const avgProfitStr = computed(() => `${avgProfit.value >= 0 ? '+' : ''}${avgProfit.value.toFixed(2)}%`)

const profitRatio = computed(() => {
  const list = completedList.value
  const wins = list.filter((r) => r.profit > 0)
  const losses = list.filter((r) => r.profit < 0)
  if (wins.length === 0 || losses.length === 0) return wins.length / (losses.length || 1)
  const avgWin = wins.reduce((a, r) => a + r.profit, 0) / wins.length
  const avgLoss = Math.abs(losses.reduce((a, r) => a + r.profit, 0) / losses.length)
  return +(avgWin / (avgLoss || 1)).toFixed(2)
})
const profitRatioStr = computed(() => profitRatio.value.toFixed(2))

// ---- 失败原因汇总（profit < 5%）----
const lossItems = computed(() => {
  return completedList.value.filter((r) => r.profit < 5)
})

// ---- 待分析标的 ----
const pendingItems = computed(() => {
  return completedList.value.filter((r) => !r.ai_analyzed && r.profit < 5)
})

// ---------------------------------------------------------------------------
// 盈利走势（design D8：由监控中列表各标的收益率前端聚合，替换 mock 随机游走）
// ---------------------------------------------------------------------------
/** 汇总模式：按买卖点时间（收益计算起点）逐标的聚合的累计均值曲线；
 *  null 收益率行跳过不计入（backend 确认口径） */
const summarySeries = computed<{ date: string; value: number }[]>(() => {
  const rows = monitorList.value
    .filter((r) => r.current_pnl_pct != null && Number.isFinite(r.bsp_date))
    .slice()
    .sort((a, b) => a.bsp_date - b.bsp_date)
  if (rows.length === 0) return []
  const series: { date: string; value: number }[] = []
  let sum = 0
  rows.forEach((r, i) => {
    sum += r.current_pnl_pct as number
    const d = new Date(r.bsp_date)
    series.push({
      date: `${d.getMonth() + 1}/${d.getDate()}`,
      value: +(sum / (i + 1)).toFixed(2),
    })
  })
  return series
})

const profitSeg = ref('summary')
const segItems = [
  { label: '汇总', value: 'summary' },
  { label: '单只', value: 'single' },
]

// ---- 单只标的走势（保留：基于买卖点价 → 当前价的收益率序列） ----
const singleStockId = ref<number | null>(null)
const singleStockSeries = computed(() => {
  if (!singleStockId.value) return []
  const row = monitorList.value.find((r) => r.id === singleStockId.value)
  if (!row) return []
  // 有真实收益率（current_pnl_pct）时以终点直连，否则用入场价平走容错
  const start = row.bsp_price
  const endPnl = row.current_pnl_pct
  const end = endPnl != null ? start * (1 + endPnl / 100) : (row.current_price ?? start)
  if (!start) return []
  const series: { date: string; value: number }[] = []
  for (let i = 13; i >= 0; i--) {
    const d = new Date(Date.now() - i * 86400000)
    const ratio = (13 - i) / 13
    const v = +(((start * (1 + ratio * ((end - start) / start))) - start) / start * 100).toFixed(2)
    series.push({
      date: `${d.getMonth() + 1}/${d.getDate()}`,
      value: v,
    })
  }
  return series
})

// ---- 工具 ----
function fmtPrice(v: number | null | undefined) {
  // 后端 DuckDB 不可用时 current_price 等可为 null（design D5 容错）
  if (v == null) return '--'
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
/** 百分比列容错格式化：null/undefined 显示 --（design D5）；signed=true 时带正负号 */
function fmtPct(v: number | null | undefined, signed = false) {
  if (v == null) return '--'
  const s = v.toFixed(2)
  return signed ? `${v >= 0 ? '+' : ''}${s}%` : `${s}%`
}
/** 买卖点时间（ms）→ YYYY-MM-DD HH:mm（design D8：收益计算起点） */
function fmtDateTime(ts: number | null | undefined) {
  if (ts == null) return '--'
  const d = new Date(ts)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
function fmtDate(ts: number | null | undefined) {
  if (ts == null) return '--'
  const d = new Date(ts)
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${m}-${day}`
}
function klLabel(k: string) {
  const m: Record<string, string> = { '30m': '30分钟', '60m': '60分钟', D: '日线', W: '周线', M: '月线' }
  return m[k] || k
}

function reasonCategory(item: CompletedItem): string {
  const t = item.attribution || ''
  if (/包含|逻辑|计算|中枢区间|端点/.test(t)) return '计算逻辑错误'
  return '缠论失效'
}
function reasonBadgeClass(item: CompletedItem) {
  return reasonCategory(item) === '计算逻辑错误' ? 'badge--info' : 'badge--warning'
}

// ---- 操作：手动结束监控 ----
const endingId = ref<number | null>(null)
async function onEnd(row: MonitorItem) {
  try {
    await ElMessageBox.confirm(`确认手动结束「${row.name}」的监控？`, '提示', {
      type: 'warning',
      confirmButtonText: '确认结束',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  endingId.value = row.id
  try {
    await endMonitor(row.id)
    monitorList.value = monitorList.value.filter((r) => r.id !== row.id)
    ElMessage.success('已结束监控')
  } finally {
    endingId.value = null
  }
}

// ---- 双击名称/编码跳转 K 线页（design D12：携带级别，对齐 BspView 的 period 映射） ----
// 监控周期词表（D4：D/W/M/30m/60m）→ K 线页 period 词表（1d/1w/1M/30m/60m）
const KL_TO_KLINE_PERIOD: Record<string, string> = {
  D: '1d',
  W: '1w',
  M: '1M',
  '30m': '30m',
  '60m': '60m',
}
const router = useRouter()

function onGoKline(row: { code: string; kl_type: string }) {
  const q: { code: string; period?: string } = { code: row.code }
  const period = row.kl_type ? KL_TO_KLINE_PERIOD[row.kl_type] : undefined
  if (period) q.period = period
  router.push({ name: 'kline', query: q })
}

// ---- 查看详情（design D6：页内切到已完成 tab 并定位/高亮对应标的行，不走路由） ----
/** 已完成列表中待高亮的标的 code（切 tab 定位行用） */
const highlightCode = ref('')

function completedRowClass({ row }: { row: CompletedItem }): string {
  return row.code === highlightCode.value ? 'row--hl' : ''
}

async function onViewDetail(row: MonitorItem) {
  highlightCode.value = row.code
  tabMode.value = 'completed'
  cPage.value = 1
  cSearch.reset()
  await nextTick()
  const idx = filteredCompletedList.value.findIndex((r) => r.code === row.code)
  if (idx < 0) {
    // 该标的尚无完成记录（仍在监控中）：切到已完成 tab 不定位，给出提示
    console.warn('[MonitorView.onViewDetail] 标的无完成记录，跳过定位', { code: row.code })
    ElMessage.info(`「${row.name}」暂无完成记录`)
    highlightCode.value = ''
    return
  }
  cPage.value = Math.floor(idx / cPageSize.value) + 1
}

// ---- 归因详情抽屉（design D6：状态随内容并入，SampleDrawer 复用） ----
const drawerVisible = ref(false)
const drawerItem = ref<CompletedItem | null>(null)

function onViewAttrDetail(row: CompletedItem) {
  drawerItem.value = row
  drawerVisible.value = true
}

// ---- AI 分析（design D5：真实归因对接；成功展示归因内容，失败展示明确错误） ----
const analyzingId = ref<number | null>(null)

/** 应用真实返回的归因结果（AttributionRecord[]）到标的行 */
function applyAttribution(row: CompletedItem, res: AnalyzeResult) {
  const evidences = (res.attribution || []).map((a) => a.evidence).filter(Boolean)
  if (evidences.length > 0) row.attribution = evidences.join('\n')
  row.ai_analyzed = true
}

async function onAnalyze(row: CompletedItem) {
  analyzingId.value = row.id
  try {
    const res = await analyzeMonitor(row.id)
    applyAttribution(row, res)
    ElMessage.success('归因分析完成')
    // 展示归因内容
    drawerItem.value = row
    drawerVisible.value = true
  } catch {
    // 失败（400 未配置/盈利≥5、调用失败 5xx）：明确错误文案由 client 拦截器按后端 detail 展示，不写占位结果
  } finally {
    analyzingId.value = null
  }
}

// ---- 批量分析（前端过滤：仅 pnl < 5% 可触发） ----
const batchAnalyzing = ref(false)
const batchProgress = ref(0)
async function onBatchAnalyze() {
  const targets = pendingItems.value
  if (targets.length === 0) {
    ElMessage.info('没有待分析的标的')
    return
  }
  batchAnalyzing.value = true
  batchProgress.value = 0
  let okCount = 0
  let failCount = 0
  try {
    for (let i = 0; i < targets.length; i++) {
      const row = targets[i]
      try {
        const res = await analyzeMonitor(row.id)
        applyAttribution(row, res)
        okCount++
      } catch {
        // 单条失败：错误文案由拦截器按 detail 提示，继续处理后续标的
        failCount++
      }
      batchProgress.value = Math.round(((i + 1) / targets.length) * 100)
    }
    if (failCount === 0) {
      ElMessage.success(`完成 ${okCount} 只标的的归因分析`)
    } else {
      ElMessage.warning(`归因完成 ${okCount} 只，失败 ${failCount} 只`)
    }
  } finally {
    batchAnalyzing.value = false
  }
}

// ---- 加载 ----
async function loadAll() {
  loading.value = true
  try {
    const [ml, cl] = await Promise.all([
      getMonitorList(),
      getCompletedList(),
    ])
    monitorList.value = ml
    completedList.value = cl
    completedCount.value = cl.length
    statusItems[0].count = ml.length
    statusItems[1].count = cl.length
    setTotal(ml.length)
  } finally {
    loading.value = false
  }
}

onMounted(loadAll)

onBeforeUnmount(() => {
  mSearch.dispose()
  cSearch.dispose()
})
</script>

<style scoped>
.monitor-page {
  display: flex;
  flex-direction: column;
  gap: var(--sp-lg);
  flex: 1;
}
/* 顶部 tab（design D6）：显著位置整体切换内容区 */
.tabbar {
  display: flex;
  align-items: center;
  gap: var(--sp-md);
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
/* 双击跳转 K 线（design D12）：可交互提示 */
.cell-stock--link {
  cursor: pointer;
}
.cell-stock--link:hover .nm {
  text-decoration: underline;
}
.pager-wrap {
  display: flex;
  justify-content: flex-end;
  padding: var(--sp-md) var(--sp-lg);
}
.single-stock-toolbar {
  position: absolute;
  top: 10px;
  right: 14px;
  z-index: 10;
}
/* 搜索候选下拉项（D7：对齐 K 线页 code + 名称插槽） */
.code-field {
  width: 240px;
}
.code-field :deep(.el-autocomplete) {
  width: 100%;
}
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
/* 查看详情定位高亮行（design D6） */
:deep(.el-table .row--hl) {
  background: var(--accent-dim);
}
.progress-hint {
  display: flex;
  align-items: center;
  gap: 12px;
  max-width: 360px;
}
.progress-hint .lbl {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
}
.progress-hint .progress {
  flex: 1;
}
.sum-list {
  padding: 4px 0;
}
.sum-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px var(--sp-lg);
  border-bottom: 1px solid var(--border-base);
}
.sum-item:last-child {
  border-bottom: none;
}
.sum-item .reason {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
}
.sum-item .reason .t {
  font-size: 13px;
  color: var(--text-primary);
}
.sum-item .reason .s {
  font-size: 11px;
  color: var(--text-disabled);
}
</style>
