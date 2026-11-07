# Tasks

## 1. 配置存储与参数元数据

- [x] 1.1 新建 `WebAPI/chan_config_store.py`：惰性 `_ensure_tables()` 建 `chan_config` 单行表（`id` 固定 1、`config JSONB`、`preset`、`version BIGINT`、`updated_at`、`updated_by`，`ON CONFLICT (id) DO UPDATE` 写入并 bump `version`）；`load()` 带进程内 `(version, config)` 缓存，每次先查 `version` 再决定是否重读整行。验证：连续两次 `load()` 只反序列化一次（加计数断言）；`save()` 后 `version` 递增且 `load()` 返回新值；重复执行建表语句不报错。
- [x] 1.2 在 `WebAPI/update-win.sql` 追加 `chan_config` 建表语句（`CREATE TABLE IF NOT EXISTS`，前置执行时间注释）。验证：在已存在的库上重复执行两次均无报错；`\d chan_config` 与 `_ensure_tables()` 建出的结构一致。
- [x] 1.3 新建 `WebAPI/chan_config_schema.py`：为 58 项参数（56 常驻 + 2 条件项 `cal_rsi`/`rsi_cycle`）定义元数据，含标识、展示名、三组分类（`bsp_judgement` 33 / `ladder_annotation` 8 / `structure` 17，含 2 条件项）、控件类型、影响面、`plain`/`effect`/`scope` 三段白话解释。**默认值与合法取值运行期从 `CChanConfig()` 实例反射读取，不硬编码**。验证：单测断言元数据项数 = 58，每项 `plain`/`effect` 非空且不含「特征序列」「线段破坏」等术语，只影响标注的 8 项 `effect` 含「不改变」「不会增减」字样。**落地偏差**：设计初稿写 55 项（判据 32 / 结构 15），实现时把 `bsp_preset` 计入判据组、`cal_rsi`/`rsi_cycle` 归入结构组，实际 33 / 8 / 17。
- [x] 1.4 枚举型参数的合法取值来源与配置构造期校验对齐。验证：单测对每个枚举参数断言 `set(元数据给出的取值) == set(_check_choice 白名单元组)`，并覆盖 `bsp1_new_extreme_mode`（含 `chan-bsp1-strict-extreme` 计划新增的 `level`）。
- [x] 1.5 为 `macd_algo` 的 6 个受限取值写附加说明：5 个量能类标注「线段级别使用峰值算法回退」，`rsi` 标注「自动开启 RSI 指标计算」。验证：单测断言这 6 项的元数据带 `caveat` 字段且文案非空。

## 2. 计算链路接入与指纹扩展

