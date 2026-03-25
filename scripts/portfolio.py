"""
股票池管理脚本 — 自选股增删改查 + 持仓管理 + 批量诊断 + 批量回测

用法：
  python scripts/portfolio.py --action list                              # 查看自选池
  python scripts/portfolio.py --action add --symbol 300750.SZ --name 宁德时代
  python scripts/portfolio.py --action remove --symbol 000001.SZ
  python scripts/portfolio.py --action diagnose                          # 对自选池运行信号分析
  python scripts/portfolio.py --action backtest-all                      # 对自选池批量回测
  python scripts/portfolio.py --action diagnose --freq F60               # 使用 60 分钟频率
  python scripts/portfolio.py --action update-holding --symbol 300750.SZ --buy-price 195.5 --shares 500
  python scripts/portfolio.py --action clear-holding --symbol 300750.SZ --sell-price 210 --shares 200  # 部分卖出
  python scripts/portfolio.py --action clear-holding --symbol 300750.SZ --sell-price 210             # 全部清仓
  python scripts/portfolio.py --action holdings                          # 查看所有持仓
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

    held = [s for s in stocks if s.get("holding")]
    print("=" * 70)
    print(f"  自选股票池（{len(stocks)} 只，持仓 {len(held)} 只）")
    print(f"  最后更新: {data.get('updated_at', '未知')}")
    print("=" * 70)
    print()
    print(f"  {'#':>3}  {'代码':10s}  {'名称':8s}  {'持仓':6s}  {'买入价':8s}  {'数量':6s}  {'加入日期':12s}")
    print(f"  {'---':>3}  {'----------':10s}  {'--------':8s}  {'------':6s}  {'--------':8s}  {'------':6s}  {'----------':12s}")
    for i, s in enumerate(stocks, 1):
        hold_flag = "✅" if s.get("holding") else "—"
        bp = f"{s['buy_price']:.2f}" if s.get("buy_price") else "—"
        shares = str(s.get("shares", "")) if s.get("shares") else "—"
        print(
            f"  {i:3d}  {s['symbol']:10s}  {s.get('name', ''):8s}  "
            f"{hold_flag:6s}  {bp:8s}  {shares:6s}  {s.get('added_date', ''):12s}"
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


def action_update_holding(
    data: dict, symbol: str, buy_price: float,
    shares: int = 0, note: str = "",
):
    """更新持仓信息（买入记录）"""
    stocks = data.get("stocks", [])
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    found = False
    for s in stocks:
        if s["symbol"] == symbol:
            s["holding"] = True
            s["buy_price"] = buy_price
            s["buy_date"] = now_str
            if shares > 0:
                s["shares"] = shares
            if note:
                s["holding_note"] = note
            found = True
            break

    if not found:
        entry = {
            "symbol": symbol,
            "name": symbol,
            "added_date": datetime.now().strftime("%Y-%m-%d"),
            "add_reason": "通过持仓更新自动添加",
            "holding": True,
            "buy_price": buy_price,
            "buy_date": now_str,
            "shares": shares if shares > 0 else 0,
        }
        if note:
            entry["holding_note"] = note
        stocks.append(entry)
        data["stocks"] = stocks

    save_portfolio(data)
    name = next((s.get("name", symbol) for s in stocks if s["symbol"] == symbol), symbol)
    print(f"  [OK] 已更新持仓: {name} ({symbol})")
    print(f"       买入价={buy_price}  数量={shares if shares > 0 else '未指定'}")


def action_clear_holding(
    data: dict, symbol: str, sell_price: float = 0, sell_shares: int = 0,
):
    """清除或部分卖出持仓

    sell_shares=0 或 >= 持仓总量时全部清仓，否则部分卖出。
    """
    stocks = data.get("stocks", [])
    found = False
    for s in stocks:
        if s["symbol"] == symbol:
            name = s.get("name", symbol)
            buy_price = s.get("buy_price", 0)
            total_shares = s.get("shares", 0)
            buy_date = s.get("buy_date", "未知")
            sell_time = datetime.now().strftime("%Y-%m-%d %H:%M")

            is_partial = (
                sell_shares > 0
                and total_shares > 0
                and sell_shares < total_shares
            )
            actual_sell = sell_shares if is_partial else total_shares

            if sell_price > 0 and buy_price > 0:
                pnl_pct = (sell_price - buy_price) / buy_price * 100
                pnl_amount = (sell_price - buy_price) * actual_sell if actual_sell > 0 else 0
                print(f"  本次交易: 买入{buy_price}({buy_date}) → 卖出{sell_price}({sell_time})")
                print(f"  卖出数量: {actual_sell if actual_sell > 0 else '全部'}")
                print(f"  盈亏比例: {pnl_pct:+.1f}%")
                if actual_sell > 0:
                    print(f"  盈亏金额: {pnl_amount:+,.0f} 元")

            if is_partial:
                remaining = total_shares - sell_shares
                s["shares"] = remaining
                print(f"  [OK] 部分卖出 {name} ({symbol}): 卖出 {sell_shares} 股, 剩余 {remaining} 股")
                print(f"       买入价 {buy_price} 不变, 继续持仓")
            else:
                s["holding"] = False
                s.pop("buy_price", None)
                s.pop("buy_date", None)
                s.pop("shares", None)
                s.pop("holding_note", None)
                print(f"  [OK] 已清仓: {name} ({symbol})")

            found = True
            break

    if not found:
        print(f"  [WARN] {symbol} 不在自选池中或无持仓记录。")
        return

    save_portfolio(data)


def action_holdings(data: dict):
    """查看所有持仓"""
    stocks = data.get("stocks", [])
    held = [s for s in stocks if s.get("holding") and s.get("buy_price")]

    if not held:
        print("  当前无持仓记录。")
        print("  使用 --action update-holding --symbol XXX --buy-price YYY 记录买入。")
        return

    print("=" * 70)
    print(f"  当前持仓（{len(held)} 只）")
    print("=" * 70)
    print()
    print(f"  {'#':>3}  {'代码':10s}  {'名称':8s}  {'买入价':8s}  {'数量':6s}  {'买入日期':12s}  {'备注'}")
    print(f"  {'---':>3}  {'----------':10s}  {'--------':8s}  {'--------':8s}  {'------':6s}  {'----------':12s}  {'----'}")
    for i, s in enumerate(held, 1):
        bp = f"{s['buy_price']:.2f}" if s.get("buy_price") else "—"
        shares = str(s.get("shares", "")) if s.get("shares") else "—"
        note = s.get("holding_note", "")[:30]
        print(
            f"  {i:3d}  {s['symbol']:10s}  {s.get('name', ''):8s}  "
            f"{bp:8s}  {shares:6s}  {s.get('buy_date', ''):12s}  {note}"
        )
    print()


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
    parser = argparse.ArgumentParser(description="QStock 自选股票池管理 + 持仓管理")
    parser.add_argument(
        "--action", required=True,
        choices=[
            "list", "add", "remove", "diagnose", "backtest-all",
            "update-holding", "clear-holding", "holdings",
        ],
        help="操作类型",
    )
    parser.add_argument("--symbol", default=None, help="股票代码（add/remove/holding 时必填）")
    parser.add_argument("--name", default="", help="股票名称（add 时可选）")
    parser.add_argument("--reason", default="", help="添加原因（add 时可选）")
    parser.add_argument("--buy-price", type=float, default=0, help="买入价格（update-holding 时必填）")
    parser.add_argument("--sell-price", type=float, default=0, help="卖出价格（clear-holding 时可选，用于计算盈亏）")
    parser.add_argument("--shares", type=int, default=0, help="股数（update-holding: 买入数量; clear-holding: 卖出数量, 0=全部清仓）")
    parser.add_argument("--note", default="", help="持仓备注（update-holding 时可选）")
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
    elif args.action == "update-holding":
        if not args.symbol or args.buy_price <= 0:
            print("  错误: --action update-holding 需要 --symbol 和 --buy-price 参数")
            return
        action_update_holding(data, args.symbol, args.buy_price, args.shares, args.note)
    elif args.action == "clear-holding":
        if not args.symbol:
            print("  错误: --action clear-holding 需要 --symbol 参数")
            return
        action_clear_holding(data, args.symbol, args.sell_price, args.shares)
    elif args.action == "holdings":
        action_holdings(data)
    elif args.action == "diagnose":
        action_diagnose(data, args.freq)
    elif args.action == "backtest-all":
        action_backtest_all(data, args.freq)


if __name__ == "__main__":
    main()
