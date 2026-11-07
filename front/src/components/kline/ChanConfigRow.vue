<template>
  <div
    class="cfg-row"
    :class="{ 'is-modified': overridden, 'is-wide': param.control === 'multi' }"
  >
    <div class="cfg-row__head">
      <div class="cfg-row__label">
        <span class="cfg-row__name">{{ param.label }}</span>

        <!-- 问号：悬浮展开结构化解释卡片（不是一条挤在暗底上的小字） -->
        <el-popover
          placement="bottom-start"
          :width="392"
          popper-style="max-width: min(392px, calc(100vw - 32px));"
          trigger="hover"
          popper-class="cfg-tip"
          :show-after="120"
          :hide-after="80"
          :offset="8"
        >
          <template #reference>
            <button class="cfg-row__help" type="button" :aria-label="`${param.label} 参数说明`">
              <el-icon><QuestionFilled /></el-icon>
            </button>
          </template>

          <div class="cfg-tip__body">
            <div class="cfg-tip__eyebrow mono">PARAMETER · 参数说明</div>
            <div class="cfg-tip__title">{{ param.label }}</div>

            <p class="cfg-tip__plain">{{ param.plain }}</p>

            <section class="cfg-tip__sect">
              <div class="cfg-tip__sect-head">
                <span class="cfg-tip__sect-key">调大 / 调小</span>
              </div>
              <p class="cfg-tip__text">{{ param.effect }}</p>
            </section>

            <section class="cfg-tip__sect">
              <div class="cfg-tip__sect-head">
                <span class="cfg-tip__sect-key">影响范围</span>
              </div>
              <p class="cfg-tip__text">{{ param.scope }}</p>
            </section>

            <div class="cfg-tip__foot">
              <span class="cfg-tip__foot-item mono">出厂默认 · {{ formatDefault }}</span>
              <span v-if="param.conditional" class="cfg-tip__foot-tag">条件项</span>
            </div>
          </div>
        </el-popover>

        <!-- 已改：一键回到当前档位默认值 -->
        <button
          v-if="overridden && !readonly"
          class="cfg-row__reset"
          type="button"
          title="恢复当前档位默认值"
          @click="emit('reset')"
        >
          <el-icon><RefreshLeft /></el-icon>
        </button>
      </div>

      <!-- 控件区 -->
      <div class="cfg-row__control">
        <!-- 布尔 -->
        <el-switch
          v-if="param.control === 'bool'"
          :model-value="boolValue"
          size="small"
          :disabled="readonly"
          @update:model-value="onBoolInput"
        />

        <!-- 整数 / 数值 -->
        <div v-else-if="param.control === 'integer' || param.control === 'number'" class="cfg-num">
          <el-input-number
            :model-value="numValue"
            :min="param.min ?? undefined"
            :max="param.max ?? undefined"
            :step="param.step ?? (param.control === 'integer' ? 1 : 0.01)"
            :precision="param.control === 'integer' ? 0 : undefined"
            :controls="false"
            size="small"
            :disabled="readonly || isInf"
            :placeholder="isInf ? '不限' : ''"
            class="cfg-num__input"
            @update:model-value="onInput"
          />
          <!-- 允许 inf 的参数（divergence_rate）：∞ 胶囊开关代替勾选框 -->
          <button
            v-if="param.allow_inf"
            class="cfg-inf"
            :class="{ 'is-on': isInf }"
            type="button"
            :disabled="readonly"
            :title="isInf ? '当前不限：点击填回 1' : '点击表示不做该维度的限制（inf）'"
            @click="onInfToggle(!isInf)"
          >
            ∞<span>不限</span>
          </button>
        </div>

        <!-- 单选枚举 -->
        <el-select
          v-else-if="param.control === 'select'"
          :model-value="modelValue"
          size="small"
          class="cfg-select"
          :disabled="readonly"
          @update:model-value="onInput"
        >
          <el-option
            v-for="c in param.choices || []"
            :key="String(c)"
            :label="choiceLabel(c)"
            :value="normalizeChoice(c)"
          />
        </el-select>

        <!-- 档位预设 -->
        <el-select
          v-else-if="param.control === 'preset'"
          :model-value="modelValue"
          size="small"
          class="cfg-select"
          :disabled="readonly"
          @update:model-value="onPresetChange"
        >
          <el-option
            v-for="c in param.choices || []"
            :key="String(c)"
            :label="choiceLabel(c)"
            :value="normalizeChoice(c)"
          />
        </el-select>

        <!-- 多选（bs_type） -->
        <div v-else-if="param.control === 'multi'" class="cfg-multi">
          <el-checkbox
            v-for="c in param.choices || []"
            :key="String(c)"
            :model-value="multiValue.includes(String(normalizeChoice(c)))"
            size="small"
            :disabled="readonly"
            @update:model-value="onMultiToggle(c, $event)"
          >
            {{ choiceLabel(c) }}
          </el-checkbox>
        </div>

        <span v-else class="cfg-row__unsupported">（暂不支持的控件：{{ param.control }}）</span>
      </div>
    </div>

    <!-- 影响范围 + 改动态 -->
    <div class="cfg-row__meta">
      <span class="cfg-row__scope" :title="param.scope">{{ param.scope }}</span>
      <span v-if="overridden" class="cfg-row__badge" title="已偏离当前档位的默认值">已自定义</span>
    </div>

    <!-- 受限取值的常驻说明（不只藏在问号里） -->
    <div v-if="activeCaveat" class="cfg-row__caveat">
      <el-icon><WarningFilled /></el-icon>
      <span>{{ activeCaveat }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * ChanConfigRow.vue — 单个缠论参数的编辑行（chan-config-panel 5.4）。
 *
 * - 按 `control` 渲染控件：布尔 / 数值 / 单选 / 多选 / 档位
 * - 标签旁的问号悬浮显示**结构化解释卡片**：`plain`（是什么）/ `effect`（调大调小
 *   会怎样）/ `scope`（影响谁）。卡片使用设计令牌的前景与底色，不再用 Element 的
 *   暗色 popper（原实现是 #303133 底 + 11.5px 灰字，#b8b8b8 在深底上对比不足）。
 * - `caveat` 固定在行下方显示：受限取值（如 macd_algo 的量能类）必须一眼可见，
 *   不能只藏在 tooltip 里 —— 那是「你选的只半生效」的事实。
 * - 组件**不自己存状态**：值来自 `modelValue`，改动通过 `update:modelValue` 上抛，
 *   由 store 的草稿统一持有（草稿语义，见 design D9）。
 */
import { computed } from 'vue'
import { QuestionFilled, RefreshLeft, WarningFilled } from '@element-plus/icons-vue'
import type { ChanParamSchema } from '@/api/types'

const props = defineProps<{
  param: ChanParamSchema
  modelValue: unknown
  /**
   * 出厂默认值（`schema.kernel_defaults[key]`）。
   *
   * 不能用 `param.default` —— 那是按当前已保存配置反射的值，用户改过就跟着变，
   * 悬浮提示里「出厂默认」会显示成用户自己的值。
   */
  kernelDefault?: unknown
  /** 只读（无 manage 权限时禁用全部控件，但问号仍可看） */
  readonly?: boolean
  /** 相对当前档位基线已被改动（行内显示「已修改」并提供单项重置） */
  overridden?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: unknown]
  /** 单项恢复当前档位默认值 */
  reset: []
}>()

