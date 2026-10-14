# -*- coding: utf-8 -*-
"""
VolBreakoutPullbackEngine — 放量启动回调策略引擎（strategy-volume-breakout-pullback）。

判定语义（spec delta 见 openspec/changes/strategy-volume-breakout-pullback）：
- 放量启动识别（A 日）：volume / 前 20 日均量 >= volume_ratio_min（默认 2.3）
  且收盘涨幅 >= a_pct_min（默认 5%）
- A 日后回调窗口（pullback_max_days 交易日，默认 13）三道逐日门，任一触发
  → expired（D' 缩量终局判定废弃，被趋势口径取代）：
  * 破位门：任一回调日收盘 < A 日开盘
  * 涨幅门：尚无任何 B 级事件确认时，日收盘涨幅 > pullback_pct_max（默认 0.04）
  * 量能趋势门：A+3 日起，当日 3 日均量 > 前 3 日均量 × volume_trend_ratio（默认 1.1）
- B 点分级判定（五级独立探测、互不前置，只在窗口内判定，不越窗）：
  * B1 = 日线 MACD 柱绿柱绝对值连续 3 根递减，或柱值由负转正（金叉）
  * B2 = 30m MACD 柱面积底背离（两段下跌，价创新低、绿柱面积和不创新低；
    局部低点锚定：相邻低点间隔 >= 8 bar 且其间反弹 >= 4 bar）
  * B3 = 30m 缠论任意等级买点（bsp_reader 只读 PG，按需补算）
  * B4 = 日线缠论任意等级买点（同上）
  * B  = 放量突破回调期高点（收盘 > 窗口此前最高收盘 且 量 >= A 日量 ×
    breakout_vol_ratio 默认 0.4）
- 窗口走完终局：>=1 个 B 级事件 → 信号成立（有 B → running；仅 B1~B4 →
  triggered）；零 B → expired（当前区间策略无效）
- 回调天数 = 最早 B 级事件日 − A 日（交易日）；< pullback_min_days（默认 4）
  → expired（回调不充分）
- 绩效：每个 B 级事件独立计算 7/14/30 日收益（基准 = 事件价格，compute_outcome
  加权口径）；信号级绩效按最早 B 事件起算

水位语义：scan 时若 watermark 非空，从 watermark 之后有新 K 线才重算该 code
的信号（信号状态可能因新 K 线演进）；返回事件附带 watermark_new（该 code 最新
time_key），由调度方推进 strategy_scan_cursor。

硬性约束：不 import CChan 计算模块（MACD 用包内 macd.py，缠论买点经
bsp_reader 间接链路——只读 PG bsp_index + 按需调 incremental_engine 补算）。
"""

import logging
from typing import Optional

from ChanAnalyse.DataAPI.KLineStore import DEFAULT_DB_PATH, KLineStore

from ..config import DUCKDB_PATH
from . import compute_outcome
from .bsp_reader import get_bsp_buy_points
from .macd import macd_columns

log = logging.getLogger("strategy_vol_breakout")

# 均量窗口（A 日前的参考均量天数）
_VOL_MA_WINDOW = 20
# B1 绿柱递减根数（spec 严格口径，不做参数）
_B1_GREEN_SHRINK_BARS = 3
# B2 局部低点锚定：相邻低点最小间隔（30m bar 数）与反弹最小 bar 数（design D2）
_B2_LOW_GAP_BARS = 8
_B2_REBOUND_BARS = 4


def _duckdb_path() -> str:
    """DuckDB 路径（与 incremental_engine._duckdb_path 同口径）。"""
    import os

    return DUCKDB_PATH if os.path.exists(DUCKDB_PATH) else DEFAULT_DB_PATH


def _load_30m_kl(code: str) -> list[tuple]:
    """读 30m K 线序列（time_key/open/close/volume），无数据返回空表。

    B2 判定用（量能趋势门/逐日门在日线层）。失败返回空表 = B2 不可判
    （D5 暂态降级：不淘汰信号）。
    """
    try:
        with KLineStore(_duckdb_path(), read_only=True) as store:
            rows = store.execute(
                """
                SELECT time_key, open, close, volume
                FROM kline
                WHERE code = ? AND kl_type = 'K_30M' AND autype = 'QFQ'
                ORDER BY time_key
                """,
                [code],
            )
    except Exception as e:
        log.warning("读取 30m K 线失败 %s: %s", code, e)
        return []
    return [
        (str(r[0]), float(r[1]), float(r[2]), float(r[3]) if r[3] is not None else 0.0)
        for r in rows
    ]


