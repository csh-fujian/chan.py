## 1. 基础设施：力度算法与配置骨架

- [x] 1.1 在 `ChanAnalyse/Common/CEnum.py` 的 `MACD_ALGO` 中新增 `DIFF_PEAK`，验证枚举可被 `SetMacdAlgo` 的字符串映射识别（`"diff_peak"`），且 `MACD_ALGO.DIFF` 语义保持原样未改
- [x] 1.2 在 `ChanAnalyse/Bi/Bi.py` 实现 `Cal_MACD_diff_peak`（笔区间内 DIF 线的极值：买取 `min(DIF)`、卖取 `max(DIF)`），并在 `cal_macd_metric` 挂上该分支；验证对同一笔 `diff_peak` 与现有 `peak`（柱体）取值不同且方向正确
- [x] 1.3 把 `Cal_MACD_area` / `Cal_MACD_peak` / `Cal_MACD_half` / `Cal_MACD_diff` / `Cal_Rsi` 中「遍历 K 线并按方向累积」的逻辑抽为可复用的模块级函数，验证 `CBi` 重构后 output 与重构前逐笔完全一致（对比重构前后对 41 只日线的段落指标快照）
- [x] 1.4 在 `ChanAnalyse/Seg/Seg.py` 的 `cal_macd_metric` 中接入上述算法（`area`/`full_area`/`peak`/`diff_peak`/`rsi`），验证线段级别对同一线段调用这些算法不再抛 `CChanException`
- [x] 1.5 移除 `ChanAnalyse/ChanConfig.py:214-217` 对 `seg_bs_point_conf` 的 `macd_algo` 硬编码 `slope`，改为与笔级别一致的默认 `peak`；验证 `seg_bs_point_conf.b_conf.macd_algo` 与 `bs_point_conf.b_conf.macd_algo` 默认值相同

## 2. 配置项与档位预设

- [x] 2.1 在 `ChanAnalyse/BuySellPoint/BSPointConfig.py` 的 `CPointConfig` 增加一买开关组（`bsp1_trend`、`bsp1_new_extreme`、`bsp1_dif_div`、`bsp1_zero_axis`、`bsp1_new_extreme_mode`、`bsp1_trend_mode`、`bsp1_zs_extend_to_seg_end`），并在 `CBSPointConfig` 构造签名中贯穿；验证构造 `CChanConfig({})` 不抛异常且默认值符合规范
- [x] 2.2 在 `CPointConfig` 增加二买/类二开关组（`bsp2_retrace_zs`、`bsp2s_require_zs`、`bsp2s_rate_mode`、`bsp2s_follow_2` 语义修正标记），默认值分别为 `False` / `True` / `"amp"`；验证 `CChanConfig({})` 取到上述默认值
- [x] 2.3 在 `CPointConfig` 增加三买开关组（`bsp3b_mode`、`bsp3_peak_on_breakout`、`bsp3_follow_1_mode`），默认值分别为 `"standard"` / `True` / `"sure"`；验证 `CChanConfig({})` 取到上述默认值
- [x] 2.4 在 `ChanAnalyse/ChanConfig.py` 的 `set_bsp_config` 增加 `bsp_preset` 解析：`standard`（默认）与 `legacy` 两档，预设先展开为默认字典、用户显式 key 后覆盖；`legacy` 展开为 `{divergence_rate: inf, min_zs_cnt: 1, bsp1_trend: False, bsp1_new_extreme: False, bsp1_dif_div: False, bsp1_zero_axis: False, bsp2s_require_zs: False, bsp2s_rate_mode: "disp", bsp3b_mode: "legacy", bsp3_peak_on_breakout: False}`；验证未知预设值抛 `CChanException`，且显式单项配置能压过预设
- [x] 2.5 在 `ChanConfig.py` 的 `ConfigWithCheck` 白名单中登记全部新增 key；验证拼错 key 仍按既有行为抛 `CChanException`
- [x] 2.6 为枚举型配置（`bsp_preset`、`bsp3b_mode`、`bsp2s_rate_mode`、`bsp1_trend_mode`、`bsp1_new_extreme_mode`、`bsp3_follow_1_mode`）增加取值白名单校验；验证非法取值抛 `CChanException` 且错误信息含合法取值列表
- [x] 2.7 把默认档位的 `divergence_rate` 与 `min_zs_cnt` 调为 `0.9` / `2`，`legacy` 档位保持 `inf` / `1`；验证 `CChanConfig({})` 与 `CChanConfig({"bsp_preset":"legacy"})` 的这两个值分别是 0.9/2 与 inf/1

