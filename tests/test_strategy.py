"""
Step 3 综合验证 — 策略模块测试
测试 chan_signals / dragon_signals / signal_engine 三个模块
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from czsc import Freq
from core.data_provider import get_raw_bars


def section(title: str):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def main():
    print("=" * 60)
    print("  Step 3 - 策略模块综合测试")
    print("=" * 60)

    # ================================================================ #
    #  0. 获取测试数据                                                   #
    # ================================================================ #
    section("0. 获取测试数据 (600519.SH 贵州茅台 60分钟)")
    bars = get_raw_bars("600519.SH#E", Freq.F60, "20250901", "20260322")
    print(f"    数据量: {len(bars)} 条 60分钟 RawBar")
    print(f"    时间范围: {bars[0].dt} ~ {bars[-1].dt}")
    assert len(bars) > 100, f"数据量不足: {len(bars)}"
    print("    ✅ 数据获取成功")

    # ================================================================ #
    #  1. ChanSignalGenerator                                          #
    # ================================================================ #
    section("1. 缠论信号模块 (ChanSignalGenerator)")
    from strategy.chan_signals import ChanSignalGenerator

    chan = ChanSignalGenerator(bars)
    chan_result = chan.analyze()

    print(f"    信号:         {chan_result['signal']}")
    print(f"    详情:         {chan_result['detail']}")
    print(f"    趋势:         {chan_result['trend']}")
    print(f"    分型数:       {chan_result['fx_count']}")
    print(f"    笔数:         {chan_result['bi_count']}")
    print(f"    最后一笔方向: {chan_result['last_bi_direction']}")

    assert chan_result['bi_count'] > 0, "笔数量为 0"
    assert chan_result['fx_count'] > chan_result['bi_count'], "分型数应 > 笔数"
    valid_chan = {'HOLD', 'BUY_1', 'BUY_2', 'BUY_3',
                  'SELL_2', 'SELL_3', 'BUY_DIV', 'SELL_DIV'}
    assert chan_result['signal'] in valid_chan, \
        f"未知信号: {chan_result['signal']}"
    assert chan_result['trend'] in ('up', 'down', 'sideways', 'unknown')
    print("    ✅ ChanSignalGenerator 测试通过")

    # --- 逐根更新测试 ---
    section("1b. 缠论信号 — 逐根更新测试")
    bars_init = bars[:-5]
    bars_update = bars[-5:]
    chan2 = ChanSignalGenerator(bars_init)
    bi_before = chan2.analyze()['bi_count']
    for bar in bars_update:
        chan2.update(bar)
    result2 = chan2.analyze()
    bi_after = result2['bi_count']
    print(f"    初始笔数:        {bi_before}")
    print(f"    追加 5 根后笔数: {bi_after}")
    print(f"    追加后信号:      {result2['signal']}")
    assert bi_after > 0, "逐根更新后笔数应 > 0"
    assert result2['signal'] in valid_chan, "逐根更新后信号应合法"
    print("    ✅ 逐根更新测试通过")

    # ================================================================ #
    #  2. DragonSignalGenerator                                        #
    # ================================================================ #
    section("2. 双龙战法模块 (DragonSignalGenerator)")
    from strategy.dragon_signals import DragonSignalGenerator

    dragon = DragonSignalGenerator(bars)
    dragon_result = dragon.get_signal()

    print(f"    信号:     {dragon_result['signal']}")
    print(f"    详情:     {dragon_result['detail']}")
    print(f"    EMA5:     {dragon_result['ema5']}")
    print(f"    EMA10:    {dragon_result['ema10']}")
    print(f"    DIF:      {dragon_result['dif']}")
    print(f"    DEA:      {dragon_result['dea']}")
    print(f"    MACD柱:   {dragon_result['macd_hist']}")

    valid_dragon = {'HOLD', 'BUY', 'STRONG_BUY', 'SELL'}
    assert dragon_result['signal'] in valid_dragon, \
        f"未知信号: {dragon_result['signal']}"
    assert dragon_result['ema5'] is not None
    assert dragon_result['ema10'] is not None
    print("    ✅ DragonSignalGenerator 测试通过")

    # --- 全量信号统计 ---
    section("2b. 双龙 — 全量信号统计 (回测模式)")
    df_signals = dragon.get_all_signals()
    signal_counts = df_signals['dragon_signal'].value_counts()
    print(f"    总 K 线数: {len(df_signals)}")
    for sig, count in signal_counts.items():
        pct = count / len(df_signals)
        print(f"      {sig:12s}  {count:4d} 次  ({pct:.1%})")
    assert len(df_signals) == len(bars), "DataFrame 行数应等于 bars 数量"
    print("    ✅ 全量信号测试通过")

    # ================================================================ #
    #  3. SignalEngine                                                  #
    # ================================================================ #
    section("3. 信号融合引擎 (SignalEngine)")
    from strategy.signal_engine import SignalEngine

    engine = SignalEngine(bars)
    result = engine.generate()

    print(f"    最终信号: {result['final_signal']}")
    print(f"    置信度:   {result['confidence']:.0%}")
    print(f"    原因:     {result['reason']}")
    print(f"    缠论:     {result['chan_signal']}  {result['chan_detail']}")
    print(f"    双龙:     {result['dragon_signal']}  {result['dragon_detail']}")
    print(f"    趋势:     {result['chan_trend']}")

    valid_final = {'HOLD', 'BUY', 'STRONG_BUY', 'SELL',
                   'BUY_WATCH', 'WAIT_CONFIRM'}
    assert result['final_signal'] in valid_final, \
        f"未知信号: {result['final_signal']}"
    assert 0 <= result['confidence'] <= 1.0
    print("    ✅ SignalEngine 测试通过")

    # ================================================================ #
    #  4. analyze_stock 便捷函数                                         #
    # ================================================================ #
    section("4. analyze_stock 便捷函数")
    from strategy.signal_engine import analyze_stock

    stock_result = analyze_stock("600519.SH#E", "20250901", "20260322")

    print(f"    股票:   {stock_result.get('symbol')}")
    print(f"    时间:   {stock_result.get('datetime')}")
    print(f"    收盘价: {stock_result.get('close')}")
    print(f"    K线数:  {stock_result.get('bar_count')}")
    print(f"    信号:   {stock_result.get('final_signal')}")
    print(f"    原因:   {stock_result.get('reason')}")

    assert 'error' not in stock_result, \
        f"analyze_stock 出错: {stock_result}"
    assert stock_result['bar_count'] > 100
    print("    ✅ analyze_stock 测试通过")

    # ================================================================ #
    #  总结                                                             #
    # ================================================================ #
    print("\n" + "=" * 60)
    print("  [OK] Step 3 ALL CHECKS PASSED — 策略模块全部验证通过")
    print("=" * 60)
    print()
    print("  产出物:")
    print("    strategy/chan_signals.py   — 缠论买卖点信号模块")
    print("    strategy/dragon_signals.py — 双龙战法信号模块")
    print("    strategy/signal_engine.py  — 信号融合引擎")


if __name__ == "__main__":
    main()
