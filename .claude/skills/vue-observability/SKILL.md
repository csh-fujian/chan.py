---
name: vue-observability
description: Logging, error messages, and debugging patterns for Vue 3.5 Composition API + Pinia. Use when adding logging, designing error messages, debugging production issues, or improving code observability. Works for both Vue 3 web and Nuxt.
---

# Vue Observability

## Problem Statement

Silent failures are debugging nightmares. Code that returns early without logging, error messages that lack context, and missing observability make production issues impossible to diagnose. Write code as if you'll debug it at 3am with only logs.

---

## Pattern: No Silent Early Returns

**Problem:** Early returns without logging create invisible failure paths in composables and Pinia actions.

```typescript
// WRONG - silent death
const saveData = (id: string, value: number) => {
  if (!validIds.has(id)) {
    return;  // Why did we return? No one knows.
  }
  // ... save logic
};

// CORRECT - observable
const saveData = (id: string, value: number) => {
  if (!validIds.has(id)) {
    logger.warn('[saveData] Dropping save - invalid ID', {
      id,
      value,
      validIds: Array.from(validIds),
    });
    return;
  }
  // ... save logic
};
```

**Rule:** Every early return should log why it's returning, with enough context to diagnose.

**Pinia action example:**

```typescript
// stores/user.ts
export const useUserStore = defineStore('user', () => {
  const profile = ref<User | null>(null);

  async function updateProfile(patch: Partial<User>) {
    if (!profile.value?.id) {
      logger.warn('[updateProfile] No active profile - dropping update', {
        patch,
        hasProfile: !!profile.value,
      });
      return;
    }
    // ... update logic
  }

  return { profile, updateProfile };
});
```

---

## Pattern: Error Message Design

**Problem:** Error messages that don't help diagnose the issue.

```typescript
// BAD - no context
throw new Error('Data not found');

// BAD - slightly better but still useless at 3am
throw new Error('Data not found. Please try again.');

// GOOD - diagnostic context included
throw new Error(
  `Data not found. ID: ${id}, ` +
  `Available: ${Object.keys(data).length} items, ` +
  `Last fetch: ${lastFetchTime}. This may indicate a caching issue.`
);
```

**Error message template:**

```typescript
throw new Error(
  `[${functionName}] ${whatFailed}. ` +
  `Context: ${relevantState}. ` +
  `Possible cause: ${hypothesis}.`
);
```

**What to include:**

| Element | Why |
|---------|-----|
| Function/location | Where the error occurred |
| What failed | The specific condition that wasn't met |
| Relevant state | Values that help diagnose |
| Possible cause | Your best guess for the fix |

---

## Pattern: Structured Logging

**Problem:** Console.log statements that are hard to parse and search.

```typescript
// BAD - unstructured
console.log('saving data', id, value);
console.log('current state', data);

// GOOD - structured with context object
logger.info('[saveData] Saving data', {
  id,
  value,
  existingCount: Object.keys(data).length,
});
```

**Logging levels:**

| Level | Use for |
|-------|---------|
| `error` | Exceptions, failures that need immediate attention |
| `warn` | Unexpected conditions that didn't fail but might indicate problems |
| `info` | Important business events (user actions, flow milestones) |
| `debug` | Detailed diagnostic info (state dumps, timing) |

**Wrapper for consistent logging:**

```typescript
// utils/logger.ts
const LOG_LEVELS = ['debug', 'info', 'warn', 'error'] as const;
type LogLevel = typeof LOG_LEVELS[number];

const currentLevel: LogLevel = import.meta.env.DEV ? 'debug' : 'warn';

function shouldLog(level: LogLevel): boolean {
  return LOG_LEVELS.indexOf(level) >= LOG_LEVELS.indexOf(currentLevel);
}

export const logger = {
  debug: (message: string, context?: object) => {
    if (shouldLog('debug')) {
      console.log(`[DEBUG] ${message}`, context ?? '');
    }
  },
  info: (message: string, context?: object) => {
    if (shouldLog('info')) {
      console.log(`[INFO] ${message}`, context ?? '');
    }
  },
  warn: (message: string, context?: object) => {
    if (shouldLog('warn')) {
      console.warn(`[WARN] ${message}`, context ?? '');
    }
  },
  error: (message: string, context?: object) => {
    if (shouldLog('error')) {
      console.error(`[ERROR] ${message}`, context ?? '');
    }
  },
};
```

