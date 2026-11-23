# Tasks

## 1. 检测框架与元数据

- [x] 1.1 新建 `WebAPI/pattern_detector.py`：`DETECT_PARAMS` 常量表（每项注释对应文档条目）、`PatternHit` 数据结构、滑动窗口扫描框架；用内存构造 K 线序列跑通框架冒烟（无需联网）。验证：`python -c` 导入无错 + Debug 冒烟脚本输出命中。
- [x] 1.2 新建 `WebAPI/pattern_meta.py`：`PATTERN_META` 8 形态静态元数据（名称/注意事项 cautions[]/评分项文案 scoring/确认引擎说明），文案全部来自 `文档/买卖点走势图/买点/` 8 张图。验证：meta 覆盖 8 键，每形态 cautions 非空。
- [x] 1.3 实现共用突破确认引擎（收盘站稳连续 N 根 / 量比 ≥k / 回踩缩量不破加分 / 跌回失效），统一用 close 判定（禁 high）。验证：构造突破+假突破+回踩三种内存序列断言三种结果。

## 2. 八个形态检测器

- [x] 2.1 W底检测器（两谷差≤3%、颈线=中间反弹高点、右底大幅破左底不报）+ 内存构造用例。验证：Debug 用例断言命中与两个否定场景。
- [x] 2.2 头肩底检测器（三谷两峰、头低于两肩、右肩不破头、颈线两峰连线允许微斜）+ 用例。验证：同上模式。
- [x] 2.3 箱体突破检测器（上下轨各≥2次触碰、收盘放量站上上轨）+ 用例。
- [x] 2.4 上升三角形检测器（≥2 高点等高水平压力 + ≥2 低点抬升支撑、最小二乘拟合、整理缩量）+ 用例。
- [x] 2.5 低位旗形检测器（旗杆陡峭笔上涨、旗面向下倾斜窄通道线性回归、旗面缩量、低位约束）+ 用例。
- [x] 2.6 V型反转检测器（连续大阴急跌笔 + 大阳急拉笔、尖底、急跌后放量长阳确认）+ 用例。
- [x] 2.7 圆弧底检测器（中值序列 (high+low)/2 二次拟合：开口向上/顶点中部/R²达标/曲率带、三段结构与量能检验、突破圆弧上沿）+ 用例。验证：构造理想弧形命中、V型与横盘序列不命中。
- [x] 2.8 杯柄形态检测器（杯体复用圆弧判据+回撤15%~30%约束、柄部=杯口小幅回调不破杯体上半区/回撤<杯深1/3、确认线=杯口高点）+ 用例。
- [x] 2.9 置信分引擎：结构轴40/量能轴30/确认轴30、一票否决（无量突破/高位出现/最小周期不足）、分数边界沿用 59/60/79、`pattern_qual_of(score)` 同源档位推导。验证：单测覆盖三边界与三个否决项。

## 3. 落库与计算接入

- [x] 3.1 新建 `WebAPI/pattern_store.py`：`pattern_signal` 惰性 DDL（唯一键 code+kl_type+autype+pattern_type+confirm_time_key，列含 score/qual/invalid/detail JSONB，不落文案）、upsert、查询、PG_DSN 缺失降级。验证：连本机 PG 建表成功，重复 upsert 不产生重复行；未配 DSN 时静默跳过。
- [x] 3.2 `WebAPI/update-win.sql` 与 `update-mac.sql` 追加幂等建表记录（带执行时间注释）。验证：文件按机器各自追加、SQL 可重复执行。
- [x] 3.3 `incremental_engine.py` 在 persist_full_set 完成后调用 `run_pattern_detection()` 落库（步进模式不检测）。验证：跑一次已灌数股票的 catch_up，`pattern_signal` 出现行，再次执行无重复。
- [x] 3.4 存量补算：catch-up 流程追加 pattern 步骤，对已计算股票补跑。验证：对一只存量股票补算后查询接口有数据。

## 4. 查询接口

- [x] 4.1 新建 `WebAPI/routers/pattern.py`：`GET /api/pattern`（pattern_type/kl_type/date_from/date_to/code/invalid/score_min 分页筛选）、`GET /api/pattern/meta`（返回 PATTERN_META 含 cautions）。验证：uvicorn 起服后 curl 各参数组合返回正确筛选结果。
- [x] 4.2 `serializer.py`（/api/klines）增加 `pattern[]`：参考线/关键点/确认时间/分数/档位/cautions 现算/`is_new`（确认时间 ≥ 最近 M 根边界，M=5 常量）。验证：curl /api/klines 检查 pattern 字段与 is_new 边界（第 4/5/6 根前确认的信号 is_new 正确）。

## 5. 前端

- [x] 5.1 `src/api/` 新增 pattern client（列表/meta 两接口 TS 类型）。验证：`vue-tsc -b` 通过。
- [x] 5.2 K 线页形态 overlay（`components/chan/chan_pattern` 模式）：参考线虚线、关键点标记、确认 K 线标签（形态名+分数）、`is_new` 醒目徽标点击定位。验证：dev 页面 8001 后端数据下 overlay 渲染、徽标只出现在最近 M 根内确认的信号。
- [x] 5.3 形态标记/徽标点击弹窗：注意事项列表 + 置信分明细 + 确认数据。验证：点击任一形态标记弹窗内容与 meta 一致。
- [x] 5.4 BspView 新增「形态信号」独立 Tab：独立列表与查询条件（形态类型/周期/日期/失效状态/最低分数）、行点击弹窗、双击跳 K 线页、失效行视觉区分。验证：dev 页面切 Tab 查询、筛选、弹窗、双击跳转全链路可用。
- [x] 5.5 前端构建与类型检查全量通过。验证：`cd Front && npm run build` 成功。

## 6. 集成验证

- [x] 6.1 端到端冒烟：选 2~3 只已灌数股票跑 catch_up → PG 有 pattern 行 → /api/pattern 可查 → K 线页显示 overlay 与新信号徽标 → 形态 Tab 查询与弹窗正常。验证：手动走查记录到 Debug 脚本或截图。
- [x] 6.2 真实数据调参：对圆弧底/杯柄在多只股票上可视化检测输出，调 R²/曲率/振幅阈值，减少误报。验证：Debug 可视化脚本输出与人工判读一致率记录。

## Workflow follow-up

- 归档前按项目评审要求完成检查（openspec validate）。
- 归档变更（/opsx:archive）。
