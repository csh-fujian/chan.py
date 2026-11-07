# Design

## Context

见 proposal.md - Why。以下是塑造本设计方案的现状与约束。

### 配置构造的两个入口（都必须改，否则会出现双口径）

```text
ChanAnalyse/ChanConfig.py  CChanConfig
        ^                  ^
        |                  |
WebAPI/chan_service.py:138    WebAPI/incremental_engine.py:127
_make_chan_config()          _make_chan_config()
{"trigger_step": False,      {"trigger_step": True,
 "kl_data_check": False}     "kl_data_check": False}
        |                            |
   /api/klines                  recompute_stock → bsp_index
   （K 线页）                    （买卖点页/策略/绩效）
```

两处都留有同一条注释：「此处不得显式覆盖任何 bsp 参数，否则会静默压过 `bsp_preset` 档位」。
这是本变更要改写的契约，而不是要违反它 —— 新契约把用户配置定义为第三层，档位预设仍是
第二层，两者不再互斥。

### `CChanConfig` 的三层解析机制（已存在，可直接复用）

`set_bsp_config()` 的展开顺序是：`para_dict` 硬编码默认 → `_BSP_PRESETS[preset]` 覆盖 →
`conf.get(key, 当前值)`。**用户显式 key 天然是第三层**，内核无需改动。

字符串值一律被转成带引号的字面量后走 `set()`（`setattr`，已于 2026-10-25 修复双重解释）。
断言与白名单校验（`_check_choice`、`bsp2_confirm_window ∈ {1,2}`、
`bsp2_time_axis_strong < weak`、`bsp3a_max_zs_cnt >= 1`、`max_bs2_rate <= 1`、
`bsp1_qjt_depth >= 1`）都在构造期触发 —— 实测 `CChanConfig({"bsp2_confirm_window": 3})`
直接抛 `CChanException`，`CChanConfig({"bsp3b_mode": "bogus"})` 同理。这是保存前校验的天然抓手。

### 配置指纹的现状（最大的陷阱）

`config_fingerprint.collect_config()` 只读 `conf.bs_point_conf`（含 `b_conf`/`s_conf` 差异）
与 `seg_bs_point_conf` 的两个键；`FINGERPRINT_KEYS` 是 36 个买卖点键的固定元组。
`bi_conf` / `seg_conf` / `zs_conf` / `macd_config` **完全不在范围内**。

而 `recompute_stock()` 的续算判定完全依赖指纹：

```python
fp = config_fingerprint(_make_chan_config())
if not force_full and cursor is not None \
        and get_snapshot_fingerprint(...) != fp:
    force_full = True
```

不扩展指纹，用户调 `bi_fx_check` 后点「同步所有股票」，73 个键全部走续算，
已确认前缀的旧结构原样保留 —— 配置改了但输出没变。

### `macd_algo` 的实测可用性（本设计的关键输入）

13 个取值逐个跑 `sz.000001` 日线（`Log` 中的历史日期无关，取当日 DuckDB 全量）：

| 取值 | 结果 | 原因 |
|---|---|---|
| `peak` / `area` / `full_area` / `diff` / `diff_peak` / `slope` / `amp` | 通过 | 笔与线段级别均有实现 |
| `volumn` / `amount` / `volumn_avg` / `amount_avg` / `turnrate_avg` | **崩溃** | `Seg.py:278` 的 `cal_macd_metric` 无分支，抛 `CChanException` |
| `rsi` | **崩溃** | `klu.rsi` 仅在 `cal_rsi=True` 时由指标模型写入（`KLine_Unit.py:244`） |

实测 `{"macd_algo": "volumn", "macd_algo-seg": "peak"}` 正常出 11 个买卖点 ——
后缀覆盖是一条现成的绕行通道。`{"macd_algo": "rsi", "cal_rsi": True}` 同样正常出 7 个。

### `/api/klines` 的缓存是死代码

`main.py:148` 取到 `cached_hit, cached_data` 后**从未使用**，紧接着无条件
`_compute_chan()` 全量重算。这带来两个后果：