---

## Pattern: Sensitive Data Handling

**Problem:** Logging sensitive data to console or error reporting.

```typescript
// utils/secureLogger.ts
const SENSITIVE_KEYS = ['password', 'token', 'ssn', 'creditCard', 'apiKey', 'secret'];

function redactSensitive(obj: object): object {
  const redacted = { ...obj };
  for (const key of Object.keys(redacted)) {
    if (SENSITIVE_KEYS.some(s => key.toLowerCase().includes(s))) {
      redacted[key] = '[REDACTED]';
    } else if (typeof redacted[key] === 'object' && redacted[key] !== null) {
      redacted[key] = redactSensitive(redacted[key]);
    }
  }
  return redacted;
}

export const secureLogger = {
  info: (message: string, context?: object) => {
    const safeContext = context ? redactSensitive(context) : undefined;
    logger.info(message, safeContext);
  },
  // ... other levels
};
```

---

## Pattern: Flow Tracing

**Problem:** Multi-step operations where it's unclear how far execution got.

```typescript
async function checkoutFlow(cartId: string) {
  const flowId = `checkout-${Date.now()}`;

  logger.info(`[checkoutFlow:${flowId}] Starting`, { cartId });

  try {
    logger.debug(`[checkoutFlow:${flowId}] Step 1: Validating cart`);
    await validateCart(cartId);

    logger.debug(`[checkoutFlow:${flowId}] Step 2: Processing payment`);
    await processPayment(cartId);

    logger.debug(`[checkoutFlow:${flowId}] Step 3: Confirming order`);
    await confirmOrder(cartId);

    logger.info(`[checkoutFlow:${flowId}] Completed successfully`);
  } catch (error) {
    logger.error(`[checkoutFlow:${flowId}] Failed`, {
      error: error.message,
      stack: error.stack,
      cartId,
    });
    throw error;
  }
}
```

**Pinia action with flow tracing:**

```typescript
// stores/checkout.ts
export const useCheckoutStore = defineStore('checkout', () => {
  async function executeCheckout(cartId: string) {
    const flowId = `checkout-${Date.now()}`;

    logger.info(`[executeCheckout:${flowId}] Starting`, { cartId });

    const steps = ['validateCart', 'processPayment', 'confirmOrder'];
    for (const step of steps) {
      logger.debug(`[executeCheckout:${flowId}] Step: ${step}`);
      await api[step](cartId);
    }

    logger.info(`[executeCheckout:${flowId}] Completed successfully`);
  }

  return { executeCheckout };
});
```

**Benefits:**
- Can search logs by flowId to see entire flow
- Know exactly which step failed
- Timing visible via timestamps

---

## Pattern: State Snapshots for Debugging

**Problem:** Need to understand state at specific points in complex flows.

```typescript
function snapshotState(label: string) {
  const store = useUserStore();
  logger.debug(`[StateSnapshot] ${label}`, {
    user: store.$state,
  });
}

// Usage in flow
async function complexFlow() {
  snapshotState('Before load');
  await loadData(id);
  snapshotState('After load');
  await processData();
  snapshotState('After process');
}
```

**Multiple stores snapshot:**

```typescript
function snapshotAllStores(label: string) {
  const stores = {
    user: useUserStore().$state,
    cart: useCartStore().$state,
    ui: useUiStore().$state,
  };
  logger.debug(`[StateSnapshot] ${label}`, stores);
}
```

---

## Pattern: Assertion Helpers

**Problem:** Conditions that "should never happen" but need visibility when they do.

```typescript
// utils/assertions.ts
export function assertDefined<T>(
  value: T | null | undefined,
  context: string
): asserts value is T {
  if (value === null || value === undefined) {
    const message = `[Assertion Failed] Expected defined value: ${context}`;
    logger.error(message, { value });
    throw new Error(message);
  }
}

export function assertCondition(
  condition: boolean,
  context: string,
  debugInfo?: object
): asserts condition {
  if (!condition) {
    const message = `[Assertion Failed] ${context}`;
    logger.error(message, debugInfo);
    throw new Error(message);
  }
}

// Usage
assertDefined(user, `User not found: ${userId}`);
assertCondition(
  items.length > 0,
  `No items found`,
  { searchQuery, filters }
);
```

