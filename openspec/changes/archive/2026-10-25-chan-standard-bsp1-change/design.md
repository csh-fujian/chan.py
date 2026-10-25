## Context

见 proposal.md 的 Why。本设计要解决的技术约束（均来自对当前代码的只读核查）：

- **降级点必须在 `treat_bsp1` 内部判定**。`cal_single_bs1point` 已经在 `bsp1_zs_extend_to_seg_end` 处做了 T1/T1P 的路由分流，但那条路由只区分「中枢是否延伸到线段末笔」，无法知道趋势判据的结果。趋势判据的结果只在 `treat_bsp1` 内产生（`check_bsp1_standard` 的 `reason`），因此降级只能在这里发生——而 `treat_bsp1` 拿不到 `bi_list`，只能拿到 `seg`（`seg.bi_list` 可用，`check_new_extreme` 用的正是它）。
- **`add_bs` 对 T1/T1P 有特批分支**：只要 `bs_type in [T1, T1P]`，无论 `is_target_bsp` 真假都会创建 `CBS_Point` 并进入 `bsp1_list`，且 `is_target_bsp=True` 时才进 `bsp1_sure_dict`。这意味着「降级点只落候选、不进成立集合」在现有 `add_bs` 上可以直接表达，但有一个陷阱：若同一笔先以 T1 登记为候选、后以 T1P 降级，`add_bs` 的 `exist_bsp` 分支会把「候选→成立」的升级逻辑跑一遍（索引 282-285 行），需要避免降级路径误触发该升级。
- **`treat_pz_bsp1` 不能用**：它的判据是「最后两笔同段、方向一致、创极值、逐笔背驰」，与降级点是两套完全不同的结构（降级点有中枢、比的是离开笔 vs 进入笔）。复用会同时改变既有 T1P 的输出。二者只能并列。
- **二买/三买锚点依赖 `bsp1_sure_dict`**（`treat_bsp2` 的 `real_bsp1`、`bsp2_follow_1`、`bsp3_follow_1` 的 `sure` 档、`relate_bsp1` 取值）。降级点绝不能进该字典。
- **配置指纹是白名单式的**：`WebAPI/config_fingerprint.py` 的 `FINGERPRINT_KEYS` 是显式元组，新增配置项必须手动加入，否则切开关不会使缓存失效。前一变更已在注释里写明该约束。
- **增量游标约束**：`cal` 只重算 `last_sure_seg_idx` 之后的线段，`clear_bsp1_end` 同步清理 `bsp1_list` 与 `bsp1_sure_list` 两个集合。降级点走同一集合，无需新增清理逻辑——但前提是它确实只进 `bsp1_list`。

## Goals / Non-Goals

**Goals:**

- 把「趋势不达标但背驰成立」的点以 T1P 身份保留，且**只增 `1p`，不动其余五类**
- 降级开关默认开启、可显式关闭、`legacy` 档自动关闭
- 下游可凭特征字段区分降级点与既有盘整背驰
- 增量续算、缓存指纹、档位回退三条既有机制零改动地继续成立
- **（第二部分）** 把一买力度比较的 b/c 口径从「单笔」升级为「走势段」，修复 §4.4；标准档默认生效，可单独回退

**Non-Goals:**

- 不让降级点参与任何「一买锚点」语义（这是本设计的核心边界，见 D2）
- 不改变 `check_bsp1_standard` 的四项判据及其短路顺序、不改 `treat_pz_bsp1`
- 不为降级点新增 `BSP_TYPE` 枚举值（遵守前一变更 Non-Goal）
- 不做「盘整背驰的后续确认」（如回抽中枢），那属于事后价格确认的既有未修复项
- 不在前端暴露降级成因标记（内核与 WebAPI 透出即可，前端按需后续）
- **（第二部分）** 不改 `check_zero_axis` 的零轴回抽判据（§4.5 另案）；不为成交量/换手率类力度算法新增区间版本，它们自动退回单笔口径
- **（第二部分）注意**：本设计**会**改变 T1 的力度口径（§4.4），这是对本变更初稿「不改 T1 判据」的**有意例外**——四项标准判据一字未动，改的是它们上游的 `is_divergence` 取值窗口。初稿 Non-Goals 的「不改 T1 判据」应理解为「不改四项标准判据」，见 D7

## Decisions

### D1：降级判定放在 `treat_bsp1` 内，用「背驰链路成立 + reason=='trend'」作为触发条件

**做法**：在 `treat_bsp1` 中保留现有计算（`break_peak`、`is_diver`、`check_bsp1_standard`），在决定 `add_bs` 的类型前插入一条判断：