- 好消息：保存配置后前端重新请求 `/api/klines` 就立即生效，后端不需要任何失效机制
- 代价：「保存后刷新当前股票」= 一次完整 CChan 计算（历史日志单只日线 7~26 秒）

### 重算量级

`Log/recompute_chan_standard.log` 实测：171 个键全量重刷 **964 秒**。
DuckDB 现有 73 个 (code, kl_type, autype) 键（K_DAY 41 / K_30M 8 / K_WEEK 7 / K_MON 7 /
K_5M 5 / K_60M 3 / K_15M 2），按比例约 5~8 分钟。必须异步 + 进度。

同日志中 `sh.600007 5m` 出现过 `RecursionError: maximum recursion depth exceeded while
pickling an object` —— 批量同步必须单键失败不阻断。

### 前端既有模式

- 抽屉：`views/bsp/NestingDrawer.vue`、`views/strategy/SignalDrawer.vue`（`el-drawer` rtl）
- 弹窗配置 + localStorage 版本化：`stores/chartConfig.ts` + `components/kline/MaConfigDialog.vue`
- 后台任务 + 进度轮询：`routers/stocks.py` 的 `_SYNC_RUNNING` 内存标志 + `sync_job` 表
- 权限守卫：`auth.require_manage` / `require_menu_system`
- 惰性建表：`bsp_store._ensure_tables()`（模块导入时执行，是真正的 schema 契约）

## Goals / Non-Goals

**Goals:**

- 用户配置成为唯一真源，两个计算入口共用同一次读取，K 线页与买卖点页口径不可能分叉
- 参数清单、默认值、合法取值全部由后端下发，内核默认值调整（如进行中的
  `chan-bsp1-strict-extreme` 把 `macd_algo` 默认改为 `full_area`）不需要改前端
- 保存前用内核自己的构造期校验拦截非法组合，不在前端复刻规则
- 结构参数改动能可靠地触发全量重算（指纹扩展）
- `macd_algo` 的 6 个崩溃取值可用，但不静默改写用户选定的值
- 批量同步有进度、可观察、单键失败不阻断、配置中途变更能被识别

**Non-Goals:**

- 不改 `CChan` / `CBiList` / `CSegListChan` / `CZSList` / `CBSPointList` 的计算逻辑
- 不修 `Seg.cal_macd_metric` 缺失的 5 个分支（那是内核补全，独立变更；
  本变更用后缀覆盖绕行）
- 不暴露 `-buy` / `-sell` / `-seg` 分侧后缀配置（第一期只做买卖两侧共用层）
- 不做 per-user 配置（`bsp_index` 无用户维度）
- 不暴露运行模式（`trigger_step` / `skip_step`）与数据校验参数
- 不改造 `/api/klines` 的死缓存（保持现状，避免扩大改动面）

## Decisions

### D1 · 配置存储：PG 单行表 + 进程内缓存

**选择**：新建 `chan_config` 表，主键固定为 `1`，列 `config JSONB` / `preset VARCHAR` /
`version BIGINT` / `updated_at TIMESTAMPTZ` / `updated_by VARCHAR`。惰性建表放在
`chan_config_store._ensure_tables()`（模块导入时执行），`update-win.sql` 只作变更记录。

**为什么不用 JSON 文件**：配置必须与 `bsp_index`/`chan_snapshot` 同库同事务语义，
否则「配置已保存但索引没重算」无法可靠判定。JSON 文件还会引入多进程（uvicorn 多 worker）
读写不一致问题。

**为什么用单行而非一行一参数**：指纹需要全量快照的稳定哈希；单行读一次即可，
避免 55 行查询与部分更新的中间态。

**进程内缓存**：`load()` 缓存 `(version, config_dict)`；每次读取前先 `SELECT version`
（单行主键查询，微秒级），版本变化才重读整行。避免每个 `/api/klines` 请求都反序列化
JSONB，同时保证多 worker 下配置一致。

**替代方案**：复用 `user_setting` 表（`qa_store` 已有）—— 该表按用户维度设计，
与「全局单份」冲突，放弃。

### D2 · 参数元数据：后端生成，默认值反射读取

**选择**：`chan_config_schema.py` 定义参数的结构化描述（标识、分类、控件类型、白话解释、
影响面），但**默认值与合法取值运行期从实例读取**：