## 3. 一买判据（核心）

- [x] 3.1 在 `ChanAnalyse/BuySellPoint/BSPointList.py` 新增层级无关纯函数 `_bsp1_standard_ok(ele, ele_list, zs_lst, cfg)`，按顺序返回各条件的通过情况与不通过原因；验证对 `CBi` 与 `CSeg` 两种入参都能正常执行不抛类型错误
- [x] 3.2 实现趋势前提：要求最后一个中枢与前一个中枢满足 `z2.high < z1.low`（买）/ `z2.low > z1.high`（卖），另提供 `overlap` 模式的弱定义；验证构造两个依次下移中枢的合成笔序列可通过、两个重叠中枢不可通过
- [x] 3.3 实现创趋势新低：起点取「第一个中枢的进入要素」，比较范围为该起点之后到判定要素为止的全部同向要素；验证 `trend_start` 模式与 `prev_zs_in` / `all` 两模式在同一数据上给出预期的不同通过数（笔级别参考值 28 / 63 / 26，允许因数据快照不同而浮动）
- [x] 3.4 实现 DIF 背驰：比较进入最后中枢的要素与离开要素的 DIF 极值，要求买点离开段 DIF 更高、卖点更低；验证与面积判据的「与」关系——面积过而 DIF 不过时整体不通过
- [x] 3.5 实现零轴回抽：取进入段结束到离开段开始之间的 K 线，检查 DIF 是否出现反号；验证两段之间 DIF 恒为同号时不通过
- [x] 3.6 把 `treat_bsp1` 改为调用 `_bsp1_standard_ok`，保留 `bs1_peak` 与 `is_divergence` 的既有链路作为其中两个条件；验证 `legacy` 档位下 41 只日线的 T1 逐笔与改造前完全一致
- [x] 3.7 让线段级别的买卖点计算路径调用同一个 `_bsp1_standard_ok`（元素为 `CSeg`、中枢为 `segzs_list`）；验证 `seg_bs_point_lst` 能产出 T1 且其元素类型为线段
- [x] 3.8 收紧差异点 4.8：把「中枢须延伸到线段末笔」从强制转 T1P 改为受 `bsp1_zs_extend_to_seg_end` 控制的开关（默认关闭）；验证关闭后 T1P 数量下降、T1 候选池上升
- [x] 3.9 修正 `ZS.is_divergence` 的 `divergence_rate > 100` 分支语义：默认档位下不再「无条件视为背驰」，改为显式表示「关闭背驰判据」且不影响结构条件的判定；验证 `legacy` 档位仍复现旧输出

## 4. 候选与成立分层、引用口径

- [x] 4.1 在 `CBSPointList` 新增 `bsp1_sure_list` / `bsp1_sure_dict`，只收录 `is_target_bsp=True` 的一买；`bsp1_list` / `bsp1_dict` 语义保持不变；验证候选数与成立数可分别读取
- [x] 4.2 把 `treat_bsp2` / `treat_bsp3_before` / `treat_bsp3_after` 中 `relate_bsp1` 的取值统一改为成立口径（`bsp1_sure_dict`）；验证不存在「二买/三买引用未成立一买」的样本
- [x] 4.3 让 `clear_bsp1_end` 同步清理新增的成立集合，验证增量重算后两个集合长度一致且在尾部同步收缩

## 5. 等价性与敏感性验证

- [x] 5.1 新增 `Debug/bsp_standard_equivalence.py`：对 41 只日线分别以 `legacy` 档位运行，与改造前保存的基线逐笔逐类型比对，验证差异为 0
- [x] 5.2 在 `Debug/bsp_standard_equivalence.py` 中增加逐条件测量：一买四个开关各单独开启一次，输出 T1 / T1P / T2 / T2S / T3A / T3B 六类数量表，验证单条件影响可被单独观察
- [x] 5.3 增加组合测量：从全关到全开的逐级递增，输出笔级别与线段级别两张漏斗表，验证严格化后 T1 数量单调不增（差值仅来自 4.8 的放宽）
- [x] 5.4 记录改造前基线数字以作对照：41 只日线（`divergence_rate=0.9`）为 `1:134 / 1p:39 / 2:166 / 2s:157 / 3a:33 / 3b:33`；legacy 档（`inf`/`min_zs_cnt=1`）为 `1:258 / 1p:69 / 2:318 / 2s:317 / 3a:61 / 3b:50`。验证脚本能复现两组数字

## 6. 下游衔接

