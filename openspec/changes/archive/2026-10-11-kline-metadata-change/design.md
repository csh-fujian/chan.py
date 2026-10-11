## Context

见 proposal.md（Why/What）。与本设计相关的现状事实：

- `GET /api/stocks?q=` 已存在（`WebAPI/routers/stocks.py` → `stock_store.list_stocks`），当前匹配条件为 `code ILIKE OR name ILIKE`，自选/预警页已在用。
- `stock.name` 有三个写入口，全部收口在 `WebAPI/stock_store.py`：`upsert_stock`（手动增改）、身份域同步（约 L559，BaoStock 名单同步，name 会变）、`import_stocks`（全市场批量导入）。
- K 线页顶栏是裸 `el-input` + `handleSearch()`：输入值原样当 code 加载，无下拉、不查库。
- 前端已有 `searchStocks(q)` API 封装与 watchlist 的 `el-select filterable remote` 用法；**全前端无 debounce 工具**（watchlist 逐键直发）。
- PG 不可用时 `_fallback_list_stocks` 读 DuckDB `kline` 表——**只有 code，没有名称**。
- `stock` 表约 6k 行（A 股全市场量级）。

## Goals / Non-Goals

**Goals:**

- K 线页搜索框支持编号/名称/拼音首字母三列模糊搜索下拉，点选后精确加载 K 线
- 手动输入完整代码回车的既有行为保持不变
- 拼音首字母作为 `stock` 表数据维护（写入生成 + 存量回填），搜索在 PG 侧完成模糊匹配
- 复用既有 `GET /api/stocks?q=`，watchlist/alerts 免费获得拼音匹配

**Non-Goals:**

- 全拼/部分拼音匹配（`pingan`）——已确认本期只存首字母
- 曾用简称（former_names）参与搜索
- pg_trgm GIN 索引（行数太少，见 D4）
- 搜索结果按相关度排序/高亮（保持分页原序）
- 无 PG 时的名称/拼音兜底匹配（DuckDB 无名称数据，code-only 即达标）

## Decisions

### D1. 复用 `GET /api/stocks?q=`，匹配扩为三列 OR

```sql
(s.code ILIKE %s OR s.name ILIKE %s OR s.name_py ILIKE %s)  -- 同一 q 参数绑定三次
```

- **备选：新增 `/api/stocks/search` 专用端点** —— 拒绝：契约与 `list_stocks` 完全同构（q + 分页），新端点只会造成两处实现漂移；自选/预警调用方零改动获得新能力是净收益。
- 不区分输入类型，编号/中文/字母混着输都交给三列 OR，前端不做类型判断。

### D2. `stock.name_py` 列：仅首字母，pypinyin 生成，写入口收口

- 列定义：`name_py VARCHAR NOT NULL DEFAULT ''`，存小写首字母串（「平安银行」→ `payh`），非中文字符（`ST`、数字）原样保留拼入，匹配靠 ILIKE 大小写不敏感。
- 生成：`pypinyin.lazy_pinyin(name, style=Style.FIRST_LETTER)` 过滤连接，抽一个 `gen_name_py(name)` 辅助函数，**三个 name 写入口统一调用**。
- **备选 a：PG 扩展（pg_pinyin 等）在 SQL 内转换** —— 拒绝：需装扩展，部署环境不可控。
- **备选 b：查询时应用层内存计算全表拼音** —— 拒绝：违背「通过 PG 表模糊匹配」的既定方向，且每次查询付 pypinyin 成本。
- **备选 c：`trigger` 触发器生成** —— 拒绝：pypinyin 在 PG 内跑不了，触发器仍要回应用层，徒增复杂度。

### D3. 迁移与回填：init.sql 补列 + `_ensure_tables` 进程级一次性回填

- `init.sql` 加幂等 `ALTER TABLE stock ADD COLUMN IF NOT EXISTS name_py ...`（与既有补列惯例一致）。
- `stock_store._ensure_tables`（负责存量补列的既有位置）：补列成功后，进程内首次执行时回填——`SELECT code, name FROM stock WHERE name_py = '' AND name <> ''`，应用层算拼音后批量 UPDATE。模块级 flag 保证每进程至多一次。
- 回填条件 `name_py = ''` 天然幂等，且**兜底任何未来新写入口漏生成**的情形（重启即自愈）。
- **不做独立回填脚本**：6k 行、纯 CPU、秒级，挂在启动路径足够；独立脚本多一个会被忘掉的人工步骤。

### D4. 暂不建索引

- `ILIKE '%q%'` 走不了 btree；6k 行顺序扫描在毫秒级，加 LIMIT 30 后端到端无感。
- 若未来行数/延迟有问题，逃生通道是 `pg_trgm` GIN（code/name/name_py 三列），届时再立任务，不在本期。

### D5. K 线页下拉：`el-autocomplete`，Enter 恒走原值（方向键浏览后除外）

