# Tasks

## 1. 后端：背驰判定 + 序列化字段

- [x] 1.1 在 `WebAPI/serializer.py` 新增背驰判定辅助函数（口径 A：末尾元素 vs 相邻同向前一元素；多指标 AND；`divergence_rate` 阈值；inf → null；量零/不可比 → null；段级量能类 algo 回退 `MACD_ALGO.PEAK`，量能类判定复用 `chan_config_store.VOLUME_MACD_ALGOS`，多选归一复用 `ChanAnalyse/ZS/ZS.py` 的 `cfg_algos`），并验证：`python -c` 单测式脚本对构造的 `CBi`/`CSeg` mock 序列跑判定，覆盖 inf/null/AND/回退四分支
- [x] 1.2 `_serialize_bi`/`_serialize_seg` 支持接收配置（笔级 `bs_point_lst.config.b_conf`、段级 `seg_bs_point_lst.config.b_conf`，缺容器属性回退笔级），对末尾元素写入 `is_divergence`，非末尾元素不写该键；`serialize_chan` 接线传参，并验证：`PYTHONPATH=. python Debug/` 新增冒烟脚本跑 DuckDB 离线（如 sz.000001 日线），断言响应 dict 的 `bi[-1].is_divergence` 存在且为 `true/false/null` 之一、`bi[:-1]` 无该键
- [x] 1.3 验证配置联动：改 `chan_config` 的 `macd_algo`/`divergence_rate`（如把 `divergence_rate` 存为 `"inf"` 再读出）后重新序列化，`is_divergence` 输出为 `null`；确认 `config_fingerprint` 含 `macd_algo`/`divergence_rate` 分段（读 `WebAPI/config_fingerprint.py` 现状即可，无代码改动）

## 2. 前端：类型 + overlay 元数据

- [x] 2.1 `Front/src/api/types.ts` 的 `Bi`/`Seg` 类型加可选字段 `is_divergence?: boolean | null`，并验证：`cd Front && npx vue-tsc -b --noEmit`（或 `npm run build` 的类型段）无新增类型错误
- [x] 2.2 `KLineChart.vue` 的 `rebuildAllOverlays` 把 `b.is_divergence`/`s.is_divergence` 写入 `biMeta`/`segMeta`（`ChanBiMeta`/`ChanSegMeta` 加 `isDivergence?: boolean | null`），并验证：mock 数据下打开 K 线页，末尾笔带 `is_divergence: true` 时图表渲染出红线（人工浏览器验证）

## 3. 前端：红色阴影渲染（设计优化）

- [x] 3.1 `Front/src/components/chan/palette.ts` 新增背驰阴影色字段（明暗两套半透明红），并验证：主题切换时 `getChanPalette()` 返回对应色值（console/unit 断言）
- [x] 3.2 `chan_bi.ts` `createPointFigures`：`isDivergence === true` 时在原 line 前垫一条更粗（约 4~5px）半透明红 line（虚笔时阴影线用实线），并验证：mock 末尾笔背驰时红晕可见、非背驰笔无变化、虚笔背驰 = 虚线 + 红阴影并存（人工验证 + 截图）
- [x] 3.3 `chan_seg.ts` 同款实现（垫线约 6~7px，2026-11-10 按用户要求收细为 6.5/4.5px），并验证同 3.2 场景在线段上成立
- [x] 3.4 MSW mock（`Front/src/mock/data/kline.ts`）给末尾 bi/seg 补 `is_divergence` 示例值（含 true 与 null 两形态），并验证：`cd Front && npm run dev` mock 模式下 K 线页正常渲染标注
- [x] 3.5 使用 /frontend-design 技能对红色阴影标注做视觉走查（颜色/线宽/透明度与暗色终端风格的协调性、与红涨蜡烛的区分度、明暗主题下的对比度），按走查结论微调 palette 取值并复验

## 4. 端到端集成验证

- [x] 4.1 真后端链路冒烟：启动 WebAPI（PG + DuckDB 就绪），请求 `/api/klines?symbol=sz.000001&period=1d`，确认响应 `bi[-1].is_divergence`/`seg[-1].is_divergence` 字段存在且类型合法；切换 `macd_algo` 保存并重算后字段口径随之变化；前端 `VITE_USE_MOCK=false` 打开 K 线页看到标注（人工验证，记录截图）

  > 结果：`/api/klines?symbol=sz.000001&period=1d`（8666 根，391 笔 / 59 段）返回 `bi[-1].is_divergence=false`、`seg[-1].is_divergence=true`，倒数第二个元素均**无该键**。把 `macd_algo` 由 `full_area` 改为 `area` 保存后重拉，`bi[-1]` 由 `false` 翻为 `true`（结构数不变），随后已恢复原配置并复验回 `false`。`VITE_USE_MOCK=false` + 真实后端打开 K 线页可见末段「蓝虚线芯 + 红色光晕」并存（未确认段 + 背驰标注，截图见 `C:\Windows\TEMP\kl_glow_5x.png`）。
- [x] 4.2 回归确认：`python Debug/bi_test.py` 与既有 `Debug/test_e2e_duckdb.py` 冒烟通过，证明内核零改动未被破坏

  > 结果：`bi_test.py` 全通过（3 笔）。`test_e2e_duckdb.py` 的 8 条实质检查（round-trip 逐根一致 + 笔/段/中枢/买卖点两源等价）全通过；仅末尾「产出非平凡（有笔/段/买卖点）」断言失败。已用 `git worktree` 检出**干净 HEAD** 跑同一测试，**同样失败**（合成 500 根数据只有 2 段 / 1 中枢 / 0 买卖点；真实 sz.000001 日线 2020+ 为 13 段 / 10 中枢 / 2 买卖点），证明该断言是既有 fixture 数据量不足导致、与本变更无关，非回归。

