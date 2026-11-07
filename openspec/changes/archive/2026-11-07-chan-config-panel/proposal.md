# Proposal

## Why

缠论的内核参数（买卖点判据、笔/线段/中枢算法、MACD 三参数）当前**没有任何业务入口**：
`WebAPI/chan_service._make_chan_config()` 与 `WebAPI/incremental_engine._make_chan_config()`
都硬编码为 `{"trigger_step": ..., "kl_data_check": False}`，两处注释明确写着「不得显式覆盖任何
bsp 参数，否则会静默压过 `bsp_preset` 档位」。要换口径只能改代码再跑全库重算（`文档/缠论配置参数.md`
§十四：「目前没有任何买卖点参数开放到业务配置。切档位只能改代码」）。

这不是缺一个按钮的问题。调参是缠论研究的主循环——换 `macd_algo`、收紧 `bsp1_new_extreme`、
把 `bsp1_new_extreme_mode` 从 `trend_start` 切到 `level`，每一项都要立刻在 K 线图上看到买卖点如何变化，
否则无法判断某个参数在本市场是改善还是恶化。当前链路每换一次口径的代价是：改代码 → 重启服务 →
全库重算（历史日志实测 171 个键 964 秒）→ 回看。这个循环太慢，导致参数事实上一律停在默认值。

同时，开放参数会直接踩到三个已存在的陷阱（本变更的实测结论，详见 design.md）：

1. `config_fingerprint.FINGERPRINT_KEYS` 只收 36 个买卖点键，**不含 `bi_*`/`seg_*`/`zs_*`/`macd`**。
   开结构参数却不同步扩展指纹，用户改完点「同步所有股票」，`recompute_stock` 会走快照续算，
   已确认前缀里的旧结构原样保留 —— 配置改了但输出没变，这是本项目记录在案的「最难排查的故障形态」。
2. `macd_algo` 的 13 个取值里有 6 个**当场崩溃**：`volumn`/`amount`/`volumn_avg`/`amount_avg`/
   `turnrate_avg` 在 `CSeg.cal_macd_metric` 没有分支（`Seg.py:278` 抛 `CChanException`），
   `rsi` 依赖 `klu.rsi` 而该字段仅在 `cal_rsi=True` 时被写入（`KLine_Unit.py:244`）。
   平铺选项 = 用户一选就 500。
3. 配置进 PG 会让 `/api/klines` 首次依赖 PG，与 `main.py:131-133` 记录的「纯 DuckDB 计算、
   不依赖 PG，不应因 PG 故障而失败」相冲突，需要显式降级策略。

## What Changes

- **新增持久化配置真源**：PG 单行表 `chan_config` 存 58 项缠论参数的全量快照 + 档位预设名 + 版本号。
  两个 `_make_chan_config()` 改为读该表，**用户配置作为第 3 层覆盖**（内核默认值 → `bsp_preset`
  预设 → 用户显式值），并把两处「此处不得覆盖 bsp 参数」的注释改写为新契约。配置全局单份，
  写入挂 `manage` 权限。
- **新增参数元数据接口**：后端下发每个参数的分类、控件类型、合法取值、默认值（**实时从
  `CChanConfig()` 实例反射读取**）、影响面与白话解释，前端不硬编码任何参数清单或默认值
  —— 进行中的 `chan-bsp1-strict-extreme` 正把 `macd_algo` 默认从 `peak` 改成 `full_area`，
  并给 `bsp1_new_extreme_mode` 增加 `level` 取值，前端写死必然漂移。
- **新增 K 线页配置抽屉**：顶栏「缠论参数」按钮打开右侧抽屉，按「改了什么」分类（买卖点判据 /
  证据阶梯标注 / 高级·结构），每项带问号悬浮白话解释。**草稿态**：抽屉内所有修改只改内存，
  点「保存」才落库并触发重算；关闭抽屉有未保存改动时二次确认。
