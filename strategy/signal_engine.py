"""
信号融合引擎 v4（第八阶段 — 多周期趋势过滤）

v4 新增：
  - 日线趋势过滤：EMA20/EMA60 判断大方向（UP/DOWN/SIDE）
  - UP 时接受全部买入，弱卖出（REDUCE）降级
  - DOWN 时拒绝全部买入，强化卖出
  - SIDE 时仅保留 STRONG_BUY，其余买入降级
  - daily_bars=None 时行为与 v3 完全一致（向后兼容）

v3 基础：
  - 买入不再要求严格 AND 共振，缠论买点 + 双龙趋势向上即可
  - 卖出分层：缠论卖 → SELL_ALL，双龙死叉 → REDUCE
  - BUY_EARLY 处理，confidence 映射仓位比例
"""

import pandas as pd
import pandas_ta as ta
from czsc import RawBar, Freq
from typing import List, Optional, Dict
from strategy.chan_signals import ChanSignalGenerator
from strategy.dragon_signals import DragonSignalGenerator


class SignalEngine:
    """综合信号引擎 v4（含日线趋势过滤）"""

    def __init__(self, bars: List[RawBar], daily_bars: Optional[List[RawBar]] = None):
        self.bars = bars
        self.chan = ChanSignalGenerator(bars)
        self.dragon = DragonSignalGenerator(bars)
        self.daily_trend_map: Dict[str, str] = {}
        if daily_bars and len(daily_bars) >= 60:
            self.daily_trend_map = compute_daily_trend(daily_bars)

    def generate(self) -> dict:
        chan_result = self.chan.analyze()
        dragon_result = self.dragon.get_signal()

        last_date = str(pd.Timestamp(self.bars[-1].dt).date())
        d_trend = self.daily_trend_map.get(last_date, "UNKNOWN")

        final = self._fuse(
            chan_signal=chan_result["signal"],
            chan_trend=chan_result["trend"],
            dragon_signal=dragon_result["signal"],
            dragon_trend=dragon_result.get("trend", "neutral"),
            filters=chan_result.get("filters", {}),
            daily_trend=d_trend,
        )

        return {
            "final_signal": final["action"],
            "confidence": final["confidence"],
            "reason": final["reason"],
            "chan_signal": chan_result["signal"],
            "chan_detail": chan_result["detail"],
            "chan_trend": chan_result["trend"],
            "dragon_signal": dragon_result["signal"],
            "dragon_detail": dragon_result["detail"],
            "dragon_trend": dragon_result.get("trend", "neutral"),
            "daily_trend": d_trend,
            "bi_count": chan_result["bi_count"],
            "last_bi_direction": chan_result["last_bi_direction"],
            "ema5": dragon_result["ema5"],
            "ema10": dragon_result["ema10"],
            "dif": dragon_result["dif"],
            "dea": dragon_result["dea"],
            "filters": chan_result.get("filters", {}),
        }

    def _fuse(
        self,
        chan_signal: str,
        chan_trend: str,
        dragon_signal: str,
        dragon_trend: str,
        filters: dict,
        daily_trend: str = "UNKNOWN",
    ) -> dict:
        """
        v4 融合规则（在 v3 基础上加入日线趋势过滤）:
        --- 日线过滤（仅影响买入，不干预卖出/减仓） ---
        DOWN → 拒绝全部买入
        SIDE → 仅保留 STRONG_BUY
        UP   → 全部放行（卖出/减仓照常执行）
        """
        raw = _fuse_raw(chan_signal, chan_trend, dragon_signal, dragon_trend)
        action, confidence, reason = raw["action"], raw["confidence"], raw["reason"]

        if daily_trend == "UNKNOWN":
            return {"action": action, "confidence": confidence, "reason": reason}

        is_buy = action in ("STRONG_BUY", "BUY", "BUY_EARLY", "BUY_WATCH", "WAIT_CONFIRM")

        if daily_trend == "DOWN" and is_buy:
            return {
                "action": "HOLD",
                "confidence": 0.0,
                "reason": f"日线DOWN过滤: 原{action}({reason})",
            }

        if daily_trend == "SIDE" and is_buy and action != "STRONG_BUY":
            return {
                "action": "HOLD",
                "confidence": 0.0,
                "reason": f"日线SIDE过滤: 原{action}({reason})",
            }

        return {"action": action, "confidence": confidence, "reason": reason}


