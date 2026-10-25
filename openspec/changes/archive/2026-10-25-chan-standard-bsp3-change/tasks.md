# Tasks: chan-standard-bsp3-change

> Part A 纯文档 + spec 回标（零计算逻辑改动），可先行；Part B 是 WebAPI 层功能变更（成立判据仍零改动），须在 `chan-standard-bsp2-change` 归档后实施（design D8）。

## 1. Part A：README 参数段修正（§4.6 处置，可先行）

- [x] 1.1 修改 `Document/README.md` 买卖点参数段 `strict_bsp3` 行（现 `:571`）：把「3类买卖点对应的中枢必须紧挨着1类买卖点，默认为 False」拆为两条分支描述——三买A：中枢的**进入笔**为一买笔的下一笔；三买B：中枢的**离开笔**即一买笔；并注明两分支「紧邻」定义不同、默认 `False`、标准档输出不受影响。验证：修改后两种分支条件与 `BSPointList.py:952` / `:1022` 的代码条件一一对应，无笼统表述残留
- [x] 1.2 核对本行改动未触碰参数段其他行（`bsp3_peak`、`bsp3a_max_zs_cnt` 等已由归档任务 14.2 修正，不得重写）。验证：`git diff Document/README.md` 仅含 `strict_bsp3` 一处的行级变更

## 2. Part A：差异点文档回标与决策补记（可先行）

- [x] 2.1 《文档/三买三卖差异点说明.md》§4.6 末尾补记处置决策：双分支语义差异为结构性必然（T3A 中枢在 next_seg、T3B 在当前 seg），不再追求统一，引用本变更与 spec 新增 Requirement。验证：§4.6 末尾存在指向 `chan-standard-bsp3-change` 的决策段
- [x] 2.2 §4.11 与 §五「一句话」结论后补记：标准档重写已消除实质风险（同笔重叠为空），编号保留、不修复理由（改名破坏面：`BSP_TYPE` 枚举、`bs_type` 配置、PG 存量行、前端、脚本）。验证：§4.11 / §五 均有指向本变更的不修复理由段
- [x] 2.3 §4.8 处补记：线段级别 T3 零下游消费为已确认现状，维持不暴露；与《二买二卖差异点说明.md》§4.4 的 T2 调研结论同向，T3 不另立项。验证：补记与「次级别走势类型的层级落地」Requirement 的双口径表述不矛盾
- [x] 2.4 §七 回标表：§4.6 / §4.8 / §4.11 三行状态由「部分修复」改为「设计性收口（不修复）」，对应任务号列补 `chan-standard-bsp3-change`（状态取值说明处同步加一行「设计性收口」定义）。验证：表格三行状态与状态取值说明一致
- [x] 2.5 §八 复核记录末尾追加一行：复核发现的代码事实（`strict_bsp3` 双分支差异仍在）不变，处置终态由本变更给出（设计性收口）。验证：追加行不改动 §八 原有更正内容

## 3. Part B：确认轴纯函数模块（依赖 bsp2-change 归档）

- [x] 3.1 新建 `WebAPI/bsp3_confirm.py`：`confirm_axis(bsp, bi_list, cfg)` 纯函数，档位 C3（后续笔突破回抽笔端点）/ C2（收复回抽幅度一半）/ C1（跌回锚定中枢区间，证伪终态）/ C0（窗口不足进行态）；证伪基准取登记时锚定中枢的区间值（design D7，从 feature_dict 反查，非对象引用）；两级阈值口径 strong/weak 同 bsp2；窗口笔数读 `bsp3_confirm_window` 配置（默认待定项 1 定夺）。验证：`Debug/bsp3_axes_unit_test.py` 单元用例覆盖四档各自触发路径 + 买卖镜像 + 窗口外数据不可达（时间封顶断言）
- [x] 3.2 在 `treat_bsp3_before`/`treat_bsp3_after` 的 `add_bs` feature_dict 中补记锚定中枢区间值（`bsp3_zs_low` / `bsp3_zs_high` 两个只读 feature，供证伪线反查）——**这是唯一触碰 `ChanAnalyse/BuySellPoint/` 的改动，且为纯 feature 附加，不参与任何成立判定**。验证：`Debug/bsp3_axes_unit_test.py` 断言新增 feature 存在且与锚定中枢一致；`git diff ChanAnalyse` 仅含该两行 feature 写入；T3 成立点集合与改动前逐点一致（41 只日线 count 对比）

## 4. Part B：四轴阶梯模块与类型路由

