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
          :hide-after="200"
          :offset="8"
          @show="onPopoverShow"
        >
          <template #reference>
            <button
              ref="helpBtn"
              class="cfg-row__help"
              type="button"
              :aria-label="`${param.label} 参数说明`"
            >
              <el-icon><QuestionFilled /></el-icon>
            </button>
          </template>

          <div class="cfg-tip__body" :style="tipStyle">
            <!-- 固定头：正文可滚动后，标题必须钉在顶部 —— 滚到一半还要能确认
                 「这是哪个参数的说明」，否则只剩几段没有主语的散文。 -->
            <div class="cfg-tip__head">
              <div class="cfg-tip__eyebrow mono">PARAMETER · 参数说明</div>
              <div class="cfg-tip__title">{{ param.label }}</div>
            </div>

            <!-- 滚动区：最长的一条约 800 字（「是否背驰的技术指标」13 个选项规则、
                 「背驰力度阈值」9 行公式），不限高会直接顶出视口。 -->
            <div class="cfg-tip__scroll-wrap">
              <div ref="scrollEl" class="cfg-tip__scroll" @scroll="onScroll">
                <p class="cfg-tip__plain">{{ param.plain }}</p>

                <!-- 计算公式：结构化字段（后端 formula 数组），等宽字体逐行渲染。
                     公式不能挤在 plain 的散文里 —— 分子分母、量纲口径一眼可读。 -->
                <section v-if="formulaLines.length" class="cfg-tip__sect cfg-tip__formula">
                  <div class="cfg-tip__sect-head">
                    <span class="cfg-tip__sect-key">计算公式</span>
                  </div>
                  <pre class="cfg-tip__formula-body">{{ formulaLines.join('\n') }}</pre>
                </section>

                <section class="cfg-tip__sect">
                  <div class="cfg-tip__sect-head">
                    <span class="cfg-tip__sect-key">{{ effectHeading }}</span>
                  </div>
                  <p class="cfg-tip__text">{{ param.effect }}</p>
                </section>

                <section v-if="param.scope" class="cfg-tip__sect">
                  <div class="cfg-tip__sect-head">
                    <span class="cfg-tip__sect-key">影响范围</span>
                  </div>
                  <p class="cfg-tip__text">{{ param.scope }}</p>
                </section>

                <!-- 选项规则：把每个可选值的判定规则摊开。
                     下拉框只能显示一行标签，规则本身必须在这里讲清楚，否则用户
                     只能靠反复试值来猜「跟谁比」。排序维度由后端 `choice_order_hint`
                     声明（多数是宽松 → 严格，多选类是判据强弱）。 -->
                <section v-if="choiceRules.length" class="cfg-tip__sect">
                  <div class="cfg-tip__sect-head cfg-tip__sect-head--split">
                    <span class="cfg-tip__sect-key">选项规则</span>
                    <span v-if="orderHint" class="cfg-tip__order mono">{{ orderHint }}</span>
                  </div>
                  <ol class="cfg-rules">
                    <li
                      v-for="(r, i) in choiceRules"
                      :key="r.value"
                      class="cfg-rules__item"
                      :class="{ 'is-active': r.active }"
                    >
                      <span class="cfg-rules__rank mono">{{ i + 1 }}</span>
                      <div class="cfg-rules__body">
                        <span class="cfg-rules__label">
                          {{ r.label }}
                          <span v-if="r.active" class="cfg-rules__now mono">当前</span>
                        </span>
                        <span class="cfg-rules__text">{{ r.text }}</span>
                      </div>
                    </li>
                  </ol>
                </section>
              </div>

              <!-- 滚动提示：卡片被限高后，底部若直接切断会看起来像内容缺失。
                   渐隐遮罩告诉用户「下面还有」。滚到底即消失，避免读完还留个假阴影。 -->
              <div v-show="showScrollHint" class="cfg-tip__scroll-hint" aria-hidden="true" />
            </div>

            <!-- 固定脚：「出厂默认」是判断「我到底改没改」的锚点，不该被滚走 -->
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
      <span
        v-if="param.legacy"
        class="cfg-row__badge cfg-row__badge--legacy"
        title="历史参数：内核仍在计算，但结果没有任何界面或接口展示"
      >历史 · 无展示</span>
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
import { computed, nextTick, ref } from 'vue'
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

/**
 * 解释卡片里第二段的标题 —— 跟随控件类型，而不是一律写「调大 / 调小」。
 *
 * 开关类没有「调大」这回事，多选类也没有「调大」，统一标题会让说明与控件对不上。
 * 数值类说「调整数值」，下拉单选 / 多选各自说「单选」「多选」，开关说「开关」。
 */
