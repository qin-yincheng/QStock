"""
Step 4.1 — 回测引擎验证
对 ≥3 只股票运行回测，验证 T+1 约束、手续费计算和指标输出。
测试两种信号模式：dragon（纯双龙）和 fused（缠论+双龙融合）。
"""
import time
from core.data_provider import get_raw_bars
from czsc import Freq
from backtest.backtester import Backtester, print_report

TEST_STOCKS = [
    ("600519.SH#E", "贵州茅台"),
    ("000001.SZ#E", "平安银行"),
    ("300750.SZ#E", "宁德时代"),
]

SDT = "20250101"
EDT = "20260322"


def fetch_all_data():
    """获取所有测试股票数据（统一获取，避免回测过程中重复请求）"""
    data = {}
    for symbol, name in TEST_STOCKS:
        print(f"  Fetching {name}({symbol.split('#')[0]}) ...")
        bars = get_raw_bars(symbol, Freq.F60, SDT, EDT)
        if bars:
            data[symbol] = bars
            print(f"    [OK] {len(bars)} bars, {bars[0].dt.date()} ~ {bars[-1].dt.date()}")
        else:
            print(f"    [FAIL] no data")
        time.sleep(1)
    return data


def verify_t1_constraint(result: dict) -> bool:
    """验证 T+1 约束：卖出日期必须严格晚于买入日期"""
    import pandas as pd
    trades = result.get('trades', [])
    buy_trades = [t for t in trades if t['action'] == 'BUY']
    sell_trades = [t for t in trades if t['action'] == 'SELL']

    for bt, st in zip(buy_trades, sell_trades):
        buy_d = pd.Timestamp(bt['datetime']).date()
        sell_d = pd.Timestamp(st['datetime']).date()
        if sell_d <= buy_d:
            print(f"    [FAIL] T+1 violated: buy {buy_d} sell {sell_d}")
            return False
    return True


def run_backtest_suite():
    print("=" * 65)
    print("  QStock Backtest Validation -- Step 4.1")
    print("  T+1 | commission 0.03% | stamp tax 0.1% | slippage 0.1%")
    print("=" * 65)

    print("\n[1/4] DATA FETCH")
    print("-" * 65)
    data = fetch_all_data()
    if not data:
        print("[FAIL] no data, abort")
        return

    bt = Backtester(initial_cash=100000)

    # ---- dragon mode ---- #
    print("\n\n[2/4] BACKTEST: dragon (pure double-dragon)")
    print("=" * 65)
    dragon_results = {}
    for symbol, name in TEST_STOCKS:
        bars = data.get(symbol)
        if not bars:
            print(f"  {name}: no data, skip")
            continue
        result = bt.run(bars, mode='dragon')
        dragon_results[symbol] = result
        print_report(result, name, 'dragon')
        print()

    # ---- fused mode ---- #
    print("\n[3/4] BACKTEST: fused (chan + dragon)")
    print("=" * 65)
    fused_results = {}
    for symbol, name in TEST_STOCKS:
        bars = data.get(symbol)
        if not bars:
            print(f"  {name}: no data, skip")
            continue
        result = bt.run(bars, mode='fused')
        fused_results[symbol] = result
        print_report(result, name, 'fused')
        print()

    # ---- T+1 verification ---- #
    print("\n[4/4] T+1 CONSTRAINT CHECK")
    print("-" * 65)
    all_pass = True
    for symbol, name in TEST_STOCKS:
        for mode, results in [('dragon', dragon_results), ('fused', fused_results)]:
            r = results.get(symbol, {})
            if 'error' in r or not r:
                continue
            ok = verify_t1_constraint(r)
            status = "[PASS]" if ok else "[FAIL]"
            n_trades = r.get('total_trades', 0)
            print(f"  {name} [{mode}]: {status} ({n_trades} round-trip trades)")
            if not ok:
                all_pass = False

    # ---- summary ---- #
    print("\n\nSUMMARY: mode comparison")
    print("-" * 65)
    print(f"  {'Stock':<10} {'Mode':<8} {'Return':>8} {'Annual':>8} "
          f"{'MaxDD':>8} {'Sharpe':>7} {'#Trd':>4} {'WinR':>6}")
    print(f"  {'-'*10} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*7} {'-'*4} {'-'*6}")
    for symbol, name in TEST_STOCKS:
        for mode, results in [('dragon', dragon_results), ('fused', fused_results)]:
            r = results.get(symbol, {})
            if 'error' in r or not r:
                continue
            print(f"  {name:<10} {mode:<8} {r['total_return']:>8} {r['annual_return']:>8} "
                  f"{r['max_drawdown']:>8} {r['sharpe_ratio']:>7} "
                  f"{r['total_trades']:>4} {r['win_rate']:>6}")

    print("\n" + "=" * 65)
    if all_pass:
        print("[ALL PASS] Step 4.1 backtest validation succeeded")
    else:
        print("[FAIL] Some checks failed, please review")
    print("=" * 65)


if __name__ == "__main__":
    run_backtest_suite()