```python
base = CChanConfig()                       # 内核默认
for key, meta in PARAM_META.items():
    current = getattr_effective(base, key)  # 反射取值
```

枚举型参数的合法取值从 `CPointConfig._check_choice` 的白名单元组按名反射
（避免复制一份），或在该模块维护一张显式映射并附单测断言与 `_check_choice`
调用点一致。

**为什么不在前端硬编码**：进行中的 `chan-bsp1-strict-extreme` 正在改 `macd_algo` 默认值
与给 `bsp1_new_extreme_mode` 加 `level` 取值。前端硬编码会在那次变更落地后立即显示错误的
默认值与缺失的选项 —— 而且没有任何报错，只是静默给出旧信息。

**替代方案**：由前端维护一份参数表 —— 放弃，理由同上。

### D3 · 优先级与快照语义

**选择**：保存时同时写入两份数据 ——

| 列 | 内容 | 用途 |
|---|---|---|
| `config` | 全量快照（58 项保存时的生效值） | 展示、审计、诊断「当时看到的是什么」 |
| `overrides` | **仅用户显式改过的键**（保存时与「预设展开结果」比较得出） | 生效语义的唯一来源 |

生效配置 = 内核默认 → `bsp_preset` 预设展开 → `overrides`。

**为什么需要 `overrides` 而不是只存全量**：spec `chan-bsp-standard` 要求
「用户切换档位且未对某判据保存过显式取值时，该判据取新档位预设给出的取值」。
若把全量快照当作生效值，每一次保存都会把所有参数固化成显式值，切档位后
**没有任何项会跟随预设** —— 档位机制形同虚设。只存 diff 又会让未配置项跟随内核默认漂移
（`macd_algo` 默认即将从 `peak` 改为 `full_area`）。

两者结合解决这对矛盾：`overrides` 决定「哪些项听用户的」，`config` 记录「用户当时看到的整套值」。
内核默认值调整时，只有不在 `overrides` 里的项会跟随 —— 这正是档位语义的正确行为。

**`overrides` 的判定方式**：前端在「恢复默认」与「保存」之间知道自己改过哪些控件，但这不够
可靠（用户可能改回原值）。由后端计算更稳：用 `CChanConfig({"bsp_preset": preset})` 得到
预设展开后的基线，与候选全量快照逐项比较，**取值不同的键即为 overrides**。
这样「改成和预设一样的值」不会被误记为 override，「改了又改回去」也会自然消失。

**实现补记（落地时的偏差与修正）**：`PUT` 实际接收的是**前端算好的 overrides**，
后端只做构造期校验。因此「基线从哪来」成了前端的事，而这里踩过两个坑：

1. 前端最初拿 `schema.params[].default` 当基线 —— 它是按**当前已保存配置**反射的，
   会漂移。用户改 A 项保存后 `default` 就等于 A 的新值，下次只改 B 项保存时 A 被判成
   「没改过」而踢出 overrides，**A 的改动静默丢失**。
2. 改用 `kernel_defaults`（内核出厂默认）后又出现反向问题：`legacy` 档会把
   `divergence_rate` / `min_zs_cnt` / `bsp1_trend` / `macd_algo` 等十余项展开成不同取值，
   拿内核默认当基线会把这些**预设带来的**取值误判成用户覆盖写死进 overrides，
   **档位切换从此不再跟随预设**。

最终方案：`GET /schema` 同时返回 `kernel_defaults` 与 `preset_baselines[档位]`，
前端 `computeOverrides()` / `resetToDefaults()` 一律取 `preset_baselines[当前档位]`
（缺失时退回 `kernel_defaults`）。这是 D3 语义在前端侧的正确落点。

**`version` 语义**：`version = version + 1` 用于跨进程缓存失效与「同步任务结果是否过期」判定。
`updated_at` / `updated_by` 记录审计信息。

**写入语义**：单行 upsert，`ON CONFLICT (id) DO UPDATE`。

### D4 · 保存前校验：调用内核构造，不复刻规则

