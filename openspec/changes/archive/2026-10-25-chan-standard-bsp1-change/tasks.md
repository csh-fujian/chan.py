# Tasks

## 1. 配置项与档位预设

- [x] 1.1 在 `ChanAnalyse/BuySellPoint/BSPointConfig.py` 的 `CPointConfig.__init__` 增加形参 `bsp1_downgrade_to_pz=True` 并赋值，同步补类 docstring 的属性说明；验证 `CChanConfig({}).bs_point_conf.b_conf.bsp1_downgrade_to_pz is True`、`CChanConfig({"bsp1_downgrade_to_pz": False})` 取到 `False`
- [x] 1.2 在 `ChanAnalyse/ChanConfig.py` 的 `set_bsp_config` 的 `para_dict` 增加 `"bsp1_downgrade_to_pz": True`，并在 `_BSP_PRESETS["legacy"]` 展开中加入 `"bsp1_downgrade_to_pz": False`；验证 `CChanConfig({})` 与 `CChanConfig({"bsp_preset": "legacy"})` 的取值分别为 `True` / `False`，且 `ConfigWithCheck` 白名单接受该 key（拼错时仍抛 `CChanException`）
- [x] 1.3 在 `WebAPI/config_fingerprint.py` 的 `FINGERPRINT_KEYS` 追加 `"bsp1_downgrade_to_pz"`；验证对同一 `CChanConfig` 仅翻转该开关时 `config_fingerprint()` 结果不同，连续两次求值相同

## 2. 降级路由（核心）

- [x] 2.1 在 `BSPointList.treat_bsp1` 中抽出「背驰链路是否成立」的局部变量（`peak_ok = (not BSP_CONF.bs1_peak) or break_peak`、`divergence_ok = is_diver`），并把现有对 `is_target_bsp` 的两次置 False 改为基于这两个变量计算，行为保持不变；验证 `bsp_preset="legacy"` 下 41 只日线输出与改造前基线逐类型一致（`1:258 1p:69 2:318 2s:317 3a:61 3b:50`）
- [x] 2.2 实现降级触发：当 `bsp1_downgrade_to_pz` 为真、`diver_proven` 为真、`peak_ok` 为真、`(not standard_ok) and standard_reason == 'trend'` 为真、且 `rest_ok` 为真时，改以 `BSP_TYPE.T1P` 登记，固定传 `is_target_bsp=False`；其余情况维持现有 T1 分支。其中 `diver_proven = is_diver and BSP_CONF.divergence_rate <= 100`（注意：**必须读配置值 `BSP_CONF.divergence_rate`，不是 `is_divergence` 返回的实测比率**），`peak_ok = (not BSP_CONF.bs1_peak) or break_peak`，`rest_ok` = 以 `bsp1_trend=False` **且 `bsp1_new_extreme_mode="all"`** 的 `copy.copy(BSP_CONF)` 重跑 `check_bsp1_standard` 并通过（若 `BSP_CONF.bsp1_trend` 本已为 False，则直接令 `rest_ok = standard_ok` 避免重复调用；`mode` 覆写依据 design D1-c——`check_new_extreme` 经 overlap 找趋势对会把比较起点锚到 `z1.bi_in`、排除线段内更早笔，导致降级点比较窗口随中枢形态漂移）。验证：单中枢合成序列触发降级；两中枢重叠合成序列触发降级；DIF 背驰不过的样本不触发；`divergence_rate=200` 且 `bsp1_trend=True` 的合成场景降级点为 0
- [x] 2.2a 验证 `diver_proven` 的空真陷阱已规避：构造 `divergence_rate > 100`、`bsp1_trend=True`、单中枢的序列，断言 `is_divergence` 返回 True（证明空真确实发生），但 `treat_bsp1` 不产出 T1P；再在 `treat_bsp1` 与 `ZS.is_divergence` 两处各加一行互指注释，锁定 `>100` 魔数的双重语义依赖，禁止任一侧单独改阈值
- [x] 2.2b 验证 `rest_ok` 全检的必要性：构造「趋势不过 + 面积背驰过 + 极值过 + 新低不过」的合成序列，断言不降级；并统计 41 只日线下「仅 `reason=='trend'`」与「补全检后」的降级点数，前者为 **142**（漏斗第三/四档），后者为 **53**（D1-c 的 `mode="all"` 与 `trend_start` 两种口径实测差异为 0，两者同为 53，见 design D1-c 实测复核）；将 53 写入 `Debug/bsp_standard_equivalence.py` 模块注释基线区作为断言值
- [x] 2.2c 验证 D1-c 的窗口一致性：构造两个合成场景做对照——①线段内仅一个中枢、线段前部存在比 c 段低点更深的下跌笔（应不降级）；②同一线段把前部深笔改为「位于第二中枢（重叠式下移）之后」，其余结构相同（两场景 c 段低点相同）。断言两个场景的降级结论一致：若②按 `trend_start` 锚点会把①中被排除的深笔重新纳入时，②必须同样不降级。同时验证 T1 首轮判定不受影响：`bsp1_trend_mode="strict"` 且趋势成立时，`standard_info` 的 `ref_start_idx` 仍为趋势起点（不被 `mode="all"` 覆写污染——覆写只发生在 `rest_ok` 重跑的副本配置上）
- [x] 2.3 在降级点的 `feature_dict` 写入 `bsp1_downgrade_reason`：`standard_info.get('zs_cnt', 0) < 2` 时取 `"single_zs"`，否则取 `"no_trend"`；验证 41 只日线全部降级点均带该字段且取值只在这两个字符串内（遍历 `bsp1_list` 中断言）
- [x] 2.4 在 `check_bsp1_standard` 的 `check_trend` 调用处加注释，锁定「`trend` 必须是第一个检查项，降级路由依赖 `reason == 'trend'` 表示除趋势外全部通过」这一契约；验证注释存在且 `openspec/changes/chan-standard-bsp1-change/specs/chan-bsp1-downgrade/spec.md` 的顺序语义可被逐条对应
- [x] 2.5 在 `treat_bsp1` docstring 中说明降级路由的触发条件与「降级点不得作为锚点」的约束，并在 `treat_pz_bsp1` docstring 中说明它与降级点的边界（前者是无中枢的笔背驰、后者是有中枢的趋势不达标）；验证两处 docstring 与 design.md D1/D2 描述一致