const effectHeading = computed(() => {
  switch (props.param.control) {
    case 'number':
    case 'integer':
      return '调整数值'
    case 'select':
    case 'preset':
      return '单选'
    case 'multi':
      return '多选'
    case 'bool':
      return '开关'
    default:
      return '调整数值'
  }
})

/**
 * 问号卡片里的「计算公式」逐行内容。
 *
 * 后端 `formula` 是结构化字段（字符串数组），前端只负责渲染，不自行拼公式 ——
 * 公式口径的唯一真源在内核判据（`BSPJudgement.check_bsp2_standard` 等），
 * 手写在前端会和实现漂移。
 */
const formulaLines = computed<string[]>(() => props.param.formula ?? [])

/**
 * 「选项规则」清单右上角的排序说明。
 *
 * 由后端 `choice_order_hint` 声明 —— 各参数的排序维度并不相同（多数是
 * 「宽松 → 严格」，也有「严格 → 宽松」「推荐 → 老口径」，还有的只是并列的
 * 类型清单，本就没有强弱序列）。前端写死一种会与清单实际顺序对不上，
 * 因此在后端未声明时用中性的「逐项说明」，而不是硬套「宽松 → 严格」。
 */
const orderHint = computed<string>(() => props.param.choice_order_hint || '逐项说明')

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

/**
 * 问号卡片里的「选项规则」清单。
 *
 * 顺序**严格照 `choices` 的顺序**渲染 —— 后端已按 `choice_order_hint` 声明的
 * 维度排好序（如 `bsp1_new_extreme_mode` 的 prev_zs_in → trend_start → all → level），
 * 前端再排序一次只会让两处口径分叉。
 *
 * 每项的说明文字优先取 `choice_hints`（这个取值「是什么意思」），没有再退回
 * `choice_caveats`（「有什么限制」）。分开的理由：`choice_caveats` 会同步显示在
 * 行下方的常驻警告行（`activeCaveat`），把含义写进它会让每一行都挂着一条黄字，
 * 而含义本来只在问号卡片里看。
 *
 * 两者都没有的参数返回空数组，整个区块不渲染。
 * 当前生效项高亮：`modelValue` 可能是数组（多选控件），命中任一项即算当前。
 */
const choiceRules = computed(() => {
  const caveats = props.param.choice_caveats
  const hints = props.param.choice_hints
  const list = props.param.choices
  if ((!caveats && !hints) || !list?.length) return []
  const cur = Array.isArray(props.modelValue)
    ? props.modelValue.map(String)
    : [String(props.modelValue)]
  return list.map((c: string | number) => ({
    value: String(c),
    label: choiceLabel(c),
    text: hints?.[String(c)] || caveats?.[String(c)] || '',
    active: cur.includes(String(c)),
  }))
})

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

/* ---- 滚动提示 ---------------------------------------------------------
   卡片限高后正文可能超出一屏，底部直接切断会像内容缺失。这里用「是否还有
   未滚到的内容」驱动一层渐隐遮罩，让用户知道可以继续滚。

   为什么不用 `ResizeObserver`：popper 内容是挂载即定型的静态文本（参数说明
   在抽屉打开时就不再变），唯一会改变高度的是 `param` 切换（同一行组件复用
   时）。用 `watch(param)` 重新量一次，比常驻观察器省掉每条参数一个 observer
   ——抽屉里同时有 56 行。

   量不出高度（组件尚未布局、`scrollHeight` 为 0）时保持隐藏，宁可少一个提示
   也不要给短说明挂一条假阴影。 */
const scrollEl = ref<HTMLElement | null>(null)
const showScrollHint = ref(false)

function measureScrollHint(): void {
  const el = scrollEl.value
  if (!el) return
  const overflow = el.scrollHeight - el.clientHeight
  // 容差 2px：小数缩放（125% / 150% DPI）下 scrollHeight 常比 clientHeight
  // 大 1px，不设容差会给刚好装得下的说明也挂上提示。
  showScrollHint.value = overflow > 2 && el.scrollTop < overflow - 2
}

function onScroll(): void {
  measureScrollHint()
}

/**
 * 每次悬浮展开都重新量一次。
 *
 * 比 `immediate: true` 的 watch 更可靠：popper 是 `v-if` 懒渲染的，首次 watch
 * 跑在卡片还没进 DOM 时（`scrollEl` 为 null），会被 `measureScrollHint()` 直接
 * 跳过；展开事件才是「现在真的有布局了」的那个时刻。
 */
function onPopoverShow(): void {
  computeTipMaxHeight()
  nextTick(measureScrollHint)
}