**选择**：`PUT /api/chan-config` 收到候选配置后先执行
`CChanConfig(候选)`，捕获 `CChanException` 与 `AssertionError` → 返回 422，
`detail` 携带内核异常原文。

**为什么**：内核的校验分布在 `CPointConfig.__init__`（6 处断言 + 4 处 `_check_choice`）、
`CBiConfig`、`CSegConfig`、`CZSConfig`、`CChanConfig.set_bsp_config`。
在前端或后端各复刻一遍必然与内核漂移，而漂移的表现是「前端放行、后端计算时崩」
或「前端拦住、后端其实允许」。

**例外处理**：`bs_type` 的合法性由 `parse_target_type()` 的 `assert` 检查，
该断言在**计算时**才执行（不在构造期）。所以保存校验需额外显式调用一次
`conf.bs_point_conf.b_conf.parse_target_type()` 把这类延迟校验前移。

**错误定位**：内核异常消息已包含参数名与合法取值（实测
`bsp3b_mode='bogus' 非法，可选值：standard, legacy`），直接透传即可；
对不含参数名的断言（`max_bs2_rate <= 1` 之类）由 `chan_config_schema` 提供
「参数 → 人类可读约束描述」映射做补充说明。

**形态规整（落地时补充）**：内核有两类「构造期放行、计算期才崩」的取值，必须在
校验前处理掉，否则脏值会入库、在重算时才炸：

| 输入形态 | 内核构造 | 计算期 | 处理 |
|---|---|---|---|
| `divergence_rate="inf"`（字符串） | 通过 | `"inf" <= 100` → `TypeError` | 校验前 `_decode_value()` 还原为 `float("inf")` |
| `divergence_rate=None` | 通过 | `None <= 100` → `TypeError` | 直接 422 拒绝（前端旧版把 `Infinity` `JSON.stringify` 成 `null` 就是这么来的） |
| `max_bsp2s_lv=None` | 通过 | `is not None` 守卫，安全 | 放行 —— 内核默认就是 `None`，语义是「不限制」 |

「哪些项允许 `None`」由 `_nullable_keys()` 反射内核默认为 `None` 的参数得出，不硬编码。

### D5 · 指纹扩展：结构化分段

**选择**：把 `collect_config()` 从「只收 bsp 键」改为分段收集：

```text
{"bsp": {...36 个原有键...},
 "seg_bsp": {...},
 "bi":  {...bi_conf...},
 "seg": {...seg_conf...},
 "zs":  {...zs_conf...},
 "macd": {...macd 三参数...},
 "indicator": {...仅当 macd_algo=rsi 时含 cal_rsi/rsi_cycle...}}
```

**实现要点**：`bi_conf` 等对象含枚举成员（`FX_CHECK_METHOD` 等），`_normalize()` 已处理
`hasattr(name)` 的枚举分支，可直接复用。`need_combine`/`is_strict`/`left_method`
的属性名与配置 key 不同（`zs_combine`/`bi_strict`/`left_seg_method`），按属性名取值即可
—— 指纹只要求稳定，不要求 key 与配置字典同形。

**`indicator` 段仅在 `macd_algo=rsi` 时收录**：`cal_rsi` 在其它算法下不影响任何输出，
无条件收录会让「为了方便在别处看 RSI 而打开它」这种无害改动触发全量重算（5~8 分钟）。

**点号键的桥接**（实现期新增）：元数据用 `macd.fast` / `macd.slow` / `macd.signal`
表达嵌套项，内核 `CChanConfig` 要的是 `{"macd": {"fast": ...}}`。规则是：

- 数据库与元数据统一用**点号形式**（与前端收发同一命名空间，前端零转换）
- `chan_config_store.build_conf()` 是唯一转换点（`to_kernel()`），指纹与计算都从这里出
- `to_flat()` 供读取时反向还原（API 返回给前端）

这样「存的形式」与「算的形式」只在 `build_conf()` 一处交汇，不会出现偏差。

**BREAKING（数据）**：指纹口径变化使 73 个存量快照全部失配，首次重算必然全量。
这与 `LADDER_SCHEMA_VERSION` bump 是同类机制，无需额外迁移脚本。

