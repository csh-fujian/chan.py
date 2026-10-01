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
      <div class="qa-input__actions">
        <button class="btn btn--ghost btn--sm" title="查看 / 编辑系统提示词" @click="openPromptDialog">
          <el-icon><Setting /></el-icon> 提示词
        </button>
        <button class="btn btn--primary qa-send" :disabled="asking || !question.trim()" @click="onAsk">
          <el-icon v-if="!asking"><Promotion /></el-icon>
          <el-icon v-else class="is-loading"><Loading /></el-icon>
          {{ asking ? '分析中' : '发送' }}
        </button>
      </div>
    </div>

    <!-- 当前回答（最近一次完成的回答；流式过程在弹窗内展示） -->
    <div v-if="latest" class="qa-answer">
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

    <!-- 流式回答弹窗（6.2）：发送即打开，逐段追加 delta -->
    <el-dialog
      v-model="streamVisible"
      title="AI 问答"
      width="560px"
      append-to-body
      :close-on-click-modal="false"
      class="qa-stream-dialog"
      @close="onStreamClose"
    >
      <div class="qa-stream">
        <div class="qa-detail__label">提问</div>
        <div class="qa-detail__q">{{ streamQuestion }}</div>
        <div class="qa-detail__label">回答</div>
        <div ref="streamBodyRef" class="qa-stream__body">
          <div v-if="!streamAnswer && asking" class="qa-answer is-thinking">
            <span class="dot-bounce"></span> 大模型正在分析，请稍候…
          </div>
          <div v-else class="qa-detail__a">
            {{ streamAnswer }}<span v-if="asking" class="qa-stream__cursor"></span>
          </div>
        </div>
        <div v-if="streamError" class="qa-stream__error">
          <el-icon><WarningFilled /></el-icon> {{ streamError }}
        </div>
      </div>
      <template #footer>
        <el-button v-if="asking" @click="onAbortStream">停止</el-button>
        <el-button type="primary" @click="streamVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 系统提示词弹窗（6.3）：展示 / 编辑 / 恢复默认 -->
    <el-dialog v-model="promptVisible" title="系统提示词" width="640px" append-to-body>
      <div class="qa-prompt-hint">
        按用户保存、跨会话持久；未设置（或恢复默认）时使用内置默认提示词。修改仅影响本人后续提问。
      </div>
      <el-input
        v-model="promptText"
        type="textarea"
        :rows="14"
        resize="vertical"
        :disabled="promptLoading"
        placeholder="系统提示词（system 角色）"
      />
      <template #footer>
        <el-button :loading="promptLoading" @click="onResetPrompt">恢复默认</el-button>
        <el-button @click="promptVisible = false">取消</el-button>
        <el-button type="primary" :loading="promptSaving" @click="onSavePrompt">保存</el-button>
      </template>
    </el-dialog>

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
/**
 * QaPanel.vue — 问答面板
 * 6.1：提问携带当前股票 code / period 上下文（design D8.4 结构注入由后端自动完成）
 * 6.2：SSE 流式回答对话框（fetch + ReadableStream，见 api/modules/qa.ts）
 * 6.3：系统提示词对话框（按用户 GET/PUT，恢复默认 = PUT 空串）
 * 6.4：mock 侧按登录账号隔离记录 + 假流式（mock/handlers/qa.ts）
 */
import { ref, watch, nextTick, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Star, StarFilled, Promotion, Loading, Setting, WarningFilled } from '@element-plus/icons-vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import {
  askQuestionStream,
  getQaRecords,
  starQaRecord,
  batchStarQa,
  deleteUnstarredQa,
  getSystemPrompt,
  updateSystemPrompt,
} from '@/api/modules/qa'
import type { QaRecord } from '@/api/types'

const props = defineProps<{
  /** 当前股票代码 / 周期：提问时携带，用于结构上下文注入 */
  code: string
  period: string
}>()

const question = ref('')
const asking = ref(false)
const records = ref<QaRecord[]>([])
const latest = ref<QaRecord | null>(null)
const selectedIds = ref<number[]>([])

const detailVisible = ref(false)
const detail = ref<QaRecord | null>(null)

// --- 流式回答对话框状态 ---
const streamVisible = ref(false)
const streamQuestion = ref('')
const streamAnswer = ref('')
const streamError = ref('')
const streamBodyRef = ref<HTMLElement | null>(null)
let abortCtrl: AbortController | null = null

