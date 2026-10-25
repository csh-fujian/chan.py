# Design

## Context

见 proposal.md（Why / What Changes）。当前基建形态（chan-bsp-ladder-change 交付或即将交付）：

- `WebAPI/bsp_ladder.cal_ladder` 是阶梯推导唯一入口：L4 短路 → `is_bsp1_family` 过滤（非一买返回 None）→ 三轴拼接。落库链路（`incremental_engine._extract_bsp_rows`）与序列化链路（`serializer._serialize_bsp`）共用此入口，口径单点。
- 三轴的三个轴函数各自独立：`bsp_progress.progress_axis`（读 feature）、`bsp_ladder.corroboration_axis`（读子级容器）、`fractal_strength.fractal_of_bi`（纯只读分级）。缺证据时轴缺席，`cal_ladder` 已支持「部分轴缺席」。
- 落库为 **DELETE→INSERT 全集替换**（`persist_full_set`，事务内 `_delete_bsp_rows` + `_insert_bsp_rows`）——每次重算整表重写，**没有逐行 UPDATE**。这一形态对翻转语义的设计有决定性影响（见 D2）。
- `bsp_index.ladder` 现为 `VARCHAR(16)`（三轴组合值上限），惰性 DDL（`_ensure_tables`）+ `update-win.sql` 双轨扩容先例已存在。
- `LADDER_SCHEMA_VERSION = "3axis-v1"` 参与配置指纹，阶梯口径升级会触发全量重刷（fingerprint bump）。
- T2/T2S 判据链的中间事实已在 feature：`bsp2_reason`、`bsp2_retrace_rate`、`bsp2s_*` 系列。`bsp2_retrace_zs` 的「当前线段 vs 一买线段」口径差异（文档/README 与代码不一致）仍未修正，本变更不修（属文档同步项，见 Open Questions）。

## Goals / Non-Goals

**Goals:**

- T2/T2S 候选点获得五轴阶梯，落库与序列化双链路口径一致
- 确认轴（事后价格）以单向终态落进既有翻转框架，时间轴支持双向翻转
- 既有 T1 家族阶梯行为逐字节不变（回归验证）

**Non-Goals:**

- 不改 `treat_bsp2`/`treat_bsp2s` 成立判据、不改 `bsp_is_sure` 水位线口径
- 不暴露 `seg_bs_point_lst` 到 WebAPI（仅做重合度调研，见 Open Questions）
- 不做量能/ML 特征（显式排除）
- 不动 T3A/T3B（保持 NULL 过渡）
- 不为 T2 引入独立候选容器（`bsp1_list`/`bsp1_sure_list` 的 T2 对应物）——T2 候选性继续由水位线 + 阶梯表达

## Decisions

### D1 五轴复用 `cal_ladder` 单点，T2 分派而非平铺

`cal_ladder` 保持唯一入口，内部按 `is_bsp1_family` 分派：T1 家族走既有三轴函数；T2/T2S 走新的 `bsp2_ladder` 推导模块（同层新文件，结构与 `bsp_ladder` 平行）。L4 短路在分派**之前**，保证全类型已确认语义统一。

- **为什么不并入三轴函数**：T2 的进度轴证据源（`bsp2_reason` 等 feature）与佐证窗口（回调笔窗口 vs c 走势段窗口）都不同，强行共用会把两个家族的判定搅在一起；分派保持 T1 侧零改动。
- **为什么同在 WebAPI 层**：沿用「级别判定在 WebAPI 层、不修改计算内核」的既有 spec 约束。T2 五轴全部只读：进度轴读 feature、确认轴/时间轴读行情笔序列（`bi_list`，已有）、佐证轴读子级容器、分型轴复用 `fractal_strength`。

### D2 翻转不引入逐行 UPDATE，靠 DELETE→INSERT 全集替换天然实现

落库是整表替换（每次重算 DELETE 全部行再 INSERT 当前全集），所以「时间轴降档」「确认轴翻转为已确认」**天然生效**：下一次重算写入新档位即可，不需要任何 UPDATE 语句或终态保护逻辑。

