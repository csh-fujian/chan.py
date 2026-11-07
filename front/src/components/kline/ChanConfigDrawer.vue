<template>
  <el-drawer
    v-model="visible"
    title="缠论参数配置"
    direction="rtl"
    size="min(1120px, 94vw)"
    class="chan-config-drawer"
    :close-on-click-modal="false"
    :before-close="handleBeforeClose"
    append-to-body
  >
    <!-- 自定义头部：标题 + 档位总开关（档位是「整套规则」的开关，不该埋在 58 项里） -->
    <template #header>
      <div class="cfg-head">
        <div class="cfg-head__main">
          <div class="cfg-head__eyebrow mono">CHAN PARAMETERS · 全库共享</div>
          <h1 class="cfg-head__title">
            缠论参数配置
            <span v-if="props.code" class="cfg-head__code mono">{{ props.code }}</span>
          </h1>
        </div>

        <div v-if="presetChoices.length" class="cfg-head__preset">
          <span class="cfg-head__preset-label">规则档位</span>
          <div class="preset-seg" role="group" aria-label="规则档位">
            <button
              v-for="c in presetChoices"
              :key="String(c)"
              type="button"
              class="preset-seg__item"
              :class="{ 'is-active': String(c) === curPreset }"
              :disabled="!canManage"
              @click="onPresetPick(c)"
            >
              {{ presetLabelOf(c) }}
            </button>
          </div>
        </div>
      </div>
    </template>

    <!-- 首次加载（无 schema）：骨架屏 -->
    <div v-if="loading && !store.schema" class="cfg-loading">
      <el-skeleton :rows="10" animated />
    </div>

    <!-- 再次打开（schema 已缓存）：只挡交互，不闪骨架 -->
    <div v-else-if="loading" class="cfg-loading cfg-loading--busy">
      <span class="cfg-loading__spin" />
      <span>正在载入最新配置…</span>
    </div>

    <!-- 拉取失败（schema 缺席）：给出可读的状态而非空白抽屉 -->
    <div v-else-if="!store.schema" class="cfg-loading cfg-loading--error">
      <p>参数元数据未能加载。请关闭抽屉后重试，或确认后端服务可用。</p>
    </div>

    <div v-else class="cfg-shell">
      <!-- ---------------- 左：分类导航 ---------------- -->
      <aside class="cfg-nav">
        <div class="cfg-nav__search">
          <el-input
            v-model="keyword"
            size="small"
            clearable
            placeholder="搜索参数名 / 键名"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
        </div>

        <button
          type="button"
          class="cfg-nav__chip"
          :class="{ 'is-on': onlyModified }"
          :disabled="!store.overriddenKeys.size"
          title="只看偏离当前档位默认值的参数（含已保存的自定义项）"
          @click="onlyModified = !onlyModified"
        >
          仅看自定义
          <span class="mono">{{ store.overriddenKeys.size }}</span>
        </button>

        <nav class="cfg-nav__list">
          <div v-for="(g, gi) in filteredGroups" :key="g.id" class="cfg-nav__group">
            <button
              type="button"
              class="cfg-nav__link"
              :class="{ 'is-active': activeGroup === g.id }"
              :style="{ '--g-accent': g.accent }"
              @click="scrollToGroup(g.id)"
            >
              <span class="cfg-nav__index mono">{{ String(gi + 1).padStart(2, '0') }}</span>
              <span class="cfg-nav__name">{{ g.title }}</span>
              <span class="cfg-nav__count mono">{{ g.count }}</span>
            </button>

            <transition name="subs">
              <div v-if="activeGroup === g.id && g.subs.length > 1" class="cfg-nav__subs">
                <button
                  v-for="s in g.subs"
                  :key="s.id"
                  type="button"
                  class="cfg-nav__sub"
                  @click="scrollToSub(s.id)"
                >
                  <span class="cfg-nav__sub-name">{{ s.title }}</span>
                  <span class="cfg-nav__sub-count mono">{{ s.count }}</span>
                </button>
              </div>
            </transition>
          </div>

          <p v-if="!filteredGroups.length" class="cfg-nav__none">无匹配参数</p>
        </nav>

        <div class="cfg-nav__foot">
          <p>改动<strong>只有点「保存」才生效</strong></p>
          <p class="cfg-nav__warn">参数全库共享，会影响所有人的计算结果</p>
        </div>
      </aside>

      <!-- ---------------- 右：分组内容 ---------------- -->
      <div ref="scrollEl" class="cfg-main" @scroll.passive="onScroll">
        <div class="cfg-main__inner">
          <section
            v-for="(g, gi) in filteredGroups"
            :key="g.id"
            class="cfg-group"
            :data-group="g.id"
            :style="{ '--g-accent': g.accent }"
          >
            <header class="cfg-group__head">
              <span class="cfg-group__index mono">{{ String(gi + 1).padStart(2, '0') }}</span>
              <div class="cfg-group__titles">
                <h2 class="cfg-group__title">
                  {{ g.title }}
                  <span v-if="g.risk" class="cfg-group__badge">高风险</span>
                </h2>
                <p class="cfg-group__hint">{{ g.hint }}</p>
              </div>
              <span class="cfg-group__count mono">{{ g.count }} 项</span>
            </header>

            <!-- 结构组展开前二次确认（新手误碰会重排整张图） -->
            <div
              v-if="g.risk && !structureAcknowledged && !keyword && !onlyModified"
              class="cfg-gate"
            >
              <p>这组参数会重排笔、线段与中枢，进而改变图上所有买卖点。确定要看吗？</p>
              <el-button size="small" type="warning" plain @click="structureAcknowledged = true">
                我了解，展开查看
              </el-button>
            </div>

            <template v-else>
              <div
                v-for="s in g.subs"
                :key="s.id"
                class="cfg-sub"
                :data-sub="s.id"
              >
                <div class="cfg-sub__head">
                  <span class="cfg-sub__title">{{ s.title }}</span>
                  <span class="cfg-sub__line" />
                  <span class="cfg-sub__count mono">{{ s.count }}</span>
                </div>

                <div class="cfg-sub__grid">
                  <ChanConfigRow
                    v-for="p in s.params"
                    :key="p.key"
                    :param="p"
                    :kernel-default="store.schema?.kernel_defaults?.[p.key]"
                    :model-value="store.draft[p.key]"
                    :readonly="!canManage"
                    :overridden="store.overriddenKeys.has(p.key)"
                    @update:model-value="(v) => onRowInput(p.key, v)"
                    @reset="store.resetKey(p.key)"
                  />
                </div>
              </div>
            </template>
          </section>

          <!-- ---------------- 全库同步 ---------------- -->
          <section class="cfg-sync">
            <div class="cfg-sync__head">
              <div>
                <div class="cfg-sync__title">同步所有股票</div>
                <p class="cfg-sync__hint">
                  按当前<strong>已保存</strong>的参数，重算全库所有股票并写回数据库。
                  全量同步实测约 3~6 分钟，期间其它页面仍可正常看图。
                </p>
              </div>
              <el-button
                size="small"
                :disabled="!canManage || syncRunning"
                :loading="syncRunning"
                @click="onStartSync"
              >
                {{ syncRunning ? '同步中…' : '开始同步' }}
              </el-button>
            </div>

            <div v-if="syncJob" class="cfg-sync__progress">
              <el-progress :percentage="syncPercent" :status="syncStatusType" :stroke-width="6" />
              <div class="cfg-sync__stats mono">
                {{ syncJob.done }} / {{ syncJob.total || '?' }}
                <template v-if="syncJob.failed"> · 失败 {{ syncJob.failed }}</template>
              </div>
            </div>

            <div v-if="syncFailures.length" class="cfg-sync__failures">
              <div class="cfg-sync__failures-title">失败明细（不影响其余股票）</div>
              <div v-for="(f, i) in syncFailures" :key="i" class="cfg-sync__failure mono">
                {{ f.code }} / {{ f.kl_type || f.period }}：{{ f.error }}
              </div>
            </div>

            <el-alert
              v-if="syncStale"
              type="warning"
              :closable="false"
              show-icon
              title="同步期间参数又变了"
              description="这次同步结果不代表当前参数，建议重新同步一次。"
            />
          </section>
        </div>
      </div>
    </div>

    <!-- 底部吸顶操作栏 -->
    <template #footer>
      <div class="cfg-footer">
        <div class="cfg-footer__status">
          <span class="cfg-footer__dot" :class="{ 'is-dirty': store.dirtyCount > 0 }" />
          <span v-if="store.dirtyCount" class="cfg-footer__dirty">
            <strong class="mono">{{ store.dirtyCount }}</strong> 项修改尚未保存
          </span>
          <span v-else class="cfg-footer__clean">未做修改</span>
          <span v-if="presetLabel" class="cfg-footer__sep">·</span>
          <span v-if="presetLabel" class="cfg-footer__preset">当前档位 {{ presetLabel }}</span>
          <span v-if="!canManage" class="cfg-footer__readonly">只读模式</span>
        </div>
        <div class="cfg-footer__actions">
          <el-button size="small" :disabled="!store.dirtyCount" @click="onResetDefaults">
            恢复默认
          </el-button>
          <el-button size="small" :disabled="!store.dirtyCount" @click="onCancel">取消</el-button>
          <el-button
            size="small"
            type="primary"
            :loading="store.saving || recomputing"
            :disabled="!canManage || !store.dirtyCount"
            @click="onSave"
          >
            保存并重算当前股票
          </el-button>
        </div>
      </div>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