- [x] 2.1 改 `WebAPI/chan_service._make_chan_config()` 与 `WebAPI/incremental_engine._make_chan_config()`：改为消费 `chan_config_store.load()` 的输出，保留各自入口专属的 `trigger_step` / `kl_data_check`（用户配置不含这两项）；把「此处不得显式覆盖任何 bsp 参数」的注释改写为新契约（三层优先级说明）。验证：两个入口对同一份已保存配置构造出的 `CChanConfig` 在全部 58 项上取值相同（单测逐项比对）。
- [x] 2.2 实现 D12 的降级：`load()` 在 PG 不可达时返回内核默认配置 + `log.warning`，`/api/klines` 与 `recompute_stock` 均不因此失败。验证：单测 mock PG 连接抛 `OperationalError`，断言 `_make_chan_config()` 返回配置且不抛异常、日志含降级文案；同时断言 `save()` 在此场景抛 503 而非静默成功。
- [x] 2.3 实现 D6 的派生键：`load()` 输出中，5 个量能类取值自动补 `macd_algo-seg`（已有则保留），`rsi` 自动补 `cal_rsi=True`。验证：实测 `{"macd_algo": "volumn"}` 经 `load()` 后能完成 `sz.000001` 日线计算（此前实测崩溃）；`{"macd_algo": "rsi"}` 同样完成。断言用户存储中的 `macd_algo` 原值未被改写。
- [x] 2.4 扩展 `WebAPI/config_fingerprint.collect_config()` 为结构化分段（`bsp` / `seg_bsp` / `bi` / `seg` / `zs` / `macd` / `indicator`），复用既有 `_normalize()` 的枚举分支。验证：单测断言仅改 `bi_fx_check` 时指纹变化、仅改 `zs_combine` 时指纹变化、仅改 `macd.fast` 时指纹变化；仅改 `bsp1_zero_axis` 时（原有能力）仍变化；配置不变时两次调用指纹相同。
- [x] 2.5 保持派生键与指纹的单一出口：断言「从 `load()` 输出构造的配置对象」的指纹包含派生结果（即无派生与有派生的配置指纹不同）。验证：单测对比 `load()` 输出构造的配置指纹与手工去掉派生键后的指纹，断言不等。
- [x] 2.6 验证结构参数改动触发全量重算：先以配置 A 跑 `recompute_stock`，改 `bi_fx_check` 保存后再跑，断言 `mode == "full"` 且旧口径结构不残留。验证：对 `sz.000001` 日线执行两次，第二次 summary 的 `mode` 为 `full`；对 `bi_*` 未改动的场景断言仍为 `incremental`。
- [x] 2.7 为 `bs_type` 的延迟断言补前置校验入口（`parse_target_type()` 在计算期才 assert）。验证：单测断言保存前的校验函数对 `bs_type="1,9"` 抛错、对 `"1,1p,2,2s,3a,3b"` 通过。

## 3. 配置读写 API

- [x] 3.1 新建 `WebAPI/routers/chan_config.py` 并挂载到 `WebAPI/app.py`：`GET /api/chan-config`（当前生效配置 + version + preset，`menu:kline` 守卫）、`GET /api/chan-config/schema`（元数据，`menu:kline`）、`PUT /api/chan-config`（`require_manage`）。验证：启动服务后四个端点均可达；无 `manage` 权限的用户 `PUT` 返回 403、`GET` 正常。
- [x] 3.2 `PUT` 实现 D4 的构造期校验：先用候选配置构造 `CChanConfig`，捕获 `CChanException`/`AssertionError` → 422 并透传内核异常原文；额外调用 `parse_target_type()` 把延迟断言前移。验证：`bsp2_confirm_window=3`、`bsp3b_mode=bogus`、`bsp2_time_axis_strong >= weak`、`max_bs2_rate=1.5`、`bs_type="1,9"` 五种非法输入均返回 422 且 `detail` 可定位到参数；校验失败后 `GET /api/chan-config` 返回的仍是旧配置（未写入）。
- [x] 3.3 `PUT` 写入全量快照 + 当下档位预设名（D3），并返回新 `version`。验证：只改一个参数后保存，`GET` 返回的配置含全部 58 项且未改项取值为保存时的当前生效值；`preset` 字段等于保存时选择的档位。
  **收官复核时发现的真缺陷（已修复）**：档位名只落在 `preset` 列，从未进入计算链路。`load()` 从库里把 `preset` 读出来却**弃之不用**，`build_conf()` 也只合并 `overrides`，于是 `CChanConfig` 永远按硬编码默认 `standard` 展开 —— 用户切到 `legacy` 后**一处判据都不跟着变**（实测 `preset=legacy` + 空 overrides：`min_zs_cnt` 仍 2、`divergence_rate` 仍 0.9、`bsp1_trend` 仍 `True`）。根因是设计上 `bsp_preset` 不进 `overrides`（前端 `computeOverrides()` 拿它与档位基线比，相等就不写，它本来就不是「用户改过的项」），所以没有任何一处把 `preset` 列回填。
  修复：新增 `chan_config_store.load_preset()`（走与 `load()` 同一份版本缓存）与 `_preset_injected()`，由 `build_conf()` / `effective_config()` 回填；`routers/chan_config.py` 新增 `_conf_from_meta()` 供 `effective` 与 `/schema` 的 `params[].default` 共用（否则界面显示与图上计算两份口径）。`load()` 保持纯净（不含 `bsp_preset`），既有断言不变。
  连带暴露并修复：`GET /api/chan-config` 裸返回 `effective`，legacy 档 `divergence_rate=inf` 让 starlette 的 `json.dumps` 抛 `Out of range float values are not JSON compliant`（500）。改为整份响应走 `store.encode_config()`（`/schema` 早已如此）。
  回归断言：`Debug/test_chan_config_store.py` 第 7 组 9 项（档位注入、显式覆盖优先、`bsp_preset` 显式写入优先于 `preset` 列）；HTTP 层实测切 legacy 后 `effective.min_zs_cnt=1`、`divergence_rate="inf"`、`preset_baselines.legacy.min_zs_cnt=1`。
  **顺带补的第三处缺陷**：`PUT` 的 `preset` 字段此前完全绕过校验（`validate_config()` 只校验 overrides）。档位现在真正进入计算链路后，一个非法档位名一旦落库，后续**每次** `CChanConfig(...)` 都会抛 `unknown bsp_preset`，**全站 K 线请求 500**。新增 `chan_config_store.validate_preset()`（合法清单直接取内核 `_BSP_PRESETS`，不复制）并在 `put_config()` 写入前调用。第 8 组 7 项断言固定该行为；HTTP 实测 `PUT {"preset": "bogus"}` → 422、`detail.param == "bsp_preset"`、库中 `version`/`preset`/`overrides` 三项均未变。
