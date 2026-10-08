# Design

## Context

买卖点确认状态体系已落地（`bsp-sure-annotation`）：`bsp_sure.py` 以水位线 `last_sure_pos` 推导 `is_sure`，落库（`incremental_engine._extract_bsp_rows`）与序列化（`serializer._serialize_bsp`）两链路同口径。本变更在其上补全四级确认阶梯（`ladder`）。已知现状缺口：

- K 线页 `KLineChart.vue` 构建 `ChanBspMeta` 时丢弃 `is_sure`（`chanMarks` 只带 `isBuy/types/v/barTs`），`chan_bsp.ts` 绘制不区分确认状态
- `bsp_index` 无 `ladder` 列；`GET /api/bsp` 响应无该字段
- L3 判定原料（`CBi.cal_macd_metric` 笔 MACD 力度对比）与 L1 判定原料（多级别 `lv_list` 递归计算）在计算内核均已内建但未被 WebAPI 使用

计算内核红线：不修改 `CChan`/`CBSPointList`/`CBiList`/`CSegListChan`——所有推导在 WebAPI 层复用现有只读 API。

## Goals / Non-Goals

**Goals**

- 单一 `ladder` 字段的四级推导、落库、查询、双页面展示（买卖点页级别列 + K 线图 hover tooltip）
- 级别随整套替换写入收敛（与 `is_sure` 同事务同口径）

**Non-Goals**

- 不做分级预警推送（L1/L2/L3 触发通知归 alerts 体系，另行变更）
- 不做分级仓位计算器/下单联动（仓位指引是纯展示文案）
- 不做 L1/L2/L3 独立信号流（每条记录只有一个当前级别）
- 不改回测口径（`regression-testing-change` 的分级触发设计只共享四级语义，不共享实现）

## Decisions

### D1. 级别推导函数集中在 `WebAPI/bsp_ladder.py`（新模块）

```
bsp_ladder.py（与 bsp_sure.py 同模式）
  cal_ladder(bsp, bs_point_lst, sub_chan_result=None) -> "L1"|"L2"|"L3"|"L4"

  L4: bsp_is_sure(bsp, bs_point_lst) == True            # 复用水位线口径
  L3: is_sure=False AND 背驰判定(bsp.bi)                  # cal_macd_metric 力度对比
  L1: is_sure=False AND sub_chan 同向买卖点共振            # 区间套佐证
  L2: is_sure=False AND 其余                              # 兜底 = 虚笔候选
```

判定顺序固定 L4 > L3 > L1 > L2（L1 与 L3 可能同时成立，取更保守预警在前？——裁定：**L3 优先**，背驰是本级别信息，L1 是跨级别佐证；同时成立时标 L3，tooltip 内另行展示 L1 共振标记）。

理由：与 `bsp_sure.py` 的「单点集中、双链路复用」先例同构；避免推导逻辑散落 `incremental_engine` 与 `serializer` 两处漂移。

### D2. 背驰判定的阈值口径

复用 `CBSPointList` 内部背驰判定同款比较（`cal_macd_metric(BSP_CONF.macd_algo)` 离开笔 vs 进入笔），但**不 import 内部私有比较函数**——在 `bsp_ladder.py` 重写一个只读比较（进笔力度 > 出笔力度 × 默认比率即视为背驰预警），阈值常量放模块顶部可调。理由：内核红线要求不依赖 `CBSPointList` 私有状态；重写比较只有几行且语义稳定。

### D3. L1 子级别共振的计算策略：双链路均计算（2026-10-09 修订，推翻初版「落库不算」裁定）

L1 需要对每条未确认买卖点判断「直接一级子级别是否同向买卖点共振」。初版裁定落库链路不算 L1（性能顾虑：日终批量对每只股票额外算一个子级别 CChan，全市场约 ×2 计算量）。**用户反馈推翻该裁定**：买卖点页读 PG 落库值，L1 不落库则页面永远看不到 L1，双链路口径漂移（`bsp_index.ladder` 为 L2 而 `/api/klines` 为 L1）造成困惑。修订为双链路同口径：

- **落库链路**（`incremental_engine.recompute_stock`）：主级别计算完成后调 `_compute_sub_for_l1` 计算子级别买卖点全集（**只读**：借快照续算机制恢复/全量计算，但不落库、不推子级游标），传入 `cal_ladder(sub_bsps=...)`
- **`/api/klines` 序列化链路**（`serializer`）：原有按需计算保持不变

**子级别映射（D3 修订二，同日用户指定）**：单级直连 `5m→30m→D→W→M`——每个级别只看**直接一级**子级别的买卖点做共振判定，不做跨级递归传递（5m 信号只佐证 30m 的 L1，不会经 30m 传递影响 D/W/M）。`SUB_LEVEL_MAP`：30m/60m→5m、D→30m、W→D、M→W；5m 为最低级别无子级。60m 不在用户指定链中，按 30m 同档配 5m。

