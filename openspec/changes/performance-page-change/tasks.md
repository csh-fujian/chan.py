## 1. system-page-change 裁剪

- [x] 1.1 删除 `openspec/changes/system-page-change/specs/bsp-performance/` 目录（含 spec.md）；验证：`openspec validate --change system-page-change` 通过，无残留 bsp-performance 引用
- [x] 1.2 修改 `openspec/changes/system-page-change/proposal.md`：Capabilities 移除 `bsp-performance` 条目、What Changes 中绩效迁入描述改为已迁出（指向 performance-page-change）；验证：proposal 中 grep `bsp-performance` 无命中
- [x] 1.3 修改 `openspec/changes/system-page-change/design.md`：D4 映射表删除 `bsp-performance` 行；验证：design.md 中 grep `bsp-performance` 无需求归属性命中
- [x] 1.4 修改 `openspec/changes/system-page-change/tasks.md`：删除 8.2（买卖点绩效统计迁移验证记录——需求已归 performance-page-change）；验证：tasks.md 无绩效追踪条目

## 2. chan-stock-manage 指向更新

- [x] 2.1 修改 `openspec/changes/chan-stock-manage/proposal.md`：两处 `bsp-performance` 迁移指向由 `system-page-change` 改为 `performance-page-change`；验证：proposal 中 grep `bsp-performance` 仅指向 performance-page-change

## 3. 后端实现（design D1/D2）

- [x] 3.1 `WebAPI/routers/performance.py` `GET /api/performance/stats` 接真：monitor completed 按 `(bsp_type, kl_type)` GROUP BY 聚合，返回样本数/胜率/平均盈亏/盈亏比/期望值（胜率 = pnl_pct>0 占比；期望 = 胜率×平均盈利 − 败率×|平均亏损|）；`source`/`instance_id` 参数兑现过滤（chan/strategy+实例精确匹配/watchlist）；PG 不可用降级空集；验证：真实 PG 下统计值与 completed 记录手工核算一致，source 过滤生效
- [x] 3.2 `GET /api/performance/samples` 接真：completed 明细行含 `code/name/bsp_type/kl_type/source_type/strategy_label/bsp_date/sold_at(hold_days)/bsp_price(entry_price)/end_price(sold_price)/profit(pnl_pct)/attribution`；支持 `bsp_type`/`kl_type`/`source`/`instance_id` 过滤；验证：样本明细与 stats 同分组计数一致，字段与前端类型对齐
- [x] 3.3 归因摘要透传：samples 行从 PG 归因表（`get_attribution` 语义）取归因文本，未归因为空串；验证：已归因样本返回摘要、未归因返回空

## 4. 前端删摆设与筛选统一（design D3/D4）

- [x] 4.1 删除表格上方 `el-select` 双入口筛选（`filterBspType`/`filterDirection`/`onFilterChange`/`applyCategoryFilter`），筛选统一侧栏；验证：表格区无独立筛选控件，侧栏筛选生效
- [x] 4.2 周期筛选落地：侧栏周期词表对齐 D4 口径（全部/30m/60m/D/W/M），统计表增「周期」列（`PerformanceStat.kl_type`），周期筛选消费于 `filteredStats`；验证：选周期后统计表仅剩该周期分组
- [x] 4.3 侧栏增来源树（复用 `getMonitorSources` 字典：全部来源/缠论/各策略实例/自选），选中映射 `source`/`instance_id` 请求参数；验证：选策略实例后统计与明细仅剩该实例样本
- [x] 4.4 统计联动：顶部 4 统计卡与胜率柱状图数据源改为 `filteredStats`（含方向/类型/周期/来源四组筛选）；验证：任一筛选变化统计卡与图同步重算，清空恢复全量
- [x] 4.5 胜率图剔除无样本类型（删缺补 0 逻辑）；验证：mock 删某类型样本后图中不再出现该柱

## 5. 新增分析件（design D5）

- [x] 5.1 统计表与样本抽屉增「期望值」列（红正绿负）；验证：期望值 = 胜率×平均盈利 − 败率×|平均亏损| 手工核算一致
- [x] 5.2 月度胜率/平均盈亏双线趋势图（按样本 bsp_date 月度前端聚合，盈利红/亏损绿分段着色 + 0 轴参考线）；验证：趋势与样本月度分组手工核算一致
- [x] 5.3 样本不足标记：统计表样本数 < 5 的行加「样本不足」badge（tooltip 提示统计意义有限）；空态引导「先在监控页积累结算样本」；验证：小样本行显示标记，大样本不显示
- [x] 5.4 样本明细归因摘要 + 双击跳 K 线：明细行展示归因摘要（截断 + tooltip），双击行 `router.push({ name: 'kline', query: { code, period } })`（period 用 `KL_TO_KLINE_PERIOD` 映射）；验证：已归因样本显示摘要，双击跳 K 线且级别生效