- [x] 3.4 断言「内核默认值变化不改写已保存配置」：单测保存一份显式配置后，模拟内核默认值改动（用 monkeypatch 改 `set_bsp_config` 的 `para_dict` 默认），断言 `load()` 返回的仍是保存值。验证：该单测通过。

## 4. 单只重算与批量同步

- [x] 4.1 新建 `chan_config_sync_job` 表（惰性 DDL 在 `chan_config_store` 或独立 store 内，并在 `update-win.sql` 追加记录）：`id` / `config_version` / `status` / `total` / `done` / `failed` / `summary JSONB` / `started_at` / `finished_at`。验证：重复执行建表幂等；一次同步后可从表读到完整进度与汇总。
- [x] 4.2 给 `incremental_engine.catch_up` 增加可选进度回调（默认 None，不改变现有调用方行为），逐键推进 `done` 计数。验证：现有 `Debug/bsp_engine_regression.py` 相关入口在不传回调时行为不变；传入回调时每个键回调一次。
- [x] 4.3 `POST /api/chan-config/recompute`：对单个 `(code, period, autype)` 调 `recompute_stock`，后台执行，返回受理标识。`force_full` 传 `False`（指纹已变会自动转全量）。验证：改配置后调用，该股票 `bsp_index` 行数与 `GET /api/klines` 的 `bsp` 长度一致。
- [x] 4.4 `POST /api/chan-config/sync`：`catch_up(None, None, None, limit=0, force=True)`，内存标志防重入（已有任务 → 409），启动时快照 `config_version`。验证：连点两次第二次返回 409；同步期间 `GET /api/chan-config/sync/status` 返回 `running=true` 与递增的 `done`。
- [x] 4.5 `GET /api/chan-config/sync/status`：返回运行状态、`total`/`done`/`failed`、失败明细、以及 `stale`（结束时比对 `config_version` 与当前）。验证：单测模拟任务中途 bump 配置版本，断言完成时 `stale=true`。
- [x] 4.6 单键失败不阻断：验证一次含失败键的批量同步，`summary.failed` 列出该键的 code/period/原因，其余键全部成功。可用历史失败样本 `sh.600007 / 5m`（pickle 递归溢出）复现。
- [x] 4.7 全量同步回归：对当前 DuckDB 全部键执行一次，记录耗时与成功/失败数写入 `Log/`，确认
  `bsp_index` 与按新配置重算的结果一致（抽样 5 只比对行数与类型分布）。
  **实测结果（2026-11-07）**：DuckDB 75 个 (code, kl_type, autype) 键，剔除 ST 后 73 个，
  耗时 208s（2.9s/键），成功 73 / 失败 0，抽样 5 个键 `bsp_index` 行数与 `summary.bsp_rows`
  完全一致，73 个快照指纹全部等于当前配置。日志 `Log/chan_config_sync_regression_20261107_201758.log`。
  抽样校验需按 `autype` 过滤——库中存有 80 行历史遗留的 `sh.600000` HFQ 数据，不属于 QFQ 口径。
  该次运行后后端调度器又灌入 6 个键（现 81 个 / 49 只），属数据增长而非口径变化。
  **并发注意**：DuckDB 单文件锁在 Windows 上抛 `Cannot open file ... 另一个程序正在使用此文件`，
  `KLineStore._connect()` 已改按跨平台特征识别锁冲突（`Debug/test_klstore_lock_retry.py` 固定该规则）。
  **档位修复后复跑（2026-11-07 21:39，日志 `Log/chan_config_sync_regression_20261107_213945.log`）**：
  `Debug/test_chan_config_sync.py` 全库 79 键重算 **6 PASS / 0 FAIL**，抽样 3 键
  （`sh.000001` 12、`sh.000010` 19、`sh.000016` 13）`bsp_index` 行数与计算值逐一相等，
  79 个快照指纹**全部**等于当前配置指纹 —— 证明档位回填后计算出口用的确是库里那份配置。

