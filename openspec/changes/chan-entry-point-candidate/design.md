# Design

## Context

区间套现状是「一买候选点上的备查特征」（内核 `BSPointList._annotate_qjt` 后置通道，只写 `bsp1_qjt_hit` feature），2买/3买无任何介入点概念。本变更在其旁边新建「介入点候选」判定层：三类买卖点、买卖对称、双方法（区间套递归 / 辅助确认信号）任一命中即成立。落库与展示复用 `ladder` 已走通的双链路（`incremental_engine._extract_bsp_rows` 落库 / `serializer._serialize_bsp` 序列化）。

内核红线（CLAUDE.md + 既有 spec 约定）：不改 `CChan`/`CBiList`/`CSegListChan`/`CZSList`/`CBSPointList` 的既有判定链路。`_annotate_qjt` 先例确立的「cal() 收尾后置、只写 feature、物理上不参与 is_target_bsp」模式是本设计的结构模板。

## Goals / Non-Goals

**Goals:**
- 介入点判定一份计算、双链路消费（落库 + 序列化），批量与步进终态一致
- 配置三层联动（总开关 → 方法1 → 递归层数 + 方法2），12 键全进指纹
- 零回归：开关全关时输出与现状逐笔一致

**Non-Goals:**
- 不改任何买卖点成立性、不新增 `bsp_type` 枚举、不动 ladder 三轴/五轴/四轴
- 方法2 右端「N 笔确认窗」限制（预留键位不实现）
- 监控规则新触发类型（可后续低优先级追加）
- 介入点的历史回溯统计（见 Risks 第 3 条的语义边界）

## Decisions

### D1: 判定放内核后置通道（模式复制 `_annotate_qjt`），WebAPI 只读 feature

**选择**：在 `BSPointList.cal()` 收尾、`_annotate_qjt()` 之后新增 `_annotate_entry_point()`，写 feature：`entry_hit`（bool）、`entry_method`（`'qjt'`/`'aux'`）、`entry_level`（实际递归层数）。落库（`_extract_bsp_rows`）与序列化（`_serialize_bsp`）直接读 feature，不重复计算。

**理由**：介入点需要的输入（`sub_bs_point_lst` 链、`bsp1_list`/`bsp_store_dict`、段与笔结构）内核全部可达；放 WebAPI 层推导则落库链路（单级别 CChan + `_compute_sub_for_l1`）与序列化链路要各自再映射一遍窗口，两处口径必然漂移。feature 后置通道不碰判定链路，与内核红线和 `chan-bsp1-qjt` spec 的「后置执行」条款同构。

**替代方案**：WebAPI 层推导（ladder 模式）——被否，ladder 需要 WebAPI 侧 bi_list/配置做轴判定所以放外面；介入点判定不需要这些，放内核更省一层。

**注意**：多级别 CChan 内 `sub_bs_point_lst` 由 `load_iterator` 天然挂好；**两条生产链路的主级别都是单级别 CChan**（落库 `incremental_engine._compute_full`、序列化 `chan_service._compute_chan`，子级别各自旁路计算），`cal()` 收尾时 `sub_bs_point_lst` 尚未挂载——`_annotate_entry_point` 直接返回。落库链路由 `_compute_sub_for_l1` 补算子级后在 `_extract_bsp_rows` 内调判定核心；序列化链路由 `serialize_chan` 在序列化前调 `attach_sub_bspoint_and_annotate` 补挂子级容器并补跑注解（与 `CChan._refresh_qjt` 的收尾同构），再读 feature。两条链路因此都拿得到子级输入。

### D2: 配置键族 `bsp{1,2,3}_entry*`，与既有 `bsp1_qjt` 特征键彻底分离

12 键命名（避免与既有 `bsp1_qjt`/`bsp1_qjt_depth` 特征键撞名——特征语义必须保持独立）：

```
bsp{N}_entry            是否开启候选点计算（总开关，默认 False）
bsp{N}_entry_qjt        方法1：区间套递归（visible_when: entry=True）
bsp{N}_entry_qjt_depth  递归层数（visible_when: entry_qjt=True，默认 1）
bsp{N}_entry_aux        方法2：辅助确认信号（visible_when: entry=True）
```

