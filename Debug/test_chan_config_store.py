# -*- coding: utf-8 -*-
"""`WebAPI/chan_config_store` 冒烟自测 —— 单行表读写、版本缓存、Infinity 编解码、派生键。

覆盖点（tasks.md 1.1 / 2.3 / 2.5 / 3.3）：
  1. 惰性建表幂等
  2. save() 递增 version，load() 立即返回新值
  3. 进程内缓存：版本未变时不重复反序列化
  4. JSONB 不存 Infinity：legacy 档的 `divergence_rate=inf` 可往返
  5. 派生键：量能类补 `macd_algo-seg`、`rsi` 强制 `cal_rsi`，且不落库
  6. overrides / config 双列语义（design D3）

需要 PG（PG_DSN 或默认本地连接）。PG 不可用时整体 SKIP（退出码 0），
便于在无库环境跑其余单测。

运行：  .venv/Scripts/python.exe Debug/test_chan_config_store.py
"""

import os
import sys

_DEBUG_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_DEBUG_DIR)
sys.path.insert(0, _REPO_ROOT)

# 默认本地连接（与 Script/start_backend.sh 的默认值一致），便于开箱即跑
os.environ.setdefault("PG_DSN", "host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres")

from WebAPI import chan_config_store as store  # noqa: E402
from WebAPI.config import PG_DSN  # noqa: E402

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


# ---------------------------------------------------------------------------
# PG 可用性门（不可用则 SKIP，不算失败）
# ---------------------------------------------------------------------------
_conn = store._get_pg_conn()
if _conn is None:
    print(f"SKIP: PG 不可用（PG_DSN={PG_DSN!r}），本脚本需要 PostgreSQL")
    sys.exit(0)
_conn.close()

# 保存现场以便收尾还原（不污染开发库里的实际配置）
_original = store.load_with_meta()


def _restore():
    """还原测试前的配置；原先未初始化则清空表。"""
    try:
        if _original["initialized"]:
            store.save(_original["overrides"], _original["preset"],
                       _original["config"], "test-restore")
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
    except Exception as e:  # 还原失败只告警，不掩盖测试结论
        print(f"  [WARN] 还原现场失败: {e}")


print("\n[1] 惰性建表幂等")
try:
    store._ensure_tables()
    store._ensure_tables()
    check("重复 _ensure_tables() 不报错", True)
except Exception as e:
    check("重复 _ensure_tables() 不报错", False, repr(e))

print("\n[2] save/load 与版本递增")
try:
    v1 = store.save({"bsp_preset": "standard", "divergence_rate": 0.9}, "standard", updated_by="test")
    got1 = store.load()
    check("save 返回版本号", isinstance(v1, int) and v1 >= 1, f"v1={v1}")
    check("load 返回刚保存的值", got1.get("divergence_rate") == 0.9, str(got1))

    v2 = store.save({"bsp_preset": "standard", "divergence_rate": 0.7}, "standard", updated_by="test")
    check("第二次 save 版本递增", v2 == v1 + 1, f"{v1} -> {v2}")
    check("load 返回新值", store.load().get("divergence_rate") == 0.7)
except Exception as e:
    check("save/load 基本流程", False, repr(e))

print("\n[3] 进程内缓存：版本未变不重复反序列化")
try:
    calls = {"n": 0}
    _orig_decode = store._decode_value

    def _counting_decode(v):
        calls["n"] += 1
        return _orig_decode(v)

    store._decode_value = _counting_decode
    try:
        store.invalidate_cache()
        store.load()          # 首次：必须解码
        first = calls["n"]
        store.load()          # 第二次：版本未变，应命中缓存
        store.load()
        second = calls["n"]
    finally:
        store._decode_value = _orig_decode

    check("首次 load 触发解码", first >= 1, f"calls={first}")
    check("后续 load 不再解码", second == first, f"{first} -> {second}")
except Exception as e:
    check("缓存命中", False, repr(e))

