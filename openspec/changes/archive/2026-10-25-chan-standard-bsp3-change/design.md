# Design: chan-standard-bsp3-change（差异收尾 + T3 候选确认体系）

## Context

两部分。Part A：《三买三卖差异点说明.md》§七 三条「部分修复」判定为结构性残留，处置结论固化到文档与 spec（代码锚点 `BSPointList.py:952`/`:1022`、`Document/README.md:571`）。Part B：T3A/T3B 接入候选确认体系——阶梯类型路由现状（`bsp_ladder.py:322` T3 分支 `return None`）与 bsp2-change 落盘的五轴框架（`bsp2_ladder.py` / `bsp2_confirm.py` / `bsp2_progress.py` / `bsp2_time_axis.py`）为本变更提供了完整模板；T3 缺的是：佐证/确认/分型/时间四轴的 T3 适配、类型路由接入、落库翻转重刷、前端词表。前置依赖：`chan-standard-bsp`、`chan-standard-bsp1-change`、`chan-bsp-ladder-change` 已归档；`chan-standard-bsp2-change` 代码已落盘、状态 in-progress 待归档。

## Goals / Non-Goals

**Goals**

- Part A：三条遗留差异显式终态，后续审计不再重查
- Part B：T3 候选点获得四轴证据分层，`bsp_index.ladder` 3a/3b 终结 NULL 过渡语义
- 缠论要素 E（回抽后趋势延续）以事后确认层落地——真/假三买可区分，绩效统计可分组
- 全程成立判据零改动（证据标注与成立性正交）

**Non-Goals**

- 不统一 `strict_bsp3` 两分支条件（见 D1）
- 不给笔级别三买引入次级别走势类型成立判据（双口径既有结论）
- 不重命名 3a/3b、不暴露 `seg_bs_point_lst`
- **不把要素 E 做成成立判据**（见 D5——这是本设计最重要的排除项）
- 不做中枢升级排除判据（标准档 T3 样本 41 只日线仅 1+1，无法实证；见 D9）
- 量能/MACD 不进轴不进判据（沿用 bsp2-change 已拍板的排除决策，仅允许只读 feature）
- 不改 T1 三轴、T2 五轴的既有语法与行为

## Decisions

### D1: `strict_bsp3` 双分支差异定性为「结构必然」，以 ADDED Requirement 落 spec（Part A）

两分支中枢位置不同（T3A 锚 `next_seg` 第一个多笔中枢、T3B 锚当前线段最后一个多笔中枢），「紧邻一买」必然是两个不同条件。归档任务 11.8 的「统一」落成「T3A 补注释 + 保留差异」是做对了而非没做完。ADDED 而非 MODIFIED：既有各条 Requirement 描述单分支判定，没有需要修正的「统一」表述。替代方案（改代码统一两分支）对 T3B 无意义且破坏 `strict_bsp3=True` 回退契约，否决。

### D2: §4.11 / §4.8 以差异点文档回标收口，不新增 spec 条目（Part A）

§4.11 实质风险已被标准档重写消除，剩余是命名约定无行为差异；§4.8 双口径已被 `chan-bsp-standard`「次级别走势类型的层级落地」Requirement 覆盖。处置理由记入差异点文档，避免 spec 膨胀。

### D3: README 修正限定在 `strict_bsp3` 一行（Part A）

`:571` 拆两分支描述，其余参数段已由归档任务 14.2 修正过，不重复触碰。

### D4: Part A 与 bsp2-change 无代码交集，可先行实施

Part A 只动文档与 spec（`chan-bsp-standard` 一条 ADDED），bsp2-change 归档的 specs 同步不涉及该条，无合并冲突。**Part B 相反**（见 D8）。

### D5: 要素 E 落「事后确认层」而非「成立判据」（Part B 核心）

两条路径对比：

- 路径 (a) E 作为成立判据：三买输出条件加「回抽后不跌回中枢」→ 需要未来 window 根 K 线 → 信号整体后移 1~2 笔 → 回抽低点本身才是买点，等确认后出信号等于永远买在确认笔高位 → 引入未来函数，缠论实战同样反对（缠师把 E 称为持有期的走势确认，非买点成立条件）。**否决**。
- 路径 (b) E 作为事后确认层（采纳）：三买照常在回抽笔端点输出（进场点位不变），确认窗口内 C3 突破回抽笔端点 / C2 收复一半 / C1 跌回中枢（证伪终态）/ C0 进行中。与 `bsp2_confirm.py` 同构，仅参照物不同：T2 用 break_bi 端点，T3 用回抽笔端点 + 中枢失守线。真/假三买可分，绩效可分组。

### D6: 轴结构 S|C|K|T 四轴，无 P 进度轴（Part B）

