## Context

前端为 Vue3 + Vite + TypeScript（`Front/`），MSW mock 驱动（`VITE_USE_MOCK=true`），真实后端（FastAPI + PostgreSQL）已落地于 `WebAPI/`（问答路由仍为 stub，LLM 未接入——即本变更后端任务的起点）。K 线页 `KLineView.vue` 当前为「顶栏（代码搜索/周期/副图指标/图例）+ 主图」单列布局。自选已存在独立页面 `WatchlistView.vue`（文件夹树 + 股票表格，支持新建/删除文件夹、加/移/移动股票），但缺少「重命名分组」；`Stock` 类型仅含 `industries`，无地区/概念。无任何大模型问答能力。

## Goals / Non-Goals

**Goals:**
- K 线页新增可折叠左侧面板，用「标的 / 问答」两 Tab 收纳自选管理、标的详情、问答三块能力，主图占剩余宽度。
- Tab 切换带内容缓存（含后续 `kline-metadata-change` 追加的「股票信息」Tab），切回时内容仍在。
- 标的详情补全地区/概念字段并全量展示板块信息。
- 自选在 K 线页提供「加入/移出 + 分组管理（含重命名）」。
- 问答完整闭环：提问 → 流式解答（系统提示词按用户可配、缠论结构自动注入）→ 记录列表（按 user_id 隔离）→ 详情弹窗 → 打星/批量打星/一键删除未打星 → PG 持久化。
- LLM 供应商预设可配置切换（管理员在 /system 管理，激活即时生效）。

**Non-Goals:**
- 不重做独立的 `/watchlist` 页面（其全量浏览仍在原页）。
- 不改 `CChan` 计算逻辑、不碰 K 线/缠论序列化契约。
- 不实现股票搜索联想（归 `chan-web-viewer` backlog）。

## Decisions

### D1. K 线页布局：可折叠左侧面板 + 主图（两 Tab）
`KLineView` 根容器由单列改为 `display:flex` 行布局：左侧面板（固定宽约 320px，可折叠）+ 主图（`flex:1`）。面板用两个 Tab：

- **标的**：标的头部（名称/编码/股价/涨跌幅）+ 行业/地区/概念 + 自选管理（加入/移出 + 分组管理）。
- **问答**：输入框 + 回答展示 + 记录列表（每条右侧带星星收藏图标，点击亮起/熄灭）+ 工具栏（批量打星 / 一键删除未打星）。

顶栏新增「加入自选 ★」按钮（展开面板并聚焦自选区）与「AI 问答」按钮（展开面板并切到问答 Tab）。理由：三块能力都与「当前股票」强相关，收纳为同一上下文面板比散落多入口更聚合；Tab 避免单列面板过长。

备选：三块能力分开放到独立路由/独立页面——被否，用户明确要求「在页面增加」并合理排版。

### D2. 标的详情数据模型与接口
`Stock` 扩展 `region: string` 与 `concepts: string[]`；新增 `StockProfile`（= Stock + 全量板块字段）。新增 `GET /api/stocks/:code/profile` 返回 `StockProfile`。mock 侧在 `stocks.ts` 补 region/concepts，新增 handler。展示时行业/概念全量渲染（复用 `IndustryBadges` 的 badge 样式，地区用单 badge）。

理由：现有 `findStock` 仅用于自选搜索，profile 需独立契约以承载「全量板块」；地区为单值、行业/概念为多值。

### D3. 自选管理：复用 + 新增「重命名」
复用既有自选 API（`getFolders`/`createFolder`/`deleteFolder`/`addStock`/`removeStock`/`moveStock`）。新增 `renameFolder(id, name)` → `PATCH /api/watchlist/folders/:id`。「是否已自选」由 `getFolders()` 返回的 `codes` 推导（无需新查询）；「移出自选」= 对该股票所属分组调用 `removeStock`。底层 `watchlist_folder`/`watchlist_item` schema 复用 `chan-stock-manage` D1 定义，不重复建表。

理由：最小改动补齐「编辑分组（重命名）」缺口，避免与既有 watchlist 能力重复定义 schema。

### D4. 问答 API 契约与 PG schema（2026-10 修订：user_id 隔离 + SSE 流式）

新增 PG 表：

```sql
qa_record (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES chan_user(id),
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  starred BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_qa_record_user_created ON qa_record (user_id, created_at DESC);

user_setting (
  user_id INTEGER NOT NULL REFERENCES chan_user(id),
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  PRIMARY KEY (user_id, key)
);
```

