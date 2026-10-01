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
        <div class="field" style="width: 240px">
          <el-icon class="field-icon"><Search /></el-icon>
          <input
            v-model="keyword"
            placeholder="搜索名称 / 编码"
            @keyup.enter="onSearch"
          />
        </div>
        <button class="btn btn--default" @click="onSearch">搜索</button>
        <button class="btn btn--default" @click="onReset">重置</button>
        <span class="spacer"></span>
        <button class="btn btn--primary" @click="addDialogVisible = true">
          <span class="icon-plus"></span> 添加股票
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
            <el-table-column label="操作" width="180" align="right">
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
            placeholder="输入名称或编码搜索"
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
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onActivated, onBeforeUnmount, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Folder, Search, Close, EditPen, Rank } from '@element-plus/icons-vue'
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
import type { Stock } from '@/api/types'

const router = useRouter()

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

// ---- 工具 ----
function formatPrice(v: number) {
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** 全量刷新：文件夹树 + 当前视图股票（loadStocks 自带 activeQuery，关键字随刷新重新生效） */
async function reload() {
  await loadFolders()
  await loadStocks()
}

/** KeepAlive 首次激活与 onMounted 会同时触发，跳过首次避免双请求 */
let isFirstActivate = true

onMounted(async () => {
  await nextTick()
  ensureStockSortable()
  await reload()
})

onActivated(async () => {
  // KeepAlive 再次激活时全量刷新（D4：跨页变更在回到本页时可见）
  ensureStockSortable()
  if (isFirstActivate) {
    isFirstActivate = false
    return
  }
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
.dialog-hint {
  font-size: 12px;
  color: var(--text-disabled);
  margin: 0;
}

/* 表格行双击可点击提示 */
:deep(.el-table__body tr) {
  cursor: pointer;
}
:deep(.el-table__body tr:hover) {
  background: var(--bg-surface-hover);
}
</style>
