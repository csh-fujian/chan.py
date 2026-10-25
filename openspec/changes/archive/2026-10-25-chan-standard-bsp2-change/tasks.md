# Tasks

## 0. 前置实证（不动代码，产出定标数据）

- [x] 0.1 新增 `Debug/bsp2_confirm_stats.py`：41 只日线（`Data/kl_store.duckdb`，standard 档）统计 T2/T2S 候选点「回调笔后下一笔/下两笔是否突破 break_bi 高点（强确认）与收复一半（弱确认）」的三档占比、以及信号时点后移量；产出报告落 `文档/`；验证：报告含三档计数、总样本数、后移量分布
- [x] 0.2 同脚本扩展时间轴统计：速度比三档（0.5/1.0）× 确认结果交叉表，验证强档突破率是否显著高于弱档；产出交叉表落报告；验证：若强档/弱档突破率差 < 10 个百分点，在报告中标记「时间轴判别力不足，建议降级为 feature」供评审裁决
- [x] 0.3 线段/笔级别 T2 重合度调研：对同批数据计算 `seg_bs_point_lst` 与 `bs_point_lst` 的 T2 重合度（时间映射口径）；验证：报告给出重合率数字与「是否建议暴露」结论，写入 design.md Open Questions 2 的处置

## 1. 配置与判据纯函数

- [x] 1.1 `BSPointConfig` 新增 T2 阶梯配置组：`bsp2_confirm_window`（取值 1/2，默认待 0.1 实证定）、`bsp2_time_axis_strong`/`bsp2_time_axis_weak`（默认 0.5/1.0）、`bsp2_confirm_level`（strong/weak 两级阈值口径，默认 strong）；验证：`CChanConfig({})` 取到默认值，非法取值抛 `PARA_ERROR`
- [x] 1.2 新增 `WebAPI/bsp2_confirm.py` 纯函数 `confirm_axis(bsp, bi_list, cfg)`：定位回调笔、取窗口 N 笔、按两级阈值判三档；窗口不足输出「进行中」；窗口外数据不进输入（边界断言）；验证：单元用例覆盖突破/收复/未动/进行中/窗口外新高不翻五场景
- [x] 1.3 新增 `WebAPI/bsp2_time_axis.py` 纯函数：速度比计算（`bars` 取笔内 K 线根数）+ 三档分档；验证：单元用例覆盖设计 D4 数值例（0.33→强/0.89→中/1.67→弱）与同回撤率不同时间比的区分
- [x] 1.4 `WebAPI/bsp2_progress.py`：从 `bsp2_reason`/`relate_bsp1` feature 推导 T2 判据链五项进度，两档划分（ceil(5/2)=3）；验证：单元用例覆盖「回撤率短路→P1」「全过未确认→P2」

## 2. 五轴组装与类型分派

- [x] 2.1 新增 `WebAPI/bsp2_ladder.py`：五轴组装（P|S|K|C|T 语法、轴序固定、未知段忽略的解析函数）、佐证窗口取回调笔单笔窗口（复用 `_sub_time_span` 含回退口径）；验证：单元用例覆盖全轴组合字符串生成与解析 round-trip
- [x] 2.2 改 `WebAPI/bsp_ladder.cal_ladder`：L4 短路后按类型分派——T1 家族走既有三轴（代码零改动）、T2/T2S 走 `bsp2_ladder`、T3A/T3B 维持返回 None；验证：单测断言 T1 路径输出与改造前逐字节一致（同输入快照对比）
- [x] 2.3 `WebAPI/fractal_strength` 复用确认：T2 的分型轴直接调用 `fractal_of_bi(bsp2_bi)`；验证：现有分级函数对 T2 回调笔可正常输出（无 bsp1 前置依赖），异常时轴缺席不抛

## 3. 落库与序列化双链路

- [x] 3.1 `bsp_store._ensure_tables()`：`ladder` 列 `VARCHAR(16)` → `VARCHAR(32)` 幂等扩容块；验证：重复执行 `_ensure_tables` 无报错、列宽已变
- [x] 3.2 `update-win.sql` 追加幂等扩容 SQL（带 `-- 2026-10-25 chan-standard-bsp2-change` 日期注释）；验证：本机 PG 重复执行两次均成功
- [x] 3.3 `config_fingerprint.LADDER_SCHEMA_VERSION` 升 `bsp2-5axis-v1`；验证：新旧指纹不同，触发重刷路径（既有 fingerprint 机制单测/日志确认）
- [x] 3.4 `incremental_engine._extract_bsp_rows`：子级计算结果传入 T2 分派路径（佐证轴数据源，复用 `_compute_sub_for_l1`）；验证：落库行中 T2 候选 ladder 为组合值、T3A 仍为 NULL
- [x] 3.5 `serializer._serialize_bsp`：同一 `cal_ladder` 入口自动覆盖（零改动或仅参数透传）；验证：`/api/klines` 单股请求返回的 T2 候选带五轴组合值，与落库值一致（双链路口径一致性断言）

## 4. 翻转与回归验收

- [x] 4.1 步进 vs 批量终态一致（承接既有不变量）：同一标的 `trigger_step=True` 逐根推进 vs 批量模式，最终 `bsp_store_dict` T2/T2S 数量一致、ladder 组合值最终集合一致（允许过程中时间轴/确认轴翻转）；验证：步进回放脚本断言
- [x] 4.2 翻转专项用例：①确认轴窗口内未动→已突破翻转为最高档后不再降；②时间轴强→中降档（回调笔延长）；③已确认为 `L4` 的 T2 点轴证据变化不影响单值；验证：构造 K 线序列驱动 `cal_ladder` 断言三次取值
- [x] 4.3 T1 家族回归基线：改造前后全量 41 只日线的 T1/T1P 候选 ladder 值逐行比对；验证：diff 为空
- [x] 4.4 成立判据零改动回归：改造前后 T2/T2S 成立集合（`bsp_store_dict` 逐点）一致；验证：`Debug/bsp_standard_equivalence.py` 扩展 T2 断言或新增对比脚本

## 5. 文档回标

- [x] 5.1 《文档/二买二卖差异点说明.md》§4.4/§4.7 回标更新（§4.4 → 佐证轴落地、§4.7 → 确认轴落地），§七 回标表追加对应行；验证：两节状态与代码现状一致
- [x] 5.2 `Document/README.md` 买卖点参数段补 T2 阶梯配置组（`bsp2_confirm_window` 等）；验证：可检索到 `bsp2_confirm_window` 且默认值与代码一致
- [x] 5.3 `文档/缠论策略.md` 补 T2 五轴阶梯语义节（判据链不变、五轴为证据标注）；验证：与 spec `chan-bsp2-ladder` 的轴定义表述一致
- [x] 5.4 顺手项（design Open Questions 1，评审定）：`Document/README.md:580` `bsp2_retrace_zs` 语义描述修正为「回调笔所在线段」（与代码 `check_retrace_in_zs` 实际口径对齐）；验证：文档与代码口径一致

## 6. 部署演练

- [x] 6.1 Windows 本机：fingerprint bump → 全量重刷一只股票（sz.000001 日线）→ `psql` 查询验证 T2 候选行 ladder 为五轴组合值、T1 行与改造前逐字节一致、T3A 行为 NULL、无截断值（组合长度 ≤ 32）；验证：SQL 查询结果人工核对四项
