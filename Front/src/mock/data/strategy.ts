import type {
  StrategyDefinition,
  StrategyTask,
  StrategySignalRow,
  StrategyTaskStockResult,
  StrategyTaskDetail,
  StrategyParamSchema,
  BEventRow,
} from '@/api/types'
import { stocks, findStock } from './stocks'
import { watchFolders } from './watchlist'
import { mockUsers, userIdFromRequest } from './auth'

/**
 * 策略任务 mock 数据（strategy-task-redesign design D1/D5 / 任务 4.1 +
 * vp-entry-strategy-integration 任务 4.2）：
 * 3 个策略定义（量价分组：vol_breakout_pullback + vp_entry；趋势分组：ma_trend，
 * detail_schema 声明不同 → 任务详情风格不同）× 任务（manual/watchlist/bsp_query/all
 * 四种范围、test/persistent、各状态、混合参数版本信号）× 逐股结果（显式范围任务才有）
 * + vp_entry 定义（首个 enum 参数 vol_gate 样例），驱动 /strategy 页任务树 / 任务列表 /
 * 创建编辑弹窗 / detail_blocks 渲染器联调。
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
// 策略定义（代码注册语义：mock 用静态常量，用户不可增删）；
// detail_schema 声明不同（design D5）→ 各策略任务详情页风格不同：
// - vol_breakout_pullback：[summary, per_stock, signals, kv(首板统计)]
// - ma_trend：[summary, signals, timeline]
// - vp_entry：[summary, per_stock, signals, kv(基底特征统计)]
// ---------------------------------------------------------------------------

/** 定义一：放量启动回调（vol_breakout_pullback）— states: watching/triggered/expired/running；
 *  策略名与 a_pct_min 参数对齐后端 strategy-signal-outcome D11（原名「放量首板回调」）；
 *  params_schema/columns 对齐后端 strategy-volume-breakout-pullback D8/D7
 *  （13/4/2.3 默认值、三新参数、删 volume_shrink_max、A/B 三值合并列 + B 弹窗） */
const volBreakoutDef: StrategyDefinition = {
  id: 'vol_breakout_pullback',
  name: '放量启动回调',
  group_name: '量价策略',
  sort: 0,
  params_schema: [
    {
      key: 'pullback_max_days', label: '回调天数上限', type: 'int', default: 13, min: 1, max: 20,
      desc: '启动日之后最多观察多少个交易日的回调，B 级买点必须落在这个窗口内，窗口走完还没有任何 B 级确认就判定失效。调高：愿意等更久、能捕捉回调慢的形态但资金等待期变长；调低：只接受快速企稳的形态，信号更少但更干脆。例：设 8 时第 9 天才出现 B3 买点的信号会被漏掉。',
    },
    {
      key: 'pullback_min_days', label: '回调天数下限', type: 'int', default: 4, min: 0, max: 19,
      desc: '最早出现的 B 级买点距启动日至少多少个交易日，不足则视为回调不充分、信号不成立。调高：要求回调更扎实、信号更少；调低：不设下限，启动次日就出买点也算。例：设 6 时第 4 天出现 B1 的信号会被淘汰。',
    },
    {
      key: 'volume_ratio_min', label: '启动放量倍数下限', type: 'float', default: 2.3, min: 1.0, max: 10.0, precision: 1, step: 0.1,
      desc: '启动日成交量要达到前 20 日平均量的几倍。调高：只认放量大、假启动少，但信号明显变少；调低：信号多但容易混入普通波动的假启动。例：设 3.0 时多数日子平淡的股票难有信号；设 1.5 时几乎每次温和放量都会报信号。',
    },
    {
      // strategy-signal-outcome D11：涨幅门槛参数化（默认 5%）
      key: 'a_pct_min', label: '启动日涨幅门槛', type: 'float', default: 0.05, min: 0.03, max: 0.15, precision: 2, step: 0.01,
      desc: '启动日收盘涨幅至少要达到多少。调高：只认涨得猛的启动（如 0.098 只抓接近涨停的大阳线），信号少而强；调低：涨幅温和也算启动，信号多但更弱。例：0.05 时涨 6% 的日子符合条件；0.098 时同一天不再符合。',
    },
    {
      key: 'pullback_pct_max', label: '回调涨幅门阈值', type: 'float', default: 0.04, min: 0.02, max: 0.1, precision: 2, step: 0.01,
      desc: 'B 级买点确认之前，回调期间单日收盘涨幅的上限，超过就判失效（回调中不该出现大涨）。调高：容忍回调中反弹更猛；调低：要求回调走势更平稳。例：设 0.06 时回调中某天涨 5% 仍可继续观察；默认 0.04 时同一天信号失效。',
    },
    {
      key: 'volume_trend_ratio', label: '量能趋势门倍数', type: 'float', default: 1.1, min: 1.05, max: 2.0, precision: 2, step: 0.05,
      desc: '启动日第 4 个交易日起，当日 3 日均量超过前 3 日均量的这个倍数就判失效（回调期量能应逐步萎缩）。调高：允许量能波动大一些不易触发；调低：对放量抬升更敏感、淘汰更严格。例：设 1.3 时连续温和放量可存活；默认 1.1 时连续放量抬升即失效。',
    },
    {
      key: 'breakout_vol_ratio', label: '突破量比', type: 'float', default: 0.4, min: 0.2, max: 1.0, precision: 1, step: 0.1,
      desc: 'B 级确认（放量突破回调期高点）要求的当日成交量下限，等于启动日成交量的这个比例。调高：要求突破时放量更足、确认更可靠但更难出现；调低：轻微放量也算突破。例：设 0.6 时缩量创新高不算 B；设 0.25 时基本只要创新高就算。',
    },
  ],
  states: [
    { value: 'watching', label: '回调中', color: 'info' },
    { value: 'triggered', label: '已触发', color: 'danger' },
    { value: 'expired', label: '已失效', color: 'warning' },
    { value: 'running', label: '已启动', color: 'success' },
  ],
  columns: [
    { key: 'pullback_days', label: '回调天数', type: 'int' },
    { key: 'volume_ratio', label: '放量倍数', type: 'float' },
    // A/B 列整合（strategy-volume-breakout-pullback D7）：A 日日期+价格+涨幅
    // 合并为 a_col 三值列；B 列 b_col 同构 + popup 标记（点击弹多 B 事件表）；
    // 「信号日期」列删除（与 A 日冲突，BlockSignals 已不渲染）
    { key: 'a_col', label: 'A日', type: 'date_price_pct', dateKey: 'a_date', priceKey: 'a_close', pctKey: 'a_pct' },
    { key: 'b_col', label: 'B日', type: 'date_price_pct', dateKey: 'b_date', priceKey: 'b_close', pctKey: 'b_day_pct', popup: 'b_events' },
    { key: 'close_5d_price', label: '5日股价', type: 'price_pct', priceKey: 'close_5d', pctKey: 'ret_5d' },
    { key: 'close_10d_price', label: '10日股价', type: 'price_pct', priceKey: 'close_10d', pctKey: 'ret_10d' },
    { key: 'close_15d_price', label: '15日股价', type: 'price_pct', priceKey: 'close_15d', pctKey: 'ret_15d' },
    { key: 'outcome', label: '成功判定', type: 'outcome' },
  ],
  // design D5 v1 声明：[summary, per_stock, signals, kv(绩效准确率统计)]——
  // D12：删首板日分布/平均放量倍数/平均回调天数三个形态统计项，聚焦绩效；
  // 2026-10-15 修订：删 pending_cnt 数据不足数、平均收益随窗口改 5/10/15
  detail_schema: [
    { type: 'summary' },
    { type: 'per_stock' },
    { type: 'signals' },
    {
      type: 'kv',
      title: '绩效统计',
      items: [
        // 绩效准确率统计项（D6：与后端 compute_outcome_kv_stats 键一一对齐；
        // accuracy/avg_ret_* 为小数或 null → fmt 'pct' 百分比渲染、null '--'）
        { key: 'accuracy', label: '准确率', fmt: 'pct' },
        { key: 'success_cnt', label: '成功数', fmt: 'int' },
        { key: 'failed_cnt', label: '失败数', fmt: 'int' },
        { key: 'avg_ret_5d', label: '平均5日收益', fmt: 'pct' },
        { key: 'avg_ret_10d', label: '平均10日收益', fmt: 'pct' },
        { key: 'avg_ret_15d', label: '平均15日收益', fmt: 'pct' },
      ],
    },
  ],
  tasks: [],
}