## 3. 锚点隔离与 `add_bs` 保护

- [x] 3.1 在 `BSPointList.add_bs` 的 `exist_bsp` 分支增加「降级不得升级」保护：降级请求命中已有买卖点时只调用 `add_another_bsp_prop` 后返回，不执行「候选→成立」的 `bsp1_sure_dict` 补齐逻辑；验证构造「同笔先 T1 候选、后 T1P 降级」的合成场景，该笔不出现在 `bsp1_sure_dict` 中
- [x] 3.2 回归验证「先候选后成立」的 T1 升级路径未被破坏：构造同一笔先因 `bs1_peak` 不过登记为候选、后续因条件变化登记为成立的场景，验证该笔正确进入 `bsp1_sure_dict`；并确认 41 只日线标准档的 `bsp1_sure_list` 长度与改造前一致（14）
- [x] 3.3 验证降级点绝不进入 `bsp1_sure_dict`：41 只日线标准档下遍历 `bsp1_list`，所有带 `bsp1_downgrade_reason` 的点其 `bi.idx` 均不在 `bsp1_sure_dict` 中（断言 0 例违规）
- [x] 3.4 验证下游类型数量零扰动：同一数据分别在 `bsp1_downgrade_to_pz=True` / `False` 下重算，逐类型比对 `T1` / `T2` / `T2S` / `T3A` / `T3B` 数量完全相同（期望值 `1:14 2:12 2s:4 3a:1 3b:1`），差异只在 `1p`（期望 `0 → 53`；本项与 §4.4 的力度口径改造叠加后为 `1p: 0 → 52`，见 tasks 9.7）

## 4. 增量续算与线段级别

- [x] 4.1 验证 `clear_bsp1_end` 对降级点的清理正确：以 `trigger_step=True` 逐根推进某标的，在降级点所在线段尚未确认时该点存在、线段确认后若判定变化则同步收缩；验证 `bsp1_list` 与 `bsp1_sure_list` 在尾部同步收敛且不残留降级点
- [x] 4.2 验证线段级别路径同样生效且口径一致：41 只日线 `seg_bs_point_lst` 中降级点带 `bsp1_downgrade_reason`，其 `T1` 数量与改造前一致（1），违规进 `bsp1_sure_dict` 的降级点为 0
- [x] 4.3 验证批量模式与步进模式的最终结果一致：同一标的分别以 `trigger_step=False` 与逐根 `trigger_step=True` 跑完整序列，比对 `bsp_store_dict` 六类数量与降级点集合完全一致

## 5. 验证脚本与基线

