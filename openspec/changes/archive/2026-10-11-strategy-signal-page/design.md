# Design: strategy-signal-page

## Context

/bsp 页与 bsp_index 深度绑定缠论语义（六类 bsp_type、多级别、区间套），不适合承载非缠论策略信号。监控是 bsp_index 唯一已落地的下游消费方（`_fill_bsp_context` 按 (code, kl_type) 回查，见 monitor_store.py:725）；预警、绩效后端均为 stub。原始 K 线已在 DuckDB（`Data/kl_store.duckdb`，KLineStore 读取）。选股器页（/screener）已有 mock 层的 `Strategy` 概念（缠论买卖点过滤器），与本变更的策略引擎信号是不同实体，需命名区分。

约束（延续既有变更约定）：不改 CChan/CBiList/CSegListChan/CZSList/CBSPointList 计算逻辑；不动 bsp_index 表结构；DuckDB 存原始 K 线、PG 存结论与元数据；策略引擎纯读 DuckDB。

## Goals / Non-Goals

Goals：
- 策略定义 / 参数实例 / 信号三层抽象，新策略接入 = 注册定义 + 写引擎，前端零改动
- 实例不可变，历史信号永不覆盖，绩效可按实例（参数组）对比
- 策略信号接入监控（source 维度），预警/绩效契约预留
- 与 catchup 同风格的低风险水位调度

Non-Goals：
- 不做策略参数的版本化覆盖回算（不可变实例消解该问题）
- 不做预警/绩效实现（stub 只预留 source 参数）
- 不做信号与监控双向联动（state 冻结、监控事件不回写）
- 不做盘中实时扫描（第一版 EOD 日终一次）
- 不把缠论买卖点纳入策略信号页（/bsp 保持唯一缠论入口）
- 不实现「回调中→已触发」之外更细的量价明细落库（payload 只存列表列所需摘要）

## Decisions

### D1. 三层数据模型：`strategy` / `strategy_instance` / `strategy_signal`

```
strategy              -- 定义层，代码注册，非用户 CRUD
  id VARCHAR PK        -- 如 'vol_breakout_pullback'
  name, group_name, engine, sort
  params_schema JSONB  -- [{key,label,type,default,min,max}]
  states     JSONB     -- [{value,label,color}]
  columns    JSONB     -- [{key,label,from_payload,type}]

strategy_instance     -- 使用层，用户配置，不可变
  id SERIAL PK
  strategy_id VARCHAR FK
  label VARCHAR        -- 侧栏显示名，如「回调5日」
  params JSONB
  enabled BOOLEAN DEFAULT TRUE
  created_at

strategy_signal       -- 信号，挂实例
  id SERIAL PK
  instance_id INT FK, code, signal_date DATE
  state VARCHAR        -- 取值域 = 所属 strategy.states
  is_buy BOOLEAN
  entry_ref_price, stop_ref_price DOUBLE PRECISION
  payload JSONB        -- 策略私有字段（首板日/回调天数/量比…）
  updated_at
  UNIQUE (instance_id, code, signal_date)
```

备选：每策略一张专表（类型安全）vs 统一宽表 + payload。选统一宽表：多策略开放接入下，专表会让「跨策略查询/下游接入/动态列」都要按表分叉，schema 驱动的前端形态（D5）也依赖统一注册表。私有字段高频筛选的代价用表达式索引兜底（按需）。

`UNIQUE(instance_id, code, signal_date)` 的取舍：同日同股同实例只允许一条信号（首板策略语义下自然成立：同日不可能两个独立信号事件）。若未来策略需要同日多信号，扩展唯一键加 `seq` 列，属非破坏演进。

### D2. 实例不可变 + 建实例即全量回算

改参数 = 新实例。回算成本：引擎纯读 DuckDB K 线做增量式扫描（无 pickle 链），单实例全量扫约几千键，EOD 窗口内可完成；全量回算只在建实例那一刻发生一次。删除实例级联删除其信号（PG FK ON DELETE CASCADE，UI 确认）。

备选：参数可变 + 信号按参数版本标记。否决：回算覆盖语义复杂（部分信号失效/保留判定无原则可依），绩效归因模糊。不可变实例让「哪组参数跑出来的」永远可追溯。

### D3. 引擎接口与状态机

```python
class StrategyEngine(Protocol):
    def scan(self, keys: list[tuple[str, str]], watermark: ... ) -> list[SignalEvent]
```

- `keys` 为 (code, kl_type_db) 集合（复用 catchup 的键枚举方式）；watermark 按 (instance_id, code) 记在 `strategy_scan_cursor` 表（仿 recompute_cursor）
- `SignalEvent` 含 code、signal_date、state、is_buy、entry_ref_price、stop_ref_price、payload；引擎内部自行管理状态演进（如 回调中 → 第5日未触发 → 已失效）
- 状态冻结：信号加入监控时在 strategy_signal 上记 `frozen BOOLEAN`（加监控动作置位），引擎 upsert 前跳过 frozen 行
- 首个引擎 `VolBreakoutPullbackEngine`：读 DuckDB 日线，参数（params_schema 声明）：回调天数上限（默认5）、放量倍数（默认2.0）、回调量缩阈值等；状态集 watching/triggered/expired/running

备选：状态机由框架统一驱动（引擎只出原始事件）。否决：状态语义是策略私有的（「已启动」的判定就是策略逻辑本身），框架统一状态机会稀释语义，注册表声明 states 已满足展示层需求。

### D4. 调度：EOD 复用 + 独立游标表，不进 bsp catchup

