<template>
  <div class="page-layout">
    <!-- 左侧策略任务树（strategy-task-redesign 4.2）：
         策略大类（group_name）→ 策略定义 → 任务节点（按 user_group 分组组织，含信号计数） -->
    <aside class="panel sidebar reveal reveal--1">
      <div class="sidebar__head">
        策略任务
        <span class="spacer"></span>
      </div>
      <div class="tree">
        <div v-for="group in groupedDefinitions" :key="group.name" class="sidebar__group">
          <div class="sidebar__group-label">{{ group.name }}</div>
          <div v-for="def in group.defs" :key="def.id" class="def-block">
            <!-- 策略名（组标签）：点击过滤任务列表到该策略；+ 新建任务小按钮 -->
            <div class="def-label" @click="onDefLabelClick(def)">
              <span class="def-name" :title="def.name">{{ def.name }}</span>
              <span class="spacer"></span>
              <button
                class="btn btn--ghost btn--sm def-add-btn"
                title="新建任务"
                @click="openCreateTask(def)"
              >
                <el-icon><Plus /></el-icon>
              </button>
            </div>
            <!-- 任务节点：按 user_group 分组组织展示 -->
            <div
              v-for="ug in taskGroupsOf(def)"
              :key="ug.name"
              class="task-group"
            >
              <div v-if="ug.name" class="task-group-label">{{ ug.name }}</div>
              <!-- 任务节点：点击切换任务（信号列表切换为该任务信号集，筛选保留、页码重置） -->
              <div
                v-for="task in ug.tasks"
                :key="task.id"
                class="tree__item"
                :class="{ 'is-active': currentTaskId === task.id }"
                @click="selectTask(task.id)"
              >
                <span class="task-label" :title="task.label">{{ task.label }}</span>
                <span class="badge task-mode" :class="task.mode === 'persistent' ? 'badge--accent' : 'badge--default'">
                  {{ task.mode === 'persistent' ? '长期' : '测试' }}
                </span>
                <span class="count">{{ task.signal_count }}</span>
              </div>
            </div>
            <div v-if="def.tasks.length === 0" class="task-empty">暂无任务</div>
          </div>
        </div>
      </div>
    </aside>

    <!-- 右侧主面板 -->
    <div class="main-panel">
      <div class="strategy-page">
        <!-- 视图 Tab：任务列表 | 信号列表 -->
        <div class="view-tabs reveal reveal--1">
          <button
            v-for="t in viewTabs"
            :key="t.key"
            class="tab-btn"
            :class="{ 'is-active': activeView === t.key }"
            @click="activeView = t.key"
          >
            {{ t.label }}
          </button>
        </div>

        <!-- ===== 任务列表 Tab ===== -->
        <div v-show="activeView === 'tasks'" class="panel reveal reveal--2">
          <div class="tbl-wrap" v-loading="tasksLoading">
            <el-table :data="filteredTasks" empty-text="暂无任务" row-key="id">
              <el-table-column label="任务名" min-width="150">
                <template #default="{ row }">
                  <div class="cell-task">
                    <span class="nm">{{ row.label }}</span>
                    <span class="sub">{{ defNameOf(row.strategy_id) }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="分组" width="110" align="center">
                <template #default="{ row }">
                  <span class="badge badge--default">{{ row.user_group || '未分组' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="形态" width="80" align="center">
                <template #default="{ row }">
                  <span class="badge" :class="row.mode === 'persistent' ? 'badge--accent' : 'badge--info'">
                    {{ row.mode === 'persistent' ? '长期' : '测试' }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="90" align="center">
                <template #default="{ row }">
                  <span class="badge" :class="STATUS_COLOR[row.status] || 'badge--default'">
                    {{ STATUS_LABEL[row.status] || row.status }}
                  </span>
                </template>
              </el-table-column>
              <!-- 执行进度：el-progress 进度条 + 已扫/总数 -->
              <el-table-column label="执行进度" min-width="170">
                <template #default="{ row }">
                  <div class="cell-progress">
                    <el-progress
                      :percentage="progressPct(row)"
                      :stroke-width="6"
                      :show-text="false"
                      :color="row.status === 'done' ? '#2EBD85' : undefined"
                    />
                    <span class="num progress-text">
                      {{ row.progress_scanned }} / {{ row.progress_total }}
                      <span v-if="row.status === 'running'" class="running-hint">扫描中</span>
                    </span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="信号数" width="80" align="right" class-name="col-num">
                <template #default="{ row }">
                  <span class="num link" @click="gotoSignals(row)">{{ row.signal_count }}</span>
                </template>
              </el-table-column>
              <el-table-column label="创建人" width="80" align="center">
                <template #default="{ row }">{{ row.created_by }}</template>
              </el-table-column>
              <el-table-column label="创建时间" width="100" align="center">
                <template #default="{ row }">
                  <span class="num">{{ fmtDate(row.created_at) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="230" align="center" fixed="right">
                <template #default="{ row }">
                  <!-- 启动 / 暂停（按状态互斥） -->
                  <el-button
                    v-if="row.status === 'pending' || row.status === 'paused'"
                    link type="primary" size="small"
                    @click="onStartTask(row)"
                  >启动</el-button>
                  <el-button
                    v-if="row.status === 'running'"
                    link type="warning" size="small"
                    @click="onPauseTask(row)"
                  >暂停</el-button>
                  <!-- 续跑（paused/done 的任务） -->
                  <el-button
                    v-if="row.status === 'paused' || row.status === 'done'"
                    link type="primary" size="small"
                    @click="openResumeDialog(row)"
                  >续跑</el-button>
                  <!-- 编辑（仅 paused） -->
                  <el-button
                    v-if="row.status === 'paused'"
                    link type="primary" size="small"
                    @click="openEditDialog(row)"
                  >编辑</el-button>
                  <!-- 转正（done 的 test 任务） -->
                  <el-button
                    v-if="row.status === 'done' && row.mode === 'test'"
                    link type="primary" size="small"
                    @click="onPromoteTask(row)"
                  >转正</el-button>
                  <!-- 复制 / 删除 -->
                  <el-button link type="primary" size="small" @click="onCopyTask(row)">复制</el-button>
                  <el-button link type="danger" size="small" @click="onDeleteTask(row)">删除</el-button>
                  <!-- 详情 -->
                  <el-button link size="small" @click="openDetail(row)">详情</el-button>
                </template>
              </el-table-column>
              <template #empty>
                <EmptyState description="暂无任务，点击左侧策略名旁的 + 新建" />
              </template>
            </el-table>
          </div>
        </div>

        <!-- ===== 信号列表 Tab（沿用原筛选 + 服务端分页骨架，查询挂 task_id） ===== -->
        <div v-show="activeView === 'signals'" class="signal-view">
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
            <!-- 状态下拉：options 由当前任务所属定义的 states 声明渲染 -->
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

          <!-- 信号列表（服务端分页）：通用列 + columns 声明驱动私有列 + states 声明着色
               + 参数版本标识（strategy-task-redesign：混合参数任务按版本归因） -->
          <div class="panel reveal reveal--2">
            <div class="tbl-wrap" v-loading="loading">
              <el-table
                v-if="currentTaskId != null"
                :key="currentTaskId"
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
                <!-- 参数版本标识（spec：信号行标注产生它的参数版本，如「参数 v2」） -->
                <el-table-column label="参数版本" width="90" align="center">
                  <template #default="{ row }">
                    <span class="badge badge--accent mono">参数 v{{ row.params_version }}</span>
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
                <!-- 私有列（columns 声明驱动，row.payload[key] 取值渲染；
                     pct/price_pct/outcome 新列型兜底（D7/D12）：主列表仍按
                     完整声明渲染全列（通用列不裁剪，仅任务详情裁剪）；
                     pct/price_pct 涨幅分量转百分比文本、price_pct 合并列
                     「价格 | 涨跌幅」双值、outcome 中文标签，保持不报错） -->
                <el-table-column
                  v-for="col in currentDefinition?.columns || []"
                  :key="col.key"
                  :label="col.label"
                  :width="col.type === 'date' ? 110 : col.type === 'outcome' ? 80 : col.type === 'price_pct' ? 140 : 90"
                  :align="col.type === 'date' ? 'center' : 'right'"
                  class-name="col-num"
                >
                  <template #default="{ row }">
                    <!-- price_pct：合并单元格「价格 | 涨跌幅」（D12 兜底渲染，
                         价格分量普通 float 文本，涨幅分量 pct 规则着色） -->
                    <template v-if="col.type === 'price_pct'">
                      <span class="num">{{ fmtPriceComponent(colValue(row, col.priceKey || '')) }}</span>
                      <span class="num pp-sep">|</span>
                      <span class="num" :class="pctClass(colValue(row, col.pctKey || ''))">
                        {{ formatPayload(colValue(row, col.pctKey || ''), 'pct') }}
                      </span>
                    </template>
                    <span
                      v-else
                      class="num"
                      :class="col.type === 'pct' ? pctClass(colValue(row, col.key)) : ''"
                    >{{ formatPayload(colValue(row, col.key), col.type) }}</span>
                  </template>
                </el-table-column>
                <template #empty>
                  <EmptyState description="暂无信号记录，请调整筛选条件" />
                </template>
              </el-table>
              <EmptyState v-else description="请在左侧选择策略任务" />
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
    </div>

    <!-- 新建任务弹窗（4.3：params_schema 驱动表单 + 范围三来源 + 全量兜底） -->
    <TaskDialog
      v-model:visible="taskDialogVisible"
      :definition="taskDialogDef"
      :known-groups="knownGroups"
      @saved="reloadDefinitions"
    />

    <!-- 编辑与续跑弹窗（4.4：paused 编辑 + 重新运行/剩余继续二选一） -->
    <TaskEditDialog
      v-model:visible="editDialogVisible"
      :task="editDialogTask"
      :definition="editDialogDef"
      :known-groups="knownGroups"
      @saved="reloadDefinitions"
    />

    <!-- 续跑选择弹窗（从任务列表「续跑」入口，二选一默认重新运行） -->
    <TaskResumeDialog
      v-model:visible="resumeDialogVisible"
      :task="resumeDialogTask"
      @resumed="reloadDefinitions"
    />

    <!-- 任务详情抽屉（4.5：detail_blocks 渲染器，按 detail_schema 声明渲染） -->
    <TaskDetailDrawer
      v-model:visible="detailVisible"
      :task-id="detailTaskId"
    />

    <!-- 信号详情抽屉 -->
    <SignalDrawer
      v-model:visible="drawerVisible"
      :signal="drawerSignal"
      :definition="currentDefinition"
      :task="currentTask"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import type { AutocompleteInstance } from 'element-plus'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Plus } from '@element-plus/icons-vue'
import IndustryBadges from '@/components/ui/IndustryBadges.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import TaskDialog from './TaskDialog.vue'
import TaskEditDialog from './TaskEditDialog.vue'
import TaskResumeDialog from './TaskResumeDialog.vue'
import TaskDetailDrawer from './TaskDetailDrawer.vue'
import SignalDrawer from './SignalDrawer.vue'
import {
  getStrategyDefinitions,
  getStrategySignals,
  startStrategyTask,
  pauseStrategyTask,
  promoteStrategyTask,
  copyStrategyTask,
  deleteStrategyTask,
} from '@/api/modules/strategy'
import { searchStocks } from '@/api/modules/stock'
import type {
  StrategyDefinition,
  StrategyTask,
  StrategySignalRow,
  StrategyColumnDecl,
} from '@/api/types'

/**
 * 策略任务页（strategy-task-redesign 4.2）：
 * - 侧栏：策略大类 → 策略定义 → 任务树（任务按 user_group 分组组织、含信号计数）
 * - 主区 Tab：任务列表（基础信息/形态/状态/进度条/创建人/创建时间 + 启停/续跑/编辑/转正/复制/删除/详情）
 *   与信号列表（按 task_id 服务端分页，沿用原筛选骨架）
 * - 私有列 / 状态着色 / 任务表单全部由定义声明驱动渲染（新策略接入零前端改动）
 * - running 任务进度轮询 3s（design D4）
 */

// ---- 定义与任务树 ----
const definitions = ref<StrategyDefinition[]>([])
const currentTaskId = ref<number | null>(null)
const tasksLoading = ref(false)

/** 视图 Tab（任务列表 / 信号列表） */
const activeView = ref<'tasks' | 'signals'>('tasks')
const viewTabs = [
  { key: 'tasks' as const, label: '任务列表' },
  { key: 'signals' as const, label: '信号列表' },
]

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

/** 已知分组名集合（创建/编辑弹窗分组下拉可选项来源） */
const knownGroups = computed<string[]>(() => {
  const set = new Set<string>()
  for (const def of definitions.value) {
    for (const t of def.tasks) {
      if (t.user_group) set.add(t.user_group)
    }
  }
  return Array.from(set)
})

/** 定义下任务按 user_group 分组组织（空 user_group 归「未分组」，不显示子标签） */
function taskGroupsOf(def: StrategyDefinition): { name: string; tasks: StrategyTask[] }[] {
  const groups: { name: string; tasks: StrategyTask[] }[] = []
  for (const t of def.tasks) {
    const name = t.user_group || ''
    const g = groups.find((x) => x.name === name)
    if (g) g.tasks.push(t)
    else groups.push({ name, tasks: [t] })
  }
  return groups
}

/** 任务列表数据（全定义任务按创建时间倒序） */
const allTasks = computed<StrategyTask[]>(() =>
  definitions.value.flatMap((d) => d.tasks).sort((a, b) => b.created_at - a.created_at),
)

/** 任务列表展示集：当前侧栏选中定义时仅显示该定义任务，否则全部 */
const filteredTasks = computed<StrategyTask[]>(() => {
  if (selectedDefId.value) return allTasks.value.filter((t) => t.strategy_id === selectedDefId.value)
  return allTasks.value
})

/** 侧栏定义节点选中态（点策略名行切换任务列表过滤；实现见 onDefLabelClick） */
const selectedDefId = ref<string>('')

function onDefLabelClick(def: StrategyDefinition) {
  selectedDefId.value = selectedDefId.value === def.id ? '' : def.id
}

function defNameOf(strategyId: string): string {
  return definitions.value.find((d) => d.id === strategyId)?.name || strategyId
}

/** 当前任务（操作与加监控上下文用） */
const currentTask = computed<StrategyTask | null>(() => {
  if (currentTaskId.value == null) return null
  return allTasks.value.find((t) => t.id === currentTaskId.value) || null
})

/** 当前任务所属定义（states/columns 声明来源） */
const currentDefinition = computed<StrategyDefinition | null>(() => {
  const t = currentTask.value
  if (!t) return null
  return definitions.value.find((d) => d.id === t.strategy_id) || null
})

async function loadDefinitions() {
  tasksLoading.value = true
  try {
    definitions.value = await getStrategyDefinitions()
    // 默认选中第一个任务（无选中时）
    if (currentTaskId.value == null) {
      const first = definitions.value.flatMap((d) => d.tasks)[0]
      if (first) currentTaskId.value = first.id
    }
  } catch (e) {
    console.warn('[StrategySignalView.loadDefinitions] 策略定义加载失败', { error: e })
    definitions.value = []
  } finally {
    tasksLoading.value = false
  }
}

/** 任务变更后重载树（新建/删除/启停/编辑操作后侧栏与列表同步） */
async function reloadDefinitions() {
  await loadDefinitions()
  if (activeView.value === 'signals') await loadList()
}

// ---- 进度轮询（design D4：running 任务 3s 间隔轮询任务列表） ----
let pollTimer: ReturnType<typeof setInterval> | null = null

const hasRunningTask = computed(() => allTasks.value.some((t) => t.status === 'running'))

function ensurePolling() {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    if (!hasRunningTask.value) return
    // 静默刷新：不置 loading，避免表格闪烁
    try {
      definitions.value = await getStrategyDefinitions()
    } catch {
      // 轮询失败静默：下一轮重试
    }
  }, 3000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

// ---- 任务列表操作 ----
const STATUS_LABEL: Record<string, string> = {
  pending: '待执行',
  running: '执行中',
  paused: '已暂停',
  done: '已完成',
}
const STATUS_COLOR: Record<string, string> = {
  pending: 'badge--default',
  running: 'badge--info',
  paused: 'badge--warning',
  done: 'badge--fall',
}

function progressPct(t: StrategyTask): number {
  if (!t.progress_total) return 0
  return Math.min(100, Math.round((t.progress_scanned / t.progress_total) * 100))
}

function fmtDate(ts: number): string {
  const d = new Date(ts)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

async function refreshTree() {
  try {
    definitions.value = await getStrategyDefinitions()
  } catch (e) {
    console.warn('[StrategySignalView.refreshTree] 刷新失败', { error: e })
  }
}

async function onStartTask(task: StrategyTask) {
  try {
    await startStrategyTask(task.id)
    ElMessage.success(`任务「${task.label}」已启动`)
    await refreshTree()
  } catch {
    // 409 等失败已由拦截器提示
  }
}

async function onPauseTask(task: StrategyTask) {
  try {
    await pauseStrategyTask(task.id)
    ElMessage.success(`任务「${task.label}」已暂停，可编辑参数与范围后续跑`)
    await refreshTree()
  } catch {
    // 失败已由拦截器提示
  }
}

async function onPromoteTask(task: StrategyTask) {
  try {
    await ElMessageBox.confirm(
      `确定将任务「${task.label}」转正为长期任务吗？转正后挂入日终调度，每日自动增量扫描；既有信号保留，参数将冻结（调参需复制为新的测试任务）。`,
      '任务转正',
      { type: 'warning', confirmButtonText: '确认转正', cancelButtonText: '取消' },
    )
  } catch {
    return // 用户取消
  }
  try {
    await promoteStrategyTask(task.id)
    ElMessage.success(`任务「${task.label}」已转正为长期任务（纳入日终调度）`)
    await refreshTree()
  } catch (e) {
    console.warn('[StrategySignalView.onPromoteTask] 转正失败', { id: task.id, error: e })
  }
}

async function onCopyTask(task: StrategyTask) {
  try {
    const copy = await copyStrategyTask(task.id)
    ElMessage.success(`已复制为测试任务「${copy.label}」（参数与范围同源，可自由编辑）`)
    await refreshTree()
  } catch (e) {
    console.warn('[StrategySignalView.onCopyTask] 复制失败', { id: task.id, error: e })
  }
}

async function onDeleteTask(task: StrategyTask) {
  const signalNote = task.signal_count > 0 ? `其 ${task.signal_count} 条历史信号与逐股结果将被一并删除。` : '其逐股结果将被一并删除。'
  try {
    await ElMessageBox.confirm(
      `确定删除任务「${task.label}」吗？任务不可恢复，${signalNote}`,
      '删除任务',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
  } catch {
    return // 用户取消
  }
  try {
    await deleteStrategyTask(task.id)
    ElMessage.success(`任务「${task.label}」已删除`)
    // 删除的是当前选中任务 → 回退到首个可用任务
    if (currentTaskId.value === task.id) {
      currentTaskId.value = null
      const first = definitions.value.flatMap((d) => d.tasks).find((t) => t.id !== task.id)
      if (first) currentTaskId.value = first.id
    }
    await refreshTree()
    await loadList()
  } catch (e) {
    console.warn('[StrategySignalView.onDeleteTask] 删除任务失败', { id: task.id, error: e })
  }
}

/** 点击信号数跳到信号列表 Tab（选中该任务） */
function gotoSignals(task: StrategyTask) {
  if (currentTaskId.value !== task.id) {
    currentTaskId.value = task.id
    query.page = 1
  }
  activeView.value = 'signals'
  loadList()
}

// ---- 信号查询状态（切换任务：保留筛选、重置页码、重新请求） ----
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
  if (currentTaskId.value == null) {
    records.value = []
    total.value = 0
    return
  }
  loading.value = true
  syncDateRangeToQuery()
  try {
    const res = await getStrategySignals({
      task_id: currentTaskId.value,
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
      taskId: currentTaskId.value,
      error: e,
    })
    records.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

// ---- 切换任务（spec：信号列表切换为该任务信号集，筛选条件保留） ----
async function selectTask(id: number) {
  if (currentTaskId.value === id) return
  currentTaskId.value = id
  // 状态筛选取值域随定义变化：不在新定义 states 内的值回退「全部」
  const def = currentDefinition.value
  if (def && query.state && !def.states.some((s) => s.value === query.state)) {
    query.state = ''
  }
  query.page = 1
  if (activeView.value === 'signals') await loadList()
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
function formatPayload(v: number | string | null | undefined, type: StrategyColumnDecl['type']): string {
  if (v == null) return '--'
  if (type === 'float') return Number(v).toFixed(2)
  // pct/outcome/price_pct 新列型兜底（strategy-signal-outcome D7/D12）：
  // /signals 独立页按完整声明渲染全列（不裁剪通用列，也渲染 price_pct
  // 合并列——价格分量普通文本 + 涨幅分量 pct 规则），保证不显示裸小数
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

/** price_pct 合并列兜底（D12/6.6）：价格分量 float 文本（不足 '--'） */
function fmtPriceComponent(v: number | string | null | undefined): string {
  if (v == null || v === '') return '--'
  const n = Number(v)
  if (!Number.isFinite(n)) return '--'
  return n.toFixed(2)
}

/** 列取值兜底（strategy-signal-outcome 5.1）：先 payload[key]，无键回退行级
 *  字段（ret_7d 等绩效列与 outcome 不在 payload） */
function colValue(row: StrategySignalRow, key: string): number | string | null | undefined {
  const pv = row.payload?.[key]
  if (pv !== undefined) return pv
  return row[key as keyof StrategySignalRow] as number | string | null | undefined
}

/** pct 列着色（A 股红涨绿跌） */
function pctClass(v: number | string | null | undefined): string {
  if (v == null || v === '') return ''
  const n = Number(v)
  if (!Number.isFinite(n) || n === 0) return ''
  return n > 0 ? 'text-rise' : 'text-fall'
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

// ---- 新建任务（4.3 TaskDialog 承载） ----
const taskDialogVisible = ref(false)
const taskDialogDef = ref<StrategyDefinition | null>(null)

function openCreateTask(def: StrategyDefinition) {
  taskDialogDef.value = def
  taskDialogVisible.value = true
}

// ---- 编辑与续跑（4.4 TaskEditDialog / TaskResumeDialog 承载） ----
const editDialogVisible = ref(false)
const editDialogTask = ref<StrategyTask | null>(null)
const editDialogDef = ref<StrategyDefinition | null>(null)

function openEditDialog(task: StrategyTask) {
  editDialogTask.value = task
  editDialogDef.value = definitions.value.find((d) => d.id === task.strategy_id) || null
  editDialogVisible.value = true
}

const resumeDialogVisible = ref(false)
const resumeDialogTask = ref<StrategyTask | null>(null)

function openResumeDialog(task: StrategyTask) {
  resumeDialogTask.value = task
  resumeDialogVisible.value = true
}

// ---- 任务详情（4.5 TaskDetailDrawer 承载） ----
const detailVisible = ref(false)
const detailTaskId = ref<number | null>(null)

function openDetail(task: StrategyTask) {
  detailTaskId.value = task.id
  detailVisible.value = true
}

// ---- 信号详情抽屉 ----
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
  ensurePolling()
})

onUnmounted(stopPolling)
</script>

<style scoped>
.strategy-page {
  display: flex;
  flex-direction: column;
  gap: var(--sp-lg);
  flex: 1;
}
/* ---- 视图 Tab ---- */
.view-tabs {
  display: flex;
  gap: var(--sp-sm);
}
.tab-btn {
  padding: 6px 16px;
  font-size: 13px;
  color: var(--text-secondary);
  background: var(--bg-surface);
  border: 1px solid var(--border-base);
  border-radius: var(--r-md);
  cursor: pointer;
  transition: all 0.15s;
}
.tab-btn:hover {
  color: var(--text-primary);
}
.tab-btn.is-active {
  color: var(--accent-hover);
  background: var(--accent-dim);
  border-color: var(--accent-border);
  font-weight: 500;
}
/* ---- 策略树（大类 → 策略 → 任务按 user_group 分组） ---- */
.def-block {
  padding: 2px 0 6px;
}
.def-label {
  display: flex;
  align-items: center;
  padding: 4px 10px 2px;
  cursor: pointer;
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
.task-group {
  padding: 0;
}
.task-group-label {
  padding: 3px 10px 1px 18px;
  font-size: 11px;
  color: var(--text-disabled);
}
.task-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.task-mode {
  flex-shrink: 0;
  margin-left: 4px;
  transform: scale(0.86);
}
.task-empty {
  padding: 4px 10px;
  font-size: 11px;
  color: var(--text-disabled);
}
/* ---- 任务列表 ---- */
.cell-task {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}
.cell-task .nm {
  color: var(--text-primary);
  font-size: 13px;
}
.cell-task .sub {
  color: var(--text-disabled);
  font-size: 11px;
}
.cell-progress {
  display: flex;
  align-items: center;
  gap: var(--sp-sm);
  min-width: 0;
}
.cell-progress :deep(.el-progress) {
  flex: 1;
  min-width: 60px;
}
.progress-text {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
}
.running-hint {
  margin-left: 4px;
  color: var(--accent-hover);
}
.num.link {
  color: var(--accent-hover);
  cursor: pointer;
}
.num.link:hover {
  text-decoration: underline;
}
/* ---- 信号视图（沿用原骨架） ---- */
.signal-view {
  display: flex;
  flex-direction: column;
  gap: var(--sp-lg);
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
/* price_pct 合并列两值分隔符（D12：弱化分隔符视觉层级） */
.pp-sep {
  color: var(--text-disabled);
  margin: 0 2px;
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