**替代方案**：给结构参数单独一个「结构指纹」列 —— 增加一列与一次迁移，收益仅仅是
能区分「哪类参数变了」。当前没有按类分级的重算需求，放弃。

### D6 · `macd_algo` 的 6 个崩溃取值：派生键绕行

**选择**：`chan_config_store` 在 `load()` 返回配置时，按 `macd_algo` 的取值自动补充派生键：

| 条件 | 派生 |
|---|---|
| `macd_algo ∈ {volumn, amount, volumn_avg, amount_avg, turnrate_avg}` | `macd_algo-seg` = 已有的 `macd_algo-seg`（若有）否则 `peak` |
| `macd_algo == "rsi"` | `cal_rsi = True`（用户显式关也一样） |

**为什么用后缀覆盖而不是改内核**：`macd_algo-seg` 是内核已支持的现有机制；
补全 `Seg.cal_macd_metric` 的 5 个分支是等价于「让线段级别也支持量能背驰」的语义决策，
需要单独验证其对买卖点的影响，不适合塞进本变更。

**为什么不把量能类从选项里删掉**：笔级别的量能背驰是有效判据（`CBi` 支持），
删掉会损失能力。而且 `bsp1_force_scope="bi"` 场景下线段级别本来就退回单笔口径。

**必须显式告知**：`chan_config_schema` 为这 6 个取值各写一条附加说明，
抽屉里在参数下方常驻显示（不只放问号里），因为这是「你选的半生效」的事实。

**注意派生键与指纹的交互**：派生键在 `load()` 输出中，而 `config_fingerprint` 在
`_make_chan_config()` 之后计算 —— 只要派生发生在 `load()` 内、
`_make_chan_config()` 消费 `load()` 的输出，指纹自然包含派生结果。这一点在实现时
必须保持单一出口，避免出现「一个入口带派生、一个入口不带」。

### D7 · 保存后的重算：两段式，先后台不阻塞

**选择**：`PUT /api/chan-config` 成功返回后，前端：

1. 立即 `GET /api/klines` 重拉图表（后端无缓存，配置已生效，结果即为新口径）
2. 并行 `POST /api/chan-config/recompute?code=X&period=Y` 触发该股票 PG 索引重算
   （后台任务，返回 job 标识）

**为什么两段而非一个同步接口**：`/api/klines` 是秒级反馈（单只计算 7~26 秒，
前端已有 `loading` 态承接）；PG 重算同样 7~26 秒，若串在保存请求里会让保存按钮卡住
半分钟，且用户此时已经看到了新图，没有等它的理由。

**为什么不用现有的 `catch_up(force=True)`**：`catch_up` 面向「全部键」，
单只重算现有 `recompute_stock(code, period, autype, force_full=False)` 更直接。
`force_full` 传 `False` 即可 —— 指纹已变，`recompute_stock` 内部会自动转全量。

### D8 · 批量同步：复用 `catch_up(force=True)`，独立进度通道

**选择**：`POST /api/chan-config/sync` 调用
`catch_up(None, None, None, limit=0, force=True)`，在 `asyncio.to_thread` 中执行，
`_SYNC_RUNNING` 式内存标志防重入，配置 `version` 在启动时快照。

**为什么不复用 `sync_job` 表**：`sync_job` 的 `domains` 语义是股票元数据域
（`meta_sync.DOMAIN_ORDER`），买卖点重算与它无关，混用会污染状态查询。

**进度来源**：`catch_up` 目前只在结束时返回汇总，无中间进度。两个选择：

- **A**（推荐）：新建轻量 `chan_config_sync_job` 表（`id` / `config_version` /
  `status` / `total` / `done` / `failed` / `summary JSONB` / `started_at` / `finished_at`），
  `catch_up` 增加可选回调参数逐键推进 `done`
- **B**：给 `catch_up` 加 `progress_cb` 参数但不落表，进度只在进程内存里

选 A：进程重启后进度仍可查（与 `sync_job` 的既有设计取向一致），且能记录
「结果是否已过期」所需的 `config_version`。B 在重启后状态全丢，而批量同步本身要跑 5~8 分钟。

**结果过期判定**：任务结束时比较 `snapshot_version` 与当前 `chan_config.version`，
不一致则 `summary.stale = true`。

