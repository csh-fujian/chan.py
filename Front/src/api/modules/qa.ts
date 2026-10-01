import client from '../client'
import { useAuthStore } from '@/stores/auth'
import type { QaRecord, QaStreamHandlers, SystemPromptInfo } from '../types'

export interface AskParams {
  question: string
  code?: string
  period?: string
}

/** SSE 结束事件（design D8.2：done 之前成功才落库，中断不产生残缺记录） */
type SseEvent =
  | { type: 'delta'; text: string }
  | { type: 'done'; record: QaRecord }
  | { type: 'error'; detail: string }

/**
 * 提问：SSE 流式回答（design D8.2）。
 * axios 无法读响应流，此处用原生 fetch + ReadableStream 解析；
 * 拦截器不生效，需手动携带 Authorization: Bearer（token 取自 auth store，与 axios 一致）。
 */
export async function askQuestionStream(
  params: AskParams,
  handlers: QaStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const auth = useAuthStore()
  const base = import.meta.env.VITE_API_BASE || '/api'
  let sawDone = false

  try {
    const res = await fetch(`${base}/qa`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(auth.token ? { Authorization: `Bearer ${auth.token}` } : {}),
      },
      body: JSON.stringify(params),
      signal,
    })

    if (!res.ok) {
      // 非 2xx（如 503 LLM 未配置）：尽量取错误原文
      let detail = `请求失败（HTTP ${res.status}）`
      try {
        const data = (await res.json()) as { message?: string; detail?: string }
        detail = data.detail || data.message || detail
      } catch {
        // 非 JSON 响应体，保留默认文案
      }
      handlers.onError(detail)
      return
    }
    if (!res.body) {
      handlers.onError('响应无内容流')
      return
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      // SSE 事件以空行分隔；跨 chunk 缓冲后按 \n\n 切事件
      let sep: number
      while ((sep = findEventSeparator(buf)) >= 0) {
        const raw = buf.slice(0, sep)
        buf = buf.slice(sep + separatorLength(buf, sep))
        const ev = parseSseEvent(raw)
        if (!ev) continue
        if (ev.type === 'delta') {
          handlers.onDelta(ev.text)
        } else if (ev.type === 'done') {
          sawDone = true
          await handlers.onDone(ev.record)
        } else {
          handlers.onError(ev.detail)
          void reader.cancel().catch(() => {
            // 流可能已被服务端关闭
          })
          return
        }
      }
    }
    if (!sawDone) {
      handlers.onError('连接中断，回答未完成')
    }
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') return // 用户中断，静默
    handlers.onError(e instanceof Error ? e.message : String(e))
  }
}

/** 事件分隔符定位（兼容 \r\n\r\n 与 \n\n） */
function findEventSeparator(buf: string): number {
  const a = buf.indexOf('\n\n')
  const b = buf.indexOf('\r\n\r\n')
  if (a < 0) return b
  if (b < 0) return a
  return Math.min(a, b)
}

function separatorLength(buf: string, sep: number): number {
  return buf.startsWith('\r\n\r\n', sep) ? 4 : 2
}

/** 解析单个 SSE 事件块：data: 前缀行（可多行）→ JSON */
function parseSseEvent(raw: string): SseEvent | null {
  const dataLines = raw
    .split(/\r?\n/)
    .filter((l) => l.startsWith('data:'))
    .map((l) => l.slice(5).replace(/^ /, ''))
  if (!dataLines.length) return null
  try {
    return JSON.parse(dataLines.join('\n')) as SseEvent
  } catch {
    console.warn('[askQuestionStream] 无法解析 SSE 事件', { raw })
    return null
  }
}

/** 获取问答记录列表（本人，时间倒序） */
export function getQaRecords() {
  return client.get<unknown, QaRecord[]>('/qa')
}

/** 单条打星/取消收藏 */
export function starQaRecord(id: number, starred: boolean) {
  return client.patch<unknown, { success: boolean }>(`/qa/${id}/star`, { starred })
}

/** 批量打星 */
export function batchStarQa(ids: number[], starred: boolean) {
  return client.post<unknown, { success: boolean }>('/qa/star', { ids, starred })
}

/** 一键删除未打星记录 */
export function deleteUnstarredQa() {
  return client.delete<unknown, { success: boolean }>('/qa/unstarred')
}

/** 读取系统提示词（按用户，未设置返回内置默认） */
export function getSystemPrompt() {
  return client.get<unknown, SystemPromptInfo>('/qa/system-prompt')
}

/** 保存系统提示词（空串 = 恢复默认） */
export function updateSystemPrompt(prompt: string) {
  return client.put<unknown, { success: boolean }>('/qa/system-prompt', { prompt })
}
