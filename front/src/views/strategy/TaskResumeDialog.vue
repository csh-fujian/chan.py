<template>
  <el-dialog
    v-model="visibleRef"
    :title="`续跑任务 · ${task?.label || ''}`"
    width="480px"
    append-to-body
    :close-on-click-modal="false"
  >
    <div v-if="task">
      <p class="dialog-hint">
        当前进度 {{ task.progress_scanned }} / {{ task.progress_total }}（参数 v{{ task.params_version }}）。
        选择续跑方式：
      </p>
      <el-radio-group v-model="rerunMode" class="rerun-group">
        <!-- 重新运行（默认，design D2/spec：清空旧信号与逐股结果，按当前参数从头全量执行） -->
        <el-radio value="full" class="rerun-item">
          <div class="rerun-title">
            重新运行（默认）
            <span class="rerun-sub">清空已产生的信号与逐股结果，按当前参数从头全量重扫</span>
          </div>
        </el-radio>
        <!-- 剩余股票继续（spec：保留已扫结果，从当前进度起用新参数继续剩余股票） -->
        <el-radio value="remaining" class="rerun-item">
          <div class="rerun-title">
            剩余股票继续
            <span class="rerun-sub">
              保留前 {{ task.progress_scanned }} 只的既有结果（旧参数产物），从第
              {{ task.progress_scanned + 1 }} 只起用当前参数（参数 v{{ task.params_version }}）继续
            </span>
          </div>
        </el-radio>
      </el-radio-group>
      <p class="rerun-hint">
        两种方式均使用当前生效参数执行剩余部分；历史信号携带各自参数版本，可按版本区分归因。
      </p>
    </div>
    <template #footer>
      <el-button @click="visibleRef = false">取消</el-button>
      <el-button type="primary" :loading="running" @click="onResume">开始续跑</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { resumeStrategyTask, type ResumeMode } from '@/api/modules/strategy'
import type { StrategyTask } from '@/api/types'

/**
 * 续跑选择弹窗（strategy-task-redesign 4.4，design D2 两种语义）：
 * - 重新运行（默认）：清空旧信号与逐股结果，按当前参数从头全量执行
 * - 剩余股票继续：保留已扫股票既有结果，从当前进度用新参数续扫剩余股票
 * 任务入口从任务列表「续跑」（paused/done）与编辑保存后引导触发。
 */
const props = defineProps<{
  visible: boolean
  task: StrategyTask | null
}>()
const emit = defineEmits<{
  'update:visible': [v: boolean]
  resumed: []
}>()

const visibleRef = ref(props.visible)
watch(() => props.visible, (v) => (visibleRef.value = v))
watch(visibleRef, (v) => emit('update:visible', v))

const running = ref(false)
/** 续跑方式（默认 'full' 重新运行，spec） */
const rerunMode = ref<ResumeMode>('full')

// 打开时重置为默认「重新运行」
watch(
  () => props.visible,
  (v) => {
    if (v) rerunMode.value = 'full'
  },
)

async function onResume() {
  if (!props.task) return
  running.value = true
  try {
    await resumeStrategyTask(props.task.id, rerunMode.value)
    ElMessage.success(
      rerunMode.value === 'full'
        ? `任务「${props.task.label}」已重新运行（旧信号已清空，按参数 v${props.task.params_version} 重扫）`
        : `任务「${props.task.label}」已从剩余股票继续（新增信号按参数 v${props.task.params_version} 归因）`,
    )
    emit('resumed')
    visibleRef.value = false
  } catch {
    // 409（不可续跑状态等）已由拦截器提示
  } finally {
    running.value = false
  }
}
</script>

<style scoped>
.dialog-hint {
  font-size: 12px;
  color: var(--text-disabled);
  margin: 0 0 var(--sp-md);
  padding: var(--sp-sm) var(--sp-md);
  background: var(--bg-surface-hover);
  border-radius: var(--r-md);
}
.rerun-group {
  display: flex;
  flex-direction: column;
  gap: var(--sp-sm);
  width: 100%;
}
.rerun-item {
  display: flex;
  align-items: flex-start;
  height: auto;
  padding: var(--sp-sm) var(--sp-md);
  border: 1px solid var(--border-base);
  border-radius: var(--r-md);
}
.rerun-title {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 13px;
  color: var(--text-primary);
}
.rerun-sub {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-secondary);
  line-height: 1.5;
}
.rerun-hint {
  margin: var(--sp-md) 0 0;
  font-size: 11px;
  color: var(--text-disabled);
  line-height: 1.6;
}
</style>
