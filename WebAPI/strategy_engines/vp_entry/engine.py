# -*- coding: utf-8 -*-
"""
VpEntryEngine — 量价三段式买点策略引擎（vp-entry-strategy-integration
tasks 2.1/2.2，design D2/D3）。

复用 vol_breakout 引擎整体模式（协议对齐、水位门、全史重算 + 唯一键 upsert
幂等，幂等由 store 层 ON CONFLICT ... WHERE frozen = FALSE 保证）：

- 读 DuckDB 该 code 全历史日线，逐根喂入 VPStateMachine（判定内核，D1 迁入）；
- 水位门：watermark 非空且其后无新 K 线 → 返回 []（无演进，调度方不推进水位）；
- B 日候选懒加载分钟数据（K_5M）：当日查 K_5M，有则分钟版终判（F(t) 用该股
  B 日前的分钟历史构造，per-scan 内存缓存仿 run_backtest 的 f_ratio_cache），
  无则日线退化版兜底；
- 信号行映射（D2）：signal_date = b_date / is_buy=True / state 由 D3 状态追踪
  推导 / entry_ref_price = buy_price / stop_ref_price = stop_loss_low；
  payload 携带 a_date/p_date/entry_mode/volume_ratio/spring/drift_bucket/
  wick_box/box_days/box_r/a_ret/b_bar_time/b_high（b_high 供 D3 状态重放与
  kv 统计）；
- 绩效四字段（strategy-signal-outcome D9）：匹配态（triggered/running）事件
  带 ret_7d/ret_14d/ret_30d/outcome——入场日 = 分钟版 B 日 / 日线版 B+1 日
  （买价口径：分钟版 = 触发分钟收盘、日线版 = B+1 开盘），复用通用
  compute_outcome；payload 按缺补齐 A/B 点过程字段 a_close/a_pct/b_date/
  b_open/b_close/b_day_pct（6.2：B 日日线 OHLC，分钟版 = B 日、日线版 =
  B+1 日，b_day_pct = b_close/b_open - 1 引擎直出）/close_7d/close_14d/
  close_30d（D10）；
- B 日后状态追踪（D3，纯函数式重放）：triggered（B 日触发）→ close > b_high
  → running / close < stop_loss_low → expired；同日双满足按 expired 优先
  （保守口径）；未演进保持 triggered。

硬性约束：绝不 import CChan 任何模块，只读 DuckDB（KLineStore read_only）；
不触碰 bsp_index 与缠论内核。
"""

import logging
from typing import Optional

import pandas as pd

from ChanAnalyse.DataAPI.KLineStore import DEFAULT_DB_PATH, KLineStore

from ...config import DUCKDB_PATH
from .. import compute_outcome
from .params import VPParams
from .signal_rule import DayBar, VPStateMachine
from .vp_volume import build_f_ratio

log = logging.getLogger("strategy_vp_entry")

# 分钟数据 kl_type（B 日懒加载口径，与 run_backtest 的 K_5M 一致）
_MINUTE_KL_TYPE = "K_5M"


def _duckdb_path() -> str:
    """DuckDB 路径（与 vol_breakout._duckdb_path 同口径）。"""
    import os

    return DUCKDB_PATH if os.path.exists(DUCKDB_PATH) else DEFAULT_DB_PATH