def _trading_day(ts: str) -> str:
    """'YYYY-MM-DD HH:MM:SS' / 'YYYY-MM-DD' → 'YYYY-MM-DD'。"""
    return ts[:10]


# ----------------------------------------------------------------------
# B 级事件探测（纯函数：窗口上下文 → 事件列表）
# ----------------------------------------------------------------------

def _detect_b1(
    kl: list[tuple], i: int, window_end: int, cols: list[float]
) -> Optional[int]:
    """B1：日线 MACD 绿柱绝对值连续 N 根递减，或柱值由负转正（金叉）。

    cols 为全序列 MACD 柱（与 kl 等长）。在窗口 [i+1, window_end] 内逐日探测，
    返回首个命中日索引；无命中返回 None。B1 物理最早出现在 A+4（柱先有
    绿柱且要 3 根递减）。
    """
    for j in range(i + 1, window_end + 1):
        c = cols[j]
        if c > 0 and cols[j - 1] <= 0:
            return j  # 金叉（柱由负/零转正）
        # 绿柱递减：当前及前 N-1 根均为负柱，且 |柱| 逐根递减
        if c < 0 and j >= i + _B1_GREEN_SHRINK_BARS - 1:
            window_slice = cols[j - _B1_GREEN_SHRINK_BARS + 1 : j + 1]
            if all(x < 0 for x in window_slice):
                abs_vals = [-x for x in window_slice]
                if all(abs_vals[k + 1] < abs_vals[k] for k in range(len(abs_vals) - 1)):
                    return j
    return None


def _detect_b2(
    kl30: list[tuple], window_days: set[str]
) -> Optional[tuple]:
    """B2：30m MACD 柱面积底背离（design D2 简化锚定）。

    在窗口日集合内识别两个局部低点（k1 在前、k2 在后），满足：
    - 间隔 >= 8 bar 且其间反弹收复 k1（两段独立下跌，非同一波段）
    - k2 为 [k1, k2] 区间最低收盘（真正创新低）
    - 两段下跌（各自反弹高点 → 低点）的 MACD 绿柱面积和：area2 < area1
      （价创新低而绿柱面积不创新低 → 底背离）
    返回最早确认的 (确认 bar 时间, 确认 bar 收盘价)；不可判返回 None。
    """
    # 窗口内的 30m bar（含首尾日全部 bar）
    bars = [(idx, b) for idx, b in enumerate(kl30) if _trading_day(b[0]) in window_days]
    if len(bars) < _B2_LOW_GAP_BARS * 2 + _B2_REBOUND_BARS:
        return None
    indices = [idx for idx, _ in bars]
    closes = [kl30[idx][2] for idx in indices]
    closes_all = [b[2] for b in kl30]
    cols = macd_columns(closes_all)

    # 局部低点：比前后 bar 收盘都低，且为 ±2 bar 邻域最小（去抖动噪声）
    lows = [
        k for k in range(1, len(closes) - 1)
        if closes[k] < closes[k - 1] and closes[k] < closes[k + 1]
        and closes[k] == min(closes[max(0, k - 2): k + 3])
    ]

    def _decline_area(seg_lo: int, seg_hi: int) -> float:
        """下跌段 [反弹高点 seg_lo, 低点 seg_hi] 的 MACD 绿柱面积和。"""
        return sum(
            -cols[indices[m]] for m in range(seg_lo, seg_hi + 1)
            if cols[indices[m]] < 0
        )

    # 按确认时间从早到晚遍历（外层 k2 升序，返回最早的背离确认）
    for b in range(1, len(lows)):
        k2 = lows[b]
        for a in range(b - 1, -1, -1):
            k1 = lows[a]
            if k2 - k1 < _B2_LOW_GAP_BARS:
                continue
            # 反弹收复 k1：两段独立下跌的锚定
            mid_max = max(closes[k1 + 1: k2]) if k2 > k1 + 1 else closes[k1]
            if mid_max <= closes[k1]:
                continue
            # k2 须为区间真正最低（越窗前的伪新低不算）
            if closes[k2] >= min(closes[k1: k2]):
                continue
            # 两段下跌：k1 前的局部反弹高点 → k1；k1/k2 间反弹高点 → k2
            seg1_lo = max(0, k1 - _B2_LOW_GAP_BARS)
            seg1_peak = seg1_lo + max(
                range(seg1_lo, k1 + 1), key=lambda m: closes[m]
            )
            area1 = _decline_area(seg1_peak, k1)
            mid_peak = k1 + 1 + max(
                range(k1 + 1, k2), key=lambda m: closes[m]
            )
            area2 = _decline_area(mid_peak, k2)
            if area2 > 0 and area1 > 0 and area2 < area1:
                return (kl30[indices[k2]][0], kl30[indices[k2]][2])
    return None


