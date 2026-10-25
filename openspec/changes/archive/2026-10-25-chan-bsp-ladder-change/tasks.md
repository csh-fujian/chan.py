# Tasks: chan-bsp-ladder-change

## 1. 内核：判据链进度透出（feature 契约）

- [x] 1.1 在 `ChanAnalyse/BuySellPoint/BSPointList.py` 的 `treat_bsp1` 中把 ②③④ 的判定结果（`end_bi_break`、`break_peak`、`is_diver`）以结构化键追加进 `feature_dict`（键名 `bsp1_judged_steps` 或逐项布尔，键名与 design D1 一致）；验证：`CChan` 默认配置跑任一日线，每个 T1/降级 T1P 候选点的 feature 都携带新键，且旧键（`divergence_rate`/`zs_cnt`/`bsp1_standard_reason`）不变
- [x] 1.2 写 `WebAPI/bsp_ladder.py`（或独立纯函数文件）内的「reason → 进度序号」反推表与两段拼接逻辑（②③④ feature + ①⑤⑥⑦ reason），输出进度值 0~7；验证：单元验证（内存构造 `feature_dict` + reason 组合）覆盖 `reason` 闭集（trend/new_extreme/dif_div/zero_axis/None）× feature 有无的 10 种组合，进度值全部正确
- [x] 1.3 `Debug/bsp_standard_equivalence.py` 增加「feature 键存在性」断言段：41 只日线全部 T1/1p 候选点携带 `bsp1_judged_steps`；六类数量与改动前逐类一致（feature 透出不改成立性）

## 2. 内核：T1P 力度口径走势段化

- [x] 2.1 在 `ChanAnalyse/BuySellPoint/BSPointList.py` 的 `treat_pz_bsp1` 中实现反向笔组分隔窗口（`seg.bi_list` 按方向分组，末组=c、倒数第二组=b，仅一组时退回单笔），力度取值走 `_span_metric`（与 T1 swing 同函数）；`bsp1_force_scope="bi"`（legacy 档展开）时走旧单笔口径；`macd_algo` 不支持区间时退单笔并写 `bsp1_force_scope_effective="bi_fallback"`；验证：内存构造「线段内两组同向笔、反弹段夹在中间」的用例，断言 b 窗口不含反弹笔、c 窗口为末组全部笔
- [x] 2.2 `Debug/bsp_standard_equivalence.py` 增加 T1P 口径对照行：41 只日线 `1p` 行数（单笔口径 vs 走势段口径）与 `legacy` 档等价基线不变（legacy 下 T1P 走 `bi` 口径，数量与改造前一致）
- [x] 2.3 更新 `文档/缠论策略.md`（判据变更同步约定）：T1P 力度口径章节、`bsp1_force_scope` 对 T1P 的作用说明、「面积背驰」统一改称「力度背驰」；验证：文档内检索 `treat_pz_bsp1` 与 `bsp1_force_scope` 均有新口径描述

## 3. WebAPI：分型强弱与佐证轴推导

- [x] 3.1 新增分型强弱分级函数（`classify_fx`：输入 pre/fx/next 三根合并 K 线与方向，输出 L3-3/L3-2/L3-1/None；实体口径 (a)：合并 K 线内全部原始 K 线 `max(open,close)` 取最大；含 `C_max == A_max` 平边界归 L3-2）；验证：内存构造三档各自的 K 线样本（含平边界、多根原始 K 线聚合、分型未形成三种边界），断言分类正确
- [x] 3.2 在 `WebAPI/bsp_ladder.py` 实现佐证轴三档判定（L2-3 复用内核 `bsp1_sure_list` + `_c_window_of` 窗口语义；L2-2 子级 `bsp1_list` 候选 + 进度在 L1 档；L2-1 子级末端分型同向）；三档互斥取最高命中；子级容器缺失时佐证轴跳过；验证：内存构造子级 `CChan` mock（已确认点/候选点/仅分型三种形态），断言各档命中与互斥顺序
- [x] 3.3 重写 `cal_ladder` 为三轴推导（`cal_ladder_v2`：进度轴 + 佐证轴 + 分型轴组合为竖线分隔字符串；非一买类型返回 None；L4 优先短路）；删除 `cal_l1_resonance`/`L1_WINDOW_SECONDS`/`is_beichi_warning`/`_beichi_with_list`/`ladder_of_legacy`；验证：grep 全仓无残留引用；`incremental_engine`/`serializer` 两处调用点改为新签名

