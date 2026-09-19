---
name: vue-testing
description: Testing patterns for Vue 3.5 with Vitest and @vue/test-utils. Use when writing tests, mocking modules, testing Pinia stores, testing composables, or debugging test failures in Vue web applications.
---

# Vue 3.5 Testing

## Problem Statement

Vue 3.5 testing requires understanding component rendering, reactive state, composables, and async state management. This skill covers Vitest with @vue/test-utils patterns for Vue 3 web applications, including Pinia stores, vue-router, and @tanstack/vue-query.

---

## Pattern: Pinia Store Testing

**Problem:** Store state persists between tests, causing flaky tests.

```typescript
import { setActivePinia, createPinia } from 'pinia'
import { useAppStore } from '@/stores/appStore'

const initialState = {
  items: [],
  loading: false,
  error: null,
}

describe('App Store', () => {
  // Fresh Pinia instance per test
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('adds item to store', async () => {
    const store = useAppStore()

    await store.addItem({ id: '1', name: 'Test' })

    expect(store.items).toHaveLength(1)
  })

  it('handles loading state', async () => {
    const store = useAppStore()

    const loadPromise = store.fetchItems()
    expect(store.loading).toBe(true)

    await loadPromise
    expect(store.loading).toBe(false)
  })

  it('resets on $reset', () => {
    const store = useAppStore()
    store.items = [{ id: '1', name: 'Test' }]

    store.$reset()

    expect(store.items).toEqual([])
  })
})
```

**Key points:**
- Call `setActivePinia(createPinia())` in `beforeEach` for a fresh instance per test
- Access reactive state properties directly (`store.items`, `store.loading`)
- Use `$reset()` if the store defines a reset via the state factory
- Pinia actions support async/await; just `await` the call

---

## Pattern: Async Store Operations

**Problem:** Testing async Pinia actions with proper waiting.

```typescript
import { setActivePinia, createPinia } from 'pinia'
import { nextTick } from 'vue'
import { flushPromises } from '@vue/test-utils'

describe('App Store - Async', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('loads data correctly', async () => {
    const store = useAppStore()

    await store.loadData('123')

    expect(Object.keys(store.data).length).toBeGreaterThan(0)
  })

  it('completes multi-step flow', async () => {
    const store = useAppStore()

    // Step 1
    await store.loadItems()
    expect(store.items).toBeDefined()

    // Step 2: Flush pending microtasks
    await flushPromises()
    expect(store.processed).toBe(true)
  })

  it('reflects reactive updates in DOM after store change', async () => {
    const store = useAppStore()
    const wrapper = mount(ItemList)

    await store.addItem({ id: '1', name: 'New Item' })
    await nextTick()

    expect(wrapper.text()).toContain('New Item')
  })
})
```

**Key points:**
- Pinia actions return promises; no need for `act()`
- Use `flushPromises()` from @vue/test-utils to drain unsettled microtasks
- Use Vue's `nextTick()` when waiting for reactive DOM update
- Store mutations via an action are synchronous with reactivity -- component wrappers pick them up after `nextTick()`

---

## Pattern: Component Testing

```typescript
import { mount, shallowMount } from '@vue/test-utils'
import { describe, it, expect, vi } from 'vitest'
import ItemCard from '@/components/ItemCard.vue'

describe('ItemCard', () => {
  const mockItem = {
    id: '1',
    title: 'Test Item',
    price: 99.99,
  }

  it('displays item data', () => {
    const wrapper = mount(ItemCard, {
      props: { item: mockItem }
    })

    expect(wrapper.text()).toContain('Test Item')
    expect(wrapper.text()).toContain('$99.99')
  })

  it('emits select event on button click', async () => {
    const wrapper = mount(ItemCard, {
      props: { item: mockItem }
    })

    await wrapper.find('button').trigger('click')

    expect(wrapper.emitted('select')).toBeTruthy()
    expect(wrapper.emitted('select')[0]).toEqual([mockItem.id])
  })

  it('shows loading state', () => {
    const wrapper = mount(ItemCard, {
      props: { item: mockItem, loading: true }
    })

    expect(wrapper.find('[data-testid="loading-spinner"]').exists()).toBe(true)
  })

  it('matches snapshot', () => {
    const wrapper = mount(ItemCard, {
      props: { item: mockItem }
    })

    expect(wrapper.html()).toMatchSnapshot()
  })
})
```

