# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

chan.py 是缠论（Chan Theory）技术分析的 Python 实现，用于从 K 线数据计算分形、笔、线段、中枢、买卖点。这是**开源版**（约 5300 行），完整版（约 22000 行）的策略、交易引擎、ML/AutoML 模块未包含在本仓库中。

- 作者: Vespa314, MIT 协议
- 要求 **Python >= 3.11**
- 文档: `Document/README.md`（~1500 行中文，主要参考文档）、`Document/quick_guide.md`、`Document/ONBOARDING.md`（知识图谱自动生成的入职指南）、`Document/阅读文档.md`、`Document/代码走读说明.md`

仓库同时包含两个在开源计算内核上新增的子系统（均在缠论核心之外，不改动 `CChan` 计算逻辑）：

- **K 线持久化**：原始 K 线落本地 DuckDB 单文件（`Data/kl_store.duckdb`），计算阶段完全离线；配套灌数 / 盘中轮询脚本。
- **Web 前端**：`Front/` 是 Vue3 + Vite + TS 的缠论量化终端前端（11 个页面），当前由 MSW mock 数据驱动，真实后端（FastAPI + PostgreSQL）尚未落地。

## 常用命令

```bash
# 安装依赖（用项目自带 venv）
.venv/bin/pip install -r Script/requirements.txt

# 运行主演示（计算 sz.000001 日线缠论并绘图，默认走 BaoStock 网络源）
python main.py

# 策略回测演示（手动冒烟测试）
python Debug/strategy_demo.py     # step-playback 回测
python Debug/strategy_demo2.py    # 外部推送回测
python Debug/strategy_demo3.py    # 小级别触发大级别重算
python Debug/strategy_demo4.py    # 多级别无时间对齐推送
python Debug/strategy_demo5.py    # ML 特征生成 + XGBoost 训练
python Debug/strategy_demo6.py    # 模型预测

# GUI 扫描器（需要 akshare + PyQt6）
python App/ashare_bsp_scanner_gui.py
```

### K 线持久化 / 灌数（DuckDB）

```bash
# 枚举全部 A 股，生成批量灌数配置（需能访问 BaoStock）
PYTHONPATH=. python Data/gen_stock_list.py --limit 20        # 调试：前 20 只

# 灌数：拉取 → 校验 → 幂等写入 Data/kl_store.duckdb
python Data/download_kl.py --code sz.000001 --kl-type K_DAY --autype QFQ
python Data/download_kl.py --code sz.000001 --kl-type K_DAY --autype QFQ --full      # 全量重刷
python Data/download_kl.py --code sz.000001 --kl-type K_DAY --autype QFQ --begin 2024-01-01 --end 2024-06-30
python Data/download_kl.py --config Data/ingest_config.all_stocks.json               # 批量

# 盘中分钟级轮询（落库 + 推进 PG 重算游标 + 通知重算）
python Data/intraday_poll.py --config Data/ingest_config.minute.json --pg-dsn "host=... dbname=..." --once
```

### 手动测试脚本（无 pytest，`Debug/*_test*.py` 充当冒烟测试）

```bash
.venv/bin/python Debug/bi_test.py                    # 笔识别，内存构造 K 线，无需联网
.venv/bin/python Debug/test_e2e_duckdb.py            # DuckDB 离线 round-trip + 数据源可互换（无需联网）
.venv/bin/python Debug/test_baostock_vs_duckdb.py    # 真网络端到端（需访问 BaoStock）
.venv/bin/python Debug/test_intraday_poll.py         # 盘中轮询逻辑
```

### 前端（`Front/`）

```bash
cd Front
npm install          # 安装依赖
npm run dev          # 开发服务器 http://localhost:5173
npm run build        # vue-tsc -b && vite build
npm run preview      # 预览生产包
```

前端默认 `VITE_USE_MOCK=true`（`.env`），由 MSW 在 Service Worker 层拦截 `/api/*`，不依赖后端。测试账号：`admin/admin123`（管理员）、`trader/trader123`（交易员）、`viewer/viewer123`（观察者）。

## 核心架构

### 计算流水线