- [x] 4.1 新建 `WebAPI/bsp3_ladder.py`：`bsp3_ladder(bsp, bs_point_lst, bi_list, cfg, sub_bs_point_lst, sub_kl)` 组装四轴（轴序 佐证→确认→分型→时间，design D6 无 P 轴）；佐证轴窗口 = 回抽笔单笔区间（复用 `bsp_ladder._sub_time_span` / `_in_window_and_same_dir` / `_sub_progress_is_early` / `_sub_has_fractal_in_window`，同 bsp2 版模式）；确认轴调 3.1；分型轴 `fractal_strength.fractal_of_bi` + K 档映射；时间轴复用/平移 `bsp2_time_axis` 的速度比口径（参照笔换突破笔）。验证：单元用例覆盖各轴独立缺席、组合串格式、子级不可用时佐证轴缺席
- [x] 4.2 `WebAPI/bsp_ladder.py` `cal_ladder` 类型路由接入：T3A/T3B 分支从 `return None` 改为调 `bsp3_ladder`（L4 短路保持在上层全类型语义，分派位置同 bsp2 的 D1 设计）。验证：路由单测——T1 走三轴、T2 走五轴、T3 走四轴、L4 短路全类型生效；grep 确认无残留 `T3A/T3B：维持 NULL` 分支
- [x] 4.3 配置项：`bsp3_confirm_window` / `bsp3_confirm_level`（同 bsp2 命名模式）加入 `CBSPointConfig` 与 `CChanConfig` 参数说明；`config_fingerprint.py` 纳入指纹。验证：改窗口值后 fingerprint 变化；未配置时默认值生效

## 5. Part B：落库链路与翻转重刷

- [x] 5.1 `WebAPI/incremental_engine.py`：T3 候选行携带四轴 ladder 落库；确认轴终态单向翻转（C0 → C1/C3 可翻，C1/C3 终态不重刷，fingerprint 不 bump）；佐证/分型/时间轴随重算收敛（同 bsp2 口径）。验证：翻转用例——C0 补数据后转终态、终态点重复重算行不变、证伪行不被撤销
- [x] 5.2 `WebAPI/bsp_store.py` `_ensure_tables()`：ladder 列宽确认容纳四轴组合（`VARCHAR(32)` 沿用 bsp2 扩容，若已扩则零改动）；`WebAPI/update-win.sql` 幂等追加变更记录（Windows 机器，注释执行时间）。验证：重复执行 `_ensure_tables` 幂等；`update-win.sql` 可重放
- [x] 5.3 存量 T3A/T3B 行回刷脚本（NULL → 组合值/L4，幂等可重放）。验证：对已回刷数据二次执行零变更；终态行档位与首次推导一致

## 6. Part B：实证与前端

- [x] 6.1 `Debug/bsp3_confirm_stats.py`：41 只日线统计——确认轴四档分布、C3 时点后移量（窗口 1 vs 2 笔对比）、时间轴三档 × C3/C1 交叉判别力。产出写回 design 待定项 1/2 的结论。验证：脚本输出三组统计并落 `Debug/` 结果文件（**实测 41 只日线标准档仅 1 个 T3 成立点，样本不足，三待定项均无法定标——见 design Open Questions 的更新**）
- [x] 6.2 前端 `front/src/utils/bspLadder.ts`：T3 四轴档位词表与 tooltip 说明（S/C/K/T 语义、无 P 轴注明、C1 证伪终态文案）；买卖点页「级别」列与 K 线 hover 渲染 T3 组合值。验证：mock 一条 `S3|C2|K3|T1` 数据，页面展示与 tooltip 正确、解析非法段跳过
- [x] 6.3 《文档/三买三卖差异点说明.md》补「要素 E 回标」：§三 表 E 行与 §4.8 相关表述标注「E 缺口已由 chan-standard-bsp3-change 确认轴补全（事后确认层，非成立判据）」；`Document/README.md` 补 T3 阶梯参数段。验证：回标行与本变更 spec 语义一致

## 7. 全链验证与收尾

- [x] 7.1 `openspec validate chan-standard-bsp3-change --strict` 通过。验证：命令退出码 0
- [x] 7.2 Part A 全链一致性：README → 差异点文档 → spec delta → `BSPointList.py` 实际代码，四方对 `strict_bsp3` 两分支语义表述一致。验证：抽查 `:952`/`:1022` 与文档对应
- [x] 7.3 Part B 成立性零改动回归：41 只日线 T3A/T3B 成立点集合与本变更实施前逐点一致（ladder 仅标注差异）；`Debug/bi_test.py` / `Debug/bsp2_axes_unit_test.py`（回归 bsp2 不受影响）通过。验证：对比脚本输出成立点集合哈希一致
- [x] 7.4 端到端：`Debug/bsp3_axes_unit_test.py` + `Debug/bsp3_confirm_stats.py` + 翻转用例全绿；`git status` 确认 `ChanAnalyse/BuySellPoint/BSPointList.py` 仅有 3.2 的两个 feature 写入

## 8. Workflow follow-up

- 归档时把三个 delta spec（chan-bsp-standard / chan-bsp3-ladder / chan-bsp3-confirm / bsp-index）同步进 `openspec/specs/`（`/opsx:archive` 流程处理）
- `/opsx:apply` 启动 Part B 前检查 `chan-standard-bsp2-change` 已归档（design D8 排他时序）
- 实证待定项 1（确认窗口）、2（时间轴阈值）由 6.1 产出回填 design，若结论改变轴结构（如时间轴降级为 feature）需回炉 specs