- `user_id` 按用户隔离问答库（决策选项 3）：列表只返回本人记录，打星/批量打星/删除只作用于本人记录（批量按 `ids + user_id` 过滤）。
- `user_setting` 存系统提示词（`key='system_prompt'`），空/缺省回退默认提示词（见 D8.3）。

API 契约（原 5 个问答路由 + 2 个系统提示词路由全部挂 `get_current_user`——仓库首个鉴权的业务路由）：

- `POST /api/qa` body `{ question, code?, period? }` → **SSE 流式响应**（事件契约见 D8.2），`done` 事件携带落库后的完整 `QaRecord`。
- `GET /api/qa` → 本人 `QaRecord[]`（按 `created_at` 倒序）。
- `PATCH /api/qa/:id/star` body `{ starred }` → 单条打星/取消（校验记录归属）。
- `POST /api/qa/star` body `{ ids: number[], starred }` → 批量打星（`WHERE user_id = 当前用户`）。
- `DELETE /api/qa/unstarred` → 删除本人所有 `starred=false` 的记录。
- `GET /api/qa/system-prompt` → `{ prompt }`；`PUT /api/qa/system-prompt` body `{ prompt }` → 写入 `user_setting`（见 D8.3）。

DAO 用 psycopg2 裸 SQL（对齐 `RecomputeCursor` 与 `chan-stock-manage` 约定）；问答记录强依赖 PG——连接失败时直接 503、不做内存回退（避免重启即丢记录的假象，区别于 watchlist 的离线降级）。

### D5. LLM 供应商可插拔（2026-10 修订：OpenAI 兼容 + 双签名）

提问输入 = 问题文本 + 当前股票/周期上下文（`code`/`period`，见 D8.4 自动注入）；输出 = 回答文本。后端抽 `WebAPI/llm_client.py`，**仅依赖 `requests`**（不引入 openai/httpx SDK），调 OpenAI 兼容 Chat Completions 端点：

- `complete(system: str, prompt: str, timeout: float) -> str` — 非流式，供测试连接与内部调用。
- `complete_stream(system: str, prompt: str, timeout: float) -> Iterator[str]` — 流式增量，ask 路由经 `await asyncio.to_thread(...)` 消费。

供应商与模型由 D8.1 的解析链决定（PG 激活预设 > env 兜底 > 503）；契约先行、供应商可插拔。

### D6. 前端 mock-first，后端后置
前端先以 MSW 落地：新增 `qa`/`stock` handler 与 mock 数据，`qa` mock 用延迟 + 预设回答模拟 LLM；记录在 mock 内以内存数组模拟 PG（`VITE_USE_MOCK=true`）。真实后端（D4/D5 的 FastAPI + PG）在 `WebAPI/` 落地时接入，前端切 `VITE_USE_MOCK=false` 即用真实接口。

### D7. Tab 内容缓存：面板内 `<component>` + `KeepAlive`
`kline-side__body` 的 `v-if / v-else-if / v-else` 链改为 `<component :is="activeTabComponent">` 外包 `<KeepAlive>`，每个 Tab 一个缓存槽（标的 / 股票信息 / 问答，共 3 个，数量有界）：首次切换才挂载（惰性），其后实例与其本地状态（问答输入草稿与记录、标的分组列表与详情、股票信息元数据）跨 Tab 切换保留。

- **与 chan-web-viewer D10 的关系**：D10 是「页面 ↔ 页面」的路由级缓存（AppShell 的 KeepAlive）；本决策是同一页面内「Tab ↔ Tab」缓存，挂在面板层，互不干扰——页面级缓存复活 KLineView 时，其内部 Tab 缓存一并保留。
- **换股一致性**：缓存实例仍接收 `:code` prop 更新。`StockPanel`/`StockMetaPanel` 已有 `watch(() => props.code, ..., { immediate: true })`（失活状态下 watcher 照常触发）→ 缓存不会展示过期股票信息；`QaPanel` 记录为按用户的全局数据、与 code 无关，提问时取最新 `:code`/`:period` prop（用于 D8.4 结构注入），缓存同样安全。
- **「股票信息」Tab**：由 `kline-metadata-change` 追加，其 spec 要求切换行为与既有 Tab 一致，故同样进入缓存槽；该变更是否为其补独立缓存场景由其自身负责。
- **备选 `v-show` 三 Tab 全渲染**：被否——页面加载即并发三份请求且 DOM 常驻；`KeepAlive` 惰性挂载、按槽缓存，且与既有页面级 KeepAlive 模式一致。

