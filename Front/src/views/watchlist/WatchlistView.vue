<template>
  <div class="watchlist-layout">
    <!-- 左侧文件夹树 -->
    <aside class="panel folder-panel reveal reveal--1">
      <div class="panel__head">
        自选
        <span class="spacer"></span>
        <button class="btn btn--ghost btn--sm" title="新建文件夹" @click="openCreateFolder">
          <span class="icon-plus"></span> 新建
        </button>
      </div>
      <div class="tree">
        <!-- 「全部」虚拟节点：渲染在 draggable 容器外，固定首行，不参与拖拽/删除 -->
        <div
          class="tree__item"
          :class="{ 'is-active': activeKey === 'all' }"
          @click="selectFolder('all')"
        >
          <el-icon class="tree__icon"><Folder /></el-icon>
          <span>全部</span>
          <span class="count">{{ totalCount }}</span>
        </div>
        <!-- 用户文件夹：长按 200ms 进入拖拽排序，短按仍为点击选中 -->
        <draggable
          :list="folders"
          item-key="id"
          tag="div"
          class="tree__drag"
          :delay="200"
          :delay-on-touch-only="false"
          :touch-start-threshold="4"
          filter=".folder-edit, .folder-del"
          :prevent-on-filter="false"
          @start="onFolderDragStart"
          @end="onFolderDragEnd"
        >
          <template #item="{ element: f }">
            <div
              class="tree__item"
              :class="{ 'is-active': activeKey === String(f.id) }"
              @click="selectFolder(String(f.id))"
            >
              <el-icon class="tree__icon"><Folder /></el-icon>
              <span class="folder-name" :title="f.name">{{ f.name }}</span>
              <span class="count">{{ f.codes.length }}</span>
              <el-icon
                class="folder-edit"
                title="重命名文件夹"
                @click.stop="openRenameFolder(f)"
              ><EditPen /></el-icon>
              <el-icon
                class="folder-del"
                title="删除文件夹"
                @click.stop="onDeleteFolder(f)"
              ><Close /></el-icon>
            </div>
          </template>
        </draggable>
      </div>
    </aside>

    <!-- 右侧主面板 -->
    <div class="main-panel">
      <!-- 工具条 -->
      <div class="toolbar reveal reveal--2">
        <!-- 股票搜索：模糊下拉选 code，点「搜索」才触发查询 -->
        <el-autocomplete
          ref="acRef"
          v-model="keyword"
          :fetch-suggestions="queryStocks"
          :trigger-on-focus="false"
          :debounce="300"
          placeholder="搜索代码 / 名称 / 拼音"
          :prefix-icon="Search"
          clearable
          style="width: 240px"
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
        <button class="btn btn--default" @click="onSearch">搜索</button>
        <button class="btn btn--default" @click="onReset">重置</button>
        <span class="spacer"></span>
        <button class="btn btn--primary" @click="addDialogVisible = true">
          <span class="icon-plus"></span> 添加股票
        </button>
        <button class="btn btn--default" :disabled="!hasSelected" @click="onBatchMonitor">
          批量加入监控
        </button>
        <button class="btn btn--default" :disabled="!hasSelected" @click="onBatchRemove">
          批量移出
        </button>
      </div>

      <!-- 股票表格 -->
      <div class="panel reveal reveal--3" v-loading="loading">
        <div class="tbl-wrap" ref="tblWrapRef">
          <el-table
            :data="pagedStocks"
            empty-text="该文件夹暂无股票"
            @selection-change="onSelectionChange"
            @row-dblclick="onRowDblClick"
            @sort-change="onSortChange"
            row-key="code"
          >
            <el-table-column type="selection" width="44" reserve-selection />
            <el-table-column label="名称 / 编码" width="200">
              <template #default="{ row }">
                <div class="cell-stock">
                  <span
                    class="row-drag-handle"
                    :class="{ 'is-disabled': rowDragDisabled }"
                    :data-code="row.code"
                    :title="rowDragDisabled ? '列排序或「全部」视图下不支持拖拽' : '拖拽调整顺序'"
                  ><el-icon><Rank /></el-icon></span>
                  <div class="cell-stock-text">
                    <span class="nm">{{ row.name }}</span>
                    <span class="cd mono">{{ row.code }}</span>
                  </div>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="股价" width="120" align="right" sortable :sort-by="'price'">
              <template #default="{ row }">
                <span class="num">{{ formatPrice(row.price) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="涨跌幅" width="130" align="right" sortable :sort-by="'change_pct'">
              <template #default="{ row }">
                <ChangeBadge :value="row.change_pct" />
              </template>
            </el-table-column>
            <el-table-column label="行业" min-width="180">
              <template #default="{ row }">
                <IndustryBadges :industries="row.industries" />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="220" align="right">
              <template #default="{ row }">
                <el-dropdown trigger="click" @command="(cmd: string) => onMove(row, cmd)">
                  <button class="row-action">移动</button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item
                        v-for="f in folders"
                        :key="f.id"
                        :command="String(f.id)"
                        :disabled="currentFolderId === f.id"
                      >
                        {{ f.name }}
                      </el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
                <button class="row-action" @click="openMonitorDialog(row)">加入监控</button>
                <button class="row-action row-action--danger" @click="onRemove(row)">移出</button>
              </template>
            </el-table-column>
            <template #empty>
              <EmptyState description="该文件夹暂无股票，点击「添加股票」加入自选" />
            </template>
          </el-table>
        </div>

        <!-- 分页（数据源为服务端查询结果） -->
        <div class="pager" v-if="folderStocks.length > 0">
          <el-pagination
            v-model:current-page="page"
            v-model:page-size="pageSize"
            :total="folderStocks.length"
            :page-sizes="[20]"
            layout="total, prev, pager, next, jumper"
            background
          />
        </div>
      </div>
    </div>

    <!-- 文件夹弹窗：新建 / 重命名 复用同一对话框（D6） -->
    <el-dialog
      v-model="folderDialogVisible"
      :title="folderDialogMode === 'create' ? '新建文件夹' : '重命名文件夹'"
      width="420px"
      append-to-body
    >
      <el-form @submit.prevent>
        <el-form-item label="文件夹名">
          <el-input v-model="folderName" placeholder="请输入文件夹名" autofocus />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="folderDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="folderSaving" @click="onSubmitFolder">确认</el-button>
      </template>
    </el-dialog>

    <!-- 添加股票弹窗 -->
    <el-dialog v-model="addDialogVisible" title="添加股票到自选" width="520px" append-to-body>
      <div class="add-dialog-body">
        <div class="form-row">
          <label>目标文件夹</label>
          <el-select v-model="addFolderId" placeholder="选择文件夹" style="width: 100%">
            <el-option v-for="f in folders" :key="f.id" :label="f.name" :value="f.id" />
          </el-select>
        </div>
        <div class="form-row">
          <label>股票编码</label>
          <el-select
            v-model="addStockCode"
            filterable
            remote
            :remote-method="searchStock"
            placeholder="输入代码 / 名称 / 拼音搜索"
            style="width: 100%"
            :loading="stockSearching"
          >
            <el-option
              v-for="s in stockOptions"
              :key="s.code"
              :label="`${s.name} (${s.code})`"
              :value="s.code"
            />
          </el-select>
        </div>
        <p class="dialog-hint">输入股票编码（如 sz.000001）从全市场搜索后添加到目标文件夹。</p>
      </div>
      <template #footer>
        <el-button @click="addDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="adding" @click="onAddStock">确认加入</el-button>
      </template>
    </el-dialog>

    <!-- 加入监控弹窗（design D9/D10，任务 7.3/7.4）：复用 BspView 弹窗模式，
         级别下拉（默认日线）/监控起始时间（默认「此刻」+「此刻」按钮）/分组（含行内新建）；
         单只模式价格初始 = 行股价并随级别/时间 300ms 防抖联动取价；
         批量模式统一参数、不逐只展示价格；提交携带 source_type='watchlist' -->
    <el-dialog v-model="monitorDialogVisible" :title="monitorDialogTitle" width="440px" append-to-body>
      <div class="add-dialog-body" v-if="monitorTargets.length > 0" v-loading="addingMonitor">
        <div class="monitor-ctx">
          <div class="form-row">
            <label>股票</label>
            <span v-if="monitorMode === 'single'" class="ctx-value">
              {{ monitorTargets[0].name }}
              <span class="mono ctx-code">{{ monitorTargets[0].code }}</span>
            </span>
            <span v-else class="ctx-value">已选 {{ monitorTargets.length }} 只股票（统一参数）</span>
          </div>
          <div class="form-row">
            <label>级别</label>
            <el-select v-model="monitorKlType" style="width: 100%" @change="onMonitorTimeChange">
              <el-option v-for="it in klTypeItems" :key="it.value" :label="it.label" :value="it.value" />
            </el-select>
          </div>
          <div v-if="monitorMode === 'single'" class="form-row">
            <label>入场价格</label>
            <span class="ctx-value num" :class="{ 'price-stale': priceLoading }">
              {{ formatPrice(monitorPrice) }}
            </span>
          </div>
        </div>
        <div class="form-row">
          <label>监控起始时间</label>
          <div class="monitor-time-row">
            <el-date-picker
              v-model="monitorStartTime"
              type="datetime"
              value-format="YYYY-MM-DD HH:mm:ss"
              format="YYYY-MM-DD HH:mm:ss"
              placeholder="选择监控起始时间"
              clearable
              :disabled="addingMonitor"
              style="flex: 1"
              @change="onMonitorTimeChange"
            />
            <el-button :disabled="addingMonitor" @click="setMonitorTimeNow">此刻</el-button>
          </div>
        </div>
        <!-- 分组选择（同 BspView 弹窗）：可选，默认「未分组」，下拉尾部「新增分组」行内输入 -->
        <div class="form-row">
          <label>分组</label>
          <el-select
            v-model="monitorGroupId"
            placeholder="未分组"
            :disabled="addingMonitor"
            style="width: 100%"
            @visible-change="onGroupSelectVisible"
          >
            <el-option label="未分组" :value="null" />
            <el-option v-for="g in monitorGroups" :key="g.id" :label="g.name" :value="g.id" />
            <template #footer>
              <div v-if="!groupCreating" class="group-add-entry" @click="groupCreating = true">
                <el-icon><Plus /></el-icon>
                <span>新增分组</span>
              </div>
              <div v-else class="group-add-form">
                <el-input
                  v-model="newGroupName"
                  size="small"
                  placeholder="输入分组名"
                  maxlength="20"
                  @keyup.enter="onCreateGroup"
                />
                <el-button size="small" :loading="groupSaving" @click="onCreateGroup">确定</el-button>
              </div>
            </template>
          </el-select>
        </div>
        <p class="dialog-hint">
          {{
            monitorMode === 'single'
              ? '提交后自监控起始时间起对该股票进行监控，入场价格取所选时间点收盘价，来源标记为「自选」。'
              : '提交后逐只按统一级别/时间/分组加入监控（价格按各股所选时间点收盘价，取价失败按列表行股价），来源标记为「自选」。'
          }}
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
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Folder, Search, Close, EditPen, Rank, Plus } from '@element-plus/icons-vue'
import draggable from 'vuedraggable'
import Sortable, { type SortableEvent } from 'sortablejs'
import ChangeBadge from '@/components/ui/ChangeBadge.vue'
import IndustryBadges from '@/components/ui/IndustryBadges.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import {
  getFolders,
  createFolder,
  deleteFolder,
  renameFolder,
  getFolderStocks,
  reorderFolders,
  reorderFolderStocks,
  addStock,
  removeStock,
  moveStock,
  type WatchFolder,
} from '@/api/modules/watchlist'
import { searchStocks } from '@/api/modules/stock'
import { getPriceAt } from '@/api/modules/bsp'
import {
  createMonitor,
  createMonitorGroup,
  getMonitorGroups,
  type MonitorGroup,
} from '@/api/modules/monitor'
import type { Stock } from '@/api/types'
import type { AutocompleteInstance } from 'element-plus'