/** 定义二：均线趋势（ma_trend）— states: forming/broken；detail_schema 用 timeline 块与定义一区分 */
const maTrendDef: StrategyDefinition = {
  id: 'ma_trend',
  name: '均线趋势',
  group_name: '趋势策略',
  sort: 1,
  params_schema: [
    {
      key: 'fast_period', label: '快线周期', type: 'int', default: 20, min: 5, max: 60,
      desc: '均线金叉判定的快线周期（交易日数）',
    },
    {
      key: 'slow_period', label: '慢线周期', type: 'int', default: 60, min: 30, max: 250,
      desc: '均线金叉判定的慢线周期（交易日数），慢线越长趋势过滤越保守',
    },
  ],
  states: [
    { value: 'forming', label: '形成中', color: 'info' },
    { value: 'broken', label: '已破位', color: 'danger' },
  ],
  columns: [
    { key: 'golden_cross_date', label: '金叉日', type: 'date' },
    { key: 'trend_strength', label: '趋势强度', type: 'float' },
  ],
  detail_schema: [
    { type: 'summary' },
    { type: 'signals' },
    { type: 'timeline' },
  ],
  tasks: [],
}

/** 定义三：量价三段式买点（vp_entry）— states: triggered/running/expired；
 *  vol_gate 为首个 enum 参数样例（vp-entry-strategy-integration D4）；
 *  detail_schema [summary, per_stock, signals, kv(基底特征统计)]，无 timeline
 *  （B 日后状态演进由 states 着色承载） */
const vpEntryDef: StrategyDefinition = {
  id: 'vp_entry',
  name: '量价三段式买点',
  group_name: '量价策略',
  sort: 2,
  params_schema: [
    {
      key: 'cv7_max', label: 'CV7 门限', type: 'float', default: 0.25, min: 0.15, max: 0.35, precision: 2, step: 0.01,
      desc: '蓄势期量能要平稳到什么程度（7 天量能波动幅度上限）。调高：容忍量能忽大忽小、蓄势判定更宽松、信号更多；调低：要求量能非常平稳、蓄势形态更扎实但更难出现。例：0.25 时日均量上下波动三成以内的都算蓄势；0.15 时几乎只有极度地量的票才符合。',
    },
    {
      key: 'box_width_max', label: '区间盒宽上限', type: 'float', default: 0.12, min: 0.08, max: 0.18, precision: 2, step: 0.01,
      desc: '蓄势期股价横盘的波动幅度上限（相对均价）。调高：容忍横盘中上下晃得更宽、更容易成箱；调低：要求横得足够窄、形态更标准但更难等到。例：0.12 时箱体上下沿差 12% 以内的通过；0.08 时差 10% 的箱体会被淘汰。',
    },
    {
      key: 'n_max', label: '调整期超时天数', type: 'int', default: 7, min: 4, max: 10,
      desc: '放量启动之后等回踩触发的最长交易日数，超时则淘汰。调高：给回踩更长的窗口、介入机会更多但资金占用更久；调低：节奏更快但容易在启动后洗盘没结束就提前淘汰。例：设 4 时第 5 天才回踩到位的信号被漏掉；设 10 时要接受两周的等待。',
    },
    {
      key: 'stop_loss', label: '止损容忍', type: 'float', default: 0.12, min: 0.05, max: 0.15, precision: 2, step: 0.01,
      desc: '买入后允许的最大回撤比例，跌破即止损。调高：容忍更深的回调、不容易被洗出去但单笔亏损更大；调低：止损快、单笔亏得少但容易被正常波动洗掉。例：0.05 时回撤 6% 就止损出局；0.12 时能扛住 10% 的回调等反弹。',
    },
    {
      // 首个 enum 参数样例：量能门口径开关（均值门 / 逐日严格门）
      key: 'vol_gate', label: '量能门口径', type: 'enum', default: 'mean',
      options: [
        { value: 'mean', label: '均值门' },
        { value: 'strict', label: '逐日严格门' },
      ],
      desc: '蓄势期量能判定的宽严口径。均值门按整个蓄势期的平均量一次判定，信号多；逐日严格门要求每一天量都低于门槛，信号少但更严格。例：某蓄势期里有一天放量、其余地量——均值门仍通过，逐日严格门会淘汰。',
    },
  ],
  states: [
    { value: 'triggered', label: '观察中', color: 'info' },
    { value: 'running', label: '已启动', color: 'success' },
    { value: 'expired', label: '已淘汰', color: 'danger' },
  ],
  columns: [
    { key: 'a_date', label: 'A 日', type: 'date' },
    { key: 'p_date', label: '量能峰日', type: 'date' },
    { key: 'entry_mode', label: '触发方式', type: 'str' },
    { key: 'volume_ratio', label: '放量倍数', type: 'float' },
    { key: 'spring', label: 'Spring', type: 'str' },
    { key: 'drift_bucket', label: '漂移桶', type: 'str' },
    { key: 'wick_box', label: '影线盒宽', type: 'float' },
    { key: 'box_days', label: '蓄势天数', type: 'int' },
    // A/B 点过程与绩效列（strategy-signal-outcome D12 合并列声明：
    // price_pct 单列「价格 | 涨跌幅」，双 key 显式声明；a_date/p_date 已有
    // 列不重复；b_date 保留）
    { key: 'a_price', label: 'A日股价', type: 'price_pct', priceKey: 'a_close', pctKey: 'a_pct' },
    { key: 'b_date', label: 'B点时间', type: 'date' },
    { key: 'b_price', label: 'B日股价', type: 'price_pct', priceKey: 'b_close', pctKey: 'b_day_pct' },
    { key: 'p5', label: '5日股价', type: 'price_pct', priceKey: 'close_5d', pctKey: 'ret_5d' },
    { key: 'p10', label: '10日股价', type: 'price_pct', priceKey: 'close_10d', pctKey: 'ret_10d' },
    { key: 'p15', label: '15日股价', type: 'price_pct', priceKey: 'close_15d', pctKey: 'ret_15d' },
    { key: 'outcome', label: '成功判定', type: 'outcome' },
  ],
  // design D5：[summary, per_stock, signals, kv(基底特征统计 + 绩效准确率)]——无 timeline
  detail_schema: [
    { type: 'summary' },
    { type: 'per_stock' },
    { type: 'signals' },
    {
      type: 'kv',
      title: '基底特征统计',
      items: [
        { key: 'signal_total', label: '信号总数', fmt: 'int' },
        { key: 'minute_ratio', label: '分钟版占比', fmt: 'str' },
        { key: 'daily_ratio', label: '日线版占比', fmt: 'str' },
        { key: 'spring_ratio', label: 'Spring 占比', fmt: 'str' },
        { key: 'drift_dist', label: '漂移三桶分布', fmt: 'str' },
        { key: 'avg_wick_box', label: '平均影线盒宽', fmt: 'float' },
        { key: 'avg_box_days', label: '平均蓄势天数', fmt: 'float' },
        { key: 'avg_a_ret', label: '平均 A 日涨幅', fmt: 'float' },
        { key: 'alive_count', label: '存活信号数', fmt: 'int' },
        // 绩效准确率统计项（D6：与后端 compute_outcome_kv_stats 键一一对齐；
        // 2026-10-15 修订：删 pending_cnt 数据不足数、平均收益随窗口改 5/10/15）
        { key: 'accuracy', label: '准确率', fmt: 'pct' },
        { key: 'success_cnt', label: '成功数', fmt: 'int' },
        { key: 'failed_cnt', label: '失败数', fmt: 'int' },
        { key: 'avg_ret_5d', label: '平均5日收益', fmt: 'pct' },
        { key: 'avg_ret_10d', label: '平均10日收益', fmt: 'pct' },
        { key: 'avg_ret_15d', label: '平均15日收益', fmt: 'pct' },
      ],
    },
  ],
  tasks: [],
}

