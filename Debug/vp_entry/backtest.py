# -*- coding: utf-8 -*-
"""回测引擎：信号事件 → 持仓撮合 → 五口径离场 → 绩效统计 → 基准对照（tasks 4.1~4.4）。

与判定内核（signal_rule）的边界（design D2）：
- 判定内核产出 SignalEvent（买价/止损参考/全部标签）；
- 本模块负责离场路径（五口径）、T+1 约束、绩效分组统计、随机/等权基准。

五口径（spec entry-backtest「离场规则」）：
- stop  : 收盘 < max(O_A, 买价×(1-容忍)) → 次日开盘卖；买入当日跌破也次日卖（T+1）
- T+5/T+10/T+20 : 买入后第 N 个交易日收盘卖
- MA5/MA10 : 收盘跌破均线 → 次日开盘卖（均线按 B 日前后的全量日线滚动计算）

各口径独立成报表，不混算（spec 要求）。
"""

import logging

import numpy as np
import pandas as pd

from WebAPI.strategy_engines.vp_entry.params import VPParams

log = logging.getLogger("vp_backtest")

EXIT_STOP = "stop"
EXIT_T5 = "T+5"
EXIT_T10 = "T+10"
EXIT_T20 = "T+20"
EXIT_MA5 = "MA5"
EXIT_MA10 = "MA10"
EXIT_ALL = (EXIT_STOP, EXIT_T5, EXIT_T10, EXIT_T20, EXIT_MA5, EXIT_MA10)
_HOLD_MAP = {EXIT_T5: 5, EXIT_T10: 10, EXIT_T20: 20}
# stop / MA 口径持仓上限（交易日）：超时仍未触发 → 以截断日收盘平仓。
# 防止跨复权基准的极长持有（QFQ 历史价差失真）与统计噪声。
EXIT_MAX_HOLD_DAYS = 30


def _to_df(signals) -> pd.DataFrame:
    """SignalEvent 列表 → DataFrame（dataclass 字段直接展开）。"""
    if not signals:
        return pd.DataFrame()
    rows = []
    for s in signals:
        rows.append({
            "code": s.code, "a_date": s.a_date, "p_date": s.p_date, "b_date": s.b_date,
            "b_bar_time": s.b_bar_time, "entry_mode": s.entry_mode,
            "buy_price": s.buy_price, "stop_loss_low": s.stop_loss_low,
            "spring": s.spring, "drift_bucket": s.drift_bucket,
            "wick_box": s.wick_box, "box_days": s.box_days,
            "vol_gate": s.vol_gate, "box_r": s.box_r, "a_ret": s.a_ret,
        })
    return pd.DataFrame(rows)


