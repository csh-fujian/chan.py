---
name: vue-styling
description: Styling patterns for Vue 3.5 applications. Use when working with Element Plus, Tailwind CSS, CSS Modules, theming, responsive design, or component styling.
---

# Web Styling (Vue)

## Element Plus Usage

Element Plus 2.8 是 Vue 3 生态中最主流的 UI 组件库，提供 70+ 高质量组件。Tailwind CSS 负责布局、间距、响应式等底层样式，Element Plus 负责交互逻辑和无障碍。

### 基础组件 + Tailwind 定制

```vue
<template>
  <!-- 按钮：Element Plus 语义 + Tailwind 增强 -->
  <el-button type="primary" class="hover:shadow-lg transition-shadow rounded-lg">
    提交
  </el-button>

  <!-- 卡片 -->
  <el-card class="hover:shadow-md transition-shadow cursor-pointer" shadow="hover">
    <template #header>
      <div class="flex items-center justify-between">
        <span class="font-semibold text-lg">标题</span>
        <el-tag type="success" size="small">已完成</el-tag>
      </div>
    </template>
    <p class="text-gray-600 dark:text-gray-400">卡片内容区域</p>
  </el-card>

  <!-- 表格 -->
  <el-table
    :data="tableData"
    class="w-full rounded-lg overflow-hidden"
    stripe
    border
    empty-text="暂无数据"
  >
    <el-table-column prop="name" label="名称" width="180" />
    <el-table-column prop="status" label="状态" width="120">
      <template #default="{ row }">
        <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">
          {{ row.status }}
        </el-tag>
      </template>
    </el-table-column>
    <el-table-column label="操作" width="150">
      <template #default>
        <el-button type="primary" link size="small">编辑</el-button>
        <el-button type="danger" link size="small">删除</el-button>
      </template>
    </el-table-column>
  </el-table>
</template>

<script setup>
import { ref } from 'vue'

const tableData = ref([
  { id: 1, name: '项目 Alpha', status: 'active' },
  { id: 2, name: '项目 Beta', status: 'inactive' },
])
</script>
```

### 表单 + 条件样式

```vue
<template>
  <el-form
    :model="form"
    :rules="rules"
    label-width="100px"
    class="max-w-lg mx-auto"
  >
    <el-form-item label="用户名" prop="username">
      <el-input
        v-model="form.username"
        :class="{ 'border-red-500': errors.username }"
        class="w-full"
        placeholder="请输入用户名"
      />
    </el-form-item>

    <el-form-item label="角色" prop="role">
      <el-select
        v-model="form.role"
        class="w-full"
        :class="{ 'opacity-50': loading }"
        :disabled="loading"
      >
        <el-option label="管理员" value="admin" />
        <el-option label="编辑者" value="editor" />
      </el-select>
    </el-form-item>

    <el-form-item>
      <el-button
        type="primary"
        :loading="submitting"
        class="w-full sm:w-auto"
        @click="handleSubmit"
      >
        {{ submitting ? '提交中...' : '提交' }}
      </el-button>
    </el-form-item>
  </el-form>
</template>

<script setup>
import { reactive, ref } from 'vue'

const form = reactive({ username: '', role: '' })
const errors = ref({})
const loading = ref(false)
const submitting = ref(false)

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
}

function handleSubmit() { /* ... */ }
</script>
```

### 对话框 + 过渡动画

```vue
<template>
  <el-dialog
    v-model="visible"
    title="编辑信息"
    width="500px"
    :close-on-click-modal="false"
    class="rounded-xl"
  >
    <el-form :model="form" label-width="80px">
      <el-form-item label="名称">
        <el-input v-model="form.name" />
      </el-form-item>
    </el-form>

    <template #footer>
      <div class="flex justify-end gap-3">
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" @click="handleConfirm">确认</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive } from 'vue'

const visible = ref(false)
const form = reactive({ name: '' })

function handleConfirm() {
  visible.value = false
}
</script>
```

### 导航菜单

