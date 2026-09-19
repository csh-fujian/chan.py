---
name: vue-pinia-patterns
description: Pinia state management patterns for Vue. Use when working with Pinia stores, debugging state timing issues, or implementing async actions. Works for Vue web and Vue Native applications.
---

# Pinia Patterns for Vue

## Problem Statement

Pinia's reactivity-first design hides important details. State mutations are synchronous and Vue batches component updates. Stores are reactive by default, but destructuring breaks reactivity — `storeToRefs()` is essential. Async actions in stores need careful handling. Understanding these internals prevents subtle bugs.

---

## Pattern: State Mutations are Synchronous, Component Updates are Batched

**Problem:** Assuming the DOM is updated immediately after mutating Pinia state.

```typescript
export const useStore = defineStore('main', () => {
  const count = ref(0)

  function increment() {
    count.value++
    // State IS updated here synchronously
    console.log(count.value) // ✅ Shows new value

    // But the DOM hasn't updated yet
    // Use nextTick() to wait for DOM update
  }

  return { count, increment }
})
```

**Key insight:**
- Pinia state mutations are synchronous
- Vue's reactivity system updates the DOM asynchronously (batched)
- Use `nextTick()` when you need the DOM after a state change

```typescript
import { nextTick } from 'vue'

async function incrementAndFocus() {
  count.value++
  await nextTick() // Wait for DOM update
  document.getElementById('counter')?.focus()
}
```

**When this matters:**
- Chaining multiple state updates
- Accessing DOM elements after state changes
- Debugging "stale" DOM values

---

## Pattern: storeToRefs() Preserves Reactivity

**Problem:** Destructuring a Pinia store directly extracts plain values, breaking reactivity.

```typescript
import { storeToRefs } from 'pinia'

const store = useDataStore()

// ❌ WRONG: Destructuring loses reactivity
const { data, loading } = store
// data and loading are plain values, not reactive
// They won't update in the template or watchers

// ✅ CORRECT: Use storeToRefs to extract reactive refs
const { data, loading } = storeToRefs(store)
// data and loading are Ref objects — fully reactive

// ✅ CORRECT: Store actions can be destructured directly (not reactive, just functions)
const { fetchData, reset } = store
```

**Rule:** When destructuring state or getters from a Pinia store, always use `storeToRefs()`. Actions can be destructured normally.

---

## Pattern: Async Actions in Stores

**Problem:** Async actions need proper Promise handling and careful state reads after awaits.

```typescript
export const useDataStore = defineStore('data', () => {
  const data = ref<Data | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  // ❌ WRONG: No error handling, race conditions
  function fetchDataBad(id: string) {
    loading.value = true
    api.fetch(id).then((result) => {
      data.value = result
      loading.value = false
    })
    // Returns nothing, caller can't await
  }

  // ✅ CORRECT: Proper async action
  async function fetchData(id: string) {
    loading.value = true
    error.value = null

    try {
      const result = await api.fetch(id)
      // After await, read current state from the store (it's reactive)
      if (loading.value) { // Check we're still loading (not cancelled)
        data.value = result
      }
    } catch (err) {
      error.value = (err as Error).message
    } finally {
      loading.value = false
    }
  }

  return { data, loading, error, fetchData }
})

// Caller can properly await
const store = useDataStore()
await store.fetchData('123')
```

**Key insight:** After an `await`, always read reactive state directly from the store (through `store.xxx` or inside the store via `xxx.value`). Never rely on locally destructured values captured before the await.

---

## Pattern: Selector Stability with computed()

**Problem:** Creating derived state that behaves like a selector without boilerplate.

