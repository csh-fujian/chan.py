# Design: chan-bsp-ladder-change

## Context

见 proposal.md 的 Why。本设计要解决的技术约束（均来自对当前代码的只读核查，2026-10-25）：

- **阶梯推导的现位置在 WebAPI 层**：`WebAPI/bsp_ladder.py` 的 `cal_ladder` 被 `incremental_engine`（落库）与 `serializer`（/api/klines）双链路调用，`bsp_sure.bsp_is_sure` 是 L4 的水位线口径。既有 spec 约束「级别判定 SHALL 在 WebAPI 层完成，不修改缠论计算内核」——三轴推导必须延续这个位置，否则触碰内核成立性链路。
- **判据链进度的信息已存在但未结构化**：`check_bsp1_standard`（`BSPJudgement.py:148-188`）返回 `(ok, reason, info)`，`reason` 是首个不通过的判据名（短路）。由 `reason` 可推导「通过到第几项」，但：四项判据（trend/new_extreme/dif_div/zero_axis）的顺序与②③（`end_bi_break`/`out_bi_is_peak`）④（`is_divergence`）**不在同一函数内**——②③④在 `treat_bsp1` 里先跑，四项判据在 `check_bsp1_standard` 里后跑。进度轴的「①~⑦」需要把两段拼接成统一序号。
- **分型三根合并 K 线的实体口径**：分型检测在 `CKLine_Combiner.update_fx(pre, fx, next)`，合并 K 线持有全部原始 K 线（`lst`）。实体上沿 = 合并 K 线内全部原始 K 线的 `max(open, close)` 取最大（口径 (a)，待确认默认）。
- **佐证轴的窗口与命中资格已有单点实现**：内核 `bsp1_qjt_hit` 的 `_c_window_of`/`_sub_time_span`（结构映射）与 `bsp1_sure_list`（已确认资格）。L2-3 直接复用；L2-2/L2-1 需要子级**候选**信息（`bsp1_list`）与子级**末端分型**——这两者内核特征没有，须在 WebAPI 层从子级 `CChan` 对象只读推导。
- **落库链路已有子级计算钩子**：`incremental_engine` 的「主级别算完后补算子级」（D3 修订）已在做 D→30m/W→D/M→W 的子级 `CChan` 计算（`main.py:161`），serializer 链路有 `sub_chan`。佐证轴需要的子级容器在这两条链路上都已就绪，无需新建基础设施。
- **PG 列宽**：`bsp_store._ensure_tables()` 建的 `bsp_index.ladder VARCHAR(2)`（`bsp_store.py:114`）；DDL 规范要求惰性 DDL 先行 + `update-win.sql` 幂等记录。
- **存量语义反转**：旧 L1（时间窗共振）/L2（虚笔兜底）/L3（逐笔背驰预警）与新三轴值完全异义，不可增量迁移。

## Goals / Non-Goals

**Goals:**

- 三轴阶梯推导落在 WebAPI 层，双链路（落库/序列化）口径单点锁定
- 进度轴以判据链短路信息为唯一事实源，不重复实现判据
- 佐证轴沿结构映射窗口，L2-3 与内核 `bsp1_qjt_hit` 同口径；时间窗口径彻底退役
- 分型强弱为纯只读函数，不改 `update_fx`、不改笔/分型检测
- T1P 力度口径走势段化（内核 `treat_pz_bsp1`），与 T1 的 swing 口径同构
- 非一买类型 NULL 过渡；全量回刷清旧值
- 笔级别与线段级别（泛型同构）自动双覆盖

**Non-Goals:**

- 不为二买/类二/三买定义三轴判据链（后续变更逐类型接入）
- 不改 `check_bsp1_standard` 的四项判据实现与短路顺序（进度轴只消费其返回值）
- 不改 `bsp1_qjt` 内核特征的行为（特征化语义、指纹、深度默认全部不动）
- 不做佐证轴多层递归（沿用 depth=1；L2-2 的子级进度评估只看子级单层）
- 不做「判据链全过但未确认」之外的新确认语义（L4 水位线口径不变）
- 前端不做仓位指引的计算化（纯展示文案，沿用 bsp-ladder-change 的 Non-Goal 边界）

## Decisions

### D1：进度轴 = 判据链统一序号的短路位置，信息源为 `treat_bsp1` 现有计算

**做法**：定义七项统一序号：①`check_trend` ②`end_bi_break` ③`out_bi_is_peak` ④`is_divergence`（swing 窗口）⑤`check_new_extreme` ⑥`check_dif_divergence` ⑦`check_zero_axis`。进度 = 已通过的最大序号。推导分两段拼接：