- [x] 6.1 在 `WebAPI/bsp_ladder.py` 的 L3 背驰判定中改用新档位的力度口径（默认 `peak` 与 `diff_peak` 的 `与`），验证 `DIVERGENCE_RATE` 常量与内核默认 `divergence_rate` 一致；同时删除该文件 `:42` 与 `:44` 中「内核默认 divergence_rate=inf（保送）」的过期注释
- [x] 6.2 排查下游按类型统计的分母变化：T1 从 258 降到 5~23、T2S 从 157 降到约 90、T3B 从 33 增到约 81，买卖点绩效（胜率/盈亏比）与监控预警阈值的分母随之改变。验证在 `WebAPI/` 中定位全部「按 `bsp_type` 计数/求均值」的读取点并逐条记录其分母变化后的合理性（不要求改业务逻辑，但必须形成清单）；确认 `bsp_ladder.py` 的 L1/L3 统计不因 T3B 数量增加而放大预警量

  **执行结果**：8 个读取点的清单已写入 `WebAPI/performance_store.py` 模块 docstring（表格：位置 / 口径 / 分母变化后的合理性）。其中 7 处随分母变化但语义自洽，**第 6 处（`strategy_store` 的 `bsp_query` 范围固化）需人为注意**——同一查询条件在改造前后会固化成不同股票集，已在该表格后写明处置建议。

  `bsp_ladder` 的预警量**不随类型数量缩放**（逐点判定，非比值），实测（41 只日线、笔级别）：

  | 档位 / 配置 | L2 | L3 | L4 | L3 占比 |
  |---|---|---|---|---|
  | standard（默认，T3B 合计 1） | 7 | 2 | 23 | 6.2% |
  | standard + `bsp3_follow_1=False`（T3B 放开到 89） | 32 | 9 | 181 | 4.1% |
  | legacy（基线） | 128 | 87 | 816 | 8.4% |

  T3B 从 1 增到 89 时 L3 占比反而从 6.2% 降到 4.1%——三买是「突破后回抽」的强结构信号，其所在笔多数不满足背驰条件。**结论：无需为 T3B 增加额外阈值**，已写入 `bsp_ladder.DIVERGENCE_RATE` 上方注释。
- [x] 6.3 用 `WebAPI/incremental_engine.py` 的 `recompute_stock` 对库内全部股票重跑一次，验证 `bsp_index` 中各类 `bsp_type` 的行数与重算结果一致、无残留旧口径行

  **执行结果（2026-10-21）**：`recompute_stock(force_full=True)` 跑遍库内全部 171 个 `(code, kl_type, autype)`：
  - **64 成功**（走 `full`，即指纹不匹配强制全量，同 D12 预期）
  - **1 失败**：`sh.600007 5m` 的 `RecursionError`（见 15.6，既有环境限制，与本次改造无关）
  - **106 跳过**：`(code, kl_type)` 在 DuckDB 无 K 线

  跳过项暴露了原任务未覆盖的问题：`bsp_index` 有 **103 个组合、13183 行（占全表 92%）**在 DuckDB 里已无对应 K 线——既无法重算、也无法验证是否为旧口径，是历史灌数/周期变更留下的孤儿行。经用户确认后**已删除**（先备份到 `Log/bsp_index_orphans_backup.csv` 与 `Log/bsp_index_orphan_combos.txt`，四表 `bsp_index` / `chan_structure` / `recompute_cursor` 一并清理，`chan_snapshot` 本无这些组合）。

  删除后复核：`bsp_index` 剩 46 组合 / 1176 行，**全部**在 DuckDB 有 K 线（孤儿组合 0），类型分布 `2:358  1:288  2s:270  3a:95  3b:91  1p:74`，无未知 `bsp_type`，全部带 `ladder`。至此「无残留旧口径行」成立：剩余每一行都可被当前配置重新算出。
