<template>
  <div class="app-shell">
    <Topnav />
    <main class="content">
      <!-- 页面缓存（design.md D10）：按 route.name 缓存，切回时排版与数据保持原样。
           应用内换页不加过渡：保证 scrollBehavior 在 DOM 就位后恢复滚动位置。 -->
      <router-view v-slot="{ Component, route }">
        <KeepAlive>
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
