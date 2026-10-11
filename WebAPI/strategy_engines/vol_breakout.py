# -*- coding: utf-8 -*-
"""
VolBreakoutPullbackEngine — 放量启动回调策略引擎（strategy-signal-page 2.2 +
strategy-signal-outcome 2.1/2.2/2.3 修订）。

逻辑（vol-breakout-pullback spec 成文 + design D8/D11/D3）：
- 放量启动识别（A 日）：某日 volume / 前 N 日（20）均量 >= volume_ratio_min
  且当日收盘涨幅 >= a_pct_min（涨幅门槛可配参数，默认 5%——对齐 vp_entry 的
  A 日口径；配 9.8% 可还原近似涨停首板语义）
- A 日后进入 watching（回调中），回调窗口内（pullback_max_days 交易日）观察：
  * 量能峰锚定缩量判定（D8 冲高豁免）：P = 窗口内最后一个量 >= A 日量 × 0.8
    的交易日（无则 P = A 日）；缩量判定只作用于 P 之后的回调日
    D' = {P+1, …, 窗口末}——A 日后放量冲高不直接判缩量失败（冲高回落形态
    由 P 锚定后的末段缩量兜底）
  * 破位判定作用于窗口全程（口径不变）：任一回调日收盘 < A 日开盘 → expired
  * 窗口走完且未破位、且 D' 全程缩量（每个 D' 日量 < A 日量 × volume_shrink_max）
    → triggered（入场参考价 = 窗口内最低收盘价，止损参考价 = A 日最低价）；
    D' 缩量不满足 → expired
- 触发后价格突破回调期间高点 → running（已启动）
- signal_date 用 A 日（同一 (code, A 日) 只一条信号，与 PG 唯一键对齐）
- B 日重定义（D12/6.8，2026-10-11 修订）：B 日 = 回调窗口内最低收盘价出现日
  （实际回踩低点日，min_close_idx），不再恒等于窗口结束日——回调天数
  （payload pullback_days）= B 日 − A 日为实际值；绩效入场日 = B 日
- 绩效（D3/D4）：匹配态（triggered/running）事件带 ret_7d/ret_14d/ret_30d/
  outcome 四键（入场日 = B 日 = min_close_idx，复用 compute_outcome）；
  payload 存 first_board_date / pullback_days / volume_ratio + A/B 点过程
  字段（D10）：a_date/a_close/a_pct/b_date/b_open/b_close/b_day_pct/
  close_7d/close_14d/close_30d

水位语义：scan 时若 watermark 非空，从 watermark 之后有新 K 线才重算该 code
的信号（信号状态可能因新 K 线演进）；返回事件附带 watermark_new（该 code 最新
time_key），由调度方推进 strategy_scan_cursor。

硬性约束：绝不 import CChan 任何模块，只读 DuckDB（KLineStore read_only）。
"""

import logging
from typing import Optional

from ChanAnalyse.DataAPI.KLineStore import DEFAULT_DB_PATH, KLineStore

from ..config import DUCKDB_PATH
from . import compute_outcome

log = logging.getLogger("strategy_vol_breakout")

# 均量窗口（A 日前的参考均量天数）
_VOL_MA_WINDOW = 20
# 量能峰锚定阈值（D8：0.8 定死，对齐 vp_entry peak_anchor_ratio 先例，不做参数）
_PEAK_ANCHOR_RATIO = 0.8


def _duckdb_path() -> str:
    """DuckDB 路径（与 incremental_engine._duckdb_path 同口径）。"""
    import os

    return DUCKDB_PATH if os.path.exists(DUCKDB_PATH) else DEFAULT_DB_PATH


