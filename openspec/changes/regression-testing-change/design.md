# Design

（占位）回归测试变更的技术设计。具体的技术选型、架构决策与风险权衡由后续 explore 流程调研后补充填充。

## Context

本变更为占位变更（见 proposal.md），当前仓库现状供后续 explore 参考：

- 测试以 `Debug/` 下手动脚本为主（无 pytest）：`bi_test.py`（笔识别，内存构造，离线）、`test_e2e_duckdb.py`（DuckDB round-trip，离线）、`test_baostock_vs_duckdb.py`（真网络）、`bsp_engine_regression.py`（补算引擎幂等语义，需 PG + DuckDB）、`test_intraday_poll.py`、`monitor_group_smoke.py`、`strategy_signal_smoke.py` 等。
- 已归档/进行中的 openspec 变更约定不修改 `CChan` 计算核心逻辑。

## Goals / Non-Goals

（待补充）

## Decisions

（待补充）

## Risks / Trade-offs

（待补充）

## Migration Plan

（待补充）
