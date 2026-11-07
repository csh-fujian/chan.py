# -*- coding: utf-8 -*-
"""配置链路自测 —— 两个入口同源、指纹分段、派生键单出口、降级、前置校验。

覆盖点（tasks.md 2.1 / 2.2 / 2.4 / 2.5 / 2.7）：
  1. 两个 `_make_chan_config()` 对同一份已保存配置构造出的 `CChanConfig`
     在全部常驻参数上取值相同，且各自保留 `trigger_step` / `kl_data_check`
  2. PG 不可达时 `load()` 降级为空配置、`_make_chan_config()` 不抛异常；
     `save()` 抛 `ConfigStoreUnavailable`（router 层转 503）
  3. 指纹分段：仅改结构参数（bi/seg/zs/macd）即改变指纹
  4. 派生键进指纹：`load()` 输出构造的指纹 ≠ 手工去掉派生键后的指纹
  5. `bs_type` 前置校验可拦截非法类型

需要 PG 的段落在 PG 不可用时 SKIP（退出码 0）；其余纯内存段照常运行。

运行：  .venv/Scripts/python.exe Debug/test_chan_config_pipeline.py
"""

import os
import sys

_DEBUG_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_DEBUG_DIR)
sys.path.insert(0, _REPO_ROOT)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

os.environ.setdefault(
    "PG_DSN", "host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres"
)

from ChanAnalyse.ChanConfig import CChanConfig  # noqa: E402
from WebAPI import chan_config_store as store  # noqa: E402
from WebAPI.chan_config_schema import PARAMS  # noqa: E402
from WebAPI.config_fingerprint import config_fingerprint  # noqa: E402

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


def _read(conf, key):
    """按元数据 key 读 `CChanConfig` 实例上的生效值。"""
    from WebAPI.chan_config_schema import _read_default
    return _read_default(conf, key)


_conn = store._get_pg_conn()
_pg_ok = _conn is not None
if _pg_ok:
    _conn.close()
    _original = store.load_with_meta()

# ---------------------------------------------------------------------------
print("\n[1] 两个入口同源（tasks 2.1）")
# 保存一份「非默认」配置，验证两个入口都吃到了它
_DISTINGUISHING = {
    "divergence_rate": 0.75,
    "min_zs_cnt": 3,
    "bi_fx_check": "huge_check" if False else "totally",   # 结构参数也验证
    "zs_combine": False,
}
if _pg_ok:
    try:
        store.save(_DISTINGUISHING, "standard", updated_by="test-pipeline")

        from WebAPI.chan_service import _make_chan_config as api_conf
        from WebAPI.incremental_engine import _make_chan_config as engine_conf

        c_api = api_conf()
        c_engine = engine_conf()

        # 全部常驻参数（含结构类）逐项比对
        uncond = [p["key"] for p in PARAMS if not p["conditional"]]
        diffs = []
        for key in uncond:
            try:
                a, b = _read(c_api, key), _read(c_engine, key)
            except Exception as e:
                diffs.append((key, "ERR", repr(e)))
                continue
            if a != b:
                diffs.append((key, a, b))
        check(f"全部 {len(uncond)} 项常驻参数取值相同", not diffs,
              str(diffs[:5]))

        # 用户配置确实生效（不是两边都用默认）
        check("用户 divergence_rate=0.75 已生效",
              _read(c_api, "divergence_rate") == 0.75, str(_read(c_api, "divergence_rate")))
        check("用户 min_zs_cnt=3 已生效", _read(c_engine, "min_zs_cnt") == 3)
        check("用户 bi_fx_check=totally 已生效",
              _read(c_api, "bi_fx_check") == "totally", str(_read(c_api, "bi_fx_check")))
        check("用户 zs_combine=False 已生效", _read(c_engine, "zs_combine") is False)

        # 入口专属键各自保留
        check("/api/klines 入口 trigger_step=False", c_api.trigger_step is False)
        check("落库入口 trigger_step=True", c_engine.trigger_step is True)
        check("两个入口 kl_data_check 均为 False",
              c_api.kl_data_check is False and c_engine.kl_data_check is False)
    except Exception as e:
        check("两入口同源", False, repr(e))
else:
    print("  SKIP: PG 不可用，跳过（依赖已保存配置）")