## 4. WebAPI：落库与数据库扩容

- [x] 4.1 `WebAPI/bsp_store.py`：`_ensure_tables()` 的 `ladder` 列宽改 `VARCHAR(16)`（`ALTER TABLE ... ALTER COLUMN ... TYPE VARCHAR(16)` 幂等判断列宽后执行）；`update-win.sql` 追加该语句并注明执行时间；验证：对已存在的 `VARCHAR(2)` 旧表执行 `_ensure_tables()` 后列宽为 16，重复执行不报错
- [x] 4.2 `WebAPI/config_fingerprint.py`：阶梯口径版本常量 bump（design D5——ladder 口径非配置项，靠常量失效全量快照）；验证：同配置下新旧常量值计算的指纹不同
- [x] 4.3 `WebAPI/incremental_engine.py` 落库链路验证：fingerprint 失效 → 全量重算路径 → `bsp_index` 整套替换后 `ladder` 列取值为新三轴组合值/NULL/L4；41 只日线重刷后统计三轴分布（进度轴 L1/L2 计数、佐证轴各档计数、分型轴各档计数、组合值种类数）并与等价性脚本输出对齐

## 5. 前端：三轴词表与展示

- [x] 5.1 重写 `front/src/utils/bspLadder.ts`：三轴定义（PROGRESS/CORROBORATION/FRACTAL 枚举 + 各档名称/说明文案）、`parseLadder(raw)` 解析函数（L4/组合值/NULL 三态）、仓位指引重映射到进度轴；验证：单测（Vitest）覆盖 `L2|L2-3|L3-2` 解析、`L4`、NULL、非法值兜底
- [x] 5.2 `front/src/views/bsp/BspView.vue` 级别列改为按轴并列徽章（进度/佐证/分型各一色系，L4 单徽章实色，NULL「未定级」弱化，hover 各轴说明）；验证：MSW mock 数据补三轴组合值样本后页面渲染 1~3 个并列徽章，tooltip 文案与词表一致
- [x] 5.3 `front/src/components/chan/chan_bsp.ts` 与 `KLineChart.vue` tooltip：三轴区块说明、达成项高亮、NULL「未定级」兜底（含「该类型暂未接入新阶梯」说明）；验证：K 线页悬浮任一买卖点标记，tooltip 按组合值分轴展示且当前达成档高亮
- [x] 5.4 `front/src/api/types.ts` 的 ladder 类型从 `'L1'|'L2'|'L3'|'L4'` 改为 `string | null`（组合字符串）+ 前端解析层收窄；MSW handlers 同步；验证：`npm run build`（vue-tsc）通过

## 6. 集成验证与文档

- [x] 6.1 步进与批量终态一致（承接既有不变量）：同一标的 `trigger_step=True` 逐根推进 vs 批量模式，最终 `bsp_store_dict` 六类数量一致；`ladder` 组合值最终集合一致（允许过程中佐证/分型轴 False→True 翻转）；用 `Debug/bsp_qjt_step.py` 或新增脚本验证
- [x] 6.2 佐证轴 L2-3 与内核 `bsp1_qjt_hit` 同口径验证：开启 `bsp1_qjt` 的同一数据上，「佐证轴命中 L2-3 的点集合」⊇「`bsp1_qjt_hit=True` 的点集合」（WebAPI 判定不窄于内核特征）；差异点（如子级确认滞后）记录说明
- [x] 6.3 更新 `文档/一买一卖差异点说明.md`（§4.6 边界表——L1 共振行改写为佐证轴 L2-3 复用）与 `Document/README.md`（买卖点参数段 + ladder 三轴说明）；验证：两处均可检索到「三轴」「佐证轴」关键词且描述一致
- [x] 6.4 部署演练：Windows 本机跑 fingerprint bump → 全量重刷一只股票（sz.000001 日线）→ `psql` 查询 `bsp_index` 确认 ladder 列为组合值/NULL/`L4`，无旧 L1/L2/L3 单值残留；`update-win.sql` 在本机执行幂等

## Workflow follow-up

- 实现与验证全部完成后，执行 `/opsx:archive` 归档本变更（specs 的 `bsp-ladder-progress` 提升为主 spec，四个 MODIFIED delta 合并进 `bsp-index`/`bsp-page`/`kline-unsure-visual`/`chan-bsp1-qjt`）
