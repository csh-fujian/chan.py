## Context

买卖点索引的落库链路：`incremental_engine.py _extract_bsp_rows()` 遍历 `kl.bs_point_lst.getSortedBspList()` 全集生成行元组 `(bsp_date, bsp_type, is_buy, price, time_key)` → `bsp_store.persist_full_set()` 整套替换写入 `bsp_index`（同事务推进游标）。`_extract_bsp_rows` 与同文件 `_extract_structure`（bi/seg/zs 有 `if is_sure` 过滤）构成契约不对称：买卖点不带确认状态。

计算内核侧：`CBS_Point` 无 `is_sure` 字段；确认语义的权威来源是 `CBSPointList` 的水位游标 `last_sure_pos`/`last_sure_seg_idx`（`BSPointList.py update_last_pos` 从最后一个 `is_sure` 线段倒推）。买卖点的确认性完全由其所在笔 `bi` 的 klu 索引与水位线的关系决定。`bi.parent_seg` 反向引用在计算过程中维护，但落库时点（全量/续算收尾）的取值可靠性需推导逻辑不依赖它。

查询侧：`query_bsp()`（`bsp_store.py:183`）已把 keyword/kl_type/bsp_types/is_buy/日期全部下推 SQL WHERE，`sure` 过滤可同一模式追加。`routers/bsp.py bsp_list` 端点已解析 `direction`/`bsp_type`（方向化标签）参数。前端 `BspView.vue` 查询表单已有周期/类型/方向/日期/关键词筛选。

CLAUDE.md 约束：数据库 DDL 变更必须同步追加到 `WebAPI/update.sql`（带执行时间注释、幂等可重跑）。

## Goals / Non-Goals

**Goals:**

- `bsp_index` 每行携带 `is_sure`，落库时从水位线口径推导（不在 `CBS_Point` 加字段，不动计算内核）
- `GET /api/bsp` 查询参数支持按确认状态过滤，响应行携带 `is_sure`
- 前端买卖点页未确认行视觉标注 + 查询表单确认状态筛选
- `/api/klines` 的 `bsp` 序列化同步补 `is_sure`（对齐 bi/seg 契约）

**Non-Goals:**

- 不改计算内核（`ChanAnalyse/BuySellPoint/`、`CChan`——推导在 WebAPI 层）
- 不做「实时信号流」视图（step mode 快照序列的历史回放，属更严格的「当时可见」方案，后续独立变更）
- 不改 K 线页 `chan_bsp.ts` 绘制（未确认买卖点的图表视觉弱化是否需要，等本变更落地后按用户反馈另立变更）
- 不迁移/回填存量 `bsp_index` 数据（下一轮整套替换写入自然收敛，见 Migration）

## Decisions

### D1: 确认推导口径 —— 水位线 `last_sure_pos`，而非 `bi.parent_seg.is_sure`

**决策**：`_extract_bsp_rows` 里判断 `bsp.bi.get_end_klu().idx <= kl.bs_point_lst.last_sure_pos` → `is_sure=True`，否则 `False`。

**理由**：与 `CBSPointList` 自身的回滚逻辑同源——`clear_store_end` 正是用 `bi.get_end_klu().idx <= last_sure_pos` 判定哪些尾部买卖点需要撤销重算，本口径与它语义完全一致（≤ 水位线 = 稳定不会撤）。而 `bi.parent_seg` 指向虚段时取值随重算摇摆，且笔的 `seg_idx` 与段列表的对应关系在续算过程中有复杂回退，可靠性不如水位线。`update_last_pos` 的水位线在 `cal()` 收尾必然已刷新，落库时点可直接读。

**备选**：`bi.parent_seg.is_sure`——被否（上述摇摆问题）；`bi.is_sure`（笔自身确认）——被否（口径过宽：笔确认但所在段未确认时，依托该虚段的买卖点仍可能随段重画而移动，应以段的水位线为准）。

### D2: DDL —— `bsp_index` 加 `is_sure BOOLEAN NOT NULL DEFAULT TRUE`

**决策**：`update.sql` 追加幂等加列（`IF NOT EXISTS` DO 块，`DEFAULT TRUE`），存量行按「已确认」回填，应用层 `_ensure_tables` 同步建表语句。

