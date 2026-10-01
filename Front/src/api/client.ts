import axios, { type AxiosInstance } from 'axios'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const client: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '/api',
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
})

// 请求拦截器 — 注入 token
client.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.token) {
    config.headers.Authorization = `Bearer ${auth.token}`
  }
  return config
})

/**
 * 提取后端错误文案：优先 FastAPI HTTPException 的 `detail`，其次兼容 `message`；
 * 无文案时回退兜底文案（error 契约 UI：必须展示后端 detail/message）。
 */
function extractErrorText(data: unknown, fallback: string): string {
  if (data && typeof data === 'object') {
    const detail = (data as { detail?: unknown }).detail
    if (typeof detail === 'string' && detail.trim()) return detail
    const message = (data as { message?: unknown }).message
    if (typeof message === 'string' && message.trim()) return message
  }
  return fallback
}

// 响应拦截器 — 统一错误处理
client.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const status = error.response?.status
    const message = extractErrorText(error.response?.data, error.message || '请求失败')

    if (status === 401) {
      const auth = useAuthStore()
      auth.logout()
      ElMessage.error('登录已过期，请重新登录')
      // 延迟跳转避免在路由守卫中重复
      setTimeout(() => {
        if (window.location.pathname !== '/login') {
          window.location.href = '/login'
        }
      }, 600)
    } else if (status === 403) {
      // 403 优先展示后端 detail（admin 保护 / 无权限场景各有具体文案）
      ElMessage.error(extractErrorText(error.response?.data, '没有权限执行此操作'))
    } else {
      ElMessage.error(message)
    }
    return Promise.reject(error)
  },
)

export default client
