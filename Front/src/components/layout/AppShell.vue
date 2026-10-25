<template>
  <div class="app-shell">
    <Topnav />
    <main class="content">
      <!-- 页面缓存（design.md D10，2026-10-20 修订）：K 线 / 买卖点 / 策略信号三页缓存
           （include 白名单按组件名匹配，脚本 setup 组件需 defineOptions 显式命名），
           切回时排版与数据保持原样；其余页面不缓存、重挂载现拉。
           应用内换页不加过渡：保证 scrollBehavior 在 DOM 就位后恢复滚动位置。 -->
      <router-view v-slot="{ Component, route }">
        <KeepAlive :include="['KLineView', 'BspView', 'StrategySignalView']">
          <component :is="Component" :key="route.name ?? route.path" />
        </KeepAlive>
      </router-view>
    </main>
  </div>
</template>

<script setup lang="ts">
import Topnav from './Topnav.vue'
</script>

<style scoped>
.app-shell {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}
</style>
