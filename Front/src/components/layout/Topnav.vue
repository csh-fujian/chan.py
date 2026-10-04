<template>
  <nav class="topnav">
    <div class="topnav__brand">
      <span class="brand-mark"></span>
      <span class="brand-name">chan<span class="accent">.py</span></span>
      <span class="brand-sub">缠论量化</span>
    </div>

    <div class="topnav__menu">
      <router-link
        v-for="item in menuItems"
        :key="item.key"
        :to="item.to"
        class="menu-item"
        :class="{ 'is-active': isActive(item.key), 'menu-item--admin': item.admin }"
      >
        {{ item.label }}
        <span v-if="item.admin" class="admin-dot"></span>
      </router-link>
    </div>

    <el-tooltip content="切换主题" placement="bottom">
      <button
        class="topnav__theme-btn"
        type="button"
        aria-label="切换主题"
        @click="themeStore.toggle()"
      >
        <el-icon v-if="themeStore.theme === 'dark'"><Sunny /></el-icon>
        <el-icon v-else><Moon /></el-icon>
      </button>
    </el-tooltip>

    <el-dropdown trigger="click" @command="onUserCommand">
      <div class="topnav__user">
        <span class="user-avatar">{{ avatarText }}</span>
        <span class="user-name">{{ auth.user?.nickname || '未登录' }}</span>
        <el-icon class="user-chevron"><ArrowDown /></el-icon>
      </div>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item command="profile" :icon="User">{{ auth.user?.username }}</el-dropdown-item>
          <el-dropdown-item command="logout" :icon="SwitchButton" divided>退出登录</el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </nav>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ArrowDown, User, SwitchButton, Sunny, Moon } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
// 全局主题切换入口（kline-chart-change 6.2）：任意页面即时生效并持久化
const themeStore = useThemeStore()

interface MenuItem {
  key: string
  label: string
  to: string
  admin?: boolean
}

const allMenus: MenuItem[] = [
  { key: 'kline', label: 'K线', to: '/kline' },
  { key: 'watchlist', label: '自选', to: '/watchlist' },
  { key: 'bsp', label: '买卖点', to: '/bsp' },
  { key: 'strategy', label: '策略信号', to: '/strategy' },
  { key: 'monitor', label: '监控', to: '/monitor' },
  { key: 'performance', label: '绩效', to: '/performance' },
  { key: 'screener', label: '选股', to: '/screener' },
  { key: 'alerts', label: '预警', to: '/alerts' },
  { key: 'system', label: '权限管理', to: '/system', admin: true },
]

const menuItems = computed(() =>
  allMenus.filter((m) => auth.hasMenu(m.key)),
)

function isActive(key: string) {
  return route.meta.navKey === key
}

const avatarText = computed(() => {
  const name = auth.user?.nickname || auth.user?.username || '?'
  return name.charAt(0)
})

function onUserCommand(cmd: string) {
  if (cmd === 'logout') {
    auth.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
/* 主题切换按钮：与 topnav__user 同风格的图标按钮（全部走 token，随主题迁移） */
.topnav__theme-btn {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  border: 1px solid var(--border-base);
  border-radius: var(--r-md);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}
.topnav__theme-btn:hover {
  color: var(--accent-hover);
  border-color: var(--accent-base);
  background: var(--bg-surface-hover);
}
.topnav__theme-btn :deep(.el-icon) {
  width: 15px;
  height: 15px;
}
</style>
