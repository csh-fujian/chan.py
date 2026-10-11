<template>
  <el-dialog
    v-model="visibleRef"
    :title="`新建任务 · ${definition?.name || ''}`"
    width="640px"
    append-to-body
    :close-on-click-modal="false"
  >
    <div v-if="definition" class="task-dialog-body">
      <p class="dialog-hint">
        任务为策略执行的原子单位：参数与范围创建后可暂停编辑，历史信号按参数版本归因。
      </p>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="110px">
        <el-form-item label="任务名" prop="label">
          <el-input v-model="form.label" placeholder="如：回调5日" maxlength="20" style="width: 260px" />
        </el-form-item>
        <!-- 分组：下拉选择已有分组 / 输入新分组名（创建即归入，spec：自定义分组） -->
        <el-form-item label="分组" prop="user_group">
          <el-select
            v-model="form.user_groupMode"
            placeholder="选择分组方式"
            style="width: 180px"
            @change="onGroupModeChange"
          >
            <el-option label="新建分组" value="new" />
            <el-option label="不分组" value="none" />
            <el-option v-for="g in props.knownGroups" :key="g" :label="g" :value="g" />
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
        <!-- 参数项按 definition.params_schema 声明动态渲染（design D5/D6 schema 驱动）：
             int → 整数输入；float → 一位小数；enum → el-select 下拉（options 声明，
             vp-entry-strategy-integration D4）；min/max 与选项集由输入控件与后端双侧校验；
             desc 悬浮 tooltip 图标（design D6：desc 透出给前端） -->
        <el-form-item
          v-for="p in definition.params_schema"
          :key="p.key"
          :label="p.label"
          :prop="`params.${p.key}`"
          :rules="paramRules(p)"
        >
          <!-- enum 参数：下拉选择（options 声明的选项集，缺省选中 default） -->
          <el-select
            v-if="p.type === 'enum'"
            v-model="form.params[p.key]"
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
               precision/step 渲染（strategy-signal-outcome D12/6.9，修硬编码
               precision=1/step=0.1 导致 a_pct_min 只能拨 0.1 档的缺陷）；
               声明缺省时按 default 小数位推导（0.05 → 2/0.01；2.0 → 1/0.1；
               int → 0/1）；min/max 与后端双侧校验 -->
          <el-input-number
            v-else
            v-model="form.params[p.key]"
            :min="p.min"
            :max="p.max"
            :precision="paramPrecision(p)"
            :step="paramStep(p)"
            controls-position="right"
            style="width: 180px"
          />
          <span v-if="p.type !== 'enum'" class="param-range num">{{ p.min }} ~ {{ p.max }}</span>
          <!-- desc 悬浮说明图标 -->
          <el-tooltip v-if="p.desc" :content="p.desc" placement="top" :show-after="200">
            <el-icon class="param-desc-icon"><QuestionFilled /></el-icon>
          </el-tooltip>
        </el-form-item>

        <el-divider content-position="left">股票范围</el-divider>
        <!-- 范围三来源（spec）：manual 手动批量 / watchlist 自选文件夹（拷贝快照）/
             bsp_query 买卖点查询条件；未选任何股票 → 全量 A 股兜底（默认排 ST/*ST） -->
        <el-form-item label="范围来源">
          <el-radio-group v-model="form.scopeSource">
            <el-radio value="manual">手动添加</el-radio>
            <el-radio value="watchlist">自选文件夹</el-radio>
            <el-radio value="bsp_query">买卖点查询</el-radio>
            <el-radio value="all">全量 A 股</el-radio>
          </el-radio-group>
        </el-form-item>

        <!-- manual：股票搜索 + 已选列表 -->
        <template v-if="form.scopeSource === 'manual'">
          <el-form-item label="选择股票">
            <el-autocomplete
              v-model="stockInput"
              :fetch-suggestions="queryStocks"
              :trigger-on-focus="false"
              :debounce="300"
              placeholder="代码 / 名称 / 拼音，回车或点选添加"
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
          <el-form-item v-if="form.scopeCodes.length > 0" label="已选股票">
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

        <!-- watchlist：文件夹下拉（spec：拷贝该文件夹股票为固化快照） -->
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

        <!-- bsp_query：买卖点查询条件（spec：复用 /bsp 页查询条件查询并固化） -->
        <template v-if="form.scopeSource === 'bsp_query'">
          <el-form-item label="买卖点类型">
            <el-select v-model="form.bspQuery.bsp_type" placeholder="全部类型" style="width: 180px" clearable>
              <el-option v-for="t in ALL_BSP_LABELS" :key="t" :label="t" :value="t" />
            </el-select>
          </el-form-item>
          <el-form-item label="周期">
            <el-select v-model="form.bspQuery.kl_type" placeholder="全部周期" style="width: 180px" clearable>
              <el-option v-for="kl in klOptions" :key="kl.value" :label="kl.label" :value="kl.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="日期范围">
            <el-date-picker
              v-model="bspDateRange"
              type="daterange"
              value-format="YYYY-MM-DD"
              start-placeholder="开始日期"
              end-placeholder="结束日期"
              unlink-panels
              clearable
              style="width: 320px"
            />
          </el-form-item>
        </template>

        <!-- all：全量兜底提示（spec：默认排除 ST 与 *ST） -->
        <el-form-item v-if="form.scopeSource === 'all'">
          <p class="scope-hint">
            未选择股票时默认全量扫描所有 A 股，执行时自动排除 ST 与 *ST 股票。
            全量范围任务仅维护聚合计数，不落逐股结果。
          </p>
        </el-form-item>
      </el-form>
    </div>
    <template #footer>
      <el-button @click="visibleRef = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="onSave">创建任务</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules, type FormItemRule } from 'element-plus'
import { QuestionFilled } from '@element-plus/icons-vue'
import { createStrategyTask, type CreateStrategyTaskPayload } from '@/api/modules/strategy'
import { searchStocks } from '@/api/modules/stock'
import { getFolders } from '@/api/modules/watchlist'
import { ALL_BSP_LABELS } from '@/utils/bsp'
import type { StrategyDefinition, StrategyParamSchema } from '@/api/types'

/**
 * 新建任务弹窗（strategy-task-redesign 4.3）：
 * - 表单项由 definition.params_schema 声明驱动渲染（int/float → el-input-number），
 *   desc 悬浮 tooltip 说明；min/max 前端拦截（422 后端校验兜底由拦截器提示）
 * - 任务命名 + 分组选择/新建（spec：自定义分组，新分组名直接创建）
 * - 股票范围三来源（manual 手动批量 / watchlist 文件夹拷贝快照 / bsp_query 查询条件），
 *   未选任何股票 → 'all' 全量 A 股兜底（默认排 ST/*ST，仅聚合不落逐股结果）
 */
