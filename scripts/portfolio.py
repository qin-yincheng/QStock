"""
股票池管理脚本 — 自选股增删改查 + 批量诊断 + 批量回测

用法：
  python scripts/portfolio.py --action list                              # 查看自选池
  python scripts/portfolio.py --action add --symbol 300750.SZ --name 宁德时代
  python scripts/portfolio.py --action remove --symbol 000001.SZ
  python scripts/portfolio.py --action diagnose                          # 对自选池运行信号分析
  python scripts/portfolio.py --action backtest-all                      # 对自选池批量回测
  python scripts/portfolio.py --action diagnose --freq F60               # 使用 60 分钟频率
"""

import sys
import os
import json
import argparse
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from czsc import Freq

FREQ_MAP = {"F15": Freq.F15, "F30": Freq.F30, "F60": Freq.F60}
BARS_PER_DAY = {"F15": 16, "F30": 8, "F60": 4}

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
PORTFOLIO_PATH = os.path.join(DATA_DIR, "portfolio.json")
MAX_STOCKS = 20


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_portfolio() -> dict:
    if not os.path.exists(PORTFOLIO_PATH):
        return {"stocks": [], "updated_at": None}
    with open(PORTFOLIO_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_portfolio(data: dict):
    _ensure_data_dir()
    data["updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with open(PORTFOLIO_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def action_list(data: dict):
    stocks = data.get("stocks", [])
    if not stocks:
        print("  自选池为空。使用 --action add --symbol XXX 添加股票。")
        return

    print("=" * 70)
    print(f"  自选股票池（{len(stocks)} 只）")
    print(f"  最后更新: {data.get('updated_at', '未知')}")
    print("=" * 70)
    print()
    print(f"  {'#':>3}  {'代码':10s}  {'名称':8s}  {'加入日期':12s}  {'原因'}")
    print(f"  {'---':>3}  {'----------':10s}  {'--------':8s}  {'----------':12s}  {'----'}")
    for i, s in enumerate(stocks, 1):
        print(
            f"  {i:3d}  {s['symbol']:10s}  {s.get('name', ''):8s}  "
            f"{s.get('added_date', ''):12s}  {s.get('add_reason', '')[:40]}"
        )
    print()


def action_add(data: dict, symbol: str, name: str = "", reason: str = ""):
    stocks = data.get("stocks", [])

    existing = [s for s in stocks if s["symbol"] == symbol]
    if existing:
        print(f"  [WARN] {symbol} 已在自选池中，跳过。")
        return

    if len(stocks) >= MAX_STOCKS:
        print(f"  [WARN] 自选池已达上限 {MAX_STOCKS} 只，请先移除再添加。")
        return

    entry = {
        "symbol": symbol,
        "name": name or symbol,
        "added_date": datetime.now().strftime("%Y-%m-%d"),
        "add_reason": reason,
    }
    stocks.append(entry)
    data["stocks"] = stocks
    save_portfolio(data)
    print(f"  [OK] 已添加: {name or symbol} ({symbol})")
    print(f"  当前自选池: {len(stocks)} 只")


def action_remove(data: dict, symbol: str):
    stocks = data.get("stocks", [])
    before = len(stocks)
    stocks = [s for s in stocks if s["symbol"] != symbol]

    if len(stocks) == before:
        print(f"  [WARN] {symbol} 不在自选池中。")
        return

    data["stocks"] = stocks
    save_portfolio(data)
    print(f"  [OK] 已移除: {symbol}")
    print(f"  当前自选池: {len(stocks)} 只")


def action_diagnose(data: dict, freq_key: str = "F30"):
    from strategy.signal_engine import analyze_stock_realtime

    stocks = data.get("stocks", [])
    if not stocks:
        print("  自选池为空。")
        return

    freq = FREQ_MAP[freq_key]
    freq_label = str(freq)

    print("=" * 70)
    print(f"  自选池诊断（{len(stocks)} 只，{freq_label}）")
    print("=" * 70)
    print()

    signal_cn = {
        "STRONG_BUY": "强烈买入", "BUY": "买入", "BUY_EARLY": "早期买入",
        "BUY_WATCH": "观察", "WAIT_CONFIRM": "等待确认",
        "SELL_ALL": "卖出(全)", "SELL": "卖出", "REDUCE": "减仓", "HOLD": "持仓等待",
    }

    for i, s in enumerate(stocks, 1):
        sym = s["symbol"]
        name = s.get("name", sym)
        full_sym = sym if "#" in sym else f"{sym}#E"
        print(f"  [{i}/{len(stocks)}] {name} ({sym})...", end=" ")

        try:
            result = analyze_stock_realtime(full_sym, freq=freq)
            if "error" in result:
                print(f"错误: {result['error']}")
                continue

            sig = result.get("final_signal", "HOLD")
            sig_text = signal_cn.get(sig, sig)
            conf = result.get("confidence", 0)
            print(f"{sig_text} ({conf:.0%})")

            s["latest_signal"] = sig
            s["latest_check"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        except Exception as e:
            print(f"失败: {str(e)[:50]}")

    save_portfolio(data)
    print()
    print("  诊断完成，信号已更新到 portfolio.json")
    print("=" * 70)


def action_backtest_all(data: dict, freq_key: str = "F30"):
    from core.data_provider import get_raw_bars
    from backtest.backtester import Backtester, print_report

    stocks = data.get("stocks", [])
    if not stocks:
        print("  自选池为空。")
        return

    freq = FREQ_MAP[freq_key]
    bpd = BARS_PER_DAY[freq_key]
    freq_label = str(freq)

    edt = datetime.now().strftime("%Y%m%d")
    sdt = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")

    print("=" * 70)
    print(f"  自选池批量回测（{len(stocks)} 只，{freq_label}）")
    print(f"  回测区间: {sdt} ~ {edt}")
    print("=" * 70)
    print()

    bt = Backtester(bars_per_day=bpd)

    for i, s in enumerate(stocks, 1):
        sym = s["symbol"]
        name = s.get("name", sym)
        full_sym = sym if "#" in sym else f"{sym}#E"
        print(f"  [{i}/{len(stocks)}] {name} ({sym})")

        try:
            bars = get_raw_bars(full_sym, freq, sdt, edt)
            if not bars or len(bars) < 30:
                print(f"    数据不足 ({len(bars) if bars else 0} 根)")
                continue
            result = bt.run(bars, mode="fused")
            print_report(result, name, "fused")
        except Exception as e:
            print(f"    回测失败: {str(e)[:60]}")
        print()

    print("  [!] 免责声明: 历史回测不代表未来收益, 仅供参考。")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="QStock 自选股票池管理")
    parser.add_argument(
        "--action", required=True,
        choices=["list", "add", "remove", "diagnose", "backtest-all"],
        help="操作类型",
    )
    parser.add_argument("--symbol", default=None, help="股票代码（add/remove 时必填）")
    parser.add_argument("--name", default="", help="股票名称（add 时可选）")
    parser.add_argument("--reason", default="", help="添加原因（add 时可选）")
    parser.add_argument(
        "--freq", default="F30", choices=["F15", "F30", "F60"],
        help="K线频率（默认 F30）",
    )
    args = parser.parse_args()

    data = load_portfolio()

    if args.action == "list":
        action_list(data)
    elif args.action == "add":
        if not args.symbol:
            print("  错误: --action add 需要 --symbol 参数")
            return
        action_add(data, args.symbol, args.name, args.reason)
    elif args.action == "remove":
        if not args.symbol:
            print("  错误: --action remove 需要 --symbol 参数")
            return
        action_remove(data, args.symbol)
    elif args.action == "diagnose":
        action_diagnose(data, args.freq)
    elif args.action == "backtest-all":
        action_backtest_all(data, args.freq)


if __name__ == "__main__":
    main()
