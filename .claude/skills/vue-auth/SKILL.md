---
name: vue-auth
description: Authentication patterns for Vue web applications. Use when implementing login flows, OAuth, JWT handling, session management, or protected routes in Vue 3.5 web apps.
---

# Web Authentication (Vue 3.5)

## Core Patterns

### JWT Token Storage

**Options and trade-offs:**

| Storage | XSS Safe | CSRF Safe | Best For |
|---------|----------|-----------|----------|
| httpOnly cookie | Yes | No (needs CSRF token) | Most secure for tokens |
| localStorage | No | Yes | Simple apps, short-lived tokens |
| Memory (Pinia state) | Yes | Yes | Very short-lived tokens with refresh |

### Cookie-Based Auth (Recommended)

```typescript
// api/auth.ts — Axios API client setup
import axios from 'axios';

const authApi = axios.create({
  baseURL: '/api/auth',
  withCredentials: true, // Important: send/receive cookies
  headers: { 'Content-Type': 'application/json' },
});

export function login(email: string, password: string) {
  return authApi.post('/login', { email, password });
}

export function logout() {
  return authApi.post('/logout');
}

export function getUser() {
  return authApi.get('/me');
}
```

### Auth Store Pattern (Pinia)

```typescript
// stores/auth.ts
import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import { login, logout, getUser } from '@/api/auth';

export interface User {
  id: string;
  email: string;
  name: string;
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null);
  const isLoading = ref(true);

  const isAuthenticated = computed(() => !!user.value);

  async function checkAuth() {
    try {
      const response = await getUser();
      user.value = response.data.user;
    } catch {
      user.value = null;
    } finally {
      isLoading.value = false;
    }
  }

  async function doLogin(email: string, password: string) {
    const response = await login(email, password);
    user.value = response.data.user;
  }

  async function doLogout() {
    await logout();
    user.value = null;
  }

  async function refresh() {
    await checkAuth();
  }

  // Initialize on store creation
  checkAuth();

  return {
    user,
    isLoading,
    isAuthenticated,
    login: doLogin,
    logout: doLogout,
    refresh,
  };
});
```

```vue
<!-- App.vue — Show loading state while auth initializes -->
<script setup lang="ts">
import { useAuthStore } from '@/stores/auth';

const auth = useAuthStore();
</script>

<template>
  <div v-if="auth.isLoading" class="loading-screen">
    <p>Loading...</p>
  </div>
  <router-view v-else />
</template>
```

---

## OAuth Patterns

### Google OAuth (Web)

```vue
<!-- components/GoogleLoginButton.vue -->
<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import axios from 'axios';

declare global {
  interface Window {
    google: any;
  }
}

const router = useRouter();
const googleButtonRef = ref<HTMLElement | null>(null);
const scriptEl = ref<HTMLScriptElement | null>(null);

async function handleGoogleResponse(response: { credential: string }) {
  try {
    await axios.post('/api/auth/google', { token: response.credential }, {
      withCredentials: true,
    });
    router.push('/dashboard');
  } catch {
    console.error('Google login failed');
  }
}

onMounted(() => {
  const script = document.createElement('script');
  script.src = 'https://accounts.google.com/gsi/client';
  script.async = true;
  scriptEl.value = script;

  script.onload = () => {
    window.google.accounts.id.initialize({
      client_id: import.meta.env.VITE_GOOGLE_CLIENT_ID,
      callback: handleGoogleResponse,
    });

    if (googleButtonRef.value) {
      window.google.accounts.id.renderButton(
        googleButtonRef.value,
        { theme: 'outline', size: 'large' },
      );
    }
  };

  document.body.appendChild(script);
});

onUnmounted(() => {
  if (scriptEl.value) {
    document.body.removeChild(scriptEl.value);
  }
});
</script>

<template>
  <div ref="googleButtonRef" />
</template>
```

### Custom Auth Composable (替代 NextAuth.js)

