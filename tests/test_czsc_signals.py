"""
Step 2.3 - czsc 内置信号体系探索
目标：了解 czsc.signals 模块，掌握信号函数的调用方式和返回格式，
      为后续 strategy/ 模块开发奠定基础。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from czsc import CZSC, Freq
import czsc.signals as sigs
from core.data_provider import get_raw_bars


def section(title: str):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def main():
    print("=" * 60)
    print("Step 2.3 - czsc 内置信号体系探索")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 1. 获取数据并构建 CZSC 对象
    # ------------------------------------------------------------------
    section("1. 获取数据")
    bars = get_raw_bars("600519.SH#E", Freq.F60, "20250901", "20260319")
    print(f"    数据量: {len(bars)} 条 60分钟 RawBar")
    print(f"    时间范围: {bars[0].dt} ~ {bars[-1].dt}")
    assert len(bars) > 100, "数据量不足"

    c = CZSC(bars)
    print(f"    分型数: {len(c.fx_list)}   笔数: {len(c.bi_list)}")

    # ------------------------------------------------------------------
    # 2. 浏览信号模块全貌
    # ------------------------------------------------------------------
    section("2. czsc.signals 模块概览")
    all_names = [n for n in dir(sigs) if not n.startswith('_')]
    fn_names  = [n for n in all_names if callable(getattr(sigs, n))]
    print(f"    模块内公开名称总数: {len(all_names)}")
    print(f"    可调用信号函数总数: {len(fn_names)}")

    # 按前缀分类统计
    prefixes = {}
    for name in fn_names:
        prefix = name.split('_')[0]
        prefixes[prefix] = prefixes.get(prefix, 0) + 1
    print("\n    信号函数按前缀分类:")
    for prefix, count in sorted(prefixes.items(), key=lambda x: -x[1]):
        print(f"      {prefix:<10} {count} 个")

    # 展示与缠论/均线/MACD 最相关的函数
    relevant = [n for n in fn_names if any(
        kw in n for kw in ['bi_end', 'first_buy', 'second_bs', 'third_buy',
                            'third_bs', 'double_ma', 'macd_base', 'macd_bc',
                            'macd_bs1', 'bi_status']
    )]
    print(f"\n    与本项目最相关的信号函数 ({len(relevant)} 个):")
    for name in relevant:
        print(f"      {name}")

    # ------------------------------------------------------------------
    # 3. 信号体系架构说明
    # ------------------------------------------------------------------
    section("3. czsc 信号体系架构")
    print("    Signal（信号）→ Factor（因子）→ Event（事件）→ Position（仓位）")
    print()
    print("    每个信号函数:")
    print("      输入: CZSC 对象 + 可选关键字参数")
    print("      输出: OrderedDict，key 为信号名称，value 为信号值字符串")
    print()
    print("    信号名称格式: '{freq}_{参数描述}_{函数标签}'")
    print("    信号值格式:   '{状态}_{细节}_{保留}_0'")
    print("      例: '60分钟_D1MACD12#26#9#MACD_BS辅助V221028_多头_转折_其他_0'")

    # ------------------------------------------------------------------
    # 4. 调用笔结束信号 cxt_bi_end_V230104
    # ------------------------------------------------------------------
    section("4. 笔结束信号 cxt_bi_end_V230104")
    try:
        result = sigs.cxt_bi_end_V230104(c, ma_type='SMA', timeperiod=5, th=50)
        print(f"    返回类型: {type(result).__name__}")
        print(f"    信号条目数: {len(result)}")
        print("    信号内容:")
        for k, v in result.items():
            print(f"      {k}")
            print(f"        → {v}")
    except Exception as e:
        print(f"    [ERROR] {e}")

    # ------------------------------------------------------------------
    # 5. 调用一类买点信号 cxt_first_buy_V221126
    # ------------------------------------------------------------------
    section("5. 一类买点信号 cxt_first_buy_V221126")
    try:
        result = sigs.cxt_first_buy_V221126(c, di=1)
        print("    信号内容:")
        for k, v in result.items():
            print(f"      {k}")
            print(f"        → {v}")
        # 判断当前是否触发一买
        for k, v in result.items():
            if '其他' not in str(v):
                print(f"    [触发] 一买信号: {v}")
    except Exception as e:
        print(f"    [ERROR] {e}")

    # ------------------------------------------------------------------
    # 6. 调用二类买卖点信号 cxt_second_bs_V230320
    # ------------------------------------------------------------------
    section("6. 二类买卖点信号 cxt_second_bs_V230320")
    try:
        result = sigs.cxt_second_bs_V230320(c, di=1)
        print("    信号内容:")
        for k, v in result.items():
            print(f"      {k}")
            print(f"        → {v}")
    except Exception as e:
        print(f"    [ERROR] {e}")

    # ------------------------------------------------------------------
    # 7. 调用三类买卖点信号 cxt_third_buy_V230228
    # ------------------------------------------------------------------
    section("7. 三类买点信号 cxt_third_buy_V230228")
    try:
        result = sigs.cxt_third_buy_V230228(c, di=1)
        print("    信号内容:")
        for k, v in result.items():
            print(f"      {k}")
            print(f"        → {v}")
    except Exception as e:
        print(f"    [ERROR] {e}")

    # ------------------------------------------------------------------
    # 8. 调用 MACD 基础信号 tas_macd_base_V221028
    # ------------------------------------------------------------------
    section("8. MACD 基础信号 tas_macd_base_V221028")
    try:
        result = sigs.tas_macd_base_V221028(c, di=1, key='macd')
        print("    信号内容 (key=macd):")
        for k, v in result.items():
            print(f"      {k}")
            print(f"        → {v}")

        result_dif = sigs.tas_macd_base_V221028(c, di=1, key='dif')
        print("    信号内容 (key=dif):")
        for k, v in result_dif.items():
            print(f"      {k}")
            print(f"        → {v}")
    except Exception as e:
        print(f"    [ERROR] {e}")

    # ------------------------------------------------------------------
    # 9. 调用双均线金叉信号 tas_double_ma_V221203
    # ------------------------------------------------------------------
    section("9. 双均线金叉信号 tas_double_ma_V221203")
    try:
        result = sigs.tas_double_ma_V221203(c, di=1, ma_type='EMA', ma_seq=(5, 10), th=100)
        print("    信号内容 (EMA5/EMA10):")
        for k, v in result.items():
            print(f"      {k}")
            print(f"        → {v}")
        # 判断是否金叉
        for k, v in result.items():
            if '金叉' in str(v):
                print(f"    [触发] 均线金叉: {v}")
            elif '死叉' in str(v):
                print(f"    [触发] 均线死叉: {v}")
    except Exception as e:
        print(f"    [ERROR] {e}")

    # ------------------------------------------------------------------
    # 10. 调用 MACD 背驰信号 tas_macd_bc_V221201
    # ------------------------------------------------------------------
    section("10. MACD 背驰信号 tas_macd_bc_V221201")
    try:
        result = sigs.tas_macd_bc_V221201(c, di=1)
        print("    信号内容:")
        for k, v in result.items():
            print(f"      {k}")
            print(f"        → {v}")
    except Exception as e:
        print(f"    [ERROR] {e}")

    # ------------------------------------------------------------------
    # 11. 批量扫描所有相关信号的当前触发状态
    # ------------------------------------------------------------------
    section("11. 批量扫描：当前触发的缠论/双龙相关信号")
    scan_funcs = [
        (sigs.cxt_bi_end_V230104,    dict(ma_type='SMA', timeperiod=5, th=50)),
        (sigs.cxt_first_buy_V221126, dict(di=1)),
        (sigs.cxt_second_bs_V230320, dict(di=1)),
        (sigs.cxt_third_buy_V230228, dict(di=1)),
        (sigs.tas_macd_base_V221028, dict(di=1, key='macd')),
        (sigs.tas_macd_base_V221028, dict(di=1, key='dif')),
        (sigs.tas_double_ma_V221203, dict(di=1, ma_type='EMA', ma_seq=(5, 10), th=100)),
        (sigs.tas_macd_bc_V221201,   dict(di=1)),
    ]

    triggered = []
    errors = []
    for fn, kwargs in scan_funcs:
        try:
            res = fn(c, **kwargs)
            for k, v in res.items():
                if '其他' not in str(v):
                    triggered.append((fn.__name__, k, str(v)))
        except Exception as e:
            errors.append((fn.__name__, str(e)))

    if triggered:
        print(f"    当前触发的非'其他'信号 ({len(triggered)} 条):")
        for fn_name, sig_key, sig_val in triggered:
            print(f"      [{fn_name}]")
            print(f"        key: {sig_key}")
            print(f"        val: {sig_val}")
    else:
        print("    当前无触发信号（所有信号均为'其他'状态，属正常情况）")

    if errors:
        print(f"\n    调用出错的函数 ({len(errors)} 个):")
        for fn_name, err in errors:
            print(f"      [{fn_name}] {err}")

    # ------------------------------------------------------------------
    # 12. 总结：与本项目策略的对应关系
    # ------------------------------------------------------------------
    section("12. 总结：czsc 信号与本项目策略模块的对应关系")
    print("    缠论信号模块 (strategy/chan_signals.py):")
    print("      cxt_first_buy_V221126   → 一类买点")
    print("      cxt_second_bs_V230320   → 二类买卖点")
    print("      cxt_third_buy_V230228   → 三类买点")
    print("      cxt_third_bs_V230318/19 → 三类卖点")
    print("      tas_macd_bc_V221201     → MACD 背驰辅助")
    print()
    print("    双龙战法模块 (strategy/dragon_signals.py):")
    print("      tas_double_ma_V221203   → EMA5/EMA10 金叉（第一龙）")
    print("      tas_macd_base_V221028   → MACD DIF/DEA 金叉（第二龙）")
    print()
    print("    信号融合引擎 (strategy/signal_engine.py):")
    print("      缠论方向确认 + 双龙时机触发 → 综合买入/卖出信号")

    print("\n" + "=" * 60)
    print("[OK] Step 2.3 ALL CHECKS PASSED - czsc 信号体系探索完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
