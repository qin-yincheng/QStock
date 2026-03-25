"""
实时 K 线数据获取方案 v3 - 最终版
成功获取新浪财经实时分时数据，并聚合成 60 分钟 K 线
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import requests
from datetime import timedelta
from typing import List, Optional
from czsc import RawBar, Freq


def get_intraday_from_sina(symbol: str, scale: str = "5") -> Optional[pd.DataFrame]:
    """
    从新浪财经获取当天分时数据（5 分钟/15 分钟/30 分钟/60 分钟）

    接口：https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData

    Args:
        symbol: 股票代码（如 '600519.SH'）
        scale: K 线周期 ('5'/'15'/'30'/'60')

    Returns:
        DataFrame 或 None
    """
    # 转换代码格式
    if symbol.startswith("6"):
        sina_code = f"sh{symbol.replace('.SH', '')}"
    else:
        sina_code = f"sz{symbol.replace('.SZ', '')}"

    try:
        url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        params = {"symbol": sina_code, "scale": scale, "datalen": "100"}  # 最多 100 根

        response = requests.get(url, params=params, timeout=10)

        if response.status_code == 200:
            data = response.json()

            if data and len(data) > 0:
                # 数据结构：[日期，开盘，最高，最低，收盘，成交量，成交额（空）]
                df = pd.DataFrame(data)
                df = df[["day", "open", "high", "low", "close", "volume"]].copy()

                # 解析日期：'2026-03-23 10:30'
                df["datetime"] = pd.to_datetime(df["day"])

                # 数值转换
                for col in ["open", "high", "low", "close", "volume"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

                df = df.sort_values("datetime").reset_index(drop=True)

                print(f"[OK] sina: {symbol} 获取 {len(df)} 根 {scale}分钟 K 线")
                print(
                    f"   时间范围：{df['datetime'].iloc[0]} ~ {df['datetime'].iloc[-1]}"
                )
                print(f"   最新价格：{df['close'].iloc[-1]:.2f}")

                return df
            else:
                print(f"[WARN] sina: {symbol} 无数据")
        else:
            print(f"[ERR] sina: HTTP {response.status_code}")

    except Exception as e:
        print(f"[ERR] sina: {str(e)[:60]}")

    return None


def aggregate_5min_to_60min(df_5min: pd.DataFrame, symbol: str) -> List[RawBar]:
    """
    将 5 分钟 K 线聚合成 60 分钟 K 线

    A 股交易时段：
    - 上午：9:30-11:30（2 根 60 分钟 K 线：10:30, 11:30）
    - 下午：13:00-15:00（2 根 60 分钟 K 线：14:00, 15:00）
    """
    bars = []

    if df_5min is None or len(df_5min) == 0:
        return bars

    # 60 分钟 K 线的 4 个时间点
    time_periods = [
        ("09:30", "10:30"),  # 第 1 根（9:30-10:30，12 根 5 分钟 K 线）
        ("10:30", "11:30"),  # 第 2 根（10:30-11:30，12 根 5 分钟 K 线）
        ("13:00", "14:00"),  # 第 3 根（13:00-14:00，12 根 5 分钟 K 线）
        ("14:00", "15:00"),  # 第 4 根（14:00-15:00，12 根 5 分钟 K 线）
    ]

    today = pd.Timestamp("today").normalize()

    for i, (start_t, end_t) in enumerate(time_periods):
        start_dt = pd.Timestamp(f"{today.date()} {start_t}")
        end_dt = pd.Timestamp(f"{today.date()} {end_t}")

        # 筛选该时段的 5 分钟 K 线
        mask = (df_5min["datetime"] > start_dt) & (df_5min["datetime"] <= end_dt)
        period_df = df_5min[mask]

        if len(period_df) >= 10:  # 至少 10 根 5 分钟 K 线（允许数据不完整）
            # 计算 OHLC
            open_price = period_df.iloc[0]["open"]
            close_price = period_df.iloc[-1]["close"]
            high_price = period_df["high"].max()
            low_price = period_df["low"].min()
            volume = period_df["volume"].sum()

            bar = RawBar(
                symbol=symbol,
                dt=end_dt,
                id=i,
                freq=Freq.F60,
                open=float(open_price),
                close=float(close_price),
                high=float(high_price),
                low=float(low_price),
                vol=int(volume),
                amount=0,
            )
            bars.append(bar)

            print(
                f"   合成 60 分钟 K 线 #{i+1}: {start_t}-{end_t}, 收盘={close_price:.2f}"
            )

    return bars


def get_realtime_60min_bars(symbol: str) -> List[RawBar]:
    """
    获取实时 60 分钟 K 线（历史 + 当天实时）

    策略：
    1. 历史数据：使用 Tushare（通过 data_provider）
    2. 当天数据：使用新浪财经 5 分钟 K 线聚合

    Returns:
        List[RawBar]
    """
    print(f"\n[RT] 获取 {symbol} 实时 60 分钟 K 线...")

    # 1. 获取历史数据（Tushare）
    from core.data_provider import get_raw_bars

    end_date = (pd.Timestamp("today") - timedelta(days=1)).strftime("%Y%m%d")
    start_date = (pd.Timestamp("today") - timedelta(days=180)).strftime("%Y%m%d")

    print(f"   获取历史数据：{start_date} ~ {end_date}")
    hist_bars = get_raw_bars(f"{symbol}#E", Freq.F60, start_date, end_date)
    print(f"   历史数据：{len(hist_bars)} 根")

    # 2. 获取当天 5 分钟 K 线
    today = pd.Timestamp("today")
    now = pd.Timestamp.now()

    # 检查是否在交易时段
    is_trading_time = (
        (now.hour == 9 and now.minute >= 30)
        or (now.hour >= 10 and now.hour < 12)
        or (now.hour >= 13 and now.hour < 15)
    )

    if is_trading_time:
        print(
            f"   当前在交易时段 ({now.hour:02d}:{now.minute:02d})，获取当天实时数据..."
        )

        # 获取 5 分钟 K 线
        df_5min = get_intraday_from_sina(symbol, scale="5")

        if df_5min is not None and len(df_5min) > 0:
            # 聚合成 60 分钟 K 线
            today_bars = aggregate_5min_to_60min(df_5min, symbol)

            if today_bars:
                print(f"   [OK] 当天数据：{len(today_bars)} 根 60 分钟 K 线（实时）")

                # 合并历史 + 当天，重新编号 id（RawBar 不可变，需创建新对象）
                merged = hist_bars + today_bars
                all_bars = [
                    RawBar(
                        symbol=b.symbol, dt=b.dt, id=idx, freq=b.freq,
                        open=b.open, close=b.close, high=b.high, low=b.low,
                        vol=b.vol, amount=b.amount,
                    )
                    for idx, b in enumerate(merged)
                ]

                print(f"   [OK] 总计：{len(all_bars)} 根 60 分钟 K 线")
                return all_bars
    else:
        print(f"   当前不在交易时段，使用历史数据")

    # 返回历史数据
    print(f"   [WARN] 返回历史数据（{len(hist_bars)} 根，延迟到昨日）")
    return hist_bars


def analyze_realtime(symbol: str):
    """
    实时分析股票（使用实时 60 分钟 K 线）
    """
    from czsc import CZSC

    print("=" * 70)
    print(f"  QStock 实时分析报告 — {symbol}")
    print(f"  分析时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # 获取实时 K 线
    bars = get_realtime_60min_bars(symbol)

    if not bars or len(bars) < 30:
        print(f"[ERR] 数据不足（{len(bars) if bars else 0}根），需要至少 30 根 K 线")
        return

    # 创建 CZSC 对象
    c = CZSC(bars)

    # 最新数据
    latest_price = bars[-1].close
    latest_time = bars[-1].dt

    print(f"\n【数据概况】")
    print(f"  K 线数量：{len(bars)} 根（60 分钟级别）")
    print(f"  最新时间：{latest_time}")
    print(f"  最新价格：{latest_price:.2f}")

    # 缠论分析
    print(f"\n【缠论结构】")
    print(f"  分型数量：{len(c.fx_list)}")
    print(f"  笔数量：{len(c.bi_list)}")

    if len(c.bi_list) > 0:
        last_bi = c.bi_list[-1]
        direction = "上升 ↑" if last_bi.direction.value == "向上" else "下降 ↓"
        print(f"  最后笔方向：{direction}")

    # 趋势判断
    trend = "未知"
    if len(c.bi_list) >= 3:
        last3 = c.bi_list[-3:]
        if last3[-1].high > last3[0].high and last3[-1].low > last3[0].low:
            trend = "上升"
        elif last3[-1].high < last3[0].high and last3[-1].low < last3[0].low:
            trend = "下降"
        else:
            trend = "震荡"
        print(f"  趋势判断：{trend}")

    print("\n" + "=" * 70)

    return {
        "symbol": symbol,
        "datetime": latest_time,
        "close": latest_price,
        "bar_count": len(bars),
        "bi_count": len(c.bi_list),
        "trend": trend,
    }


FREQ_SCALE_MAP = {
    "15分钟": "15",
    "30分钟": "30",
    "60分钟": "60",
}

FREQ_BARS_PER_DAY = {
    "15分钟": 16,
    "30分钟": 8,
    "60分钟": 4,
}


def get_realtime_minute_bars(symbol: str, freq: Freq = Freq.F30) -> List[RawBar]:
    """
    通用实时分钟 K 线获取（历史 Tushare + 当天新浪财经）

    支持 F15 / F30 / F60，新浪接口直接提供对应级别数据，无需从 5 分钟聚合。

    Args:
        symbol: 股票代码（如 '600519.SH'）
        freq: Freq.F15 / Freq.F30 / Freq.F60

    Returns:
        List[RawBar]
    """
    freq_str = str(freq)
    scale = FREQ_SCALE_MAP.get(freq_str)
    if scale is None:
        raise ValueError(f"不支持的实时频率: {freq_str}，仅支持 F15/F30/F60")

    print(f"\n[RT] 获取 {symbol} 实时 {freq_str} K 线...")

    from core.data_provider import get_raw_bars as _hist_get_bars

    end_date = (pd.Timestamp("today") - timedelta(days=1)).strftime("%Y%m%d")
    start_date = (pd.Timestamp("today") - timedelta(days=180)).strftime("%Y%m%d")

    print(f"   获取历史数据：{start_date} ~ {end_date}")
    hist_bars = _hist_get_bars(f"{symbol}#E", freq, start_date, end_date)
    print(f"   历史数据：{len(hist_bars)} 根")

    now = pd.Timestamp.now()
    is_trading_time = (
        (now.hour == 9 and now.minute >= 30)
        or (now.hour >= 10 and now.hour < 12)
        or (now.hour >= 13 and now.hour < 15)
    )

    if not is_trading_time:
        print(f"   当前不在交易时段，返回历史数据")
        return hist_bars

    print(f"   当前在交易时段，获取新浪实时 {scale} 分钟 K 线...")
    df_sina = get_intraday_from_sina(symbol, scale=scale)

    if df_sina is None or len(df_sina) == 0:
        print(f"   [WARN] 新浪数据为空，返回历史数据")
        return hist_bars

    today_date = pd.Timestamp("today").normalize()
    today_mask = df_sina["datetime"].dt.normalize() == today_date
    today_df = df_sina[today_mask]

    if len(today_df) == 0:
        print(f"   [WARN] 今日无数据，返回历史数据")
        return hist_bars

    today_bars = []
    for i, row in today_df.iterrows():
        bar = RawBar(
            symbol=symbol,
            dt=row["datetime"],
            id=0,
            freq=freq,
            open=float(row["open"]),
            close=float(row["close"]),
            high=float(row["high"]),
            low=float(row["low"]),
            vol=int(row["volume"]),
            amount=0,
        )
        today_bars.append(bar)

    print(f"   [OK] 当天数据：{len(today_bars)} 根 {freq_str} K 线（实时）")

    merged = hist_bars + today_bars
    all_bars = [
        RawBar(
            symbol=b.symbol, dt=b.dt, id=idx, freq=b.freq,
            open=b.open, close=b.close, high=b.high, low=b.low,
            vol=b.vol, amount=b.amount,
        )
        for idx, b in enumerate(merged)
    ]

    print(f"   [OK] 总计：{len(all_bars)} 根 {freq_str} K 线")
    return all_bars


if __name__ == "__main__":
    print("=" * 70)
    print("实时 K 线获取测试 v3")
    print("=" * 70)

    result = analyze_realtime("600519.SH")

    print("\n" + "=" * 70)
    print("测试完成")
    print("=" * 70)
