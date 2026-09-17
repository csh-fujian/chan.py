# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

chan.py 是缠论（Chan Theory）技术分析的 Python 实现，用于从 K 线数据计算分形、笔、线段、中枢、买卖点。这是**开源版**（约 5300 行），完整版（约 22000 行）的策略、交易引擎、ML/AutoML 模块未包含在本仓库中。

- 作者: Vespa314, MIT 协议
- 要求 **Python >= 3.11**
- 文档: `README.md`（~1500 行中文，主要参考文档）、`quick_guide.md`、`docs/ONBOARDING.md`（知识图谱自动生成的入职指南）、`阅读文档.md`、`代码走读说明.md`

仓库同时包含两个在开源计算内核上新增的子系统（均在缠论核心之外，不改动 `CChan` 计算逻辑）：

- **K 线持久化**：原始 K 线落本地 DuckDB 单文件（`kl_store.duckdb`），计算阶段完全离线；配套灌数 / 盘中轮询脚本。
- **Web 前端**：`front/` 是 Vue3 + Vite + TS 的缠论量化终端前端（11 个页面），当前由 MSW mock 数据驱动，真实后端（FastAPI + PostgreSQL）尚未落地。

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
PYTHONPATH=. python Debug/gen_stock_list.py --limit 20        # 调试：前 20 只

# 灌数：拉取 → 校验 → 幂等写入 kl_store.duckdb
python Debug/download_kl.py --code sz.000001 --kl-type K_DAY --autype QFQ
python Debug/download_kl.py --code sz.000001 --kl-type K_DAY --autype QFQ --full      # 全量重刷
python Debug/download_kl.py --code sz.000001 --kl-type K_DAY --autype QFQ --begin 2024-01-01 --end 2024-06-30
python Debug/download_kl.py --config Debug/ingest_config.all_stocks.json               # 批量