- ②③④的结果 `treat_bsp1` 内已有（`break_peak`/`is_diver` 及前置的 `end_bi_break`），但**不在返回值里**——把三项结果追加进 `feature_dict`（`bsp1_judged_steps` 或逐项布尔），落库后 WebAPI 层从 feature 读取。
- ①⑤⑥⑦从 `standard_reason` 反推（`reason='trend'`→进度0；`'new_extreme'`→④已过；……`None`→全过）。`check_bsp1_standard` 的 reason 集合是闭集，反推表是纯函数。

分档：进度 ≤4 → L1；5~7 或全过 → L2。

**T1P 路径**：`treat_pz_bsp1` 无判据链可跑，进度轴从 feature 中可评估的项计（判据近似：同段同向 = ①的弱形式、创新低 = ⑤、力度背驰 = ④）。无法评估时进度轴不携带标签。

**备选：在内核新增独立的进度计算函数**。否决——重复实现判据逻辑，两处漂移；feature 透出是零成本路径（`treat_bsp1` 本来就在构造 `feature_dict`）。

**备选：WebAPI 层重跑判据链**。否决——`check_bsp1_standard` 需要 `seg.bi_list`/`zs_lst` 等内核对象，WebAPI 层持有 `CChan` 可做到（serializer 链路有），但双链路各自重跑会漂移，且重复计算量不小。

**风险**：`feature_dict` 的键名是 WebAPI 与内核的隐式契约——在 `文档/缠论策略.md` 判据表同步处登记键名，防止后续变更改键不通知下游。

### D2：分型强弱 = 独立只读函数，输入三根合并 K 线，WebAPI 层调用

**做法**：新增 `WebAPI/fractal_strength.py`（或并入 bsp_ladder.py 模块），`classify_fx(pre, fx, next, is_buy) -> 'L3-3'|'L3-2'|'L3-1'|None`。实体口径 (a)：`X_max = max(原始K.open, 原始K.close for X 内全部原始K)`。判据（买点侧底分型）：

```
L3-3:  C_max >  A_max
L3-2:  C_max >= (A_max + A_min) / 2   （含 C_max == A_max 的平边界）
L3-1:  其余
```

**取三根合并 K 线的路径**：候选点 `bsp.bi.get_end_klu()` 所在合并 K 线为 `fx`（B），其 `pre`/`next` 通过 K 线链表（`CKLine_Combiner` 的前后引用）取。末端分型未形成（笔延伸中、`next` 不存在或不是分型第三根）时返回 None。

**备选：口径 (b) 直接用合并 K 线 high/low**。否决——引入影线，L3-3 变成「超过前高」过严，与用户定义的实体语义不符（待确认项，若用户推翻则改此实现，接口不变）。

**备选：在内核 `CKLine_Combiner.update_fx` 里顺带计算**。否决——触碰分型检测本身，违反「WebAPI 层完成、不修改内核」的 spec 约束；且 update_fx 在特征序列（虚段）场景也被调用，会把强弱计算带进段算法路径。

### D3：佐证轴三档的推导位置与数据源

**做法**：`cal_ladder` 重写为 `cal_ladder_v2(bsp, bs_point_lst, sub_chan, kl_type, sub_kl_type) -> str|None`，三档按序短路：

- **L2-3**：子级 `bs_point_lst.bsp1_sure_list` 中同向已确认点落在结构映射窗口（复用 `_c_window_of` 的窗口语义；WebAPI 层复制该窗口计算——内核方法挂在 `CBSPointList` 上，WebAPI 可直接调用，只读）。
- **L2-2**：子级 `bsp1_list`（候选全集）中同向点落窗口内，且该点 feature 携带可评估进度 ≥1 档（其 `bsp1_judged_steps` 或 reason 反推在 L1 档）。
- **L2-1**：子级最后一笔的末端分型形成且同向（`classify_fx` 在子级末笔上评估，方向与父级候选点一致）。

**非一买类型直接返回 None**（不进三轴推导）。**`bsp` 无 `parent_seg`/窗口不可映射（如 30m 无 5m 子级）**：佐证轴跳过，只评估进度/分型轴。

**旧函数退役**：`cal_l1_resonance`/`L1_WINDOW_SECONDS`/`is_beichi_warning`/`_beichi_with_list` 删除；`ladder_of_legacy` 删除（存量行全量回刷后不存在无 ladder 解读路径——NULL 即合法值）。

**备选：保留时间窗作为结构映射不可行时的回退**。否决——用户明确「沿结构映射口径做」；结构映射不可行时佐证轴缺失（无标签）比错误的时间窗佐证更诚实。

