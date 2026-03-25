"""
统一数据提供者
- 全部走 czsc ts_connector（方案A）
- 内置对 czsc freq 枚举 bug 的修复：
  czsc 的 get_raw_bars 会把 "60分钟" 替换成 "60min" 后再 Freq("60min")，
  但 Freq 枚举值是 "60分钟" 而非 "60min"，导致报错。
  本模块直接调用底层 pro_bar_minutes + format_kline，手动传入正确的 Freq 枚举。
- 注意：czsc 的 Freq 来自 rs_czsc（Rust 扩展），不可哈希，不能作为 dict key，
  因此使用 str(freq) 做字符串匹配。
"""

import os
import pandas as pd
import tushare as ts
import czsc
from czsc import RawBar, Freq
from typing import List

# 优先使用环境变量 TUSHARE_TOKEN，未设置时使用默认值
TS_TOKEN = os.environ.get("TUSHARE_TOKEN", "810cafd073d3dafa10a68b9fecfb61c291e65e63cfad68503d3b10cf")
ts.set_token(TS_TOKEN)
czsc.set_url_token(TS_TOKEN, "http://api.tushare.pro")

# Freq 来自 rs_czsc Rust 扩展，不可哈希，用 str(Freq) 的值做映射
_MINUTE_FREQ_MAP = {
    "1分钟": "1min",
    "5分钟": "5min",
    "15分钟": "15min",
    "30分钟": "30min",
    "60分钟": "60min",
}

_DAILY_FREQ_MAP = {
    "日线": "D",
    "周线": "W",
    "月线": "M",
}


def _is_minute_freq(freq: Freq) -> bool:
    return "分钟" in str(freq)


def _to_tushare_minute_freq(freq: Freq) -> str:
    freq_str = str(freq)
    ts_freq = _MINUTE_FREQ_MAP.get(freq_str)
    if ts_freq is None:
        raise ValueError(f"不支持的分钟频率: {freq_str}")
    return ts_freq


def _to_tushare_daily_freq(freq: Freq) -> str:
    freq_str = str(freq)
    ts_freq = _DAILY_FREQ_MAP.get(freq_str)
    if ts_freq is None:
        raise ValueError(f"不支持的日线频率: {freq_str}")
    return ts_freq


def get_raw_bars(
    symbol: str, freq: Freq, sdt: str, edt: str, fq: str = "前复权"
) -> List[RawBar]:
    """
    统一获取 K 线数据（RawBar 列表）

    Args:
        symbol: "600519.SH#E" 格式（ts_code#asset）
        freq: czsc.Freq 枚举，如 Freq.F60, Freq.D
        sdt: 开始日期 "20250901"
        edt: 结束日期 "20260319"
        fq: "前复权" 或 "后复权"

    Returns:
        List[RawBar]
    """
    if "#" not in symbol:
        asset = (
            "I"
            if symbol.startswith(("000", "399")) and symbol.endswith((".SH", ".SZ"))
            else "E"
        )
        symbol = f"{symbol}#{asset}"

    ts_code, asset = symbol.split("#")
    adj = "qfq" if fq == "前复权" else "hfq"

    if _is_minute_freq(freq):
        return _get_minute_bars(ts_code, asset, freq, sdt, edt, adj)
    else:
        return _get_daily_bars(ts_code, asset, freq, sdt, edt, adj)


def _get_minute_bars(
    ts_code: str, asset: str, freq: Freq, sdt: str, edt: str, adj: str
) -> List[RawBar]:
    """获取分钟级别 K 线，绕过 czsc 的两个 bug：
    1. freq 枚举转换 bug（"60min" vs "60分钟"）
    2. pro_bar_minutes 输出列名与 format_kline 不匹配
       （pro_bar_minutes 标准化为 symbol/dt，format_kline 期望 ts_code/trade_time）
    """
    from czsc.connectors.ts_connector import pro_bar_minutes

    ts_freq = _to_tushare_minute_freq(freq)
    kline = pro_bar_minutes(
        ts_code, sdt=sdt, edt=edt, freq=ts_freq, asset=asset, adj=adj
    )

    if kline is None or kline.empty:
        print(f"警告: {ts_code} {ts_freq} 未获取到数据")
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
    import tushare as ts
    from czsc.connectors.ts_connector import format_kline

    ts_freq = _to_tushare_daily_freq(freq)

    kline = ts.pro_bar(
        ts_code, start_date=sdt, end_date=edt, freq=ts_freq, asset=asset, adj=adj
    )

    if kline is None or kline.empty:
        print(f"警告: {ts_code} {ts_freq} 未获取到数据")
        return []

    bars = format_kline(kline, freq)
    return bars


def get_realtime_bars(
    symbol: str, freq: Freq = Freq.F60, history_months: int = 6
) -> List[RawBar]:
    """
    实战盘中用：获取历史数据
    Tushare 盘中数据有一定延迟但可用
    """
    from datetime import datetime, timedelta

    edt = datetime.now().strftime("%Y%m%d")
    sdt = (datetime.now() - timedelta(days=history_months * 30)).strftime("%Y%m%d")
    return get_raw_bars(symbol, freq, sdt, edt)