/** 全部策略定义（含任务树） */
export const strategyDefinitions: StrategyDefinition[] = [volBreakoutDef, maTrendDef, vpEntryDef]

/** 定义注册表查找 */
export function findDefinition(strategyId: string): StrategyDefinition | undefined {
  return strategyDefinitions.find((d) => d.id === strategyId)
}

/** 任务查找（跨定义） */
export function findTask(taskId: number): { def: StrategyDefinition; task: StrategyTask } | undefined {
  for (const def of strategyDefinitions) {
    const task = def.tasks.find((t) => t.id === taskId)
    if (task) return { def, task }
  }
  return undefined
}

// ---------------------------------------------------------------------------
// 任务（内存态：四种范围 × 各状态/形态，覆盖任务列表全操作联调）
// ---------------------------------------------------------------------------

const now = Date.now()

/** 任务一：vol_breakout · manual 范围 · test · done（含 v1/v2 混合参数信号 → 版本归因联调） */
const volTask1: StrategyTask = {
  id: 1,
  strategy_id: 'vol_breakout_pullback',
  label: '回调5日',
  user_group: '首板测试',
  params: { pullback_max_days: 13, pullback_min_days: 4, volume_ratio_min: 2.3, a_pct_min: 0.05, pullback_pct_max: 0.04, volume_trend_ratio: 1.1, breakout_vol_ratio: 0.4 },
  params_version: 2,
  scope_type: 'manual',
  scope_codes: ['sz.000001', 'sh.600036', 'sz.002594', 'sh.600887', 'sz.000651', 'sh.601012'],
  mode: 'test',
  status: 'done',
  progress_scanned: 6,
  progress_total: 6,
  signal_count: 0, // 生成信号后回填
  accuracy: null, // 同上：生成信号后按 outcome 分布回填
  created_by: 'admin',
  created_at: now - 32 * 86400000,
  updated_at: now - 20 * 86400000,
}

/** 任务二：vol_breakout · watchlist 范围快照 · test · paused（编辑与续跑弹窗联调） */
const volTask2: StrategyTask = {
  id: 2,
  strategy_id: 'vol_breakout_pullback',
  label: '回调3日',
  user_group: '首板测试',
  params: { pullback_max_days: 8, pullback_min_days: 3, volume_ratio_min: 2.5, a_pct_min: 0.05, pullback_pct_max: 0.05, volume_trend_ratio: 1.2, breakout_vol_ratio: 0.5 },
  params_version: 1,
  scope_type: 'watchlist',
  scope_codes: ['sh.600519', 'sz.000858', 'sz.000568', 'sh.600809', 'sz.002594'],
  mode: 'test',
  status: 'paused',
  progress_scanned: 3,
  progress_total: 5,
  signal_count: 0,
  accuracy: null,
  created_by: 'trader',
  created_at: now - 15 * 86400000,
  updated_at: now - 2 * 86400000,
}

/** 任务三：vol_breakout · all 全量 · persistent · running（per_stock 块静默隐藏 + 进度轮询联调） */
const volTask3: StrategyTask = {
  id: 5,
  strategy_id: 'vol_breakout_pullback',
  label: '全量首板扫描',
  user_group: '长期任务',
  params: { pullback_max_days: 13, pullback_min_days: 4, volume_ratio_min: 2.3, a_pct_min: 0.05, pullback_pct_max: 0.04, volume_trend_ratio: 1.1, breakout_vol_ratio: 0.4 },
  params_version: 1,
  scope_type: 'all',
  scope_codes: null,
  mode: 'persistent',
  status: 'running',
  progress_scanned: 3218,
  progress_total: 5000,
  signal_count: 0,
  accuracy: null,
  created_by: 'admin',
  created_at: now - 8 * 86400000,
  updated_at: now - 3600000,
}

/** 任务四：ma_trend · bsp_query 范围 · test · pending（三来源创建路径联调） */
const maTask1: StrategyTask = {
  id: 3,
  strategy_id: 'ma_trend',
  label: '20/60 日线',
  user_group: '趋势跟踪',
  params: { fast_period: 20, slow_period: 60 },
  params_version: 1,
  scope_type: 'bsp_query',
  scope_codes: ['sh.600036', 'sz.000333', 'sh.600276', 'sz.000725'],
  mode: 'test',
  status: 'done',
  progress_scanned: 4,
  progress_total: 4,
  signal_count: 0,
  accuracy: null,
  created_by: 'trader',
  created_at: now - 25 * 86400000,
  updated_at: now - 10 * 86400000,
}

volBreakoutDef.tasks.push(volTask1, volTask2, volTask3)
maTrendDef.tasks.push(maTask1)

/** 任务五：vp_entry · manual 范围 · test · done（enum 参数 vol_gate=mean；
 *  信号含分钟版/日线版 entry_mode、三态、三桶漂移 → 详情四积木与私有列联调） */
const vpTask1: StrategyTask = {
  id: 6,
  strategy_id: 'vp_entry',
  label: '量价三段默认参数',
  user_group: '量价测试',
  params: { cv7_max: 0.25, box_width_max: 0.12, n_max: 7, stop_loss: 0.12, vol_gate: 'mean' },
  params_version: 1,
  scope_type: 'manual',
  scope_codes: ['sz.000001', 'sh.600036', 'sz.002594', 'sh.600276', 'sz.000725', 'sh.601012'],
  mode: 'test',
  status: 'done',
  progress_scanned: 6,
  progress_total: 6,
  signal_count: 0,
  accuracy: null,
  created_by: 'admin',
  created_at: now - 10 * 86400000,
  updated_at: now - 5 * 86400000,
}

/** 任务六：vp_entry · manual 范围 · test · paused（enum 参数 vol_gate=strict +
 *  v1/v2 混合参数版本 → 编辑弹窗 enum 下拉与版本归因联调） */