def _detect_b34(
    bsp_rows: Optional[list[dict]], kl: list[tuple], i: int, window_end: int
) -> list[dict]:
    """B3/B4：缠论买点行（bsp_reader）→ 窗口内买点事件。

    bsp_rows 为该 code+周期的全部买点行（None = 数据不可得，跳过判定）。
    is_sure 不作过滤（出现即打标，回顾性重扫自然演进）。
    """
    if not bsp_rows:
        return []
    a_day = _trading_day(kl[i][0])
    end_day = _trading_day(kl[window_end][0])
    events = []
    for row in bsp_rows:
        tk = row.get("time_key") or row.get("bsp_date")
        if not tk:
            continue
        day = _trading_day(str(tk))
        # 窗口边界：A 日之后（不含 A 日）至窗口末日（含当日全部 30m bar）
        if a_day < day <= end_day:
            events.append(row)
    return events


def _detect_b(
    kl: list[tuple], i: int, window_end: int, breakout_vol_ratio: float
) -> Optional[int]:
    """B：放量突破回调期高点（窗口内，此前最高收盘）。

    返回首个突破日索引；无返回 None。突破日量 >= A 日量 × breakout_vol_ratio。
    """
    a_volume = kl[i][5]
    if i + 1 > window_end:
        return None  # 窗口内无回调日，无从突破
    running_max = kl[i + 1][4]  # 窗口内此前最高收盘（初值 = 窗口第一日收盘）
    for j in range(i + 2, window_end + 1):  # 突破判定从 A+2 起（A+1 自身是首个回调日，尚无「此前」高点）
        close, volume = kl[j][4], kl[j][5]
        if close > running_max and volume >= a_volume * breakout_vol_ratio:
            return j
        if close > running_max:
            running_max = close  # 无量创新高：不出 B，但抬高后续判定基准
    return None