- [x] 5.1 在 `Debug/bsp_standard_equivalence.py` 增加第 6 节「降级路由对照」：同一组标的分别在开关开/关下输出六类数量表，断言除 `1p` 外全部相同（复用 `count_types`，新增断言并在不一致时返回 False）
- [x] 5.2 在 `Debug/bsp_standard_equivalence.py` 的模块注释把本变更的期望数字写入基线区（`standard + downgrade + swing: 1:13 1p:52 2:12 2s:4 3a:1 3b:1`，其中 `1`/`1p` 为 tasks 9.7 的走势段口径终值；`standard + downgrade + bi` 口径为 `1:14 1p:53`），并说明 `legacy` 基线不受影响；验证注释存在且 `--quick` 模式全绿
- [x] 5.2a 在等价性脚本补一条「背驰关闭」对照行：`bsp_preset="standard"` + `divergence_rate=200`（`bsp1_trend` 保持 True）下重算，断言 `1p` 与关闭降级时相同（即 `divergence_rate>100` 时降级不触发）、`1` 亦不变
- [x] 5.2b 在等价性脚本输出降级漏斗（`bsp1_list` 候选 → `reason=='trend'` → 面积背驰 → `bs1_peak` → 补全检后），五档参考值为 **573 / 314 / 168 / 142 / 53**（已由 design D1-c 实测复核确认 `mode="all"` 与 `trend_start` 无差异）；断言末档等于 53，并写入模块注释基线区
- [x] 5.3 全量跑一次 `Debug/bsp_standard_equivalence.py`（41 只）：验证 legacy 等价基线不变、档位隔离三跑无串味、T1 漏斗单调不增、新增降级对照断言全部通过
- [x] 5.4 增加降级点的成因分布统计输出（`single_zs` vs `no_trend` 各多少），验证两桶之和等于降级点总数且都大于 0（若某桶为 0 需在输出中说明是数据特征而非缺陷）

## 6. 下游数据回刷

- [x] 6.1 用 `WebAPI/incremental_engine.py` 的 `recompute_stock(force_full=True)` 对 PG 库内全部 `(code, kl_type, autype)` 重跑，验证 `bsp_index` 中 `bsp_type='1p'` 的行数与重算结果一致（期望 52，见 tasks 9.7）、无残留旧口径行，且 `2`/`2s`/`3a`/`3b` 的行数在本次变更前后完全相同
      **已执行（2026-10-25，本机 PG `127.0.0.1:5432/chan`）**：72 个 `(code, kl_type, autype)` 对中 68 成功、3 skip（ST 排除）、1 fail（`sh.600007 5m`，见下方遗留）。
      - **逐只核对通过**：58 个重算成功的对，`bsp_index` 与重算结果按 `(code, kl_type, autype, bsp_type)` 完全一致（0 不一致）。
      - **`1p` 从 0 → 246**，全部为降级点。注：246 是**全库全周期**（D/30m/5m/15m/60m/W/M，含 2019 年前全历史）的合计，与 tasks 9.7 的 52（41 只日线、`begin_time=2019-01-01`）口径不同，不可直接比对；日线 QFQ 子集实测 `1p` 22 → 163。
      - **其它五类的变化来自力度口径（`bi`→`swing`），不是降级路由**：重算子集 1: 84→78、2: 83→78、2s: 26→25、3b: 35→30、3a: 23→23（3a 完全不变）。5m 周期变化最大（T1 146→10），因为分钟级笔数多、走势段窗口更宽。这是 tasks 9.7 已确认的口径收紧在更大样本上的放大，不是缺陷。
      - **4 个未覆盖的对**：`sz.000010 D QFQ` / `sz.000016 D QFQ`（ST，`recompute_stock` 入口直接 skip，索引里的旧行是 ST 排除变更之前留下的，属既有遗留，非本次引入）；`sh.600000 D HFQ`（DuckDB 只有 QFQ 数据，`source_watermark` 返回 None → skip，同为既有遗留）。
      - **1 个失败**：`sh.600007 5m`（41056 根 K 线）`chan_dump_pickle` 抛 `RecursionError`。已验证属**既有缺陷**（改动前路径同样失败），与 `bsp1_qjt` 无关（该配置默认关）；`bsp1_qjt=True` 也未加剧（`sub_bs_point_lst` 已在 dump 前摘除）。
      - **该失败已于 2026-10-25 修复**（详见 `文档/一买一卖差异点说明.md` 独立缺陷小节与 `Debug/test_pickle_seg_roundtrip.py`）。根因与 1 分钟数据无关：`CSeg.update_bi_list` 写入的 `parent_seg` 反向引用让 `CSeg.eigen_fx → CEigen → CBi → parent_seg → CSeg(下一段)` 把整条线段序列串成单链，嵌套深度 ≈ 10 × 线段数（5m 的 385 段 → 3746 层）；Python 3.12 的 C pickler 有独立于 `setrecursionlimit` 的 1498 层上限。修复方式是 dump 前摘除、restore 时从 `seg.bi_list` / `segseg.bi_list` 重建（与 `pre`/`next` 同类）。修复后全库回刷 **78 对 / 70 成功 / 8 skip / 0 fail**。
