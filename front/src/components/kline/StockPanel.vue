<template>
  <div class="stock-panel" v-loading="loading">
    <!-- 标的头部 -->
    <div v-if="profile" class="sp-head">
      <div class="sp-head__row">
        <span class="sp-name">{{ profile.name }}</span>
        <span class="sp-code mono">{{ profile.code }}</span>
      </div>
      <div class="sp-quote">
        <span class="sp-price num">{{ formatPrice(profile.price) }}</span>
        <ChangeBadge :value="profile.change_pct" />
      </div>
    </div>

    <!-- 板块信息：行业 / 地区 / 概念 全量展示 -->
    <div v-if="profile" class="sp-section">
      <div class="sp-section__title">板块信息</div>
      <div class="sp-group">
        <span class="sp-label">行业</span>
        <div class="sp-tags">
          <span v-for="i in profile.industries" :key="i" class="badge badge--default">{{ i }}</span>
        </div>
      </div>
      <div class="sp-group">
        <span class="sp-label">地区</span>
        <div class="sp-tags">
          <span class="badge badge--accent">{{ profile.region }}</span>
        </div>
      </div>
      <div class="sp-group">
        <span class="sp-label">概念</span>
        <div class="sp-tags">
          <span v-for="c in profile.concepts" :key="c" class="badge badge--info">{{ c }}</span>
        </div>
      </div>
    </div>

    <!-- 自选管理：加入/移出 + 分组编辑 -->
    <div v-if="profile" class="sp-section">
      <div class="sp-section__title">
        自选管理
        <span class="spacer"></span>
        <button class="btn btn--ghost btn--sm" @click="openCreateFolder">
          <span class="icon-plus"></span> 新建
        </button>
      </div>

      <div class="sp-watch-actions">
        <el-dropdown trigger="click" @command="onAddToFolder">
          <button class="btn btn--primary btn--sm">
            <el-icon><Star /></el-icon> 加入自选
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item
                v-for="f in folders"
                :key="f.id"
                :command="f.id"
                :disabled="f.codes.includes(code)"
              >
                {{ f.name }}{{ f.codes.includes(code) ? '（已加入）' : '' }}
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <span v-if="memberFolders.length" class="sp-member">已加入 {{ memberFolders.length }} 个分组</span>
        <span v-else class="sp-member is-none">尚未加入自选</span>
      </div>

      <!-- 分组列表：仅展示当前股票已加入的分组（含重命名 / 删除 / 移出） -->
      <div class="sp-folders">
        <div v-for="f in memberFolders" :key="f.id" class="sp-folder">
          <el-icon class="sp-folder__icon"><Folder /></el-icon>
          <span class="sp-folder__name" :title="f.name">{{ f.name }}</span>
          <span class="sp-folder__count">{{ f.codes.length }}</span>
          <el-icon class="sp-folder__act" title="重命名分组" @click="openRenameFolder(f)"><EditPen /></el-icon>
          <el-icon
            v-if="f.id !== 1"
            class="sp-folder__act sp-folder__act--danger"
            title="删除分组"
            @click="onDeleteFolder(f)"
          ><Delete /></el-icon>
          <el-icon class="sp-folder__act sp-folder__act--danger" title="移出自选" @click="onRemoveFromFolder(f.id)"><Remove /></el-icon>
        </div>
      </div>
    </div>

    <EmptyState v-if="!profile && !loading" description="请输入有效股票代码" />

    <!-- 新建 / 重命名分组弹窗 -->
    <el-dialog
      v-model="folderDialogVisible"
      :title="folderMode === 'create' ? '新建分组' : '重命名分组'"
      width="400px"
      append-to-body
    >
      <el-form @submit.prevent>
        <el-form-item label="分组名">
          <el-input v-model="folderName" placeholder="请输入分组名" autofocus @keyup.enter="onSubmitFolder" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="folderDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingFolder" @click="onSubmitFolder">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Star, Folder, EditPen, Delete, Remove } from '@element-plus/icons-vue'
import ChangeBadge from '@/components/ui/ChangeBadge.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { getStockProfile } from '@/api/modules/stock'
import {
  getFolders,
  createFolder,
  deleteFolder,
  renameFolder,
  addStock,
  removeStock,
  type WatchFolder,
} from '@/api/modules/watchlist'
import type { StockProfile } from '@/api/types'

const props = defineProps<{ code: string }>()

const profile = ref<StockProfile | null>(null)
const loading = ref(false)
const folders = ref<WatchFolder[]>([])

const memberFolders = computed(() => folders.value.filter((f) => f.codes.includes(props.code)))

// ---- 标的详情 ----
async function loadProfile() {
  loading.value = true
  try {
    profile.value = await getStockProfile(props.code)
  } catch {
    profile.value = null
  } finally {
    loading.value = false
  }
}

