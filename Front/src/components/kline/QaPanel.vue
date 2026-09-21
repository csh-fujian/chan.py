<template>
  <div class="qa-panel">
    <!-- 提问输入 -->
    <div class="qa-input">
      <el-input
        v-model="question"
        type="textarea"
        :rows="3"
        resize="none"
        placeholder="向大模型提问，例如：当前日线级别处于哪个买卖点？"
      />
      <button class="btn btn--primary qa-send" :disabled="asking || !question.trim()" @click="onAsk">
        <el-icon v-if="!asking"><Promotion /></el-icon>
        <el-icon v-else class="is-loading"><Loading /></el-icon>
        {{ asking ? '分析中' : '发送' }}
      </button>
    </div>

    <!-- 当前回答 -->
    <div v-if="asking" class="qa-answer is-thinking">
      <span class="dot-bounce"></span> 大模型正在分析，请稍候…
    </div>
    <div v-else-if="latest" class="qa-answer">
      <div class="qa-answer__q">{{ latest.question }}</div>
      <div class="qa-answer__a">{{ latest.answer }}</div>
    </div>

    <!-- 记录工具条 -->
    <div class="qa-toolbar">
      <span class="qa-toolbar__label">问答记录</span>
      <span class="spacer"></span>
      <button class="btn btn--default btn--sm" :disabled="!selectedIds.length" @click="onBatchStar">
        批量打星
      </button>
      <button class="btn btn--default btn--sm" @click="onDeleteUnstarred">删未打星</button>
    </div>

    <!-- 记录列表：右侧星星标识收藏 -->
    <div class="qa-list">
      <div
        v-for="rec in records"
        :key="rec.id"
        class="qa-item"
        :class="{ 'is-selected': selectedIds.includes(rec.id) }"
        @click="openDetail(rec)"
      >
        <span
          class="checkbox"
          :class="{ 'is-checked': selectedIds.includes(rec.id) }"
          @click.stop="toggleSelect(rec.id)"
        />
        <div class="qa-item__body">
          <div class="qa-item__q">{{ rec.question }}</div>
          <div class="qa-item__time mono">{{ formatTime(rec.created_at) }}</div>
        </div>
        <el-icon
          class="qa-item__star"
          :class="{ 'is-starred': rec.starred }"
          title="收藏 / 取消收藏"
          @click.stop="toggleStar(rec)"
        >
          <StarFilled v-if="rec.starred" />
          <Star v-else />
        </el-icon>
      </div>
      <EmptyState v-if="!records.length && !asking" description="暂无问答记录" />
    </div>

    <!-- 详情弹窗 -->
    <el-dialog v-model="detailVisible" title="问答详情" width="520px" append-to-body>
      <div v-if="detail" class="qa-detail">
        <div class="qa-detail__label">提问</div>
        <div class="qa-detail__q">{{ detail.question }}</div>
        <div class="qa-detail__label">回答</div>
        <div class="qa-detail__a">{{ detail.answer }}</div>
        <div class="qa-detail__time mono">{{ formatTime(detail.created_at) }}</div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Star, StarFilled, Promotion, Loading } from '@element-plus/icons-vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { askQuestion, getQaRecords, starQaRecord, batchStarQa, deleteUnstarredQa } from '@/api/modules/qa'
import type { QaRecord } from '@/api/types'

const question = ref('')
const asking = ref(false)
const records = ref<QaRecord[]>([])
const latest = ref<QaRecord | null>(null)
const selectedIds = ref<number[]>([])

const detailVisible = ref(false)
const detail = ref<QaRecord | null>(null)

async function loadRecords() {
  try {
    records.value = await getQaRecords()
  } catch {
    records.value = []
  }
}

async function onAsk() {
  const q = question.value.trim()
  if (!q) {
    ElMessage.warning('请输入问题')
    return
  }
  asking.value = true
  try {
    const rec = await askQuestion({ question: q })
    latest.value = rec
    records.value = [rec, ...records.value]
    question.value = ''
  } catch {
    // 失败已处理
  } finally {
    asking.value = false
  }
}

async function toggleStar(rec: QaRecord) {
  const target = !rec.starred
  rec.starred = target // 乐观更新
  try {
    await starQaRecord(rec.id, target)
  } catch {
    rec.starred = !target
  }
}

function toggleSelect(id: number) {
  const i = selectedIds.value.indexOf(id)
  if (i >= 0) selectedIds.value.splice(i, 1)
  else selectedIds.value.push(id)
}

