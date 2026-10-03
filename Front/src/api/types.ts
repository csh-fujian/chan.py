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
// 绩效
// ---------------------------------------------------------------------------
export interface PerformanceStat {
  bsp_type: string
  samples: number
  win_rate: number
  avg_pnl: number
  profit_ratio: number
}

export interface PerformanceSample {
  id: number
  code: string
  name: string
  bsp_type: string
  direction: 'buy' | 'sell'
  bsp_price: number
  end_price: number
  profit: number
  bsp_date: number
  end_date: number
  hold_days: number
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