- 内核 `CPointConfig` 新增 12 个字段与构造期校验（层数 >= 1 整数，校验样式仿 `bsp1_qjt_depth`）；`ChanConfig.py` 出厂默认全 False、`_BSP_PRESETS["legacy"]` 显式写 12 键全 False（防御性，样式仿既有 `bsp1_qjt: False` 条目）。
- `chan_config_schema.py`：12 项元数据（判据分组、白话解释、`conditional=True` + `visible_when`），分布到「一买判据」「二买 / 类二」「三买判据」三个 subtype。
- `chan_config_store.py`：`validate_config()` 走构造期反射自动覆盖；档位回填无需额外处理（键走三层优先级标准路径）。
- `config_fingerprint.py`：12 键加入 bsp 段清单。
- 前端 `ChanConfigDrawer.vue` 的 `isVisible` 机制已支持 `visible_when`，零前端逻辑新增。

**替代方案**：复用 `bsp1_qjt` 键做方法1开关——被否，`chan-bsp1-qjt` spec 要求特征语义（不改成立性）与介入点判据化语义并存且互不污染，共键会让特征开关意外改变介入行为。

### D3: 窗口口径——三类点各自的「待确认段」

| 点类型 | 窗口 | 结构映射 |
|---|---|---|
| 1买 | c 背驰段 | 复用 `_c_window_of`（`zs.end_bi+1 ~ seg.end_bi`，与力度口径同源） |
| 2买 | 回落段 | bsp2 所在笔起、回调起点（上涨段顶点）至线段末笔的下跌笔区间 |
| 3买 | 回抽段 | 突破笔之后至 bsp3 所在笔（回抽笔）的区间 |

- 映射到次级时间区间复用 `_sub_time_span` 语义（内核版）。**单级别构建下 `sub_kl_list` 恒空**（父子 K 线链接只在多级别 `load_iterator` 里挂），内核版沿用 `bsp_ladder._sub_time_span` 的回退口径：无子级时间戳时用父级 K 线时间轴近似（左端取窗口首根父级 K 线时刻，右端取末根外扩一个父级周期中位数）。窗口边界仍是 `zs.end_bi.idx+1 ~ seg.end_bi.idx` 的结构映射（唯一事实源），回退只放大时间区间、不收窄命中集。缺这段回退时两条生产链路恒 0 命中（2026-11-09 冒烟实测：多级别构建 4 个、单级别 0 个）。
- 方法2 右端**至数据末端**：窗口右边界改为「max(段末, 数据末根子级时间戳)」；左端不变。
- 方法1 的分型确认读信号点邻域（次级 `klc.pre/next` 链），不受窗口右边界约束。
- 卖侧全镜像（`GetBSConfig(is_buy)` 分流，一套规则两个方向）。

### D4: 方法1 = 链式下钻 + 最低层「候选背驰 + 分型形成」

中间层沿用 `_find_qjt_hit` 的口径（同向**已确认**一买，层层验证）；**最低层放宽**为「次级同向一买**候选**（`bsp1_list` 家族）+ 其所在笔末端底分型/顶分型已形成（`end_klc.fx` 类型正确且 `next` 存在）」。

**理由**：笔的 `is_sure=True` 意味着分型早已形成——若最低层也要求已确认，介入时点会比底分型形成晚整整一笔（分型→新笔→笔确认），违背「介入」本义。用户原话「最低级别也出现背驰并配合底分型确认」正是「候选 + 分型」而非「笔确认」。中间层保持已确认口径是为了层层验证的稳健性，且与 `bsp1_qjt_hit` 特征口径同源、可复用链式下钻实现。

递归层数 `bsp{N}_entry_qjt_depth` 语义：k = 链式确认 k 层；某层无子级容器时按已走到的层数判定（不惩罚级别不够，与既有 depth 语义一致）。

### D5: 方法2 = 次级已成立二买/三买家族，窗口右端外扩

次级 `bsp_store_dict` 中 T2/T2S/T3A/T3B 家族、方向一致的**已成立**点（`bsp_store_dict` 登记 = `is_target_bsp` 成立；不要求 sure——「可确认的」指成立可确认，非水位确认）。窗口 = D3 的段窗口 + 右端至数据末端。命中即 `entry_method='aux'`。

**边界**：1买方法2 只认次级二买/三买（用户原文）；2买/3买方法2 同为二买/三买。次级一买不算方法2（那是方法1 的领域）。

### D6: 落库与查询——entry 三列 + 伪类型翻译

