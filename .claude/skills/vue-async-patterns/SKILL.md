---
name: vue-async-patterns
description: Async/await correctness in Vue 3.5 with Pinia. Use when debugging race conditions, missing awaits, floating promises, or async timing issues in Vue applications.
---

# Vue Async Patterns

## Problem Statement

Async bugs in Vue are insidious because they often work in development but fail under load or in edge cases. The most common issues: missing `await` on async functions, race conditions between state updates, and assuming operations complete in order.

---

## Pattern: Floating Promise Detection

**Problem:** Calling an async function without `await` causes it to run in the background. If subsequent code depends on its completion, you get a race condition.

```typescript
// Before (buggy) - saveData is async but not awaited
saveData(item);              // Fire and forget ❌
await processData(item);     // Runs before save completes

// After (fixed)
await saveData(item);        // Wait for state update ✅
await processData(item);     // Now runs in correct order
```

**Why it's subtle:** Both functions might have `async` in their signature, but only one was awaited. The code "looks right" at a glance.

**Detection:**

```bash
# Find potential floating promises - async calls without await
# Search .vue, .ts, and .tsx files
grep -rn "^\s*[a-zA-Z]*\s*(" --include="*.vue" --include="*.ts" --include="*.tsx" | \
  grep -v "await\|return\|const\|let\|if\|else\|=>"
```

**Prevention:**

1. ESLint rule `@typescript-eslint/no-floating-promises` - catches this at lint time
2. Code review trigger: Any line calling a function that might be async without `await`, `return`, or assignment

---

## Pattern: Post-Condition Validation

**Problem:** Assuming an async call succeeded without verifying. The call might return early, throw silently, or fail to update state.

```typescript
// Before (buggy) - assumed load worked
await loadData(id);
// Proceeded blindly with next steps...

// After (defensive) - using Pinia store
await loadData(id);
const store = useUserStore();
const loaded = store.data;
if (Object.keys(loaded).length === 0) {
  throw new Error(
    `Failed to load data for ${id} - cannot proceed`
  );
}

// Alternative: access raw state directly
const rawState = useUserStore().$state;
if (!rawState.data) {
  throw new Error(`Failed to load data for ${id} - cannot proceed`);
}
```

**Principle:** Treat every async call as potentially failed until proven otherwise.

**When to validate:**

- After loading data that subsequent operations depend on
- After state updates that must complete before continuing
- Before irreversible operations (submissions, deletions)

**Pattern template:**

```typescript
await someAsyncOperation();
const result = getRelevantState();
if (!isValid(result)) {
  throw new Error(`[${functionName}] Post-condition failed: ${diagnosticContext}`);
}
```

---

## Pattern: Async Function Identification

**Problem:** Not all async functions look async. Pinia actions, callbacks, and promise-returning functions may not have obvious `async` keywords.

**Hidden async patterns:**

```typescript
// Obvious async
async function fetchData() { ... }

// Less obvious - returns Promise
function fetchData(): Promise<Data> { ... }

// Hidden - Pinia action that's actually async
// stores/user.ts
export const useUserStore = defineStore('user', {
  state: () => ({
    features: [] as string[],
  }),
  actions: {
    // This looks sync but calls async internally
    enableFeature(id: string) {
      someAsyncSetup().then(() => {  // ← Hidden async!
        this.features = [...this.features, id];
      });
    },
  },
});

// Proper async Pinia action
export const useUserStore = defineStore('user', {
  state: () => ({
    features: [] as string[],
  }),
  actions: {
    async enableFeature(id: string) {
      await someAsyncSetup();
      this.features = [...this.features, id];
    },
  },
});

// Setup store syntax (Composition API style)
export const useUserStore = defineStore('user', () => {
  const features = ref<string[]>([]);

  // Proper async action
  async function enableFeature(id: string) {
    await someAsyncSetup();
    features.value = [...features.value, id];
  }

  return { features, enableFeature };
});
```

**Detection:** Check function signatures and implementations:

```bash
# Find functions returning Promise
grep -rn "): Promise<" --include="*.vue" --include="*.ts" --include="*.tsx"

# Find .then() chains that might need await
grep -rn "\.then(" --include="*.vue" --include="*.ts" --include="*.tsx"
```