```
peak_ok       ⇔  (not BSP_CONF.bs1_peak) or break_peak              # 放行语义
diver_proven  ⇔  is_diver and BSP_CONF.divergence_rate <= 100       # 证据语义
rest_ok       ⇔  以 bsp1_trend=False 的配置重跑 check_bsp1_standard 通过
趋势判据拦下   ⇔  (not standard_ok) and standard_reason == 'trend'
降级触发       ⇔  bsp1_downgrade_to_pz and diver_proven and peak_ok
                  and 趋势判据拦下 and rest_ok
```

触发时 `bs_type = BSP_TYPE.T1P`、`is_target_bsp = False`、`feature_dict` 增加 `bsp1_downgrade_reason`；否则维持原分支（`bs_type = T1`）。

**D1-a：背驰必须「实证」，不能取空真。** `treat_bsp1` 中的 `divergence_rate` 变量是 `is_divergence` 返回的**实测比率**，不是配置值；证据判定必须读 `BSP_CONF.divergence_rate`（配置阈值）。原因是 `is_divergence` 在 `divergence_rate > 100`（用户显式关闭背驰判据）时无条件返回 `True`（`ZS.py:320-322`），而该函数的 docstring 明令「不得因为背驰被关闭就把该点当成通过全部条件」。对 T1 而言 `is_diver=True` 只是放行闸门，空真无害；但降级路由把 `True` 当作「该点确实背驰」的**证据**，空真会让一个力度更强的高点被贴上「盘整背驰」标签。这与本设计已声明的一条原则对称：`bsp1_trend=False` 时降级永不触发（无趋势要求即无「趋势不达标」）；同理，背驰判据被关闭时降级也永不触发。

**D1-b：`reason == 'trend'` 不等于「其余三项通过」。** `check_bsp1_standard` 按「趋势 → 新低 → DIF → 零轴」短路，报出 `trend` 时后三项**根本没跑**，状态是「未知」而非「通过」。因此不能仅凭 `reason == 'trend'` 就断言「仅因趋势不通过」——那会把同时不创新低、DIF 不背驰的点一并降级，违反 spec 的「仅因不满足趋势前提」措辞。做法是：命中 `trend` 后，用 `copy.copy(BSP_CONF)` 把 `bsp1_trend` 置 False 再跑一次 `check_bsp1_standard`，只有通过（`rest_ok`）才降级。`check_bsp1_standard` 是纯函数、无状态，重跑成本可忽略（且逐笔已缓存）。

**D1-c：`rest_ok` 重跑必须强制 `bsp1_new_extreme_mode="all"`，否则降级判据的比较窗口不一致（2026-10-24 explore 复核补）。** `copy.copy(BSP_CONF)` 除置 `bsp1_trend=False` 外，还须把 `bsp1_new_extreme_mode` 覆写为 `"all"`。原因：`check_trend` 用**配置的** `bsp1_trend_mode`（默认 `strict`）判趋势，而 `check_new_extreme` 自己找趋势对时是 `strict or overlap`（`BSPJudgement.py:85`）。`strict` 档下，两中枢「依次下移但重叠」（`z2.high < z1.high and z2.low < z1.low` 但 `z2.high >= z1.low`）时：趋势判据失败（进入降级入口），`check_new_extreme` 却能经 overlap 找到 pair，把比较起点锚到 `z1.bi_in`——**排除该笔之前的线段内笔**。而同一线段只有单个中枢（`single_zs`）时 pair 为 None、起点退回 0、比的是整段。同一「降级 T1P」标签、同一 spec 措辞（「创趋势新低……全部通过」），窗口却取决于「是否碰巧存在一个重叠式下移的第二中枢」——这是口径漂移，会把线段内更早的更深低点漏放为降级点。趋势关闭后「趋势起点」锚点本就语义悬空（无趋势可锚），线段窗口是唯一自洽解释，且与 `pair=None` 路径天然一致。**T1 首轮判定不受影响**（仍用配置的 `trend_start`，趋势成立时锚点有效）。

**备选：`check_new_extreme` 找 pair 时改用配置的 `bsp1_trend_mode`。** 否决——修的是 `BSPJudgement.py` 的判据实现，触碰本变更 Non-Goal（不改 `check_bsp1_standard` 及其子函数）；且 `strict` 趋势成立时 `trend_start` 模式下 pair 必然存在（strict 命中即有 pair），调用侧覆写 `mode="all"` 无需动判据文件即可达成同一效果。

**备选：`rest_ok` 重跑时直接跳过 `bsp1_new_extreme` 判据。** 否决——spec 明文要求「创趋势新低」在补检中通过；跳过等于放宽，与 D1-a/D1-b 的收紧方向矛盾。

**理由**：三项条件联立（背驰实证 + 极值判据 + 其余标准判据全过）才真正对应「除趋势外全部合格」。实测 41 只日线（2019-01-01 起、QFQ、standard 档）的漏斗：