const vpTask2: StrategyTask = {
  id: 7,
  strategy_id: 'vp_entry',
  label: '严格量能门调参',
  user_group: '量价测试',
  params: { cv7_max: 0.22, box_width_max: 0.10, n_max: 6, stop_loss: 0.10, vol_gate: 'strict' },
  params_version: 2,
  scope_type: 'manual',
  scope_codes: ['sh.600519', 'sz.000858', 'sh.600809', 'sz.300750'],
  mode: 'test',
  status: 'paused',
  progress_scanned: 2,
  progress_total: 4,
  signal_count: 0,
  accuracy: null,
  created_by: 'trader',
  created_at: now - 6 * 86400000,
  updated_at: now - 86400000,
}

vpEntryDef.tasks.push(vpTask1, vpTask2)

// ---------------------------------------------------------------------------
// 信号生成（挂 task_id 维度；行携带 params_version → 混合参数任务按版本归因）
// ---------------------------------------------------------------------------

/** 生成某任务的信号集：股票取自 scope_codes/stocks，states 按声明轮转保证各状态若干；
 *  paramsVersion 显式传入（混合参数任务生成 v1/v2 两批） */
function genSignals(
  def: StrategyDefinition,
  task: StrategyTask,
  count: number,
  seedOffset: number,
  paramsVersion: number,
): StrategySignalRow[] {
  const rand = mulberry32(task.id * 97 + seedOffset)
  const pool = task.scope_codes && task.scope_codes.length > 0 ? task.scope_codes : null
  const rows: StrategySignalRow[] = []
  for (let i = 0; i < count; i++) {
    // 范围内 code 优先取（信号 ∈ 任务范围语义），不足时从 stocks 补
    const code = pool ? pool[i % pool.length] : stocks[(i * 3 + task.id * 5) % stocks.length].code
    const stock = findStock(code) || stocks[0]
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
    const payload: Record<string, number | string | null> = {}
    // 绩效四字段（strategy-signal-outcome D1 行级字段，非 payload）：仅匹配态
    // （triggered/running）携带——expired/watching 态无绩效，detail 信号页也不展示
    const isMatched = state === 'triggered' || state === 'running'
    let ret5: number | null = null
    let ret10: number | null = null
    let ret15: number | null = null
    let outcome: 'success' | 'failed' | 'pending' | null = null
    if (def.id === 'vol_breakout_pullback') {
      // 首板日 = 信号日前推若干交易日（回调窗口语义）——payload 保留
      // first_board_date 键（per_stock 消息等处引用），columns 声明已删该列（D12）
      const boardTs = signalTs - (3 + Math.floor(r * 6)) * 86400000
      payload.first_board_date = dateStr(boardTs)
      // 回调天数换锚（strategy-volume-breakout-pullback：最早 B 事件日 − A 日）
      payload.pullback_days = Math.floor(4 + r * Number(task.params.pullback_max_days || 13) * 0.6)
      payload.volume_ratio = +(1.8 + r * 1.5).toFixed(2)
      // A 日过程字段（D7 三值合并列 a_col：a_date/a_close/a_pct）
      payload.a_date = dateStr(boardTs)
      payload.a_close = +(stock.price * (0.9 + r * 0.06)).toFixed(2)
      payload.a_pct = +(0.05 + r * 0.05).toFixed(4)
      // ---- B 级事件生成（strategy-volume-breakout-pullback D1/D7） ----
      // 五级独立事件集合：非匹配态（watching）零事件（窗口未走完不打标），
      // 匹配态 1~3 个事件（B3 30m 缠论买点带时刻 / B1 日线 / B 放量突破轮转）
      const bEvents: BEventRow[] = []
      if (isMatched) {
        const bTs = signalTs - 2 * 86400000
        const levels: BEventRow['b_level'][] = ['B1', 'B2', 'B3', 'B4', 'B']
        const eventCount = 1 + Math.floor(r * 3) // 1~3 个
        for (let k = 0; k < eventCount; k++) {
          const level = levels[(i + k) % levels.length]
          // 30m 判定（B2/B3）带时刻，日线判定（B1/B4/B）日期 00:00
          const isMinute = level === 'B2' || level === 'B3'
          const dayOffset = 1 + Math.floor(r * 8)
          const eTs = signalTs - dayOffset * 86400000
          const ePrice = +(payload.a_close as number * (0.86 + r * 0.08)).toFixed(2)
          const e5 = +(0.02 + r * 0.12).toFixed(4)
          const e10 = +(0.01 + r * 0.15).toFixed(4)
          const e15 = +(r > 0.3 ? 0.02 + r * 0.2 : -0.02 + r * 0.05).toFixed(4)
          // 事件独立绩效三态轮转（与信号级同口径，2026-10-15 窗口 5/10/15）
          const eOutcome: BEventRow['outcome'] =
            k % 3 === 0 ? 'success' : k % 3 === 1 ? 'failed' : 'pending'
          bEvents.push({
            b_level: level,
            b_time: isMinute
              ? `${dateStr(eTs)} ${['10:00:00', '10:30:00', '13:30:00', '15:00:00'][(i + k) % 4]}`
              : `${dateStr(eTs)} 00:00:00`,
            b_kl_type: isMinute ? '30m' : 'D',
            price: ePrice,
            day_pct: +((r - 0.5) * 0.08).toFixed(4),
            ret_5d: eOutcome === 'pending' ? e5 : e5,
            ret_10d: eOutcome === 'pending' ? null : e10,
            ret_15d: eOutcome === 'pending' ? null : e15,
            outcome: eOutcome,
          })
        }
        // payload 摘要（D1：payload 只留 earliest 摘要 + b_count，全集弹窗取）
        payload.b_count = bEvents.length
        payload.earliest_b_level = bEvents[0].b_level
        // B 列展平键（b_col 三值合并列：最早事件）
        const first = bEvents[0]
        payload.b_date = first.b_time
        payload.b_close = first.price
        payload.b_day_pct = first.day_pct
      } else {
        payload.b_count = 0
        payload.earliest_b_level = null
        payload.b_date = null
        payload.b_close = null
        payload.b_day_pct = null
      }
      // b_events 全集（任务详情 detail 行嵌入形态；主列表页不带——mock 信号池
      // 单一形态两用，前端 bEventsOf 兼容有/无两种形态）
      ;(payload as Record<string, number | string | null | BEventRow[]>).b_events = bEvents
      if (isMatched) {
        // 绩效三态轮转（2026-10-15 加权口径 30/50/20）：0/1 成功（总收益 = 10%×0.3 +
        // 3%×0.5 + 12%×0.2 = 8.1% > 5%）、2/4 失败（总收益 ≤ 5%）、3 待定（三时段不齐）；
        // 保证 success/failed/pending 各至少若干条（任务详情联调用）
        const bucket = i % 5
        if (bucket === 0 || bucket === 1) {
          ret5 = 0.1
          ret10 = 0.03
          ret15 = 0.12
          outcome = 'success'
        } else if (bucket === 3) {
          ret5 = +(0.04 + r * 0.03).toFixed(4)
          ret10 = null
          ret15 = null
          outcome = 'pending'
        } else {
          // 失败样例：总收益 = 4%×0.3 + 1%×0.5 + 3%×0.2 = 2.5% ≤ 5%
          ret5 = +(0.04 + r * 0.02).toFixed(4)
          ret10 = +(0.01 + r * 0.01).toFixed(4)
          ret15 = +(0.03 + r * 0.01).toFixed(4)
          outcome = 'failed'
        }
        payload.close_5d = ret5 != null ? +(entry * (1 + ret5)).toFixed(2) : null
        payload.close_10d = ret10 != null ? +(entry * (1 + ret10)).toFixed(2) : null
        payload.close_15d = ret15 != null ? +(entry * (1 + ret15)).toFixed(2) : null
      } else {
        payload.close_5d = null
        payload.close_10d = null
        payload.close_15d = null
      }
    } else if (def.id === 'vp_entry') {
      // 量价三段式 payload（SignalEvent 基底特征，D2 事件转换契约）：
      // a_date/p_date 前推、entry_mode 两版轮转、drift_bucket 三桶轮转保证全覆盖
      payload.a_date = dateStr(signalTs - (8 + Math.floor(r * 5)) * 86400000)
      payload.p_date = dateStr(signalTs - (15 + Math.floor(r * 10)) * 86400000)
      payload.entry_mode = i % 3 === 2 ? 'daily' : 'minute'
      payload.volume_ratio = +(2.0 + r * 2.0).toFixed(2)
      payload.spring = i % 5 === 4 ? '是' : '否'
      payload.drift_bucket = ['low', 'mid', 'high'][i % 3]
      payload.wick_box = +(0.05 + r * 0.08).toFixed(3)
      payload.box_days = 20 + Math.floor(r * 30)
      // A 日涨幅（小数口径，kv 统计展示时 ×100 转百分比）
      payload.a_ret = +(0.03 + r * 0.06).toFixed(4)
      // A/B 点过程字段 + 绩效（D10：vp_entry B 日 = 入场日，按缺补齐）
      payload.a_close = +(stock.price * (0.88 + r * 0.06)).toFixed(2)
      payload.a_pct = +(0.05 + r * 0.04).toFixed(4)
      payload.b_date = dateStr(signalTs - 86400000)
      // B 日 OHLC + 当日涨跌幅（D10：b_day_pct = b_close/b_open - 1）
      payload.b_open = +(payload.a_close as number * (0.96 + r * 0.05)).toFixed(2)
      payload.b_close = +(payload.b_open as number * (1.01 + r * 0.04)).toFixed(2)
      payload.b_day_pct = +((payload.b_close as number) / (payload.b_open as number) - 1).toFixed(4)
      if (isMatched) {
        // 三态轮转（2026-10-15 加权口径 30/50/20）：0/2 成功（总收益 = 9%×0.3 +
        // 11%×0.5 + 4%×0.2 = 8.5% > 5%）、1/4 失败（总收益 ≤ 5%）、3 待定（detail 信号页联调）
        const bucket = i % 5
        if (bucket === 0 || bucket === 2) {
          ret5 = 0.09
          ret10 = 0.11
          ret15 = 0.04
          outcome = 'success'
        } else if (bucket === 3) {
          ret5 = +(0.05 + r * 0.03).toFixed(4)
          ret10 = null
          ret15 = null
          outcome = 'pending'
        } else {
          // 失败样例：总收益 = 3%×0.3 + 0%×0.5 + 4%×0.2 = 1.7% ≤ 5%
          ret5 = +(0.03 + r * 0.02).toFixed(4)
          ret10 = +(-0.005 + r * 0.005).toFixed(4)
          ret15 = +(0.04 + r * 0.02).toFixed(4)
          outcome = 'failed'
        }
        payload.close_5d = ret5 != null ? +(entry * (1 + ret5)).toFixed(2) : null
        payload.close_10d = ret10 != null ? +(entry * (1 + ret10)).toFixed(2) : null
        payload.close_15d = ret15 != null ? +(entry * (1 + ret15)).toFixed(2) : null
      } else {
        payload.close_5d = null
        payload.close_10d = null
        payload.close_15d = null
      }
    } else {
      // 金叉日 = 信号日前推若干交易日
      const crossTs = signalTs - (5 + Math.floor(r * 10)) * 86400000
      payload.golden_cross_date = dateStr(crossTs)
      payload.trend_strength = +(0.2 + r * 0.8).toFixed(2)
    }
    rows.push({
      // 信号行 id（strategy-volume-breakout-pullback：B 事件弹窗接口按此查；
      // mock 用 task.id * 10000 + 序号造全局唯一 id）
      id: task.id * 10000 + i,
      code: stock.code,
      name: stock.name,
      industries: stock.industries,
      signal_date: signalDate,
      state,
      is_buy: isBuy,
      entry_ref_price: entry,
      stop_ref_price: stop,
      payload,
      params_version: paramsVersion,
      // 绩效四字段（D1 行级列：非匹配态恒 null——对齐后端「匹配态才带值」；
      // 2026-10-15 修订：7/14/30 → 5/10/15）
      ret_5d: ret5,
      ret_10d: ret10,
      ret_15d: ret15,
      outcome,
    })
  }
  return rows
}

