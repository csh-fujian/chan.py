# Proposal: chan-pattern-buy-signal

## Why

`文档/买卖点走势图/买点/` 提供 8 个经典底部起涨形态（圆弧底、W底、头肩底、杯柄、V型反转、箱体突破、上升三角形、低位旗形）的判据、确认信号与避坑要点。当前系统只有缠论买卖点一类信号，缺少这批形态级买点的自动识别、落库、查询与 K 线可视化能力。本变更将 8 个形态全部实现为可计算判据，接入现有增量计算引擎与 Web 前端，使最新走势中出现形态确认信号时能主动提示。

## What Changes

- 新增 `WebAPI/pattern_detector.py`：8 个形态检测器 + 共用突破确认引擎，输入为 `chan[kl_type].bi_list` 与 K 线序列（含 close/volume），不修改 `CChan`/`CBiList` 等缠论核心计算逻辑。
- 新增形态元数据 `PATTERN_META`：每形态的名称、注意事项（弹窗展示）、置信分评分项（市场逻辑拆解为结构/量能/确认三轴）、避坑硬约束（检测器代码必须遵守的否定/过滤规则）。
- 新增 `WebAPI/pattern_store.py`：PG 表 `pattern_signal`（惰性 DDL，模式仿 `bsp_store`），只落稳定字段（总分/档位/参考线价位/关键点/确认时间/量比/回踩状态），不落文案。
- 增量引擎 `_extract_pattern_rows()`：计算完成后对全量历史做形态检测并落库（检测窗口不受"最近 M 根"限制；M 根只控制前端提示时效）。
- 新增 `routers/pattern.py`：`GET /api/pattern`（查询条件：形态类型/周期/日期范围/方向/股票/确认状态）、`GET /api/pattern/meta`（返回 PATTERN_META，含注意事项文案）。
- `/api/klines` 响应增加 `pattern[]`：K 线页展示形态参考线、关键点标记、确认点标签。
- 前端 K 线页新增形态 overlay：参考线虚线 + 关键点 + 确认标记；确认时间在最近 M 根（默认 5，常量）内的信号显示醒目「新形态信号」提示徽标。
- 前端买卖点页新增独立 Tab（方案 B）：形态信号独立列表 + 独立查询条件，行点击弹窗展示该形态的注意事项与置信分明细。
- 置信分体系（0~100）：按每形态的市场逻辑拆为结构轴/量能轴/确认轴加权评分，含一票否决项（如无量突破、高位出现）；落库只存总分与档位，评分明细现算。

## Capabilities

### New Capabilities
- `chan-pattern-signal`: 底部形态买点信号的检测判据、确认引擎、置信分评分、注意事项元数据、PG 落库、查询接口、K 线页 overlay 与新信号提示、买卖点页独立 Tab 查询。

### Modified Capabilities

（无——形态查询是独立 Tab 与独立数据源，不改变 `bsp-page` / `bsp-index` 的既有需求语义。）

## Impact

- **后端**：`WebAPI/` 新增 3 个模块（pattern_detector / pattern_store / routers/pattern.py）；`incremental_engine.py` 增加一行级调用点；`serializer.py`（klines 响应）增加 pattern 数组。
- **数据库**：PG 新表 `pattern_signal`（惰性 DDL 在 `pattern_store._ensure_tables()`）；`WebAPI/update-win.sql` / `update-mac.sql` 追加变更记录。
- **前端**：`Front/src/` 新增形态 overlay 组件（`components/chan/` 模式）、BspView 新 Tab、api 模块 `src/api/` 增 pattern client。
- **缠论核心**：零改动（只读 `bi_list` / `CKLine_Unit` 既有属性）。
- **依赖**：仅 numpy（`polyfit` 用于圆弧底/三角/旗形的直线与抛物线拟合），已在后端依赖范围内可加。
- **风险**：软形态（圆弧底/杯柄）判据阈值需真实数据调参；置信分边界（地板分/否决项）沿用 `bsp_grade.py` 的分数边界设计教训。