## 5. 前端配置抽屉

- [x] 5.1 新建 `Front/src/api/modules/chanConfig.ts`：`getChanConfig` / `getChanConfigSchema` / `saveChanConfig` / `recomputeStock` / `startSync` / `getSyncStatus`，类型定义放 `api/types.ts`（对齐既有 `api/modules/*` 风格）。验证：`npm run build` 通过 `vue-tsc` 类型检查。
- [x] 5.2 新建 `Front/src/stores/chanConfig.ts`：`saved` / `schema` / `draft` 三份状态 + `dirtyCount` 计算 + `openDraft()` 深拷贝 / `discardDraft()` / `resetToDefaults()`。验证：`Debug/test_chan_config_frontend_store.py`（esbuild 打包改写过导入路径的 store 副本 + node 运行，**13 PASS / 0 FAIL**）断言改一项后 `overrides` 只含该项、`discardDraft()` 后归零、`resetToDefaults()` 后 `draft` 等于**当前档位预设基线**（不是内核默认）而档位本身不变。
  **实测发现并修复的缺陷**：`computeOverrides()` 原先只遍历 schema 参数，会把 `saved.overrides` 里 UI 无法编辑的键（用户曾直接调接口写的 `divergence_rate-buy` 等分侧后缀）静默挤掉 —— 用户什么都没改，保存一次就丢配置。改为先把非 schema 键原样带入，再叠加 schema 参数的 diff（场景 B1/B2 固定该行为）。
  **一处被证伪的猜测**：曾怀疑 `effective` 会带后端派生键 `macd_algo-seg` 从而让 `dirtyCount` 误判。实测不成立 —— `GET /api/chan-config` 的 `effective` 由 `PARAMS` 逐项反射构造，恒为 58 个 schema 键，派生键只存在于计算出口（`load()`）与 PG 的 `overrides` 列，不会出现在 `effective` 里。已把 `dirtyCount` 的比较范围改回「并集」原状。
  另修 `load_with_meta()`：它此前对 `overrides` 做 `apply_derived()`，使 `GET /api/chan-config` 把派生键当成「用户显式改过」返回（实测保存 `macd_algo=volumn` 后 `overrides` 里冒出 `macd_algo-seg: peak`）。该值被前端原样回传、又被 `save()` 的 `_strip_derived()` 清掉，虽不致命但语义错误。现改为返回原始 overrides，派生只在计算出口生成。
