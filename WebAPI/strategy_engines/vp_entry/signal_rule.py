# -*- coding: utf-8 -*-
"""
量价三段式买点 判定内核：日线流式状态机（tasks 2.2 + 2.5 日线退化版）

状态流：IDLE → BASEMENT → TRIGGERED_A → PULLBACK → SIGNAL / DEAD

每喂入一根日 K（VPStateMachine.on_day）做有界 O(1) 状态更新（滚动历史窗口固定 80 根）：

- IDLE / BASEMENT：历史不足 61 根时纯积累（次新排除）；足够后逐日扫描当前日
  是否为合法 A 日（蓄势期 W = 前 7 根的全部条件 + A 日三条件）；
- TRIGGERED_A / PULLBACK：调整期逐日推进——先按「截至昨日」的数据评估当前日
  是否为 B 日候选（候选条件全部只依赖 ≤ B-1 的数据），再视终判结果决定当前日
  是否并入调整期 D；
- SIGNAL / DEAD：终态（产生信号 / 超时·破位淘汰），下一根日 K 复位重新扫描。

B 日的分钟级触发与日线退化版终判由 decide_b_day 完成：调用方在收到
BCandidateEvent 后调用，传入该日 5 分钟数据（DataFrame，同 kline 表结构）或
None（表示该日无分钟数据）：

- 有分钟数据 → minute_trigger 逐 bar 扫描，触发即 SIGNAL（买价 = 触发分钟收盘价，
  同一 A 日至多一信号）；无触发 → 当日放弃，当前日并入 D 继续等后续 B 日
  （不回退日线版——spec 规定退化仅适用于「无可得 5 分钟数据」）；
- 无分钟数据 → 日线退化版（高开 0% < gap ≤ 3%、V_B ≥ 2×D'末3日均量、C_B > O_B），
  买价 = B+1 日开盘价，在下一根日 K 喂入时回填到同一 SignalEvent 对象。

spec 依据：openspec/changes/volume-price-entry-rule/specs/entry-signal-rule/spec.md
歧义处理（按 spec 字面语义实现，标注如下）：
1. 「收盘仍未触发 → 该候选放弃」按「当日放弃」理解：样本继续等待后续 B 日，
   直至超时/破位淘汰（spec Scenario 标题「该候选当日判定放弃」中的「当日」限定）；
2. 严格版量能门 ∀i∈W: V_i < MA60V(i) 中最早的 i = A-7 需要 A-66 起的 60 根量能，
   历史不足 67 根时该口径 MA60V(i) 不可得 → 严格版判定不通过（spec 只定义了
   61 根的次新排除线，未覆盖严格版的更深回看，此处按「不可得即不通过」处理）；
3. D' 末 3 日均量在 |D'| < 3 时取末 min(3, |D'|) 日（与末段缩量窗口同口径）。
"""

import statistics
from dataclasses import dataclass, field
from enum import Enum

from .minute_trigger import scan_minute_trigger
from .params import VPParams

# 滚动历史保留根数：覆盖严格量能门最深回看（MA60V(A-7) 需 67 根）+ 余量
HIST_KEEP = 80


class VPState(Enum):
    """状态机状态（design D2）"""

    IDLE = "IDLE"                # 历史不足，纯积累
    BASEMENT = "BASEMENT"        # 扫描 A 日（蓄势期候选积累中）
    TRIGGERED_A = "TRIGGERED_A"  # A 日已触发，量能峰 P 暂锚定为 A，等待调整
    PULLBACK = "PULLBACK"        # 调整期内已出现量能峰 P（V ≥ 0.8×V_A），等待 B
    SIGNAL = "SIGNAL"            # 终态：已产生信号
    DEAD = "DEAD"                # 终态：超时/破位淘汰


@dataclass
class DayBar:
    """单根日线 K（前复权口径）"""

    date: str  # "YYYY-MM-DD"
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def body(self) -> float:
        """实体长度（阳/阴取绝对值）"""
        return abs(self.close - self.open)

    @property
    def lower_wick(self) -> float:
        """下影线长度"""
        return min(self.open, self.close) - self.low