```typescript
import { storeToRefs } from 'pinia'
import { computed } from 'vue'

const store = useStore()

// ✅ Extract individual reactive refs (stable, no allocation overhead)
const { name, count } = storeToRefs(store)

// ✅ Derived state with computed (auto-caches, tracks dependencies)
const total = computed(() => store.items.length)
const activeItems = computed(() => store.items.filter(i => i.active))
const sortedByName = computed(() =>
  [...store.items].sort((a, b) => a.name.localeCompare(b.name))
)

// ✅ Multiple derived values in one computed
const summary = computed(() => ({
  total: store.items.length,
  active: store.items.filter(i => i.active).length,
  hasErrors: store.items.some(i => i.error),
}))
```

**Note:** Unlike Zustand selectors, Vue's `computed` is the idiomatic way to derive state. It automatically tracks which reactive properties are accessed and only recomputes when those change.

---

## Pattern: Derived State (Getters)

Pinia supports getters two ways — Setup Store style and Options Store style.

### Setup Store Style (Recommended)

```typescript
export const useCartStore = defineStore('cart', () => {
  const items = ref<CartItem[]>([])

  // ✅ Derived state as computed
  const totalItems = computed(() => items.value.length)

  const totalPrice = computed(() =>
    items.value.reduce((sum, item) => sum + item.price * item.quantity, 0)
  )

  const hasItems = computed(() => items.value.length > 0)

  return { items, totalItems, totalPrice, hasItems }
})
```

### Options Store Style

```typescript
export const useCartStore = defineStore('cart', {
  state: () => ({
    items: [] as CartItem[],
  }),
  getters: {
    totalItems: (state) => state.items.length,
    totalPrice: (state) =>
      state.items.reduce((sum, item) => sum + item.price * item.quantity, 0),
    hasItems: (state) => state.items.length > 0,
  },
})
```

**Recommendation:** Use Setup Store style for consistency with the Composition API and better IDE support.

---

## Pattern: Store Subscriptions for Side Effects

**Problem:** Need to react to Pinia state changes outside components.

### Inside Components

```typescript
import { watch } from 'vue'
import { storeToRefs } from 'pinia'

// Watch specific state with watch
const store = useDataStore()
const { data } = storeToRefs(store)

watch(data, (newData, oldData) => {
  console.log('Data changed:', { old: oldData, new: newData })
  // Persist, send analytics, etc.
})
```

### Outside Components (store.$subscribe)

```typescript
const store = useDataStore()

store.$subscribe((mutation, state) => {
  console.log('Store changed:', mutation.storeId)
  console.log('New state:', state)
  // Persist to localStorage, sync to server, etc.
})

// With specific event type filtering
store.$subscribe((mutation, state) => {
  if (mutation.type === 'patch object') {
    // $patch was called
  }
  if (mutation.type === 'direct') {
    // Direct state assignment
  }
})
```

---

## Pattern: $patch for Batch Updates

**Problem:** Multiple individual state mutations each trigger reactivity updates.

```typescript
const store = useFormStore()

// ❌ Slower: Three separate reactivity triggers
store.name = 'John'
store.email = 'john@example.com'
store.age = 30

// ✅ Better: Single batched update via $patch
store.$patch({
  name: 'John',
  email: 'john@example.com',
  age: 30,
})

// ✅ Also works with a function for complex logic
store.$patch((state) => {
  state.name = 'John'
  state.email = 'john@example.com'
  state.age = 30
  // All mutations are batched into one update
})
```

**Use `$patch` when:**
- Setting multiple store properties at once
- Reducing the number of watcher/computed re-evaluations
- Applying partial state updates from external sources (e.g., API responses)

---

## Pattern: Store Composition

**Problem:** Sharing logic between stores without inheritance.

```typescript
// Shared authentication logic
function useAuth() {
  const token = ref<string | null>(null)
  const isAuthenticated = computed(() => !!token.value)

  async function login(credentials: Credentials) {
    const result = await authApi.login(credentials)
    token.value = result.token
  }

  function logout() {
    token.value = null
  }

  return { token, isAuthenticated, login, logout }
}

// Compose into a feature store
export const useUserStore = defineStore('user', () => {
  const profile = ref<UserProfile | null>(null)

  // Compose auth logic
  const { token, isAuthenticated, login, logout } = useAuth()

  // Use token for authenticated requests
  async function fetchProfile() {
    if (!token.value) return
    profile.value = await userApi.getProfile(token.value)
  }

  watch(token, (newToken) => {
    if (newToken) fetchProfile()
    else profile.value = null
  })

  return {
    profile,
    token,
    isAuthenticated,
    login,
    logout,
    fetchProfile,
  }
})
```

