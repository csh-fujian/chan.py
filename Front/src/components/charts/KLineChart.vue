<template>
  <div class="kline-chart-wrap">
    <div ref="chartRef" class="kline-chart-el" />
    <div v-if="loading" class="kline-chart-loading">
      <span>加载中…</span>
    </div>
    <div v-else-if="empty" class="kline-chart-empty">
      <span>无数据</span>
    </div>
    <!-- 量均线配置按钮：pane 为 canvas 无 DOM 注入点，用 HTML 浮层贴 VOL pane 右上角（kline-chart-change D2） -->
    <button
      v-if="volBtnPos"
      class="vol-config-btn"
      type="button"
      title="量均线配置"
      :style="{ top: `${volBtnPos.top}px`, left: `${volBtnPos.left}px` }"
      @click="volDialogVisible = true"
    >
      <el-icon><Setting /></el-icon>
    </button>
    <VolConfigDialog v-model="volDialogVisible" />
    <!-- 买卖点确认阶梯 hover 说明卡（bsp-ladder-change D5）：canvas overlay 无法用
         el-tooltip 包裹，走 chan_bsp 注册期注入的 hover 钩子 + 绝对定位浮层 -->
    <div
      v-if="bspLadderTip.show"
      class="bsp-ladder-tip"
      :style="{ top: `${bspLadderTip.top}px`, left: `${bspLadderTip.left}px` }"
    >
      <div class="bsp-ladder-tip__head">
        <span class="bsp-ladder-tip__badge" :class="`badge--${ladderBadgeClass(bspLadderTip.ladder)}`">
          {{ bspLadderTip.ladder ? bspLadderTip.ladder : '未定级' }}
        </span>
        <span class="bsp-ladder-tip__dir" :class="bspLadderTip.isBuy ? 'text-rise' : 'text-fall'">
          {{ bspLadderTip.isBuy ? '买点' : '卖点' }}
        </span>
        <span class="bsp-ladder-tip__types mono">{{ bspLadderTip.typesLabel }}</span>
      </div>
      <div class="bsp-ladder-tip__rows">
        <div
          v-for="l in LADDER_LEVELS"
          :key="l.level"
          class="bsp-ladder-tip__row"
          :class="{ 'is-current': l.level === bspLadderTip.ladder }"
        >
          <span class="bsp-ladder-tip__lv mono">{{ l.level }}</span>
          <span class="bsp-ladder-tip__name">{{ l.name }}</span>
          <!-- 仓位指引按悬浮标记方向取（卖点镜像文案，bspLadder.ladderPosition） -->
          <span class="bsp-ladder-tip__pos">{{ ladderPosition(l, bspLadderTip.isBuy) }}</span>
        </div>
        <div v-if="!bspLadderTip.ladder" class="bsp-ladder-tip__row is-current">
          <span class="bsp-ladder-tip__lv mono">--</span>
          <span class="bsp-ladder-tip__name">未定级（数据缺 ladder 字段或降级）</span>
          <span class="bsp-ladder-tip__pos">--</span>
        </div>
      </div>
      <div v-if="bspLadderTip.l1Resonant" class="bsp-ladder-tip__sub">
        L1 小级别共振佐证同时成立（当前按判定顺序标 {{ bspLadderTip.ladder }}）
      </div>
      <div class="bsp-ladder-tip__note">{{ LADDER_ORDER_NOTE }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * KLineChart.vue — K 线 + 缠论 overlay 渲染
 * design.md D6：chart 实例非响应式，onMounted init，watch 命令式重载。
 */
import { onMounted, onActivated, onBeforeUnmount, ref, watch } from 'vue'
import {
  init,
  dispose,
  DomPosition,
  type Chart,
  type KLineData,
  type Indicator,
  type IndicatorCreate,
  type SmoothLineStyle,
  LineType,
  PolygonType,
  LoadDataType,
} from 'klinecharts'
import { Setting } from '@element-plus/icons-vue'
import type { ChanResult } from '@/api/types'
import {
  registerAllChanOverlays,
  chanBspLabel,
  bspBoxSize,
  vBspRadius,
  setChanBspHoverHooks,
  type ChanBspMeta,
  type ChanVBspMeta,
  type ChanBiMeta,
  type ChanSegMeta,
} from '@/components/chan'
import {
  isLadder,
  ladderInfo,
  ladderPosition,
  LADDER_LEVELS,
  LADDER_ORDER_NOTE,
} from '@/utils/bspLadder'
import {
  useVirtualBsp,
  findAnchorBarTimestamp,
} from '@/composables/useVirtualBsp'
import { registerVolIndicator } from '@/components/charts/volIndicator'
import { createBollIndicator } from '@/components/charts/bollIndicator'
import {
  registerSubCandleOverlay,
  buildSubCandleOverlay,
} from '@/components/charts/subCandleOverlay'
import { getChartStyles } from '@/components/charts/chartStyles'
import { getChanPalette } from '@/components/chan/palette'
import { getKLine } from '@/api/modules/kline'
import { useChartConfigStore } from '@/stores/chartConfig'
import { useThemeStore } from '@/stores/theme'
import { useChartLegend } from '@/composables/useChartLegend'
import VolConfigDialog from '@/components/kline/VolConfigDialog.vue'

const props = defineProps<{
  result: ChanResult | null
  code?: string
  period?: string
}>()

const chartRef = ref<HTMLDivElement | null>(null)
const loading = ref(false)
const empty = ref(false)

// chart 实例非响应式（design.md D6）
let chart: Chart | null = null
let resizeObserver: ResizeObserver | null = null
/** 首屏数据是否已加载完毕，在此之前跳过增量加载 */
let initialLoadDone = false

/** 副图指标 pane id 前缀 */
const PANE_PREFIX = 'chan_sub_'
/** 副图指标 pane 固定高度（创建与 KeepAlive 复活恢复共用） */
const SUB_PANE_HEIGHT = 130
/** 当前已创建的副图指标 → paneId 映射 */
const subPaneMap = new Map<string, string>()

/** 红涨绿跌语义色走 palette（kline-chart-change 6.3，主题不变）；getChanPalette() 绘制时取 */

// ---------------------------------------------------------------------------
// 均线配置（kline-chart-change D1/D2）：chartConfig store 持久化，watch 后即时应用
// ---------------------------------------------------------------------------
const chartConfig = useChartConfigStore()
/** 主图 MA 挂载 pane（klinecharts 内建蜡烛 pane id） */
const MA_PANE_ID = 'candle_pane'

// ---------------------------------------------------------------------------
// 主题（kline-chart-change D3 / 任务 6.3）：theme store 驱动 setStyles +
// 覆盖层重建；overlay 绘制色经 getChanPalette()（读 <html data-theme>）实时取。
// ---------------------------------------------------------------------------
const themeStore = useThemeStore()

// ---------------------------------------------------------------------------
// 行情图例写方（kline-chart-change D7 / 任务 5.1、5.4）：
// 悬停跟随十字光标（subscribeAction onCrosshairChange），无悬停回退最新一根；
// prevClose 由 result.klines 本地推导。本组件只写共享状态（setSeries/attach），
// 展示在 StockPanel 头部（任务 5.3，主图左上角不再挂图例）。
// ---------------------------------------------------------------------------
const {
  setSeries: setLegendSeries,
  mergeSeries: mergeLegendSeries,
  attach: attachLegend,
  detach: detachLegend,
} = useChartLegend()

/** VOL 量均线配置按钮浮层位置（图表容器坐标系）；null = 不显示 */
const volBtnPos = ref<{ top: number; left: number } | null>(null)
const volDialogVisible = ref(false)
let volBtnRaf = 0

// ---------------------------------------------------------------------------
// 买卖点确认阶梯 hover 说明卡（bsp-ladder-change D5 / 任务 3.2）：
// chan_bsp overlay 注册期注入 hover 钩子（figure 命中 → meta + 鼠标坐标），
// 此处以绝对定位浮层渲染（canvas overlay 无法用 el-tooltip 包裹）。
// 缺 ladder 字段兜底「未定级」；浮层位置贴鼠标右上，右缘越界自动翻转。
// ---------------------------------------------------------------------------
interface BspLadderTip {
  show: boolean
  top: number
  left: number
  ladder: string | null
  isBuy: boolean
  typesLabel: string
  /** L3 命中且 L1 共振同时成立的副标记（后端 L3 优先裁定，design D1） */
  l1Resonant: boolean
}
const bspLadderTip = ref<BspLadderTip>({
  show: false, top: 0, left: 0, ladder: null, isBuy: true, typesLabel: '', l1Resonant: false,
})

/** 级别 → 徽章色（L4 实色 / L1-L3 弱化，design D6 语义与买卖点页级别列一致） */
function ladderBadgeClass(ladder: string | null): string {
  if (ladder === 'L4') return 'rise'
  if (ladder === 'L3') return 'warning'
  if (ladder === 'L1') return 'info'
  return 'default'
}

/** 估算浮层尺寸（定宽 + 估算高：头部 + 4 行 + 脚注），用于越界翻转 */
const TIP_WIDTH = 300
const TIP_HEIGHT = 210
/** 浮层与鼠标的间隙 */
const TIP_GAP = 14

/** figure 命中 → 展示浮层（位置贴鼠标右上；右缘/下缘越界翻转） */
function showBspLadderTip(meta: ChanBspMeta, x: number, y: number): void {
  const info = ladderInfo(meta.ladder)
  const label = chanBspLabel(meta.types, meta.isBuy)
  let left = x + TIP_GAP
  let top = y - TIP_HEIGHT / 2
  // 容器宽高未知时用 chart DOM 兜底；右缘越界翻到鼠标左侧
  const wrapW = chartRef.value?.clientWidth ?? 0
  const wrapH = chartRef.value?.clientHeight ?? 0
  if (wrapW > 0 && left + TIP_WIDTH > wrapW) left = x - TIP_WIDTH - TIP_GAP
  if (top < 4) top = 4
  if (wrapH > 0 && top + TIP_HEIGHT > wrapH - 4) top = Math.max(4, wrapH - TIP_HEIGHT - 4)
  bspLadderTip.value = {
    show: true,
    top,
    left,
    ladder: info?.level ?? null,
    isBuy: meta.isBuy,
    typesLabel: label,
    l1Resonant: false, // L1 共振副标记：单字段语义下 L3 命中时无独立 L1 状态可考，先常 false
  }
}

function hideBspLadderTip(): void {
  bspLadderTip.value.show = false
}

/** 构造 MA 指标创建/覆盖参数：calcParams 天数 + 逐线颜色 */
function mainMaIndicator(): IndicatorCreate {
  const list = chartConfig.mainMA
  return {
    name: 'MA',
    calcParams: list.map((m) => m.days),
    // lines 与 calcParams 位置对应。必须给出完整线型字段：实例 styles 会整段替换库默认值
    // （formatValue 不做逐字段合并），缺 dashedValue 会在 IndicatorView.drawImp 合并线段时崩溃
    styles: {
      lines: list.map(
        (m): SmoothLineStyle => ({
          style: LineType.Solid,
          smooth: false,
          size: 1,
          dashedValue: [2, 2],
          color: m.color,
        }),
      ),
    },
  }
}

/**
 * 应用主图均线配置：
 * - 空列表 → removeIndicator 移除 MA
 * - 已有实例 → overrideIndicator 原地更新（regenerateFigures 按新参数重建线）
 * - 缺失（初始化/被移除后）→ createIndicator 挂回 candle_pane
 * applyResult 重放走同一路径，保证切换股票/周期后配置仍生效。
 */
function applyMainMa(): void {
  if (!chart) return
  if (chartConfig.mainMA.length === 0) {
    chart.removeIndicator(MA_PANE_ID, 'MA')
    return
  }
  const existing = chart.getIndicatorByPaneId(MA_PANE_ID, 'MA') as Indicator | null
  if (existing) {
    chart.overrideIndicator(mainMaIndicator(), MA_PANE_ID)
  } else {
    chart.createIndicator(mainMaIndicator(), false, { id: MA_PANE_ID })
  }
}

/** 应用量均线配置到 VOL 副图（pane 不存在时跳过，创建时已带 calcParams） */
function applyVolMa(): void {
  if (!chart) return
  const paneId = subPaneMap.get('VOL')
  if (!paneId) return
  chart.overrideIndicator(
    { name: 'VOL', calcParams: chartConfig.volMA.map((v) => v.days) },
    paneId,
  )
}

/** 重算 VOL 配置按钮浮层位置（pane 布局在 resize/增删副图后变化，rAF 等布局落定） */
function scheduleVolBtnUpdate(): void {
  if (volBtnRaf) cancelAnimationFrame(volBtnRaf)
  volBtnRaf = requestAnimationFrame(() => {
    volBtnRaf = 0
    updateVolConfigBtn()
  })
}

function updateVolConfigBtn(): void {
  if (!chart) {
    volBtnPos.value = null
    return
  }
  const paneId = subPaneMap.get('VOL')
  if (!paneId) {
    volBtnPos.value = null
    return
  }
  // Main 区域（不含右侧 y 轴）bounding：按钮贴 VOL pane 绘图区右上角
  const b = chart.getSize(paneId, DomPosition.Main)
  if (!b || b.width <= 0) {
    volBtnPos.value = null
    return
  }
  volBtnPos.value = { top: b.top + 3, left: b.left + b.width - 25 }
}

/** 移除全部缠论覆盖层（按 name 匹配；切周期/股票、加载失败、主题切换时调用） */
function clearChanOverlays(): void {
  if (!chart) return
  const names = ['chan_bi', 'chan_seg', 'chan_zs', 'chan_bsp', 'chan_vbsp'] as const
  for (const name of names) {
    chart.removeOverlay({ name })
  }
}

/** 移除 BOLL 副图 sub_candle 蜡烛柱（按 name 匹配） */
function clearSubCandle(): void {
  if (!chart) return
  chart.removeOverlay({ name: 'sub_candle' })
}

// ---------------------------------------------------------------------------
// 买卖点标记重建（kline-chart-change D5/D6 / 任务 3.x、4.3）
// ---------------------------------------------------------------------------
/** 最近一次 applyResult 的数据（虚拟买卖点异步到达后据此重建 bsp overlay） */
let lastResult: ChanResult | null = null
/** lastResult 对应的股票 code（虚拟买卖点数据防串号比对用） */
let appliedCode = ''

/** 监控数据 → 虚拟买卖点（任务 4.1）：code 变化时拉取，数据到达后触发重建 */
const { state: virtualBsp, load: loadVirtualBsp } = useVirtualBsp()

/**
 * 重建 chan_bsp / chan_vbsp 买卖点覆盖层。两个 overlay 须同批重建：
 * 共存左右排布（虚拟左移 / 缠论右移）需要同时拿到双方标记，且双方都按
 * 「本地日历日吸附到 bar」后的 bar 时间戳判定同 bar。
 * 触发点：applyResult（新数据）与虚拟买卖点数据到达（异步，不阻塞渲染）。
 */
function rebuildBspOverlays(): void {
  if (!chart) return
  // removeOverlay 按 name 匹配（见 clearChanOverlays 注释）
  chart.removeOverlay({ name: 'chan_bsp' })
  chart.removeOverlay({ name: 'chan_vbsp' })
  const result = lastResult
  if (!result) return

  // bar 时间戳 → high/low（写入 extendData，绘制端 yAxis.convertToPixel 换算锚点）
  const barByTs = new Map<number, { high: number; low: number }>()
  for (const k of result.klines) {
    barByTs.set(k.timestamp, { high: k.high, low: k.low })
  }

  // —— 缠论买卖点：吸附到所在 bar（time_key 可能含时分，按日取 bar）——
  interface BspMark {
    isBuy: boolean
    types: string[]
    v: number
    barTs: number
    high: number
    low: number
    /** 确认阶梯级别（bsp-ladder-change 3.1）：保留不再丢弃；缺失 = 未定级 */
    ladder?: string
  }
  const chanMarks: BspMark[] = []
  let chanDropped = 0
  for (const b of result.bsp) {
    const barTs = findAnchorBarTimestamp(result.klines, b.t)
    const bar = barTs !== null ? barByTs.get(barTs) : undefined
    if (barTs === null || !bar) {
      chanDropped++
      continue
    }
    chanMarks.push({
      isBuy: b.is_buy,
      types: b.types,
      v: b.v,
      barTs,
      high: bar.high,
      low: bar.low,
      ladder: isLadder(b.ladder) ? b.ladder : undefined,
    })
  }

  // —— 虚拟买卖点：仅当 monitor 数据的 code 与当前图表一致（异步数据防串号）——
  interface VBspMark {
    isBuy: boolean
    v: number
    barTs: number
    high: number
    low: number
  }
  const vMarks: VBspMark[] = []
  let vDropped = 0
  const vb = virtualBsp.value
  if (vb.code === appliedCode) {
    for (const p of vb.items) {
      const barTs = findAnchorBarTimestamp(result.klines, p.t)
      const bar = barTs !== null ? barByTs.get(barTs) : undefined
      if (barTs === null || !bar) {
        vDropped++
        continue
      }
      vMarks.push({ isBuy: p.isBuy, v: p.v, barTs, high: bar.high, low: bar.low })
    }
  }
  if (chanDropped > 0 || vDropped > 0) {
    console.warn('[KLineChart.rebuildBspOverlays] 部分买卖点未吸附到 K 线 bar，已跳过', {
      chanDropped,
      vDropped,
      code: appliedCode,
    })
  }

  // —— 同 bar 双方共存 → 左右排布（任务 4.3）：虚拟左移、缠论右移 ——
  const chanBars = new Set(chanMarks.map((m) => m.barTs))
  const coexistBars = new Set<number>()
  for (const m of vMarks) {
    if (chanBars.has(m.barTs)) coexistBars.add(m.barTs)
  }

  // —— 缠论买卖点 overlay（矩形框，任务 3.1/3.2/4.3）——
  if (chanMarks.length > 0) {
    const bspPoints: Array<{ timestamp: number; value: number }> = []
    const bspMeta: ChanBspMeta[] = []
    const stackCnt = new Map<string, number>()
    for (const m of chanMarks) {
      // 同 bar 同向多标记 → 垂直堆叠序号（任务 3.2）
      const key = `${m.barTs}_${m.isBuy ? 'b' : 's'}`
      const stackIndex = stackCnt.get(key) ?? 0
      stackCnt.set(key, stackIndex + 1)
      // 共存时右移半个框宽 + 2px，与虚拟标记并排（任务 4.3）
      const { width } = bspBoxSize(chanBspLabel(m.types, m.isBuy))
      const xOffset = coexistBars.has(m.barTs) ? width / 2 + 2 : 0
      bspPoints.push({ timestamp: m.barTs, value: m.v })
      bspMeta.push({
        isBuy: m.isBuy,
        types: m.types,
        pointIndex: bspPoints.length - 1,
        high: m.high,
        low: m.low,
        stackIndex,
        xOffset,
        ladder: m.ladder,
      })
    }
    chart.createOverlay({
      name: 'chan_bsp',
      lock: true,
      points: bspPoints,
      extendData: bspMeta,
    })
  }

  // —— 虚拟买卖点 overlay（圆形框，任务 4.2/4.3）——
  if (vMarks.length > 0) {
    const vPoints: Array<{ timestamp: number; value: number }> = []
    const vMeta: ChanVBspMeta[] = []
    const stackCnt = new Map<string, number>()
    for (const m of vMarks) {
      const key = `${m.barTs}_${m.isBuy ? 'b' : 's'}`
      const stackIndex = stackCnt.get(key) ?? 0
      stackCnt.set(key, stackIndex + 1)
      // 共存时左移半个圆框宽 + 2px（圆宽 = 2r），与缠论标记并排（任务 4.3）
      const xOffset = coexistBars.has(m.barTs) ? -(vBspRadius(m.isBuy) + 2) : 0
      vPoints.push({ timestamp: m.barTs, value: m.v })
      vMeta.push({
        isBuy: m.isBuy,
        pointIndex: vPoints.length - 1,
        high: m.high,
        low: m.low,
        stackIndex,
        xOffset,
      })
    }
    chart.createOverlay({
      name: 'chan_vbsp',
      lock: true,
      points: vPoints,
      extendData: vMeta,
    })
  }
}

/**
 * 同步 BOLL 副图的 sub_candle 蜡烛覆盖层（kline-chart-change D4 / 任务 2.3）。
 * BOLL 副图存在时按当前图表数据重建蜡烛柱，否则移除 —— 与 BOLL pane 生命周期
 * （syncSubIndicators 的增删 / applyResult 重放）保持一致。
 */
function syncSubCandle(): void {
  if (!chart) return
  // 先清旧实例（removeOverlay 按 name 匹配，见 clearChanOverlays 注释）
  chart.removeOverlay({ name: 'sub_candle' })
  const paneId = subPaneMap.get('BOLL')
  if (!paneId) return
  const klines = chart.getDataList()
  if (klines.length === 0) return
  chart.createOverlay(buildSubCandleOverlay(klines), paneId)
}

/**
 * 清除并重建全部覆盖层：笔 / 线段 / 中枢 / 买卖点 + 虚拟买卖点 / BOLL 副图蜡烛。
 * 两条路径共用（任务 6.3）：
 * - applyResult（新数据载入后）；
 * - 主题切换（overlay 绘制色在 createPointFigures 取 palette，重建保证立即重绘）。
 * 数据基线 = lastResult（主题切换不重放 K 线，保留当前视野；无数据则只清不建）。
 */
function rebuildAllOverlays(): void {
  if (!chart) return
  const result = lastResult

  // 先移除旧覆盖层，再重建
  // 注意：klinecharts 的 removeOverlay(string) 按 overlay id 匹配，而 createOverlay
  // 未显式传 id 时 id 为自动生成，字符串传参删不掉旧实例 → 必须按 name 移除
  clearChanOverlays()

  if (result) {
    // 笔覆盖层：points 按 [begin, end, begin, end, ...] 顺序；lock=true 禁止拖动
    // kline-unsure-dashed：extendData 挂与 points 顺序对齐的元数据数组（每条笔一项：
    // startIndex 对齐 points 起始索引 + isSure 确认状态），绘制端按 meta 取线型
    //（isSure=false 虚笔 → 同色虚线）。meta 数组下标 = 笔序号，startIndex = 笔序号 * 2。
    if (result.bi.length > 0) {
      const biPoints: Array<{ timestamp: number; value: number }> = []
      const biMeta: ChanBiMeta[] = []
      for (const b of result.bi) {
        biMeta.push({ startIndex: biPoints.length, isSure: b.is_sure })
        biPoints.push({ timestamp: b.begin.t, value: b.begin.v })
        biPoints.push({ timestamp: b.end.t, value: b.end.v })
      }
      chart.createOverlay({
        name: 'chan_bi',
        lock: true,
        points: biPoints,
        extendData: biMeta,
      })
    }

    // 线段覆盖层：同笔结构；lock=true 禁止拖动
    // kline-unsure-dashed：extendData 元数据同 chan_bi（每条段一项：startIndex + isSure），
    // isSure=false 虚段 → 同色虚线 + 减细线宽。meta 数组下标 = 段序号，startIndex = 段序号 * 2。
    if (result.seg.length > 0) {
      const segPoints: Array<{ timestamp: number; value: number }> = []
      const segMeta: ChanSegMeta[] = []
      for (const s of result.seg) {
        segMeta.push({ startIndex: segPoints.length, isSure: s.is_sure })
        segPoints.push({ timestamp: s.begin.t, value: s.begin.v })
        segPoints.push({ timestamp: s.end.t, value: s.end.v })
      }
      chart.createOverlay({
        name: 'chan_seg',
        lock: true,
        points: segPoints,
        extendData: segMeta,
      })
    }

    // 中枢覆盖层：每个中枢 4 个角点，extendData 存 meta；lock=true 禁止拖动
    const allZs = [
      ...result.zs.map((z) => ({ z, level: 'bi' as const })),
      ...result.seg_zs.map((z) => ({ z, level: 'seg' as const })),
    ]
    if (allZs.length > 0) {
      const zsPoints: Array<{ timestamp: number; value: number }> = []
      const zsMeta: Array<{ level: 'bi' | 'seg'; startIndex: number }> = []
      allZs.forEach(({ z, level }) => {
        const startIndex = zsPoints.length
        // 4 角：左上(begin,high) 右上(end,high) 右下(end,low) 左下(begin,low)
        zsPoints.push({ timestamp: z.begin_t, value: z.high })
        zsPoints.push({ timestamp: z.end_t, value: z.high })
        zsPoints.push({ timestamp: z.end_t, value: z.low })
        zsPoints.push({ timestamp: z.begin_t, value: z.low })
        zsMeta.push({ level, startIndex })
      })
      chart.createOverlay({
        name: 'chan_zs',
        lock: true,
        points: zsPoints,
        extendData: zsMeta,
      })
    }
  }

  // 买卖点 + 虚拟买卖点覆盖层（kline-chart-change D5/D6）：同批重建
  //（共存左右排布需要同时拿到双方标记），meta 携带所在 K 线 high/low、
  // 同 bar 同向堆叠序号与共存 x 偏移
  rebuildBspOverlays()

  // BOLL 副图蜡烛柱（sub_candle）同步重建（syncSubCandle 内部先清后建）
  syncSubCandle()
}

/**
 * 主题切换应用（任务 6.3）：全局样式 + 全部覆盖层重建 + 副图指标样式重放。
 * - setStyles：网格/轴/十字光标/蜡烛语义色（涨跌不变，主题色随换）；
 * - rebuildAllOverlays：笔/段/中枢/买卖点/sub_candle 按新 palette 重绘；
 * - applySubIndicatorStyles：MACD 平盘中性灰等随主题色重新 override
 *   （MA 线色是用户配置，刻意不在此重放，主题不得覆盖用户色）。
 */
function applyThemeToChart(): void {
  if (!chart) return
  chart.setStyles(getChartStyles(themeStore.theme))
  rebuildAllOverlays()
  applySubIndicatorStyles()
}

/** 重放副图指标样式（仅主题相关色，如 MACD noChangeColor 中性灰） */
function applySubIndicatorStyles(): void {
  if (!chart) return
  for (const [name, paneId] of subPaneMap) {
    const create = indicatorCreate(name)
    chart.overrideIndicator(typeof create === 'string' ? { name: create } : create, paneId)
  }
}

/** 应用 K 线数据 + 缠论覆盖层 */
function applyResult(result: ChanResult): void {
  if (!chart) return

  // 记录当前数据与 code（虚拟买卖点异步到达后据此重建 bsp overlay，防串号）
  lastResult = result
  appliedCode = props.code ?? ''

  // 标记首屏加载中，阻止 applyNewData 触发的 Backward 增量回调
  initialLoadDone = false

  const klines: KLineData[] = result.klines.map((k) => ({
    timestamp: k.timestamp,
    open: k.open,
    high: k.high,
    low: k.low,
    close: k.close,
    volume: k.volume,
  }))
  chart.applyNewData(klines)

  // 图例数据源：result.klines 全量喂入（prevClose 本地推导基线；kline-chart-change 5.1）
  setLegendSeries(result.klines)

  // applyNewData 后首屏加载完成，后续增量加载可正常触发
  initialLoadDone = true

  // 覆盖层统一重建路径（笔/段/中枢/买卖点/虚拟买卖点/sub_candle，任务 6.3）
  rebuildAllOverlays()

  // 重放均线配置：applyNewData/pane 重建后保持主图 MA 与量均线为当前配置（kline-chart-change 1.2）
  applyMainMa()
  applyVolMa()
  scheduleVolBtnUpdate()
}

/** 初始化 chart 实例 */
function initChart(): void {
  if (!chartRef.value) return
  // 注册覆盖层（须在 init 之前）
  registerAllChanOverlays()
  // 自定义 VOL（同名覆盖内置，量柱红空心绿实心）与 sub_candle（BOLL 副图蜡烛）注册，
  // 须在 init 之前（kline-chart-change D4 / 任务 2.2、2.3）
  registerVolIndicator()
  registerSubCandleOverlay()
  chart = init(chartRef.value)
  if (!chart) return

  // 主题样式工厂（kline-chart-change 6.3）：暗色 = 原硬编码 setStyles 逐字段迁移，
  // 明亮 = 浅底/深轴字/浅网格；涨跌语义色两套不变。主题切换走 theme watch 重设。
  chart.setStyles(getChartStyles(themeStore.theme))

  // 增量加载 data loader（任务5.3：拖到最早端触发 getBars('backward')）
  // design.md D4: 缠论全量返回，增量加载只针对 K 线
  chart.setLoadDataCallback(async ({ type, data, callback }) => {
    // 首屏加载期间不触发增量加载，避免 applyNewData 导致的重复请求
    if (!initialLoadDone) return
    // 只有向前/向后滚动才触发增量加载，初始化时不触发
    if (type === LoadDataType.Init) return
    if (!props.code || !props.period) return
    try {
      // 使用当前数据中最早的 timestamp 作为分页游标
      const earliest = data?.timestamp ?? 0
      const result = await getKLine(props.code, props.period, earliest)
      if (!result.klines || result.klines.length === 0) {
        callback([])
        return
      }
      const extra: KLineData[] = result.klines.map((k) => ({
        timestamp: k.timestamp,
        open: k.open,
        high: k.high,
        low: k.low,
        close: k.close,
        volume: k.volume,
      }))
      callback(extra)
      // 增量加载的更早 K 线并入图例序列（悬停读数/前收覆盖扩展后的数据，kline-chart-change 5.1）
      mergeLegendSeries(result.klines)
      // 增量加载后重建 BOLL 副图蜡烛柱（BOLL 指标会随数据自动重算，蜡烛需同步）
      syncSubCandle()
    } catch {
      callback([])
    }
  })

  // 主图均线：按 chartConfig 配置挂 candle_pane（默认 5/10/20/60，kline-chart-change 1.2）
  applyMainMa()

  // 买卖点阶梯 hover 钩子注入（bsp-ladder-change D5）：chan_bsp figure 命中 → 浮层
  setChanBspHoverHooks({
    onEnter: (meta, pos) => showBspLadderTip(meta, pos.x, pos.y),
    onLeave: () => hideBspLadderTip(),
  })

  // 图例订阅：onCrosshairChange + 容器 mouseleave（悬停/回退最新，kline-chart-change 5.1）
  if (chartRef.value) {
    attachLegend(chart, chartRef.value)
  }
}

/**
 * 副图指标创建参数：MACD 柱体覆盖为「0 轴上红（涨）、0 轴下绿（跌）」，
 * 与主图红涨绿跌一致——klinecharts 内置 MACD 默认绿涨红跌（0 轴下是红色）。
 * VOL 创建时携带量均线天数配置（kline-chart-change 1.3，避开 create/override 的异步竞态），
 * 柱体样式由自定义 VOL 注册（volIndicator.ts）承担；BOLL 走 create-time 包装。
 * 其余指标（RSI/KDJ 等）直接用注册名，走默认样式。
 */
function indicatorCreate(name: string): string | IndicatorCreate {
  if (name === 'MACD') {
    // 涨跌语义色 + 平盘中性色取 palette（任务 6.3）；主题切换后经
    // applySubIndicatorStyles 重新 override，中性灰随主题更新
    const pal = getChanPalette()
    return {
      name,
      styles: {
        bars: [
          {
            style: PolygonType.Fill,
            borderStyle: LineType.Solid,
            borderSize: 1,
            borderDashedValue: [2, 2],
            upColor: pal.rise,
            downColor: pal.fall,
            noChangeColor: pal.neutral,
          },
        ],
      },
    }
  }
  if (name === 'VOL') {
    return { name, calcParams: chartConfig.volMA.map((v) => v.days) }
  }
  if (name === 'BOLL') {
    // create-time 包装：shouldOhlc=false 关闭库内置 OHLC 标记（避免与 sub_candle
    // 双重蜡烛），并以不可见 hi/lo 极值线撑开量程（kline-chart-change D4 / 任务 2.3）
    return createBollIndicator()
  }
  return name
}

/** 添加副图指标（VOL/MACD/BOLL/RSI/KDJ） */
function addSubIndicator(name: string): void {
  if (!chart) return
  if (subPaneMap.has(name)) return
  const paneId = `${PANE_PREFIX}${name.toLowerCase()}`
  chart.createIndicator(indicatorCreate(name), false, { id: paneId, height: SUB_PANE_HEIGHT })
  subPaneMap.set(name, paneId)
  // BOLL 副图创建后挂 sub_candle 蜡烛柱（kline-chart-change 2.3）
  if (name === 'BOLL') syncSubCandle()
  scheduleVolBtnUpdate()
}

/** 移除副图指标 */
function removeSubIndicator(name: string): void {
  if (!chart) return
  const paneId = subPaneMap.get(name)
  if (!paneId) return
  chart.removeIndicator(paneId)
  subPaneMap.delete(name)
  // BOLL 副图移除后清掉 sub_candle 蜡烛柱（kline-chart-change 2.3）
  if (name === 'BOLL') syncSubCandle()
  scheduleVolBtnUpdate()
}

/** 同步副图指标列表（增删） */
function syncSubIndicators(names: string[]): void {
  // 移除不在新列表中的
  for (const key of Array.from(subPaneMap.keys())) {
    if (!names.includes(key)) removeSubIndicator(key)
  }
  // 添加新出现的
  for (const name of names) {
    if (!subPaneMap.has(name)) addSubIndicator(name)
  }
  scheduleVolBtnUpdate()
}

onMounted(() => {
  initChart()
  if (props.result) {
    applyResult(props.result)
  }
  // 容器尺寸变化时自动重绘（折叠左侧面板 / 窗口缩放）
  // 页面缓存（design.md D10）：KeepAlive 失活时容器被移入 display:none 区域，
  // 观察到 0×0——此时 resize() 会经 _measurePaneHeight 把副图 pane 的固定高度
  // 永久改写为 0，复活后只能钳回 minHeight(30px)、主图吞掉差值 → 排版错乱。
  // 故 0 尺寸事件一律忽略；隐藏期间图表保持失活前的尺寸与布局。
  if (chartRef.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect
      if (!rect || rect.width === 0 || rect.height === 0) return
      chart?.resize()
      scheduleVolBtnUpdate()
    })
    resizeObserver.observe(chartRef.value)
  }
})