**理由**：`DEFAULT TRUE` 使存量数据与新写入（确认路径）行为向后兼容；历史行中确有基于虚段的未确认点，但整套替换写入机制保证下一轮补算（启动/定时/日终任一入口）即整体替换为带准确 `is_sure` 的全集，存量误差是自愈的、无需一次性迁移脚本。Boolean 单列无索引需求（过滤基数低、与其他条件同 WHERE 组合走现有索引足够）。

**备选**：加列同时立即全量重刷所有股票——被否（阻塞发版、收益仅是提前一轮收敛）。

### D3: 查询参数 —— `sure` 三态字符串，与 `direction` 同风格

**决策**：`GET /api/bsp?sure=confirmed|preview`，缺省不过滤；`query_bsp` 增 `is_sure: Optional[bool]` 参数，下推进同一 WHERE。

**理由**：与既有 `direction=buy|sell`（字符串枚举 → `Optional[bool]`）的参数风格完全同构，router 层解析模式复制即可；不用布尔字面量 `true/false`（缺省语义与「不过滤」冲突，三态字符串显式无歧义）。

### D4: 前端标注 —— 未确认行「未确认」浅色标签，默认不过滤

**决策**：`BspView` 结果表「买卖点类型」列或独立小列对 `is_sure=false` 行渲染灰色「未确认」tag（Element Plus `el-tag`，`type=info`）；查询表单增「确认状态」下拉（全部/已确认/未确认，默认全部）。

**理由**：默认不过滤保留「上帝视角 + 标注」语义（用户裁定：不丢信号、可见预览）；标注用弱视觉（灰 tag）避免与红涨绿跌、类型标签的方向色语义冲突。独立小列 vs 拼接在类型列——实施时按表格现有列宽裕量定，两者均满足 spec「记录携带确认状态」与视觉标注需求。

### D5: `/api/klines` 的 `bsp` 补字段，口径与 D1 一致

**决策**：`serializer.py _serialize_bsp` 每点补 `"is_sure"`，推导逻辑与 D1 同（`bs_point_lst.last_sure_pos` 水位线），抽公共工具函数供 incremental_engine 与 serializer 复用。

**理由**：K 线页 `chan_structure` 里的 bi/seg 已带 `is_sure`，bsp 不带则同一响应内契约不对称；复用工具函数保证两条链路口径永不漂移。

## Risks / Trade-offs

- [水位线在 step mode 中途快照下的语义] 增量续算过程中读 `last_sure_pos` 是「本轮计算收尾后的水位」，与落库时点一致；但极端情况下（未跑 `cal()` 的部分状态）取值可能滞后 → 推导函数内做 None/负值防御（`last_sure_pos <= 0` 时按未确认处理并告警日志）
- [存量行 `DEFAULT TRUE` 回填误差] 存量未确认点被误标为已确认，窗口期 = 存量落库到下一轮补算 → 整套替换写入自愈（启动/定时/日终任一入口触发即收敛）；页面上短期无视觉区分误差，风险可接受且随时间归零
- [前端 mock 漂移] MSW mock 数据需同步补 `is_sure` 字段与样例，否则 mock 模式下新筛选下拉查不到未确认记录 → mock 任务纳入 tasks 并以「mock 模式下三种筛选取值各自返回正确子集」为验收
- [`last_sure_pos` 为 `CBSPointList` 私有惯例] Python 无真私有（`self.last_sure_pos` 可直接读），但属跨层访问实现细节 → 推导工具函数集中在 WebAPI 层一处（D5），加注释说明口径来源，内核升级时只需核对单点

## Migration Plan

1. `update.sql` 追加幂等加列（先行，可独立执行）
2. 后端落库推导 + 查询过滤 + 序列化字段（随发版生效）
3. 前端标注 + 筛选（随前端发版）
4. 存量数据自愈：部署后第一个补算触发点（服务启动即有）整套替换写入，`is_sure` 收敛准确
5. 回滚：DDL 列保留无害（多列不影响旧代码路径）；应用层 revert 即回到「无确认区分」现状
