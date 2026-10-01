import { http, HttpResponse, delay } from 'msw'
import {
  users, roles, permissions,
  filterUsers, filterRoles, roleUsers, isAdminUser,
  addUser, updateUser, removeUser, setUserPassword, bindUsersToRole,
  addRole, updateRole, removeRole,
  listLlmProviders, addLlmProvider, activateLlmProvider, removeLlmProvider, testLlmProvider,
} from '../data/system'
import { mockUsers, userIdFromRequest } from '../data/auth'

/**
 * 错误体与真后端一致：FastAPI HTTPException 的 `{detail}` 结构（design D2）。
 * 403/409/400 均返回对应状态码，不返回 200。
 */
function err(status: number, detail: string) {
  return HttpResponse.json({ detail }, { status })
}

function notFound(what: string) {
  return err(404, `${what}不存在`)
}

// --- 权限守卫（与 WebAPI/auth.py 语义一致：读 menu:system、写 manage） ---
function currentUser(request: Request) {
  const uid = userIdFromRequest(request)
  return mockUsers.find((m) => m.id === uid)
}

/** 写接口守卫：无 manage → 403；返回 HttpResponse 表示拒绝 */
function guardManage(request: Request): ReturnType<typeof err> | null {
  const u = currentUser(request)
  if (!u) return err(401, '未提供认证信息')
  if (u.role !== 'admin' && !u.perms.includes('manage')) return err(403, '无管理权限')
  return null
}

/** 读接口守卫：无 menu:system → 403 */
function guardMenuSystem(request: Request): ReturnType<typeof err> | null {
  const u = currentUser(request)
  if (!u) return err(401, '未提供认证信息')
  if (u.role !== 'admin' && !u.perms.includes('menu:system')) return err(403, '无系统管理权限')
  return null
}