async function onBatchStar() {
  if (!selectedIds.value.length) return
  try {
    await batchStarQa(selectedIds.value, true)
    records.value.forEach((r) => {
      if (selectedIds.value.includes(r.id)) r.starred = true
    })
    ElMessage.success(`已打星 ${selectedIds.value.length} 条`)
    selectedIds.value = []
  } catch {
    // 失败已处理
  }
}

async function onDeleteUnstarred() {
  try {
    await ElMessageBox.confirm('确定删除所有未打星的问答记录吗？', '删除确认', { type: 'warning' })
    await deleteUnstarredQa()
    records.value = records.value.filter((r) => r.starred)
    ElMessage.success('已删除未打星记录')
  } catch {
    // 取消或失败
  }
}

function openDetail(rec: QaRecord) {
  detail.value = rec
  detailVisible.value = true
}

function formatTime(ts: number): string {
  const d = new Date(ts)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

onMounted(loadRecords)
</script>

<style scoped>
.qa-panel {
  padding: var(--sp-lg);
  display: flex;
  flex-direction: column;
  gap: var(--sp-lg);
  min-height: 0;
}

/* 提问输入 */
.qa-input {
  display: flex;
  flex-direction: column;
  gap: var(--sp-sm);
}
.qa-input :deep(.el-textarea__inner) {
  background: var(--bg-chart);
  box-shadow: 0 0 0 1px var(--border-base) inset;
  color: var(--text-primary);
  font-size: 13px;
  border-radius: var(--r-md);
  padding: 10px 12px;
}
.qa-input :deep(.el-textarea__inner:focus) {
  box-shadow: 0 0 0 1px var(--accent-base) inset, 0 0 14px var(--accent-glow);
}
.qa-send {
  align-self: flex-end;
}
.qa-send .is-loading {
  animation: rotating 1s linear infinite;
}
@keyframes rotating {
  to { transform: rotate(360deg); }
}

/* 当前回答 */
.qa-answer {
  background: var(--bg-chart);
  border: 1px solid var(--border-base);
  border-radius: var(--r-md);
  padding: var(--sp-md);
  display: flex;
  flex-direction: column;
  gap: var(--sp-sm);
}
.qa-answer__q {
  font-size: 12px;
  color: var(--text-secondary);
}
.qa-answer__a {
  font-size: 13px;
  color: var(--text-primary);
  line-height: 1.6;
  white-space: pre-wrap;
}
.qa-answer.is-thinking {
  flex-direction: row;
  align-items: center;
  gap: var(--sp-sm);
  color: var(--text-secondary);
  font-size: 13px;
}
.dot-bounce {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent-base);
  animation: bounce 1s ease-in-out infinite;
}
@keyframes bounce {
  0%, 100% { transform: translateY(0); opacity: 0.4; }
  50% { transform: translateY(-4px); opacity: 1; }
}

/* 工具条 */
.qa-toolbar {
  display: flex;
  align-items: center;
  gap: var(--sp-sm);
}
.qa-toolbar__label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  letter-spacing: 0.04em;
}

/* 记录列表 */
.qa-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.qa-item {
  display: flex;
  align-items: center;
  gap: var(--sp-sm);
  padding: 8px;
  border-radius: var(--r-sm);
  cursor: pointer;
  border: 1px solid transparent;
  transition: all 0.12s ease;
}
.qa-item:hover {
  background: var(--bg-surface-hover);
}
.qa-item.is-selected {
  background: rgba(59, 130, 246, 0.08);
  border-color: rgba(59, 130, 246, 0.3);
}
.qa-item__body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.qa-item__q {
  font-size: 13px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.qa-item__time {
  font-size: 11px;
  color: var(--text-disabled);
}
.qa-item__star {
  width: 16px;
  height: 16px;
  color: var(--text-disabled);
  flex-shrink: 0;
  transition: color 0.12s ease;
}
.qa-item__star:hover {
  color: var(--warning);
}
.qa-item__star.is-starred {
  color: var(--warning);
}

/* 详情弹窗 */
.qa-detail {
  display: flex;
  flex-direction: column;
  gap: var(--sp-sm);
}
.qa-detail__label {
  font-size: 11px;
  color: var(--text-disabled);
  letter-spacing: 0.06em;
}
.qa-detail__q {
  font-size: 13px;
  color: var(--text-primary);
  font-weight: 500;
}
.qa-detail__a {
  font-size: 13px;
  color: var(--text-primary);
  line-height: 1.7;
  white-space: pre-wrap;
  background: var(--bg-chart);
  border-radius: var(--r-md);
  padding: var(--sp-md);
}
.qa-detail__time {
  font-size: 11px;
  color: var(--text-disabled);
}
</style>
