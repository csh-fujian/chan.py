---
name: vue-performance
description: Performance optimization for Vue web applications. Use when optimizing renders, implementing virtualization, using computed properties, or debugging performance issues.
---

# Vue Performance (Web)

## Problem Statement

Vue performance issues often stem from unnecessary reactivity, unoptimized lists, and expensive computations on the main thread. Understanding Vue's fine-grained reactivity system is key to building performant applications.

---

## Pattern: Memoization

### computed() - Derived State with Auto-Caching

Vue's `computed()` automatically caches results and only recomputes when tracked reactive dependencies change. There is no need for an explicit `useMemo` equivalent.

```typescript
<script setup lang="ts">
import { computed, ref } from 'vue'

const items = ref<Item[]>([])

// ✅ CORRECT: Computed caches and tracks dependencies automatically
const sortedAndFilteredItems = computed(() => {
  return items.value
    .filter(item => item.active)
    .sort((a, b) => b.score - a.score)
    .slice(0, 100)
})

// ❌ WRONG: Method called in template recomputes every render
function getSortedItems() {
  return items.value
    .filter(item => item.active)
    .sort((a, b) => b.score - a.score)
}

// ❌ WRONG: Manual watch + ref (verbose, error-prone)
const sorted = ref<Item[]>([])
watch(items, (newItems) => {
  sorted.value = newItems
    .filter(item => item.active)
    .sort((a, b) => b.score - a.score)
}, { deep: true })
</script>
```

**When to use computed:**
- Array transformations (filter, sort, map chains)
- Derived primitive values (sums, counts, booleans)
- Any value that depends on reactive state and is read in the template

### No useCallback Needed

Vue does not need a `useCallback` equivalent. Functions defined in `<script setup>` are stable across re-renders as long as they don't capture reactive state that changes.

```typescript
<script setup lang="ts">
// ✅ Functions defined here are stable references
function handleClick(id: string) {
  selectedId.value = id
}

// ✅ If the callback needs current reactive state, it's captured automatically
const count = ref(0)
function increment() {
  count.value++ // always reads the current value
}

// ✅ For derived values, use computed instead of wrapping in a function
const fullName = computed(() => `${firstName.value} ${lastName.value}`)
</script>

<template>
  <ChildComponent @click="handleClick" />
</template>
```

### v-memo - Manual Memoization

Vue components are automatically optimized by the compiler. For manual subtree memoization, use the `v-memo` directive:

```vue
<template>
  <!-- Only re-render this subtree when item.id or item.selected changes -->
  <div v-memo="[item.id, item.selected]">
    <ExpensiveChild :item="item" />
  </div>
</template>
```

### shallowRef - Large Object Optimization

For large objects where only the top-level reference changes, use `shallowRef` to skip deep reactivity:

```typescript
const largeDataset = shallowRef<MassiveObject>(initialData)
// Only triggers updates when largeDataset.value is reassigned
// Changes to nested properties do NOT trigger reactivity
```

**When to use memoization in Vue:**
- `computed()` for derived values (primary tool)
- `v-memo` for expensive template subtrees with stable dependencies
- `shallowRef` for large objects where deep reactivity is unnecessary
- `shallowReactive` for large reactive objects where only top-level properties matter