// --- 系统提示词对话框状态 ---
const promptVisible = ref(false)
const promptText = ref('')
const promptLoading = ref(false)
const promptSaving = ref(false)

async function loadRecords() {
  try {
    records.value = await getQaRecords()
  } catch (e) {
    console.warn('[QaPanel.loadRecords] 加载问答记录失败', {
      error: e instanceof Error ? e.message : String(e),
    })
    records.value = []
  }
}

/** 流式回答时自动滚到底部 */
watch(streamAnswer, async () => {
  await nextTick()
  const el = streamBodyRef.value
  if (el) el.scrollTop = el.scrollHeight
})

async function onAsk() {
  const q = question.value.trim()
  if (!q) {
    ElMessage.warning('请输入问题')
    return
  }
  asking.value = true
  streamQuestion.value = q
  streamAnswer.value = ''
  streamError.value = ''
  streamVisible.value = true
  abortCtrl = new AbortController()

  await askQuestionStream(
    { question: q, code: props.code, period: props.period },
    {
      onDelta: (text) => {
        streamAnswer.value += text
      },
      onDone: async (rec) => {
        // 成功才清空草稿、落定最新回答并刷新列表（中途失败草稿保留可重试）
        question.value = ''
        latest.value = rec
        await loadRecords()
        if (!records.value.some((r) => r.id === rec.id)) {
          // 后置校验：done 记录未出现在列表中时本地兜底插入
          console.warn('[QaPanel.onDone] done 记录未出现在列表，本地兜底插入', { id: rec.id })
          records.value = [rec, ...records.value]
        }
      },
      onError: (detail) => {
        streamError.value = detail
      },
    },
    abortCtrl.signal,
  )
  asking.value = false
}

/** 关闭弹窗：生成中则中断请求（中断不产生残缺记录） */
function onStreamClose() {
  if (asking.value) {
    abortCtrl?.abort()
    asking.value = false
    ElMessage.info('已中断本次生成')
  }
}

function onAbortStream() {
  abortCtrl?.abort()
  asking.value = false
  streamVisible.value = false
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

// --- 系统提示词（6.3） ---
async function openPromptDialog() {
  promptVisible.value = true
  promptLoading.value = true
  try {
    const res = await getSystemPrompt()
    promptText.value = res.prompt
  } catch (e) {
    console.warn('[QaPanel.openPromptDialog] 读取系统提示词失败', {
      error: e instanceof Error ? e.message : String(e),
    })
    ElMessage.error('读取系统提示词失败')
  } finally {
    promptLoading.value = false
  }
}

async function onSavePrompt() {
  promptSaving.value = true
  try {
    await updateSystemPrompt(promptText.value)
    ElMessage.success('系统提示词已保存')
    promptVisible.value = false
  } catch {
    // 失败已处理
  } finally {
    promptSaving.value = false
  }
}

async function onResetPrompt() {
  try {
    await ElMessageBox.confirm('确定恢复为内置默认提示词吗？当前自定义内容将被清空。', '恢复默认', {
      type: 'warning',
      confirmButtonText: '恢复默认',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  promptLoading.value = true
  try {
    await updateSystemPrompt('') // 恢复默认 = PUT 空串
    const res = await getSystemPrompt()
    promptText.value = res.prompt
    ElMessage.success('已恢复默认提示词')
  } catch {
    // 失败已处理
  } finally {
    promptLoading.value = false
  }
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
.qa-input__actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-sm);
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
  background: var(--accent-dim);
  border-color: var(--accent-border);
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

/* 流式回答弹窗 */
.qa-stream {
  display: flex;
  flex-direction: column;
  gap: var(--sp-sm);
}
.qa-stream__body {
  max-height: 46vh;
  overflow-y: auto;
}
.qa-stream__cursor {
  display: inline-block;
  width: 7px;
  height: 14px;
  margin-left: 2px;
  vertical-align: -2px;
  background: var(--accent-base);
  animation: blink 0.9s step-start infinite;
}
@keyframes blink {
  50% { opacity: 0; }
}
.qa-stream__error {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--rise);
  background: var(--rise-dim);
  border: 1px solid var(--rise);
  border-radius: var(--r-md);
  padding: var(--sp-sm) var(--sp-md);
}

/* 系统提示词弹窗 */
.qa-prompt-hint {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: var(--sp-sm);
  line-height: 1.6;
}

/* 详情 / 流式弹窗共用文本块 */
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