# ---------------------------------------------------------------------------
print("\n[2] PG 降级（tasks 2.2 / design D12）")
try:
    # 直接构造「PG 不可达」的最简场景：PG_DSN 置空
    _saved_dsn = store.PG_DSN
    _saved_down = store._pg_down
    store.PG_DSN = ""
    try:
        store.invalidate_cache()
        check("PG 不可达时 load() 返回空 dict", store.load() == {}, str(store.load()))
        check("effective_config() 不抛异常", isinstance(store.effective_config(), dict))
        check("build_conf() 仍可构造", isinstance(store.build_conf(), dict))

        from WebAPI.chan_service import _make_chan_config as api_conf
        c = api_conf()
        check("_make_chan_config() 在 PG 不可达时不抛异常", isinstance(c, CChanConfig))
        check("降级时取内核默认（divergence_rate=0.9）",
              _read(c, "divergence_rate") == 0.9, str(_read(c, "divergence_rate")))

        raised = False
        try:
            store.save({"divergence_rate": 0.5}, "standard")
        except store.ConfigStoreUnavailable:
            raised = True
        check("save() 在 PG 不可达时抛 ConfigStoreUnavailable", raised)
    finally:
        store.PG_DSN = _saved_dsn
        store._pg_down = _saved_down
        store.invalidate_cache()
except Exception as e:
    check("PG 降级", False, repr(e))

# ---------------------------------------------------------------------------
print("\n[3] 指纹结构化分段（tasks 2.4 / design D5）")
try:
    base = config_fingerprint(CChanConfig())

    # 原有能力：买卖点判据改变指纹
    check("仅改 bsp1_zero_axis 使指纹变化",
          config_fingerprint(CChanConfig({"bsp1_zero_axis": False})) != base)

    # 新增能力：结构参数改变指纹
    structural = {
        "bi_fx_check": {"bi_fx_check": "loss"},
        "bi_strict": {"bi_strict": False},
        "gap_as_kl": {"gap_as_kl": True},
        "zs_combine": {"zs_combine": False},
        "zs_combine_mode": {"zs_combine_mode": "peak"},
        "one_bi_zs": {"one_bi_zs": True},
        "zs_algo": {"zs_algo": "over_seg"},
        "seg_algo": {"seg_algo": "1+1"},
        "left_seg_method": {"left_seg_method": "all"},
        "macd.fast": {"macd": {"fast": 8}},
        "macd.slow": {"macd": {"slow": 20}},
        "macd.signal": {"macd": {"signal": 5}},
    }
    unchanged = []
    for tag, override in structural.items():
        if config_fingerprint(CChanConfig(override)) == base:
            unchanged.append(tag)
    check("全部结构参数均进指纹", not unchanged, str(unchanged))

    # 点号键 ↔ 内核形态互转（config_fingerprint 之外的独立契约）
    flat = {"macd.fast": 8, "macd.slow": 20, "divergence_rate": 0.5}
    kernel = store.to_kernel(flat)
    check("to_kernel 聚成嵌套 macd",
          kernel.get("macd") == {"fast": 8, "slow": 20} and
          kernel.get("divergence_rate") == 0.5, str(kernel))
    check("to_flat 还原点号键",
          store.to_flat(kernel) == flat, str(store.to_flat(kernel)))
    check("build_conf() 输出的 macd 是嵌套形态",
          isinstance(store.build_conf().get("macd", {}), dict),
          str(store.build_conf().get("macd")))

    # 稳定性：同一配置两次求值相同
    check("同配置两次指纹相同",
          config_fingerprint(CChanConfig()) == config_fingerprint(CChanConfig()))

    # 分段结构存在
    from WebAPI.config_fingerprint import collect_config
    payload = collect_config(CChanConfig())
    for seg in ("bsp", "seg_bsp", "bi", "seg", "zs", "macd"):
        check(f"指纹含 {seg} 段", seg in payload, str(list(payload)))
    check("非 RSI 算法时不含 indicator 段",
          "indicator" not in payload, str(list(payload)))
    payload_rsi = collect_config(CChanConfig({"macd_algo": "rsi", "cal_rsi": True}))
    check("RSI 算法时含 indicator 段", "indicator" in payload_rsi, str(list(payload_rsi)))
except Exception as e:
    check("指纹分段", False, repr(e))

