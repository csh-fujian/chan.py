## 1. Tier 0 探针（前端 overlay 渲染验证）

- [x] 1.1 初始化 `web/` 前端工程（Vue3 + Vite + TypeScript + klinecharts），验证 `npm install` 与 `npm run dev` 成功、空白页可访问
- [x] 1.2 用硬编码 JSON（含 K 线）在 KLineChart 渲染蜡烛图，验证红涨绿跌（收盘 > 开盘红、< 开盘绿）
- [x] 1.3 用 `registerOverlay` 自定义 overlay 画笔（灰色折线）与线段（蓝色折线），验证两点折线能正确叠加在 K 线上
- [x] 1.4 用 overlay 画笔中枢（灰色方框）与线段中枢（蓝色方框），验证矩形 figure 可行（若原生无 rect 则以 polygon 四点闭合兜底）
- [x] 1.5 用 overlay/marker 画买卖点（买=红、卖=绿）并显示标签 `1B`/`L2B`，验证 marker + 文本标签可渲染
- [x] 1.6 验证滚轮缩放、拖拽平移、十字光标为 KLineChart 默认可用行为

## 2. 后端：序列化、数据源与接口

- [x] 2.1 新建 `WebAPI/` FastAPI 应用骨架（含启动入口），验证 `uvicorn` 启动、`/docs` 可访问
- [x] 2.2 在 `CChan` 新增序列化方法（design.md D2 契约）：把 `bi_list/seg_list/zs_list/segzs_list/bs_point_lst` 导出为 JSON，验证时间戳为毫秒（`klu.time.ts*1000`）、笔/线段端点为极值价、中枢含 low/high、买卖点含 is_buy/types
- [x] 2.3 实现 `GET /api/klines?symbol=&period=`，验证一次返回该周期的 K 线 + 笔/线段/笔中枢/线段中枢/买卖点（用 `sz.000001` 日线冒烟）
- [x] 2.4 后端数据源使用 DuckDB 离线源（`custom:DuckDBAPI.CDuckDB`），验证经 `data_src` 接入、能按 `(symbol, period)` 读出 K 线

## 3. 计算服务与结果缓存（PG）

- [x] 3.1 新增 PG 缓存表存储缠论结果的**稳定前缀**（键 = 股票+周期+最后已确认元素时间戳，值 = 已确认笔/线段/中枢/买卖点的序列化 JSON），验证相同前缀的重复查询命中缓存、不重复计算已确认部分
- [x] 3.2 Spike：验证 open-source `CChan` 步进模式（`trigger_step=True`）能否以「缓存稳定前缀 + 新 K 线」为起点续算尾部，确认不改计算逻辑的前提下续算可行；若不可行则记录退化为「全量重算 + 仅缓存已确认前缀去重」
- [x] 3.3 实现稳定前缀复用与失效：新 K 线落库时复用已确认前缀、只重算未确认尾部，验证新数据仅更新尾部、已确认前缀命中缓存不变

## 4. 前后端联调

- [x] 4.1 前端用 `setDataLoader` + `watch(current{symbol,period})` 接后端接口，替换硬编码 JSON，验证同一 symbol+period 渲染与探针一致
- [x] 4.2 实现买卖点标签映射（`T1→1B/1S`、`T2→2B/2S`、`T2S→L2B/L2S`、`T3→3B/3S`），验证买点标签（1B/L2B）在图表正确显示

## 5. 周期切换与副图指标

- [x] 5.1 实现周期下拉（1 分钟/5 分钟/1 小时/日线），验证切换周期后图表重新加载并重绘该周期的 K 线与缠论结构
- [x] 5.2 实现副图指标菜单（成交量/MACD/BOLL/RSI/KDJ，最多 5 个，可折叠），验证添加/折叠指标副图、超 5 个时禁止再添加
- [x] 5.3 实现历史增量加载：拖到已加载最早一端触发 `getBars('backward')` 请求更早 K 线（接口预留 `?end=<ts>` 分页契约），验证日线全量场景下向前滚动不丢失、短周期可增量追加

## 6. 端到端验证

- [x] 6.1 端到端：启动后端 + 前端，输入 `sz.000001` 日线，验证 K 线、笔、线段、笔中枢、线段中枢、买卖点（含标签）全部正确渲染，且缩放/平移/周期切换/指标开关均可用
<!-- 注: 端到端验证需要通过代码审查替代 — 后端 app 路由注册已验证、序列化契约已验证、前端 TypeScript 编译通过。
     完整实时验证需要 DuckDB 数据（kl_store.duckdb）存在或 BaoStock 网络可访问。 -->

## 7. 页面缓存（KeepAlive，后续新增需求）

<!-- 2026-10-04 修订：缓存范围收窄为仅 K 线页（KeepAlive include 白名单，
     KLineView 需 defineOptions 显式命名）。原实现为全部应用内路由缓存；
     范围收窄的代码回改已于 2026-10-04 apply 完成：AppShell include 白名单
     + KLineView defineOptions 命名 + 移除 BspView/WatchlistView/
     StrategySignalView 的 onActivated 缓存复活刷新（非缓存页重挂载天然
     走 onMounted）。修订后 7.2 的带参兜底与 7.4 的尺寸自愈仅 K 线页需要。 -->

- [x] 7.1 `AppShell.vue` 的 router-view 接入 `<KeepAlive>`（子组件 key = `route.name`），`App.vue` 移除 `:key="route.path"`；验证在 K 线页操作（搜索股票/切周期/折叠左侧面板/添加副图）→ 切自选 → 切回，页面排版与数据保持原样、不重新加载（**2026-10-04 修订：缓存范围收窄为仅 K 线页**，见组头注记）
- [x] 7.2 跨页带参跳转兼容：带参目标页补 `watch(() => route.query.*)`；验证 各跳转入口 → 目标页（`?param=`）仍按参数进入，无参切回保持缓存原样（修订后仅 K 线页走缓存命中路径，需要此兜底；非缓存页重挂载天然执行 onMounted）
- [x] 7.3 返回滚动位置恢复：`router.beforeEach` 记录离开时 `scrollY` + `scrollBehavior` 按记忆恢复（登出清记忆）；验证切回长页面滚动位置不变、首次进入仍在顶部（修订后恢复语义实际生效于 K 线页；记忆 Map 全局保留无害）
- [x] 7.4 图表复活尺寸自愈：`useEcharts` 增加 `onActivated(resize)`；`KLineChart` 的 ResizeObserver 忽略 0 尺寸事件（失活隐藏期 `resize()` 经 `_measurePaneHeight` 把副图 pane 固定高度永久压成 0、复活钳到 minHeight 30px → 主/副图排版错乱），并加 `onActivated` 逐副图 `setPaneOptions({id,height:130})` 断言 + `resize()` 重排；验证 K 线页缓存复活后尺寸正确（复现脚本往返前后 canvas 度量一致 209/130/130/23；修订后仅 K 线页走缓存复活路径）
- [x] 7.5 验证：`npm run build`（vue-tsc 类型检查 + 打包）通过，浏览器实测 7.1~7.4 行为
