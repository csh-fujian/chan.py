import { http, HttpResponse, delay } from 'msw'
import { bspRecords, getBspAggregate, getBspByCode as mockByCode } from '../data/bsp'

/** 本地时区 YYYY-MM-DD（与查询表单 date_from/date_to 参数对齐） */
function localDateStr(ts: number): string {
  const d = new Date(ts)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export const bspHandlers = [
  http.get('/api/bsp', async ({ request }) => {
    await delay(300)
    const url = new URL(request.url)
    const page = Number(url.searchParams.get('page') || '1')
    const pageSize = Number(url.searchParams.get('page_size') || '20')
    const keyword = url.searchParams.get('keyword') || ''
    const bspType = url.searchParams.get('bsp_type') || ''
    const direction = url.searchParams.get('direction') || ''
    // 周期条件（design D1/D5）：30m/60m/D/W/M，空串 = 不过滤
    const klType = url.searchParams.get('kl_type') || ''
    // 日期范围条件（D7）：双端齐备按闭区间（YYYY-MM-DD 字符串比较），单端单边，双空不过滤
    const dateFrom = url.searchParams.get('date_from') || ''
    const dateTo = url.searchParams.get('date_to') || ''

    let list = bspRecords
    if (keyword) list = list.filter((r) => r.code.includes(keyword) || r.name.includes(keyword))
    if (bspType) list = list.filter((r) => r.bsp_type === bspType)
    if (direction) list = list.filter((r) => r.direction === direction)
    if (klType) list = list.filter((r) => r.kl_type === klType)
    if (dateFrom || dateTo) {
      list = list.filter((r) => {
        const d = localDateStr(r.bsp_date)
        if (dateFrom && d < dateFrom) return false
        if (dateTo && d > dateTo) return false
        return true
      })
    }

    const total = list.length
    const start = (page - 1) * pageSize
    const pageList = list.slice(start, start + pageSize)
    return HttpResponse.json({ list: pageList, total, page, page_size: pageSize })
  }),

  http.get('/api/bsp/aggregate', async () => {
    await delay(200)
    return HttpResponse.json(getBspAggregate())
  }),

  // 多级别买卖点（区间套，bsp-page-change 4.2）：kl_types 逗号分隔过滤，未传=全部周期。
  // 注意在 /api/bsp/:code 之前已注册具体路径，顺序不影响（aggregate 是静态段，优先匹配）
  http.get('/api/bsp/:code', async ({ params, request }) => {
    await delay(250)
    const code = String(params.code || '')
    const klTypesParam = new URL(request.url).searchParams.get('kl_types') || ''
    const klTypes = klTypesParam
      ? klTypesParam.split(',').map((t) => t.trim()).filter(Boolean)
      : undefined
    return HttpResponse.json(mockByCode(code, klTypes))
  }),
]
