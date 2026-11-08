import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  getChanConfig,
  getChanConfigSchema,
  saveChanConfig,
} from '@/api/modules/chanConfig'
import type { ChanConfigSchema, ChanConfigState } from '@/api/types'

/**
 * 缠论参数配置 store（chan-config-panel design D9）。
 *
 * 三份状态：
 *   saved  —— 服务端已保存的配置（`GET /api/chan-config`）
 *   schema —— 参数元数据（`GET /api/chan-config/schema`）
 *   draft  —— 抽屉打开时从 saved 深拷贝，抽屉内所有编辑只改它
 *
 * 草稿语义：**只有点保存才会生效**。关闭抽屉即丢弃草稿（配置是服务端权威的
 * 全局设置，本地暂存草稿会在多用户场景下误导）。
 *
 * 不变量：`dirtyCount === 0` 时 `draft` 与 `saved` 语义等价 —— 保存按钮禁用、
 * 关闭无需二次确认。
 */

/**
 * 深度比较用的稳定序列化（键递归排序，保证同值同串）。
 *
 * `Infinity` 规整为字符串 `"inf"`：后端经 JSON 传输时 `inf` 只能是字符串
 * （标准 JSON 不接受非有限浮点），草稿里若是数字 `Infinity` 会被判成不同值。
 * 前端正常路径已统一写 `"inf"`，这里是兜底。
 */