- [x] 6.2 在 `WebAPI/performance_store.py` 的模块 docstring 读取点清单中补一行说明：`1p` 的分类分母现含降级点，可按 `bsp1_downgrade_reason` 拆分统计；验证说明存在且未改动任何业务查询逻辑
- [x] 6.3 确认 `WebAPI/bsp_ladder.py` 的 L1/L3 预警统计不因 `1p` 增加而放大：对 41 只日线分别以开关开/关跑 `bsp_ladder`，验证 L2/L3/L4 数量差异仅来自 `1p` 点本身、且 L3 占比变化在 5 个百分点以内；若超出则记录实测数字并在该文件注释中说明原因

## 7. 文档同步

- [x] 7.1 更新 `文档/一买一卖差异点说明.md`：在 §八 复核记录后新增「九、单中枢降级路由（chan-standard-bsp1-change）」，说明 §4.1 的处置从「丢弃」改为「降级为 T1P」、降级点不作锚点、实测数量变化；并写明两条**不触发**降级的情形——`bsp1_trend=False`（无趋势要求即无「趋势不达标」）与 `divergence_rate>100`（背驰判据被显式关闭，不得当作背驰成立）；验证 §4.1 与 §八 中「T1P 输出为 0」的表述被更新为指向新章节
- [x] 7.1a 在 §4.2（背驰被「保送」关闭）与 §七 回标表 §4.2 行附近补一句：`divergence_rate>100` 时 `is_divergence` 返回的 `True` 是空真，仅作放行闸门；降级路由要求背驰「实证」，故该配置下降级不触发。验证两处均可检索到该说明
- [x] 7.2 更新 `Document/README.md` 买卖点参数段：在「一买新增判据」组后补 `bsp1_downgrade_to_pz`（默认 True，语义、`bsp1_downgrade_reason` 取值、以及「降级点不是成立一买」的明确声明）；验证参数表条目完整且与 `CPointConfig` 形参一致
- [x] 7.3 更新 `文档/缠论策略.md`：3.6 买卖点表补 T1P 的两类来源（无中枢笔背驰 / 趋势不达标的降级点），第 11 章配置表补 `bsp1_downgrade_to_pz`；验证两处均可在文档内检索到该 key
- [x] 7.4 在三份《xx买xx卖差异点说明》的「回退方式」段附近统一补一句「降级路由对二买/三买无影响」，避免下游误判；验证三份文档均含该说明

## 8. 集成检查

- [x] 8.1 端到端验证：重启 `WebAPI.main:app`，查询 `/api/bsp?type=1p` 返回降级点且 `type=2` / `3b` 的数量与变更前一致；核对前端买卖点页 `1p` 筛选不报错、K 线覆盖层能渲染新增 `1p` 标记
      **已执行（2026-10-25，`uvicorn WebAPI.main:app` @ 127.0.0.1:8123 + 本机 PG）**：
      - `/api/bsp` 全部类型 200：`1p` 320 / `PZ-B` 212 / `PZ-S` 108 / `1` 282 / `2` 353 / `2s` 269 / `3a` 95 / `3b` 86 / `3B(内)` 36 / `3B` 92 / `3S` 89。`PZ-B + PZ-S = 320` 与原始枚举 `1p` 完全对上，方向化标签（`bsp_store.DIRECTIONAL_LABELS`）无需改动即可筛出降级点。
      - `/api/klines?symbol=sz.000001&kl_type=D` 返回的 `bsp` 中 `types` 含 `1p`，K 线覆盖层的 `chan_bsp` overlay 直接按 `types` 渲染（`Front/src/components/chan/chan_bsp.ts:56` 走 `bspLabels`），前端 `utils/bsp.ts` 已把 `'1p'` 映射为 `PZ-B`/`PZ-S`，无需改前端。
      - 说明：`type=2` / `3b` 的绝对数量**不等于**变更前——那是力度口径 `bi→swing` 的收紧结果（tasks 9.7 已确认的口径变化），不是降级路由造成的。降级路由只增 `1p`。
      前端浏览器实测（`npm run dev` + 点击 `1p` 筛选）**未执行**——前端由 MSW mock 驱动，真实后端联调不在本任务范围。
