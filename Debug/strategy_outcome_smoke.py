# -*- coding: utf-8 -*-
"""
strategy-signal-outcome 后端冒烟测试（任务 1.2 / 1.3 / 2.1 / 2.2 / 2.3 /
3.1 / 4.1 / 4.2 verify + 6.x 返工 6.1/6.2/6.5/6.8/6.9 verify）。

真 PG（127.0.0.1:5432/chan）+ 真 DuckDB（Data/kl_store.duckdb）：

1. compute_outcome 三态（1.2）：内存构造序列断言 success/failed/pending
2. upsert 绩效落库 + frozen 保护（1.3）：upsert_signals 绩效四字段写入、
   frozen 行绩效不覆盖
3. vol_breakout 量能峰锚定（2.1）：冲高回落（次日量 97%）expired→triggered、
   持续放量仍 expired、破位仍 expired；6.8 中段低点序列（pullback_days
   实际值 + ret_7d 从低点日起算）；6.2 B 日 OHLC
4. a_pct_min 参数化（2.2）：0.098 与旧口径 33 事件一致（回归锚点）、
   默认 0.05 事件数增加
5. 真实数据绩效（2.3）：sz.000001 重放，2024-02-21 新口径演进为 triggered/
   running 且带绩效四字段与 A/B 点过程字段（含 b_open/b_close/b_day_pct）
6. vp_entry 绩效（3.1）：内存构造分钟版/日线版各断言绩效与过程字段（6.2
   补 B 日 OHLC 断言）
7. matched_only 过滤（4.1）：expired 行被过滤、行透传绩效四字段
8. kv 准确率口径（4.2）：accuracy = success/(success+failed)、
   pending 不入分母；6.5 detail kv 无三个形态统计键；6.1/6.9 声明断言
   （price_pct 合并列 / precision/step 白话 desc）

运行（项目根目录）：
    PG_DSN="host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres" \
    .venv/Scripts/python -X utf8 Debug/strategy_outcome_smoke.py
"""

import asyncio
import datetime
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
# 1.2 compute_outcome 三态
# ----------------------------------------------------------------------

def test_compute_outcome():
    from WebAPI.strategy_engines import compute_outcome

    def mk(n):
        return [(f"2024-01-{i + 1:02d} 00:00:00", 10.0, 10.0, 10.0, 10.0, 100.0)
                for i in range(n)]

    def setc(kl, idx, c):
        kl[idx] = (kl[idx][0], c, c, c, c, 100.0)

    # success：entry_idx=10, price=10 → +7(+10%)/+14(+2%)/+30(+9%)
    # D13 加权：总收益 = 10%×0.5 + 2%×0.3 + 9%×0.2 = 7.4% > 5%
    kl = mk(45)
    setc(kl, 17, 11.0)
    setc(kl, 24, 10.2)
    setc(kl, 40, 10.9)
    r = compute_outcome(10, 10.0, kl)
    check("1.2 success 态", r[3] == "success", str(r))
    check("1.2 ret_7d 数值", abs(r[0] - 0.1) < 1e-9, str(r[0]))
    check("1.2 close_7d 过程字段", r[4] == 11.0, str(r[4]))

    # failed：+4% / +2% / -1% → 总收益 = 2% + 0.6% - 0.2% = 2.4% ≤ 5%
    kl2 = mk(45)
    setc(kl2, 17, 10.4)
    setc(kl2, 24, 10.2)
    setc(kl2, 40, 9.9)
    r2 = compute_outcome(10, 10.0, kl2)
    check("1.2 failed 态", r2[3] == "failed", str(r2[3]))

    # 口径迁移断言（D13）：+10% / +1% / -3% → 总收益 = 5% + 0.3% - 0.6% = 4.7% ≤ 5%
    # 旧「两时段 >8%」与新加权口径均判 failed——换 +10%/+1%/+1% 构造真迁移：
    # 旧口径（仅 7 日 >8%）判 failed，新加权总收益 = 5% + 0.3% + 0.2% = 5.5% > 5% 判 success
    kl_mig = mk(45)
    setc(kl_mig, 17, 11.0)
    setc(kl_mig, 24, 10.1)
    setc(kl_mig, 40, 10.1)
    r_mig = compute_outcome(10, 10.0, kl_mig)
    check("1.2 口径迁移（5.5% 加权 > 5%）", r_mig[3] == "success", str(r_mig[3]))

    # pending：仅 18 根 → 只 +7 可得（三时段不齐 → pending，D13：齐全才判）
    kl3 = mk(18)
    setc(kl3, 17, 11.0)
    r3 = compute_outcome(10, 10.0, kl3)
    check("1.2 pending 态（可得<2）", r3[3] == "pending", str(r3[3]))
    check("1.2 越界收盘价为 None", r3[1] is None and r3[2] is None
          and r3[5] is None and r3[6] is None, str(r3))


