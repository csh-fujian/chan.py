# -*- coding: utf-8 -*-
"""缠论参数元数据自测 —— 项数、白话解释质量、枚举取值与内核一致、受限取值说明。

覆盖点（tasks.md 1.3 / 1.4 / 1.5）：
  1. 项数与分组数（56 常驻 + 2 条件项）
  2. 每项 plain/effect/scope 非空且不含缠论专有术语
  3. 只影响标注的 8 项明确写「不影响买卖点数量」
  4. 结构类参数写明会改变结构
  5. 枚举型参数的 choices 全部被内核构造期接受；非法值被拒绝
  6. macd_algo 的 6 个受限取值带 caveat 说明
  7. 默认值随内核变化（反射读取，不是硬编码）

无需 PG / 网络 / DuckDB。

运行：  .venv/Scripts/python.exe Debug/test_chan_config_meta.py
"""

import os
import sys

_DEBUG_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_DEBUG_DIR)
sys.path.insert(0, _REPO_ROOT)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from ChanAnalyse.ChanConfig import CChanConfig  # noqa: E402
from WebAPI.chan_config_schema import (  # noqa: E402
    GROUP_BSP,
    GROUP_LADDER,
    GROUP_STRUCTURE,
    PARAMS,
    build_schema,
    probe_choice,
)

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


schema = build_schema()
by_key = {p["key"]: p for p in schema["params"]}

# ---------------------------------------------------------------------------
print("\n[1] 项数与分组")
try:
    # 56 常驻（含 chan-bsp1-strict-extreme 引入的 bs1_peak_strict）；
    # chan-bsp1-loose-extreme 删除 bs1_peak_strict 一项（-1）；
    # chan-config-bsp3-follow1-conditional 把 bsp3_follow_1_mode 改为条件项（-1 常驻 +1 条件）。
    # 故 55 常驻 + 3 条件（cal_rsi / rsi_cycle / bsp3_follow_1_mode）= 58 → 实际 57。
    check("总项数 = 57（54 常驻 + 3 条件）", schema["counts"]["total"] == 57,
          str(schema["counts"]))
    check("常驻项 = 54", schema["counts"]["unconditional"] == 54, str(schema["counts"]))
    check("条件项 = 3", schema["counts"]["conditional"] == 3, str(schema["counts"]))
    check("PARAMS 无重复 key", len({p["key"] for p in PARAMS}) == len(PARAMS))

    group_counts = {g["id"]: g["count"] for g in schema["groups"]}
    check("买卖点判据组 31 项", group_counts.get(GROUP_BSP) == 31, str(group_counts))
    check("证据阶梯组 8 项", group_counts.get(GROUP_LADDER) == 8, str(group_counts))
    check("结构算法组 15 项", group_counts.get(GROUP_STRUCTURE) == 15, str(group_counts))
    check("结构组默认折叠",
          next(g for g in schema["groups"] if g["id"] == GROUP_STRUCTURE)["collapsed_by_default"])
    check("判据组默认展开",
          not next(g for g in schema["groups"] if g["id"] == GROUP_BSP)["collapsed_by_default"])
except Exception as e:
    check("项数与分组", False, repr(e))

# ---------------------------------------------------------------------------
print("\n[2] 白话解释质量")
JARGON = ("特征序列", "线段破坏", "走势类型", "次级别", "盘整背驰的走势段窗口")
try:
    empty = [p["key"] for p in schema["params"]
             if not (p["plain"] or "").strip() or not (p["effect"] or "").strip()
             or not (p["scope"] or "").strip()]
    check("每项 plain/effect/scope 均非空", not empty, str(empty))

    # 术语只允许出现在说明性补充里；`plain` 与 `effect` 不得以术语为主体。
    # 这里做保守检查：`plain` 字段不出现术语清单里的词。
    bad = []
    for p in schema["params"]:
        for term in JARGON:
            if term in (p["plain"] or ""):
                bad.append((p["key"], term))
    check("plain 不含专有术语", not bad, str(bad[:5]))

    # 解释必须给出方向性结论（调大/调小/开启/关闭/选 等）
    DIRECTION_WORDS = ("调大", "调小", "开启", "关闭", "选", "勾", "填", "切换")
    no_direction = [p["key"] for p in schema["params"]
                    if not any(w in (p["effect"] or "") for w in DIRECTION_WORDS)]
    check("effect 均给出方向性结论", not no_direction, str(no_direction))