```vue
<template>
  <el-menu
    :default-active="activeIndex"
    mode="horizontal"
    class="sticky top-0 z-50 shadow-sm"
    background-color="transparent"
    @select="handleSelect"
  >
    <el-menu-item index="dashboard" class="h-14">
      <el-icon><Monitor /></el-icon>
      <span>仪表盘</span>
    </el-menu-item>
    <el-menu-item index="projects" class="h-14">
      <el-icon><Folder /></el-icon>
      <span>项目</span>
    </el-menu-item>
  </el-menu>
</template>

<script setup>
import { ref } from 'vue'
import { Monitor, Folder } from '@element-plus/icons-vue'

const activeIndex = ref('dashboard')
function handleSelect(index: string) { /* ... */ }
</script>
```

### 常用 Element Plus 组件 + Tailwind 定制速查

| 组件 | Tailwind 常用增强 |
|------|------------------|
| `el-button` | `rounded-lg`, `shadow-sm`, `hover:shadow-md`, `transition-all` |
| `el-card` | `rounded-xl`, `shadow`, `hover:shadow-lg`, `overflow-hidden` |
| `el-table` | `w-full`, `rounded-lg`, `overflow-hidden` |
| `el-dialog` | `rounded-xl` — 可通过 `:deep(.el-dialog)` 定制 |
| `el-input` | `w-full`, 条件 `border-red-500` |
| `el-form-item` | `mb-4` |
| `el-tag` | `rounded-full` |
| `el-menu` | `sticky top-0 z-50`, `shadow-sm` |

### 用 `:deep()` 穿透 Element Plus 内部样式

当 Tailwind 类无法直接覆盖 Element Plus 内部元素时，使用 `:deep()` 深度选择器：

```vue
<style scoped>
/* 自定义对话框圆角 */
:deep(.el-dialog) {
  border-radius: 16px;
}

/* 自定义表格表头背景 */
:deep(.el-table th.el-table__cell) {
  background-color: #f8fafc;
}

/* 暗色模式下适配 */
.dark :deep(.el-table th.el-table__cell) {
  background-color: #1f2937;
}
</style>
```

---

## Tailwind CSS

### 基础用法

```vue
<template>
  <button
    :class="[
      'px-4 py-2 rounded-lg font-medium transition-colors',
      variantClasses[variant],
    ]"
  >
    <slot />
  </button>
</template>

<script setup>
const props = defineProps({
  variant: {
    type: String as PropType<'primary' | 'secondary' | 'danger'>,
    default: 'primary',
  },
})

const variantClasses = {
  primary: 'bg-blue-600 text-white hover:bg-blue-700',
  secondary: 'bg-gray-200 text-gray-800 hover:bg-gray-300',
  danger: 'bg-red-600 text-white hover:bg-red-700',
}
</script>
```

### 条件类名：Vue `:class` 绑定

Vue 原生 `:class` 支持对象、数组、字符串三种语法，无需 clsx/twMerge 等第三方库：

```vue
<template>
  <!-- 对象语法：key 是类名，value 是布尔值 -->
  <div
    :class="{
      'p-4 rounded-lg border': true,
      'border-blue-500 bg-blue-50': isActive,
      'opacity-50 cursor-not-allowed': isDisabled,
    }"
  >
    内容
  </div>

  <!-- 数组语法：混合静态类和动态类 -->
  <div
    :class="[
      'p-4 rounded-lg border',
      isActive ? 'border-blue-500 bg-blue-50' : 'border-gray-200',
      className,
    ]"
  >
    内容
  </div>

  <!-- 与 computed 结合，适合复杂逻辑 -->
  <div :class="cardClasses">
    内容
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  isActive: Boolean,
  isDisabled: Boolean,
  className: { type: String, default: '' },
})

const cardClasses = computed(() => ({
  'p-4 rounded-lg border': true,
  'border-blue-500 bg-blue-50': props.isActive,
  'opacity-50 cursor-not-allowed': props.isDisabled,
  [props.className]: !!props.className,
}))
</script>
```

### 响应式设计

```vue
<template>
  <!-- 移动优先断点：sm: 640px, md: 768px, lg: 1024px, xl: 1280px, 2xl: 1536px -->

  <!-- 响应式网格 -->
  <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
    <Card v-for="item in items" :key="item.id" v-bind="item" />
  </div>

  <!-- 响应式文字 -->
  <h1 class="text-2xl md:text-3xl lg:text-4xl font-bold">
    标题
  </h1>

  <!-- 断点显隐 -->
  <nav class="hidden md:flex gap-4">桌面导航</nav>
  <nav class="flex md:hidden">
    <el-drawer v-model="drawerVisible" direction="ltr" size="260px">
      移动端导航
    </el-drawer>
  </nav>
</template>

<script setup>
import { ref } from 'vue'

const items = ref([])
const drawerVisible = ref(false)
</script>
```

