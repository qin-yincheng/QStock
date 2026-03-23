"""
信号融合引擎
缠论判断大方向（趋势 / 买卖点级别）+ 双龙判断入场时机 = 综合信号
"""
from czsc import RawBar, Freq
from typing import List
from strategy.chan_signals import ChanSignalGenerator
from strategy.dragon_signals import DragonSignalGenerator


class SignalEngine:
    """综合信号引擎"""

    def __init__(self, bars: List[RawBar]):
        self.bars = bars
        self.chan = ChanSignalGenerator(bars)
        self.dragon = DragonSignalGenerator(bars)

    def generate(self) -> dict:
        """生成综合交易信号"""
        chan_result = self.chan.analyze()
        dragon_result = self.dragon.get_signal()

        final = self._fuse(chan_result['signal'], dragon_result['signal'])

        return {
            'final_signal': final['action'],
            'confidence': final['confidence'],
            'reason': final['reason'],
            'chan_signal': chan_result['signal'],
            'chan_detail': chan_result['detail'],
            'chan_trend': chan_result['trend'],
            'dragon_signal': dragon_result['signal'],
            'dragon_detail': dragon_result['detail'],
            'bi_count': chan_result['bi_count'],
            'last_bi_direction': chan_result['last_bi_direction'],
            'ema5': dragon_result['ema5'],
            'ema10': dragon_result['ema10'],
            'dif': dragon_result['dif'],
            'dea': dragon_result['dea'],
        }

    def _fuse(self, chan: str, dragon: str) -> dict:
        """
        融合规则（卖出优先）:
        1. 任一卖出 → 卖出 (80%)
        2. 缠论买点 + 双龙强买 → 强烈买入 (90%)
        3. 缠论买点 + 双龙买入 → 买入 (75%)
        4. 双龙强买 (无缠论) → 观察 (60%)
        5. 缠论买点 (无双龙) → 等待确认 (50%)
        6. 其他 → 持仓等待
        """
        chan_buy = chan.startswith('BUY')
        dragon_buy = dragon in ('BUY', 'STRONG_BUY')
        dragon_strong = dragon == 'STRONG_BUY'
        any_sell = chan.startswith('SELL') or dragon == 'SELL'

        if any_sell:
            return {'action': 'SELL', 'confidence': 0.80,
                    'reason': f'卖出信号 [缠论:{chan}, 双龙:{dragon}]'}

        if chan_buy and dragon_strong:
            return {'action': 'STRONG_BUY', 'confidence': 0.90,
                    'reason': f'强买: 缠论{chan}+双龙齐飞'}

        if chan_buy and dragon_buy:
            return {'action': 'BUY', 'confidence': 0.75,
                    'reason': f'买入: 缠论{chan}+双龙确认'}

        if dragon_strong:
            return {'action': 'BUY_WATCH', 'confidence': 0.60,
                    'reason': f'观察: 双龙齐飞但缠论未确认({chan})'}

        if chan_buy:
            return {'action': 'WAIT_CONFIRM', 'confidence': 0.50,
                    'reason': f'等待: 缠论{chan}但双龙未共振'}

        return {'action': 'HOLD', 'confidence': 0.0,
                'reason': f'无信号 [缠论:{chan}, 双龙:{dragon}]'}


def analyze_stock(symbol: str, sdt: str, edt: str) -> dict:
    """分析单只股票"""
    from core.data_provider import get_raw_bars

    bars = get_raw_bars(symbol, Freq.F60, sdt, edt)
    if not bars or len(bars) < 30:
        return {'error': f'{symbol} 数据不足'}

    engine = SignalEngine(bars)
    result = engine.generate()
    result['symbol'] = symbol
    result['datetime'] = str(bars[-1].dt)
    result['close'] = bars[-1].close
    result['bar_count'] = len(bars)
    return result


def analyze_stock_realtime(symbol: str) -> dict:
    """实战盘中分析（自动拼接历史 + 实时数据）"""
    from core.data_provider import get_realtime_bars

    bars = get_realtime_bars(symbol, Freq.F60)
    if not bars or len(bars) < 30:
        return {'error': f'{symbol} 数据不足'}

    engine = SignalEngine(bars)
    result = engine.generate()
    result['symbol'] = symbol
    result['datetime'] = str(bars[-1].dt)
    result['close'] = bars[-1].close
    result['bar_count'] = len(bars)
    return result