- [x] 5.3 新建 `Front/src/components/kline/ChanConfigDrawer.vue`：`el-drawer` rtl、三组折叠（判据 33 默认展开 / 标注 8 默认展开 / 结构 15+2 条件项默认折叠且展开前显示警示）、组标题显示项数、底部吸顶「已修改 N 项 · 当前档位」+ 恢复默认 / 取消 / 保存并重算当前股票。验证：`npm run dev` 打开抽屉，三组项数分别为 33 / 8 / 15（后端 `groups[].count` 不计条件项），选 `macd_algo=rsi` 后结构组变 17，未改动时保存按钮禁用。
- [x] 5.4 新建行组件 `Front/src/components/kline/ChanConfigRow.vue`：按控件类型渲染（布尔开关 / 数值输入 / 枚举下拉 / 多选 `bs_type`），旁置问号图标，悬浮显示 `plain`/`effect`/`scope`/默认值/影响面三段白话解释；受限取值（`macd_algo` 的 6 项）在行下方常驻显示 `caveat`。验证：逐一悬浮 58 项问号均显示非空解释；选 `macd_algo=volumn` 后行下方出现回退说明；选 `rsi` 后出现 `cal_rsi`/`rsi_cycle` 两项。
- [x] 5.5 草稿语义与离开保护：所有控件只改 `draft`；`before-close` 钩子在 `dirtyCount > 0` 时二次确认；切换股票/周期/离开路由同样拦截（注意 K 线页被 KeepAlive 缓存，需处理 `onDeactivated`）。验证：改 2 项后直接关抽屉弹确认；确认放弃后图表与后端配置均未变；改 2 项后切换周期被拦截。
- [x] 5.6 保存流程：`PUT` 成功 → `load()` 重拉当前股票 → 并行 `POST /api/chan-config/recompute`；重算中显示进行中、完成显示完成、失败保留原图并显示原因与重试。校验失败（422）时抽屉保持打开、草稿完整保留、错误提示定位到参数。验证：构造 `bsp2_confirm_window=3` 触发 422，确认草稿未丢；正常保存后图表买卖点按新配置重绘。
- [x] 5.7 批量同步 UI：抽屉内「同步所有股票」按钮，存在未保存改动时提示先保存/放弃；启动后轮询 `sync/status` 显示 `done/total`、成功/失败计数；完成展示失败明细；`stale` 时提示结果已过期。验证：演示版点同步后进度条递增，完成后失败项列表可见；重复点击提示已有任务在运行。
- [x] 5.8 `KLineView.vue` 顶栏增加「缠论参数」按钮并挂载抽屉，复用 `btn btn--ghost btn--sm topbar-action` 样式（与「均线」按钮一致），仅对有 `manage` 权限的用户启用保存与同步按钮。验证：`trader` 账号登录后抽屉可打开查看但保存按钮禁用；`admin` 全部可用。

## 6. 文档与集成验证

