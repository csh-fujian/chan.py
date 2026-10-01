import { http, HttpResponse, delay } from 'msw'
import { monitorItems, completedItems, getProfitSeries, generateAttribution } from '../data/monitor'
import { activeLlmProvider } from '../data/system'

export const monitorHandlers = [
  http.get('/api/monitor', async ({ request }) => {
    await delay(300)
    const url = new URL(request.url)
    const keyword = url.searchParams.get('keyword') || ''
    let list = monitorItems
    if (keyword) list = list.filter((r) => r.code.includes(keyword) || r.name.includes(keyword))
    return HttpResponse.json(list)
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
