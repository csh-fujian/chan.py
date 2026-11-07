# Design: vp-entry-strategy-integration

## Context

strategy-task-redesign 已交付任务模型（strategy_task / strategy_task_stock_result / strategy_signal 挂 task_id + params_version）与注册表声明体系（params_schema 含 desc、detail_schema 五积木块、前端 TaskDialog/detail_blocks 声明驱动渲染）。volume-price-entry-rule 已交付判定内核（Debug/vp_entry/：VPStateMachine 流式逐日喂入、decide_b_day 终判带 minute_df/F 分叉、vp_volume F(t) 虚拟量、params 三层 dataclass）。约束：不改缠论内核与 bsp_index；引擎纯读 DuckDB；本变更不改 entry-backtest capability 的行为。

## Goals / Non-Goals

**Goals:**
- 判定内核迁入 WebAPI（方向正确性：后端引擎不 import Debug/）
- VpEntryEngine 适配既有引擎协议，任务体系零协议改动接入
- params_schema enum 类型成为声明体系通用能力
- B 日后状态追踪进引擎适配层

**Non-Goals:**
- 不改 scheduler / strategy_store / 任务 API（引擎协议已兼容，scan_with_params 透传 params dict）
- 不迁移回测/敏感性（Debug/vp_entry 的 backtest/sensitivity 留原地，改 import 来源）
- 不做 F(t) 的预计算缓存（B 日懒加载 + 每任务内存缓存，量级可控）
- 不动 monitor 联动（strategy 来源回查自动覆盖新策略）

## Decisions

### D1. 判定内核迁移与依赖方向

```
WebAPI/strategy_engines/vp_entry/        (新, 判定内核)
    signal_rule.py    minute_trigger.py    vp_volume.py    params.py
    engine.py         (新: VpEntryEngine 适配层)
Debug/vp_entry/                           (保留, 回测工作台)
    backtest.py  sensitivity.py  run_backtest.py  prescreen_sql.py  ...
    -> import WebAPI.strategy_engines.vp_entry.{signal_rule, params, ...}
```

- 迁移四文件原样搬移（内部 import 改为同包相对导入）；test_vp_entry.py 移 Debug 并改 import，随迁断言不改动（回测行为零损失的验证载体）
- 备选（内核留 Debug、WebAPI 反向 import Debug）被否决：生产代码依赖 Debug 目录方向错误；备选（复制一份）被否决：两份实现必然漂移，sensitivity 改参数时任务侧失真

### D2. VpEntryEngine 适配层

```python
class VpEntryEngine:
    def scan(self, code, kl_type_db="K_DAY", autype="QFQ", watermark=None): ...
    def scan_with_params(self, code, params, kl_type_db, autype, watermark): ...
```

- 复用 vol_breakout 的整体模式：读 DuckDB 该 code 全历史日线 → 水位门（无新 K 返回 []）→ 重算全史信号集 → 事件附 watermark_new
- 内核组装：`VPParams(fixed=FixedParams(), **task_params)`——task_params 只含 5 个可配参数；**绕开 VPParams.__post_init__ 的离散校验**：迁移时把 `__post_init__` 的敏感性集合断言移入 sensitivity.py 侧的显式检查（回测纪律留在回测世界），dataclass 保留 vol_gate 取值域断言（enum 校验前移到 validate_params）
- B 日分钟数据：`decide_b_day(pending, minute_df, f_ratio)` 分叉照用——mdf 查 K_5M 当日、f_ratio 由 vp_volume.build_f_ratio 用 B 日前的分钟历史构造，per-scan 内存缓存（仿 run_backtest 的 f_ratio_cache）
- 事件转换 `SignalEvent -> strategy_signal 行`：
  - code/signal_date=b_date/is_buy=True/state=triggered/entry_ref_price=buy_price/stop_ref_price=stop_loss_low
  - payload：a_date/p_date/entry_mode/volume_ratio（放量倍数）/spring/drift_bucket/wick_box/box_days/box_r/a_ret/b_bar_time

### D3. B 日后状态追踪（适配层内、引擎每轮全史重算时推导）