---

## Pattern: Sequential vs Parallel Async

**Problem:** Running async operations sequentially when they could be parallel (slow), or parallel when they must be sequential (race condition).

```typescript
// Sequential - correct when order matters
await stepOne();
await stepTwo();
await stepThree();

// Parallel - correct when operations are independent
const [user, settings, history] = await Promise.all([
  fetchUser(id),
  fetchSettings(id),
  fetchHistory(id),
]);

// WRONG - parallel when order matters
await Promise.all([
  stepOne(),   // These have dependencies!
  stepTwo(),
]);
```

**Decision framework:**

| Operations share state? | Must run in order? | Pattern |
|------------------------|-------------------|---------|
| No | No | `Promise.all()` |
| Yes | Yes | Sequential `await` |
| Yes | No | Usually sequential to be safe |

---

## Pattern: Async in watch/watchEffect/onMounted

**Problem:** Vue's reactive effect callbacks (`watch`, `watchEffect`, `onMounted`) can accept async functions, but without proper cleanup you'll get race conditions and updates on unmounted components.

```vue
<script setup lang="ts">
import { ref, watch, watchEffect, onMounted, onBeforeUnmount } from 'vue'

const data = ref(null)
const id = ref(1)

// WRONG - no cleanup, will try to update unmounted component or stale data
watch(id, async (newId) => {
  const result = await fetch(`/api/data/${newId}`)
  data.value = await result.json()  // Might set data for a stale id!
})

// BETTER - with cleanup using a flag
watch(id, (newId) => {
  let cancelled = false

  async function load() {
    const result = await fetch(`/api/data/${newId}`)
    if (!cancelled) {
      data.value = await result.json()
    }
  }
  load()

  return () => {
    cancelled = true
  }
})

// BEST - use AbortController for cancellable fetch
watch(id, (newId) => {
  const controller = new AbortController()

  async function load() {
    try {
      const result = await fetch(`/api/data/${newId}`, { signal: controller.signal })
      data.value = await result.json()
    } catch (error) {
      if ((error as Error).name !== 'AbortError') {
        handleError(error)
      }
    }
  }
  load()

  return () => controller.abort()
})

// watchEffect pattern - reactive dependencies are auto-tracked
watchEffect(() => {
  const controller = new AbortController()
  const currentId = id.value  // Auto-tracked dependency

  async function load() {
    try {
      const result = await fetch(`/api/data/${currentId}`, { signal: controller.signal })
      data.value = await result.json()
    } catch (error) {
      if ((error as Error).name !== 'AbortError') {
        handleError(error)
      }
    }
  }
  load()

  return () => controller.abort()
})

// onMounted pattern
let cancelled = false
onMounted(async () => {
  const result = await fetch('/api/initial-data')
  if (!cancelled) {
    data.value = await result.json()
  }
})
onBeforeUnmount(() => {
  cancelled = true
})
</script>

<template>
  <div v-if="data">
    <pre>{{ data }}</pre>
  </div>
  <div v-else>Loading...</div>
</template>
```

**Key Vue-specific cleanup rules:**

- `watch` callbacks support an `onCleanup` parameter OR return a cleanup function (both work, the return-value form is shown above)
- `watchEffect` callbacks have the same cleanup semantics as `watch`
- `onMounted` cannot have a cleanup returned — pair it with `onBeforeUnmount`/`onUnmounted`
- The `watch` `flush` option (`'pre'` by default) means the callback runs before DOM updates; `flush: 'post'` runs after

---

## Pattern: TanStack Vue Query

**Problem:** Manual async state management is error-prone. Use `@tanstack/vue-query` for declarative server-state management in Vue.

