# Design: chan-pattern-sell-signal

## Context

`chan-pattern-buy-signal`（18/25 进行中）已建好形态信号全链路：`pattern_detector.py`（SwingPoint 结构形态 + 突破确认引擎）、`pattern_meta.py`（8 项 META）、`pattern_store.py`（PG `pattern_signal` 表，惰性 DDL）、`routers/pattern.py`、`serializer.py` 的 `pattern[]`、前端 `chan_pattern.ts` overlay 与 BspView Tab。本变更在这条链路上加入卖向，不新建平行链路。5 个顶部形态与买点 8 形态的结构性差异：蜡烛图形态（1~2 根 K 线），无需突破确认引擎，确认点即形态 K 线收盘本身。

## Goals / Non-Goals

**Goals**
- 5 个顶部形态可计算判据 + 置信分 + 落库 + 查询 + K 线页独立标识
- 卖向查询的关注范围默认作用域（列表降噪）
- 与买点形态共表共存，direction 维度可查询

**Non-Goals**
- 不做独立卖点通知通道（提示沿用「最近 M 根徽标」机制）
- 不对买点变更的 spec/实现做改动（两变更独立推进，买点归档后再统一）
- 不做卖点回测/绩效统计（后续变更）
- 不修改缠论核心计算逻辑

## Decisions

### D1: 同表加 `direction` 列，不建独立表
`pattern_signal` 加 `direction VARCHAR(4) NOT NULL DEFAULT 'buy'`（惰性 DDL `ADD COLUMN IF NOT EXISTS`），存量行由 DEFAULT 天然回填 `'buy'`，无需 UPDATE 迁移。唯一键不变——`pattern_type` 命名空间已区分买卖向（买点 8 种 vs 卖点 5 种，命名不冲突），无碰撞风险。
- 备选：独立 `sell_pattern_signal` 表——隔离更彻底但 store/router/前端查询全部复制一套，维护成本翻倍，且字段结构 100% 一致，无实际收益。否决。

### D2: 前端第六个独立 overlay `chan_sell_pattern`
复制 `chan_pattern.ts` 改造为 `chan_sell_pattern.ts`，独立注册/开关/点击 hooks，色系独立（顶部形态用橙红色系警示色，与买点形态绿色系区分，与缠论标识色板也不重叠）。
- 备选：同一 overlay 内分色、共用开关——实现最省，但用户明确要求「与缠论标识分割开来，作为独立的标识」，且独立开关允许只看卖点做风控巡检。选独立 overlay。

### D3: 阴包阳与穿头破脚共用一个检测器
`detect_bearish_engulfing` 先判穿头破脚（`T2.open > T1.high AND T2.close < T1.low`），成立则产出 `high_engulfing_gap` 并跳过普通吞没判定；否则判普通吞没产出 `high_engulfing`。同一根 K 线只报一种，穿头破脚结构轴得分更高。
- 备选：两个独立检测器——同一根 K 线会重复报两条信号（穿头破脚必然满足阴包阳），需要额外去重。否决。
- 命名说明：`high_engulfing_gap` 对应图片「高位穿头破脚阴线」，`high_engulfing` 对应「高位阴包阳」；乌云盖顶 `dark_cloud_cover`、射击之星 `shooting_star`、吊颈线 `hanging_man`。

### D4: 检测器走蜡烛图路径，不进 SwingPoint/突破确认引擎
5 个顶部形态共用一个 `_bearish_context_ok`（高位前置：结构前 N 根存在上涨趋势，用 `_position_ratio` 的高位镜像）+ 逐 K 线形态判定 + 量比佐证（`_vol_features` 复用）。确认时间 = 形态 K 线（T2 或单根）的 `confirm_time_key`，`ref_line_high/low` 填形态 K 线实体边界，`detail` 存 T1/T2 OHLC 关键点。入 `_dedup` 与 `run_detection` 的统一出口，direction 一并返回。

### D5: 卖向查询关注范围过滤在 router 层实现
`GET /api/pattern?direction=sell` 且无 `code` 时，router 取自选 ∪ 监控股票清单（复用 `watchlist_store` / `monitor_store` 既有读取函数），以 `code IN (...)` 过滤；清单为空时返回空列表（而非全量——风控语义下「无关注」等价「无对象」）。`direction=buy` 与不传时行为完全不变。
- 备选：过滤下沉到 store 层——但 store 层需要额外参数语义，router 层一行组合查询更清晰。选 router 层。

### D6: 一字板与涨跌停处理
形态 K 线为一字板（`open==close==high==low`）时不判定（无实体波动，形态失真）；T2 为跌停板（收盘=最低且触跌停价）时正常报告但 detail 标记 `limit_down=true`，置信分量能轴酌情加成（跌停封死的看跌确认度更高）。

### D7: 置信分沿用买点版三轴与分数边界
结构轴（形态覆盖程度/影线比例）/量能轴（量比）/位置轴（高位程度）加权；地板分、否决项、`_qual_of` 档位直接复用 `pattern_detector._score` 框架。位置轴对买点是「低位程度」，对卖点镜像为「高位程度」。

## Risks / Trade-offs

- [蜡烛图阈值（实体比例、影线倍数、覆盖 1/3）需调参] → 全部进 params 常量区并写明来源，先按图片判据给保守默认值，真实数据跑 `Debug/` 冒烟脚本观察命中率再调
- [direction 列对进行中的买点变更产生并发落库交叉] → 两变更的落库行都带 direction（买点行 `'buy'`），唯一键含 pattern_type 无冲突；买点变更未完成的任务如触及同一文件，以本变更的 direction 透传版为准合并
- [关注范围清单查询在 router 层引入 store 依赖] → 只调用既有读取函数，不新增 store 写路径；清单为空返回空列表的语义在 spec 与实现中一致
- [误报噪音] → 位置轴硬约束（非高位丢弃）+ 量能轴降档双保险；detail 落 T1/T2 OHLC 便于前端展示复核

## Migration Plan

1. `pattern_store._ensure_tables()` 追加 `ADD COLUMN IF NOT EXISTS direction`（幂等，存量行 DEFAULT `'buy'`）
2. `update-win.sql` / `update-mac.sql` 追加变更记录（带执行时间注释）
3. 后端检测器/META/router/serializer 上线后，增量引擎下一次重算自然落卖向行；历史卖向信号随全量重算补齐（或手动触发 `/api/chan-config/recompute`）
4. 前端 overlay 与 Tab 筛选随后发布，无接口破坏性变更
- 回滚：direction 列保留无害；前端 overlay 开关默认状态可控

## Open Questions

- 量比阈值与「高位」窗口参数的具体数值（先给保守默认，真实数据调参后固化）
- 跌停板量能加成的具体幅度（D6 标记先行，评分细则实现时定）