@dataclass
class SignalEvent:
    """信号事件（判定内核唯一输出，撮合与绩效归 backtest.py）"""

    code: str
    a_date: str
    p_date: str                 # 量能峰锚定日
    b_date: str                 # 触发日
    b_bar_time: str | None      # 触发分钟 time_key（分钟版），日线版为 None
    entry_mode: str             # minute / daily
    buy_price: float            # 分钟版 = 触发分钟收盘价；日线版 = B+1 开盘（回填）
    vp_bar_ratio: float | None  # 触发分钟 VP / 阈值（分钟版诊断用）
    # ---- 基底特征标签（不设门，spec 记录要求） ----
    spring: bool                # Spring 豁免标记
    drift_bucket: str           # 净漂移三桶：low / mid / high
    wick_box: float             # 影线盒宽 (max(H_i)-min(L_i))/C_{A-1}
    box_days: int               # 盒宽 ≤ 12% 的最长持续天数
    vol_gate: str               # 量能门版本：mean / strict
    box_r: float                # 蓄势期收盘盒宽 R_W
    a_ret: float                # A 日涨幅
    # ---- 绩效侧预挂（backtest.py 消费，本模块只透传） ----
    stop_loss_low: float | None = None  # 止损参考低点 max(O_A, 买价×0.88)

    @property
    def label_summary(self) -> str:
        return (
            f"{self.code} A={self.a_date} P={self.p_date} B={self.b_date} "
            f"[{self.entry_mode}] spring={self.spring} drift={self.drift_bucket} "
            f"wick={self.wick_box:.2%} box_days={self.box_days} gate={self.vol_gate}"
        )


@dataclass
class BCandidateEvent:
    """B 日候选事件：进入 B 日时抛出，由调用方喂数据后调 decide_b_day 终判"""

    machine: "VPStateMachine"    # 所属状态机（回填终态用）
    code: str
    a_date: str
    p_date: str
    b_date: str
    # B-1 日（= D 最后一日）数据缓存（gap 计算用）
    b_prev_close: float
    # 供分钟触发 VP 门槛的参考量：D' 末 min(3, |D'|) 日均量
    dp_end_mean_vol: float
    # 基底标签（透传进 SignalEvent）
    spring: bool
    drift_bucket: str
    wick_box: float
    box_days: int
    vol_gate: str
    box_r: float
    a_ret: float
    a_open: float
    a_high: float
    # 调整期（A+1..B-1）日 K 引用，用于日线退化版的 V_B 比对与末段缩量复核
    adjust_bars: list = field(default_factory=list)