# ----------------------------------------------------------------------
# 2.1 量能峰锚定（内存构造 K 线直测 _scan_series）
# ----------------------------------------------------------------------

def _mk_bar(date, o, h, low, c, v):
    return (f"{date} 00:00:00", o, h, low, c, v)


def _vol_series(adjust, tail=None, base_vol=100.0, base_close=10.0):
    """30 根平稳历史 + A 日 + 调整序列 + tail。

    adjust: [(ret, vol_ratio, close_lt_open), ...] —— A+1 起逐日
    （close_lt_open=True 时构造收盘 < A 日开盘触发破位）。
    A 日：close=base*1.10（涨幅 10% ≥ 门槛）、vol=300（3 倍于 100 均量）。
    """
    kl = []
    d0 = datetime.date(2024, 4, 1)
    n_hist = 25
    for i in range(n_hist):
        d = (d0 + datetime.timedelta(days=i)).isoformat()
        c = base_close * (1 + 0.001 * (1 if i % 2 == 0 else -1))
        kl.append(_mk_bar(d, base_close, max(base_close, c) + 0.02, min(base_close, c) - 0.02, c, base_vol))
    a_date = (d0 + datetime.timedelta(days=n_hist)).isoformat()
    prev_close = kl[-1][4]
    a_close = prev_close * 1.10
    a_open = prev_close * 1.01
    kl.append(_mk_bar(a_date, a_open, a_close * 1.005, a_open * 0.99, a_close, 300.0))
    cur = a_close
    day = n_hist + 1
    for ret, vr, breach in adjust:
        d = (d0 + datetime.timedelta(days=day)).isoformat()
        prev = cur
        cur = cur * (1 + ret)
        if breach:
            c = a_open * 0.97  # 收盘 < A 日开盘 → 破位
        else:
            c = cur
        kl.append(_mk_bar(d, prev, max(prev, c) * 1.001, min(prev, c) * 0.999, c, 300.0 * vr))
        day += 1
    for t in (tail or []):
        kl.append(_mk_bar((d0 + datetime.timedelta(days=day)).isoformat(),
                          t, t * 1.001, t * 0.999, t, 30.0))
        day += 1
    return kl, a_open


def _ev_7d_lowpoint(kl, idx_low, ev):
    """6.8 辅助：期望 ret_7d = kl[idx_low+7].close / entry_ref - 1。"""
    c7 = kl[idx_low + 7][4]
    return ev["ret_7d"] - (c7 / ev["entry_ref_price"] - 1.0)