print("\n[4] Infinity 往返（legacy 档 divergence_rate=inf）")
try:
    store.save({"bsp_preset": "legacy", "divergence_rate": float("inf")}, "legacy", updated_by="test")
    got = store.load()
    val = got.get("divergence_rate")
    check("inf 落库后读回仍是 inf", val == float("inf"), repr(val))
    check("inf 不是字符串", not isinstance(val, str), type(val).__name__)

    # 前端只能发字符串 "inf"（JSON 不接受非有限浮点）。校验必须接受它，
    # 且返回值要已解码成 float("inf") —— 否则落库后计算期 `"inf" <= 100` 会 TypeError。
    cleaned = store.validate_config({"divergence_rate": "inf"})
    check("校验接受字符串 \"inf\" 并解码为 float",
          cleaned.get("divergence_rate") == float("inf")
          and not isinstance(cleaned.get("divergence_rate"), str),
          repr(cleaned.get("divergence_rate")))

    # None 不能当「不限」：前端旧版把 Infinity 序列化成 null，内核能构造通过，
    # 但计算期 `None <= 100` 抛 TypeError —— 必须在保存前拦住。
    try:
        store.validate_config({"divergence_rate": None})
        check("divergence_rate=None 被拒绝", False, "校验放行了")
    except store.ConfigValidationError as e:
        check("divergence_rate=None 被拒绝", e.param == "divergence_rate", str(e))

    # 但内核默认就是 None 的参数（max_bsp2s_lv，语义「不限制」）必须放行
    try:
        cleaned = store.validate_config({"max_bsp2s_lv": None})
        check("max_bsp2s_lv=None 放行（内核默认可空）",
              cleaned.get("max_bsp2s_lv") is None, str(cleaned))
    except store.ConfigValidationError as e:
        check("max_bsp2s_lv=None 放行（内核默认可空）", False, str(e))
except Exception as e:
    check("Infinity 往返", False, repr(e))

print("\n[5] 派生键（D6）")
try:
    for algo in ("volumn", "amount", "volumn_avg", "amount_avg", "turnrate_avg"):
        store.save({"macd_algo": algo}, "standard", updated_by="test")
        loaded = store.load()
        check(f"{algo}: 自动补 macd_algo-seg=peak",
              loaded.get("macd_algo-seg") == "peak", str(loaded))
        check(f"{algo}: 用户原值未被改写",
              loaded.get("macd_algo") == algo, str(loaded))

    # 用户已显式配置 macd_algo-seg 时保留用户值
    store.save({"macd_algo": "volumn", "macd_algo-seg": "amp"}, "standard", updated_by="test")
    check("显式 macd_algo-seg 不被覆盖",
          store.load().get("macd_algo-seg") == "amp", str(store.load()))

    store.save({"macd_algo": "rsi", "cal_rsi": False}, "standard", updated_by="test")
    loaded = store.load()
    check("rsi: 强制 cal_rsi=True", loaded.get("cal_rsi") is True, str(loaded))
    check("rsi: macd_algo 原值不变", loaded.get("macd_algo") == "rsi", str(loaded))

    # 派生键不落库：切回 peak 后不应残留 cal_rsi / macd_algo-seg
    store.save({"macd_algo": "peak"}, "standard", updated_by="test")
    loaded = store.load()
    check("切回 peak 后无残留派生键",
          "macd_algo-seg" not in loaded and "cal_rsi" not in loaded, str(loaded))

    # 非特权算法不产生派生
    store.save({"macd_algo": "full_area"}, "standard", updated_by="test")
    check("full_area 无派生", "macd_algo-seg" not in store.load())

    # `load_with_meta()` 供 API 返回「用户显式改过哪些项」，派生键不属于用户改动。
    # 混进去会让前端把后端推导值当作用户覆盖原样回传（GET → PUT 往返污染）。
    store.save({"macd_algo": "volumn"}, "standard", updated_by="test")
    meta = store.load_with_meta()
    check("load_with_meta().overrides 不含派生键",
          "macd_algo-seg" not in meta["overrides"], str(meta["overrides"]))
    check("load_with_meta().overrides 保留用户原值",
          meta["overrides"].get("macd_algo") == "volumn", str(meta["overrides"]))
    check("load() 仍带派生键（计算出口）",
          store.load().get("macd_algo-seg") == "peak", str(store.load()))
except Exception as e:
    check("派生键", False, repr(e))

print("\n[6] overrides / config 双列语义（D3）")
try:
    # 全量快照与 overrides 不同：overrides 决定生效值
    store.save(
        overrides={"divergence_rate": 0.5},
        preset="standard",
        full_snapshot={"divergence_rate": 0.5, "min_zs_cnt": 3},
        updated_by="test",
    )
    meta = store.load_with_meta()
    check("load() 只返回 overrides（不含未覆盖项）",
          set(store.load()) == {"divergence_rate"}, str(store.load()))
    check("config 保留全量快照",
          meta["config"].get("min_zs_cnt") == 3, str(meta["config"]))
    check("overrides 与入参一致",
          meta["overrides"].get("divergence_rate") == 0.5, str(meta["overrides"]))
    check("preset 落库", meta["preset"] == "standard", meta["preset"])

    # 传入空 overrides：等价于「全部跟随预设」
    store.save({}, "legacy", full_snapshot={"divergence_rate": float("inf")},
               updated_by="test")
    check("空 overrides 时 load() 返回空 dict", store.load() == {}, str(store.load()))
    meta = store.load_with_meta()
    check("空 overrides 时 config 仍是全量快照",
          meta["config"].get("divergence_rate") == float("inf"), str(meta["config"]))
