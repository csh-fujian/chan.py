import { http, HttpResponse, delay } from 'msw'
import { findStock, stocks, allIndustries } from '../data/stocks'
import { stockMetas, buildDefaultMeta } from '../data/stockMeta'

export const stockHandlers = [
  http.get('/api/stocks/:code/profile', async ({ params }) => {
    await delay(200)
    const stock = findStock(params.code as string)
    if (!stock) {
      return HttpResponse.json({ detail: '股票不存在' }, { status: 404 })
    }
    return HttpResponse.json(stock)
  }),

  /** 股票元数据（kline-stock-metadata 契约）：库外 code 404，库内恒定全键 */
  http.get('/api/stocks/:code/meta', async ({ params }) => {
    await delay(250)
    const code = params.code as string
    const stock = findStock(code)
    if (!stock) {
      return HttpResponse.json({ detail: '股票不存在' }, { status: 404 })
    }
    return HttpResponse.json(stockMetas[code] ?? buildDefaultMeta(stock))
  }),

  /** 搜索股票（编号/名称/名称拼音首字母 三列子串匹配，大小写不敏感） */
  http.get('/api/stocks', async ({ request }) => {
    await delay(200)
    const url = new URL(request.url)
    const q = (url.searchParams.get('q') || '').toLowerCase()
    const limit = Number(url.searchParams.get('page_size') || 30)
    if (!q) return HttpResponse.json(stocks.slice(0, limit))
    const result = stocks.filter(
      (s) =>
        s.code.toLowerCase().includes(q) ||
        s.name.toLowerCase().includes(q) ||
        s.name_py.toLowerCase().includes(q),
    ).slice(0, limit)
    return HttpResponse.json(result)
  }),

  /** 行业列表 */
  http.get('/api/stocks/industries', async () => {
    await delay(200)
    return HttpResponse.json(allIndustries)
  }),
]
