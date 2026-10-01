// useVirtualBsp.ts — 监控数据 → 虚拟（模拟交易）买卖点（kline-chart-change D6 / 任务 4.1）
// 数据流：code 变化 → GET /api/monitor + /api/monitor/completed（后端无 code 查询参数，
// 前端按 code 过滤，design.md D6）→ mapMonitorToVirtualBsp 映射成图上标记点。
// 映射规则（任务 4.1）：
// - monitoring 行 → 一个买入点 (bsp_date, bsp_price)
// - completed 行 → 买入点 (bsp_date, bsp_price) + 卖出点 (end_date, end_price)
// - 无行 → 空数组（不产生虚拟标记）
// 拉取不阻塞图表渲染：KLineChart 在 code 变化时 fire-and-forget 调 load()，
// 数据到达后再重建买卖点 overlay。
import { ref } from 'vue'
import { getMonitorList, getCompletedList } from '@/api/modules/monitor'
import type { MonitorItem, CompletedItem } from '@/api/types'

/** 虚拟买卖点（模拟交易记录 → 图上标记） */
export interface VirtualBspPoint {
  /** 原始时间（bsp_date / end_date，epoch-ms，可能含时分） */
  t: number
  /** 价位（买入价 / 卖出价） */
  v: number
  /** true = 模拟买入，false = 模拟卖出 */
  isBuy: boolean
}

/** 虚拟买卖点状态：code 标注数据归属，供绘制端与当前图表 code 防串号比对 */
export interface VirtualBspState {
  code: string
  items: VirtualBspPoint[]
}

/**
 * 监控数据 → 虚拟买卖点映射（唯一映射入口）。
 * 后端暂无 code 参数，此处按 code 过滤；无匹配行返回空数组（不产生标记）。
 */
export function mapMonitorToVirtualBsp(
  monitoring: MonitorItem[],
  completed: CompletedItem[],
  code: string,
): VirtualBspPoint[] {
  const items: VirtualBspPoint[] = []
  // 监控中 → 一个模拟买入点
  for (const row of monitoring) {
    if (row.code !== code) continue
    if (!Number.isFinite(row.bsp_date) || !Number.isFinite(row.bsp_price)) continue
    items.push({ t: row.bsp_date, v: row.bsp_price, isBuy: true })
  }
  // 已完成 → 模拟买入点 + 模拟卖出点
  for (const row of completed) {
    if (row.code !== code) continue
    if (Number.isFinite(row.bsp_date) && Number.isFinite(row.bsp_price)) {
      items.push({ t: row.bsp_date, v: row.bsp_price, isBuy: true })
    }
    if (Number.isFinite(row.end_date) && Number.isFinite(row.end_price)) {
      items.push({ t: row.end_date, v: row.end_price, isBuy: false })
    }
  }
  return items
}

const DAY_MS = 86400000

/** 本地日历日 key（YYYYMMDD 整数），用于把含时分的时间戳吸附到日线 bar */
function dayKey(ts: number): number {
  const d = new Date(ts)
  return d.getFullYear() * 10000 + (d.getMonth() + 1) * 100 + d.getDate()
}

/**
 * 把时间戳吸附到最近的 K 线 bar（任务 4.1：monitor 时间戳含时分，与 bar 的
 * time_key 不精确相等，须按本地日历日匹配）：
 * 1) 同日历日的 bar 中取时间最近者（日线唯一；分钟级多根取最近）；
 * 2) 无同日 bar（周末/节假日）→ 2 天内时间最近的 bar；
 * 3) 仍无 → null（记录不在可视序列内，不产生标记）。
 * 返回 bar 的 timestamp。
 */
export function findAnchorBarTimestamp(
  klines: Array<{ timestamp: number }>,
  ts: number,
): number | null {
  if (klines.length === 0) return null
  const key = dayKey(ts)
  let best: number | null = null
  let bestDist = Number.POSITIVE_INFINITY
  // 优先同日历日
  for (const k of klines) {
    if (dayKey(k.timestamp) !== key) continue
    const d = Math.abs(k.timestamp - ts)
    if (d < bestDist) {
      bestDist = d
      best = k.timestamp
    }
  }
  if (best !== null) return best
  // 回退：2 天内最近 bar（覆盖记录时间落在非交易日的场景）
  bestDist = 2 * DAY_MS + 1
  for (const k of klines) {
    const d = Math.abs(k.timestamp - ts)
    if (d < bestDist) {
      bestDist = d
      best = k.timestamp
    }
  }
  return best
}

/**
 * 虚拟买卖点数据源：按 code 异步拉取监控记录并映射。
 * 竞态防护：内部 loadSeq 丢弃过期响应（快速切换 code 时旧响应不覆盖新数据）。
 */
export function useVirtualBsp() {
  const state = ref<VirtualBspState>({ code: '', items: [] })
  let loadSeq = 0

  /** 拉取指定 code 的虚拟买卖点；失败置空并记录（内部消化异常，不向外抛） */
  async function load(code: string): Promise<void> {
    const seq = ++loadSeq
    if (!code) {
      state.value = { code: '', items: [] }
      return
    }
    try {
      const [monitoring, completed] = await Promise.all([getMonitorList(), getCompletedList()])
      // 快速切换 code 后的过期响应，丢弃
      if (seq !== loadSeq) return
      const items = mapMonitorToVirtualBsp(monitoring, completed, code)
      state.value = { code, items }
    } catch (e) {
      if (seq !== loadSeq) return
      console.warn('[useVirtualBsp.load] 监控数据加载失败，清空虚拟买卖点', {
        code,
        error: e instanceof Error ? e.message : String(e),
      })
      state.value = { code, items: [] }
    }
  }

  return { state, load }
}