const props = defineProps<{
  visible: boolean
  definition: StrategyDefinition | null
  /** 已有分组名（下拉可选项来源；新建分组直接输入名称） */
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

/** 自选文件夹（watchlist 来源下拉数据） */
const folders = ref<{ id: number; name: string; codes: string[] }[]>([])

/** 买卖点查询条件：周期下拉选项（与 BspView 同款） */
const klOptions = [
  { label: '30分', value: '30m' },
  { label: '60分', value: '60m' },
  { label: '日线', value: 'D' },
  { label: '周线', value: 'W' },
  { label: '月线', value: 'M' },
]

const form = reactive({
  label: '',
  /** 分组模式：'new' 新建 / 'none' 不分组 / 已有分组名（直接作为值） */
  user_groupMode: 'none',
  user_group: '',
  /** 参数值（int/float → 数值，enum → 选项 value 字符串） */
  params: {} as Record<string, number | string>,
  scopeSource: 'all' as 'manual' | 'watchlist' | 'bsp_query' | 'all',
  /** manual 已选 code 列表 */
  scopeCodes: [] as string[],
  /** watchlist 文件夹 id */
  folderId: null as number | null,
  bspQuery: {
    bsp_type: '',
    kl_type: '',
    date_from: '',
    date_to: '',
  },
})

const bspDateRange = ref<[string, string] | null>(null)

const rules: FormRules = {
  label: [{ required: true, message: '请输入任务名', trigger: 'blur' }],
}

function onGroupModeChange() {
  if (form.user_groupMode !== 'new') form.user_group = ''
}

// ---- 输入精度推导（strategy-signal-outcome D12/6.9）----
// 声明优先（params_schema 的 precision/step 展示元数据字段）；
// 缺省按 default 小数位推导：0.05 → precision 2 / step 0.01；
// 2.0 → 1 / 0.1；int → 0 / 1（enum 无输入精度，不进此分支）
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

/** 参数项校验规则（前端拦截非法参数；后端 422 兜底）：
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

// 打开时按 schema 重置表单（默认值取声明 default）
watch(
  () => props.visible,
  async (v) => {
    if (!v || !props.definition) return
    form.label = ''
    form.user_groupMode = 'none'
    form.user_group = ''
    form.params = {}
    for (const p of props.definition.params_schema) {
      form.params[p.key] = p.default
    }
    form.scopeSource = 'all'
    form.scopeCodes = []
    form.folderId = null
    form.bspQuery = { bsp_type: '', kl_type: '', date_from: '', date_to: '' }
    bspDateRange.value = null
    stockInput.value = ''
    // 懒加载自选文件夹（watchlist 来源下拉）
    if (folders.value.length === 0) {
      try {
        folders.value = await getFolders()
      } catch {
        folders.value = [] // 失败已由拦截器提示；下拉置空可切其他来源
      }
    }
  },
)

// ---- manual 股票搜索（el-autocomplete 模糊下拉选 code） ----
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
  if (!formRef.value || !props.definition) return
  try {
    await formRef.value.validate()
  } catch {
    return // 校验失败信息已由表单展示
  }
  saving.value = true
  try {
    // 范围三来源 → 请求体映射（未选股票 = 'all' 全量兜底）
    const scopeSource =
      form.scopeSource === 'manual' && form.scopeCodes.length === 0 ? 'all' : form.scopeSource
    const payload: CreateStrategyTaskPayload = {
      strategy_id: props.definition.id,
      label: form.label.trim(),
      // 分组：新建模式传输入名；'none' 传空串（未分组）；已有分组名直接作为值
      user_group:
        form.user_groupMode === 'new'
          ? form.user_group.trim()
          : form.user_groupMode === 'none'
            ? ''
            : form.user_groupMode,
      params: { ...form.params },
      scope_type: scopeSource,
    }
    if (scopeSource === 'manual') {
      payload.scope_codes = [...form.scopeCodes]
    } else if (scopeSource === 'watchlist') {
      if (form.folderId == null) {
        ElMessage.warning('请选择自选文件夹')
        return
      }
      payload.folder_id = form.folderId
    } else if (scopeSource === 'bsp_query') {
      payload.bsp_query = {
        bsp_type: form.bspQuery.bsp_type || undefined,
        kl_type: form.bspQuery.kl_type || undefined,
        date_from: bspDateRange.value?.[0] || undefined,
        date_to: bspDateRange.value?.[1] || undefined,
      }
    }
    await createStrategyTask(payload)
    ElMessage.success('任务已创建（待执行状态，可启动扫描）')
    emit('saved')
    visibleRef.value = false
  } catch {
    // 422 参数/范围校验错误已由拦截器按后端 detail 提示，保留弹窗供修改重试
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.task-dialog-body {
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