### 暗色模式

```js
// tailwind.config.js
module.exports = {
  darkMode: 'class', // 或 'media'（跟随操作系统）
  // ...
}
```

```vue
<template>
  <!-- 暗色模式类名：在需要适配的类前加 dark: 前缀 -->
  <div class="bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 min-h-screen transition-colors duration-300">
    <h1 class="text-black dark:text-white">标题</h1>
    <p class="text-gray-600 dark:text-gray-400">描述</p>
    <el-card class="dark:bg-gray-800 dark:border-gray-700">暗色适配卡片</el-card>
  </div>
</template>

<script setup>
import { ref, watchEffect } from 'vue'
import { useDark, useToggle } from '@vueuse/core'

// 方案一：使用 @vueuse/core 的 useDark（推荐）
const isDark = useDark()
const toggleDark = useToggle(isDark)

// 方案二：手动控制（不需要额外依赖）
// const isDark = ref(false)
// watchEffect(() => {
//   document.documentElement.classList.toggle('dark', isDark.value)
//   // 同时设置 Element Plus 暗色主题
//   document.documentElement.classList.toggle('dark', isDark.value)
// })
</script>

<template>
  <!-- 暗色模式切换按钮 -->
  <el-button
    :icon="isDark ? Sunny : Moon"
    circle
    @click="toggleDark()"
    class="text-lg"
  />
</template>
```

### 自定义设计令牌

```js
// tailwind.config.js
const { theme } = require('tailwindcss/defaultTheme')

module.exports = {
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#eef2ff',
          100: '#e0e7ff',
          500: '#6366f1',
          600: '#4f46e5',
          700: '#4338ca',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      spacing: {
        '18': '4.5rem',
        '88': '22rem',
      },
      transitionDuration: {
        DEFAULT: '200ms',
      },
    },
  },
}
```

```vue
<template>
  <!-- 使用自定义令牌 -->
  <el-button class="bg-brand-500 hover:bg-brand-600 border-0 text-white">
    品牌色按钮
  </el-button>
</template>
```

---

## 基础用法：`<style module>`

```vue
<template>
  <button :class="[$style.button, $style[variant]]">
    <slot />
  </button>
</template>

<script setup>
defineProps({
  variant: {
    type: String,
    default: 'primary',
  },
})
</script>

<style module>
.button {
  padding: 0.5rem 1rem;
  border-radius: 0.5rem;
  font-weight: 500;
  transition: background-color 0.2s;
}
.primary {
  background-color: #3b82f6;
  color: white;
}
.secondary {
  background-color: #e5e7eb;
  color: #1f2937;
}
</style>
```

### 命名模块 + 组合

```vue
<template>
  <!-- 通过 module="card" 指定模块名 -->
  <div :class="[cardStyles.card, isActive && cardStyles.active, className]">
    <slot />
  </div>
</template>

<script setup>
defineProps({
  isActive: Boolean,
  className: { type: String, default: '' },
})
</script>

<style module="cardStyles">
.card {
  border: 1px solid #e5e7eb;
  border-radius: 0.75rem;
  padding: 1rem;
}
.active {
  border-color: #3b82f6;
  background-color: #eff6ff;
}
</style>
```

### Scoped 样式（推荐，更接近原生 CSS 体验）

```vue
<template>
  <div class="card" :class="{ 'card--active': isActive }">
    <slot />
  </div>
</template>

<script setup>
defineProps({ isActive: Boolean })
</script>

<style scoped>
.card {
  border: 1px solid #e5e7eb;
  border-radius: 0.75rem;
  padding: 1rem;
}
.card--active {
  border-color: #3b82f6;
  background-color: #eff6ff;
}

/* 使用 v-bind() 动态绑定 JS 变量到 CSS */
.card {
  --card-radius: v-bind(borderRadius);
  border-radius: var(--card-radius);
}
</style>
```

---

## 组件变体模式

不使用 cva，而是通过 Vue props + computed + `:class` 绑定实现同等的变体系统：

