<template>
  <el-drawer
    v-model="visibleRef"
    title="任务详情"
    direction="rtl"
    size="720px"
    append-to-body
  >
    <div v-if="detail" v-loading="loading" class="detail-body">
      <!-- 头部：任务名 + 策略名 + 状态/形态/分组 badge -->
      <div class="detail-head">
        <div class="head-main">
          <span class="task-name">{{ detail.task.label }}</span>
          <span class="def-name">{{ detail.definition.name }}</span>
        </div>
        <span class="badge" :class="STATUS_COLOR[detail.task.status] || 'badge--default'">
          {{ STATUS_LABEL[detail.task.status] || detail.task.status }}
        </span>
        <span class="badge" :class="detail.task.mode === 'persistent' ? 'badge--accent' : 'badge--info'">
          {{ detail.task.mode === 'persistent' ? '长期任务' : '测试任务' }}
        </span>
        <span class="badge badge--default">{{ detail.task.user_group || '未分组' }}</span>
        <span class="badge badge--accent mono">参数 v{{ detail.task.params_version }}</span>
      </div>

      <!-- 任务元信息卡：范围/参数/创建信息 -->
      <div class="meta-card">
        <div class="meta-row">
          <label>股票范围</label>
          <div class="meta-value">
            <template v-if="detail.task.scope_type === 'all'">
              全量 A 股（执行时排除 ST/*ST，不落逐股结果）
            </template>
            <template v-else-if="detail.task.scope_codes">
              <span class="num">{{ detail.task.scope_codes.length }} 只 · </span>
              <span class="scope-codes mono" :title="detail.task.scope_codes.join('、')">
                {{ detail.task.scope_codes.slice(0, 8).join('、') }}{{ detail.task.scope_codes.length > 8 ? ' …' : '' }}
              </span>
            </template>
            <template v-else>--</template>
            <span v-if="SCOPE_LABEL[detail.task.scope_type]" class="scope-src">
              （来源：{{ SCOPE_LABEL[detail.task.scope_type] }}，已固化为快照）
            </span>
          </div>
        </div>
        <div class="meta-row" v-for="p in detail.definition.params_schema" :key="p.key">
          <label>{{ p.label }}</label>
          <!-- enum 参数值映射选项 label 展示（无匹配时兜底原值） -->
          <span class="meta-value" :class="p.type === 'enum' ? '' : 'num'">{{ paramDisplay(p) }}</span>
        </div>
        <div class="meta-row">
          <label>创建信息</label>
          <span class="meta-value">{{ detail.task.created_by }} 创建于 {{ fmtDateTime(detail.task.created_at) }}</span>
        </div>
      </div>

      <!-- detail_blocks 渲染器（按 detail_schema 声明顺序渲染积木块） -->
      <DetailBlocks
        :schema="detail.definition.detail_schema"
        :task="detail.task"
        :summary="detail.summary"
        :per-stock="detail.per_stock"
        :signals-page="detail.signals_page"
        :states="detail.definition.states"
        :columns="detail.definition.columns"
        :kv-payload="detail.kv_payload"
        :timeline="detail.timeline"
        @signal-click="onSignalClick"
      />
    </div>
    <EmptyState v-else-if="!loading" description="任务不存在或已删除" />
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import DetailBlocks from './detail_blocks/DetailBlocks.vue'
import { getStrategyTaskDetail } from '@/api/modules/strategy'
import type { StrategyTaskDetail, StrategySignalRow, StrategyParamSchema } from '@/api/types'

/**
 * 任务详情抽屉（strategy-task-redesign 4.5）：
 * GET /strategy/tasks/{id}/detail → 头部元信息 + detail_blocks 渲染器
 * （按所属定义 detail_schema 声明渲染；不同策略详情风格不同；
 *  scope='all' 时 per_stock 数据不返回 → 块静默隐藏）。
 */
const props = defineProps<{
  visible: boolean
  taskId: number | null
}>()
const emit = defineEmits<{
  'update:visible': [v: boolean]
}>()

const visibleRef = ref(props.visible)
watch(() => props.visible, (v) => (visibleRef.value = v))
watch(visibleRef, (v) => emit('update:visible', v))

const loading = ref(false)
const detail = ref<StrategyTaskDetail | null>(null)
let loadSeq = 0

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
const SCOPE_LABEL: Record<string, string> = {
  manual: '手动添加',
  watchlist: '自选文件夹',
  bsp_query: '买卖点查询',
}

async function loadDetail(id: number) {
  const seq = ++loadSeq
  loading.value = true
  detail.value = null
  try {
    const res = await getStrategyTaskDetail(id)
    if (seq !== loadSeq) return // 过期响应丢弃
    detail.value = res
    // 后置校验：详情必须携带定义声明（渲染器依赖）
    if (!res.definition?.detail_schema) {
      console.warn('[TaskDetailDrawer.loadDetail] 响应缺少 definition.detail_schema', { id })
    }
  } catch (e) {
    if (seq !== loadSeq) return
    console.warn('[TaskDetailDrawer.loadDetail] 任务详情加载失败', { id, error: e })
    detail.value = null
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

// 打开（visible && taskId）时拉取；关闭清状态
watch(
  [visibleRef, () => props.taskId],
  ([v, id]) => {
    if (v && id != null) {
      loadDetail(id)
    } else if (!v) {
      detail.value = null
      loadSeq++
    }
  },
)

/** 信号行点击 → 透传给父级（打开信号详情抽屉） */
function onSignalClick(row: StrategySignalRow) {
  console.info('[TaskDetailDrawer] 信号行点击', { code: row.code, taskId: props.taskId })
}

/** 参数值展示：enum 映射选项 label（取值不在选项集时兜底原值） */
function paramDisplay(p: StrategyParamSchema): string {
  const v = detail.value?.task.params[p.key]
  if (v == null) return '--'
  if (p.type === 'enum') {
    const opt = (p.options || []).find((o) => o.value === v)
    return opt ? opt.label : String(v)
  }
  return String(v)
}

function fmtDateTime(ts: number): string {
  const d = new Date(ts)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
</script>

<style scoped>
.detail-body {
  display: flex;
  flex-direction: column;
  gap: var(--sp-lg);
}
.detail-head {
  display: flex;
  align-items: center;
  gap: var(--sp-sm);
  flex-wrap: wrap;
}
.head-main {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
  margin-right: auto;
}
.task-name {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}
.def-name {
  font-size: 12px;
  color: var(--text-disabled);
}
.meta-card {
  display: flex;
  flex-direction: column;
  gap: var(--sp-sm);
  padding: var(--sp-md);
  border: 1px solid var(--border-base);
  border-radius: var(--r-md);
}
.meta-row {
  display: flex;
  align-items: baseline;
  font-size: 13px;
  gap: var(--sp-sm);
}
.meta-row label {
  width: 110px;
  flex-shrink: 0;
  color: var(--text-secondary);
  white-space: nowrap;
}
.meta-value {
  color: var(--text-primary);
  min-width: 0;
}
.scope-codes {
  font-size: 12px;
  color: var(--text-secondary);
  word-break: break-all;
}
.scope-src {
  font-size: 11px;
  color: var(--text-disabled);
}
</style>
