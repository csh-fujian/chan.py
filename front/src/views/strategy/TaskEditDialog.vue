<template>
  <el-dialog
    v-model="visibleRef"
    :title="`编辑任务 · ${task?.label || ''}`"
    width="640px"
    append-to-body
    :close-on-click-modal="false"
  >
    <div v-if="task && definition">
      <p class="dialog-hint">
        仅暂停状态的任务可编辑。保存后需选择续跑方式（重新运行 / 剩余股票继续）才会重新执行。
      </p>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="110px">
        <el-form-item label="任务名" prop="label">
          <el-input v-model="form.label" placeholder="任务名" maxlength="20" style="width: 260px" />
        </el-form-item>
        <!-- 分组：下拉选择已有分组 / 输入新分组名 -->
        <el-form-item label="分组">
          <el-select
            v-model="form.user_groupMode"
            placeholder="选择分组方式"
            style="width: 180px"
            @change="onGroupModeChange"
          >
            <el-option label="新建分组" value="new" />
            <el-option label="不分组" value="none" />
            <el-option v-for="g in groupOptions" :key="g" :label="g" :value="g" />
          </el-select>
          <el-input
            v-if="form.user_groupMode === 'new'"
            v-model="form.user_group"
            placeholder="新分组名"
            maxlength="20"
            style="width: 160px; margin-left: 8px"
          />
        </el-form-item>

        <el-divider content-position="left">策略参数</el-divider>
        <!-- persistent 任务参数冻结（spec：转正冻结经测试验证的参数组，调参请复制任务） -->
        <p v-if="isPersistent" class="frozen-hint">
          <el-icon><Lock /></el-icon>
          长期任务参数已冻结（转正冻结的是经测试验证的参数组）。调参请复制任务为新的测试任务。
        </p>
        <el-form-item
          v-for="p in definition.params_schema"
          :key="p.key"
          :label="p.label"
          :prop="isPersistent ? undefined : `params.${p.key}`"
          :rules="isPersistent ? undefined : paramRules(p)"
        >
          <!-- enum 参数：下拉选择（options 声明选项集，vp-entry-strategy-integration D4） -->
          <el-select
            v-if="p.type === 'enum'"
            v-model="form.params[p.key]"
            :disabled="isPersistent"
            :placeholder="`选择${p.label}`"
            style="width: 180px"
          >
            <el-option
              v-for="opt in p.options || []"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
          <!-- int/float 参数：数值输入——精度按 params_schema 声明的
               precision/step 渲染（strategy-signal-outcome D12/6.9），
               缺省按 default 小数位推导 -->
          <el-input-number
            v-else
            v-model="form.params[p.key]"
            :disabled="isPersistent"
            :min="p.min"
            :max="p.max"
            :precision="paramPrecision(p)"
            :step="paramStep(p)"
            controls-position="right"
            style="width: 180px"
          />
          <span v-if="p.type !== 'enum'" class="param-range num">{{ p.min }} ~ {{ p.max }}</span>
          <el-tooltip v-if="p.desc" :content="p.desc" placement="top" :show-after="200">
            <el-icon class="param-desc-icon"><QuestionFilled /></el-icon>
          </el-tooltip>
        </el-form-item>

        <el-divider content-position="left">股票范围</el-divider>
        <el-form-item label="范围来源">
          <el-radio-group v-model="form.scopeSource">
            <el-radio value="manual">手动添加</el-radio>
            <el-radio value="watchlist">自选文件夹</el-radio>
            <el-radio value="all">全量 A 股</el-radio>
          </el-radio-group>
        </el-form-item>
        <!-- 编辑态不提供 bsp_query（原任务快照已固化，重选走 manual/watchlist/全量） -->

        <!-- manual：展示当前快照 codes，可增删 -->
        <template v-if="form.scopeSource === 'manual'">
          <el-form-item label="添加股票">
            <el-autocomplete
              v-model="stockInput"
              :fetch-suggestions="queryStocks"
              :trigger-on-focus="false"
              :debounce="300"
              placeholder="代码 / 名称 / 拼音，点选添加"
              clearable
              style="width: 320px"
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
          </el-form-item>
          <el-form-item v-if="form.scopeCodes.length > 0" label="范围股票">
            <div class="selected-codes">
              <el-tag
                v-for="code in form.scopeCodes"
                :key="code"
                closable
                size="small"
                @close="removeCode(code)"
              >
                {{ code }}
              </el-tag>
              <span class="num selected-count">共 {{ form.scopeCodes.length }} 只</span>
            </div>
          </el-form-item>
        </template>

        <!-- watchlist：重选文件夹（重新固化快照，下次执行生效） -->
        <el-form-item v-if="form.scopeSource === 'watchlist'" label="自选文件夹">
          <el-select
            v-model="form.folderId"
            placeholder="选择文件夹（股票将被拷贝为快照）"
            style="width: 320px"
          >
            <el-option
              v-for="f in folders"
              :key="f.id"
              :label="`${f.name}（${f.codes.length} 只）`"
              :value="f.id"
            />
          </el-select>
        </el-form-item>

        <!-- all：全量兜底提示（spec：默认排除 ST 与 *ST） -->
        <el-form-item v-if="form.scopeSource === 'all'">
          <p class="scope-hint">
            切换为全量 A 股扫描，执行时自动排除 ST 与 *ST 股票；全量范围不落逐股结果，仅维护聚合计数。
          </p>
        </el-form-item>
      </el-form>
    </div>
    <template #footer>
      <el-button @click="visibleRef = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="onSave">保存编辑</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules, type FormItemRule } from 'element-plus'