export const systemHandlers = [
  // --- 用户（design D2：四条件 AND，均可选，不分页） ---
  http.get('/api/system/users', async ({ request }) => {
    await delay(200)
    const denied = guardMenuSystem(request)
    if (denied) return denied
    const url = new URL(request.url)
    const list = filterUsers({
      username: url.searchParams.get('username') || '',
      role: url.searchParams.get('role') || '',
      status: url.searchParams.get('status') || '',
      created_from: url.searchParams.get('created_from') || '',
      created_to: url.searchParams.get('created_to') || '',
    })
    return HttpResponse.json(list)
  }),

  http.post('/api/system/users', async ({ request }) => {
    await delay(200)
    const denied = guardManage(request)
    if (denied) return denied
    const body = await request.json() as { username: string; nickname: string; password: string; role: string }
    if (!body.password?.trim()) return err(400, '密码不能为空')
    if (users.some((u) => u.username === body.username)) {
      return err(409, '用户名已存在')
    }
    return HttpResponse.json(addUser(body))
  }),

  http.put('/api/system/users/:id', async ({ params, request }) => {
    await delay(200)
    const denied = guardManage(request)
    if (denied) return denied
    const id = Number(params.id)
    const target = users.find((u) => u.id === id)
    if (!target) return notFound('用户')
    const body = await request.json() as Partial<{ nickname: string; role: string; status: 'active' | 'disabled' }>
    // admin 用户保护：不可停用、不可改出 admin 角色
    if (isAdminUser(target)) {
      if (body.status === 'disabled') return err(403, 'admin 用户不可停用')
      if (body.role && body.role !== target.role && body.role !== 'admin') {
        return err(403, 'admin 用户不可改出 admin 角色')
      }
    }
    updateUser(id, body)
    return HttpResponse.json({ success: true })
  }),

  http.delete('/api/system/users/:id', async ({ params, request }) => {
    await delay(200)
    const denied = guardManage(request)
    if (denied) return denied
    const id = Number(params.id)
    const target = users.find((u) => u.id === id)
    if (!target) return notFound('用户')
    if (isAdminUser(target)) return err(403, 'admin 用户不可删除')
    removeUser(id)
    return HttpResponse.json({ success: true })
  }),

  // 重置密码：管理员输入新密码（design D2 契约，非服务端随机生成）
  http.post('/api/system/users/:id/reset-password', async ({ params, request }) => {
    await delay(200)
    const denied = guardManage(request)
    if (denied) return denied
    const id = Number(params.id)
    if (!users.some((u) => u.id === id)) return notFound('用户')
    const body = await request.json() as { password: string }
    if (!body.password?.trim()) return err(400, '密码不能为空')
    setUserPassword(id, body.password)
    return HttpResponse.json({ success: true, id })
  }),

  // --- 角色 ---
  http.get('/api/system/roles', async ({ request }) => {
    await delay(200)
    const denied = guardMenuSystem(request)
    if (denied) return denied
    const url = new URL(request.url)
    return HttpResponse.json(filterRoles(url.searchParams.get('name') || ''))
  }),

  // 角色下用户列表（字段同用户条件查询）
  http.get('/api/system/roles/:id/users', async ({ params, request }) => {
    await delay(200)
    const denied = guardMenuSystem(request)
    if (denied) return denied
    const role = roles.find((r) => r.id === Number(params.id))
    if (!role) return notFound('角色')
    return HttpResponse.json(roleUsers(role.code))
  }),

  // 批量绑定：user_ids 中用户的角色全部改为本角色（单角色覆盖，原角色自动解除）
  http.put('/api/system/roles/:id/users', async ({ params, request }) => {
    await delay(200)
    const denied = guardManage(request)
    if (denied) return denied
    const role = roles.find((r) => r.id === Number(params.id))
    if (!role) return notFound('角色')
    const body = await request.json() as { user_ids: number[] }
    const userIds = Array.isArray(body.user_ids) ? body.user_ids : []
    const { movedAdmins } = bindUsersToRole(role.code, userIds)
    if (movedAdmins.length > 0) {
      return err(403, 'admin 用户不可改出 admin 角色')
    }
    return HttpResponse.json({ success: true })
  }),

  http.post('/api/system/roles', async ({ request }) => {
    await delay(200)
    const denied = guardManage(request)
    if (denied) return denied
    const body = await request.json() as { name: string; code: string; description: string; perms?: string[] }
    if (roles.some((r) => r.code === body.code)) {
      return err(409, '角色代码已存在')
    }
    return HttpResponse.json(addRole(body))
  }),

  http.put('/api/system/roles/:id', async ({ params, request }) => {
    await delay(200)
    const denied = guardManage(request)
    if (denied) return denied
    const id = Number(params.id)
    const target = roles.find((r) => r.id === id)
    if (!target) return notFound('角色')
    const body = await request.json() as Partial<{ name: string; description: string; perms: string[] }>
    // admin 角色权限不可修改（name/description 编辑允许，design D2）
    if ((target.is_admin || target.code === 'admin') && body.perms !== undefined) {
      return err(403, 'admin 角色权限不可修改')
    }
    updateRole(id, body)
    return HttpResponse.json({ success: true })
  }),

  http.delete('/api/system/roles/:id', async ({ params, request }) => {
    await delay(200)
    const denied = guardManage(request)
    if (denied) return denied
    const id = Number(params.id)
    const target = roles.find((r) => r.id === id)
    if (!target) return notFound('角色')
    if (target.is_admin || target.code === 'admin') return err(403, 'admin 角色不可删除')
    if (target.user_count > 0) return err(409, '角色下仍有用户，请先转移')
    removeRole(id)
    return HttpResponse.json({ success: true })
  }),

  http.get('/api/system/permissions', async ({ request }) => {
    await delay(100)
    const denied = guardMenuSystem(request)
    if (denied) return denied
    return HttpResponse.json(permissions)
  }),

  // --- LLM 供应商（design D8.1）---
  http.get('/api/system/llm', async () => {
    await delay(200)
    return HttpResponse.json(listLlmProviders())
  }),

  http.post('/api/system/llm', async ({ request }) => {
    await delay(200)
    const body = await request.json() as Parameters<typeof addLlmProvider>[0]
    return HttpResponse.json(addLlmProvider(body))
  }),

  http.post('/api/system/llm/:id/activate', async ({ params }) => {
    await delay(200)
    const ok = activateLlmProvider(Number(params.id))
    if (!ok) return HttpResponse.json({ message: '预设不存在' }, { status: 404 })
    return HttpResponse.json({ success: true })
  }),

  http.delete('/api/system/llm/:id', async ({ params }) => {
    await delay(200)
    const ok = removeLlmProvider(Number(params.id))
    if (!ok) return HttpResponse.json({ message: '预设不存在' }, { status: 404 })
    return HttpResponse.json({ success: true })
  }),

  http.post('/api/system/llm/test', async ({ request }) => {
    await delay(400)
    const body = await request.json() as Parameters<typeof testLlmProvider>[0]
    return HttpResponse.json(testLlmProvider(body))
  }),
]