- [x] 6.4 检查前端 K 线买卖点覆盖层与买卖点页在 T1 大幅减少、T2S 减少约 43%、T3B 增加后的展示，验证空态与文案不误导（不要求改前端代码）

  **执行结果（2026-10-22，真实后端 `WebAPI.main:app` + `npm run dev` + Chrome 实测）**：
  - **买卖点页**：类型下拉共 12 项，`3B(后)` / `3B(内)` / `3S(后)` / `3S(内)` 均可选；查询 `3B` = 12 条，恰等于 `3B(后)` 8 + `3B(内)` 4，合并标签与拆分标签口径自洽
  - **空态**：默认「最近三个交易日」范围内无数据时显示「暂无买卖点记录，请调整查询条件」——文案为条件性提示，不会让用户误以为系统无信号。实测库内最新数据为 2026-10-09，默认范围（10-20~10-22）必然空态，属数据水位而非缺陷
  - **K 线覆盖层**：`/api/klines?symbol=sh.600007&period=1d` 返回 `types: ["1","2","3a","3b"]` 四个买卖点，同一标的内 `3a` 与 `3b` 并存——正是需要区分标签的场景；`bspLabel` 实测输出 `3a→3B(后)`、`3b→3B(内)`，覆盖层不再撞名
  - **绩效页**：侧栏分类已显示「三类(后) (中枢在下一条线段)」「三类(内) (中枢在当前线段)」，聚合行的中性标签不含买卖方向，不会把三买误渲染成三卖

  **本任务顺带修改了前端**（原任务写「不要求改前端代码」，但实际不改就会显示错误，见 15.2/15.4/15.5）：标签映射拆分、绩效页 `displayLabel` 方向误判修正、mock 词表对齐。

  **同时发现并修复的阻断级回归**：清理 `routers/bsp.py` 的方向化标签表时，`@router.get("")` 装饰器被误留在文件中间、套到了 `_to_ms` 辅助函数上，导致 `/api/bsp` 全部请求 422（`_to_ms` 的形参被当成必填查询参数）。已在实测中发现并修复，重启后验证 `/api/bsp` 恢复正常。

## 7. 参数覆盖暗坑清理（关键：不清理则改造在调用点完全失效）

> 本节独立成组的原因：`CChanConfig` 的取值是「默认 → 用户显式 key 覆盖」。
> 任何调用方只要显式写了 `divergence_rate` / `min_zs_cnt` / `bs1_peak` / `max_bs2_rate` 等，
> 就会**静默压过新默认值**，使该入口完全不体现本次改造。这类覆盖点在仓库中
> 分布 4 类，必须逐一处置并留下可验证的防回归手段。

- [x] 7.1 建立覆盖点清单：用 `grep -rn "divergence_rate\|min_zs_cnt\|bsp1_only_multibi_zs\|bs1_peak\|max_bs2_rate\|bsp2s\|bsp3" --include="*.py" .` 排除 `ChanAnalyse/` 与 `.venv/`，把结果整理成「入口 → 显式 key → 处置方式」表格写入 `Debug/bsp_standard_equivalence.py` 的模块注释；验证清单条目数与 grep 结果一致
- [x] 7.2 处置**演示入口** `main.py:47-53`：移除 `divergence_rate=float("inf")`、`min_zs_cnt=0`、`bs1_peak=False` 三项覆盖，保留 `bsp2_follow_1` / `bsp3_follow_1` 并加注释说明其与小转大场景的关系；验证 `python main.py` 的实际配置中 `divergence_rate == 0.9` 且 `min_zs_cnt == 2`
- [x] 7.3 处置**GUI 扫描器** `App/ashare_bsp_scanner_gui.py:517-527`：同上移除三项覆盖；若该扫描器的业务定位确实是「宁可多报」，则改为显式 `bsp_preset="legacy"` 并加注释，而不是散写裸参数；验证启动扫描器后打印的配置符合所选档位
- [x] 7.4 处置**策略演示脚本** `Debug/strategy_demo5.py:115-121`（含 `inf` / `min_zs_cnt=0` / `bs1_peak=False` 全套覆盖）：改为 `bsp_preset="legacy"`（若该演示依赖旧口径）或删除覆盖；验证脚本运行不抛异常且取到的档位与声明一致
- [x] 7.5 处置**策略演示脚本** `Debug/strategy_demo.py:36-37`、`strategy_demo2.py:34-35`、`strategy_demo4.py:38-39`（显式 `divergence_rate=0.8` / `min_zs_cnt=1`）：这三个是既有回测样例，按「保持原样 + 加注释说明其为历史口径」处理，验证注释存在且脚本输出不变
- [x] 7.6 处置**快照续算路径** `WebAPI/incremental_engine.py:128` 与 **序列化路径** `WebAPI/chan_service.py:139`：确认二者不显式覆盖买卖点参数（当前实测未覆盖），在代码处加一行注释锁定该约束（「此处不得显式覆盖 bsp 参数，否则会绕过内核默认档位」）；验证两处 config 字典中无 bsp 相关 key
- [x] 7.7 排查**配置持久化面**：确认 PG 的业务表（`strategy` / `monitor` 等）与前端均不下发 `divergence_rate` / `max_bs2_rate` 等内核参数（当前实测无），并在 `文档/缠论策略.md` 第 11 章补一句「这些参数目前只由代码内 `CChanConfig` 决定，未开放到业务配置」；验证 `grep -rn "divergence_rate\|max_bs2_rate" Front/src WebAPI/routers` 为空