```typescript
// composables/useAuthActions.ts
import { useAuthStore } from '@/stores/auth';
import { useRouter, useRoute } from 'vue-router';
import { computed } from 'vue';

export function useAuthActions() {
  const auth = useAuthStore();
  const router = useRouter();
  const route = useRoute();

  const status = computed<'loading' | 'authenticated' | 'unauthenticated'>(() => {
    if (auth.isLoading) return 'loading';
    return auth.isAuthenticated ? 'authenticated' : 'unauthenticated';
  });

  const session = computed(() => auth.user);

  async function signIn(provider: 'google' | 'credentials', credentials?: { email: string; password: string }) {
    if (provider === 'google') {
      // Google OAuth is handled by the GoogleLoginButton component
      return;
    }
    if (credentials) {
      await auth.login(credentials.email, credentials.password);
      const redirect = (route.query.redirect as string) || '/dashboard';
      router.push(redirect);
    }
  }

  async function signOut() {
    await auth.logout();
    router.push('/login');
  }

  return { status, session, signIn, signOut };
}
```

```vue
<!-- components/AuthButton.vue -->
<script setup lang="ts">
import { useAuthActions } from '@/composables/useAuthActions';

const { status, session, signIn, signOut } = useAuthActions();
</script>

<template>
  <div v-if="status === 'loading'">
    <span class="spinner" />
  </div>

  <div v-else-if="session">
    <span>Signed in as {{ session.email }}</span>
    <button @click="signOut">Sign out</button>
  </div>

  <div v-else>
    <button @click="signIn('google')">Sign in with Google</button>
    <button @click="signIn('credentials', { email: '', password: '' })">Sign in</button>
  </div>
</template>
```

---

## Protected Routes

### Vue Router Navigation Guards

```typescript
// router/index.ts
import { createRouter, createWebHistory } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import type { RouteLocationNormalized } from 'vue-router';

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('@/views/LoginPage.vue'),
      meta: { requiresGuest: true },
    },
    {
      path: '/dashboard',
      name: 'Dashboard',
      component: () => import('@/views/DashboardPage.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/settings',
      name: 'Settings',
      component: () => import('@/views/SettingsPage.vue'),
      meta: { requiresAuth: true },
    },
  ],
});

router.beforeEach(async (to: RouteLocationNormalized, from: RouteLocationNormalized) => {
  const auth = useAuthStore();

  // Wait for auth to initialize
  if (auth.isLoading) {
    // Optionally wait a tick for store initialization
    await new Promise<void>((resolve) => {
      const unwatch = watchEffect(() => {
        if (!auth.isLoading) {
          unwatch();
          resolve();
        }
      });
    });
  }

  if (to.meta.requiresAuth && !auth.isAuthenticated) {
    return { name: 'Login', query: { redirect: to.fullPath } };
  }

  if (to.meta.requiresGuest && auth.isAuthenticated) {
    return { name: 'Dashboard' };
  }
});

export default router;
```

```vue
<!-- views/LoginPage.vue — Redirect back after login -->
<script setup lang="ts">
import { ref } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import { useAuthStore } from '@/stores/auth';

const router = useRouter();
const route = useRoute();
const auth = useAuthStore();

const email = ref('');
const password = ref('');
const error = ref('');
const isSubmitting = ref(false);

async function handleLogin() {
  isSubmitting.value = true;
  error.value = '';
  try {
    await auth.login(email.value, password.value);
    const redirect = (route.query.redirect as string) || '/dashboard';
    router.push(redirect);
  } catch {
    error.value = 'Invalid email or password';
  } finally {
    isSubmitting.value = false;
  }
}
</script>

<template>
  <form @submit.prevent="handleLogin">
    <div v-if="error" class="error">{{ error }}</div>
    <div>
      <label for="email">Email</label>
      <input v-model="email" id="email" type="email" required />
    </div>
    <div>
      <label for="password">Password</label>
      <input v-model="password" id="password" type="password" required />
    </div>
    <button type="submit" :disabled="isSubmitting">
      {{ isSubmitting ? 'Signing in...' : 'Sign in' }}
    </button>
  </form>
</template>
```

### Route Meta for Granular Permissions