```vue
<template>
  <button :class="buttonClasses" :disabled="disabled">
    <slot />
  </button>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  variant: {
    type: String,
    default: 'primary',
    validator: (v) => ['primary', 'secondary', 'outline', 'ghost', 'danger'].includes(v),
  },
  size: {
    type: String,
    default: 'md',
    validator: (v) => ['sm', 'md', 'lg'].includes(v),
  },
  disabled: Boolean,
})

const sizeClasses = {
  sm: 'h-8 px-3 text-sm',
  md: 'h-10 px-4 text-base',
  lg: 'h-12 px-6 text-lg',
}

const variantClasses = {
  primary: 'bg-blue-600 text-white hover:bg-blue-700 active:bg-blue-800',
  secondary: 'bg-gray-100 text-gray-900 hover:bg-gray-200 active:bg-gray-300',
  outline: 'border border-gray-300 text-gray-700 hover:bg-gray-50 active:bg-gray-100',
  ghost: 'text-gray-700 hover:bg-gray-100 active:bg-gray-200',
  danger: 'bg-red-600 text-white hover:bg-red-700 active:bg-red-800',
}

const buttonClasses = computed(() => [
  // 基础样式
  'inline-flex items-center justify-center rounded-md font-medium',
  'transition-all duration-200',
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2',
  // 变体
  sizeClasses[props.size],
  variantClasses[props.variant],
  // 禁用态
  props.disabled ? 'opacity-50 cursor-not-allowed pointer-events-none' : '',
])
</script>

<!-- 使用 -->
<template>
  <MyButton variant="primary" size="lg">主要按钮</MyButton>
  <MyButton variant="outline" size="sm">小号描边</MyButton>
  <MyButton variant="danger" disabled>禁用危险按钮</MyButton>
</template>
```

对于需要同时维护 Element Plus 组件和自定义组件的场景，可以用一个 `component` 判断：

```vue
<template>
  <component
    :is="elComponent ? 'el-button' : 'button'"
    :type="elComponent ? variant === 'danger' ? 'danger' : 'primary' : undefined"
    :class="!elComponent ? buttonClasses : undefined"
    :disabled="disabled"
  >
    <slot />
  </component>
</template>
```

---

## 动画模式

### Tailwind 内置动画

```vue
<template>
  <!-- 内置动画 -->
  <div class="animate-spin w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full" />
  <div class="animate-pulse bg-gray-200 rounded h-4 w-48" />
  <div class="animate-bounce">向下滚动</div>

  <!-- 过渡动效 -->
  <button class="transition-all duration-200 hover:scale-105 active:scale-95">
    点我
  </button>
</template>
```

### 自定义 keyframes

```js
// tailwind.config.js
module.exports = {
  theme: {
    extend: {
      animation: {
        'fade-in': 'fadeIn 0.3s ease-out',
        'slide-up': 'slideUp 0.3s ease-out',
        'slide-down': 'slideDown 0.2s ease-out',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { transform: 'translateY(10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        slideDown: {
          '0%': { transform: 'translateY(-10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
      },
    },
  },
}
```

### Vue 内置 `<Transition>` 和 `<TransitionGroup>`

```vue
<template>
  <!-- 单个元素/组件的进入/离开过渡 -->
  <Transition name="fade" mode="out-in">
    <div v-if="show" key="content" class="p-6 bg-white rounded-lg shadow">
      内容区域
    </div>
  </Transition>

  <!-- 列表过渡 -->
  <TransitionGroup
    name="list"
    tag="ul"
    class="space-y-2"
  >
    <li
      v-for="item in items"
      :key="item.id"
      class="p-3 bg-white rounded shadow-sm"
    >
      {{ item.text }}
      <el-button type="danger" size="small" @click="remove(item.id)">删除</el-button>
    </li>
  </TransitionGroup>

  <!-- 模态框过渡（完整示例） -->
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="modalVisible" class="fixed inset-0 z-50 flex items-center justify-center">
        <!-- 遮罩 -->
        <div class="absolute inset-0 bg-black/50" @click="modalVisible = false" />
        <!-- 内容 -->
        <el-card class="relative z-10 w-full max-w-md mx-4 shadow-xl">
          <h2 class="text-lg font-semibold mb-4">标题</h2>
          <p class="text-gray-600 mb-6">内容...</p>
          <div class="flex justify-end gap-3">
            <el-button @click="modalVisible = false">取消</el-button>
            <el-button type="primary" @click="modalVisible = false">确认</el-button>
          </div>
        </el-card>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref } from 'vue'

const show = ref(false)
const modalVisible = ref(false)
const items = ref([
  { id: 1, text: '第一项' },
  { id: 2, text: '第二项' },
])

function remove(id: number) {
  items.value = items.value.filter(i => i.id !== id)
}
</script>

<style scoped>
/* Transition 配套 CSS — 类名规则：{name}-enter-from / {name}-leave-to 等 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* 列表动画 */
.list-enter-active,
.list-leave-active {
  transition: all 0.3s ease;
}
.list-enter-from {
  opacity: 0;
  transform: translateX(-20px);
}
.list-leave-to {
  opacity: 0;
  transform: translateX(20px);
}
.list-move {
  transition: transform 0.3s ease;
}

/* 模态框动画 */
.modal-enter-active,
.modal-leave-active {
  transition: all 0.25s ease;
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
.modal-enter-from .el-card,
.modal-leave-to .el-card {
  transform: scale(0.95) translateY(10px);
}
</style>
```

