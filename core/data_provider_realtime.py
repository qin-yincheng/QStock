"""
统一数据提供者 v2 - 支持实时数据
- 60 分钟 K 线：历史数据（Tushare）+ 当天实时（新浪财经聚合）
- 其他级别：使用原有逻辑
"""

import os
import pandas as pd
import tushare as ts
import czsc
from czsc import RawBar, Freq
from typing import List
from datetime import timedelta

# 优先使用环境变量 TUSHARE_TOKEN，未设置时使用默认值
TS_TOKEN = os.environ.get("TUSHARE_TOKEN", "810cafd073d3dafa10a68b9fecfb61c291e65e63cfad68503d3b10cf")
ts.set_token(TS_TOKEN)
czsc.set_url_token(TS_TOKEN, "http://api.tushare.pro")

_MINUTE_FREQ_MAP = {
    "1分钟": "1min",
    "5分钟": "5min",
    "15分钟": "15min",
    "30分钟": "30min",
    "60分钟": "60min",
}
_DAILY_FREQ_MAP = {"日线": "D", "周线": "W", "月线": "M"}


def get_raw_bars(
    symbol: str,
    freq: Freq,
    sdt: str = None,
    edt: str = None,
    fq: str = "前复权",
    realtime: bool = True,
) -> List[RawBar]:
    """
    统一获取 K 线数据（历史 + 实时聚合）

    Args:
        symbol: 股票代码，如 "600519.SH" 或 "600519.SH#E"
        freq: czsc.Freq 枚举，如 Freq.F60
        sdt: 开始日期（可选，默认 180 天前）
        edt: 结束日期（可选，默认今天）
        fq: "前复权" 或 "后复权"
        realtime: 是否获取实时数据（默认 True）

    Returns:
        List[RawBar]
    """
    _REALTIME_FREQS = {"15分钟", "30分钟", "60分钟"}
    if realtime and str(freq) in _REALTIME_FREQS:
        try:
            code = symbol.split("#")[0] if "#" in symbol else symbol
            if "." not in code:
                full_symbol = f"{code}.SH" if code.startswith("6") else f"{code}.SZ"
            else:
                full_symbol = code

            from core.realtime_kline_v3 import get_realtime_minute_bars
            realtime_bars = get_realtime_minute_bars(full_symbol, freq)

            if realtime_bars and len(realtime_bars) > 100:
                print(f"[OK] 使用实时聚合数据：{len(realtime_bars)} 根 {freq} K 线")
                return realtime_bars
        except Exception as e:
            print(f"[WARN] 实时数据获取失败：{str(e)[:60]}，回退到历史数据")

    # 回退到历史数据（原有逻辑）
    return _get_historical_bars(symbol, freq, sdt, edt, fq)


def _get_historical_bars(
    symbol: str, freq: Freq, sdt: str, edt: str, fq: str
) -> List[RawBar]:
    """获取历史 K 线数据（原有逻辑）"""
    if "#" not in symbol:
        asset = (
            "I"
            if symbol.startswith(("000", "399")) and symbol.endswith((".SH", ".SZ"))
            else "E"
        )
        symbol = f"{symbol}#{asset}"

    ts_code, asset = symbol.split("#")
    adj = "qfq" if fq == "前复权" else "hfq"

    # 设置默认日期
    if sdt is None:
        sdt = (pd.Timestamp("today") - timedelta(days=180)).strftime("%Y%m%d")
    if edt is None:
        edt = pd.Timestamp("today").strftime("%Y%m%d")

    if "分钟" in str(freq):
        return _get_minute_bars(ts_code, asset, freq, sdt, edt, adj)
    else:
        return _get_daily_bars(ts_code, asset, freq, sdt, edt, adj)


def _get_minute_bars(
    ts_code: str, asset: str, freq: Freq, sdt: str, edt: str, adj: str
) -> List[RawBar]:
    """获取分钟级别 K 线"""
    from czsc.connectors.ts_connector import pro_bar_minutes

    ts_freq = _MINUTE_FREQ_MAP.get(str(freq))
    if not ts_freq:
        raise ValueError(f"不支持的频率：{freq}")

    kline = pro_bar_minutes(
        ts_code, sdt=sdt, edt=edt, freq=ts_freq, asset=asset, adj=adj
    )

    if kline is None or kline.empty:
        print(f"警告：{ts_code} {ts_freq} 未获取到数据")
        return []

    kline = kline.sort_values("dt", ascending=True, ignore_index=True)
    bars = []
    for i, row in kline.iterrows():
        bar = RawBar(
            symbol=row["symbol"],
            dt=pd.to_datetime(row["dt"]),
            id=i,
            freq=freq,
            open=float(row["open"]),
            close=float(row["close"]),
            high=float(row["high"]),
            low=float(row["low"]),
            vol=int(row["vol"]) if row["vol"] > 0 else 0,
            amount=int(row["amount"]),
        )
        bars.append(bar)
    return bars


def _get_daily_bars(
    ts_code: str, asset: str, freq: Freq, sdt: str, edt: str, adj: str
) -> List[RawBar]:
    """获取日线及以上级别 K 线"""
    from czsc.connectors.ts_connector import format_kline

    ts_freq = _DAILY_FREQ_MAP.get(str(freq))
    if not ts_freq:
        raise ValueError(f"不支持的频率：{freq}")

    kline = ts.pro_bar(
        ts_code, start_date=sdt, end_date=edt, freq=ts_freq, asset=asset, adj=adj
    )

    if kline is None or kline.empty:
        print(f"警告：{ts_code} {ts_freq} 未获取到数据")
        return []

    return format_kline(kline, freq)
