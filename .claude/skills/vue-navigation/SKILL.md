---
name: vue-navigation
description: Navigation and routing patterns for Vue.js web applications using vue-router 4.4. Use when implementing vue-router, file-based routing with vite-plugin-pages, deep links, or handling navigation state in Vue 3.
---

# Web Navigation (Vue Router 4.4)

## Vue Router (v4.4)

### Basic Setup

```typescript
// router/index.ts
import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  { path: '/', component: () => import('@/pages/HomePage.vue') },
  { path: '/about', component: () => import('@/pages/AboutPage.vue') },
  { path: '/users', component: () => import('@/pages/UsersPage.vue') },
  { path: '/users/:id', component: () => import('@/pages/UserDetailPage.vue') },
  { path: '/:pathMatch(.*)*', component: () => import('@/pages/NotFoundPage.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
```

```vue
<!-- App.vue -->
<template>
  <RouterView />
</template>
```

```typescript
// main.ts
import { createApp } from 'vue'
import App from './App.vue'
import router from './router'

const app = createApp(App)
app.use(router)
app.mount('#app')
```

### Nested Routes & Layouts

```vue
<!-- layouts/DashboardLayout.vue -->
<script setup lang="ts">
import Sidebar from '@/components/Sidebar.vue'
</script>

<template>
  <div class="dashboard">
    <Sidebar />
    <main>
      <RouterView />
    </main>
  </div>
</template>
```

```typescript
// router/index.ts — Nested route config
const routes: RouteRecordRaw[] = [
  {
    path: '/dashboard',
    component: () => import('@/layouts/DashboardLayout.vue'),
    children: [
      { path: '', component: () => import('@/pages/DashboardHome.vue') },
      { path: 'analytics', component: () => import('@/pages/Analytics.vue') },
      { path: 'settings', component: () => import('@/pages/Settings.vue') },
    ],
  },
]
```

```vue
<!-- pages/DashboardHome.vue -->
<script setup lang="ts">
</script>

<template>
  <div>
    <h1>Dashboard Home</h1>
  </div>
</template>
```

### Dynamic Routes

```vue
<!-- pages/UserDetailPage.vue -->
<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

// Route: /users/:id
const userId = computed(() => route.params.id as string)
const tab = computed(() => (route.query.tab as string) || 'profile')

function setTab(newTab: string) {
  router.push({ query: { ...route.query, tab: newTab } })
}
</script>

<template>
  <div>
    <h1>User {{ userId }}</h1>
    <nav>
      <button
        v-for="t in ['profile', 'activity', 'settings']"
        :key="t"
        :class="{ active: tab === t }"
        @click="setTab(t)"
      >
        {{ t }}
      </button>
    </nav>
  </div>
</template>
```

### Programmatic Navigation

```vue
<!-- pages/LoginPage.vue -->
<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { login } from '@/services/auth'

const router = useRouter()
const route = useRoute()

const credentials = ref({ username: '', password: '' })

async function handleLogin() {
  await login(credentials.value)

  // Redirect to intended page or default
  const from = (route.query.redirect as string) || '/dashboard'
  router.push(from)
}

// Other navigation methods
// router.push('/users')           // Push to history
// router.push({ path: '/users', query: { page: 2 } })  // Push with query
// router.push({ name: 'UserDetail', params: { id: '42' } })  // Named route
// router.replace('/users')        // Replace current entry
// router.go(-1)                   // Go back
// router.go(1)                    // Go forward
// router.back()                   // Go back (alias)
</script>

<template>
  <form @submit.prevent="handleLogin">
    <input v-model="credentials.username" placeholder="Username" />
    <input v-model="credentials.password" type="password" placeholder="Password" />
    <button type="submit">Login</button>
  </form>
</template>
```

### RouterLink Component

```vue
<script setup lang="ts">
</script>

<template>
  <!-- Basic link -->
  <RouterLink to="/about">About</RouterLink>

  <!-- Named route with params -->
  <RouterLink :to="{ name: 'UserDetail', params: { id: user.id } }">
    {{ user.name }}
  </RouterLink>

  <!-- With query string -->
  <RouterLink :to="{ name: 'search', query: { q: 'vue' } }">
    Search
  </RouterLink>

  <!-- Custom active class -->
  <RouterLink
    to="/dashboard"
    active-class="router-link-active"
    exact-active-class="router-link-exact-active"
  >
    Dashboard
  </RouterLink>

  <!-- Conditional active styling (v-slot) -->
  <RouterLink to="/settings" v-slot="{ isActive, isExactActive }">
    <li :class="{ active: isActive, 'exact-active': isExactActive }">
      <a>Settings</a>
    </li>
  </RouterLink>

  <!-- Replace history instead of push -->
  <RouterLink to="/login" replace>Login</RouterLink>

  <!-- Custom tag (by default renders <a>) -->
  <RouterLink to="/profile" custom v-slot="{ href, navigate, isActive }">
    <button :class="{ active: isActive }" @click="navigate">
      Profile
    </button>
  </RouterLink>
</template>
```