```
CChan (ChanAnalyse/Chan.py)  ← 门面，接收 stock code + CChanConfig
  │
  ├─ ChanAnalyse/DataAPI/  ← 数据源适配器（BaoStock/Akshare/CCXT/CSV/DuckDB/Minute/custom）
  │   └─ 自定义数据源: 传入 "custom:ModuleName.ClassName" 字符串
  │
  ├─ load_iterator()  ← 递归加载多级别 K 线，建立父子关系
  │   │
  │   ├─ CKLine_Combiner  ← K 线包含处理/合并
  │   ├─ CBiList          ← 分形检测 → 笔的构建
  │   ├─ (step mode)      ← trigger_step=True 时，每根 K 线都会重算段/中枢/买卖点
  │   │
  │   └─ cal_seg_and_zs() ← 最终化：段、中枢、买卖点
  │       ├─ CSegListChan  ← 默认段算法（特征序列分形）
  │       ├─ CZSList       ← 中枢构建与合并
  │       └─ CBSPointList  ← 买卖点（T1/T1P/T2/T2S/T3A/T3B）
  │
  └─ 结果访问: chan[KL_TYPE].bi_list / .seg_list / .zs_list / .bs_point_lst
```

### 多级别递归

`CChan.load_iterator` 从最高级别向最低级别递归，每个父 K 线通过 `set_klu_parent_relation` 连接到子 K 线，支持区间套策略（在父 K 线下查看子级别买卖点）。

### 两种运行模式

- **批量模式** (`trigger_step=False`): 加载全部数据后一次性计算所有元素
- **步进模式** (`trigger_step=True`): `CChan` 变为生成器，每根新 K 线产生一个快照，用于回测和动画播放。`trigger_load(inp)` 往已加载实例追加新 K 线，`cal_seg_and_zs` 用 `last_sure_seg_start_bi_idx` 等游标只重算未确认尾部——这是增量续算的基底。

### 配置系统

`CChanConfig` 接受字典，组成子配置（`CBiConfig`, `CSegConfig`, `CZSConfig`, `CBSPointConfig`）。`ConfigWithCheck` 包装器会消费 key 并在遇到未知 key 时抛出异常——严格的配置校验。支持通过 `-buy`/`-sell`/`-seg` 后缀实现按买卖点类型的参数覆盖。

## 数据源与持久化（DuckDB）

仓库的 K 线数据分层（来自 openspec 变更 `persist-kl-to-duckdb`，已归档）：

- **原始 K 线 → DuckDB 单文件** `Data/kl_store.duckdb`（`ChanAnalyse/DataAPI/KLineStore.py`）：表 `kline`，主键 `(code, kl_type, autype, time_key)`；`kl_type`/`autype` 存枚举 `.name` 字符串（如 `"K_DAY"`/`"QFQ"`）；`time_key` 存无时区北京时间字符串 `"YYYY-MM-DD HH:MM:SS"`（避免 DuckDB TIMESTAMP 隐式时区问题）。幂等写入 `INSERT OR REPLACE`。
- **已是最新就不请求接口**：增量灌数先按交易日历推算「此刻本应存在的最新 K 线」（`IngestUtil.expected_latest_time_key`，日线按收盘+`bar_lag_minutes` 判定可见、周/月线只认已走完的周/月、分钟级按 bar 边界递推），水位已覆盖则整条任务跳过、连 BaoStock 登录都不做（重复请求同段数据会触发限频）。`--force` 强制请求，`--begin/--end` 显式区间亦不跳过，日历不可用时失败开放（照常请求）。
- **离线回读 → `ChanAnalyse/DataAPI/DuckDBAPI.py`** 的 `CDuckDB`（继承 `CCommonStockApi`），接入方式 `data_src = "custom:DuckDBAPI.CDuckDB"`，逐根 yield `CKLine_Unit`，使计算流水线对数据来源无感知。
- **分钟级盘中 → `ChanAnalyse/DataAPI/MinuteAPI.py`** 的 `CMinute`（akshare 东财 `stock_zh_a_hist_min_em`），经 `custom:MinuteAPI.CMinute` 接入。
- **操作态 → PostgreSQL**：`ChanAnalyse/DataAPI/RecomputeCursor.py` 把「已处理时间」游标 `recompute_cursor` 表存 PG（psycopg2 裸 SQL），避免与灌数进程抢 DuckDB 单写锁。

灌数/盘中脚本共享 `ChanAnalyse/DataAPI/IngestUtil.py`（`CKLine_Unit` ↔ DataFrame 行转换、交易日历 `exchange_calendars`、缺口/跳变校验）。

## 关键实现细节

### 缓存机制 (`ChanAnalyse/Common/cache.py`)