const router = useRouter()

// ---- 股票搜索下拉（el-autocomplete：模糊下拉选 code，点「搜索」才触发查询）----
interface StockSuggestion {
  value: string
  code: string
  name: string
  /** 无匹配候选的空态提示项，不参与查询 */
  placeholder?: boolean
}
const acRef = ref<AutocompleteInstance | null>(null)

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

/** 点选候选：输入框回填精确 code（不触发查询，点「搜索」才查） */
function onSelectSuggestion(item: StockSuggestion) {
  if (item.placeholder) return
  keyword.value = item.code
  acRef.value?.close()
}

// 股票搜索缓存
const stockCache = ref<Stock[]>([])

// ---- 文件夹 ----
const folders = ref<WatchFolder[]>([])
const activeKey = ref<string>('all')
const loading = ref(false)

const currentFolderId = computed<number | null>(() => {
  if (activeKey.value === 'all') return null
  return Number(activeKey.value)
})

const totalCount = computed(() => {
  // 全部 = 去重后的股票数
  const set = new Set<string>()
  folders.value.forEach((f) => f.codes.forEach((c) => set.add(c)))
  return set.size
})

async function loadFolders() {
  loading.value = true
  try {
    folders.value = await getFolders()
  } catch {
    // 错误已由拦截器处理
  } finally {
    loading.value = false
  }
}