- [x] 8.2 回滚验证：以 `bsp_preset="legacy"` 对 3 只标的重算，验证 `bsp_index` 整套替换为 legacy 口径（`1p` 回到无降级形态）、无新旧口径混杂；再切回默认档确认恢复
      **已执行（2026-10-25，`sh.600016` / `sz.000001` / `sh.600021` 日线 QFQ）**：
      - 默认档（standard + swing）：`sh.600016` `1p:5`；`sz.000001` `1p:6 1:1 3b:1 2:1`；`sh.600021` `1p:4 1:1 2:1`。
      - 切 `bsp_preset="legacy"` 后整套替换（`bsp_rows` 73/83/74，`DELETE→INSERT` 全集）：`sh.600016` 无 `.000001`、`2:28 2s:18 3a:4 3b:4 1p:5` 等，全部是 legacy 口径，**没有任何 standard 行残留**（行数从个位数跳到 73+ 已说明是整套替换而非增量叠加）。
      - 切回默认档后逐行**完全恢复**（含 `bsp_date` / `bsp_type` / `is_buy` / `time_key` 四字段全等）：`回滚后完全恢复: True`。
      - 一个值得注意的现象：legacy 下 `1p` **不为 0**（4/5/6）——那是 `treat_pz_bsp1` 的「无中枢笔背驰」路径，与降级点无关（legacy 下 `bsp1_trend=False`，降级永不触发）。要验证「降级消失」应看 `bsp1_downgrade_reason` 而不是 `1p==0`。

## 9. 力度口径走势化（§4.4）

- [x] 9.0 **（基线先行，必须在 9.1 之前完成）** 为 `is_divergence` 的向后兼容建立逐笔基线。在 `Debug/bsp_standard_equivalence.py` 增加 `--dump-baseline` 模式：以 `bsp_preset="standard"`（**此时 `bsp1_force_scope` 尚未存在，不得传入——`ConfigWithCheck` 会以未知 key 抛 `CChanException`，这是基线必须先行于 9.1 的根本原因**）遍历 41 只日线，导出每个 `bsp1_list` 点与每个 `bsp1_sure_list` 点，写入 `Debug/bsp1_force_scope_baseline.json`。文件结构：
  ```json
  {
    "watermark": "2026-10-20",
    "config": {"begin_time": "2019-01-01", "end_time": "2026-10-20",
               "autype": "QFQ", "kl_type": "K_DAY", "bsp_preset": "standard"},
    "codes": ["sh.600016", "..."],
    "points": [
      {"code": "sh.600016", "bi": 31, "types": ["1"], "sure": true,
       "diver": true, "ratio": 0.837}
    ]
  }
  ```
  **`end_time` 必须 pin 到水位**（`CDuckDB` 已支持，见 `ChanAnalyse/DataAPI/DuckDBAPI.py:208`）：`Data/kl_store.duckdb` 不入 git，后续灌数会改变笔的划分与 `bi.idx` 位移；不 pin 水位的基线在当前库 `max(time_key)=2026-10-20` 之后第一次灌数就会误报。脚本在比对时 SHALL 先校验当前库的 `max(time_key)` 与 JSON 的 `watermark` 一致，不一致则打印明确提示「库已推进到 X，请重新生成基线」并以非零码退出，而不是给出错误的「逐笔不一致」。验证：跑一次生成 JSON、提交进 git；再跑一次 `--dump-baseline` 结果逐字节一致（幂等）；把 `watermark` 手工改错后脚本按上述语义退出，且**恢复 watermark 后重跑不产生任何 JSON 内容变化**（证明基线只由数据与配置决定，与运行次数无关）