def _fuse_raw(
    chan_signal: str,
    chan_trend: str,
    dragon_signal: str,
    dragon_trend: str,
) -> dict:
    """v3 原始融合规则（不含日线过滤），供 SignalEngine 和 Backtester 复用。"""
    chan_buy = chan_signal.startswith("BUY")
    chan_sell = chan_signal.startswith("SELL")
    dragon_strong = dragon_signal == "STRONG_BUY"
    dragon_buy = dragon_signal in ("BUY", "STRONG_BUY")
    dragon_early = dragon_signal == "BUY_EARLY"
    dragon_sell = dragon_signal == "SELL"
    dragon_bullish = dragon_trend == "bullish"
    chan_up = chan_trend == "up"

    if chan_sell:
        return {
            "action": "SELL_ALL",
            "confidence": 0.85,
            "reason": f"缠论卖出 [{chan_signal}], 双龙:{dragon_signal}",
        }

    if dragon_sell and not chan_buy:
        return {
            "action": "REDUCE",
            "confidence": 0.60,
            "reason": f"双龙死叉减仓 [{dragon_signal}], 缠论:{chan_signal}",
        }

    if chan_buy and dragon_strong:
        return {
            "action": "STRONG_BUY",
            "confidence": 0.90,
            "reason": f"强买: 缠论{chan_signal}+双龙齐飞(强)",
        }

    if chan_buy and dragon_buy:
        return {
            "action": "BUY",
            "confidence": 0.80,
            "reason": f"买入: 缠论{chan_signal}+双龙确认",
        }

    if chan_buy and dragon_bullish:
        return {
            "action": "BUY",
            "confidence": 0.70,
            "reason": f"买入: 缠论{chan_signal}+双龙趋势向上",
        }

    if dragon_buy and chan_up:
        return {
            "action": "BUY",
            "confidence": 0.65,
            "reason": f"买入: 双龙{dragon_signal}+缠论趋势向上",
        }

    if chan_buy:
        return {
            "action": "WAIT_CONFIRM",
            "confidence": 0.55,
            "reason": f"等待: 缠论{chan_signal}但双龙未共振",
        }

    if dragon_buy or dragon_strong:
        return {
            "action": "BUY_WATCH",
            "confidence": 0.50,
            "reason": f"观察: 双龙{dragon_signal}但缠论无买点({chan_signal})",
        }

    if dragon_early and (dragon_bullish or chan_up):
        return {
            "action": "BUY_EARLY",
            "confidence": 0.40,
            "reason": f"早期买入: 双龙EMA金叉+趋势向上",
        }

    if dragon_sell and chan_buy:
        return {
            "action": "HOLD",
            "confidence": 0.0,
            "reason": f"信号矛盾: 缠论买{chan_signal} vs 双龙卖{dragon_signal}",
        }

    return {
        "action": "HOLD",
        "confidence": 0.0,
        "reason": f"无信号 [缠论:{chan_signal}, 双龙:{dragon_signal}]",
    }


# ------------------------------------------------------------------ #
#  日线趋势计算                                                         #
# ------------------------------------------------------------------ #


def compute_daily_trend(daily_bars: List[RawBar]) -> Dict[str, str]:
    """
    基于日线 EMA20/EMA60 计算每日趋势方向。

    Returns:
        {date_str: "UP"/"DOWN"/"SIDE"} 映射表
    """
    if not daily_bars or len(daily_bars) < 60:
        return {}

    df = pd.DataFrame([{
        "dt": bar.dt,
        "close": bar.close,
    } for bar in daily_bars])
    df = df.sort_values("dt").reset_index(drop=True)

    df["ema20"] = ta.ema(df["close"], length=20)
    df["ema60"] = ta.ema(df["close"], length=60)
    df["ema20_slope"] = df["ema20"] - df["ema20"].shift(5)

    trend_map: Dict[str, str] = {}
    for _, row in df.iterrows():
        if pd.isna(row["ema20"]) or pd.isna(row["ema60"]) or pd.isna(row["ema20_slope"]):
            continue
        date_str = str(pd.Timestamp(row["dt"]).date())
        if row["ema20"] > row["ema60"] and row["ema20_slope"] > 0:
            trend_map[date_str] = "UP"
        elif row["ema20"] < row["ema60"] and row["ema20_slope"] < 0:
            trend_map[date_str] = "DOWN"
        else:
            trend_map[date_str] = "SIDE"

    return trend_map


# ------------------------------------------------------------------ #
#  便捷函数                                                            #
# ------------------------------------------------------------------ #


def analyze_stock(
    symbol: str, sdt: str, edt: str,
    freq: Freq = Freq.F30,
    use_daily_filter: bool = False,
) -> dict:
    from core.data_provider import get_raw_bars

    bars = get_raw_bars(symbol, freq, sdt, edt)
    if not bars or len(bars) < 30:
        return {"error": f"{symbol} 数据不足"}

    daily_bars = None
    if use_daily_filter:
        daily_bars = get_raw_bars(symbol, Freq.D, sdt, edt)

    engine = SignalEngine(bars, daily_bars=daily_bars)
    result = engine.generate()
    result["symbol"] = symbol
    result["datetime"] = str(bars[-1].dt)
    result["close"] = bars[-1].close
    result["bar_count"] = len(bars)
    result["freq"] = str(freq)
    return result


def analyze_stock_realtime(symbol: str, freq: Freq = Freq.F30) -> dict:
    from core.data_provider_realtime import get_raw_bars

    bars = get_raw_bars(symbol, freq, realtime=True)
    if not bars or len(bars) < 30:
        return {"error": f"{symbol} 数据不足"}

    engine = SignalEngine(bars)
    result = engine.generate()
    result["symbol"] = symbol
    result["datetime"] = str(bars[-1].dt)
    result["close"] = bars[-1].close
    result["bar_count"] = len(bars)
    result["freq"] = str(freq)
    result["data_source"] = "realtime"
    return result