async function selectFolder(key: string) {
  activeKey.value = key
  page.value = 1
  clearSelection()
  // 切换即刷新：立即按所选文件夹重新请求后端（spec「文件夹切换即时刷新」）
  await loadStocks()
}

// ---- 股票列表（服务端 q 过滤 + 前端分页） ----
const folderStocks = ref<Stock[]>([])
/** 输入框实时内容（不触发查询） */
const keyword = ref('')
/** 已生效的搜索关键字（由「搜索」按钮/回车写入，loadStocks/reload 均携带） */
const activeQuery = ref('')
const page = ref(1)
const pageSize = ref(20)

const pagedStocks = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return folderStocks.value.slice(start, start + pageSize.value)
})

async function loadStocks() {
  const q = activeQuery.value
  loading.value = true
  try {
    if (activeKey.value === 'all') {
      // 全部 = 按同一关键字并发查询各文件夹后跨文件夹去重聚合
      const results = await Promise.all(
        folders.value.map((f) => getFolderStocks(f.id, q || undefined)),
      )
      const set = new Map<string, Stock>()
      results.forEach((list) => {
        list.forEach((s) => {
          if (!set.has(s.code)) set.set(s.code, s)
        })
      })
      folderStocks.value = Array.from(set.values())
    } else {
      const id = Number(activeKey.value)
      folderStocks.value = await getFolderStocks(id, q || undefined)
    }
    page.value = 1
    clearSelection()
  } catch (e) {
    // 失败已由拦截器提示；列表置空避免展示陈旧数据
    console.warn('[WatchlistView.loadStocks] 加载股票列表失败', { activeKey: activeKey.value, q, error: e })
    folderStocks.value = []
  } finally {
    loading.value = false
    // 首屏数据到位后 tbody 才可能出现/重建，确保 sortable 挂接
    void nextTick().then(() => ensureStockSortable())
  }
}