// 页面缓存复活（design.md D10）：按创建时的固定高度逐个断言副图 pane
// （任何隐藏期测量路径把高度压扁后，这里都可恢复），再按当前可见尺寸整体重排
onActivated(() => {
  if (!chart) return
  for (const paneId of subPaneMap.values()) {
    chart.setPaneOptions({ id: paneId, height: SUB_PANE_HEIGHT })
  }
  chart.resize()
  scheduleVolBtnUpdate()
})

watch(
  () => props.result,
  (result) => {
    if (!chart) return
    if (!result) {
      empty.value = true
      loading.value = false
      initialLoadDone = false // 切换股票期间禁止增量加载
      lastResult = null // 虚拟买卖点重建的数据基线一并清空
      appliedCode = ''
      setLegendSeries([]) // 图例数据源清空（字段行隐藏、现价行回退报价，kline-chart-change 5.4）
      clearChanOverlays() // 加载失败/无数据时清掉上一周期的缠论标注（含 chan_vbsp）
      clearSubCandle() // 同步清掉 BOLL 副图蜡烛柱（任务 2.3）
      return
    }
    loading.value = false
    empty.value = result.klines.length === 0
    applyResult(result)
  },
)

// 均线配置变更 → 即时应用到图表（弹窗确认写 store 后触发；kline-chart-change 1.2/1.3）
watch(
  () => chartConfig.mainMA,
  () => applyMainMa(),
  { deep: true },
)
watch(
  () => chartConfig.volMA,
  () => applyVolMa(),
  { deep: true },
)

