import { http, HttpResponse, delay } from 'msw'
import {
  strategyDefinitions,
  strategySignals,
  addInstance,
  removeInstance,
  setInstanceEnabled,
  scanInstanceSignals,
} from '../data/strategy'

/**
 * 策略信号 MSW handlers（strategy-signal-page design D5 / 任务 5.2）：
 * 全部端点与后端契约对齐——
 *   GET  /api/strategy/definitions                  定义（含实例树+计数）
 *   POST /api/strategy/instances                    新建实例（参数校验 422）
 *   DELETE /api/strategy/instances/{id}             删除实例（级联删信号）
 *   PATCH /api/strategy/instances/{id}/enabled      启停
 *   POST /api/strategy/instances/{id}/scan          手动补算（幂等）
 *   GET  /api/strategy/signals                      信号分页 + 全筛选
 */
export const strategyHandlers = [
  // 定义列表：返回实例树 + 计数（深拷贝避免调用方直接改 mock 内存态）
  http.get('/api/strategy/definitions', async () => {
    await delay(250)
    return HttpResponse.json(
      strategyDefinitions.map((d) => ({
        ...d,
        instances: d.instances.map((i) => ({ ...i, params: { ...i.params } })),
      })),
    )
  }),

  // 新建实例：params 按定义 params_schema 校验（min/max 拒绝 → 422 + 中文 detail）
  http.post('/api/strategy/instances', async ({ request }) => {
    await delay(300)
    const body = (await request.json().catch(() => null)) as
      | { strategy_id?: string; label?: string; params?: Record<string, number> }
      | null
    try {
      const inst = addInstance(
        (body?.strategy_id || '').trim(),
        (body?.label || '').trim(),
        body?.params ?? {},
      )
      return HttpResponse.json(inst)
    } catch (e) {
      return HttpResponse.json({ detail: (e as Error).message }, { status: 422 })
    }
  }),

  // 删除实例（级联删除其信号）
  http.delete('/api/strategy/instances/:id', async ({ params }) => {
    await delay(250)
    const ok = removeInstance(Number(params.id))
    if (!ok) {
      return HttpResponse.json({ detail: `实例 ${params.id} 不存在` }, { status: 404 })
    }
    return HttpResponse.json({ success: true })
  }),

  // 启停实例
  http.patch('/api/strategy/instances/:id/enabled', async ({ params, request }) => {
    await delay(200)
    const body = (await request.json().catch(() => null)) as { enabled?: boolean } | null
    if (typeof body?.enabled !== 'boolean') {
      return HttpResponse.json({ detail: 'enabled 必须为布尔值' }, { status: 422 })
    }
    const ok = setInstanceEnabled(Number(params.id), body.enabled)
    if (!ok) {
      return HttpResponse.json({ detail: `实例 ${params.id} 不存在` }, { status: 404 })
    }
    return HttpResponse.json({ success: true })
  }),

  // 手动补算（异步语义：mock 同步返回结果消息）
  http.post('/api/strategy/instances/:id/scan', async ({ params }) => {
    await delay(600)
    const res = scanInstanceSignals(Number(params.id))
    if (!res.success) {
      return HttpResponse.json({ detail: res.message }, { status: 400 })
    }
    return HttpResponse.json({ success: true, message: res.message })
  }),

  // 信号列表：instance_id 必传 + 状态/方向/日期范围/关键词筛选 + 分页
  //（筛选逻辑风格对齐 handlers/bsp.ts：闭区间日期字符串比较、分页切片）
  http.get('/api/strategy/signals', async ({ request }) => {
    await delay(300)
    const url = new URL(request.url)
    const instanceId = Number(url.searchParams.get('instance_id') || '0')
    const page = Number(url.searchParams.get('page') || '1')
    const pageSize = Number(url.searchParams.get('page_size') || '20')
    const state = url.searchParams.get('state') || ''
    const direction = url.searchParams.get('direction') || ''
    const dateFrom = url.searchParams.get('date_from') || ''
    const dateTo = url.searchParams.get('date_to') || ''
    const keyword = url.searchParams.get('keyword') || ''

    if (!instanceId) {
      return HttpResponse.json({ detail: 'instance_id is required' }, { status: 422 })
    }

    let list = strategySignals[instanceId] || []
    if (state) list = list.filter((r) => r.state === state)
    if (direction) list = list.filter((r) => (direction === 'buy' ? r.is_buy : !r.is_buy))
    if (keyword) list = list.filter((r) => r.code.includes(keyword) || r.name.includes(keyword))
    if (dateFrom || dateTo) {
      list = list.filter((r) => {
        if (dateFrom && r.signal_date < dateFrom) return false
        if (dateTo && r.signal_date > dateTo) return false
        return true
      })
    }

    const total = list.length
    const start = (page - 1) * pageSize
    const pageList = list.slice(start, start + pageSize)
    return HttpResponse.json({ list: pageList, total, page, page_size: pageSize })
  }),
]