const readonly = computed(() => props.readonly === true)

/** 布尔值（`modelValue` 可能是 undefined，但布尔控件不应出现未定义） */
const boolValue = computed(() => props.modelValue === true)

/** 数值：`effective` 里可能是字符串形式的 "inf"（后端 JSONB 编码），统一转数字 */
const numValue = computed(() => {
  const v = props.modelValue
  if (typeof v === 'number') return Number.isFinite(v) ? v : undefined
  if (typeof v === 'string') {
    const n = Number(v)
    return Number.isFinite(n) ? n : undefined
  }
  return undefined
})

/**
 * 「不限（inf）」状态：只认显式的 `"inf"` / `Infinity`。
 *
 * 不能写成「`numValue` 为空即 inf」—— 用户清空输入框时值也是空，那样会把
 * 「还没填」误判成「勾了不限」，随后保存提交 `null`（后端一律拒绝）。
 */
const isInf = computed(() => {
  const v = props.modelValue
  if (!props.param.allow_inf) return false
  if (v === Infinity) return true
  return typeof v === 'string' && v.trim().toLowerCase() === 'inf'
})

/** 多选值（`bs_type` 是数组） */
const multiValue = computed<string[]>(() => {
  const v = props.modelValue
  if (Array.isArray(v)) return v.map(String)
  if (typeof v === 'string') return v.split(',').map((s) => s.trim()).filter(Boolean)
  return []
})

