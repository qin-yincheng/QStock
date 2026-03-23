"""
市场扫描脚本 — 对股票池批量运行策略分析，筛选有信号的标的
用法：python scripts/scan.py
      python scripts/scan.py --symbols 600519.SH,000858.SZ,300750.SZ
"""
import sys
import os
import argparse
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy.signal_engine import analyze_stock

DEFAULT_POOL = {
    "600519.SH#E": "贵州茅台",
    "000858.SZ#E": "五粮液",
    "300750.SZ#E": "宁德时代",
    "601318.SH#E": "中国平安",
    "600036.SH#E": "招商银行",
    "002594.SZ#E": "比亚迪",
    "300059.SZ#E": "东方财富",
    "600900.SH#E": "长江电力",
}

SIGNAL_CN = {
    'STRONG_BUY': '[!!!] 强烈买入',
    'BUY': '[>>] 买入',
    'BUY_WATCH': '[?] 观察',
    'WAIT_CONFIRM': '[..] 等待确认',
    'SELL': '[<<] 卖出',
    'HOLD': '[--] 持仓等待',
}


def scan(pool: dict = None, sdt: str = None, edt: str = None) -> list:
    pool = pool or DEFAULT_POOL
    edt = edt or datetime.now().strftime("%Y%m%d")
    sdt = sdt or (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")

    print("=" * 60)
    print("  QStock 市场扫描报告")
    print(f"  扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  数据范围: {sdt} ~ {edt}")
    print(f"  股票池: {len(pool)} 只")
    print("=" * 60)
    print()

    results = []
    for symbol, name in pool.items():
        try:
            r = analyze_stock(symbol, sdt, edt)
            r['name'] = name
            results.append(r)
            sig = r.get('final_signal', 'ERROR')
            confidence = r.get('confidence', 0)
            sig_cn = SIGNAL_CN.get(sig, sig)
            print(f"  {name:8s} ({symbol.split('#')[0]}): "
                  f"{sig_cn} ({confidence:.0%}) - {r.get('reason', '')}")
        except Exception as e:
            print(f"  {name:8s} ({symbol.split('#')[0]}): 分析失败 - {e}")

    actionable = [r for r in results
                  if r.get('final_signal') not in ('HOLD', 'ERROR', None)]

    print()
    print("-" * 60)
    if actionable:
        print(f"  有信号标的: {len(actionable)}/{len(pool)} 只")
        print()
        for r in actionable:
            sig = r['final_signal']
            sig_cn = SIGNAL_CN.get(sig, sig)
            print(f"  {sig_cn}  {r['name']} ({r['symbol'].split('#')[0]})")
            print(f"          价格: {r.get('close', '')}")
            print(f"          依据: {r.get('reason', '')}")
            print(f"          缠论: {r.get('chan_signal', '')} | "
                  f"双龙: {r.get('dragon_signal', '')}")
            print()
    else:
        print("  当前无交易信号，市场观望。")

    print()
    print("  [!] 免责声明: 本扫描仅供参考, 不构成投资建议。")
    print("=" * 60)
    return results


def main():
    parser = argparse.ArgumentParser(description="QStock 市场扫描")
    parser.add_argument("--symbols", default=None,
                        help="股票代码列表（逗号分隔），如 600519.SH,000858.SZ")
    parser.add_argument("--sdt", default=None,
                        help="开始日期 YYYYMMDD（默认180天前）")
    parser.add_argument("--edt", default=None,
                        help="结束日期 YYYYMMDD（默认今天）")
    args = parser.parse_args()

    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",")]
        pool = {}
        for s in symbols:
            sym = s if "#" in s else f"{s}#E"
            pool[sym] = sym.split("#")[0]
    else:
        pool = DEFAULT_POOL

    scan(pool, args.sdt, args.edt)


if __name__ == "__main__":
    main()