| 口径 | 数量 |
|---|---|
| `bsp1_list` 候选总数 | 573 |
| `reason == 'trend'` | 314 |
| 　+ 面积背驰成立（`is_diver`） | 168 |
| 　+ `bs1_peak` 通过 | 142 |
| 　+ 关掉 trend 重跑其余三项全过（**采纳口径**） | **53** |

「采纳口径」的 53 与 D2 表格的期望值精确一致，佐证 D1-a/D1-b 是正确的收紧方向；若只按 `reason == 'trend'` 实现，会产出 142 个降级点，tasks 的基线断言必然失败。

**D1-c 实测复核（2026-10-24）**：对 142 个候选逐个比对 `bsp1_new_extreme_mode="trend_start"` 与 `"all"` 两种口径下的 `rest_ok` 结果，**差异为 0**，两者最终都产出 53 个降级点。D1-c 的推理（`check_new_extreme` 经 `strict or overlap` 找 pair，与趋势判据的 `strict` 口径不同）在逻辑上成立，但在当前 41 只数据上该分歧未被触发。D1-c 仍**保留**为防御性口径统一，但「会进一步把该值压到 ≤53」的预测不成立，已删除。

**备选：在 `cal_single_bs1point` 里预判趋势再路由**。否决——趋势判据需要 `cfg.bsp1_trend` 开关状态与 `bsp1_trend_mode`，在进入 `treat_bsp1` 前重复判定会造成两处实现漂移；且 `check_bsp1_standard` 一旦短路就丢失后续 info，无法在外部区分「trend 失败」与「dif_div 失败」。

**备选：改 `check_bsp1_standard` 让它返回「部分通过」**。否决——该函数是前一变更的核心契约（四项独立开关、短路返回首个失败原因），改返回结构会波及两个层级的所有调用方与既有等价性验证；D1-b 用「关掉 trend 重跑一次」在调用侧达成同一目的，无需动契约。

**备选：只在文书层面放宽 spec 措辞（接受 142 个降级点）**。否决——「盘整背驰」应至少要求背驰与创极值成立。放宽后 T1P 的输出会混入结构上并不衰竭的点，下游绩效统计的分母被稀释，且无法再用「T1P = 盘整背驰」这一语义做策略筛选。

### D2：降级点强制 `is_target_bsp=False`，绝不进 `bsp1_sure_dict`

**做法**：降级调用固定传 `is_target_bsp=False`。因 `add_bs` 对 T1/T1P 有特批（`is_target_bsp or bs_type in [T1,T1P]` 都会建对象），对象仍会创建并进 `bsp1_list`/`bsp1_dict`（候选口径），但 `add_bsp1(bsp, is_sure=False)` 使其不进 `bsp1_sure_list`/`bsp1_sure_dict`。

同时需在 `add_bs` 的 `exist_bsp` 分支加一道保护（见 D4），避免降级路径把既有候选「升级」为成立。

**理由**：实测（41 只日线，运行时打桩模拟三种路由形态）：

| 路由形态 | 1 | 1p | 2 | 2s | 3a | 3b |
|---|---|---|---|---|---|---|
| 现状（无降级） | 14 | 0 | 12 | 4 | 1 | 1 |
| 降级但仅候选 | 14 | 0 | 12 | 4 | 1 | 1 |
| 降级且进成立集合 | 14 | 53 | 61 | 17 | 8 | 22 |
| **降级落库但不作锚点（采纳）** | **14** | **53** | **12** | **4** | **1** | **1** |

「进成立集合」会让二买从 12 涨到 61、三买B 从 1 涨到 22——因为二买/三买以 `bsp1_sure_dict` 为锚，每多一个「成立一买」就多一条后续链条。这会把一个「修 §4.1 副作用」的变更变成「悄悄重定义二买三买」，不可接受。

（表中数字为**单笔口径** `bsp1_force_scope="bi"` 下的实测值。此表的用途是「锚点隔离是否必要」，与力度口径无关。**注意**：采用默认的走势段口径后，实测为 `1:13 1p:52 2:12 2s:4 3a:1 3b:0`——`1`/`1p` 各减 1，`3b` 也减 1（不是「其余四类不变」，见 D10 的锚点依赖传播）。

（表中「降级但仅候选」为 0 是因为盘中打桩时 `add_bs` 的 `exist_bsp` 分支把 T1 候选直接返回了，未走到 T1P 登记——这恰好证明了 D4 的陷阱真实存在。）

**备选：降级点进成立集合，接受下游放大**。否决——语义上 T1P 本就不是「成立的一买」，让它当一买锚点会重演 §4.1 的语义污染；量化上 5 倍放大无法向上游解释。

### D3：成因标记用 `bsp1_downgrade_reason`，取 `single_zs` / `no_trend`

