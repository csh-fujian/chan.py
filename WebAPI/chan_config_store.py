# -*- coding: utf-8 -*-
"""
缠论参数配置存储 — `chan_config` 单行表的读写与进程内缓存。

设计要点（design.md D1/D3/D6/D12）：
- 单行表（id 固定 1）存全量配置快照 + 档位预设名 + 单调递增版本号。
  单行便于指纹取全量稳定哈希，也避免 55 行部分更新的中间态。
- `load()` 缓存 `(version, config)`，每次先查 `version`（主键单行查询，微秒级），
  版本变化才重读整行。多 worker 下天然一致。
- **PG 不可用降级**：`load()` 返回空配置（等价内核默认）并记 warning，
  保证 `/api/klines` 不因配置存储故障而失败（沿用 main.py 记录的失败开放取向）。
  写入路径不降级 —— 内存里记一份会与下次读取打架。
- **JSONB 不存 Infinity**：`divergence_rate` 在 legacy 档为 `float("inf")`，
  而 PostgreSQL 的 jsonb 只接受标准 JSON。编码时把 inf 写成字符串 `"inf"`，
  解码时还原为 `float("inf")`。若原样写入会得到 `invalid input syntax for type json`。

本模块只负责「用户配置」的存取；「生效值」= 内核默认 + 用户配置的合并由
`effective_config()` 提供（供 API 与元数据接口共用）。
"""

import json
import logging
import math
import re
from typing import Any, Optional

import psycopg2

from .config import PG_DSN
from .config_fingerprint import FINGERPRINT_KEYS  # noqa: F401  （供上层复用键清单）

log = logging.getLogger("chan_config_store")

# PG 连接失败降级状态（仅状态翻转时记一次日志，防止每个请求刷屏）
_pg_down = False

# 进程内缓存：版本号未变则不再反序列化 JSONB
_cached_version: Optional[int] = None
_cached_config: Optional[dict] = None
_cached_preset: Optional[str] = None

# 「None 是合法取值」的配置项缓存（见 `_nullable_keys()`）
_NULLABLE_CACHE: Optional[frozenset] = None

_TABLE = "chan_config"
_SYNC_TABLE = "chan_config_sync_job"

# 力度算法的量能类取值：`CSeg.cal_macd_metric` 没有对应分支（Seg.py:278 抛异常），
# 只能用现有的 `macd_algo-seg` 后缀覆盖绕行。实测 `{"macd_algo": "volumn",
# "macd_algo-seg": "peak"}` 可正常完成整条计算链路。
VOLUME_MACD_ALGOS = frozenset({
    "volumn", "amount", "volumn_avg", "amount_avg", "turnrate_avg",
})

# 量能类取值在线段级别使用的回退算法（线段级别的传统口径）
SEG_FALLBACK_MACD_ALGO = "peak"

# 点号键 ↔ 内核嵌套字典的桥接。
#
# 元数据（前端控件）用点号表达嵌套项（`macd.fast`），内核 `CChanConfig` 要的是
# `{"macd": {"fast": 12, "slow": 26, "signal": 9}}`。数据库存**点号形式**
# （与元数据同一命名空间，前端收发无需转换），只在计算入口 `build_conf()`
# 转成内核形态 —— 转换点唯一，不会出现「存的和算的不是一份」。
_DOTTED_KEYS = {
    "macd.fast": ("macd", "fast"),
    "macd.slow": ("macd", "slow"),
    "macd.signal": ("macd", "signal"),
}


def to_kernel(config: dict) -> dict:
    """点号键 → 内核形态（`macd.fast` → `{"macd": {"fast": ...}}`）。

    嵌套字典按需创建并合并；不含点号键时原样返回副本。
    """
    out: dict = {}
    nested: dict = {}
    for key, value in config.items():
        path = _DOTTED_KEYS.get(key)
        if path is None:
            out[key] = value
        else:
            head, tail = path
            nested.setdefault(head, {})[tail] = value
    out.update(nested)
    return out


def to_flat(config: dict) -> dict:
    """内核形态 → 点号键（`{"macd": {...}}` → `macd.fast` 三项）。

    `macd` 字典里未出现在 `_DOTTED_KEYS` 中的子键会被丢弃（内核只认三项）。
    其它键原样保留。
    """
    out: dict = {}
    for key, value in config.items():
        if key == "macd" and isinstance(value, dict):
            for sub, v in value.items():
                flat = f"macd.{sub}"
                if flat in _DOTTED_KEYS:
                    out[flat] = v
        else:
            out[key] = value
    return out


