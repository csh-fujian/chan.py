import { http, HttpResponse, delay } from 'msw'
import {
  monitorItems,
  completedItems,
  monitorGroups,
  monitorSources,
  createGroup,
  renameGroup,
  removeGroup,
  reorderGroups,
  filterByGroupId,
  getProfitSeries,
  generateAttribution,
} from '../data/monitor'
import { activeLlmProvider } from '../data/system'
import { stocks } from '../data/stocks'

export const monitorHandlers = [
  http.get('/api/monitor', async ({ request }) => {
    await delay(300)
    const url = new URL(request.url)
    const keyword = url.searchParams.get('keyword') || ''
    // 分组过滤（monitor-group-change design D3）：缺省不过滤 / 'ungrouped' → IS NULL / 数值 → 精确匹配
    const groupId = url.searchParams.get('group_id')
    let list = filterByGroupId(monitorItems, groupId)
    if (keyword) list = list.filter((r) => r.code.includes(keyword) || r.name.includes(keyword))
    return HttpResponse.json(list)
  }),

  // 来源字典（design D14）：与真后端 GET /monitor/sources 对齐，前端来源下拉消费
  http.get('/api/monitor/sources', async () => {
    await delay(200)
    return HttpResponse.json(monitorSources)
  }),

  // ---------------------------------------------------------------------------
  // 监控分组（monitor-group-change 任务 3.2）：与真后端路由对齐——
  // GET/POST /monitor/groups、PATCH/DELETE /monitor/groups/:id、PUT /monitor/groups/reorder
  // 内存模拟：名称查重（重名/空名 400 + 中文 detail）、删除后组内记录 group_id 置 null、
  // reorder 持久化（data/monitor.ts 内存态）
  // ---------------------------------------------------------------------------
  http.get('/api/monitor/groups', async () => {
    await delay(200)
    // 组内计数（服务端聚合语义）：监控中/已完成各按 group_id 统计
    const groups = monitorGroups.map((g) => ({
      ...g,
      monitoring_count: monitorItems.filter((r) => r.group_id === g.id).length,
      completed_count: completedItems.filter((r) => r.group_id === g.id).length,
    }))
    return HttpResponse.json(groups)
  }),

  http.post('/api/monitor/groups', async ({ request }) => {
    await delay(200)
    const body = (await request.json().catch(() => null)) as { name?: string } | null
    try {
      const g = createGroup(body?.name || '')
      return HttpResponse.json(g)
    } catch (e) {
      return HttpResponse.json({ detail: (e as Error).message }, { status: 400 })
    }
  }),

  http.patch('/api/monitor/groups/:id', async ({ params, request }) => {
    await delay(150)
    const body = (await request.json().catch(() => null)) as { name?: string } | null
    try {
      renameGroup(Number(params.id), body?.name || '')
      return HttpResponse.json({ success: true })
    } catch (e) {
      return HttpResponse.json({ detail: (e as Error).message }, { status: 400 })
    }
  }),

  http.delete('/api/monitor/groups/:id', async ({ params }) => {
    await delay(200)
    try {
      removeGroup(Number(params.id))
      return HttpResponse.json({ success: true })
    } catch (e) {
      return HttpResponse.json({ detail: (e as Error).message }, { status: 400 })
    }
  }),

  http.put('/api/monitor/groups/reorder', async ({ request }) => {
    await delay(200)
    const body = (await request.json().catch(() => null)) as { ids?: number[] } | null
    reorderGroups(body?.ids ?? [])
    return HttpResponse.json({ success: true })
  }),

  // 行级加入监控（bsp-page-change 4.5）：与真后端 POST /api/monitor 语义一致——
  // code 缺失 / entry_price 为 0 → 422；成功插入 mock 列表并返回创建结果。
  // strategy-signal-page design D6：body 新增 source_type/instance_id/signal_date
  // 可选字段（不传 = 'chan' 现行为不变）；策略来源条目 bsp_type 存 state 文案、
  // direction 按信号 is_buy（与后端 _fill_bsp_context 分叉填充语义一致）。
  // watchlist-page-change design D11：source_type 放行 'watchlist'（自选页加入监控）。
  http.post('/api/monitor', async ({ request }) => {
    await delay(300)
    let body: {
      code?: string
      kl_type?: string
      entry_price?: number
      monitor_start_time?: string
      group_id?: number
      source_type?: 'chan' | 'strategy' | 'watchlist'
      instance_id?: number
      signal_date?: string
      /** mock 侧扩展：策略来源展示标签（后端由 _fill_bsp_context 回查填充，无需前端传） */
      state?: string
      is_buy?: boolean
      strategy_label?: string
    } | undefined
    try {
      const parsed: unknown = await request.json()
      if (parsed && typeof parsed === 'object') body = parsed as typeof body
    } catch {
      return HttpResponse.json({ detail: '请求体不是合法 JSON' }, { status: 422 })
    }
    const code = (body?.code || '').trim()
    const entryPrice = Number(body?.entry_price) || 0
    if (!code) {
      return HttpResponse.json({ detail: 'code is required' }, { status: 422 })
    }
    if (!entryPrice) {
      return HttpResponse.json({ detail: 'entry_price is required' }, { status: 422 })
    }
    const klType = body?.kl_type || 'K_DAY'
    const startTime = body?.monitor_start_time || ''
    // 分组归属（monitor-group-change D5）：可选，未传/不存在 → NULL（未分组）
    const groupId = body?.group_id ?? null
    if (groupId != null && !monitorGroups.some((g) => g.id === groupId)) {
      return HttpResponse.json({ detail: `分组 ${groupId} 不存在` }, { status: 400 })
    }
    // 信号来源（strategy-signal-page D6 + watchlist-page-change D11）：缺省 'chan'；
    // 白名单放行 'strategy'/'watchlist'，非法值兜底落 'chan'（与后端一致）
    const sourceType: 'chan' | 'strategy' | 'watchlist' =
      body?.source_type === 'strategy' || body?.source_type === 'watchlist' ? body.source_type : 'chan'
    const stock = stocks.find((s) => s.code === code)
    // mock 侧维护自增 id（与真后端 RETURNING id 语义一致）
    const id = mockNextId++
    const item = {
      id,
      code,
      name: stock?.name || code,
      industries: stock?.industries || [],
      // 策略来源：bsp_type 存信号 state 文案、direction 按信号 is_buy；
      // 缠论来源保持现行为（空 bsp_type，列表上下文由回查补齐语义）
      bsp_type: sourceType === 'strategy' ? (body?.state || '') : '',
      direction: (sourceType === 'strategy' ? (body?.is_buy ? 'buy' : 'sell') : 'buy') as 'buy' | 'sell',
      bsp_price: entryPrice,
      current_price: stock?.price || 0,
      bsp_date: Date.parse(startTime) || Date.now(),
      kl_type: klType,
      change_pct: 0,
      // 新建监控尚无收益率（D8：current_pnl_pct 可空，渲染兜底 --）
      current_pnl_pct: null,
      max_profit: 0,
      max_drawdown: 0,
      status: 'monitoring' as const,
      group_id: groupId,
      source_type: sourceType,
      // 策略来源展示标签（来源列渲染用；缠论来源不填）
      strategy_label: sourceType === 'strategy' ? (body?.strategy_label || undefined) : undefined,
    }
    monitorItems.push(item)
    // 返回真后端 create_monitor 的行结构（_row_to_dict）+ 来源字段
    return HttpResponse.json({
      id,
      code,
      kl_type: klType,
      monitor_start_time: startTime,
      entry_price: entryPrice,
      status: 'monitoring',
      sold_price: null,
      sold_at: null,
      pnl_pct: null,
      created_at: new Date().toISOString(),
      name: item.name,
      group_id: groupId,
      source_type: sourceType,
      instance_id: sourceType === 'strategy' ? (body?.instance_id ?? null) : null,
      signal_date: sourceType === 'strategy' ? (body?.signal_date ?? null) : null,
    })
  }),

  http.get('/api/monitor/completed', async ({ request }) => {
    await delay(300)
    const url = new URL(request.url)
    const keyword = url.searchParams.get('keyword') || ''
    // 分组过滤（monitor-group-change design D3，语义同监控中列表）
    const groupId = url.searchParams.get('group_id')
    let list = filterByGroupId(completedItems, groupId)
    if (keyword) list = list.filter((r) => r.code.includes(keyword) || r.name.includes(keyword))
    return HttpResponse.json(list)
  }),

  http.get('/api/monitor/profit-series', async () => {
    await delay(200)
    return HttpResponse.json(getProfitSeries())
  }),

  http.post('/api/monitor/:id/end', async ({ params }) => {
    await delay(300)
    return HttpResponse.json({ success: true, id: Number(params.id) })
  }),

  // 大模型归因（design D5：真实生成；未配置/盈利≥5 → 400，调用失败 → 502，均不写占位）
  http.post('/api/monitor/:id/analyze', async ({ params }) => {
    await delay(1500)
    const item = completedItems.find((c) => c.id === Number(params.id))
    if (!item) return HttpResponse.json({ detail: `Monitor ${params.id} not found` }, { status: 404 })
    // 后端校验最终盈利 < 5% 才执行（与前端过滤双侧一致）
    if (item.profit >= 5) {
      return HttpResponse.json({ detail: '盈利不低于 5%，不纳入亏损归因' }, { status: 400 })
    }
    // 未配置激活 LLM 供应商 → 400
    const provider = activeLlmProvider()
    if (!provider) {
      return HttpResponse.json({ detail: 'LLM 未配置' }, { status: 400 })
    }
    // 供应商调用失败（mock：base_url 含 fail/invalid 模拟不可达）→ 502，不写占位记录
    if (/fail|invalid/i.test(provider.base_url)) {
      return HttpResponse.json(
        { detail: `大模型调用失败：无法访问 ${provider.base_url}` },
        { status: 502 },
      )
    }
    // 成功：返回真实结构的归因结果（模拟生成文本），并持久化到标的
    const record = generateAttribution(item)
    return HttpResponse.json({ success: true, id: item.id, attribution: [record] })
  }),
]

/** mock 侧自增 id（避开 data/monitor.ts 现有 id 1..7/9001 段） */
let mockNextId = 10001