/** 显式触发服务端查询（按钮 + 回车）；清空关键字即恢复全量 */
function onSearch() {
  activeQuery.value = keyword.value.trim()
  page.value = 1
  void loadStocks()
}

/** 重置：清空输入框与已生效关键字，恢复当前视图全量列表（spec「服务端搜索-重置按钮」） */
function onReset() {
  keyword.value = ''
  activeQuery.value = ''
  page.value = 1
  void loadStocks()
}

// ---- 多选 ----
const selected = ref<Stock[]>([])
const hasSelected = computed(() => selected.value.length > 0)
function onSelectionChange(rows: Stock[]) {
  selected.value = rows
}
function clearSelection() {
  selected.value = []
}

// ---- 操作：移出 ----
function onRowDblClick(row: Stock) {
  router.push({ name: 'kline', query: { code: row.code } })
}

async function onRemove(row: Stock) {
  if (!currentFolderId.value) {
    ElMessage.warning('「全部」视图下无法移出，请先选择具体文件夹')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确定将「${row.name}」移出自选吗？`,
      '移出确认',
      { type: 'warning' },
    )
    await removeStock(currentFolderId.value, row.code)
    ElMessage.success('已移出')
    await reload()
  } catch {
    // 取消或失败
  }
}

async function onBatchRemove() {
  if (!currentFolderId.value) {
    ElMessage.warning('「全部」视图下无法批量移出，请先选择具体文件夹')
    return
  }
  if (selected.value.length === 0) return
  try {
    await ElMessageBox.confirm(
      `确定将选中的 ${selected.value.length} 只股票移出自选吗？`,
      '批量移出确认',
      { type: 'warning' },
    )
    await Promise.all(
      selected.value.map((s) => removeStock(currentFolderId.value!, s.code)),
    )
    ElMessage.success(`已移出 ${selected.value.length} 只`)
    await reload()
  } catch {
    // 取消或失败
  }
}

// ---- 操作：移动 ----
async function onMove(row: Stock, targetId: string) {
  const toId = Number(targetId)
  if (!currentFolderId.value || toId === currentFolderId.value) return
  try {
    await moveStock(currentFolderId.value, toId, row.code)
    ElMessage.success('已移动')
    await reload()
  } catch {
    // 失败已由拦截器处理
  }
}

// ---- 文件夹弹窗：新建 / 重命名（D6 模式化单 dialog） ----
const folderDialogVisible = ref(false)
const folderDialogMode = ref<'create' | 'rename'>('create')
const editingFolderId = ref<number | null>(null)
const folderName = ref('')
const folderSaving = ref(false)

function openCreateFolder() {
  folderDialogMode.value = 'create'
  editingFolderId.value = null
  folderName.value = ''
  folderDialogVisible.value = true
}

function openRenameFolder(f: WatchFolder) {
  folderDialogMode.value = 'rename'
  editingFolderId.value = f.id
  folderName.value = f.name
  folderDialogVisible.value = true
}

async function onSubmitFolder() {
  const name = folderName.value.trim()
  if (!name) {
    // 空名拦截：不发请求
    ElMessage.warning('请输入文件夹名')
    return
  }
  folderSaving.value = true
  try {
    if (folderDialogMode.value === 'rename') {
      const id = editingFolderId.value
      if (id == null) {
        console.warn('[WatchlistView.onSubmitFolder] 重命名缺少 editingFolderId，取消提交', { name })
        return
      }
      await renameFolder(id, name)
      ElMessage.success('文件夹已重命名')
    } else {
      await createFolder(name)
      ElMessage.success('文件夹已创建')
    }
    folderDialogVisible.value = false
    await loadFolders()
  } catch (e) {
    // 失败已由拦截器提示
    console.warn('[WatchlistView.onSubmitFolder] 保存文件夹失败', {
      mode: folderDialogMode.value,
      editingFolderId: editingFolderId.value,
      name,
      error: e,
    })
  } finally {
    folderSaving.value = false
  }
}

// ---- 删除文件夹 ----
async function onDeleteFolder(f: WatchFolder) {
  try {
    await ElMessageBox.confirm(
      `确定删除文件夹「${f.name}」吗？${f.codes.length > 0 ? `文件夹内含 ${f.codes.length} 只股票，将一并移出。` : ''}`,
      '删除文件夹',
      { type: 'warning' },
    )
    await deleteFolder(f.id)
    ElMessage.success('文件夹已删除')
    if (activeKey.value === String(f.id)) activeKey.value = 'all'
    await loadFolders()
    await loadStocks()
  } catch {
    // 取消
  }
}

// ---- 拖拽排序：文件夹树（vuedraggable / SortableJS，长按 200ms） ----
/** 拖拽前快照：失败回滚用 */
let folderSnapshot: WatchFolder[] = []

function onFolderDragStart() {
  folderSnapshot = folders.value.map((f) => ({ ...f, codes: [...f.codes] }))
}

async function onFolderDragEnd() {
  // vuedraggable 已乐观重排 folders，这里负责持久化；失败回滚并提示
  const ids = folders.value.map((f) => f.id)
  try {
    await reorderFolders(ids)
  } catch (e) {
    folders.value = folderSnapshot
    console.warn('[WatchlistView.onFolderDragEnd] 文件夹顺序保存失败，已回滚', { ids, error: e })
    ElMessage.error('文件夹顺序保存失败，已恢复原顺序')
  }
}

// ---- 拖拽排序：股票表格行（sortablejs 挂 tbody，行首把手触发） ----
const tblWrapRef = ref<HTMLElement | null>(null)
const columnSortActive = ref(false)
/** 行拖拽可用性：「全部」视图无法确定归属文件夹；列排序生效时拖拽与显示序冲突，均禁用 */
const rowDragDisabled = computed(() => !currentFolderId.value || columnSortActive.value)
let stockSortable: Sortable | null = null

function onSortChange({ order }: { order: string | null }) {
  columnSortActive.value = order !== null
}

function ensureStockSortable() {
  const el = tblWrapRef.value?.querySelector('.el-table__body-wrapper tbody') as HTMLElement | null
  if (!el) return
  if (stockSortable && stockSortable.el === el && el.isConnected) return
  stockSortable?.destroy()
  stockSortable = Sortable.create(el, {
    handle: '.row-drag-handle',
    animation: 150,
    disabled: rowDragDisabled.value,
    onEnd: (evt: SortableEvent) => {
      void onStockDragEnd(evt)
    },
  })
}

watch(rowDragDisabled, (disabled) => {
  stockSortable?.option('disabled', disabled)
})

async function onStockDragEnd(evt: SortableEvent) {
  const folderId = currentFolderId.value
  if (!folderId) {
    // 理论上 sortable 已禁用，兜底防御
    console.warn('[WatchlistView.onStockDragEnd] 「全部」视图不支持行拖拽，忽略本次拖拽')
    return
  }
  const handle = evt.item.querySelector('.row-drag-handle') as HTMLElement | null
  const code = handle?.dataset.code
  const prevStocks = folderStocks.value
  const prevFolderCodes = folders.value.find((f) => f.id === folderId)?.codes ?? []
  if (!code) {
    console.warn('[WatchlistView.onStockDragEnd] 无法识别拖拽行编码，忽略本次拖拽', {
      folderId,
      newIndex: evt.newIndex,
    })
    return
  }
  // 全量序中的绝对下标：表格分页只展示切片，换算 offset
  const offset = (page.value - 1) * pageSize.value
  const arr = [...prevStocks]
  const oldIdx = arr.findIndex((s) => s.code === code)
  const newIdx = offset + (evt.newIndex ?? 0)
  if (oldIdx < 0 || newIdx < 0 || newIdx >= arr.length) {
    console.warn('[WatchlistView.onStockDragEnd] 拖拽下标越界，忽略本次拖拽', {
      folderId,
      code,
      oldIdx,
      newIdx,
      length: arr.length,
    })
    return
  }
  // 乐观重排当前文件夹股票数组
  arr.splice(newIdx, 0, arr.splice(oldIdx, 1)[0])
  const newFullOrder = buildFullNewOrder(arr)
  folderStocks.value = arr
  // 同步左侧 codes 序（保持与拖拽结果一致）
  const folder = folders.value.find((f) => f.id === folderId)
  if (folder) folder.codes = newFullOrder
  try {
    await reorderFolderStocks(folderId, newFullOrder)
  } catch (e) {
    // 失败回滚本地序并提示
    folderStocks.value = prevStocks
    if (folder) folder.codes = prevFolderCodes
    console.warn('[WatchlistView.onStockDragEnd] 股票顺序保存失败，已回滚', {
      folderId,
      code,
      error: e,
    })
    ElMessage.error('股票顺序保存失败，已恢复原顺序')
  }
}

/**
 * 计算文件夹全量新序（reorder 接口为全量覆盖语义）：
 * 无搜索时可见列表即全量；带搜索时把可见子集新序合并回文件夹全量码表（不可见项保持原槽位）
 */
function buildFullNewOrder(visibleOrdered: Stock[]): string[] {
  const visibleCodes = visibleOrdered.map((s) => s.code)
  if (!activeQuery.value) return visibleCodes
  const folderId = currentFolderId.value
  const base = folders.value.find((f) => f.id === folderId)?.codes ?? []
  const listed = new Set(visibleCodes)
  const queue = [...visibleCodes]
  const merged = base.map((c) => (listed.has(c) ? (queue.shift() as string) : c))
  queue.forEach((c) => merged.push(c))
  return merged
}

// ---- 添加股票弹窗 ----
const addDialogVisible = ref(false)
const addFolderId = ref<number | null>(null)
const addStockCode = ref<string>('')
const adding = ref(false)
const stockOptions = ref<Stock[]>([])
const stockSearching = ref(false)

async function searchStock(query: string) {
  stockSearching.value = true
  try {
    stockOptions.value = await searchStocks(query)
  } catch {
    stockOptions.value = stockCache.value.filter(
      (s) => !query || s.code.toLowerCase().includes(query.toLowerCase()) || s.name.toLowerCase().includes(query.toLowerCase()),
    ).slice(0, 30)
  } finally {
    stockSearching.value = false
  }
}

async function onAddStock() {
  if (!addFolderId.value) {
    ElMessage.warning('请选择目标文件夹')
    return
  }
  if (!addStockCode.value) {
    ElMessage.warning('请选择要添加的股票')
    return
  }
  adding.value = true
  try {
    await addStock(addFolderId.value, addStockCode.value)
    ElMessage.success('已添加到自选')
    addDialogVisible.value = false
    addStockCode.value = ''
    await reload()
  } catch {
    // 失败已处理
  } finally {
    adding.value = false
  }
}

// ---------------------------------------------------------------------------
// 加入监控（design D9/D10，任务 7.3/7.4）：行级 + 批量复用同一弹窗。
// 级别可选（词表同 BspView klOptions，默认日线 D）；时间默认「此刻」；
// 价格初始 = 行股价（Stock.price），级别/时间变化 → 300ms 防抖 getPriceAt
// 联动（失败保留当前价格并提示，语义对齐 BspView）；分组选择 + 下拉尾部
// 行内新建（成功即选中）。提交携带 source_type='watchlist'。
// ---------------------------------------------------------------------------
/** 级别词表（同 BspView klOptions / MonitorView klTypeItems）：30分/60分/日线/周线/月线 */
const klTypeItems = [
  { label: '30分', value: '30m' },
  { label: '60分', value: '60m' },
  { label: '日线', value: 'D' },
  { label: '周线', value: 'W' },
  { label: '月线', value: 'M' },
]

const monitorDialogVisible = ref(false)
/** 弹窗模式：'single' 行级（上下文行）| 'batch' 批量（selected 多选数组） */
const monitorMode = ref<'single' | 'batch'>('single')
/** 弹窗目标股票：单只 → [行]；批量 → selected 列表 */
const monitorTargets = ref<Stock[]>([])
/** 级别（默认日线：自选页无买卖点上下文，spec「级别默认值」） */
const monitorKlType = ref('D')
const monitorStartTime = ref('')
const monitorPrice = ref(0)
const priceLoading = ref(false)
const addingMonitor = ref(false)

const monitorDialogTitle = computed(() =>
  monitorMode.value === 'batch'
    ? `批量加入监控（${monitorTargets.value.length} 只）`
    : '加入监控',
)

// ---- 弹窗分组选择（同 BspView，monitor-group-change D5）----
const monitorGroups = ref<MonitorGroup[]>([])
const monitorGroupId = ref<number | null>(null)
const groupCreating = ref(false)
const newGroupName = ref('')
const groupSaving = ref(false)

/** 下拉展开时拉分组列表（每次展开都刷新，与 BspView 保持数据一致） */
async function onGroupSelectVisible(visible: boolean) {
  if (!visible) return
  try {
    monitorGroups.value = await getMonitorGroups()
  } catch {
    // 失败已由拦截器提示；保留现有选项
  }
}

/** 行内新建分组：成功即自动选中新组（交互与 BspView 弹窗一致） */
async function onCreateGroup() {
  const name = newGroupName.value.trim()
  if (!name) {
    ElMessage.warning('请输入分组名')
    return
  }
  groupSaving.value = true
  try {
    const g = await createMonitorGroup(name)
    monitorGroups.value = await getMonitorGroups()
    monitorGroupId.value = g.id
    newGroupName.value = ''
    groupCreating.value = false
  } catch {
    // 重名/非法：后端 detail 已由拦截器提示，保留输入供修改重试
  } finally {
    groupSaving.value = false
  }
}

// ---- 价格联动（复制自 BspView，自持一份保持改动最小）----
let priceSeq = 0
let priceTimer: ReturnType<typeof setTimeout> | null = null

/** ms 时间戳 → 'YYYY-MM-DD HH:mm:ss'（含秒，与提交格式一致） */
function toDateTimeStr(ts: number) {
  const d = new Date(ts)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

/** 按级别与时间取价（design D9）：失败/404 保留当前价格并提示（初始 = 行股价） */
async function fetchMonitorPrice(time: string) {
  const targets = monitorTargets.value
  if (monitorMode.value !== 'single' || targets.length !== 1 || !time) return
  const stock = targets[0]
  const seq = ++priceSeq
  priceLoading.value = true
  try {
    const r = await getPriceAt(stock.code, monitorKlType.value, time)
    if (seq !== priceSeq) return // 过期响应丢弃
    monitorPrice.value = r.price
  } catch {
    if (seq !== priceSeq) return
    ElMessage.warning('所选时间无 K 线数据，保留原价格')
  } finally {
    if (seq === priceSeq) priceLoading.value = false
  }
}

/** 级别/时间变化 → 300ms 防抖取价（design D9） */
function onMonitorTimeChange() {
  if (monitorMode.value !== 'single') return // 批量模式不逐只展示价格
  if (priceTimer) clearTimeout(priceTimer)
  if (!monitorStartTime.value) return
  priceTimer = setTimeout(() => fetchMonitorPrice(monitorStartTime.value), 300)
}

/** 每次打开弹窗重置全部状态（级别回日线、时间回此刻、分组回未分组、价格回行股价） */
function openMonitorDialog(row: Stock) {
  monitorMode.value = 'single'
  monitorTargets.value = [row]
  resetMonitorDialogState(row.price)
  monitorDialogVisible.value = true
  // 默认时间也触发一次联动（语义统一：价格 = 所选时间点收盘价）
  fetchMonitorPrice(monitorStartTime.value)
}

/** 批量入口：目标 = 多选列表，统一参数（级别/时间/分组） */
function onBatchMonitor() {
  if (!hasSelected.value || selected.value.length === 0) return
  monitorMode.value = 'batch'
  monitorTargets.value = [...selected.value]
  resetMonitorDialogState()
  monitorDialogVisible.value = true
}

/** 弹窗状态重置（批量无上下文行价：monitorPrice 不参与批量提交） */
function resetMonitorDialogState(initialPrice?: number) {
  monitorKlType.value = 'D'
  monitorStartTime.value = toDateTimeStr(Date.now())
  monitorGroupId.value = null
  groupCreating.value = false
  newGroupName.value = ''
  monitorPrice.value = initialPrice ?? 0
  priceLoading.value = false
  if (priceTimer) {
    clearTimeout(priceTimer)
    priceTimer = null
  }
  priceSeq++ // 使在途取价响应过期
}

/** 「此刻」按钮：监控起始时间置为当前时间（经 change 事件触发联动） */
function setMonitorTimeNow() {
  monitorStartTime.value = toDateTimeStr(Date.now())
  onMonitorTimeChange()
}

/** 提交：单只 → 单次 createMonitor；批量 → 串行逐只（先 getPriceAt，
 *  取价失败按行股价提交并计入失败提示；单只 createMonitor 失败不中断） */
async function confirmAddMonitor() {
  const targets = monitorTargets.value
  if (targets.length === 0) {
    console.warn('[WatchlistView.confirmAddMonitor] 无目标股票，忽略提交', {
      dialogVisible: monitorDialogVisible.value,
    })
    return
  }
  if (!monitorStartTime.value) {
    ElMessage.warning('请设置监控起始时间')
    return
  }
  addingMonitor.value = true
  try {
    if (monitorMode.value === 'single') {
      const stock = targets[0]
      await createMonitor({
        code: stock.code,
        kl_type: monitorKlType.value,
        entry_price: monitorPrice.value, // 联动后的所选时间点价格（失败兜底 = 行股价）
        monitor_start_time: monitorStartTime.value,
        group_id: monitorGroupId.value ?? undefined,
        source_type: 'watchlist',
      })
      ElMessage.success(`已将「${stock.name}」加入监控`)
    } else {
      // 批量（design D10）：前端串行循环既有 POST /api/monitor，统一参数；
      // 失败计数 = 取价失败（按行股价提交）+ 提交失败，单只失败不中断
      let okCount = 0
      let failCount = 0
      for (const stock of targets) {
        let entryPrice: number
        try {
          const r = await getPriceAt(stock.code, monitorKlType.value, monitorStartTime.value)
          entryPrice = r.price
        } catch {
          // 取价失败兜底：按该行股价提交并计入失败提示（不阻塞整体）
          entryPrice = stock.price
          failCount++
        }
        try {
          await createMonitor({
            code: stock.code,
            kl_type: monitorKlType.value,
            entry_price: entryPrice,
            monitor_start_time: monitorStartTime.value,
            group_id: monitorGroupId.value ?? undefined,
            source_type: 'watchlist',
          })
          okCount++
        } catch {
          // 单只提交失败：错误文案由拦截器提示，继续后续标的
          failCount++
        }
      }
      if (failCount === 0) {
        ElMessage.success(`已将 ${okCount} 只股票加入监控`)
      } else {
        ElMessage.warning(`成功 ${okCount} / 失败 ${failCount}（失败含取价失败与提交失败，取价失败已按行股价提交）`)
      }
    }
    monitorDialogVisible.value = false
  } finally {
    addingMonitor.value = false
  }
}

// ---- 工具 ----
function formatPrice(v: number) {
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** 全量刷新：文件夹树 + 当前视图股票（loadStocks 自带 activeQuery，关键字随刷新重新生效） */
async function reload() {
  await loadFolders()
  await loadStocks()
}

onMounted(async () => {
  await nextTick()
  ensureStockSortable()
  await reload()
})

onBeforeUnmount(() => {
  stockSortable?.destroy()
  stockSortable = null
})
</script>

<style scoped>
.watchlist-layout {
  display: flex;
  gap: var(--sp-lg);
  align-items: stretch;
  flex: 1;
  min-height: 0;
}
.folder-panel {
  width: 220px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
}
.folder-panel .tree {
  flex: 1;
  overflow-y: auto;
}
.folder-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
.folder-del,
.folder-edit {
  color: var(--text-disabled);
  width: 14px;
  height: 14px;
  margin-left: 2px;
  border-radius: var(--r-sm);
}
.folder-edit:hover {
  color: var(--accent-hover);
  background: var(--accent-dim);
}
.folder-del:hover {
  color: var(--rise);
  background: var(--rise-dim);
}
/* 拖拽行时的视觉反馈 */
:deep(.tree__drag .sortable-ghost) {
  opacity: 0.45;
  background: var(--accent-dim);
}
:deep(.tree__drag .sortable-chosen) {
  background: var(--bg-surface-hover);
}
.main-panel {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--sp-md);
}
.cell-stock {
  display: flex;
  align-items: center;
  gap: 6px;
  line-height: 1.3;
}
.cell-stock-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.cell-stock .nm {
  color: var(--text-primary);
  font-size: 13px;
}
.cell-stock .cd {
  color: var(--text-disabled);
  font-size: 11px;
}
/* 行拖拽把手：行内双击跳转 / 按钮与拖拽隔离 */
.row-drag-handle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  color: var(--text-disabled);
  cursor: grab;
  border-radius: var(--r-sm);
}
.row-drag-handle:hover {
  color: var(--accent-hover);
  background: var(--accent-dim);
}
.row-drag-handle:active {
  cursor: grabbing;
}
.row-drag-handle.is-disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.row-drag-handle.is-disabled:hover {
  color: var(--text-disabled);
  background: transparent;
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
/* ---- 加入监控弹窗（任务 7.3/7.4，样式对齐 BspView）---- */
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
/* 价格联动取价中的弱化显示 */
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
/* 下拉尾部「新增分组」行内入口（同 BspView） */
.group-add-entry {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  font-size: 13px;
  color: var(--accent-hover);
  cursor: pointer;
  border-top: 1px solid var(--border-base);
}
.group-add-entry:hover {
  background: var(--accent-dim);
}
.group-add-form {
  display: flex;
  align-items: center;
  gap: var(--sp-sm);
  padding: 6px 8px;
  border-top: 1px solid var(--border-base);
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

/* 表格行双击可点击提示 */
:deep(.el-table__body tr) {
  cursor: pointer;
}
:deep(.el-table__body tr:hover) {
  background: var(--bg-surface-hover);
}
</style>