def _get_pg_conn():
    """获取 PG 连接；PG_DSN 未配置或不可达时返回 None（调用方决定降级或报错）。"""
    global _pg_down
    if not PG_DSN:
        return None
    try:
        conn = psycopg2.connect(PG_DSN)
    except psycopg2.OperationalError as e:
        if not _pg_down:
            log.warning("PG 不可达，配置读取降级为内核默认、写入将被拒绝: %s", e)
            _pg_down = True
        return None
    if _pg_down:
        log.info("PG 连接已恢复")
        _pg_down = False
    return conn


def _ensure_tables() -> None:
    """惰性建表（CREATE TABLE IF NOT EXISTS）。

    与 `bsp_store` / `system_store` 同风格：模块导入时执行一次，是真正的 schema 契约；
    `update-win.sql` / `update-mac.sql` 只作变更记录。
    """
    conn = _get_pg_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_TABLE} (
                    id          SMALLINT PRIMARY KEY DEFAULT 1,
                    config      JSONB NOT NULL DEFAULT '{{}}',
                    overrides   JSONB NOT NULL DEFAULT '{{}}',
                    preset      VARCHAR NOT NULL DEFAULT 'standard',
                    version     BIGINT NOT NULL DEFAULT 1,
                    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_by  VARCHAR,
                    CONSTRAINT chk_{_TABLE}_singleton CHECK (id = 1)
                )
                """
            )
            # overrides 列（design D3）：只存用户显式改过的键，是生效语义的来源；
            # config 列存全量快照，仅供展示与审计。幂等补列（旧库升级）。
            cur.execute(
                f"ALTER TABLE {_TABLE} ADD COLUMN IF NOT EXISTS "
                f"overrides JSONB NOT NULL DEFAULT '{{}}'"
            )
            # 批量同步任务表（design D8）：进程重启后进度仍可查，且记录
            # 启动时的配置版本以判定「结果是否已过期」。
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_SYNC_TABLE} (
                    id              SERIAL PRIMARY KEY,
                    config_version  BIGINT,
                    status          VARCHAR NOT NULL DEFAULT 'running',
                    total           INT NOT NULL DEFAULT 0,
                    done            INT NOT NULL DEFAULT 0,
                    failed          INT NOT NULL DEFAULT 0,
                    summary         JSONB,
                    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    finished_at     TIMESTAMPTZ,
                    CONSTRAINT chk_{_SYNC_TABLE}_status
                        CHECK (status IN ('running', 'interrupted', 'done', 'failed'))
                )
                """
            )
        conn.commit()
    finally:
        conn.close()


# ----------------------------------------------------------------------
# JSONB 编解码（Infinity 处理）
# ----------------------------------------------------------------------

