<template>
  <router-view v-slot="{ Component }">
    <transition name="router-fade" mode="out-in">
      <component :is="Component" />
    </transition>
  </router-view>
</template>

<script setup lang="ts">
// App.vue — 仅作路由出口 + 过渡。布局由各路由 meta.layout 决定（blank / app）。
// 注意：不要给 component 加 key（曾用 route.path）——那会让布局组件 AppShell 随路径
// 整体重建，其内部 KeepAlive 页面缓存无法跨页存活（design.md D10）。
// 移除 key 后，本层过渡仅在「空白布局 ↔ 应用布局」切换（登录/403）时触发；
// 应用内页面切换由 AppShell 内的 KeepAlive 直接换页，无过渡。
</script>
