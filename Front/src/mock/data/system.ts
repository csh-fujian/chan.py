import type { User, Role, Permission, LlmProvider, LlmProviderInput } from '@/api/types'
import { mockUsers } from './auth'

export const permissions: Permission[] = [
  { id: 1, code: 'menu:kline', name: 'K线分析', category: '菜单' },
  { id: 2, code: 'menu:watchlist', name: '自选', category: '菜单' },
  { id: 3, code: 'menu:bsp', name: '买卖点', category: '菜单' },
  { id: 4, code: 'menu:monitor', name: '监控', category: '菜单' },
  { id: 5, code: 'menu:performance', name: '绩效', category: '菜单' },
  { id: 6, code: 'menu:screener', name: '选股', category: '菜单' },
  { id: 7, code: 'menu:alerts', name: '预警', category: '菜单' },
  { id: 8, code: 'menu:system', name: '权限管理', category: '菜单' },
  { id: 9, code: 'manage', name: '管理操作', category: '管理' },
]

export const roles: Role[] = [
  {
    id: 1, name: '管理员', code: 'admin', description: '拥有所有权限',
    user_count: 1,
    perms: permissions.map((p) => p.code),
    is_admin: true,
  },
  {
    id: 2, name: '交易员', code: 'trader', description: '可访问业务页面，无系统管理权限',
    user_count: 1,
    perms: ['menu:kline', 'menu:watchlist', 'menu:bsp', 'menu:monitor', 'menu:performance', 'menu:screener', 'menu:alerts'],
    is_admin: false,
  },
  {
    id: 3, name: '观察者', code: 'viewer', description: '仅可查看K线和自选',
    user_count: 1,
    perms: ['menu:kline', 'menu:watchlist'],
    is_admin: false,
  },
]

export const users: User[] = [
  {
    id: 1, username: 'admin', nickname: '管理员', role: 'admin', role_name: '管理员',
    status: 'active', created_at: Date.now() - 86400000 * 90,
  },
  {
    id: 2, username: 'trader', nickname: '交易员', role: 'trader', role_name: '交易员',
    status: 'active', created_at: Date.now() - 86400000 * 30,
  },
  {
    id: 3, username: 'viewer', nickname: '观察者', role: 'viewer', role_name: '观察者',
    status: 'active', created_at: Date.now() - 86400000 * 7,
  },
]

let nextUserId = 4
let nextRoleId = 4

// ---------------------------------------------------------------------------
// 登录侧（mock/data/auth.ts 的 mockUsers）同步 —— 使系统页写操作与登录行为一致：
// 新建/改角色/启停/重置密码后，该用户可按新状态登录、权限随角色生效
// ---------------------------------------------------------------------------
function syncAuthUser(u: User, password?: string) {
  const role = roles.find((r) => r.code === u.role)
  const perms = role ? [...role.perms] : []
  const authU = mockUsers.find((m) => m.id === u.id)
  if (authU) {
    authU.username = u.username
    authU.nickname = u.nickname
    authU.role = u.role
    authU.status = u.status
    authU.perms = perms
    if (password) authU.password = password
    return
  }
  mockUsers.push({
    id: u.id,
    username: u.username,
    password: password ?? 'changeme123',
    nickname: u.nickname,
    role: u.role,
    status: u.status,
    perms,
  })
}

function syncAuthUsersOfRole(roleCode: string) {
  const role = roles.find((r) => r.code === roleCode)
  if (!role) return
  for (const m of mockUsers) {
    if (m.role === roleCode) m.perms = [...role.perms]
  }
}

function recomputeUserCounts() {
  for (const r of roles) {
    r.user_count = users.filter((u) => u.role === r.code).length
  }
}

