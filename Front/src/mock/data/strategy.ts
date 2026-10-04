import type {
  StrategyDefinition,
  StrategyInstance,
  StrategySignalRow,
} from '@/api/types'
import { stocks } from './stocks'

/**
 * 策略信号 mock 数据（strategy-signal-page design D5 / 任务 5.2）：
 * 2 个策略定义（量价/趋势分组）× 各 1-2 实例 × 20-40 条信号（states 各若干），
 * 驱动 /strategy 页 schema 驱动渲染（侧栏树 / 实例表单 / 状态着色 / 私有列）。
 */

/** 确定性伪随机（种子固定，每次渲染一致，风格同 data/kline.ts） */
function mulberry32(seed: number) {
  return function () {
    seed |= 0
    seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** 本地时区 YYYY-MM-DD（与 signal_date / 日期筛选参数同格式） */
function dateStr(ts: number): string {
  const d = new Date(ts)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// ---------------------------------------------------------------------------
// 策略定义（代码注册语义：mock 用静态常量，用户不可增删）
// ---------------------------------------------------------------------------

/** 定义一：放量首板回调（vol_breakout_pullback）— states: watching/triggered/expired/running */
const volBreakoutDef: StrategyDefinition = {
  id: 'vol_breakout_pullback',
  name: '放量首板回调',
  group_name: '量价策略',
  sort: 0,
  params_schema: [
    { key: 'pullback_days', label: '回调天数上限', type: 'int', default: 5, min: 1, max: 20 },
    { key: 'vol_ratio', label: '放量倍数', type: 'float', default: 2.0, min: 1.0, max: 10.0 },
    { key: 'shrink_threshold', label: '回调量缩阈值', type: 'float', default: 0.6, min: 0.1, max: 1.0 },
  ],
  states: [
    { value: 'watching', label: '回调中', color: 'info' },
    { value: 'triggered', label: '已触发', color: 'danger' },
    { value: 'expired', label: '已失效', color: 'warning' },
    { value: 'running', label: '已启动', color: 'success' },
  ],
  columns: [
    { key: 'first_board_date', label: '首板日', type: 'date' },
    { key: 'pullback_days_used', label: '回调天数', type: 'int' },
    { key: 'vol_ratio', label: '放量倍数', type: 'float' },
  ],
  instances: [],
}

/** 定义二：均线趋势（ma_trend）— states: forming/broken */
const maTrendDef: StrategyDefinition = {
  id: 'ma_trend',
  name: '均线趋势',
  group_name: '趋势策略',
  sort: 1,
  params_schema: [
    { key: 'fast_period', label: '快线周期', type: 'int', default: 20, min: 5, max: 60 },
    { key: 'slow_period', label: '慢线周期', type: 'int', default: 60, min: 30, max: 250 },
  ],
  states: [
    { value: 'forming', label: '形成中', color: 'info' },
    { value: 'broken', label: '已破位', color: 'danger' },
  ],
  columns: [
    { key: 'golden_cross_date', label: '金叉日', type: 'date' },
    { key: 'trend_strength', label: '趋势强度', type: 'float' },
  ],
  instances: [],
}

// ---------------------------------------------------------------------------
// 实例（不可变：mock 内存态，实例数组随定义维护）
// ---------------------------------------------------------------------------

const volInst1: StrategyInstance = {
  id: 1,
  label: '回调5日',
  params: { pullback_days: 5, vol_ratio: 2.0, shrink_threshold: 0.6 },
  enabled: true,
  signal_count: 0, // 生成信号后回填
}

const volInst2: StrategyInstance = {
  id: 2,
  label: '回调3日',
  params: { pullback_days: 3, vol_ratio: 2.5, shrink_threshold: 0.5 },
  enabled: true,
  signal_count: 0,
}

const maInst1: StrategyInstance = {
  id: 3,
  label: '20/60 日线',
  params: { fast_period: 20, slow_period: 60 },
  enabled: true,
  signal_count: 0,
}

volBreakoutDef.instances.push(volInst1, volInst2)
maTrendDef.instances.push(maInst1)

/** 全部策略定义（含实例树） */
export const strategyDefinitions: StrategyDefinition[] = [volBreakoutDef, maTrendDef]

/** 定义注册表查找 */
export function findDefinition(strategyId: string): StrategyDefinition | undefined {
  return strategyDefinitions.find((d) => d.id === strategyId)
}

/** 实例查找（跨定义） */
export function findInstance(instanceId: number): { def: StrategyDefinition; inst: StrategyInstance } | undefined {
  for (const def of strategyDefinitions) {
    const inst = def.instances.find((i) => i.id === instanceId)
    if (inst) return { def, inst }
  }
  return undefined
}

// ---------------------------------------------------------------------------
// 信号生成（20-40 条：vol_breakout 两实例各 16-24 条 + ma_trend 8 条，
// 日期近 30 天、payload 含私有列字段、signal_date 与首板日/金叉日语义对齐）
// ---------------------------------------------------------------------------

/** 生成某实例的信号集：股票取自 stocks，states 按声明轮转保证各状态若干 */
function genSignals(def: StrategyDefinition, inst: StrategyInstance, count: number, seedOffset: number): StrategySignalRow[] {
  const rand = mulberry32(inst.id * 97 + seedOffset)
  const rows: StrategySignalRow[] = []
  for (let i = 0; i < count; i++) {
    const stock = stocks[(i * 3 + inst.id * 5) % stocks.length]
    const state = def.states[i % def.states.length].value
    const r = rand()
    // 信号日期：近 30 天内（确定性伪随机）
    const signalTs = Date.now() - Math.floor(r * 30) * 86400000
    const signalDate = dateStr(signalTs)
    // 买点为主（放量首板回调 / 均线金叉均为做多语义），少量卖点
    const isBuy = i % 7 !== 6
    const entry = +(stock.price * (0.92 + r * 0.1)).toFixed(2)
    const stop = +(entry * (0.9 + r * 0.04)).toFixed(2)
    // payload：私有列字段按定义 columns 声明的 key 填充
    const payload: Record<string, number | string> = {}
    if (def.id === 'vol_breakout_pullback') {
      // 首板日 = 信号日前推若干交易日（回调窗口语义）
      const boardTs = signalTs - (3 + Math.floor(r * 6)) * 86400000
      payload.first_board_date = dateStr(boardTs)
      payload.pullback_days_used = Math.floor(r * (inst.params.pullback_days || 5)) + 1
      payload.vol_ratio = +(1.8 + r * 1.5).toFixed(2)
    } else {
      // 金叉日 = 信号日前推若干交易日
      const crossTs = signalTs - (5 + Math.floor(r * 10)) * 86400000
      payload.golden_cross_date = dateStr(crossTs)
      payload.trend_strength = +(0.2 + r * 0.8).toFixed(2)
    }
    rows.push({
      code: stock.code,
      name: stock.name,
      industries: stock.industries,
      signal_date: signalDate,
      state,
      is_buy: isBuy,
      entry_ref_price: entry,
      stop_ref_price: stop,
      payload,
    })
  }
  return rows
}

/** 内存信号池（按实例隔离；spec：信号挂实例，跨实例互不可见） */
export const strategySignals: Record<number, StrategySignalRow[]> = {
  1: genSignals(volBreakoutDef, volInst1, 24, 11),
  2: genSignals(volBreakoutDef, volInst2, 16, 23),
  3: genSignals(maTrendDef, maInst1, 8, 37),
}

// 信号计数回填（侧栏 badge 与列表 total 用同一口径）
for (const def of strategyDefinitions) {
  for (const inst of def.instances) {
    inst.signal_count = (strategySignals[inst.id] || []).length
  }
}

// ---------------------------------------------------------------------------
// 实例管理（内存态，风格对齐 data/screener.ts 的 addStrategy 模式）
// ---------------------------------------------------------------------------

let nextInstanceId = 100
/** 新建实例：params 按定义 params_schema 校验（min/max 拒绝抛错 → handler 转 422） */
export function addInstance(strategyId: string, label: string, params: Record<string, number>): StrategyInstance {
  const def = findDefinition(strategyId)
  if (!def) throw new Error(`策略定义 ${strategyId} 不存在`)
  const name = label.trim()
  if (!name) throw new Error('实例名不能为空')
  // 参数校验（design D1：非法值抛错；后端 422 detail 同语义）
  for (const schema of def.params_schema) {
    const v = params[schema.key]
    if (v == null || !Number.isFinite(v)) {
      throw new Error(`参数「${schema.label}」缺失或不是数值`)
    }
    if (v < schema.min || v > schema.max) {
      throw new Error(`参数「${schema.label}」超出范围 [${schema.min}, ${schema.max}]`)
    }
  }
  const inst: StrategyInstance = {
    id: nextInstanceId++,
    label: name,
    params: { ...params },
    enabled: true,
    signal_count: 0,
  }
  def.instances.push(inst)
  // 创建即全量回算（design D2）：mock 侧生成一批信号（数量按定义种子派生）
  strategySignals[inst.id] = genSignals(def, inst, 6 + (inst.id % 5), inst.id)
  inst.signal_count = strategySignals[inst.id].length
  return inst
}

/** 删除实例（级联删信号） */
export function removeInstance(id: number): boolean {
  for (const def of strategyDefinitions) {
    const idx = def.instances.findIndex((i) => i.id === id)
    if (idx >= 0) {
      def.instances.splice(idx, 1)
      delete strategySignals[id]
      return true
    }
  }
  return false
}

/** 启停实例 */
export function setInstanceEnabled(id: number, enabled: boolean): boolean {
  const found = findInstance(id)
  if (!found) return false
  found.inst.enabled = enabled
  return true
}

/** 手动补算（mock：追加 1-2 条信号模拟增量扫描结果） */
export function scanInstanceSignals(id: number): { success: boolean; message: string } {
  const found = findInstance(id)
  if (!found) return { success: false, message: `实例 ${id} 不存在` }
  if (!found.inst.enabled) return { success: false, message: '实例已停用，不参与扫描' }
  const before = (strategySignals[id] || []).length
  const extra = genSignals(found.def, found.inst, 2, Date.now() % 1000)
  strategySignals[id] = [...(strategySignals[id] || []), ...extra]
  found.inst.signal_count = strategySignals[id].length
  return { success: true, message: `补算完成：新增 ${strategySignals[id].length - before} 条信号` }
}