/**
 * 当前应显示的常驻说明：优先取「当前取值」的逐项说明（`choice_caveats`），
 * 没有则退回参数级 `caveat`。
 */
const activeCaveat = computed(() => {
  const table = props.param.choice_caveats
  if (table) {
    const key = String(props.modelValue)
    const hit = table[key]
    if (hit) return hit
  }
  return props.param.caveat || ''
})

const formatDefault = computed(() => {
  const kd = props.kernelDefault
  const v = kd === undefined ? props.param.default : kd
  if (v === Infinity || v === 'inf') return '不限（inf）'
  if (Array.isArray(v)) return v.join(', ')
  if (v === null || v === undefined) return '不限'
  if (typeof v === 'boolean') return v ? '开启' : '关闭'
  return String(v)
})

/**
 * 后端把枚举选项以 JSON 原样返回（数字型选项如 `bsp2_confirm_window` 是 `1`/`2`），
 * 直接用即可；字符串数字（极少数由 Python 枚举转出）统一转数字，避免选中不匹配。
 */
function normalizeChoice(c: string | number): string | number {
  return c
}

/** 选项展示名：有 `choice_labels` 用中文，否则用原值 */
function choiceLabel(c: string | number): string {
  const labels = props.param.choice_labels
  if (labels && labels[String(c)]) return labels[String(c)]
  return String(c)
}

function onInput(v: unknown): void {
  if (readonly.value) return
  // `null` 是合法语义：`max_bsp2s_lv` 等可空项「留空 = 不限制」必须能提交空值。
  // 非可空项收到 null 会由后端 422 拦下（`validate_config()` 拒绝 None），
  // 抽屉保持打开、错误定位到参数，不会静默写入坏配置。
  emit('update:modelValue', v ?? null)
}

/** 布尔开关：`el-switch` 的值可能是 boolean / string / number，统一转布尔 */
function onBoolInput(v: unknown): void {
  onInput(Boolean(v))
}

/**
 * 「不限（inf）」开关：开启写字符串 `"inf"`，关闭回到 1。
 *
 * 不能写数字 `Infinity` —— `JSON.stringify(Infinity)` 得到 `null`，后端收到的
 * 是空值，校验能过但计算期 `None <= 100` 会 `TypeError`。标准 JSON 也不允许
 * 非有限浮点，所以 `inf` 只能以字符串形态跨线；后端 `_decode_value()` 会把它
 * 还原成 `float("inf")`。
 */
function onInfToggle(v: boolean): void {
  onInput(v ? 'inf' : 1)
}

/**
 * 切换档位预设。
 *
 * 只上抛 `bsp_preset` 一个键的改动；**草稿里各参数的联动由 store 的
 * `switchPreset()` 负责** —— 它会把「用户没改过」的项换成新档位的预设值，
 * 让抽屉里显示的正是切换后将要生效的口径，同时保证 `computeOverrides()`
 * 不会把这些预设值误判成用户覆盖。
 */
function onPresetChange(v: unknown): void {
  if (readonly.value) return
  emit('update:modelValue', v)
}

/** 多选：保持参数原有顺序（`bs_type` 的展示顺序应与 schema 一致，不随勾选顺序变） */
function toggleMulti(value: string | number, on: boolean): void {
  if (readonly.value) return
  const order = (props.param.choices || []).map((c) => String(normalizeChoice(c)))
  const set = new Set(multiValue.value)
  if (on) set.add(String(value))
  else set.delete(String(value))
  emit('update:modelValue', order.filter((k) => set.has(k)))
}

/** 多选勾选回调（模板里 `$event` 是 unknown，收口到 `toggleMulti`） */
function onMultiToggle(choice: string | number, on: unknown): void {
  toggleMulti(String(normalizeChoice(choice)), Boolean(on))
}
</script>