---

## Manual Route Configuration Patterns

### Route Groups with Meta

```typescript
// router/index.ts
import type { RouteRecordRaw } from 'vue-router'

declare module 'vue-router' {
  interface RouteMeta {
    requiresAuth?: boolean
    hideNav?: boolean
    title?: string
    roles?: string[]
  }
}

const routes: RouteRecordRaw[] = [
  // Public routes
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/pages/LoginPage.vue'),
    meta: { hideNav: true },
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/pages/RegisterPage.vue'),
    meta: { hideNav: true },
  },

  // Protected routes
  {
    path: '/dashboard',
    component: () => import('@/layouts/DashboardLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      { path: '', name: 'Dashboard', component: () => import('@/pages/DashboardHome.vue') },
      {
        path: 'admin',
        component: () => import('@/pages/AdminPage.vue'),
        meta: { requiresAuth: true, roles: ['admin'] },
      },
    ],
  },

  // Catch-all 404
  { path: '/:pathMatch(.*)*', name: 'NotFound', component: () => import('@/pages/NotFoundPage.vue') },
]
```

---

## Navigation Guards

### Global Guards (router.beforeEach)

```typescript
// router/guards.ts
import type { Router } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

export function registerAuthGuard(router: Router) {
  router.beforeEach((to, from, next) => {
    const authStore = useAuthStore()

    // Check if route requires authentication
    if (to.meta.requiresAuth && !authStore.isAuthenticated) {
      // Save intended destination for post-login redirect
      next({ name: 'Login', query: { redirect: to.fullPath } })
      return
    }

    // Check role-based access
    if (to.meta.roles && !to.meta.roles.includes(authStore.userRole)) {
      next({ name: 'Dashboard' }) // Redirect unauthorized users
      return
    }

    next()
  })
}
```

```typescript
// router/index.ts — Register guards
import { createRouter, createWebHistory } from 'vue-router'
import { registerAuthGuard } from './guards'

const router = createRouter({
  history: createWebHistory(),
  routes,
})

registerAuthGuard(router)

export default router
```

### Per-Route Guards

```typescript
// router/index.ts
const routes: RouteRecordRaw[] = [
  {
    path: '/admin',
    component: () => import('@/layouts/AdminLayout.vue'),
    beforeEnter: (to, from, next) => {
      const authStore = useAuthStore()
      if (!authStore.isAuthenticated) {
        next({ name: 'Login' })
      } else {
        next()
      }
    },
    children: [
      // ...
    ],
  },
]
```

### In-Component Guards (Composition API)

```vue
<!-- pages/EditForm.vue — Prevent navigation with unsaved changes -->
<script setup lang="ts">
import { ref, onBeforeUnload } from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'

const isDirty = ref(false)
const router = useRouter()

// In-component navigation guard
onBeforeRouteLeave((to, from, next) => {
  if (!isDirty.value) {
    next()
    return
  }

  const leave = window.confirm('You have unsaved changes. Leave anyway?')
  next(leave)
})

// Be careful with browser-level navigation (close/refresh)
onBeforeUnload((event) => {
  if (isDirty.value) {
    event.preventDefault()
  }
})
</script>

<template>
  <form @change="isDirty = true">
    <input v-model="formData.title" />
    <textarea v-model="formData.content" />
    <button type="submit">Save</button>
  </form>
</template>
```

### Custom Confirm Dialog Guard

```vue
<!-- components/UnsavedChangesGuard.vue -->
<script setup lang="ts">
import { ref } from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'

const props = defineProps<{
  isDirty: boolean
}>()

const showDialog = ref(false)
let pendingNext: ((path?: string | false | void) => void) | null = null

const router = useRouter()

onBeforeRouteLeave((to, from, next) => {
  if (!props.isDirty) {
    next()
    return
  }

  showDialog.value = true
  pendingNext = next
})

function confirmLeave() {
  showDialog.value = false
  pendingNext?.(true)
  pendingNext = null
}

function cancelLeave() {
  showDialog.value = false
  pendingNext?.(false)
  pendingNext = null
}
</script>

<template>
  <Teleport to="body">
    <div v-if="showDialog" class="modal-overlay">
      <div class="modal">
        <h3>Unsaved Changes</h3>
        <p>You have unsaved changes. Leave anyway?</p>
        <div class="modal-actions">
          <button @click="cancelLeave">Stay</button>
          <button class="danger" @click="confirmLeave">Leave</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
```

---

## Loading & Error States

### Suspense with Async Components

