// ============================================================================
// chan.py 前端 API 类型定义
// ============================================================================

/** 通用分页响应 */
export interface PageRes<T> {
  list: T[]
  total: number
  page: number
  page_size: number
}

/** 分页查询参数 */
export interface PageQuery {
  page?: number
  page_size?: number
  keyword?: string
}

// ---------------------------------------------------------------------------
// 股票基础
// ---------------------------------------------------------------------------
export interface Stock {
  code: string
  name: string
  industries: string[]
  region: string
  concepts: string[]
  price: number
  change_pct: number
}

/** 标的详情（完整板块信息：行业/地区/概念全量展示） */
export type StockProfile = Stock

// ---------------------------------------------------------------------------
// 股票元数据（kline-stock-metadata 契约：GET /api/stocks/{code}/meta）
// ---------------------------------------------------------------------------

/** 股东户数序列项（近 1 年，按 stat_date 升序） */
export interface StockHolderPoint {
  stat_date: string
  holder_num: number | null
}

/**
 * 股票元数据 — 一次性返回，键恒定存在：
 * 空值形态：字符串 = ''、数值/日期 = null、序列 = []（可空数组）
 */
export interface StockMeta {
  // 身份
  code: string
  name: string
  exchange: string
  ipo_date: string | null
  board: string
  // A 公司档案（16 列）
  full_name: string
  en_name: string
  former_names: string
  legal_person: string
  reg_capital: string
  found_date: string | null
  website: string
  email: string
  phone: string
  fax: string
  reg_addr: string
  office_addr: string
  postal_code: string
  main_business: string
  business_scope: string
  intro: string
  // D 行情快照（8 列；快照缺失时数值为 null、snapshot_at 为 null）
  price: number | null
  total_mv: number | null
  float_mv: number | null
  pe_ttm: number | null
  pb: number | null
  turnover_rate: number | null
  main_net_inflow: number | null
  snapshot_at: string | null
  // 用户列
  tags: string[]
  notes: string
  // 股东户数近 1 年序列
  holders: StockHolderPoint[]
}