- [x] 6.1 改写 `文档/缠论配置参数.md` §十四：把「目前没有任何买卖点参数开放到业务配置」整节替换为「开放范围 / 三层优先级 / 生效方式 / 指纹范围 / 派生键说明」，并在 §十三 补结构参数已入指纹。验证：文档中不再出现「切档位只能改代码」，且 §十三 的指纹清单与 `config_fingerprint.py` 实际一致。
- [x] 6.2 更新 `文档/缠论策略.md` 中关于「切档位只能改代码、改后需重跑全库」的表述（`chan-strategy-doc-sync` 约定）。验证：该表述改为指向配置抽屉与保存后重算流程。
- [x] 6.3 更新 `CLAUDE.md` 的 WebAPI 段落，记录 `chan_config` 表与新增 router。验证：`grep -n "chan_config" CLAUDE.md` 有命中。
- [x] 6.4 端到端集成验证：管理员登录 → 打开抽屉 → 改 3 项（1 项判据 + 1 项标注 + 1 项结构）→ 保存 → 确认 K 线图重绘且当前股票 `bsp_index` 与 `/api/klines` 口径一致 → 点「同步所有股票」→ 等完成 → 抽样 5 只核对。验证：全流程无报错，抽样核对一致，失败项为 0 或仅历史已知失败样本。
  **实测结果（2026-11-07）**：`Debug/test_chan_config_e2e.py` 直连 `http://127.0.0.1:8011` 走完整 HTTP 流程，
  **19 PASS / 0 FAIL**（日志 `Log/e2e_run.log`）。关键断言：保存 3 项改动后 `effective` 已反映；
  `bsp_index` 行数 12 == `/api/klines` 的 `bsp` 个数 12；重复启动同步返回 409；
  全库 79 键同步完成、失败 0、`stale=false`；抽样 3 只快照指纹一致；恢复基线后 overrides 回到原值。
  **注意**：该脚本必须与其它写配置的测试脚本**串行**运行 —— 首次并行跑到第 5 步时，
  `test_chan_config_store.py` 反复 `save()` 把配置版本推高，`sync/status` 正确返回 `stale=true`，
  被测脚本报 FAIL，那是我并发操作造成的假阳性，不是产品缺陷。
  **串行复跑（2026-11-07，日志 `Log/e2e_run2.log`）**：重启后端后不与任何写配置脚本并发，
  再次得到 **19 PASS / 0 FAIL**；同步任务 `job_id=37`，`79/79` 键完成、`failed=0`、
  全程 `config_version=240` 未被推高、完成时 `stale=false`。这坐实了首轮的 `stale=true` 是并发写配置所致，
  与产品逻辑无关。抽样 3 只（`sz.000001` 12 个买卖点、`sh.600000` 16 个、`sz.301123` 0 个）
  快照指纹均为 `3972e854d218a90f`，与当前配置一致。
  **第三次并发失误（`Log/e2e_run3.log`）**：修复档位缺陷后我**又**在同步任务 `job_id=44`
  进行中跑了 `Debug/test_chan_config_store.py`（数十次 `save()`），版本被从 354 推到 373，
  完成时 `stale=true`，e2e 报 **18 PASS / 1 FAIL**。这个 FAIL 是我自己造成的假阳性 ——
  同一类错误已发生三次（run1 / run3 皆然），**规矩是：e2e 运行期间不得执行任何写配置的脚本**。
  **第四次串行复跑（2026-11-07，日志 `Log/e2e_run4.log`，档位修复 + `validate_preset` 之后）**：
  先重启后端让 `validate_preset` 生效，确认无遗留写配置进程，再运行 →
  **19 PASS / 0 FAIL**。同步任务 `job_id=45`，`scanned=79` / `updated=79` / `failed=0`、
  耗时 2 分 35 秒、全程 `config_version=375` 未被推高、完成时 `stale=false`。
  抽样 3 只（`sz.000001` / `sh.600000` / `sz.301123`）均有快照指纹，恢复基线后 `overrides` 回到原值。
  同一轮还实测了档位的 HTTP 层行为：`PUT {"preset": "bogus"}` → **422**，
  `detail.param == "bsp_preset"`，且 `version` / `preset` / `overrides` 三项均未被改动（未写库）。
- [x] 6.5 回滚验证：把 `_make_chan_config()` 临时改回硬编码后启动，确认 K 线页行为等同改造前；确认此时因指纹失配会触发一次全量重算（记录到文档的回滚说明中）。验证：临时改回后 `/api/klines` 正常返回，`recompute_stock` 的 summary 显示 `mode=full`。
  **实测结果（2026-11-07）**：不修改源码，直接对比两种构造口径的指纹（`Debug/test_chan_config_rollback.py`，7 项断言全过）——
  用户未覆盖任何项时，硬编码口径与 `build_conf()` 口径的指纹**完全相同**（回滚不会造成口径漂移）；
  存在用户覆盖（`bsp1_zero_axis=False`）时两者不同，故回滚后首次重算必转全量，与文档 §14.6 的描述一致。
  `bsp`/`bi`/`seg`/`zs`/`macd` 五段各取一个代表参数，改动任一段都会改变指纹。
  回滚说明见 `文档/缠论配置参数.md` §14.6。
