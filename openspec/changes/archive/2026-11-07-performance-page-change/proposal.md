## Why

绩效页面（`/performance`）前端已按 spec 搭好（统计卡/胜率柱状图/聚合表/样本明细抽屉，mock 驱动），但后端 `GET /api/performance/*` 始终为 stub 返回空集——页面无真实数据；且存在三处摆设（周期筛选不生效、统计卡不随筛选联动、胜率图缺样本补 0 误导）。监控页迭代（D8 收益率口径、D13 结算价修复、D14 来源字典与统计联动）已把绩效所需原料全部备齐：monitor 表 completed 记录即现成的绩效样本。

## What Changes

- **新建 `bsp-performance` 能力**（自 `system-page-change` 迁入两条 requirement 并重写），按口径 A 落地：
  - **后端接真**：`GET /api/performance/stats` 改为对 monitor 表 completed 记录 PG 聚合（GROUP BY bsp_type, kl_type），`GET /api/performance/samples` 返回 completed 明细（含来源/持有天数）；`strategy-signal-page` D7 预留的 `source`/`instance_id` 参数兑现
  - **删除**：周期侧栏摆设（以落地版周期筛选替代）、表格上方 el-select 双入口筛选（统一侧栏单入口）、胜率图「缺样本补 0」逻辑（无样本类型剔除）
  - **改造**：统计卡与胜率柱状图联动侧栏筛选（复用 monitor D14 统计联动模式）；统计表与样本明细增加周期维度（对齐 D4 口径 30m/60m/D/W/M）；来源维度（复用 `GET /monitor/sources` 字典，缠论/策略实例/自选对比）
  - **新增**：类型期望值列（胜率×平均盈 − 败率×平均亏）、月度胜率/盈亏趋势折线（按买卖点时间月度聚合，红涨绿跌）、样本明细归因摘要联动（已归因行显示 LLM 归因一句话 + 双击跳 K 线，对齐 monitor D12 模式）、样本不足标记（<5 显示统计意义有限提示）
- **增量需求（2026-10-05 二轮，已确认）**：
  - **类型树细化到 6 枚举**：侧栏「类型」从第一/二/三类三档粗分（`startsWith` 前缀匹配，`1p` 混入第一类、`2s` 混入第二类）细化为 6 档枚举精确匹配（第一类 1 / 盘整背驰 1p / 第二类 2 / 类二 2s / 三类a 3a / 三类b 3b）；`3a`/`3b` 前端标签撞名（同为 3B/3S）在表格与胜率图加枚举尾缀区分；组合类型口径固化（数据层已按类型展开多行，绩效统计无组合字符串，多属性点按属性分别计入各枚举组）
  - **监控分组维度**：侧栏第五组「分组」树（复用 `GET /monitor/groups` 字典：全部分组/未分组哨兵/各分组），`/api/performance/stats|samples` 增 `group_id` 过滤参数（正整数或 `'ungrouped'`，语义对齐 monitor 路由 D3），选中分组重拉统计（同来源维度模式）
- **同步裁剪来源变更**：`system-page-change` 的 `specs/bsp-performance/` 整体移除、proposal Capabilities 删除 `bsp-performance`、tasks 8.2 删除；`chan-stock-manage` proposal 迁移指向文字更新（`bsp-performance` 归 `performance-page-change`）

## Capabilities

### New Capabilities

- `bsp-performance`: 买卖点绩效统计能力（自 system-page-change 迁入重写）——基于监控结算样本（口径 A）按买卖点类型/周期/来源统计历史胜率、盈亏比、期望值与月度趋势，样本明细复核口径并联动归因复盘

### Modified Capabilities

<!-- 无：openspec/specs/ 下尚无 bsp-performance 已归档 spec；system-page-change 为未归档变更，在其中移除 delta 不构成对已归档 spec 的修改。 -->

## Impact

- **openspec 工件**：
  - 本变更新增 `specs/bsp-performance/spec.md`（需求自 system-page-change 迁入并按口径 A 重写）
  - `system-page-change` 删除 `specs/bsp-performance/`、proposal Capabilities 移除 `bsp-performance`、design D4 映射表删对应行、tasks 8.2 删除
  - `chan-stock-manage` proposal 迁移指向文字更新（一行）
- **前端**：`Front/src/views/performance/PerformanceView.vue`（删摆设/联动/新图表）、`Front/src/api/modules/performance.ts`（参数扩展）、`Front/src/mock/data|handlers/performance.ts`（mock 数据补 kl_type/source/期望值月度趋势）
- **后端**：`WebAPI/routers/performance.py`（stub → 真实现）、`WebAPI/monitor_store.py` 或新增 `performance_store.py`（completed 聚合 + 样本明细）；复用 `GET /api/monitor/sources` 字典
- **口径裁定**：绩效样本 = monitor 表 completed 结算记录（口径 A）；否决 chan-stock-manage 历史 design D9 的 bsp_index 全量联查口径（详见 design D1）
- **不修改**：`CChan` 计算流水线；monitor 表 schema（聚合为只读查询）；monitor-page-change 已归档行为