- **保存后重算当前股票**：落库成功后重新 `GET /api/klines`（`/api/klines` 的
  `chan_stable_prefix` 缓存当前是死代码 —— `main.py:148` 拿到 `cached_hit` 后未使用，
  每次请求都全量重算，因此无需额外失效机制），同时后台对该股票调 `recompute_stock`
  刷新 PG 的 `bsp_index`，使买卖点页/策略信号/绩效与 K 线页同口径。
- **新增「同步所有股票」**：抽屉内独立按钮，对 DuckDB 内全部 73 个 (code, kl_type, autype) 键
  执行全量重写，后台任务 + 进度轮询。任务启动时快照配置版本，结束时比对，不一致标记为
  stale 提示重新同步。
- **扩展配置指纹**：`FINGERPRINT_KEYS` 之外增加结构段（`bi_conf`/`seg_conf`/`zs_conf`/`macd`），
  使结构参数变化同样触发强制全量重算。**BREAKING（数据）**：指纹口径变化导致全部存量快照
  指纹失配，首次同步必然全量重算全部 73 个键（历史日志 171 键 / 964s，73 键约 5~8 分钟）。
  这是一次性的，但必须提前告知。
- **`macd_algo` 取值收敛与自动兜底**：量能类 5 个取值不支持线段级别，保存时自动注入
  `macd_algo-seg` 回退并在 UI 明示「线段级别自动使用峰值算法」；选 `rsi` 时自动带
  `cal_rsi=True` 并把 `cal_rsi`/`rsi_cycle` 纳入指纹。**不静默改用户值**，只注入派生键。
- **PG 不可用时降级**：`chan_config_store.load()` 在 PG 不可达时返回内核默认配置并记 warning，
  保证 K 线页仍能出图（沿用现有的「失败开放」风格）。
- **不改动**：`CChan`/`CBiList`/`CSegListChan`/`CZSList`/`CBSPointList` 的任何计算逻辑；
  `bsp_index`/`chan_structure`/`chan_snapshot` 的表结构与整套替换写入语义。

## Capabilities

### New Capabilities

- `chan-config`: 缠论参数配置的真源与生效契约 —— 参数清单的分类与元数据、三层优先级
  （内核默认 → 档位预设 → 用户显式值）、保存前的构造期校验、配置指纹对结构参数的覆盖、
  保存与批量同步触发的重算、以及 PG 不可用时的降级。约束的是「配置如何被解释与生效」，
  不约束任何判据本身的语义（那是 `chan-bsp-standard` 等能力的事）。
- `chan-config-page`: K 线页参数配置抽屉的交互契约 —— 入口位置、分类分组与折叠、
  每项的白话解释、草稿态与保存语义、未保存改动的离开保护、当前股票重算的可见反馈、
  以及「同步所有股票」的触发与进度呈现。

### Modified Capabilities

- `bsp-index`: 「增量续算」与「日终买卖点索引」两条需求需要容纳持久化用户配置 ——
  索引内容不再只随 `bsp_preset` 档位变化，而是随用户配置变化；指纹校验的范围从买卖点参数
  扩展到结构性参数，否则结构参数改动会走续算、新旧结构混在同一份索引里。
- `chan-bsp-standard`: 「档位预设与旧行为回退」需要明确加入第三层 —— 持久化用户配置
  覆盖档位预设，且预设的默认值调整**不得**静默改写已保存的用户配置。

## Impact

- **新增代码**：
  - `WebAPI/chan_config_store.py` —— 惰性建表 `_ensure_tables()`（对齐 `bsp_store`/`system_store`
    风格）、`load()`/`save()`、进程内缓存 + 版本失效
  - `WebAPI/chan_config_schema.py` —— 参数元数据与白话解释（默认值从 `CChanConfig()` 反射）
  - `WebAPI/routers/chan_config.py` —— `GET /api/chan-config`、`GET /api/chan-config/schema`、
    `PUT /api/chan-config`（`require_manage`）、`POST /api/chan-config/sync`（`require_manage`）、
    `GET /api/chan-config/sync/status`
  - `Front/src/components/kline/ChanConfigDrawer.vue` + 行组件 + `Front/src/api/modules/chanConfig.ts`
  - `Front/src/stores/chanConfig.ts`（草稿态，对齐 `stores/chartConfig.ts` 的写法）