- **终态单向性由此实现**：确认轴的判据本身带终态语义——窗口走完未突破后，无论重算多少次，窗口内事实不变，推导结果恒为降级档。「不回退」不是靠存储层锁，而是靠**判据的时间确定性**（窗口只考察固定几笔）。这比在 DB 上加终态字段简单一个数量级。
- **窗口外新高不翻**同理：判据只看窗口内笔，窗口外行情不进判据输入。
- **风险提示**：这意味着「翻转语义」的正确性完全落在判据函数的纯度上——判据若误读窗口外数据，终态就被破坏。验收用例必须覆盖「窗口外突破不翻」场景（见 tasks）。
- **替代方案（否决）**：终态落独立列 + UPDATE 语句。更重的 schema、双写路径、与全集替换模式冲突，无收益。

### D3 确认轴窗口的确定性输入：从 `bi_list` 取「回调笔后的 N 笔」

确认轴判据 `confirm_axis(bsp, bi_list, cfg)`：定位 `bsp2_bi.idx`，取其后的 N 笔（N = 窗口长度，默认待实证定），考察窗口内**同向反弹笔**的最高价（买侧）对两级阈值的突破。卖点镜像。

- **两级阈值**：强确认 = `break_bi` 高点；弱确认 = 收复 `break_bi` 振幅一半（`break_bi.low + 0.5*amp`）。默认取强确认口径（spec 已定）。
- **窗口不足**（回调笔后不足 N 笔）：确认轴输出「进行中」档（未终态），不是缺席——与「未动」区分：未动是终态，进行中是还没走完。这是 spec 三档之外的一个瞬时态，序列化为一档标签，落库语义上属未终态。
- **为什么读 `bi_list` 而非 K 线**：窗口笔的数量用笔计，跨笔中途的 K 线新高不构成「笔突破」——与缠论「次级别走势」粒度一致，也避免盘中毛刺。

### D4 时间轴速度比：`bars` 取笔内 K 线根数（合并 K 线数）

`v = (amp(bsp2_bi)/amp(break_bi)) / (bars(bsp2_bi)/bars(break_bi))`，`bars` 取 `len(bi.__klu_lst)`（笔内 K 线单元数，非合并 K 线组数）。三档阈值 0.5/1.0 默认、可配置（`bsp2_time_axis` 配置组）。

- **为什么用 K 线根数**：合并 K 线数受包含关系处理影响（同一形态不同包含历史会得不同 bars），K 线根数是行情的固有属性，跨配置可比。
- **候选笔延长 → 档位滑动**：由 D2 的全集替换天然支持，验收用例须覆盖降档。

### D5 T2 阶梯语法：语义前缀 `P|S|K|C|T`，轴序固定

组合字符串形如 `P1|S3|K2|C3|T1`（轴顺序：进度/佐证/确认/分型/时间；档位数字 1=低 3=高，确认轴 3=已突破）。`L4` 单值不变。分隔符复用 `AXIS_SEPARATOR`。

- **为什么不用 L 续编号**：L1/L2/L3/L4 在 T1 语法中已语义固化（L2-x 佐证、L3-x 分型、L4 已确认），T2 复用会撞车；独立前缀 + bsp_type 路由，两套语法无歧义。
- **解析规则**：按 `|` split，段首字母识别轴，未知段忽略（向前兼容：后续加轴不破坏旧值解析）。

### D6 `ladder` 列扩容 `VARCHAR(16)` → `VARCHAR(32)`

五轴组合最大约 5×2+4=14 字符，取 32 留余量。沿用双轨：`bsp_store._ensure_tables()` 的 `ALTER COLUMN TYPE` 幂等块 + `update-win.sql` 追加（带日期注释）。`LADDER_SCHEMA_VERSION` 升 `bsp2-5axis-v1` 触发 fingerprint bump → 全量重刷，存量 T2/2s 的 NULL 行在重刷中自然变为组合值，**不需要独立回刷脚本**（全集替换会重写所有行）。

- **替代方案（否决）**：存量行定向 UPDATE。全集替换已覆盖，定向 UPDATE 是第二条路径，违反单路径原则。