---

## Pattern: Production Error Reporting

**Problem:** Errors in production with no visibility.

```typescript
// Integration with error reporting service (Sentry example)
import * as Sentry from '@sentry/vue';

export function captureError(
  error: Error,
  context?: Record<string, unknown>
) {
  logger.error(error.message, { ...context, stack: error.stack });

  if (import.meta.env.PROD) {
    Sentry.captureException(error, {
      extra: context,
    });
  }
}

// Usage
try {
  await riskyOperation();
} catch (error) {
  captureError(error, {
    userId,
    action: 'checkout',
    cartItems: cart.items.length,
  });
  throw error;
}
```

**Sentry integration in Vue app setup:**

```typescript
// main.ts
import { createApp } from 'vue';
import * as Sentry from '@sentry/vue';

const app = createApp(App);

Sentry.init({
  app,
  dsn: 'your-dsn',
  integrations: [
    Sentry.browserTracingIntegration(),
    Sentry.replayIntegration(),
  ],
  tracesSampleRate: 1.0,
});

app.mount('#app');
```

---

## Pattern: Vue Error Handling

Vue 3 does not have React-style ErrorBoundary class components. Instead, it provides three complementary error handling mechanisms.

### 1. Global Error Handler

```typescript
// main.ts
import { createApp } from 'vue';

const app = createApp(App);

app.config.errorHandler = (err, instance, info) => {
  logger.error('[GlobalErrorHandler] Unhandled error', {
    error: err instanceof Error ? err.message : String(err),
    stack: err instanceof Error ? err.stack : undefined,
    component: (instance?.type as any)?.name ?? 'unknown',
    info,
  });

  captureError(err instanceof Error ? err : new Error(String(err)), {
    component: instance?.$.type?.name,
    info,
  });
};

app.mount('#app');
```

### 2. Component-Level with `onErrorCaptured`

```typescript
// composables/useErrorHandler.ts
import { onErrorCaptured, ref } from 'vue';

export function useErrorHandler() {
  const error = ref<Error | null>(null);

  onErrorCaptured((err, instance, info) => {
    error.value = err instanceof Error ? err : new Error(String(err));

    logger.error('[onErrorCaptured] Caught error in component', {
      error: error.value.message,
      component: (instance?.type as any)?.name ?? 'unknown',
      info,
    });

    captureError(error.value, {
      component: instance?.$.type?.name,
      info,
    });

    return false; // Prevent propagation to parent handlers
  });

  function clearError() {
    error.value = null;
  }

  return { error, clearError };
}
```

### 3. Custom Error Boundary Component

```vue
<!-- components/ErrorBoundary.vue -->
<script setup lang="ts">
import { onErrorCaptured, ref } from 'vue';

const error = ref<Error | null>(null);

onErrorCaptured((err, instance, info) => {
  error.value = err instanceof Error ? err : new Error(String(err));

  logger.error('[ErrorBoundary] Caught error', {
    error: error.value.message,
    component: (instance?.type as any)?.name ?? 'unknown',
    info,
  });

  captureError(error.value, {
    component: instance?.$.type?.name,
    info,
  });

  return false; // Prevent propagation
});
</script>

<template>
  <slot v-if="!error" />
  <slot v-else name="fallback" :error="error">
    <div class="error-boundary-fallback">
      <h2>Something went wrong</h2>
      <p>{{ error.message }}</p>
      <button @click="error = null">Try again</button>
    </div>
  </slot>
</template>
```

**Usage:**

```vue
<template>
  <ErrorBoundary>
    <DangerousComponent />
    <template #fallback="{ error }">
      <CustomErrorPanel :error="error" />
    </template>
  </ErrorBoundary>
</template>
```

---

## Vue-Specific Pattern: Composable Error Handling

**Problem:** Async operations in composables fail silently without structured error handling.

