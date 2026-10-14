import { http, HttpResponse, delay } from 'msw'
import {
  strategyDefinitions,
  strategySignals,
  addTask,
  removeTask,
  startTask,
  pauseTask,
  resumeTask,
  patchTask,
  promoteTask,
  copyTask,
  buildTaskDetail,
  syncSignalCounts,
} from '../data/strategy'

/**
 * 策略任务 MSW handlers（strategy-task-redesign design D6 / 任务 4.1）：
 * 全部端点与后端任务契约对齐——
 *   GET    /api/strategy/definitions            定义（含任务树+计数+desc/detail_schema）
 *   GET    /api/strategy/tasks                  任务列表（strategy_id/user_group/status 过滤）
 *   POST   /api/strategy/tasks                  新建任务（范围三来源解析 + params 422）
 *   PATCH  /api/strategy/tasks/{id}             编辑（仅 paused；persistent 参数冻结 409）
 *   POST   /api/strategy/tasks/{id}/start|pause 启停
 *   POST   /api/strategy/tasks/{id}/resume      续跑（rerun: full|remaining）
 *   POST   /api/strategy/tasks/{id}/promote     转正（done 的 test → persistent）
 *   POST   /api/strategy/tasks/{id}/copy        复制（继承参数与范围为 test）
 *   DELETE /api/strategy/tasks/{id}             删除（级联删信号与逐股结果）
 *   GET    /api/strategy/tasks/{id}/detail      任务详情（detail_schema 渲染数据源）
 *   GET    /api/strategy/signals                信号分页（task_id 必传 + 全筛选）
 * 原实例端点（/strategy/instances*）全部移除（BREAKING）。
 */