def _encode_value(v: Any) -> Any:
    """把 Python 值编码为标准 JSON 可表示的形式（inf → "inf"）。"""
    if isinstance(v, float):
        if math.isinf(v):
            return "inf" if v > 0 else "-inf"
        if math.isnan(v):
            return None
        return v
    if isinstance(v, dict):
        return {k: _encode_value(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_encode_value(x) for x in v]
    return v


def _decode_value(v: Any) -> Any:
    """把存储值还原为内核可消费的形式（"inf" → float("inf")）。"""
    if isinstance(v, str):
        if v == "inf":
            return float("inf")
        if v == "-inf":
            return float("-inf")
        return v
    if isinstance(v, dict):
        return {k: _decode_value(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_decode_value(x) for x in v]
    return v


def encode_config(config: dict) -> dict:
    """对外暴露的编码入口（测试与 router 复用）。"""
    return _encode_value(config)


def decode_config(config: dict) -> dict:
    """对外暴露的解码入口（测试与 router 复用）。"""
    return _decode_value(config)


# ----------------------------------------------------------------------
# 派生键（design D6）
# ----------------------------------------------------------------------

def apply_derived(config: dict) -> dict:
    """按用户选定的 `macd_algo` 补充派生键，返回新 dict（不改入参）。

    - 量能类取值：`CSeg.cal_macd_metric` 无分支，补 `macd_algo-seg` 回退
      （用户已显式配置 `macd_algo-seg` 时保留用户值）
    - `rsi`：力度算法读 `klu.rsi`，该字段仅 `cal_rsi=True` 时由指标模型写入，
      因此强制开启（用户显式关闭也不生效 —— 否则计算必然 AttributeError）

    派生只发生在读取出口，用户存储中的 `macd_algo` 原值永不被改写。
    """
    out = dict(config)
    algo = out.get("macd_algo")
    if algo in VOLUME_MACD_ALGOS:
        out.setdefault("macd_algo-seg", SEG_FALLBACK_MACD_ALGO)
    elif algo == "rsi":
        out["cal_rsi"] = True
    return out


def _strip_derived(config: dict) -> dict:
    """落库前清理派生键与失效键。

    规则：
    - `macd_algo-seg` 只在 `macd_algo` 为量能类时有意义（其余算法线段级别有原生实现，
      残留的 `-seg` 覆盖会静默改变线段级别口径）。量能类下用户显式配置的值**保留** ——
      它是专家可选项，`apply_derived()` 用 `setdefault` 不会覆盖。
    - `rsi` 场景下 `cal_rsi` 由派生强制开启，不落库 —— 否则「用户没配」与「用户配了」
      无法区分，切回其它算法后残留的 `cal_rsi=True` 会污染指纹。
    """
    out = dict(config)
    if out.get("macd_algo") not in VOLUME_MACD_ALGOS:
        out.pop("macd_algo-seg", None)
    if out.get("macd_algo") == "rsi":
        out.pop("cal_rsi", None)
    return out


# ----------------------------------------------------------------------
# 读
# ----------------------------------------------------------------------

def _fallback_config() -> dict:
    """配置存储不可用时的降级结果：空配置（等价内核默认）。"""
    return {}


def load() -> dict:
    """读取用户配置的 **overrides**（已解码、已应用派生键）。不可用时降级为空配置。

    `overrides` 只含用户显式改过的键（design D3），因此返回的 dict 传给
    `CChanConfig` 即可 —— 未覆盖项由内核补默认。

    **注意**：返回里**不含** `bsp_preset` —— 档位存在独立的 `preset` 列，
    且它不属于「用户显式改过的项」。档位回填发生在计算出口
    （`build_conf()` / `effective_config()` / `load_preset()`），
    见 `_preset_injected()` 的说明。

    需要「全量快照」（用于展示/审计）请用 `load_with_meta()` 的 `config` 字段；
    需要「整套生效值」请用 `effective_config()`。
    """
    global _cached_version, _cached_config, _cached_preset

    conn = _get_pg_conn()
    if conn is None:
        return _fallback_config()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT version, overrides, preset FROM {_TABLE} WHERE id = 1")
            row = cur.fetchone()
        if row is None:
            # 表已建但未初始化（首次部署）：等价于「用户未配置」
            return _fallback_config()
        version, raw, preset = row
        if version != _cached_version:
            _cached_config = _decode_value(raw or {})
            _cached_preset = preset
            _cached_version = version
        return apply_derived(dict(_cached_config or {}))
    except psycopg2.Error as e:
        log.warning("配置读取失败，降级为内核默认: %s", e)
        return _fallback_config()
    finally:
        conn.close()


def load_with_meta() -> dict:
    """读取完整配置行（供 API 返回）。

    返回 `{"config": 全量快照, "overrides": 显式覆盖, "preset": str,
           "version": int | None, "initialized": bool}`。
    `initialized=False` 表示表内尚无配置行（或存储不可用）。

    `overrides` **不带派生键** —— 它是「用户显式改过哪些项」的答案，派生键
    （`macd_algo-seg` / `cal_rsi`）是后端按 `macd_algo` 推出来的，用户没配过。
    混进来的后果很实际：前端 `computeOverrides()` 会把它们当成用户覆盖原样
    回传，而 `save()` 的 `_strip_derived()` 又会清掉 —— 表面上无害，但
    「未改动」的 overrides 与 GET 返回的不一致，保存一次就悄悄改写库里的值。
    需要派生后的生效值请用 `load()` / `effective_config()`。
    """
    conn = _get_pg_conn()
    if conn is None:
        return {"config": {}, "overrides": {}, "preset": "standard",
                "version": None, "initialized": False}
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT version, config, overrides, preset FROM {_TABLE} WHERE id = 1"
            )
            row = cur.fetchone()
        if row is None:
            return {"config": {}, "overrides": {}, "preset": "standard",
                    "version": None, "initialized": False}
        version, raw_cfg, raw_ovr, preset = row
        return {
            "config": _decode_value(raw_cfg or {}),
            "overrides": _decode_value(raw_ovr or {}),
            "preset": preset or "standard",
            "version": version,
            "initialized": True,
        }
    except psycopg2.Error as e:
        log.warning("配置读取失败，降级为内核默认: %s", e)
        return {"config": {}, "overrides": {}, "preset": "standard",
                "version": None, "initialized": False}
    finally:
        conn.close()


def load_preset() -> str:
    """读取已保存的档位预设名（`preset` 列），不可用时退回 `standard`。

    **为什么要单独一个函数**：`bsp_preset` 在库里存的是 `preset` 列，而不是
    `overrides` 里的一个键 —— 前端 `computeOverrides()` 拿它与档位基线相比，
    相等就不写进 overrides（它本来就不是「用户改过的项」）。若计算出口忘了回填，
    `CChanConfig` 只能看到硬编码默认 `standard`，用户切到 legacy 后一处判据都
    不会跟着变（实测：`preset=legacy` + 空 overrides 时 `min_zs_cnt` 仍是 2、
    `divergence_rate` 仍是 0.9、`bsp1_trend` 仍是 True）。

    走与 `load()` 同一份进程内缓存（`_cached_preset` 随 `version` 一起失效），
    不额外查库。
    """
    global _cached_version, _cached_config, _cached_preset

    load()                       # 确保缓存已按当前版本刷新（含 _cached_preset）
    return _cached_preset or "standard"


def _preset_injected(conf: dict) -> dict:
    """把档位名回填进配置字典（用户已在 `overrides` 里显式写 `bsp_preset` 时以它为准）。"""
    if "bsp_preset" in conf:
        return conf
    return {**conf, "bsp_preset": load_preset()}


def effective_config() -> dict:
    """生效配置 = 内核默认 + 档位预设 + 用户配置（已应用派生键与档位）。

    供元数据接口展示「当前生效值」。计算链路不需要展开默认值 ——
    `CChanConfig` 自己会补默认，直接传 `build_conf()` 的结果即可。
    """
    return apply_derived(_preset_injected(dict(load())))


def build_conf(entry_conf: Optional[dict] = None) -> dict:
    """构造传给 `CChanConfig` 的配置字典 —— 计算链路的**唯一出口**。

    三层优先级的落地（design D1）：
        内核 `para_dict` 默认  →  `bsp_preset` 展开  →  用户 overrides

    `load()` 返回的 overrides 天然位于第三层（`CChanConfig` 先铺默认、再展开预设、
    最后用传入的 key 覆盖），因此这里只需把入口专属键（`trigger_step` /
    `kl_data_check` 等，用户配置不含）叠加在最上面。

    **档位必须在此回填**：`bsp_preset` 存的是独立的 `preset` 列，不在 overrides 里
    （它不属于「用户改过的项」）。漏掉这一步，`CChanConfig` 永远按 `standard` 展开，
    切档位完全无效 —— 详见 `load_preset()`。

    派生键（`macd_algo-seg` / `cal_rsi`）已由 `load()` 补齐，指纹与计算都从
    **同一个**返回字典构造 `CChanConfig`，两者不可能用到不同口径（design D6/D7）。

    点号键（`macd.fast` 等）在此转成内核的嵌套 `macd` 字典 —— 转换点唯一。
    """
    merged = _preset_injected(dict(load()))
    if entry_conf:
        merged.update(entry_conf)
    return to_kernel(merged)


# ----------------------------------------------------------------------
# 写
# ----------------------------------------------------------------------

class ConfigStoreUnavailable(RuntimeError):
    """配置存储不可用（写入路径无降级语义）。"""


class ConfigValidationError(ValueError):
    """候选配置被内核拒绝。

    `param` 为可定位的配置 key（能解析出来时），`kernel_message` 保留内核异常原文 ——
    内核的消息已含参数名与合法取值，直接透传给前端最准确（design D4）。
    """

    def __init__(self, message: str, param: Optional[str] = None,
                 kernel_message: str = ""):
        super().__init__(message)
        self.param = param
        self.kernel_message = kernel_message or message


# 内核异常消息里常见的前缀形式，用于反查出错的参数名
_KEY_IN_MESSAGE = re.compile(
    r"(?:^|[\s(（,，])([A-Za-z_][A-Za-z0-9_.\-]*)\s*[=＝]"
)


def _guess_param(message: str, candidates) -> Optional[str]:
    """从内核异常消息里反查配置 key（取消息中最先出现的候选者）。

    三步匹配，从精确到宽松：
        1. `key=value` 形式的精确命中（大多数 `_check_choice` 异常）
        2. 消息里直接出现完整 key（如 `bsp2_confirm_window=3 非法`）
        3. 消息里出现 key 的**前缀**（成对约束的消息写作
           「bsp2_time_axis 阈值非法：strong=... 必须小于 weak=...」，
           而实际参数是 `bsp2_time_axis_strong/weak`）
    """
    message = message or ""
    found = [m.group(1) for m in _KEY_IN_MESSAGE.finditer(message)]
    for name in found:
        if name in candidates:
            return name

    # 精确子串匹配（长 key 优先，避免 `bsp2_time_axis` 抢 `bsp2_time_axis_strong`）
    for name in sorted(candidates, key=len, reverse=True):
        if name in message:
            return name

    # 前缀匹配：成对约束的消息只提到参数族（`bsp2_time_axis`），
    # 而实际参数是族下的成员（`bsp2_time_axis_strong` / `_weak`）。
    # 返回**族名**而非某个成员 —— 内核说的是「这两个值的关系不对」，
    # 单指一个成员会让前端把错误提示标在半对上面，误导用户只改一侧。
    #
    # 只取「去掉最后一段」的族名（`bsp2_time_axis_strong` → `bsp2_time_axis`），
    # 不再往上拆（否则 `bsp2_time_axis` 会退化成 `bsp2`，比消息里实际提到的还短）。
    family_hits = []
    for name in candidates:
        sep = "." if "." in name else "_"
        parts = re.split(r"[._]", name)
        if len(parts) < 2:
            continue
        family = sep.join(parts[:-1])
        if len(family) >= 5 and family in message:
            family_hits.append((len(family), family))
    if family_hits:
        family_hits.sort(reverse=True)
        return family_hits[0][1]
    return None


def _diagnose_param(kernel_conf: dict) -> Optional[str]:
    """消息为空时定位出错的配置 key（内核里 `assert` 不带消息的场合）。

    做法：逐个 key 单独构造一次 `CChanConfig`，第一个抛异常的即为元凶。
    只在**错误路径**上执行，保存成功时零开销，因此不必优化。

    注意 `bsp2_time_axis_strong` / `weak` 的约束是**成对**的（strong < weak），
    单看任一项都可能通过；所以先整体试一遍成对键，再逐项试其余键。
    """
    from ChanAnalyse.ChanConfig import CChanConfig

    paired = [("bsp2_time_axis_strong", "bsp2_time_axis_weak"),
              ("bsp3_time_axis_strong", "bsp3_time_axis_weak")]
    for pair in paired:
        if not all(k in kernel_conf for k in pair):
            continue
        sub = {k: kernel_conf[k] for k in pair}
        try:
            CChanConfig(sub)
        except Exception:
            return pair[0]

    for key, value in kernel_conf.items():
        try:
            CChanConfig({key: value})
        except Exception:
            return key
    return None


def _nullable_keys() -> frozenset:
    """内核默认值就是 `None` 的配置项（`None` 是合法取值，语义为「不限制」）。

    目前只有 `max_bsp2s_lv`。用反射而不是硬编码，内核将来放开别的可空项时
    校验会自动跟上。
    """
    global _NULLABLE_CACHE
    if _NULLABLE_CACHE is None:
        from ChanAnalyse.ChanConfig import CChanConfig
        from .chan_config_schema import PARAMS, _read_default

        conf = CChanConfig()
        keys = set()
        for spec in PARAMS:
            try:
                if _read_default(conf, spec["key"]) is None:
                    keys.add(spec["key"])
            except Exception:
                continue
        _NULLABLE_CACHE = frozenset(keys)
    return _NULLABLE_CACHE


def validate_config(overrides: dict) -> dict:
    """保存前的构造期校验（design D4），返回将要落库的规范化 overrides。

    四道关卡，全部在**写入前**完成，失败即抛 `ConfigValidationError`：

    1. **形态规整**：把 JSON 传过来的 `"inf"` / `"-inf"` 字符串还原成
       `float("inf")`（前端勾「不限」发的就是字符串）。不还原的话内核会把它当成
       字符串存进配置，计算期 `"inf" <= 100` 直接 `TypeError`。
       同时拒绝 `None`（除内核默认可空项外）。
    2. **构造期校验**：`CChanConfig(...)` 会做枚举白名单（`_check_choice`）、
       区间约束（`bsp2_time_axis_strong < weak` 等）、未知 key 检查
    3. **延迟断言前移**：`bs_type` 的合法性原本由 `parse_target_type()` 的
       `assert` 在**计算时**才检查，这里显式调用一次把它搬到保存前
    4. **派生键一致性**：校验用与实际计算**同一个** `to_kernel(apply_derived(...))`
       形态，避免「校验通过但计算时因派生缺失而崩」

    返回的是**解码后**、去掉派生键的 overrides（`"inf"` 已是 `float("inf")`；
    派生由 `load()` 出口统一生成，不落库）。
    """
    from ChanAnalyse.ChanConfig import CChanConfig

    if not isinstance(overrides, dict):
        raise ConfigValidationError("配置必须是 JSON 对象")

    decoded = _decode_value(overrides)
    nullable = _nullable_keys()
    for key, raw in overrides.items():
        if raw is None and key not in nullable:
            # `None` 在内核侧多数字段能构造通过，却在计算期才炸（如
            # `divergence_rate=None` 让 `None <= 100` 抛 TypeError）。
            # 前端历史版本曾把 Infinity 序列化成 null，这里明确拒绝，避免脏值入库。
            # 只有内核默认就是 None 的参数（`max_bsp2s_lv`，语义是「不限制」）
            # 才把 None 当作合法取值。
            raise ConfigValidationError(
                f"{key} 取值非法：不能为空（要「不限」请传 \"inf\"）", param=key)

    candidate = apply_derived(decoded)
    # 入口专属键由计算链路叠加，校验时给出同形态的值（trigger_step 必须为 False，
    # 否则 CChan 构造会变成生成器模式，但这里只构造 CChanConfig，不受影响）
    kernel_conf = to_kernel(candidate)

    known = set(kernel_conf) | set(_DOTTED_KEYS)
    try:
        # 必须传副本：`CChanConfig` 内部的 `ConfigWithCheck.get()` 每读一个 key
        # 就把它从字典里 `del` 掉（未读的剩余 key 即「未知参数」）。
        # 直接传 `kernel_conf` 会在构造失败时把它清空，导致后续无法定位出错参数。
        conf = CChanConfig(dict(kernel_conf))
    except Exception as e:
        msg = str(e) or type(e).__name__
        param = _guess_param(msg, known)
        if param is None and not str(e):
            # 内核的裸 assert（如 `assert max_bs2_rate <= 1`）消息为空，
            # 无法从文本反查，靠逐个 key 单独构造来定位
            param = _diagnose_param(kernel_conf)
        detail = f"{param} 取值非法" if param else "配置非法"
        raise ConfigValidationError(
            f"{detail}：{msg}", param=param, kernel_message=msg) from e

    # bs_type 的 assert 在 parse_target_type() 里，构造期不触发。
    # 注意：`CChanConfig` 只在 `set_bsp_config` 末尾 parse 一次，而 `tmp_target_types`
    # 到那时已是列表 —— 非法类型在这一步以空消息 AssertionError 抛出，
    # 所以要先于此处判断。真实情况里上面的构造就抛了，这里兜住「构造没抛」的实现差异。
    try:
        conf.bs_point_conf.b_conf.parse_target_type()
        conf.bs_point_conf.s_conf.parse_target_type()
        conf.seg_bs_point_conf.b_conf.parse_target_type()
        conf.seg_bs_point_conf.s_conf.parse_target_type()
    except Exception as e:
        msg = str(e) or "assert"
        raise ConfigValidationError(
            f"bs_type 取值非法：{overrides.get('bs_type')!r}", param="bs_type",
            kernel_message=msg) from e

    # 返回**解码后**的值：`"inf"` 已还原为 `float("inf")`。落库时
    # `save()` 内部再 `_encode_value()` 转回 `"inf"` —— 存的是 JSON 可表示形态，
    # 但进程内缓存与计算链路拿到的始终是 `float("inf")`。
    return _strip_derived(decoded)


def validate_preset(preset: str) -> str:
    """校验档位预设名，返回规范值；非法时抛 `ConfigValidationError`。

    档位名以独立字段提交（`ConfigSaveRequest.preset`），不经过 `validate_config()`
    的 `CChanConfig` 构造 —— 但它会被 `build_conf()` 回填进内核配置，非法值一旦
    落库，此后每次计算都会抛 `unknown bsp_preset`，**整站 K 线请求 500**。
    因此必须在写入前单独拦一道，并以内核的档位表为唯一真源（不复制清单）。
    """
    from ChanAnalyse.ChanConfig import _BSP_PRESETS

    if not isinstance(preset, str) or preset not in _BSP_PRESETS:
        raise ConfigValidationError(
            f"bsp_preset 取值非法：只能取 {' / '.join(_BSP_PRESETS)}，收到 {preset!r}",
            param="bsp_preset",
        )
    return preset


def save(
    overrides: dict,
    preset: str,
    full_snapshot: Optional[dict] = None,
    updated_by: Optional[str] = None,
) -> int:
    """写入用户显式覆盖 + 全量快照并 bump 版本号，返回新版本。

    参数（design D3）：
        overrides: **生效语义的唯一来源** —— 只含用户显式改过的键。
            未包含的项由内核补默认（`bsp_preset` 展开），因此切档位时会跟随预设。
        preset: 保存时的档位预设名。**它单独落 `preset` 列，不进 overrides** ——
            但计算出口会把它回填进内核配置（`_preset_injected()`），所以它
            真正参与判定，不是诊断标注。非法取值须在入口用 `validate_preset()` 拦住。
        full_snapshot: 全量快照（58 项保存时的生效值），仅供展示/审计。
            缺省时用 `overrides` 填充（等价于「所有项都是显式值」）。

    派生键（`macd_algo-seg` / `cal_rsi`）不落库 —— 它们由 `apply_derived()` 在读取出口生成，
    落库会让「用户没配」与「用户配了」无法区分。
    """
    global _cached_version, _cached_config, _cached_preset

    conn = _get_pg_conn()
    if conn is None:
        raise ConfigStoreUnavailable("配置存储不可用，无法保存")

    stored_ovr = _strip_derived(overrides)
    stored_cfg = _strip_derived(full_snapshot if full_snapshot is not None else overrides)
    ovr_payload = json.dumps(_encode_value(stored_ovr), ensure_ascii=False, sort_keys=True)
    cfg_payload = json.dumps(_encode_value(stored_cfg), ensure_ascii=False, sort_keys=True)

    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {_TABLE}
                    (id, config, overrides, preset, version, updated_at, updated_by)
                VALUES (1, %s::jsonb, %s::jsonb, %s, 1, NOW(), %s)
                ON CONFLICT (id) DO UPDATE SET
                    config     = EXCLUDED.config,
                    overrides  = EXCLUDED.overrides,
                    preset     = EXCLUDED.preset,
                    version    = {_TABLE}.version + 1,
                    updated_at = NOW(),
                    updated_by = EXCLUDED.updated_by
                RETURNING version
                """,
                (cfg_payload, ovr_payload, preset, updated_by),
            )
            version = cur.fetchone()[0]
        conn.commit()
        # 本进程立即生效：整行已写入，直接同步缓存（不必再读一次库）
        _cached_version = version
        _cached_config = stored_ovr
        _cached_preset = preset
        return version
    except psycopg2.Error as e:
        conn.rollback()
        raise ConfigStoreUnavailable(f"配置保存失败: {e}") from e
    finally:
        conn.close()


def invalidate_cache() -> None:
    """清空进程内缓存（测试与多进程一致性排查用）。"""
    global _cached_version, _cached_config, _cached_preset
    _cached_version = None
    _cached_config = None
    _cached_preset = None


# ----------------------------------------------------------------------
# 批量同步任务（design D8）
# ----------------------------------------------------------------------

def sync_job_create(config_version: int, total: int = 0) -> int:
    """新建一条 running 任务，返回 job id。"""
    conn = _get_pg_conn()
    if conn is None:
        raise ConfigStoreUnavailable("配置存储不可用，无法创建同步任务")
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""INSERT INTO {_SYNC_TABLE} (config_version, status, total)
                    VALUES (%s, 'running', %s) RETURNING id""",
                (config_version, total),
            )
            job_id = cur.fetchone()[0]
        conn.commit()
        return job_id
    except psycopg2.Error as e:
        conn.rollback()
        raise ConfigStoreUnavailable(f"创建同步任务失败: {e}") from e
    finally:
        conn.close()