except Exception as e:
    check("白话解释质量", False, repr(e))

# ---------------------------------------------------------------------------
print("\n[3] 只影响标注的参数明确声明无害")
try:
    ladder = [p for p in schema["params"] if p["group"] == GROUP_LADDER]
    check("阶梯组 8 项", len(ladder) == 8, str(len(ladder)))
    undeclared = [p["key"] for p in ladder
                  if "不影响买卖点数量" not in (p["scope"] or "")
                  and "不会增减" not in (p["effect"] or "")]
    check("全部声明「不会增减买卖点」", not undeclared, str(undeclared))
    # bsp1_qjt 也是「特征不是判据」，必须同样声明
    qjt = by_key["bsp1_qjt"]
    check("bsp1_qjt 声明不影响数量",
          "不影响买卖点数量" in qjt["scope"] or "不会增减" in qjt["effect"], qjt["scope"])
    check("bsp1_qjt 带 caveat", bool(qjt["caveat"]), qjt["caveat"])
except Exception as e:
    check("标注类声明", False, repr(e))

# ---------------------------------------------------------------------------
print("\n[4] 结构类参数写明风险")
try:
    struct = [p for p in schema["params"]
              if p["group"] == GROUP_STRUCTURE and not p["conditional"]]
    check("结构组 15 项", len(struct) == 15, str(len(struct)))
    # 结构类的 effect 或 scope 必须提到「结构」或「笔/中枢」等载体
    KEYWORDS = ("结构", "笔", "中枢", "线段")
    weak = [p["key"] for p in struct
            if not any(k in (p["effect"] or "") + (p["scope"] or "") for k in KEYWORDS)]
    check("结构类均写明影响载体", not weak, str(weak))
    check("one_bi_zs 带高风险 caveat", "高风险" in by_key["one_bi_zs"]["caveat"],
          by_key["one_bi_zs"]["caveat"])
except Exception as e:
    check("结构类风险说明", False, repr(e))

# ---------------------------------------------------------------------------
print("\n[5] 枚举取值与内核构造期一致（tasks 1.4）")
try:
    # 对每个带 choices 的枚举型参数：候选池里的每个取值都必须被内核接受
    enum_params = [p for p in schema["params"]
                   if p["choices"] and p["control"] in ("select", "preset", "multi")]
    rejected = []
    for p in enum_params:
        for v in p["choices"]:
            if not probe_choice(p["key"], v):
                rejected.append((p["key"], v))
    check("候选取值全部被内核接受", not rejected, str(rejected))

    # 非法值必须被内核拒绝（证明 choices 不是「随便填都行」）
    bogus = {"bsp3b_mode": "bogus", "bsp1_force_scope": "bogus",
             "bsp2s_rate_mode": "bogus", "bsp1_trend_mode": "bogus",
             "bsp1_new_extreme_mode": "bogus", "bsp3_confirm_level": "bogus",
             "bsp2_confirm_level": "bogus"}
    not_rejected = [k for k, v in bogus.items() if probe_choice(k, v)]
    check("非法枚举被内核拒绝", not not_rejected, str(not_rejected))

    # 探测收敛：bsp1_new_extreme_mode 的 choices 必须等于内核实际接受的子集
    m = by_key["bsp1_new_extreme_mode"]
    all_candidates = ["trend_start", "prev_zs_in", "all", "level"]
    expected = [c for c in all_candidates if probe_choice("bsp1_new_extreme_mode", c)]
    check("bsp1_new_extreme_mode 选项经探测收敛", m["choices"] == expected,
          f"{m['choices']} vs {expected}")
    check("level 口径已可展示（并行变更已落地）", "level" in m["choices"], str(m["choices"]))
except Exception as e:
    check("枚举一致性", False, repr(e))

# ---------------------------------------------------------------------------
print("\n[6] 受限取值说明（tasks 1.5 / design D6）")
try:
    VOLUME_ALGOS = ("volumn", "amount", "volumn_avg", "amount_avg", "turnrate_avg")
    macd = by_key["macd_algo"]
    cav = macd.get("choice_caveats") or {}
    missing = [a for a in VOLUME_ALGOS if not cav.get(a)]
    check("5 个量能类取值带回退说明", not missing, str(missing))
    check("量能类说明提到线段级别回退",
          all("线段级别" in cav.get(a, "") for a in VOLUME_ALGOS),
          str({a: cav.get(a) for a in VOLUME_ALGOS}))
    check("rsi 取值带自动开启说明", "自动开启" in cav.get("rsi", ""), cav.get("rsi"))
    check("原生算法无额外说明",
          all(not cav.get(a) for a in ("peak", "area", "full_area", "diff", "diff_peak",
                                       "slope", "amp")),
          str(cav))