export const strategyHandlers = [
  // 定义列表：返回任务树 + 计数（深拷贝避免调用方直接改 mock 内存态）
  http.get('/api/strategy/definitions', async () => {
    await delay(250)
    return HttpResponse.json(
      strategyDefinitions.map((d) => ({
        ...d,
        tasks: d.tasks.map((t) => ({ ...t, params: { ...t.params } })),
      })),
    )
  }),

  // 任务列表：strategy_id/user_group/status 可选过滤（v1 前端本地过滤，接口预留）
  http.get('/api/strategy/tasks', async ({ request }) => {
    await delay(250)
    const url = new URL(request.url)
    const strategyId = url.searchParams.get('strategy_id') || ''
    const userGroup = url.searchParams.get('user_group') || ''
    const status = url.searchParams.get('status') || ''
    let tasks = strategyDefinitions.flatMap((d) => d.tasks)
    if (strategyId) tasks = tasks.filter((t) => t.strategy_id === strategyId)
    if (userGroup) tasks = tasks.filter((t) => t.user_group === userGroup)
    if (status) tasks = tasks.filter((t) => t.status === status)
    return HttpResponse.json(tasks.map((t) => ({ ...t, params: { ...t.params } })))
  }),

  // 新建任务：params 按定义 params_schema 校验（min/max 拒绝 → 422 + 中文 detail）；
  // 范围三来源解析（manual codes / watchlist folder_id / bsp_query 条件）+ 全量兜底
  http.post('/api/strategy/tasks', async ({ request }) => {
    await delay(300)
    const body = (await request.json().catch(() => null)) as
      | {
          strategy_id?: string
          label?: string
          user_group?: string
          params?: Record<string, number | string>
          scope_type?: string
          scope_codes?: string[]
          folder_id?: number
          mode?: string
        }
      | null
    try {
      const task = addTask(body ?? {}, request)
      return HttpResponse.json(task)
    } catch (e) {
      return HttpResponse.json({ detail: (e as Error).message }, { status: 422 })
    }
  }),

  // 编辑任务（仅 paused；test 可改参数/范围，persistent 仅范围——参数冻结 409）
  http.patch('/api/strategy/tasks/:id', async ({ params, request }) => {
    await delay(300)
    const body = (await request.json().catch(() => null)) as
      | {
          label?: string
          user_group?: string
          params?: Record<string, number | string>
          scope_type?: string
          scope_codes?: string[]
          folder_id?: number
        }
      | null
    try {
      const task = patchTask(Number(params.id), body ?? {})
      syncSignalCounts()
      return HttpResponse.json(task)
    } catch (e) {
      return HttpResponse.json({ detail: (e as Error).message }, { status: 409 })
    }
  }),

  // 启动任务（pending/paused → running；非可启动状态 409）
  http.post('/api/strategy/tasks/:id/start', async ({ params }) => {
    await delay(200)
    const ok = startTask(Number(params.id))
    if (!ok) return HttpResponse.json({ detail: `任务 ${params.id} 不存在或当前状态不可启动` }, { status: 409 })
    return HttpResponse.json({ success: true })
  }),

  // 暂停任务（running → paused；非执行中 409）
  http.post('/api/strategy/tasks/:id/pause', async ({ params }) => {
    await delay(200)
    const ok = pauseTask(Number(params.id))
    if (!ok) return HttpResponse.json({ detail: `任务 ${params.id} 不存在或不在执行中` }, { status: 409 })
    return HttpResponse.json({ success: true })
  }),

  // 续跑（design D2：full=重新运行清空重扫 / remaining=剩余股票继续新参数续扫）
  http.post('/api/strategy/tasks/:id/resume', async ({ params, request }) => {
    await delay(600)
    const body = (await request.json().catch(() => null)) as { rerun?: string } | null
    const res = resumeTask(Number(params.id), body?.rerun || 'full')
    if (!res.success) {
      return HttpResponse.json({ detail: res.message }, { status: 409 })
    }
    return HttpResponse.json({ success: true, message: res.message })
  }),

  // 转正（done 的 test → persistent；不满足前置 409）
  http.post('/api/strategy/tasks/:id/promote', async ({ params }) => {
    await delay(300)
    try {
      const task = promoteTask(Number(params.id))
      return HttpResponse.json(task)
    } catch (e) {
      return HttpResponse.json({ detail: (e as Error).message }, { status: 409 })
    }
  }),

  // 复制任务（继承参数与范围为新的 test 任务）
  http.post('/api/strategy/tasks/:id/copy', async ({ params, request }) => {
    await delay(300)
    try {
      const task = copyTask(Number(params.id), request)
      return HttpResponse.json(task)
    } catch (e) {
      return HttpResponse.json({ detail: (e as Error).message }, { status: 404 })
    }
  }),

  // 删除任务（级联删除其信号与逐股结果）
  http.delete('/api/strategy/tasks/:id', async ({ params }) => {
    await delay(250)
    const ok = removeTask(Number(params.id))
    if (!ok) {
      return HttpResponse.json({ detail: `任务 ${params.id} 不存在` }, { status: 404 })
    }
    return HttpResponse.json({ success: true })
  }),

  // 任务详情（design D5：task/summary/kv_payload/per_stock?/signals_page/definition/timeline；
  // scope='all' 时不含 per_stock 键 → 前端 per_stock 块静默隐藏）
  http.get('/api/strategy/tasks/:id/detail', async ({ params }) => {
    await delay(300)
    const detail = buildTaskDetail(Number(params.id))
    if (!detail) {
      return HttpResponse.json({ detail: `任务 ${params.id} 不存在` }, { status: 404 })
    }
    return HttpResponse.json(detail)
  }),

  // 信号列表：task_id 必传 + 状态/方向/日期范围/关键词筛选 + 分页
  //（筛选逻辑风格对齐 handlers/bsp.ts：闭区间日期字符串比较、分页切片）
  http.get('/api/strategy/signals', async ({ request }) => {
    await delay(300)
    const url = new URL(request.url)
    const taskId = Number(url.searchParams.get('task_id') || '0')
    const page = Number(url.searchParams.get('page') || '1')
    const pageSize = Number(url.searchParams.get('page_size') || '20')
    const state = url.searchParams.get('state') || ''
    const direction = url.searchParams.get('direction') || ''
    const dateFrom = url.searchParams.get('date_from') || ''
    const dateTo = url.searchParams.get('date_to') || ''
    const keyword = url.searchParams.get('keyword') || ''

    if (!taskId) {
      return HttpResponse.json({ detail: 'task_id is required' }, { status: 422 })
    }

    let list = strategySignals[taskId] || []
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

  // 单信号 B 级事件全集（strategy-volume-breakout-pullback D7：B 列弹窗数据源；
  // mock 信号 payload 已嵌 b_events，直接回取；跨任务线性查 id——mock 池小可接受）
  http.get('/api/strategy/signals/:signalId/b-events', ({ params }) => {
    const signalId = Number(params.signalId)
    for (const rows of Object.values(strategySignals)) {
      const row = rows.find((r) => r.id === signalId)
      if (row) {
        const v = row.payload?.b_events
        const bEvents = Array.isArray(v) ? v : []
        return HttpResponse.json({ signal_id: signalId, b_events: bEvents })
      }
    }
    return HttpResponse.json({ detail: '信号不存在' }, { status: 404 })
  }),
]
