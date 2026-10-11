# -*- coding: utf-8 -*-
"""回测 CLI 入口（tasks 5.1）。

用法（项目根目录，零网络——全部数据来自本地 DuckDB）：
    .venv/Scripts/python.exe -X utf8 Debug/vp_entry/run_backtest.py \
        --codes sh.600000,sz.000001 --begin 2024-01-01 --end 2024-12-31 \
        [--out-dir Debug/vp_entry/reports/smoke] \
        [--cv7 0.25] [--box 0.12] [--n 7] [--stop 0.12] [--gate mean]

流程：DuckDB 读日线（+可得时读 5 分钟）→ 状态机逐股扫描 → B 候选终判
（该股该日有 K_5M 数据 → 分钟版触发（F(t) 用该股 B 日前 60 个完整分钟
样本日构造）；无 → 日线退化版）→ evaluate_exits 六口径 → compute_stats
分组统计 → 随机/等权基准 → CSV 明细 + Markdown 汇总落 out-dir。

时间窗语义：begin/end 过滤的是 B 日（信号触发日）——A 日可在 begin 前
（历史回看由 DuckDB 全量数据供给，状态机喂入 begin 前的全部历史以满足
61 根次新门槛与 MA60V 窗口）。
"""

import argparse
import logging
import os
import sys

# 支持两种启动：项目根目录直接跑脚本，或 python -m Debug.vp_entry.run_backtest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import duckdb
import pandas as pd

from Debug.vp_entry.backtest import (equal_weight_baseline, evaluate_exits,
                                     compute_stats, random_baseline)
from Debug.vp_entry.sensitivity import assert_scan_params, run_sensitivity
from WebAPI.strategy_engines.vp_entry.params import VPParams
from WebAPI.strategy_engines.vp_entry.signal_rule import DayBar, VPStateMachine
from WebAPI.strategy_engines.vp_entry.vp_volume import build_f_ratio

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("vp_run")

DB_PATH_DEFAULT = "Data/kl_store.duckdb"


def load_daily(conn, codes=None, begin=None, end=None, autype="QFQ") -> pd.DataFrame:
    """读全量日线（不做时间窗截断——窗口语义是过滤 B 日，历史要完整）。"""
    sql = ("SELECT code, time_key, open, high, low, close, volume FROM kline "
           "WHERE kl_type='K_DAY' AND autype=?")
    args = [autype]
    if codes:
        sql += " AND code IN (" + ",".join("?" * len(codes)) + ")"
        args += list(codes)
    df = conn.execute(sql, args).fetchdf()
    return df.sort_values(["code", "time_key"]).reset_index(drop=True)


def load_minute(conn, code, day, autype="QFQ") -> pd.DataFrame | None:
    """读某股某日 5 分钟数据；该日无行返回 None（→ 日线退化版）。"""
    df = conn.execute(
        "SELECT time_key, open, high, low, close, volume FROM kline "
        "WHERE kl_type='K_5M' AND autype=? AND code=? "
        "AND SUBSTR(time_key, 1, 10) = ?", [autype, code, day]).fetchdf()
    return df if len(df) else None


def load_minute_history(conn, code, end_day, autype="QFQ") -> pd.DataFrame:
    """读某股 end_day 之前的全部 5 分钟数据（F(t) 构造用，按日升序）。"""
    return conn.execute(
        "SELECT time_key, open, high, low, close, volume FROM kline "
        "WHERE kl_type='K_5M' AND autype=? AND code=? AND SUBSTR(time_key, 1, 10) < ?",
        [autype, code, end_day]).fetchdf()


def scan_signals(daily: pd.DataFrame, conn, params: VPParams,
                 begin: str | None, end: str | None, use_minute=True) -> list:
    """全池状态机扫描。返回 SignalEvent 列表（日线版买价已回填）。"""
    signals = []
    for code, g in daily.groupby("code"):
        g = g.sort_values("time_key")
        m = VPStateMachine(code=code, params=params)
        f_ratio_cache: dict[str, dict] = {}  # F(t) 按 B 日缓存（每 B 日构造一次）
        pending = None
        for row in g.itertuples(index=False):
            d = str(row.time_key)[:10]
            bar = DayBar(d, row.open, row.high, row.low, row.close, row.volume)
            if pending is not None:
                # 该候选日窗口过滤（窗口语义：过滤 B 日）
                in_window = ((begin is None or d >= begin) and
                             (end is None or d <= end))
                if in_window:
                    if use_minute:
                        mdf = load_minute(conn, code, d)
                        if mdf is not None and len(mdf) > 0:
                            hist = load_minute_history(conn, code, d)
                            if d not in f_ratio_cache:
                                try:
                                    f_ratio_cache[d] = build_f_ratio(hist) if len(hist) else None
                                except ValueError:
                                    f_ratio_cache[d] = None
                            f_ratio = f_ratio_cache.get(d)
                            m.decide_b_day(pending, minute_df=mdf, f_ratio=f_ratio)
                        else:
                            m.decide_b_day(pending, minute_df=None)
                    else:
                        m.decide_b_day(pending, minute_df=None)
                else:
                    m.decide_b_day(pending, minute_df=None)  # 窗口外仍按无分钟推进
                pending = None
            ev = m.on_day(bar)
            if ev is not None:
                pending = ev
        if pending is not None:
            m.decide_b_day(pending, minute_df=None)
        signals.extend(m.signals)
        f_ratio_cache.clear()
    return signals


