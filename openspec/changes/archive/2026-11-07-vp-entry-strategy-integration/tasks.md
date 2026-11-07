# Tasks: vp-entry-strategy-integration

## 1. 判定内核迁移

- [x] 1.1 迁移 `Debug/vp_entry/` 判定内核四文件（signal_rule/minute_trigger/vp_volume/params）至 `WebAPI/strategy_engines/vp_entry/`，内部 import 改同包相对导入，verify: `py_compile` 通过 + import 成功
- [x] 1.2 `VPParams.__post_init__` 的敏感性集合断言外移至 sensitivity.py 显式校验（vol_gate 取值域断言保留），verify: 迁移后 VPParams 接受连续区间取值（如 cv7_max=0.27）构造成功
- [x] 1.3 Debug/vp_entry 回测侧（backtest/sensitivity/run_backtest/prescreen_sql）与 test_vp_entry.py 的 import 改指新位置，verify: `.venv/Scripts/python Debug/test_vp_entry.py` 全部断言通过（回测零损失回归锚点）

## 2. 引擎与注册表

- [x] 2.1 新建 `WebAPI/strategy_engines/vp_entry/engine.py`：VpEntryEngine（scan/scan_with_params，全史日线重算 + 水位门 + B 日分钟懒加载/F 缓存 + SignalEvent→信号行转换 + payload 字段集），verify: 冒烟脚本对含 K_5M 与不含的两只股票分别产出分钟版/日线版信号
- [x] 2.2 B 日后状态追踪：重放推导 triggered→running/expired（expired 优先口径）+ 事件 payload 补充 b_high，verify: 冒烟构造历史数据断言三种终态各出现
- [x] 2.3 注册 vp_entry 定义（params_schema 五参数含 desc 与连续区间/states 三态/columns 私有列/detail_schema 四积木），verify: DEFINITIONS['vp_entry'] 声明完整、strategy_store 同步落库
- [x] 2.4 `validate_params` 支持 enum 类型（选项集校验 + 错误文案带合法值），verify: 合法 enum 值通过、非法值 422 文案含选项集

## 3. 任务体系接入

- [x] 3.1 detail API 的 kv 块数据：vp_entry 任务详情统计（总数/两版占比/spring 占比/三桶分布/平均影线盒宽/平均蓄势天数/平均 A 日涨幅/存活数）服务端聚合，verify: 冒烟对已知信号集断言统计值正确
- [x] 3.2 端到端冒烟：真 PG + DuckDB 跑 vp_entry 任务全生命周期（建任务→执行→信号落库含 payload/状态追踪→暂停/续跑→转正→详情 kv 正确→信号加监控走 strategy 来源回查），verify: Debug/strategy 冒烟脚本断言各环节
- [x] 3.3 vol_breakout 任务回归：既有策略在引擎注册表扩展后行为不变，verify: 重跑 Debug/strategy_task_smoke.py 全绿

## 4. 前端

- [x] 4.1 types + TaskDialog 支持 enum 参数（el-select 渲染 options），verify: `npm run build` 通过
- [x] 4.2 MSW mock 增加 vp_entry 定义（含 enum 参数样例）与任务/信号样例数据，verify: mock 模式创建 vp_entry 任务表单 enum 下拉正常、任务详情四积木渲染