```typescript
// composables/useAsyncData.ts
import { ref, readonly } from 'vue';

interface AsyncState<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
}

export function useAsyncData<T>(asyncFn: () => Promise<T>) {
  const state = ref<AsyncState<T>>({
    data: null,
    error: null,
    loading: false,
  });

  async function execute() {
    state.value = { data: null, error: null, loading: true };

    try {
      const result = await asyncFn();
      state.value = { data: result, error: null, loading: false };
      return result;
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));

      logger.error('[useAsyncData] Async operation failed', {
        error: error.message,
        stack: error.stack,
      });

      captureError(error, {
        source: 'useAsyncData',
      });

      state.value = { data: null, error, loading: false };
      throw error;
    }
  }

  return {
    state: readonly(state),
    execute,
  };
}
```

**Usage in a component or composable:**

```typescript
const { state, execute } = useAsyncData(() => fetchUserProfile(userId));

onMounted(() => {
  execute();
});
```

---

## Vue-Specific Pattern: Async Component Error Handling

**Problem:** Async component loading errors need clean, centralized handling.

```vue
<!-- App.vue -->
<template>
  <Suspense>
    <template #default>
      <AsyncDashboard />
    </template>
    <template #fallback>
      <LoadingSkeleton />
    </template>
  </Suspense>
</template>

<script setup lang="ts">
import { onErrorCaptured } from 'vue'

// onErrorCaptured catches errors from descendant components and async setups
onErrorCaptured((err, instance, info) => {
  logger.error('[ErrorBoundary] Captured error', {
    error: err instanceof Error ? err.message : String(err),
    info,
  })
  // Return false to stop error propagation; return true/undefined to let it bubble
  return false
})
</script>
```

**Async component with Suspense-aware error handling:**

```vue
<!-- components/AsyncDashboard.vue -->
<script setup lang="ts">
const data = await fetchDashboardData();

logger.info('[AsyncDashboard] Dashboard data loaded', {
  panels: data.panels.length,
  lastUpdated: data.lastUpdated,
});
</script>

<template>
  <DashboardLayout :data="data" />
</template>
```

**Composable for async data loading with error handling:**

```typescript
// composables/useSuspenseData.ts
import { ref, shallowRef, onErrorCaptured } from 'vue';

export function useSuspenseData<T>(loader: () => Promise<T>) {
  const data = shallowRef<T | null>(null);
  const error = ref<Error | null>(null);

  // Initial load via top-level await (Suspense mode)
  await loader()
    .then(result => {
      data.value = result;
    })
    .catch(err => {
      error.value = err instanceof Error ? err : new Error(String(err));
      logger.error('[useSuspenseData] Initial load failed', {
        error: error.value.message,
        stack: error.value.stack,
      });
    });

  onErrorCaptured((err, instance, info) => {
    logger.error('[useSuspenseData] Error captured', {
      error: err instanceof Error ? err.message : String(err),
      component: (instance?.type as any)?.name ?? 'unknown',
      info,
    });
    return false;
  });

  return { data, error };
}
```

---

## Checklist: Adding Observability

When writing new code:

- [ ] All early returns have logging with context (in composables and Pinia actions)
- [ ] Error messages include diagnostic information
- [ ] Multi-step operations have flow tracing
- [ ] Sensitive data is redacted before logging
- [ ] State snapshots available for debugging complex flows (Pinia `$state`)
- [ ] Production errors are captured with context
- [ ] Composables wrapping async operations include error handling
- [ ] `app.config.errorHandler` is configured in main.ts
- [ ] `onErrorCaptured` is used in error-prone component subtrees

When debugging existing code:

- [ ] Add logging to suspect early returns
- [ ] Add state snapshots before and after async operations (via `useXxxStore().$state`)
- [ ] Check for silent catches that swallow errors
- [ ] Verify error messages have enough context

---

## Quick Debugging Template

Add this temporarily when debugging async/state issues:

```typescript
const DEBUG = true;

function debugLog(label: string, data?: object) {
  if (DEBUG) {
    console.log(`[DEBUG ${Date.now()}] ${label}`, data ?? '');
  }
}

// In your composable or Pinia action
debugLog('Flow start', { inputs });
debugLog('After step 1', { state: useCartStore().$state });
debugLog('After step 2', { state: useCartStore().$state });
debugLog('Flow end', { result });
```

Remove before committing, or gate behind a flag like `import.meta.env.DEV`.