/**
 * ChanConfigDrawer.vue — 缠论参数配置抽屉（chan-config-panel 5.3/5.5/5.6/5.7）。
 *
 * 交互契约（design D9）：
 *   1. 打开 = `store.openDraft()`，草稿从服务端已保存配置深拷贝
 *   2. 抽屉内**所有**编辑只改 `draft`，后端配置与图表都不动
 *   3. 点「保存并重算当前股票」→ PUT → 重拉图表 → 后台重算该股票 PG 索引
 *   4. 有未保存改动时关闭，二次确认
 *
 * 保存是**两段式**（design D7）：
 *   第一段 `/api/klines` 重拉（秒级，用户立刻看到新图）
 *   第二段 `/api/chan-config/recompute` 后台刷新 PG 索引（7~26 秒）
 *
 * 版面（2026-11 重设计）：
 *   58 项参数平铺在单列折叠面板里是不可读的 —— 用户找不到「二买回调上限」在哪，
 *   也不知道自己改过的项埋在哪。现改为**两栏**：
 *     · 左栏常驻分类导航（01/02/03 + 组内子分类锚点 + 搜索 + 只看已修改）
 *     · 右栏分区网格（组标题层级化、子分类二级标题、参数卡片两列）
 *   `bsp_preset` 从参数列表提到抽屉头部做成分段开关 —— 它是整套规则的总闸，
 *   与单项参数不是一个层级。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { useChanConfigStore } from '@/stores/chanConfig'
import {
  getChanSyncStatus,
  recomputeStock,
  startChanSync,
} from '@/api/modules/chanConfig'
import type { ChanParamGroup, ChanParamSchema, ChanSyncJob } from '@/api/types'
import ChanConfigRow from './ChanConfigRow.vue'

const props = defineProps<{
  modelValue: boolean
  /** 当前股票（保存后重算它） */
  code: string
  /** 当前周期（前端词表，如 1d） */
  period: string
  /** 是否有 manage 权限（无则只读查看） */
  canManage?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [v: boolean]
  /** 保存成功后通知父组件重拉图表 */
  saved: [version: number]
}>()