**佐证资格（D3 修订三，同日用户裁定）**：子级别买卖点作为父级 L1 佐证，须自身**已确认**（子级点 is_sure=true，即子级 L4）。理由：未确认的子级点（子级 L1/L2/L3）会随重算漂移甚至消失——用会消失的信号证明父级信号，等于用影子证明身体。子级点是否 L4 用其自身水位线（`bsp_is_sure`）判定，**不递归计算子级点的 ladder**——否则「子级点的 L1 又依赖孙级别」形成级联传递，违反修订二的单级直连约束。代价：L1 命中数收紧（可能阶段性归零），宁缺毋滥是语义正确的代价。

**共振窗口按级别对差异化**：日级及以上（子级 30m/D/W）沿用初版 ±5 自然日；分钟级（30m/60m ← 子级 5m）收窄到 ±2 小时——5m 信号半衰期短，5 天宽窗会把无关 5m 信号也算成共振，导致分钟级 L1 泛滥。窗口表 `L1_WINDOW_SECONDS` 集中在 `bsp_ladder.py`，`cal_ladder`/`cal_l1_resonance` 增级别键参数，未传键回退日级默认窗（向后兼容旧调用方）。

性能应急闸门：`BSP_L1_PERSIST` 环境变量（默认 `1` 开启），全市场批量吃紧时置 `0` 回退初版行为（未确认行落 L2）；判定口径与 `compute_sub_chan` 一致，子级别失败降级不计算 L1，不阻断主级别落库。

（备选被否：维持初版裁定——已由用户反馈证伪；备选「日终批量算 + tick 补算不算」——两入口共用 `recompute_stock` 一条路径，拆口径反而漂移；备选「30m 保持无子级」——用户明确指定 5m 带动 30m。）

### D4. `bsp_index.ladder` 列与 DDL

`ALTER TABLE bsp_index ADD COLUMN IF NOT EXISTS ladder VARCHAR(2)`，`update.sql` 幂等追加（含执行时间注释，按 CLAUDE.md 数据库变更规范）。写入随 `_extract_bsp_rows` 扩展一列；查询投影补 `ladder`。存量行迁移：**不回填**，旧行 `ladder` 为 NULL 时查询响应按 `L2` 兜底？——否，**按 `is_sure` 映射兜底**（`is_sure=true → L4`，`false → L2`），语义保守且零回填成本；下一次整套替换写入后自然收敛为精确值。

### D5. K 线图 hover tooltip 实现

klinecharts overlay 无内置 tooltip，走 klinecharts 的 overlay 事件回调（`chart.createOverlay` 后监听 `onOverlayTap`/自定义 figure 命中）→ 悬浮命中买卖点 figure 时，在 `KLineChart.vue` 用绝对定位浮层（Element Plus `el-tooltip` 受限于图表 canvas，不可直接包 overlay）渲染分级说明卡。浮层内容：当前级别徽章（高亮）+ 四级列表（每级名称 + 一句说明 + 仓位指引）+ L1 共振标记（仅当同时成立）。`ChanBspMeta` 增 `ladder` 字段（`chanMarks` 构建时不再丢弃）；响应缺 `ladder` 时兜底「未定级」。

### D6. 买卖点页级别列

`BspView.vue` 结果表在「周期」列后新增「级别」列：`ladder` 徽章（L4 实色 / L1-L3 弱化色）+ 说明 tooltip（hover 显全文：级别名 + 仓位指引）。与既有「未确认」灰 tag 并存（L4 行无灰 tag）。

### D7. Mock 数据同步

`mock/data/bsp.ts`（记录补 `ladder` 样例，覆盖 L1-L4 各态）、`mock/data/kline.ts`（`bsp` 数组补 `ladder`）、handlers 透传。前端演示可脱离后端验证视觉。

## Risks / Trade-offs

- [D3 落库链路子级别计算放大批量耗时] → Mitigation：子级别只读不落库（无写入开销），失败降级不阻断主级别；`BSP_L1_PERSIST=0` 性能应急闸门可整体回退；真实数据实测 7 股票 5 周期全量耗时在分钟级（见 tasks 5.1）
- [D2 重写背驰比较与内核判定漂移] → Mitigation：阈值常量集中可调；单元冒烟对照 `CBSPointList` 既有判定样本（同笔序列两侧比对），不作为硬门
- [D5 overlay hover 命中率/性能] → Mitigation：figure 命中走 klinecharts 事件委托（原生 canvas 事件），无逐点事件监听；浮层单例复用
- [D1 L3/L1 同时成立的语义混淆] → Mitigation：标 L3 且 tooltip 显示 L1 共振副标记，spec/design 已固化该裁定

## Migration Plan

1. DDL 先行（`update.sql` 幂等，可重复执行）
2. 后端推导 + 落库 + 查询字段（对旧客户端向后兼容——新增字段，既有消费者无感）
3. 前端两页面 + mock
4. 回滚：前端字段可选渲染，后端新增列无 NOT NULL 约束——单侧回退均不阻断

## Open Questions

- L3 背驰阈值（离开笔/进入笔力度比）默认值取多少：参照 `BSP_CONF.divergence_rate` 默认值起步，实现时以几只样本股目测校准——不阻塞 spec/tasks，实现期微调
