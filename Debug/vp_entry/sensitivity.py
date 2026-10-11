# -*- coding: utf-8 -*-
"""敏感性扫描驱动（tasks 4.5）：108 组合全本地无网络。

扫描网格（spec entry-backtest 敏感性纪律）：CV7 × N × R_W × 止损 × 量能门
= 3 × 3 × 3 × 2 × 2 = 108 组合。每个组合：
  1. 对池内每只股票全量喂日线状态机（B 候选走日线退化版终判——分钟数据
     仅 2020 年后可得，敏感性扫描以全历史口径为准，分钟版触发在
     run_backtest.py 的正式回测里做，不混入扫描）；
  2. 信号 → evaluate_exits 六口径 → 每口径汇总统计；
  3. 落一行进绩效-参数曲线 CSV。

悬崖参数标记（防过拟合纪律）：
  - 信号量悬崖：固定其余参数、单独调一个参数到相邻档位，信号数变化
    比例超过 signal_cliff_ratio（默认 40%）→ 该参数档位标记 CLIFF_SIGNAL；
  - 绩效悬崖：mean_ret（T+10 口径）跨相邻档位变化超过 ret_cliff（默认
    5 个百分点）→ 标记 CLIFF_RET。
  标记结果以 CSV 附加列 + 单独 cliff 报告 DataFrame 两种形式输出。

数据输入：daily DataFrame（code/time_key/open/high/low/close/volume，
来自本地 DuckDB kline 表），全流程零网络调用。
"""

import itertools
import logging

import pandas as pd

from .backtest import EXIT_T10, evaluate_exits
from WebAPI.strategy_engines.vp_entry.params import FixedParams, SCAN, VPParams
from WebAPI.strategy_engines.vp_entry.signal_rule import DayBar, VPStateMachine

log = logging.getLogger("vp_sensitivity")

SIGNAL_CLIFF_RATIO = 0.40  # 信号量悬崖阈值：相邻档位变化 ≥ 40%
RET_CLIFF = 0.05           # 绩效悬崖阈值：相邻档位 mean_ret 变化 ≥ 5pp


def assert_scan_params(params: VPParams) -> None:
    """敏感性集合显式校验（vp-entry-strategy-integration design D1/D2）。

    VPParams.__post_init__ 的离散集合断言已外移到本函数（任务侧参数为连续
    取值域，dataclass 不再拦截），回测侧在构造扫描参数后调用本函数，保证
    108 组合全部落在声明的敏感性集合内。
    """
    checks = (
        ("cv7_max", params.cv7_max, SCAN.cv7_max_list),
        ("box_width_max", params.box_width_max, SCAN.r_w_list),
        ("n_max", params.n_max, SCAN.n_max_list),
        ("stop_loss", params.stop_loss, SCAN.stop_loss_list),
    )
    for name, value, allowed in checks:
        if value not in allowed:
            raise ValueError(
                f"{name} 必须在敏感性集合 {set(allowed)}，收到 {value}"
            )


def _run_one(daily: pd.DataFrame, params: VPParams) -> tuple[list, pd.DataFrame]:
    """单组合：全池状态机扫描（日线退化版终判）→ (signals, 交易明细)。

    返回的 signals 为 SignalEvent dataclass 列表（已含日线版 B+1 买价回填）。
    """
    assert_scan_params(params)  # 敏感性集合纪律（design D2：回测侧显式校验）
    signals = []
    for code, g in daily.groupby("code"):
        g = g.sort_values("time_key")
        m = VPStateMachine(code=code, params=params)
        pending = None  # 待终判的 B 候选（当日喂入产生，需该日 OHLCV 终判）
        for row in g.itertuples(index=False):
            bar = DayBar(str(row.time_key)[:10], row.open, row.high, row.low,
                         row.close, row.volume)
            if pending is not None:
                # 用候选日的完整日 K 做日线退化版终判（minute_df=None）
                ev, pending = pending, None
                m.decide_b_day(ev, minute_df=None)
            ev = m.on_day(bar)
            if ev is not None:
                pending = ev
        if pending is not None:
            m.decide_b_day(pending, minute_df=None)
        signals.extend(m.signals)
    if not signals:
        return signals, pd.DataFrame()
    sig_df = pd.DataFrame([vars(s) for s in signals])
    trades = evaluate_exits(sig_df, daily, params)
    return signals, trades


def _combo_rows(trades: pd.DataFrame, params: VPParams) -> list[dict]:
    """单组合 → 曲线 CSV 行（每口径一行 + 汇总行）。"""
    base = {"cv7_max": params.cv7_max, "box_width_max": params.box_width_max,
            "n_max": params.n_max, "stop_loss": params.stop_loss,
            "vol_gate": params.vol_gate}
    if trades is None or trades.empty:
        return [{**base, "exit_method": "ALL", "n_signals": 0, "n_trades": 0,
                 "win_rate": float("nan"), "mean_ret": float("nan"),
                 "median_ret": float("nan")}]
    rows = []
    for method, g in trades.groupby("exit_method"):
        r = g["ret"]
        rows.append({**base, "exit_method": method, "n_signals": len(g),
                     "n_trades": len(g), "win_rate": float((r > 0).mean()),
                     "mean_ret": float(r.mean()), "median_ret": float(r.median())})
    r = trades["ret"]
    rows.append({**base, "exit_method": "ALL", "n_signals": len(trades),
                 "n_trades": len(trades), "win_rate": float((r > 0).mean()),
                 "mean_ret": float(r.mean()), "median_ret": float(r.median())})
    return rows