def fmt_pct(x) -> str:
    return "—" if x is None or pd.isna(x) else f"{x * 100:.2f}%"


def write_report(out_dir: str, params: VPParams, trades: pd.DataFrame,
                 stats: pd.DataFrame, signals: pd.DataFrame,
                 baseline: dict, eq_baseline: float,
                 begin=None, end=None, codes_desc="",
                 curve: pd.DataFrame | None = None) -> None:
    """5.2 的报告骨架：CSV 明细 + Markdown 汇总（四区块之常态三块；
    敏感性扫描为独立入口，报告在 5.2 汇总）。"""
    os.makedirs(out_dir, exist_ok=True)
    trades.to_csv(os.path.join(out_dir, "trades.csv"), index=False,
                  encoding="utf-8-sig")
    if signals is not None and len(signals):
        signals.to_csv(os.path.join(out_dir, "signals.csv"), index=False,
                       encoding="utf-8-sig")
    stats.to_csv(os.path.join(out_dir, "stats.csv"), index=False,
                 encoding="utf-8-sig")

    # 基准对照判定：策略 T+10 均值 vs 随机 CI95
    t10 = trades[trades["exit_method"] == "T+10"] if len(trades) else pd.DataFrame()
    strategy_mean = float(t10["ret"].mean()) if len(t10) else float("nan")
    lo, hi = baseline.get("ci95", (float("nan"), float("nan")))
    excess = (strategy_mean > hi) if not pd.isna(strategy_mean) and not pd.isna(hi) else None
    verdict = ("**显著超额**（策略 T+10 均值高于随机基准 95% CI 上界）" if excess
               else "**无显著超额**——策略 T+10 均值未越过随机基准 95% CI 上界，"
                    "收益可能来自市场共性而非选股能力")

    lines = [
        "# 量价三段式买点 回测报告", "",
        f"- 参数：{params.describe()}",
        f"- 股票池：{codes_desc}",
        f"- 时间窗（B 日过滤）：{begin or '不限'} ~ {end or '不限'}",
        f"- 信号数：{len(signals) if signals is not None else 0}"
        "（分钟版 / 日线退化版分列见 stats.csv 的 entry_mode 分组）", "",
        "## 一、五口径离场绩效", "",
        "| 口径 | n | 胜率 | 均值 | 中位 | 盈亏比 | 平均持有 |",
        "|---|---|---|---|---|---|---|",
    ]
    if len(stats):
        for r in stats.itertuples(index=False):
            if r.group.startswith("exit="):
                plr = (f"{r.profit_loss_ratio:.2f}" if not pd.isna(r.profit_loss_ratio)
                       else "—")
                lines.append(
                    f"| {r.group[5:]} | {r.n} | {fmt_pct(r.win_rate)} | "
                    f"{fmt_pct(r.mean_ret)} | {fmt_pct(r.median_ret)} | "
                    f"{plr} | {r.mean_hold_days:.1f} |")
    lines += ["", "## 二、分组统计（spring / 基底桶 / 分钟vs日线 / 量能门）", ""]
    if len(stats):
        for r in stats.itertuples(index=False):
            if not r.group.startswith("exit="):
                lines.append(
                    f"- {r.group}: n={r.n} 胜率={fmt_pct(r.win_rate)} "
                    f"均值={fmt_pct(r.mean_ret)}")
    lines += ["", "## 三、基准对照", "",
              f"- 随机买入基准（95% CI）：均值 {fmt_pct(baseline.get('mean'))}，"
              f"区间 [{fmt_pct(lo)}, {fmt_pct(hi)}]",
              f"- 等权基准（持有 10 日）：{fmt_pct(eq_baseline)}",
              f"- 策略 T+10 口径均值：{fmt_pct(strategy_mean)}",
              f"- 超额（策略 - 随机基准均值）："
              f"{fmt_pct(strategy_mean - baseline.get('mean', float('nan')))}；"
              f"超额（策略 - 等权基准）："
              f"{fmt_pct(strategy_mean - eq_baseline)}",
              f"- 结论：{verdict}", ""]
    # ---- 第四区块：敏感性扫描（--scan 时产出） ----
    lines += ["## 四、敏感性扫描（108 组合）", ""]
    if curve is None or curve.empty:
        lines += ["本报告未运行敏感性扫描（加 --scan 参数产出）。", ""]
    else:
        all_rows = curve[curve["exit_method"] == "ALL"]
        n_cliff = int((all_rows["is_cliff"].astype(str) != "").sum())
        lines += [
            f"- 组合数：108（CV7 3×N 3×R_W 3×止损 2×量能门 2），全本地零网络",
            f"- 信号数范围：{int(all_rows['n_signals'].min())} ~ "
            f"{int(all_rows['n_signals'].max())}",
            f"- T+10 均值范围：{fmt_pct(all_rows['mean_ret_T10'].min())} ~ "
            f"{fmt_pct(all_rows['mean_ret_T10'].max())}",
            f"- 悬崖标记组合：{n_cliff} 个"
            "（相邻档位信号数变化 ≥40% 或 T+10 均值变化 ≥5pp，"
            "标记明细见 sensitivity_curve.csv 的 is_cliff 列）",
            "",
            "**默认参数组**（当前回测参数）：",
            "",
        ]
        cur = all_rows[
            (all_rows["cv7_max"] == params.cv7_max) &
            (all_rows["box_width_max"] == params.box_width_max) &
            (all_rows["n_max"] == params.n_max) &
            (all_rows["stop_loss"] == params.stop_loss) &
            (all_rows["vol_gate"] == params.vol_gate)]
        for r in cur.itertuples(index=False):
            lines.append(f"- 信号 {r.n_signals} 个，胜率 {fmt_pct(r.win_rate)}，"
                         f"T+10 均值 {fmt_pct(r.mean_ret)}")
        lines += ["", "绩效-参数全曲线见 sensitivity_curve.csv（含 is_cliff 标记）。", ""]
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="量价三段式买点回测 CLI")
    ap.add_argument("--codes", default=None, help="逗号分隔股票代码（缺省用全库）")
    ap.add_argument("--db", default=DB_PATH_DEFAULT, help="DuckDB 路径")
    ap.add_argument("--begin", default=None, help="时间窗起点（过滤 B 日）")
    ap.add_argument("--end", default=None, help="时间窗终点（过滤 B 日）")
    ap.add_argument("--out-dir", default="Debug/vp_entry/reports/run", help="输出目录")
    ap.add_argument("--cv7", type=float, default=0.25, choices=[0.20, 0.25, 0.30])
    ap.add_argument("--box", type=float, default=0.12, choices=[0.10, 0.12, 0.15])
    ap.add_argument("-n", "--n", dest="n", type=int, default=7, choices=[5, 7, 9])
    ap.add_argument("--stop", type=float, default=0.12, choices=[0.08, 0.12])
    ap.add_argument("--gate", default="mean", choices=["mean", "strict"])
    ap.add_argument("--no-minute", action="store_true",
                    help="禁用分钟版触发（全部走日线退化版）")
    ap.add_argument("--scan", action="store_true",
                    help="附加 108 组合敏感性扫描（第四区块 + sensitivity_curve.csv，全本地）")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    params = VPParams(cv7_max=args.cv7, box_width_max=args.box, n_max=args.n,
                      stop_loss=args.stop, vol_gate=args.gate)
    assert_scan_params(params)  # 敏感性集合纪律（CLI choices 之外再显式校验）
    codes = args.codes.split(",") if args.codes else None
    log.info("参数：%s | 池：%s | 窗口：%s~%s", params.describe(),
             codes or "全库", args.begin or "不限", args.end or "不限")

    conn = duckdb.connect(args.db, read_only=True)
    try:
        daily = load_daily(conn, codes=codes)
        if daily.empty:
            log.error("DuckDB 无匹配日线数据（codes=%s）", codes)
            return 1
        signals = scan_signals(daily, conn, params, args.begin, args.end,
                               use_minute=not args.no_minute)
    finally:
        conn.close()

    if not signals:
        log.warning("窗口内无信号；产出空报表")
        sig_df = pd.DataFrame()
        trades = pd.DataFrame()
    else:
        sig_df = pd.DataFrame([vars(s) for s in signals])
        trades = evaluate_exits(sig_df, daily, params)
    stats = compute_stats(trades)
    baseline = random_baseline(daily, n_signals=max(len(sig_df), 1), hold=10,
                               n_samples=200)
    eq = equal_weight_baseline(daily, hold=10)

    codes_desc = (f"{len(codes)} 只指定股票" if codes
                  else f"全库 {daily['code'].nunique()} 只")
    # 敏感性扫描（--scan，全本地零网络）
    curve = None
    if args.scan:
        log.info("敏感性扫描启动（108 组合，全本地）……")
        curve = run_sensitivity(daily, progress_every=36)
        curve.to_csv(os.path.join(args.out_dir, "sensitivity_curve.csv"),
                     index=False, encoding="utf-8-sig")
    write_report(args.out_dir, params, trades, stats, sig_df, baseline, eq,
                 begin=args.begin, end=args.end, codes_desc=codes_desc,
                 curve=curve)
    log.info("报告落盘：%s（信号 %d，交易 %d 行）", args.out_dir, len(sig_df), len(trades))
    return 0


if __name__ == "__main__":
    sys.exit(main())