### Flexbox

```vue
<template>
  <!-- 居中 -->
  <div class="flex items-center justify-center min-h-screen">
    <el-card>居中内容</el-card>
  </div>

  <!-- 两端对齐 -->
  <div class="flex items-center justify-between px-4 h-16">
    <Logo />
    <Navigation />
    <UserMenu />
  </div>

  <!-- 响应式方向 -->
  <div class="flex flex-col md:flex-row gap-4">
    <aside class="md:w-64 shrink-0">侧边栏</aside>
    <main class="flex-1 min-w-0">主内容</main>
  </div>

  <!-- 平均分布 -->
  <div class="flex gap-4">
    <div v-for="n in 3" :key="n" class="flex-1 p-4 bg-gray-100 rounded">
      列 {{ n }}
    </div>
  </div>
</template>
```

### Grid

```vue
<template>
  <!-- 等宽列 -->
  <div class="grid grid-cols-3 gap-4">
    <Card v-for="item in items" :key="item.id" v-bind="item" />
  </div>

  <!-- 经典 12 列布局 -->
  <div class="grid grid-cols-12 gap-4">
    <aside class="col-span-3">侧边栏</aside>
    <main class="col-span-6">主内容</main>
    <aside class="col-span-3">右侧边栏</aside>
  </div>

  <!-- auto-fit：未知数量自适应 -->
  <div class="grid grid-cols-[repeat(auto-fit,minmax(250px,1fr))] gap-4">
    <Card v-for="item in items" :key="item.id" v-bind="item" />
  </div>

  <!-- 仪表盘布局 -->
  <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
    <div class="col-span-1 md:col-span-2 lg:col-span-2">
      <el-card>主指标</el-card>
    </div>
    <el-card>指标 1</el-card>
    <el-card>指标 2</el-card>
  </div>
</template>
```

### Container

```vue
<template>
  <!-- 居中容器 + 最大宽度 -->
  <div class="container mx-auto px-4">
    <slot />
  </div>

  <!-- 自定义最大宽度 + 响应式内边距 -->
  <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
    <slot />
  </div>
</template>
```

### 粘性页脚布局

```vue
<template>
  <div class="flex flex-col min-h-screen">
    <header class="h-16 shrink-0 border-b">
      <!-- 导航 -->
    </header>

    <main class="flex-1">
      <!-- 内容：flex-1 确保撑满剩余空间 -->
      <slot />
    </main>

    <footer class="h-16 shrink-0 border-t bg-gray-50 dark:bg-gray-900">
      <!-- 页脚 -->
    </footer>
  </div>
</template>
```

---

## 主题系统

### Element Plus 主题定制 + CSS 变量 + Tailwind

Element Plus 使用 CSS 变量驱动主题。结合 Tailwind 可以做到三个层次的样式定制：

```css
/* styles/variables.css */
:root {
  /* Element Plus 主题变量覆盖 */
  --el-color-primary: #6366f1;
  --el-color-primary-light-3: #a5b4fc;
  --el-color-primary-dark-2: #4338ca;
  --el-border-radius-base: 8px;

  /* 自定义设计变量 */
  --color-background: #ffffff;
  --color-surface: #f9fafb;
  --color-text-primary: #111827;
  --color-text-secondary: #6b7280;
  --color-border: #e5e7eb;
}

.dark {
  --el-color-primary: #818cf8;
  --el-bg-color: #111827;
  --el-bg-color-overlay: #1f2937;
  --el-border-color: #374151;

  --color-background: #111827;
  --color-surface: #1f2937;
  --color-text-primary: #f9fafb;
  --color-text-secondary: #9ca3af;
  --color-border: #374151;
}
```

