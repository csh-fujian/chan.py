# Design

## Context

`/api/klines`（`WebAPI/main.py:103`）→ `_compute_chan` → `serialize_chan`（`WebAPI/serializer.py:151`）已对每级别输出 `bi[]`/`seg[]`（`begin/end/dir/is_sure`），前端 `KLineChart.vue:538` 把它们注入 `chan_bi`/`chan_seg` overlay 的 `extendData` 元数据（`ChanBiMeta`/`ChanSegMeta`）。背驰判断所需的力度接口已存在于内核（`CBi.cal_macd_metric`、`CSeg.cal_macd_metric`），配置读取出口为 `chan_config_store`。本变更在这条链路上加「末尾元素背驰」一个只读旁路，见 proposal 的动机。

## Goals / Non-Goals

**Goals**

- 每级别末尾笔/段的背驰判定（口径 A：相邻同向前一元素直接比力度）+ 前端红色阴影标注。
- 判断口径与买卖点链路共享同一份生效配置（`macd_algo` 多选 AND + `divergence_rate`）。

**Non-Goals**

- 不给中间元素计算背驰（只算末尾，历史元素不输出）。
- 不落库（`bsp_index`/`incremental_engine` 链路零改动）；不新增配置项、不改 schema。
- 不改 `CChan`/`CBiList`/`CSegListChan` 等计算内核（仓库约定）。
- 不做背驰的悬浮提示/tooltip（后续可加）。

## Decisions

### D1 计算位置：serializer，序列化末尾元素时同步计算

`_serialize_bi`/`_serialize_seg` 遍历时对**最后一个元素**追加 `is_divergence` 字段。备选方案（前端计算）被否决：前端拿不到 `cal_macd_metric` 的原始 K 线 MACD 序列；备选方案（内核加字段）被否决：违反「不动计算内核」约定。序列化层只读内核接口，天然覆盖所有周期，且结果随 `/api/klines` 缓存（`config_fingerprint` 已含 `macd_algo`/`divergence_rate`，配置变更 → 指纹失配 → 自动重算重算缓存，无需额外失效逻辑）。

### D2 配置来源：级别对应配置对象，买侧口径

- 笔级取 `kl_list.bs_point_lst.config`（`CPointConfig`，`_serialize_bsp` 已有同款读取先例）。
- 段级取 `kl_list.seg_bs_point_lst.config`（若容器无此属性则回退笔级配置）。
- `CPointConfig` 有 `b_conf`/`s_conf` 两侧，仅当用户用了 `-buy`/`-sell` 后缀覆盖时两侧 `divergence_rate`/`macd_algos` 才不同。背驰标注不分买卖侧（力度指标本身方向无关，`cal_macd_metric` 内部按 `is_down` 取向），**取买侧 `b_conf`** 作为统一口径，避免两侧不一致时二选一无依据。`macd_algos` 多选形态经 `cfg_algos`（`ChanAnalyse/ZS/ZS.py`）归一。

### D3 判定逻辑：复用 `CZS.is_divergence` 的两段比较范式，独立实现轻量版

```python
# 伪代码（bi 为末尾笔，prev 为同向前一笔 bi[-2]）
for algo in cfg_algos(b_conf):
    cur  = bi.cal_macd_metric(algo, is_reverse=False)
    prev = prev_bi.cal_macd_metric(algo, is_reverse=False)
    if cur > divergence_rate * prev:  → 不背驰
```

- **不调用 `CZS.is_divergence` 本体**：它绑定中枢语义（`end_bi_break` 前置、进入/离开方向），口径 A 没有中枢；只复用其「多指标 AND + rate 比较 + inf 处理」的数值范式（`ZS.py:449-484`）。
- **力度为零/不可比 → `null`**：`prev == 0`（除零）或任一侧 metric 为 None 时判不适用，不做特殊缩放。
- **`divergence_rate = inf`（`math.isinf`）→ 整级 `null`**：与 spec「不判断力度时输出 null」对齐。内核的 `> 100` 关闭口径不采用——那是买卖点链路的「保送」语义，本标注无后续判据链，inf 就是不判断。
- 两侧同向由结构保证（笔列表方向交替，`bi[-1]` 与 `bi[-3]` 同向、与 `bi[-2]` 反向），仍做防御性方向校验。

### D4 量能类段级回退：`peak`

`CSeg.cal_macd_metric` 对 `VOLUMN/AMOUNT/...` 抛 `unsupport macd_algo`（`Seg.py:278`）。段级计算时若 algo ∈ `VOLUME_MACD_ALGOS`（`chan_config_store.py:54` frozenset，直接 import 复用），替换为 `MACD_ALGO.PEAK`。与买卖点链路 `SEG_FALLBACK_MACD_ALGO` 同口径，不复制常量。用户显式配过 `macd_algo-seg` 时该覆盖已进 `build_conf` → `CChanConfig` → 段级配置对象的 `macd_algos`，天然优先。

### D5 前端：垫线阴影而非描边

klinecharts line figure 无边框样式。方案：`createPointFigures` 中对 `isDivergence=true` 的元素**先** push **两层**同坐标半透明红线（外层宽淡 / 内层窄浓，叠出外发光过渡，避免单层半透明形成平铺色带），**再** push 原线——同 figure 数组内后者覆盖前者，视觉上是原线下透出的红色阴影边。线宽（2026-11-10 按用户要求收细到原值约 70%）：笔 5px / 3.25px，段 6.5px / 4.5px；alpha 见 `DIVERGENCE_ALPHA`（outer 0.14 / inner 0.34）。备选（`shadowBlur` canvas 特效）跨主题/缩放不稳，弃。虚笔/虚段时阴影线用实线（阴影表达背驰、虚线表达未确认，两语义正交）。主题切换经 `rebuildAllOverlays` 既有路径重绘，阴影色值挂 `getChanPalette()` 新增字段（明暗两套微调）。

### D6 数据契约：可选字段，旧消费者零感知

`bi[]`/`seg[]` 末尾元素加 `is_divergence: true|false|null`；非末尾元素**不写该键**（比写 null 更省字节，TS 类型标可选 `is_divergence?: boolean | null`）。MSW mock（`Front/src/mock`）同步补字段保持契约演示完整。缓存兼容：旧缓存条目无此键 → 前端按 `undefined` 处理 = 不标注，无需清缓存。

## Risks / Trade-offs

- [买侧口径在 `-buy`/`-sell` 覆盖不一致时与买卖侧判定有偏差] → 记录于 D2，属可接受的展示口径；后续如需精确可按末元素方向取对应侧。
- [末尾虚笔重算时判定会摆动（虚笔端点随新 K 线变）] → 与 `is_sure` 同类的固有属性；标注随每次 `/api/klines` 刷新重算，无需稳定化。
- [红色阴影与 A 股红涨色（`--rise: #F6465D`）视觉相近] → 双层发光形态（垫线）+ 半透明度与蜡烛实体区分；`palette.ts` 的阴影红独立取色（暗色 `255,82,108` 偏粉紫 / 明亮 `206,38,62` 压深），刻意偏离涨红色相。
- [量能类段级回退为 `peak`，用户可能以为段级也在比成交量] → spec 已明示该回退为契约行为；前端不做额外提示（Non-Goal）。

## Migration Plan

纯增量：后端字段可选、前端 `undefined` 兜底，部署即生效，无需数据迁移；回滚 = revert 两个 commit（serializer / 前端）。

## Open Questions

（无——口径已全部在探索阶段确认。）
