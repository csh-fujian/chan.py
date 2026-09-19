---
name: vue-state-flows
description: Complex multi-step operations in Vue 3.5 Composition API + Pinia. Use when implementing flows with multiple async steps, state machine patterns, or debugging flow ordering issues. Works for both Vue web and Nuxt applications.
---

# Complex State Flows

## Problem Statement

Multi-step operations with dependencies between steps are prone to ordering bugs, missing preconditions, and untested edge cases. Even without a formal state machine library, thinking in states and transitions prevents bugs.

---

## Pattern: State Machine Thinking

**Problem:** Complex flows have implicit states that aren't modeled, leading to invalid transitions.

**Example - Checkout flow states:**

```
IDLE → VALIDATING → PROCESSING_PAYMENT → CONFIRMING → COMPLETE
                                                         ↓
                                                      ERROR
```

**Each transition should have:**

1. **Preconditions** - What must be true before this step
2. **Action** - What happens during this step
3. **Postconditions** - What must be true after this step
4. **Error handling** - What to do if this step fails

```typescript
// Document the flow explicitly
/*
 * CHECKOUT FLOW
 *
 * State: IDLE
 * Precondition: cart exists with items
 * Action: validateCart
 * Postcondition: cart validated, prices confirmed
 *
 * State: VALIDATING
 * Precondition: cart validated
 * Action: processPayment
 * Postcondition: payment authorized
 *
 * State: PROCESSING_PAYMENT
 * Precondition: payment authorized
 * Action: confirmOrder
 * Postcondition: order created, confirmation number assigned
 *
 * ... continue for each state
 */
```

---

## Pattern: Explicit Flow Implementation

**Problem:** Flow logic scattered across multiple functions, hard to verify ordering.

```typescript
// WRONG - implicit flow, easy to miss steps or misordering
async function checkout(cartId: string) {
  validateCart(cartId);              // Missing await!
  await processPayment(cartId);
  await confirmOrder(cartId);
}

// CORRECT - explicit flow with validation
async function checkout(cartId: string) {
  const flowId = `checkout-${Date.now()}`;
  logger.info(`[${flowId}] Starting checkout flow`, { cartId });

  // Step 1: Validate cart
  await validateCart(cartId);
  const cartStore = useCartStore();
  if (!cartStore.cart.validated) {
    throw new Error(`[${flowId}] Cart validation failed`);
  }
  logger.debug(`[${flowId}] Cart validated`);

  // Step 2: Process payment
  await processPayment(cartId);
  const paymentStore = usePaymentStore();
  if (!paymentStore.payment.authorized) {
    throw new Error(`[${flowId}] Payment authorization failed`);
  }
  logger.debug(`[${flowId}] Payment processed`);

  // Step 3: Confirm order
  await confirmOrder(cartId);
  logger.info(`[${flowId}] Checkout flow completed`);
}
```

---

## Pattern: Flow Object

**Problem:** Long async functions with many steps become unwieldy.

```typescript
interface FlowStep<TContext> {
  name: string;
  execute: (context: TContext) => Promise<void>;
  validate?: (context: TContext) => void;  // Postcondition check
}

interface CheckoutContext {
  cartId: string;
  flowId: string;
}

const checkoutSteps: FlowStep<CheckoutContext>[] = [
  {
    name: 'validateCart',
    execute: async (ctx) => {
      await validateCart(ctx.cartId);
    },
    validate: (ctx) => {
      const cartStore = useCartStore();
      if (!cartStore.cart.validated) {
        throw new Error(`[${ctx.flowId}] Cart not validated`);
      }
    },
  },
  {
    name: 'processPayment',
    execute: async (ctx) => {
      await processPayment(ctx.cartId);
    },
    validate: (ctx) => {
      const paymentStore = usePaymentStore();
      if (!paymentStore.payment.authorized) {
        throw new Error(`[${ctx.flowId}] Payment not authorized`);
      }
    },
  },
  {
    name: 'confirmOrder',
    execute: async (ctx) => {
      await confirmOrder(ctx.cartId);
    },
  },
];

async function executeFlow<TContext>(
  steps: FlowStep<TContext>[],
  context: TContext,
  flowName: string
) {
  const flowId = `${flowName}-${Date.now()}`;
  logger.info(`[${flowId}] Starting flow`, context);

  for (const step of steps) {
    logger.debug(`[${flowId}] Executing: ${step.name}`);
    try {
      await step.execute(context);
      if (step.validate) {
        step.validate(context);
      }
      logger.debug(`[${flowId}] Completed: ${step.name}`);
    } catch (error) {
      logger.error(`[${flowId}] Failed at: ${step.name}`, { error: error.message });
      throw error;
    }
  }

  logger.info(`[${flowId}] Flow completed`);
}

// Usage
await executeFlow(checkoutSteps, { cartId, flowId }, 'checkout');
```

---

## Pattern: Flow State Tracking

**Problem:** Components need to know current flow state for UI feedback.

```typescript
// stores/checkoutStore.ts
import { defineStore } from 'pinia'
import { ref } from 'vue'

type CheckoutFlowState =
  | { status: 'idle' }
  | { status: 'loading'; step: string }
  | { status: 'ready' }
  | { status: 'processing'; step: string }
  | { status: 'complete'; orderId: string }
  | { status: 'error'; message: string; step: string };

export const useCheckoutStore = defineStore('checkout', () => {
  const flowState = ref<CheckoutFlowState>({ status: 'idle' })

  function setFlowState(state: CheckoutFlowState) {
    flowState.value = state
  }

  return { flowState, setFlowState }
})
```