def test_peak_anchor():
    from WebAPI.strategy_engines.vol_breakout import VolBreakoutPullbackEngine

    eng = VolBreakoutPullbackEngine()
    # 缩量阈值取 0.3（峰锚阈值 0.8 定死不可配；若 shrink_max 也取 0.8，
    # 任何「不缩量」的日自动也是峰日，D' 永远不含失败日，场景 2 无法构造）
    params = {"pullback_max_days": 5, "volume_ratio_min": 2.0,
              "volume_shrink_max": 0.3, "a_pct_min": 0.098}

    # 场景 1 冲高回落：A+1 量 97%（≥0.8×A 量，成峰 P=A+1），A+2..A+5 缩量 25%
    # 旧口径：A+1 量 97% ≥ 0.8×A → 缩量失败 expired；新口径：P 锚定 A+1，
    # D'=A+2..A+5 全缩量 → triggered
    kl, a_open = _vol_series([
        (0.02, 0.97, False),
        (-0.015, 0.25, False),
        (-0.015, 0.25, False),
        (-0.015, 0.25, False),
        (-0.015, 0.25, False),
    ], tail=[9.8] * 10)
    evs = eng._scan_series("sz.test1", kl, params)
    check("2.1 冲高回落 expired→triggered", len(evs) == 1 and evs[0]["state"] == "triggered",
          str([(e["signal_date"], e["state"]) for e in evs]))
    if evs:
        ev = evs[0]
        check("2.1 triggered 带绩效四键", ev["outcome"] is not None and ev["ret_7d"] is not None,
              str((ev["ret_7d"], ev["outcome"])))
        check("2.1 payload A/B 点字段齐", set(ev["payload"]) >= {
            "a_date", "a_close", "a_pct", "b_date", "b_open", "b_close", "b_day_pct",
            "close_7d", "close_14d", "close_30d"},
            str(sorted(ev["payload"])))
        # 构造口径：25 根历史（2024-04-01 起）+ A 日 + 5 回调日；A+1 冲高 +2%、
        # A+2..A+5 各 -1.5% 单调回落 → 窗口最低收盘出现在窗口末 A+5（索引 30）
        # = 2024-05-01；b_date = 最低收盘出现日（6.8 新口径）
        check("2.1 b_date = 窗口最低收盘出现日", ev["payload"]["b_date"] == "2024-05-01"
              and ev["payload"]["a_date"] == "2024-04-26",
              str((ev["payload"]["a_date"], ev["payload"]["b_date"])))
        # 6.2：B 日 OHLC（b_close 与 entry_ref 同源同值、b_day_pct = 收/开-1）
        check("6.2 b_close 与 entry_ref 同源同值",
              abs(ev["payload"]["b_close"] - ev["entry_ref_price"]) < 5e-4,
              str((ev["payload"]["b_close"], ev["entry_ref_price"])))
        b_open = ev["payload"]["b_open"]
        check("6.2 b_day_pct 口径", ev["payload"]["b_day_pct"] is not None
              and abs(ev["payload"]["b_day_pct"]
                      - (ev["payload"]["b_close"] / b_open - 1)) < 1e-4,
              str((b_open, ev["payload"]["b_close"], ev["payload"]["b_day_pct"])))
        # 6.8：单调回落序列最低收盘在窗口末 → pullback_days = 窗口长（5）
        check("6.8 低点在窗口末时 pullback_days = 5",
              ev["payload"]["pullback_days"] == 5, str(ev["payload"]["pullback_days"]))

    # 场景 1b（6.8）：低点出现在窗口中段——A+2 冲高后 A+3 深跌到低点，
    # A+4/A+5 回升 → min_close 在 A+3（索引 28 = 2024-04-29）
    kl_mid, _ = _vol_series([
        (0.02, 0.97, False),
        (-0.015, 0.25, False),
        (-0.06, 0.25, False),   # 深跌日（窗口内最低收盘）
        (0.02, 0.25, False),
        (0.02, 0.25, False),
    ], tail=[9.8] * 10)
    evs_mid = eng._scan_series("sz.test1b", kl_mid, params)
    check("6.8 中段低点序列 triggered", len(evs_mid) == 1
          and evs_mid[0]["state"] == "triggered",
          str([(e["state"]) for e in evs_mid]))
    if evs_mid:
        evm = evs_mid[0]
        pm = evm["payload"]
        check("6.8 pullback_days < pullback_max_days（低点在窗口中段）",
              pm["pullback_days"] == 3, str(pm["pullback_days"]))
        check("6.8 b_date = 低点日（非窗口末）", pm["b_date"] == "2024-04-29",
              str(pm["b_date"]))
        check("6.8 b_close = 窗口最低收盘价",
              abs(pm["b_close"] - evm["entry_ref_price"]) < 5e-4,
              str((pm["b_close"], evm["entry_ref_price"])))
        # 绩效起算从低点日：ret_7d 的 close_7d = kl[min_close_idx + 7] 收盘
        idx_low = 28  # 25 历史 + A 日 + 3 回调日（A+1/A+2/A+3）
        check("6.8 ret_7d 从低点日起算", abs(_ev_7d_lowpoint(kl_mid, idx_low, evm)) < 5e-4,
              str((evm["ret_7d"], evm["payload"]["close_7d"])))

    # 场景 2 量能峰后持续放量：A+3 放量 85% 成峰 P，A+4 量 40%（<0.8 不成峰、
    # ≥0.3 不缩量）→ D' 含失败日 → expired（旧口径同判 expired，非回归）
    kl2, _ = _vol_series([
        (-0.015, 0.25, False),
        (-0.015, 0.25, False),
        (-0.015, 0.85, False),
        (-0.015, 0.40, False),
        (-0.015, 0.25, False),
    ])
    evs2 = eng._scan_series("sz.test2", kl2, params)
    check("2.1 量能峰后放量仍 expired", len(evs2) == 1 and evs2[0]["state"] == "expired",
          str([(e["state"]) for e in evs2]))
    if evs2:
        check("2.1 expired 绩效四键为 None",
              evs2[0]["outcome"] is None and evs2[0]["ret_7d"] is None,
              str((evs2[0]["ret_7d"], evs2[0]["outcome"])))

    # 场景 3 回调破位：任一日收盘 < A 日开盘 → expired（口径不变）
    kl3, a_open3 = _vol_series([
        (-0.015, 0.30, False),
        (-0.015, 0.30, True),   # 破位日
        (-0.015, 0.30, False),
        (-0.015, 0.30, False),
        (-0.015, 0.30, False),
    ])
    evs3 = eng._scan_series("sz.test3", kl3, params)
    check("2.1 破位仍 expired", len(evs3) == 1 and evs3[0]["state"] == "expired",
          str([(e["state"]) for e in evs3]))
    if evs3:
        check("2.1 破位不给入场价", evs3[0]["entry_ref_price"] is None,
              str(evs3[0]["entry_ref_price"]))