**单键失败不阻断**：`catch_up` 现有实现已 `try/except` 逐键收集 `failed`，直接复用。

### D9 · 前端草稿态：Pinia store + 抽屉本地副本

**选择**：`stores/chanConfig.ts` 维护三份状态：

```text
saved    : 来自 GET /api/chan-config 的已保存配置
schema   : 来自 GET /api/chan-config/schema 的元数据
draft    : 抽屉打开时从 saved 深拷贝，抽屉内所有编辑只改 draft
```

`dirtyCount = diff(draft, saved)` 的变更项数。

**为什么不用 localStorage 暂存草稿**：配置是全局的、服务端权威的，
本地暂存的草稿在多用户场景下会误导（管理员改了配置，另一个人的旧草稿看起来仍「未保存」）。
关闭抽屉即丢弃，符合「草稿」语义。

**离开保护**：`el-drawer` 的 `before-close` 钩子 + 路由 `onBeforeRouteLeave` / 
`window.beforeunload`。K 线页被 KeepAlive 缓存，还需要处理 `onDeactivated`。

**替代方案**：用 `el-form` + `v-model` 双向绑定 —— 仍需要独立的 draft 对象才能实现
「取消即丢弃」，不如显式分层清晰。

### D10 · 参数分类的三组划分依据

**选择**：

| 组 | 判据 | 内容 |
|---|---|---|
| 买卖点判据 | 改变 `is_target_bsp` 或买卖点集合 | 通用 8 + 跟随 4 + 一买 11 + 二买/类二 5 + 三买 5 = 33 |
| 证据标注 | 只写 `ladder`/feature，不改成立性 | T2 阶梯 4 + T3 阶梯 4 = 8 |
| 高级 · 结构 | 改变笔/线段/中枢数量，进而间接改变全部买卖点 | 笔 6 + 线段 2 + 中枢 4 + MACD 3 = 15，另有 2 个条件项（`cal_rsi`/`rsi_cycle`） |

合计 58（56 无条件 + 2 条件项：`cal_rsi`/`rsi_cycle` 仅 `macd_algo=rsi` 时出现）。

**为什么这样分而不是按模块分（笔/线段/中枢/买卖点）**：新手不知道「中枢配置」会怎么影响
他看到的买卖点。按「改了什么后果」分，用户能判断「我能不能调这个」。

**「证据标注」组必须与「判据」组在视觉上明显区隔**，否则用户会以为调了会变。
本组内每个参数的解释都必须写明「不会增减任何买卖点」。

### D11 · 白话解释的组织

**选择**：`chan_config_schema.py` 的每条元数据带三个字段：

- `plain`：一句话说明这是什么（不含缠论术语）
- `effect`：调大/调小/切换取值分别会发生什么（面向可观察结果）
- `scope`：影响哪些买卖点类型或结构

**写作纪律**（作为任务验收项）：

1. 术语只能出现在括号补充里，不作为解释主体
2. 必须写出「调大 → 更多/更少」这样的方向性结论
3. 只影响标注的参数必须写「不改变买卖点数量」
4. 结构类参数必须写「会改变笔/中枢数量」

### D12 · PG 不可用时的降级

**选择**：`chan_config_store.load()` 捕获连接异常 → 返回
`CChanConfig({"trigger_step": ..., "kl_data_check": False})`（即当前硬编码的行为）
并 `log.warning`。保存路径则直接抛 503，不降级。

**为什么读降级、写不降级**：`main.py:131-133` 已确立「`/api/klines` 纯 DuckDB，
不应因 PG 故障失败」的取向 —— 本变更打破了这个纯粹性，必须给出等价保障。
写路径没有降级的合理语义：内存里记一份会与下次读取打架。

**副作用**：PG 故障期间 K 线页与买卖点页口径不同（前者默认档、后者是快照里的旧配置）。
在 warning 日志里明确写出这一点，并在抽屉打开时提示「配置服务不可用，当前展示为内核默认」。

## Risks / Trade-offs

**[首次同步 73 键必然全量，约 5~8 分钟]** → 指纹口径变化使存量快照全部失配，这是
一次性代价。drawer 的批量同步界面明确显示预计耗时与进度；文档记录这是预期行为而非故障。

