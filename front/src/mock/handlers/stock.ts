import { http, HttpResponse, delay } from 'msw'
import { findStock, stocks, allIndustries } from '../data/stocks'

export const stockHandlers = [
  http.get('/api/stocks/:code/profile', async ({ params }) => {
    await delay(200)
    const stock = findStock(params.code as string)
    if (!stock) {
      return HttpResponse.json({ detail: '股票不存在' }, { status: 404 })
    }
    return HttpResponse.json(stock)
  }),

  /** 搜索股票（名称/编码） */
  http.get('/api/stocks', async ({ request }) => {
    await delay(200)
    const url = new URL(request.url)
    const q = (url.searchParams.get('q') || '').toLowerCase()
    const limit = Number(url.searchParams.get('page_size') || 30)
    if (!q) return HttpResponse.json(stocks.slice(0, limit))
    const result = stocks.filter(
      (s) => s.code.toLowerCase().includes(q) || s.name.toLowerCase().includes(q),
    ).slice(0, limit)
    return HttpResponse.json(result)
  }),

  /** 行业列表 */
  http.get('/api/stocks/industries', async () => {
    await delay(200)
    return HttpResponse.json(allIndustries)
  }),
]