class VPStateMachine:
    """单只股票的量价三段式判定状态机（流式，每根日 K O(1) 更新）"""

    def __init__(self, code: str, params: VPParams | None = None):
        self.code = code
        self.params = params or VPParams()
        self.state = VPState.IDLE
        self.hist: list[DayBar] = []      # 滚动日线历史（定长 HIST_KEEP）
        self.total_bars = 0               # 累计喂入根数（次新排除判定用）
        # ---- 当前 A 上下文（TRIGGERED_A / PULLBACK 期有效） ----
        self._a_ctx: dict = {}
        # 待回填的日线版信号（等 B+1 开盘价）
        self._pending_daily_signal: SignalEvent | None = None
        self.signals: list[SignalEvent] = []   # 已产生的信号（含回填完成的）
        self.last_event: BCandidateEvent | None = None  # 最近一次 B 候选事件

    # ------------------------------------------------------------------
    # 日线喂入
    # ------------------------------------------------------------------

    def on_day(self, bar: DayBar) -> BCandidateEvent | None:
        """喂入一根日 K。返回 B 日候选事件（需调 decide_b_day 终判），否则 None。"""
        self.total_bars += 1

        # 日线版信号买价回填（B+1 开盘价 = 当前喂入根）
        if self._pending_daily_signal is not None:
            sig = self._pending_daily_signal
            sig.buy_price = bar.open
            sig.stop_loss_low = max(
                sig.stop_loss_low or 0.0,
                sig.buy_price * self.params.stop_loss_price_ratio,
            )
            self.signals.append(sig)
            self._pending_daily_signal = None
            # 日线版信号已闭环，从 BASEMENT 重新扫描（同一 A 日不重复进场）
            self._reset()

        # 滚动窗口维护
        self.hist.append(bar)
        if len(self.hist) > HIST_KEEP:
            self.hist = self.hist[-HIST_KEEP:]

        event = None
        if self.state == VPState.IDLE:
            if self.total_bars >= self.params.fixed.min_daily_bars:
                self.state = VPState.BASEMENT
        elif self.state == VPState.BASEMENT:
            event = self._try_day_a()
        elif self.state in (VPState.TRIGGERED_A, VPState.PULLBACK):
            event = self._advance_adjustment(bar)
        elif self.state in (VPState.SIGNAL, VPState.DEAD):
            # 终态复位后当日继续按 BASEMENT 扫描（新的 A 日可在相邻日出现）
            self._reset()
            event = self._try_day_a()

        self.last_event = event
        return event

    # ------------------------------------------------------------------
    # A 日判定（BASEMENT 状态，含蓄势期全部条件）
    # ------------------------------------------------------------------

    def _try_day_a(self) -> BCandidateEvent | None:
        """以当前 hist 末根为候选 A 日做判定。通过则进入 TRIGGERED_A。"""
        p = self.params
        fx = p.fixed
        # 历史深度由 _check_basement 内的 _ma 返回 None 兜底（口径见模块 docstring 歧义 2）
        a = self.hist[-1]
        w = self.hist[-(fx.basement_len + 1):-1]  # W = A-7 … A-1（7 根）
        ret_a = a.close / w[-1].close - 1.0
        if ret_a < fx.a_day_ret_min:
            return None
        if a.volume < fx.a_day_vol_mult * _mean([b.volume for b in w]):
            return None
        if a.close <= max(b.close for b in self.hist[-(fx.a_day_new_high_days + 1):-1]):
            return None  # 10 日收盘新高
        if not self._check_basement(w, w_base=self.hist[-(fx.basement_len + 2)]):
            return None

        # ---- 通过：建立 A 上下文 ----
        spring_used = False  # Spring 豁免将按全 D 范围逐日判定
        self._a_ctx = {
            "a": a,
            "a_date": a.date,
            "a_ret": ret_a,
            "p_date": a.date,        # 峰 P 初值 = A（spec：若无满足 V_i ≥ 0.8×V_A 则 P=A）
            "p_bar": a,
            "adjust_bars": [],       # D = {A+1, …, B-1}
            "spring": spring_used,
            # 基底特征标签（判定时已可计算）
            "drift_bucket": _drift_bucket(w[-1].close / w[0].close - 1.0),
            "wick_box": (max(b.high for b in w) - min(b.low for b in w)) / w[-1].close,
            "box_days": _longest_box_days(w, p.box_width_max),
            "box_r": (max(b.close for b in w) - min(b.close for b in w)) / w[-1].close,
        }
        self.state = VPState.TRIGGERED_A
        return None

    def _check_basement(self, w: list[DayBar], w_base: DayBar | None = None) -> bool:
        """蓄势期 W（7 根）全部条件判定

        w_base: W 首根的前一交易日（A-8）。单日防异动按 spec 字面语义
        ∀i∈W: |C_i/C_{i-1}-1| ≤ 5%，i∈W 含首根，首根的基期是 A-8；
        A-8 不可得（历史恰好 68 根边界）时按对齐验证口径跳过首根检查。
        """
        p = self.params
        fx = p.fixed
        # 1. CV7 = std/mean ≤ cv7_max（ddof=1，与 SQL STDDEV_SAMP 对齐）
        vols = [b.volume for b in w]
        mean_v = _mean(vols)
        if mean_v <= 0:
            return False
        cv7 = statistics.stdev(vols) / mean_v
        if cv7 > p.cv7_max:
            return False
        # 2. 量能门（均值门 / 严格版逐日门，A/B 对照口径）
        # 均值门需 A-60 起共 60 根、严格版需 A-7 起的 MA60V(i)（A-66 起 67 根）；
        # 历史不足（_ma 返回 None）→ 该口径不可得 → 不通过（模块 docstring 歧义 2）
        a_idx = len(self.hist) - 1
        if p.vol_gate == "mean":
            # mean(V_i) ≤ 0.8 × MA60V(A-1)：MA60V(A-1) 需 A-60 起共 60 根
            ma60v_prev = _ma(self.hist, a_idx - 1, fx.ma60v_window)
            if ma60v_prev is None or mean_v > fx.vol_mean_gate * ma60v_prev:
                return False
        else:  # strict
            # ∀i∈W: V_i < MA60V(i)，i 最早 = A-7，需 67 根历史
            for off in range(fx.basement_len, 0, -1):  # A-7 … A-1
                i_idx = a_idx - off
                ma60v_i = _ma(self.hist, i_idx, fx.ma60v_window)
                if ma60v_i is None or self.hist[i_idx].volume >= ma60v_i:
                    return False
        # 3. 价格区间盒 R_W ≤ box_width_max（分母 C_{A-1}）
        box_r = (max(b.close for b in w) - min(b.close for b in w)) / w[-1].close
        if box_r > p.box_width_max:
            return False
        # 4. 单日防异动 |ret_i| ≤ 5%（i∈W 含首根，首根基期 = A-8 = w_base）
        if w_base is not None:
            ret_first = w[0].close / w_base.close - 1.0
            if abs(ret_first) > fx.single_day_ret_limit:
                return False
        for j in range(1, len(w)):
            ret_i = w[j].close / w[j - 1].close - 1.0
            if abs(ret_i) > fx.single_day_ret_limit:
                return False
        return True

    # ------------------------------------------------------------------
    # 调整期推进（TRIGGERED_A / PULLBACK 状态）
    # ------------------------------------------------------------------

    def _advance_adjustment(self, bar: DayBar) -> BCandidateEvent | None:
        """调整期推进一根日 K（当前日为候选 B 日）。

        判定顺序（当前日 t）：
        1. 超时：t 超过 A+N → DEAD；
        2. 破位：调整期任一日（含新收盘的昨日）L < O_A 且不满足 Spring 豁免 → DEAD；
        3. 当前日是否为合法 B 日候选（B ≥ P+2 + 末段缩量 + 滞涨，全部只依赖
           ≤ B-1 的数据）→ 是则返回 BCandidateEvent；
        4. 非候选 → 当前日并入 D，若 V_t ≥ 0.8×V_A 则更新峰 P。
        """
        p = self.params
        a = self._a_ctx["a"]
        adjust = self._a_ctx["adjust_bars"]
        day = len(adjust) + 1  # 当前日 = A+day

        # 1. 超时：B ≤ A+N+1，即 day ≤ N+1（超过即淘汰）
        if day > p.n_max + 1:
            self.state = VPState.DEAD
            return None
        # 2. 破位（全 D 范围，含已并入的调整日 + 当前 B 候选日本身的插针：
        #    spec 破位条件作用于全 D 范围，B 候选日 bar 虽不属于 D，但当日
        #    L < O_A 时同样按 Spring 口径判定——不豁免则该日不可能成为合法 B）
        probe_bars = adjust + [bar]
        for d_bar in probe_bars:
            if d_bar.low < a.open:
                if not self._spring_ok(d_bar, a):
                    self.state = VPState.DEAD
                    return None
                # Spring 豁免：保留样本并标记（spec：绩效单列统计）
                self._a_ctx["spring"] = True
        # 3. B 日候选判定（不含当前日自身的数据）
        if self._is_b_candidate():
            return self._make_b_candidate_event(bar)
        # 4. 当前日并入 D，更新峰 P
        self._append_adjust_day(bar)
        return None

    def _append_adjust_day(self, bar: DayBar) -> None:
        """当前日并入调整期 D，若为量能峰则更新锚定 P"""
        a = self._a_ctx["a"]
        self._a_ctx["adjust_bars"].append(bar)
        if bar.volume >= self.params.fixed.peak_anchor_ratio * a.volume:
            # 量能峰 P = D 中最后一个满足 V ≥ 0.8×V_A 的日
            self._a_ctx["p_date"] = bar.date
            self._a_ctx["p_bar"] = bar
            self.state = VPState.PULLBACK

    def _spring_ok(self, d_bar: DayBar, a: DayBar) -> bool:
        """Spring 插针豁免：L < O_A 且 C ≥ O_A 且下影线 ≥ 2×实体"""
        return (
            d_bar.close >= a.open
            and d_bar.lower_wick >= self.params.fixed.spring_wick_body_ratio * d_bar.body
        )

    def _dp_range(self) -> list[DayBar]:
        """回踩段 D' = {P+1, …, B-1}（以当前 adjust_bars 为 D 截至昨日）"""
        p_idx = -1
        for i, b in enumerate(self._a_ctx["adjust_bars"]):
            if b.date == self._a_ctx["p_date"]:
                p_idx = i
        return self._a_ctx["adjust_bars"][p_idx + 1:]

    def _is_b_candidate(self) -> bool:
        """当前日是否为合法 B 日候选（全部条件只依赖 ≤ B-1 数据）。

        条件（spec 阶段三 1~3）：B ≥ P+2（|D'| ≥ 1）、末段缩量、滞涨。
        破位与超时在 _advance_adjustment 已处理（破位用 D 截至昨日 + 当前
        非候选日并入时逐日检查；当日自身低点属于 B 日数据，不在 D 范围）。
        """
        p = self.params
        fx = p.fixed
        a = self._a_ctx["a"]
        # 1. B ≥ P+2 ⇔ |D'| = D 中 P 之后的日数 ≥ 1
        dp = self._dp_range()
        if len(dp) < 1:
            return False
        # 2. 末段缩量：mean(V, D' 末 min(3,|D'|)) ≤ 0.5 × V_A
        k = min(fx.daily_end_vol_days, len(dp))
        end_mean = _mean([b.volume for b in dp[-k:]])
        if end_mean > fx.dp_end_shrink_ratio * a.volume:
            return False
        # 3. 滞涨：∀i∈D': C_i ≤ max(H_A, H_P) × 1.02
        cap = max(a.high, self._a_ctx["p_bar"].high) * fx.stag_high_mult
        for b in dp:
            if b.close > cap:
                return False
        return True

    def _make_b_candidate_event(self, bar: DayBar) -> BCandidateEvent:
        """构造 B 日候选事件（当前日 bar = B 日，其 OHLCV 供日线退化版用）

        注意：B 日 bar 本身不属于 D（D = {A+1…B-1}），暂存仅供日线退化版的
        V_B / gap 判定；若 decide_b_day 判定放弃，_give_up_day 会把它取回
        并入 D。
        """
        fx = self.params.fixed
        a = self._a_ctx["a"]
        dp = self._dp_range()
        k = min(fx.daily_end_vol_days, len(dp))
        dp_end_mean_vol = _mean([b.volume for b in dp[-k:]])
        b_prev = self._a_ctx["adjust_bars"][-1]  # B-1 = D 最后一日
        self._a_ctx["adjust_bars"].append(bar)   # B 日也暂存（退化为日线版时供 V_B 判定）
        return BCandidateEvent(
            machine=self,
            code=self.code,
            a_date=self._a_ctx["a_date"],
            p_date=self._a_ctx["p_date"],
            b_date=bar.date,
            b_prev_close=b_prev.close,
            dp_end_mean_vol=dp_end_mean_vol,
            spring=self._a_ctx["spring"],
            drift_bucket=self._a_ctx["drift_bucket"],
            wick_box=self._a_ctx["wick_box"],
            box_days=self._a_ctx["box_days"],
            vol_gate=self.params.vol_gate,
            box_r=self._a_ctx["box_r"],
            a_ret=self._a_ctx["a_ret"],
            a_open=a.open,
            a_high=a.high,
            adjust_bars=self._a_ctx["adjust_bars"],
        )

    # ------------------------------------------------------------------
    # B 日终判（分钟版 / 日线退化版）
    # ------------------------------------------------------------------

    def decide_b_day(self, event: BCandidateEvent, minute_df=None, f_ratio=None):
        """B 日终判。返回 SignalEvent（触发）或 None（当日放弃）。

        - minute_df 为 None → 日线退化版；
        - minute_df 为 DataFrame（time_key/open/high/low/close/volume，同 kline 表
          结构）→ 分钟级触发扫描。f_ratio 为该股当日 F(t) 函数（vp_volume 模块
          产出，t 为 bar 序号），None 时由 minute_trigger 用均匀分布 0.5 兜底
          （测试/诊断场景；回测必须传真实 F）。
        """
        p = self.params
        fx = p.fixed
        a = self._a_ctx["a"]
        b_bar = event.adjust_bars[-1]  # B 日日 K

        if minute_df is None:
            # ---- 日线退化版（spec：B 日区间无可得 5 分钟数据） ----
            gap = b_bar.open / event.b_prev_close - 1.0
            if not (fx.daily_open_low < gap <= fx.daily_open_high):
                return self._give_up_day()
            if b_bar.volume < fx.daily_vol_mult * event.dp_end_mean_vol:
                return self._give_up_day()
            if b_bar.close <= b_bar.open:
                return self._give_up_day()
            # 触发：买价 B+1 开盘（on_day 回填），同 A 日至多一信号
            signal = SignalEvent(
                code=self.code,
                a_date=event.a_date,
                p_date=event.p_date,
                b_date=event.b_date,
                b_bar_time=None,
                entry_mode="daily",
                buy_price=float("nan"),  # 待 B+1 开盘回填
                vp_bar_ratio=None,
                spring=event.spring,
                drift_bucket=event.drift_bucket,
                wick_box=event.wick_box,
                box_days=event.box_days,
                vol_gate=event.vol_gate,
                box_r=event.box_r,
                a_ret=event.a_ret,
                stop_loss_low=a.open,  # 先挂 max(O_A, ·)，B+1 开盘回填时补足
            )
            self._pending_daily_signal = signal
            return signal

        # ---- 分钟级触发（minute_trigger.py） ----
        trig = scan_minute_trigger(
            minute_df,
            event.b_prev_close,
            event.dp_end_mean_vol,
            p,
            f_ratio=f_ratio,
        )
        if trig is None:
            return self._give_up_day()
        bar_time, buy_price, vp_ratio = trig
        signal = SignalEvent(
            code=self.code,
            a_date=event.a_date,
            p_date=event.p_date,
            b_date=event.b_date,
            b_bar_time=bar_time,
            entry_mode="minute",
            buy_price=buy_price,
            vp_bar_ratio=vp_ratio,
            spring=event.spring,
            drift_bucket=event.drift_bucket,
            wick_box=event.wick_box,
            box_days=event.box_days,
            vol_gate=event.vol_gate,
            box_r=event.box_r,
            a_ret=event.a_ret,
            stop_loss_low=max(a.open, buy_price * p.stop_loss_price_ratio),
        )
        self.signals.append(signal)
        # 终态：等待下一根日 K 复位后重新扫描（口径见模块 docstring）
        self.state = VPState.SIGNAL
        return signal

    def _give_up_day(self) -> None:
        """B 日判定放弃：当前日并入 D（若为量能峰则更新 P），继续等后续 B 日"""
        b_bar = self._a_ctx["adjust_bars"].pop()  # 取回 B 日日 K
        self._append_adjust_day(b_bar)
        return None

    # ------------------------------------------------------------------
    # 复位
    # ------------------------------------------------------------------

    def _reset(self) -> None:
        """终态复位：保留历史，重新进入 BASEMENT 扫描"""
        self.state = VPState.BASEMENT
        self._a_ctx = {}


