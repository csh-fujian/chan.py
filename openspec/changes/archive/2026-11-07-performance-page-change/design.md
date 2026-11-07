## Context

绩效页面现状（前端完整 / 后端 stub）：

- 前端 `Front/src/views/performance/PerformanceView.vue`：侧栏筛选（方向/类型/周期）+ 4 统计卡 + 胜率柱状图（固定 8 柱）+ 聚合统计表 + 行点击样本抽屉；mock 数据 7 统计行 + 40 样本
- 后端 `WebAPI/routers/performance.py`：`GET /api/performance/stats|samples` stub 返回空集，`source`/`instance_id` 参数契约预留（strategy-signal-page D7）
- 三处摆设：周期筛选只存 key 无消费（`PerformanceStat` 无 kl_type 维度）；统计卡/柱状图基于全量 stats 不联动；柱状图缺样本补 0 误导

需求来源迁移链：`chan-stock-manage`（D9 历史设计，已迁出）→ `system-page-change`（`bsp-performance` spec 两条件 + tasks 8.2）→ 本变更（迁入重写）。

数据原料（均已就绪）：monitor 表 completed 记录含 `code/kl_type/entry_price/pnl_pct/sold_price/sold_at/monitor_start_time/source_type/instance_id`；`_fill_bsp_context` 已回查 `bsp_type`；LLM 归因存 PG；`GET /api/monitor/sources` 来源字典已落地（monitor-page-change D14）。

二轮增量事实（2026-10-05，类型树细化 + 分组维度的依据）：

- bsp_index 全库 bsp_type 仅 6 个单值（`2` 5202 / `2s` 4437 / `1` 3869 / `1p` 1581 / `3a` 1219 / `3b` 1056），**无组合字符串**——incremental_engine D4 语义「一个点多类型按类型展开多行」已在数据层消解组合问题；多属性点分别计入各枚举组
- `3a`（中枢在一类**之后**，回抽不入）与 `3b`（中枢在一类**之前**）前端标签撞名（同 3B/3S，bsp.ts TYPE_MAP），语义不同的两枚举在展示层无法区分
- 一轮落地的「类型」侧栏用 `startsWith` 前缀粗匹配：`1p` 混入「第一类」、`2s` 混入「第二类」，粗分污染买卖点有效性结论
- monitor 的 `group_id` 维度：分组语义为用户手工组织的业务批次（monitor-group-change D1/D3），回答「这批监控做得怎么样」；分组过滤参数语义已存在于 monitor 路由 D3（正整数 / `'ungrouped'` 哨兵）

## Goals / Non-Goals

**Goals:**
- 绩效页接真实数据（monitor completed 聚合），成为「统计胜率、总结经验」的复盘入口
- 删除三处摆设（周期筛选无效、统计不联动、胜率图补 0）
- 兑现 strategy-signal-page 预留的来源/实例维度（策略参数组对比）
- 迁移承接 `bsp-performance` spec（自 system-page-change），裁剪来源变更

**Non-Goals:**
- 不做 bsp_index 全量回测统计（口径 A 否决，见 D1）
- 不修改 monitor 表 schema 与 monitor-page-change 已落地行为
- 不做归因的重新生成（只消费已有归因结果）
- 不修改 CChan 计算流水线

## Decisions

### D1. 统计口径裁定：仅监控结算样本（口径 A）

**裁定**：绩效样本 = monitor 表 `status='completed'` 记录。胜率 = `pnl_pct > 0` 占比；平均盈亏 = `pnl_pct` 均值；盈亏比 = 平均盈利 / |平均亏损|；持有天数 = `sold_at − monitor_start_time`。

**否决备选**：chan-stock-manage 历史 design D9 的 `(kl_type, bsp_type, is_buy)` 联查 bsp_index 全量口径——该设计在 2026-10-01 时绩效尚未实现，混入 bsp_index 全量样本实质即「回测口径」（口径 B），与用户确认的口径 A 冲突；且回测需新定义出场规则（持有 N 根/到反向买卖点），语义与「监控结算」分叉。历史记录保留在 cSM design 中不动，需求以本变更为准。