// ---- 自选分组 ----
async function loadFolders() {
  try {
    folders.value = await getFolders()
  } catch {
    // 错误已由拦截器处理
  }
}

async function onAddToFolder(folderId: number) {
  try {
    await addStock(folderId, props.code)
    ElMessage.success('已加入自选')
    await loadFolders()
  } catch {
    // 失败已处理
  }
}

async function onRemoveFromFolder(folderId: number) {
  try {
    await removeStock(folderId, props.code)
    ElMessage.success('已移出自选')
    await loadFolders()
  } catch {
    // 失败已处理
  }
}

// ---- 分组编辑：新建 / 重命名 / 删除 ----
const folderDialogVisible = ref(false)
const folderMode = ref<'create' | 'rename'>('create')
const folderName = ref('')
const savingFolder = ref(false)
const editingFolderId = ref<number | null>(null)

function openCreateFolder() {
  folderMode.value = 'create'
  folderName.value = ''
  editingFolderId.value = null
  folderDialogVisible.value = true
}

function openRenameFolder(f: WatchFolder) {
  folderMode.value = 'rename'
  folderName.value = f.name
  editingFolderId.value = f.id
  folderDialogVisible.value = true
}

async function onSubmitFolder() {
  const name = folderName.value.trim()
  if (!name) {
    ElMessage.warning('请输入分组名')
    return
  }
  savingFolder.value = true
  try {
    if (folderMode.value === 'create') {
      await createFolder(name)
      ElMessage.success('分组已创建')
    } else if (editingFolderId.value != null) {
      await renameFolder(editingFolderId.value, name)
      ElMessage.success('分组已重命名')
    }
    folderDialogVisible.value = false
    await loadFolders()
  } catch {
    // 失败已处理
  } finally {
    savingFolder.value = false
  }
}

async function onDeleteFolder(f: WatchFolder) {
  try {
    await ElMessageBox.confirm(
      `确定删除分组「${f.name}」吗？${f.codes.length ? `组内 ${f.codes.length} 只股票将一并移出。` : ''}`,
      '删除分组',
      { type: 'warning' },
    )
    await deleteFolder(f.id)
    ElMessage.success('分组已删除')
    await loadFolders()
  } catch {
    // 取消
  }
}

// ---- 工具 ----
function formatPrice(v: number) {
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

watch(() => props.code, loadProfile, { immediate: true })
onMounted(loadFolders)
</script>

<style scoped>
.stock-panel {
  padding: var(--sp-lg);
  display: flex;
  flex-direction: column;
  gap: var(--sp-lg);
  min-height: 0;
}

/* 标的头部 */
.sp-head {
  display: flex;
  flex-direction: column;
  gap: var(--sp-sm);
  padding-bottom: var(--sp-lg);
  border-bottom: 1px solid var(--border-base);
}
.sp-head__row {
  display: flex;
  align-items: baseline;
  gap: var(--sp-sm);
}
.sp-name {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
}
.sp-code {
  font-size: 12px;
  color: var(--text-disabled);
}
.sp-quote {
  display: flex;
  align-items: center;
  gap: var(--sp-md);
}
.sp-price {
  font-size: 24px;
  font-weight: 700;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  color: var(--text-primary);
  line-height: 1;
}

/* 板块信息 */
.sp-section {
  display: flex;
  flex-direction: column;
  gap: var(--sp-md);
}
.sp-section__title {
  display: flex;
  align-items: center;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  letter-spacing: 0.04em;
}
.sp-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sp-label {
  font-size: 11px;
  color: var(--text-disabled);
}
.sp-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

/* 自选管理 */
.sp-watch-actions {
  display: flex;
  align-items: center;
  gap: var(--sp-sm);
  flex-wrap: wrap;
}
.sp-member {
  font-size: 12px;
  color: var(--text-secondary);
}
.sp-member.is-none {
  color: var(--text-disabled);
}

.sp-folders {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.sp-folder {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 32px;
  padding: 0 8px;
  border-radius: var(--r-sm);
  transition: background 0.12s ease;
}
.sp-folder:hover {
  background: var(--bg-surface-hover);
}
.sp-folder__icon {
  color: var(--text-disabled);
  width: 14px;
  height: 14px;
}
.sp-folder__name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: var(--text-primary);
}
.sp-folder__count {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-disabled);
}
.sp-folder__act {
  color: var(--text-disabled);
  width: 14px;
  height: 14px;
  border-radius: var(--r-sm);
  cursor: pointer;
  transition: all 0.12s ease;
}
.sp-folder__act:hover {
  color: var(--accent-hover);
  background: rgba(59, 130, 246, 0.1);
}
.sp-folder__act--danger:hover {
  color: var(--rise);
  background: var(--rise-dim);
}
</style>
