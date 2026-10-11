# -*- coding: utf-8 -*-
"""
量价三段式买点判定内核包（vp-entry-strategy-integration design D1 迁移自
Debug/vp_entry/，原文件原样搬移，仅改内部 import 为同包相对导入）。

- params.py        参数三层 dataclass（定死/扫描/总表）
- signal_rule.py   日线流式状态机（VPStateMachine）与 SignalEvent
- minute_trigger.py B 日分钟级触发扫描
- vp_volume.py     F(t) 分时量能分布与虚拟全天量 VP(t)
- engine.py        VpEntryEngine 策略引擎适配层（实现 StrategyEngine 协议）

判定逻辑零改动：回测侧（Debug/vp_entry 的 backtest/sensitivity/run_backtest/
prescreen_sql）从本包 import，回测行为零损失（Debug/test_vp_entry.py 为
回归锚点）。
"""

from .params import FixedParams, ScanParams, VPParams  # noqa: F401
from .signal_rule import (  # noqa: F401
    BCandidateEvent,
    DayBar,
    SignalEvent,
    VPState,
    VPStateMachine,
)

__all__ = [
    "FixedParams",
    "ScanParams",
    "VPParams",
    "BCandidateEvent",
    "DayBar",
    "SignalEvent",
    "VPState",
    "VPStateMachine",
]