const store = useChanConfigStore()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const canManage = computed(() => props.canManage === true)

/* ------------------------------------------------------------------ */
/* 视图模型：把 schema 的 group / subtype 拍平成「导航 + 分区网格」      */
/* ------------------------------------------------------------------ */

/** 每组一个语义色：判据=主蓝（改结论）、标注=青（只改证据标签）、结构=琥珀（高风险） */
const GROUP_ACCENT: Record<string, string> = {
  bsp_judgement: 'var(--accent-base)',
  ladder_annotation: 'var(--accent-cyan)',
  structure: 'var(--warning)',
}

interface SubView {
  id: string
  title: string
  count: number
  params: ChanParamSchema[]
}

interface GroupView {
  id: ChanParamGroup
  title: string
  hint: string
  count: number
  risk: boolean
  accent: string
  subs: SubView[]
}

const keyword = ref('')
const onlyModified = ref(false)
/** 当前滚动到的分组（导航高亮） */
const activeGroup = ref('')
const scrollEl = ref<HTMLElement | null>(null)

/** 打开中（schema 与 saved 同时就绪前不渲染主体，避免闪空态） */
const loading = ref(false)

const structureAcknowledged = ref(false)

const recomputing = ref(false)
const syncRunning = ref(false)
const syncJob = ref<ChanSyncJob | null>(null)
const syncStale = ref(false)
let syncTimer: ReturnType<typeof setInterval> | null = null

/** 档位参数（已从参数列表中移除，改由头部开关承载） */
const presetParam = computed(
  () => store.schema?.params.find((p) => p.control === 'preset') ?? null,
)
const presetChoices = computed<Array<string | number>>(() => presetParam.value?.choices ?? [])
const curPreset = computed(() =>
  String(store.draft.bsp_preset ?? store.saved?.preset ?? 'standard'),
)

/**
 * 条件项可见性（如 `cal_rsi` 仅在 `macd_algo === 'rsi'` 时出现）。
 * 判定依据是**草稿**当前值 —— 用户在抽屉里选 RSI，即刻看到相关项。
 */
function isVisible(p: ChanParamSchema): boolean {
  if (!p.conditional || !p.visible_when) return true
  return Object.entries(p.visible_when).every(([k, v]) => String(store.draft[k]) === String(v))
}

const filteredGroups = computed<GroupView[]>(() => {
  const s = store.schema
  if (!s) return []
  const kw = keyword.value.trim().toLowerCase()
  const mods = store.overriddenKeys
  const out: GroupView[] = []

  for (const gm of s.groups) {
    const subs: SubView[] = []
    for (const p of s.params) {
      if (p.group !== gm.id) continue
      // 档位已提到头部，不再作为普通参数行出现
      if (p.control === 'preset') continue
      if (!isVisible(p)) continue
      if (onlyModified.value && !mods.has(p.key)) continue
      if (kw) {
        const hay = `${p.label} ${p.key} ${p.subtype} ${p.plain}`.toLowerCase()
        if (!hay.includes(kw)) continue
      }
      const title = p.subtype || '其它'
      let sub = subs.find((x) => x.title === title)
      if (!sub) {
        // id 只用于滚动锚点：走 ASCII 序号而非标题，避免中文/符号进选择器
        sub = { id: `${gm.id}-s${subs.length}`, title, count: 0, params: [] }
        subs.push(sub)
      }
      sub.params.push(p)
      sub.count += 1
    }
    if (!subs.length) continue
    out.push({
      id: gm.id,
      title: gm.title,
      hint: gm.hint,
      count: subs.reduce((n, x) => n + x.count, 0),
      risk: gm.id === 'structure',
      accent: GROUP_ACCENT[gm.id] ?? 'var(--accent-base)',
      subs,
    })
  }
  return out
})