/** 内存信号池（按任务隔离；spec：信号挂任务，跨任务互不可见） */
export const strategySignals: Record<number, StrategySignalRow[]> = {
  // 任务一：v1 旧参数 8 条 + v2 新参数 16 条 → 信号行版本标识联调
  1: [
    ...genSignals(volBreakoutDef, { ...volTask1, params: { pullback_max_days: 5, pullback_min_days: 4, volume_ratio_min: 1.8, a_pct_min: 0.05 } } as StrategyTask, 8, 11, 1),
    ...genSignals(volBreakoutDef, volTask1, 16, 23, 2),
  ],
  2: genSignals(volBreakoutDef, volTask2, 10, 23, 1),
  5: genSignals(volBreakoutDef, volTask3, 12, 41, 1),
  3: genSignals(maTrendDef, maTask1, 8, 37, 1),
  // vp_entry 任务（三态轮转、entry_mode 两版、drift 三桶全覆盖）
  6: genSignals(vpEntryDef, vpTask1, 12, 53, 1),
  7: [
    ...genSignals(vpEntryDef, { ...vpTask2, params: { cv7_max: 0.25, box_width_max: 0.12, n_max: 7, stop_loss: 0.12, vol_gate: 'mean' } } as StrategyTask, 4, 61, 1),
    ...genSignals(vpEntryDef, vpTask2, 6, 71, 2),
  ],
}

// 信号计数与准确率回填（侧栏 badge / 列表 total / 准确率列同一口径；
// accuracy 口径对齐后端 compute_outcome_kv_stats：仅匹配态行
// （triggered/running）计入，success/(success+failed)，分母 0 → null）
for (const def of strategyDefinitions) {
  for (const task of def.tasks) {
    task.signal_count = (strategySignals[task.id] || []).length
    const matched = (strategySignals[task.id] || []).filter(
      (s) => s.state === 'triggered' || s.state === 'running',
    )
    const successCnt = matched.filter((s) => s.outcome === 'success').length
    const failedCnt = matched.filter((s) => s.outcome === 'failed').length
    const denom = successCnt + failedCnt
    task.accuracy = denom ? +(successCnt / denom).toFixed(4) : null
  }
}

// ---------------------------------------------------------------------------
// 逐股结果（strategy-task-redesign spec：仅显式范围任务落逐股结果；全量只维护聚合计数）
// ---------------------------------------------------------------------------

