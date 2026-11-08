# -*- coding: utf-8 -*-
"""缠论参数配置（chan-config-panel）全量单元/集成回归汇总。

一次跑完本次变更新增的全部验证脚本，便于改动后快速确认没有回归：

    .venv/Scripts/python.exe Debug/test_chan_config_all.py

各脚本也可单独运行。注意 `test_chan_config_sync.py` 与 `test_chan_config_e2e.py`
是**破坏性**的（会用当前配置重写整库 `bsp_index`），且都要求 PG 可用。
"""

import subprocess
import sys
import os

_DEBUG_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DEBUG_DIR)

# (脚本, 说明, 是否破坏性)
SCRIPTS = [
    ("test_chan_config_store.py", "配置存储读写 / 派生键 / inf 编解码 / None 校验", False),
    ("test_chan_config_meta.py", "57 项参数元数据 / 三条默认值基线", False),
    ("test_chan_config_pipeline.py", "单一出口 / 指纹分段 / 校验 / PG 降级", False),
    ("test_chan_config_api.py", "6 个端点（直调 router 函数）", False),
    ("test_chan_config_rollback.py", "回滚等价性（硬编码口径 vs build_conf）", False),
    ("test_chan_config_frontend_store.py", "前端草稿/档位/overrides 逻辑（esbuild + node）", False),
    ("test_chan_config_failure_isolation.py", "单键失败不阻断其余键", True),
    ("test_klstore_lock_retry.py", "DuckDB 跨平台锁冲突识别", False),
]


def main():
    only = sys.argv[1:] or None
    failed = []
    for name, desc, destructive in SCRIPTS:
        if only and not any(o in name for o in only):
            continue
        print(f"\n{'=' * 60}\n>>> {name} —— {desc}")
        if destructive:
            print("    （会写入 PG/DuckDB）")
        r = subprocess.run(
            [sys.executable, os.path.join(_DEBUG_DIR, name)],
            cwd=_ROOT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        if r.returncode != 0:
            failed.append(name)

    print(f"\n{'=' * 60}")
    if failed:
        print(f"失败脚本：{failed}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
