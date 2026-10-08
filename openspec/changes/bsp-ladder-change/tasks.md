# Tasks

## 1. 后端级别推导与落库

- [x] 1.1 新建 `WebAPI/bsp_ladder.py`：`cal_ladder(bsp, bs_point_lst, sub_result=None)` 四级推导（L4 复用 `bsp_is_sure`、L3 笔力度背驰比较、L1 子级别共振、L2 兜底），阈值常量集中；验证：对合成笔序列单测冒烟（L1-L4 各路径命中）→ `Debug/bsp_ladder_smoke.py` 13/13 PASS
- [x] 1.2 `WebAPI/update.sql` 幂等追加 `bsp_index.ladder VARCHAR(2)` 列 DDL（含执行时间注释）；验证：重复执行 `update.sql` 不报错，`information_schema` 确认列存在 → 本地 PG 两次执行无报错、列存在
- [x] 1.3 `WebAPI/incremental_engine.py` `_extract_bsp_rows` 落库带 `ladder`（落库链路不算 L1，未确认无背驰落 L2）；`bsp_store.py` 写入投影补列；验证：`Debug/bsp_engine_regression.py` 全量 PASS（既有回归不破）→ 8/8 PASS（T1-T8），落库值分布 L4=78/L3=5/L2=3（sz.000001 D）
- [x] 1.4 `WebAPI/bsp_store.py` `query_bsp` 查询投影补 `ladder`（存量 NULL 行按 `is_sure` 映射兜底 L4/L2）；`routers/bsp.py` 响应字段补 `ladder`；验证：`Debug/bsp_engine_regression.py` T7 契约用例 PASS 且响应含 `ladder`（含 `get_bsp_by_code` 投影同步 + 顺带修复直调时 Query 缺省值误入 400 分支的既有小缺陷）

## 2. /api/klines 序列化与 L1 共振

- [x] 2.1 `WebAPI/serializer.py` `_serialize_bsp` 输出 `ladder` 字段（L1 按 D3 在此链路计算）；验证：单股 `get_serialized_chan` 返回的 `bsp[]` 含 `ladder`（sz.000001 D：L4=75/L3=5/L2=3），与 `bsp_is_sure` 判定交叉抽查一致（L4 ⇔ is_sure 全量成立）
- [x] 2.2 `WebAPI/chan_service.py` 增子级别计算入口（映射 30m/60m→5m、D→30m、W→D、M→W，5m 无子级返回 None）供 serializer L1 共振判定；验证：`compute_sub_chan` 映射正确（D→K_30M、W→K_DAY、30m→K_5M、5m→None），sh.600009（有 30m 数据）触发子级计算成功 → 修订二重验：sh.600007（有 5m 数据）30m 级 L1 落库命中（2026-9-30 1 卖点）
- [x] 2.3 L1 共振判定实现：未确认买卖点的时间窗口内子级别存在同向（买点对买点）买卖点即共振；验证：sh.600009 W→D 有子级 {L4:8, L3:2, **L1:2**, L2:1} vs 无子级 {L4:8, L3:2, L2:3}——3 个 L2 中 2 个升 L1、方向反向与窗口外均正确不共振

## 3. K 线图 hover tooltip

- [x] 3.1 `Front/src/components/charts/KLineChart.vue`：`chanMarks`/`ChanBspMeta` 构建时保留 `ladder`（不再丢弃该字段）；验证：overlay extendData 中每条 bsp meta 含 `ladder` → 真实后端 hover 命中回读 meta，L4/L3/L2 各级浮层徽章均按 extendData.ladder 渲染
- [x] 3.2 买卖点 figure hover 命中 → 绝对定位浮层展示级别说明卡（当前级别高亮 + L1-L4 四级名称/说明/仓位指引 + L1 共振副标记；缺 `ladder` 兜底「未定级」）；验证：`npm run dev` 手动悬浮各级别标记，浮层内容与 mock 数据一致 → mock 模式网格扫描命中（全 4 级 + 未定级兜底）；真实后端（sz.000001 D，83 bsp：L4=75/L3=5/L2=3）hover 命中 L4（badge--rise/买点/L2B/满仓）、L3（badge--warning/卖点/PZ-S）、L2（badge--default），is-current 行高亮正确，mouseleave 后浮层隐藏
- [x] 3.3 `Front/src/mock/data/kline.ts` bsp 样例补 `ladder`（L1-L4 各态覆盖）；验证：MSW mock 模式下 hover 全级别可演示 → is_sure=true → L4，未确认在 L1/L2/L3 轮转，mock 模式扫描全级别命中
- [x] 3.4 明暗主题切换下浮层样式正常（`design.css` 令牌）；验证：双主题各悬浮一次 → dark（tipBg rgb(22,27,34)/0.96、border rgb(58,66,78)）与 light（tipBg rgb(255,255,255)/0.96、border rgb(184,192,204)）均按 data-theme 令牌切换，L4 徽章色与 is-current 高亮两主题下正常