---

## Pattern: Setup Store vs Options Store

| Aspect | Setup Store | Options Store |
|--------|------------|---------------|
| Syntax | `defineStore('id', () => { ... })` | `defineStore('id', { state, getters, actions })` |
| Style | Composition API | Options API |
| TypeScript | Natural inference | Requires explicit typing sometimes |
| Composables | Can use `useXxx()` composables | Cannot use composables |
| Flexibility | Higher (can compose logic freely) | More structured |
| Recommendation | **Preferred** for new projects | Use if migrating from Vuex or prefer Options API |

```typescript
// Setup Store (recommended)
export const useCounterSetup = defineStore('counter-setup', () => {
  const count = ref(0)
  const double = computed(() => count.value * 2)

  function increment() { count.value++ }

  return { count, double, increment }
})

// Options Store (alternative)
export const useCounterOptions = defineStore('counter-options', {
  state: () => ({ count: 0 }),
  getters: { double: (state) => state.count * 2 },
  actions: { increment() { this.count++ } },
})
```

---

## Pattern: Testing Pinia Stores

**Problem:** Tests need isolated Pinia instances and store state reset.

```typescript
import { setActivePinia, createPinia } from 'pinia'
import { useDataStore } from '@/stores/data'

// vi.mock is hoisted to module root — define mocks here, not inside tests
vi.mock('@/api', () => ({
  fetch: vi.fn()
}))

import { fetch } from '@/api'

describe('Data Store', () => {
  // Create fresh Pinia instance before each test
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('fetches data correctly', async () => {
    const store = useDataStore()

    vi.mocked(fetch).mockResolvedValue({ id: '1', name: 'Test' })

    await store.fetchData('123')

    expect(store.data).toBeDefined()
    expect(store.loading).toBe(false)
    expect(store.error).toBeNull()
  })

  it('handles errors gracefully', async () => {
    const store = useDataStore()

    vi.mocked(fetch).mockRejectedValue(new Error('Network error'))

    await store.fetchData('123')

    expect(store.error).toBe('Network error')
    expect(store.loading).toBe(false)
  })
})
```

### $reset() for Testing

```typescript
// Options Store supports $reset() natively
export const useFormStore = defineStore('form', {
  state: () => ({
    name: '',
    email: '',
  }),
})

// In tests:
beforeEach(() => {
  setActivePinia(createPinia())
  const store = useFormStore()
  store.$reset() // Resets to initial state
})

// Setup Stores can define their own reset
export const useFormSetupStore = defineStore('form-setup', () => {
  const name = ref('')
  const email = ref('')

  function $reset() {
    name.value = ''
    email.value = ''
  }

  return { name, email, $reset }
})
```

---

## Pattern: Persist Middleware

**Problem:** Persisting Pinia state across sessions.

```typescript
// Install: npm install pinia-plugin-persistedstate

// main.ts - Register the plugin
import { createPinia } from 'pinia'
import piniaPluginPersistedstate from 'pinia-plugin-persistedstate'

const pinia = createPinia()
pinia.use(piniaPluginPersistedstate)

// stores/preferences.ts - Enable per-store
export const usePreferencesStore = defineStore(
  'preferences',
  () => {
    const theme = ref<'light' | 'dark'>('light')
    const language = ref('zh-CN')

    function toggleTheme() {
      theme.value = theme.value === 'light' ? 'dark' : 'light'
    }

    return { theme, language, toggleTheme }
  },
  {
    persist: true, // Persist entire store to localStorage
  }
)

// For fine-grained control, pass persist options:
// export const useAuthStore = defineStore('auth', () => ({ ... }), {
//   persist: { key: 'auth-storage', storage: sessionStorage, pick: ['token', 'sessionExpiry'] },
// })
```