// 主题切换 → 全局样式 + 覆盖层重建 + 副图指标样式重放（kline-chart-change 6.3）。
// Topnav toggle() 写 store 后同步 <html data-theme>，overlay palette 绘制时读同一属性。
watch(
  () => themeStore.theme,
  () => applyThemeToChart(),
)

// 监控数据接入（kline-chart-change D6 / 任务 4.1）：code 变化时异步拉取虚拟买卖点，
// 不阻塞图表渲染；数据到达后仅重建买卖点 overlay（不重放整图）
watch(
  () => props.code,
  (code) => {
    // fire-and-forget：load() 内部消化异常并做竞态防护（快速切 code 丢弃过期响应）
    void loadVirtualBsp(code ?? '')
  },
  { immediate: true },
)
watch(virtualBsp, () => {
  rebuildBspOverlays()
})

onBeforeUnmount(() => {
  // 阶梯 hover 钩子移除（bsp-ladder-change D5）
  setChanBspHoverHooks(null)
  hideBspLadderTip()
  // 图例订阅清理（subscribeAction / mouseleave；kline-chart-change 5.1）
  detachLegend()
  resizeObserver?.disconnect()
  resizeObserver = null
  if (chart) {
    dispose(chart)
    chart = null
  }
})

defineExpose({
  resize: () => chart?.resize(),
  addSubIndicator,
  removeSubIndicator,
  syncSubIndicators,
})
</script>