`@make_cache` 装饰器将缓存绑定到实例的 `self._memoize_cache` 上（区别于 `functools.lru_cache`）。`CBi` 和 `CKLine_Combiner` 大量使用它来缓存昂贵的派生属性。当底层状态变更时调用 `clean_cache()` 使缓存失效。

### 序列化陷阱 (`ChanAnalyse/Chan.py`)

`CChan.__deepcopy__` 手动重建跨级别的 `sup_kl`/`sub_kl_list` 指针图。`chan_dump_pickle`/`chan_load_pickle` 在 pickle 前临时移除 `pre`/`next` 链表指针（并调整 `sys.setrecursionlimit`），以避免 pickle 递归溢出，之后恢复。

### 段算法

三种段算法，均继承 `CSegListComm`：
- `chan`（默认，`SegListChan.py`）：特征序列分形
- `1+1`（`SegListDYH.py`，已弃用）：都业华版
- `break`（`SegListDef.py`，已弃用）：定义版

`CSegListComm` 包含未确认段（虚段）的复杂处理逻辑。

### 绘图

- `CPlotDriver`：matplotlib 静态渲染，输出 PNG
- `CAnimateDriver`：步进回放动画，支持 Jupyter Notebook 内嵌

### 指标

所有技术指标均为手写实现（MACD, BOLL, RSI, KDJ, DeMark, TrendLine），不依赖 talib。

### 数据库 DDL 变更规范（WebAPI/update-mac.sql / update-win.sql）

代码对数据库表做 DDL 变更时（建表、加列、加索引、加约束等），或变更**数据库初始化数据**时（枚举或字典，如 `strategy` 定义行、`permission` 权限项、`role` 角色项），必须按**发生变更的机器**在对应文件追加 SQL：

- 在 **macOS** 上运行期间产生的变更 → `WebAPI/update-mac.sql`
- 在 **Windows** 上运行期间产生的变更 → `WebAPI/update-win.sql`

（原先的 `WebAPI/update.sql` 已废弃并删除。）

- 每次追加需在语句前注释**执行时间**（如 `-- 2026-10-04 xxx 表加列`）。
- 所有 SQL 必须幂等，可重复执行：建表用 `CREATE TABLE IF NOT EXISTS`，加列/加索引/加约束用 `IF NOT EXISTS` 或先查 `information_schema`/`pg_attribute` 再执行的 DO 块判断，字典数据用 `ON CONFLICT ... DO NOTHING`/`DO UPDATE`，禁止裸 `CREATE/ALTER` 直接报错重跑。

> **惰性 DDL 才是真正的 schema 契约**：各 store 模块（`bsp_store` / `monitor_store` / `strategy_store` / `stock_store` / `watchlist_store` / `qa_store` / `llm_store`）在**模块导入时**执行 `_ensure_tables()`（`CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`），运行时自动补表补列。因此新增表/列时**必须先改对应模块的 `_ensure_tables()`**，两个 `update-*.sql` 只是变更记录。另注意 `WebAPI/init.sql` 已与实物漂移（如它为 `bsp_index`/`chan_structure`/`chan_snapshot` 声明了 `id`/`created_at`，而实际表由惰性 DDL 建成、没有这些列），**不要以 `init.sql` 判断实际表结构**。

## 缠论参数配置（`chan-config-panel`）

缠论参数已全部开放为业务配置，由 K 线页顶栏「缠论参数」按钮打开的抽屉维护（57 项：54 常驻 + 3 条件项；分组 判据 31 / 标注 8 / 结构 15）。

| 模块 | 职责 |
|------|------|
| `WebAPI/chan_config_store.py` | `chan_config` + `chan_config_sync_job` 惰性 DDL、读写（`load()` 带版本缓存）、派生键（`apply_derived()`）、档位回填（`load_preset()`/`_preset_injected()`）、构造期校验（`validate_config()`/`validate_preset()`）、点号键桥接（`to_kernel()`/`to_flat()`） |
| `WebAPI/chan_config_schema.py` | 57 项参数元数据（分组 / 控件 / 白话解释 / 默认值反射） |
| `WebAPI/routers/chan_config.py` | `GET/PUT /api/chan-config`、`GET /schema`、`POST /recompute`、`POST /sync`、`GET /sync/status` |
| `Front/src/components/kline/ChanConfigDrawer.vue` | 抽屉主体（草稿态 + 保存并重算 + 批量同步轮询） |
| `Front/src/stores/chanConfig.ts` | `saved`/`schema`/`draft` 三态 + `dirtyCount` |

