# Design: chan-pattern-buy-signal

## Context

形态来源：`文档/买卖点走势图/买点/` 9 张图（1 总览 + 8 形态详情），每张含形态特征、市场逻辑、确认信号、成交量特征、注意事项/实战避坑。已确认决策：8 形态全上；买卖点页走独立 Tab（方案 B）；提示标识 = 全量检测 + 最近 M 根时效（M 默认 5，常量起步）。

现有可复用基建（均已在本仓库验证过）：

- `incremental_engine.py` 计算完成钩子 + `_extract_bsp_rows()` 抽取落库模式；
- `bsp_store.py` 惰性 DDL + PG 读写 + `PG_DSN` 降级模式；
- `bsp_grade.py` 置信分三轴打分、分数边界（`_CAP_BLOCKED=59 < _FLOOR_JUDGED_PASSED=60 < _CAP_PENDING_CONFIRM=79`）、分数与措辞同源推导、只落稳定字段不落文案的设计教训；
- `chan_config_schema.py` 静态元数据表模式；
- 前端 `components/chan/` 的 KLineChart `registerOverlay` 覆盖层模式；`BspView.vue` 已有 Tab/筛选/弹窗组件。

约束：不修改 `CChan`/`CBiList`/`CSegListChan`/`CZSList`/`CBSPointList` 计算逻辑；DDL 变更需同步 `update-win.sql`/`update-mac.sql`；涉及缠论策略的说明文档同步约定不触发（本变更不改缠论计算）。

## Goals / Non-Goals

**Goals:**

- 8 个形态全部可计算检测，判据参数化（模块常量），每形态硬编码其避坑规则。
- 统一突破确认引擎：收盘站稳参考线 + 量比 + 回踩加分 + 跌回失效，6 个"突破类"形态共用。
- 置信分 0~100（结构/量能/确认三轴 + 一票否决），落库只存 score/qual。
- 全量历史检测落库；K 线页 overlay + 新信号提示；买卖点页独立 Tab 查询。
- 注意事项/评分明细/文案由 `PATTERN_META` 现算返回，不落库。

**Non-Goals:**

- 不做形态参数的 Web 配置化（第一期常量，验证后另起变更）。
- 不做形态信号的通知推送（预警系统对接留待后续）。
- 不做形态失效后的自动重算回滚（invalidated 仅作标记展示）。
- 不引入第三方形态识别库（调研结论：无成熟可用，自研拟合 + 规则）。

## Decisions

### D1. 检测数据源：笔端点为主，K 线中值序列为辅

- 离散形态（W底/头肩底/箱体/三角/旗形/V型）：用 `bi_list` 端点几何，笔天然滤噪且与缠论结构同源。
- 连续形态（圆弧底/杯柄杯体）：用 K 线中值序列 `(high+low)/2`——笔端点会把圆弧揉成折线丢失特征；中值比收盘价更平滑。杯柄 = 中值拟合杯体 + 笔端点定柄部。
- 备选：纯收盘价序列——被否，中值滤掉单根影线更稳。

### D2. 架构：一个框架 + N 个薄检测器

```
PatternDetector (框架)
  ├─ 滑动窗口扫描 (按形态配置窗口范围, 步进)
  ├─ 8 个 detect_xxx() 结构检测器 → 命中时输出
  │    PatternHit{type, key_points[], ref_line, ref_line2?, window}
  ├─ 共用 BreakoutConfirmEngine (突破类 6 形态)
  │    收盘>ref_line 连续站稳N根 / 量比≥k / 回踩缩量不破=加分 / 跌回=失效
  ├─ 置信分引擎 PatternScorer (结构轴40 + 量能轴30 + 确认轴30)
  │    一票否决项: 无量突破 / 高位出现 / 最小周期不足
  └─ 失效检测: 确认后收盘跌破 ref_line 或关键低点 → invalidated
```

备选：8 个独立大函数——被否，确认逻辑重复 6 次，评分口径漂移。

### D3. 圆弧底判据（用户提出中值点方案）

抛物线拟合（`numpy.polyfit` 二次）而非圆拟合：圆拟合对噪声极敏感；实际圆弧很少是几何圆。

判定链（全部通过才报）：
1. **拟合检验**：窗口中值点二次拟合，开口向上（a<0）、顶点在窗口中部 1/3~2/3 区间、R² ≥ 0.6、曲率适中（排除 V 型尖底与近似横盘）。
2. **三段结构**：左段跌幅 ≥ 阈值；底段斜率≈0 且振幅收窄、持续 ≥ N 根；右段斜率转正。
3. **量能**：底段均量最低、右段温和放大。
4. **突破确认**：共用引擎，参考线 = 圆弧上沿压力线（窗口左起点与右段高点连线水平投影，或窗口内前高）。

杯柄复用：杯体判据同上（回撤深度 15%~30% 约束），柄部 = 杯口高点后的小幅回调（不跌破杯体上半区、回撤 < 杯深 1/3），确认线 = 杯口高点。

### D4. 落库口径（复刻 bsp-grade 教训）

