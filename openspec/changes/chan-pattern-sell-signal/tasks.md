# Tasks: chan-pattern-sell-signal

## 1. 后端检测器与元数据

- [x] 1.1 `pattern_detector.py`：新增高位上下文辅助 `_bearish_context_ok`（上涨趋势前置判定，`_position_ratio` 高位镜像）与一字板/跌停板判定辅助
- [x] 1.2 `pattern_detector.py`：实现 `detect_dark_cloud_cover`（乌云盖顶：T1 阳线 + T2 高开低走阴线覆盖前实体 ≥1/3）
- [x] 1.3 `pattern_detector.py`：实现 `detect_shooting_star`（射击之星：小实体 + 长上影 ≥阈值×实体 + 短下影 + 爆量）
- [x] 1.4 `pattern_detector.py`：实现 `detect_hanging_man`（吊颈线：射击之星镜像，长下影 + 短上影 + 放量）
- [x] 1.5 `pattern_detector.py`：实现 `detect_bearish_engulfing`（阴包阳与穿头破脚共检测器：先判 `high_engulfing_gap`（穿头破脚），否则判 `high_engulfing`，同一 K 线只报一种）
- [x] 1.6 `PatternHit` 增加 `direction` 字段；5 个检测器接入 `_dedup` 与 `run_detection` 统一出口；`hit_to_row` / `ROW_FIELDS` 透传 direction
- [x] 1.7 `pattern_meta.py`：新增 5 项 PATTERN_META（名称、注意事项、三轴评分项、避坑硬约束），带 `direction='sell'`
- [x] 1.8 `Debug/test_sell_pattern_detector.py`：内存构造 K 线冒烟——5 形态各一个成立样例 + 一个判据不足不报样例 + 非高位丢弃样例 + 一字板剔除样例

## 2. 落库与查询接口

- [x] 2.1 `pattern_store.py`：`_ensure_tables()` 追加 `direction VARCHAR(4) NOT NULL DEFAULT 'buy'` 幂等加列；`upsert_pattern_rows` 行序扩展
- [x] 2.2 `update-win.sql` / `update-mac.sql`：按机器追加 direction 加列变更记录（带执行时间注释，幂等）
- [x] 2.3 `incremental_engine.py`：`_extract_pattern_rows` 落库链路透传 direction（落库前算 grade/qual 逻辑不变）
- [x] 2.4 `routers/pattern.py`：`GET /api/pattern` 增加 `direction` 参数；`direction=sell` 且无 `code` 时按自选 ∪ 监控清单过滤（清单空返回空列表）；`GET /api/pattern/meta` 响应带 direction
- [x] 2.5 `serializer.py`：`pattern[]` 每项带 `direction`
- [x] 2.6 `Debug/test_sell_pattern_api.py`：PG 可用时验证 direction 落库 round-trip 与关注范围过滤语义（含清单为空→空列表、显式 code 不过滤）

## 3. 前端

- [x] 3.1 `components/chan/chan_sell_pattern.ts`：复制 `chan_pattern.ts` 改造为第六个独立 overlay（独立注册/开关/点击 hooks），顶部形态用独立橙红色系警示色板
- [x] 3.2 `components/chan/index.ts` 与 K 线页：注册 `chan_sell_pattern`，overlay 开关独立于买点形态与缠论标识
- [x] 3.3 `src/api/` pattern client：查询与 meta 响应带 direction；K 线页数据流接 `pattern[]` 的 direction 分流（buy→chan_pattern，sell→chan_sell_pattern）
- [x] 3.4 BspView 形态 Tab：增加「买/卖方向」筛选；卖向默认关注范围查询；最近 M 根内确认的关注股票卖向行显示「新卖点信号」徽标；点击弹窗展示该形态注意事项与置信分明细

## 4. 验证

- [x] 4.1 重启 8001 后端（无 --reload 须手动重启，带 PG_DSN，PYTHONIOENCODING=utf-8），`vue-tsc -b` 通过，K 线页手动验证：独立开关生效、卖点标识独立展示、点击弹窗正常
- [x] 4.2 同步文档：`文档/缠论策略.md` 增补 5 个顶部形态判据与实现口径（按缠论文档同步约定）