**[`K_5M` 历史上有 pickle 递归溢出]** → `catch_up` 已逐键 `try/except`，
失败项进 `failed` 列表并在 UI 展示；不因单只失败中止整批。

**[全局配置，一次保存影响所有用户]** → 写入挂 `require_manage`；抽屉内保存按钮
对有管理权限的用户才启用，其余用户只读；保存确认对话框写明「本次修改会影响所有用户的
买卖点与策略信号」。

**[批量同步期间买卖点页数据处于中间态]** → 逐键整套替换，每个键内部是事务的，
不存在单个键的中间态；跨键的不一致窗口由进度提示承接。若下游对一致性有硬要求，
可在同步期间隐藏买卖点页的刷新按钮（不做，第一期只做提示）。

**[PG 故障期间 K 线页与买卖点页口径不一致]** → 见 D12，warning 日志 + 抽屉提示；
这是「失败开放」的既有取向的必然代价。

**[派生键（`macd_algo-seg` / `cal_rsi`）与指纹的耦合]** → 若某个入口绕过
`chan_config_store.load()` 直接构造配置，指纹与实际计算会不一致。
→ 缓解：两个 `_make_chan_config()` 是唯一出口；新增单测断言「从 `load()` 输出构造的
配置对象，其指纹与直接对该对象计算的指纹一致」。

**[`bs_type` 的延迟断言]** → `parse_target_type()` 在计算期才 assert，
保存校验必须显式调用（D4）。若遗漏，用户能保存非法 `bs_type`，症状是计算时才崩。
→ 任务里作为独立的验收项。

**[抽屉内 58 项参数的信息密度]** → 单个抽屉滚动浏览 58 项容易迷失。
→ 三组折叠 + 组内二级分类标题 + 吸顶的「已修改 N 项」状态条。
若实测仍难用，可退化为一期只展示买卖点 33 项，结构组整体折叠但可展开（已是本设计形态）。

**[删除 `chan_stable_prefix` 死缓存的分歧]** → 本设计不动它（Non-Goal）。
但它意味着每次 `/api/klines` 都全量计算，保存配置后的「刷新」开销不可优化。
→ 记录为后续独立变更（让死缓存真正生效）的输入。

## Migration Plan

**部署顺序**（顺序不可颠倒）：

1. 后端先上：`chan_config_store` / `chan_config_schema` / router / 两个
   `_make_chan_config()` 改造 / 指纹扩展
2. 首次启动时 `chan_config` 表为空 → `load()` 返回内核默认配置并记录
   「未初始化」→ 行为与改造前完全一致（向后兼容）
3. 管理员打开抽屉点保存 → 写入首份配置 → 指纹变化 → 该股票与后续同步走全量
4. 管理员点「同步所有股票」→ 73 键全量重刷（一次性 5~8 分钟）
5. 前端最后上：抽屉与按钮（后端已就绪，前端上线即用）

**回滚策略**：

- **只回滚前端**：后端保留配置读取能力，但无人修改配置 → 行为等同部署前
- **回滚后端**：`_make_chan_config()` 恢复硬编码 → 配置表留存但不再被读取 →
  行为回到改造前；需注意此时指纹已按新口径写入快照，回滚后指纹再次失配，
  会触发一次全量重算（代价可接受，但需预告）
- **数据回滚**：`bsp_index` 按旧配置重刷即可收敛（`catch_up(force=True)` 幂等）；
  `chan_config` 表可直接 `UPDATE config = <旧快照>` 并 bump `version`

**数据迁移**：无需数据迁移。指纹变化由 `recompute_stock` 的指纹校验自然触发全量，
与 `LADDER_SCHEMA_VERSION` bump 的既有机制一致。

## Open Questions

- 批量同步的预计耗时是否需要在界面上动态估算（按已完成键的实际速率外推）？
  可先做固定文案，视实测观感再决定。
- 抽屉是否需要「导出/导入配置 JSON」以便在不同环境间搬运口径？当前不做，
  但 `chan_config_schema` 的结构化元数据让该功能后续接入成本很低。