- 状态推导为**纯函数式重放**：扫描全史时记录 SignalEvent 的 b_high（B 日最高价，事件 payload 补充）与 stop_loss_low；重放 B 日之后的日 K 序列：close > b_high → running；close < stop_loss_low → expired；先到哪个算哪个（同日同时满足按 expired 优先，保守口径）
- 备选（跨扫描增量续推状态）被否决：全史重算模式天然覆盖（水位门保证无新 K 不重算），增量续推要额外存每信号的已重放游标，复杂度不成比例
- frozen 保护沿用 store 层 upsert 约束，引擎不管
- states 声明：triggered(观察中, info)/running(已启动, success)/expired(已淘汰, danger)——无 vol_breakout 的 watching 态（VP 信号只有触发后才有生命周期）

### D4. params_schema enum 类型

- 后端 `validate_params`：`type == 'enum'` 时校验取值 ∈ options[].value（选项集外的值报错文案带合法值列表）；_TYPE_CAST 不动（enum 走独立分支，value 透传字符串）
- 前端 types：`StrategyParamSchema.type` 加 'enum' + `options?: {value,label}[]`；TaskDialog 渲染分支：enum → el-select（options 为选项），int/float → el-input-number（现状不变）
- mock：vp_entry 定义的 vol_gate 参数即首个 enum 样例
- vp_entry params_schema 声明（含 desc）：
  - cv7_max: float [0.15, 0.35] default 0.25
  - box_width_max: float [0.08, 0.18] default 0.12
  - n_max: int [4, 10] default 7
  - stop_loss: float [0.05, 0.15] default 0.12
  - vol_gate: enum [mean, strict] default mean

### D6. columns 类型体系补 str（实施发现的既有缺口，修正 proposal「detail_blocks 零改动」表述）

proposal 原表述「detail_blocks / 任务页零改动」不完全成立：vp_entry 私有列（触发方式/Spring/漂移桶）是字符串列，而 columns 声明类型体系原只有 date/int/float。本变更加 `'str'` 列类型（前端类型联合 + BlockSignals 渲染器识别，向后兼容加法）；TaskDetailDrawer 元信息区对 enum 参数值映射 options label 展示（体验增强，value 兜底）。除此之外 detail_blocks/任务页主体确为零改动。

### D5. detail_schema 与 kv 统计计算

- vp_entry 声明：`[summary, per_stock, signals, kv]`（无 timeline——B 日后状态演进已有 states 着色承载，信号按日期排序的 timeline 信息冗余）
- kv 块统计（detail API 服务端算，一次性 SQL/内存聚合该任务信号 payload）：信号总数、分钟版/日线版占比、spring 占比、三桶漂移分布、平均影线盒宽、平均蓄势天数、平均 A 日涨幅、存活信号数（state=triggered）
- detail API 现有返回结构不动（kv payload 塞进既有 detail 响应的 kv 数据字段，块声明 from 声明驱动）

## Risks / Trade-offs

- [分钟数据可用性分叉造成信号不可比（同股不同 B 日口径不同）] → payload 记录 entry_mode，kv 统计给出版本占比，用户可见口径；不做数据补齐（灌数是用户决策）
- [全史重算的分钟懒加载读放大（每 B 日一次 K_5M 查询）] → 单股 B 候选数量级小（~个位数/年）；f_ratio per-scan 缓存；实测慢再优化
- [内核迁移引发回测侧 import 断裂] → test_vp_entry.py 随迁移同改并作为回归锚点；sensitivity/run_backtest import 统一改
- [__post_init__ 敏感性校验外移后回测侧可能漏校] → sensitivity.py 显式加回集合断言（迁移任务内完成，非新增 scope）
- [expired/running 同日双满足的口径歧义] → 定死 expired 优先（保守），design 记录即可

## Migration Plan

1. 归档 strategy-task-redesign（前置：本变更 strategy-signal MODIFIED delta 需要任务语义版本的主树 spec）
2. 判定内核迁移 + 回测侧 import 更新 + test_vp_entry 回归通过
3. 引擎适配层 + 注册定义 + validate_params enum → 冒烟（真 PG + DuckDB 跑 vp_entry 任务全生命周期）
4. 前端 enum 渲染 + mock → build 通过
5. 回滚：vp_entry 定义/引擎注册即插即拔（DEFINITIONS 删一行即回滚）；enum 类型向后兼容（旧定义无 enum 参数不受影响）

## Open Questions

- kv 统计的「平均 A 日涨幅」是否需要分布图（v1 纯数字即可，chart 块已有 date_histogram 预留可后续接）
- 分钟数据缺失的全量任务（大部分股票无 K_5M）是否在 summary 块加「分钟数据覆盖率」提示——实现阶段看 detail 数据是否顺手可得（DuckDB 一次 COUNT 即可），不加也不违 spec