## 6. mock 同步（design D6）

- [x] 6.1 `mock/data/performance.ts`：stats 补 `kl_type` 与期望值、样本补 `kl_type/source_type/strategy_label/attribution`；handlers 消化 `bsp_type`/`kl_type`/`source`/`instance_id` 过滤参数；验证：mock 模式全流程（筛选→联动→下钻→跳转）无报错

## 7. 端到端走查

- [x] 7.1 真后端冒烟（`VITE_USE_MOCK=false`，需后端重启）：登录 → 统计卡/图/表加载真实聚合 → 侧栏四组筛选联动 → 样本下钻归因摘要 → 双击跳 K 线；验证：统计值与 PG completed 记录一致，全流程无报错
- [x] 7.2 mock 模式走查：同流程 mock 下契约一致；验证：`vue-tsc` 0 错误、`npm run build` 通过、console 无报错（浏览器实测待用户 `npm run dev` 确认）
- [x] 7.3 `openspec validate performance-page-change --type change` 通过；对 `system-page-change`、`chan-stock-manage` 执行 validate 确认无跨变更引用断裂

## 8. 类型树细化 + 监控分组维度（2026-10-05 二轮增量，design D8/D9）

- [x] 8.1 后端 `group_id` 参数：`routers/performance.py` stats/samples 增 `group_id: str = Query("")`（正整数或字面 `'ungrouped'`，校验复用 monitor 路由 D3 正则，非法 422）；`performance_store._filter_completed` 增分组过滤分支（completed 行 `group_id` 比对：`ungrouped` → is None，正整数 → 精确匹配）；验证：真实 PG 下选未分组返回全量（当前 4 条均 group_id=None）、选不存在分组返回空集、非法 group_id 422
  <!-- 实施裁定：list_completed 本身已支持 group_id SQL 过滤（monitor 路由 /completed 在用，_group_filter_condition 实现 D3 语义），且其 SELECT 不含 group_id 列（行字段比对方案不成立）——改为把 group_id 下推到 list_completed 的 SQL WHERE，monitor_store 零改动，过滤语义与 monitor 路由完全同源。 -->
- [x] 8.2 前端类型树 6 档：`categoryItems` 改为 全部/第一类(`1`)/盘整背驰(`1p`)/第二类(`2`)/类二(`2s`)/三类a(`3a`)/三类b(`3b`)，筛选从 `startsWith` 改为 `r.bsp_type === key` 精确匹配（`filteredStats`/`filteredSamples` 两处）；验证：选「盘整背驰」仅剩 bsp_type='1p' 行，'1' 行不混入
- [x] 8.3 3a/3b 展示区分：统计表 badge 与胜率图轴标签对 `'3a'`/`'3b'` 显示 `3B-a`/`3B-b`（枚举尾缀，副语义中枢后/中枢前）；验证：两枚举行在表格与图中可目视区分
- [x] 8.4 前端分组树：侧栏第五组「分组」TreeList（`getMonitorGroups()` 加载字典，失败静默；items = 全部分组/未分组(`ungrouped`)/各分组）；选中变化触发 `loadAll()` 重拉（`groupParams()` 拆解：'all'→不传，其余原值透传）；`api/modules/performance.ts` stats/samples 增 `group_id` 参数（非空携带）；验证：选中分组后统计与明细重拉且仅剩该分组样本
- [x] 8.5 mock 同步：`mock/data/performance.ts` samples 补 `group_id`（约 60% NULL/其余轮换）；`PerformanceSample` 类型增 `group_id?: number | null`；handlers stats/samples 消化 `group_id` 过滤（`ungrouped` → `s.group_id == null`，正整数 → 精确）；验证：mock 模式选分组/未分组过滤生效
- [x] 8.6 走查：`vue-tsc` 0 错误 + `npm run build` 通过 + 真后端冒烟（group_id 参数与过滤链路）+ `openspec validate performance-page-change --type change` 通过
  <!-- 8.2-8.5 实施附带裁定：① mock 的 bsp_type 从 '1B' 展示标签口径修正为原始枚举口径（'1'/'1p'/'2'/'2s'/'3a'/'3b'，与真后端 performance_store 一致），样本方向改由 direction 字段承载——这是 6 档精确匹配在 mock 模式可验证的前提；② 统计行 badge 由涨跌色改中性（聚合行不含方向，isBuy 判定在枚举口径下无意义）；③ 一并修复 onSourceChange 不回写 activeSource 的受控组件高亮缺失（一轮隐藏 bug）。遗留：真后端同枚举跨周期多行时胜率图轴标签会重复（name 未拼周期），样本积累后可后续立 delta。 -->
