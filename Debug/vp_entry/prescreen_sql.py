# -*- coding: utf-8 -*-
"""DuckDB 粗筛 SQL 下推（tasks 3.1）。

把蓄势期 + A 日的日线筛门全部下推到 DuckDB 窗口函数内计算：
MA60V / CV7(ddof=1) / 区间盒 R_W / 10 日收盘新高 / 量能均值门 / 单日涨跌幅。
只把通过粗筛的候选 (code, A日) 返回 Python，供状态机精判。

与状态机精判的关系（design D3）：
- 粗筛只判定「A 日触发点」是否成立（蓄势期 + A 日条件），调整期/B 日需要逐日
  前瞻状态，仍由状态机做；
- 粗筛与状态机共享同一份 VPParams（单一参数来源），两段判定必须一致——
  对齐验证：SQL 粗筛候选集 == 状态机进入 TRIGGERED_A 的 A 日集合。
- CV7 用 STDDEV_SAMP（ddof=1），与状态机 statistics.stdev（ddof=1）对齐
  （design D3 的静默偏差风险点，对齐测试强制覆盖）。

严格版量能门（逐日 V_i < MA60V(i)）需要逐行对比 W 窗口内 V 与各自 MA60V，
SQL 用第二层窗口 max(V_i - MA60V_i) 表达：窗口内任一日越线即严格门不通过。
"""

import logging

import pandas as pd

from WebAPI.strategy_engines.vp_entry.params import VPParams

log = logging.getLogger("vp_prescreen")

# 两层 CTE：
#   d1: 按行算派生量（ret / MA60V / 10日新高 / W 窗口聚合 / 行号）
#   d2: 在 d1 之上算 W 窗口内逐日 |ret| 最大值、V_i-MA60V_i 最大越线量（严格门）
_PREEN_SQL = """
WITH d1 AS (
    SELECT
        code,
        SUBSTR(time_key, 1, 10) AS a_date,
        open, high, low, close, volume,
        close / LAG(close) OVER w - 1.0 AS ret,
        -- MA60V(A-1)：A-60 … A-1（不含 A 日本身，与状态机 _ma(a_idx-1) 对齐）
        AVG(volume) OVER (PARTITION BY code ORDER BY time_key
                          ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING) AS ma60v,
        MAX(close) OVER (PARTITION BY code ORDER BY time_key
                         ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) AS max_c10_prev,
        AVG(volume) OVER (PARTITION BY code ORDER BY time_key
                          ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING) AS w_mean_v,
        STDDEV_SAMP(volume) OVER (PARTITION BY code ORDER BY time_key
                                  ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING) AS w_std_v,
        MAX(close) OVER (PARTITION BY code ORDER BY time_key
                         ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING) AS w_max_c,
        MIN(close) OVER (PARTITION BY code ORDER BY time_key
                         ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING) AS w_min_c,
        LAG(close) OVER w AS close_prev,
        COUNT(*) OVER (PARTITION BY code ORDER BY time_key
                       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS rn
    FROM kline
    WHERE kl_type = 'K_DAY' AND autype = ?
    WINDOW w AS (PARTITION BY code ORDER BY time_key)
),
d2 AS (
    SELECT *,
        MAX(ABS(ret)) OVER (PARTITION BY code ORDER BY a_date
                            ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING) AS w_max_abs_ret,
        MAX(volume - ma60v) OVER (PARTITION BY code ORDER BY a_date
                                  ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING) AS w_max_v_over_ma
    FROM d1
    WHERE ret IS NOT NULL AND rn >= {min_bars}
)
SELECT code, a_date, open, high, low, close, volume,
       ret, ma60v, w_mean_v, w_std_v, w_max_c, w_min_c, w_max_abs_ret, w_max_v_over_ma,
       close_prev, max_c10_prev
FROM d2
WHERE close_prev IS NOT NULL
"""


def prescreen_sql(conn, params: VPParams, autype: str = "QFQ") -> pd.DataFrame:
    """在 DuckDB 连接上跑粗筛 SQL，返回 A 日触发点成立的行（含派生量列）。

    阈值判定在 Python 侧按 params 比对（数值由 SQL 算出），保证粗筛/精判
    用同一参数来源与同一比较口径。
    """
    f = params.fixed
    sql = _PREEN_SQL.format(min_bars=f.min_daily_bars)
    df = conn.execute(sql, [autype]).fetchdf()
    if df.empty:
        return df

    cv7 = df["w_std_v"] / df["w_mean_v"]
    box = (df["w_max_c"] - df["w_min_c"]) / df["close_prev"]
    mask = (
        (df["ret"] >= f.a_day_ret_min)
        & (df["volume"] >= f.a_day_vol_mult * df["w_mean_v"])
        & (df["close"] > df["max_c10_prev"])
        & (cv7 <= params.cv7_max)
        & (box <= params.box_width_max)
        & (df["w_max_abs_ret"] <= f.single_day_ret_limit)
    )
    if params.vol_gate == "mean":
        mask &= df["w_mean_v"] <= f.vol_mean_gate * df["ma60v"]
    elif params.vol_gate == "strict":
        # W 窗口内任一日 V_i >= MA60V(i) 则严格门不通过（w_max_v_over_ma < 0 表示全部低于）
        mask &= df["w_max_v_over_ma"] < 0
    else:
        raise ValueError(f"未知 vol_gate: {params.vol_gate}")
    return df[mask].reset_index(drop=True)


def prescreen_vs_machine(conn, daily_df: pd.DataFrame, params: VPParams) -> dict:
    """对齐验证（design D3 风险项）：SQL 粗筛 A 日集合 == 状态机 TRIGGERED_A 集合。

    daily_df: kline 表 K_DAY 行（code, time_key, open/high/low/close/volume），升序。
    返回 {sql_set, machine_set, only_sql, only_machine, aligned}。
    """
    from WebAPI.strategy_engines.vp_entry.signal_rule import DayBar, VPStateMachine

    sql_df = prescreen_sql(conn, params)
    sql_set = set(zip(sql_df["code"], sql_df["a_date"]))

    machines = {}
    machine_set = set()
    for row in daily_df.itertuples(index=False):
        m = machines.setdefault(row.code, VPStateMachine(code=row.code, params=params))
        prev_state = m.state if hasattr(m, "state") else None
        m.on_day(DayBar(str(row.time_key)[:10], row.open, row.high, row.low, row.close, row.volume))
        cur_state = m.state if hasattr(m, "state") else None
        if prev_state is not None and "TRIGGERED_A" in str(cur_state):
            # on_day 返回 B 候选时状态已推进；A 日确认 = 进入 TRIGGERED_A 的当日
            machine_set.add((row.code, str(row.time_key)[:10]))

    only_sql = sql_set - machine_set
    only_machine = machine_set - sql_set
    return {
        "sql_set": sql_set,
        "machine_set": machine_set,
        "only_sql": only_sql,
        "only_machine": only_machine,
        "aligned": not only_sql and not only_machine,
    }
