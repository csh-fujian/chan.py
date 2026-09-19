---
name: vue-build-deploy
description: 构建和部署 Vue 3.5 + Vite Web 应用。适用于配置构建、部署到 Vercel/Netlify、设置 CI/CD、Docker 或管理环境。
---

# Web 构建与部署（Vue 3.5 + Vite）

## Vercel 部署

### 快速部署

```bash
# 安装 Vercel CLI
npm i -g vercel

# 部署
vercel

# 部署到生产环境
vercel --prod
```

### 配置 (vercel.json)

```json
{
  "buildCommand": "npm run build",
  "outputDirectory": "dist",
  "framework": "vite",
  "rewrites": [
    { "source": "/(.*)", "destination": "/" }
  ],
  "headers": [
    {
      "source": "/(.*)",
      "headers": [
        { "key": "X-Content-Type-Options", "value": "nosniff" },
        { "key": "X-Frame-Options", "value": "DENY" }
      ]
    }
  ]
}
```

### 环境变量

```bash
# 通过 CLI 添加
vercel env add VITE_API_URL

# 或在 Vercel 控制面板中：Settings > Environment Variables

# 在代码中访问
const apiUrl = import.meta.env.VITE_API_URL;
```

### 预览部署

每次推送到分支会自动创建预览 URL：
- `https://project-git-branch-username.vercel.app`

---

## Netlify 部署

### 快速部署

```bash
# 安装 Netlify CLI
npm i -g netlify-cli

# 登录
netlify login

# 部署预览
netlify deploy

# 部署到生产环境
netlify deploy --prod
```

### 配置 (netlify.toml)

```toml
[build]
  command = "npm run build"
  publish = "dist"

[[redirects]]
  from = "/*"
  to = "/index.html"
  status = 200

[[headers]]
  for = "/*"
  [headers.values]
    X-Frame-Options = "DENY"
    X-Content-Type-Options = "nosniff"

[build.environment]
  NODE_VERSION = "20"
```

### 环境变量

```bash
# 通过 CLI 添加
netlify env:set VITE_API_URL https://api.example.com

# 或在 Netlify 控制面板中：Site settings > Environment variables
```

---

## Docker 部署

### Dockerfile（多阶段构建）

```dockerfile
# 构建阶段
FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

# 生产阶段
FROM nginx:alpine

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制 nginx 配置（Vue Router history 模式 SPA 回退）
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
```

### nginx.conf（Vue Router history 模式 SPA 回退）

```nginx
server {
    listen 80;
    server_name localhost;
    root /usr/share/nginx/html;
    index index.html;

    # Gzip 压缩
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml;

    # 缓存静态资源
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # Vue Router history 模式 SPA 回退
    location / {
        try_files $uri $uri/ /index.html;
    }

    # 安全头
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
}
```

### Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  web:
    build: .
    ports:
      - "80:80"
    environment:
      - NODE_ENV=production
    restart: unless-stopped

  # 含后端
  api:
    build: ./backend
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/app
    depends_on:
      - db

  db:
    image: postgres:15-alpine
    volumes:
      - postgres_data:/var/lib/postgresql/data
    environment:
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
      - POSTGRES_DB=app

volumes:
  postgres_data:
```

### 构建与运行

```bash
# 构建镜像
docker build -t myapp:latest .

# 运行容器
docker run -p 80:80 myapp:latest

# 使用 docker-compose
docker-compose up -d
docker-compose down
```

---

## GitHub Actions CI/CD

### 基础工作流 (Vercel CLI)

```yaml
# .github/workflows/deploy.yml
name: Deploy

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Setup Node
        uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'

      - name: Install dependencies
        run: npm ci

      - name: Run tests
        run: npm test

      - name: Build
        run: npm run build
        env:
          VITE_API_URL: ${{ secrets.API_URL }}

      - name: Deploy to Vercel
        if: github.ref == 'refs/heads/main'
        run: |
          npm i -g vercel
          vercel deploy --prod --token=${{ secrets.VERCEL_TOKEN }}
```

### 预览部署 (Vercel CLI)

```yaml
name: Preview

on: [pull_request]