- **单一出口**：`chan_service._make_chan_config()` 与 `incremental_engine._make_chan_config()` 都走 `chan_config_store.build_conf()`，各自只补 `trigger_step` / `kl_data_check`。此处**不得**再显式覆盖任何 bsp 参数。
- **三层优先级**：内核硬编码默认 → `bsp_preset` 展开 → 用户 overrides。
- **档位存在 `preset` 列，不在 `overrides` 里，必须由计算出口回填**：前端 `computeOverrides()` 拿 `bsp_preset` 与档位基线比对，相等就不写（它本来就不是「用户改过的项」），所以库里 `preset` 列是档位的唯一真源。`load()` 故意**不**返回 `bsp_preset`（保持 overrides 纯净），由 `build_conf()` / `effective_config()` 里的 `_preset_injected()` 用 `load_preset()` 补上。漏了这一步 `CChanConfig` 只会看到硬编码默认 `standard`，**切到 legacy 后一处判据都不跟着变**（实测：`min_zs_cnt` 仍 2、`divergence_rate` 仍 0.9）。同理 `routers/chan_config.py` 的 `_conf_from_meta()` 反射 `effective` / `params[].default` 时也要补档位，否则界面显示与图上计算不是一回事。
- **`GET /api/chan-config` 整份响应必须走 `store.encode_config()`**：legacy 档 `divergence_rate=inf`，裸返回会让 starlette 在 `json.dumps` 处抛 `Out of range float values are not JSON compliant: inf`（500）。`/schema` 早就这么做了，`/` 以前漏着，档位修好后立刻暴露。
- **`PUT` 的 `preset` 字段必须单独校验**：它绕过 `validate_config()`（那只校验 `overrides`），但现在真正进入计算链路 —— 非法档位名一旦落库，此后**每次** `CChanConfig(...)` 都抛 `unknown bsp_preset`，**全站 K 线请求 500**。`put_config()` 写入前调 `validate_preset()`，合法清单直接取内核 `_BSP_PRESETS`（不复制）。
- **三条基线别混用**（`GET /schema` 同时返回）：`params[].default` 是按当前已存配置反射的（会漂移，只能用于展示）；`kernel_defaults` 是出厂默认；**算 overrides 与「恢复默认」必须用 `preset_baselines[当前档位]`**。用 `params[].default` 会让已保存的覆盖项在下一次保存时静默丢失；用 `kernel_defaults` 会把 legacy 档预设展开的十余项误判成用户覆盖、写死进 overrides，使档位切换失效。
- **点号键桥接**：元数据/前端/DB 用 `macd.fast`，内核要 `{"macd": {"fast": ...}}`，只在 `to_kernel()`/`to_flat()` 转换。
- **派生键**：5 个量能类 `macd_algo` 自动补 `macd_algo-seg=peak`；`rsi` 自动补 `cal_rsi=True`。缺失会直接崩（`Seg.py` 抛 `unsupport macd_algo` / `klu.rsi` 属性不存在）。派生只在**计算出口**（`load()` / `effective_config()` / `build_conf()`）生成：`load_with_meta().overrides` 返回的是**用户显式改过的原始键**，不含派生键 —— 那不是用户配的，混进去会让 `GET → PUT` 往返把它当作用户覆盖回传。
- **`inf` 只能以字符串跨 JSON**：标准 JSON 不接受非有限浮点。前端勾「不限」发 `"inf"`，`validate_config()` 用 `_decode_value()` 还原成 `float("inf")` 再校验并返回，`save()` 落库时再 `_encode_value()` 转回 `"inf"`。`GET /schema` 整份响应也走 `encode_config()`——legacy 档的 `divergence_rate=inf` 会让裸 `json.dumps` 直接 500。**`None` 一律拒绝**（内核默认可空的 `max_bsp2s_lv` 除外，由 `_nullable_keys()` 反射判定）：`divergence_rate=None` 能通过构造，却在计算期 `None <= 100` 抛 `TypeError`。
- **`ConfigWithCheck.get()` 会 del 传进去的 dict** —— `validate_config()` 必须传副本，否则报错时字典已空、定不出哪个参数非法。
- **指纹已结构化**（`config_fingerprint.collect_config()` 分 `bsp`/`seg_bsp`/`bi`/`seg`/`zs`/`macd`/`indicator` 七段），结构参数改动也会强制全量重算。这是 BREAKING 变更，存量快照首次重算一律走全量。