## 4. 买卖点页级别列

- [x] 4.1 `Front/src/api/types.ts` + `api/modules/bsp.ts`：`BspRecord` 补 `ladder` 字段；验证：`npm run build`（vue-tsc）类型检查通过 → build 成功（15.19s）
- [x] 4.2 `Front/src/views/bsp/BspView.vue` 结果表新增「级别」列：徽章（L4 实色 / L1-L3 弱化）+ hover 说明（级别名 + 仓位指引），与未确认灰 tag 协调（L4 无灰 tag）；验证：mock 模式下各级别行渲染正确、翻页/筛选后列保持 → 真实后端 + mock 双模式验证：L4 badge--rise（无灰 tag）、L3 badge--warning + 未确认灰 tag、L2 badge--default、L1 badge--info；hover tooltip 文案「背驰预警 · 加仓至 1/2 — …」；翻页与方向筛选后列保持
- [x] 4.3 `Front/src/mock/data/bsp.ts` 记录补 `ladder` 样例；验证：mock handlers 透传后页面级别列非空 → bspRecords 确认行 L4 / 尾部 6 条在 L1/L2/L3 轮转，getBspByCode 尾部同样覆盖；mock 模式页面分布 L4=6/L1=2/L2=2/L3=2 全部非空

## 5. 收尾验证

- [x] 5.1 端到端冒烟：真实后端（PG + DuckDB）跑通「日终补算 → `GET /api/bsp` 含 ladder → K 线页 hover / 买卖点页级别列」全链路；验证：`Debug/bsp_engine_regression.py` 全量 PASS + 手动页面检查清单（每级至少一条可见）→ 回归 8/8 PASS（--codes sh.600009,sh.600007；默认 sz.000002 在 DuckDB 无 K 线属环境缺数非变更缺陷）；K 线页 hover L4/L3/L2 可见（L1 为序列化链路独有，sh.600009 W→D 场景已单测验证 2 条）；买卖点页 L4（确认）/L3/L2（preview 过滤）各多条可见；T7.4 响应契约含 ladder 字段
- [x] 5.2 计算内核零改动核验：`git diff --stat ChanAnalyse/` 为空；验证：命令输出为空 → 输出为空（exit 0），全部改动落在 WebAPI/、Front/、Debug/、openspec/
- [x] 5.3 D3 修订（2026-10-09，用户反馈推翻「落库不算 L1」）：`recompute_stock` 接 `_compute_sub_for_l1`——主级别算完后额外计算子级别买卖点全集（只读不落库不推游标），`cal_ladder(sub_bsps=...)` 落库链路同口径计算 L1；`BSP_L1_PERSIST` 环境开关（默认 1，置 0 回退初版行为）+ 回归 T9 验证；验证：sh.600009 W 级（W→D 共振）落库出现 L1 行（升级前 L2）、T9 全 PASS → 落库分布出现 L1（sh.600009 W：L1=3；sh.600007 W：L1=3）；`BSP_L1_PERSIST=0` 重算 L1 行消失回 L2；`git diff --stat ChanAnalyse/` 仍为空
- [x] 5.4 D3 修订二（2026-10-09，用户指定子级链）：子级别映射改单级直连 `5m→30m→D→W→M`（`SUB_LEVEL_MAP`：30m/60m→5m、D→30m、W→D、M→W、5m 无子级），每级只看直接一级子级、无跨级递归传递；L1 共振窗口按级别对差异化（日级 ±5 自然日 / 分钟级 ±2 小时，`L1_WINDOW_SECONDS`），`cal_ladder`/`cal_l1_resonance`/`_serialize_bsp` 增级别键参数；验证：冒烟 13/13 PASS（向后兼容回退默认窗）；sh.600007 30m 级（子级 5m，78k 根）L1 落库命中（2026-9-30 卖点 1 条，窄窗过滤了宽窗会误判的旧 5m 信号）；`resolve_sub_level` 映射单测（30m→K_5M、D→K_30M、5m→None）
- [x] 5.5 D3 修订三（2026-10-09，用户裁定佐证资格）：L1 共振的子级点须自身 is_sure=true（子级 L4）才可作佐证——`cal_l1_resonance` 增 `sub_bs_point_lst` 参数做子级水位线过滤（不递归算子级 ladder，避免级联传递）；落库链路 `_compute_sub_for_l1` 返回 (bsps, bs_point_lst) 二元组、serializer 链路同补；验证：冒烟新增 4 用例全 PASS（子级未确认不共振 / 子级 L4 共振 / 分钟级窗 3h 外不共振 / 1h 窗内共振，17/17）；真实数据过滤生效——sh.600007 30m L1=1→0（5m 佐证点未确认被滤）、sh.600009 W L1=3→2、sh.600007 W L1=3→2；回归 9/9 PASS、`git diff --stat ChanAnalyse/` 仍为空
