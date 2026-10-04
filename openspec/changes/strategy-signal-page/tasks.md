# Tasks: strategy-signal-page

## 1. PG 存储层（strategy_store）

- [x] 1.1 新建 `WebAPI/strategy_store.py`：惰性建表 strategy / strategy_instance / strategy_signal / strategy_scan_cursor（CREATE TABLE IF NOT EXISTS，风格对齐 bsp_store.py），验证：模块导入无错、首次调用建表后 PG 中四表存在且列结构符合 design D1
- [x] 1.2 实现实例 CRUD：create_instance（params 按 params_schema 校验，非法值抛错）、list_instances、set_enabled、delete_instance（级联删信号）；验证：手动脚本对非法参数（回调天数 0）断言拒绝、删除实例后 strategy_signal 无残留
- [x] 1.3 实现信号 upsert：`ON CONFLICT (instance_id, code, signal_date) DO UPDATE ... WHERE strategy_signal.frozen = FALSE`（design D8 冻结跳过）+ frozen 置位接口；验证：脚本对同一事件重复 upsert 幂等、frozen 行不被更新
- [x] 1.4 实现信号查询：按实例分页 + 状态/方向/日期范围筛选，返回行含 payload 解包与 stock 名称/行业联查；侧栏计数接口（按实例统计）；验证：查询脚本覆盖筛选组合与分页字段（list/total/page/page_size）

## 2. 策略引擎层

- [x] 2.1 新建 `WebAPI/strategy_engines/__init__.py` 定义 `StrategyEngine` 协议（scan(keys, watermark) -> SignalEvent[]）与策略定义注册表（代码注册 definition：id/name/group/engine/params_schema/states/columns），注册首个定义 `vol_breakout_pullback`（回调天数上限默认5、放量倍数默认2.0，states：watching/triggered/expired/running，columns：首板日/回调天数/量比）；验证：注册表可被 store 消费、params_schema 校验逻辑单测通过
- [x] 2.2 实现 `VolBreakoutPullbackEngine.scan`：读 DuckDB 日线（复用 KLineStore 读取路径，不触碰 CChan），按参数识别放量首板 → 回调窗口 → 触发/失效/启动状态演进，产出 SignalEvent（含 entry_ref_price/stop_ref_price/payload）；验证：Debug 冒烟脚本对构造 K 线序列断言各状态产出正确（触发、超期失效、重复扫描幂等）
- [x] 2.3 实现水位调度：strategy_scan_cursor 读写 + `scan_instance(instance_id, batch)`（全量回算 = 水位归零扫全史，增量 = 水位续扫）；验证：脚本建实例触发全量回算后水位前移，二次调用只扫增量无重复信号

## 3. 后端 API 与调度接入

- [x] 3.1 新建 `WebAPI/routers/strategy.py`：GET /api/strategy/definitions（含实例树+计数）、POST/DELETE /api/strategy/instances、PATCH /instances/{id}/enabled、POST /instances/{id}/scan（BackgroundTasks 异步补算）、GET /api/strategy/signals（分页筛选）；挂载到 app.py；验证：uvicorn 启动后 curl 各端点返回契约字段
- [x] 3.2 app.py EOD loop 追加策略扫描阶段（BSP_EOD_AT 之后顺序执行、独立 try/except，`STRATEGY_SCAN_ENABLED` 环境变量开关默认开）；验证：日志确认策略阶段执行且失败不影响 bsp 阶段
- [x] 3.3 monitor 表 ALTER 加 source_type/instance_id/signal_date（DEFAULT 'chan'，strategy_store 或 monitor_store 惰性执行）；`POST /api/monitor` body 接受来源字段（缺省 'chan'）；验证：旧调用不传字段行为不变，新调用写入 strategy 来源

## 4. monitor 下游分叉

- [x] 4.1 `_fill_bsp_context` 按 source 分叉：strategy 来源按 (instance_id, signal_date) 查 strategy_signal 填充上下文（state/is_buy/entry_ref_price），查不到兜底同现状；验证：脚本构造两来源监控条目，断言 chan 走 bsp_index 路径、strategy 走 strategy_signal 路径
- [x] 4.2 加监控成功与 frozen 置位同事务（design D8）；验证：加监控后信号 state 不再被引擎更新（回归断言 spec「状态冻结边界」场景）
- [x] 4.3 策略来源监控不触发卖点自动卖出（仅 chan 维持现状）；预警/绩效 stub API 契约预留 source/instance_id 参数（接受不报错）；验证：路由 OpenAPI schema 含预留字段、strategy 条目结算不回写 strategy_signal（spec「监控事件不回写信号」断言）

## 5. 前端：策略信号页

- [x] 5.1 类型与 API 层：`Front/src/api/types.ts` 增 StrategyDefinition/StrategyInstance/StrategySignalRow（与 screener 的 Strategy 明确分离），`api/modules/strategy.ts` 封装全部端点；验证：vue-tsc 编译通过
- [x] 5.2 MSW mock：`mock/handlers/strategy.ts`（2 个策略定义 × 各 1-2 实例 × 各状态信号若干），注册进 mock/browser 与 handlers/index；验证：mock 下页面接口全部返回数据
- [x] 5.3 路由与权限：`/strategy` 路由 + `menu:strategy` 权限项（admin 默认授予），顶导菜单项「策略信号」置于「买卖点」之后；验证：admin 登录可见可进，无权限角色不可见
- [x] 5.4 页面骨架：`views/strategy/StrategySignalView.vue` 侧栏策略树（定义分组→实例节点+计数，切换实例）+ 工具栏（股票搜索/状态/方向/日期范围）+ 服务端分页信号列表（通用列 + columns 声明驱动私有列 + states 声明驱动状态着色）；验证：切换实例列表与私有列随之变化、筛选翻页请求参数正确（Network 面板）
- [x] 5.5 实例管理弹窗：InstanceDialog 按 params_schema 动态渲染表单（新建校验/启停/删除确认）；验证：非法参数前端拦截、新建后侧栏出现实例
- [x] 5.6 信号详情抽屉 + 加入监控：抽屉展示 K 线与信号标注（按 KLineChart overlay 能力选简单标记），「加入监控」调 POST /api/monitor 携带 source_type/instance_id/signal_date；验证：mock 下监控列表出现策略来源条目

## 6. monitor 前端来源标签

- [x] 6.1 monitor 页列表加来源标签列（chan 显示买卖点类型语义、strategy 显示「策略名 · 实例名 · 状态」），其余列布局不变；验证：mock 两来源条目标签正确渲染、列布局回归无破坏

## 7. 端到端验证

- [x] 7.1 后端端到端：对已灌数的 sz.000001 建 vol_breakout_pullback 实例 → 全量回算 → 查询信号 → 加监控 → 断言监控上下文来自 strategy_signal 且信号冻结；脚本落在 Debug/ 下（风格对齐 test_e2e_duckdb.py）
- [x] 7.2 前端构建回归：`npm run build`（vue-tsc + vite）通过；`VITE_USE_MOCK=false` 下页面降级行为不崩溃
- [x] 7.3 openspec 校验：`openspec validate strategy-signal-page` 通过，任务全部勾选后 status 为 complete