# ----------------------------------------------------------------------
# 引擎主体
# ----------------------------------------------------------------------

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
        stop_ref_price / payload（含 b_events）/ ret_5d / ret_10d / ret_15d /
        outcome / watermark_new（绩效四键仅匹配态带值，其余态为 None）。
        watermark 非空且其后无新 K 线时返回 []（无演进，调度方无需推进水位）。
        """
        kl, latest_time_key = self._load_daily(code, kl_type_db, autype)
        if not kl:
            return []
        if watermark is not None and latest_time_key <= str(watermark):
            return []
        events = self._scan_series(code, kl, self._default_params())
        for ev in events:
            ev["watermark_new"] = latest_time_key
        return events

    @staticmethod
    def _default_params() -> dict:
        """引擎默认参数（与 params_schema 声明一致，供无参调用兜底）。"""
        return {
            "pullback_max_days": 13,
            "pullback_min_days": 4,
            "volume_ratio_min": 2.3,
            "a_pct_min": 0.05,
            "pullback_pct_max": 0.04,
            "volume_trend_ratio": 1.1,
            "breakout_vol_ratio": 0.4,
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

        旧任务 params 无新键时 merged 落默认（与 a_pct_min 先例同机制）。
        """
        kl, latest_time_key = self._load_daily(code, kl_type_db, autype)
        if not kl:
            return []
        if watermark is not None and latest_time_key <= str(watermark):
            return []
        merged = {**self._default_params(), **(params or {})}
        events = self._scan_series(code, kl, merged)
        for ev in events:
            ev["watermark_new"] = latest_time_key
        return events

    # ------------------------------------------------------------------
    # 数据加载
    # ------------------------------------------------------------------

    @staticmethod
    def _load_daily(code: str, kl_type_db: str, autype: str) -> tuple[list[tuple], str]:
        """读全历史日线（time_key/open/high/low/close/volume）。"""
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
        kl = [
            (str(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]),
             float(r[5]) if r[5] is not None else 0.0)
            for r in rows
        ]
        latest = str(rows[-1][0]) if rows else ""
        return kl, latest

    # ------------------------------------------------------------------
    # 序列扫描（纯函数：便于 Debug 冒烟脚本构造 K 线序列直测）
    # ------------------------------------------------------------------

    def _scan_series(self, code: str, kl: list[tuple], params: dict) -> list[dict]:
        """在日线序列上识别全部 A 日信号事件（signal_date = A 日）。

        每个 A 日产出一条事件，state 由窗口内三道逐日门 + B 级探测终局决定。
        相邻 A 日（前一信号窗口尚未走完时又出现新 A 日）跳过——信号不重叠。
        """
        pullback_max_days = int(params.get("pullback_max_days", 13))
        pullback_min_days = int(params.get("pullback_min_days", 4))
        volume_ratio_min = float(params.get("volume_ratio_min", 2.3))
        a_pct_min = float(params.get("a_pct_min", 0.05))
        pullback_pct_max = float(params.get("pullback_pct_max", 0.04))
        volume_trend_ratio = float(params.get("volume_trend_ratio", 1.1))
        breakout_vol_ratio = float(params.get("breakout_vol_ratio", 0.4))

        n = len(kl)
        events: list[dict] = []
        if n == 0:
            return events

        # 全序列 MACD 柱（B1 判定基准，一次算完）
        day_cols = macd_columns([k[4] for k in kl])
        # 30m K 线与缠论买点（B2/B3 数据源，懒加载一次）
        kl30 = _load_30m_kl(code)
        bsp_rows_30m = get_bsp_buy_points(code, "30m")
        bsp_rows_d = get_bsp_buy_points(code, "D")

        i = 0
        while i < n:
            tk, o, h, low, close, volume = kl[i]
            if i < _VOL_MA_WINDOW or close <= 0 or kl[i - 1][4] <= 0:
                i += 1
                continue

            # 放量启动判定：量比 + 涨幅门槛
            vol_ma = sum(kl[j][5] for j in range(i - _VOL_MA_WINDOW, i)) / _VOL_MA_WINDOW
            if vol_ma <= 0:
                i += 1
                continue
            volume_ratio = volume / vol_ma
            chg = close / kl[i - 1][4] - 1
            if volume_ratio < volume_ratio_min or chg < a_pct_min:
                i += 1
                continue

            # A 日确认 → 从 i+1 起观察回调窗口
            a_date = tk[:10]
            a_open = o
            a_low = low
            window_end = min(i + pullback_max_days, n - 1)  # 含
            window_full = (i + pullback_max_days <= n - 1)  # 窗口是否走完（终局可判）
            window_days = {
                _trading_day(kl[j][0]) for j in range(i + 1, window_end + 1)
            }

            # ---- 逐日门（破位/涨幅/量能趋势）+ B 级事件探测 ----
            state = "watching"
            gate_reason = None
            b_events: list[dict] = []  # 窗口内按时间序累计的 B 级事件
            running_max_close = close  # 窗口内此前最高收盘（涨幅门后的新高跟踪）

            # B1：日线 MACD（全序列柱）
            b1_idx = _detect_b1(kl, i, window_end, day_cols)
            # B2：30m MACD 底背离（数据不可得时 None → 不判）
            b2_hit = _detect_b2(kl30, window_days) if kl30 else None
            # B3/B4：缠论买点（数据不可得时 None → 不判）
            b3_rows = _detect_b34(bsp_rows_30m, kl, i, window_end) if bsp_rows_30m else []
            b4_rows = _detect_b34(bsp_rows_d, kl, i, window_end) if bsp_rows_d else []
            # B：放量突破（逐日扫描内联判定，与逐日门同一循环推进）
            b_idx = _detect_b(kl, i, window_end, breakout_vol_ratio)

            # 组装 B 级事件（等级/时间/价格/涨幅），供涨幅门「已确认」判定与落库
            if b1_idx is not None:
                b_events.append(self._mk_event("B1", kl, b1_idx, "D"))
            if b2_hit is not None:
                # b2_hit = (bar 时间, bar 收盘)；day_pct 用 30m bar 涨幅
                b_events.append(self._mk_event_30m("B2", kl30, b2_hit))
            for row in b3_rows:
                b_events.append(self._mk_bsp_event("B3", row, "30m", kl30))
            for row in b4_rows:
                b_events.append(self._mk_bsp_event("B4", row, "D", kl))
            if b_idx is not None:
                b_events.append(self._mk_event("B", kl, b_idx, "D"))
            b_events.sort(key=lambda e: e["b_time"])

            # 逐日门：B 确认前的涨幅门需要「首个 B 事件日」做分界
            first_b_day = min((_trading_day(e["b_time"]) for e in b_events), default=None)

            vol_ma3 = None  # 3 日均量递推缓存
            for j in range(i + 1, window_end + 1):
                ptk, po, ph, pl, pc, pv = kl[j]
                # 破位门（全程）
                if pc < a_open:
                    state = "expired"
                    gate_reason = "回调破位"
                    break
                day_chg = pc / kl[j - 1][4] - 1 if kl[j - 1][4] > 0 else 0.0
                # 涨幅门（B 确认日之后不再拦截：B 已确认，涨回来是突破在即）
                if (
                    first_b_day is None or _trading_day(ptk) < first_b_day
                ) and day_chg > pullback_pct_max:
                    state = "expired"
                    gate_reason = "B 确认前涨幅超限"
                    break
                # 量能趋势门（A+3 起）：3 日均量 vs 前 3 日均量
                if j >= i + 3:
                    cur3 = sum(kl[m][5] for m in range(j - 2, j + 1)) / 3.0
                    prev3 = sum(kl[m][5] for m in range(j - 3, j)) / 3.0
                    if prev3 > 0 and cur3 > prev3 * volume_trend_ratio:
                        state = "expired"
                        gate_reason = "量能趋势抬升"
                        break

            # ---- 终局判定 ----
            if state == "watching" and window_full:
                if not b_events:
                    state = "expired"
                    gate_reason = "窗口内零 B 确认"
                elif any(e["b_level"] == "B" for e in b_events):
                    state = "running"
                else:
                    state = "triggered"

            # 回调天数下限过滤（换锚：最早 B 事件日 − A 日，按交易日）
            pullback_days = None
            if b_events:
                first_b_idx = min(
                    (idx for idx in range(i + 1, window_end + 1)
                     if _trading_day(kl[idx][0]) == first_b_day),
                    default=None,
                )
                if first_b_idx is not None:
                    pullback_days = first_b_idx - i
                    if state in ("triggered", "running") and pullback_days < pullback_min_days:
                        state = "expired"
                        gate_reason = "回调天数不足下限"

            is_matched = state in ("triggered", "running")
            entry_ref = None
            stop_ref = round(a_low, 3) if is_matched else None

            # ---- 绩效：B 事件独立 + 信号级（最早事件） ----
            # 2026-10-15 修订：绩效窗口 7/14/30 → 5/10/15（compute_outcome 全局口径）
            ret_5d = ret_10d = ret_15d = outcome = None
            close_5d = close_10d = close_15d = None
            if is_matched and b_events:
                for e in b_events:
                    e_idx, e_price = self._event_ref(e, kl)
                    if e_idx is None:
                        continue
                    r5, r10, r15, oc, c5, c10, c15 = compute_outcome(e_idx, e_price, kl)
                    e["ret_5d"] = r5
                    e["ret_10d"] = r10
                    e["ret_15d"] = r15
                    e["outcome"] = oc
                    e["close_5d"] = c5
                    e["close_10d"] = c10
                    e["close_15d"] = c15
                first = b_events[0]
                entry_ref = round(first["price"], 3)
                ret_5d, ret_10d, ret_15d = first.get("ret_5d"), first.get("ret_10d"), first.get("ret_15d")
                outcome = first.get("outcome")
                close_5d, close_10d, close_15d = (
                    first.get("close_5d"), first.get("close_10d"), first.get("close_15d")
                )

            # payload 的 B 列展平键（b_col 列型渲染取值）：最早 B 事件
            b_date = b_close = b_open = b_day_pct = None
            if b_events:
                first = b_events[0]
                b_date = first["b_time"][:19]
                b_close = first.get("price")
                b_open = first.get("open")
                b_day_pct = first.get("day_pct")

            events.append({
                "code": code,
                "signal_date": a_date,
                "state": state,
                "is_buy": True,
                "entry_ref_price": entry_ref,
                "stop_ref_price": stop_ref,
                "ret_5d": ret_5d,
                "ret_10d": ret_10d,
                "ret_15d": ret_15d,
                "outcome": outcome,
                "payload": {
                    "first_board_date": a_date,
                    "pullback_days": pullback_days,
                    "volume_ratio": round(volume_ratio, 2),
                    "gate_reason": gate_reason,  # expired 归因（调试与展示用）
                    "a_date": a_date,
                    "a_close": round(close, 4),
                    "a_pct": round(chg, 6),
                    "b_date": b_date,
                    "b_open": b_open,
                    "b_close": round(b_close, 4) if b_close is not None else None,
                    "b_day_pct": round(b_day_pct, 6) if b_day_pct is not None else None,
                    "b_count": len(b_events),
                    "earliest_b_level": b_events[0]["b_level"] if b_events else None,
                    "b_events": b_events,  # 事件全集（store 层落 strategy_signal_b_event）
                    "close_5d": round(close_5d, 4) if close_5d is not None else None,
                    "close_10d": round(close_10d, 4) if close_10d is not None else None,
                    "close_15d": round(close_15d, 4) if close_15d is not None else None,
                },
            })

            # 跳到窗口之后继续找下一个 A 日（信号不重叠）
            i = window_end + 1

        return events

    # ------------------------------------------------------------------
    # B 事件构造辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _mk_event(level: str, kl: list[tuple], idx: int, kl_type: str) -> dict:
        """日线 B 事件（B1/B/B4 通用）：时间取交易日 00:00:00。"""
        tk, o, _h, _l, c, _v = kl[idx]
        day_pct = (c / o - 1.0) if (o and o > 0 and c) else None
        return {
            "b_level": level,
            "b_time": tk[:10] + " 00:00:00",
            "b_kl_type": kl_type,
            "price": c,
            "open": o,
            "day_pct": round(day_pct, 6) if day_pct is not None else None,
        }

    @staticmethod
    def _mk_event_30m(level: str, kl30: list[tuple], hit: tuple) -> dict:
        """30m B2 事件：bar 时间 + bar 收盘 + bar 涨幅（收盘/开盘−1）。"""
        tk, o, c = hit[0], None, hit[1]
        # kl30 行为 (time_key, open, close, volume)——查原行取 open
        for row in kl30:
            if row[0] == hit[0]:
                o = row[1]
                break
        day_pct = (c / o - 1.0) if (o and o > 0 and c) else None
        return {
            "b_level": level,
            "b_time": tk,
            "b_kl_type": "30m",
            "price": c,
            "open": o,
            "day_pct": round(day_pct, 6) if day_pct is not None else None,
        }

    @staticmethod
    def _mk_bsp_event(level: str, row: dict, kl_type: str, kl_ref: list) -> dict:
        """B3/B4 事件：价格取 bsp_index.price；时间 30m 带时刻、日线取日期。"""
        tk = row.get("time_key") or row.get("bsp_date")
        if kl_type == "30m" and tk and len(tk) > 10:
            b_time = tk  # 'YYYY-MM-DD HH:MM:SS'
            price = row.get("price")
            day_pct = None  # 30m bar 涨幅在存储层按需补（弹窗展示）
        else:
            b_time = _trading_day(str(tk)) + " 00:00:00"
            price = row.get("price")
            day_pct = None
        return {
            "b_level": level,
            "b_time": b_time,
            "b_kl_type": kl_type,
            "price": price,
            "bsp_type": row.get("bsp_type"),
            "is_sure": row.get("is_sure"),
            "day_pct": day_pct,
        }

    @staticmethod
    def _event_ref(e: dict, kl: list[tuple]) -> tuple[Optional[int], Optional[float]]:
        """B 事件 → 绩效计算参照（日线索引 + 基准价）。

        30m 事件折算到所属交易日索引（日线 kl 中定位），价格用事件价格
        （B2 30m bar 收盘 / B3 bsp price）；日线事件直接取日索引。
        """
        day = _trading_day(e["b_time"])
        price = e.get("price")
        if price is None:
            return None, None
        for idx in range(len(kl)):
            if _trading_day(kl[idx][0]) == day:
                return idx, float(price)
        return None, None