## 8. 快照与缓存失效（跨口径残留）

> 本节独立成组的原因：快照与缓存都**不含配置指纹**，切档位后旧结果会被
> 直接复用，导致「改了配置但输出没变」这一最难排查的故障形态。

- [x] 8.1 在 `WebAPI/cache.py` 的 `chan_stable_prefix` 表增加 `config_fingerprint` 列（对买卖点相关配置求稳定哈希），`get` 时不匹配即视为未命中；验证以不同档位先后请求同一 (code, kl_type) 时第二次不返回首次的缓存
- [x] 8.2 在 `WebAPI/incremental_engine.py` 的 `chan_snapshot` 使用处（`:303-305`）增加配置指纹校验：快照落库时一并写入指纹，续算前比对不一致则强制 `force_full=True`；验证手工切换档位后重跑走的是 `full` 而非 `incremental`
- [x] 8.3 为该两处新增列写幂等 DDL：`WebAPI/update-win.sql`（Windows）与 `WebAPI/update-mac.sql`（macOS，按实际变更机器择一，另一侧留空并以注释说明），并同步改 `bsp_store.py` / `cache.py` 的 `_ensure_tables()` 惰性 DDL；验证重复执行两次不报错
- [x] 8.4 增加回归用例：以 `legacy` 档位跑一次 → 切默认档位重跑 → 再切回 `legacy`，三次结果的六类买卖点序列分别与其档位对应，验证不存在跨档位串味

## 9. 二买（T2）标准化

> 前置：本组依赖 3.1~3.7 产出的 `bsp1_sure_dict`（4.1/4.2）。

- [x] 9.1 修正 `treat_bsp2` 首线段分支的配置方向：把 `BSP_CONF = self.config.GetBSConfig(seg.is_up())` 改为 `seg.is_down()`（design D14）；验证构造一个只有一条线段的合成标的，用 `-buy` / `-sell` 分别配不同 `max_bs2_rate`，确认买单取到买侧配置
- [x] 9.2 把 `treat_bsp2` 的 `real_bsp1 = self.bsp1_dict.get(bsp1_bi.idx)` 改为 `self.bsp1_sure_dict.get(bsp1_bi.idx)`（design D13）；验证 `bsp2_follow_1=False` 时不再出现 `relate_bsp1` 指向未成立一买的样本（改造前该配置下有 22 个）
- [x] 9.3 把 `bsp2_follow_1` 的校验从 `bsp_store_flat_dict` 改为 `bsp1_sure_dict`；验证某笔仅为二买、并非一买时不能通过该校验
- [x] 9.4 新增开关 `bsp2_retrace_zs`（默认 `False`），开启后要求回调笔 `bsp2_bi` 的高低区间与 `bsp2_bi.parent_seg.zs_lst` 中某个非单笔中枢有交集（design D21）；验证默认关闭时 41 只日线 T2 数与基线一致（166），开启后数量下降且下降后的样本全部与中枢有交集
- [x] 9.5 把二买判定抽为层级无关函数 `_bsp2_standard_ok(...)`，笔级别与线段级别共用（design D23）；验证 `seg_bs_point_lst` 的二买判定与 `bs_point_lst` 同构
- [x] 9.6 `legacy` 档位下验证：T2 数与改造前逐笔一致（41 只日线为 166，legacy 档为 318）

## 10. 类二（T2S）标准化