**做法**：`check_trend` 已返回 `{'zs_cnt': n, 'trend_zs_pair': ...}` 并写入 `standard_info`（进而进 `feature_dict`）。降级时据此填标记：`zs_cnt < 2` → `single_zs`；否则 → `no_trend`。

**理由**：两种情况的下游含义不同——`single_zs` 是「盘整」，`no_trend` 是「有趋势结构但方向不成立」。策略层若想只消费「单中枢盘整背驰」，需要能筛掉后者。

**备选：新增 `BSP_TYPE.T1P_DOWNGRADE`**。否决——`bsp_type` 是落库列与前端标签的既有词表，新增枚举会牵连 `bsp_store` 的 `DIRECTIONAL_LABELS`、前端 `bspLabel`、`bs_type` 配置解析的 `assert target_t in [...]`（`BSPointConfig.py:197`）。收益仅是「无需读 feature」，不值得。

### D4：`add_bs` 的 `exist_bsp` 分支增加「降级不得升级」保护

**做法**：`add_bs` 收到降级请求时，若该笔已有 `exist_bsp`，只 `add_another_bsp_prop(T1P, ...)` 并返回，**不执行**索引 282-285 行的「候选→成立」升级逻辑。实现上通过一个内部参数（如 `is_downgrade=True`）区分，或把该升级分支的条件收紧为 `bs_type is T1`。

**理由**：现有升级逻辑的语义是「该笔原先只是 T1 候选、本次被判定为成立」，对降级路径不成立——降级点永远不该成立。且 `add_another_bsp_prop` 的 `relate_bsp1` 保留策略（保留先登记者）在这里是安全的：降级点 `relate_bsp1=None`。

**风险**：若某笔先以 T1 成立、后又被降级（当前代码路径下不会发生，因为一个 `seg.end_bi` 每次 `treat_bsp1` 只判定一次），保护逻辑会让它保持成立——这是正确行为。

### D5：配置项加入 `FINGERPRINT_KEYS`，`legacy` 预设展开为 False

**做法**：`BSPointConfig.CPointConfig.__init__` 增加 `bsp1_downgrade_to_pz=True` 与 `bsp1_force_scope="swing"` 两个形参；`ChanConfig.set_bsp_config` 的 `para_dict` 加对应默认值；`_BSP_PRESETS["legacy"]` 加 `"bsp1_downgrade_to_pz": False` 与 `"bsp1_force_scope": "bi"`；`WebAPI/config_fingerprint.py` 的 `FINGERPRINT_KEYS` 追加这两个 key。

**理由**：`legacy` 的目标是逐笔复现改造前输出。当前 legacy 下 `min_zs_cnt=1` + `bsp1_trend=False`，趋势判据关闭 → `reason` 永不为 `'trend'` → 降级永不触发。也就是说 legacy 下该开关的取值对输出无影响，但**显式写入预设**是防御性的：若将来有人单独调 legacy 的 `bsp1_trend=True`，理应同时关掉降级才能得到「改造前 + 仅趋势」的效果。`bsp1_force_scope="bi"` 同理——legacy 下 `divergence_rate=inf` 根本不计算 metric，但显式写入可防止将来单独放开背驰时口径意外变化。

**D7-d：`bsp1_force_scope` 的两条回退路径互不干扰**：

```
legacy 档回退（粗粒度）  divergence_rate=inf → is_divergence 走 >100 分支
                          不算 metric，span 改动天然不生效
bsp1_force_scope="bi"   standard 档下单独回退力度口径（细粒度）
                          （新增）只影响 standard 档
```

因此等价性脚本的 legacy 基线（笔级别 258/69/318/317/61/50）**自动保持**，无需额外处理。

### D6：线段级别路径同样生效，但不新增点

**做法**：不改 `treat_bsp1` 的层级无关性——`seg.bi_list` 与 `seg.zs_lst` 在笔级别（元素是 `CBi`）与线段级别（元素是 `CSeg`）语义同构，`check_bsp1_standard` 已按 D1 的纯函数契约实现。

**理由与实测**：线段级别标准档当前成立 T1 = 1，趋势失败候选 53 个；实测打桩显示该路径同样会产出降级 T1P，但数量级很小。保持在两个层级生效符合前一变更 D23「两个层级口径必须一致」的原则。

### D7-q：区间套做成后置特征注解，窗口与力度口径共用 `c` 走势段定义（§4.6）

**做法**：新增 `bsp1_qjt`（默认 `False`）后，在 `CBSPointList.cal` 的收尾（`cal_seg_bs1point` 之后）执行 `_annotate_qjt`：对 `bsp1_list` 家族每个点，取其 c 走势段——**与 `bsp1_force_scope="swing"` 的 c 窗口（`zs.end_bi`+1 ~ `seg.end_bi`）同一处定义**——映射到次级别结构区间，查次级 `bs_point_lst.bsp1_sure_list` 中同向已确认 T1，命中写 `feature_dict['bsp1_qjt_hit']` 与 `bsp1_qjt_sub_idx`。次级别容器引用由 `CChan` 级别循环在 `cal_seg_and_zs` 后注入（只读引用，不建立新指针图，不参与 pickle/deepcopy 的指针重建——这点与 `sup_kl`/`sub_kl_list` 的教训一致）。