**备选：L2-2 用子级 ladder 递归（子级自己算好的三轴）**。否决——递归引入子级确认滞后放大（design D8 的教训），L2-2 只读子级 feature 的进度信息，不做级联。

**验证补充（6.2，2026-10-25）**：⊇ 关系须在**候选全集**上比较——内核 `_cal_qjt_feature` 对 `bsp1_list` 全量写 `bsp1_qjt_hit`，含未成立、不进 `bsp_store_flat_dict` 的候选（sz.000001 日线 14 个候选只有 4 个落库，唯一命中点不在落库集合内）。在 `getSortedBspList()` 上比较会误报遗漏。佐证轴覆盖面天然更宽（与 `bsp1_qjt` 开关无关），反向放宽是预期行为。验证脚本：`Debug/bsp_ladder_qjt_equiv.py`。

**实现修订（6.4 部署演练发现）**：落库链路的父级 `CChan` 是**单级别**的（`_compute_full` 只 load 本级别，子级别由 `_compute_sub_for_l1` 独立计算），所以父级 K 线的 `sub_kl_list` 恒空，`_sub_time_span` 恒返回 `(None, None)`——佐证轴在生产落库路径上**永不生效**，日线 ladder 只剩两轴。这是实现与 D3 的偏离，spec Scenario 未覆盖。

**处置**：`_sub_time_span` 增加**回退口径**——无子级时间戳时改用父级 K 线自身的时间轴：左端取窗口首根父级 K 线时刻、右端取末根时刻外扩一个父级周期（相邻时间差的中位数）。c 窗口**边界**不变（仍是结构映射，唯一事实源），回退的只是「这个结构区间对应哪些次级别时间戳」的映射手段。外扩只会放大命中集，不会收窄，故仍满足「WebAPI 判定不窄于内核特征」——由 `Debug/bsp_ladder_qjt_equiv.py` 的 `check_ingest_path_window` 段断言（多级别结构映射与单级别回退窗的同一点集命中一致）。

**备选：落库链路改用多级别 `CChan`**。否决——`incremental_engine` 的快照/游标是**按单级别**存取的（`chan_snapshot` 主键含 kl_type），改成多级别会同时改快照格式、续算语义与全部存量快照的兼容性，代价远超收益。

### D4：T1P 力度口径走势段化——反向笔组分隔窗口

**做法**：`treat_pz_bsp1` 中，b/c 窗口按**同向笔组**划分：线段内 `seg.bi_list` 按方向交替分成组，末组（含 `last_bi`，全部同向）为 c 段；倒数第二组为 b 段（若不存在——线段只有一组同向笔——则 b 段为 `pre_bi` 单笔，退化为现状）。窗口内笔的 `klc_lst` 串联后走 `_span_metric`（与 T1 的 swing 完全同一取值函数）。`macd_algo` 不支持区间时退回单笔并标注 `bi_fallback`（同 D7-c 惯例）。

**镜像**：卖点侧 T1P 同构（顶分型/上涨笔组）。

**备选：b 段取线段起点到前前笔**。否决——线段内可能有多组同向笔组（下跌-反弹-下跌-反弹-下跌），「起点到前前笔」会把反弹段计入 b，稀释进入段力度。反向笔组分隔与 T1 的「上一中枢后~进入笔」语义同构（分隔物从中枢换成反向笔组）。

**BREAKING**：`1p` 行数变化（单笔→走势段口径），`bsp_index` 的 `1p` 行需全量回刷。`legacy` 档：`treat_pz_bsp1` 现无档位分支，本变更给 `legacy` 展开 `bsp1_force_scope="bi"` 已存在——T1P 复用同一开关（`bi` 时走旧单笔口径），无需新配置项。

### D5：数据库与落库

**做法**：`bsp_store._ensure_tables()` 的 `ladder VARCHAR(2)` → `VARCHAR(16)`（`ALTER TABLE ... ALTER COLUMN ... TYPE VARCHAR(16)` 幂等判断列宽后执行）；`update-win.sql` 追加同语句（本次变更在 Windows 机器上运行产生）。组合格式：`L1|L2-3|L3-3`（竖线分隔，轴顺序固定：进度→佐证→分型）。全量回刷靠既有「整套替换」机制——`config_fingerprint` 不覆盖 ladder 口径（非配置项），但本次 T1P 口径变化会经 `bsp1_force_scope` 已在指纹内的事实间接失效？否——`swing` 是默认档，开关值不变则指纹不变。**故回刷触发须显式**：部署后跑一次全量重算脚本（`incremental_engine` 的全量路径），或把「阶梯口径版本」追加进 fingerprint 常量。倾向后者（常量 bump，一次代码改动自动失效所有快照）。

