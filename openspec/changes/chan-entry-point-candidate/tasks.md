# Tasks

## 1. 内核配置键与校验

- [x] 1.1 `CPointConfig`（BSPointConfig.py）新增 12 个介入点字段（`bsp{1,2,3}_entry` / `_entry_qjt` / `_entry_qjt_depth` / `_entry_aux`），构造期校验层数为 >= 1 整数（样式仿 `bsp1_qjt_depth` 的既有校验）；验证：非法层数构造时抛 `CChanException`
- [x] 1.2 `ChanConfig.py` 出厂默认补 12 键（全 False / 层 1），`_BSP_PRESETS["legacy"]` 显式写 12 键全 False（防御性条目）；验证：`CChanConfig({"bsp_preset": "legacy"})` 构造成功且 12 键全 False

## 2. 内核介入点判定核心

- [x] 2.1 从 `BSPointList` 提取窗口/时间映射为模块级可复用函数（`_c_window_of`、`_sub_time_span` 核心逻辑），保持既有调用点行为不变；验证：`Debug/bi_test.py`、`Debug/bsp_qjt_step.py` 通过（既有基线不回归）
- [x] 2.2 实现介入点判定核心（模块级纯函数，输入 bsp / 子级容器 / 配置，输出 hit/method/level）：方法1 链式下钻（中间层同向已确认一买、最低层同向候选一买 + 末端分型形成）、方法2 次级已成立 T2/T2S/T3A/T3B 同向点、窗口按 D3 口径（1买 c 段 / 2买回落段 / 3买回抽段，方法2 右端至数据末端）、必要条件按 D7（仅未确认段上的候选点）；验证：新建 `Debug/entry_point_synth.py` 合成数据单测，覆盖 spec 全部 scenario（开关全关零变化、方法1 命中、方法2 命中、双未命中、卖镜像、窗口排除段前信号、右端容纳滞后、必要条件不满足、单方法关闭、legacy 全关）
- [x] 2.3 `BSPointList.cal()` 收尾（`_annotate_qjt` 之后）新增 `_annotate_entry_point()`：读配置分流 12 键，写 feature `entry_hit`/`entry_method`/`entry_level`；`sub_bs_point_lst is None` 时直接返回；验证：批量/步进终态 feature 一致（`Debug/entry_point_synth.py` 的 step 分支）

## 3. WebAPI 配置链路

- [x] 3.1 `chan_config_schema.py` 补 12 项元数据：判据分组、白话解释、`conditional=True` + `visible_when`（entry→qjt→depth 链 + aux），分布到一买/二买/三买 subtype；验证：`GET /api/chan-config/schema` 返回 12 项且 visible_when 链正确、响应走 `encode_config` 不 500
- [x] 3.2 `config_fingerprint.py` bsp 段加入 12 键；`chan_config_store.validate_config()` 传副本构造一次（既有机制自动覆盖新键）；验证：改介入开关后指纹变化、非法层数保存被拒且报错定位到具体键
- [x] 3.3 按项目规范在 `WebAPI/update-win.sql` 追加幂等 SQL（`bsp_index` 加三列 `entry_point`/`entry_method`/`entry_level`，带执行时间注释）；验证：SQL 在 PG 上重复执行不报错

## 4. 落库与查询链路

- [x] 4.1 `bsp_store.py` 惰性 DDL `_ensure_tables()` 加三列 + 两处 INSERT 语句同步加列；验证：全新库建表含三列、老库启动自动补列且旧行为 NULL
- [x] 4.2 `incremental_engine.py`：判定核心在 `_extract_bsp_rows` 内以 WebAPI 侧调用（复用任务 2.1 提取的函数，输入 `sub_result`），行拼接三列；无子级时三列为 NULL/False；验证：`Debug/test_e2e_duckdb.py` 通过 + 新建落库冒烟脚本检查介入列正确写入与增量刷新
- [x] 4.3 `resolve_bsp_type` 扩展伪类型 `'entry'`/`'entry1'`/`'entry2'`/`'entry3'` 翻译为 `entry_point=TRUE`（+类型 IN）；`routers/bsp.py` 透传；`query_bsp`/按代码查询返回记录携带介入字段；验证：伪类型筛选只返回介入成立行且 `total` 正确
- [x] 4.4 `serializer.py` `_serialize_bsp` 的 bsp dict 加 `entry`/`entry_method`/`entry_level`（多级别链路读内核 feature）；验证：`/api/klines` 响应中 bsp 节点含三字段

## 5. 前端配置与展示

- [x] 5.1 `ChanConfigDrawer.vue` 无需逻辑改动（`isVisible` 已支持），检查 12 项在抽屉中按 visible_when 正确显隐、草稿切换即时响应、隐藏不清值；验证：手动走查三层联动（spec chan-config-page 四个 scenario）
- [x] 5.2 `utils/bsp.ts` 新增介入合成标签（`1B·介`/`1S·介`）；`chan_bsp.ts` `ChanBspMeta` 加 entry 字段、`chanBspLabel` 合成；验证：图上介入点标签显示后缀，非介入点不变
- [x] 5.3 BspView 类型列用同一合成函数、类型筛选下拉加伪类型项（调用 4.3 的参数）；`front/src/mock/` bsp 数据补三字段与示例；验证：MSW mock 下列表与筛选行为正确
- [x] 5.4 介入点 tooltip 标注暂时性语义（随数据推进可翻转）；验证：hover 介入标记显示说明文案

## 6. 回归与文档

- [x] 6.1 等价回归：`Debug/bsp_standard_equivalence.py`（开关全关时六类逐笔一致、legacy 档基线不变）；验证：脚本全绿
- [x] 6.2 双链路口径一致：落库行介入列与 `/api/klines` 序列化值对同一标的同一时点一致（复用任务 2.1 共享核心）；验证：新建对比脚本输出一致
- [x] 6.3 `文档/缠论策略.md` 同步介入点判定逻辑（必要条件、双方法、窗口、买卖镜像、暂时性语义）；验证：文档含三类型判定树与配置键说明
- [x] 6.4 手动冒烟：前端开启介入点（1买方法1+方法2）→ 保存重算 → K 线图标签合成、买卖点列表伪类型筛选、配置抽屉三层联动全链路；验证：全链路无 500、行为与 spec scenario 一致