`pattern_signal` 表（惰性 DDL）：`(code, kl_type, autype, pattern_type, confirm_time_key)` 唯一；列含 `pattern_date, price, ref_line, score SMALLINT, qual VARCHAR(8), invalid BOOLEAN, detail JSONB`。`detail` 存稳定的关键点与量比数据（key_points/time_keys/volume_ratio），**不存**文案/建议/注意事项。

存量行兼容：与 bsp-index 同理，score/qual 为 NULL 的行前端显示"未评估"，不猜分。

### D5. 提示时效（用户确认语义）

检测在全量历史跑，M 根只控制"新信号"提示：`GET /api/klines` 返回的 pattern[] 中 `is_new = confirm_time_key >= 最近M根边界`，M=5 常量。K 线页新信号徽标 + 买卖点页 Tab 角标读 `is_new`。

### D6. 置信分三轴与文档条目的映射

每形态 `PATTERN_META[type].scoring` 定义轴权重与判分项，市场逻辑逐条映射：

- 结构轴(40)：形态特征的几何判据逐项（如头肩底：头低于两肩/右肩不破头/颈线水平度）。
- 量能轴(30)：文档「成交量规律」逐条（如旗形：旗杆放量/旗面缩量/突破放量）。
- 确认轴(30)：收盘站稳/回踩不破/周期长度（"周期越长越可靠"）。
- 一票否决（score=0 或封顶 59）：无量突破（文档"无量突破大多是假突破"）、高位出现（"高位出现警惕诱多"）、最小周期不足（"几根K线小形态参考意义低"）。

分数边界沿用 bsp_grade 三道边界设计（59/60/79），分数与档位措辞同源推导（`pattern_qual_of(score)`）。

### D7. 查询与展示

- `GET /api/pattern`：`pattern_type/kl_type/date_from/date_to/code/direction(买)/invalid/score_min` 分页查询；`GET /api/pattern/meta` 返回 PATTERN_META（含 cautions[]、scoring 明细文案）。
- `/api/klines` 响应 `pattern[]`：`{type, name, ref_line, key_points, confirm_time, score, qual, is_new, cautions现算}`。
- K 线页 overlay `chan_pattern`：参考线虚线 + 关键点圆标记 + 确认 K 线标签（形态名+分数）；`is_new` → 图表角标提示。
- BspView 新 Tab「形态信号」：独立列表（形态/周期/日期/股票/分数/档位/失效标记），筛选条件同查询参数；行点击弹窗 = 注意事项 + 置信分明细 + 确认数据；双击跳 K 线页。

### D8. 计算接入点

`incremental_engine` 在 `persist_full_set` 完成后调用 `run_pattern_detection(chan, kl_type)`（全量 bi_list + K 线），结果 upsert `pattern_signal`。步进模式（trigger_step）不做形态检测——形态需多笔端点，步进尾部只产生 candidate，第一期只对批量最终化结果落库。DuckDB 无 PG 场景（PG_DSN 缺失）跳过落库，检测函数仍可被 klines 路由现算调用（降级路径与 bsp_store 一致）。

### D9. 阈值参数

第一期全部模块常量集中在 `pattern_detector.py` 顶部（如 `W_BOTTOM_TOL=0.03`、`VOL_RATIO_K=1.5`、`MIN_PATTERN_BARS` 等），每常量注释对应文档条目。为调参留 `DETECT_PARAMS` dict 可整体覆盖（测试/实验用），不进 CChanConfig。

## Risks / Trade-offs

- [圆弧底/杯柄拟合阈值在真实数据上误报/漏报] → 检测器按 D9 参数集中，先在 Debug 脚本对多只股票可视化验证，再调常量；两形态实现顺序最后。
- [全量检测的计算开销（每股票每周期滑窗+拟合）] → 只在批量最终化/persist 时跑一次（非每根 K 线步进），窗口数有限；箱体/三角检测 O(n) 笔扫描。如实测慢，再加"只重算增量窗口"游标。
- [8 形态同窗重叠误报（W底与头肩底结构相近）] → 同一确认点允许并存多形态（独立行），但同形态同确认时间唯一约束去重；前端列表展示形态类型列可辨。
- [置信分边界设计错误导致档位措辞矛盾] → 沿用 bsp_grade 已验证的 59/60/79 边界与"分数与措辞同源"规则，测试用例覆盖三边界。
- [存量股票无 pattern 数据] → 与 bsp 相同：靠 `/api/pattern/catch-up` 式补算入口（复用 catch_up 流程追加 pattern 步骤），或首次访问时现算降级。
- [numpy 依赖] → 后端环境已具备科学计算栈（requirements 确认），无新引入风险。

## Migration Plan

1. `pattern_store._ensure_tables()` 惰性建表（部署即生效，无需预执行 SQL）。
2. `update-win.sql` / `update-mac.sql` 追加建表记录（幂等）。
3. 存量数据：提供补算入口（复用 catch-up），按需对自选/已计算股票补跑形态检测。
4. 回滚：删除 routers/pattern 注册与 klines pattern 字段即前端无感知；表保留无害。

## Open Questions

（无——形态范围、Tab 方案、提示语义、圆弧判据均已在探索中与用户确认。）
