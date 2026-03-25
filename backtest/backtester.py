"""
回测引擎 v8（第八阶段最终版 — ATR自适应止损 + 量能确认）

v8 正式配置（8.3a 验证通过）：
  - ATR 自适应止损：买入时读取 ATR14，止损距离=2×ATR/买入价，限制在[-3%,-8%]
  - ATR 移动止盈：激活=1.5×ATR，回撤=1.0×ATR
  - 量能确认：vol_ratio 作为仓位乘数（放量1.2x/缩量0.3x，软过滤不阻止信号）
  - 验证结果：验证集 8/10 只股票改善，盈亏比 1.31→1.75，回撤 -1.83%→-1.52%
  - use_atr_stops=False / use_vol_filter=False 时退回到 v7.2 固定百分比（向后兼容）

v5 基础：
  - 日线趋势过滤（daily_bars=None 时不启用）
  - 初始资金 100 万，基于总权益计算仓位，支持加仓
  - T+1 约束、手续费万三、印花税千一、滑点 0.1%
"""

import pandas as pd
import numpy as np
from czsc import RawBar, Freq
from typing import List

from strategy.dragon_signals import DragonSignalGenerator


class Backtester:

    def __init__(
        self,
        initial_cash: float = 1_000_000,
        commission: float = 0.0003,
        stamp_tax: float = 0.001,
        slippage: float = 0.001,
        stop_loss: float = -0.05,
        trailing_activate: float = 0.05,
        trailing_stop_pct: float = 0.03,
        time_stop_bars: int = 40,
        max_consecutive_losses: int = 3,
        max_position_pct: float = 0.50,
        dragon_lookback: int = 5,
        position_sizing: dict = None,
        use_atr_stops: bool = True,
        atr_stop_multiplier: float = 2.0,
        atr_tp_activate: float = 1.5,
        atr_trail_multiplier: float = 1.0,
        atr_stop_floor: float = -0.03,
        atr_stop_ceil: float = -0.08,
        use_vol_filter: bool = True,
        reduce_cooldown_bars: int = 0,
        bars_per_day: int = 4,
    ):
        self.initial_cash = initial_cash
        self.commission = commission
        self.stamp_tax = stamp_tax
        self.slippage = slippage
        self.stop_loss = stop_loss
        self.trailing_activate = trailing_activate
        self.trailing_stop_pct = trailing_stop_pct
        self.time_stop_bars = time_stop_bars
        self.max_consecutive_losses = max_consecutive_losses
        self.max_position_pct = max_position_pct
        self.dragon_lookback = dragon_lookback
        self.use_atr_stops = use_atr_stops
        self.atr_stop_multiplier = atr_stop_multiplier
        self.atr_tp_activate = atr_tp_activate
        self.atr_trail_multiplier = atr_trail_multiplier
        self.atr_stop_floor = atr_stop_floor
        self.atr_stop_ceil = atr_stop_ceil
        self.use_vol_filter = use_vol_filter
        self.reduce_cooldown_bars = reduce_cooldown_bars
        self.bars_per_day = bars_per_day
        self.position_sizing = position_sizing or {
            "STRONG_BUY": 0.40,
            "BUY": 0.30,
            "BUY_EARLY": 0.20,
            "BUY_WATCH": 0.20,
            "WAIT_CONFIRM": 0.20,
        }

    def run(
        self, bars: List[RawBar], mode: str = "fused",
        daily_bars: List[RawBar] = None,
    ) -> dict:
        if len(bars) < 60:
            return {"error": f"数据不足（仅{len(bars)}根），至少需要60根K线"}

        signals_df = self._generate_signals(bars, mode, daily_bars=daily_bars)
        equity_curve, trades = self._simulate(signals_df)
        return self._compute_metrics(equity_curve, trades)

    def run_with_signals(self, signals_df: pd.DataFrame) -> dict:
        """使用预生成的信号 DataFrame 直接运行模拟（参数搜索用）"""
        equity_curve, trades = self._simulate(signals_df)
        return self._compute_metrics(equity_curve, trades)

    def generate_signals(
        self, bars: List[RawBar], mode: str = "fused",
        daily_bars: List[RawBar] = None,
    ) -> pd.DataFrame:
        """公开的信号生成接口（配合 run_with_signals 实现参数搜索）"""
        if len(bars) < 60:
            return pd.DataFrame()
        return self._generate_signals(bars, mode, daily_bars=daily_bars)

    # ------------------------------------------------------------------ #
    #  信号生成                                                            #
    # ------------------------------------------------------------------ #

    def _generate_signals(
        self, bars: List[RawBar], mode: str,
        daily_bars: List[RawBar] = None,
    ) -> pd.DataFrame:
        if mode == "dragon":
            return self._dragon_signals(bars)
        elif mode == "fused":
            return self._fused_signals(bars, daily_bars=daily_bars)
        raise ValueError(f"未知信号模式: {mode}，可选 'dragon' 或 'fused'")

    def _dragon_signals(self, bars: List[RawBar]) -> pd.DataFrame:
        dragon = DragonSignalGenerator(bars, lookback_window=self.dragon_lookback)
        df = dragon.get_all_signals()
        df["signal"] = df["dragon_signal"]
        df["sell_type"] = "none"
        sell_mask = df["signal"] == "SELL"
        df.loc[sell_mask, "sell_type"] = "dragon_sell"
        return df

    def _fused_signals(
        self, bars: List[RawBar], daily_bars: List[RawBar] = None,
    ) -> pd.DataFrame:
        from strategy.chan_signals import ChanSignalGenerator
        from strategy.signal_engine import compute_daily_trend

        dragon = DragonSignalGenerator(bars, lookback_window=self.dragon_lookback)
        dragon_df = dragon.get_all_signals()

        init_size = min(100, len(bars) - 1)
        chan = ChanSignalGenerator(bars[:init_size])
        chan_signals = ["HOLD"] * init_size
        chan_trends = ["unknown"] * init_size

        for bar in bars[init_size:]:
            chan.update(bar)
            result = chan.analyze()
            chan_signals.append(result["signal"])
            chan_trends.append(result["trend"])

        dragon_df["chan_signal"] = chan_signals
        dragon_df["chan_trend"] = chan_trends

        daily_trend_map = {}
        if daily_bars and len(daily_bars) >= 60:
            daily_trend_map = compute_daily_trend(daily_bars)

        def fuse_row(row):
            dt_trend = "UNKNOWN"
            if daily_trend_map:
                date_str = str(pd.Timestamp(row["datetime"]).date())
                dt_trend = daily_trend_map.get(date_str, "UNKNOWN")
            return self._fuse(
                row["chan_signal"],
                row["chan_trend"],
                row["dragon_signal"],
                row.get("dragon_trend", "neutral"),
                dt_trend,
            )

        fused = dragon_df.apply(fuse_row, axis=1, result_type="expand")
        dragon_df["signal"] = fused[0]
        dragon_df["sell_type"] = fused[1]
        return dragon_df

    @staticmethod
    def _fuse(
        chan: str, chan_trend: str, dragon: str, dragon_trend: str,
        daily_trend: str = "UNKNOWN",
    ) -> tuple:
        """
        v4 融合规则，返回 (信号, 卖出类型)。
        在 v3 基础上叠加日线趋势过滤。
        """
        chan_buy = chan.startswith("BUY")
        chan_sell = chan.startswith("SELL")
        dragon_strong = dragon == "STRONG_BUY"
        dragon_buy = dragon in ("BUY", "STRONG_BUY")
        dragon_early = dragon == "BUY_EARLY"
        dragon_sell = dragon == "SELL"
        dragon_bullish = dragon_trend == "bullish"
        chan_up = chan_trend == "up"

        # --- 原始信号（v3 规则） ---
        raw_signal = "HOLD"
        raw_sell_type = "none"

        if chan_sell:
            raw_signal, raw_sell_type = "SELL_ALL", "chan_sell"
        elif dragon_sell and not chan_buy:
            raw_signal, raw_sell_type = "REDUCE", "dragon_sell"
        elif chan_buy and dragon_strong:
            raw_signal = "STRONG_BUY"
        elif chan_buy and dragon_buy:
            raw_signal = "BUY"
        elif chan_buy and dragon_bullish:
            raw_signal = "BUY"
        elif dragon_buy and chan_up:
            raw_signal = "BUY"
        elif chan_buy:
            raw_signal = "WAIT_CONFIRM"
        elif dragon_buy or dragon_strong:
            raw_signal = "BUY_WATCH"
        elif dragon_early and (dragon_bullish or chan_up):
            raw_signal = "BUY_EARLY"
        elif dragon_sell and chan_buy:
            raw_signal = "HOLD"

        # --- 日线趋势过滤（仅影响买入，不干预卖出/减仓） ---
        if daily_trend == "UNKNOWN":
            return (raw_signal, raw_sell_type)

        is_buy = raw_signal in (
            "STRONG_BUY", "BUY", "BUY_EARLY", "BUY_WATCH", "WAIT_CONFIRM",
        )

        if daily_trend == "DOWN" and is_buy:
            return ("HOLD", "none")

        if daily_trend == "SIDE" and is_buy and raw_signal != "STRONG_BUY":
            return ("HOLD", "none")

        return (raw_signal, raw_sell_type)

    # ------------------------------------------------------------------ #
    #  交易模拟（含分层退出、止损止盈、时间止损）                                #
    # ------------------------------------------------------------------ #

    def _simulate(self, df: pd.DataFrame) -> tuple:
        cash = self.initial_cash
        position = 0
        position_cost = 0.0
        avg_buy_price = 0.0
        buy_date = None
        first_buy_bar_idx = 0
        highest_since_buy = 0.0
        consecutive_losses = 0
        buy_atr = 0.0
        trades: list = []
        equity_curve: list = []

        for bar_idx, (_, row) in enumerate(df.iterrows()):
            price = row["close"]
            signal = row["signal"]
            sell_type = row.get("sell_type", "none")
            dt = row["datetime"]
            current_date = pd.Timestamp(dt).date()

            cur_atr = row.get("atr14", 0.0)
            if pd.isna(cur_atr):
                cur_atr = 0.0

            equity = cash + position * price
            equity_curve.append({
                "datetime": dt,
                "equity": equity,
                "price": price,
                "position": position,
            })

            if position > 0 and price > highest_since_buy:
                highest_since_buy = price

            can_sell = position > 0 and (buy_date is None or current_date > buy_date)
            bars_held = bar_idx - first_buy_bar_idx

            # === 持仓中的退出检查 ===
            if can_sell:
                action, reason = self._check_exit(
                    price=price,
                    buy_price=avg_buy_price,
                    highest_since_buy=highest_since_buy,
                    bars_held=bars_held,
                    signal=signal,
                    sell_type=sell_type,
                    atr_at_buy=buy_atr,
                )

                if action == "SELL_ALL":
                    exec_price = price * (1 - self.slippage)
                    gross_revenue = position * exec_price
                    net_revenue = gross_revenue * (1 - self.commission - self.stamp_tax)
                    profit = net_revenue - position_cost
                    pct_return = profit / position_cost if position_cost > 0 else 0

                    cash += net_revenue
                    trades.append({
                        "datetime": str(dt),
                        "action": "SELL",
                        "price": round(exec_price, 2),
                        "shares": position,
                        "revenue": round(net_revenue, 2),
                        "profit": round(profit, 2),
                        "pct_return": round(pct_return, 4),
                        "signal": signal,
                        "reason": reason,
                    })

                    if profit <= 0:
                        consecutive_losses += 1
                    else:
                        consecutive_losses = 0

                    position = 0
                    position_cost = 0.0
                    buy_date = None
                    avg_buy_price = 0.0
                    highest_since_buy = 0.0
                    buy_atr = 0.0
                    continue

                elif action == "REDUCE":
                    reduce_shares = (position // 2 // 100) * 100
                    if reduce_shares >= 100:
                        exec_price = price * (1 - self.slippage)
                        gross_revenue = reduce_shares * exec_price
                        net_revenue = gross_revenue * (1 - self.commission - self.stamp_tax)
                        cost_portion = position_cost * (reduce_shares / position)
                        profit = net_revenue - cost_portion
                        pct_return = profit / cost_portion if cost_portion > 0 else 0

                        cash += net_revenue
                        position -= reduce_shares
                        position_cost -= cost_portion

                        trades.append({
                            "datetime": str(dt),
                            "action": "REDUCE",
                            "price": round(exec_price, 2),
                            "shares": reduce_shares,
                            "revenue": round(net_revenue, 2),
                            "profit": round(profit, 2),
                            "pct_return": round(pct_return, 4),
                            "signal": signal,
                            "reason": reason,
                        })
                        continue

            # === 买入 / 加仓检查 ===
            if signal in self.position_sizing:
                if consecutive_losses >= self.max_consecutive_losses:
                    continue

                target_alloc = self.position_sizing[signal]
                if target_alloc <= 0:
                    continue

                current_alloc = (position * price) / equity if equity > 0 else 0
                effective_max = min(target_alloc, self.max_position_pct)

                if current_alloc >= effective_max:
                    continue

                if position > 0:
                    if not can_sell:
                        continue
                    gap = effective_max - current_alloc
                    if gap < 0.05 or signal not in ("STRONG_BUY", "BUY"):
                        continue

                additional_alloc = effective_max - current_alloc

                if self.use_vol_filter:
                    vr = row.get("vol_ratio", 1.0)
                    if pd.isna(vr):
                        vr = 1.0
                    if vr >= 1.5:
                        vol_mult = 1.2
                    elif vr >= 1.0:
                        vol_mult = 1.0
                    elif vr >= 0.6:
                        vol_mult = 0.6
                    else:
                        vol_mult = 0.3
                    additional_alloc *= vol_mult
                    additional_alloc = min(additional_alloc, self.max_position_pct - current_alloc)

                exec_price = price * (1 + self.slippage)
                available = equity * additional_alloc
                max_shares = available / (exec_price * (1 + self.commission))
                shares = int(max_shares / 100) * 100

                if shares >= 100:
                    cost = shares * exec_price * (1 + self.commission)
                    if cost <= cash:
                        cash -= cost
                        is_new = position == 0

                        if is_new:
                            avg_buy_price = exec_price
                            highest_since_buy = price
                            first_buy_bar_idx = bar_idx
                            buy_atr = cur_atr
                        else:
                            old_val = position * avg_buy_price
                            new_val = shares * exec_price
                            avg_buy_price = (old_val + new_val) / (position + shares)

                        position += shares
                        position_cost += cost
                        buy_date = current_date

                        action_label = "BUY" if is_new else "ADD"
                        trades.append({
                            "datetime": str(dt),
                            "action": action_label,
                            "price": round(exec_price, 2),
                            "shares": shares,
                            "cost": round(cost, 2),
                            "signal": signal,
                            "reason": f"{'买入' if is_new else '加仓'}({signal}, 目标{target_alloc:.0%})",
                        })

        return equity_curve, trades

    def _check_exit(
        self,
        price: float,
        buy_price: float,
        highest_since_buy: float,
        bars_held: int,
        signal: str,
        sell_type: str,
        atr_at_buy: float = 0.0,
    ) -> tuple:
        """
        分层退出检查，按优先级返回 (action, reason):
        1. 止损（ATR 自适应 或 固定百分比）
        2. 移动止盈（ATR 自适应 或 固定百分比）
        3. 信号卖出（缠论→全卖，双龙死叉→减仓，含 REDUCE 冷却期）
        4. 时间止损
        """
        if buy_price <= 0:
            return ("HOLD", "")

        pct_from_buy = (price - buy_price) / buy_price

        # --- 1. 止损 ---
        if self.use_atr_stops and atr_at_buy > 0:
            atr_stop_dist = self.atr_stop_multiplier * atr_at_buy / buy_price
            atr_stop_dist = max(atr_stop_dist, abs(self.atr_stop_floor))
            atr_stop_dist = min(atr_stop_dist, abs(self.atr_stop_ceil))
            effective_stop = -atr_stop_dist
            if pct_from_buy <= effective_stop:
                return (
                    "SELL_ALL",
                    f"ATR止损: {pct_from_buy:.2%} <= {effective_stop:.2%} "
                    f"(ATR={atr_at_buy:.2f}, {self.atr_stop_multiplier}x)",
                )
        else:
            if pct_from_buy <= self.stop_loss:
                return ("SELL_ALL", f"止损: {pct_from_buy:.2%} <= {self.stop_loss:.0%}")

        # --- 2. 移动止盈 ---
        if highest_since_buy > 0:
            pct_from_high = (price - highest_since_buy) / highest_since_buy
            pct_profit_from_buy = (highest_since_buy - buy_price) / buy_price

            if self.use_atr_stops and atr_at_buy > 0:
                tp_activate = self.atr_tp_activate * atr_at_buy / buy_price
                tp_trail = self.atr_trail_multiplier * atr_at_buy / highest_since_buy
                if pct_profit_from_buy >= tp_activate and pct_from_high <= -tp_trail:
                    return (
                        "SELL_ALL",
                        f"ATR移动止盈: 最高盈利{pct_profit_from_buy:.2%}, "
                        f"回撤{pct_from_high:.2%} (阈值{tp_trail:.2%})",
                    )
            else:
                if (
                    pct_profit_from_buy >= self.trailing_activate
                    and pct_from_high <= -self.trailing_stop_pct
                ):
                    return (
                        "SELL_ALL",
                        f"移动止盈: 最高盈利{pct_profit_from_buy:.2%}, 回撤{pct_from_high:.2%}",
                    )

        # --- 3. 信号卖出 ---
        if sell_type == "chan_sell" or signal == "SELL_ALL":
            return ("SELL_ALL", f"缠论卖出信号")

        if sell_type == "dragon_sell" or signal == "REDUCE":
            if self.reduce_cooldown_bars > 0 and bars_held < self.reduce_cooldown_bars:
                pass
            else:
                return ("REDUCE", f"双龙死叉减仓")

        # --- 4. 时间止损 ---
        if bars_held >= self.time_stop_bars:
            if pct_from_buy < 0:
                return ("SELL_ALL", f"时间止损: 持仓{bars_held}根K线, 亏损{pct_from_buy:.2%}")
            elif pct_from_buy < 0.02:
                return ("REDUCE", f"时间减仓: 持仓{bars_held}根K线, 微利{pct_from_buy:.2%}")

        return ("HOLD", "")

    # ------------------------------------------------------------------ #
    #  指标计算                                                            #
    # ------------------------------------------------------------------ #

    def _compute_metrics(self, equity_curve: list, trades: list) -> dict:
        eq_df = pd.DataFrame(equity_curve)
        if eq_df.empty:
            return {"error": "无权益数据"}

        final_equity = eq_df["equity"].iloc[-1]
        total_return = (final_equity - self.initial_cash) / self.initial_cash

        eq_df["peak"] = eq_df["equity"].cummax()
        eq_df["drawdown"] = (eq_df["equity"] - eq_df["peak"]) / eq_df["peak"]
        max_drawdown = eq_df["drawdown"].min()

        sell_trades = [t for t in trades if t["action"] in ("SELL", "REDUCE")]
        wins = [t for t in sell_trades if t.get("profit", 0) > 0]
        losses = [t for t in sell_trades if t.get("profit", 0) <= 0]

        n_bars = len(eq_df)
        n_years = n_bars / (250 * self.bars_per_day) if n_bars > 0 else 1
        annual_return = (
            (1 + total_return) ** (1 / max(n_years, 0.01)) - 1
            if total_return > -1
            else -1
        )

        win_rate = len(wins) / len(sell_trades) if sell_trades else 0
        avg_win = float(np.mean([t["profit"] for t in wins])) if wins else 0.0
        avg_loss = float(abs(np.mean([t["profit"] for t in losses]))) if losses else 0.0
        profit_ratio = avg_win / avg_loss if avg_loss > 0 else float("inf")

        eq_df["bar_return"] = eq_df["equity"].pct_change()
        sharpe = 0.0
        if len(eq_df) > 1:
            std = eq_df["bar_return"].std()
            if std > 0:
                sharpe = float(eq_df["bar_return"].mean() / std * np.sqrt(250 * self.bars_per_day))

        buy_count = len([t for t in trades if t["action"] == "BUY"])
        add_count = len([t for t in trades if t["action"] == "ADD"])
        sell_all_count = len([t for t in trades if t["action"] == "SELL"])
        reduce_count = len([t for t in trades if t["action"] == "REDUCE"])

        return {
            "initial_cash": self.initial_cash,
            "final_equity": round(final_equity, 2),
            "total_return": f"{total_return:.2%}",
            "total_return_pct": round(total_return * 100, 2),
            "annual_return": f"{annual_return:.2%}",
            "max_drawdown": f"{max_drawdown:.2%}",
            "max_drawdown_pct": round(max_drawdown * 100, 2),
            "sharpe_ratio": round(sharpe, 2),
            "total_trades": len(sell_trades),
            "buy_count": buy_count,
            "add_count": add_count,
            "sell_all_count": sell_all_count,
            "reduce_count": reduce_count,
            "win_rate": f"{win_rate:.2%}",
            "win_rate_pct": round(win_rate * 100, 2),
            "profit_ratio": f"{profit_ratio:.2f}",
            "profit_ratio_raw": round(profit_ratio, 4),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "trades": trades,
            "equity_curve": eq_df,
        }


# ------------------------------------------------------------------ #
#  便捷函数                                                            #
# ------------------------------------------------------------------ #


def print_report(result: dict, stock_name: str = "", mode: str = ""):
    if "error" in result:
        print(f"  {stock_name}: {result['error']}")
        return

    header = f"  {stock_name}" if stock_name else "  回测结果"
    if mode:
        header += f" [{mode}]"
    print(header)
    print(f"    资金: {result['initial_cash']:,.0f} → {result['final_equity']:,.0f}")
    print(f"    收益: {result['total_return']}  年化: {result['annual_return']}")
    print(f"    回撤: {result['max_drawdown']}  Sharpe: {result['sharpe_ratio']}")
    add_str = f"/加仓{result['add_count']}" if result.get('add_count', 0) > 0 else ""
    print(
        f"    交易: {result['total_trades']}次 "
        f"(买{result.get('buy_count', '?')}{add_str}"
        f"/卖{result.get('sell_all_count', '?')}/减仓{result.get('reduce_count', '?')})  "
        f"胜率: {result['win_rate']}  盈亏比: {result['profit_ratio']}"
    )

    trades = result.get("trades", [])
    if not trades:
        return

    rounds = []
    current_entries = []
    current_exits = []
    for t in trades:
        if t["action"] == "BUY":
            if current_entries and current_exits:
                rounds.append((current_entries, current_exits))
            current_entries = [t]
            current_exits = []
        elif t["action"] == "ADD":
            current_entries.append(t)
        elif t["action"] in ("SELL", "REDUCE"):
            current_exits.append(t)
    if current_entries and current_exits:
        rounds.append((current_entries, current_exits))

    if rounds:
        print(f"    交易明细 ({len(rounds)} 个回合):")
        for i, (entries, exits) in enumerate(rounds, 1):
            total_profit = sum(e.get("profit", 0) for e in exits)
            total_cost = sum(e.get("cost", 0) for e in entries)
            total_shares = sum(e.get("shares", 0) for e in entries)
            flag = "[+]" if total_profit > 0 else "[-]"
            first_buy = entries[0]
            last_exit = exits[-1]
            add_info = f"+{len(entries)-1}次加仓" if len(entries) > 1 else ""
            print(
                f"      #{i} {flag} 买{first_buy['datetime'][:10]} @{first_buy['price']:.2f} "
                f"({total_shares}股{add_info})"
                f" → {last_exit['datetime'][:10]} "
                f"总盈亏{total_profit:+.2f}"
            )
            for e in exits:
                label = "清仓" if e["action"] == "SELL" else "减仓"
                reason = e.get("reason", "")
                print(
                    f"          {label} @{e['price']:.2f} "
                    f"{e.get('shares', '?')}股 "
                    f"{e['profit']:+.2f} "
                    f"[{reason}]"
                )
