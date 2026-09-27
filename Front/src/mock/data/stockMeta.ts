import type { StockMeta } from '@/api/types'
import type { MockStock } from './stocks'

/**
 * 股票元数据 mock（kline-stock-metadata 契约，D10）
 * 三种形态：
 *   ① 字段齐全     — sz.000001 平安银行
 *   ② 稀疏字段为空 — sh.600519 贵州茅台（profile 域未同步：A/C/B 为空，D 快照正常）
 *   ③ holders 空   — sz.000858 五粮液（股东户数序列为空数组）
 * 其余 mock 股票走 buildDefaultMeta（快照缺失 + 档案稀疏 + holders 空）。
 */

/** 形态①：字段齐全 */
const fullMeta: StockMeta = {
  code: 'sz.000001',
  name: '平安银行',
  exchange: '深圳证券交易所',
  ipo_date: '1991-04-03',
  board: '主板',
  full_name: '平安银行股份有限公司',
  en_name: 'Ping An Bank Co., Ltd.',
  former_names: '深发展A;深发展',
  legal_person: '谢永林',
  reg_capital: '194.06亿元',
  found_date: '1987-12-22',
  website: 'bank.pingan.com',
  email: 'pab@pingan.com.cn',
  phone: '0755-82080387',
  fax: '0755-82080386',
  reg_addr: '广东省深圳市罗湖区深南东路5047号',
  office_addr: '广东省深圳市福田区益田路5023号平安金融中心B座',
  postal_code: '518001',
  main_business: '吸收公众存款；发放短期、中期和长期贷款；办理国内外结算；办理票据承兑与贴现；发行金融债券；代理发行、代理兑付、承销政府债券；买卖政府债券、金融债券；从事同业拆借；买卖、代理买卖外汇；从事银行卡业务；提供信用证服务及担保；代理收付款项及代理保险业务；提供保管箱服务；结汇、售汇业务；黄金业务；证券投资基金销售业务等。',
  business_scope:
    '办理人民币存、贷、结算、汇兑业务；人民币票据承兑和贴现；各类汇兑业务；外汇存款、借款、贷款及境外借款；国际结算、结汇、售汇；同业拆借；提供信用证服务及担保；代理收付款项及代理保险业务；提供保险箱业务；股票、证券投资基金、企业年金及其他金融资产的托管业务；离岸银行业务；资信调查、咨询、见证业务；企业、个人财务顾问服务等。（依法须经批准的项目，经相关部门批准后方可开展经营活动）',
  intro:
    '平安银行股份有限公司是中国内地首家公开上市的全国性股份制商业银行，前身为深圳发展银行。本行以打造「中国最卓越、全球领先的智能化零售银行」为战略目标，持续深化零售转型，对公业务精耕细作，金融科技赋能创新，致力于为个人、企业和政府客户提供专业、便利、高效的综合金融服务。',
  price: 11.85,
  total_mv: 2301.25,
  float_mv: 2301.22,
  pe_ttm: 4.52,
  pb: 0.49,
  turnover_rate: 0.68,
  main_net_inflow: -12345.6,
  snapshot_at: '2026-09-26T07:30:00.000Z',
  tags: ['低估值', '高股息', '核心资产'],
  notes: '长期关注标的，零售转型进展跟踪中。分红稳定，适合底仓配置。',
  holders: [
    { stat_date: '2025-09-30', holder_num: 512345 },
    { stat_date: '2025-12-31', holder_num: 505210 },
    { stat_date: '2026-03-31', holder_num: 498760 },
    { stat_date: '2026-06-30', holder_num: 487120 },
    { stat_date: '2026-08-31', holder_num: 478933 },
    { stat_date: '2026-09-20', holder_num: 471205 },
  ],
}

/** 形态②：稀疏字段为空（profile 域未同步，A/C/B 组空值、D 组快照正常） */
const sparseMeta: StockMeta = {
  code: 'sh.600519',
  name: '贵州茅台',
  exchange: '上海证券交易所',
  ipo_date: '2001-08-27',
  board: '主板',
  full_name: '',
  en_name: '',
  former_names: '',
  legal_person: '',
  reg_capital: '',
  found_date: null,
  website: '',
  email: '',
  phone: '',
  fax: '',
  reg_addr: '',
  office_addr: '',
  postal_code: '',
  main_business: '',
  business_scope: '',
  intro: '',
  price: 1685.5,
  total_mv: 21170.8,
  float_mv: 21170.8,
  pe_ttm: 22.35,
  pb: 7.12,
  turnover_rate: 0.21,
  main_net_inflow: 8320.5,
  snapshot_at: '2026-09-26T07:30:00.000Z',
  tags: [],
  notes: '',
  holders: [
    { stat_date: '2026-03-31', holder_num: 155230 },
    { stat_date: '2026-06-30', holder_num: 152110 },
    { stat_date: '2026-09-15', holder_num: 149884 },
  ],
}

/** 形态③：holders 空序列（其余字段齐全） */
const emptyHoldersMeta: StockMeta = {
  code: 'sz.000858',
  name: '五粮液',
  exchange: '深圳证券交易所',
  ipo_date: '1998-04-27',
  board: '主板',
  full_name: '宜宾五粮液股份有限公司',
  en_name: 'Wuliangye Yibin Co., Ltd.',
  former_names: '',
  legal_person: '曾从钦',
  reg_capital: '38.82亿元',
  found_date: '1998-04-21',
  website: 'www.wuliangye.com.cn',
  email: '000858-wly@sohu.com',
  phone: '0831-3567000',
  fax: '',
  reg_addr: '四川省宜宾市翠屏区岷江西路150号',
  office_addr: '四川省宜宾市翠屏区岷江西路150号',
  postal_code: '644007',
  main_business: '酒类产品的生产和销售。',
  business_scope:
    '酒类及相关产品的生产、销售；包装材料、玻璃制品的生产、销售；物业管理；住宿、餐饮服务（仅限分支机构经营）。',
  intro: '',
  price: 142.3,
  total_mv: 5523.4,
  float_mv: 5523.4,
  pe_ttm: 15.6,
  pb: 3.42,
  turnover_rate: 0.55,
  main_net_inflow: null,
  snapshot_at: '2026-09-26T07:30:00.000Z',
  tags: ['白马股', '消费龙头'],
  notes: '',
  holders: [],
}

export const stockMetas: Record<string, StockMeta> = {
  'sz.000001': fullMeta,
  'sh.600519': sparseMeta,
  'sz.000858': emptyHoldersMeta,
}

/**
 * 其余 mock 股票兜底形态：快照缺失（数值 null、snapshot_at null）
 * + 档案稀疏 + holders 空序列，用于验证快照缺失时的占位展示。
 */
export function buildDefaultMeta(stock: MockStock): StockMeta {
  return {
    code: stock.code,
    name: stock.name,
    exchange: '',
    ipo_date: null,
    board: '',
    full_name: '',
    en_name: '',
    former_names: '',
    legal_person: '',
    reg_capital: '',
    found_date: null,
    website: '',
    email: '',
    phone: '',
    fax: '',
    reg_addr: '',
    office_addr: '',
    postal_code: '',
    main_business: '',
    business_scope: '',
    intro: '',
    price: null,
    total_mv: null,
    float_mv: null,
    pe_ttm: null,
    pb: null,
    turnover_rate: null,
    main_net_inflow: null,
    snapshot_at: null,
    tags: [],
    notes: '',
    holders: [],
  }
}