// ---------------------------------------------------------------------------
// K 线（design.md D2 序列化契约）
// ---------------------------------------------------------------------------
export interface KLine {
  timestamp: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface BiPoint {
  t: number
  v: number
}

export interface Bi {
  begin: BiPoint
  end: BiPoint
  dir: 'UP' | 'DOWN'
  is_sure: boolean
}

export interface Seg extends Bi {
  level: number
}

export interface ZS {
  begin_t: number
  end_t: number
  low: number
  high: number
  mid: number
  level: 'bi' | 'seg'
}

export interface BspPoint {
  t: number
  v: number
  is_buy: boolean
  types: string[] // 原始枚举: '1','2','2s','3a','3b','1p'
  /** 确认状态（bsp-sure-annotation D5）：依托线段已确认为 true，依托虚段（未确认段）为 false */
  is_sure: boolean
  /** 确认阶梯级别（bsp-ladder-change D3）：'L1' 小级别区间套 / 'L2' 虚笔候选 /
   *  'L3' 背驰预警 / 'L4' 确认买卖点；缺失 = 未定级（前端兜底展示） */
  ladder?: string
}

export interface ChanResult {
  klines: KLine[]
  bi: Bi[]
  seg: Seg[]
  zs: ZS[]
  seg_zs: ZS[]
  bsp: BspPoint[]
}

// ---------------------------------------------------------------------------
// 买卖点记录
// ---------------------------------------------------------------------------
export interface BspRecord {
  id: number
  code: string
  name: string
  industries: string[]
  bsp_type: string // 1B/2B/3B/1S/2S/L2B/L2S/PZ-B/PZ-S
  direction: 'buy' | 'sell'
  bsp_price: number
  current_price: number
  bsp_date: number
  kl_type: string
  change_pct: number
  /** 确认状态（bsp-sure-annotation）：依托线段已确认为 true（定型信号），依托虚段为 false（预览信号，可能随重算消失） */
  is_sure: boolean
  /** 确认阶梯级别（bsp-ladder-change D6）：'L1'/'L2'/'L3'/'L4'；存量行 NULL 由后端按 is_sure 映射兜底，
   *  缺失时前端兜底「未定级」 */
  ladder?: string
}

export interface BspAggregate {
  industry: string
  total: number
  buy_count: number
  sell_count: number
}

// ---------------------------------------------------------------------------
// 监控
// ---------------------------------------------------------------------------
export interface MonitorItem {
  id: number
  code: string
  name: string
  industries: string[]
  bsp_type: string
  direction: 'buy' | 'sell'
  bsp_price: number
  current_price: number
  bsp_date: number
  kl_type: string
  change_pct: number
  /** 收益率：(当前价 − 买卖点价) / 买卖点价 × 100，自买卖点时间起累计涨跌；
   *  后端 DuckDB 不可用或 entry_price=0 时为 null（design D5/D8 容错） */
  current_pnl_pct: number | null
  max_profit: number
  max_drawdown: number
  status: 'monitoring' | 'completed'
  /** 分组归属（monitor-group-change：null = 未分组，存量记录零迁移即 NULL） */
  group_id: number | null
  /** 信号来源（strategy-signal-page design D6 + D14 / watchlist-page-change design D8/D11）：
   *  'chan'（默认，存量行为不变）、'strategy' 或 'watchlist'（自选页加入监控，来源列显示「自选」） */
  source_type?: 'chan' | 'strategy' | 'watchlist'
  /** 策略来源所属任务（source_type='strategy' 时随信号携带；原 instance_id 废弃，BREAKING） */
  task_id?: number
  /** 策略来源展示标签（「策略名 · 任务名 · 状态」，后端/mock 填充；chan/watchlist 来源不传） */
  strategy_label?: string
}

export interface CompletedItem extends MonitorItem {
  end_date: number
  end_price: number
  profit: number
  attribution: string
  ai_analyzed: boolean
}

/** 归因记录（POST /monitor/{id}/analyze 成功返回的真实结构，design D5） */
export interface AttributionRecord {
  id: number
  monitor_id: number
  reason_type: string
  evidence: string
  created_at: number
}

/** 归因分析结果 */
export interface AnalyzeResult {
  success: boolean
  id: number
  attribution: AttributionRecord[]
}

// ---------------------------------------------------------------------------
// 策略任务（strategy-task-redesign design D1/D5/D6）
// 命名区分：本节的 StrategyDefinition/StrategyTask/StrategySignalRow 是
// 策略引擎的「策略定义 / 任务 / 信号」三层实体（schema 驱动、任务为中心），
// 与上方选股器的 Strategy（缠论买卖点过滤器）是完全不同的概念，刻意不共用命名。
// 原实例模型（strategy_instance）废弃，统一为任务模型（BREAKING）。
// ---------------------------------------------------------------------------
/** 策略参数声明（params_schema 项）：动态渲染任务表单项
 *  （int/float → el-input-number；enum → el-select 下拉，选项集声明驱动） */
export interface StrategyParamSchema {
  key: string
  label: string
  /** 参数类型：int/float 数值区间；enum 枚举选项集（vp-entry-strategy-integration D4） */
  type: 'int' | 'float' | 'enum'
  /** 默认值（enum 参数为选项 value 字符串，如 'mean'） */
  default: number | string
  /** int/float 参数的取值区间（enum 参数无该字段，由 options 声明合法取值集） */
  min?: number
  max?: number
  /** 参数说明（strategy-task-redesign D6）：创建/编辑表单参数名旁 tooltip 悬浮文案 */
  desc?: string
  /** enum 参数的选项集（type='enum' 时必填；提交取值必须在 options[].value 内，
   *  前端拦截 + 后端 422 兜底） */
  options?: { value: string; label: string }[]
  /** float 参数输入精度（strategy-signal-outcome D12/6.9）：el-input-number 的
   *  precision；缺省按 default 小数位推导（0.05 → 2；2.0 → 1；int → 0）。
   *  展示元数据键，不参与取值校验（后端 validate_params 放行，同 desc 先例） */
  precision?: number
  /** float 参数输入步进（el-input-number 的 step）；缺省按 precision 推导
   *  10^-precision（如 0.01）；int 缺省 1 */
  step?: number
}

/** 策略状态声明（states 项）：信号生命周期状态 + 展示色（映射 badge 样式类） */
export interface StrategyStateDecl {
  value: string
  label: string
  /** 展示色声明：info→badge--info / warning→badge--warning / danger→badge--rise / success→badge--fall */
  color: 'info' | 'warning' | 'danger' | 'success'
}

/** 策略私有列声明（columns 项）：信号列表的动态列（取值先 payload[key]、
 *  无该键时回退行级字段——ret_7d/ret_14d/ret_30d/outcome 为行级绩效列、
 *  entry_ref_price 为行级 B 点价格列，均不在 payload）
 *  date/int/float → 数值与日期格式化；str → 原样字符串（如触发方式/Spring 标记）；
 *  pct → 涨跌百分比（小数 0.173 → +17.3%，正涨红 var(--rise)/负跌绿 var(--fall)、
 *  空值 '--'，strategy-signal-outcome D7）；
 *  price_pct → 合并单元格「价格 | 涨跌幅」（D12，如 `9.81 | +6.2%`）：
 *  价格分量取 priceKey、涨幅分量取 pctKey（均为 payload 先、行级回退的双路径），
 *  涨幅渲染规则同 pct；outcome → 成功判定 badge
 *  （success 成功绿 / failed 失败红 / pending 待定灰 / null '--'） */
export interface StrategyColumnDecl {
  key: string
  label: string
  type: 'date' | 'int' | 'float' | 'str' | 'pct' | 'price_pct' | 'outcome'
  /** price_pct 列价格分量取值 key（如 'a_close'；type='price_pct' 时必填） */
  priceKey?: string
  /** price_pct 列涨幅分量取值 key（如 'a_pct'；type='price_pct' 时必填） */
  pctKey?: string
}

/** 任务股票范围来源（design D3）：'all' = 全量 A 股（默认排 ST/*ST），scope_codes 为 null */
export type StrategyTaskScopeType = 'manual' | 'watchlist' | 'bsp_query' | 'all'

/** 任务形态（design D1）：test 一次性测试 / persistent 长期任务（挂 EOD 日终调度） */
export type StrategyTaskMode = 'test' | 'persistent'

/** 任务状态（design D1）：pending 待执行 / running 执行中 / paused 已暂停 / done 已完成 */
export type StrategyTaskStatus = 'pending' | 'running' | 'paused' | 'done'

/** 策略任务（strategy_task，策略执行的原子单位：参数/范围可编辑、两种续跑、转正冻结） */
export interface StrategyTask {
  id: number
  /** 所属策略定义 id */
  strategy_id: string
  /** 用户命名 */
  label: string
  /** 用户自定义分组（纯组织性标签，无独立分组表） */
  user_group: string
  /** 当前生效参数（按定义 params_schema 校验；int/float → 数值，enum → 选项 value 字符串） */
  params: Record<string, number | string>
  /** 参数版本号（每次参数编辑 +1；信号行携带产生它时的版本） */
  params_version: number
  scope_type: StrategyTaskScopeType
  /** 显式范围：固化快照 code 列表；scope_type='all' 时为 null */
  scope_codes: string[] | null
  mode: StrategyTaskMode
  status: StrategyTaskStatus
  /** 进度：已扫股票数 / 总股票数 */
  progress_scanned: number
  progress_total: number
  /** 信号计数（列表/树节点 badge 用，后端联查返回） */
  signal_count: number
  created_by: string
  created_at: number
  updated_at: number
}

// ---------------------------------------------------------------------------
// 任务详情 detail_schema 积木块（design D5）
// v1 类型全集：summary / signals / per_stock / kv / timeline；
// 渲染器为 Front/src/views/strategy/detail_blocks/ 通用积木组件，按声明顺序渲染。
// ---------------------------------------------------------------------------

/** summary 块：汇总面板（进度/总数/匹配数/失败数），无附加声明字段 */
export interface DetailBlockSummary {
  type: 'summary'
}

/** signals 块：该任务信号表格（复用信号列表列声明） */
export interface DetailBlockSignals {
  type: 'signals'
}

/** per_stock 块：逐股结果表格（scope_type='all' 时后端不返回数据、前端静默隐藏） */
export interface DetailBlockPerStock {
  type: 'per_stock'
}

/** kv 块：键值摘要块，items 的取值来自 payload 聚合或任务字段 */
export interface DetailBlockKvItem {
  /** 展示标签 */
  label: string
  /** 取值来源：detail API 响应的 kv_payload 键名 */
  key: string
  /** 值格式化类型：pct = 小数转百分比（0.173 → 17.3%，绩效统计项用，
   *  strategy-signal-outcome D7：accuracy/avg_ret_* 为小数或 null） */
  fmt?: 'int' | 'float' | 'str' | 'pct'
}

export interface DetailBlockKv {
  type: 'kv'
  /** 块标题（无则缺省「策略摘要」） */
  title?: string
  items: DetailBlockKvItem[]
}

/** timeline 块：时间线（信号日期序列 + 状态演进） */
export interface DetailBlockTimeline {
  type: 'timeline'
}

/** chart 块：信号日期分布图（design D5 v1 可支持 date_histogram；当前 mock 定义未声明） */
export interface DetailBlockChart {
  type: 'chart'
}

/** detail_schema 积木块声明（联合类型，按定义声明顺序渲染） */
export type DetailBlockDecl =
  | DetailBlockSummary
  | DetailBlockSignals
  | DetailBlockPerStock
  | DetailBlockKv
  | DetailBlockTimeline
  | DetailBlockChart

/** 策略定义（代码注册，用户不可增删；表单/状态/私有列/任务详情均由声明驱动渲染） */
export interface StrategyDefinition {
  id: string
  name: string
  group_name: string
  sort: number
  /** 每项含 desc（参数说明，表单 tooltip 消费） */
  params_schema: StrategyParamSchema[]
  states: StrategyStateDecl[]
  columns: StrategyColumnDecl[]
  /** 任务详情展示声明（design D5 积木块序列；新策略注册必填） */
  detail_schema: DetailBlockDecl[]
  /** 定义下的任务树（后端联查返回，含各任务信号计数） */
  tasks: StrategyTask[]
}

/** 策略信号行（GET /api/strategy/signals 分页项；挂 task_id 维度） */
export interface StrategySignalRow {
  code: string
  name: string
  industries: string[]
  /** 信号日期（YYYY-MM-DD，闭区间筛选参数同格式） */
  signal_date: string
  /** 取值域 = 所属策略定义声明的 states */
  state: string
  is_buy: boolean
  entry_ref_price: number
  stop_ref_price: number
  /** 策略私有字段（按 columns 声明的 key 取值渲染；A/B 点过程字段
   *  a_date/a_close/a_pct/b_date/close_7d/14d/30d 亦在此，D10；
   *  过程字段缺键或越界（数据不足）时值为 null） */
  payload: Record<string, number | string | null>
  /** 产生该信号的参数版本（strategy-task-redesign：混合参数任务按版本归因） */
  params_version: number
  /** 信号绩效四字段（strategy-signal-outcome D1 行级独立列，非 payload）：
   *  入场日后 +7/+14/+30 日收益率（小数 0.173 = +17.3%，NULL = 数据不足/无绩效）
   *  与成功判定（success/failed/pending；NULL = 旧信号无绩效）。
   *  行级字段按 columns 声明的 ret_7d/ret_14d/ret_30d/outcome key 渲染。 */
  ret_7d?: number | null
  ret_14d?: number | null
  ret_30d?: number | null
  outcome?: 'success' | 'failed' | 'pending' | null
}

/** 逐股结果行（strategy_task_stock_result，detail API per_stock 块数据；显式范围任务才有） */
export interface StrategyTaskStockResult {
  code: string
  name: string
  /** 是否命中策略 */
  matched: boolean
  /** 执行状态：'ok' | 'failed' */
  run_status: 'ok' | 'failed'
  /** 失败原因 / 摘要 */
  message: string
  /** matched 时冗余信号日期 */
  signal_date: string | null
  /** 该行结果产生时的参数版本 */
  params_version: number
  /** 执行时间（ms 时间戳） */
  executed_at: number
}

/** 任务详情响应（GET /api/strategy/tasks/{id}/detail，design D5） */
export interface StrategyTaskDetail {
  /** 任务行（含进度/参数/范围） */
  task: StrategyTask
  /** 汇总计数（summary 块消费：匹配/失败/进度聚合） */
  summary: {
    total: number
    scanned: number
    matched: number
    failed: number
  }
  /** kv 块取值载荷（key → 值，声明 items[].key 取值；值可为 null——
   *  绩效统计 accuracy/avg_ret_* 无样本时为 null，前端显示 '--'） */
  kv_payload: Record<string, number | string | null>
  /** 逐股结果（scope='all' 时后端不返回该键 → undefined，per_stock 块静默隐藏） */
  per_stock?: StrategyTaskStockResult[]
  /** 任务信号首页（signals 块初始数据，同信号列表分页结构） */
  signals_page: PageRes<StrategySignalRow>
  /** 所属策略定义（states/columns/detail_schema 声明随详情返回，渲染器消费） */
  definition: {
    id: string
    name: string
    group_name: string
    params_schema: StrategyParamSchema[]
    states: StrategyStateDecl[]
    columns: StrategyColumnDecl[]
    detail_schema: DetailBlockDecl[]
  }
  /** 时间线事件（timeline 块消费：信号日期序列 + 状态演进） */
  timeline: { date: string; event: string; state: string }[]
}

// ---------------------------------------------------------------------------
// 绩效
// ---------------------------------------------------------------------------
/** 绩效统计行（GET /performance/stats，按 (bsp_type, kl_type) 分组聚合） */
export interface PerformanceStat {
  /** 买卖点类型原始枚举（'2s'/'1'/…，展示由前端 bspLabel 映射） */
  bsp_type: string
  /** K 线周期分组维度（'30m'/'60m'/'D'/'W'/'M'） */
  kl_type: string
  samples: number
  win_rate: number
  avg_pnl: number
  profit_ratio: number
  /** 期望值（胜率×平均盈利 − 败率×|平均亏损|，单位 %） */
  expectancy: number
}

export interface PerformanceSample {
  id: number
  code: string
  name: string
  bsp_type: string
  /** K 线周期（'30m'/'60m'/'D'/'W'/'M'） */
  kl_type: string
  /** 信号来源（缺省视为 'chan'，与后端兜底语义一致） */
  source_type?: 'chan' | 'strategy' | 'watchlist'
  /** source_type='strategy' 时的任务 id（来源树 strategy:<id> 过滤用；原 instance_id 废弃） */
  task_id?: number
  /** source_type='strategy' 时的「策略名·任务名·状态」标签 */
  strategy_label?: string
  direction: 'buy' | 'sell'
  bsp_price: number
  end_price: number
  profit: number
  bsp_date: number
  end_date: number
  hold_days: number
  /** 归因摘要（未归因为空串/缺省） */
  attribution?: string
  /** 监控分组 id（null = 未分组；design D9 分组维度过滤用，后端缺省返回 null/0 时视为未分组） */
  group_id?: number | null
}

// ---------------------------------------------------------------------------
// 选股
// ---------------------------------------------------------------------------
export interface Strategy {
  id: number
  name: string
  description: string
  bsp_types: string[]
  kl_type: string
  industries: string[]
  status: 'active' | 'inactive'
  last_run?: number
  result_count?: number
}

export interface ScreenerResult {
  code: string
  name: string
  industries: string[]
  bsp_type: string
  price: number
  change_pct: number
  score: number
}

// ---------------------------------------------------------------------------
// 预警
// ---------------------------------------------------------------------------
export interface AlertRule {
  id: number
  name: string
  code: string
  stock_name: string
  condition: string
  kl_type: string
  enabled: boolean
  trigger_count: number
  created_at: number
}

export interface AlertNotification {
  id: number
  rule_id: number
  rule_name: string
  code: string
  stock_name: string
  message: string
  triggered_at: number
  read: boolean
}

// ---------------------------------------------------------------------------
// 系统管理
// ---------------------------------------------------------------------------
export interface User {
  id: number
  username: string
  nickname: string
  role: string
  role_name: string
  status: 'active' | 'disabled'
  created_at: number
}

export interface Role {
  id: number
  name: string
  code: string
  description: string
  user_count: number
  perms: string[]
  /** 内置 admin 角色：删除/权限修改受保护（design D2） */
  is_admin: boolean
}

export interface Permission {
  id: number
  code: string
  name: string
  category: string
}

// ---------------------------------------------------------------------------
// 大模型问答
// ---------------------------------------------------------------------------
export interface QaRecord {
  id: number
  question: string
  answer: string
  starred: boolean
  created_at: number
}

/** 系统提示词读写（GET/PUT /api/qa/system-prompt，按用户隔离，空值回退内置默认） */
export interface SystemPromptInfo {
  prompt: string
}

/** ask SSE 流式事件回调（design D8.2：delta / done / error 三事件） */
export interface QaStreamHandlers {
  /** LLM 增量文本 */
  onDelta: (text: string) => void
  /** 生成完成且落库成功，携带完整记录（可异步刷新列表） */
  onDone: (record: QaRecord) => void | Promise<void>
  /** 生成/落库失败（不产生残缺记录） */
  onError: (detail: string) => void
}

// ---------------------------------------------------------------------------
// LLM 供应商（design D8.1：cc-switch 式预设切换，manage 权限管理）
// ---------------------------------------------------------------------------
/** 供应商预设（api_key 已脱敏，仅尾 4 位明文） */
export interface LlmProvider {
  id: number
  name: string
  base_url: string
  api_key: string
  model: string
  active: boolean
}

/** 新增供应商请求体 */
export interface LlmProviderInput {
  name: string
  base_url: string
  api_key: string
  model: string
}

/** 测试连接结果 */
export interface LlmTestResult {
  ok: boolean
  detail: string
}
