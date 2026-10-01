import { http, HttpResponse, delay } from 'msw'
import {
  watchFolders,
  addFolder,
  removeFolder,
  renameFolder,
  addStockToFolder,
  removeStockFromFolder,
  moveStock,
  getWatchStocks,
  reorderFolders,
  reorderFolderStocks,
} from '../data/watchlist'

export const watchlistHandlers = [
  http.get('/api/watchlist/folders', async () => {
    await delay(200)
    return HttpResponse.json(watchFolders)
  }),

  http.post('/api/watchlist/folders', async ({ request }) => {
    await delay(200)
    const body = await request.json() as { name: string }
    const f = addFolder(body.name)
    return HttpResponse.json(f)
  }),

  http.delete('/api/watchlist/folders/:id', async ({ params }) => {
    await delay(200)
    removeFolder(Number(params.id))
    return HttpResponse.json({ success: true })
  }),

  http.patch('/api/watchlist/folders/:id', async ({ params, request }) => {
    await delay(150)
    const body = await request.json() as { name: string }
    renameFolder(Number(params.id), body.name)
    return HttpResponse.json({ success: true })
  }),

  http.get('/api/watchlist/folders/:id/stocks', async ({ params, request }) => {
    await delay(200)
    // q：按编码/名称不区分大小写子串过滤（与真实后端一致）
    const q = new URL(request.url).searchParams.get('q') ?? ''
    return HttpResponse.json(getWatchStocks(Number(params.id), q))
  }),

  http.put('/api/watchlist/folders/reorder', async ({ request }) => {
    await delay(200)
    const body = (await request.json()) as { ids: number[] }
    reorderFolders(body.ids ?? [])
    return HttpResponse.json({ success: true })
  }),

  http.put('/api/watchlist/folders/:id/stocks/reorder', async ({ params, request }) => {
    await delay(200)
    const body = (await request.json()) as { codes: string[] }
    reorderFolderStocks(Number(params.id), body.codes ?? [])
    return HttpResponse.json({ success: true })
  }),

  http.post('/api/watchlist/folders/:id/stocks', async ({ params, request }) => {
    await delay(200)
    const body = await request.json() as { code: string }
    addStockToFolder(Number(params.id), body.code)
    return HttpResponse.json({ success: true })
  }),

  http.delete('/api/watchlist/folders/:id/stocks/:code', async ({ params }) => {
    await delay(200)
    removeStockFromFolder(Number(params.id), params.code as string)
    return HttpResponse.json({ success: true })
  }),

  http.post('/api/watchlist/move', async ({ request }) => {
    await delay(200)
    const body = await request.json() as { from: number; to: number; code: string }
    moveStock(body.from, body.to, body.code)
    return HttpResponse.json({ success: true })
  }),
]
