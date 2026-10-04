# -*- coding: utf-8 -*-
"""
VolBreakoutPullbackEngine — 放量首板回调策略引擎（strategy-signal-page 2.2）。

逻辑（design D3 / open question 文案落地）：
- 放量首板识别：某日 volume / 前 N 日（20）均量 >= volume_ratio_min 且当日涨幅
  >= 9.8%（首板近似：close / 前收 - 1 >= 0.098）
- 首板后进入 watching（回调中），回调窗口内（pullback_max_days 交易日）观察：
  量能萎缩（回调日量 < 首板量 * volume_shrink_max）且价格未破首板日开盘价
  → 窗口结束仍持有 → triggered（入场参考价 = 回调窗口最低收盘价，
  止损参考价 = 首板日最低价）；窗口超时未满足 → expired
- 触发后价格突破回调期间高点 → running（已启动）
- signal_date 用首板日（同一 (code, 首板日) 只一条信号，与 PG 唯一键对齐）；
  payload 存 first_board_date / pullback_days / volume_ratio

水位语义：scan 时若 watermark 非空，从 watermark 之后有新 K 线才重算该 code
的信号（信号状态可能因新 K 线演进）；返回事件附带 watermark_new（该 code 最新
time_key），由调度方推进 strategy_scan_cursor。

硬性约束：绝不 import CChan 任何模块，只读 DuckDB（KLineStore read_only）。
"""

import logging
from typing import Optional

from ChanAnalyse.DataAPI.KLineStore import DEFAULT_DB_PATH, KLineStore

from ..config import DUCKDB_PATH

log = logging.getLogger("strategy_vol_breakout")

# 首板涨幅阈值（近似涨停 9.8%，覆盖主板 10% 限制的当日涨幅判定）
_LIMIT_UP_PCT = 0.098
# 均量窗口（首板前的参考均量天数）
_VOL_MA_WINDOW = 20


def _duckdb_path() -> str:
    """DuckDB 路径（与 incremental_engine._duckdb_path 同口径）。"""
    import os

    return DUCKDB_PATH if os.path.exists(DUCKDB_PATH) else DEFAULT_DB_PATH


class VolBreakoutPullbackEngine:
    """放量首板回调引擎（实现 StrategyEngine 协议）。

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
        stop_ref_price / payload / watermark_new。
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

        # 引擎自身无参数（参数在实例侧，由调度方传入 → 见 scan_with_params）
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
        }

    def scan_with_params(
        self,
        code: str,
        params: dict,
        kl_type_db: str = "K_DAY",
        autype: str = "QFQ",
        watermark: Optional[str] = None,
    ) -> list[dict]:
        """带实例参数扫描（调度方 scan_instance 使用，事件含 watermark_new）。"""
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
        """在日线序列上识别全部首板信号事件（signal_date = 首板日）。

        每个「首板」只产出一条事件，其 state 由首板之后的行情演进决定：
        watching（窗口未走完，行情未到终局）→ triggered/expired（窗口走完的
        终局判定）→ running（触发后突破回调期间最高收盘价）。相邻首板（前一
        信号窗口尚未走完时又出现新首板）跳过——避免信号语义重叠。

        窗口终局判定（参数语义与设计文档对齐）：
        - 任一回调日收盘 < 首板日开盘 → expired（回调破位）
        - 窗口走完且全程缩量（每个回调日 volume < 首板量 × volume_shrink_max）
          → triggered；缩量不满足 → expired
        - triggered 后任一日收盘 > 窗口内最高收盘 → running
        """
        pullback_max_days = int(params.get("pullback_max_days", 5))
        volume_ratio_min = float(params.get("volume_ratio_min", 2.0))
        volume_shrink_max = float(params.get("volume_shrink_max", 0.8))

        n = len(kl)
        events: list[dict] = []
        i = 0
        while i < n:
            tk, o, h, low, close, volume = kl[i]
            if i < _VOL_MA_WINDOW or close <= 0 or kl[i - 1][4] <= 0:
                i += 1
                continue

            # 放量首板判定：量比 + 涨幅（近似首板 9.8%）
            vol_ma = sum(kl[j][5] for j in range(i - _VOL_MA_WINDOW, i)) / _VOL_MA_WINDOW
            if vol_ma <= 0:
                i += 1
                continue
            volume_ratio = volume / vol_ma
            chg = close / kl[i - 1][4] - 1
            if volume_ratio < volume_ratio_min or chg < _LIMIT_UP_PCT:
                i += 1
                continue

            # 首板确认 → 从 i+1 起观察回调窗口（窗口末端受数据边界截断）
            first_board_date = tk[:10]
            board_open = o
            board_low = low
            board_volume = volume
            window_end = min(i + pullback_max_days, n - 1)  # 含
            window_full = (i + pullback_max_days <= n - 1)  # 窗口是否走完（终局可判）

            state = "watching"
            all_shrunk = True
            min_close_in_window = close  # 窗口内最低收盘价（入场参考价）
            max_close_in_window = close  # 窗口内最高收盘价（running 判定基准）
            for j in range(i + 1, window_end + 1):
                ptk, po, ph, pl, pc, pv = kl[j]
                if pc < min_close_in_window:
                    min_close_in_window = pc
                if pc > max_close_in_window:
                    max_close_in_window = pc
                if pc < board_open:
                    state = "expired"  # 回调破位：终局
                    break
                if pv >= board_volume * volume_shrink_max:
                    all_shrunk = False

            if state == "watching" and window_full:
                # 窗口走完且未破位：终局按缩量判定
                state = "triggered" if all_shrunk else "expired"
                if state == "triggered":
                    # 触发后演进：突破回调期间最高收盘价 → running
                    for k in range(window_end + 1, n):
                        if kl[k][4] > max_close_in_window:
                            state = "running"
                            break

            # 事件补充：watching 状态窗口未走完（数据边界），entry/stop 留空
            entry_ref = round(min_close_in_window, 3) if state in ("triggered", "running") else None
            stop_ref = round(board_low, 3) if state in ("triggered", "running") else None

            events.append({
                "code": code,
                "signal_date": first_board_date,
                "state": state,
                "is_buy": True,  # 首板回调策略恒为买方向
                "entry_ref_price": entry_ref,
                "stop_ref_price": stop_ref,
                "payload": {
                    "first_board_date": first_board_date,
                    "pullback_days": window_end - i,
                    "volume_ratio": round(volume_ratio, 2),
                },
            })

            # 跳到窗口之后继续找下一个首板（信号不重叠）
            i = window_end + 1

        return events