**风险**：`VARCHAR(16)` 最长组合 `L2|L2-3|L3-3` = 13 字符，留 3 字符余量。若未来分型轴细分到 L3-4 或佐证轴 L2-4，仍够。

### D6：前端词表与展示

**做法**：`bspLadder.ts` 重写为三轴模型：

```ts
// 轴定义（进度轴是单值枚举，佐证/分型轴是档位枚举）
PROGRESS: L1(判据链前半链) / L2(后半链)
CORROBORATION: L2-3/L2-2/L2-1
FRACTAL: L3-3/L3-2/L3-1
parseLadder(raw: string|null): {progress?, corrobor?, fractal?} | 'L4' | null
```

- `BspView.vue` 级别列：`parseLadder` 结果渲染 1~3 个并列徽章（各轴一色系：进度蓝、佐证青、分型橙，L4 实色红），NULL → 「未定级」弱化。
- `KLineChart` tooltip / `chan_bsp.ts`：三轴区块说明，达成项高亮。
- MSW mock 数据补组合值样本（`L1|L2-1|L3-1`、`L2|L2-3|L3-3`、NULL 各档）。
- 仓位指引文案保留但重映射到进度轴（L1 观察仓 1/4 → L2 加仓 1/2 → L4 满仓；佐证/分型轴不映射仓位，纯证据说明）。

**风险**：`front/src/utils/bspLadder.ts` 是「前端唯一词表」的既有约定——三轴定义必须仍单点维护在该文件，KLineChart 与 BspView 都从这里 import，不得各自内联。

### D7：双链路口径单点

**做法**：三轴推导全部收敛在 `WebAPI/bsp_ladder.py`（重写后），`incremental_engine` 与 `serializer` 只传参调用（子级容器、kl_type 对）。与 `bsp_sure` 的既有模式一致（「集中放 WebAPI 层一处……保证两条链路口径不漂移」）。

**注解时机**（承接 chan-standard-bsp1-change D7-q 的坑）：佐证轴的子级结果必须先于父级 ladder 计算就绪。落库链路的「主级别算完后补算子级」顺序天然满足；serializer 链路的 `sub_chan` 先于主级序列化计算也已满足。无需引入 `_refresh_qjt` 式的两阶段。

## Risks / Trade-offs

- [进度轴依赖 feature 键名契约] → 在 `文档/缠论策略.md` 判据配置表登记 `bsp1_judged_steps` 键名与语义；`Debug/bsp_standard_equivalence.py` 增加键存在性断言。
- [佐证轴子级确认滞后导致快照间翻转（False→True）] → spec 已声明翻转不改变成立性；沿用 chan-standard-bsp1-change D8 的步进/批量终态一致性验证。
- [分型实体口径 (a) 在合并 K 线含多根原始 K 线时的语义模糊] → A/B/C 三根各自取「全部原始 K 线实体上沿的最大值」；文档写明该聚合规则；若用户推翻改口径 (b)，只动 `classify_fx` 单函数。
- [非一买类型 NULL 造成功能回退观感（原来有 L1/L3 标签）] → proposal 已声明方案 A；前端「未定级」弱化样式 + tooltip 说明「该类型暂未接入新阶梯」。
- [全量回刷量大（全股票全周期）] → 增量引擎的全量路径已有；回刷窗口选交易日结束后执行；fingerprint 常量 bump 保证不漏刷。
- [T1P 口径变化使 `1p` 行数下降（单笔→走势段更严）] → 预期行为（与 T1 的 swing 修复同向）；等价性脚本记录前后基线。

## Migration Plan

1. 部署顺序：内核 feature 透出 + WebAPI 三轴推导 + 前端词表，**同版本发布**（旧前端读不了新组合值）。
2. fingerprint 常量 bump → 全部快照失效 → 增量引擎对每只股票走全量重算路径 → `bsp_index` 整套替换（含 `ladder` 新值与 NULL）。
3. `update-win.sql` 追加 `ALTER COLUMN`（Windows 机器运行时）；Mac 侧由 `_ensure_tables()` 惰性补齐（列宽 ALTER 幂等）。
4. 回滚：代码回退 + fingerprint 常量再 bump（强制再次全量）→ 恢复旧口径落库。旧值已被替换，回滚后按旧口径重刷。

## Open Questions

- 分型实体口径 (a)/(b)（用户已在探索中倾向 (a)，标注待确认；不影响接口，只动 `classify_fx` 实现）。
- 非一买类型过渡方案 A/B（用户倾向 A=置 NULL；若推翻为 B=保留旧口径，需撤销 Non-Goal 的「旧口径不残留」条款并保留 `cal_l1_resonance`——影响 spec，须回探索）。
