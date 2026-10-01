import { createRouter, createWebHistory } from 'vue-router'
import { routes } from './routes'
import { useAuthStore } from '@/stores/auth'

// 页面缓存（design.md D10）：按 fullPath 记录离开时的滚动位置，切回时恢复
const scrollMemory = new Map<string, number>()

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: (to, from, savedPosition) => {
    const remembered = scrollMemory.get(to.fullPath)
    if (remembered !== undefined) return { top: remembered }
    if (savedPosition) return savedPosition
    return { top: 0 }
  },
})

router.beforeEach(async (to, from) => {
  // 离开时记录滚动位置：守卫阶段旧页面 DOM 尚在，scrollY 仍属于 from 页面
  scrollMemory.set(from.fullPath, window.scrollY)
  // 登出会话边界：进登录页清空记忆，重新登录后从干净状态开始
  if (to.name === 'login') scrollMemory.clear()

  const auth = useAuthStore()

  // 公开路由直接放行
  if (to.meta.public) {
    // 已登录用户访问登录页 → 跳首页
    if (to.name === 'login' && auth.token) {
      return { path: '/kline' }
    }
    return true
  }

  // 未登录 → 跳登录
  if (!auth.token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  // token 存在但 user 未加载 → 拉取用户信息
  if (!auth.user) {
    try {
      await auth.fetchMe()
    } catch {
      auth.logout()
      return { path: '/login', query: { redirect: to.fullPath } }
    }
  }

  // 权限校验
  const perm = to.meta.perm as string | undefined
  if (perm && !auth.hasPerm(perm)) {
    return { path: '/403' }
  }

  return true
})

export default router