def evaluate_exits(signals_df: pd.DataFrame, daily: pd.DataFrame,
                   params: VPParams) -> pd.DataFrame:
    """五口径离场收益（tasks 4.1 + 4.2）。

    signals_df: SignalEvent 展开的 DataFrame（_to_df 产物或等价结构）
    daily: kline K_DAY 行（code, time_key, open, close, volume），升序，需含
           B 日之后至少 max(20, 观察窗) 个交易日（不足则该口径自然提前终止）

    返回行粒度 = 信号 × 口径：(code, b_date, exit_method, sell_price, hold_days, ret)
    - ret = sell_price / buy_price - 1
    - 样本不足（后续日线耗尽）时以最后可得收盘卖出并标记 truncated
    """
    if signals_df.empty:
        return pd.DataFrame(columns=["code", "a_date", "b_date", "exit_method",
                                     "sell_price", "hold_days", "ret", "truncated",
                                     "spring", "drift_bucket", "entry_mode", "vol_gate"])
    # 防御性去重（同一 A 日至多一信号由内核保证；这里按 code+B 日兜底）
    signals_df = signals_df.drop_duplicates(subset=["code", "a_date"], keep="first")

    daily = daily.copy()
    daily["d"] = daily["time_key"].str[:10]
    daily_by_code = {c: g.sort_values("d").reset_index(drop=True)
                     for c, g in daily.groupby("code")}
    # MA5/MA10 预计算（全量日线滚动，含 B 日之前——均线口径应基于完整历史）
    for g in daily_by_code.values():
        g["ma5"] = g["close"].rolling(5).mean()
        g["ma10"] = g["close"].rolling(10).mean()

    rows = []
    for sig in signals_df.itertuples(index=False):
        g = daily_by_code.get(sig.code)
        if g is None:
            continue
        # B 日（分钟版）或 B+1 日（日线版）在日线序列中的定位：
        # 持仓起点 = 买入执行日（日线版买价是 B+1 开盘，从 B+1 起算持有）
        anchor = sig.b_date if sig.entry_mode == "minute" else None
        idx = None
        if anchor is not None:
            hit = g.index[g["d"] == anchor]
            idx = int(hit[0]) if len(hit) else None
        if idx is None:  # 日线版：B 日后第一根日线 = B+1
            hit = g.index[g["d"] > sig.b_date]
            idx = int(hit[0]) if len(hit) else None
        if idx is None:
            continue
        if sig.entry_mode == "minute":
            pass  # 买入执行日 = B（idx 已定位），T+1 当日不可卖（stop/MA 触发也只能次日开盘）
        else:
            pass  # 买入执行日 = B+1（idx 已定位）
        # T+N 口径：第 N 个交易日收盘卖（买入日 = 第 0 日，path 起点即第 1 日）
        path = g.iloc[idx + 1:]
        # stop / MA 口径：收盘跌破含买入日当天（spec：买入当日跌破也次日开盘卖，
        # 与 T+1 约束天然一致——触发日为买入日时，卖出日 = 次日开盘）
        check_path = g.iloc[idx: idx + EXIT_MAX_HOLD_DAYS + 1]
        if check_path.empty:
            continue

        base = {"code": sig.code, "a_date": sig.a_date, "b_date": sig.b_date,
                "spring": sig.spring, "drift_bucket": sig.drift_bucket,
                "entry_mode": sig.entry_mode, "vol_gate": sig.vol_gate,
                "buy_price": sig.buy_price, "stop_loss_low": sig.stop_loss_low}

        # ---- stop / MA 口径在观察窗内未触发 → 以截断日收盘平仓（truncated=True） ----
        # 观察窗 = 买入日起 EXIT_MAX_HOLD_DAYS 个交易日（防跨复权基准的长持失真）

        # ---- stop 口径：收盘 < max(O_A, 买价×(1-容忍)) → 次日开盘卖 ----
        stop_line = sig.stop_loss_low if sig.stop_loss_low is not None else (
            sig.buy_price * params.stop_loss_price_ratio)
        below = check_path[check_path["close"] < stop_line]
        if len(below):
            b_i = below.index[0]
            sell_idx = b_i + 1
            if sell_idx < len(g):
                rows.append({**base, "exit_method": EXIT_STOP,
                             "sell_price": float(g.loc[sell_idx, "open"]),
                             "hold_days": int(sell_idx - idx), "ret": None, "truncated": False})
            else:  # 止损触发但次日无数据（样本末端），以触发日收盘近似
                rows.append({**base, "exit_method": EXIT_STOP,
                             "sell_price": float(g.loc[b_i, "close"]),
                             "hold_days": int(b_i - idx), "ret": None, "truncated": True})
        else:
            # 未触发止损 → 以样本末端收盘平仓（截断标记）
            last_i = check_path.index[-1]
            rows.append({**base, "exit_method": EXIT_STOP,
                         "sell_price": float(g.loc[last_i, "close"]),
                         "hold_days": int(last_i - idx), "ret": None, "truncated": True})

        # ---- T+N 口径：第 N 个交易日收盘卖 ----
        for name, n in _HOLD_MAP.items():
            if len(path) >= n:
                sell_i = path.index[n - 1]
                rows.append({**base, "exit_method": name,
                             "sell_price": float(g.loc[sell_i, "close"]),
                             "hold_days": n, "ret": None, "truncated": False})
            else:
                sell_i = check_path.index[-1]
                rows.append({**base, "exit_method": name,
                             "sell_price": float(g.loc[sell_i, "close"]),
                             "hold_days": int(sell_i - idx), "ret": None, "truncated": True})

        # ---- MA5 / MA10 口径：收盘跌破均线 → 次日开盘卖（含买入日当天） ----
        for name, macol in ((EXIT_MA5, "ma5"), (EXIT_MA10, "ma10")):
            sub = check_path[check_path[macol].notna() & (check_path["close"] < check_path[macol])]
            if len(sub):
                b_i = sub.index[0]
                sell_idx = b_i + 1
                if sell_idx < len(g):
                    rows.append({**base, "exit_method": name,
                                 "sell_price": float(g.loc[sell_idx, "open"]),
                                 "hold_days": int(sell_idx - idx), "ret": None, "truncated": False})
                else:
                    rows.append({**base, "exit_method": name,
                                 "sell_price": float(g.loc[b_i, "close"]),
                                 "hold_days": int(b_i - idx), "ret": None, "truncated": True})
            else:
                last_i = check_path.index[-1]
                rows.append({**base, "exit_method": name,
                             "sell_price": float(g.loc[last_i, "close"]),
                             "hold_days": int(last_i - idx), "ret": None, "truncated": True})

    out = pd.DataFrame(rows)
    if not out.empty:
        # ret = sell/buy - 1：QFQ 前复权在同一复权基准内逐笔可比（买入/卖出价
        # 同属一次信号持有的连续价格序列，未经跨期价格拆分）；
        # 长持有由 EXIT_MAX_HOLD_DAYS 截断保护（防跨复权基准失真）
        out["ret"] = out["sell_price"] / out["buy_price"] - 1.0
    return out


