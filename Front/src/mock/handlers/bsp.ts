import { http, HttpResponse, delay } from 'msw'
import { bspRecords, getBspAggregate } from '../data/bsp'

/** 本地时区 YYYY-MM-DD（与查询表单 date 参数对齐） */
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
    // 日期条件（U6）：命中买卖点日期等于所选日期；空则不过滤
    const date = url.searchParams.get('date') || ''

    let list = bspRecords
    if (keyword) list = list.filter((r) => r.code.includes(keyword) || r.name.includes(keyword))
    if (bspType) list = list.filter((r) => r.bsp_type === bspType)
    if (direction) list = list.filter((r) => r.direction === direction)
    if (klType) list = list.filter((r) => r.kl_type === klType)
    if (date) list = list.filter((r) => localDateStr(r.bsp_date) === date)

    const total = list.length
    const start = (page - 1) * pageSize
    const pageList = list.slice(start, start + pageSize)
    return HttpResponse.json({ list: pageList, total, page, page_size: pageSize })
  }),

  http.get('/api/bsp/aggregate', async () => {
    await delay(200)
    return HttpResponse.json(getBspAggregate())
  }),
]
