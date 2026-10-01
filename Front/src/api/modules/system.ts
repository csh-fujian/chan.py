import client from '../client'
import type { User, Role, Permission, LlmProvider, LlmProviderInput, LlmTestResult } from '@/api/types'

// --- 用户 ---
/** 用户四条件查询参数（AND 组合，均可选；日期为 YYYY-MM-DD，含端点，design D2） */
export interface UserQuery {
  username?: string
  role?: string
  status?: 'active' | 'disabled' | ''
  created_from?: string
  created_to?: string
}

/** 日期 → YYYY-MM-DD（本地时区） */
export function toDateParam(d: Date | string | null | undefined): string | undefined {
  if (!d) return undefined
  const dt = typeof d === 'string' ? new Date(d) : d
  if (Number.isNaN(dt.getTime())) return undefined
  const m = String(dt.getMonth() + 1).padStart(2, '0')
  const day = String(dt.getDate()).padStart(2, '0')
  return `${dt.getFullYear()}-${m}-${day}`
}

export function getUsers(params?: UserQuery) {
  return client.get<unknown, User[]>('/system/users', { params })
}

export function createUser(data: { username: string; nickname: string; password: string; role: string }) {
  return client.post<unknown, User>('/system/users', data)
}

export function updateUser(id: number, patch: { nickname?: string; role?: string; status?: 'active' | 'disabled' }) {
  return client.put<unknown, { success: boolean }>(`/system/users/${id}`, patch)
}

export function deleteUser(id: number) {
  return client.delete<unknown, { success: boolean }>(`/system/users/${id}`)
}

/** 重置密码：管理员输入新密码（非空），原密码失效（design D2 契约） */
export function resetPassword(id: number, password: string) {
  return client.post<unknown, { success: boolean; id: number }>(`/system/users/${id}/reset-password`, { password })
}

// --- 角色 ---
export function getRoles(params?: { name?: string }) {
  return client.get<unknown, Role[]>('/system/roles', { params })
}

export function createRole(data: { name: string; code: string; description: string; perms?: string[] }) {
  return client.post<unknown, Role>('/system/roles', data)
}

export function updateRole(id: number, patch: { name?: string; description?: string; perms?: string[] }) {
  return client.put<unknown, { success: boolean }>(`/system/roles/${id}`, patch)
}

export function deleteRole(id: number) {
  return client.delete<unknown, { success: boolean }>(`/system/roles/${id}`)
}

/** 角色下已绑定用户列表（字段同用户条件查询，design D2） */
export function getRoleUsers(roleId: number) {
  return client.get<unknown, User[]>(`/system/roles/${roleId}/users`)
}

/** 批量绑定：user_ids 中用户的角色全部改为本角色（单角色，原角色自动解除） */
export function bindRoleUsers(roleId: number, userIds: number[]) {
  return client.put<unknown, { success: boolean }>(`/system/roles/${roleId}/users`, { user_ids: userIds })
}

// --- 权限 ---
export function getPermissions() {
  return client.get<unknown, Permission[]>('/system/permissions')
}

// --- LLM 供应商（design D8.1，manage 权限；api_key 返回时已脱敏） ---
export function getLlmProviders() {
  return client.get<unknown, LlmProvider[]>('/system/llm')
}

export function createLlmProvider(data: LlmProviderInput) {
  return client.post<unknown, LlmProvider>('/system/llm', data)
}

export function activateLlmProvider(id: number) {
  return client.post<unknown, { success: boolean }>(`/system/llm/${id}/activate`)
}

export function deleteLlmProvider(id: number) {
  return client.delete<unknown, { success: boolean }>(`/system/llm/${id}`)
}

/** 测试连接：按 id 测已存预设，或按 base_url/api_key/model 测未保存配置 */
export function testLlmProvider(payload: {
  id?: number
  base_url?: string
  api_key?: string
  model?: string
}) {
  return client.post<unknown, LlmTestResult>('/system/llm/test', payload)
}