function stableStringify(value: unknown): string {
  if (value === Infinity) return JSON.stringify('inf')
  if (value === -Infinity) return JSON.stringify('-inf')
  if (value === null || typeof value !== 'object') return JSON.stringify(value)
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`
  const obj = value as Record<string, unknown>
  const keys = Object.keys(obj).sort()
  return `{${keys.map((k) => `${JSON.stringify(k)}:${stableStringify(obj[k])}`).join(',')}}`
}

export const useChanConfigStore = defineStore('chanConfig', () => {
  /** 服务端已保存配置 */
  const saved = ref<ChanConfigState | null>(null)
  /** 参数元数据 */
  const schema = ref<ChanConfigSchema | null>(null)
  /** 草稿（抽屉内编辑的副本） */
  const draft = ref<Record<string, unknown>>({})
  /** 元数据加载中 */
  const schemaLoading = ref(false)
  /** 保存进行中 */
  const saving = ref(false)

  /**
   * 草稿相对已保存值的变更项数。
   *
   * 比较范围是 `saved.effective` 与 `draft` 的键并集。`effective` 由后端按
   * schema 参数反射构造（当前 57 个参数键，不含派生键与分侧后缀键），与 `draft`
   * 同构，可直接逐键深比较；并集只是防御「草稿里多出键」的情况。
   */
  const dirtyCount = computed(() => {
    const base = saved.value?.effective ?? {}
    const keys = new Set([...Object.keys(base), ...Object.keys(draft.value)])
    let n = 0
    for (const key of keys) {
      if (stableStringify(base[key]) !== stableStringify(draft.value[key])) n += 1
    }
    return n
  })

  /** 是否有未保存改动 */
  const isDirty = computed(() => dirtyCount.value > 0)

  /** 拉取已保存配置（同时把草稿重置为它） */
  async function fetchSaved(): Promise<void> {
    const state = await getChanConfig()
    saved.value = state
    draft.value = { ...state.effective }
  }

  /** 拉取参数元数据（幂等，已加载过则跳过；`force` 强制重取） */
  async function fetchSchema(force = false): Promise<void> {
    if (schema.value && !force) return
    schemaLoading.value = true
    try {
      schema.value = await getChanConfigSchema()
    } finally {
      schemaLoading.value = false
    }
  }

  /** 打开抽屉：确保 schema 与 saved 就绪，草稿从 saved 深拷贝 */
  async function openDraft(): Promise<void> {
    await Promise.all([fetchSchema(), fetchSaved()])
  }

  /** 丢弃草稿（恢复为已保存配置） */
  function discardDraft(): void {
    draft.value = { ...(saved.value?.effective ?? {}) }
  }

  /** 某项的档位基线（缺失时退回参数级 `default`） */
  function baselineValue(
    key: string,
    base: Record<string, unknown>,
    fallback: unknown,
  ): unknown {
    return key in base ? base[key] : fallback
  }

  /**
   * 切换档位：没被用户改过的项跟随新档位，改过的项保留。
   *
   * 不做这一步的话，用户从 standard 切到 legacy 后，草稿里那十余项仍是 standard
   * 的值 —— `computeOverrides()` 拿 legacy 基线一比，会把它们全判成「用户覆盖」
   * 写死进 overrides，此后切档位再也不跟随预设，档位机制形同虚设。
   *
   * 判定「用户改过」用**切换前档位**的基线比：与旧基线一致的项说明用户没动过。
   */
  function switchPreset(next: string): void {
    const s = schema.value
    if (!s) {
      draft.value = { ...draft.value, bsp_preset: next }
      return
    }
    const prev = String(draft.value.bsp_preset ?? saved.value?.preset ?? 'standard')
    const oldBase = baselineFor(prev)
    const newBase = baselineFor(next)
    const nextDraft: Record<string, unknown> = {}
    for (const p of s.params) {
      const cur = draft.value[p.key]
      const oldDefault = baselineValue(p.key, oldBase, p.default)
      const newDefault = baselineValue(p.key, newBase, p.default)
      // 与旧基线一致（用户没改过）→ 跟随新档位；否则保留用户的显式取值
      nextDraft[p.key] =
        stableStringify(cur) === stableStringify(oldDefault) ? newDefault : cur
    }
    nextDraft.bsp_preset = next
    draft.value = nextDraft
  }

  /** 单项改值（只改草稿）；改档位走 `switchPreset()` 重基线 */
  function setDraftValue(key: string, value: unknown): void {
    if (key === 'bsp_preset') {
      switchPreset(String(value))
      return
    }
    draft.value = { ...draft.value, [key]: value }
  }

  /**
   * 指定档位的预设基线。
   *
   * 优先级：`schema.preset_baselines[档位]` → `schema.kernel_defaults` → `{}`。
   *
   * 为什么不能用 `params[].default`：那是「当前已保存配置反射出的值」，用户改过
   * 就跟着变。拿它当基线时，用户改 A 项保存后 `default` 就等于 A 的新值，下次
   * 只改 B 项保存时 A 会被判成「没改过」而踢出 overrides → A 的改动静默丢失。
   *
   * 为什么不能只用 `kernel_defaults`：legacy 档会把 `min_zs_cnt` / `bsp1_trend` /
   * `macd_algo` 等十余项展开成不同取值，拿内核默认当基线会把这些**预设带来的**
   * 取值误判成用户覆盖写死进 overrides，此后切档位不再跟随预设。
   */
  function baselineFor(preset: string): Record<string, unknown> {
    const s = schema.value
    if (!s) return {}
    return (s.preset_baselines?.[preset] ?? s.kernel_defaults ?? {}) as Record<string, unknown>
  }

  /** 当前草稿档位对应的基线 */
  function defaultsBaseline(): Record<string, unknown> {
    const preset = String(draft.value.bsp_preset ?? saved.value?.preset ?? 'standard')
    return baselineFor(preset)
  }

  /** 当前档位基线（UI 用：单行「恢复默认」与「已改」标记的参照值） */
  const activeBaseline = computed<Record<string, unknown>>(() => defaultsBaseline())

  /**
   * 草稿中相对**当前档位基线**已改的参数键。
   *
   * 与 `dirtyCount` 口径不同：`dirtyCount` 比的是「服务端已保存的生效值」（含后端
   * 派生键），用于「有没有未保存改动」；这里比的是「相对档位默认改没改」，用于
   * 行级「已改」标记与单项重置 —— 用户把某项改回档位默认后标记必须消失，否则
   * 界面会一直声称「改过」而用户无从判断该还哪一项。
   */
  const overriddenKeys = computed<Set<string>>(() => {
    const s = schema.value
    const out = new Set<string>()
    if (!s) return out
    const base = activeBaseline.value
    for (const p of s.params) {
      // 档位本身不是「一项参数」：它在抽屉头部单独呈现，不该出现在
      // 「仅看自定义」计数与行级标记里（否则列表里找不到对应行）。
      if (p.control === 'preset') continue
      const cur = draft.value[p.key]
      if (cur === undefined) continue
      const b = p.key in base ? base[p.key] : p.default
      if (stableStringify(cur) !== stableStringify(b)) out.add(p.key)
    }
    return out
  })

  /**
   * 恢复默认值：把草稿重置为**当前档位预设展开后**的默认值。
   *
   * 只回到当前档位，不强制回 standard —— 用户选 legacy 后点「恢复默认」，
   * 期望的是「legacy 档的开箱值」，而不是被悄悄切回 standard。
   * 只改草稿，`saved` 不动 —— 仍需用户点保存才生效。
   */
  function resetToDefaults(): void {
    if (!schema.value) return
    const baseline = defaultsBaseline()
    const preset = draft.value.bsp_preset ?? saved.value?.preset ?? 'standard'
    const next: Record<string, unknown> = {}
    for (const p of schema.value.params) {
      next[p.key] = p.key in baseline ? baseline[p.key] : p.default
    }
    next.bsp_preset = preset      // 档位本身保持不变
    draft.value = next
  }

  /**
   * 计算「相对当前档位基线」的显式覆盖项 —— 即 `PUT` 要提交的 `overrides`。
   *
   * 语义（design D3）：只有与该档位预设基线不同的项才写进 overrides，其余项
   * 跟随内核默认与档位预设。这样将来内核调整默认值时，未被用户改过的项会自动
   * 跟上；切档位时没改过的项也会跟着换。
   *
   * 不在 schema 里的键原样保留：`saved.overrides` 可能含 UI 无法编辑的键
   * （用户曾直接调接口写的 `macd_algo-seg` 等分侧后缀）。只遍历 schema 参数
   * 会把它们挤掉 —— 用户什么都没改，保存一次就丢了配置。
   */
  function computeOverrides(): Record<string, unknown> {
    if (!schema.value) return { ...draft.value }
    const baseline = defaultsBaseline()
    const known = new Set(schema.value.params.map((p) => p.key))
    const out: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(saved.value?.overrides ?? {})) {
      if (!known.has(k)) out[k] = v
    }
    for (const p of schema.value.params) {
      const cur = draft.value[p.key]
      if (cur === undefined) continue
      const base = p.key in baseline ? baseline[p.key] : p.default
      if (stableStringify(cur) !== stableStringify(base)) {
        out[p.key] = cur
      }
    }
    return out
  }

  /** 保存草稿；成功后用返回的版本刷新 saved（草稿保留，便于继续调整） */
  async function save(): Promise<number> {
    saving.value = true
    try {
      const overrides = computeOverrides()
      const preset = (draft.value.bsp_preset as string) ?? saved.value?.preset ?? 'standard'
      // 全量快照：保存时的全部生效值，仅供后端展示/审计
      const result = await saveChanConfig({
        overrides,
        preset,
        full_snapshot: { ...draft.value },
      })
      // 保存后重拉：schema 里的 default 也是按新配置反射的，需同步刷新
      saved.value = await getChanConfig()
      schema.value = await getChanConfigSchema()
      draft.value = { ...saved.value.effective }
      return result.version
    } finally {
      saving.value = false
    }
  }

  /** 单项恢复为当前档位基线值（只改草稿，仍需保存才生效） */
  function resetKey(key: string): void {
    const s = schema.value
    const p = s?.params.find((x) => x.key === key)
    if (!p) return
    const base = activeBaseline.value
    const v = key in base ? base[key] : p.default
    draft.value = { ...draft.value, [key]: v }
  }

  /** 重置全部状态（登出时调用，避免跨账号残留） */
  function reset(): void {
    saved.value = null
    schema.value = null
    draft.value = {}
  }

  return {
    saved,
    schema,
    draft,
    schemaLoading,
    saving,
    dirtyCount,
    isDirty,
    overriddenKeys,
    fetchSaved,
    fetchSchema,
    openDraft,
    discardDraft,
    setDraftValue,
    switchPreset,
    resetToDefaults,
    resetKey,
    computeOverrides,
    save,
    reset,
  }
})
