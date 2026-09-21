import { http, HttpResponse, delay } from 'msw'
import { listQa, askQa, starQa, batchStarQa, deleteUnstarredQa } from '../data/qa'

export const qaHandlers = [
  http.get('/api/qa', async () => {
    await delay(200)
    return HttpResponse.json(listQa())
  }),

  http.post('/api/qa', async ({ request }) => {
    await delay(600)
    const body = await request.json() as { question: string }
    const rec = askQa(body.question)
    return HttpResponse.json(rec)
  }),

  http.patch('/api/qa/:id/star', async ({ params, request }) => {
    await delay(150)
    const body = await request.json() as { starred: boolean }
    starQa(Number(params.id), body.starred)
    return HttpResponse.json({ success: true })
  }),

  http.post('/api/qa/star', async ({ request }) => {
    await delay(150)
    const body = await request.json() as { ids: number[]; starred: boolean }
    batchStarQa(body.ids, body.starred)
    return HttpResponse.json({ success: true })
  }),

  http.delete('/api/qa/unstarred', async () => {
    await delay(200)
    const count = deleteUnstarredQa()
    return HttpResponse.json({ success: true, count })
  }),
]
