import { http, HttpResponse, delay } from 'msw'
import { getChanResult } from '../data/kline'

export const klineHandlers = [
  http.get('/api/klines', async ({ request }) => {
    await delay(400)
    const url = new URL(request.url)
    const code = url.searchParams.get('symbol') || 'sz.000001'
    // period 参数预留，mock 生成器暂不区分周期，始终返回相同数据
    const result = getChanResult(code)
    return HttpResponse.json(result)
  }),
]