# ----------------------------------------------------------------------
# 2.2 a_pct_min 参数化 + 2.3 真实数据绩效（sz.000001 重放）
# ----------------------------------------------------------------------

def test_a_pct_min_and_realdata():
    from WebAPI.strategy_engines.vol_breakout import VolBreakoutPullbackEngine

    eng = VolBreakoutPullbackEngine()
    # 回归锚点：a_pct_min=0.098（原 _LIMIT_UP_PCT 硬编码口径）信号数 = 33
    evs = eng.scan_with_params("sz.000001", {
        "pullback_max_days": 5, "volume_ratio_min": 2.0,
        "volume_shrink_max": 0.8, "a_pct_min": 0.098})
    check("2.2 a_pct_min=0.098 与旧口径一致（33 事件）", len(evs) == 33, str(len(evs)))

    # 默认 0.05：信号集放宽（> 33）
    evs2 = eng.scan_with_params("sz.000001", {})
    check("2.2 默认 a_pct_min=0.05 信号数增加", len(evs2) > 33, str(len(evs2)))

    # 2024-02-21 信号：量能峰锚定豁免了次日 97% 量 → 新口径演进为匹配态
    target = [e for e in evs2 if e["signal_date"] == "2024-02-21"]
    check("2.3 2024-02-21 信号存在", len(target) == 1, str(len(target)))
    if target:
        e = target[0]
        check("2.3 2024-02-21 演进为 triggered/running（原 expired）",
              e["state"] in ("triggered", "running"), e["state"])
        check("2.3 绩效四字段落事件", e["ret_7d"] is not None and e["outcome"] is not None,
              str((e["ret_7d"], e["outcome"])))
        check("2.3 payload 过程字段齐", set(e["payload"]) >= {
            "a_date", "a_close", "a_pct", "b_date", "b_open", "b_close", "b_day_pct",
            "close_7d", "close_14d", "close_30d"},
            str(sorted(e["payload"])))
        check("2.3 b_close 与 entry_ref 同源同值（真实数据）",
              e["payload"]["b_close"] is not None
              and abs(e["payload"]["b_close"] - e["entry_ref_price"]) < 5e-4,
              str((e["payload"]["b_close"], e["entry_ref_price"])))
        check("2.3 a_pct = A 日涨幅", abs(e["payload"]["a_pct"] - 0.0998) < 0.001,
              str(e["payload"]["a_pct"]))

    # 全集口径自检：匹配态 100% 带绩效、expired 100% 无绩效
    n_matched = sum(1 for e in evs2 if e["state"] in ("triggered", "running"))
    n_with = sum(1 for e in evs2 if e["state"] in ("triggered", "running") and e["outcome"] is not None)
    n_expired_clean = all(e["outcome"] is None for e in evs2 if e["state"] == "expired")
    check("2.3 匹配态全带绩效", n_matched > 0 and n_with == n_matched,
          f"{n_with}/{n_matched}")
    check("2.3 expired 态绩效恒 None", n_expired_clean)


# ----------------------------------------------------------------------
# 1.3 / 4.1 / 4.2 store 层（真 PG）
# ----------------------------------------------------------------------