/** 任务一（manual 6 只）：含未匹配/失败/匹配各态 → per_stock 块联调 */
export const taskStockResults: Record<number, StrategyTaskStockResult[]> = {
  1: volTask1.scope_codes!.map((code, i) => {
    const stock = findStock(code) || stocks[0]
    const matched = i % 3 !== 2 // 前两只命中、第三只未匹配，轮转
    const failed = i === 5
    return {
      code,
      name: stock.name,
      matched: matched && !failed,
      run_status: failed ? 'failed' : 'ok',
      message: failed
        ? 'DuckDB 缺少该 code 的日线数据（灌数缺口）'
        : matched
          ? `命中策略：首板 ${dateStr(now - (10 + i) * 86400000)}`
          : '未匹配：回调量缩不满足阈值',
      signal_date: matched && !failed ? dateStr(now - (3 + i) * 86400000) : null,
      // v1/v2 混合：前 3 只为重新运行前的旧版本产物快照（示意重扫前状态），其余 v2
      params_version: i < 3 ? 1 : 2,
      executed_at: now - (20 + i) * 86400000,
    }
  }),
  2: (volTask2.scope_codes || []).slice(0, volTask2.progress_scanned).map((code, i) => {
    const stock = findStock(code) || stocks[0]
    const matched = i % 2 === 0
    return {
      code,
      name: stock.name,
      matched,
      run_status: 'ok' as const,
      message: matched ? `命中策略：首板 ${dateStr(now - (6 + i) * 86400000)}` : '未匹配：未出现放量首板',
      signal_date: matched ? dateStr(now - (2 + i) * 86400000) : null,
      params_version: 1,
      executed_at: now - 2 * 86400000,
    }
  }),
  3: (maTask1.scope_codes || []).map((code, i) => {
    const stock = findStock(code) || stocks[0]
    const matched = i < 2
    return {
      code,
      name: stock.name,
      matched,
      run_status: 'ok' as const,
      message: matched
        ? `金叉成立：${maTask1.params.fast_period}/${maTask1.params.slow_period} 日均线多头排列`
        : '未匹配：快线仍在慢线下方',
      signal_date: matched ? dateStr(now - (4 + i) * 86400000) : null,
      params_version: 1,
      executed_at: now - 10 * 86400000,
    }
  }),
  // vp_entry 任务六（manual 6 只）：三段式判定各态（命中/未匹配/分钟数据缺失兜底）
  6: (vpTask1.scope_codes || []).map((code, i) => {
    const stock = findStock(code) || stocks[0]
    const matched = i % 3 !== 1 // 第 2/5 只未匹配（蓄势期 CV7 超门限），其余命中
    return {
      code,
      name: stock.name,
      matched,
      run_status: 'ok' as const,
      message: matched
        ? `命中三段式：A 日 ${dateStr(now - (10 + i) * 86400000)} 放量，B 日 ${i % 3 === 2 ? '日线退化版（当日无 K_5M 分钟数据）' : '分钟版触发'}`
        : '未匹配：蓄势期 CV7 变异系数超门限，蓄势不充分',
      signal_date: matched ? dateStr(now - (2 + i) * 86400000) : null,
      params_version: 1,
      executed_at: now - 5 * 86400000,
    }
  }),
  // vp_entry 任务七（manual 4 只，仅扫 2 只）：paused 中途态
  7: (vpTask2.scope_codes || []).slice(0, vpTask2.progress_scanned).map((code, i) => {
    const stock = findStock(code) || stocks[0]
    const matched = i === 0
    return {
      code,
      name: stock.name,
      matched,
      run_status: 'ok' as const,
      message: matched
        ? `命中三段式：量能门 ${vpTask2.params.vol_gate === 'strict' ? '逐日严格门' : '均值门'} 口径`
        : '未匹配：调整期超时未触发 B 日介入',
      signal_date: matched ? dateStr(now - 3 * 86400000) : null,
      params_version: 1,
      executed_at: now - 86400000,
    }
  }),
  // 注意：任务 5（scope='all'）刻意不落逐股结果（spec：全量范围不落逐股结果）
}

// ---------------------------------------------------------------------------
// 任务详情（design D5：detail API 返回 {task, summary, per_stock?, signals_page,
// kv_payload, definition, timeline}；per_stock 在 scope='all' 时后端不返回 → 前端静默隐藏）
// ---------------------------------------------------------------------------

/** kv_payload（按定义一 detail_schema kv 块 items[].key 取值；
 *  D12：删首板日分布/平均放量倍数/平均回调天数三形态统计值，
 *  仅保留绩效准确率通用块 D6——outcomeKvStats 自取信号池） */
function volKvPayload(taskId: number): Record<string, number | string | null> {
  return {
    ...outcomeKvStats(taskId),
  }
}

/** 通用绩效聚合（strategy-signal-outcome D6：对齐后端 compute_outcome_kv_stats 键，
 *  匹配态信号 outcome 分布聚合；accuracy = success/(success+failed)，
 *  pending 数据不足不入分母；avg_ret_* 为非 NULL 收益率均值，无样本为 null。
 *  2026-10-15 修订：删 pending_cnt（kv 块不再展示数据不足数）、
 *  avg_ret_* 随窗口改 5/10/15） */
