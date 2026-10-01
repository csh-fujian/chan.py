import { defineStore } from 'pinia'
import { ref } from 'vue'

/** 主题名：暗色（默认外观）/ 明亮 */
export type ThemeName = 'dark' | 'light'

/**
 * localStorage 键。持久化模式沿用 auth.ts / chartConfig.ts 的显式 localStorage 读写
 * （不引入 pinia-plugin-persistedstate，保持零新依赖）。
 */
const STORAGE_KEY = 'chan_theme'
const DEFAULT_THEME: ThemeName = 'dark'

function isThemeName(v: unknown): v is ThemeName {
  return v === 'dark' || v === 'light'
}

/** 读取持久化主题偏好；脏数据 / 读取失败一律回退暗色（spec「默认黑夜」） */
function loadPersisted(): ThemeName {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw && isThemeName(raw)) return raw
    if (raw) {
      console.warn('[theme.loadPersisted] 非法主题值，回退暗色', { raw })
    }
    return DEFAULT_THEME
  } catch (e) {
    console.warn('[theme.loadPersisted] 读取 localStorage 失败，回退暗色', {
      error: e instanceof Error ? e.message : String(e),
    })
    return DEFAULT_THEME
  }
}

/** 把主题写到 <html data-theme>，design.css 双主题 token 随之切换 */
function applyThemeAttr(theme: ThemeName): void {
  document.documentElement.dataset.theme = theme
}

/**
 * 尽早应用持久化主题（main.ts 挂载前调用），避免首屏暗色闪烁。
 * 无 Pinia 依赖，可在 store 创建前独立调用；与 store 初始化幂等。
 */
export function applyStoredTheme(): void {
  applyThemeAttr(loadPersisted())
}

export const useThemeStore = defineStore('theme', () => {
  const theme = ref<ThemeName>(loadPersisted())
  // store 创建即应用（applyStoredTheme 已先行设置时为幂等 no-op）
  applyThemeAttr(theme.value)

  /** 设置主题：状态 + DOM 属性 + 持久化三者同步 */
  function setTheme(t: ThemeName): void {
    theme.value = t
    applyThemeAttr(t)
    try {
      localStorage.setItem(STORAGE_KEY, t)
    } catch (e) {
      console.warn('[theme.setTheme] 写入 localStorage 失败', {
        theme: t,
        error: e instanceof Error ? e.message : String(e),
      })
    }
  }

  /** 暗 ↔ 明切换（Topnav 全局入口调用） */
  function toggle(): void {
    setTheme(theme.value === 'dark' ? 'light' : 'dark')
  }

  return {
    theme,
    setTheme,
    toggle,
  }
})
