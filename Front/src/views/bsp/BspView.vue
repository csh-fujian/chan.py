<template>
  <div class="page-layout">
    <!-- 左侧菜单栏 -->
    <aside class="panel sidebar reveal reveal--1">
      <div class="sidebar__head">
        买卖点
        <span class="spacer"></span>
      </div>
      <div class="tree">
        <div class="sidebar__group">
          <div class="sidebar__group-label">方向</div>
          <div
            class="tree__item"
            :class="{ 'is-active': query.direction === '' }"
            @click="setDirection('')"
          >
            <el-icon class="tree__icon"><TrendCharts /></el-icon>
            <span>全部方向</span>
            <span class="count">{{ stats.total }}</span>
          </div>
          <div
            class="tree__item"
            :class="{ 'is-active': query.direction === 'buy' }"
            @click="setDirection('buy')"
          >
            <el-icon class="tree__icon"><Top /></el-icon>
            <span>买点</span>
            <span class="count">{{ stats.buy }}</span>
          </div>
          <div
            class="tree__item"
            :class="{ 'is-active': query.direction === 'sell' }"
            @click="setDirection('sell')"
          >
            <el-icon class="tree__icon"><Bottom /></el-icon>
            <span>卖点</span>
            <span class="count">{{ stats.sell }}</span>
          </div>
        </div>
        <div class="sidebar__group">
          <div class="sidebar__group-label">周期</div>
          <div
            v-for="kl in klOptions"
            :key="kl.value"
            class="tree__item"
            :class="{ 'is-active': query.kl_type === kl.value }"
            @click="setKlType(kl.value)"
          >
            <el-icon class="tree__icon"><Calendar /></el-icon>
            <span>{{ kl.label }}</span>
          </div>
        </div>
      </div>
    </aside>

    <!-- 右侧主面板 -->
    <div class="main-panel">
      <div class="bsp-page">
        <!-- 查询筛选区：股票搜索（模糊下拉选 code）| 周期 | 日期 | 买卖点类型 | 方向 -->
        <div class="toolbar reveal reveal--1">
          <!-- 股票搜索（最前）：输入模糊匹配下拉，选中后锁定精确 code，点「查询」才触发 -->
          <el-autocomplete
            ref="acRef"
            v-model="keywordInput"
            :fetch-suggestions="queryStocks"
            :trigger-on-focus="false"
            :debounce="300"
            placeholder="代码 / 名称 / 拼音"
            :prefix-icon="Search"
            clearable
            style="width: 180px"
            @select="onSelectSuggestion"
            @clear="onKeywordClear"
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
          <el-select v-model="query.kl_type" placeholder="周期" style="width: 110px" @change="onQueryChange">
            <el-option v-for="kl in klOptions" :key="kl.value" :label="kl.label" :value="kl.value" />
          </el-select>
          <!-- 日期范围条件（D7/D9）：默认最近三个交易日；双端齐备按闭区间过滤，清空后恢复全期 -->
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            unlink-panels
            clearable
            style="width: 220px"
            @change="onQueryChange"
          />
          <el-select v-model="query.bsp_type" placeholder="买卖点类型" style="width: 130px" @change="onQueryChange">
            <el-option label="全部类型" value="" />
            <el-option v-for="t in ALL_BSP_LABELS" :key="t" :label="t" :value="t" />
          </el-select>
          <el-select v-model="query.direction" placeholder="方向" style="width: 100px" @change="onQueryChange">
            <el-option label="全部方向" value="" />
            <el-option label="买" value="buy" />
            <el-option label="卖" value="sell" />
          </el-select>
          <button class="btn btn--primary" @click="onQuery">查询</button>
          <button class="btn btn--default" @click="onReset">重置</button>
        </div>

        <!-- 操作工具条 -->
        <div class="toolbar reveal reveal--2">
          <span class="text-secondary" style="font-size: 12px">
            已选 <span class="num">{{ selectedCount }}</span> 项
          </span>
          <span class="spacer"></span>
          <button class="btn btn--default" :disabled="!hasSelected" @click="onBatchWatchlist">
            批量加入自选
          </button>
          <button class="btn btn--default" :disabled="!hasSelected" @click="onBatchMonitor">
            加入监控
          </button>
        </div>

        <!-- 结果区 -->
        <div class="panel reveal reveal--3">
          <el-tabs v-model="activeTab" class="bsp-tabs">
            <el-tab-pane label="结果列表" name="list">
              <div class="tbl-wrap" v-loading="loading">
                <el-table
                  :data="records"
                  empty-text="暂无买卖点记录"
                  @selection-change="onSelectionChange"
                  @row-dblclick="onRowDblClick"
                  row-key="id"
                >
                  <el-table-column type="selection" width="44" reserve-selection />
                  <el-table-column label="编码" width="110">
                    <template #default="{ row }">
                      <span class="mono">{{ row.code }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="名称" width="100">
                    <template #default="{ row }">
                      <span>{{ row.name }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="股价" width="100" align="right">
                    <template #default="{ row }">
                      <span class="num">{{ formatPrice(row.current_price) }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="涨跌幅" width="95" align="right">
                    <template #default="{ row }">
                      <ChangeBadge :value="row.change_pct" />
                    </template>
                  </el-table-column>
                  <el-table-column label="行业" min-width="160">
                    <template #default="{ row }">
                      <IndustryBadges :industries="row.industries" />
                    </template>
                  </el-table-column>
                  <el-table-column label="买卖点类型" width="110">
                    <template #default="{ row }">
                      <span class="badge" :class="row.direction === 'buy' ? 'badge--rise' : 'badge--fall'">
                        {{ bspLabel(row.bsp_type, row.direction === 'buy') }}
                      </span>
                    </template>
                  </el-table-column>
                  <el-table-column label="买卖点价格" width="120" align="right">
                    <template #default="{ row }">
                      <span class="num">{{ formatPrice(row.bsp_price) }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="当前价格" width="100" align="right">
                    <template #default="{ row }">
                      <span class="num">{{ formatPrice(row.current_price) }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="买卖点时间" width="140">
                    <template #default="{ row }">
                      <span class="num">{{ formatBspTime(row) }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="周期" width="90">
                    <template #default="{ row }">
                      <span class="num">{{ klLabel(row.kl_type) }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="操作" width="150" align="right">
                    <template #default="{ row }">
                      <button class="row-action" @click="openNesting(row)">区间套</button>
                      <button class="row-action" @click="openMonitorDialog(row)">加入监控</button>
                    </template>
                  </el-table-column>
                  <template #empty>
                    <EmptyState description="暂无买卖点记录，请调整查询条件" />
                  </template>
                </el-table>
              </div>
              <div class="pager" v-if="total > 0">
                <el-pagination
                  v-model:current-page="query.page"
                  v-model:page-size="query.page_size"
                  :total="total"
                  :page-sizes="[20]"
                  layout="total, prev, pager, next, jumper"
                  background
                  @current-change="loadList"
                />
              </div>
            </el-tab-pane>

            <el-tab-pane label="板块聚合" name="sector">
              <div class="tbl-wrap" v-loading="aggLoading">
                <el-table :data="aggregate" empty-text="暂无聚合数据">
                  <el-table-column label="行业" min-width="160">
                    <template #default="{ row }">
                      <span class="badge badge--default">{{ row.industry }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="买点股票数" width="140" align="right">
                    <template #default="{ row }">
                      <span class="num text-rise">{{ row.buy_count }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="卖点股票数" width="140" align="right">
                    <template #default="{ row }">
                      <span class="num text-fall">{{ row.sell_count }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="合计" width="120" align="right">
                    <template #default="{ row }">
                      <span class="num">{{ row.total }}</span>
                    </template>
                  </el-table-column>
                  <template #empty>
                    <EmptyState description="暂无板块聚合数据" />
                  </template>
                </el-table>
              </div>
            </el-tab-pane>
          </el-tabs>
        </div>
      </div>
    </div>

    <!-- 区间套抽屉 -->
    <NestingDrawer
      v-model:visible="nestingVisible"
      :record="nestingRecord"
    />

    <!-- 批量加入自选弹窗 -->
    <el-dialog v-model="watchlistDialogVisible" title="批量加入自选" width="420px" append-to-body>
      <div class="add-dialog-body">
        <div class="form-row">
          <label>目标文件夹</label>
          <el-select v-model="watchlistFolderId" placeholder="选择文件夹" style="width: 100%">
            <el-option v-for="f in watchFolders" :key="f.id" :label="f.name" :value="f.id" />
          </el-select>
        </div>
        <p class="dialog-hint">
          选中的 {{ selectedCount }} 只股票将按 code 去重后加入目标文件夹。
        </p>
      </div>
      <template #footer>
        <el-button @click="watchlistDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="addingWatch" @click="confirmBatchWatchlist">确认加入</el-button>
      </template>
    </el-dialog>

    <!-- 行级加入监控弹窗（design D8 修订，任务 4.5）：
         只读上下文（股票/周期/买卖点价格）+ 买点时间（默认 = 该行买卖点时间，
         可编辑，「此刻」按钮取当前时间），提交 POST /api/monitor -->
    <el-dialog v-model="monitorDialogVisible" title="加入监控" width="440px" append-to-body>
      <div class="add-dialog-body" v-if="monitorRow">
        <div class="monitor-ctx">
          <div class="form-row">
            <label>股票</label>
            <span class="ctx-value">
              {{ monitorRow.name }}
              <span class="mono ctx-code">{{ monitorRow.code }}</span>
            </span>
          </div>
          <div class="form-row">
            <label>周期</label>
            <span class="ctx-value">{{ klLabel(monitorRow.kl_type) }}</span>
          </div>
          <div class="form-row">
            <label>买卖点价格</label>
            <span class="ctx-value num" :class="{ 'price-stale': priceLoading }">
              {{ formatPrice(monitorPrice) }}
            </span>
          </div>
        </div>
        <div class="form-row">
          <label>买点时间</label>
          <div class="monitor-time-row">
            <el-date-picker
              v-model="monitorStartTime"
              type="datetime"
              value-format="YYYY-MM-DD HH:mm:ss"
              format="YYYY-MM-DD HH:mm:ss"
              placeholder="选择买点时间"
              clearable
              style="flex: 1"
              @change="onMonitorTimeChange"
            />
            <el-button @click="setMonitorTimeNow">此刻</el-button>
          </div>
        </div>
        <p class="dialog-hint">
          提交后将以所选买点时间对应的股票价格作为入场价，自买点时间起对该股票进行监控。
        </p>
      </div>
      <template #footer>
        <el-button @click="monitorDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="addingMonitor" @click="confirmAddMonitor">确认加入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, onActivated } from 'vue'
import type { AutocompleteInstance } from 'element-plus'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { TrendCharts, Top, Bottom, Calendar, Search } from '@element-plus/icons-vue'
import IndustryBadges from '@/components/ui/IndustryBadges.vue'
import ChangeBadge from '@/components/ui/ChangeBadge.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import NestingDrawer from './NestingDrawer.vue'
import { getBspList, getBspAggregate, getPriceAt, type BspQuery } from '@/api/modules/bsp'
import { getFolders, addStock, type WatchFolder } from '@/api/modules/watchlist'
import { createMonitor } from '@/api/modules/monitor'
import { searchStocks } from '@/api/modules/stock'
import { ALL_BSP_LABELS, bspLabel } from '@/utils/bsp'
import type { BspRecord, BspAggregate } from '@/api/types'

// 周期词表（design D1）：30分 → 60分 → 日线 → 周线 → 月线，无 1/5/15 分钟
// 单一数组同时驱动左侧周期列表与工具栏下拉，改一处两边同步
const klOptions = [
  { label: '30分', value: '30m' },
  { label: '60分', value: '60m' },
  { label: '日线', value: 'D' },
  { label: '周线', value: 'W' },
  { label: '月线', value: 'M' },
]

function klLabel(v: string) {
  return klOptions.find((k) => k.value === v)?.label || v
}

// ---- 查询 ----
// 日期范围默认值 = 最近三个交易日（design D9）：前端跳周末近似（节假日不跳，范围过滤语义下可接受）
// date_to = 今天，date_from = 自今天向前数第 3 个工作日（周内）
function recentThreeWorkdays(): [string, string] {
  const fmt = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  const to = new Date()
  let n = 0
  let cur = new Date(to)
  // 向前找 2 个更早的工作日（含今天共 3 个工作日）
  while (n < 2) {
    cur = new Date(cur.getFullYear(), cur.getMonth(), cur.getDate() - 1)
    if (cur.getDay() !== 0 && cur.getDay() !== 6) n++
  }
  return [fmt(cur), fmt(to)]
}

const query = reactive<BspQuery>({
  page: 1,
  page_size: 20,
  keyword: '',
  bsp_type: '',
  direction: '',
  kl_type: '',
  date_from: '',
  date_to: '',
})

// 日期范围控件本地状态（daterange 绑定 [start, end]，空为 null）
const dateRange = ref<[string, string] | null>(recentThreeWorkdays())

// 发请求前把 dateRange 同步进 query（null/空时两端都置 ''，即不过滤）
function syncDateRangeToQuery() {
  query.date_from = dateRange.value?.[0] || ''
  query.date_to = dateRange.value?.[1] || ''
}
syncDateRangeToQuery()

const activeTab = ref<'list' | 'sector'>('list')
const loading = ref(false)
const records = ref<BspRecord[]>([])
const total = ref(0)

// 统计（侧栏 count）
const stats = reactive({ total: 0, buy: 0, sell: 0 })

async function loadList() {
  loading.value = true
  // 每次请求前同步日期范围（控件可能被用户改写/清空）
  syncDateRangeToQuery()
  try {
    const res = await getBspList(query)
    records.value = res.list
    total.value = res.total
    // 统计（侧栏 count）：buy/sell = 同一条件下（不含方向）按方向拆分的总数
    // total = buy + sell，确保三个统计值口径一致（不受当前 direction 筛选影响）
    const [buyRes, sellRes] = await Promise.all([
      getBspList({ ...query, page: 1, page_size: 1, direction: 'buy' }),
      getBspList({ ...query, page: 1, page_size: 1, direction: 'sell' }),
    ])
    stats.buy = buyRes.total
    stats.sell = sellRes.total
    stats.total = buyRes.total + sellRes.total
  } catch {
    records.value = []
    total.value = 0
    stats.total = 0
    stats.buy = 0
    stats.sell = 0
  } finally {
    loading.value = false
  }
}

// 板块聚合
const aggLoading = ref(false)
const aggregate = ref<BspAggregate[]>([])
async function loadAggregate() {
  aggLoading.value = true
  try {
    aggregate.value = await getBspAggregate()
  } catch {
    aggregate.value = []
  } finally {
    aggLoading.value = false
  }
}

// ---- 股票搜索（el-autocomplete：模糊下拉选 code，点「查询」才触发请求）----
interface StockSuggestion {
  value: string
  code: string
  name: string
  /** 无匹配候选的空态提示项，不参与查询 */
  placeholder?: boolean
}
const acRef = ref<AutocompleteInstance | null>(null)
/** 输入框绑定值（自由文本）；选中候选后回填为精确 code */
const keywordInput = ref('')
/** 选中候选后的精确查询 code（'' = 未选中，查询退化为关键词模糊匹配） */
const selectedCode = ref('')

/** 远程模糊搜索候选（searchStocks 已含防抖语义，此处仅做空输入短路） */
async function queryStocks(q: string, cb: (items: StockSuggestion[]) => void) {
  const query = q.trim()
  if (!query) {
    cb([])
    return
  }
  try {
    const list = await searchStocks(query)
    if (!list.length) {
      cb([{ value: query, code: '', name: '无匹配候选', placeholder: true }])
      return
    }
    cb(list.map((s) => ({ value: s.code, code: s.code, name: s.name })))
  } catch {
    cb([])
  }
}

/** 点选候选：输入框回填精确 code，锁定 selectedCode（不触发查询） */
function onSelectSuggestion(item: StockSuggestion) {
  if (item.placeholder) return
  selectedCode.value = item.code
  keywordInput.value = item.code
  acRef.value?.close()
}

/** 手动清空/修改输入后，解除已锁定的精确 code（退回模糊语义） */
function onKeywordClear() {
  selectedCode.value = ''
}

// 点「查询」时才把搜索框内容同步进 query：
// 选中过候选 → 精确 code；否则用输入文本做关键词模糊匹配
function syncKeywordToQuery() {
  query.keyword = selectedCode.value || keywordInput.value.trim()
}

function onQueryChange() {
  query.page = 1
  loadList()
}

function onQuery() {
  syncKeywordToQuery()
  query.page = 1
  loadList()
}

function onReset() {
  keywordInput.value = ''
  selectedCode.value = ''
  query.keyword = ''
  query.bsp_type = ''
  query.direction = ''
  query.kl_type = ''
  // 日期范围恢复默认：最近三个交易日（spec「默认日期范围为最近三个交易日」）
  dateRange.value = recentThreeWorkdays()
  syncDateRangeToQuery()
  query.page = 1
  loadList()
}

function setDirection(d: 'buy' | 'sell' | '') {
  query.direction = d
  onQueryChange()
}
function setKlType(v: string) {
  query.kl_type = v
  onQueryChange()
}

// ---- 双击行跳转 K 线页（任务 4.3）----
// bsp 周期词表（D1：D/W/M/30m/60m）→ K 线页词表（1d/1w/1M/30m/60m），
// 30m/60m 两页同值；空周期（全部）不带 period，K 线页保持其默认日线
const KL_TO_KLINE_PERIOD: Record<string, string> = {
  D: '1d',
  W: '1w',
  M: '1M',
  '30m': '30m',
  '60m': '60m',
}
const router = useRouter()

function onRowDblClick(row: BspRecord) {
  const q: { code: string; period?: string } = { code: row.code }
  const period = row.kl_type ? KL_TO_KLINE_PERIOD[row.kl_type] : undefined
  if (period) q.period = period
  router.push({ name: 'kline', query: q })
}

// ---- 多选 ----
const selected = ref<BspRecord[]>([])
const selectedCount = ref(0)
const hasSelected = ref(false)
function onSelectionChange(rows: BspRecord[]) {
  selected.value = rows
  selectedCount.value = rows.length
  hasSelected.value = rows.length > 0
}

// ---- 区间套 ----
const nestingVisible = ref(false)
const nestingRecord = ref<BspRecord | null>(null)
function openNesting(row: BspRecord) {
  nestingRecord.value = row
  nestingVisible.value = true
}

// ---- 批量加入自选 ----
const watchlistDialogVisible = ref(false)
const watchlistFolderId = ref<number | null>(null)
const watchFolders = ref<WatchFolder[]>([])
const addingWatch = ref(false)

async function onBatchWatchlist() {
  if (!hasSelected.value) return
  try {
    watchFolders.value = await getFolders()
    watchlistFolderId.value = watchFolders.value[0]?.id ?? null
    watchlistDialogVisible.value = true
  } catch {
    // 失败已处理
  }
}

async function confirmBatchWatchlist() {
  if (!watchlistFolderId.value) {
    ElMessage.warning('请选择目标文件夹')
    return
  }
  addingWatch.value = true
  try {
    // 按 code 去重
    const codes = Array.from(new Set(selected.value.map((r) => r.code)))
    await Promise.all(codes.map((c) => addStock(watchlistFolderId.value!, c)))
    ElMessage.success(`已加入 ${codes.length} 只到自选`)
    watchlistDialogVisible.value = false
  } catch {
    // 失败已处理
  } finally {
    addingWatch.value = false
  }
}

// ---- 加入监控 ----
function onBatchMonitor() {
  if (!hasSelected.value) return
  ElMessage.success(`已将 ${selectedCount.value} 条记录加入监控（演示）`)
}

// ---- 行级加入监控（design D8 修订 + D12 价格联动，任务 4.5/4.9）----
// 弹窗：股票/周期只读 + 买点时间（默认 = 该行买卖点时间，可编辑，「此刻」置当前时间）
// + 买卖点价格随买点时间联动（GET /bsp/price-at：所选时间点监控周期最近收盘价）；
// 提交 POST /api/monitor（entry_price = 联动后价格）。
// monitor_start_time 传 'YYYY-MM-DD HH:mm:ss'：monitor 表存 VARCHAR，
// 消费方（DuckDB time_key 字符串比较 / LLM prompt 文本）均兼容该格式。
const monitorDialogVisible = ref(false)
const monitorRow = ref<BspRecord | null>(null)
const monitorStartTime = ref<string>('')
const addingMonitor = ref(false)
// D12 价格联动：弹窗内显示与提交用的价格（初始 = 行买卖点价格，随时间变化更新）
const monitorPrice = ref<number>(0)
const priceLoading = ref(false)
let priceSeq = 0
let priceTimer: ReturnType<typeof setTimeout> | null = null

/** ms 时间戳 → 'YYYY-MM-DD HH:mm:ss'（含秒，与提交格式一致） */
function toDateTimeStr(ts: number) {
  const d = new Date(ts)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

/** 按买点时间取价（design D12）：失败/404 保留原价格并提示 */
async function fetchMonitorPrice(time: string) {
  const row = monitorRow.value
  if (!row || !time) return
  const seq = ++priceSeq
  priceLoading.value = true
  try {
    const r = await getPriceAt(row.code, row.kl_type, time)
    if (seq !== priceSeq) return // 过期响应丢弃
    monitorPrice.value = r.price
  } catch {
    if (seq !== priceSeq) return
    ElMessage.warning('所选时间无 K 线数据，保留原买卖点价格')
  } finally {
    if (seq === priceSeq) priceLoading.value = false
  }
}

/** 买点时间变化 → 300ms 防抖取价（design D12） */
function onMonitorTimeChange() {
  if (priceTimer) clearTimeout(priceTimer)
  if (!monitorStartTime.value) return
  priceTimer = setTimeout(() => fetchMonitorPrice(monitorStartTime.value), 300)
}

function openMonitorDialog(row: BspRecord) {
  monitorRow.value = row
  // 默认值 = 该行买卖点时间（bsp_date 为 ms 时间戳，已含时分秒）
  monitorStartTime.value = toDateTimeStr(row.bsp_date)
  monitorPrice.value = row.bsp_price
  monitorDialogVisible.value = true
  // 默认时间也触发一次联动（语义统一：价格 = 所选时间点收盘价）
  fetchMonitorPrice(monitorStartTime.value)
}

/** 「此刻」按钮：买点时间置为当前时间（经 date-picker change 事件触发联动） */
function setMonitorTimeNow() {
  monitorStartTime.value = toDateTimeStr(Date.now())
  onMonitorTimeChange()
}

async function confirmAddMonitor() {
  const row = monitorRow.value
  if (!row) {
    console.warn('[confirmAddMonitor] 无上下文行，忽略提交', { dialogVisible: monitorDialogVisible.value })
    return
  }
  if (!monitorStartTime.value) {
    ElMessage.warning('请设置买点时间')
    return
  }
  addingMonitor.value = true
  try {
    await createMonitor({
      code: row.code,
      kl_type: row.kl_type,
      entry_price: monitorPrice.value, // D12：联动后的所选时间点价格
      monitor_start_time: monitorStartTime.value,
    })
    ElMessage.success(`已将「${row.name}」加入监控`)
    monitorDialogVisible.value = false
  } catch {
    // 失败已由 axios 拦截器统一 ElMessage.error（含后端 detail），此处仅保留弹窗供重试
  } finally {
    addingMonitor.value = false
  }
}

// ---- 工具 ----
function formatPrice(v: number) {
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
function formatDate(ts: number) {
  const d = new Date(ts)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

// ---- 买卖点时间格式化（design D10，任务 4.4）----
// bsp_date 是 ms 时间戳（后端已按 time_key 转出，携带时分秒）。
// 按行周期区分：分钟级（30m/60m）显示日期+时分；日线及以上（D/W/M）只显示日期
// （time_key 为 00:00，显示时分是冗余噪音）。与 NestingDrawer 共用同一语义。
const MINUTE_KL_TYPES = new Set(['30m', '60m'])
function formatBspTime(row: { bsp_date: number; kl_type: string }) {
  const d = new Date(row.bsp_date)
  const date = formatDate(row.bsp_date)
  if (!MINUTE_KL_TYPES.has(row.kl_type)) return date
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${date} ${hh}:${mm}`
}

onMounted(() => {
  loadList()
  loadAggregate()
})

// keep-alive 缓存后再次进入时，重新查询以确保数据时效性
onActivated(() => {
  loadList()
  loadAggregate()
})
</script>

<style scoped>
.bsp-page {
  display: flex;
  flex-direction: column;
  gap: var(--sp-lg);
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
.bsp-tabs :deep(.el-tabs__header) {
  margin: 0;
  padding: 0 var(--sp-md);
}
.bsp-tabs :deep(.el-tabs__nav-wrap::after) {
  background: var(--border-base);
}
.pager {
  display: flex;
  justify-content: flex-end;
  padding: var(--sp-md) var(--sp-lg);
  border-top: 1px solid var(--border-base);
}
.add-dialog-body {
  display: flex;
  flex-direction: column;
  gap: var(--sp-lg);
}
.monitor-ctx {
  display: flex;
  flex-direction: column;
  gap: var(--sp-md);
  padding: var(--sp-md);
  border: 1px solid var(--border-base);
  border-radius: var(--r-md);
}
.monitor-ctx .form-row {
  flex-direction: row;
  align-items: center;
  gap: var(--sp-md);
}
.monitor-ctx .form-row label {
  width: 90px;
  flex-shrink: 0;
}
.ctx-value {
  font-size: 13px;
  color: var(--text-primary);
}
/* D12 价格联动取价中的弱化显示 */
.ctx-value.price-stale {
  opacity: 0.5;
}
.ctx-code {
  margin-left: 6px;
  font-size: 12px;
  color: var(--text-disabled);
}
.monitor-time-row {
  display: flex;
  align-items: center;
  gap: var(--sp-sm);
}
.dialog-hint {
  font-size: 12px;
  color: var(--text-disabled);
  margin: 0;
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
</style>