<style scoped>
/* ---- 行卡片 ---------------------------------------------------------- */
.cfg-row {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
  padding: 10px 12px 9px;
  border: 1px solid var(--border-base);
  border-radius: var(--r-md);
  background: var(--bg-surface);
  transition:
    border-color 0.16s ease,
    background 0.16s ease,
    box-shadow 0.16s ease;
}
.cfg-row:hover {
  background: var(--bg-surface-hover);
  border-color: var(--border-strong);
}
.cfg-row.is-modified {
  border-color: color-mix(in srgb, var(--warning) 46%, var(--border-base));
  box-shadow: inset 2px 0 0 var(--warning);
}

.cfg-row__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sp-md);
  min-height: 26px;
}

.cfg-row__label {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  flex: 1 1 auto;
  padding-top: 3px;
}
/* 问号与重置按钮不允许被压扁 */
.cfg-row__label > .cfg-row__help,
.cfg-row__label > .cfg-row__reset {
  flex: 0 0 auto;
}

.cfg-row__name {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text-primary);
  line-height: 1.45;
  /* 不用 overflow-wrap: anywhere —— 中文标题在 12.5px 下两行仍可读，
     被截断成「背驰力度阈…」反而认不出是哪一项。 */
  min-width: 0;
}

.cfg-row__help {
  display: inline-grid;
  place-items: center;
  width: 16px;
  height: 16px;
  flex: 0 0 auto;
  padding: 0;
  border: none;
  background: transparent;
  border-radius: 50%;
  color: var(--text-disabled);
  cursor: help;
  transition: color 0.15s ease, background 0.15s ease;
}
.cfg-row__help:hover,
.cfg-row__help:focus-visible {
  color: var(--accent-hover);
  background: var(--accent-dim);
  outline: none;
}
.cfg-row__help :deep(.el-icon) {
  font-size: 13px;
}

.cfg-row__reset {
  display: inline-grid;
  place-items: center;
  width: 16px;
  height: 16px;
  flex: 0 0 auto;
  padding: 0;
  border: none;
  background: transparent;
  border-radius: 3px;
  color: var(--warning);
  opacity: 0.55;
  cursor: pointer;
  transition: opacity 0.15s ease, background 0.15s ease;
}
.cfg-row__reset:hover {
  opacity: 1;
  background: var(--warning-dim);
}
.cfg-row__reset :deep(.el-icon) {
  font-size: 12px;
}

.cfg-row__control {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  /* 控件不再吃满半行：数值 88px + ∞ 胶囊 ≈ 180px，下拉 200px。
     `max-width` 只是兜底，真正的宽度由各控件自己定，避免 grid 拉伸后
     标签和控件之间出现大片空白。 */
  max-width: 232px;
}

/* ---- 控件 ------------------------------------------------------------ */
.cfg-num {
  display: flex;
  align-items: center;
  gap: 6px;
}
.cfg-num__input {
  width: 88px;
}
.cfg-num__input :deep(.el-input__wrapper) {
  background: var(--bg-base);
  box-shadow: 0 0 0 1px var(--border-base) inset;
}

/* ∞ 不限：胶囊开关，比勾选框省一行空间也更易点中 */
.cfg-inf {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  height: 24px;
  padding: 0 8px;
  border-radius: var(--r-full);
  border: 1px solid var(--border-base);
  background: var(--bg-base);
  color: var(--text-secondary);
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1;
  transition: all 0.15s ease;
}
.cfg-inf span {
  font-family: var(--font-ui);
  font-size: 10.5px;
}
.cfg-inf:hover:not(:disabled) {
  color: var(--text-primary);
  border-color: var(--border-strong);
}
.cfg-inf.is-on {
  color: var(--warning);
  border-color: color-mix(in srgb, var(--warning) 55%, transparent);
  background: var(--warning-dim);
}
.cfg-inf:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.cfg-select {
  width: 200px;
}

.cfg-multi {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 12px;
  justify-content: flex-start;
  max-width: 100%;
  flex: 1 1 auto;
}
.cfg-multi :deep(.el-checkbox) {
  margin-right: 0;
  height: 24px;
}
.cfg-multi :deep(.el-checkbox__label) {
  font-size: 11.5px;
  padding-left: 5px;
}
/* 未选中偏暗，选中项保留 Element 的高亮色。
   注意 `is-checked` 挂在 `.el-checkbox__input` 上（不是根 `.el-checkbox`），
   写成 `:not(.is-checked)` 去排除根元素会永远匹配，把选中色一起压暗。 */
.cfg-multi :deep(.el-checkbox__input:not(.is-checked) + .el-checkbox__label) {
  color: var(--text-secondary);
}

