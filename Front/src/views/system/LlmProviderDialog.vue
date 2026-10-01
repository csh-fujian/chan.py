<template>
  <el-dialog
    v-model="visible"
    title="新增 LLM 供应商"
    width="520px"
    :close-on-click-modal="false"
    append-to-body
    class="llm-dialog"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="onSave">
      <el-form-item label="名称" prop="name">
        <el-input v-model="form.name" placeholder="如 OpenAI / DeepSeek / 本地 Ollama" />
      </el-form-item>
      <el-form-item label="接口地址 base_url" prop="base_url">
        <el-input v-model="form.base_url" placeholder="https://api.openai.com/v1" class="mono-input" />
      </el-form-item>
      <el-form-item label="API Key" prop="api_key">
        <el-input v-model="form.api_key" type="password" show-password placeholder="sk-..." class="mono-input" />
      </el-form-item>
      <el-form-item label="模型" prop="model">
        <el-input v-model="form.model" placeholder="如 gpt-4o / deepseek-chat" class="mono-input" />
      </el-form-item>
    </el-form>

    <!-- 测试连接结果展示（{ok, detail}） -->
    <div v-if="testResult" class="llm-test-result" :class="testResult.ok ? 'is-ok' : 'is-fail'">
      <el-icon><CircleCheckFilled v-if="testResult.ok" /><CircleCloseFilled v-else /></el-icon>
      <span>{{ testResult.detail }}</span>
    </div>

    <template #footer>
      <el-button :loading="testing" @click="onTest">测试连接</el-button>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
/**
 * LlmProviderDialog.vue — 新增 LLM 供应商预设（design D8.1，6.5）
 * 保存前可对未保存配置测试连接（POST /api/system/llm/test 不带 id）。
 */
import { ref, reactive, watch, computed } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { CircleCheckFilled, CircleCloseFilled } from '@element-plus/icons-vue'
import * as systemApi from '@/api/modules/system'
import type { LlmTestResult } from '@/api/types'

const props = defineProps<{
  modelValue: boolean
}>()
const emit = defineEmits<{
  'update:modelValue': [v: boolean]
  saved: []
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const formRef = ref<FormInstance>()
const saving = ref(false)
const testing = ref(false)
const testResult = ref<LlmTestResult | null>(null)

const form = reactive({
  name: '',
  base_url: '',
  api_key: '',
  model: '',
})

const rules: FormRules = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  base_url: [{ required: true, message: '请输入接口地址', trigger: 'blur' }],
  api_key: [{ required: true, message: '请输入 API Key', trigger: 'blur' }],
  model: [{ required: true, message: '请输入模型名', trigger: 'blur' }],
}

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    Object.assign(form, { name: '', base_url: '', api_key: '', model: '' })
    testResult.value = null
  },
)

async function onTest() {
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await systemApi.testLlmProvider({
      base_url: form.base_url,
      api_key: form.api_key,
      model: form.model,
    })
  } catch (e) {
    testResult.value = {
      ok: false,
      detail: e instanceof Error ? e.message : '测试请求失败',
    }
  } finally {
    testing.value = false
  }
}

async function onSave() {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
  } catch {
    return
  }
  saving.value = true
  try {
    await systemApi.createLlmProvider({ ...form })
    ElMessage.success('已新增供应商预设')
    emit('saved')
    visible.value = false
  } catch {
    // 失败已处理
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.mono-input :deep(.el-input__inner) {
  font-family: var(--font-mono);
  font-size: 12px;
}

.llm-test-result {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  border-radius: var(--r-md);
  padding: var(--sp-sm) var(--sp-md);
  line-height: 1.5;
}
.llm-test-result.is-ok {
  color: var(--fall);
  background: var(--fall-dim);
  border: 1px solid var(--fall);
}
.llm-test-result.is-fail {
  color: var(--rise);
  background: var(--rise-dim);
  border: 1px solid var(--rise);
}
</style>
