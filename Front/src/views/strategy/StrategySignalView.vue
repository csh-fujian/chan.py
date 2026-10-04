<template>
  <div class="page-layout">
    <!-- 左侧策略树（design D5 / 任务 5.4）：group_name 分组 → 定义名（组标签）
         → 实例节点（label + 信号计数 badge；is-active 高亮当前实例） -->
    <aside class="panel sidebar reveal reveal--1">
      <div class="sidebar__head">
        策略信号
        <span class="spacer"></span>
      </div>
      <div class="tree">
        <div v-for="group in groupedDefinitions" :key="group.name" class="sidebar__group">
          <div class="sidebar__group-label">{{ group.name }}</div>
          <div v-for="def in group.defs" :key="def.id" class="def-block">
            <!-- 定义名（组标签）+ 新建实例小按钮（manage 语义放开，admin 全权限） -->
            <div class="def-label">
              <span class="def-name" :title="def.name">{{ def.name }}</span>
              <span class="spacer"></span>
              <button
                class="btn btn--ghost btn--sm def-add-btn"
                title="新建实例"
                @click="openCreateInstance(def)"
              >
                <el-icon><Plus /></el-icon>
              </button>
            </div>
            <!-- 实例节点：点击切换实例（保留筛选、重置页码、重新请求） -->
            <div
              v-for="inst in def.instances"
              :key="inst.id"
              class="tree__item"
              :class="{ 'is-active': currentInstanceId === inst.id }"
              @click="selectInstance(inst.id)"
            >
              <span class="inst-label" :title="inst.label">{{ inst.label }}</span>
              <span class="count">{{ inst.signal_count }}</span>
              <!-- 实例操作（任务 5.5 简化实现）：启停开关 + 扫描 + 删除 -->
              <span
                v-if="currentInstanceId === inst.id"
                class="inst-actions"
                @click.stop
              >
                <el-switch
                  :model-value="inst.enabled"
                  size="small"
                  title="启用/停用"
                  @change="(v: any) => onToggleInstance(inst, v)"
                />
                <el-icon class="inst-act" title="立即扫描" @click.stop="onScanInstance(inst)"><Refresh /></el-icon>
                <el-icon class="inst-act inst-act--del" title="删除实例" @click.stop="onDeleteInstance(inst)"><Close /></el-icon>
              </span>
            </div>
            <div v-if="def.instances.length === 0" class="inst-empty">暂无实例</div>
          </div>
        </div>
      </div>
    </aside>

    <!-- 右侧主面板 -->
    <div class="main-panel">
      <div class="strategy-page">
        <!-- 工具栏：股票搜索 | 状态（states 声明驱动）| 方向 | 日期范围 | 查询/重置 -->
        <div class="toolbar reveal reveal--1">
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
          <!-- 状态下拉：options 由当前实例所属定义的 states 声明渲染 -->
          <el-select v-model="query.state" placeholder="状态" style="width: 120px" :disabled="!currentDefinition" @change="onQueryChange">
            <el-option label="全部状态" value="" />
            <el-option
              v-for="s in currentDefinition?.states || []"
              :key="s.value"
              :label="s.label"
              :value="s.value"
            />
          </el-select>
          <el-select v-model="query.direction" placeholder="方向" style="width: 100px" @change="onQueryChange">
            <el-option label="全部方向" value="" />
            <el-option label="买" value="buy" />
            <el-option label="卖" value="sell" />
          </el-select>
          <!-- 日期范围（闭区间，YYYY-MM-DD） -->
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
          <button class="btn btn--primary" @click="onQuery">查询</button>
          <button class="btn btn--default" @click="onReset">重置</button>
        </div>

        <!-- 信号列表（服务端分页）：通用列 + columns 声明驱动私有列 + states 声明着色 -->
        <div class="panel reveal reveal--2">
          <div class="tbl-wrap" v-loading="loading">
            <el-table
              v-if="currentInstanceId != null"
              :key="currentInstanceId"
              :data="records"
              empty-text="暂无信号记录"
              row-key="code"
              @row-click="onRowClick"
            >
              <el-table-column label="名称 / 编码" min-width="140">
                <template #default="{ row }">
                  <div class="cell-stock">
                    <span class="nm">{{ row.name }}</span>
                    <span class="cd mono">{{ row.code }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="行业" min-width="150">
                <template #default="{ row }">
                  <IndustryBadges :industries="row.industries" />
                </template>
              </el-table-column>
              <el-table-column label="信号日期" width="110" align="center">
                <template #default="{ row }">
                  <span class="num">{{ row.signal_date }}</span>
                </template>
              </el-table-column>
              <!-- 状态列：states 声明 color 映射 badge 样式类 -->
              <el-table-column label="状态" width="90" align="center">
                <template #default="{ row }">
                  <span class="badge" :class="stateBadgeClass(row.state)">{{ stateLabel(row.state) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="方向" width="70" align="center">
                <template #default="{ row }">
                  <span class="badge" :class="row.is_buy ? 'badge--rise' : 'badge--fall'">
                    {{ row.is_buy ? '买' : '卖' }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="入场参考价" width="100" align="right" class-name="col-num">
                <template #default="{ row }">
                  <span class="num">{{ formatPrice(row.entry_ref_price) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="止损参考价" width="100" align="right" class-name="col-num">
                <template #default="{ row }">
                  <span class="num">{{ formatPrice(row.stop_ref_price) }}</span>
                </template>
              </el-table-column>
              <!-- 私有列（columns 声明驱动，row.payload[key] 取值渲染） -->
              <el-table-column
                v-for="col in currentDefinition?.columns || []"
                :key="col.key"
                :label="col.label"
                :width="col.type === 'date' ? 110 : 90"
                :align="col.type === 'date' ? 'center' : 'right'"
                class-name="col-num"
              >
                <template #default="{ row }">
                  <span class="num">{{ formatPayload(row.payload?.[col.key], col.type) }}</span>
                </template>
              </el-table-column>
              <template #empty>
                <EmptyState description="暂无信号记录，请调整筛选条件" />
              </template>
            </el-table>
            <EmptyState v-else description="请在左侧选择策略实例" />
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
        </div>
      </div>
    </div>

    <!-- 新建实例弹窗（params_schema 声明驱动表单） -->
    <InstanceDialog
      v-model:visible="instanceDialogVisible"
      :definition="instanceDialogDef"
      @saved="reloadDefinitions"
    />

    <!-- 信号详情抽屉 -->
    <SignalDrawer
      v-model:visible="drawerVisible"
      :signal="drawerSignal"
      :definition="currentDefinition"
      :instance-id="currentInstanceId"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import type { AutocompleteInstance } from 'element-plus'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Plus, Refresh, Close } from '@element-plus/icons-vue'
import IndustryBadges from '@/components/ui/IndustryBadges.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import InstanceDialog from './InstanceDialog.vue'
import SignalDrawer from './SignalDrawer.vue'
import {
  getStrategyDefinitions,
  getStrategySignals,
  setInstanceEnabled,
  deleteInstance,
  scanInstance,
} from '@/api/modules/strategy'
import { searchStocks } from '@/api/modules/stock'
import type {
  StrategyDefinition,
  StrategyInstance,
  StrategySignalRow,
  StrategyColumnDecl,
} from '@/api/types'

/**
 * 策略信号页（strategy-signal-page design D5 / 任务 5.4）：
 * 侧栏策略树（定义分组 → 实例节点 + 计数）+ 工具栏筛选 + 服务端分页信号列表；
 * 私有列 / 状态着色 / 实例表单全部由定义声明驱动渲染（新策略接入零前端改动）。
 */

// ---- 定义与实例树 ----
const definitions = ref<StrategyDefinition[]>([])
const currentInstanceId = ref<number | null>(null)

/** 按 group_name 分组（组内按 sort 升序，对齐后端返回顺序） */
const groupedDefinitions = computed(() => {
  const groups: { name: string; defs: StrategyDefinition[] }[] = []
  for (const def of definitions.value) {
    const g = groups.find((x) => x.name === def.group_name)
    if (g) g.defs.push(def)
    else groups.push({ name: def.group_name, defs: [def] })
  }
  return groups
})

/** 当前实例所属定义（states/columns 声明来源） */
const currentDefinition = computed<StrategyDefinition | null>(() => {
  if (currentInstanceId.value == null) return null
  for (const def of definitions.value) {
    if (def.instances.some((i) => i.id === currentInstanceId.value)) return def
  }
  return null
})

/** 当前实例对象（启停等操作用） */
const currentInstance = computed<StrategyInstance | null>(() => {
  if (currentInstanceId.value == null) return null
  return currentDefinition.value?.instances.find((i) => i.id === currentInstanceId.value) || null
})

async function loadDefinitions() {
  try {
    definitions.value = await getStrategyDefinitions()
    // 默认选中第一个实例（无选中时）
    if (currentInstanceId.value == null) {
      for (const def of definitions.value) {
        if (def.instances.length > 0) {
          currentInstanceId.value = def.instances[0].id
          break
        }
      }
    }
  } catch (e) {
    console.warn('[StrategySignalView.loadDefinitions] 策略定义加载失败', { error: e })
    definitions.value = []
  }
}

/** 实例变更后重载树（新建/删除/启停/扫描计数变化后侧栏同步） */
async function reloadDefinitions() {
  await loadDefinitions()
  await loadList()
}

// ---- 查询状态（切换实例：保留筛选、重置页码、重新请求） ----
const query = reactive({
  page: 1,
  page_size: 20,
  state: '',
  direction: '' as 'buy' | 'sell' | '',
  date_from: '',
  date_to: '',
  keyword: '',
})

const dateRange = ref<[string, string] | null>(null)

function syncDateRangeToQuery() {
  query.date_from = dateRange.value?.[0] || ''
  query.date_to = dateRange.value?.[1] || ''
}

const loading = ref(false)
const records = ref<StrategySignalRow[]>([])
const total = ref(0)

async function loadList() {
  if (currentInstanceId.value == null) {
    records.value = []
    total.value = 0
    return
  }
  loading.value = true
  syncDateRangeToQuery()
  try {
    const res = await getStrategySignals({
      instance_id: currentInstanceId.value,
      page: query.page,
      page_size: query.page_size,
      state: query.state || undefined,
      direction: query.direction || undefined,
      date_from: query.date_from || undefined,
      date_to: query.date_to || undefined,
      keyword: query.keyword || undefined,
    })
    records.value = res.list
    total.value = res.total
  } catch (e) {
    console.warn('[StrategySignalView.loadList] 信号查询失败', {
      instanceId: currentInstanceId.value,
      error: e,
    })
    records.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

// ---- 切换实例（spec：列表切换为该实例信号集，筛选条件保留） ----
async function selectInstance(id: number) {
  if (currentInstanceId.value === id) return
  currentInstanceId.value = id
  // 状态筛选取值域随定义变化：不在新定义 states 内的值回退「全部」
  const def = currentDefinition.value
  if (def && query.state && !def.states.some((s) => s.value === query.state)) {
    query.state = ''
  }
  query.page = 1
  await loadList()
}

// ---- 状态着色 / 文案（states 声明驱动） ----
const COLOR_CLASS: Record<string, string> = {
  info: 'badge--info',
  warning: 'badge--warning',
  danger: 'badge--rise',
  success: 'badge--fall',
}
function stateDeclOf(value: string) {
  return currentDefinition.value?.states.find((s) => s.value === value) || null
}
function stateLabel(value: string) {
  return stateDeclOf(value)?.label || value
}
function stateBadgeClass(value: string) {
  const decl = stateDeclOf(value)
  return COLOR_CLASS[decl?.color || 'info'] || 'badge--info'
}

// ---- 私有列格式化（columns 声明 type 驱动） ----
function formatPayload(v: number | string | undefined, type: StrategyColumnDecl['type']): string {
  if (v == null) return '--'
  if (type === 'float') return Number(v).toFixed(2)
  return String(v)
}

function formatPrice(v: number | null | undefined) {
  if (v == null) return '--'
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

// ---- 股票搜索（el-autocomplete 模糊下拉选 code，复制 BspView 实现模式） ----
interface StockSuggestion {
  value: string
  code: string
  name: string
  /** 无匹配候选的空态提示项，不参与查询 */
  placeholder?: boolean
}
const acRef = ref<AutocompleteInstance | null>(null)
const keywordInput = ref('')
const selectedCode = ref('')

async function queryStocks(q: string, cb: (items: StockSuggestion[]) => void) {
  const text = q.trim()
  if (!text) {
    cb([])
    return
  }
  try {
    const list = await searchStocks(text)
    if (!list.length) {
      cb([{ value: text, code: '', name: '无匹配候选', placeholder: true }])
      return
    }
    cb(list.map((s) => ({ value: s.code, code: s.code, name: s.name })))
  } catch {
    cb([])
  }
}

function onSelectSuggestion(item: StockSuggestion) {
  if (item.placeholder) return
  selectedCode.value = item.code
  keywordInput.value = item.code
  acRef.value?.close()
}

function onKeywordClear() {
  selectedCode.value = ''
}

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
  query.state = ''
  query.direction = ''
  dateRange.value = null
  syncDateRangeToQuery()
  query.page = 1
  loadList()
}

// ---- 新建实例（params_schema 声明驱动表单，InstanceDialog 承载） ----
const instanceDialogVisible = ref(false)
const instanceDialogDef = ref<StrategyDefinition | null>(null)

function openCreateInstance(def: StrategyDefinition) {
  instanceDialogDef.value = def
  instanceDialogVisible.value = true
}

// ---- 实例操作（任务 5.5 简化实现：节点尾部开关 / 扫描 / 删除） ----
async function onToggleInstance(inst: StrategyInstance, enabled: boolean) {
  try {
    await setInstanceEnabled(inst.id, enabled)
    inst.enabled = enabled
    ElMessage.success(enabled ? `实例「${inst.label}」已启用` : `实例「${inst.label}」已停用（信号仍可查询）`)
  } catch {
    // 失败已由拦截器提示；定义树下次重载时状态回滚
  }
}

async function onScanInstance(inst: StrategyInstance) {
  try {
    const res = await scanInstance(inst.id)
    ElMessage.success(res.message || `实例「${inst.label}」补算完成`)
    await reloadDefinitions()
  } catch {
    // 失败已由拦截器提示（如实例已停用）
  }
}

async function onDeleteInstance(inst: StrategyInstance) {
  const def = currentDefinition.value
  const signalNote = inst.signal_count > 0 ? `其 ${inst.signal_count} 条历史信号将被一并删除。` : ''
  try {
    await ElMessageBox.confirm(
      `确定删除实例「${inst.label}」吗？实例不可恢复，${signalNote}`,
      '删除实例',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
  } catch {
    return // 用户取消
  }
  try {
    await deleteInstance(inst.id)
    ElMessage.success(`实例「${inst.label}」已删除`)
    // 删除的是当前选中实例 → 回退到首个可用实例
    if (currentInstanceId.value === inst.id) {
      currentInstanceId.value = null
      for (const d of definitions.value) {
        if (d.instances.some((i) => i.id === inst.id)) {
          d.instances = d.instances.filter((i) => i.id !== inst.id)
        }
        if (currentInstanceId.value == null && d.instances.length > 0) {
          currentInstanceId.value = d.instances[0].id
        }
      }
      if (def) def.instances = def.instances.filter((i) => i.id !== inst.id)
    } else {
      // 其他实例：就地从树中移除（避免整树闪烁）
      for (const d of definitions.value) {
        d.instances = d.instances.filter((i) => i.id !== inst.id)
      }
    }
    await loadList()
  } catch (e) {
    console.warn('[StrategySignalView.onDeleteInstance] 删除实例失败', { id: inst.id, error: e })
  }
}

// ---- 详情抽屉 ----
const drawerVisible = ref(false)
const drawerSignal = ref<StrategySignalRow | null>(null)

function onRowClick(row: StrategySignalRow) {
  drawerSignal.value = row
  drawerVisible.value = true
}

// ---- 生命周期 ----
onMounted(async () => {
  await loadDefinitions()
  await loadList()
})
</script>

<style scoped>
.strategy-page {
  display: flex;
  flex-direction: column;
  gap: var(--sp-lg);
  flex: 1;
}
/* ---- 策略树（定义分组 → 定义块 → 实例节点） ---- */
.def-block {
  padding: 2px 0 6px;
}
.def-label {
  display: flex;
  align-items: center;
  padding: 4px 10px 2px;
}
.def-name {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.def-add-btn {
  padding: 0 4px;
  min-width: 22px;
  height: 20px;
}
.inst-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* 实例节点尾部操作区（仅当前选中实例展开，避免节点拥挤） */
.inst-actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: 2px;
  flex-shrink: 0;
}
.inst-act {
  width: 14px;
  height: 14px;
  border-radius: var(--r-sm);
  color: var(--text-disabled);
  cursor: pointer;
  flex-shrink: 0;
}
.inst-act:hover {
  color: var(--accent-hover);
  background: var(--accent-dim);
}
.inst-act--del:hover {
  color: var(--rise);
  background: var(--rise-dim);
}
.inst-empty {
  padding: 4px 10px;
  font-size: 11px;
  color: var(--text-disabled);
}
/* ---- 表格 / 分页（对齐 BspView 样式） ---- */
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
.pager {
  display: flex;
  justify-content: flex-end;
  padding: var(--sp-md) var(--sp-lg);
  border-top: 1px solid var(--border-base);
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