**理由**：§4.4 的力度口径走势化已在 `treat_bsp1` 建立「c 段 = 走势段」的窗口对象，区间套的次级别映射直接复用它——分两个变更会重复定义同一窗口。特征注解放在 `cal` 收尾而非 `treat_bsp1` 内，保证它**物理上不可能**影响 `is_target_bsp`（判定链路已结束），这是「特征不改成立性」约束的结构保证，不靠纪律。

**备选：把区间套做成 `check_bsp1_standard` 的第五项判据**。否决——硬判据要求子级点「已确认」，而子级确认天然滞后于父级候选产生（父级线段确认依赖子级之后的 K 线），步进模式下系统性漏判；且会把「先候选、后因子级确认而成立」的状态机问题提前引爆。先特征化观测，数据支持后另案升级（届时与 §4.9 延迟确认合流）。

**备选：删除 `WebAPI/bsp_ladder.cal_l1_resonance`**。否决——二者不是同一功能：内核 qjt 是一买候选的成立性证据（仅 T1 家族、结构窗口、特征随点持久）；L1 是**全类型**未确认点的跨级别佐证（二买/三买候选没有「c 段」概念，时间窗是唯一可行口径），且 L1 是已归档 `bsp-ladder-change` 的 ladder 落库列契约、前端 `bspLadder.ts` 词表来源。删它会让未确认二买/三买全部失去跨级别佐证。可选的未来收敛（T1/1p 的 L1 改读内核特征）属另案。

### D8：递归深度默认 1 层，命中资格用子级 `bsp1_sure_list` 口径

**做法**：`bsp1_qjt_depth` 默认 1。命中资格 = 子级点同向 ∧ 在子级 `bsp1_sure_list`（已确认）——不用 `bsp1_list` 候选口径。

**理由（示例）**：深度 2（如 60m→5m）时，60m T1 在 6/19、其 c 段末端 5m T1 在 6/19 14:30，则 6/19 15:00 快照下 60m 线段尚未确认（需 6/20 的特征序列分形）、5m 更未确认，两层链全部悬空 → 命中=False（假阴性）；批量终态回看则为 True。**步进与批量给出不同答案**，违反 tasks 4.3 的既有不变量。一层 + 特征化把失真压到「特征字段在快照间可能翻 True」（可观测、可接受），多层 + 硬判据会变成「买卖点本身翻脸」。

命中资格镜像 D2 的锚点隔离：子级若用候选口径，父级 T1 会拿到「子级连趋势都没成立的点」背书——降级点不作锚点的边界，在级间命中资格上同样执行（spec 场景「降级点不参与命中资格」）。

### D9：`legacy` 档显式展开 `bsp1_qjt=False`，指纹进 `FINGERPRINT_KEYS`

**做法**：与 D5 同构——虽然默认已 False、legacy 下取值对输出无影响，但显式写入预设是防御性的（将来有人单独调 legacy 的判据开关时不被特征字段污染等价性基线）；`FINGERPRINT_KEYS` 追加 `bsp1_qjt`，切开关时缓存与快照自动失效。

### D7：力度口径走势化——`is_divergence` 增加可选窗口参数（§4.4）

**问题**：`ZS.is_divergence` 取 `get_bi_in()` 与 `out_bi` 做力度比较。`bi_in = bi_list[zs.begin_bi.idx - 1]`（`KLine_List.py:386`）——**紧邻中枢开始前的那一笔**。理论要求 b = 「进入中枢的次级别走势」，c = 「离开中枢的次级别走势」。当离开中枢后走了多笔才见底，单笔口径只看最后一笔，会误判为力度衰竭。

**做法**：分两处，保持单一职责。

```python
# ZS.py —— 中枢只做「两段比大小」，窗口由调用方决定
def is_divergence(self, config, out_bi=None, b_window=None, c_window=None):
    ...
    in_metric  = _metric_of(b_window)  if b_window is not None else self.get_bi_in().cal_macd_metric(...)
    out_metric = _metric_of(c_window)  if c_window is not None else out_bi.cal_macd_metric(...)
    # 其余分支（end_bi_break、>100 显式关闭、阈值比较）逐字节不变
```

