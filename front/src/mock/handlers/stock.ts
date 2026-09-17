import { http, HttpResponse, delay } from 'msw'
import { findStock } from '../data/stocks'

export const stockHandlers = [
  http.get('/api/stocks/:code/profile', async ({ params }) => {
    await delay(200)
    const stock = findStock(params.code as string)
    if (!stock) {
      return HttpResponse.json({ detail: '股票不存在' }, { status: 404 })
    }
    return HttpResponse.json(stock)
  }),
]
