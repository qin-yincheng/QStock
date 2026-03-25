"""
双龙战法信号模块 v4（第八阶段 — ATR/量能增强）

第一龙：EMA5 上穿 EMA10（均线金叉）
第二龙：MACD DIF 上穿 DEA（MACD 金叉）
双龙齐飞 = 两个金叉在 lookback 窗口内同时出现

v4 新增：
  - ATR14 列（供回测引擎做自适应止损/止盈）
  - vol_ma20 / vol_ratio 列（供量能确认使用）

v3 基础：
  - lookback_window 默认 5（原 3，过紧）
  - 取消 require_macd_positive 默认限制（零轴附近金叉也有效）
  - 新增 BUY_EARLY 信号（仅 EMA 金叉 + MACD 方向向上，低强度但增加覆盖面）
  - 新增趋势状态输出 bullish/bearish/neutral
"""

import pandas as pd
import pandas_ta as ta
from czsc import RawBar
from typing import List


class DragonSignalGenerator:
    """双龙战法信号生成器 v4"""

    def __init__(
        self,
        bars: List[RawBar],
        lookback_window: int = 5,
        require_macd_positive: bool = False,
    ):
        self.lookback = lookback_window
        self.require_macd_positive = require_macd_positive
        self.df = self._bars_to_df(bars)
        self._calculate()

    def _bars_to_df(self, bars: List[RawBar]) -> pd.DataFrame:
        records = [
            {
                "datetime": bar.dt,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.vol,
            }
            for bar in bars
        ]
        return pd.DataFrame(records)

    def _calculate(self):
        df = self.df

        df["ema5"] = ta.ema(df["close"], length=5)
        df["ema10"] = ta.ema(df["close"], length=10)

        macd_result = ta.macd(df["close"], fast=12, slow=26, signal=9)
        df["dif"] = macd_result.iloc[:, 0]
        df["dea"] = macd_result.iloc[:, 1]
        df["macd_hist"] = macd_result.iloc[:, 2]

        df["ema_cross_up"] = (df["ema5"] > df["ema10"]) & (
            df["ema5"].shift(1) <= df["ema10"].shift(1)
        )
        df["ema_cross_down"] = (df["ema5"] < df["ema10"]) & (
            df["ema5"].shift(1) >= df["ema10"].shift(1)
        )
        df["macd_cross_up"] = (df["dif"] > df["dea"]) & (
            df["dif"].shift(1) <= df["dea"].shift(1)
        )
        df["macd_cross_down"] = (df["dif"] < df["dea"]) & (
            df["dif"].shift(1) >= df["dea"].shift(1)
        )

        df["ema_buy_window"] = (
            df["ema_cross_up"].rolling(self.lookback).max().fillna(0).astype(bool)
        )
        df["macd_buy_window"] = (
            df["macd_cross_up"].rolling(self.lookback).max().fillna(0).astype(bool)
        )

        df["ema_bullish"] = df["ema5"] > df["ema10"]
        df["macd_rising"] = df["dif"] > df["dif"].shift(1)

        df["atr14"] = ta.atr(df["high"], df["low"], df["close"], length=14)

        df["vol_ma20"] = df["volume"].rolling(20).mean()
        df["vol_ratio"] = df["volume"] / df["vol_ma20"].replace(0, float("nan"))

        self.df = df

    def get_trend_state(self) -> str:
        """获取当前趋势状态：bullish / bearish / neutral"""
        last = self.df.iloc[-1]
        ema_bull = last.get("ema_bullish", False)
        dif_above_dea = last["dif"] > last["dea"] if pd.notna(last["dif"]) else False

        if ema_bull and dif_above_dea:
            return "bullish"
        if not ema_bull and not dif_above_dea:
            return "bearish"
        return "neutral"

    def get_signal(self) -> dict:
        """获取最新一根 K 线的双龙信号"""
        last = self.df.iloc[-1]

        signal = "HOLD"
        detail = ""

        if last["ema_cross_down"] or last["macd_cross_down"]:
            signal = "SELL"
            parts = []
            if last["ema_cross_down"]:
                parts.append("EMA死叉")
            if last["macd_cross_down"]:
                parts.append("MACD死叉")
            detail = f"死叉: {'+'.join(parts)}"

        elif (
            last["ema_buy_window"]
            and last["macd_buy_window"]
            and last["dif"] > last["dea"]
            and last["dea"] > 0
        ):
            signal = "STRONG_BUY"
            detail = (
                f"双龙齐飞(强): EMA5={last['ema5']:.2f}>"
                f"EMA10={last['ema10']:.2f}, DIF>DEA>0"
            )

        elif last["ema_buy_window"] and last["macd_buy_window"] and last["dif"] > last["dea"]:
            signal = "BUY"
            detail = (
                f"双龙齐飞: EMA5={last['ema5']:.2f}>"
                f"EMA10={last['ema10']:.2f}, DIF>DEA"
            )

        elif last["ema_cross_up"] and last.get("macd_rising", False):
            signal = "BUY_EARLY"
            detail = (
                f"早期买入: EMA金叉+MACD方向向上, "
                f"EMA5={last['ema5']:.2f}, DIF={last['dif']:.4f}"
            )

        trend = self.get_trend_state()
        return {
            "signal": signal,
            "detail": detail,
            "trend": trend,
            "ema5": round(last["ema5"], 2) if pd.notna(last["ema5"]) else None,
            "ema10": round(last["ema10"], 2) if pd.notna(last["ema10"]) else None,
            "dif": round(last["dif"], 4) if pd.notna(last["dif"]) else None,
            "dea": round(last["dea"], 4) if pd.notna(last["dea"]) else None,
            "macd_hist": (
                round(last["macd_hist"], 4) if pd.notna(last["macd_hist"]) else None
            ),
        }

    def get_all_signals(self) -> pd.DataFrame:
        """返回带信号标注的完整 DataFrame（回测用）"""
        df = self.df.copy()
        df["dragon_signal"] = "HOLD"

        sell = df["ema_cross_down"] | df["macd_cross_down"]

        strong_buy = (
            df["ema_buy_window"]
            & df["macd_buy_window"]
            & (df["dif"] > df["dea"])
            & (df["dea"] > 0)
        )
        normal_buy = (
            df["ema_buy_window"]
            & df["macd_buy_window"]
            & (df["dif"] > df["dea"])
            & ~strong_buy
        )
        early_buy = (
            df["ema_cross_up"]
            & df["macd_rising"]
            & ~strong_buy
            & ~normal_buy
        )

        df.loc[early_buy, "dragon_signal"] = "BUY_EARLY"
        df.loc[normal_buy, "dragon_signal"] = "BUY"
        df.loc[strong_buy, "dragon_signal"] = "STRONG_BUY"
        df.loc[sell, "dragon_signal"] = "SELL"

        df["dragon_trend"] = "neutral"
        bullish = df["ema_bullish"] & (df["dif"] > df["dea"])
        bearish = ~df["ema_bullish"] & (df["dif"] <= df["dea"])
        df.loc[bullish, "dragon_trend"] = "bullish"
        df.loc[bearish, "dragon_trend"] = "bearish"

        return df
