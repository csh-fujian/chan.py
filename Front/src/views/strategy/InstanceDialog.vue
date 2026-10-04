<template>
  <el-dialog
    v-model="visibleRef"
    :title="`新建实例 · ${definition?.name || ''}`"
    width="480px"
    append-to-body
  >
    <div v-if="definition" class="instance-dialog-body">
      <p class="dialog-hint">
        实例创建后参数不可修改（历史信号随实例保留）；调整参数请新建实例。
      </p>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="110px">
        <el-form-item label="实例名" prop="label">
          <el-input v-model="form.label" placeholder="如：回调5日" maxlength="20" />
        </el-form-item>
        <!-- 参数项按 definition.params_schema 声明动态渲染（design D5 schema 驱动）：
             int → 整数输入；float → 一位小数；min/max 约束由输入控件与后端双侧校验 -->
        <el-form-item
          v-for="p in definition.params_schema"
          :key="p.key"
          :label="p.label"
          :prop="`params.${p.key}`"
          :rules="paramRules(p)"
        >
          <el-input-number
            v-model="form.params[p.key]"
            :min="p.min"
            :max="p.max"
            :precision="p.type === 'float' ? 1 : 0"
            :step="p.type === 'float' ? 0.1 : 1"
            controls-position="right"
            style="width: 180px"
          />
          <span class="param-range num">{{ p.min }} ~ {{ p.max }}</span>
        </el-form-item>
      </el-form>
    </div>
    <template #footer>
      <el-button @click="visibleRef = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="onSave">创建实例</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules, type FormItemRule } from 'element-plus'
import { createInstance } from '@/api/modules/strategy'
import type { StrategyDefinition, StrategyParamSchema } from '@/api/types'

/**
 * 新建实例弹窗（strategy-signal-page 任务 5.5）：
 * 表单项由 definition.params_schema 声明驱动渲染（int/float → el-input-number），
 * min/max 前端拦截（422 后端校验兜底由拦截器提示）；保存成功 emit saved。
 */
const props = defineProps<{
  visible: boolean
  definition: StrategyDefinition | null
}>()
const emit = defineEmits<{
  'update:visible': [v: boolean]
  saved: []
}>()

const visibleRef = ref(props.visible)
watch(() => props.visible, (v) => (visibleRef.value = v))
watch(visibleRef, (v) => emit('update:visible', v))

const formRef = ref<FormInstance>()
const saving = ref(false)

const form = reactive({
  label: '',
  params: {} as Record<string, number>,
})

const rules: FormRules = {
  label: [{ required: true, message: '请输入实例名', trigger: 'blur' }],
}

/** 参数项校验规则（required + min/max 范围，前端拦截非法参数） */
function paramRules(p: StrategyParamSchema): FormItemRule[] {
  return [
    {
      required: true,
      validator: (_rule, value: number, callback) => {
        if (value == null || !Number.isFinite(value)) {
          callback(new Error(`请输入${p.label}`))
          return
        }
        if (value < p.min || value > p.max) {
          callback(new Error(`${p.label} 范围 ${p.min} ~ ${p.max}`))
          return
        }
        callback()
      },
      trigger: 'blur',
    },
  ]
}

// 打开时按 schema 重置表单（默认值取声明 default）
watch(
  () => props.visible,
  (v) => {
    if (!v || !props.definition) return
    form.label = ''
    form.params = {}
    for (const p of props.definition.params_schema) {
      form.params[p.key] = p.default
    }
  },
)

async function onSave() {
  if (!formRef.value || !props.definition) return
  try {
    await formRef.value.validate()
  } catch {
    return // 校验失败信息已由表单展示
  }
  saving.value = true
  try {
    await createInstance({
      strategy_id: props.definition.id,
      label: form.label.trim(),
      params: { ...form.params },
    })
    ElMessage.success('实例已创建（已触发全量回算）')
    emit('saved')
    visibleRef.value = false
  } catch {
    // 422 参数校验错误已由拦截器按后端 detail 提示，保留弹窗供修改重试
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.instance-dialog-body {
  display: flex;
  flex-direction: column;
  gap: var(--sp-md);
}
.dialog-hint {
  font-size: 12px;
  color: var(--text-disabled);
  margin: 0;
  padding: var(--sp-sm) var(--sp-md);
  background: var(--bg-surface-hover);
  border-radius: var(--r-md);
}
.param-range {
  margin-left: 8px;
  font-size: 11px;
  color: var(--text-disabled);
}
</style>
