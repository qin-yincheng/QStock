"""
市场扫描脚本 v4 — 选股 + 信号扫描统一入口

集成 StockScreenerV3，实现：
  1. ADX 趋势强度筛选（>= 20）
  2. SignalEngine v3 融合信号分析
  3. 波动率适配度评估
  4. 综合评分 → 推荐 / 关注 / 淘汰
  5. 支持实时数据（盘中自动获取当天 K 线）
  6. 支持自选池模式（--portfolio）
  7. 支持多频率（--freq F15/F30/F60，默认 F30）

用法：
  python scripts/scan.py                              # 默认 50 只股票池, 30分钟
  python scripts/scan.py --portfolio                  # 扫描自选池
  python scripts/scan.py --freq F60                   # 使用 60 分钟频率
  python scripts/scan.py --symbols 600519.SH,300750.SZ  # 指定股票
  python scripts/scan.py --adx-threshold 25           # 自定义 ADX 门槛
  python scripts/scan.py --no-realtime                # 关闭实时数据
  python scripts/scan.py --output docs/scan_report.md # 输出报告
"""

import sys
import os
import json
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from czsc import Freq
from tools.stock_screener_v3 import StockScreenerV3, DEFAULT_POOL, POSITION_MAP

FREQ_MAP = {"F15": Freq.F15, "F30": Freq.F30, "F60": Freq.F60}
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORTFOLIO_PATH = os.path.join(PROJECT_ROOT, "data", "portfolio.json")

GRADE_LABEL = {
    "推荐": ">>",
    "关注": "--",
    "淘汰": "  ",
}

SIGNAL_CN = {
    "STRONG_BUY": "强烈买入",
    "BUY": "买入",
    "BUY_EARLY": "早期买入",
    "BUY_WATCH": "观察",
    "WAIT_CONFIRM": "等待确认",
    "SELL_ALL": "卖出(全)",
    "SELL": "卖出",
    "REDUCE": "减仓",
    "HOLD": "持仓等待",
}

BUY_SIGNALS = {"STRONG_BUY", "BUY", "BUY_EARLY", "BUY_WATCH", "WAIT_CONFIRM"}
SELL_SIGNALS = {"SELL_ALL", "SELL", "REDUCE"}