jobs:
  preview:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Deploy Preview
        id: deploy
        run: |
          npm i -g vercel
          vercel deploy --token=${{ secrets.VERCEL_TOKEN }} > deploy-url.txt
          echo "preview_url=$(cat deploy-url.txt)" >> $GITHUB_OUTPUT

      - name: Comment PR
        uses: actions/github-script@v7
        with:
          script: |
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: '🚀 Preview deployed to: ${{ steps.deploy.outputs.preview_url }}'
            })
```

---

## 环境配置

### Vite 环境变量

```typescript
// vite.config.ts
import { defineConfig, loadEnv } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  return {
    plugins: [vue()],
    define: {
      __APP_ENV__: JSON.stringify(env.VITE_APP_ENV),
    },
  };
});
```

```bash
# .env.development
VITE_API_URL=http://localhost:8000
VITE_APP_TITLE=My App (Dev)

# .env.production
VITE_API_URL=https://api.example.com
VITE_APP_TITLE=My App
```

**注意事项：**

- 所有客户端暴露的环境变量必须以 `VITE_` 为前缀，否则在客户端代码中不可用。
- 在 Vue 组件或 JS/TS 代码中通过 `import.meta.env.VITE_XXX` 访问。
- TypeScript 项目建议在 `env.d.ts` 中添加类型声明：

```typescript
// src/env.d.ts
/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL: string;
  readonly VITE_APP_TITLE: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
```

---

## 构建优化

### Vite 构建分析

```bash
# 安装分析器
npm i -D rollup-plugin-visualizer

# 添加到 vite.config.ts
import { visualizer } from 'rollup-plugin-visualizer';

export default defineConfig({
  plugins: [
    vue(),
    visualizer({
      filename: 'stats.html',
      open: true,
    }),
  ],
});

# 构建并分析
npm run build
```

### 代码分割

使用 Vue 的 `defineAsyncComponent` 实现按需加载：

```typescript
// 路由级分割（Vue Router）
import { createRouter, createWebHistory } from 'vue-router';

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/dashboard',
      component: () => import('./views/Dashboard.vue'),
    },
    {
      path: '/settings',
      component: () => import('./views/Settings.vue'),
    },
  ],
});

// 组件级分割
import { defineAsyncComponent } from 'vue';

const HeavyChart = defineAsyncComponent({
  loader: () => import('./components/HeavyChart.vue'),
  loadingComponent: LoadingSpinner,
  errorComponent: ErrorDisplay,
  delay: 200,
  timeout: 10000,
});
```

### 分包缓存策略

```typescript
// vite.config.ts
export default defineConfig({
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['vue', 'vue-router', 'pinia'],
          ui: ['element-plus'],
          utils: ['axios', 'dayjs'],
        },
      },
    },
  },
});
```

### Element Plus 按需导入优化

使用 `unplugin-vue-components` 和 `unplugin-auto-import` 实现 Element Plus 组件的按需导入，避免引入整个库的体积负担：

```bash
npm i -D unplugin-vue-components unplugin-auto-import
```

```typescript
// vite.config.ts
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import AutoImport from 'unplugin-auto-import/vite';
import Components from 'unplugin-vue-components/vite';
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers';

export default defineConfig({
  plugins: [
    vue(),
    AutoImport({
      resolvers: [ElementPlusResolver()],
      imports: ['vue', 'vue-router', 'pinia'],
      dts: 'src/auto-imports.d.ts',
    }),
    Components({
      resolvers: [ElementPlusResolver()],
      dts: 'src/components.d.ts',
    }),
  ],
});
```

**收益：** 未使用的 Element Plus 组件不会被打包到产物中，可显著减小生产 bundle 体积。同时自动声明类型文件，获得完整的 TypeScript 支持。

### 生产环境构建配置建议

```typescript
// vite.config.ts
export default defineConfig({
  build: {
    target: 'es2020',
    cssCodeSplit: true,
    sourcemap: false, // 生产环境关闭 source map
    chunkSizeWarningLimit: 500,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['vue', 'vue-router', 'pinia'],
        },
      },
    },
  },
  css: {
    preprocessorOptions: {
      scss: {
        additionalData: `@use "@/styles/variables.scss" as *;`,
      },
    },
  },
});
```

---

## SPA 与 SSR 说明

### SPA 模式（默认）

Vue 3.5 + Vite 默认构建为纯前端 SPA。**所有路由（除静态文件外）必须回退到 `index.html`**，否则用户刷新非根路径页面时将返回 404。

- **Nginx 回退：** `try_files $uri $uri/ /index.html;`
- **Vercel/Netlify：** 配置 rewrites/redirects 规则（见上文各平台配置）。

Vue Router 需使用 `createWebHistory` 模式：

```typescript
// src/router/index.ts
import { createRouter, createWebHistory } from 'vue-router';