def test_store_layer():
    import psycopg2

    from WebAPI import strategy_store as ss

    label = "strategy_outcome_smoke"
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("""DELETE FROM strategy_signal WHERE task_id IN
                   (SELECT id FROM strategy_task WHERE label LIKE %s)""", (label + "%",))
    cur.execute("""DELETE FROM strategy_task_stock_result WHERE task_id IN
                   (SELECT id FROM strategy_task WHERE label LIKE %s)""", (label + "%",))
    cur.execute("""DELETE FROM strategy_scan_cursor WHERE task_id IN
                   (SELECT id FROM strategy_task WHERE label LIKE %s)""", (label + "%",))
    cur.execute("DELETE FROM strategy_task WHERE label LIKE %s", (label + "%",))
    conn.close()

    task = ss.create_task(
        strategy_id="vol_breakout_pullback",
        label=label,
        params={"pullback_max_days": 5, "volume_ratio_min": 2.0, "volume_shrink_max": 0.8},
        scope_type="manual",
        scope_codes=["sz.000001"],
        mode="test",
    )
    tid = task["id"]
    check("冒烟任务创建（新 params 含 a_pct_min）",
          task["params"].get("a_pct_min") == 0.05, str(task["params"]))

    # 手工 upsert 事件（带绩效）→ 落库验证
    ev_ok = {
        "code": "sz.000001", "signal_date": "2024-02-21", "state": "running",
        "is_buy": True, "entry_ref_price": 8.618, "stop_ref_price": 8.4,
        "ret_7d": 0.10, "ret_14d": 0.02, "ret_30d": 0.09, "outcome": "success",
        "payload": {"a_date": "2024-02-21", "b_date": "2024-02-28"},
    }
    ev_expired = {
        "code": "sz.000001", "signal_date": "2023-01-01", "state": "expired",
        "is_buy": True, "entry_ref_price": None, "stop_ref_price": None,
        "payload": {},
    }
    ss.upsert_signals(tid, [ev_ok, ev_expired], params_version=1)
    sigs = ss.query_signals(tid, page_size=100)
    by_date = {s["signal_date"]: s for s in sigs["items"]}
    check("1.3 upsert 绩效四字段落库",
          by_date["2024-02-21"]["ret_7d"] == 0.10
          and by_date["2024-02-21"]["outcome"] == "success",
          str(by_date.get("2024-02-21")))
    check("1.3 事件缺绩效键 → NULL",
          by_date["2023-01-01"]["outcome"] is None
          and by_date["2023-01-01"]["ret_7d"] is None,
          str(by_date.get("2023-01-01")))

    # 4.1 matched_only：expired 行被过滤
    matched = ss.query_signals(tid, page_size=100, matched_only=True)
    check("4.1 matched_only 过滤 expired", matched["total"] == 1
          and all(s["state"] in ("triggered", "running") for s in matched["items"]),
          f"total={matched['total']}")
    check("4.1 行透传绩效四字段", "ret_7d" in matched["items"][0]
          and "outcome" in matched["items"][0], str(matched["items"][0]))

    # 4.1 幂等：重复 upsert 同键不重复（重扫幂等）
    ev_ok_v2 = dict(ev_ok, ret_7d=0.11, outcome="failed")
    ss.upsert_signals(tid, [ev_ok_v2], params_version=2)
    sigs2 = ss.query_signals(tid, page_size=100)
    by2 = {s["signal_date"]: s for s in sigs2["items"]}
    check("1.3 重扫幂等（同键覆盖不重复）", sigs2["total"] == 2, str(sigs2["total"]))
    check("1.3 绩效幂等覆盖", by2["2024-02-21"]["ret_7d"] == 0.11
          and by2["2024-02-21"]["outcome"] == "failed",
          str(by2["2024-02-21"]))

    # 1.3 frozen 保护：冻结行绩效不覆盖
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("""UPDATE strategy_signal SET frozen = TRUE
                   WHERE task_id = %s AND signal_date = '2024-02-21'""", (tid,))
    conn.close()
    ev_ok_v3 = dict(ev_ok, ret_7d=0.99, outcome="success")
    ss.upsert_signals(tid, [ev_ok_v3], params_version=3)
    sigs3 = ss.query_signals(tid, page_size=100)
    by3 = {s["signal_date"]: s for s in sigs3["items"]}
    check("1.3 frozen 行绩效不覆盖", by3["2024-02-21"]["ret_7d"] == 0.11,
          str(by3["2024-02-21"]))

    # 4.2 kv 准确率口径：当前行（running success=0 / failed=1[frozen]）
    # 注意 frozen 行 outcome='failed' 仍在行上 → kv 统计含 frozen 行（绩效冻结
    # 保留判定）。当前行集：running(failed) 1 条 → accuracy = 0/1 = 0.0
    kv = ss.compute_outcome_kv_stats(tid)
    check("4.2 kv 键集完整", set(kv) >= {"accuracy", "success_cnt", "failed_cnt",
                                        "pending_cnt", "avg_ret_7d"}, str(kv))
    check("4.2 kv 统计口径", kv["success_cnt"] == 0 and kv["failed_cnt"] == 1
          and kv["accuracy"] == 0.0, str(kv))

    # pending 不入分母：追加一条 pending 行 → accuracy 分母不变
    ev_pending = {
        "code": "sz.000001", "signal_date": "2025-01-01", "state": "running",
        "is_buy": True, "entry_ref_price": 10.0, "stop_ref_price": 9.5,
        "ret_7d": 0.05, "ret_14d": None, "ret_30d": None, "outcome": "pending",
        "payload": {},
    }
    ss.upsert_signals(tid, [ev_pending], params_version=1)
    kv2 = ss.compute_outcome_kv_stats(tid)
    check("4.2 pending 不入分母", kv2["pending_cnt"] == 1
          and kv2["failed_cnt"] == 1 and kv2["accuracy"] == 0.0, str(kv2))

    # 4.2 detail API：matched_only 数据源 + kv 通用注入
    from WebAPI.routers.strategy import strategy_task_detail

    detail = asyncio.run(strategy_task_detail(tid))
    states = [r["state"] for r in detail["signals_page"]["list"]]
    check("4.2 detail signals 只含匹配信号", all(s in ("triggered", "running") for s in states),
          str(states))
    check("4.2 detail 行透传绩效", all("outcome" in r for r in detail["signals_page"]["list"]))
    kv_payload = detail.get("kv_payload") or {}
    check("4.2 detail kv_payload 含准确率", "accuracy" in kv_payload
          and "success_cnt" in kv_payload, str(sorted(kv_payload)[:8]))
    check("4.2 detail kv accuracy 口径", kv_payload.get("accuracy") == 0.0,
          str(kv_payload.get("accuracy")))

    # 6.5：detail kv 块无三个形态统计键（D12 返工：声明已删，聚合无产出）
    check("6.5 detail kv 无形态统计三键", not {"first_board_date_hist",
          "avg_volume_ratio", "avg_pullback_days"} & set(kv_payload),
          str(sorted(kv_payload)))

    # 6.1：columns 声明返工（price_pct 合并列，无独立价格/涨幅列）
    from WebAPI.strategy_engines import get_definition, validate_params

    for sid in ("vol_breakout_pullback", "vp_entry"):
        d = get_definition(sid)
        col_keys = {c["key"] for c in d.columns}
        col_types = {c["type"] for c in d.columns}
        price_cols = [c for c in d.columns if c["type"] == "price_pct"]
        check(f"6.1 {sid} 无 first_board_date 列", "first_board_date" not in col_keys)
        check(f"6.1 {sid} 无独立价格/涨幅列", not {"a_close", "b_close", "close_7d",
              "a_pct", "ret_7d", "ret_30d"} & col_keys, str(sorted(col_keys)))
        check(f"6.1 {sid} 合并列声明齐（5 组 price_pct + 双 key）",
              len(price_cols) == 5 and all(
                  "priceKey" in c and "pctKey" in c for c in price_cols),
              str(price_cols))
        check(f"6.1 {sid} 无独立 pct/float 绩效列", "pct" not in col_types,
              str(sorted(col_types)))

    # 6.9：precision/step 声明 + 白话 desc + validate_params 放行
    d = get_definition("vol_breakout_pullback")
    p_a = next(p for p in d.params_schema if p["key"] == "a_pct_min")
    check("6.9 a_pct_min 含 precision/step 声明",
          p_a.get("precision") == 2 and p_a.get("step") == 0.01, str(p_a))
    check("6.9 全部数值参数含 precision/step", all(
        "precision" in p and "step" in p for p in d.params_schema
        if p["type"] in ("int", "float")), str(d.params_schema))
    check("6.9 desc 白话化（无内部术语）", all(
        p.get("desc") and "口径" not in p["desc"] and "量价规则" not in p["desc"]
        for p in d.params_schema))
    normalized, errors = validate_params(d, {"a_pct_min": 0.05})
    check("6.9 validate_params 含 precision/step 声明时校验通过",
          not errors and normalized.get("a_pct_min") == 0.05, str((normalized, errors)))

    # 清理
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("DELETE FROM strategy_signal WHERE task_id = %s", (tid,))
    cur.execute("DELETE FROM strategy_task_stock_result WHERE task_id = %s", (tid,))
    cur.execute("DELETE FROM strategy_scan_cursor WHERE task_id = %s", (tid,))
    cur.execute("DELETE FROM strategy_task WHERE id = %s", (tid,))
    conn.close()