T2 五轴的 P 进度轴语义是「判据链推进到第几步」（T2 判据链 ①一买 ②+2 笔 ③不破极值 ④回撤率 ⑤中枢关联可分步推进）。T3 判据链是**瞬时**的：①中枢锚定 ②突破方向 ③第一次回抽 ④不回中枢，在回抽笔端点一次性全部可判，成立即全链通过——没有「推进到一半」的中间态。硬造 P 轴只能输出恒 P1（全链），无信息量。轴序：佐证 → 确认 → 分型 → 时间（与 T2 语法的轴序子集对齐，便于前端统一渲染）。

### D7: 证伪线以「判据链采纳的中枢」为基准（Part B）

C1 证伪判据 = 确认窗口内后续笔跌回**登记时锚定的那个中枢**的区间（买侧低点 < ZG、卖侧高点 > ZD），而非「回抽笔所在线段的最后中枢」——后者与登记时采纳的中枢不等价（《三买三卖差异点说明.md》统计口径声明已证明两者混用会得出错误结论）。参照物从 feature_dict 既有 `bsp3_zs_height` 的推导路径反查（`add_bs` 时锚定的 `zs`）。中枢后续升级/延伸不改已登记点的证伪基准（登记时快照语义）。

### D8: Part B 依赖 bsp2-change 归档后实施（Part B 时序）

两者同改 `bsp_ladder.py`（类型路由）、`incremental_engine.py`（翻转重刷）、`bsp_store.py`（列宽）。bsp2-change 代码虽已落盘但 in-progress，其 delta 归档（bsp-index spec 同步）是本变更 `bsp-index` delta 的 MODIFIED 基线——并行会互踩验证基线与 spec 合并。实施顺序：Part A 可立即做（纯文档）；Part B 排在 bsp2-change 归档之后。

### D9: 中枢升级排除判据明确不做（Part B 排除项）

严格派要求「依托中枢已升级（内部笔数超 9 笔）的三买剔除」。否决理由：①标准档 T3 样本量 1+1（41 只日线），改动收益无法实证；②中枢延伸计数在增量模式下不稳定（虚段反复合并抖动），会破坏翻转重刷的时间确定性。记为 Non-Goal 防止后续误立项。

### D10: 分型轴判据对象直用既有实现（Part B）

`fractal_strength.fractal_of_bi(bsp.bi, is_buy)` 对 T3 回抽笔完全适用（三买回抽笔是向下笔、末端底分型，`is_buy=True` 走底分型分支；已处理「末端分型未形成返回 None」的盘中态）。分型强弱对 T3 的价值：回抽底分型强 = 回抽动能弱 = 中枢支撑强的微观证据。K 前缀档位映射沿用 bsp2 的 `_FRACTAL_MAP` 先例。

## Risks / Trade-offs

- [未来有人仍以「语义不一致」为由提 `strict_bsp3` 统一改动] → spec ADDED Requirement 写明 SHALL NOT，评审被拦（Part A）
- [E 被后人误读为「已修成成立判据」] → spec `chan-bsp3-confirm` 第一条 Requirement 显式写「SHALL NOT 成为成立判据」「输出时点不变」（Part B）
- [证伪线参照物漂移（重算后中枢对象变化）] → D7 登记时快照语义；feature_dict 记录锚定中枢的区间值而非对象引用
- [四轴组合串超列宽] → 复用 bsp2 的 `VARCHAR(32)` 扩容先例（四轴最长约 20 字符，32 够用）；惰性 DDL + `update-win.sql` 双轨
- [T3 样本量薄导致实证弱] → 实证脚本先跑确认轴档位分布；若 C1 占比极端（<5% 或 >90%），证伪线阈值回炉重议——这是待定项而非设计缺陷
- [与 bsp2-change 实施窗口重叠] → D8 排他时序写进 proposal 依赖段；`/opsx:apply` 启动前检查 bsp2-change 归档状态

## Migration Plan

- Part A：无部署迁移，revert 文档与 spec 即回退
- Part B：`bsp_index.ladder` 存量 T3A/T3B 行从 NULL 回刷为组合值/L4（幂等可重放）；列宽若需扩容走 `bsp_store._ensure_tables()` 惰性 DDL + `WebAPI/update-win.sql` 幂等追加（Windows 机器）；确认轴终态行回刷恒定（时间确定性判据保证）
- 回退：Part B 代码 revert 后存量行回刷为 NULL（回刷脚本幂等反向执行）

## Open Questions

1. **确认窗口长度**（回抽笔后 1 笔还是 2 笔）：影响 C3 时效与信号后移量，41 只日线实证后定——待定项与 bsp2 的窗口选择可对齐但不必相同
2. **时间轴阈值三档切点**：初始拍定后依交叉判别力校准；判别力不足则降级为纯 feature 不成轴
3. **盘中 C0 口径**：盘中最短几根 K 线后允许进入确认窗口评估（影响 `intraday_poll` 轮询翻转频率）