<style scoped>
.kline-chart-wrap {
  position: relative;
  width: 100%;
  height: 100%;
  background: var(--bg-chart);
  border-radius: var(--r-md);
  overflow: hidden;
}
.kline-chart-el {
  width: 100%;
  height: 100%;
}
.kline-chart-loading,
.kline-chart-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-disabled);
  font-size: 13px;
  background: var(--bg-chart);
  z-index: 2;
}

/* 量均线配置按钮：绝对定位浮层，贴 VOL 副图绘图区右上角（kline-chart-change D2） */
.vol-config-btn {
  position: absolute;
  z-index: 3;
  width: 22px;
  height: 22px;
  display: grid;
  place-items: center;
  border-radius: var(--r-sm);
  border: 1px solid var(--border-base);
  background: color-mix(in srgb, var(--bg-surface) 82%, transparent);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}
.vol-config-btn:hover {
  color: var(--accent-hover);
  border-color: var(--accent-base);
  background: var(--bg-surface-hover);
}
.vol-config-btn :deep(.el-icon) {
  width: 13px;
  height: 13px;
}

/* 买卖点确认阶梯 hover 说明卡（bsp-ladder-change D5 / 任务 3.4）：
   全部走 design.css 令牌，明暗主题随 <html data-theme> 自动切换 */
