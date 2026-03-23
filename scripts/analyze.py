"""
单股分析脚本 — 供 OpenClaw Agent 调用
用法：python scripts/analyze.py --symbol 600519.SH
"""
import sys
import os
import argparse
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy.signal_engine import analyze_stock
from czsc import Freq


SIGNAL_CN = {
    'STRONG_BUY': '强烈买入',
    'BUY': '买入',
    'BUY_WATCH': '观察（双龙齐飞但缠论未确认）',
    'WAIT_CONFIRM': '等待确认（缠论买点但双龙未共振）',
    'SELL': '卖出',
    'HOLD': '持仓等待',
}

TREND_CN = {
    'up': '上升趋势',
    'down': '下降趋势',
    'sideways': '震荡整理',
    'unknown': '趋势不明',
}


def format_report(result: dict) -> str:
    """将分析结果格式化为中文报告"""
    if 'error' in result:
        return f"分析失败: {result['error']}"

    signal = result.get('final_signal', 'HOLD')
    confidence = result.get('confidence', 0)
    symbol = result.get('symbol', '')
    dt = result.get('datetime', '')
    close = result.get('close', 0)
    bar_count = result.get('bar_count', 0)

    lines = [
        "=" * 60,
        f"  QStock 量化分析报告 — {symbol.split('#')[0]}",
        "=" * 60,
        f"  分析时间: {dt}",
        f"  最新价格: {close:.2f}",
        f"  K线数量: {bar_count} 根（60分钟级别）",
        "",
        "  【综合信号】",
        f"    信号: {SIGNAL_CN.get(signal, signal)}",
        f"    置信度: {confidence:.0%}",
        f"    依据: {result.get('reason', '')}",
        "",
        "  【缠论分析】",
        f"    缠论信号: {result.get('chan_signal', '')}",
        f"    信号详情: {result.get('chan_detail', '')}",
        f"    趋势方向: {TREND_CN.get(result.get('chan_trend', ''), '')}",
        f"    笔数量: {result.get('bi_count', 0)}",
        f"    最后笔方向: {result.get('last_bi_direction', '')}",
        "",
        "  【双龙战法】",
        f"    双龙信号: {result.get('dragon_signal', '')}",
        f"    信号详情: {result.get('dragon_detail', '')}",
        f"    EMA5: {result.get('ema5', '')}  EMA10: {result.get('ema10', '')}",
        f"    DIF: {result.get('dif', '')}  DEA: {result.get('dea', '')}",
        "",
        "  【操作建议】",
    ]

    if signal == 'STRONG_BUY':
        lines.append("    缠论买点与双龙齐飞共振，强烈买入信号。")
        lines.append("    建议：可考虑建仓，注意控制仓位。")
    elif signal == 'BUY':
        lines.append("    缠论买点与双龙确认共振，买入信号。")
        lines.append("    建议：可考虑轻仓介入，等待进一步确认。")
    elif signal == 'BUY_WATCH':
        lines.append("    双龙齐飞但缠论尚未出现买点，需观察。")
        lines.append("    建议：关注但暂不操作，等待缠论买点确认。")
    elif signal == 'WAIT_CONFIRM':
        lines.append("    缠论出现买点但双龙未共振，等待确认。")
        lines.append("    建议：持币观望，等待双龙金叉信号配合。")
    elif signal == 'SELL':
        lines.append("    出现卖出信号，注意风险。")
        lines.append("    建议：已持仓的考虑减仓或止盈。")
    else:
        lines.append("    当前无明确交易信号。")
        lines.append("    建议：继续持仓等待，不追涨杀跌。")

    lines.extend([
        "",
        "  [!] 免责声明: 本分析仅供参考, 不构成投资建议。",
        "      A股实行T+1制度, 买入当天不能卖出。",
        "=" * 60,
    ])

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="QStock 单股分析")
    parser.add_argument("--symbol", required=True,
                        help="股票代码，如 600519.SH 或 600519.SH#E")
    parser.add_argument("--sdt", default=None,
                        help="开始日期 YYYYMMDD（默认180天前）")
    parser.add_argument("--edt", default=None,
                        help="结束日期 YYYYMMDD（默认今天）")
    args = parser.parse_args()

    symbol = args.symbol
    if "#" not in symbol:
        symbol = f"{symbol}#E"

    edt = args.edt or datetime.now().strftime("%Y%m%d")
    sdt = args.sdt or (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")

    result = analyze_stock(symbol, sdt, edt)
    print(format_report(result))


if __name__ == "__main__":
    main()