function outcomeKvStats(taskId: number): Record<string, number | null> {
  const signals = strategySignals[taskId] || []
  const successCnt = signals.filter((s) => s.outcome === 'success').length
  const failedCnt = signals.filter((s) => s.outcome === 'failed').length
  const avg = (key: 'ret_5d' | 'ret_10d' | 'ret_15d'): number | null => {
    const vals = signals.map((s) => s[key]).filter((v): v is number => v != null)
    return vals.length ? +(vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(6) : null
  }
  const denom = successCnt + failedCnt
  return {
    success_cnt: successCnt,
    failed_cnt: failedCnt,
    accuracy: denom ? +(successCnt / denom).toFixed(4) : null,
    avg_ret_5d: avg('ret_5d'),
    avg_ret_10d: avg('ret_10d'),
    avg_ret_15d: avg('ret_15d'),
  }
}

/** vp_entry kv_payload（按 D5 契约服务端聚合：总数/两版占比/spring 占比/
 *  三桶漂移分布/平均影线盒宽/平均蓄势天数/平均 A 日涨幅/存活数
 *  + 绩效准确率通用块 D6） */
function vpEntryKvPayload(taskId: number): Record<string, number | string | null> {
  const signals = strategySignals[taskId] || []
  const total = signals.length
  if (total === 0) {
    return {
      signal_total: 0, minute_ratio: '--', daily_ratio: '--', spring_ratio: '--',
      drift_dist: '--', avg_wick_box: 0, avg_box_days: 0, avg_a_ret: 0, alive_count: 0,
      ...outcomeKvStats(taskId),
    }
  }
  const pct = (n: number) => `${Math.round((n / total) * 100)}%`
  const minuteN = signals.filter((s) => s.payload.entry_mode === 'minute').length
  const springN = signals.filter((s) => s.payload.spring === '是').length
  const buckets = ['low', 'mid', 'high'].map(
    (b) => `${b === 'low' ? '低' : b === 'mid' ? '中' : '高'} ${signals.filter((s) => s.payload.drift_bucket === b).length}`,
  )
  const wick = signals.map((s) => Number(s.payload.wick_box ?? 0)).filter((v) => Number.isFinite(v) && v > 0)
  const days = signals.map((s) => Number(s.payload.box_days ?? 0)).filter((v) => Number.isFinite(v) && v > 0)
  const aRets = signals.map((s) => Number(s.payload.a_ret ?? 0)).filter((v) => Number.isFinite(v))
  return {
    signal_total: total,
    minute_ratio: pct(minuteN),
    daily_ratio: pct(total - minuteN),
    spring_ratio: pct(springN),
    drift_dist: buckets.join(' / '),
    avg_wick_box: wick.length ? +(wick.reduce((a, b) => a + b, 0) / wick.length).toFixed(3) : 0,
    avg_box_days: days.length ? +(days.reduce((a, b) => a + b, 0) / days.length).toFixed(1) : 0,
    avg_a_ret: aRets.length ? +((aRets.reduce((a, b) => a + b, 0) / aRets.length) * 100).toFixed(2) : 0,
    alive_count: signals.filter((s) => s.state === 'triggered').length,
    ...outcomeKvStats(taskId),
  }
}

/** timeline 事件（定义二 timeline 块消费：信号日期序列 + 状态演进） */
function timelineOf(taskId: number): { date: string; event: string; state: string }[] {
  const signals = strategySignals[taskId] || []
  const events: { date: string; event: string; state: string }[] = []
  for (const s of signals.slice(0, 8)) {
    events.push({ date: s.signal_date, event: `信号产生 · ${s.name}`, state: s.state })
  }
  events.push({ date: dateStr(now), event: '任务执行完成', state: 'done' })
  return events.sort((a, b) => (a.date < b.date ? -1 : 1))
}

/** 任务详情聚合（与真后端 detail 端点同构；strategy-signal-outcome D6：
 *  signals_page 只含匹配态行（state ∈ triggered/running）——expired 行从
 *  详情信号页剔除，独立 /signals handler 保留全量，对齐后端行为） */
export function buildTaskDetail(taskId: number): StrategyTaskDetail | null {
  const found = findTask(taskId)
  if (!found) return null
  const { def, task } = found
  const signals = strategySignals[taskId] || []
  const matchedSignals = signals.filter((s) => s.state === 'triggered' || s.state === 'running')
  const results = taskStockResults[taskId] || []
  const summary = {
    total: task.progress_total,
    scanned: task.progress_scanned,
    matched: signals.length,
    failed: results.filter((r) => r.run_status === 'failed').length,
  }
  return {
    task: { ...task, params: { ...task.params } },
    summary,
    kv_payload:
      def.id === 'vol_breakout_pullback'
        ? volKvPayload(taskId)
        : def.id === 'vp_entry'
          ? vpEntryKvPayload(taskId)
          : {},
    // scope='all'：后端不返回 per_stock 键（design D5）→ 前端 per_stock 块静默隐藏
    ...(task.scope_type !== 'all' ? { per_stock: results.map((r) => ({ ...r })) } : {}),
    signals_page: {
      list: matchedSignals.slice(0, 20).map((s) => ({ ...s })),
      total: matchedSignals.length,
      page: 1,
      page_size: 20,
    },
    definition: {
      id: def.id,
      name: def.name,
      group_name: def.group_name,
      params_schema: def.params_schema,
      states: def.states,
      columns: def.columns,
      detail_schema: def.detail_schema,
    },
    timeline: timelineOf(taskId),
  }
}

// ---------------------------------------------------------------------------
// 任务管理（内存态，风格对齐 data/screener.ts 的 addStrategy 模式）
// ---------------------------------------------------------------------------

let nextTaskId = 100

/** 参数校验（design D1：非法值抛错；后端 422 detail 同语义）：
 *  int/float → 数值区间；enum → 取值必须在 options[].value 选项集内
 *  （vp-entry-strategy-integration D4，错误文案带合法值列表） */
function validateParams(def: StrategyDefinition, params: Record<string, number | string>) {
  for (const schema of def.params_schema) {
    const v = params[schema.key]
    if (schema.type === 'enum') {
      const opts = schema.options || []
      if (typeof v !== 'string' || !opts.some((o) => o.value === v)) {
        throw new Error(
          `参数「${schema.label}」取值非法：${String(v)}，合法选项：${opts.map((o) => `${o.label}(${o.value})`).join('、')}`,
        )
      }
      continue
    }
    const num = Number(v)
    if (v == null || !Number.isFinite(num)) {
      throw new Error(`参数「${schema.label}」缺失或不是数值`)
    }
    const min = (schema as StrategyParamSchema).min
    const max = (schema as StrategyParamSchema).max
    if (min != null && num < min) {
      throw new Error(`参数「${schema.label}」超出范围 [${min}, ${max}]`)
    }
    if (max != null && num > max) {
      throw new Error(`参数「${schema.label}」超出范围 [${min}, ${max}]`)
    }
  }
}

/** 范围解析（design D3 三来源 + 全量兜底）：
 *  manual → 前端传 codes；watchlist → 读 mock 文件夹快照；bsp_query → 模拟按条件
 *  取 code 列表（mock 简化为固定集合）；未选股票 → 'all'（scope_codes null） */
function resolveScope(payload: {
  scope_type?: string
  scope_codes?: string[]
  folder_id?: number
}): { scope_type: StrategyTask['scope_type']; scope_codes: string[] | null } {
  const t = payload.scope_type
  if (!t || t === 'all') return { scope_type: 'all', scope_codes: null }
  if (t === 'manual') {
    const codes = (payload.scope_codes || []).map((c) => c.trim()).filter(Boolean)
    if (codes.length === 0) return { scope_type: 'all', scope_codes: null }
    return { scope_type: 'manual', scope_codes: Array.from(new Set(codes)) }
  }
  if (t === 'watchlist') {
    const folder = watchFolders.find((f) => f.id === payload.folder_id)
    if (!folder) throw new Error(`自选文件夹 ${payload.folder_id} 不存在`)
    if (folder.codes.length === 0) throw new Error('所选自选文件夹为空')
    // 快照语义：拷贝该文件夹当前股票（此后文件夹变化不影响任务）
    return { scope_type: 'watchlist', scope_codes: [...folder.codes] }
  }
  if (t === 'bsp_query') {
    // mock：模拟后端按 /bsp 查询条件取 code 列表后固化快照
    const codes = ['sz.000001', 'sh.600036', 'sz.002594', 'sh.601012', 'sz.300750']
    return { scope_type: 'bsp_query', scope_codes: [...codes] }
  }
  throw new Error(`未知范围类型 ${t}`)
}

/** 新建任务：params 按定义 params_schema 校验（min/max 拒绝抛错 → handler 转 422）；
 *  创建后 pending 待执行（spec：创建即进入待执行状态，非隐式全量回算）。
 *  created_by 取请求头 token 解析出的当前 mock 用户 username（对齐真后端鉴权注入） */
export function addTask(payload: {
  strategy_id?: string
  label?: string
  user_group?: string
  params?: Record<string, number | string>
  scope_type?: string
  scope_codes?: string[]
  folder_id?: number
  mode?: string
}, request?: Request): StrategyTask {
  const def = findDefinition((payload.strategy_id || '').trim())
  if (!def) throw new Error(`策略定义 ${payload.strategy_id} 不存在`)
  const label = (payload.label || '').trim()
  if (!label) throw new Error('任务名不能为空')
  const params = payload.params ?? {}
  validateParams(def, params)
  const scope = resolveScope(payload)
  const total = scope.scope_codes ? scope.scope_codes.length : 5000 // mock：全量 A 股按 5000 档
  const uid = request ? userIdFromRequest(request) : 1
  const creator = mockUsers.find((m) => m.id === uid)?.username || 'admin'
  const task: StrategyTask = {
    id: nextTaskId++,
    strategy_id: def.id,
    label,
    user_group: (payload.user_group || '').trim(),
    params: { ...params },
    params_version: 1,
    ...scope,
    mode: payload.mode === 'persistent' ? 'persistent' : 'test',
    status: 'pending',
    progress_scanned: 0,
    progress_total: total,
    signal_count: 0,
    accuracy: null,
    created_by: creator,
    created_at: Date.now(),
    updated_at: Date.now(),
  }
  def.tasks.push(task)
  return { ...task, params: { ...task.params } }
}

/** 删除任务（级联删信号与逐股结果） */
export function removeTask(id: number): boolean {
  for (const def of strategyDefinitions) {
    const idx = def.tasks.findIndex((t) => t.id === id)
    if (idx >= 0) {
      def.tasks.splice(idx, 1)
      delete strategySignals[id]
      delete taskStockResults[id]
      return true
    }
  }
  return false
}

/** 启动任务（pending/paused → running；done 任务重启走 resume 语义，此处拒绝） */
export function startTask(id: number): boolean {
  const found = findTask(id)
  if (!found) return false
  if (found.task.status !== 'pending' && found.task.status !== 'paused') return false
  found.task.status = 'running'
  found.task.updated_at = Date.now()
  return true
}

/** 暂停任务（running → paused；已产生信号与逐股结果保留） */
export function pauseTask(id: number): boolean {
  const found = findTask(id)
  if (!found) return false
  if (found.task.status !== 'running') return false
  found.task.status = 'paused'
  found.task.updated_at = Date.now()
  return true
}

/**
 * 续跑（design D2 两种语义）：
 * - full（重新运行，默认）：清空旧信号/逐股结果/进度归零 → 重扫（mock：同步生成新批次信号）
 * - remaining（剩余继续）：保留已扫结果，从当前进度用新参数续扫
 *   （mock：追加一批新参数版本信号，params_version 取任务当前值）
 */
export function resumeTask(id: number, rerun: string): { success: boolean; message?: string } {
  const found = findTask(id)
  if (!found) return { success: false, message: `任务 ${id} 不存在` }
  const { def, task } = found
  if (task.status !== 'paused' && task.status !== 'done') {
    return { success: false, message: '仅暂停/完成状态的任务可续跑' }
  }
  const version = task.params_version
  if (rerun === 'full') {
    delete strategySignals[id]
    delete taskStockResults[id]
    task.progress_scanned = 0
    task.status = 'running'
    // mock：重新生成整批新参数信号并推进至完成
    const count = 6 + (task.id % 5)
    strategySignals[id] = genSignals(def, task, count, task.id * 3 + 7, version)
    task.progress_scanned = task.progress_total
    if (task.mode === 'test') task.status = 'done'
    task.signal_count = strategySignals[id].length
    return { success: true, message: `重新运行完成：生成 ${strategySignals[id].length} 条信号（参数 v${version}）` }
  }
  if (rerun === 'remaining') {
    const remaining = task.progress_total - task.progress_scanned
    if (remaining <= 0) return { success: false, message: '任务已全部扫完，请选择重新运行' }
    task.status = 'running'
    // mock：从当前进度续扫（新参数版本信号追加，旧参数信号保留 → 混合版本归因联调）
    const extra = genSignals(def, task, Math.min(4, remaining), task.id * 5 + 3, version)
    strategySignals[id] = [...(strategySignals[id] || []), ...extra]
    task.progress_scanned = task.progress_total
    if (task.mode === 'test') task.status = 'done'
    task.signal_count = strategySignals[id].length
    return { success: true, message: `剩余 ${remaining} 只股票继续完成：新增 ${extra.length} 条信号（参数 v${version}）` }
  }
  return { success: false, message: `未知续跑方式 ${rerun}` }
}

/** 编辑任务（design D6：仅 paused 可编辑；test 可改参数与范围，persistent 仅范围——参数冻结）；
 *  params 变化时 params_version +1（spec：每次参数编辑使版本递增） */
export function patchTask(
  id: number,
  payload: {
    label?: string
    user_group?: string
    params?: Record<string, number | string>
    scope_type?: string
    scope_codes?: string[]
    folder_id?: number
  },
): StrategyTask {
  const found = findTask(id)
  if (!found) throw new Error(`任务 ${id} 不存在`)
  const { def, task } = found
  if (task.status !== 'paused') {
    throw new Error('仅暂停状态的任务可编辑，请先暂停任务')
  }
  // 参数冻结（persistent）：拒绝参数修改并提示复制任务调参
  if (payload.params && Object.keys(payload.params).length > 0) {
    if (task.mode === 'persistent') {
      throw new Error('长期任务参数已冻结（转正冻结的是经测试验证的参数组），调参请复制任务为新的测试任务')
    }
    validateParams(def, payload.params)
    const changed = def.params_schema.some((s) => {
      const oldV = task.params[s.key]
      const newV = payload.params?.[s.key]
      return newV != null && oldV !== newV
    })
    if (changed) {
      task.params = { ...task.params, ...payload.params }
      task.params_version += 1
    }
  }
  if (payload.label != null) {
    const label = payload.label.trim()
    if (!label) throw new Error('任务名不能为空')
    task.label = label
  }
  if (payload.user_group != null) task.user_group = payload.user_group.trim()
  if (payload.scope_type != null) {
    const scope = resolveScope(payload)
    task.scope_type = scope.scope_type
    task.scope_codes = scope.scope_codes
    task.progress_total = scope.scope_codes ? scope.scope_codes.length : 5000
  }
  task.updated_at = Date.now()
  return { ...task, params: { ...task.params } }
}

/** 转正（done 的 test → persistent，挂 EOD 调度；既有信号保留） */
export function promoteTask(id: number): StrategyTask {
  const found = findTask(id)
  if (!found) throw new Error(`任务 ${id} 不存在`)
  const { task } = found
  if (task.mode !== 'test') throw new Error('仅测试任务可转正')
  if (task.status !== 'done') throw new Error('仅已完成状态的测试任务可转正')
  task.mode = 'persistent'
  task.updated_at = Date.now()
  return { ...task, params: { ...task.params } }
}

/** 复制任务（继承参数与范围为新的 test 任务，可自由编辑——调参路径） */
export function copyTask(id: number, request?: Request): StrategyTask {
  const found = findTask(id)
  if (!found) throw new Error(`任务 ${id} 不存在`)
  const { def, task } = found
  const uid = request ? userIdFromRequest(request) : 1
  const creator = mockUsers.find((m) => m.id === uid)?.username || 'admin'
  const copy: StrategyTask = {
    id: nextTaskId++,
    strategy_id: task.strategy_id,
    label: `${task.label} 副本`,
    user_group: task.user_group,
    params: { ...task.params },
    params_version: 1,
    scope_type: task.scope_type,
    scope_codes: task.scope_codes ? [...task.scope_codes] : null,
    mode: 'test',
    status: 'pending',
    progress_scanned: 0,
    progress_total: task.progress_total,
    signal_count: 0,
    accuracy: null,
    created_by: creator,
    created_at: Date.now(),
    updated_at: Date.now(),
  }
  def.tasks.push(copy)
  return { ...copy, params: { ...copy.params } }
}

/** 信号计数同步（handlers 操作后调用） */
export function syncSignalCounts() {
  for (const def of strategyDefinitions) {
    for (const task of def.tasks) {
      task.signal_count = (strategySignals[task.id] || []).length
    }
  }
}