.bsp-ladder-tip {
  position: absolute;
  z-index: 4;
  width: 300px;
  padding: 10px 12px;
  border-radius: var(--r-md);
  border: 1px solid var(--border-strong);
  background: color-mix(in srgb, var(--bg-surface) 96%, transparent);
  box-shadow: var(--shadow-popover);
  pointer-events: none;
  font-size: 12px;
  line-height: 1.5;
}
.bsp-ladder-tip__head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border-base);
}
.bsp-ladder-tip__badge {
  display: inline-flex;
  align-items: center;
  height: 18px;
  padding: 0 8px;
  border-radius: var(--r-full);
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
.bsp-ladder-tip__badge.badge--rise { background: var(--rise-dim); color: var(--rise); }
.bsp-ladder-tip__badge.badge--warning { background: var(--warning-dim); color: var(--warning); }
.bsp-ladder-tip__badge.badge--info { background: var(--accent-dim); color: var(--accent-hover); }
.bsp-ladder-tip__badge.badge--default { background: var(--bg-surface-hover); color: var(--text-secondary); }
.bsp-ladder-tip__dir {
  font-size: 12px;
  font-weight: 600;
}
.bsp-ladder-tip__types {
  margin-left: auto;
  color: var(--text-secondary);
  font-size: 11px;
}
.bsp-ladder-tip__rows {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px 0;
}
.bsp-ladder-tip__row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 2px 6px;
  border-radius: var(--r-sm);
  color: var(--text-secondary);
}
.bsp-ladder-tip__row.is-current {
  background: var(--accent-dim);
  color: var(--text-primary);
  font-weight: 600;
}
.bsp-ladder-tip__lv {
  width: 22px;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
  color: var(--text-primary);
}
.bsp-ladder-tip__name {
  flex: 1;
}
.bsp-ladder-tip__pos {
  flex-shrink: 0;
  color: var(--text-secondary);
  font-size: 11px;
}
.bsp-ladder-tip__row.is-current .bsp-ladder-tip__pos {
  color: var(--text-primary);
}
.bsp-ladder-tip__sub {
  padding: 4px 6px;
  color: var(--warning);
  font-size: 11px;
}
.bsp-ladder-tip__note {
  padding-top: 6px;
  border-top: 1px solid var(--border-base);
  color: var(--text-disabled);
  font-size: 11px;
}
</style>