**Key points:**
- Use `mount()` for full rendering (child components included)
- Use `shallowMount()` to stub child components
- `wrapper.text()` returns the full rendered text
- `wrapper.emitted('eventName')` returns an array of event payload arrays
- Data attributes (`data-testid`) are preferred over CSS class selectors for test stability
- Async interactions must be awaited

---

## Pattern: @tanstack/vue-query Testing

**Problem:** Components using @tanstack/vue-query need a QueryClient and VueQueryPlugin.

```typescript
import { mount } from '@vue/test-utils'
import { VueQueryPlugin, QueryClient } from '@tanstack/vue-query'

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
    },
  })
}

function mountWithQuery(component, options = {}) {
  const queryClient = createTestQueryClient()
  options.global = options.global || {}
  options.global.plugins = [
    ...(options.global.plugins || []),
    [VueQueryPlugin, { queryClient }],
  ]
  return mount(component, options)
}

// Usage in tests
it('fetches and displays data', async () => {
  const wrapper = mountWithQuery(UserProfile, {
    props: { userId: '123' }
  })

  // Shows loading initially
  expect(wrapper.text()).toContain('Loading...')

  // Wait for data
  await flushPromises()
  expect(wrapper.text()).toContain('John Doe')
})
```

**Key points:**
- Install `VueQueryPlugin` through the `global.plugins` mount option
- Create a fresh `QueryClient` per test with `retry: false` to avoid async retries
- Use `flushPromises()` to wait for async query resolution

---

## Pattern: Composable Testing

```typescript
import { setActivePinia, createPinia } from 'pinia'
import { useAuth } from '@/composables/useAuth'
import { ref } from 'vue'

describe('useAuth', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('signs in user', async () => {
    // Composables are called directly -- no renderHook needed
    const { user, isAuthenticated, signIn } = useAuth()

    await signIn('test@example.com', 'password')

    expect(user.value).toBeDefined()
    expect(isAuthenticated.value).toBe(true)
  })

  it('handles sign in error', async () => {
    const { error, signIn } = useAuth()

    try {
      await signIn('invalid@example.com', 'wrong')
    } catch (e) {
      // Expected
    }

    expect(error.value).toBe('Invalid credentials')
  })
})

// Composable that reads from Pinia store
describe('useUserData', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('returns current user data', () => {
    // Pre-populate store
    const userStore = useUserStore()
    userStore.user = { id: '1', name: 'Test' }

    const { user } = useUserData()

    expect(user.value.name).toBe('Test')
  })
})

// Composable with watchers or lifecycle hooks
describe('useDebounce', () => {
  it('debounces input value', async () => {
    vi.useFakeTimers()

    const input = ref('')
    const { debounced } = useDebounce(input, { delay: 300 })

    input.value = 'hello'
    await nextTick()

    vi.advanceTimersByTime(300)

    expect(debounced.value).toBe('hello')
    vi.useRealTimers()
  })
})
```

**Key points:**
- Composables are just functions -- call them directly in tests
- Access reactive refs with `.value` in assertions
- Set up Pinia via `setActivePinia(createPinia())` for composables that use stores
- Use `vi.useFakeTimers()` / `vi.useRealTimers()` for debounce or throttle composables

---

## Pattern: Mocking API Calls

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock fetch globally
const mockFetch = vi.fn()
global.fetch = mockFetch

beforeEach(() => {
  mockFetch.mockClear()
})

it('fetches user data', async () => {
  mockFetch.mockResolvedValueOnce({
    ok: true,
    json: async () => ({ id: '1', name: 'John' }),
  })

  const wrapper = mount(UserProfile, {
    props: { userId: '1' }
  })

  await flushPromises()

  expect(wrapper.text()).toContain('John')
  expect(mockFetch).toHaveBeenCalledWith('/api/users/1')
})

// Mock specific module with vi.mock
vi.mock('@/api/users', () => ({
  getUser: vi.fn(),
  updateUser: vi.fn(),
}))

import { getUser, updateUser } from '@/api/users'