import { QuestionFilled, Lock } from '@element-plus/icons-vue'
import { updateStrategyTask, type UpdateStrategyTaskPayload } from '@/api/modules/strategy'
import { searchStocks } from '@/api/modules/stock'
import { getFolders } from '@/api/modules/watchlist'
import type { StrategyDefinition, StrategyParamSchema, StrategyTask } from '@/api/types'

/**
 * 任务编辑弹窗（strategy-task-redesign 4.4，仅 paused 可编辑——入口由父级控制）：
 * - test 任务：可编辑参数与范围；persistent 任务：仅范围（参数冻结禁用 + 提示复制任务调参）
 * - 参数修改保存后 params_version 递增（后端语义），历史信号按版本归因
 * - 保存只落编辑；重新执行需在保存后续跑（重新运行 / 剩余股票继续，TaskResumeDialog 承载）
 */
const props = defineProps<{
  visible: boolean
  task: StrategyTask | null
  definition: StrategyDefinition | null
  knownGroups: string[]
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
const folders = ref<{ id: number; name: string; codes: string[] }[]>([])

/** persistent 任务：参数冻结（spec） */
const isPersistent = computed(() => props.task?.mode === 'persistent')

/** 分组下拉选项 = 已有分组 ∪ 当前任务分组 */
const groupOptions = computed<string[]>(() => {
  const set = new Set(props.knownGroups)
  if (props.task?.user_group) set.add(props.task.user_group)
  return Array.from(set)
})

const form = reactive({
  label: '',
  user_groupMode: 'none',
  user_group: '',
  /** 参数值（int/float → 数值，enum → 选项 value 字符串） */
  params: {} as Record<string, number | string>,
  scopeSource: 'all' as 'manual' | 'watchlist' | 'all',
  scopeCodes: [] as string[],
  folderId: null as number | null,
})

const rules: FormRules = {
  label: [{ required: true, message: '请输入任务名', trigger: 'blur' }],
}

function onGroupModeChange() {
  if (form.user_groupMode !== 'new') form.user_group = ''
}

// ---- 输入精度推导（strategy-signal-outcome D12/6.9）----
// 声明优先（params_schema 的 precision/step）；缺省按 default 小数位推导
// （0.05 → 2/0.01；2.0 → 1/0.1；int → 0/1）
function paramPrecision(p: StrategyParamSchema): number {
  if (p.precision != null) return p.precision
  if (p.type === 'int') return 0
  const s = String(p.default)
  const dot = s.indexOf('.')
  return dot === -1 ? 0 : s.length - dot - 1
}
function paramStep(p: StrategyParamSchema): number {
  if (p.step != null) return p.step
  if (p.type === 'int') return 1
  return +(Math.pow(10, -paramPrecision(p))).toFixed(paramPrecision(p))
}

/** 参数项校验规则（前端拦截；后端 422 兜底）：
 *  - int/float：required + min/max 范围
 *  - enum：取值必须在 options[].value 选项集内（vp-entry-strategy-integration D4） */
function paramRules(p: StrategyParamSchema): FormItemRule[] {
  return [
    {
      required: true,
      validator: (_rule, value: number | string, callback) => {
        if (p.type === 'enum') {
          const opts = p.options || []
          if (value == null || value === '') {
            callback(new Error(`请选择${p.label}`))
            return
          }
          if (!opts.some((o) => o.value === value)) {
            callback(
              new Error(`${p.label} 取值非法，合法选项：${opts.map((o) => o.label).join('、')}`),
            )
            return
          }
          callback()
          return
        }
        const num = Number(value)
        if (value == null || value === '' || !Number.isFinite(num)) {
          callback(new Error(`请输入${p.label}`))
          return
        }
        if (num < (p.min ?? -Infinity) || num > (p.max ?? Infinity)) {
          callback(new Error(`${p.label} 范围 ${p.min} ~ ${p.max}`))
          return
        }
        callback()
      },
      trigger: ['blur', 'change'],
    },
  ]
}

// 打开时按任务当前值填充表单
watch(
  () => props.visible,
  async (v) => {
    if (!v || !props.task || !props.definition) return
    const t = props.task
    form.label = t.label
    // 分组模式初始化：已有分组 → 选中该值；空 → 'none'
    form.user_groupMode = t.user_group || 'none'
    form.user_group = ''
    form.params = { ...t.params }
    // 范围初始化：显式范围（manual/watchlist/bsp_query）→ 按当前 scope_type 映射到可编辑三选项；
    // 'all' 或 bsp_query 快照 → 默认 manual 展示快照 codes（用户可改）
    form.scopeSource = t.scope_type === 'watchlist' ? 'watchlist' : t.scope_type === 'all' ? 'all' : 'manual'
    form.scopeCodes = t.scope_codes ? [...t.scope_codes] : []
    form.folderId = null
    stockInput.value = ''
    if (folders.value.length === 0) {
      try {
        folders.value = await getFolders()
      } catch {
        folders.value = []
      }
    }
  },
)

// ---- manual 股票搜索 ----
interface StockSuggestion {
  value: string
  code: string
  name: string
  placeholder?: boolean
}
const stockInput = ref('')

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
  if (item.code && !form.scopeCodes.includes(item.code)) {
    form.scopeCodes.push(item.code)
  }
  stockInput.value = ''
}