/* ---- 弹窗限高 ---------------------------------------------------------
   单纯写 `max-height: 60vh` 不够：抽屉可滚动，靠下的那一行展开时下方只剩
   一两百像素，全局视口比例算出来的高度仍会让卡片探出屏幕底部。

   这里按触发器的实际位置算「下方可用空间」：
     可用 = 视口高 - 触发器底边 - 间距 - 安全边距
   再封顶在 600px（≈35 行正文，足够读完最长的一条说明），下限 220px。

   为什么下限是 220px 而不是更小：低于这个高度时固定头 + 固定脚就吃掉一半，
   正文只剩三四行，滚动反而比直接截断更难读。空间实在不够时（触发器贴着
   屏幕底部），Element 的 popper 会自动翻转到上方，`computeTipMaxHeight`
   在翻转后由 `onPopoverShow` 重算一次即可 —— `placement` 是
   bottom-start，翻转后 Element 会给 popper 加 `x-placement`，但高度只需按
   「下方可用」算：翻转上去时下方的空间限制不再成立，此时按下限处理。 */
const TIP_MAX_HEIGHT = 600
const TIP_MIN_HEIGHT = 220
/** 触发器与卡片之间的间距（与 `:offset="8"` 对齐）+ 距视口底部的安全边距 */
const TIP_GAP = 8 + 16

const helpBtn = ref<HTMLElement | null>(null)
const tipMaxHeight = ref<number | undefined>(undefined)

function computeTipMaxHeight(): void {
  const el = helpBtn.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const below = window.innerHeight - rect.bottom - TIP_GAP
  // 下方已经被挤到放不下最小高度：交给 Element 翻转，此时按上限给足，
  // 让翻转后的卡片能用满屏幕上方空间。
  tipMaxHeight.value = below < TIP_MIN_HEIGHT
    ? TIP_MAX_HEIGHT
    : Math.min(TIP_MAX_HEIGHT, below)
}

const tipStyle = computed(() => {
  const h = tipMaxHeight.value
  // 未测量前不写：退回 CSS 的 min(600px, 100vh - 140px) 兜底，避免闪一下
  return h === undefined ? undefined : { maxHeight: `${Math.round(h)}px` }
})
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
/* 历史参数徽标：比「已自定义」更弱，表示「能改但改了也看不见」 */
.cfg-row__badge--legacy {
  color: var(--text-secondary);
  background: var(--bg-surface-hover);
  border: 1px solid var(--border-strong);
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
     裁掉气泡溢出的部分会把箭头一起削掉。圆角改由内部 body 自己保证。
     高度上限因此挂在 .cfg-tip__body 上（见下），不在这里裁。 */
}
.cfg-tip.el-popover.el-popper .el-popper__arrow::before {
  background: var(--bg-surface) !important;
  border-color: var(--border-strong) !important;
}

/* 卡片本体 = 固定头 + 滚动正文 + 固定脚。
   `max-height` 是这一整套布局的前提：没有它，flex 列容器会按内容撑开，
   滚动区永远不触发，长说明照样顶穿视口。
   取值 min(600px, 视口高 - 140px)：桌面大屏封顶 600px（≈35 行正文，够读完
   最长的一条「是否背驰的技术指标」）；笔记本高度不足时留出 140px 给
   Element 的 popper 边界避让（上下各 70px），避免气泡贴边后被翻转到页面上方。 */
.cfg-tip__body {
  display: flex;
  flex-direction: column;
  max-height: min(600px, calc(100vh - 140px));
  /* 内边距下沉到 head / scroll / foot 各自身上：滚动区要贴边，这样滚动条
     落在卡片右缘而不是浮在文字中间。 */
  padding: 0;
  font-family: var(--font-ui);
  color: var(--text-primary);
}

/* ---- 固定头 ---------------------------------------------------------- */
.cfg-tip__head {
  flex: 0 0 auto;
  padding: 13px 16px 9px;
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
}

/* ---- 滚动正文 -------------------------------------------------------- */
/* 外层只负责定位渐隐遮罩，本身不滚动也不参与 flex 收缩计算。 */
.cfg-tip__scroll-wrap {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
}

/* `min-height: 0` 不可省：flex 子项默认 min-height:auto，会以内容高度为下限
   拒绝收缩，结果不是内部滚动而是整张卡片被撑高（max-height 形同虚设）。
   `overscroll-behavior: contain` 防止滚到底后继续滚带动抽屉背景。 */
.cfg-tip__scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 0 16px 6px;
}