except Exception as e:
    check("受限取值说明", False, repr(e))

# ---------------------------------------------------------------------------
print("\n[7] 默认值反射（不硬编码）")
try:
    # 默认值必须等于直接构造 CChanConfig() 读到的值
    conf = CChanConfig()
    check("bsp_preset 默认 = standard", by_key["bsp_preset"]["default"] == "standard")
    check("min_zs_cnt 默认 = 2", by_key["min_zs_cnt"]["default"] == 2)
    check("bsp1_trend 默认 = True", by_key["bsp1_trend"]["default"] is True)
    check("bi_fx_check 默认 = strict（非 CBiConfig 签名的 half）",
          by_key["bi_fx_check"]["default"] == "strict", by_key["bi_fx_check"]["default"])
    check("zs_combine 默认 = True（属性名为 need_combine）",
          by_key["zs_combine"]["default"] is True)

    # 关键：默认值必须跟随内核。macd_algo 在 chan-bsp1-strict-extreme 中已从
    # peak 改为 full_area —— 硬编码会在这里失败。
    # 多选改造后元数据返回名称列表，内核侧比对也用列表形态。
    actual_default = [a.name.lower() for a in conf.bs_point_conf.b_conf.macd_algos]
    check("macd_algo 默认值跟随内核", by_key["macd_algo"]["default"] == actual_default,
          f"元数据={by_key['macd_algo']['default']} 内核={actual_default}")

    check("macd.fast 默认 = 12", by_key["macd.fast"]["default"] == 12)
    check("macd.slow 默认 = 26", by_key["macd.slow"]["default"] == 26)
    check("macd.signal 默认 = 9", by_key["macd.signal"]["default"] == 9)

    # bs_type 默认是列表
    check("bs_type 默认是列表且含 6 类",
          by_key["bs_type"]["default"] == ["1", "1p", "2", "2s", "3a", "3b"],
          str(by_key["bs_type"]["default"]))

    # legacy 档下默认值变化必须被反射到
    legacy = build_schema(CChanConfig({"bsp_preset": "legacy"}))
    legacy_by_key = {p["key"]: p for p in legacy["params"]}
    check("legacy 档 divergence_rate = inf",
          legacy_by_key["divergence_rate"]["default"] == float("inf"),
          repr(legacy_by_key["divergence_rate"]["default"]))
    check("legacy 档 min_zs_cnt = 1", legacy_by_key["min_zs_cnt"]["default"] == 1)
    check("legacy 档 bsp1_trend = False", legacy_by_key["bsp1_trend"]["default"] is False)
except Exception as e:
    check("默认值反射", False, repr(e))

# ---------------------------------------------------------------------------
print("\n[8] 条件项")
try:
    check("cal_rsi 是条件项", by_key["cal_rsi"]["conditional"] is True)
    check("rsi_cycle 是条件项", by_key["rsi_cycle"]["conditional"] is True)
    check("条件项在 macd_algo 选中 rsi 时可见",
          by_key["cal_rsi"]["visible_when"] == {"macd_algo": "rsi"},
          str(by_key["cal_rsi"]["visible_when"]))
    # 多选改造：macd_algo 的草稿值是数组，可见性判定必须按「包含」而非整串比较，
    # 否则 RSI 两项永久隐藏。元数据侧仍用单值声明，前端负责数组展开。
    check("macd_algo 是多选控件", by_key["macd_algo"]["control"] == "multi",
          by_key["macd_algo"]["control"])
    check("macd_algo 默认值是列表", isinstance(by_key["macd_algo"]["default"], list),
          str(type(by_key["macd_algo"]["default"])))
    # 三买查哪种一买 → 改名 + 与「三买必须跟在一买之后」联动
    mode = by_key["bsp3_follow_1_mode"]
    check("bsp3_follow_1_mode 已改名「一买类型」", mode["label"] == "一买类型", mode["label"])
    check("bsp3_follow_1_mode 是条件项", mode["conditional"] is True)
    check("bsp3_follow_1_mode 仅在 bsp3_follow_1 开启时可见",
          mode["visible_when"] == {"bsp3_follow_1": True}, str(mode["visible_when"]))
    check("预设清单含 standard/legacy",
          set(schema["presets"]) == {"standard", "legacy"}, str(schema["presets"]))