- **备选 a：抄 watchlist 的 `el-select filterable remote`** —— 拒绝：`el-select` 是「值必须来自选项」的选中模型，K 线页顶栏要求「任意文本 + Enter 原样提交」，两者语义冲突，硬凑要 hack `allow-create` 一堆边角。
- **备选 b：手写下拉面板** —— 拒绝：自己处理定位/键盘/空态，工作量大于收益。
- 选 `el-autocomplete`：`v-model` 保持自由文本（既有 `codeInput` 不动），`:fetch-suggestions` 接 `searchStocks`，`@select` 处理点选 → `code.value = 选中code; load()` 并同步输入框。
- **Enter 语义**（保证 spec「手动精确输入」）：拦截 autocomplete 默认的「回车选中高亮项」——
  - 用户未用方向键浏览过候选 → Enter 按**输入框原值**走既有 `handleSearch()`
  - 用户用 ↑↓ 浏览过候选（记 flag）→ Enter 选中高亮项；鼠标点选任何时候都选中
  - 方向键浏览后输入内容变化 → 重置 flag

### D6. 防抖 300ms，本地实现

- 输入停顿 300ms 后才发请求；空输入不请求并收起下拉；进行中请求用「后发覆盖」（忽略过期响应，只采纳最后一次 query 的结果）。
- **不引 lodash**：前端现无任何 debounce 工具，为一个 10 行的 `setTimeout` guard 引整库不成比例；逻辑内联在 `KLineView.vue`（或抽 `Front/src/utils` 下小函数，实现时定）。
- watchlist 现状无防抖，本期不顺手改（范围控制），仅在 design 留痕。

### D7. Mock 与真实后端行为对齐

- `Front/src/mock/handlers/stock.ts`：mock 数据补 `name_py` 字段，匹配条件加第三列 `name_py.includes(q)`，保持 `VITE_USE_MOCK=true` 下演示行为与 spec 一致。
- mock 的 `name_py` 手工标注即可（mock 数据量小，不引入 pypinyin 到前端）。

## 元数据 tab（kline-stock-metadata）的实现取舍

spec 已把行为（分组顺序、去重边界、接口契约、空态）钉死，这里只记录实现层面的选择：

### D8. 元数据聚合为单接口 `GET /api/stocks/{code}/meta`

- 一次请求内查 `stock` 单行（档案/快照/身份/tags/notes 全在其上）+ `stock_holder_num` 近 1 年序列，组装后返回；两三个小查询在同请求内顺序执行即可，不开并行、不做缓存（面板低频访问）。
- **备选：前端并行调 `/stocks/{code}`、`/profile`、holders 多接口再聚合** —— 拒绝：N 次往返、聚合逻辑泄漏到前端、404/部分失败语义难统一；spec 要求「一键全量、键恒定存在」，单接口最直接。

### D9. 前端 `StockMetaPanel.vue` 单组件，ECharts 画户数趋势

- 挂在 `KLineView.vue` 左侧第三个 tab（「标的 / 股票信息 / 问答」），组件自取 `props.code` 拉取 meta。
- 长文本折叠用 `el-collapse`；股东户数 sparkline 用项目已有的 ECharts（`vue-echarts`/直接实例按 K 线页现有惯例），不引图表新库。
- 404 → 面板级「暂无元数据」空态；字段空值 → `--` 占位（spec 已定义，组件内统一格式化函数）。

### D10. Mock 先行可联调

- `Front/src/mock/handlers/stock.ts` 加 `GET /stocks/:code/meta` handler，数据手工编造覆盖「有值 + 稀疏字段为空 + holders 空序列」三种形态，保证 `VITE_USE_MOCK=true` 下三种 spec 场景均可手验。



- [未来新增 name 写入口漏生成 `name_py`] → D3 的 `name_py = ''` 条件回填在每次进程启动时自愈；规范上新写入口应调 `gen_name_py`。
- [`stock-metadata-sync`（进行中）与本变更同改 `WebAPI/stock_store.py`，合并冲突] → proposal Impact 已注明；实施时小步提交、先合已完成方。
- [pypinyin 多音字首字母偏差（人名/地名多音字）] → 股票简称以词组为主，pypinyin 按词拼音准确率可接受；即便偏差，编号/名称两列仍是准确兜底，搜索不因此失效。
- [拼音只存首字母 → 用户输全拼匹配不到] → 已确认的本期范围（Non-Goal）；名称模糊匹配覆盖「输部分中文」的场景。
- [`el-autocomplete` Enter 拦截与 Element Plus 内部键盘处理的兼容] → 用捕获阶段处理 keydown 并 `stopPropagation`；验收以 spec「手动输代码回车」场景为准。
- [ILIKE 前通配全表扫] → D4：6k 行无感；规模化后走 pg_trgm 逃生通道。

## Migration Plan

1. `Script/requirements.txt` 加 `pypinyin`，`pip install`
2. 部署 `init.sql` 补列（幂等）→ 重启 WebAPI（`_ensure_tables` 自动补列 + 一次性回填）
3. 前端发布（搜索下拉 + mock 同步）
4. **回滚**：列与依赖均为增量，旧代码忽略 `name_py`，回滚代码即可，无需回滚 DDL

## Open Questions

- （无——全拼支持、pg_trgm、watchlist 防抖均为已记录的 Non-Goal/留痕项，不影响本期方案与任务拆分。）