- `bsp_index` 惰性 DDL 加三列：`entry_point BOOLEAN DEFAULT FALSE`、`entry_method VARCHAR(8)`、`entry_level INTEGER`；`WebAPI/update-win.sql` 幂等追加（本变更在 Windows 机器开发）。
- `_extract_bsp_rows`：读 feature 拼三列；`bsp_store.py` 两处 INSERT（`241`、`732` 附近）同步加列。落库链路介入点依赖子级 → `_compute_sub_for_l1` 计算的子级结果需挂回主级别（既有挂载点 `_sub_kl_for_fractal` 模式扩展挂 `sub_bs_point_lst` 供内核注解？**否**——内核注解在 CChan 计算内发生，落库链路的单级别 CChan 算完才知道子级。落库链路的介入判定改在 `_extract_bsp_rows` 内以 WebAPI 侧函数计算（复用内核窗口函数导出），输入 `sub_result`。这与 ladder 的 `cal_ladder` 落库位置完全同构。**序列化链路**同样是**单级别** CChan（`_compute_chan`，子级别由 `compute_sub_chan` 旁路独立计算）——`cal()` 时 `sub_bs_point_lst` 未挂、feature 不会被写。修复：`serialize_chan` 在序列化前调 `CBSPointList.attach_sub_bspoint_and_annotate(sub_bs_point_lst)` 补挂只读引用并补跑 `_annotate_entry_point`，之后 `_serialize_bsp` 读 feature。两条链路共用同一个判定核心函数（从 `BSPointList` 提取为模块级纯函数），保证口径单点；窗口映射同源（`sub_time_span` 含父级时间轴回退）。
- 查询：`resolve_bsp_type` 扩展伪类型 `'entry'`/`'entry1'`/`'entry2'`/`'entry3'` → `entry_point = TRUE`（+ 类型 IN 条件）；路由与前端下拉透传。
- 序列化：`_serialize_bsp` 的 bsp dict 加 `entry`/`entry_method`/`entry_level` 三字段（序列化链路在 `serialize_chan` 内补挂子级容器并补跑内核注解，再读 feature；见上条）。

### D7: 必要条件按当前结构状态判定（末端语义）

「回落段/回抽段内部结构未完成」「背驰段成立中」按**判定时刻的结构状态**判定（`last_sure_pos` 水位）：只有未确认段上的候选点满足必要条件；已确认历史点介入列恒 False。批量与步进终态一致（同一最终水位）。

**理由**：介入点是时机判定，段完成后介入时机已不存在；历史化「该点当时是否未完成」需要快照回放，成本不成比例。

### D8: 展示合成单点

- `utils/bsp.ts`：`bspLabel` 增加介入后缀参数或新函数 `bspLabelWithEntry(type, isBuy, entry)` → `1B·介`；`chanBspLabel` 合成（meta 加 `entry`/`entryMethod` 字段）。
- BspView 类型列同函数；类型筛选下拉加伪类型项。
- Mock 数据（`front/src/mock/`）同步补字段与示例，MSW 拦截层无需结构变更。

## Risks / Trade-offs

- **[多层数字段开启拖慢计算 + 步进翻转]** → 默认 1 层；文档说明每加一层的翻转放大（沿用 `bsp1_qjt_depth` 的既有警示文案模式）
- **[末端介入判定的暂时性被误解为终态]** → 前端 tooltip 与文档标注「介入点为当前口径，随数据推进可翻转」；与 `is_sure`/`ladder` 翻转语义对齐，不新发明机制
- **[历史点介入列恒 False → 绩效对比样本受限]** → 显式接受（介入=时机语义）；若后续要历史回测，需快照回放，另立变更
- **[落库链路与序列化链路双实现口径漂移]** → 判定核心提为单一模块级函数，两链路共用；等价测试覆盖双链路
- **[12 键进指纹使存量快照全部失配]** → 预期行为（BREAKING 语义同 config_fingerprint 既有约定），首算走全量；键默认 False 时指纹值与「未引入前」不同但重算结果逐笔一致

## Migration Plan

1. 内核键与注解通道合入（开关默认关，行为零变化）
2. WebAPI schema/指纹/落库/查询合入；惰性 DDL 自动补列（既有行 NULL）
3. 前端配置联动 + 展示合成合入
4. 回滚：任一阶段回滚代码即可——开关默认关 + DDL 幂等加列不破坏既有读写（旧行 NULL 被前端当「无介入」处理）

## Open Questions

- 方法2 是否应允许次级**未确认但已成立**的三买（当前设计允许——`bsp_store_dict` 登记即成立）？若实战中发现假信号过多，可收紧为 `bsp_is_sure` 水位口径，属阈值级调整不改结构。
