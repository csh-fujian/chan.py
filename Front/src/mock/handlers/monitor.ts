import { http, HttpResponse, delay } from 'msw'
import { monitorItems, completedItems, getProfitSeries, generateAttribution } from '../data/monitor'
import { activeLlmProvider } from '../data/system'
import { stocks } from '../data/stocks'

export const monitorHandlers = [
  http.get('/api/monitor', async ({ request }) => {
    await delay(300)
    const url = new URL(request.url)
    const keyword = url.searchParams.get('keyword') || ''
    let list = monitorItems
    if (keyword) list = list.filter((r) => r.code.includes(keyword) || r.name.includes(keyword))
    return HttpResponse.json(list)
  }),

  // 行级加入监控（bsp-page-change 4.5）：与真后端 POST /api/monitor 语义一致——
  // code 缺失 / entry_price 为 0 → 422；成功插入 mock 列表并返回创建结果
  http.post('/api/monitor', async ({ request }) => {
    await delay(300)
    let body: { code?: string; kl_type?: string; entry_price?: number; monitor_start_time?: string } | undefined
    try {
      const parsed: unknown = await request.json()
      if (parsed && typeof parsed === 'object') body = parsed as typeof body
    } catch {
      return HttpResponse.json({ detail: '请求体不是合法 JSON' }, { status: 422 })
    }
    const code = (body?.code || '').trim()
    const entryPrice = Number(body?.entry_price) || 0
    if (!code) {
      return HttpResponse.json({ detail: 'code is required' }, { status: 422 })
    }
    if (!entryPrice) {
      return HttpResponse.json({ detail: 'entry_price is required' }, { status: 422 })
    }
    const klType = body?.kl_type || 'K_DAY'
    const startTime = body?.monitor_start_time || ''
    const stock = stocks.find((s) => s.code === code)
    // mock 侧维护自增 id（与真后端 RETURNING id 语义一致）
    const id = mockNextId++
    const item = {
      id,
      code,
      name: stock?.name || code,
      industries: stock?.industries || [],
      bsp_type: '',
      direction: 'buy' as const,
      bsp_price: entryPrice,
      current_price: stock?.price || 0,
      bsp_date: Date.parse(startTime) || Date.now(),
      kl_type: klType,
      change_pct: 0,
      // 新建监控尚无收益率（D8：current_pnl_pct 可空，渲染兜底 --）
      current_pnl_pct: null,
      max_profit: 0,
      max_drawdown: 0,
      status: 'monitoring' as const,
    }
    monitorItems.push(item)
    // 返回真后端 create_monitor 的行结构（_row_to_dict）
    return HttpResponse.json({
      id,
      code,
      kl_type: klType,
      monitor_start_time: startTime,
      entry_price: entryPrice,
      status: 'monitoring',
      sold_price: null,
      sold_at: null,
      pnl_pct: null,
      created_at: new Date().toISOString(),
      name: item.name,
    })
  }),

  http.get('/api/monitor/completed', async ({ request }) => {
    await delay(300)
    const url = new URL(request.url)
    const keyword = url.searchParams.get('keyword') || ''
    let list = completedItems
    if (keyword) list = list.filter((r) => r.code.includes(keyword) || r.name.includes(keyword))
    return HttpResponse.json(list)
  }),

  http.get('/api/monitor/profit-series', async () => {
    await delay(200)
    return HttpResponse.json(getProfitSeries())
  }),

  http.post('/api/monitor/:id/end', async ({ params }) => {
    await delay(300)
    return HttpResponse.json({ success: true, id: Number(params.id) })
  }),

  // 大模型归因（design D5：真实生成；未配置/盈利≥5 → 400，调用失败 → 502，均不写占位）
  http.post('/api/monitor/:id/analyze', async ({ params }) => {
    await delay(1500)
    const item = completedItems.find((c) => c.id === Number(params.id))
    if (!item) return HttpResponse.json({ detail: `Monitor ${params.id} not found` }, { status: 404 })
    // 后端校验最终盈利 < 5% 才执行（与前端过滤双侧一致）
    if (item.profit >= 5) {
      return HttpResponse.json({ detail: '盈利不低于 5%，不纳入亏损归因' }, { status: 400 })
    }
    // 未配置激活 LLM 供应商 → 400
    const provider = activeLlmProvider()
    if (!provider) {
      return HttpResponse.json({ detail: 'LLM 未配置' }, { status: 400 })
    }
    // 供应商调用失败（mock：base_url 含 fail/invalid 模拟不可达）→ 502，不写占位记录
    if (/fail|invalid/i.test(provider.base_url)) {
      return HttpResponse.json(
        { detail: `大模型调用失败：无法访问 ${provider.base_url}` },
        { status: 502 },
      )
    }
    // 成功：返回真实结构的归因结果（模拟生成文本），并持久化到标的
    const record = generateAttribution(item)
    return HttpResponse.json({ success: true, id: item.id, attribution: [record] })
  }),
]

/** mock 侧自增 id（避开 data/monitor.ts 现有 id 1..7/9001 段） */
let mockNextId = 10001
