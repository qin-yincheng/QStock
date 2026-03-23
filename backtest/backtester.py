"""
回测引擎
- T+1 约束：买入当天不能卖出
- 手续费：万三（双向收取）
- 印花税：千一（仅卖出时收取）
- 滑点：0.1%
- 支持两种信号模式：dragon（纯双龙）/ fused（缠论+双龙融合）
"""
import pandas as pd
import numpy as np
from czsc import RawBar, Freq
from typing import List

from strategy.dragon_signals import DragonSignalGenerator


class Backtester:
    """含 T+1 约束的回测引擎"""

    def __init__(self, initial_cash: float = 100000,
                 commission: float = 0.0003,
                 stamp_tax: float = 0.001,
                 slippage: float = 0.001):
        self.initial_cash = initial_cash
        self.commission = commission
        self.stamp_tax = stamp_tax
        self.slippage = slippage

    def run(self, bars: List[RawBar], mode: str = 'fused') -> dict:
        """
        运行回测

        Args:
            bars: K线数据列表
            mode: 信号模式 — 'dragon'（纯双龙）或 'fused'（缠论+双龙融合）

        Returns:
            包含 metrics、trades、equity_curve 的字典
        """
        if len(bars) < 60:
            return {'error': f'数据不足（仅{len(bars)}根），至少需要60根K线'}

        signals_df = self._generate_signals(bars, mode)
        equity_curve, trades = self._simulate(signals_df)
        return self._compute_metrics(equity_curve, trades)

    # ------------------------------------------------------------------ #
    #  信号生成                                                            #
    # ------------------------------------------------------------------ #

    def _generate_signals(self, bars: List[RawBar], mode: str) -> pd.DataFrame:
        if mode == 'dragon':
            return self._dragon_signals(bars)
        elif mode == 'fused':
            return self._fused_signals(bars)
        raise ValueError(f"未知信号模式: {mode}，可选 'dragon' 或 'fused'")

    def _dragon_signals(self, bars: List[RawBar]) -> pd.DataFrame:
        """纯双龙信号"""
        dragon = DragonSignalGenerator(bars)
        df = dragon.get_all_signals()
        df['signal'] = df['dragon_signal']
        return df

    def _fused_signals(self, bars: List[RawBar]) -> pd.DataFrame:
        """
        缠论 + 双龙融合信号

        双龙信号一次性全量计算（EMA/MACD 是顺序指标，无前瞻偏差）；
        缠论信号逐 K 线增量更新，保证第 i 根 K 线的信号只依赖 bars[0..i]。
        """
        from strategy.chan_signals import ChanSignalGenerator

        dragon = DragonSignalGenerator(bars)
        dragon_df = dragon.get_all_signals()

        init_size = min(100, len(bars) - 1)
        chan = ChanSignalGenerator(bars[:init_size])
        chan_signals = ['HOLD'] * init_size

        for bar in bars[init_size:]:
            chan.update(bar)
            chan_signals.append(chan.analyze()['signal'])

        dragon_df['chan_signal'] = chan_signals
        dragon_df['signal'] = dragon_df.apply(
            lambda row: self._fuse(row['chan_signal'], row['dragon_signal']),
            axis=1,
        )
        return dragon_df

    @staticmethod
    def _fuse(chan: str, dragon: str) -> str:
        """
        融合规则（与 SignalEngine._fuse 对齐，简化为交易动作）:
          卖出优先 → 缠论+双龙共振买入 → 双龙强买独立触发 → 其余 HOLD
        """
        if chan.startswith('SELL') or dragon == 'SELL':
            return 'SELL'

        chan_buy = chan.startswith('BUY')
        dragon_strong = dragon == 'STRONG_BUY'
        dragon_buy = dragon in ('BUY', 'STRONG_BUY')

        if chan_buy and dragon_buy:
            return 'STRONG_BUY' if dragon_strong else 'BUY'
        if dragon_strong:
            return 'BUY'
        return 'HOLD'

    # ------------------------------------------------------------------ #
    #  交易模拟                                                            #
    # ------------------------------------------------------------------ #

    def _simulate(self, df: pd.DataFrame) -> tuple:
        cash = self.initial_cash
        position = 0
        position_cost = 0.0
        buy_price = 0.0
        buy_date = None
        trades: list = []
        equity_curve: list = []

        for _, row in df.iterrows():
            price = row['close']
            signal = row['signal']
            dt = row['datetime']
            current_date = pd.Timestamp(dt).date()

            equity = cash + position * price
            equity_curve.append({
                'datetime': dt,
                'equity': equity,
                'price': price,
                'position': position,
            })

            if signal in ('BUY', 'STRONG_BUY') and position == 0:
                exec_price = price * (1 + self.slippage)
                max_shares = cash / (exec_price * (1 + self.commission))
                shares = int(max_shares / 100) * 100
                if shares >= 100:
                    cost = shares * exec_price * (1 + self.commission)
                    cash -= cost
                    position = shares
                    position_cost = cost
                    buy_price = exec_price
                    buy_date = current_date
                    trades.append({
                        'datetime': str(dt),
                        'action': 'BUY',
                        'price': round(exec_price, 2),
                        'shares': shares,
                        'cost': round(cost, 2),
                        'signal': signal,
                    })

            elif signal == 'SELL' and position > 0:
                if buy_date is not None and current_date <= buy_date:
                    continue

                exec_price = price * (1 - self.slippage)
                gross_revenue = position * exec_price
                net_revenue = gross_revenue * (1 - self.commission - self.stamp_tax)
                profit = net_revenue - position_cost
                pct_return = profit / position_cost if position_cost > 0 else 0

                cash += net_revenue
                trades.append({
                    'datetime': str(dt),
                    'action': 'SELL',
                    'price': round(exec_price, 2),
                    'shares': position,
                    'revenue': round(net_revenue, 2),
                    'profit': round(profit, 2),
                    'pct_return': round(pct_return, 4),
                    'signal': signal,
                })
                position = 0
                position_cost = 0.0
                buy_date = None

        return equity_curve, trades

    # ------------------------------------------------------------------ #
    #  指标计算                                                            #
    # ------------------------------------------------------------------ #

    def _compute_metrics(self, equity_curve: list, trades: list) -> dict:
        eq_df = pd.DataFrame(equity_curve)
        if eq_df.empty:
            return {'error': '无权益数据'}

        final_equity = eq_df['equity'].iloc[-1]
        total_return = (final_equity - self.initial_cash) / self.initial_cash

        eq_df['peak'] = eq_df['equity'].cummax()
        eq_df['drawdown'] = (eq_df['equity'] - eq_df['peak']) / eq_df['peak']
        max_drawdown = eq_df['drawdown'].min()

        sell_trades = [t for t in trades if t['action'] == 'SELL']
        wins = [t for t in sell_trades if t.get('profit', 0) > 0]
        losses = [t for t in sell_trades if t.get('profit', 0) <= 0]

        # 60 分钟 K 线约每天 4 根、每年 250 个交易日
        n_bars = len(eq_df)
        n_years = n_bars / (250 * 4) if n_bars > 0 else 1
        annual_return = (
            (1 + total_return) ** (1 / max(n_years, 0.01)) - 1
            if total_return > -1 else -1
        )

        win_rate = len(wins) / len(sell_trades) if sell_trades else 0
        avg_win = float(np.mean([t['profit'] for t in wins])) if wins else 0.0
        avg_loss = float(abs(np.mean([t['profit'] for t in losses]))) if losses else 0.0
        profit_ratio = avg_win / avg_loss if avg_loss > 0 else float('inf')

        eq_df['bar_return'] = eq_df['equity'].pct_change()
        sharpe = 0.0
        if len(eq_df) > 1:
            std = eq_df['bar_return'].std()
            if std > 0:
                sharpe = float(eq_df['bar_return'].mean() / std * np.sqrt(250 * 4))

        return {
            'initial_cash': self.initial_cash,
            'final_equity': round(final_equity, 2),
            'total_return': f"{total_return:.2%}",
            'annual_return': f"{annual_return:.2%}",
            'max_drawdown': f"{max_drawdown:.2%}",
            'sharpe_ratio': round(sharpe, 2),
            'total_trades': len(sell_trades),
            'win_rate': f"{win_rate:.2%}",
            'profit_ratio': f"{profit_ratio:.2f}",
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'trades': trades,
            'equity_curve': eq_df,
        }


