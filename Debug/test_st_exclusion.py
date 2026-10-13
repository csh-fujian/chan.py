# -*- coding: utf-8 -*-
"""
ST 股票排除（openspec 变更 exclude-st-stocks）离线冒烟自测。

不需要 PG / 网络 / DuckDB：用假游标断言生成的 SQL，用 monkeypatch 断言调用参数。

覆盖 tasks.md 的验证点：
- 1.1 判定表（is_st_name）
- 2.1 list_stocks 始终追加 ST_EXCLUDE_SQL，COUNT 与 SELECT 共用同一 where
- 2.2 PG 不可用时 list_stocks 抛 StockNameSourceUnavailable（不再返回兜底列表）
- 4.1 list_pool_codes 的 exclude_st 开关
- 4.3 due_domains：identity 域不排除 ST，逐股域排除
- 6.1 /api/klines 对 ST 返回 404 且不碰缓存、不触发计算
- 6.2 /api/klines 在名称来源不可用时放行（不 503）
- 7.6 名称来源不可用时策略任务复位为 paused（后台路径与 EOD 路径），不留 running

运行：  .venv/bin/python Debug/test_st_exclusion.py
"""

import asyncio
import os
import sys

_DEBUG_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_DEBUG_DIR)
sys.path.insert(0, _REPO_ROOT)

from WebAPI import main as web_main
from WebAPI import stock_store
from WebAPI.stock_store import StockNameSourceUnavailable, is_st_name, ST_EXCLUDE_SQL