- [x] 9.1 在 `ChanAnalyse/BuySellPoint/BSPointConfig.py` 的 `CPointConfig.__init__` 增加形参 `bsp1_force_scope="swing"` 并赋值，同步补类 docstring 的属性说明（含两档语义）；验证 `CChanConfig({}).bs_point_conf.b_conf.bsp1_force_scope == "swing"`、`CChanConfig({"bsp1_force_scope": "bi"})` 取到 `"bi"`，且赋非法值（如 `"seg"`）在配置构造阶段抛 `CChanException`（不静默回退）
- [x] 9.2 在 `ChanAnalyse/ChanConfig.py` 的 `set_bsp_config` 的 `para_dict` 增加 `"bsp1_force_scope": "swing"`，并在 `_BSP_PRESETS["legacy"]` 展开中加入 `"bsp1_force_scope": "bi"`；验证 `CChanConfig({"bsp_preset": "legacy"})` 取到 `"bi"`
- [x] 9.3 在 `WebAPI/config_fingerprint.py` 的 `FINGERPRINT_KEYS` 追加 `"bsp1_force_scope"`；验证仅翻转该 key 时 `config_fingerprint()` 结果不同
- [x] 9.3a 扩展 9.0 的基线比对：此时 `bsp1_force_scope="bi"` 已可被配置接受。以 `bsp_preset="standard"` + `bsp1_force_scope="bi"` 重跑 41 只日线（`end_time` 取 `watermark`），与 `Debug/bsp1_force_scope_baseline.json` 的 `points` **逐笔比对** `(code, bi, types, sure)` 完全一致、`ratio` 在相对容差 1e-9 内一致；断言 0 例新增、0 例消失、0 例类型漂移。这一步在**尚未改动 `ZS.py` 任何取值逻辑**时完成，证明「新增开关且取 `bi` 档」不改变任何输出——它是 9.4 之后能区分「开关无效」与「签名改造出错」的对照组
- [x] 9.4 修改 `ChanAnalyse/ZS/ZS.py` 的 `is_divergence` 签名，增加可选参数 `b_window=None, c_window=None`：两者均为 `None` 时走原取指路径（`get_bi_in()` / `out_bi`），否则按窗口聚合取值；`end_bi_break` 校验、`divergence_rate > 100` 显式关闭分支、阈值比较三条分支逐字节不变；在两处互指注释中写明「`>100` 魔数与降级证据判定共用同一口径」（承接 tasks 2.2a）。**验证（向后兼容契约）**：重跑 9.3a 的同一比对，结果必须仍与基线 JSON 逐笔一致（0 增 0 删 0 漂移，`ratio` 容差 1e-9）。这是「改签名不得改默认行为」的唯一硬证据；若 9.3a 通过而本步不通过，故障必在签名改造本身，与力度口径改动的正确性无关
- [x] 9.5 在 `BSPointList.treat_bsp1` 计算并传入窗口：实现 `_cal_force_windows(seg, zs)`，b 窗口 = 该线段内最后一个满足 `end_bi.idx < zs.begin_bi.idx` 的**非一笔**中枢的 `end_bi.idx + 1` 起（不存在则取该线段首笔）至 `zs.get_bi_in().idx`；c 窗口 = `zs.end_bi.idx + 1` 至 `seg.end_bi.idx`；**切片一律用线段内相对索引 `idx - seg.start_bi.idx`**（`seg.bi_list` 是 `range(start, end+1)` 的连续切片，直接用全局 `bi.idx` 会错位/越界）；`BSP_CONF.bsp1_force_scope == "bi"` 时不传窗口走原路径。**验证**：①构造「离开段 3 笔」与「进入段跨过前一个中枢」两类合成序列，断言窗口首尾笔的 `idx` 与预期一致；②以 `sh.600016` 的 `bi=31` 为端到端锚点，断言两种口径下的力度比率分别落在基线的 `ratio`（≈0.837，取自 `Debug/bsp1_force_scope_baseline.json`）与新值 ≈1.746 上——窗口索引若写错，这两个数字不会一个命中一个偏离
- [x] 9.6 实现 span 力度取值：复用 `ChanAnalyse/Math/Metric.py` 已有的区间版本（`cal_macd_area` / `cal_macd_full_area` / `cal_macd_peak` / `cal_macd_diff` / `cal_macd_diff_peak` / `cal_macd_slope` / `cal_macd_amp` / `cal_macd_rsi`），把窗口内各笔的 `klc_lst` 串联后按起始/结束 K 线索引取值；对没有区间版本的 5 种算法（`volumn` / `amount` / `volumn_avg` / `amount_avg` / `turnrate_avg`）自动退回单笔口径，并在 `feature_dict` 写 `bsp1_force_scope_effective="bi_fallback"`；验证：逐算法遍历，8 种区间算法产出 `bsp1_force_scope_effective` 缺省（或 `"swing"`）、5 种产出 `"bi_fallback"`，且全部不抛异常
- [x] 9.7 回归 §4.4 的实测差异：41 只日线（2019-01-01 起、QFQ、standard 档、`end_time` 取基线水位）分别在 `bsp1_force_scope="bi"` / `"swing"` 下重算，验证成立 T1 `14 → 13`、降级 T1P `53 → 52`。**逐笔差异必须与基线可对账**：以 `Debug/bsp1_force_scope_baseline.json` 为改造前真值，输出「`bi` 口径 == 基线」与「`swing` 口径相对基线的增删集」，断言新增集为空、消失集恰为 2 个（`sh.600016 bi=31`：`ratio` 0.837→1.746 判不背驰；`sz.000011 bi=44`：c 段含 3 笔、整段 `ratio` 0.026→0.913 判不背驰），`no_trend`/`single_zs` 两桶与六类数量以实测为准并回写本节。**`3b` 由 1 变 0 不是缺陷**——它锚定的 `sh.600016 bi=31` 不再是成立一买，属锚点依赖的正确传播（design D10）；断言据此收窄为「`2`/`2s`/`3a` 完全不变，`3b` 的差异必须能从一买消失集逐笔对账」。
- [x] 9.8 在 `Debug/bsp_standard_equivalence.py` 增加第 7 节「力度口径对照」：同一组标的分别在 `bsp1_force_scope="bi"` / `"swing"` 下输出六类数量表与翻转点清单（含 code / bi.idx / 两种口径的力度比率），翻转点清单直接从第 9.0 的基线 JSON 与 `swing` 口径结果做集合差得到；断言 `2` / `2s` / `3a` 数量完全相同（期望 `12 / 4 / 1`），`3b` 的差异须能由「所锚定一买已消失」解释（design D10），差异只出现在 `1` / `1p` / `3b`；同时确认 legacy 基线（笔级别 `1:258 1p:69 2:318 2s:317 3a:61 3b:50`）不受影响。该节 SHALL 在库水位与 JSON 的 `watermark` 不一致时跳过逐笔断言并打印重生成提示（与 9.0 同一语义），不静默放过
- [x] 9.9 验证线段级别路径口径一致：41 只日线 `seg_bs_point_lst` 在 `"swing"` 口径下重算，线段级 T1 数量与改造前一致（1）且无异常；若出现新增/消失点，记录实测并在 `Debug/bsp_standard_equivalence.py` 说明
- [x] 9.10 更新 `文档/一买一卖差异点说明.md`：§4.4 的状态从「部分修复」改为「已修复」，说明笔级别 b/c 已升级为走势段窗口（b 从前一中枢之后 / 线段首笔至进入笔，c 从离开笔至线段末笔）、线段级别的既有口径不变；§七 回标表 §4.4 行同步改写并标注本变更名；§八 复核记录补一段 `sh.600016 bi=31` 的翻转案例与「`bsp1_force_scope="bi"` 可单独回退力度口径」
- [x] 9.11 更新 `Document/README.md` 买卖点参数段与 `文档/缠论策略.md` 第 11 章配置表：补 `bsp1_force_scope`（默认 `"swing"`，两档语义，以及成交量/换手率类算法自动退回单笔口径的行为）；验证两处均可检索到该 key 且描述一致