# 盘中分钟级轮询（落库 + 推进 PG 重算游标 + 通知重算）
python Debug/intraday_poll.py --config Debug/ingest_config.minute.json --pg-dsn "host=... dbname=..." --once
```

### 手动测试脚本（无 pytest，`Debug/*_test*.py` 充当冒烟测试）

```bash
.venv/bin/python Debug/bi_test.py                    # 笔识别，内存构造 K 线，无需联网
.venv/bin/python Debug/test_e2e_duckdb.py            # DuckDB 离线 round-trip + 数据源可互换（无需联网）
.venv/bin/python Debug/test_baostock_vs_duckdb.py    # 真网络端到端（需访问 BaoStock）
.venv/bin/python Debug/test_intraday_poll.py         # 盘中轮询逻辑
```

### 前端（`front/`）

```bash
cd front
npm install          # 安装依赖
npm run dev          # 开发服务器 http://localhost:5173
npm run build        # vue-tsc -b && vite build
npm run preview      # 预览生产包
```

前端默认 `VITE_USE_MOCK=true`（`.env`），由 MSW 在 Service Worker 层拦截 `/api/*`，不依赖后端。测试账号：`admin/admin123`（管理员）、`trader/trader123`（交易员）、`viewer/viewer123`（观察者）。

## 核心架构

### 计算流水线

```
CChan (Chan.py)  ← 门面，接收 stock code + CChanConfig
  │
  ├─ DataAPI/  ← 数据源适配器（BaoStock/Akshare/CCXT/CSV/DuckDB/Minute/custom）
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

- **原始 K 线 → DuckDB 单文件** `kl_store.duckdb`（`DataAPI/KLineStore.py`）：表 `kline`，主键 `(code, kl_type, autype, time_key)`；`kl_type`/`autype` 存枚举 `.name` 字符串（如 `"K_DAY"`/`"QFQ"`）；`time_key` 存无时区北京时间字符串 `"YYYY-MM-DD HH:MM:SS"`（避免 DuckDB TIMESTAMP 隐式时区问题）。幂等写入 `INSERT OR REPLACE`。
- **离线回读 → `DataAPI/DuckDBAPI.py`** 的 `CDuckDB`（继承 `CCommonStockApi`），接入方式 `data_src = "custom:DuckDBAPI.CDuckDB"`，逐根 yield `CKLine_Unit`，使计算流水线对数据来源无感知。
- **分钟级盘中 → `DataAPI/MinuteAPI.py`** 的 `CMinute`（akshare 东财 `stock_zh_a_hist_min_em`），经 `custom:MinuteAPI.CMinute` 接入。
- **操作态 → PostgreSQL**：`DataAPI/RecomputeCursor.py` 把「已处理时间」游标 `recompute_cursor` 表存 PG（psycopg2 裸 SQL），避免与灌数进程抢 DuckDB 单写锁。

灌数/盘中脚本共享 `DataAPI/IngestUtil.py`（`CKLine_Unit` ↔ DataFrame 行转换、交易日历 `exchange_calendars`、缺口/跳变校验）。

## 关键实现细节

### 缓存机制 (`Common/cache.py`)

`@make_cache` 装饰器将缓存绑定到实例的 `self._memoize_cache` 上（区别于 `functools.lru_cache`）。`CBi` 和 `CKLine_Combiner` 大量使用它来缓存昂贵的派生属性。当底层状态变更时调用 `clean_cache()` 使缓存失效。

### 序列化陷阱 (`Chan.py`)

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

## 前端（`front/`）

Vue3 + Vite + TypeScript + Element Plus + ECharts + KLineChart + Pinia，暗色专业终端风格，A 股红涨绿跌。结构见 `front/README.md`。

- K 线页（`views/kline/`）用 KLineChart 的 `registerOverlay` API 实现 4 个缠论覆盖层（`components/chan/`）：`chan_bi`（笔）、`chan_seg`（线段）、`chan_zs`（中枢）、`chan_bsp`（买卖点）。
- API 层 `src/api/` 按模块拆 axios client；`src/mock/` 是 MSW handlers + 数据；真实后端尚未实现，切真实后端只需 `VITE_USE_MOCK=false`。
- 设计令牌在 `src/styles/design.css`；红涨绿跌变量 `--rise: #F6465D` / `--fall: #2EBD85`。
- RBAC：`menu:*` 权限控制菜单显隐，`manage` 权限控制管理按钮，`v-permission` 指令（`directives/permission.ts`），admin 全权限。

## Spec-driven 开发（openspec）

仓库采用 openspec 的 spec-driven 流程（见 `openspec/`，命令/技能在 `.claude/commands/opsx/` 与 `.claude/skills/openspec-*`）。改动前先查 openspec 是否有进行中变更：

- **进行中**：`openspec/changes/chan-stock-manage/`（股票管理 Web 闭环：增量续算引擎 + 买卖点索引落 PG、自选/历史买卖点/监控三 Tab、行业多对多、买卖点绩效、选股器、区间套、预警、多用户 RBAC）；`openspec/changes/chan-web-viewer/`（Web 交互式 K 线可视化）。
- **已归档**：`openspec/changes/archive/2026-09-16-persist-kl-to-duckdb/`（DuckDB 持久化）。

这些变更都约定**不修改 `CChan`/`CBiList`/`CSegListChan`/`CZSList`/`CBSPointList` 的计算逻辑**，只复用其 `trigger_step` / `trigger_load` / pickle 能力，并以 DuckDB 存原始 K 线、PG 存缠论结论与业务元数据。规划中的后端 `WebAPI/`（FastAPI）尚未创建；前端目录实际落在 `front/`（而非 proposal 里写的 `web/`）。

## 目录结构速查

| 目录 | 用途 |
|------|------|
| `Chan.py` | 主入口类 `CChan` |
| `ChanConfig.py` | 配置系统 `CChanConfig` |
| `Common/` | 枚举、异常、缓存、工具函数 |
| `KLine/` | K 线单元、合并 K 线、K 线列表容器 |
| `Combiner/` | K 线包含处理/合并逻辑 |
| `Bi/` | 笔的构建与管理 |
| `Seg/` | 段算法（特征序列、虚段处理） |
| `ZS/` | 中枢构建与合并 |
| `BuySellPoint/` | 买卖点计算 |
| `Math/` | 手写技术指标 |
| `DataAPI/` | 数据源适配器（BaoStock/Akshare/CCXT/CSV/DuckDB/Minute）+ 持久化（KLineStore/IngestUtil/RecomputeCursor） |
| `Plot/` | matplotlib 绘图 |
| `Debug/` | 策略演示 / 灌数 / 手动测试脚本 |
| `App/` | GUI 扫描器 |
| `ChanModel/` | ML 特征容器（开源版中不完整） |
| `front/` | Vue3 前端（MSW mock 驱动，后端未落地） |
| `openspec/` | spec-driven 变更提案与规范 |
| `docs/` | 自动生成的入职指南 `ONBOARDING.md` |