```python
# BSPointList.treat_bsp1 —— 负责定义窗口
scope = BSP_CONF.bsp1_force_scope          # "swing"（默认）| "bi"
if scope == "swing":
    b_window, c_window = _cal_force_windows(seg, last_zs)
    is_diver, divergence_rate = last_zs.is_divergence(BSP_CONF, out_bi=seg.end_bi,
                                                      b_window=b_window, c_window=c_window)
else:
    is_diver, divergence_rate = last_zs.is_divergence(BSP_CONF, out_bi=seg.end_bi)  # 原路径
```

**窗口边界定义**（D7-a）：

```
b 窗口： 上一中枢结束笔 + 1  ~  zs.bi_in
         无上一中枢时 → seg.start_bi ~ zs.bi_in
c 窗口： zs.end_bi + 1  ~  seg.end_bi
```

「上一中枢」指该线段内**排在当前中枢之前**的最后一个非一笔中枢（`[z for z in zss if z.end_bi.idx < zs.begin_bi.idx][-1]`）。这样 b 段跨过整个「进入前的中枢」，才符合「次级别走势」的粒度；c 段从离开中枢的第一笔起算到线段末笔。

**D7-b：索引换算陷阱。** `seg.bi_list` 是**连续切片**（`Seg.update_bi_list` 用 `range(idx1, idx2+1)` 逐笔 append），所以 `seg.bi_list[i]` 对应全局 `bi_list[seg.start_bi.idx + i]`。窗口切片必须用**线段内相对索引** `idx - seg.start_bi.idx`，直接用全局 `bi.idx` 会越界或错位。这是实现时最容易写错的一处。

**D7-c：算法覆盖与降级行为。** `Metric.py` 只有 8 种算法提供区间版本：`area` / `full_area` / `peak` / `diff` / `diff_peak` / `slope` / `amp` / `rsi`。成交量与换手率类的 5 种（`volumn` / `amount` / `volumn_avg` / `amount_avg` / `turnrate_avg`）没有区间版本。处理方式：span 口径只对前者生效，后者自动退回单笔口径，并在 `feature_dict` 写 `bsp1_force_scope_effective="bi_fallback"`。

**理由与实测**：

| 指标（41 只日线、standard 档） | 单笔 | 区间聚合 |
|---|---|---|
| 成立 T1 | 14 | 13 |
| 降级 T1P | 53 | 52 |

唯一翻转样本 `sh.600016 bi=31`：离开段 3 笔，单笔 `r=0.837 ≤ 0.9` 判背驰，整段 `r=1.746 > 0.9` 判不背驰——离开中枢后每笔都在创新低，整段动能增强。

**备选：逐笔取 max 聚合**。否决——实测与区间聚合几乎等价（20 vs 19），但「取 max」是人为拼装，解释成本高；区间聚合复用 `Metric.py` 已有函数，语义就是「整段力度」。

**备选：在 `treat_bsp1` 里绕过 `is_divergence` 自己算**。否决——会丢掉 `end_bi_break` 的统一校验，且与降级路由的 `diver_proven` 脱节，两处口径漂移。

**备选：直接改 `is_divergence` 内部取窗口（不给参数）**。否决——该函数签名拿不到 `seg`（只有 `config` + `out_bi`），且会让通用中枢方法承担「窗口策略」职责。

### D10：力度口径改造的锚点依赖传播——三买会随一买口径连带减少（2026-10-24 实现期实测修正）

**问题**：本变更初稿（tasks 9.7 与 proposal 的 `2/2s/3a/3b` 完全不变声明）假定力度口径只影响 `1` 与 `1p`。实现完成后的实测否定了这一点：

| 口径 | 1 | 1p | 2 | 2s | 3a | 3b |
|---|---|---|---|---|---|---|
| `bsp1_force_scope="bi"`（单笔，改造前） | 14 | 53 | 12 | 4 | 1 | 1 |
| `bsp1_force_scope="swing"`（走势段，默认） | **13** | **52** | 12 | 4 | 1 | **0** |

**机制**（不是缺陷，是锚点依赖的正确传播）：
`cal_seg_bs3point` 以「该线段的 `end_bi` 是否在 `bsp1_sure_dict` 中」作为三买的前置条件（`bsp3_follow_1` + `bsp3_follow_1_mode="sure"`）。`sh.600016 bi=31` 原本是成立一买，走势段口径下整段力度 `r=1.746 > 0.9` 判不背驰、不再是成立一买；同一线段内 `bi=28` 的 T3B 锚定的正是这个一买，于是随之消失。

这与 D2 论证的是**同一原理的两面**：
```
降级点不作锚点  ⇒  一买不成立时，依赖它的二买/三买不产生
                    （否则 2:12→61、3b:1→22 的 5 倍放大，见 D2 表格）
一买口径收紧    ⇒  原本成立的一买消失时，依赖它的二买/三买同步消失
                    （本次实测 3b: 1→0，方向与放大相反、机制相同）
```
若反过来让三买保留，就等于说「三买可以锚定一个已经不成立的一买」——与 D2 的锚点隔离原则直接矛盾。