// --- 用户四条件过滤（AND；username 模糊、role/status 精确、created_at 日期区间含端点） ---
function localDateStr(ts: number): string {
  const d = new Date(ts)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export interface MockUserQuery {
  username?: string
  role?: string
  status?: string
  created_from?: string
  created_to?: string
}

export function filterUsers(q: MockUserQuery): User[] {
  return users.filter((u) => {
    if (q.username && !u.username.toLowerCase().includes(q.username.trim().toLowerCase())) return false
    if (q.role && u.role !== q.role) return false
    if (q.status && u.status !== q.status) return false
    if (q.created_from || q.created_to) {
      const d = localDateStr(u.created_at)
      if (q.created_from && d < q.created_from) return false
      if (q.created_to && d > q.created_to) return false
    }
    return true
  })
}

/** 角色名模糊过滤 */
export function filterRoles(name?: string): Role[] {
  const kw = (name || '').trim().toLowerCase()
  if (!kw) return roles
  return roles.filter((r) => r.name.toLowerCase().includes(kw))
}

/** 角色下已绑定用户 */
export function roleUsers(roleCode: string): User[] {
  return users.filter((u) => u.role === roleCode)
}

/** admin 用户判定：所属角色 is_admin（或 code=admin），design D2 */
export function isAdminUser(u: User): boolean {
  if (u.role === 'admin') return true
  const r = roles.find((x) => x.code === u.role)
  return !!r?.is_admin
}

export function addUser(u: { username: string; nickname: string; password: string; role: string }): User {
  const roleObj = roles.find((r) => r.code === u.role)
  const user: User = {
    id: nextUserId++,
    username: u.username,
    nickname: u.nickname,
    role: u.role,
    role_name: roleObj?.name || u.role,
    status: 'active',
    created_at: Date.now(),
  }
  users.push(user)
  syncAuthUser(user, u.password)
  recomputeUserCounts()
  return user
}

export function updateUser(id: number, patch: Partial<User>) {
  const idx = users.findIndex((u) => u.id === id)
  if (idx < 0) return false
  if (patch.role) {
    const roleObj = roles.find((r) => r.code === patch.role)
    patch = { ...patch, role_name: roleObj?.name || patch.role }
  }
  users[idx] = { ...users[idx], ...patch }
  syncAuthUser(users[idx])
  if (patch.role) recomputeUserCounts()
  return true
}

export function removeUser(id: number) {
  const idx = users.findIndex((u) => u.id === id)
  if (idx < 0) return false
  users.splice(idx, 1)
  const aIdx = mockUsers.findIndex((m) => m.id === id)
  if (aIdx >= 0) mockUsers.splice(aIdx, 1)
  recomputeUserCounts()
  return true
}

/** 重置密码：更新登录侧口令，新密码可登录、原密码失效 */
export function setUserPassword(id: number, password: string): boolean {
  const u = users.find((x) => x.id === id)
  if (!u) return false
  syncAuthUser(u, password)
  return true
}

/**
 * 批量绑定用户到角色（单角色覆盖语义）：user_ids 中用户的角色全部改为该角色，
 * 原角色自动解除；返回被移出 admin 角色的用户（供 handler 拒绝，admin 保护）
 */
export function bindUsersToRole(roleCode: string, userIds: number[]): { movedAdmins: User[] } {
  const movedAdmins: User[] = []
  for (const uid of userIds) {
    const u = users.find((x) => x.id === uid)
    if (!u) continue
    if (isAdminUser(u) && roleCode !== u.role) movedAdmins.push(u)
  }
  if (movedAdmins.length > 0) return { movedAdmins }
  for (const uid of userIds) {
    const u = users.find((x) => x.id === uid)
    if (!u) continue
    updateUser(u.id, { role: roleCode })
  }
  recomputeUserCounts()
  return { movedAdmins: [] }
}

export function addRole(r: { name: string; code: string; description: string; perms?: string[] }): Role {
  const role: Role = {
    id: nextRoleId++,
    name: r.name,
    code: r.code,
    description: r.description,
    user_count: 0,
    perms: r.perms ? [...r.perms] : [],
    is_admin: false,
  }
  roles.push(role)
  return role
}

export function updateRole(id: number, patch: Partial<Role>) {
  const idx = roles.findIndex((r) => r.id === id)
  if (idx < 0) return false
  roles[idx] = { ...roles[idx], ...patch }
  // 权限保存即生效：同步该角色用户的登录侧权限
  if (patch.perms) syncAuthUsersOfRole(roles[idx].code)
  return true
}

export function removeRole(id: number) {
  const idx = roles.findIndex((r) => r.id === id)
  if (idx < 0) return false
  roles.splice(idx, 1)
  return true
}

// ---------------------------------------------------------------------------
// LLM 供应商预设（design D8.1：至多一条 active；api_key 返回时脱敏尾 4）
// ---------------------------------------------------------------------------
interface MockLlmProvider {
  id: number
  name: string
  base_url: string
  api_key: string
  model: string
  active: boolean
}

const llmProviders: MockLlmProvider[] = [
  {
    id: 1, name: 'OpenAI 兼容网关', base_url: 'https://api.openai.com/v1',
    api_key: 'sk-proj-demo-8H2kQ91x', model: 'gpt-4o', active: true,
  },
  {
    id: 2, name: 'DeepSeek', base_url: 'https://api.deepseek.com/v1',
    api_key: 'sk-deep-aB3dE5fG', model: 'deepseek-chat', active: false,
  },
  {
    id: 3, name: '本地 Ollama', base_url: 'http://localhost:11434/v1',
    api_key: 'ollama-local-1234', model: 'qwen2.5:14b', active: false,
  },
]

let nextLlmId = 4

/** api_key 脱敏：仅尾 4 位明文 */
function maskApiKey(key: string): string {
  return key.length <= 4 ? '****' : `****${key.slice(-4)}`
}

function toPublic(p: MockLlmProvider): LlmProvider {
  return { ...p, api_key: maskApiKey(p.api_key) }
}

/** 当前激活的供应商（ask/测试连接解析链的第 1 层） */
export function activeLlmProvider(): MockLlmProvider | undefined {
  return llmProviders.find((p) => p.active)
}

export function listLlmProviders(): LlmProvider[] {
  return llmProviders.map(toPublic)
}

export function addLlmProvider(input: LlmProviderInput): LlmProvider {
  const p: MockLlmProvider = { ...input, id: nextLlmId++, active: false }
  llmProviders.push(p)
  return toPublic(p)
}

/** 激活：先全部置 false 再置目标 true（至多一条 active） */
export function activateLlmProvider(id: number): boolean {
  const target = llmProviders.find((p) => p.id === id)
  if (!target) return false
  for (const p of llmProviders) p.active = false
  target.active = true
  return true
}

export function removeLlmProvider(id: number): boolean {
  const idx = llmProviders.findIndex((p) => p.id === id)
  if (idx >= 0) llmProviders.splice(idx, 1)
  return idx >= 0
}

/** 测试连接：按 id 测已存预设，或按 base_url/api_key/model 测未保存配置 */
export function testLlmProvider(payload: {
  id?: number
  base_url?: string
  api_key?: string
  model?: string
}): { ok: boolean; detail: string } {
  let base_url = payload.base_url || ''
  let model = payload.model || ''
  if (payload.id != null) {
    const p = llmProviders.find((x) => x.id === payload.id)
    if (!p) return { ok: false, detail: `预设 #${payload.id} 不存在` }
    base_url = p.base_url
    model = p.model
  }
  if (!base_url.trim()) return { ok: false, detail: 'base_url 不能为空' }
  if (!model.trim()) return { ok: false, detail: 'model 不能为空' }
  if (/fail|invalid/i.test(base_url)) {
    return { ok: false, detail: `连接失败：无法访问 ${base_url}（mock 模拟错误）` }
  }
  return { ok: true, detail: `连接成功：${base_url} · ${model}（mock）` }
}