class VpEntryEngine:
    """量价三段式买点引擎（实现 StrategyEngine 协议）。

    scan 为协议入口（引擎默认参数）；调度方带实例参数扫描走 scan_with_params。
    两条路径都读该 code 全历史日线重算信号全集（蓄势期需要 60+ 根历史上下文），
    结果经 store 层唯一键 (task_id, code, signal_date=B 日) upsert 天然幂等——
    已 frozen 的行不被覆盖。
    """

    def scan(
        self,
        code: str,
        kl_type_db: str = "K_DAY",
        autype: str = "QFQ",
        watermark: Optional[str] = None,
    ) -> list[dict]:
        """扫描一只股票，返回 SignalEvent dict 列表（可能为空）。"""
        return self.scan_with_params(
            code, self._default_params(), kl_type_db, autype, watermark
        )

    @staticmethod
    def _default_params() -> dict:
        """引擎默认参数（与 params_schema 声明的 default 一致，供无参调用兜底）。"""
        return {
            "cv7_max": 0.25,
            "box_width_max": 0.12,
            "n_max": 7,
            "stop_loss": 0.12,
            "vol_gate": "mean",
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
                if not rows:
                    return []

                latest_time_key = str(rows[-1][0])
                # 水位门（D2）：watermark 之后无新 K 线 → 不重算
                if watermark is not None and latest_time_key <= str(watermark):
                    return []

                kl = [
                    (str(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]),
                     float(r[5]) if r[5] is not None else 0.0)
                    for r in rows
                ]
                events = self._scan_series(store, code, kl, autype, self._merge_params(params))
        except Exception as e:  # 锁冲突/文件缺失：单键失败上抛由调度方跳过
            log.warning("读取 DuckDB 失败 %s: %s", code, e)
            raise

        for ev in events:
            ev["watermark_new"] = latest_time_key
        return events

    @staticmethod
    def _merge_params(params: Optional[dict]) -> dict:
        """默认参数 + 实例参数合并（调度方透传的 params 缺键时兜底）。"""
        merged = {**VpEntryEngine._default_params(), **(params or {})}
        return {
            "cv7_max": float(merged["cv7_max"]),
            "box_width_max": float(merged["box_width_max"]),
            "n_max": int(merged["n_max"]),
            "stop_loss": float(merged["stop_loss"]),
            "vol_gate": str(merged["vol_gate"]),
        }

    # ------------------------------------------------------------------
    # 序列扫描（D2：状态机喂入 + B 日分钟懒加载 + 事件转换；
    # 纯函数：便于 Debug 冒烟脚本构造 K 线序列直测）
    # ------------------------------------------------------------------

    def _scan_series(
        self,
        store: KLineStore,
        code: str,
        kl: list[tuple],
        autype: str,
        params: dict,
    ) -> list[dict]:
        """在日线序列上识别全部 VP 信号事件（signal_date = B 日）。

        - VPParams 组装：任务侧 5 个连续参数 + 定死参数（D2：离散敏感性校验
          已外移回测侧，dataclass 不拦截连续取值）；
        - B 日分钟懒加载：候选事件当日查 K_5M，有则分钟版（F(t) per-scan 缓存），
          无则日线退化版；
        - 每条 SignalEvent 重放 B 日之后的日 K 推导状态（D3）。
        """
        vp_params = VPParams(**params)
        machine = VPStateMachine(code=code, params=vp_params)
        f_ratio_cache: dict[str, Optional[dict]] = {}  # F(t) 按 B 日缓存

        pending = None  # 待终判的 B 候选（当日喂入产生）
        for row in kl:
            d, o, h, low, c, v = row
            if pending is not None:
                # 候选在 B 日喂入时产生、下一根喂入前终判：分钟数据属于 B 日
                # （pending.b_date），不是当前行日期（B+1）
                self._decide_with_minute(
                    store, machine, pending, code, pending.b_date, autype, f_ratio_cache
                )
                pending = None
            ev = machine.on_day(DayBar(d, o, h, low, c, v))
            if ev is not None:
                pending = ev
        # 末端悬置候选：无 B+1 数据，日线版买价无法回填 → 当日放弃（不产信号）
        if pending is not None:
            machine.decide_b_day(pending, minute_df=None)

        # 全史信号 → 事件 dict（含 D3 状态重放；b_high 补进 payload 留档）
        bars_by_date = {r[0]: r for r in kl}
        dates = [r[0] for r in kl]
        events = []
        for sig in machine.signals:
            state = self._replay_state(sig, bars_by_date, dates)
            ev = self._to_event(code, sig, state)
            ev["payload"]["b_high"] = (
                round(bars_by_date[sig.b_date][2], 4) if sig.b_date in bars_by_date else None
            )
            # 绩效四字段 + A/B 点过程字段补齐（strategy-signal-outcome D9/D10）：
            # 入场日 = 分钟版 B 日 / 日线版 B+1 日；B 日索引在 dates 现成可得，
            # 同一段循环复用 compute_outcome。绩效四键只对匹配态
            # （triggered/running）计算（spec「匹配信号」口径）；expired/
            # watching 态同样带 payload 过程字段（b_date/close_*），绩效为 None
            ev["ret_7d"] = ev["ret_14d"] = ev["ret_30d"] = ev["outcome"] = None
            if sig.b_date in dates:
                b_idx = dates.index(sig.b_date)
                # 日线版买价在 B+1 开盘回填：入场日 = B+1（成交日在 B+1）
                entry_idx = b_idx if sig.entry_mode == "minute" else b_idx + 1
                entry_price = ev["entry_ref_price"]
                is_matched = state in ("triggered", "running")
                if entry_price is not None and entry_idx < len(kl):
                    ret_7d, ret_14d, ret_30d, outcome, c7, c14, c30 = compute_outcome(
                        entry_idx, entry_price, kl
                    )
                    if is_matched:
                        ev["ret_7d"] = ret_7d
                        ev["ret_14d"] = ret_14d
                        ev["ret_30d"] = ret_30d
                        ev["outcome"] = outcome
                    # B 日 OHLC（D10/6.2：分钟版 = B 日、日线版 = B+1 日，
                    # 与入场日同索引；b_day_pct = 收盘/开盘 - 1 引擎直出）
                    ev["payload"]["b_date"] = kl[entry_idx][0][:10]
                    b_open = kl[entry_idx][1]
                    b_close = kl[entry_idx][4]
                    ev["payload"]["b_open"] = (
                        round(b_open, 4) if b_open is not None else None
                    )
                    ev["payload"]["b_close"] = (
                        round(b_close, 4) if b_close is not None else None
                    )
                    ev["payload"]["b_day_pct"] = (
                        round(b_close / b_open - 1.0, 6)
                        if (b_open and b_open > 0 and b_close is not None) else None
                    )
                    ev["payload"]["close_7d"] = round(c7, 4) if c7 is not None else None
                    ev["payload"]["close_14d"] = round(c14, 4) if c14 is not None else None
                    ev["payload"]["close_30d"] = round(c30, 4) if c30 is not None else None
                else:
                    # 买价缺失/入场日越界（防御性，理论上不出现）
                    ev["payload"]["b_date"] = kl[entry_idx][0][:10] if entry_idx < len(kl) else None
                    ev["payload"].setdefault("b_open", None)
                    ev["payload"].setdefault("b_close", None)
                    ev["payload"].setdefault("b_day_pct", None)
                    ev["payload"].setdefault("close_7d", None)
                    ev["payload"].setdefault("close_14d", None)
                    ev["payload"].setdefault("close_30d", None)
            # A 日过程字段按缺补齐（a_date 已有；a_close 从 A 日 bar 收盘取，
            # a_pct 直接复用 SignalEvent.a_ret——A 日涨幅判定口径）
            if sig.a_date in bars_by_date:
                a_bar = bars_by_date[sig.a_date]
                ev["payload"].setdefault("a_close", round(float(a_bar[4]), 4))
            ev["payload"].setdefault("a_pct", round(sig.a_ret, 6))
            events.append(ev)
        return events

    def _decide_with_minute(
        self,
        store: KLineStore,
        machine: VPStateMachine,
        event,
        code: str,
        b_date: str,
        autype: str,
        f_ratio_cache: dict,
    ) -> None:
        """B 日终判：当日有 K_5M → 分钟版（懒加载 + F 缓存）；无 → 日线退化版。

        F(t) 用 B 日前的分钟历史构造（run_backtest 同口径）；历史不足构造
        失败时 f_ratio=None（minute_trigger 用均匀分布兜底仅限诊断——引擎按
        「F 不可得 → 不触发」处理：build_f_ratio 抛 ValueError 时当日按
        无分钟数据推进日线退化版，避免兜底口径混入生产判定）。
        """
        try:
            mdf = pd.DataFrame(
                store.execute(
                    """
                    SELECT time_key, open, high, low, close, volume
                    FROM kline
                    WHERE code = ? AND kl_type = ? AND autype = ?
                      AND SUBSTR(time_key, 1, 10) = ?
                    ORDER BY time_key
                    """,
                    [code, _MINUTE_KL_TYPE, autype, b_date],
                ),
                columns=["time_key", "open", "high", "low", "close", "volume"],
            )
        except Exception as e:
            log.warning("读 K_5M 失败 %s %s（按日线退化版推进）: %s", code, b_date, e)
            machine.decide_b_day(event, minute_df=None)
            return

        if mdf.empty:
            machine.decide_b_day(event, minute_df=None)
            return

        # 分钟版：构造/复用该股截至 B 日前的 F(t)（per-scan 缓存，key = B 日）
        if b_date not in f_ratio_cache:
            f_ratio = None
            try:
                hist = pd.DataFrame(
                    store.execute(
                        """
                        SELECT time_key, open, high, low, close, volume
                        FROM kline
                        WHERE code = ? AND kl_type = ? AND autype = ?
                          AND SUBSTR(time_key, 1, 10) < ?
                        ORDER BY time_key
                        """,
                        [code, _MINUTE_KL_TYPE, autype, b_date],
                    ),
                    columns=["time_key", "open", "high", "low", "close", "volume"],
                )
                if not hist.empty:
                    f_ratio = build_f_ratio(hist)
            except ValueError:
                f_ratio = None  # 无完整样本日：F 不可得
            except Exception as e:
                log.warning("构造 F(t) 失败 %s %s: %s", code, b_date, e)
                f_ratio = None
            f_ratio_cache[b_date] = f_ratio
        machine.decide_b_day(event, minute_df=mdf, f_ratio=f_ratio_cache[b_date])

    # ------------------------------------------------------------------
    # B 日后状态追踪（D3：纯函数式重放）
    # ------------------------------------------------------------------

    @staticmethod
    def _replay_state(sig, bars_by_date: dict, dates: list[str]) -> str:
        """重放 B 日之后的日 K 推导信号状态（design D3）。

        - close > b_high → running（上破 B 日最高价）
        - close < stop_loss_low → expired（跌破止损参考低点）
        - 同日双满足按 expired 优先（保守口径，design 记录）
        - 未发生演进保持 triggered
        - 买价缺失（日线版 B+1 回填未完成，理论上不出现：末端悬置候选已放弃）
          → 保持 triggered
        """
        b_date = sig.b_date
        if b_date not in bars_by_date:
            return "triggered"
        stop = sig.stop_loss_low
        # B 日 bar（重放基准 b_high 取自 B 日 high）
        b_high = bars_by_date[b_date][2]
        idx = dates.index(b_date)
        # 日线版买价在 B+1 开盘回填：状态重放从 B+1 起看（与分钟版同为「B 日后」
        # 的日 K 序列；B 日本身收盘不可能既触发又演进——触发即信号产生）
        for d in dates[idx + 1:]:
            _, _, _, _, close, _ = bars_by_date[d]
            if stop is not None and close < stop:
                return "expired"
            if close > b_high:
                return "running"
        return "triggered"

    # ------------------------------------------------------------------
    # SignalEvent → 信号行事件转换（D2 字段映射）
    # ------------------------------------------------------------------

    @staticmethod
    def _to_event(code: str, sig, state: str) -> dict:
        """SignalEvent dataclass → 策略信号事件 dict（D2 字段口径）。"""
        return {
            "code": code,
            "signal_date": sig.b_date,
            "state": state,
            "is_buy": True,  # VP 三段式买点恒为买方向
            "entry_ref_price": round(sig.buy_price, 4) if sig.buy_price == sig.buy_price else None,
            "stop_ref_price": round(sig.stop_loss_low, 4) if sig.stop_loss_low is not None else None,
            "payload": {
                "a_date": sig.a_date,
                "p_date": sig.p_date,
                "entry_mode": sig.entry_mode,          # minute / daily（分钟版/日线版）
                "volume_ratio": round(sig.vp_bar_ratio, 4) if sig.vp_bar_ratio is not None else None,
                "spring": bool(sig.spring),
                "drift_bucket": sig.drift_bucket,      # low / mid / high
                "wick_box": round(sig.wick_box, 6),
                "box_days": int(sig.box_days),
                "box_r": round(sig.box_r, 6),
                "a_ret": round(sig.a_ret, 6),
                "b_bar_time": sig.b_bar_time,          # 触发分钟（分钟版；日线版 None）
            },
        }