**When NOT to use:**
- Simple property access (Vue's reactivity is already efficient)
- Values that change on every render anyway
- When `computed` would track too many unnecessary dependencies

---

## Pattern: List Virtualization

For long lists, render only visible items using `vue-virtual-scroller` or `@tanstack/vue-virtual`.

```vue
<script setup lang="ts">
import { useVirtualizer } from '@tanstack/vue-virtual'
import { ref } from 'vue'

const parentRef = ref<HTMLElement>()
const items = ref<Item[]>([])

const rowVirtualizer = useVirtualizer(
  computed(() => ({
    count: items.value.length,
    getScrollElement: () => parentRef.value,
    estimateSize: () => 80,
  }))
)
</script>

<template>
  <div ref="parentRef" style="height: 600px; overflow: auto">
    <div
      :style="{
        height: `${rowVirtualizer.getTotalSize()}px`,
        width: '100%',
        position: 'relative',
      }"
    >
      <div
        v-for="virtualRow in rowVirtualizer.getVirtualItems()"
        :key="virtualRow.key"
        :style="{
          position: 'absolute',
          top: 0,
          left: 0,
          width: '100%',
          height: `${virtualRow.size}px`,
          transform: `translateY(${virtualRow.start}px)`,
        }"
      >
        <ItemCard :item="items[virtualRow.index]" />
      </div>
    </div>
  </div>
</template>
```

Alternative with `vue-virtual-scroller`:

```vue
<script setup lang="ts">
import { RecycleScroller } from 'vue-virtual-scroller'
import 'vue-virtual-scroller/dist/vue-virtual-scroller.css'
</script>

<template>
  <RecycleScroller
    :items="items"
    :item-size="80"
    key-field="id"
    :buffer="200"
    style="height: 600px"
  >
    <template #default="{ item }">
      <ItemCard :item="item" />
    </template>
  </RecycleScroller>
</template>
```

**When to virtualize:**
- Lists with 100+ items
- Complex item components
- Scrollable containers with many children

---

## Pattern: Pinia Selector Optimization

**Problem:** Selecting too much state or using the wrong destructuring pattern loses reactivity or triggers unnecessary updates.

```typescript
import { storeToRefs } from 'pinia'

// ❌ WRONG: Destructuring directly loses reactivity
const { items, loading } = useAppStore()
// items and loading are plain values, NOT reactive

// ❌ WRONG: Accessing entire store creates unnecessary tracking
const store = useAppStore()
// Template accessing store.items tracks EVERY reactive property on store

// ✅ CORRECT: Use storeToRefs to preserve reactivity
const store = useAppStore()
const { items, loading } = storeToRefs(store)
// items and loading are Ref objects, individually reactive

// ✅ CORRECT: Use computed for derived values
const activeCount = computed(() => store.items.filter(i => i.active).length)

// ✅ CORRECT: Watch specific properties
watch(() => store.items, (newItems) => {
  console.log('Items changed:', newItems)
})
```

---

## Pattern: Avoiding Re-Renders

Vue's reactivity system is fine-grained: components only re-render when their **tracked** reactive dependencies change. This is fundamentally different from React's top-down re-render model.

### Inline Object/Array Props

```vue
<script setup lang="ts">
import { computed } from 'vue'

// ❌ WRONG in template: New object literal on every re-render
// <ChildComponent :config="{ enabled: true }" />

// ✅ CORRECT: Stable reference with computed
const config = computed(() => ({ enabled: true }))

// ✅ CORRECT: Define outside component for truly static values
const staticConfig = { enabled: true }
</script>

<template>
  <ChildComponent :config="config" />
</template>
```

### Function Props

Vue's template functions are stable. You generally do NOT need to memoize event handlers:

```vue
<template>
  <!-- ✅ Template functions are stable -->
  <ChildComponent @click="(id) => handleClick(id)" />
  <ChildComponent @select="(item) => selectItem(item)" />
</template>
```

### Children Stability

```vue
<template>
  <!-- ✅ Slots are stable by default in Vue -->
  <ParentComponent>
    <ChildComponent />
  </ParentComponent>
</template>
```

**Key Vue insight:** Vue's compiler optimizes templates at build time. Static content is hoisted, dynamic bindings are patched surgically, and the Virtual DOM diffing is highly optimized. Manual optimization is rarely needed compared to React.

---

## Pattern: Code Splitting

Use Vue's `defineAsyncComponent` for lazy loading:

```typescript
import { defineAsyncComponent } from 'vue'

// Lazy load components
const Dashboard = defineAsyncComponent(() => import('./views/Dashboard.vue'))
const Settings = defineAsyncComponent(() => import('./views/Settings.vue'))

// With loading/error states
const Reports = defineAsyncComponent({
  loader: () => import('./views/Reports.vue'),
  loadingComponent: LoadingSpinner,
  errorComponent: ErrorDisplay,
  delay: 200, // Show loading only if load exceeds 200ms
  timeout: 10000,
})
```

With Vue Router, use dynamic imports:

```typescript
const routes = [
  {
    path: '/dashboard',
    component: () => import('./views/Dashboard.vue'),
  },
  {
    path: '/settings',
    component: () => import('./views/Settings.vue'),
  },
]
```

---

## Pattern: Debouncing and Throttling

Use VueUse for debouncing and throttling:

```typescript
<script setup lang="ts">
import { useDebounceFn, useThrottleFn } from '@vueuse/core'

// Debounce - wait until user stops typing
const onSearch = (query: string) => {
  // API call
}
const debouncedSearch = useDebounceFn(onSearch, 300)

// Throttle - limit how often function runs
const onLoadMore = () => {
  // Fetch next page
}
const throttledLoad = useThrottleFn(onLoadMore, 1000)
</script>

<template>
  <input type="text" @input="debouncedSearch(($event.target as HTMLInputElement).value)" />
</template>
```

Without VueUse (manual approach):

```typescript
import { ref, onUnmounted } from 'vue'

const query = ref('')
let timer: ReturnType<typeof setTimeout>

function onInput(value: string) {
  clearTimeout(timer)
  timer = setTimeout(() => {
    query.value = value
  }, 300)
}

onUnmounted(() => clearTimeout(timer))
```

---

## Pattern: Image Optimization

```vue
<template>
  <!-- Native lazy loading (recommended for Vue 3) -->
  <img :src="imageUrl" loading="lazy" alt="Description" />
</template>
```

---

## Pattern: Detecting Re-Renders

### Vue DevTools Timeline

1. Open Vue DevTools
2. Go to the **Timeline** tab
3. Click record, interact with the app, stop
4. Review component render events and their durations
5. Look for components rendering with unchanged props

### Custom Render Tracking

```vue
<script setup lang="ts">
import { onUpdated } from 'vue'

// Log every time this component re-renders
onUpdated(() => {
  console.log('[ComponentName] re-rendered')
})
</script>
```

### Vue DevTools Performance Tab

The Performance tab in Vue DevTools shows:
- Component render time
- Number of renders
- Flame graph of component tree updates
- Event timeline

---

## Performance Checklist

Before shipping:

- [ ] Large lists are virtualized (vue-virtual-scroller or @tanstack/vue-virtual)
- [ ] Derived values use `computed()` (not methods or manual watchers)
- [ ] Large objects use `shallowRef` when deep reactivity is unnecessary
- [ ] Pinia stores use `storeToRefs()` for destructuring (preserves reactivity)
- [ ] Images use lazy loading (native `loading="lazy"` or `v-lazy`)
- [ ] Heavy routes are code-split with `defineAsyncComponent` or dynamic router imports
- [ ] Debounced/throttled handlers use `useDebounceFn` / `useThrottleFn` from VueUse
- [ ] No manual watchers where `computed` would suffice
- [ ] Vue DevTools Timeline shows no unnecessary component updates
- [ ] `v-memo` considered for expensive subtrees with stable dependencies

---

## Common Issues

| Issue | Solution |
|-------|----------|
| List scroll lag | Virtualize list with `@tanstack/vue-virtual` or `vue-virtual-scroller` |
| Component re-renders too often | Check computed vs method usage: methods used in templates recompute every render; prefer `computed`. Check watch `deep` option — prefer specific watched paths. |
| Slow initial render | Use `defineAsyncComponent` for code splitting, reduce main bundle size |
| Memory growing | Check event listener cleanup (`onUnmounted`), watcher teardown, `setInterval`/`setTimeout` cleanup |
| UI freezes on interaction | Move heavy computation to web worker or use `requestIdleCallback` |
| Large reactive objects causing slowness | Use `shallowRef` or `markRaw` to skip deep reactivity for large datasets |
| Unnecessary watchers | Prefer `computed` over `watch` when deriving state — computed auto-tracks and caches |
| Destructured store loses reactivity | Use `storeToRefs()` when destructuring Pinia stores |

---

## Relationship to Other Skills

- **vue-pinia-patterns**: Store selector optimization and reactive destructuring patterns
- **vue-async-patterns**: Proper async handling prevents reactivity glitches and render loops