**为什么不给三买单独绕过**：`bsp1_force_scope` 只改变 `ZS.is_divergence` 的**取值窗口**，不改三买判据。三买数量的变化全部来自「锚点是否成立」这一既有机制，不是三买判据被改动。让三买不受影响，只能在三买侧单独维护一套「旧口径成立一买」的影子集合，这会让同一份构建里出现两套一买口径，正是 design D7「单一职责」要避免的。

**结论**：`2` / `2s` / `3a` 的「完全不变」仍然成立（实测确为 12/4/1）；`3b` 的表述应改为「**仅在所锚定一买因口径收紧而消失时连带变化**」，当前数据上为 1→0。等价性脚本第 7 节的断言据此从「四类完全相同」收窄为「`2`/`2s`/`3a` 完全相同，`3b` 的差异必须能从一买消失集逐笔对账」。

**回退**：`bsp1_force_scope="bi"` 可单独退回单笔口径，此时三买恢复到 1——这条路径同时也是「验证连带消失确由力度口径引起」的对照组。

## Risks / Trade-offs

- **`1p` 从 0 增至 52（41 只日线，默认档 = 降级路由 + 走势段口径的终值；仅开降级、单笔口径时为 53），是数量级变化** —— 两个数字均已实测确认，D1-c 的 `mode="all"` 与 `trend_start` 两种口径差异为 0（见 D1-c 实测复核）→ 缓解：`bsp_index` 按 `bsp_type` 分行统计，`1p` 与 `1` 的分母本就独立；`config_fingerprint` 变化使缓存与快照自动失效，不会混入旧行；回退只需关开关。
- **降级点可能被下游误当作「一买」使用** → 缓解：类型是 T1P（不是 T1）、不进 `bsp1_sure_dict`、带 `bsp1_downgrade_reason`。文档三处（一买差异点、缠论策略、README）明确写出「降级 T1P 不是成立一买」。
- **`add_bs` 的升级分支保护若实现不当，会破坏 T1 的候选→成立路径**（该路径在增量重算中真实使用） → 缓解：tasks 中要求单列一个回归用例，验证「先候选后成立」的 T1 仍能正确进 `bsp1_sure_dict`；等价性脚本的 legacy 基线必须保持 258/69/318/317/61/50 不变。
- **`reason=='trend'` 的字符串耦合** → 缓解：`check_bsp1_standard` 的短路顺序是显式契约（proposal 已写入 spec 的顺序语义），且 strings 集中在 `BSPJudgement.py` 一处；tasks 要求加注释锁定「`trend` 必须始终是第一个检查项」。注意 `reason=='trend'` 只是**入口**，不是充分条件——D1-b 的全检才是。
- **`divergence_rate > 100` 这个魔数现在有两处语义依赖**：`ZS.is_divergence`（关闭判据，空真返回 True）与 `treat_bsp1` 的降级证据判定（`divergence_rate <= 100` 才承认背驰）。两处必须共用同一口径，否则「关闭背驰」与「降级资格」会漂移。缓解：实现时在 `ZS.is_divergence` 与 `treat_bsp1` 两处各加一行注释互指，禁止任一侧改阈值；等价性脚本补「`divergence_rate>100` 下降级点为 0」的断言。
- **趋势判据被单独关闭（`bsp1_trend=False`）时降级永不触发** → 这是正确行为（无趋势要求即无「趋势不达标」），但需在文档中说明，避免用户误以为开关失效。**同一条原则的另一面**：背驰判据被显式关闭（`divergence_rate>100`）时降级同样永不触发——用户既然声明不关心力度，系统就不该替他产出「盘整背驰」标签。两处都要写进 §九 与 `Document/README.md` 的参数说明。
- **D1-b 的全检在 `bsp1_trend=False` 配置下会退化为「重复一次相同调用」**（两次都是 trend 关闭）→ 无副作用，但实现时应直接复用第一次的结果而非真的再算：可先判 `BSP_CONF.bsp1_trend`，为 False 时 `rest_ok = standard_ok`。
- **走势段口径会让「离开段很长」的结构更容易被判为不背驰**，即 T1 与降级 T1P 同时小幅减少（实测各 -1）→ 这是修复方向本身（长离开段意味着动能未衰竭），但会改变历史回测的可比性。缓解：`bsp1_force_scope="bi"` 可单独回退到单笔口径，回退后与改造前的区别仅剩降级路由一项，便于二分定位。
- **窗口切片用错索引会静默产出错误数值而非报错**（`seg.bi_list` 是相对索引的连续切片，全局 `bi.idx` 与其相差 `seg.start_bi.idx`）→ 缓解：tasks 9.5 要求合成序列断言窗口首尾笔的 `idx`，并用 `sh.600016 bi=31` 的双口径力度比率（0.837 / 1.746）做端到端锚点；若实现写错，这两个数字会同时偏离。
- **成交量/换手率类算法下口径开关「看起来生效但实际退回单笔」** → 缓解：`feature_dict` 写 `bsp1_force_scope_effective="bi_fallback"` 使差异可见；tasks 9.6 要求逐算法遍历验证。
- **逐笔基线依赖数据水位，会随灌数腐烂**（`Data/kl_store.duckdb` 在 `.gitignore` 中，不进 git；新 K 线进入后笔的划分与 `bi.idx` 会整体位移）→ 缓解：tasks 9.0 要求基线 JSON 自带 `watermark`、校验前先比对当前库 `max(time_key)`，不一致则明确提示重新生成并以非零码退出（而不是报「逐笔不一致」这种误导性结论）；比对查询一律 pin `end_time=watermark`。选 JSON 落在 `Debug/` 而非 `Log/` 的理由：`Log/` 是工作目录（`*.log` 已 gitignore、现有 CSV 全为 untracked 临时产物），基线是契约不能放在会被随手清空的目录；`Debug/vp_entry/reports/final_40pool/sensitivity_curve.csv` 已有提交样本文件的先例。
- **基线必须生成于代码改动之前，否则自我循环**（用新代码生成的基线去验证新代码，等于什么也没证明）→ 缓解：tasks 9.0 显式排在 9.1 之前，并给出根本原因——`bsp1_force_scope` 在 9.1 之前不存在，`ConfigWithCheck` 会以未知 key 抛异常，所以 9.0 只能用 `bsp_preset="standard"` 生成。9.3a 在「开关已存在但 `ZS.py` 未改」时补一次对照，把「开关无效」与「签名改造出错」两种故障分开归因。
- **区间套特征在步进快照间可能翻转（子级确认滞后）**——父级候选点产生时子级 T1 尚未确认，`bsp1_qjt_hit` 先为 False、子级确认后翻 True → 缓解：特征不改成立性（D7-q 的结构保证），翻转只影响特征列；tasks 要求批量/步进终态断言命中集合一致（中间翻转不算失败）。若未来误把它升级为硬判据而不做延迟确认，会直接违反 tasks 4.3 的不变量——design 备选已明确否决该路径。
- **`CChan` 注入次级容器引用若参与 deepcopy/pickle 指针图，会重演 `sup_kl`/`sub_kl_list` 的序列化陷阱** → 缓解：引用只在 `cal_seg_and_zs` 后的注解阶段使用、不挂在 `CKLine_List` 的持久化属性上；`__deepcopy__`/`chan_dump_pickle` 两处的手工重建清单不加入该引用（design D7-q 已写明）。

