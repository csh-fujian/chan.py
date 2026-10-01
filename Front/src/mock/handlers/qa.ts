import { http, HttpResponse, delay } from 'msw'
import {
  listQa,
  askQa,
  toQaRecord,
  starQa,
  batchStarQa,
  deleteUnstarredQa,
  getSystemPromptFor,
  setSystemPromptFor,
  mockAnswer,
  type AskContext,
} from '../data/qa'
import { activeLlmProvider } from '../data/system'
import { userIdFromRequest } from '../data/auth'

/** SSE 事件编码：data: {json}\n\n（design D8.2） */
function sseEncode(payload: object): Uint8Array {
  return new TextEncoder().encode(`data: ${JSON.stringify(payload)}\n\n`)
}

/**
 * 把预设回答切片，逐片延迟发出 delta，最后发 done（含新建记录）。
 * 中途 abort（reader cancel）则不落库，与「仅 done 之前成功才落库」契约一致。
 */
function sseFakeStream(
  pieces: string[],
  buildRecord: () => ReturnType<typeof askQa>,
): ReadableStream<Uint8Array> {
  let cancelled = false
  return new ReadableStream<Uint8Array>({
    async start(controller) {
      try {
        // 首 token 前的“思考”延迟
        await delay(400)
        for (const piece of pieces) {
          if (cancelled) return
          await delay(50 + Math.floor(Math.random() * 50))
          if (cancelled) return
          controller.enqueue(sseEncode({ type: 'delta', text: piece }))
        }
        if (cancelled) return
        const rec = buildRecord()
        controller.enqueue(sseEncode({ type: 'done', record: toQaRecord(rec) }))
        controller.close()
      } catch {
        // 流被中止/关闭：静默退出，不产生残缺记录
        try {
          controller.close()
        } catch {
          // 已关闭
        }
      }
    },
    cancel() {
      cancelled = true
    },
  })
}

export const qaHandlers = [
  // 记录列表：本人，时间倒序（design D4 按 user_id 隔离）
  http.get('/api/qa', async ({ request }) => {
    await delay(200)
    return HttpResponse.json(listQa(userIdFromRequest(request)))
  }),

  // 提问：SSE 流式（delta → done/error）
  http.post('/api/qa', async ({ request }) => {
    const userId = userIdFromRequest(request)
    const body = (await request.json()) as { question: string; code?: string; period?: string }
    const ctx: AskContext = { question: body.question, code: body.code, period: body.period }

    // 无激活预设且未配置 env（mock 简化为仅看预设）→ error 事件、不落库
    if (!activeLlmProvider()) {
      const stream = new ReadableStream<Uint8Array>({
        async start(controller) {
          await delay(200)
          controller.enqueue(sseEncode({ type: 'error', detail: 'LLM 未配置' }))
          controller.close()
        },
      })
      return new HttpResponse(stream, {
        headers: { 'Content-Type': 'text/event-stream; charset=utf-8' },
      })
    }

    // 预设回答按词/短句分片，模拟 LLM 流式输出
    const answer = mockAnswer(ctx, userId)
    const pieces: string[] = []
    for (let i = 0; i < answer.length; i += 4) {
      pieces.push(answer.slice(i, i + 4))
    }
    const stream = sseFakeStream(pieces, () => askQa(userId, ctx))
    return new HttpResponse(stream, {
      headers: { 'Content-Type': 'text/event-stream; charset=utf-8' },
    })
  }),

  http.patch('/api/qa/:id/star', async ({ params, request }) => {
    await delay(150)
    const body = await request.json() as { starred: boolean }
    starQa(userIdFromRequest(request), Number(params.id), body.starred)
    return HttpResponse.json({ success: true })
  }),

  http.post('/api/qa/star', async ({ request }) => {
    await delay(150)
    const body = await request.json() as { ids: number[]; starred: boolean }
    batchStarQa(userIdFromRequest(request), body.ids, body.starred)
    return HttpResponse.json({ success: true })
  }),

  http.delete('/api/qa/unstarred', async ({ request }) => {
    await delay(200)
    const count = deleteUnstarredQa(userIdFromRequest(request))
    return HttpResponse.json({ success: true, count })
  }),

  // 系统提示词（design D8.3：按用户，空值回退内置默认；恢复默认 = PUT 空串）
  http.get('/api/qa/system-prompt', async ({ request }) => {
    await delay(150)
    return HttpResponse.json({ prompt: getSystemPromptFor(userIdFromRequest(request)) })
  }),

  http.put('/api/qa/system-prompt', async ({ request }) => {
    await delay(200)
    const body = await request.json() as { prompt: string }
    setSystemPromptFor(userIdFromRequest(request), body.prompt ?? '')
    return HttpResponse.json({ success: true })
  }),
]