def run_sensitivity(daily: pd.DataFrame, progress_every: int = 20) -> pd.DataFrame:
    """跑 108 组合，返回绩效-参数曲线长表（含 cliff 标记列）。

    构造前先过 assert_scan_params（敏感性集合纪律），组合数 108 由
    itertools.product 网格保证。
    """
    combos = [
        VPParams(cv7_max=cv7, box_width_max=rw, n_max=n, stop_loss=sl, vol_gate=vg)
        for cv7, rw, n, sl, vg in itertools.product(
            SCAN.cv7_max_list, SCAN.r_w_list, SCAN.n_max_list,
            SCAN.stop_loss_list, SCAN.vol_gate_list)
    ]
    assert len(combos) == 108, f"扫描组合数应为 108，实际 {len(combos)}"

    rows = []
    for i, params in enumerate(combos):
        _, trades = _run_one(daily, params)
        rows.extend(_combo_rows(trades, params))
        if progress_every and (i + 1) % progress_every == 0:
            log.info("敏感性扫描进度 %d/108", i + 1)
    curve = pd.DataFrame(rows)

    # ---- 悬崖标记（先并 T+10 均值供绩效悬崖对比） ----
    curve = attach_t10_mean(curve)
    curve = mark_cliffs(curve)
    return curve


def mark_cliffs(curve: pd.DataFrame) -> pd.DataFrame:
    """对曲线长表做悬崖参数标记（附加 is_cliff 列，值 = 悬崖类型或空）。"""
    curve = curve.copy()
    curve["is_cliff"] = ""
    if curve.empty:
        return curve
    # 用 ALL 行做组合级对比
    all_rows = curve[curve["exit_method"] == "ALL"].copy()
    dims = {
        "cv7_max": sorted(SCAN.cv7_max_list),
        "box_width_max": sorted(SCAN.r_w_list),
        "n_max": sorted(SCAN.n_max_list),
        "stop_loss": sorted(SCAN.stop_loss_list),
        "vol_gate": list(SCAN.vol_gate_list),
    }

    def _key(row) -> tuple:
        return (row.cv7_max, row.box_width_max, row.n_max,
                row.stop_loss, row.vol_gate)

    lookup = {_key(r): r for r in all_rows.itertuples(index=False)}

    cliff_keys = set()
    # 相邻档位两两对比：每个维度取扫描集合相邻值（按扫描顺序，非数值大小）
    for dim, values in dims.items():
        for v1, v2 in zip(values, values[1:]):
            fixed_dims = [d for d in dims if d != dim]
            for combo in itertools.product(*[dims[d] for d in fixed_dims]):
                kv = dict(zip(fixed_dims, combo))
                r1 = lookup.get(_key_make(kv, dim, v1))
                r2 = lookup.get(_key_make(kv, dim, v2))
                if r1 is None or r2 is None:
                    continue
                # 信号量悬崖
                n1, n2 = r1.n_signals, r2.n_signals
                if n1 > 0 or n2 > 0:
                    ratio = abs(n2 - n1) / max(n1, n2, 1)
                    if ratio >= SIGNAL_CLIFF_RATIO:
                        cliff_keys.add((_key(r1), f"CLIFF_SIGNAL:{dim}={v2}"))
                        cliff_keys.add((_key(r2), f"CLIFF_SIGNAL:{dim}={v1}"))
                # 绩效悬崖（T+10 口径的 mean_ret 相邻档位差）
                m1 = getattr(r1, "mean_ret_T10", None)
                m2 = getattr(r2, "mean_ret_T10", None)
                if m1 is not None and m2 is not None and not (
                        pd.isna(m1) or pd.isna(m2)):
                    if abs(m2 - m1) >= RET_CLIFF:
                        cliff_keys.add((_key(r1), f"CLIFF_RET:{dim}={v2}"))
                        cliff_keys.add((_key(r2), f"CLIFF_RET:{dim}={v1}"))

    # 写回：同组合全部行共享标记
    for key, tag in cliff_keys:
        mask = ((curve["cv7_max"] == key[0]) & (curve["box_width_max"] == key[1]) &
                (curve["n_max"] == key[2]) & (curve["stop_loss"] == key[3]) &
                (curve["vol_gate"] == key[4]))
        existing = curve.loc[mask, "is_cliff"]
        curve.loc[mask, "is_cliff"] = existing.apply(
            lambda s: ";".join(filter(None, [s, tag])))
    return curve


def _key_make(kv: dict, dim: str, v) -> tuple:
    """按 mark_cliffs 内 _key 的固定顺序拼组合键。"""
    d = dict(kv)
    d[dim] = v
    return (d["cv7_max"], d["box_width_max"], d["n_max"],
            d["stop_loss"], d["vol_gate"])


def attach_t10_mean(curve: pd.DataFrame) -> pd.DataFrame:
    """把 T+10 口径的 mean_ret 并到 ALL 行（供绩效悬崖对比）。

    返回新 DataFrame（ALL 行多一列 mean_ret_T10）。
    """
    curve = curve.copy()
    t10 = curve[curve["exit_method"] == EXIT_T10][
        ["cv7_max", "box_width_max", "n_max", "stop_loss", "vol_gate", "mean_ret"]]
    t10 = t10.rename(columns={"mean_ret": "mean_ret_T10"})
    all_mask = curve["exit_method"] == "ALL"
    merged = curve[all_mask].merge(
        t10, on=["cv7_max", "box_width_max", "n_max", "stop_loss", "vol_gate"],
        how="left")
    merged["exit_method"] = "ALL"
    # 用 merge 结果替换 ALL 行（保持列对齐：其余行补 NaN 列）
    others = curve[~all_mask].copy()
    others["mean_ret_T10"] = float("nan")
    out = pd.concat([others, merged], ignore_index=True)
    return out