- [x] 10.1 修正 `bsp2s_follow_2` 的语义位置：把 `elif BSP_CONF.bsp2s_follow_2: return` 从「二买未命中」分支移到 `treat_bsp2s` 入口，语义改为「开关为真且锚点二买未成立 → 返回」（design D17）；验证在 `max_bs2_rate=0.618` 下 `follow=False` 得 T2S 83、`follow=True` 得 60（数值允许因数据快照浮动，但必须 `True <= False`）
- [x] 10.2 在 `Debug/bsp_standard_equivalence.py` 中固化 `bsp2s_follow_2` 的可观察性对照表：`max_bs2_rate` 取 1.0 / 0.8 / 0.618 / 0.5 四档，每档输出 `follow=False` 与 `True` 两组 T2S 数；验证 1.0 档两组相同（因二买几乎全成立）而其余档不同——这是正确行为，需在输出中打印说明
- [x] 10.3 新增 `bsp2s_require_zs`（默认 `True`）：在 `treat_bsp2s` 每登记一个 T2S 前，要求 `bsp2s_bi.get_end_val()` 落在 `bsp2s_bi.parent_seg.zs_lst` 中某个非单笔中枢的 `[low, high]` 内，且该线段至少有一个非单笔中枢（design D15）；验证默认开启时 41 只日线 T2S 从 157 降到约 90（±10%），关闭时回到 157
- [x] 10.4 新增 `bsp2s_rate_mode`（默认 `"amp"`），把类二回撤率公式改为 `bsp2s_bi.amp() / break_bi.amp()`；`"disp"` 保留旧公式（design D16）；验证 `max_bs2_rate=1.0` 时 amp 口径 T2S 约 144、disp 口径约 157；`0.618` 时约 66 / 83
- [x] 10.5 处理 `bsp2s_rate_mode` 与 `bsp2s_require_zs` 的交互：两项同时开启时先做量纲换算再做中枢过滤，验证顺序不影响最终集合（过滤是集合求交，应可交换）
- [x] 10.6 把类二判定抽为层级无关函数 `_bsp2s_standard_ok(...)`（design D23）；验证线段级别二买/类二与笔级别同构
- [x] 10.7 `legacy` 档位下验证：T2S 数与改造前逐笔一致（41 只日线为 157，legacy 档为 317）

## 11. 三买（T3A / T3B）标准化

- [x] 11.1 重写 `treat_bsp3_before` 的回抽定位逻辑（design D18）：锚点保持 `seg.get_final_multi_bi_zs()`，回抽笔从 `bi_list[bsp1_bi.idx+2::2]` 扫描改为 `bi_list[zs.bi_out.idx + 1]`，并把遇回中枢时的 `continue` 改为 `break`；验证 `bsp3b_mode="standard"` 下 41 只日线 T3B 约为 81±10%（改造前为 33）
- [x] 11.2 在 `treat_bsp3_before` 新增突破方向校验：买要求 `zs.bi_out.is_up() and zs.bi_out._high() > zs.high`，卖要求 `zs.bi_out.is_down() and zs.bi_out._low() < zs.low`（design D18）；验证全部登记的三买B 满足该条件（应为 100%）
- [x] 11.3 在 `treat_bsp3_before` 新增回抽方向校验：买要求回抽笔 `is_down()`、卖要求 `is_up()`；验证全部登记的三买B 的回抽笔方向与买卖方向相反
- [x] 11.4 新增 `bsp3b_mode` 档位（默认 `"standard"`，`"legacy"` 保留旧扫描）；验证 `legacy` 档下 T3B 数与改造前逐笔一致（41 只日线为 33，legacy 档为 50），且 `standard` 档下与 T2/T2S 的重叠为 0（改造前 11 个中 7 个重叠）
- [x] 11.5 修正 `bsp3_peak` 的判据对象（design D19）：把 `bsp3_break_zspeak(bsp3_bi, zs)` 的入参从回抽笔改为中枢离开笔 `zs.bi_out`，并在 `treat_bsp3_before` 中同样调用；验证 `bsp3_peak=True` 时 T3A 与 T3B 均受影响（改造前 T3B 完全不受影响）
- [x] 11.6 新增 `bsp3_peak_on_breakout`（默认 `True`）控制 D19 的新旧语义；设为 `False` 时恢复「判回抽笔且只在 T3A 生效」。验证两种取值下 T3A 的数量差异，并记录被过滤的样本明细
- [x] 11.7 把 `bsp3_follow_1` 的校验从 `bsp_store_flat_dict` 改为 `bsp1_sure_dict`（design D20），并新增 `bsp3_follow_1_mode`（默认 `"sure"`，可选 `"candidate"` 取 `bsp1_dict`）；验证某笔仅为二买时不能通过校验
- [x] 11.8 统一 `strict_bsp3` 在两条分支的语义为「中枢紧邻一买」，并保留 T3A 现有的「中枢进入笔 == 一买笔 + 1」表述；验证 `strict_bsp3=True` 时两条分支的过滤样本能被逐一列出
- [x] 11.9 把三买判定抽为层级无关函数 `_bsp3_standard_ok(...)`（含 `_breakout_ok` 与 `_first_retrace`，design D23）；验证 `seg_bs_point_lst` 的三买判定与 `bs_point_lst` 同构
- [x] 11.10 修正 `bsp3a_max_zs_cnt` 的文档语义（「在下一条线段内最多检查前 N 个中枢」而非「最多跨越多少个中枢」），并在 `Document/README.md` 中说明该参数在多数数据上无区分度（实测 1/3/5 三档 T3A 均为 9）