except Exception as e:
    check("条件项", False, repr(e))

# ---------------------------------------------------------------------------
print("\n[9] kernel_defaults 不随用户配置漂移")
try:
    # 场景：用户已保存 bsp1_zero_axis=False 与 bi_fx_check='loss' 两项覆盖。
    # params[].default 会跟着变成 False/'loss'（反映当前生效口径），
    # 但 kernel_defaults 必须仍是内核出厂值 True/'strict'。
    # 前端 computeOverrides() 用后者当基线 —— 用错会让已保存的覆盖项在下一次
    # 保存时被静默丢弃（改 A 存一次，再改 B 存一次，A 就没了）。
    overridden = build_schema(CChanConfig({
        "bsp1_zero_axis": False,
        "bi_fx_check": "loss",
    }))
    ov_by_key = {p["key"]: p for p in overridden["params"]}
    kd = overridden["kernel_defaults"]

    check("kernel_defaults 覆盖全部 57 项", len(kd) == 57, str(len(kd)))
    check("覆盖项被反射进 params[].default（当前口径）",
          ov_by_key["bsp1_zero_axis"]["default"] is False
          and ov_by_key["bi_fx_check"]["default"] == "loss",
          f"{ov_by_key['bsp1_zero_axis']['default']} / "
          f"{ov_by_key['bi_fx_check']['default']}")
    check("kernel_defaults 仍是内核出厂值（不受覆盖影响）",
          kd["bsp1_zero_axis"] is True and kd["bi_fx_check"] == "strict",
          f"{kd['bsp1_zero_axis']} / {kd['bi_fx_check']}")
    check("两者在覆盖项上确实不同（防止断言退化成恒真）",
          ov_by_key["bsp1_zero_axis"]["default"] != kd["bsp1_zero_axis"]
          and ov_by_key["bi_fx_check"]["default"] != kd["bi_fx_check"])
    check("未覆盖项两者一致",
          ov_by_key["min_zs_cnt"]["default"] == kd["min_zs_cnt"] == 2)

    # 终局保障：无覆盖时 kernel_defaults 与 params[].default 应逐项相等
    drift = [
        p["key"] for p in schema["params"]
        if repr(p["default"]) != repr(schema["kernel_defaults"][p["key"]])
    ]
    check("默认配置下 kernel_defaults 与 params[].default 一致",
          not drift, str(drift[:5]))
except Exception as e:
    check("kernel_defaults 语义", False, repr(e))

# ---------------------------------------------------------------------------
print("\n[10] preset_baselines：档位展开后的基线")
try:
    pb = schema["preset_baselines"]
    check("覆盖全部档位", set(pb) == {"standard", "legacy"}, str(set(pb)))
    check("每档覆盖全部 57 项",
          all(len(v) == 57 for v in pb.values()), str({k: len(v) for k, v in pb.items()}))
    check("standard 基线 = kernel_defaults", pb["standard"] == schema["kernel_defaults"])

    # legacy 档的预设展开必须体现在基线上 —— 这正是不能用 kernel_defaults
    # 当覆盖基线的理由：否则这十几项会被误判成用户覆盖写死进 overrides。
    legacy_base = pb["legacy"]
    check("legacy 基线含预设展开值（min_zs_cnt=1 / bsp1_trend=False / macd_algo=[peak]）",
          legacy_base["min_zs_cnt"] == 1
          and legacy_base["bsp1_trend"] is False
          and legacy_base["macd_algo"] == ["peak"],
          f"{legacy_base['min_zs_cnt']} / {legacy_base['bsp1_trend']} / "
          f"{legacy_base['macd_algo']}")
    check("legacy 与 standard 基线确有多项不同",
          sum(1 for k in legacy_base if repr(legacy_base[k]) != repr(pb["standard"][k])) >= 10,
          str(sum(1 for k in legacy_base
                  if repr(legacy_base[k]) != repr(pb["standard"][k]))))
    check("legacy 基线自带 bsp_preset=legacy", legacy_base["bsp_preset"] == "legacy")
except Exception as e:
    check("preset_baselines", False, repr(e))

print(f"\n{'=' * 46}\n合计: {_PASS} PASS, {_FAIL} FAIL\n{'=' * 46}")
sys.exit(1 if _FAIL else 0)