### D8. LLM 接入方案（2026-10 定稿：流式 + 供应商切换 + 按用户提示词 + 结构注入）

#### D8.1 供应商预设与三层解析（cc-switch 式切换）

PG 表：

```sql
llm_provider (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  base_url TEXT NOT NULL,
  api_key TEXT NOT NULL,
  model TEXT NOT NULL,
  active BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

- 约束：至多一条 `active=true`（DAO 在事务内先全部置 false 再置目标为 true）。
- 新增/激活/删除/测试连接路由挂 `manage` 权限（`get_current_user` + 权限位检查，对齐 RBAC 按钮显隐约定）；列表返回时 `api_key` 脱敏（仅尾 4 位）。
- 配置解析链（每请求实时取，切换即时生效、无需重启）：
  1. PG 中 `active=true` 的预设；
  2. 环境变量 `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` / `LLM_TIMEOUT`（默认 60s）——写入 `WebAPI/config.py`；
  3. 均无 → 503 `LLM 未配置`。
- 测试连接：用解析到的配置调 `complete()` 发一条极短 prompt，返回成功或供应商错误原文。

#### D8.2 ask SSE 流式链路

`POST /api/qa` 返回 `Content-Type: text/event-stream`，事件为 `data:` 携带的 JSON：

- `{"type":"delta","text":"..."}` — LLM 增量文本；
- `{"type":"done","record":{...QaRecord}}` — 生成完成**且落库成功**后发送；
- `{"type":"error","detail":"..."}` — 生成/落库失败。

约束：

- 仅在 `done` 之前成功才落库——中途断开或 LLM 报错不产生残缺记录；
- 块间空闲超时 30s 判失败（防供应商挂起）；
- FE 必须用 `fetch` + `ReadableStream` 解析（axios 无法读流）；
- 提示词组装 = system（用户系统提示词或默认）+ 注入结构段（可选，D8.4）+ 用户问题。

#### D8.3 系统提示词按用户配置（存储方案 B：PG 按用户）

- 默认提示词硬编码为后端常量，v1 定稿如下（2026-10-01 用户提供）：

```text
# Role: 缠论量化拓扑专家与资深全栈算法架构师

## 1. 核心定位与能力边界
你拥有双重专家身份：
1. **缠中说禅原生理论践行者**：深度洞察《教你炒股票108课》哲学本质与几何拓扑逻辑，坚持“不测而测、唯信号分类”的客观态度。杜绝神化与宿命论，用几何结构严格定义当下走势，利用多级别联立（动态区间套）推演各分类的概率边界。
2. **资深量化工程与算法架构师**：拥有10年以上金融工程与Python高频/中频量化交易系统开发经验，深刻理解时序数据处理中的“未来函数陷阱”、“回放动态重绘（Repainting）”与实盘低延迟挑战。

---

## 2. 缠论理论分析标准规范

当进行行情分析与推演时，你必须严格按照以下递进逻辑执行：

### Step 1: 严格几何形态定义（严禁跳跃推演）
- **分型定义**：基于K线完全包含处理（向前包含原则）后的极值顶底分型。
- **笔的严格确认**：顶底分型之间至少包含一根独立K线（即无包含关系的5根K线底到顶/顶到底）；区分“成笔”与“笔破坏”。
- **线段与中枢**：至少由连续三笔重叠部分构成基础中枢 $[Z_G, Z_D]$；明确线段特征序列的分型逻辑与第一/二类线段破坏。
- **背驰判定**：必须结合“走势形态背驰（盘整背驰/趋势背驰）”与“动力学指标衰竭（如MACD面积/柱体高度收缩、成交量缩量）”。严格区分背驰与盘整背驰。

### Step 2: 走势分类与当下位置定性
- 标明当前分析的基准级别（如日线、30分钟、5分钟）。
- 定位当前属于该级别的哪种状态：中枢震荡、趋势延续（中枢离开段）、三买/三卖确认期、抑或背驰反转点。
- 运用**区间套定理**，自上而下进行三级联立（大级别定方向，本级别定中枢，次级别抓转折点精确打点）。

### Step 3: 后续走势分类与概率推演（动态不测而测）
- 依据“走势必完美”与中枢生灭定理，穷尽后续可能出现的**完全分类**（通常为2至3种路径）。
- 结合量价结构与次级别背驰形态，给出各分类的**触发条件、确认信号、演变概率与失效边界（止损位）**。
- 输出决策矩阵：买点（一买抄底、二买确认、三买中继加速）与卖点对应仓位管理策略。

---

## 3. Python量化工程与算法实现标准