## 12. 同笔多类型的去重口径

- [x] 12.1 在 `ChanAnalyse/BuySellPoint/BS_Point.py` 的 `CBS_Point` 增加只读属性 `primary_type`，按固定优先序 `T1 > T1P > T2 > T3A > T3B > T2S` 从 `type` 列表中取第一个（design D22）；验证 `type` 列表本身与改造前一致
- [x] 12.2 在 `WebAPI/bsp_store.py` 的索引入库路径改用 `primary_type` 作为 `bsp_type`，并保证按 `bi.idx`（或等价唯一键）去重；验证标准化后同一笔上的 T3B 与 T3A 只产生一行
- [x] 12.3 验证 `bsp-index` 统计口径：改造前 11 个 T3B 中 7 个与 T2/T2S 同笔，去重后该类重复计数消失；改造后 T3B 与 T3A 有 15 个重叠，去重后的总点数等于不同笔数

## 13. 快照与缓存失效的档位扩展

- [x] 13.1 把 `config_fingerprint` 的哈希输入范围定义为「全部 bsp 相关 key」（`bsp_preset`、`divergence_rate`、`min_zs_cnt`、`bs_type`、`macd_algo` 及 D1~D20 新增的全部开关），验证修改任一单项都会改变指纹
- [x] 13.2 验证指纹稳定性：同一配置连续两次求哈希结果相同（不得依赖字典插入顺序、对象 id、时间戳）
- [x] 13.3 验证 `legacy` 档位与默认档位产生不同指纹，且 `legacy` + 显式覆盖某项新开关时指纹又与两者都不同

## 14. 文档同步

- [x] 14.1 更新 `文档/缠论策略.md`：3.6 买卖点表（六类口径）、3.7 背驰与指标（修正 `macd_algo` 默认值 `area` → `peak`）、第 11 章配置表（`divergence_rate` 语义、全部新增开关、`bsp_preset`、以及 7.7 要求的「参数只由代码内 `CChanConfig` 决定」说明）
- [x] 14.2 更新 `Document/README.md` 的买卖点参数段：补全部新增开关，修正 `bsp3_peak`（判据对象为突破笔、两分支均生效）、`bsp3a_max_zs_cnt`（语义为「最多检查前 N 个中枢」）、`bsp2s_follow_2`（语义为「类二必须跟在成立的二买后」，并说明其在默认 `max_bs2_rate=1.0` 下不可观察）的既有描述错误
- [x] 14.3 在三份《xx买xx卖差异点说明》中对已修复条目加「已修复（chan-standard-bsp）」标记，验证每条差异都能对应到本变更的具体任务号
- [x] 14.4 在 `文档/缠论策略.md` 中明确写出「笔级别二买/类二/三买 = 单笔口径」「线段级别 = 次级别走势类型的严格实现」，并说明两个层级的映射关系（`chan-bsp-standard` 的「次级别走势类型的层级落地」Requirement）

## 15. 实施阶段发现并修复的缺陷（非原计划范围，见「范围变更」）

> 实施过程中暴露的问题：前两项是本次改造**直接引入**的（必须修），后两项是
> **既有缺陷**被本次改造放大后暴露（修了，但属于范围外补充）。