For more options, see [pinia-plugin-persistedstate docs](https://prazdevs.github.io/pinia-plugin-persistedstate/).

---

## Pattern: Debugging State Changes

### Vue DevTools Pinia Tab

1. Open Vue DevTools
2. Go to the **Pinia** tab
3. See all active stores with their current state
4. Watch state changes in real-time
5. Use the timeline to replay state mutations

### Timeline Tracking

The Pinia tab shows a history of state mutations with:
- Which store was modified
- What changed (old value vs new value)
- When the change happened
- Which action triggered it

### Manual Logging

```typescript
export const useDataStore = defineStore('data', () => {
  const data = ref<Record<string, unknown>>({})

  function saveData(id: string, value: unknown) {
    console.log('[data.saveData] Before:', {
      id,
      value,
      currentData: { ...data.value },
    })

    data.value = { ...data.value, [id]: value }

    console.log('[data.saveData] After:', {
      data: { ...data.value },
    })
  }

  return { data, saveData }
})
```

### $subscribe for Debugging

```typescript
if (import.meta.env.DEV) {
  const store = useDataStore()
  store.$subscribe((mutation, state) => {
    console.group(`[${mutation.storeId}] State Change`)
    console.log('Type:', mutation.type)
    console.log('Events:', mutation.events)
    console.log('New State:', JSON.parse(JSON.stringify(state)))
    console.groupEnd()
  })
}
```

---

## Common Pitfalls

| Pitfall | Solution |
|---------|----------|
| Stale closure after await | Access state directly from the store (it's reactive); never rely on destructured values captured before `await` |
| Destructuring loses reactivity | Always use `storeToRefs()` when destructuring state or getters |
| Action not awaitable | Always make async actions return a Promise (use `async function`) |
| State values not reactive | Use `storeToRefs` to preserve reactivity when destructuring; never destructure state directly |
| Selector returns new object | Use `computed()` — Vue tracks individual property access, not reference equality |
| Multiple state updates slow | Use `store.$patch()` for batch updates |
| Store not resetting between tests | Use `setActivePinia(createPinia())` in `beforeEach` and `store.$reset()` |
| Large object causing slowness | Use `shallowRef` inside store, or `markRaw` for non-reactive data |
| Watcher runs too often | Prefer `computed` over `watch`; use specific watched paths instead of `deep: true` |

---

## Common Pinia Gotchas

### Gotcha 1: Setup Stores Cannot Use `$reset()` by Default

```typescript
// Options Stores: $reset() works natively
// Setup Stores: You must define it yourself

export const useSetupStore = defineStore('my-store', () => {
  const count = ref(0)

  // Define $reset manually for Setup Stores
  function $reset() {
    count.value = 0
  }

  return { count, $reset }
})
```

### Gotcha 2: storeToRefs Only Extracts Reactive State and Getters

```typescript
const store = useDataStore()

// ✅ storeToRefs extracts: ref(), computed(), reactive(), shallowRef()
const { data, loading, totalItems } = storeToRefs(store)

// ❌ storeToRefs does NOT extract actions
// Actions are functions, keep them on the store object
const { fetchData } = store // Correct — plain destructure for actions
```

### Gotcha 4: Accessing Other Stores

```typescript
// Inside a Pinia store, access another store by calling it:
export const useOrderStore = defineStore('order', () => {
  // Access another store
  const userStore = useUserStore()
  const cartStore = useCartStore()

  async function placeOrder() {
    if (!userStore.isAuthenticated) {
      throw new Error('Must be logged in')
    }
    const items = cartStore.items // Directly reactive
    // ...
  }

  return { placeOrder }
})
```