# ----------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------

def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _ma(hist: list[DayBar], idx: int, window: int) -> float | None:
    """hist[idx-window+1 .. idx] 的均量；数据不足返回 None"""
    if idx - window + 1 < 0:
        return None
    return _mean([b.volume for b in hist[idx - window + 1: idx + 1]])


def _drift_bucket(drift: float) -> str:
    """净漂移三桶：≤-3% / -3%~+3% / ≥+3%"""
    if drift <= -0.03:
        return "low"
    if drift < 0.03:
        return "mid"
    return "high"


def _longest_box_days(w: list[DayBar], box_max: float) -> int:
    """蓄势期 W 内收盘盒宽 ≤ box_max 的最长持续天数（标签，不设门）。

    语义：对 W 的每个后缀窗口 [i..j]，max(close)-min(close) ≤ box_max×C_{A-1}
    的最长天数。C_{A-1} 取 W 最后一根收盘（与 R_W 同分母）。
    """
    base = w[-1].close
    limit = box_max * base
    best = 0
    n = len(w)
    for i in range(n):
        hi = lo = w[i].close
        for j in range(i, n):
            hi = max(hi, w[j].close)
            lo = min(lo, w[j].close)
            if hi - lo <= limit:
                best = max(best, j - i + 1)
            else:
                break
    return best