/* 滚动条收窄到 8px 并改用卡片底色描边：全局样式按 --bg-base 描边，
   放在 --bg-surface 的卡片里会形成一圈突兀的深色边。 */
.cfg-tip__scroll::-webkit-scrollbar {
  width: 8px;
}
.cfg-tip__scroll::-webkit-scrollbar-thumb {
  background: var(--border-strong);
  border-radius: var(--r-full);
  border: 2px solid var(--bg-surface);
}

/* 底部渐隐：仅在「下面还有内容」时出现（`v-show` 由滚动位置驱动）。
   两端都用 color-mix 从 --bg-surface 推出来（0% 透明 → 100% 实体），而不是
   写 `transparent` —— 关键字 transparent 是 rgba(0,0,0,0)，与不透明色做
   渐变时中间会泛灰（浏览器按非预乘空间插值），暗色主题下尤其明显。 */
.cfg-tip__scroll-hint {
  position: absolute;
  left: 0;
  right: 8px;
  bottom: 0;
  height: 26px;
  pointer-events: none;
  background: linear-gradient(
    to bottom,
    color-mix(in srgb, var(--bg-surface) 0%, transparent),
    var(--bg-surface)
  );
}

.cfg-tip__plain {
  margin: 0;
  font-size: 13px;
  line-height: 1.75;
  color: var(--text-primary);
  /* 后端说明里用 \n 分段（「是什么」常是两三个短句）。普通 <p> 会把换行折叠成
     空格，长句糊成一大团；pre-line 保换行、仍按窗口宽度自动折行。 */
  white-space: pre-line;
}

.cfg-tip__sect {
  margin-top: 10px;
  padding-top: 9px;
  border-top: 1px solid var(--border-base);
}

.cfg-tip__sect-head {
  margin-bottom: 3px;
}
.cfg-tip__sect-head--split {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

/* 排序说明：告诉用户这份清单是按什么维度排列的，而不是随手排的 */
.cfg-tip__order {
  font-size: 9.5px;
  letter-spacing: 0.06em;
  color: var(--text-secondary);
  opacity: 0.85;
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
  /* 与 .cfg-tip__plain 同理：方向性说明按「调大 / 调小 / 关闭」分行写。 */
  white-space: pre-line;
}

/* 计算公式：等宽 + 浅一档的底色，与散文区分开。
   公式里的 ÷、|−|、下标对等宽字体友好；行间 1.6 保证多行公式不糊。 */
.cfg-tip__formula-body {
  margin: 4px 0 0;
  padding: 8px 10px;
  border-radius: 4px;
  border: 1px solid var(--border-base);
  background: var(--bg-base);
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-primary);
  white-space: pre-wrap;
  overflow-x: auto;
}

/* ---- 固定脚 ---------------------------------------------------------- */
.cfg-tip__foot {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 16px 11px;
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

/* --------------------------------------------------------------------------
   选项规则清单（按宽松 → 严格排列）

   设计意图：下拉框只能显示一行标签，「这条口径到底跟谁比」讲不完。这份清单
   用序号 + 逐项说明把规则摊开，并用左侧竖线表示「严格度递增」的方向感 ——
   越往下越严格。当前选中项用强调色 + 「当前」徽标标出，避免用户看完四条
   还要回去核对下拉框里到底选了哪条。
   -------------------------------------------------------------------------- */
.cfg-rules {
  list-style: none;
  margin: 6px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.cfg-rules__item {
  display: flex;
  gap: 8px;
  padding: 5px 7px 5px 6px;
  border-radius: 4px;
  border-left: 2px solid var(--border-base);
  background: transparent;
  transition: background 0.12s ease, border-color 0.12s ease;
}

/* 当前生效项：强调色左边线 + 淡背景，与「已修改」徽标同色系 */
.cfg-rules__item.is-active {
  border-left-color: var(--accent-hover);
  background: var(--accent-dim);
}

.cfg-rules__rank {
  flex: 0 0 14px;
  font-size: 9.5px;
  line-height: 1.55;
  color: var(--text-secondary);
  opacity: 0.7;
  text-align: right;
}

.cfg-rules__item.is-active .cfg-rules__rank {
  color: var(--accent-hover);
  opacity: 1;
}

.cfg-rules__body {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.cfg-rules__label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.cfg-rules__now {
  font-size: 9px;
  font-weight: 500;
  letter-spacing: 0.04em;
  padding: 0 4px;
  border-radius: 3px;
  color: var(--accent-hover);
  background: var(--bg-surface);
  border: 1px solid var(--accent-hover);
  line-height: 1.5;
}

.cfg-rules__text {
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--text-secondary);
}
</style>