except Exception as e:
    check("overrides/config 双列", False, repr(e))

print("\n[7] 档位必须进入计算链路（load() 不带 bsp_preset，出口要补）")
try:
    # `bsp_preset` 存的是独立的 preset 列，不在 overrides 里（前端 computeOverrides()
    # 拿它与档位基线比，相等就不写 —— 它本来就不是「用户改过的项」）。
    # 若计算出口漏了回填，CChanConfig 只能看到硬编码默认 standard，
    # 用户切到 legacy 后一处判据都不会跟着变 —— 档位机制彻底失效。
    store.save({}, "legacy", updated_by="test")
    store.invalidate_cache()

    check("load() 仍不含 bsp_preset（保持 overrides 纯净）",
          "bsp_preset" not in store.load(), str(store.load()))
    check("load_preset() 读到 legacy", store.load_preset() == "legacy",
          store.load_preset())

    from ChanAnalyse.ChanConfig import CChanConfig
    b = CChanConfig(dict(store.build_conf())).bs_point_conf.b_conf
    check("build_conf 注入档位：min_zs_cnt=1", b.min_zs_cnt == 1, str(b.min_zs_cnt))
    check("build_conf 注入档位：divergence_rate=inf",
          b.divergence_rate == float("inf"), repr(b.divergence_rate))
    check("build_conf 注入档位：bsp1_trend=False",
          b.bsp1_trend is False, str(b.bsp1_trend))

    eff = CChanConfig(store.to_kernel(store.effective_config())).bs_point_conf.b_conf
    check("effective_config 同样注入档位", eff.min_zs_cnt == 1, str(eff.min_zs_cnt))

    # 显式覆盖优先于档位
    store.save({"min_zs_cnt": 3}, "legacy", updated_by="test")
    store.invalidate_cache()
    b2 = CChanConfig(dict(store.build_conf())).bs_point_conf.b_conf
    check("显式 overrides 压过档位（min_zs_cnt=3）", b2.min_zs_cnt == 3, str(b2.min_zs_cnt))
    check("未被覆盖的档位项仍生效（divergence_rate=inf）",
          b2.divergence_rate == float("inf"), repr(b2.divergence_rate))

    # 用户若在 overrides 里显式写 bsp_preset，以它为准
    store.save({"bsp_preset": "standard"}, "legacy", updated_by="test")
    store.invalidate_cache()
    b3 = CChanConfig(dict(store.build_conf())).bs_point_conf.b_conf
    check("overrides 里的 bsp_preset 优先于 preset 列", b3.min_zs_cnt == 2, str(b3.min_zs_cnt))
except Exception as e:
    check("档位进入计算链路", False, repr(e))

print("\n[8] preset 字段独立校验（不经过 validate_config）")
try:
    # 档位名以独立字段提交，绕过 overrides 的构造期校验。它现已真正进入
    # 计算链路，非法值落库会让**所有** K 线请求在内核构造处 500。
    check("standard 接受", store.validate_preset("standard") == "standard")
    check("legacy 接受", store.validate_preset("legacy") == "legacy")
    for bad in ("bogus", "", None, 123):
        try:
            store.validate_preset(bad)
            check(f"{bad!r} 被拒绝", False, "放行了")
        except store.ConfigValidationError as e:
            check(f"{bad!r} 被拒绝", e.param == "bsp_preset", str(e))
    # 合法清单以内核档位表为唯一真源，不复制
    from ChanAnalyse.ChanConfig import _BSP_PRESETS
    check("档位清单与内核同源",
          all(store.validate_preset(k) == k for k in _BSP_PRESETS), str(list(_BSP_PRESETS)))
except Exception as e:
    check("preset 校验", False, repr(e))

_restore()

print(f"\n{'=' * 46}\n合计: {_PASS} PASS, {_FAIL} FAIL\n{'=' * 46}")
sys.exit(1 if _FAIL else 0)