## 前端（`Front/`）

Vue3 + Vite + TypeScript + Element Plus + ECharts + KLineChart + Pinia，暗色专业终端风格，A 股红涨绿跌。结构见 `Front/README.md`。

- K 线页（`views/kline/`）用 KLineChart 的 `registerOverlay` API 实现 4 个缠论覆盖层（`components/chan/`）：`chan_bi`（笔）、`chan_seg`（线段）、`chan_zs`（中枢）、`chan_bsp`（买卖点）。
- API 层 `src/api/` 按模块拆 axios client；`src/mock/` 是 MSW handlers + 数据；真实后端尚未实现，切真实后端只需 `VITE_USE_MOCK=false`。
- 设计令牌在 `src/styles/design.css`；红涨绿跌变量 `--rise: #F6465D` / `--fall: #2EBD85`。
- RBAC：`menu:*` 权限控制菜单显隐，`manage` 权限控制管理按钮，`v-permission` 指令（`directives/permission.ts`），admin 全权限。

## Spec-driven 开发（openspec）

仓库采用 openspec 的 spec-driven 流程（见 `openspec/`，命令/技能在 `.claude/commands/opsx/` 与 `.claude/skills/openspec-*`）。改动前先查 openspec 是否有进行中变更：

- **进行中**：`openspec/changes/chan-stock-manage/`（股票管理 Web 闭环：增量续算引擎 + 买卖点索引落 PG、自选/历史买卖点/监控三 Tab、行业多对多、买卖点绩效、选股器、区间套、预警、多用户 RBAC）；`openspec/changes/chan-web-viewer/`（Web 交互式 K 线可视化）。
- **已归档**：`openspec/changes/archive/2026-09-16-persist-kl-to-duckdb/`（DuckDB 持久化）。

这些变更都约定**不修改 `CChan`/`CBiList`/`CSegListChan`/`CZSList`/`CBSPointList` 的计算逻辑**，只复用其 `trigger_step` / `trigger_load` / pickle 能力，并以 DuckDB 存原始 K 线、PG 存缠论结论与业务元数据。规划中的后端 `WebAPI/`（FastAPI）尚未创建；前端目录实际落在 `Front/`（而非 proposal 里写的 `web/`）。

## 目录结构速查

| 目录 | 用途 |
|------|------|
| `ChanAnalyse/` | 缠论核心库（CChan 主入口 + 全部计算模块） |
| `ChanAnalyse/Chan.py` | 主入口类 `CChan` |
| `ChanAnalyse/ChanConfig.py` | 配置系统 `CChanConfig` |
| `ChanAnalyse/Common/` | 枚举、异常、缓存、工具函数 |
| `ChanAnalyse/KLine/` | K 线单元、合并 K 线、K 线列表容器 |
| `ChanAnalyse/Combiner/` | K 线包含处理/合并逻辑 |
| `ChanAnalyse/Bi/` | 笔的构建与管理 |
| `ChanAnalyse/Seg/` | 段算法（特征序列、虚段处理） |
| `ChanAnalyse/ZS/` | 中枢构建与合并 |
| `ChanAnalyse/BuySellPoint/` | 买卖点计算 |
| `ChanAnalyse/Math/` | 手写技术指标 |
| `ChanAnalyse/DataAPI/` | 数据源适配器（BaoStock/Akshare/CCXT/CSV/DuckDB/Minute）+ 持久化（KLineStore/IngestUtil/RecomputeCursor） |
| `ChanAnalyse/Plot/` | matplotlib 绘图 |
| `ChanAnalyse/ChanModel/` | ML 特征容器（开源版中不完整） |
| `WebAPI/` | FastAPI 后端（PG 缠论结论 + 业务元数据） |
| `Front/` | Vue3 前端（MSW mock 驱动，后端未落地） |
| `Data/` | 灌数脚本与配置（download_kl / intraday_poll / gen_stock_list / ingest_config.*.json）+ DuckDB 数据文件 |
| `Debug/` | 策略演示 / 手动测试脚本 |
| `App/` | GUI 扫描器 |
| `Document/` | 项目文档（README / quick_guide / 阅读文档 / 代码走读说明 / ONBOARDING / images） |
| `Log/` | 日志文件（ingest_*.log） |
| `Script/` | 脚本（requirements.txt / start_backend.sh） |
| `openspec/` | spec-driven 变更提案与规范 |