function removeCode(code: string) {
  form.scopeCodes = form.scopeCodes.filter((c) => c !== code)
}

// ---- 保存 ----
async function onSave() {
  if (!formRef.value || !props.task || !props.definition) return
  try {
    await formRef.value.validate()
  } catch {
    return
  }
  saving.value = true
  try {
    const payload: UpdateStrategyTaskPayload = {
      label: form.label.trim(),
      user_group:
        form.user_groupMode === 'new'
          ? form.user_group.trim()
          : form.user_groupMode === 'none'
            ? ''
            : form.user_groupMode,
    }
    // 参数：persistent 冻结不传（后端拒绝 + 409 提示兜底）；test 正常提交
    if (!isPersistent.value) {
      payload.params = { ...form.params }
    }
    // 范围：manual 未选股票 = 'all' 全量兜底（与创建语义一致）
    const scopeSource =
      form.scopeSource === 'manual' && form.scopeCodes.length === 0 ? 'all' : form.scopeSource
    payload.scope_type = scopeSource
    if (scopeSource === 'manual') {
      payload.scope_codes = [...form.scopeCodes]
    } else if (scopeSource === 'watchlist') {
      if (form.folderId == null) {
        ElMessage.warning('请选择自选文件夹')
        return
      }
      payload.folder_id = form.folderId
    }
    await updateStrategyTask(props.task.id, payload)
    ElMessage.success(
      isPersistent.value
        ? '范围已更新（快照重新固化，下次执行生效）'
        : '任务已保存；参数变化将在续跑时按新参数执行（历史信号按参数版本归因）',
    )
    emit('saved')
    visibleRef.value = false
  } catch {
    // 409（非 paused / persistent 传参数）等错误已由拦截器提示，保留弹窗供修改重试
  } finally {
    saving.value = false
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
.frozen-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0 0 var(--sp-sm);
  padding: var(--sp-sm) var(--sp-md);
  font-size: 12px;
  color: var(--warning);
  background: var(--warning-dim);
  border-radius: var(--r-md);
}
.param-range {
  margin-left: 8px;
  font-size: 11px;
  color: var(--text-disabled);
}
.param-desc-icon {
  margin-left: 6px;
  color: var(--text-disabled);
  cursor: help;
  font-size: 14px;
}
.param-desc-icon:hover {
  color: var(--accent-hover);
}
.selected-codes {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  max-width: 420px;
  align-items: center;
}
.selected-count {
  margin-left: 8px;
  font-size: 11px;
  color: var(--text-disabled);
}
.scope-hint {
  margin: 0;
  font-size: 12px;
  color: var(--text-secondary);
  padding: var(--sp-sm) var(--sp-md);
  background: var(--accent-dim);
  border-radius: var(--r-md);
  line-height: 1.6;
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