# ----------------------------------------------------------------------
# 3.1 vp_entry 绩效与过程字段（内存构造：分钟版/日线版）
# ----------------------------------------------------------------------

def test_vp_entry_outcome():
    from WebAPI.strategy_engines.vp_entry.engine import VpEntryEngine
    from WebAPI.strategy_engines.vp_entry.signal_rule import DayBar

    def make_history(n, base_close=10.0, vol=100.0, start="2024-01-01"):
        d0 = datetime.date.fromisoformat(start)
        bars = []
        for i in range(n):
            d = (d0 + datetime.timedelta(days=i)).isoformat()
            c = base_close * (1 + 0.002 * (1 if i % 2 == 0 else -1))
            o = base_close
            bars.append(DayBar(d, o, max(o, c) + 0.02, min(o, c) - 0.02, c, vol + (2 if i % 2 == 0 else -2)))
        return bars

    def build_case(v_a=300.0, tail=None):
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
        for ret, vol in [(0.02, 0.9 * v_a), (-0.015, 0.25 * v_a), (-0.015, 0.25 * v_a)]:
            date = (d0 + datetime.timedelta(days=day)).isoformat()
            prev_c = cur
            cur = cur * (1 + ret)
            bars.append(DayBar(date, prev_c, max(prev_c, cur) * 1.001, min(prev_c, cur) * 0.999, cur, vol))
            day += 1
        bars_all = hist + bars + list(tail or [])
        kl = [(b.date, b.open, b.high, b.low, b.close, b.volume) for b in bars_all]
        return hist, bars, kl

    v_a = 300.0
    d0 = datetime.date(2024, 4, 1)

    # ---- 日线版：B+1 买价 + B+2..B+31 后续（绩效可判）----
    _hist, bars, _ = build_case(v_a)
    b_prev_close = bars[-1].close
    d_end3_mean = 0.25 * v_a
    o_b = b_prev_close * 1.015
    c_b = o_b * 1.02
    b_bar = DayBar((d0 + datetime.timedelta(days=11)).isoformat(), o_b,
                   c_b * 1.005, o_b * 0.99, c_b, 3.0 * d_end3_mean)
    o_b1 = c_b * 1.002
    # B+1 买价 o_b1；后续 30 根日线（+7/+14/+30 可得）：先涨后横
    tail = [DayBar((d0 + datetime.timedelta(days=12)).isoformat(), o_b1,
                   o_b1 * 1.03, o_b1 * 0.99, o_b1 * 1.028, 100.0)]
    cur = o_b1 * 1.028
    for i in range(30):
        d = (d0 + datetime.timedelta(days=13 + i)).isoformat()
        prev = cur
        cur = cur * (1 + (0.05 if i == 6 else 0.001))  # +7 日 +5%
        tail.append(DayBar(d, prev, prev * 1.001, prev * 0.999, cur, 50.0))
    _, _, kl = build_case(v_a, tail=[b_bar] + tail)

    class _EmptyStore:
        def execute(self, sql, params=None):
            return []

    eng = VpEntryEngine()
    events = eng._scan_series(_EmptyStore(), "sz.daily", kl, "QFQ",
                              {"cv7_max": 0.25, "box_width_max": 0.12,
                               "n_max": 7, "stop_loss": 0.12, "vol_gate": "mean"})
    check("3.1 日线版触发", len(events) == 1, str(len(events)))
    if events:
        ev = events[0]
        p = ev["payload"]
        check("3.1 日线版绩效四键", ev["ret_7d"] is not None and ev["outcome"] is not None,
              str((ev["ret_7d"], ev["outcome"])))
        check("3.1 日线版入场日 = B+1（b_date）", p.get("b_date") ==
              (d0 + datetime.timedelta(days=12)).isoformat(), str(p.get("b_date")))
        check("3.1 日线版过程字段齐", set(p) >= {
            "a_close", "a_pct", "b_date", "b_open", "b_close", "b_day_pct",
            "close_7d", "close_14d", "close_30d"},
            str(sorted(p)))
        # 6.2：日线版 B 日（= B+1）OHLC；b_day_pct = 收/开 - 1
        check("6.2 vp 日线版 B 日 OHLC 齐", p.get("b_open") is not None
              and p.get("b_close") is not None and p.get("b_day_pct") is not None,
              str((p.get("b_open"), p.get("b_close"), p.get("b_day_pct"))))
        # 绩效复算：+7 收盘 = o_b1*1.028*1.05*1.001^0（构造口径）……直接断言非空即可
        check("3.1 日线版 close_7d 非空", p.get("close_7d") is not None, str(p.get("close_7d")))

    # ---- 分钟版：B 日触发（买价 = 触发分钟收盘），后续日线供绩效 ----
    _hist, bars, _ = build_case(v_a)
    b_date = (d0 + datetime.timedelta(days=11)).isoformat()
    o_b2 = bars[-1].close * 1.015
    c_b2 = o_b2 * 1.02
    b_bar2 = DayBar(b_date, o_b2, c_b2 * 1.005, o_b2 * 0.99, c_b2, 3.0 * 0.25 * v_a)
    # B+1..B+30 后续（微涨 +7 日 +10%）
    cur = c_b2
    tail2 = []
    for i in range(30):
        d = (d0 + datetime.timedelta(days=12 + i)).isoformat()
        prev = cur
        cur = cur * (1 + (0.10 if i == 6 else 0.001))
        tail2.append(DayBar(d, prev, prev * 1.001, prev * 0.999, cur, 100.0))
    _, _, kl2 = build_case(v_a, tail=[b_bar2] + tail2)

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
    hist_rows = []
    d0f = datetime.date(2024, 1, 1)
    for k in range(60):
        d = (d0f + datetime.timedelta(days=k)).isoformat()
        for t in times:
            hist_rows.append((f"{d} {t}:00", 10.0, 10.1, 9.9, 10.0, 100.0))
    b_minute = []
    for i, t in enumerate(times):
        r = 0.02 * (i / 6) if i <= 6 else 0.02
        c = bars[-1].close * (1 + r)
        v = 400.0 if i == 6 else 20.0
        b_minute.append((f"{b_date} {t}:00", c * 0.999, c * 1.001, c * 0.998, c, v))

    class _MinuteStore:
        def execute(self, sql, params=None):
            sql_l = sql.replace("\n", " ")
            if "SUBSTR(time_key, 1, 10) = ?" in sql_l:
                day = params[3]
                return b_minute if day == b_date else []
            if "SUBSTR(time_key, 1, 10) < ?" in sql_l:
                return hist_rows
            raise AssertionError(f"意外 SQL: {sql_l[:80]}")

    events2 = eng._scan_series(_MinuteStore(), "sz.minute", kl2, "QFQ",
                               {"cv7_max": 0.25, "box_width_max": 0.12,
                                "n_max": 7, "stop_loss": 0.12, "vol_gate": "mean"})
    check("3.1 分钟版触发", len(events2) == 1
          and events2[0]["payload"]["entry_mode"] == "minute", str(len(events2)))
    if events2:
        ev2 = events2[0]
        p2 = ev2["payload"]
        check("3.1 分钟版绩效四键", ev2["ret_7d"] is not None and ev2["outcome"] is not None,
              str((ev2["ret_7d"], ev2["outcome"])))
        check("3.1 分钟版入场日 = B 日（b_date）", p2.get("b_date") == b_date, str(p2.get("b_date")))
        check("3.1 分钟版过程字段齐", set(p2) >= {
            "a_close", "a_pct", "b_date", "b_open", "b_close", "b_day_pct",
            "close_7d", "close_14d", "close_30d"},
            str(sorted(p2)))
        # 6.2：分钟版 B 日（= B 日日线 bar）OHLC；b_close = B 日日线收盘
        check("6.2 vp 分钟版 B 日 OHLC 齐", p2.get("b_open") is not None
              and p2.get("b_close") is not None and p2.get("b_day_pct") is not None,
              str((p2.get("b_open"), p2.get("b_close"), p2.get("b_day_pct"))))
        # 分钟版买价 = 触发分钟收盘（B 前一日收 ×1.02）；+7 日日线收盘基于
        # B 日收 ×1.02 复利再涨 10% → ret_7d ≈ 1.02×1.10−1 ≈ 12.2%
        check("3.1 分钟版 ret_7d 口径（分钟买价复利）", abs(ev2["ret_7d"] - 0.122) < 0.01,
              str(ev2["ret_7d"]))


def main():
    print("=" * 70)
    print("strategy-signal-outcome 后端冒烟（tasks 1.2/1.3/2.1/2.2/2.3/3.1/4.1/4.2）")
    print("=" * 70)
    print("\n== 1.2 compute_outcome 三态 ==")
    test_compute_outcome()
    print("\n== 2.1 量能峰锚定（冲高豁免） ==")
    test_peak_anchor()
    print("\n== 2.2/2.3 a_pct_min 参数化 + sz.000001 真实数据 ==")
    test_a_pct_min_and_realdata()
    print("\n== 3.1 vp_entry 绩效与过程字段 ==")
    test_vp_entry_outcome()
    print("\n== 1.3/4.1/4.2 store 层 + detail API（真 PG） ==")
    test_store_layer()
    print(f"\n===== 结果：{len(PASS)} 通过 / {len(FAIL)} 失败 =====")
    for f in FAIL:
        print("  FAIL:", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