def _load_holdings() -> dict:
    """从 portfolio.json 加载持仓信息，返回 {symbol: holding_info} 映射"""
    if not os.path.exists(PORTFOLIO_PATH):
        return {}
    try:
        with open(PORTFOLIO_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        holdings = {}
        for item in data.get("stocks", []):
            if item.get("holding") and item.get("buy_price"):
                holdings[item["symbol"]] = item
        return holdings
    except Exception:
        return {}


def _format_detail_block(r: dict, holdings: dict) -> list:
    """为单只股票生成详细操作参数文本块"""
    lines = []
    signal = r["signal"]
    sym = r["symbol"]
    price = r.get("latest_price", 0)
    op = r.get("op_params", {})

    # 缠论结构详情
    chan_detail = r.get("chan_detail", "")
    if chan_detail:
        lines.append(f"     缠论结构: {chan_detail}")

    # 双龙状态详情
    dragon_detail = r.get("dragon_detail", "")
    if dragon_detail:
        lines.append(f"     双龙状态: {dragon_detail}")
    else:
        ema5 = r.get("ema5")
        ema10 = r.get("ema10")
        dif = r.get("dif")
        dea = r.get("dea")
        if ema5 is not None and ema10 is not None:
            ema_state = "多头" if ema5 > ema10 else "空头"
            macd_state = "多头" if (dif and dea and dif > dea) else "空头"
            lines.append(
                f"     双龙状态: EMA5={ema5} {'>' if ema5 > ema10 else '<'} "
                f"EMA10={ema10} ({ema_state}), "
                f"DIF={'>' if dif and dea and dif > dea else '<'}DEA ({macd_state})"
            )

    # 操作参数（v8 策略）
    if op and op.get("atr14"):
        if signal in BUY_SIGNALS:
            lines.append(f"     ┌─── 操作参数（v8 策略）───┐")
            lines.append(f"     │ 当前价: {price:.2f}")
            lines.append(f"     │ 建议仓位: {r['position_size']:.0%}")
            lines.append(f"     │ ATR(14) = {op['atr14']}")
            lines.append(
                f"     │ 止损价: {op['stop_loss_price']} "
                f"({op['stop_loss_pct']}%)"
            )
            lines.append(
                f"     │ 止盈激活: {op['tp_activate_price']} "
                f"(+{op['tp_activate_pct']}%)"
            )
            lines.append(f"     │ 止盈回撤: {op['tp_trail_note']}")
            lines.append(
                f"     │ 时间止损: {op['time_stop_bars']}根K线"
                f"(约{op['time_stop_days']}天)"
            )
            lines.append(f"     └────────────────────────┘")
        elif signal in SELL_SIGNALS:
            lines.append(f"     ┌─── 卖出参考 ───┐")
            lines.append(f"     │ 当前价: {price:.2f}")
            lines.append(f"     │ ATR(14) = {op['atr14']}")
            if signal == "REDUCE":
                lines.append(f"     │ 建议: 减仓50%")
            else:
                lines.append(f"     │ 建议: 清仓")
            lines.append(f"     └────────────────┘")

    # 持仓状态差异化建议
    holding = holdings.get(sym, {})
    if holding and holding.get("buy_price"):
        buy_price = holding["buy_price"]
        shares = holding.get("shares", 0)
        pnl = (price - buy_price) / buy_price * 100 if buy_price > 0 else 0
        pnl_label = f"+{pnl:.1f}%" if pnl >= 0 else f"{pnl:.1f}%"
        lines.append(f"     [已持仓] 买入价={buy_price} 持股={shares} 浮盈={pnl_label}")
        if signal in SELL_SIGNALS:
            if pnl < -5:
                lines.append(f"     → 已错过最佳卖点，当前缠论确认卖点是最后退出机会")
            else:
                lines.append(f"     → 建议执行卖出信号，锁定{'利润' if pnl > 0 else '减少亏损'}")
        elif signal in BUY_SIGNALS:
            if pnl < 0:
                lines.append(f"     → 已亏损中，不建议加仓")
            else:
                lines.append(f"     → 可考虑加仓（如信号更强）")
        else:
            if op and op.get("stop_loss_price"):
                lines.append(f"     → 继续持有，止损设在 {op['stop_loss_price']}")
    else:
        if signal in BUY_SIGNALS and op and op.get("stop_loss_price"):
            lines.append(
                f"     [未持仓] 可在 {price:.2f} 附近建仓 "
                f"{r['position_size']:.0%}，严格止损 {op['stop_loss_price']}"
            )
        elif signal in SELL_SIGNALS:
            lines.append(f"     [未持仓] 不操作，等待后续回调企稳后的买入机会")
        else:
            lines.append(f"     [未持仓] 无明确信号，继续观望")

    return lines


def scan(
    screener: StockScreenerV3,
    pool: list = None,
    output_path: str = None,
) -> list:
    """运行选股筛选并打印结果"""
    pool = pool or DEFAULT_POOL
    holdings = _load_holdings()

    print("=" * 70)
    print("  QStock 市场扫描报告 v5")
    print(f"  扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  股票池: {len(pool)} 只")
    print(f"  数据模式: {'实时+历史' if screener.realtime else '纯历史'}")
    print(f"  频率级别: {screener.freq}")
    print(f"  ADX 门槛: {screener.adx_threshold}")
    print(f"  策略: fused（缠论+双龙融合, v8 参数）")
    if holdings:
        print(f"  已持仓: {len(holdings)} 只")
    print("=" * 70)
    print()

    results = screener.screen_pool(pool)

    recommended = [r for r in results if r["grade"] == "推荐"]
    watching = [r for r in results if r["grade"] == "关注"]
    eliminated = [r for r in results if r["grade"] == "淘汰"]

    print()
    print("=" * 70)
    print(f"  筛选结果: 推荐 {len(recommended)} | 关注 {len(watching)} | 淘汰 {len(eliminated)}")
    print("=" * 70)

    if recommended:
        print()
        print("  【推荐交易】")
        for r in recommended:
            sig_cn = SIGNAL_CN.get(r["signal"], r["signal"])
            sig_dt = r.get("latest_dt", "")
            print(
                f"  >> {r['name']:8s} ({r['symbol']}): "
                f"{sig_cn} | 仓位 {r['position_size']:.0%} | "
                f"ADX={r['avg_adx']} | 趋势={r['trend']} | 得分={r['score']}"
            )
            print(
                f"     缠论: {r['chan_signal']} | 双龙: {r['dragon_signal']} | "
                f"波动率: {r['atr_ratio']}%"
            )
            print(f"     信号时间: {sig_dt}")
            for line in _format_detail_block(r, holdings):
                print(line)
            print()

    if watching:
        print("  【关注观察】")
        for r in watching:
            sig_cn = SIGNAL_CN.get(r["signal"], r["signal"])
            sig_dt = r.get("latest_dt", "")
            print(
                f"  -- {r['name']:8s} ({r['symbol']}): "
                f"{sig_cn} | ADX={r['avg_adx']} | 趋势={r['trend']} | 得分={r['score']}"
                f" | 信号时间: {sig_dt}"
            )
            # 关注级别也附带简要持仓建议
            detail_lines = _format_detail_block(r, holdings)
            for line in detail_lines:
                print(line)
        print()

    if not recommended and not watching:
        print()
        print("  当前无推荐或关注标的，建议观望。")
        print()

    print("  [!] 免责声明: 本扫描仅供参考, 不构成投资建议。A股T+1制度, 买入当天不能卖出。")
    print("=" * 70)

    if output_path:
        report = screener.generate_report(results, holdings=holdings)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\n  报告已保存: {output_path}")

    return results


def _load_portfolio_pool() -> list:
    """从 portfolio.json 加载自选池，转为 (symbol#E, name) 列表"""
    if not os.path.exists(PORTFOLIO_PATH):
        print(f"  [WARN] 自选池文件不存在: {PORTFOLIO_PATH}")
        return []
    with open(PORTFOLIO_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    pool = []
    for item in data.get("stocks", []):
        sym = item["symbol"]
        full = sym if "#" in sym else f"{sym}#E"
        pool.append((full, item.get("name", sym)))
    return pool


def main():
    parser = argparse.ArgumentParser(
        description="QStock 市场扫描 v4（选股+信号扫描一体化）"
    )
    parser.add_argument(
        "--symbols",
        default=None,
        help="股票代码列表（逗号分隔），如 600519.SH,300750.SZ",
    )
    parser.add_argument(
        "--portfolio",
        action="store_true",
        help="扫描自选股票池（读取 data/portfolio.json）",
    )
    parser.add_argument(
        "--freq", default="F30", choices=["F15", "F30", "F60"],
        help="K线频率（默认 F30）",
    )
    parser.add_argument(
        "--adx-threshold",
        type=float,
        default=20.0,
        help="ADX 趋势强度门槛（默认 20）",
    )
    parser.add_argument(
        "--no-realtime",
        action="store_true",
        help="关闭实时数据，使用纯历史模式",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="输出 Markdown 报告路径（如 docs/scan_report.md）",
    )

    args = parser.parse_args()

    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",")]
        pool = []
        for s in symbols:
            sym = s if "#" in s else f"{s}#E"
            pool.append((sym, sym.split("#")[0]))
    elif args.portfolio:
        pool = _load_portfolio_pool()
        if not pool:
            print("  自选池为空，使用默认股票池")
            pool = DEFAULT_POOL
    else:
        pool = DEFAULT_POOL

    freq = FREQ_MAP[args.freq]

    screener = StockScreenerV3(
        adx_threshold=args.adx_threshold,
        realtime=not args.no_realtime,
        freq=freq,
    )

    scan(screener, pool, args.output)


if __name__ == "__main__":
    main()