/* ------------------------------------------------------------------ */
/* 导航与滚动                                                          */
/* ------------------------------------------------------------------ */

/** 组标题吸顶时底部留白：跳动后不要紧贴吸顶标题 */
const STICKY_GAP = 14

function scrollToGroup(id: string): void {
  const el = scrollEl.value
  const node = el?.querySelector<HTMLElement>(`[data-group="${id}"]`)
  if (!el || !node) return
  activeGroup.value = id
  el.scrollTo({ top: Math.max(0, node.offsetTop - 10), behavior: 'smooth' })
}

/**
 * 跳到子分类。
 *
 * 让开的距离按**实测**吸顶标题高度算，而不是写死常量 —— 组标题下方的 hint
 * 在窄窗口会折成两行，写死的偏移会把子分类标题盖掉一半。
 */
function scrollToSub(subId: string): void {
  const el = scrollEl.value
  const node = el?.querySelector<HTMLElement>(`[data-sub="${subId}"]`)
  if (!el || !node) return
  const head = node
    .closest<HTMLElement>('[data-group]')
    ?.querySelector<HTMLElement>('.cfg-group__head')
  const offset = (head?.offsetHeight ?? 0) + STICKY_GAP
  el.scrollTo({ top: Math.max(0, node.offsetTop - offset), behavior: 'smooth' })
}

/**
 * 滚动高亮：取「顶端越过探针线」的最后一个分组。
 *
 * 用 offsetTop 而非 IntersectionObserver —— 分组数量固定（3 个），
 * 每帧一次比较的成本可忽略，且不会在平滑滚动中途给出跳跃的高亮。
 */
let scrollRaf = 0
function onScroll(): void {
  if (scrollRaf) return
  scrollRaf = requestAnimationFrame(() => {
    scrollRaf = 0
    const el = scrollEl.value
    if (!el) return
    const probe = el.scrollTop + 120
    let active = ''
    el.querySelectorAll<HTMLElement>('[data-group]').forEach((node) => {
      if (node.offsetTop - 16 <= probe) active = node.dataset.group ?? active
    })
    if (active) activeGroup.value = active
  })
}

/* ------------------------------------------------------------------ */
/* 档位 / 参数编辑                                                     */
/* ------------------------------------------------------------------ */

function presetLabelOf(c: string | number): string {
  return presetParam.value?.choice_labels?.[String(c)] ?? String(c)
}

/** 档位切换：具体的「未改项跟随新档位」由 store 的 switchPreset 负责 */
function onPresetPick(c: string | number): void {
  if (!canManage.value) return
  store.setDraftValue('bsp_preset', c)
}

const presetLabel = computed(() => {
  if (!presetParam.value) return ''
  return presetLabelOf(String(store.draft.bsp_preset ?? store.saved?.preset ?? ''))
})

function onRowInput(key: string, value: unknown): void {
  store.setDraftValue(key, value)
}

function onResetDefaults(): void {
  store.resetToDefaults()
  ElMessage.info('已恢复为当前档位的默认值（档位本身不变），仍需点保存才生效')
}

/* ------------------------------------------------------------------ */
/* 同步进度                                                            */
/* ------------------------------------------------------------------ */

const syncPercent = computed(() => {
  const job = syncJob.value
  if (!job) return 0
  if (!job.total) return job.status === 'done' ? 100 : 5
  return Math.min(100, Math.round((job.done / job.total) * 100))
})

const syncStatusType = computed(() => {
  const s = syncJob.value?.status
  if (s === 'failed') return 'exception'
  if (s === 'done') return syncStale.value ? 'warning' : 'success'
  return undefined
})

const syncFailures = computed<Array<Record<string, string>>>(() => {
  const summary = syncJob.value?.summary as { failed?: unknown } | null
  const failed = summary?.failed
  return Array.isArray(failed) ? (failed as Array<Record<string, string>>) : []
})

/* ------------------------------------------------------------------ */
/* 保存 / 关闭                                                         */
/* ------------------------------------------------------------------ */

/** 取消：丢弃草稿并关闭（有改动时先确认） */
async function onCancel(): Promise<void> {
  if (!(await confirmDiscard())) return
  store.discardDraft()
  visible.value = false
}