it('loads and updates user', async () => {
  vi.mocked(getUser).mockResolvedValue({ id: '1', name: 'John' })
  vi.mocked(updateUser).mockResolvedValue({ id: '1', name: 'Jane' })

  // Test component that uses these APIs
})
```

**Key points:**
- Use `vi.fn()` instead of `jest.fn()`
- Use `vi.mock()` for module-level mocking (hoisted to top of file)
- Use `vi.mocked()` to infer mock types (type-safe wrappers)
- `mockClear()` resets call history; `mockReset()` also resets implementation
- Use `flushPromises()` after triggering async operations to settle pending promises

---

## Pattern: Router Testing

```typescript
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { describe, it, expect } from 'vitest'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', component: HomePage },
    { path: '/profile', component: ProfilePage },
    { path: '/users/:id', component: UserPage },
  ],
})

// Mount a component that uses router link or $route
function mountWithRouter(component, options = {}) {
  options.global = options.global || {}
  options.global.plugins = [
    ...(options.global.plugins || []),
    router,
  ]
  return mount(component, options)
}

// Test navigation
it('navigates to profile on button click', async () => {
  await router.push('/')

  const wrapper = mountWithRouter(App)

  await wrapper.find('[data-testid="profile-link"]').trigger('click')
  await router.isReady()

  expect(wrapper.text()).toContain('Profile Page')
})

// Test with route params
it('displays user from route params', async () => {
  await router.push('/users/123')
  await router.isReady()

  const wrapper = mount(UserPage, {
    global: { plugins: [router] }
  })

  expect(wrapper.text()).toContain('User 123')
})

// Test route change is reactive
it('reacts to route param changes', async () => {
  await router.push('/users/123')
  await router.isReady()

  const wrapper = mount(UserPage, {
    global: { plugins: [router] }
  })

  await router.push('/users/456')
  await nextTick()

  expect(wrapper.text()).toContain('User 456')
})
```

**Key points:**
- Use `createMemoryHistory()` instead of web history for isolated tests
- Install router via `global.plugins` in mount options
- `await router.push()` and `await router.isReady()` before assertions
- Use `nextTick()` after route changes to wait for reactivity

---

## Pattern: Form Testing

```typescript
import { mount } from '@vue/test-utils'
import { describe, it, expect, vi } from 'vitest'

describe('LoginForm', () => {
  it('submits form with entered data', async () => {
    const onSubmit = vi.fn()

    const wrapper = mount(LoginForm, {
      props: { onSubmit }
    })

    await wrapper.find('input[type="email"]').setValue('test@example.com')
    await wrapper.find('input[type="password"]').setValue('password123')
    await wrapper.find('form').trigger('submit.prevent')

    expect(onSubmit).toHaveBeenCalledWith({
      email: 'test@example.com',
      password: 'password123',
    })
  })

  it('shows validation errors', async () => {
    const wrapper = mount(LoginForm)

    // Submit without filling form
    await wrapper.find('form').trigger('submit.prevent')
    await nextTick()

    expect(wrapper.text()).toContain('Email is required')
    expect(wrapper.text()).toContain('Password is required')
  })

  it('disables submit while loading', () => {
    const wrapper = mount(LoginForm, {
      props: { loading: true }
    })

    const button = wrapper.find('button[type="submit"]')
    expect(button.attributes('disabled')).toBeDefined()
  })

  it('handles input v-model binding', async () => {
    const wrapper = mount(LoginForm)

    const emailInput = wrapper.find('input[type="email"]')
    await emailInput.setValue('test@example.com')

    // Check that the input element's value updated
    expect(emailInput.element.value).toBe('test@example.com')
  })
})
```

**Key points:**
- Use `wrapper.find('...').setValue(value)` to simulate user typing
- Trigger form submit with `trigger('submit.prevent')` if using `.prevent` modifier
- Use `nextTick()` after triggers that cause reactive updates
- Check disabled state with `button.attributes('disabled')`
- `element.value` gives the raw DOM element's value for v-model verification

---

## Pattern: Using nextTick and flushPromises

**Problem:** "Test finished without waiting for async updates" or state changes not reflected in assertions.

```typescript
import { nextTick } from 'vue'
import { flushPromises } from '@vue/test-utils'

// WRONG - state update happens after test
it('loads data', () => {
  const wrapper = mount(DataComponent)
  // Component fetches data async, update happens after test ends
})

// CORRECT - wait for async completion
it('loads data', async () => {
  const wrapper = mount(DataComponent)

  // Wait for pending promises to resolve
  await flushPromises()
  // Wait for Vue reactivity to flush
  await nextTick()

  expect(wrapper.text()).toContain('Data loaded')
})

