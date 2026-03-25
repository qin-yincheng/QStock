"""
回测报告脚本 — 对指定股票运行历史回测
用法：python scripts/backtest_report.py --symbol 600519.SH
      python scripts/backtest_report.py --symbol 300750.SZ --mode fused --freq F60
"""

import sys
import os
import argparse
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.data_provider import get_raw_bars
from backtest.backtester import Backtester, print_report
from czsc import Freq

FREQ_MAP = {"F15": Freq.F15, "F30": Freq.F30, "F60": Freq.F60}
BARS_PER_DAY = {"F15": 16, "F30": 8, "F60": 4}


def main():
    parser = argparse.ArgumentParser(description="QStock 回测报告")
    parser.add_argument(
        "--symbol", required=True, help="股票代码，如 600519.SH 或 600519.SH#E"
    )
    parser.add_argument("--sdt", default=None, help="开始日期 YYYYMMDD（默认365天前）")
    parser.add_argument("--edt", default=None, help="结束日期 YYYYMMDD（默认今天）")
    parser.add_argument(
        "--mode",
        default="both",
        choices=["dragon", "fused", "both"],
        help="信号模式: dragon(纯双龙), fused(缠论+双龙融合), both(两者对比)",
    )
    parser.add_argument(
        "--cash", type=float, default=1000000, help="初始资金（默认100万）"
    )
    parser.add_argument(
        "--freq", default="F30", choices=["F15", "F30", "F60"],
        help="K线频率（默认 F30）",
    )
    args = parser.parse_args()

    symbol = args.symbol
    if "#" not in symbol:
        symbol = f"{symbol}#E"

    freq = FREQ_MAP[args.freq]
    bars_per_day = BARS_PER_DAY[args.freq]
    freq_label = str(freq)
    edt = args.edt or datetime.now().strftime("%Y%m%d")
    sdt = args.sdt or (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")

    stock_name = symbol.split("#")[0]

    print("=" * 60)
    print(f"  QStock 回测报告 — {stock_name}")
    print("=" * 60)
    print(f"  回测区间: {sdt} ~ {edt}")
    print(f"  频率级别: {freq_label}")
    print(f"  初始资金: {args.cash:,.0f}")
    print(f"  交易约束: T+1 | 手续费万三 | 印花税千一 | 滑点0.1%")
    print()

    bars = get_raw_bars(symbol, freq, sdt, edt)
    if not bars:
        print(f"  错误: 无法获取 {stock_name} 的数据")
        return
    print(f"  数据: {len(bars)} 根 {freq_label} K线")
    print(f"  时间: {bars[0].dt} ~ {bars[-1].dt}")
    print()

    bt = Backtester(initial_cash=args.cash, bars_per_day=bars_per_day)
    modes = ["dragon", "fused"] if args.mode == "both" else [args.mode]

    for mode in modes:
        mode_cn = "纯双龙战法" if mode == "dragon" else "缠论+双龙融合"
        print(f"--- {mode_cn} ({mode}) ---")
        result = bt.run(bars, mode=mode)
        print_report(result, stock_name, mode)
        print()

    print("  [!] 免责声明: 历史回测不代表未来收益, 仅供参考。")
    print("=" * 60)


if __name__ == "__main__":
    main()