class VolBreakoutPullbackEngine:
    """放量启动回调引擎（实现 StrategyEngine 协议）。

    scan 为协议入口（引擎默认参数）；调度方带实例参数扫描走 scan_with_params。
    两条路径都读该 code 全历史日线重算信号全集（量价窗口需要历史上下文），
    结果经 store 层唯一键 upsert 天然幂等——已 frozen 的行不会被覆盖
    （见 strategy_store.upsert_signal 的 ON CONFLICT ... WHERE frozen = FALSE）。
    """

    def scan(
        self,
        code: str,
        kl_type_db: str = "K_DAY",
        autype: str = "QFQ",
        watermark: Optional[str] = None,
    ) -> list[dict]:
        """扫描一只股票，返回 SignalEvent dict 列表（可能为空）。

        事件字段：code / signal_date / state / is_buy / entry_ref_price /
        stop_ref_price / payload / ret_7d / ret_14d / ret_30d / outcome /
        watermark_new（绩效四键仅匹配态带值，其余态为 None）。
        watermark 非空且其后无新 K 线时返回 []（无演进，调度方无需推进水位）。
        """
        try:
            with KLineStore(_duckdb_path(), read_only=True) as store:
                rows = store.execute(
                    """
                    SELECT time_key, open, high, low, close, volume
                    FROM kline
                    WHERE code = ? AND kl_type = ? AND autype = ?
                    ORDER BY time_key
                    """,
                    [code, kl_type_db, autype],
                )
        except Exception as e:  # 锁冲突/文件缺失：单键失败上抛由调度方跳过
            log.warning("读取 DuckDB 失败 %s: %s", code, e)
            raise

        if not rows:
            return []

        # 水位门（D3）：watermark 之后无新 K 线 → 不重算
        latest_time_key = str(rows[-1][0])
        if watermark is not None and latest_time_key <= str(watermark):
            return []

        # 展开为行序列（time_key/open/high/low/close/volume）
        kl = [(str(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]),
               float(r[5]) if r[5] is not None else 0.0) for r in rows]

        events = self._scan_series(code, kl, self._default_params())
        for ev in events:
            ev["watermark_new"] = latest_time_key
        return events

    @staticmethod
    def _default_params() -> dict:
        """引擎默认参数（与 params_schema 声明一致，供无参调用兜底）。"""
        return {
            "pullback_max_days": 5,
            "volume_ratio_min": 2.0,
            "volume_shrink_max": 0.8,
            "a_pct_min": 0.05,
        }

    def scan_with_params(
        self,
        code: str,
        params: dict,
        kl_type_db: str = "K_DAY",
        autype: str = "QFQ",
        watermark: Optional[str] = None,
    ) -> list[dict]:
        """带实例参数扫描（调度方 scan_instance 使用，事件含 watermark_new）。

        旧任务 params 无 a_pct_min 键时 merged 落默认 0.05（D11：spec 是
        source of truth，旧行为不保留；需要首板口径显式配 9.8%）。
        """
        try:
            with KLineStore(_duckdb_path(), read_only=True) as store:
                rows = store.execute(
                    """
                    SELECT time_key, open, high, low, close, volume
                    FROM kline
                    WHERE code = ? AND kl_type = ? AND autype = ?
                    ORDER BY time_key
                    """,
                    [code, kl_type_db, autype],
                )
        except Exception as e:
            log.warning("读取 DuckDB 失败 %s: %s", code, e)
            raise

        if not rows:
            return []

        latest_time_key = str(rows[-1][0])
        if watermark is not None and latest_time_key <= str(watermark):
            return []

        kl = [(str(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]),
               float(r[5]) if r[5] is not None else 0.0) for r in rows]

        merged = {**self._default_params(), **(params or {})}
        events = self._scan_series(code, kl, merged)
        for ev in events:
            ev["watermark_new"] = latest_time_key
        return events

    # ------------------------------------------------------------------
    # 序列扫描（纯函数：便于 Debug 冒烟脚本构造 K 线序列直测）
    # ------------------------------------------------------------------

    def _scan_series(self, code: str, kl: list[tuple], params: dict) -> list[dict]:
        """在日线序列上识别全部 A 日信号事件（signal_date = A 日）。

        每个「A 日」只产出一条事件，其 state 由 A 日之后的行情演进决定：
        watching（窗口未走完，行情未到终局）→ triggered/expired（窗口走完的
        终局判定）→ running（触发后突破回调期间最高收盘价）。相邻 A 日（前一
        信号窗口尚未走完时又出现新 A 日）跳过——避免信号语义重叠。

        窗口终局判定（vol-breakout-pullback spec「回调窗口量能判定与冲高豁免」）：
        - 任一回调日收盘 < A 日开盘 → expired（回调破位，窗口全程口径不变）
        - 量能峰 P 锚定（D8）：P = 窗口内最后一个量 >= A 日量 × 0.8 的日
          （无则 P = A 日）；缩量判定只作用于 D' = {P+1, …, window_end}：
          每个回调日量 < A 日量 × volume_shrink_max 视为缩量满足——A 日后
          放量冲高（冲高回落形态）不直接判缩量失败
        - 窗口走完且未破位、且 D' 全程缩量 → triggered；否则 expired
        - triggered 后任一日收盘 > 窗口内最高收盘 → running

        绩效（D3/D4 + 6.8 B 日重定义）：匹配态事件附 ret_7d/14d/30d + outcome
        （入场日 = min_close_idx 窗口最低收盘出现日，买入基准价 = entry_ref）；
        watching/expired 态绩效四键为 None（无入场即无绩效）。
        """
        pullback_max_days = int(params.get("pullback_max_days", 5))
        volume_ratio_min = float(params.get("volume_ratio_min", 2.0))
        volume_shrink_max = float(params.get("volume_shrink_max", 0.8))
        a_pct_min = float(params.get("a_pct_min", 0.05))

        n = len(kl)
        events: list[dict] = []
        i = 0
        while i < n:
            tk, o, h, low, close, volume = kl[i]
            if i < _VOL_MA_WINDOW or close <= 0 or kl[i - 1][4] <= 0:
                i += 1
                continue

            # 放量启动判定：量比 + 涨幅门槛（a_pct_min 可配，默认 5%）
            vol_ma = sum(kl[j][5] for j in range(i - _VOL_MA_WINDOW, i)) / _VOL_MA_WINDOW
            if vol_ma <= 0:
                i += 1
                continue
            volume_ratio = volume / vol_ma
            chg = close / kl[i - 1][4] - 1
            if volume_ratio < volume_ratio_min or chg < a_pct_min:
                i += 1
                continue

            # A 日确认 → 从 i+1 起观察回调窗口（窗口末端受数据边界截断）
            a_date = tk[:10]
            a_open = o
            a_low = low
            a_volume = volume
            window_end = min(i + pullback_max_days, n - 1)  # 含
            window_full = (i + pullback_max_days <= n - 1)  # 窗口是否走完（终局可判）

            state = "watching"
            # 量能峰锚定（D8）：P 初值 = A 日，窗口内最后一个量 >= A日量×0.8
            # 的日更新 P；缩量判定窗口 D' = P+1..window_end
            peak_idx = i
            d_prime_shrunk = True  # D' 全程缩量标记
            min_close_in_window = close  # 窗口内最低收盘价（入场参考价，全窗口口径不变）
            min_close_idx = i  # 最低收盘出现索引（6.8 B 日重定义：初值 = A 日）
            max_close_in_window = close  # 窗口内最高收盘价（running 判定基准）
            for j in range(i + 1, window_end + 1):
                ptk, po, ph, pl, pc, pv = kl[j]
                if pc < min_close_in_window:
                    min_close_in_window = pc
                    min_close_idx = j
                if pc > max_close_in_window:
                    max_close_in_window = pc
                if pc < a_open:
                    state = "expired"  # 回调破位：终局（窗口全程口径，不豁免）
                    break
                if pv >= a_volume * _PEAK_ANCHOR_RATIO:
                    # 放量冲高日：更新量能峰锚 P（当日及其之前的回调日豁免缩量
                    # 判定——P 是「最后一个」放量日，新峰出现时旧 D' 判定追溯作废）
                    peak_idx = j
                    d_prime_shrunk = True
                elif j > peak_idx:
                    # D' 内的回调日：缩量判定
                    if pv >= a_volume * volume_shrink_max:
                        d_prime_shrunk = False

            if state == "watching" and window_full:
                # 窗口走完且未破位：终局按 D' 缩量判定
                state = "triggered" if d_prime_shrunk else "expired"
                if state == "triggered":
                    # 触发后演进：突破回调期间最高收盘价 → running
                    for k in range(window_end + 1, n):
                        if kl[k][4] > max_close_in_window:
                            state = "running"
                            break

            # 事件补充：watching 状态窗口未走完（数据边界），entry/stop 留空
            is_matched = state in ("triggered", "running")
            entry_ref = round(min_close_in_window, 3) if is_matched else None
            stop_ref = round(a_low, 3) if is_matched else None

            # 绩效四字段（D3/D4 + 6.8）：匹配态才有——入场日 = B 日 =
            # min_close_idx（窗口最低收盘出现日，与 entry_ref 同源同日），
            # 买入基准价 = entry_ref；kl 全序列在手，同循环复用 compute_outcome
            ret_7d = ret_14d = ret_30d = outcome = None
            close_7d = close_14d = close_30d = None
            if is_matched:
                ret_7d, ret_14d, ret_30d, outcome, close_7d, close_14d, close_30d = (
                    compute_outcome(min_close_idx, entry_ref, kl)
                )

            # B 日 OHLC（D10/6.2）：B 日 = min_close_idx，b_close 与 entry_ref
            # 同源同值（窗口最低收盘价）；b_day_pct = B 日收盘/开盘 - 1
            # （引擎直出，open 为 0/None 时为 None）
            b_open = kl[min_close_idx][1]
            b_close = kl[min_close_idx][4]
            b_day_pct = (
                round(b_close / b_open - 1.0, 6)
                if (b_open and b_open > 0 and b_close is not None) else None
            )

            events.append({
                "code": code,
                "signal_date": a_date,
                "state": state,
                "is_buy": True,  # 放量启动回调策略恒为买方向
                "entry_ref_price": entry_ref,
                "stop_ref_price": stop_ref,
                "ret_7d": ret_7d,
                "ret_14d": ret_14d,
                "ret_30d": ret_30d,
                "outcome": outcome,
                "payload": {
                    "first_board_date": a_date,  # 首板日语义保留（历史列消费）
                    "pullback_days": min_close_idx - i,  # 实际回调天数（6.8：不再恒等于参数值）
                    "volume_ratio": round(volume_ratio, 2),
                    # A/B 点过程字段（D10：策略私有过程字段走 payload）
                    "a_date": a_date,
                    "a_close": round(close, 4),
                    "a_pct": round(chg, 6),
                    "b_date": kl[min_close_idx][0][:10],  # B 点 = 窗口最低收盘出现日（6.8）
                    "b_open": round(b_open, 4) if b_open is not None else None,
                    "b_close": round(b_close, 4) if b_close is not None else None,
                    "b_day_pct": b_day_pct,
                    "close_7d": round(close_7d, 4) if close_7d is not None else None,
                    "close_14d": round(close_14d, 4) if close_14d is not None else None,
                    "close_30d": round(close_30d, 4) if close_30d is not None else None,
                },
            })

            # 跳到窗口之后继续找下一个 A 日（信号不重叠）
            i = window_end + 1

        return events
