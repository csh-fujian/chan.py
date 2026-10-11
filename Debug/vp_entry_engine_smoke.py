# -*- coding: utf-8 -*-
"""
vp_entry 策略引擎冒烟测试（vp-entry-strategy-integration tasks 2.1/2.2/
3.1/3.2 verify）。

真 PG（127.0.0.1:5432/chan）+ 真 DuckDB（Data/kl_store.duckdb）：

1. 引擎扫描行为（2.1）：内存构造 K 线直测 _scan_series（分钟版触发 +
   日线版兜底 + 水位门 + payload 字段集）
2. B 日后状态追踪（2.2）：构造历史数据断言 triggered/running/expired
   三种终态各出现（expired 同日双满足优先）
3. 任务全生命周期（3.2）：建任务（enum 参数校验路径）→ 启动执行 →
   信号落库含 payload/状态 → 重扫幂等 → detail kv 统计正确（3.1）
4. 连续区间参数（spec「任务侧参数自由配置」）：cv7_max=0.27（不在回测
   敏感性集合内）创建与执行正常
5. engine 协议回归：scheduler 对 vp_entry 任务的 scan_with_params 透传

运行（项目根目录）：
    .venv/Scripts/python.exe -X utf8 Debug/vp_entry_engine_smoke.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PG_DSN = os.environ.get(
    "PG_DSN", "host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres"
)
os.environ["PG_DSN"] = PG_DSN

PASS = []
FAIL = []


def check(name: str, cond: bool, detail: str = ""):
    """断言收集（不中断，最后统一汇报）。"""
    if cond:
        PASS.append(name)
        print(f"  [PASS] {name}")
    else:
        FAIL.append(f"{name} {detail}")
        print(f"  [FAIL] {name} {detail}")


# ----------------------------------------------------------------------
# 内存构造 K 线（对齐 Debug/test_vp_entry.py 的构造工具）
# ----------------------------------------------------------------------

import datetime

from WebAPI.strategy_engines.vp_entry.engine import VpEntryEngine
from WebAPI.strategy_engines.vp_entry.signal_rule import DayBar


def make_history(n, base_close=10.0, vol=100.0, start="2024-01-01"):
    """n 根平稳历史日 K（满足 61 根门槛与 MA60V≈100 基准）。"""
    d0 = datetime.date.fromisoformat(start)
    bars = []
    for i in range(n):
        d = (d0 + datetime.timedelta(days=i)).isoformat()
        c = base_close * (1 + 0.002 * (1 if i % 2 == 0 else -1))
        o = base_close
        bars.append(DayBar(d, o, max(o, c) + 0.02, min(o, c) - 0.02, c, vol + (2 if i % 2 == 0 else -2)))
    return bars


def build_case(v_a=300.0, tail=None):
    """hist(70) + 蓄势 7 + A + 调整序列（A+1 冲高成峰，A+2/A+3 缩量回踩）。

    tail: B 日之后的后续日 K 列表（状态重放用）。
    """
    hist = make_history(70)
    d0 = datetime.date(2024, 4, 1)
    c = hist[-1].close
    bars = []
    for i in range(7):
        date = (d0 + datetime.timedelta(days=i)).isoformat()
        prev_c = c
        c = c * 1.001
        bars.append(DayBar(date, prev_c, c * 1.001, prev_c * 0.999, c, 75.0))
    a_open = c * 1.01
    a_close = c * 1.06
    a = DayBar((d0 + datetime.timedelta(days=7)).isoformat(), a_open,
               a_close * 1.005, c, a_close, v_a)
    bars.append(a)
    cur = a_close
    day = 8
    for ret, vol, low_ratio in [(0.02, 0.9 * v_a, 0.0), (-0.015, 0.25 * v_a, 0.0),
                                (-0.015, 0.25 * v_a, 0.0)]:
        date = (d0 + datetime.timedelta(days=day)).isoformat()
        prev_c = cur
        cur = cur * (1 + ret)
        lo = min(prev_c, cur) * (1 - low_ratio)
        bars.append(DayBar(date, prev_c, max(prev_c, cur) * 1.001, lo, cur, vol))
        day += 1
    bars_all = hist + bars + list(tail or [])
    # 日线序列元组（_scan_series 的输入形态：date, open, high, low, close, volume）
    # 注意必须含 hist（61 根门槛与 MA60V 上下文），对齐 test_vp_entry 的喂入顺序
    kl = [(b.date, b.open, b.high, b.low, b.close, b.volume) for b in bars_all]
    return hist, bars, kl


def _bars_of(kl):
    return [DayBar(*r) for r in kl]


# ----------------------------------------------------------------------
# 任务 2.1：引擎扫描行为（内存构造，_scan_series 直测）
# ----------------------------------------------------------------------

def test_scan_series_daily_fallback():
    """日线退化版：无分钟数据（store=None 不可用时调 decide 兜底）——
    用伪造 store：任何 K_5M 查询返回空 → 全部走日线版。"""
    v_a = 300.0
    d0 = datetime.date(2024, 4, 1)
    # 构造 B 日（A+4）：高开 1.5%、V_B=3×、C>O（对齐 test_vp_entry Scenario 11）
    _hist, bars, _ = build_case(v_a)
    b_prev_close = bars[-1].close
    d_end3_mean = 0.25 * v_a
    o_b = b_prev_close * 1.015
    c_b = o_b * 1.02
    b_bar = DayBar((d0 + datetime.timedelta(days=11)).isoformat(), o_b,
                   c_b * 1.005, o_b * 0.99, c_b, 3.0 * d_end3_mean)
    o_b1 = c_b * 1.002
    tail = [
        # B+1：日线版买价 = B+1 开盘；后续走势决定状态（先涨破 B 日最高 → running）
        DayBar((d0 + datetime.timedelta(days=12)).isoformat(), o_b1,
               o_b1 * 1.03, o_b1 * 0.99, o_b1 * 1.028, 100.0),
    ]
    _, _, kl = build_case(v_a, tail=[b_bar] + tail)

    class _EmptyStore:
        def execute(self, sql, params=None):
            return []

    eng = VpEntryEngine()
    events = eng._scan_series(_EmptyStore(), "sz.daily", kl, "QFQ",
                              {"cv7_max": 0.25, "box_width_max": 0.12,
                               "n_max": 7, "stop_loss": 0.12, "vol_gate": "mean"})
    check("2.1 日线版兜底触发", len(events) == 1, str([(e["signal_date"], e["payload"].get("entry_mode")) for e in events]))
    if events:
        ev = events[0]
        check("signal_date = B 日", ev["signal_date"] == b_bar.date, ev["signal_date"])
        check("entry_mode = daily", ev["payload"]["entry_mode"] == "daily")
        check("entry_ref_price = B+1 开盘", abs(ev["entry_ref_price"] - o_b1) < 5e-4, str(ev["entry_ref_price"]))
        check("is_buy = True", ev["is_buy"] is True)
        check("payload 字段集完整", set(ev["payload"]) >= {
            "a_date", "p_date", "entry_mode", "spring", "drift_bucket",
            "wick_box", "box_days", "box_r", "a_ret", "b_bar_time", "b_high"}, str(set(ev["payload"])))
        # 6.2：B 日（日线版 = B+1）日线 OHLC 落 payload（b_open/b_close/b_day_pct）
        check("6.2 payload B 日 OHLC 齐（日线版）", all(
            k in ev["payload"] and ev["payload"][k] is not None
            for k in ("b_open", "b_close", "b_day_pct")),
            str({k: ev["payload"].get(k) for k in ("b_open", "b_close", "b_day_pct")}))
        check("b_high = B 日最高", abs(ev["payload"]["b_high"] - b_bar.high) < 5e-4, str(ev["payload"]["b_high"]))
        # stop_ref_price = max(O_A, 买价×0.88)
        a_bar = bars[-4]  # A 日（蓄势 7 根后第 1 根）
        check("stop_ref_price 口径", ev["stop_ref_price"] is not None and
              abs(ev["stop_ref_price"] - max(a_bar.open, o_b1 * 0.88)) < 0.01, str(ev["stop_ref_price"]))
        # 状态重放：B+1 close 上破 B 日 high → running
        check("2.2 上破 B 日高 → running", ev["state"] == "running", ev["state"])


def test_scan_series_minute():
    """分钟版触发：伪造 store 返回该 B 日的 K_5M（触发分钟收盘为买价）。"""
    v_a = 300.0
    d0 = datetime.date(2024, 4, 1)
    _hist, bars, _ = build_case(v_a)
    # B 日 = A+4（bars 长度 12：hist 单独喂，bars 7+1+3=11 根 + B = 12）
    # 与 daily 测试同构，但 store 返回分钟数据
    b_prev_close = bars[-1].close
    b_date = (d0 + datetime.timedelta(days=11)).isoformat()
    o_b = b_prev_close * 1.015
    c_b = o_b * 1.02
    b_bar = DayBar(b_date, o_b, c_b * 1.005, o_b * 0.99, c_b, 3.0 * 0.25 * v_a)
    tail = [
        DayBar((d0 + datetime.timedelta(days=12)).isoformat(), c_b * 1.002,
               c_b * 1.003, c_b * 0.98, c_b * 0.99, 100.0),  # B+1 回落（不破止损、不上破）
        DayBar((d0 + datetime.timedelta(days=13)).isoformat(), c_b * 0.99,
               c_b * 0.995, c_b * 0.80, c_b * 0.85, 100.0),  # B+2 深跌 → expired
    ]
    _, _, kl = build_case(v_a, tail=[b_bar] + tail)

    # 构造触发分钟序列（48 根 bar，第 7 根巨量触发，r=2%）
    times = []
    hh, mm = 9, 35
    while len(times) < 48:
        t = f"{hh:02d}:{mm:02d}"
        in_lunch = (hh == 11 and mm > 30) or hh == 12 or (hh == 13 and mm == 0)
        if not in_lunch:
            times.append(t)
        mm += 5
        if mm >= 60:
            mm -= 60
            hh += 1
    # F 历史：60 个完整样本日均匀分布（每 bar 量 100）
    hist_rows = []
    d0f = datetime.date(2024, 1, 1)
    for k in range(60):
        d = (d0f + datetime.timedelta(days=k)).isoformat()
        for t in times:
            hist_rows.append((f"{d} {t}:00", 10.0, 10.1, 9.9, 10.0, 100.0))
    # B 日分钟：r 线性升至 2%，第 7 根（idx 6）巨量 400
    b_minute = []
    for i, t in enumerate(times):
        r = 0.02 * (i / 6) if i <= 6 else 0.02
        c = b_prev_close * (1 + r)
        v = 400.0 if i == 6 else 20.0
        b_minute.append((f"{b_date} {t}:00", c * 0.999, c * 1.001, c * 0.998, c, v))

    class _MinuteStore:
        def execute(self, sql, params=None):
            sql_l = sql.replace("\n", " ")
            if "SUBSTR(time_key, 1, 10) = ?" in sql_l:
                # params = [code, kl_type, autype, b_date]
                day = params[3]
                return b_minute if day == b_date else []
            if "SUBSTR(time_key, 1, 10) < ?" in sql_l:
                return hist_rows
            raise AssertionError(f"意外 SQL: {sql_l[:80]}")

    eng = VpEntryEngine()
    events = eng._scan_series(_MinuteStore(), "sz.minute", kl, "QFQ",
                              {"cv7_max": 0.25, "box_width_max": 0.12,
                               "n_max": 7, "stop_loss": 0.12, "vol_gate": "mean"})
    check("2.1 分钟版触发", len(events) == 1 and events[0]["payload"]["entry_mode"] == "minute",
          str([(e["signal_date"], e["payload"].get("entry_mode"), e["state"]) for e in events]))
    if events:
        ev = events[0]
        # 买价 = 触发分钟收盘（r=2%）
        expect_buy = round(b_prev_close * 1.02, 4)
        check("分钟版买价 = 触发分钟收盘", abs(ev["entry_ref_price"] - expect_buy) < 1e-4, str(ev["entry_ref_price"]))
        check("b_bar_time = 10:05", "10:05" in (ev["payload"]["b_bar_time"] or ""), str(ev["payload"]["b_bar_time"]))
        check("volume_ratio 非空", ev["payload"]["volume_ratio"] is not None, str(ev["payload"]["volume_ratio"]))
        # 6.2：分钟版 B 日（= B 日日线 bar）OHLC 落 payload
        check("6.2 payload B 日 OHLC 齐（分钟版）", all(
            k in ev["payload"] and ev["payload"][k] is not None
            for k in ("b_open", "b_close", "b_day_pct")),
            str({k: ev["payload"].get(k) for k in ("b_open", "b_close", "b_day_pct")}))
        # 状态重放：B+1 未演进、B+2 收盘跌破止损（买价×0.88 与 O_A 的 max）→ expired
        check("2.2 跌破止损 → expired", ev["state"] == "expired", ev["state"])


def test_state_replay_triggered_kept():
    """未演进保持 triggered（B 后横盘）。"""
    v_a = 300.0
    d0 = datetime.date(2024, 4, 1)
    _hist, bars, _ = build_case(v_a)
    b_prev_close = bars[-1].close
    o_b = b_prev_close * 1.015
    c_b = o_b * 1.02
    b_bar = DayBar((d0 + datetime.timedelta(days=11)).isoformat(), o_b,
                   c_b * 1.005, o_b * 0.99, c_b, 3.0 * 0.25 * v_a)
    tail = [DayBar((d0 + datetime.timedelta(days=12 + i)).isoformat(), c_b * 0.999,
                   c_b * 1.0, c_b * 0.99, c_b * 0.995, 60.0) for i in range(5)]
    _, _, kl = build_case(v_a, tail=[b_bar] + tail)

    class _EmptyStore:
        def execute(self, sql, params=None):
            return []

    eng = VpEntryEngine()
    events = eng._scan_series(_EmptyStore(), "sz.flat", kl, "QFQ",
                              {"cv7_max": 0.25, "box_width_max": 0.12,
                               "n_max": 7, "stop_loss": 0.12, "vol_gate": "mean"})
    check("2.2 未演进保持 triggered", len(events) == 1 and events[0]["state"] == "triggered",
          str([(e["signal_date"], e["state"]) for e in events]))


def test_watermark_gate():
    """水位门：watermark 非空且 latest <= watermark → 返回 []。"""
    import duckdb  # 真库验证水位门（sz.000014 有历史信号）
    from WebAPI.strategy_engines.vp_entry.engine import _duckdb_path

    eng = VpEntryEngine()
    code = "sz.000014"
    with duckdb.connect(_duckdb_path(), read_only=True) as conn:
        latest = conn.execute(
            "SELECT max(time_key) FROM kline WHERE kl_type='K_DAY' AND code=?",
            [code]).fetchone()[0]
    evs = eng.scan_with_params(code, {}, watermark=str(latest))
    check("2.1 水位门：无新 K 返回 []", evs == [], str(evs[:2]))
    evs2 = eng.scan_with_params(code, {})
    check("2.1 全史重算非空（sz.000014 有信号）", isinstance(evs2, list) and len(evs2) >= 1, str(len(evs2)))
    if evs2:
        check("事件附 watermark_new", evs2[0].get("watermark_new") == str(latest), str(evs2[0].get("watermark_new")))


# ----------------------------------------------------------------------
# 任务 3.1/3.2：任务全生命周期 + kv 统计（真 PG + 真 DuckDB）
# ----------------------------------------------------------------------

def test_task_lifecycle():
    import psycopg2

    from WebAPI import strategy_store as ss
    from WebAPI.strategy_engines.scheduler import list_all_codes, run_task

    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    cur = conn.cursor()
    # 清理冒烟残留
    cur.execute("""DELETE FROM strategy_signal WHERE task_id IN
                   (SELECT id FROM strategy_task WHERE label LIKE 'vp_entry_smoke%')""")
    cur.execute("""DELETE FROM strategy_task_stock_result WHERE task_id IN
                   (SELECT id FROM strategy_task WHERE label LIKE 'vp_entry_smoke%')""")
    cur.execute("""DELETE FROM strategy_scan_cursor WHERE task_id IN
                   (SELECT id FROM strategy_task WHERE label LIKE 'vp_entry_smoke%')""")
    cur.execute("DELETE FROM strategy_task WHERE label LIKE 'vp_entry_smoke%'")
    conn.close()

    all_codes = list_all_codes()
    check("DuckDB code 枚举非空", len(all_codes) > 0)

    # ---- enum 参数校验（2.4 spec：非法 enum 被拒绝）----
    try:
        ss.create_task(strategy_id="vp_entry", label="vp_entry_smoke_bad_enum",
                       params={"vol_gate": "bogus"}, scope_type="all")
        check("enum 非法被拒绝", False, "未抛 ValueError")
    except ValueError as e:
        check("enum 非法被拒绝（文案含选项集）", "mean" in str(e) and "strict" in str(e), str(e))

    # ---- 连续区间参数（spec：cv7_max=0.27 不在回测敏感性集合内）----
    task = ss.create_task(
        strategy_id="vp_entry",
        label="vp_entry_smoke_main",
        params={"cv7_max": 0.27},
        scope_type="manual",
        scope_codes=["sz.000014", "sh.600000", "sz.000007"],
        mode="test",
        user_group="vp冒烟",
    )
    check("连续区间参数创建成功（cv7_max=0.27）", task["params"]["cv7_max"] == 0.27, str(task["params"]))
    check("默认参数补全（vol_gate=mean）", task["params"]["vol_gate"] == "mean")
    tid = task["id"]

    # ---- 启动执行 → 信号落库 ----
    ss.start_task(tid)
    summary = run_task(tid)
    t = ss.get_task(tid)
    check("任务扫完 done", t["status"] == "done", str(summary))
    sigs = ss.query_signals(tid, page_size=100)
    check("信号落库非空", sigs["total"] >= 1, str(sigs["total"]))
    if sigs["items"]:
        s = sigs["items"][0]
        check("信号行携带 payload 基底特征", set(s["payload"]) >= {
            "a_date", "p_date", "entry_mode", "spring", "drift_bucket",
            "wick_box", "box_days", "b_bar_time"}, str(set(s["payload"]))[:120])
        check("signal_date = B 日口径", s["signal_date"] >= "1990-01-01")
        check("信号 state ∈ 三态", s["state"] in ("triggered", "running", "expired"), s["state"])
        check("params_version = 1", s["params_version"] == 1)

    # ---- 重扫幂等（done 任务重跑无新扫描；水位门生效）----
    again = run_task(tid)
    check("重扫幂等（无新扫描）", again["scanned"] == 0, str(again))

    # ---- kv 统计正确性（3.1 verify：对已知信号集手工重算比对）----
    kv = ss.compute_vp_entry_kv_stats(tid)
    items = ss.query_signals(tid, page_size=500)["items"]
    n = len(items)
    check("kv 信号总数正确", kv["total_signals"] == n, f"{kv['total_signals']} vs {n}")
    n_minute = sum(1 for it in items if it["payload"].get("entry_mode") == "minute")
    n_alive = sum(1 for it in items if it["state"] == "triggered")
    check("kv 存活数正确（state=triggered）", kv["alive_signals"] == n_alive,
          f"{kv['alive_signals']} vs {n_alive}")
    expect_minute_ratio = f"{n_minute / n * 100:.1f}%" if n else "0.0%"
    check("kv 分钟版占比正确", kv["minute_ratio"] == expect_minute_ratio,
          f"{kv['minute_ratio']} vs {expect_minute_ratio} (minute={n_minute}/{n})")
    n_spring = sum(1 for it in items if it["payload"].get("spring"))
    check("kv spring 占比正确", kv["spring_ratio"] == (f"{n_spring / n * 100:.1f}%" if n else "0.0%"),
          f"{kv['spring_ratio']} spring={n_spring}/{n}")
    wicks = [it["payload"]["wick_box"] for it in items
             if isinstance(it["payload"].get("wick_box"), (int, float))]
    if wicks:
        check("kv 平均影线盒宽正确", abs(kv["avg_wick_box"] - round(sum(wicks) / len(wicks), 4)) < 1e-9,
              f"{kv['avg_wick_box']}")
    buckets = {"low": 0, "mid": 0, "high": 0}
    for it in items:
        b = it["payload"].get("drift_bucket")
        if b in buckets:
            buckets[b] += 1
    check("kv 三桶漂移分布正确",
          (kv["drift_low_ratio"], kv["drift_mid_ratio"], kv["drift_high_ratio"]) ==
          tuple(f"{buckets[k] / n * 100:.1f}%" if n else "0.0%" for k in ("low", "mid", "high")),
          str((kv["drift_low_ratio"], buckets)))

    # ---- detail API kv 块挂接（路由层）----
    from WebAPI.routers.strategy import strategy_task_detail

    detail = None

    class _Q:
        pass

    import asyncio

    detail = asyncio.run(strategy_task_detail(tid))
    check("detail 返回 kv_payload", isinstance(detail.get("kv_payload"), dict) and
          detail["kv_payload"].get("total_signals") == n,
          str(detail.get("kv_payload")))
    check("detail definition 四积木", [b["type"] for b in detail["definition"]["detail_schema"]] ==
          ["summary", "per_stock", "signals", "kv"])
    check("detail per_stock（显式范围）", "per_stock" in detail)

    # ---- 信号加监控走 strategy 来源回查（3.2 verify）----
    from WebAPI import monitor_store as ms

    if sigs["items"]:
        sig = sigs["items"][0]
        mon = ms.create_monitor(
            code=sig["code"], kl_type="K_DAY",
            entry_price=sig["entry_ref_price"] or 10.0,
            monitor_start_time=sig["signal_date"] + " 00:00:00",
            source_type="strategy", task_id=tid, signal_date=sig["signal_date"],
        )
        check("vp 信号加监控成功", mon is not None and mon.get("task_id") == tid, str(mon)[:100])
        back = ss.get_signal_for_monitor(tid, sig["signal_date"], sig["code"])
        check("strategy 来源回查定位信号", back is not None and back.get("state") == sig["state"], str(back))
        mine = [m for m in ms.list_monitoring() if m.get("task_id") == tid]
        check("监控列表含 vp_entry 来源行", len(mine) > 0)
        if mine:
            label = mine[0].get("strategy_label") or ""
            check("来源标签含策略名/任务名", "量价三段式买点" in label and "vp_entry_smoke_main" in label, label)
            ms.end_monitor(mine[0]["id"])

    # ---- 转正（vp_entry 任务进入 persistent 调度集）----
    promoted = ss.promote_task(tid)
    check("vp 任务转正 persistent", promoted["mode"] == "persistent")
    check("纳入 persistent 调度集", any(x["id"] == tid for x in ss.list_persistent_tasks()))

    # ---- 清理 ----
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("DELETE FROM monitor WHERE task_id = %s", (tid,))
    cur.execute("DELETE FROM strategy_signal WHERE task_id = %s", (tid,))
    cur.execute("DELETE FROM strategy_task_stock_result WHERE task_id = %s", (tid,))
    cur.execute("DELETE FROM strategy_scan_cursor WHERE task_id = %s", (tid,))
    cur.execute("DELETE FROM strategy_task WHERE id = %s", (tid,))
    conn.close()


def main():
    print("=" * 70)
    print("vp_entry 策略引擎冒烟（vp-entry-strategy-integration tasks 2.1/2.2/3.1/3.2）")
    print("=" * 70)
    print("\n== 2.1/2.2 引擎扫描行为（内存构造） ==")
    test_scan_series_daily_fallback()
    test_scan_series_minute()
    test_state_replay_triggered_kept()
    test_watermark_gate()
    print("\n== 3.1/3.2 任务全生命周期 + kv 统计（真 PG + DuckDB） ==")
    test_task_lifecycle()
    print(f"\n===== 结果：{len(PASS)} 通过 / {len(FAIL)} 失败 =====")
    for f in FAIL:
        print("  FAIL:", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