def sync_job_progress(job_id: int, done: int, failed: int,
                      total: Optional[int] = None) -> None:
    """推进任务的 done / failed 计数（每个键回调一次，允许批量刷新）。"""
    conn = _get_pg_conn()
    if conn is None:
        return   # 进度丢失不阻断同步本身
    try:
        with conn.cursor() as cur:
            if total is None:
                cur.execute(
                    f"UPDATE {_SYNC_TABLE} SET done=%s, failed=%s WHERE id=%s",
                    (done, failed, job_id),
                )
            else:
                cur.execute(
                    f"UPDATE {_SYNC_TABLE} SET done=%s, failed=%s, total=%s WHERE id=%s",
                    (done, failed, total, job_id),
                )
        conn.commit()
    except psycopg2.Error as e:
        log.warning("同步进度写入失败（不影响同步）: %s", e)
        conn.rollback()
    finally:
        conn.close()


def sync_job_finish(job_id: int, status: str, done: int, failed: int,
                    summary: dict) -> None:
    """收尾：置终态 + 汇总（含 `stale` 判定需要的 config_version 比对）。"""
    conn = _get_pg_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""UPDATE {_SYNC_TABLE}
                    SET status=%s, done=%s, failed=%s,
                        summary=%s::jsonb, finished_at=NOW()
                    WHERE id=%s""",
                (status, done, failed,
                 json.dumps(_encode_value(summary), ensure_ascii=False), job_id),
            )
        conn.commit()
    except psycopg2.Error as e:
        log.warning("同步任务收尾写入失败: %s", e)
        conn.rollback()
    finally:
        conn.close()


def sync_job_latest() -> Optional[dict]:
    """最近一条同步任务（供 status 接口；含 stale 计算）。

    `stale` = 任务启动时快照的配置版本 ≠ 当前版本 —— 说明同步跑完后配置又变了，
    结果不能代表当前口径，需要再同步一次。
    """
    conn = _get_pg_conn()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT id, config_version, status, total, done, failed,
                           summary, started_at, finished_at
                    FROM {_SYNC_TABLE} ORDER BY id DESC LIMIT 1"""
            )
            row = cur.fetchone()
            if row is None:
                return None
            (job_id, cfg_ver, status, total, done, failed,
             summary, started, finished) = row
            cur.execute(f"SELECT version FROM {_TABLE} WHERE id = 1")
            vrow = cur.fetchone()
        current = vrow[0] if vrow else None
        stale = cfg_ver is not None and current is not None and cfg_ver != current
        return {
            "job_id": job_id,
            "config_version": cfg_ver,
            "current_version": current,
            "status": status,
            "total": total,
            "done": done,
            "failed": failed,
            "summary": _decode_value(summary or {}),
            "started_at": started,
            "finished_at": finished,
            "stale": stale,
        }
    except psycopg2.Error as e:
        log.warning("同步任务读取失败: %s", e)
        return None
    finally:
        conn.close()


def sync_job_mark_interrupted() -> None:
    """进程启动时把残留的 running 任务标为 interrupted（上次进程已不在了）。"""
    conn = _get_pg_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""UPDATE {_SYNC_TABLE} SET status='interrupted', finished_at=NOW()
                    WHERE status='running'"""
            )
        conn.commit()
    except psycopg2.Error as e:
        log.warning("清理残留同步任务失败: %s", e)
        conn.rollback()
    finally:
        conn.close()


_ensure_tables()
