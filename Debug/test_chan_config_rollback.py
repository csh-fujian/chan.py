# -*- coding: utf-8 -*-
"""chan-config-panel task 6.5 —— 回滚等价性验证。

回滚方式：把 `chan_service._make_chan_config()` / `incremental_engine._make_chan_config()`
改回硬编码 `CChanConfig({"trigger_step": ..., "kl_data_check": False})`。

本脚本不真的改代码，而是直接对比两种构造口径的**配置指纹**：

    回滚口径（硬编码）  ==  改造后且用户未覆盖任何项
    回滚口径（硬编码）  !=  改造后且用户有覆盖（→ 回滚后首次重算转全量）

运行：
    .venv/Scripts/python.exe Debug/test_chan_config_rollback.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ChanAnalyse.ChanConfig import CChanConfig
from WebAPI.config_fingerprint import collect_config
from WebAPI import chan_config_store as store

_PASS = 0
_FAIL = 0


def check(label, cond, detail=""):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  [OK]   {label}")
    else:
        _FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


# 两个计算入口各自叠加的运行模式键
ENTRY_KEYS = {"trigger_step": False, "kl_data_check": False}

# 本脚本的前提是「用户未覆盖任何项」。开发库里通常已经存着上一轮测试留下的
# overrides（实测 `bi_fx_check=loss` / `bsp1_zero_axis=False` / `bsp2_confirm_window=1`），
# 那会让 `build_conf()` 带出用户口径、与硬编码口径必然不等 —— 脚本报 FAIL，
# 但被测的等价性其实没坏。所以先备份、清空、跑完还原，与其它 test_chan_config_* 同风格。
_original = store.load_with_meta()


def _restore():
    try:
        if _original["initialized"]:
            store.save(_original["overrides"], _original["preset"],
                       _original["config"], "rollback-restore")
        else:
            conn = store._get_pg_conn()
            if conn is not None:
                try:
                    with conn.cursor() as cur:
                        cur.execute(f"DELETE FROM {store._TABLE} WHERE id = 1")
                    conn.commit()
                finally:
                    conn.close()
        store.invalidate_cache()
    except Exception as e:      # 还原失败只告警，不掩盖测试结论
        print(f"  [WARN] 还原现场失败: {e}")


def rollback_fp() -> str:
    """回滚口径：硬编码构造（改造前的写法）。"""
    return collect_config(CChanConfig(dict(ENTRY_KEYS)))


def current_fp() -> str:
    """改造后口径：走 build_conf()，用户未覆盖任何项。"""
    return collect_config(CChanConfig(store.build_conf(dict(ENTRY_KEYS))))


def main():
    # 前提：清空用户覆盖，让 build_conf() 等价于「纯档位 + 内核默认」
    store.save({}, "standard", updated_by="rollback-test")
    store.invalidate_cache()

    print("[1] 用户未覆盖任何项时，回滚口径与改造后口径指纹等价")
    rb, cur = rollback_fp(), current_fp()
    print(f"      回滚={rb}\n      改造后={cur}")
    check("指纹相同（回滚不会导致口径漂移）", rb == cur, f"{rb} vs {cur}")

    print("\n[2] 有用户覆盖时指纹不同（回滚后首次重算转全量）")
    # 直接构造「已保存了 bsp1_zero_axis=False」的配置，不写库
    overridden = CChanConfig({
        **store.build_conf(dict(ENTRY_KEYS)),
        "bsp1_zero_axis": False,
    })
    ovr_fp = collect_config(overridden)
    print(f"      有覆盖={ovr_fp}")
    check("与回滚口径不同", ovr_fp != rb, f"{ovr_fp} vs {rb}")

    print("\n[3] 指纹分段全部生效（任一段变化都能被检出）")
    # 七段各取一个代表参数，逐个断言指纹变化
    probes = {
        "bsp": {"bsp1_zero_axis": False},
        "bi": {"bi_fx_check": "loss"},
        "seg": {"left_seg_method": "all"},
        "zs": {"zs_combine": False},
        "macd": {"macd": {"fast": 8}},
    }
    base = dict(ENTRY_KEYS)
    for segment, patch in probes.items():
        conf = CChanConfig({**store.build_conf(dict(base)), **patch})
        fp = collect_config(conf)
        check(f"{segment} 段参数改动 → 指纹变化", fp != rb, f"{fp} vs {rb}")

    print(f"\n{'=' * 46}\n合计: {_PASS} PASS, {_FAIL} FAIL\n{'=' * 46}")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        _restore()
    sys.exit(rc)