def compute_stats(trades: pd.DataFrame) -> pd.DataFrame:
    """绩效统计（tasks 4.3）：整体 + 分组（spring/基底桶/分钟vs日线/量能门/口径）。"""
    if trades is None or trades.empty:
        return pd.DataFrame()
    rows = []

    def _stat(g: pd.DataFrame, label: str):
        r = g["ret"]
        wins, losses = r[r > 0], r[r <= 0]
        rows.append({
            "group": label, "n": len(g),
            "win_rate": float((r > 0).mean()),
            "mean_ret": float(r.mean()),
            "median_ret": float(r.median()),
            "profit_loss_ratio": float(wins.mean() / abs(losses.mean()))
            if len(wins) and len(losses) else np.nan,
            "max_loss": float(r.min()),
            "mean_hold_days": float(g["hold_days"].mean()),
        })

    # 先按口径分（主报表维度），再按标签分组
    for method, g in trades.groupby("exit_method"):
        _stat(g, f"exit={method}")
    _stat(trades, "exit=ALL")
    for col in ("spring", "drift_bucket", "entry_mode", "vol_gate"):
        if col in trades.columns and trades[col].notna().any():
            for val, g in trades.groupby(col):
                _stat(g, f"{col}={val}")
    return pd.DataFrame(rows)


def random_baseline(daily: pd.DataFrame, n_signals: int, hold: int = 10,
                    n_samples: int = 200, seed: int = 7) -> dict:
    """随机买入基准（tasks 4.4）：等量随机 (code, 日期) 组合的收益分布（95% CI）。"""
    if daily is None or daily.empty or n_signals == 0:
        return {"mean": np.nan, "ci95": (np.nan, np.nan), "n_signals": 0}
    rng = np.random.default_rng(seed)
    daily = daily.copy()
    daily["d"] = daily["time_key"].str[:10]
    codes = daily["code"].unique()
    d_sorted = {c: g.sort_values("d").reset_index(drop=True)
                for c, g in daily.groupby("code")}
    means = []
    for _ in range(n_samples):
        rets = []
        for _ in range(min(n_signals, 200)):  # 单样本抽样上限，防过慢
            c = codes[rng.integers(len(codes))]
            g = d_sorted[c]
            if len(g) < hold + 2:
                continue
            i = rng.integers(len(g) - hold - 1)
            buy, sell = g.loc[i, "close"], g.loc[i + hold, "close"]
            if buy and buy > 0:
                rets.append(sell / buy - 1)
        if rets:
            means.append(np.mean(rets))
    if not means:
        return {"mean": np.nan, "ci95": (np.nan, np.nan), "n_signals": n_signals}
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {"mean": float(np.mean(means)), "ci95": (float(lo), float(hi)),
            "n_signals": n_signals}


def equal_weight_baseline(daily: pd.DataFrame, hold: int = 10) -> float:
    """全样本等权基准：每只股票样本期首日买入、持有 hold 日的等权平均收益。"""
    if daily is None or daily.empty:
        return np.nan
    daily = daily.copy()
    daily["d"] = daily["time_key"].str[:10]
    rets = []
    for _, g in daily.groupby("code"):
        g = g.sort_values("d").reset_index(drop=True)
        if len(g) < hold + 1:
            continue
        buy, sell = g.loc[0, "close"], g.loc[hold, "close"]
        if buy and buy > 0:
            rets.append(sell / buy - 1)
    return float(np.mean(rets)) if rets else np.nan