# ---------------------------------------------------------------------------
# 断言工具
# ---------------------------------------------------------------------------
_PASS = 0
_FAIL = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  PASS  {label}")
    else:
        _FAIL += 1
        print(f"  FAIL  {label}" + (f"  -- {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# 假 PG 连接：记录 SQL，不真的连库
# ---------------------------------------------------------------------------
class _FakeCursor:
    def __init__(self, sink):
        self.sink = sink

    def execute(self, sql, params=None):
        self.sink.append((" ".join(str(sql).split()), list(params or [])))

    def fetchone(self):
        return (0,)

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    """假连接：_ensure_tables 会往 sink 里塞大量 DDL，断言时按内容挑目标查询。"""

    def __init__(self, sink):
        self.sink = sink

    def cursor(self):
        return _FakeCursor(self.sink)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _find(sink, needle):
    """按内容挑出第一条匹配的 SQL（跳过 _ensure_tables 的 DDL 噪声）。"""
    for sql, params in sink:
        if needle in sql:
            return sql, params
    return None, None


class _Patch:
    """临时替换模块属性，退出时还原。"""

    def __init__(self, obj, **attrs):
        self.obj, self.attrs, self.saved = obj, attrs, {}

    def __enter__(self):
        for k, v in self.attrs.items():
            self.saved[k] = getattr(self.obj, k)
            setattr(self.obj, k, v)
        return self

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            setattr(self.obj, k, v)
        return False


# ---------------------------------------------------------------------------
# 1.1 判定表
# ---------------------------------------------------------------------------
print("\n[1.1] is_st_name 判定表")
for name, expected in [
    ("ST某某", True),
    ("*ST某某", True),
    ("st某某", True),
    (" *ST 某", True),
    ("平安银行", False),
    ("中ST", False),
    ("", False),
    (None, False),
]:
    check(f"is_st_name({name!r}) is {expected}", is_st_name(name) is expected)

check("ST_EXCLUDE_SQL 含 COALESCE（无名股票不被误排除）", "COALESCE" in ST_EXCLUDE_SQL)
check("ST_EXCLUDE_SQL 假定别名 s", "s.name" in ST_EXCLUDE_SQL)
# 该片段会被拼进带 params 的 execute()，psycopg2 会对整条 SQL 做 % 格式化：
# 字面量 % 会被当作占位符（ValueError/TypeError），故必须不含 %。
check("ST_EXCLUDE_SQL 不含 %（psycopg2 参数化安全）", "%" not in ST_EXCLUDE_SQL, ST_EXCLUDE_SQL)
check("ST_EXCLUDE_SQL 同时排除 ST 与 *ST", "'ST'" in ST_EXCLUDE_SQL and "'*ST'" in ST_EXCLUDE_SQL)


# ---------------------------------------------------------------------------
# 2.1 / 2.2 list_stocks
# ---------------------------------------------------------------------------
print("\n[2.1] list_stocks 始终追加 ST_EXCLUDE_SQL")
sink = []
with _Patch(stock_store, _get_pg_conn=lambda: _FakeConn(sink)):
    stock_store.list_stocks(q="平安")
count_sql = _find(sink, "SELECT COUNT(*)")[0]
select_sql = _find(sink, "SELECT s.code, s.name, s.exchange")[0]
check("取到了 COUNT 与 items 两条查询", count_sql is not None and select_sql is not None)
check("COUNT 查询含 ST 排除谓词（单一来源常量）", ST_EXCLUDE_SQL in count_sql, count_sql)
check("SELECT 查询含 ST 排除谓词（单一来源常量）", ST_EXCLUDE_SQL in select_sql, select_sql)
check(
    "COUNT 与 SELECT 共用同一 where",
    count_sql.split("WHERE", 1)[1].strip() == select_sql.split("WHERE", 1)[1].split("ORDER BY")[0].strip(),
)

print("\n[2.2] PG 不可用时失败关闭")
with _Patch(stock_store, _get_pg_conn=lambda: None):
    try:
        stock_store.list_stocks()
        check("list_stocks 抛 StockNameSourceUnavailable", False, "未抛异常")
    except StockNameSourceUnavailable:
        check("list_stocks 抛 StockNameSourceUnavailable", True)
    except Exception as e:
        check("list_stocks 抛 StockNameSourceUnavailable", False, f"抛了 {type(e).__name__}")
    try:
        stock_store._fallback_list_stocks()
        check("_fallback_list_stocks 不再返回未过滤列表", False, "未抛异常")
    except StockNameSourceUnavailable:
        check("_fallback_list_stocks 不再返回未过滤列表", True)


# ---------------------------------------------------------------------------
# 4.1 list_pool_codes
# ---------------------------------------------------------------------------
print("\n[4.1] list_pool_codes 的 exclude_st 开关")
sink = []
with _Patch(stock_store, _get_pg_conn=lambda: _FakeConn(sink)):
    stock_store.list_pool_codes()
sql_default = _find(sink, "SELECT s.code FROM stock s")[0]
check("默认不漏 NOT LIKE（identity 域行为不变）", sql_default is not None and "NOT LIKE" not in sql_default, sql_default)

sink = []
with _Patch(stock_store, _get_pg_conn=lambda: _FakeConn(sink)):
    stock_store.list_pool_codes(enabled=True, exclude_st=True)
sql_excl = _find(sink, "SELECT s.code FROM stock s")[0]
check("exclude_st=True 追加排除谓词", ST_EXCLUDE_SQL in sql_excl, sql_excl)
check("exclude_st=True 与 enabled 条件叠加", "s.enabled = %s" in sql_excl, sql_excl)
check("别名为 s（与 ST_EXCLUDE_SQL 对齐）", "FROM stock s" in sql_excl, sql_excl)


# ---------------------------------------------------------------------------
# 4.3 due_domains 域间差异
# ---------------------------------------------------------------------------
print("\n[4.3] due_domains：identity 不排除 ST，逐股域排除")
calls: list[dict] = []


def _spy_pool_codes(enabled=None, exclude_st=False):
    calls.append({"enabled": enabled, "exclude_st": exclude_st})
    return []


from WebAPI import meta_sync

with _Patch(stock_store, list_pool_codes=_spy_pool_codes):
    meta_sync.due_domains(domains=["identity", "profile"])

identity_call = next((c for c in calls if c["enabled"] is None), None)
profile_call = next((c for c in calls if c["enabled"] is True), None)
check("identity 域 enabled=None（全市场）", identity_call is not None, str(calls))
check("identity 域不排除 ST", identity_call is not None and identity_call["exclude_st"] is False, str(calls))
check("profile 域 enabled=True", profile_call is not None, str(calls))
check("profile 域排除 ST", profile_call is not None and profile_call["exclude_st"] is True, str(calls))


# ---------------------------------------------------------------------------
# 6.1 / 6.2 GET /api/klines
# ---------------------------------------------------------------------------
print("\n[6.1] /api/klines 对 ST 返回 404")


def _boom(*a, **k):
    raise AssertionError("不应被调用")


def _run_get_klines():
    return asyncio.run(web_main.get_klines(symbol="sz.000001", period="1d", end=None))


# 6.1：ST 名称 → 404，且缓存/计算均不被触碰
with _Patch(
    web_main,
    get_stock_name=lambda code: "ST某某",
    get_chan_cache=_boom,
    _compute_chan=_boom,
):
    try:
        _run_get_klines()
        check("ST 代码返回 404", False, "未抛 HTTPException")
    except Exception as e:
        is_404 = getattr(e, "status_code", None) == 404
        check("ST 代码返回 404", is_404, f"{type(e).__name__}: {e}")
        check("detail 为「已排除：ST 股票」", getattr(e, "detail", None) == "已排除：ST 股票", str(getattr(e, "detail", None)))

# 6.2：名称来源不可用 → 放行（进入计算，而不是 503）。
# 注意：get_klines 会把计算期异常统一包成 404，所以不能用「抛异常」当探针，
# 要用标记变量证明控制流确实走到了计算阶段。
reached = {}


def _mark_compute(*a, **k):
    reached["compute"] = True
    raise RuntimeError("停在这里，不再往下走")


def _raise_unavailable(code):
    raise StockNameSourceUnavailable("PG 不可用")


class _StubCache:
    """缓存桩：未命中。放行路径会先经过缓存读取，不能让它抛异常。"""

    def get(self, symbol, kl_type):
        return False, None


with _Patch(web_main, get_stock_name=_raise_unavailable, get_chan_cache=lambda: _StubCache(), _compute_chan=_mark_compute):
    try:
        _run_get_klines()
    except Exception:
        pass  # _mark_compute 的 RuntimeError 会被包装成 404，这里只关心是否走到了计算

check("名称来源不可用时放行至计算", reached.get("compute") is True)


# ---------------------------------------------------------------------------
# 7.6 名称来源不可用不得让策略任务卡在 running
# ---------------------------------------------------------------------------
print("\n[7.6] 策略任务在 PG 不可用时的状态复位")

from WebAPI.routers import strategy as strategy_router
from WebAPI.strategy_engines import scheduler as _sch

# 后台路径（routers/strategy._run_task_background）：run_task 因名称来源不可用
# 抛错时，任务已被 start/resume 置为 running，必须复位，否则永久卡 running。
_bg_calls: list = []


def _raise_unavailable_task(task_id, *a, **k):
    raise StockNameSourceUnavailable("PG 不可用")


def _spy_set_status(task_id, status, *a, **k):
    _bg_calls.append((task_id, status))
    return True


with _Patch(strategy_router, run_task=_raise_unavailable_task, set_task_status=_spy_set_status):
    strategy_router._run_task_background(42)
check("名称来源不可用 → 复位为 paused（不留 running）", _bg_calls == [(42, "paused")], str(_bg_calls))

# 控制组：其他异常维持原行为（仅记日志，不改状态）
_bg_calls.clear()


def _raise_other(task_id, *a, **k):
    raise RuntimeError("boom")


with _Patch(strategy_router, run_task=_raise_other, set_task_status=_spy_set_status):
    strategy_router._run_task_background(43)
check("其他异常不改任务状态（仅记日志）", _bg_calls == [], str(_bg_calls))

# EOD 路径（scheduler.run_eod_tasks）：原实现异常一律复位 done（会掩盖「未扫完」）。
# 名称来源不可用是可重试的环境故障 → 复位 paused；其他异常仍复位 done。
_eod_calls: list = []


def _spy_eod_status(task_id, status, *a, **k):
    _eod_calls.append((task_id, status))
    return True


def _eod_run(task):
    with _Patch(
        _sch.strategy_store,
        list_persistent_tasks=lambda: [{"id": 7, "status": "pending", "strategy_id": "vp"}],
        set_task_status=_spy_eod_status,
    ), _Patch(_sch, run_task=task):
        _sch.run_eod_tasks()


_eod_run(_raise_unavailable_task)
check("EOD：名称来源不可用 → 复位 paused", (7, "paused") in _eod_calls, str(_eod_calls))

_eod_calls.clear()
_eod_run(_raise_other)
check("EOD：其他异常 → 仍复位 done（原行为不变）", (7, "done") in _eod_calls, str(_eod_calls))


# ---------------------------------------------------------------------------
print(f"\n{'=' * 46}\n合计: {_PASS} PASS, {_FAIL} FAIL\n{'=' * 46}")
sys.exit(1 if _FAIL else 0)