### D2. 后端实现：stub → monitor 聚合

- `GET /api/performance/stats?source=&instance_id=`：`list_completed()` 基础上按 `(bsp_type, kl_type)` GROUP BY 聚合——样本数/胜率/平均盈亏/盈亏比/期望值（期望 = 胜率×平均盈利 − 败率×|平均亏损|）；`source`/`instance_id` 参数过滤（兑现 strategy-signal-page D7 预留契约）
- `GET /api/performance/samples?bsp_type=&kl_type=&source=&instance_id=`：completed 明细行（含 `source_type`/`strategy_label`/`bsp_type`/`kl_type`/`hold_days`/归因摘要 `attribution`）
- 聚合放 `monitor_store.py`（复用 `list_completed` 的 `_fill_bsp_context`/`_enrich_with_real_time_pnl` 链路）或抽 `performance_store.py`——实现时按 monitor_store 体量裁定，逻辑归绩效能力
- PG 不可用降级空集（与 monitor 路由同语义）
- **否决备选**：物化统计表（当前数据量小，实时聚合足够；物化要引入刷新调度）

### D3. 前端删摆设与筛选统一

- **删**：表格上方 `el-select` 双入口（`filterBspType`/`filterDirection` + `onFilterChange` 手写同步 + `applyCategoryFilter` 空函数）——筛选统一为侧栏单入口
- **删**：胜率图 `allBspTypes.map` 缺样本补 0 逻辑——改为仅绘制有样本的类型
- **周期落地**：侧栏周期词表对齐 D4 口径（全部周期 → 30m → 60m → D → W → M，无 1/5/15 分钟），`PerformanceStat` 增 `kl_type` 字段，统计表增「周期」列
- **侧栏增来源树**：复用 `GET /api/monitor/sources` 字典（全部来源/缠论/各策略实例/自选），选中传 `source`/`instance_id` 参数

### D4. 统计联动（复用 monitor D14 模式）

顶部统计卡（总样本/综合胜率/平均盈亏/盈利比）与胜率柱状图数据源从全量 `stats` 改为侧栏四组筛选后的 `filteredStats`；筛选清空恢复全量。综合胜率保持样本数加权口径。

### D5. 新增分析件

- **期望值列**：统计表与样本抽屉均展示（胜率 × 平均盈利 − 败率 × |平均亏损|，单位 %），红正绿负着色
- **月度趋势**：按样本 `bsp_date` 月度聚合的胜率 + 平均盈亏双线折线（ECharts，盈利红/亏损绿，复用 ProfitChart 分段着色模式）；数据来自前端对 `filteredStats` 对应样本的月度聚合（samples 已全量加载）或后端聚合——实现时按样本量裁定，默认前端聚合（样本量为 completed 数，量级小）
- **样本不足标记**：统计表样本数 < 5 的行加「样本不足」badge（title 提示统计意义有限）
- **归因摘要联动**：样本明细行展示 `attribution` 摘要（超长截断 + tooltip 全文），双击行跳 K 线（`router.push({ name: 'kline', query: { code, period } })`，period 映射对齐 monitor D12 的 `KL_TO_KLINE_PERIOD`）

### D6. mock 同步

`mock/data/performance.ts` 样本补 `kl_type`/`source_type`/`strategy_label`/归因摘要字段；stats 补 `kl_type`/期望值/月度序列；handlers 消化新 query 参数（bsp_type/kl_type/source/instance_id 前端过滤语义对齐真后端）。

### D7. 迁移裁剪（沿用 monitor-page-change 模式）

- `system-page-change`：删 `specs/bsp-performance/`、proposal Capabilities 移除 `bsp-performance`、design D4 映射表删 `bsp-performance` 行、tasks 8.2 删除
- `chan-stock-manage` proposal：迁移指向文字由「已迁移至 system-page-change」改为「已迁移至 performance-page-change」（两处）
- 归档 spec：`openspec/specs/` 下无 bsp-performance，无需 Modified Capabilities