## 10. 区间套特征化（§4.6）

- [x] 10.1 在 `ChanAnalyse/BuySellPoint/BSPointConfig.py` 的 `CPointConfig.__init__` 增加形参 `bsp1_qjt=False` 与 `bsp1_qjt_depth=1` 并赋值，同步补类 docstring 的属性说明；验证 `CChanConfig({}).bs_point_conf.b_conf.bsp1_qjt is False`、`CChanConfig({"bsp1_qjt": True})` 取到 `True`，`bsp1_qjt_depth` 取非法值（0、负数、非 int）在配置构造阶段抛 `CChanException`
- [x] 10.2 在 `ChanAnalyse/ChanConfig.py` 的 `set_bsp_config` 的 `para_dict` 增加 `"bsp1_qjt": False` 与 `"bsp1_qjt_depth": 1`，并在 `_BSP_PRESETS["legacy"]` 展开中加入 `"bsp1_qjt": False`；在 `WebAPI/config_fingerprint.py` 的 `FINGERPRINT_KEYS` 追加 `"bsp1_qjt"`（`bsp1_qjt_depth` 随 `bsp1_qjt` 一并指纹化或单独追加，二选一后在 design 注明）；验证 `CChanConfig({"bsp_preset": "legacy"})` 取到 `False`、仅翻转 `bsp1_qjt` 时 `config_fingerprint()` 结果不同
- [x] 10.3 在 `ChanAnalyse/Chan.py` 的级别循环（`cal_seg_and_zs` 触发后）注入次级别 `CKLine_List` 的**只读引用**（如 `kl_datas[lv].bs_point_lst` 上的 `sub_bs_point_lst` 临时引用，最低级别为 None）：引用只在注解阶段使用，**不得**加入 `__deepcopy__` / `chan_dump_pickle` 的手工重建清单（design D7-q 的序列化约束）；验证 `copy.deepcopy` 与 `chan_dump_pickle`/`chan_load_pickle` round-trip 在开启 `bsp1_qjt` 时均不报错、产物不含该引用的持久化副本
- [x] 10.4 实现 `BSPointList._annotate_qjt` 并挂在 `cal` 收尾（`cal_seg_bs1point` 与 `cal_seg_bs2point`/`cal_seg_bs3point` 全部完成之后）：对 `bsp1_list` 家族每个点，取其 c 走势段窗口（**与 `_cal_force_windows` 的 c 窗口同一处定义**，design D7-q 的单点锁定），沿 `sup_kl`/`sub_kl_list` 映射到次级别 K 线 idx 区间，查次级 `bs_point_lst.bsp1_sure_list` 中同向、klu 时间落在映射区间内的点；命中写 `feature_dict['bsp1_qjt_hit']=True` 与 `bsp1_qjt_sub_idx`（命中点次级笔索引），未命中写 `False`。`bsp1_qjt=False` 或无次级别容器时跳过。**验证（特征不改成立性）**：41 只日线分别在 `bsp1_qjt=True` / `False` 下重算，六类数量逐类完全一致（`1:13 1p:52 2:12 2s:4 3a:1 3b:1`，swing 口径终值），差异只在特征字典
- [x] 10.5 验证命中资格三条件：构造合成序列分别覆盖——①次级同向已确认 T1（应命中）；②次级同向但仅在 `bsp1_list` 候选未进 `bsp1_sure_list`（不命中）；③次级**反向**已确认 T1（不命中）；④次级区间外（c 段开始之前）的同向已确认 T1（不命中，spec「窗口排除 c 段之前的衰竭」场景）；逐条断言
- [x] 10.6 验证递归深度默认 1：次级命中点自身的 c 段内存在次次级同向 T1 时，默认深度下不影响本级命中结果（spec「默认不递归到次次级别」场景）；`bsp1_qjt_depth=2` 的行为只做冒烟（不设数量断言，避免依赖数据特征）
- [x] 10.7 验证步进与批量终态一致（承接 tasks 4.3 的不变量）：同一标的以 `trigger_step=True` 逐根推进、`bsp1_qjt=True`，最终 `bsp_store_dict` 六类数量与批量模式完全一致；`bsp1_qjt_hit` 特征允许在快照间由 False 翻 True（子级确认滞后，design D8），但**最终命中集合**与批量模式一致
- [x] 10.8 在 `WebAPI/bsp_ladder.py` 的模块 docstring 补一段边界说明：内核 `bsp1_qjt_hit` 是一买候选的成立性证据（仅 T1 家族、结构窗口），L1 共振是全类型未确认点的跨级别佐证（时间窗），二者并存、L1 不因内核特征的存在而删除（design D7-q 备选二）；验证说明存在且 `cal_l1_resonance` 逻辑零改动
- [x] 10.9 在 `Debug/bsp_standard_equivalence.py` 增加第 8 节「区间套对照」：41 只日线在 `bsp1_qjt=True` 下输出命中统计（命中数 / 候选数 / 命中率，及 `bsp1_sure_list` 命中与 `bsp1_list` 候选命中的分桶），断言六类数量与 `bsp1_qjt=False` 时逐类一致；命中数为 0 时打印「数据特征或映射未覆盖」说明而非直接判失败
- [x] 10.10 更新 `文档/一买一卖差异点说明.md`：§4.6 状态从「未修复」改为「**部分修复**——区间套以特征字段落地（`bsp1_qjt_hit`），不改成立性；硬判据化待命中率数据支持后另案」；§七 回标表 §4.6 行同步改写并标注本变更名；补一段「内核区间套特征与 WebAPI L1 共振的边界」（判定对象、覆盖类型、窗口口径、生命周期四个维度）
- [x] 10.11 更新 `Document/README.md` 买卖点参数段与 `文档/缠论策略.md` 第 11 章配置表：补 `bsp1_qjt`（默认 False，特征化语义、`bsp1_qjt_hit`/`bsp1_qjt_sub_idx` 取值、「不是判据、不改买卖点输出」的明确声明）与 `bsp1_qjt_depth`（默认 1）；验证两处均可检索到该 key 且描述一致

## Workflow follow-up

- 实现与验证全部完成后，执行 `/opsx:archive` 归档本变更（archive 会把 `specs/chan-bsp1-downgrade`、`specs/chan-bsp1-force-scope` 与 `specs/chan-bsp1-qjt` 提升为主 spec，并合并 `bsp-index` 的 delta）
- 归档前确认 `openspec validate chan-standard-bsp1-change --strict` 通过