```vue
<!-- pages/UserPage.vue -->
<script setup lang="ts">
import { defineAsyncComponent } from 'vue'
import Spinner from '@/components/Spinner.vue'
import ErrorFallback from '@/components/ErrorFallback.vue'

const UserProfile = defineAsyncComponent({
  loader: () => import('@/components/UserProfile.vue'),
  loadingComponent: Spinner,
  errorComponent: ErrorFallback,
  delay: 200,    // Show loading after 200ms
  timeout: 10000, // Error after 10s
})
</script>

<template>
  <Suspense>
    <!-- Component with async setup() -->
    <UserProfile />

    <!-- Fallback during loading -->
    <template #fallback>
      <Spinner />
    </template>
  </Suspense>
</template>
```

### Data Fetching with Route Watch

```vue
<!-- pages/UserDetailPage.vue -->
<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import type { User } from '@/types'

const route = useRoute()
const user = ref<User | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

async function fetchUser(id: string) {
  loading.value = true
  error.value = null
  try {
    const response = await fetch(`/api/users/${id}`)
    if (!response.ok) throw new Error('User not found')
    user.value = await response.json()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

// Re-fetch when route params change
watch(
  () => route.params.id,
  (id) => {
    if (id) fetchUser(id as string)
  },
  { immediate: true }
)
</script>

<template>
  <div>
    <Spinner v-if="loading" />
    <div v-else-if="error" class="error">
      <p>{{ error }}</p>
      <button @click="fetchUser(route.params.id as string)">Retry</button>
    </div>
    <div v-else-if="user">
      <h1>{{ user.name }}</h1>
      <p>{{ user.email }}</p>
    </div>
  </div>
</template>
```

### ErrorBoundary via onErrorCaptured

```vue
<!-- components/ErrorBoundary.vue -->
<script setup lang="ts">
import { ref, onErrorCaptured } from 'vue'

const hasError = ref(false)
const errorMessage = ref('')

onErrorCaptured((err, instance, info) => {
  hasError.value = true
  errorMessage.value = (err as Error).message
  // Prevent error from propagating further
  return false
})

function reset() {
  hasError.value = false
  errorMessage.value = ''
}
</script>

<template>
  <slot v-if="!hasError" />
  <div v-else class="error-boundary">
    <h2>Something went wrong!</h2>
    <p>{{ errorMessage }}</p>
    <button @click="reset">Try again</button>
  </div>
</template>
```

---

## Scroll Restoration

### Built-in scrollBehavior

```typescript
// router/index.ts
const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(to, from, savedPosition) {
    // Saved position (browser back/forward)
    if (savedPosition) {
      return savedPosition
    }

    // Scroll to hash anchor
    if (to.hash) {
      return {
        el: to.hash,
        behavior: 'smooth',
      }
    }

    // Scroll to top for all other navigation
    return { top: 0 }
  },
})
```

### Per-Route Scroll Behavior

```typescript
// router/index.ts
const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(to, from, savedPosition) {
    // Keep scroll position within a list
    if (to.path === '/users' && from.path.startsWith('/users/')) {
      return false // Do not scroll
    }

    // Delayed scroll (wait for async data)
    if (to.meta.scrollToTop) {
      return new Promise((resolve) => {
        setTimeout(() => resolve({ top: 0, behavior: 'smooth' }), 300)
      })
    }

    return { top: 0 }
  },
})
```

---

## Deep Linking / Query Params

### Type-Safe Query Param Composable

```typescript
// composables/useFilters.ts
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

interface Filters {
  category?: string
  sort?: 'asc' | 'desc'
  page?: number
}

export function useFilters() {
  const route = useRoute()
  const router = useRouter()

  const filters = computed<Filters>(() => ({
    category: (route.query.category as string) || undefined,
    sort: (route.query.sort as 'asc' | 'desc') || undefined,
    page: route.query.page ? Number(route.query.page) : 1,
  }))

  function setFilters(newFilters: Partial<Filters>) {
    const query = { ...route.query }

    for (const [key, value] of Object.entries(newFilters)) {
      if (value !== undefined && value !== null) {
        query[key] = String(value)
      } else {
        delete query[key]
      }
    }

    router.push({ query })
  }

  return { filters, setFilters }
}
```

```vue
<!-- pages/ProductList.vue -->
<script setup lang="ts">
import { useFilters } from '@/composables/useFilters'

const { filters, setFilters } = useFilters()
</script>

<template>
  <div>
    <select
      :value="filters.category"
      @change="setFilters({ category: ($event.target as HTMLSelectElement).value })"
    >
      <option value="">All Categories</option>
      <option value="electronics">Electronics</option>
      <option value="clothing">Clothing</option>
    </select>

    <select
      :value="filters.sort"
      @change="setFilters({ sort: ($event.target as HTMLSelectElement).value as 'asc' | 'desc' })"
    >
      <option value="asc">Price: Low to High</option>
      <option value="desc">Price: High to Low</option>
    </select>

    <ProductGrid :products="products" />

    <Pagination
      :page="filters.page"
      @change="(p: number) => setFilters({ page: p })"
    />
  </div>
</template>
```