/** 有未保存改动时二次确认；返回 true 表示可以放弃草稿 */
async function confirmDiscard(): Promise<boolean> {
  if (!store.dirtyCount) return true
  try {
    await ElMessageBox.confirm(
      `有 ${store.dirtyCount} 项修改尚未保存，确定放弃吗？`,
      '放弃修改',
      { type: 'warning', confirmButtonText: '放弃', cancelButtonText: '继续编辑' },
    )
    return true
  } catch {
    return false
  }
}

/** 抽屉关闭钩子（Esc / 点遮罩 / 关闭按钮都会走这里） */
async function handleBeforeClose(done: () => void): Promise<void> {
  if (!(await confirmDiscard())) return
  store.discardDraft()
  done()
}

/**
 * 保存流程（design D7）：
 *   PUT → 成功后 emit saved（父组件重拉 /api/klines）
 *   → 并行触发该股票后台重算
 *
 * 422（校验失败）时抽屉保持打开、草稿完整保留，错误定位到参数。
 */
async function onSave(): Promise<void> {
  try {
    const version = await store.save()
    emit('saved', version)
    ElMessage.success('参数已保存，正在按新参数重算当前股票')

    if (props.code) {
      recomputing.value = true
      try {
        await recomputeStock(props.code, props.period)
        ElMessage.success('当前股票的数据库索引已刷新')
      } catch (e) {
        // 图表已按新参数重绘，索引刷新失败不影响查看，提示可重试
        ElMessage.warning('图表已更新，但数据库索引刷新失败，稍后可重新保存一次')
        console.warn('[ChanConfigDrawer] recompute 失败', e)
      } finally {
        recomputing.value = false
      }
    }
  } catch (e) {
    // 422：错误文案已由 axios 响应拦截器展示（detail.message），
    // 这里只做本地处理 —— 抽屉保持打开、草稿完整保留，用户就地改。
    console.warn('[ChanConfigDrawer] 保存失败', e)
  }
}

/** 批量同步：先提示未保存改动，再启动并轮询进度 */
async function onStartSync(): Promise<void> {
  if (store.dirtyCount) {
    try {
      await ElMessageBox.confirm(
        `有 ${store.dirtyCount} 项修改尚未保存。同步使用的是**已保存**的参数，是否先保存？`,
        '有未保存的修改',
        { type: 'warning', confirmButtonText: '先保存再同步', cancelButtonText: '用已保存的参数同步' },
      )
      await onSave()
    } catch {
      // 用户选择用已保存的参数同步，继续
    }
  }

  try {
    await startChanSync()
    syncRunning.value = true
    ElMessage.success('已开始同步所有股票，可在下方查看进度')
    pollSync(true)
  } catch (e) {
    const status = (e as { response?: { status?: number } }).response?.status
    if (status === 409) ElMessage.warning('已有同步任务在运行，请等待完成')
    else ElMessage.error('启动同步失败')
  }
}

/** 轮询同步状态；`immediate` 为 true 时立即拉一次 */
function pollSync(immediate = false): void {
  const tick = async () => {
    try {
      const st = await getChanSyncStatus()
      syncJob.value = st.job
      syncStale.value = st.stale
      syncRunning.value = st.running
      if (!st.running) {
        stopPoll()
        if (st.job?.status === 'done') {
          ElMessage.success(st.job.failed ? `同步完成，${st.job.failed} 个失败` : '同步完成')
        }
      }
    } catch (e) {
      console.warn('[ChanConfigDrawer] 同步状态查询失败', e)
    }
  }
  stopPoll()
  if (immediate) void tick()
  syncTimer = setInterval(tick, 3000)
}

function stopPoll(): void {
  if (syncTimer) {
    clearInterval(syncTimer)
    syncTimer = null
  }
}

/* ------------------------------------------------------------------ */
/* 打开 / 关闭生命周期                                                  */
/* ------------------------------------------------------------------ */

watch(visible, async (v) => {
  if (!v) {
    stopPoll()
    return
  }
  structureAcknowledged.value = false
  keyword.value = ''
  onlyModified.value = false
  // 每次打开都真去拉一次已保存配置，期间挡一下交互 —— 否则上一次的草稿会短暂
  // 可见，用户在这几百毫秒里改的值会被随后的 `fetchSaved()` 覆盖掉。
  loading.value = true
  try {
    await store.openDraft()
  } catch (e) {
    ElMessage.error('加载参数配置失败')
    console.warn('[ChanConfigDrawer] openDraft 失败', e)
  } finally {
    loading.value = false
  }
  activeGroup.value = filteredGroups.value[0]?.id ?? ''
  // 抽屉打开时若已有同步任务在跑，接上进度显示
  try {
    const st = await getChanSyncStatus()
    syncJob.value = st.job
    syncStale.value = st.stale
    syncRunning.value = st.running
    if (st.running) pollSync()
  } catch {
    /* 状态查询失败不影响抽屉使用 */
  }
})

/** 筛选变化后重新定位高亮（被过滤掉的组不应继续高亮） */
watch(filteredGroups, (list) => {
  if (!list.some((g) => g.id === activeGroup.value)) {
    activeGroup.value = list[0]?.id ?? ''
  }
})

