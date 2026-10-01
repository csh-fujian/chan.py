import client from '../client'
import type { Stock } from '@/api/types'

/** 自选文件夹 */
export interface WatchFolder {
  id: number
  name: string
  codes: string[]
}

/** 获取文件夹列表 */
export function getFolders() {
  return client.get<unknown, WatchFolder[]>('/watchlist/folders')
}

/** 新建文件夹 */
export function createFolder(name: string) {
  return client.post<unknown, WatchFolder>('/watchlist/folders', { name })
}

/** 删除文件夹 */
export function deleteFolder(id: number) {
  return client.delete<unknown, { success: boolean }>(`/watchlist/folders/${id}`)
}

/** 重命名文件夹 */
export function renameFolder(id: number, name: string) {
  return client.patch<unknown, { success: boolean }>(`/watchlist/folders/${id}`, { name })
}

/**
 * 获取某文件夹下的股票（mock 返回全量数组；真实后端全量返回 + 前端分页）
 * @param q 可选关键字，服务端按编码/名称子串过滤；空/缺省返回全量
 */
export function getFolderStocks(folderId: number, q?: string) {
  const keyword = q?.trim()
  return client.get<unknown, Stock[]>(`/watchlist/folders/${folderId}/stocks`, {
    params: keyword ? { q: keyword } : {},
  })
}

/** 重排文件夹顺序（全量覆盖 sort_order，ids 下标即新序） */
export function reorderFolders(ids: number[]) {
  return client.put<unknown, { success: boolean }>('/watchlist/folders/reorder', { ids })
}

/** 重排文件夹内股票顺序（全量覆盖该文件夹 sort_order，codes 下标即新序） */
export function reorderFolderStocks(folderId: number, codes: string[]) {
  return client.put<unknown, { success: boolean }>(
    `/watchlist/folders/${folderId}/stocks/reorder`,
    { codes },
  )
}

/** 添加股票到文件夹 */
export function addStock(folderId: number, code: string) {
  return client.post<unknown, { success: boolean }>(`/watchlist/folders/${folderId}/stocks`, {
    code,
  })
}

/** 从文件夹移出股票 */
export function removeStock(folderId: number, code: string) {
  return client.delete<unknown, { success: boolean }>(
    `/watchlist/folders/${folderId}/stocks/${code}`,
  )
}

/** 移动股票到其他文件夹 */
export function moveStock(from: number, to: number, code: string) {
  return client.post<unknown, { success: boolean }>('/watchlist/move', { from, to, code })
}