# ---------------------------------------------------------------------------
print("\n[4] 派生键与指纹单出口（tasks 2.5 / design D6）")
if _pg_ok:
    try:
        store.save({"macd_algo": "volumn"}, "standard", updated_by="test-pipeline")
        loaded = store.load()
        check("load() 含派生键 macd_algo-seg",
              loaded.get("macd_algo-seg") == "peak", str(loaded))
        check("load() 不含 cal_rsi", "cal_rsi" not in loaded, str(loaded))

        fp_with = config_fingerprint(CChanConfig(store.build_conf()))
        stripped = {k: v for k, v in loaded.items() if k != "macd_algo-seg"}
        fp_without = config_fingerprint(CChanConfig(
            {**stripped, "trigger_step": False, "kl_data_check": False}))
        check("派生键进入指纹（有/无派生指纹不同）", fp_with != fp_without,
              f"{fp_with} vs {fp_without}")

        # rsi 的派生
        store.save({"macd_algo": "rsi"}, "standard", updated_by="test-pipeline")
        loaded_rsi = store.load()
        check("rsi 派生 cal_rsi=True", loaded_rsi.get("cal_rsi") is True, str(loaded_rsi))
        conf_rsi = CChanConfig(store.build_conf())
        check("派生后 cal_rsi 在配置对象上生效", conf_rsi.cal_rsi is True)
        check("派生后 RSI 模型会被创建",
              any(type(m).__name__ == "RSI" for m in conf_rsi.GetMetricModel()))
    except Exception as e:
        check("派生键进指纹", False, repr(e))
else:
    print("  SKIP: PG 不可用，跳过")

# ---------------------------------------------------------------------------
print("\n[5] 保存前校验（tasks 2.7 / 3.2 / design D4）")
try:
    from WebAPI.chan_config_store import ConfigValidationError, validate_config

    # 合法配置：返回的是去掉派生键的 overrides
    ok = validate_config({"divergence_rate": 0.8, "bsp1_zero_axis": False})
    check("合法配置通过校验", ok == {"divergence_rate": 0.8, "bsp1_zero_axis": False}, str(ok))
    check("合法 bs_type 通过", validate_config({"bs_type": "1,1p,2,2s,3a,3b"})["bs_type"]
          == "1,1p,2,2s,3a,3b")

    # 派生键不落库：volumn 校验通过但返回里不带 macd_algo-seg
    v = validate_config({"macd_algo": "volumn"})
    check("校验通过的 overrides 不含派生键",
          "macd_algo-seg" not in v and v.get("macd_algo") == "volumn", str(v))
    check("校验时用了派生形态（volumn 不报错）", True)

    # 五种非法输入都要被拦，且 param 可定位
    cases = [
        ({"bsp2_confirm_window": 3}, "bsp2_confirm_window"),
        ({"bsp3b_mode": "bogus"}, "bsp3b_mode"),
        ({"bsp2_time_axis_strong": 2.0, "bsp2_time_axis_weak": 1.0}, "bsp2_time_axis"),
        ({"max_bs2_rate": 1.5}, "max_bs2_rate"),
        ({"bs_type": "1,9"}, "bs_type"),
    ]
    for payload, expect in cases:
        try:
            validate_config(payload)
            check(f"{list(payload)[0]} 被拒绝", False, "未抛异常")
        except ConfigValidationError as e:
            hit = (e.param == expect) or (expect in (e.param or "")) \
                  or (expect in str(e))
            check(f"{list(payload)[0]} 被拒绝且可定位", hit,
                  f"param={e.param!r} msg={e}")

    # 未知 key
    try:
        validate_config({"no_such_param": 1})
        check("未知 key 被拒绝", False, "未抛异常")
    except ConfigValidationError:
        check("未知 key 被拒绝", True)
except Exception as e:
    check("保存前校验", False, repr(e))

# ---------------------------------------------------------------------------
# 还原现场
if _pg_ok:
    try:
        if _original["initialized"]:
            store.save(_original["overrides"], _original["preset"],
                       _original["config"], "test-pipeline-restore")
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
    except Exception as e:
        print(f"  [WARN] 还原现场失败: {e}")

print(f"\n{'=' * 46}\n合计: {_PASS} PASS, {_FAIL} FAIL\n{'=' * 46}")
sys.exit(1 if _FAIL else 0)