/**
 * 搜索/筛选变化时把右栏拉回顶部。
 *
 * 不这么做的话：用户滚到「一买判据」中部再输入关键词，命中的项在别组，
 * 右栏停在原位置显示大片空白，看起来像「搜不到」。
 */
watch([keyword, onlyModified], () => {
  scrollEl.value?.scrollTo({ top: 0 })
})

/**
 * 自定义项归零时自动退出「仅看自定义」。
 *
 * 触发场景：用户点「恢复默认」或把最后一项改回档位默认值 —— 此时筛选结果为空，
 * 抽屉看起来像「参数全没了」，而且筛选按钮本身已因计数为 0 变成禁用，
 * 用户无从关掉它。自动退出是唯一不困住用户的选择。
 */
watch(
  () => store.overriddenKeys.size,
  (n) => {
    if (n === 0) onlyModified.value = false
  },
)
</script>

<style scoped>
/* ==================== 头部 ==================== */
.cfg-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  /* 窄屏时档位开关落到第二行，而不是被 el-drawer__header 的 overflow:hidden 切掉 */
  flex-wrap: wrap;
  gap: 10px var(--sp-2xl);
  flex: 1;
  min-width: 0;
}
.cfg-head__eyebrow {
  font-size: 9.5px;
  letter-spacing: 0.16em;
  color: var(--text-secondary);
  opacity: 0.75;
  margin-bottom: 3px;
}
.cfg-head__title {
  display: flex;
  align-items: baseline;
  gap: 10px;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--text-primary);
  line-height: 1.3;
}
.cfg-head__code {
  font-size: 11.5px;
  font-weight: 400;
  color: var(--text-secondary);
  padding: 1px 7px;
  border-radius: 3px;
  background: var(--bg-surface-hover);
  border: 1px solid var(--border-base);
}

.cfg-head__preset {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 0 0 auto;
}
.cfg-head__preset-label {
  font-size: 11px;
  color: var(--text-secondary);
  letter-spacing: 0.04em;
}
.preset-seg {
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  border-radius: var(--r-md);
  background: var(--bg-base);
  border: 1px solid var(--border-base);
}
.preset-seg__item {
  padding: 4px 12px;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 11.5px;
  font-weight: 500;
  white-space: nowrap;
  transition: all 0.15s ease;
}
.preset-seg__item:hover:not(:disabled):not(.is-active) {
  color: var(--text-primary);
  background: var(--bg-surface-hover);
}
.preset-seg__item.is-active {
  background: var(--accent-base);
  color: var(--text-on-accent);
  box-shadow: 0 2px 8px color-mix(in srgb, var(--accent-base) 32%, transparent);
}
.preset-seg__item:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.cfg-loading {
  flex: 1;
  width: 100%;
  padding: var(--sp-xl);
}
.cfg-loading--error p {
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-secondary);
}
.cfg-loading--busy {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
  gap: 10px;
  font-size: 12px;
  color: var(--text-secondary);
}
.cfg-loading__spin {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 1.5px solid var(--border-strong);
  border-top-color: var(--accent-base);
  animation: cfg-spin 0.8s linear infinite;
}
@keyframes cfg-spin {
  to { transform: rotate(360deg); }
}

/* ==================== 两栏骨架 ==================== */
.cfg-shell {
  display: flex;
  flex: 1;
  min-height: 0;
  min-width: 0;
}

/* ---- 左栏导航 ---- */
.cfg-nav {
  width: 214px;
  flex: 0 0 214px;
  display: flex;
  flex-direction: column;
  gap: var(--sp-sm);
  min-height: 0;          /* 显式声明，否则长列表会被 flex 撑高而不出滚动条 */
  padding: var(--sp-lg) 12px var(--sp-lg) var(--sp-lg);
  border-right: 1px solid var(--border-base);
  background: linear-gradient(
    180deg,
    color-mix(in srgb, var(--bg-surface) 55%, transparent),
    transparent 240px
  );
  overflow-y: auto;
}

.cfg-nav__search :deep(.el-input__wrapper) {
  background: var(--bg-base);
}

.cfg-nav__chip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 5px 9px;
  border: 1px solid var(--border-base);
  border-radius: var(--r-sm);
  background: var(--bg-base);
  color: var(--text-secondary);
  font-size: 11.5px;
  transition: all 0.15s ease;
}
.cfg-nav__chip .mono {
  color: var(--text-secondary);
  opacity: 0.7;
  font-size: 10.5px;
}
.cfg-nav__chip:hover:not(:disabled) {
  color: var(--text-primary);
  border-color: var(--border-strong);
}
.cfg-nav__chip.is-on {
  color: var(--warning);
  border-color: color-mix(in srgb, var(--warning) 55%, transparent);
  background: var(--warning-dim);
}
.cfg-nav__chip.is-on .mono {
  color: var(--warning);
}
.cfg-nav__chip:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.cfg-nav__list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: 2px;
}