## Migration Plan

1. **阶段 0（内核）**：新增三个配置项（`bsp1_downgrade_to_pz` / `bsp1_force_scope` / `bsp1_qjt`，第三个默认关闭）、降级路由、`add_bs` 保护、`legacy` 预设；`is_divergence` 加窗口参数、`treat_bsp1` 计算窗口、span 力度取值与 `bi_fallback`；`CChan` 级别循环注入次级容器引用与 `_annotate_qjt` 收尾；跑等价性脚本确认 legacy 基线不变、`standard+bi` 口径 T1=14/T1P=53、`standard+swing` 口径 T1=13/T1P=52、开 `bsp1_qjt` 后六类数量与关时逐类一致。
2. **阶段 1（下游回刷）**：对 PG 全部已入库股票执行 `recompute_stock(force_full=True)`（指纹已变，首轮必为全量），`bsp_index` 整套替换。`bsp1_qjt` 默认关闭，本次回刷不含区间套特征；需要命中统计时另行开启重算（只影响特征列，不改行数）。
3. **阶段 2（文档）**：四份文档回标（含 §4.6 从「未修复」改为「部分修复——特征化落地」）+ `Document/README.md` 参数段 + `文档/缠论策略.md` 配置表。
4. **回滚**：细粒度用 `bsp1_force_scope="bi"`（只退力度口径）、`bsp1_downgrade_to_pz=False`（只退降级路由）或 `bsp1_qjt=False`（只关区间套特征，默认即关）；粗粒度用 `bsp_preset="legacy"`；任一情况下再跑一次全库回刷。

## Open Questions

- 降级点是否需要透出到前端（买卖点页可按成因筛选）？当前只要求内核与 WebAPI 可见，前端按后续需求再定，不影响判据。
- 区间套命中率数据积累后是否升级为硬判据（届时与 §4.9 延迟确认合流设计）？特征化阶段结束时用等价性脚本的命中统计决策。
- T1/1p 的 L1 共振是否改为读内核 `bsp1_qjt_hit`（其余类型保留时间窗）？属未来收敛项，需 `bsp-ladder-change` spec 演进配合，本次不做。