```vue
<script setup lang="ts">
import { useQuery, useMutation, useQueryClient } from '@tanstack/vue-query'

interface User {
  id: string
  name: string
}

async function fetchUser(userId: string): Promise<User> {
  const res = await fetch(`/api/users/${userId}`)
  return res.json()
}

async function updateUser(user: User): Promise<User> {
  const res = await fetch(`/api/users/${user.id}`, {
    method: 'PUT',
    body: JSON.stringify(user),
    headers: { 'Content-Type': 'application/json' },
  })
  return res.json()
}

// Fetching data
const props = defineProps<{ userId: string }>()
const { data, isLoading, error } = useQuery({
  queryKey: ['user', () => props.userId],
  queryFn: () => fetchUser(props.userId),
})

// Mutations with cache invalidation
const queryClient = useQueryClient()
const mutation = useMutation({
  mutationFn: updateUser,
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ['user'] })
  },
})
</script>

<template>
  <div>
    <Spinner v-if="isLoading" />
    <Error :error="error" v-else-if="error" />
    <Profile :user="data" v-else />
    <button @click="mutation.mutate(userData)">Save</button>
  </div>
</template>
```

**Key differences from React:**
- `queryKey` can use Vue `ref` or getter functions: `['user', () => userId.value]`
- Reactive state is returned as `Ref` objects — destructure with care use `storeToRefs()` for reactive destructuring

---

## ESLint Configuration

Add these rules to catch async issues at lint time:

```json
{
  "rules": {
    "@typescript-eslint/no-floating-promises": "error",
    "@typescript-eslint/require-await": "warn",
    "@typescript-eslint/await-thenable": "error",
    "@typescript-eslint/no-misused-promises": "error"
  }
}
```

**Required:** `@typescript-eslint/eslint-plugin` and proper TypeScript configuration.

For Vue projects, also ensure:
- `vue-tsc` is used for type-checking `.vue` SFC files (catches async type errors that ESLint alone might miss)
- `eslint-plugin-vue` for Vue-specific lint rules alongside the TypeScript rules above
- Your `tsconfig.json` includes `.vue` files and has `"strict": true`

---

## Code Review Checklist

When reviewing async code in Vue, check:

- [ ] Every async function call is either `await`ed, `return`ed, or explicitly fire-and-forget with a comment
- [ ] Operations that depend on each other are sequenced with `await`
- [ ] Post-conditions validated after critical async operations using Pinia store state
- [ ] `watch` and `watchEffect` with async use proper cleanup (returned function or `onCleanup`)
- [ ] `onMounted` with async is paired with `onBeforeUnmount` for cancellation
- [ ] Race conditions considered when component could unmount during async work
- [ ] Error handling exists for async failures
- [ ] `AbortController` used for fetch calls that should be cancellable
- [ ] Pinia actions are properly `async` when they perform async work internally
- [ ] `storeToRefs()` is used when destructuring reactive store state (to preserve reactivity)
- [ ] Complex mutations performed through actions or `$patch` for clarity

---

## Quick Debugging

When async timing issues occur:

```typescript
// Add timestamps to trace execution order
console.log(`[${Date.now()}] Starting step 1`);
await stepOne();
console.log(`[${Date.now()}] Finished step 1`);
console.log(`[${Date.now()}] Starting step 2`);
await stepTwo();
console.log(`[${Date.now()}] Finished step 2`);
```

Look for:
- Operations finishing out of expected order
- Operations starting before previous ones complete
- Suspiciously fast "completions" (might not have awaited)

---

## Pinia Store Access Patterns

Quick reference for common Pinia state access patterns used throughout these examples:

```typescript
import { storeToRefs } from 'pinia'

// Direct access (state is reactive proxy — destructuring BREAKS reactivity)
const store = useUserStore()
console.log(store.data)        // Reactive - safe
const { data } = store          // NOT reactive after destructure

// storeToRefs — preserves reactivity when destructuring
const { data, isLoading } = storeToRefs(useUserStore())
console.log(data.value)         // Ref — reactive

// Raw snapshot (non-reactive, includes all state including $state internals)
const snapshot = useUserStore().$state

// Mutating state (prefer actions, but direct assignment works in Options API stores)
store.someField = newValue      // Allowed but prefer actions for consistency

// Batch updates
store.$patch({
  fieldA: valueA,
  fieldB: valueB,
})

// Async action call from a component
const store = useUserStore()
await store.enableFeature('feature-id')
```