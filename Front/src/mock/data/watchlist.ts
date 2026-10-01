import { stocks, findStock } from './stocks'

export interface WatchFolder {
  id: number
  name: string
  codes: string[]
}

/** 自选文件夹 mock */
export const watchFolders: WatchFolder[] = [
  { id: 1, name: '默认自选', codes: ['sz.000001', 'sh.600519', 'sz.000858', 'sh.600036', 'sz.002594'] },
  { id: 2, name: '白酒板块', codes: ['sh.600519', 'sz.000858', 'sz.000568', 'sh.600809'] },
  { id: 3, name: '新能源', codes: ['sz.002594', 'sz.300750', 'sh.601012', 'sz.000625'] },
  { id: 4, name: '金融', codes: ['sz.000001', 'sh.600036', 'sh.601318', 'sh.601166', 'sh.600030'] },
  { id: 5, name: '医药', codes: ['sh.600276', 'sz.000538', 'sh.600436'] },
]

let nextFolderId = 6

export function addFolder(name: string): WatchFolder {
  const f = { id: nextFolderId++, name, codes: [] }
  watchFolders.push(f)
  return f
}

export function removeFolder(id: number) {
  const idx = watchFolders.findIndex((f) => f.id === id)
  if (idx >= 0) watchFolders.splice(idx, 1)
}

export function renameFolder(id: number, name: string) {
  const f = watchFolders.find((f) => f.id === id)
  if (f) f.name = name
}

export function addStockToFolder(folderId: number, code: string) {
  const f = watchFolders.find((f) => f.id === folderId)
  if (f && !f.codes.includes(code)) f.codes.push(code)
}

/** 重排文件夹顺序：按 ids 全量覆盖（下标即新序），未列出的文件夹保持在末尾 */
export function reorderFolders(ids: number[]) {
  const byId = new Map(watchFolders.map((f) => [f.id, f]))
  const next: WatchFolder[] = []
  for (const id of ids) {
    const f = byId.get(id)
    if (f) {
      next.push(f)
      byId.delete(id)
    }
  }
  byId.forEach((f) => next.push(f))
  watchFolders.splice(0, watchFolders.length, ...next)
}

/**
 * 重排文件夹内股票顺序：codes 为该文件夹全量新序（全量覆盖）；
 * 若传入子集则仅调整子集相对顺序，其余编码保持原槽位
 */
export function reorderFolderStocks(folderId: number, codes: string[]) {
  const f = watchFolders.find((x) => x.id === folderId)
  if (!f) return
  const listed = new Set(codes)
  const queue = [...codes]
  const merged = f.codes.map((c) => (listed.has(c) ? (queue.shift() as string) : c))
  queue.forEach((c) => merged.push(c))
  f.codes = merged
}

export function removeStockFromFolder(folderId: number, code: string) {
  const f = watchFolders.find((f) => f.id === folderId)
  if (f) f.codes = f.codes.filter((c) => c !== code)
}

export function moveStock(fromId: number, toId: number, code: string) {
  removeStockFromFolder(fromId, code)
  addStockToFolder(toId, code)
}

/**
 * 获取自选股票完整信息
 * @param q 可选关键字，按编码/名称不区分大小写子串过滤（与真实后端行为一致）
 */
export function getWatchStocks(folderId: number, q?: string) {
  const f = watchFolders.find((f) => f.id === folderId)
  if (!f) return []
  const kw = (q ?? '').trim().toLowerCase()
  return f.codes
    .map((c) => findStock(c))
    .filter((s): s is NonNullable<typeof s> => !!s)
    .filter(
      (s) =>
        !kw ||
        s.code.toLowerCase().includes(kw) ||
        s.name.toLowerCase().includes(kw),
    ) as typeof stocks
}