```typescript
// services/checkoutFlow.ts
import { useCheckoutStore } from '@/stores/checkoutStore'

async function checkout(cartId: string) {
  const store = useCheckoutStore()

  try {
    store.setFlowState({ status: 'processing', step: 'validating' })
    await validateCart(cartId)

    store.setFlowState({ status: 'processing', step: 'payment' })
    await processPayment(cartId)

    store.setFlowState({ status: 'processing', step: 'confirming' })
    const order = await confirmOrder(cartId)

    store.setFlowState({ status: 'complete', orderId: order.id })
  } catch (error) {
    store.setFlowState({
      status: 'error',
      message: error.message,
      step: store.flowState.status === 'processing' ? store.flowState.step : 'unknown',
    })
  }
}
```

```vue
<!-- Component usage -->
<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { useCheckoutStore } from '@/stores/checkoutStore'

const store = useCheckoutStore()
const { flowState } = storeToRefs(store)
</script>

<template>
  <Loading v-if="flowState.status === 'processing'" :step="flowState.step" />
  <Error v-else-if="flowState.status === 'error'" :message="flowState.message" :step="flowState.step" />
  <Confirmation v-else-if="flowState.status === 'complete'" :order-id="flowState.orderId" />
  <!-- ... render based on state -->
</template>
```

---

## Pattern: Integration Testing Flows

**Problem:** Unit tests for individual functions don't catch flow-level bugs.

```typescript
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useCheckoutStore } from '@/stores/checkoutStore'
import { useCartStore } from '@/stores/cartStore'

describe('Checkout Flow', () => {
  let checkoutStore: ReturnType<typeof useCheckoutStore>
  let cartStore: ReturnType<typeof useCartStore>

  beforeEach(() => {
    // Create a fresh Pinia instance for each test
    setActivePinia(createPinia())
    checkoutStore = useCheckoutStore()
    cartStore = useCartStore()
  })

  it('completes full checkout flow', async () => {
    const cartId = 'test-cart'

    // Setup: Add items to cart
    cartStore.addItem({ id: 'item-1', price: 100 })

    // Execute full flow
    await checkoutStore.checkout(cartId)

    // Verify final state
    expect(checkoutStore.flowState.status).toBe('complete')
    expect(checkoutStore.flowState.orderId).toBeDefined()
  })

  it('handles payment failure gracefully', async () => {
    const cartId = 'test-cart'

    // Mock payment to fail
    mockPaymentApi.mockRejectedValueOnce(new Error('Card declined'))

    await expect(
      checkoutStore.checkout(cartId)
    ).rejects.toThrow('Card declined')

    expect(checkoutStore.flowState.status).toBe('error')
    expect(checkoutStore.flowState.step).toBe('payment')
  })

  it('renders loading state during processing', async () => {
    const wrapper = mount(CheckoutScreen, {
      global: {
        plugins: [createTestingPinia({
          initialState: {
            checkout: {
              flowState: { status: 'processing', step: 'validating' }
            }
          }
        })]
      }
    })

    expect(wrapper.findComponent(Loading).exists()).toBe(true)
    expect(wrapper.findComponent(Error).exists()).toBe(false)
    expect(wrapper.findComponent(Confirmation).exists()).toBe(false)
  })
})
```

---

## Pattern: Flow Documentation

Document complex flows with diagrams for team understanding:

```markdown
## Checkout Flow

### Happy Path

```
┌─────────┐     ┌──────────────┐     ┌─────────────────┐     ┌─────────────┐
│  Start  │────▶│ Validate Cart│────▶│ Process Payment │────▶│ Confirm     │
└─────────┘     └──────────────┘     └─────────────────┘     └─────────────┘
                       │                     │                      │
                       ▼                     ▼                      ▼
                 Postcondition:        Postcondition:          Postcondition:
                 cart.validated        payment.authorized      order.created
                                                                    │
                                                                    ▼
                                                              ┌──────────┐
                                                              │ Complete │
                                                              └──────────┘
```

### Error States

Any step can fail → transition to ERROR state with step context.
From ERROR: user can retry or exit.
```

---

## Checklist: Designing Complex Flows

Before implementing:

- [ ] Sketch state diagram (even on paper)
- [ ] Identify all states, including error states
- [ ] Document preconditions for each transition
- [ ] Document postconditions to verify
- [ ] Plan how to surface state to UI via Pinia stores and storeToRefs

During implementation:

- [ ] Verify preconditions before each step
- [ ] Validate postconditions after each step
- [ ] Log state transitions with flow ID
- [ ] Handle errors at each step with context
- [ ] Surface flow state for UI feedback using `storeToRefs` for reactivity
- [ ] Ensure Pinia stores use Composition API (setup store) syntax for consistency with Vue 3.5

After implementation:

- [ ] Integration test for happy path with vitest and `createTestingPinia`
- [ ] Integration test for error at each step
- [ ] Component test with `@vue/test-utils` to verify conditional rendering (`v-if`/`v-else-if`)
- [ ] Verify logs are sufficient for debugging
- [ ] Document flow for team

---

## When to Use XState

Consider XState when:

- Flow has > 6 states
- Complex branching/parallel states
- Need visualization/debugging tools
- State machine is shared across team

For simpler flows, explicit steps with validation (as shown above) are often sufficient and more readable. XState integrates with both Vue and Pinia through its framework-agnostic core.