.cfg-nav__link {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 9px;
  border: none;
  border-radius: var(--r-sm);
  background: transparent;
  text-align: left;
  color: var(--text-secondary);
  transition: all 0.15s ease;
}
.cfg-nav__link::before {
  content: "";
  position: absolute;
  left: 0;
  top: 50%;
  width: 2px;
  height: 0;
  border-radius: var(--r-full);
  background: var(--g-accent, var(--accent-base));
  transform: translateY(-50%);
  transition: height 0.2s cubic-bezier(0.22, 1, 0.36, 1);
}
.cfg-nav__link:hover {
  background: var(--bg-surface-hover);
  color: var(--text-primary);
}
.cfg-nav__link.is-active {
  background: var(--bg-surface-hover);
  color: var(--text-primary);
}
.cfg-nav__link.is-active::before {
  height: 18px;
}

.cfg-nav__index {
  font-size: 9.5px;
  letter-spacing: 0.04em;
  color: var(--text-disabled);
  flex: 0 0 auto;
}
.cfg-nav__link.is-active .cfg-nav__index {
  color: var(--g-accent, var(--accent-base));
}
.cfg-nav__name {
  flex: 1;
  min-width: 0;
  font-size: 12.5px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cfg-nav__count {
  font-size: 10px;
  color: var(--text-secondary);
  opacity: 0.7;
  flex: 0 0 auto;
}

.cfg-nav__subs {
  display: flex;
  flex-direction: column;
  gap: 1px;
  margin: 2px 0 6px 13px;
  padding-left: 10px;
  border-left: 1px solid var(--border-base);
}
.cfg-nav__sub {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  width: 100%;
  padding: 4px 8px;
  border: none;
  border-radius: 3px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 11px;
  text-align: left;
  transition: all 0.14s ease;
}
.cfg-nav__sub:hover {
  color: var(--text-primary);
  background: var(--bg-surface);
}
.cfg-nav__sub-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cfg-nav__sub-count {
  font-size: 9.5px;
  flex: 0 0 auto;
}

.subs-enter-active,
.subs-leave-active {
  transition: opacity 0.16s ease, transform 0.16s ease;
}
.subs-enter-from,
.subs-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

.cfg-nav__none {
  font-size: 11.5px;
  color: var(--text-secondary);
  padding: 10px 4px;
}

.cfg-nav__foot {
  margin-top: auto;
  padding-top: var(--sp-md);
  border-top: 1px solid var(--border-base);
}
.cfg-nav__foot p {
  margin: 0;
  font-size: 10.5px;
  line-height: 1.6;
  color: var(--text-secondary);
  opacity: 0.8;
}
.cfg-nav__foot strong {
  color: var(--text-secondary);
  font-weight: 600;
}
.cfg-nav__warn {
  color: var(--warning);
  opacity: 0.85;
}

/* ---- 右栏内容 ---- */
.cfg-main {
  position: relative;
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  scroll-behavior: smooth;
}
.cfg-main__inner {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2xl);
  /* 顶部留够：吸顶组标题需要一点上边距，否则贴边发闷 */
  padding: var(--sp-md) var(--sp-xl) var(--sp-2xl);
}

/* ==================== 分组 ==================== */
.cfg-group {
  scroll-margin-top: 8px;
}

.cfg-group__head {
  /* 吸顶：滚到「一买判据」第 8 项时仍知道自己在哪一组（长列表的必要锚点）。
     底色必须不透明，否则下方参数会透上来。 */
  position: sticky;
  top: 0;
  z-index: 2;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 8px 0 12px;
  margin-bottom: 14px;
  border-bottom: 1px solid var(--border-base);
  background: var(--bg-base);
  box-shadow: 0 -8px 0 var(--bg-base), 0 8px 12px -8px var(--bg-base);
}
.cfg-group__head::after {
  content: "";
  position: absolute;
  left: 0;
  bottom: -1px;
  width: 56px;
  height: 2px;
  border-radius: var(--r-full);
  background: var(--g-accent, var(--accent-base));
}

.cfg-group__index {
  flex: 0 0 auto;
  font-size: 26px;
  font-weight: 700;
  line-height: 1;
  letter-spacing: -0.04em;
  color: var(--g-accent, var(--accent-base));
  opacity: 0.32;
  padding-top: 2px;
  font-variant-numeric: tabular-nums;
}

.cfg-group__titles {
  flex: 1;
  min-width: 0;
}
.cfg-group__title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 17px;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--text-primary);
  line-height: 1.3;
}
.cfg-group__badge {
  font-size: 9.5px;
  font-weight: 500;
  letter-spacing: 0.04em;
  padding: 1px 6px;
  border-radius: 3px;
  color: var(--warning);
  background: var(--warning-dim);
  border: 1px solid color-mix(in srgb, var(--warning) 30%, transparent);
}
.cfg-group__hint {
  margin-top: 4px;
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--text-secondary);
}
.cfg-group__count {
  flex: 0 0 auto;
  font-size: 10.5px;
  color: var(--text-secondary);
  opacity: 0.7;
  padding-top: 4px;
}