```typescript
// router/index.ts (extended)
const routes = [
  {
    path: '/admin',
    component: () => import('@/layouts/AdminLayout.vue'),
    meta: { requiresAuth: true, roles: ['admin'] },
    children: [
      { path: 'users', component: () => import('@/views/admin/UsersPage.vue') },
    ],
  },
];

router.beforeEach(async (to, from) => {
  const auth = useAuthStore();

  if (to.meta.requiresAuth && !auth.isAuthenticated) {
    return { name: 'Login', query: { redirect: to.fullPath } };
  }

  if (to.meta.roles && !to.meta.roles.includes(auth.user?.role)) {
    return { name: 'Forbidden' };
  }
});
```

---

## Token Refresh Pattern

### Axios Interceptor with Automatic Token Refresh

```typescript
// api/client.ts
import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios';
import { useAuthStore } from '@/stores/auth';
import router from '@/router';

const apiClient = axios.create({
  baseURL: '/api',
  withCredentials: true,
});

let isRefreshing = false;
let failedQueue: Array<{
  resolve: (token?: string) => void;
  reject: (error: unknown) => void;
}> = [];

function processQueue(error: unknown, token: string | null = null) {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error);
    } else {
      prom.resolve(token ?? undefined);
    }
  });
  failedQueue = [];
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean };

    // Only retry once and only on 401
    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        // Queue the request until refresh completes
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        })
          .then(() => apiClient(originalRequest))
          .catch((err) => Promise.reject(err));
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        await axios.post('/api/auth/refresh', {}, { withCredentials: true });
        processQueue(null);
        return apiClient(originalRequest);
      } catch (refreshError) {
        processQueue(refreshError, null);
        const auth = useAuthStore();
        await auth.logout();
        router.push('/login');
        return Promise.reject(refreshError);
      } finally {
        isRefreshing = false;
      }
    }

    return Promise.reject(error);
  },
);

export default apiClient;
```

---

## Form Handling

### Element Plus Form with Validation

```vue
<!-- views/LoginPageElementPlus.vue -->
<script setup lang="ts">
import { reactive, ref } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import type { FormInstance, FormRules } from 'element-plus';

const router = useRouter();
const route = useRoute();
const auth = useAuthStore();

const formRef = ref<FormInstance>();
const isSubmitting = ref(false);
const formError = ref('');

const form = reactive({
  email: '',
  password: '',
});

const rules: FormRules = {
  email: [
    { required: true, message: 'Email is required', trigger: 'blur' },
    { type: 'email', message: 'Invalid email address', trigger: 'blur' },
  ],
  password: [
    { required: true, message: 'Password is required', trigger: 'blur' },
    { min: 8, message: 'Password must be at least 8 characters', trigger: 'blur' },
  ],
};

async function onSubmit() {
  if (!formRef.value) return;

  try {
    await formRef.value.validate();
  } catch {
    return;
  }

  isSubmitting.value = true;
  formError.value = '';

  try {
    await auth.login(form.email, form.password);
    const redirect = (route.query.redirect as string) || '/dashboard';
    router.push(redirect);
  } catch {
    formError.value = 'Invalid email or password';
  } finally {
    isSubmitting.value = false;
  }
}
</script>

<template>
  <el-form
    ref="formRef"
    :model="form"
    :rules="rules"
    label-position="top"
    @submit.prevent="onSubmit"
  >
    <el-alert
      v-if="formError"
      :title="formError"
      type="error"
      show-icon
      closable
      @close="formError = ''"
    />

    <el-form-item label="Email" prop="email">
      <el-input v-model="form.email" type="email" placeholder="you@example.com" />
    </el-form-item>

    <el-form-item label="Password" prop="password">
      <el-input v-model="form.password" type="password" placeholder="Enter your password" show-password />
    </el-form-item>

    <el-form-item>
      <el-button
        type="primary"
        native-type="submit"
        :loading="isSubmitting"
        :disabled="isSubmitting"
      >
        {{ isSubmitting ? 'Signing in...' : 'Sign in' }}
      </el-button>
    </el-form-item>
  </el-form>
</template>
```

### Vee-Validate Alternative