当编写缠论指标、结构识别及策略回测代码时，遵循以下工程规范：

### 工程架构设计
1. **纯矢量化与状态机混合架构**：
   - 包含关系处理与分型初筛：优先使用 `NumPy` / `Pandas` / `Numba` 进行高性能矢量化处理。
   - 笔与线段识别：采用严格的**确定性有限状态机（FSM）**，有效管理“未定笔/临时笔”与“已确认笔”。
2. **零未来函数（No Future Leakage）**：
   - 笔和中枢的动态确认必须具有时间因果性。实盘计算时，未完成的笔只能作为“临时笔”标记，严禁将未确认的右侧极值写入已闭合的K线状态。
3. **策略接口标准**：
   - 基于主流事件驱动框架（如 Backtrader、VN.PY）或纯高频流式数据处理进行模块化封装。
   - 接口需包含明确的Type Hints、输入校验与完备的单元测试用例。

---

## 4. 输出响应协议

每当用户提出分析请求或编程任务时，按以下结构分步输出：

- **若是行情分析**：
 1. `【当前级别与形态定义】`：包含关系清洗后的分型、当前笔/线段所处位置。
 2. `【中枢拓扑与能量分析】`：中枢区间 $[Z_G, Z_D]$、进入段与离开段动力学背驰比对。
 3. `【多级别联立推演】`：大级别背景、本级别分类、次级别验证。
 4. `【完全分类走势与概率研判】`：分类1（条件/概率/目标位）、分类2（条件/概率/破位预警）。
 5. `【操作纪律策略】`：开平仓触发条件、止损止盈硬线、仓位建议。

- **若是代码实现**：
 1. `【算法数学模型与状态机定义】`：解释如何消除未来函数、核心状态转移条件。
 2. `【生产级完整代码】`：包含数据结构类、状态机处理类、信号生成逻辑，代码自带清晰文档注释。
 3. `【实战陷阱与性能优化提示】`：指出重绘边界、滑动差价应对、次级别数据对齐注意事项。
```

- `GET/PUT /api/qa/system-prompt` 读写 `user_setting(user_id, key='system_prompt')`（D4）；恢复默认 = 写入空串，读取时空值回退上述默认常量。
- 前端在问答 Tab 提供「提示词」对话框编辑（任务 6.3）。
- ask 时将解析出的提示词作为 `system` 角色消息传入，不拼进 user 消息。
- 按用户隔离：A 的修改不影响 B。

#### D8.4 缠论结构上下文注入（v2，自动注入 + 静默降级）

- **触发**：请求带 `code` 时自动注入；FE 问答 Tab 必传当前 `:code`/`:period`（现 QaPanel 无 props 为已知缺口，任务 6.1 补）；不做前端开关。
- **来源**：复用 `/api/klines` 同一路径 `_compute_chan` + `serialize_chan()`（含 `chan_stable_prefix` 缓存），不新增计算逻辑。
- **裁剪**（约 1500 token 量级）：最近 20 根 K 线（OHLC 摘要）、最近 10 笔、最近 3 段、最近 2~3 个中枢、最近 5 个买卖点；`is_sure=false` 的元素标注「未确认」。
- **注入位置**：system 之后、用户问题之前，作为独立 context 段。
- **降级**：结构计算失败（无该 code/period 数据、缓存异常等）→ **静默**跳过注入、按纯文本继续（不报错、前端无感知）；LLM 调用失败 → `error` 事件、不落库。

## Risks / Trade-offs

- [与 chan-stock-manage 的 watchlist 能力重叠] → 本变更只新增「重命名」+ K 线页集成，schema/模型复用其定义；归档时协调合并，避免冲突。
- [供应商非 OpenAI 兼容端点] → 预设链只支持 OpenAI 兼容 `/chat/completions`（D8.1）；异构供应商需自备网关代理，v1 不支持。
- [流式中断产生残缺记录] → 仅 `done` 前落库（D8.2），中断即无记录，用户重发即可。
- [结构注入的 token 与耗时成本] → 裁剪至约 1500 token 量级、复用既有缓存（D8.4）；失败静默降级不影响可用性。
- [左侧面板挤压主图宽度] → 面板可折叠，默认展开；窄屏下折叠后主图占满宽度。

## Open Questions

- （2026-10 已决）供应商与模型 → D8.1 预设表 + env 兜底；上下文携带 → D8.4 带 `code` 即自动注入；系统提示词 → D8.3 按用户可配、内置默认；问答记录 → D4 按 `user_id` 隔离。