/* ==================== 子分类 ==================== */
.cfg-sub {
  scroll-margin-top: 96px;   /* 让开吸顶的组标题 */
}
.cfg-sub + .cfg-sub {
  margin-top: var(--sp-lg);
}
.cfg-sub__head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.cfg-sub__title {
  flex: 0 0 auto;
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.05em;
  color: var(--text-primary);
  padding: 2px 9px;
  border-radius: var(--r-full);
  background: color-mix(in srgb, var(--g-accent, var(--accent-base)) 11%, transparent);
  border: 1px solid color-mix(in srgb, var(--g-accent, var(--accent-base)) 24%, transparent);
}
.cfg-sub__line {
  flex: 1;
  height: 1px;
  background: var(--border-base);
}
.cfg-sub__count {
  flex: 0 0 auto;
  font-size: 10px;
  color: var(--text-secondary);
  opacity: 0.7;
}

.cfg-sub__grid {
  display: grid;
  /* 两列（有一列容不下就退成一列）：宽屏 1120px 抽屉里右栏约 850px，
     348px 的下限正好排出两列，既不让卡片被拉得过宽，也不浪费横向空间。 */
  grid-template-columns: repeat(auto-fill, minmax(348px, 1fr));
  gap: 8px;
  align-items: start;
}
/* 多选行（bs_type）候选多，整行横跨 */
.cfg-sub__grid > :deep(.cfg-row.is-wide) {
  grid-column: 1 / -1;
}

/* 窄屏：导航收窄，把宽度留给参数网格 */
@media (max-width: 1180px) {
  .cfg-nav {
    width: 184px;
    flex-basis: 184px;
  }
}

/* 结构组门槛 */
.cfg-gate {
  padding: var(--sp-xl);
  border: 1px dashed var(--border-strong);
  border-radius: var(--r-md);
  background: var(--bg-surface);
  text-align: center;
}
.cfg-gate p {
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-secondary);
  margin: 0 0 var(--sp-md);
}

/* ==================== 全库同步 ==================== */
.cfg-sync {
  padding: var(--sp-lg);
  border-radius: var(--r-md);
  background: var(--bg-surface);
  border: 1px solid var(--border-base);
}
.cfg-sync__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sp-lg);
}
.cfg-sync__title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.cfg-sync__hint {
  font-size: 11.5px;
  line-height: 1.65;
  color: var(--text-secondary);
  margin: 5px 0 0;
  max-width: 620px;
}
.cfg-sync__progress {
  margin-top: var(--sp-md);
}
.cfg-sync__stats {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 5px;
}
.cfg-sync__failures {
  margin-top: var(--sp-sm);
  max-height: 140px;
  overflow-y: auto;
}
.cfg-sync__failures-title {
  font-size: 11.5px;
  color: var(--rise);
  margin-bottom: 4px;
}
.cfg-sync__failure {
  font-size: 11px;
  line-height: 1.5;
  color: var(--text-secondary);
}

/* ==================== 底部 ==================== */
.cfg-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-lg);
  width: 100%;
}
.cfg-footer__status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  min-width: 0;
}
.cfg-footer__dot {
  width: 6px;
  height: 6px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: var(--text-disabled);
  transition: background 0.2s ease, box-shadow 0.2s ease;
}
.cfg-footer__dot.is-dirty {
  background: var(--warning);
  box-shadow: 0 0 0 3px var(--warning-dim);
}
.cfg-footer__dirty {
  color: var(--warning);
}
.cfg-footer__dirty strong {
  font-size: 13px;
}
.cfg-footer__clean {
  color: var(--text-secondary);
}
.cfg-footer__sep {
  color: var(--text-disabled);
}
.cfg-footer__preset {
  color: var(--text-secondary);
  font-size: 11.5px;
}
.cfg-footer__readonly {
  font-size: 10px;
  letter-spacing: 0.04em;
  padding: 1px 6px;
  border-radius: 3px;
  color: var(--text-secondary);
  border: 1px solid var(--border-base);
}
.cfg-footer__actions {
  display: flex;
  gap: var(--sp-sm);
  flex: 0 0 auto;
}
</style>

<style>
/* 抽屉本体（append-to-body，wrapper 的 scoped 样式够不到）：
   去掉默认 padding 与滚动，让内部两栏各自滚动。 */
.chan-config-drawer .el-drawer__body {
  padding: 0;
  overflow: hidden;
  display: flex;
  min-height: 0;
}
.chan-config-drawer .el-drawer__header {
  margin-bottom: 0;
  padding: 14px 20px;
  align-items: center;
  border-bottom: 1px solid var(--border-base);
  background: linear-gradient(
    180deg,
    color-mix(in srgb, var(--bg-surface) 78%, transparent),
    var(--bg-base)
  );
}
.chan-config-drawer .el-drawer__footer {
  padding: 10px 20px;
  border-top: 1px solid var(--border-base);
  background: var(--bg-base);
}
</style>
