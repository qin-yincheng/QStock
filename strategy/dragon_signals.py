"""
双龙战法信号模块
第一龙：EMA5 上穿 EMA10（均线金叉）
第二龙：MACD DIF 上穿 DEA（MACD 金叉）
双龙齐飞 = 两个金叉在 lookback 窗口内同时出现
"""
import pandas as pd
import pandas_ta as ta
from czsc import RawBar
from typing import List


class DragonSignalGenerator:
    """双龙战法信号生成器"""

    def __init__(self, bars: List[RawBar], lookback_window: int = 3):
        self.lookback = lookback_window
        self.df = self._bars_to_df(bars)
        self._calculate()

    def _bars_to_df(self, bars: List[RawBar]) -> pd.DataFrame:
        records = [{
            'datetime': bar.dt, 'open': bar.open, 'high': bar.high,
            'low': bar.low, 'close': bar.close, 'volume': bar.vol,
        } for bar in bars]
        return pd.DataFrame(records)

    def _calculate(self):
        df = self.df

        df['ema5'] = ta.ema(df['close'], length=5)
        df['ema10'] = ta.ema(df['close'], length=10)

        macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
        df['dif'] = macd.iloc[:, 0]
        df['dea'] = macd.iloc[:, 1]
        df['macd_hist'] = macd.iloc[:, 2]

        df['ema_cross_up'] = (
            (df['ema5'] > df['ema10'])
            & (df['ema5'].shift(1) <= df['ema10'].shift(1))
        )
        df['ema_cross_down'] = (
            (df['ema5'] < df['ema10'])
            & (df['ema5'].shift(1) >= df['ema10'].shift(1))
        )
        df['macd_cross_up'] = (
            (df['dif'] > df['dea'])
            & (df['dif'].shift(1) <= df['dea'].shift(1))
        )
        df['macd_cross_down'] = (
            (df['dif'] < df['dea'])
            & (df['dif'].shift(1) >= df['dea'].shift(1))
        )

        df['ema_buy_window'] = (
            df['ema_cross_up']
            .rolling(self.lookback).max().fillna(0).astype(bool)
        )
        df['macd_buy_window'] = (
            df['macd_cross_up']
            .rolling(self.lookback).max().fillna(0).astype(bool)
        )

        self.df = df

    def get_signal(self) -> dict:
        """获取最新一根 K 线的双龙信号"""
        last = self.df.iloc[-1]

        signal = 'HOLD'
        detail = ''

        if last['ema_cross_down'] or last['macd_cross_down']:
            signal = 'SELL'
            parts = []
            if last['ema_cross_down']:
                parts.append('EMA死叉')
            if last['macd_cross_down']:
                parts.append('MACD死叉')
            detail = f"死叉: {'+'.join(parts)}"
        elif (last['ema_buy_window'] and last['macd_buy_window']
              and last['macd_hist'] > 0 and last['dea'] > 0):
            signal = 'STRONG_BUY'
            detail = (f"双龙齐飞(强): EMA5={last['ema5']:.2f}>"
                      f"EMA10={last['ema10']:.2f}, DIF>DEA>0")
        elif (last['ema_buy_window'] and last['macd_buy_window']
              and last['macd_hist'] > 0):
            signal = 'BUY'
            detail = (f"双龙齐飞: EMA5={last['ema5']:.2f}>"
                      f"EMA10={last['ema10']:.2f}, MACD柱正")

        return {
            'signal': signal,
            'detail': detail,
            'ema5': round(last['ema5'], 2) if pd.notna(last['ema5']) else None,
            'ema10': round(last['ema10'], 2) if pd.notna(last['ema10']) else None,
            'dif': round(last['dif'], 4) if pd.notna(last['dif']) else None,
            'dea': round(last['dea'], 4) if pd.notna(last['dea']) else None,
            'macd_hist': round(last['macd_hist'], 4) if pd.notna(last['macd_hist']) else None,
        }

    def get_all_signals(self) -> pd.DataFrame:
        """返回带信号标注的完整 DataFrame（回测用）"""
        df = self.df.copy()
        df['dragon_signal'] = 'HOLD'

        sell = df['ema_cross_down'] | df['macd_cross_down']
        strong_buy = (
            df['ema_buy_window'] & df['macd_buy_window']
            & (df['macd_hist'] > 0) & (df['dea'] > 0)
        )
        normal_buy = (
            df['ema_buy_window'] & df['macd_buy_window']
            & (df['macd_hist'] > 0) & ~strong_buy
        )

        df.loc[normal_buy, 'dragon_signal'] = 'BUY'
        df.loc[strong_buy, 'dragon_signal'] = 'STRONG_BUY'
        df.loc[sell, 'dragon_signal'] = 'SELL'

        return df