- 独立 `strategy_scan_cursor`（instance_id, code → watermark），不与 recompute_cursor 混用（两者水位语义不同：缠论是计算游标，策略是扫描游标）
- 挂到 app.py 现有 EOD loop 之后顺序执行（BSP_EOD_AT 触发点之后追加策略扫描阶段），失败互不影响（各自 try/except）
- 手动补算入口：`POST /api/strategy/instances/{id}/scan`，异步执行（BackgroundTasks），幂等
- 备选：引擎调度并入 bsp catchup tick。否决：catchup 的批次语义、游标键、失败重试都是缠论特化的，混入策略会互相牵制回滚粒度

### D5. 前端 schema 驱动 + 命名区分

- 新页面 `Front/src/views/strategy/StrategySignalView.vue`，路由 `/strategy`，权限 `menu:strategy`（新增权限项，admin 默认有）
- 侧栏：`GET /api/strategy/definitions` 返回定义（含 params_schema/states/columns/group_name）+ 实例树 + 计数；表格私有列/状态标签/实例表单全部由声明渲染（`InstanceDialog` 按 params_schema 生成表单项）
- 类型命名：`StrategyDefinition` / `StrategyInstance` / `StrategySignalRow`，与 screener 的 `Strategy`（买卖点过滤器）明确分离；mock 层为策略信号独立建 `mock/handlers/strategy.ts`
- 复用：股票搜索 autocomplete、行业 badges、价格联动抽屉骨架（从 bsp/monitor 页抽取或就地复制，按现有代码重复度决策——项目内 BspView/MonitorView 已各自实现，第一版就地复制保持变更隔离）
- MSW mock 首版覆盖：2 个策略定义 × 各 1-2 实例 × 状态各若干信号，驱动页面开发

### D6. monitor source 改造（最小侵入）

```
monitor 表 ALTER:
  source_type   VARCHAR NOT NULL DEFAULT 'chan'
  instance_id   INT NULL REFERENCES strategy_instance(id)
  signal_date   DATE NULL
```

- `_fill_bsp_context` 分叉：strategy 来源按 (instance_id, signal_date) 直查 strategy_signal（一次 JOIN，替代逐行 bsp_index 回查的那段），返回 state/is_buy/entry_ref_price 填充 bsp_type/direction/bsp_price 语义字段；查不到兜底（同现状兜底策略）
- `POST /api/monitor` body 增加 source_type/instance_id/signal_date 可选字段，缺省 'chan'（前端 /bsp 与 monitor 现有调用不传，行为不变）
- 卖点自动卖出结算：strategy 来源条目没有「卖点」概念，第一版不触发自动卖出（只对 chan 来源维持现状），监控结束仍手动/按现有逻辑
- 备选：统一 signal 事件表（chan 与 strategy 都写入再由 monitor 引用）。否决：bsp_index 已是缠论信号的存储事实，再引一张统一信号表需要迁移写入方，违反「不动缠论链路」约定

### D7. 预警/绩效契约预留（不实现）

- alerts 规则 body 预留 `source_type` + `instance_id` 字段（stub 接受不报错）
- performance API 查询参数预留 `source`/`instance_id`（stub 返回空集）
- 仅在类型/OpenAPI 注释层面落地，无行为

### D8. 状态冻结与生命周期隔离的落地机制

- 「加监控」成功 → 置 strategy_signal.frozen=TRUE（与 monitor 创建同一事务）
- 引擎 upsert：`ON CONFLICT ... DO UPDATE ... WHERE strategy_signal.frozen = FALSE`
- 监控结束/卖出结算不触碰 strategy_signal（现有代码路径本来就不知道这张表，天然满足，spec 场景作回归断言）

## Risks / Trade-offs

- [payload JSONB 无法强类型约束] → 引擎写入前自校验；columns 声明里带 type，前端渲染容错
- [同日多信号策略未来需要] → 唯一键加 seq 的非破坏演进路径已在 D1 注明
- [策略引擎慢拖 EOD 窗口] → 全量回算仅建实例时一次；增量扫描按键分批（复用 BSP_CATCHUP_BATCH 思路）；实例可停用
- [monitor 表结构变更] → 纯加列带 DEFAULT，无数据迁移；回滚 = 前端不传 source 字段 + 新列留存无害
- [screener 的 Strategy 命名混淆] → 类型/文案/路由三重区分（D5），mock handlers 分文件
- [状态标签颜色冲突]（各策略自定义 states 可能撞色）→ states 声明带 color 字段，策略注册时自定，不做全局调色板约束

## Migration Plan

1. PG：新表 strategy/strategy_instance/strategy_signal/strategy_scan_cursor 惰性建表（IF NOT EXISTS，同 bsp_store 风格）；monitor ALTER 加列（带 DEFAULT 'chan'）
2. 后端：strategy_store + 引擎 + routers 注册；app.py EOD 追加策略扫描阶段（环境变量 `STRATEGY_SCAN_ENABLED` 开关，默认开）
3. 前端：新页面 + mock + 路由 + 权限项；monitor 页来源标签列
4. 回滚：关 STRATEGY_SCAN_ENABLED；前端路由隐藏；monitor 新列与 source 字段可忽略；strategy_* 表停用无害

## Open Questions

- 首板策略的量价参数具体默认值与状态集命名（triggered/expired/running 的中文文案）——引擎实现时定，不影响 schema
- 策略信号详情抽屉里 K 线标注的具体形态（复用 chan 覆盖层 or 简单标记）——前端实现阶段按 KLineChart overlay 能力决策
- 侧栏分组（group_name）第一版是否需要用户自定义排序——先固定 sort，后续变更