```vue
<!-- views/LoginPageVeeValidate.vue -->
<script setup lang="ts">
import { ref } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import { useForm } from 'vee-validate';
import { toTypedSchema } from '@vee-validate/zod';
import { z } from 'zod';

const router = useRouter();
const route = useRoute();
const auth = useAuthStore();

const loginSchema = toTypedSchema(
  z.object({
    email: z.string().email('Invalid email'),
    password: z.string().min(8, 'Password must be at least 8 characters'),
  }),
);

const { handleSubmit, isSubmitting, setFieldError } = useForm({
  validationSchema: loginSchema,
});

const formError = ref('');

const onSubmit = handleSubmit(async (values) => {
  try {
    await auth.login(values.email, values.password);
    const redirect = (route.query.redirect as string) || '/dashboard';
    router.push(redirect);
  } catch {
    setFieldError('email', 'Invalid credentials');
    formError.value = 'Invalid email or password';
  }
});
</script>

<template>
  <form @submit="onSubmit">
    <div v-if="formError" class="error">{{ formError }}</div>

    <div>
      <label for="email">Email</label>
      <Field id="email" name="email" type="email" />
      <ErrorMessage name="email" />
    </div>

    <div>
      <label for="password">Password</label>
      <Field id="password" name="password" type="password" />
      <ErrorMessage name="password" />
    </div>

    <button type="submit" :disabled="isSubmitting">
      {{ isSubmitting ? 'Signing in...' : 'Sign in' }}
    </button>
  </form>
</template>
```

---

## Security Best Practices

### CSRF Protection

```typescript
// api/csrf.ts
import axios from 'axios';

const csrfApi = axios.create({
  baseURL: '/api',
  withCredentials: true,
});

// Fetch CSRF token on app initialization
export async function fetchCsrfToken(): Promise<string> {
  const response = await csrfApi.get('/csrf-token');
  const token = response.data.csrfToken;
  if (token) {
    axios.defaults.headers.common['X-CSRF-Token'] = token;
  }
  return token;
}

// Or read from meta tag (server-rendered)
function getCsrfTokenFromMeta(): string {
  const meta = document.querySelector<HTMLMetaElement>('meta[name="csrf-token"]');
  return meta?.content || '';
}
```

```typescript
// main.ts — Fetch CSRF token on app startup
import { createApp } from 'vue';
import { createPinia } from 'pinia';
import App from './App.vue';
import router from './router';
import { fetchCsrfToken } from './api/csrf';

async function bootstrap() {
  await fetchCsrfToken();

  const app = createApp(App);
  app.use(createPinia());
  app.use(router);
  app.mount('#app');
}

bootstrap();
```

### Security Headers (Vite Config)

```typescript
// vite.config.ts — Set security headers in dev server
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  plugins: [vue()],
  server: {
    headers: {
      'X-Content-Type-Options': 'nosniff',
      'X-Frame-Options': 'DENY',
      'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
    },
  },
});
```

> **Note:** In production, security headers should be set by the reverse proxy (Nginx, Caddy) or CDN, not by the Vite dev server. The Vite config above is for development consistency only.

---

## Common Issues

| Issue | Solution |
|-------|----------|
| Cookie not sent | Set `withCredentials: true` in axios instance or per-request config |
| CORS error with cookies | Server must set `Access-Control-Allow-Credentials: true` and `Access-Control-Allow-Origin` to a specific origin (not `*`) |
| Session lost on refresh | Verify cookie settings (domain, path, secure, SameSite) |
| OAuth redirect fails | Check redirect URI in Google Cloud Console matches deployed URL |
| Token in localStorage stolen | Move to httpOnly cookies; use Pinia state only for identity display |
| Store state lost on hard refresh | Re-initialize from cookie-based `/me` endpoint on app mount (built into Pinia store setup) |
| watchEffect not running in guard | Use a Promise-based wait pattern in `router.beforeEach` when auth is loading |
| Element Plus form `validate()` rejects | Wrap in try/catch; validation failure throws — this is expected behavior |
| Google GIS script re-loads on every mount | Clean up in `onUnmounted`; use `defineAsyncComponent` or keep the button mounted |

---