```js
// tailwind.config.js — 同步 CSS 变量到 Tailwind 令牌
module.exports = {
  theme: {
    extend: {
      colors: {
        background: 'var(--color-background)',
        surface: 'var(--color-surface)',
        'text-primary': 'var(--color-text-primary)',
        'text-secondary': 'var(--color-text-secondary)',
        border: 'var(--color-border)',
      },
    },
  },
}
```

```vue
<template>
  <!-- Tailwind 中使用 CSS 变量标记的令牌 -->
  <div class="bg-background text-text-primary">
    <el-card class="bg-surface border-border">
      <h1 class="text-xl font-bold">主题适配的卡片</h1>
    </el-card>
  </div>
</template>
```

### 按需引入 Element Plus 主题

Element Plus 支持按需导入，推荐使用 `unplugin-element-plus` 自动导入样式：

```js
// vite.config.ts
import ElementPlus from 'unplugin-element-plus/vite'

export default defineConfig({
  plugins: [
    vue(),
    ElementPlus({
      // 可选：自定义主题的 scss 变量
      // importStyle: 'sass',
    }),
  ],
})
```

---

## 常见问题

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| Element Plus 样式被 Tailwind 覆盖 | Tailwind reset（Preflight）重置了默认样式 | 在 `tailwind.config.js` 中设置 `corePlugins: { preflight: false }`，或确保 Element Plus CSS 后于 Tailwind 加载 |
| `el-dialog` 内部 Tailwind 类不生效 | 对话框渲染在 body 末尾，scoped 样式无法穿透 | 使用 `:deep()` 选择器，或将样式写在非 scoped 的全局样式表中 |
| 暗色模式切换后 Element Plus 组件未响应 | Element Plus 依赖 `html.dark` 类名切换 | 确保 `useDark()` 或手动 toggle 时同时操作 `document.documentElement` 的 `dark` 类 |
| `el-table` 列宽异常 | Tailwind 的 `w-full` 与 Element Plus 内部宽度计算冲突 | 直接用 `style="width: 100%"` 替代 `class="w-full"`，或给表格外层容器指定宽度 |
| `<Transition>` 动画闪烁 | 过渡元素缺少 key，导致 Vue 复用 DOM | 给被过渡的元素添加唯一的 `key` 属性 |
| 响应式断点下布局错乱 | Element Plus 组件的默认 min-width 过大 | 在对应断点下用 Tailwind 覆盖，如 `sm:max-w-[320px]` |
| CSS 变量在 Tailwind 中不生效 | Tailwind 的 JIT 引擎在构建时无法分析动态值 | 使用 `var()` 语法并确保变量在 `:root` 中定义（`bg-[var(--color-bg)]`） |

---

## 文件结构

```
src/
  styles/
    variables.css         # CSS 自定义属性 + Element Plus 主题覆盖
    global.css            # 全局样式、字体导入、Tailwind 指令
    reset.css             # 可选的浅层 CSS Reset
    transitions.css       # 全局 Transition 类名样式
  components/
    base/
      MyButton.vue        # 自定义变体组件
      MyCard.vue
    layout/
      AppHeader.vue
      AppSidebar.vue
      PageContainer.vue   # 粘性布局容器
  composables/
    useTheme.ts           # 主题切换逻辑（useDark 封装）
    useBreakpoint.ts      # 响应式断点侦听
  App.vue
  main.ts                 # 入口：注册 Element Plus、引入全局样式
```

### 入口文件示例

```typescript
// main.ts
import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
// 或按需：import 'element-plus/theme-chalk/src/index.scss'

import App from './App.vue'
import './styles/global.css'
import './styles/variables.css'

const app = createApp(App)
app.use(ElementPlus, { size: 'default' })
app.mount('#app')
```

```css
/* styles/global.css */
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  html {
    font-family: 'Inter', system-ui, sans-serif;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }

  body {
    @apply bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100;
  }
}
```