/* 多选行：整行横跨网格，标签在上、候选项在下 */
.cfg-row.is-wide .cfg-row__head {
  flex-direction: column;
  align-items: stretch;
  gap: 6px;
}
.cfg-row.is-wide .cfg-row__label {
  padding-top: 0;
}
.cfg-row.is-wide .cfg-row__control {
  max-width: none;
  justify-content: flex-start;
}

/* ---- 元信息 ---------------------------------------------------------- */
.cfg-row__meta {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding-left: 1px;
}
.cfg-row__scope {
  flex: 1 1 auto;
  min-width: 0;
  font-size: 10.5px;
  line-height: 1.4;
  /* 用小字号而不是低对比度来区分次要层级：10.5px 的 --text-disabled
     （暗色 #565D66）在卡片底上只有约 2.5:1，正是「看不清」的主因。 */
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cfg-row__badge {
  flex: 0 0 auto;
  font-size: 9.5px;
  letter-spacing: 0.04em;
  padding: 1px 5px;
  border-radius: 3px;
  color: var(--warning);
  background: var(--warning-dim);
}

.cfg-row__caveat {
  display: flex;
  align-items: flex-start;
  gap: 5px;
  font-size: 11px;
  line-height: 1.45;
  color: var(--warning);
  opacity: 0.92;
}
.cfg-row__caveat :deep(.el-icon) {
  margin-top: 1px;
  flex: 0 0 auto;
  font-size: 11px;
}

.cfg-row__unsupported {
  font-size: 11.5px;
  color: var(--text-disabled);
}
</style>

<style>
/* --------------------------------------------------------------------------
   解释卡片（popper 挂在 body 上，wrapper 样式无法 scoped）
   关键修复：原实现是 Element 默认暗色 popper —— #303133 底 + 11.5px 字 +
   #b8b8b8 说明文字，深底低对比几乎读不清。这里改用设计令牌的前景/底色，
   正文 13px / 行高 1.75，说明文字用 --text-secondary（暗色下 #9BA1A8）。
   -------------------------------------------------------------------------- */
.cfg-tip.el-popover.el-popper {
  padding: 0 !important;
  background: var(--bg-surface) !important;
  border: 1px solid var(--border-strong) !important;
  border-radius: var(--r-lg) !important;
  color: var(--text-primary) !important;
  box-shadow: var(--shadow-popover) !important;
  /* Element 自带 line-height:1.4 / font-size：基础字号在 popper 根上，
     这里必须同样带足选择器权重才盖得住（单类 .cfg-tip 会输给 .el-popover.el-popper）。 */
  font-size: 12px;
  line-height: 1.65;
  /* 不要 overflow: hidden —— Element 的箭头是以 bottom:-5px 探出气泡外的，
     裁掉气泡溢出的部分会把箭头一起削掉。圆角改由内部 body 自己保证。 */
}
.cfg-tip.el-popover.el-popper .el-popper__arrow::before {
  background: var(--bg-surface) !important;
  border-color: var(--border-strong) !important;
}

.cfg-tip__body {
  padding: 14px 16px 12px;
  font-family: var(--font-ui);
  color: var(--text-primary);
}

.cfg-tip__eyebrow {
  font-size: 10px;
  letter-spacing: 0.14em;
  color: var(--text-secondary);
  margin-bottom: 5px;
}

.cfg-tip__title {
  font-size: 14px;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.cfg-tip__plain {
  margin: 0;
  font-size: 13px;
  line-height: 1.75;
  color: var(--text-primary);
}

.cfg-tip__sect {
  margin-top: 10px;
  padding-top: 9px;
  border-top: 1px solid var(--border-base);
}

.cfg-tip__sect-head {
  margin-bottom: 3px;
}

.cfg-tip__sect-key {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--accent-hover);
}

.cfg-tip__text {
  margin: 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-secondary);
}

.cfg-tip__foot {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 11px;
  padding-top: 9px;
  border-top: 1px solid var(--border-base);
}

.cfg-tip__foot-item {
  font-size: 11px;
  color: var(--text-secondary);
}

.cfg-tip__foot-tag {
  font-size: 9.5px;
  padding: 1px 5px;
  border-radius: 3px;
  color: var(--accent-hover);
  background: var(--accent-dim);
}
</style>