const router = createRouter({
  history: createWebHistory(),
  routes: [...],
});
```

> 注意：`createWebHashHistory` 不需要服务端回退，但 URL 中会带有 `#` 符号，对 SEO 不友好。

## 健康检查与监控

### 健康检查端点

对于 Docker/Kubernetes 部署，可在 Nginx 配置中添加健康检查 endpoint：

```nginx
# 添加至 nginx.conf 的 server 块内
location /health {
    access_log off;
    return 200 '{"status":"healthy","timestamp":$msec}';
    add_header Content-Type application/json;
}
```

### 错误追踪（Sentry - Vue 集成）

```bash
npm install @sentry/vue
```

```typescript
// src/main.ts
import { createApp } from 'vue';
import { createRouter, createWebHistory } from 'vue-router';
import * as Sentry from '@sentry/vue';
import App from './App.vue';
import { routes } from './router';

const app = createApp(App);
const router = createRouter({
  history: createWebHistory(),
  routes,
});

Sentry.init({
  app,
  dsn: import.meta.env.VITE_SENTRY_DSN,
  environment: import.meta.env.MODE,
  tracesSampleRate: 0.1,
  integrations: [
    Sentry.browserTracingIntegration({ router }),
    Sentry.replayIntegration(),
  ],
  replaysSessionSampleRate: 0.1,
  replaysOnErrorSampleRate: 1.0,
});

app.use(router);
app.mount('#app');
```

---

## 常见问题

| 问题 | 解决方案 |
|------|----------|
| 刷新非根路径出现 404 | 配置服务端 SPA 回退规则（Nginx `try_files`，Vercel rewrites，Netlify redirects） |
| `import.meta.env.VITE_xxx` 为 `undefined` | 确保环境变量以 `VITE_` 为前缀，且 `.env` 文件位于项目根目录 |
| 构建时 TS 报 `ImportMeta` 类型错误 | 在 `src/env.d.ts` 中添加 `/// <reference types="vite/client" />` |
| CI 构建失败 | 检查 Node 版本、清除 npm 缓存 (`npm cache clean --force`)、确认 `npm ci` 而非 `npm install` |
| Docker 镜像过大 | 使用多阶段构建 + `alpine` 基础镜像，确认 `.dockerignore` 排除 `node_modules` |
| Element Plus 打包体积过大 | 使用 `unplugin-vue-components` 按需导入（见上文“构建优化”） |
| 构建速度慢 | 启用 Vite 依赖预构建缓存、CI 中缓存 `node_modules` 目录 |
| 生产环境白屏且无报错 | 检查路由模式是否为 `createWebHistory`，确认 history 回退已配置；检查浏览器控制台 JS/CSS 加载路径是否正确 |
| 组件懒加载后首次渲染慢 | 为 `defineAsyncComponent` 配置 `loadingComponent` 和合适的 `delay` |
| CSS 变量丢失或样式异常 | 确保 `vite.config.ts` 中 `build.cssCodeSplit` 为 `true`，检查 CSS 预处理器配置 |

---

## 部署检查清单

部署到生产环境之前：

- [ ] 所有 `VITE_` 前缀环境变量已设置
- [ ] 本地构建成功（`npm run build` 无错误）
- [ ] 测试全部通过（`npm test`）
- [ ] 安全头已配置（X-Frame-Options、X-Content-Type-Options 等）
- [ ] 错误追踪已启用（Sentry 等）
- [ ] 性能已优化（bundle 大小、代码分割、Element Plus 按需加载）
- [ ] Vue Router history 模式对应的 SPA 回退已配置
- [ ] SEO meta 标签（如适用）
- [ ] SSL/HTTPS 已启用
- [ ] 自定义域名已配置
- [ ] 健康检查端点可正常工作
- [ ] `.env.production` 文件中的值已确认正确
- [ ] `.dockerignore` 已配置（Docker 部署时）