# -*- coding: utf-8 -*-
"""
买卖点配置指纹 — 让「配置改了但输出没变」不可能发生

问题：
    `chan_snapshot`（快照续算）与 `chan_stable_prefix`（结果缓存）的键分别是
    `(code, kl_type, autype)` 与 `(code, kl_type)`，**都不含配置**。
    切换 `bsp_preset` 或任一买卖点开关后：

    - 缓存命中会直接返回旧 JSON，连计算都不发生；
    - 快照续算只重算未确认尾部，已确认前缀里的旧买卖点原样保留，
      导致新旧口径的点混在同一份 `bsp_index` 里。

    这是最难排查的故障形态，必须在数据层堵死。

做法：
    对「会影响买卖点结果的配置项」求稳定哈希，落库时一并写入；
    读取时比对，不一致即视为未命中 / 强制全量重算。

稳定性要求：
    - 不依赖字典插入顺序（按键排序）
    - 不依赖对象 id、时间戳、进程状态
    - 浮点用 `repr` 而非 `str`（`float("inf")` 与 `0.9` 必须区分开）
"""

import hashlib
import json
from typing import Any, Dict, Iterable

# 影响买卖点结果的配置项清单。
# 新增买卖点相关配置时必须同步加入，否则指纹不会随其变化。
FINGERPRINT_KEYS: Iterable[str] = (
    "bsp_preset",
    "divergence_rate",
    "min_zs_cnt",
    "bsp1_only_multibi_zs",
    "max_bs2_rate",
    "macd_algo",
    "bs1_peak",
    "bs_type",
    "bsp2_follow_1",
    "bsp3_follow_1",
    "bsp3_peak",
    "bsp2s_follow_2",
    "max_bsp2s_lv",
    "strict_bsp3",
    "bsp3a_max_zs_cnt",
    "bsp1_trend",
    "bsp1_new_extreme",
    "bsp1_dif_div",
    "bsp1_zero_axis",
    "bsp1_trend_mode",
    "bsp1_new_extreme_mode",
    "bsp1_zs_extend_to_seg_end",
    "bsp2_retrace_zs",
    "bsp2s_require_zs",
    "bsp2s_rate_mode",
    "bsp3b_mode",
    "bsp3_peak_on_breakout",
    "bsp3_follow_1_mode",
    "bsp1_downgrade_to_pz",
    "bsp1_force_scope",
    "bsp1_qjt",
    "bsp1_qjt_depth",
    "bsp3_confirm_window",
    "bsp3_confirm_level",
    "bsp3_time_axis_strong",
    "bsp3_time_axis_weak",
)

# 阶梯口径版本（chan-bsp-ladder-change D5；chan-standard-bsp2-change D6 bump）。
# 阶梯不是配置项（`FINGERPRINT_KEYS` 只收影响买卖点**成立性**的配置），
# 但阶梯的落库值同样只重算未确认尾部——口径改变后，已确认前缀里的旧阶梯值
# 会原样保留。这与「配置改了但输出没变」是同一类故障，必须同样用指纹堵死。
# 口径每变一次就 bump 这个常量一次，使全部快照失效、触发全量重算。
# bsp2-5axis-v1：T2/T2S 从 NULL 过渡接入五轴阶梯（P|S|C|K|T 语法）。
# bsp3-4axis-v1：T3A/T3B 从 NULL 过渡接入四轴阶梯（S|C|K|T 语法）。
LADDER_SCHEMA_VERSION = "bsp3-4axis-v1"


def _normalize(value: Any) -> Any:
    """把配置值规范化为可稳定 JSON 序列化的形式。"""
    if isinstance(value, float):
        # repr 保留 inf / -inf / nan 的区别，且不受精度格式化影响
        return repr(value)
    if hasattr(value, "name") and hasattr(value, "value"):
        # Enum：用名字而非 auto() 值，避免枚举成员顺序调整后指纹漂移
        return f"{type(value).__name__}.{value.name}"
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in sorted(value.items())}
    return value


def collect_config(conf) -> Dict[str, Any]:
    """从 `CChanConfig` 实例提取参与指纹的配置项。

    取买入侧配置（`bs_point_conf.b_conf`）——买卖两侧由同一份 `args` 构造，
    只有 `-buy` / `-sell` 后缀显式覆盖时才会不同。为覆盖该情形，
    卖出侧中被显式改变的值也一并纳入。
    """
    out: Dict[str, Any] = {}
    bsp_conf = getattr(conf, "bs_point_conf", None)
    if bsp_conf is None:
        return out
    for side_name, side in (("b", bsp_conf.b_conf), ("s", bsp_conf.s_conf)):
        for key in FINGERPRINT_KEYS:
            if not hasattr(side, key):
                continue
            val = _normalize(getattr(side, key))
            # 买侧全部收录；卖侧只收录与买侧不同的（即被 -sell 覆盖的项）
            if side_name == "b":
                out[key] = val
            else:
                b_key = out.get(key)
                if val != b_key:
                    out[f"{key}@sell"] = val
    # 线段级别配置独立于笔级别（历史上被硬编码为 slope），单独纳入
    seg_conf = getattr(conf, "seg_bs_point_conf", None)
    if seg_conf is not None:
        for key in ("macd_algo", "bsp1_only_multibi_zs"):
            if hasattr(seg_conf.b_conf, key):
                out[f"seg_{key}"] = _normalize(getattr(seg_conf.b_conf, key))
    return out


def config_fingerprint(conf) -> str:
    """计算配置指纹（16 位十六进制）。

    参数 `conf` 可以是 `CChanConfig` 实例，也可以是已由 `collect_config`
    提取的字典——后者用于在不持有配置对象的链路上（如只读查询）比对。

    **阶梯口径版本参与指纹**（`LADDER_SCHEMA_VERSION`）：阶梯重构后旧口径的
    落库值不可增量迁移，必须靠版本号变更让全部快照失效、走全量重算。
    """
    payload = conf if isinstance(conf, dict) else collect_config(conf)
    # 版本常量并入载荷（不改调用方签名）；键名带下划线前缀避免与配置键冲突
    payload = {**payload, "_ladder_schema": LADDER_SCHEMA_VERSION}
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