# ------------------------------------------------------------------ #
#  便捷函数                                                            #
# ------------------------------------------------------------------ #

def print_report(result: dict, stock_name: str = '', mode: str = ''):
    """打印单只股票回测报告"""
    if 'error' in result:
        print(f"  {stock_name}: {result['error']}")
        return

    header = f"  {stock_name}" if stock_name else "  回测结果"
    if mode:
        header += f" [{mode}]"
    print(header)
    print(f"    资金: {result['initial_cash']:,.0f} → {result['final_equity']:,.0f}")
    print(f"    收益: {result['total_return']}  年化: {result['annual_return']}")
    print(f"    回撤: {result['max_drawdown']}  Sharpe: {result['sharpe_ratio']}")
    print(f"    交易: {result['total_trades']}次  "
          f"胜率: {result['win_rate']}  盈亏比: {result['profit_ratio']}")

    trades = result.get('trades', [])
    buy_trades = [t for t in trades if t['action'] == 'BUY']
    sell_trades = [t for t in trades if t['action'] == 'SELL']

    if sell_trades:
        print(f"    交易明细:")
        for bt, st in zip(buy_trades, sell_trades):
            pct = st.get('pct_return', 0)
            flag = '[+]' if st.get('profit', 0) > 0 else '[-]'
            print(f"      {flag} 买{bt['datetime'][:10]} @{bt['price']:.2f}"
                  f" → 卖{st['datetime'][:10]} @{st['price']:.2f}"
                  f"  盈亏{st['profit']:+.2f} ({pct:+.2%})")