### D8. 类型树细化到 6 枚举（2026-10-05 二轮增量）

**裁定**：侧栏「类型」树从 3 档粗分改为 6 档枚举精确匹配——第一类(`1`)/盘整背驰(`1p`)/第二类(`2`)/类二(`2s`)/三类a(`3a`)/三类b(`3b`)，选中筛 `r.bsp_type === '<枚举值>'`。

- **动机**：一轮的 `startsWith` 前缀匹配把 `1p`（无中枢的盘整背驰）混入第一类（趋势背驰）、`2s`（类二）混入第二类——信号强度差异大的枚举混算污染「哪类买卖点靠谱」的复盘结论
- **组合类型口径（固化）**：数据层已按 incremental_engine D4 展开多行，绩效统计无组合字符串；一个多属性点（如 T1+T1P）分别计入第一类组与盘整背驰组样本数（按属性分别归因），无需任何前端拆分逻辑
- **3a/3b 撞名处理**：`bsp.ts` TYPE_MAP 中两者都映射 3B/3S；统计表 badge 与胜率图轴标签在展示名后加枚举尾缀（`3B-a`/`3B-b`），副语义「中枢后回抽不进/中枢前回抽不进」；聚合分组仍按原始枚举（`3a`/`3b` 天然分行，不受标签撞名影响）
- **否决备选**：维持三档粗分（污染复盘结论，见动机）；类型树直接列 12 个（枚举×方向）组合档（方向维度已有独立树，重复）

### D9. 监控分组维度（2026-10-05 二轮增量）

**裁定**：侧栏第五组「分组」树 + `/api/performance/stats|samples` 增 `group_id` 过滤参数。

- **树选项**：全部/未分组（哨兵 `ungrouped`，`group_id IS NULL`）/各分组——复用 `GET /monitor/groups` 字典（monitor-group-change 已落地），前端不硬编码分组
- **后端**：`group_id` 参数接受正整数或字面 `'ungrouped'`（校验语义与 monitor 路由 D3 完全一致：正则 `^(ungrouped|[1-9]\d*)$`，非法 422）；`performance_store._filter_completed` 增分组过滤分支（从 completed 行的 `group_id` 字段比对，list_completed 行已含该字段）
- **前端**：选中分组 → 带 group_id 重拉 stats+samples（同来源维度的重新请求模式）；方向/类型/周期仍本地过滤；统计卡/胜率图/月度趋势/抽屉随请求结果联动
- **维度语义**：分组 = 业务批次视角（「这批监控做得怎么样」，验证自己的选股判断流程），与类型（买卖点有效性视角）、来源（信号渠道视角）互补，三者正交
- **mock**：samples 补 `group_id`（约 60% NULL = 未分组，其余轮换既有 mock 分组 id），handlers 消化 `group_id`（`ungrouped` → `group_id == null`，正整数 → 精确匹配）
- **风险**：当前真实库 4 条 completed 全部 `group_id=None`——选具体分组必然空表；样本不足 badge 与空态引导诚实呈现，不因空转回退（与一轮「样本不足标记」同款处理）

## Risks / Trade-offs

- **样本量起步小**（当前仅个位数 completed 记录）→ 样本不足标记 + 空态引导「先在监控页积累结算样本」，诚实呈现而非隐藏
- **stats/samples 两接口数据一致性** → 同源于 `list_completed`，聚合为纯投影，无二次计算分叉风险
- **旧 tasks 8.2 描述陈旧端点**（`GET /api/bsp/performance`）→ 迁移时以现有 `/api/performance/*` 契约为准，新 tasks 显式记录

## Migration Plan

1. 创建 `performance-page-change` 的 proposal / spec / design / tasks
2. 裁剪 `system-page-change`（spec 目录/proposal/design D4/tasks 8.2）
3. 更新 `chan-stock-manage` proposal 指向文字
4. `openspec validate` 全部受影响变更通过

## Open Questions

- 无。口径 A 已裁定；月度趋势默认前端聚合（D5），样本量增长后可切后端聚合，不阻塞当前方案。
