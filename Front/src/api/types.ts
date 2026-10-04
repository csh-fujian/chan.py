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
  /** 策略来源所属实例（source_type='strategy' 时随信号携带） */
  instance_id?: number
  /** 策略来源展示标签（「策略名 · 实例名 · 状态」，后端/mock 填充；chan/watchlist 来源不传） */
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
// 策略信号（strategy-signal-page design D5）
// 命名区分：本节的 StrategyDefinition/StrategyInstance/StrategySignalRow 是
// 策略引擎的「策略定义 / 参数实例 / 信号」三层实体（schema 驱动、实例不可变），
// 与上方选股器的 Strategy（缠论买卖点过滤器）是完全不同的概念，刻意不共用命名。
// ---------------------------------------------------------------------------
/** 策略参数声明（params_schema 项）：动态渲染实例表单项（int/float → el-input-number） */
export interface StrategyParamSchema {
  key: string
  label: string
  type: 'int' | 'float'
  default: number
  min: number
  max: number
}

/** 策略状态声明（states 项）：信号生命周期状态 + 展示色（映射 badge 样式类） */
export interface StrategyStateDecl {
  value: string
  label: string
  /** 展示色声明：info→badge--info / warning→badge--warning / danger→badge--rise / success→badge--fall */
  color: 'info' | 'warning' | 'danger' | 'success'
}

/** 策略私有列声明（columns 项）：信号列表的动态列（值取自 payload[key]） */
export interface StrategyColumnDecl {
  key: string
  label: string
  type: 'date' | 'int' | 'float'
}

/** 策略实例（不可变：改参数 = 新建实例；历史信号随实例保留） */
export interface StrategyInstance {
  id: number
  label: string
  params: Record<string, number>
  enabled: boolean
  signal_count: number
}

/** 策略定义（代码注册，用户不可增删；前端表单/状态/私有列均由声明驱动渲染） */
export interface StrategyDefinition {
  id: string
  name: string
  group_name: string
  sort: number
  params_schema: StrategyParamSchema[]
  states: StrategyStateDecl[]
  columns: StrategyColumnDecl[]
  /** 定义下的实例树（后端联查返回，含各实例信号计数） */
  instances: StrategyInstance[]
}

/** 策略信号行（GET /api/strategy/signals 分页项） */
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
  /** 策略私有字段（按 columns 声明的 key 取值渲染） */
  payload: Record<string, number | string>
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
  /** source_type='strategy' 时的实例 id（来源树 strategy:<id> 过滤用） */
  instance_id?: number
  /** source_type='strategy' 时的「策略名·实例名·状态」标签 */
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