- [x] 15.1 【本次引入，阻断级】`WebAPI/incremental_engine.py` 的 `recompute_stock` 与 `WebAPI/chan_service.py` 用 `CChan(...).config` 取配置求指纹，但 `CChan` 的实例属性名是 `conf`——`config_fingerprint` 两处调用都会 `AttributeError`，导致**所有落库与所有 /api/klines 请求直接失败**。修复：`incremental_engine` 抽出 `_make_chan_config()`（与 `chan_service` 同名函数同构），指纹从该函数取，不再经 `CChan` 实例；已验证两条链路指纹相同（`09455919653d1f5f`）
- [x] 15.2 【本次引入，阻断级】`Front/src/utils/bsp.ts` 把 `3a`/`3b` 拆成 `3B(后)`/`3B(内)` 后，后端 `WebAPI/routers/bsp.py` 的 `_DIRECTIONAL_LABELS` 仍只有合并标签 `3B`/`3S`——新标签会落到 `return [bsp_type], None` 分支，即拿 `"3B(后)"` 去匹配原始枚举列，**永远返回 0 行**。修复：标签表移入 `WebAPI/bsp_store.py`（改名为 public 的 `DIRECTIONAL_LABELS` / `resolve_bsp_type`），补全 `3B(后)`/`3B(内)`/`3S(后)`/`3S(内)` 四个标签，并保留 `3B`/`3S` 作为「两类都要」的合并快捷筛选（老书签/老任务不失效）
- [x] 15.3 【既有缺陷，被放大】`WebAPI/strategy_store.py` 的 `resolve_scope_codes` 在处理 `scope_type='bsp_query'` 时读 `bsp_query.get("bsp_types")`（原始枚举**列表**），而前端 `TaskDialog.vue` 传的是 `bsp_type`（方向化标签**字符串**）——键名与类型双重不匹配，**类型筛选被静默忽略**，任务范围按全类型固化。修复：改为读 `bsp_type` 并调用 `bsp_store.resolve_bsp_type` 转成枚举集合 + 方向约束；`is_buy` 显式给出时优先。已验证：`PZ-B` 固化 29 只、`1B` 固化 41 只（差异 12 只），筛选确实生效
- [x] 15.4 【既有缺陷，文档/前端】`Front/src/views/performance/PerformanceView.vue` 的 `displayLabel` 在标签已含方向后仍拼 `-a`/`-b` 后缀，会显示成 `3B(后)-a`；且 `isBuy('3a')` 恒为 `false` 会把三买渲染成三卖。修复：`3a`/`3b` 直接用中性标签 `三类(后)`/`三类(内)`（绩效统计行按 `(bsp_type, kl_type)` 聚合，本身不含方向维度），tooltip 与侧栏分类文案同步改为「中枢在下一条线段 / 当前线段」
- [x] 15.5 【既有缺陷，前端 mock】`Front/src/mock/data/bsp.ts` 的类型词表仍是合并的 `3B`，筛选下拉（已是 `3B(后)`/`3B(内)`）在 mock 模式下选不中任何记录。修复：词表对齐 `ALL_BSP_LABELS`

### 未解决：pickle 递归上限（既有环境限制，非本次引入）

- [x] 15.6 `CChan.chan_dump_pickle` 在 5m 级别的大对象图上抛 `RecursionError`。**已确认与本次改造无关**：用 `git worktree` 检出改造前的 HEAD，同一份 5m 数据同样失败。根因是 Python 3.12 的 C 层递归上限（`sys.setrecursionlimit` 只影响 Python 帧，`pickle` 的 C 实现在深对象图上仍会撞 C 栈限制），`chan_dump_pickle` 现有的 `setrecursionlimit(0x100000)` 无法绕开。影响面：`recompute_stock` 对 5m/15m 这类超长 K 线序列（4 万+ 合并 K 线）会失败。**不在本变更范围内**，按用户决定记录为已知限制、单独立项（可选方案：改用 `json`/自定义扁平序列化，或分片持久化）

> **15.6 处置结论（2026-10-22，用户确认）**：记录为**已知限制**，本次变更不修复。
> 已用 `git worktree` 检出改造前的 HEAD 在同一份 5m 数据上复现，确认与本次改造无关。
> 影响面：5m/15m 这类超长 K 线序列（4 万+ 合并 K 线）无法落 `chan_snapshot`；
> 其余 64 个组合全部重算成功。后续应单独立项（可选方案：扁平化序列化、分片持久化、
> 或升级到对深度更友好的序列化方式）。

- [x] 15.7 【本次引入，崩溃级】`CBS_Point.add_another_bsp_prop` 的 `assert self.relate_bsp1.klu.idx == relate_bsp1.klu.idx` 在标准档三买上会真实失败：同一笔可以既是 T3A（依托本线段末笔**之前**的中枢、锚较早的一买）又是 T3B（依托本线段**内**的中枢、锚较晚的一买），两者 `relate_bsp1` 不同，断言直接抛 `AssertionError`，**整只股票的线段级别买卖点计算崩溃**。触发条件：`divergence_rate=0.9 + min_zs_cnt=1`（43 只日线中 9 只线段级触发）、`divergence_rate=inf + min_zs_cnt=1`（25 只）。默认档 `min_zs_cnt=2` 与两个预设均不触发，所以未被常规回归发现——**是「单项配置覆盖」这条文档宣传的用法踩中的**。修复：改为保留先登记的 `relate_bsp1`（判定顺序 T3A 先于 T3B），不做覆盖也不断言。`relate_bsp1` 在仓库内无下游消费方，断言无守护价值。修复后四种配置组合的断言失败数全部归零。