// CORRECT - test reactive DOM update after user interaction
it('updates list after input', async () => {
  const wrapper = mount(TodoList)

  await wrapper.find('input').setValue('Buy milk')
  await wrapper.find('button.add').trigger('click')
  await nextTick()

  expect(wrapper.text()).toContain('Buy milk')
})

// When to use which:
// - flushPromises(): after async operations (API calls, timers, etc.)
// - nextTick(): after reactive state changes that trigger DOM updates
// - Often use both together: await flushPromises(); await nextTick();
```

**Key points:**
- `flushPromises()` drains the microtask queue (resolved promises)
- `nextTick()` waits for Vue's next DOM update tick
- After component mount with async setup, use both in order: `await flushPromises()` then `await nextTick()`
- No `act()` function needed in Vue testing

---

## Pattern: Testing with Pinia + Router (Provider Wrapper)

```typescript
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import { VueQueryPlugin, QueryClient } from '@tanstack/vue-query'

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
    },
  })
}

/**
 * Mount a component with Pinia, vue-router, and vue-query loaded as global plugins.
 * Pass additional global options (plugins, stubs, etc.) via options.global.
 */
function mountWithPlugins(component, options = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)

  const router = createRouter({
    history: createMemoryHistory(),
    routes: options.routes || [],
  })

  const queryClient = createTestQueryClient()

  const global = {
    plugins: [
      pinia,
      router,
      [VueQueryPlugin, { queryClient }],
      ...(options.global?.plugins || []),
    ],
    ...options.global,
  }

  return {
    wrapper: mount(component, { ...options, global }),
    pinia,
    router,
    queryClient,
  }
}

// Use in tests
it('renders dashboard with all context', async () => {
  const { wrapper, router } = mountWithPlugins(Dashboard, {
    routes: [
      { path: '/', component: Dashboard },
    ],
  })

  await router.push('/')
  await router.isReady()
  await flushPromises()
  await nextTick()

  expect(wrapper.text()).toContain('Dashboard')
})
```

**Key points:**
- Create a single `mountWithPlugins` helper that sets up all common infrastructure
- Return wrapper plus the Pinia/router/queryClient instances for direct manipulation
- Pass additional `globals` through from `options.global` for flexibility

---

## Test Commands

```bash
pnpm test                    # Run all tests
pnpm test -- --watch         # Watch mode
pnpm test -- --coverage      # Coverage report
pnpm test -- Button          # Run specific test file (partial match)
pnpm test -- --ui            # Vitest UI (interactive browser dashboard)
pnpm test -- --reporter=verbose  # Verbose output
```

---

## Common Issues

| Issue | Solution |
|-------|----------|
| "Cannot find module" | Verify path aliases in `vite.config.ts` resolve key |
| "getActivePinia() was called with no active Pinia" | Add `setActivePinia(createPinia())` in `beforeEach` |
| Store state bleeding across tests | Use fresh `createPinia()` + `setActivePinia()` per test |
| Async assertion fails | Use `await flushPromises()` then `await nextTick()` |
| Explicit mock not working | Ensure `vi.mock()` is at module root (before imports), and mock path matches |
| "No router instance found" | Ensure router is passed via `global.plugins` in mount options |
| Component not finding child | Use `mount()` instead of `shallowMount()` if child is expected |
| Snapshot different in CI | Ensure consistent locale, timezone, and OS-independent selectors |
| Emitted event not captured | `wrapper.emitted()` only captures events from the wrapper's component, not children |
| setValue not triggering v-model | Use `await input.setValue(value)` -- it fires the proper input events |

---

## Recommended File Structure

```
src/
  __tests__/
    utils/
      test-utils.ts          # mountWithPlugins helper, common stubs
    components/
      ItemCard.test.ts       # Component tests (co-located or __tests__)
    composables/
      useAuth.test.ts        # Composable tests
    stores/
      appStore.test.ts       # Pinia store tests
vitest.config.ts             # Vitest configuration
tests/
  setup.ts                   # Global mocks, setupBeforeEach hooks
```

**Vitest common config (`vitest.config.ts`):**
```typescript
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  test: {
    globals: true,            // describe, it, expect without imports
    environment: 'jsdom',     // or 'happy-dom' for lighter alternative
    setupFiles: ['./tests/setup.ts'],
    include: ['src/**/*.{test,spec}.{js,ts}'],
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
})
```