### Cross-Route Deep Link

```vue
<!-- composables/useDeepLink.ts -->
<script setup lang="ts">
import { useRouter } from 'vue-router'

export function useDeepLink() {
  const router = useRouter()

  function navigateToItem(type: string, id: string) {
    router.push({ name: 'ItemDetail', params: { type, id } })
  }

  function navigateWithContext(path: string, state?: Record<string, unknown>) {
    router.push({ path, state })
  }

  return { navigateToItem, navigateWithContext }
}
</script>
```

---

## Common Patterns

### Redirect After Action

```vue
<!-- components/CreateItemForm.vue -->
<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { createItem } from '@/services/items'

const router = useRouter()
const formData = ref({ title: '', content: '' })

async function handleSubmit() {
  const result = await createItem(formData.value)
  router.push({ name: 'ItemDetail', params: { id: result.id } })
}

// After login (with redirect param)
async function handleLogin() {
  await login(credentials.value)
  const redirectTo = (route.query.redirect as string) || '/dashboard'
  router.push(redirectTo)
}
</script>
```

### Tab Navigation with URL

```vue
<!-- components/ProfileTabs.vue -->
<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const tabs = ['overview', 'activity', 'settings'] as const
type Tab = (typeof tabs)[number]

const activeTab = computed<Tab>(() => {
  const tab = route.query.tab as string
  return tabs.includes(tab as Tab) ? (tab as Tab) : 'overview'
})

function setTab(tab: Tab) {
  router.push({ query: { tab } })
}
</script>

<template>
  <nav>
    <button
      v-for="t in tabs"
      :key="t"
      :class="{ active: activeTab === t }"
      @click="setTab(t)"
    >
      {{ t }}
    </button>
  </nav>
  <component :is="tabContentComponent(activeTab)" />
</template>
```

### Breadcrumbs from Route Matched

```vue
<!-- components/Breadcrumbs.vue -->
<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

interface Crumb {
  label: string
  to?: { name: string }
}

const breadcrumbs = computed<Crumb[]>(() => {
  return route.matched
    .filter((r) => r.meta.breadcrumb)
    .map((r) => ({
      label: r.meta.breadcrumb as string,
      to: r.name ? { name: r.name as string } : undefined,
    }))
})
</script>

<template>
  <nav aria-label="Breadcrumb">
    <ol>
      <li v-for="(crumb, i) in breadcrumbs" :key="i">
        <RouterLink v-if="crumb.to" :to="crumb.to">
          {{ crumb.label }}
        </RouterLink>
        <span v-else>{{ crumb.label }}</span>
      </li>
    </ol>
  </nav>
</template>
```

### Route Transitions

```vue
<!-- App.vue -->
<script setup lang="ts">
import { useRoute } from 'vue-router'

const route = useRoute()
</script>

<template>
  <RouterView v-slot="{ Component, route: currentRoute }">
    <Transition :name="currentRoute.meta.transition as string || 'fade'" mode="out-in">
      <component :is="Component" :key="currentRoute.path" />
    </Transition>
  </RouterView>
</template>

<style>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
```

---

## Common Issues

| Issue | Solution |
|-------|----------|
| RouterLink not working / 404 on click | Ensure `app.use(router)` in `main.ts`; check that `<RouterView />` renders in a parent component |
| Route not matching | Check route order (specific before dynamic); verify param syntax (`:id` not `[id]`) |
| Params/query not reactive | Access via `computed(() => route.params.id)` or destructure with `toRefs` |
| Back button doesn't trigger data reload | Use `router.beforeEach` or `watch` on `route.params` / `route.query`; consider `sensitive: true` for route matching |
| State lost on refresh | Store state in URL query/params or `route.meta`, not in component-only state |
| Scroll position wrong | Configure `scrollBehavior` in router options; check for async rendering with `scrollBehavior` promise |
| 404 in production (SPA) | Configure server fallback to `index.html` (nginx: `try_files`, Apache: `FallbackResource`, Vue CLI/Vite dev server handles this by default) |
| Named route not resolving | Verify route `name` is unique; use `resolve({ name: 'RouteName' })` to debug at runtime |
| RouterView not updating on same route | Add `:key="$route.fullPath"` on `<RouterView />` to force re-render when query changes but path stays the same |
| Multiple RouterViews for named views | Use `<RouterView name="sidebar" />` alongside default `<RouterView />`, and reference `components` (plural) in route config |
| `onBeforeRouteLeave` not firing | Only works in components directly rendered by `<RouterView />`; not in nested utility components |