### D7 佐证轴窗口映射：回调笔窗口，复用 `_sub_time_span` 回退口径

T2 的佐证窗口 = `bsp2_bi` 所在笔区间（`bsp2_bi.idx ~ bsp2_bi.idx`，单笔窗口），映射到子级时间区间沿用 `bsp_ladder._sub_time_span`（含父级时间轴外扩回退——落库链路父级单级别时子级时间戳不可得的场景）。子级证据分档判定与 T1 共用 `corroboration_axis` 的核心逻辑，仅窗口参数不同。

- **为什么单笔窗口而非 c 走势段窗口**：T2 的结构单元就是回调笔，佐证问的是「回调位置上子级别有没有走出同向结构」，不是「离开段」。T1 的 c 窗口语义不适用于 T2。

### D8 进度轴：T2 判据链五项，两档划分

判据链 ①一买成立（`bsp1_sure_dict` 命中）②回调笔存在 ③不破极值（恒过）④回撤率 ⑤中枢关联（`bsp2_retrace_zs` 开启时）。证据源：`bsp2_reason` feature（`check_bsp2_standard` 已透出短路原因）+ `relate_bsp1` 是否非空。两档：已过项 ≤ 链半（ceil(5/2)=3）→ P1，> 3 → P2；全过但未确认 → P2。

- **注意**：②③失败时 T2 根本不会 add_bs（无候选点），所以进度轴实际可见的最低进度是 ④/⑤ 短路处——P1 档在实测中只由 ④回撤率未过 情形产生。这不是缺陷：进度轴的语义是「判据链走到哪」，不是「完整复现失败原因」。

## Risks / Trade-offs

- **[风险] 时间轴阈值 0.5/1.0 拍脑袋** → 前置实证任务（三档 × 突破结果交叉统计）先跑，阈值进配置可调；判别力不足时该轴降级为 feature（spec 已预留该出口）
- **[风险] 确认轴窗口默认值未定** → 实证任务（三档占比 + 时点后移量）产出数据后在 apply 评审定稿；窗口长度进配置，改值不破坏终态（窗口只决定考察范围）
- **[风险] T1 回归破坏**（`cal_ladder` 是共享入口）→ 分派在 L4 短路后、三轴函数前，T1 路径代码零改动；验收含 T1 阶梯基线逐字节比对（用 ladder change 的既有验证脚本）
- **[风险] 五轴组合字符串超 32 字符**（未来加轴）→ D5 解析规则按段前缀识别、未知段忽略，列宽再扩容走同一 DDL 双轨先例
- **[权衡] 确认轴「进行中」档是 spec 三档外的瞬时态** → 不为它单开 spec 档位（落库值与「未动」同档数但语义上属未终态），验收用例区分「窗口未走完」与「窗口走完未突破」两种输入的档位输出
- **[权衡] 判据纯度承载终态语义**（D2）→ 确认轴判据函数做纯函数化 + 「窗口外数据不进输入」的边界测试

## Migration Plan

1. 前置实证（不动代码）：`Debug/` 新增统计脚本跑 41 只日线 → 定窗口默认值与时间轴阈值初值
2. 实现 + 单元验证（判据纯函数）
3. `LADDER_SCHEMA_VERSION` bump → fingerprint 失效 → 部署演练：Windows 本机全量重刷一只股票 → psql 验证 T2 行 ladder 为组合值、T1 行与改造前逐字节一致、T3A 行仍为 NULL
4. `update-win.sql` 幂等追加（Windows 机器运行）
5. 回滚：还原代码 + `LADDER_SCHEMA_VERSION` 回退触发下一次重刷回旧口径；`ladder` 列宽扩容可保留（无害）

## Open Questions

1. **`bsp2_retrace_zs` 的 README 语义错位**（文档写「一买所在线段」、代码判「当前线段」）：属文档同步小修，建议随本变更的文档任务顺手修掉，还是留给独立小变更？（不影响本设计——本设计不依赖该开关语义）
2. **`seg_bs_point_lst` 重合度调研结论的处置**：若重合度 > 90%，维持零暴露；若显著低，暴露方案另立变更（本变更只产出调研数字）