- **改动代码**：
  - `WebAPI/chan_service._make_chan_config()` —— 改读 `chan_config_store.load()`，
    注释改写为新契约；`_compute_chan` 签名不变
  - `WebAPI/incremental_engine._make_chan_config()` —— 同上；`recompute_stock` 的指纹校验
    自动受益
  - `WebAPI/config_fingerprint.py` —— `collect_config` 增加结构段
  - `WebAPI/app.py` —— 挂载新 router
  - `Front/src/views/kline/KLineView.vue` —— 顶栏按钮 + 抽屉挂载
  - `WebAPI/routers/bsp.py` —— 「同步所有股票」可选复用 `catch_up(force=True)`，
    或改为独立的按周期全量入口（design.md 裁定）
- **数据库（按项目 DDL 规范双轨）**：
  - `WebAPI/bsp_store` 之外新增 `chan_config_store._ensure_tables()`（惰性 DDL 才是契约）
  - `WebAPI/update-win.sql` 追加建表语句（Windows 机器上的变更），幂等 +
    执行时间注释；若在 macOS 上产生则写 `update-mac.sql`
- **文档同步**（`chan-strategy-doc-sync` 约定）：
  - `文档/缠论配置参数.md` §十四「目前没有任何买卖点参数开放到业务配置」整节作废，
    改写为「开放范围 / 优先级 / 生效方式 / 指纹范围」
  - `文档/缠论策略.md` 判据不变，但「切档位只能改代码」的表述需更新
- **数据影响**：`bsp_index` 与 `chan_snapshot` 全量重刷一次；`performance_store` 的
  按档位绩效基线需按配置版本重新建线，避免新旧口径混算
- **运行风险**：
  - 首次同步 73 键约 5~8 分钟，期间买卖点页数据处于中间态
  - 全局配置，一次保存影响所有用户的买卖点页、策略信号与绩效
  - `K_5M` 历史上出现过 pickle 递归溢出（`Log/recompute_chan_standard.log`），
    同步任务需具备单键失败不阻断其余键的能力
- **不计入本变更**：per-user 配置（`bsp_index` 无用户维度，per-user 会让同一买卖点在不同
  用户眼里成立性不同但落库只有一份）；`-buy`/`-sell`/`-seg` 分侧后缀配置的前端暴露
  （58 项 × 5 = 290 个输入框不现实，第一期只暴露买卖两侧共用的基础层）。

## 参数范围的精确口径

需求讨论中曾以「全量 68 项」表述，落地审计后实际可配集合为 **58 项**（56 无条件 + 2 条件），
差异如下（供验收对齐）：

| 来源（`文档/缠论配置参数.md`） | 项数 | 抽屉位置 |
|---|---|---|
| 买卖点判据（§A.2 剔除 T2/T3 阶梯 8 项） | 33 | 「买卖点判据」组 |
| T2·T3 阶梯（§A.2） | 8 | 「证据阶梯标注」组（只改标注） |
| 笔（§二） | 6 | 「高级 · 结构」折叠组 |
| 线段（§三） | 2 | 同上 |
| 中枢（§四） | 4 | 同上 |
| MACD 三子键（§七） | 3 | 同上 |
| RSI 周期/开关（§七） | 2 | 条件暴露：仅当 `macd_algo=rsi` 时显示 |
| 运行模式（§五） | 2 | 否 —— 由调用方决定，用户配置会破坏步进/批量语义 |
| 数据校验（§六） | 6 | 否 —— 不参与买卖点判定 |
| 其余指标（§七 绘图类） | 7 | 否 —— 不影响买卖点 |

合计上页面 **58 项** = 33 + 8 + 15（结构）+ 2（条件）。文档 §A.1 的分组合计为 71 项，
本表剔除运行模式 2、数据校验 6、绘图类指标 7 共 15 项，并把 `macd` 一项展开为
`macd.fast` / `macd.slow` / `macd.signal` 三个子键（净 +2）：
71 − 15 + 2 = 58。
