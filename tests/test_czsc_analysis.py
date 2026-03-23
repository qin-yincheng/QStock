"""
Step 2.2 - czsc chan theory analysis validation
Run CZSC object on real 60-min K-line data, verify fractal/bi/zhongshu recognition.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from czsc import CZSC, Freq, Direction
from czsc.py.objects import Mark
from core.data_provider import get_raw_bars


def find_zhongshu(bi_list):
    """Identify zhongshu (pivots) from bi list, return list of (ZG, ZD)."""
    result = []
    if len(bi_list) < 3:
        return result
    for i in range(len(bi_list) - 2):
        three = bi_list[i:i + 3]
        zg = min(bi.high for bi in three)
        zd = max(bi.low for bi in three)
        if zg > zd:
            result.append((zg, zd))
    return result


def main():
    print("=" * 60)
    print("Step 2.2 - czsc chan theory analysis validation")
    print("=" * 60)

    # 1. Get data
    print("\n[1] Fetching 600519.SH 60min K-line data...")
    bars = get_raw_bars("600519.SH#E", Freq.F60, "20250901", "20260319")
    print("    bars count:", len(bars))
    if bars:
        print("    time range:", bars[0].dt, "~", bars[-1].dt)
        print("    first bar: open=", bars[0].open, "close=", bars[0].close)

    assert len(bars) > 100, "Too few bars, check data provider."

    # 2. Build CZSC object
    print("\n[2] Building CZSC object...")
    c = CZSC(bars)
    print("    bars_raw :", len(c.bars_raw))
    print("    bars_ubi :", len(c.bars_ubi))
    print("    fx_list  :", len(c.fx_list), "fractals")
    print("    bi_list  :", len(c.bi_list), "bi")

    assert len(c.fx_list) > 0, "No fractals found"
    assert len(c.bi_list) > 0, "No bi found"
    assert len(c.fx_list) >= len(c.bi_list), "fx count should be >= bi count"
    print("    [OK] Basic structure validation passed")

    # 3. Recent 5 fractals
    print("\n[3] Recent 5 fractals:")
    for fx in c.fx_list[-5:]:
        fx_type = "Top(D)" if fx.mark == Mark.D else "Bottom(G)"
        print("   ", fx_type, str(fx.dt), "fx=", round(fx.fx, 2),
              "high=", round(fx.high, 2), "low=", round(fx.low, 2))

    # 4. Recent 5 bi
    print("\n[4] Recent 5 bi:")
    prev_dir = None
    for bi in c.bi_list[-5:]:
        direction = "Up" if bi.direction == Direction.Up else "Down"
        amplitude = abs(bi.fx_b.fx - bi.fx_a.fx)
        print("   ", direction, str(bi.fx_a.dt), "->", str(bi.fx_b.dt),
              "low=", round(bi.low, 2), "high=", round(bi.high, 2),
              "amp=", round(amplitude, 2))
        if prev_dir is not None:
            assert prev_dir != bi.direction, "Adjacent bi have same direction - data error"
        prev_dir = bi.direction
    print("    [OK] Bi direction alternation validation passed")

    # 5. Zhongshu (pivot) detection
    print("\n[5] Zhongshu (pivot) detection:")
    zhongshu_list = find_zhongshu(c.bi_list)
    print("    Total zhongshu found:", len(zhongshu_list))
    if zhongshu_list:
        print("    Recent 3 zhongshu (ZG, ZD):")
        for zg, zd in zhongshu_list[-3:]:
            print("      ZG=", round(zg, 2), " ZD=", round(zd, 2),
                  " range=", round(zg - zd, 2))
    else:
        print("    (Not enough bi to form zhongshu)")

    # 6. Trend judgment
    print("\n[6] Trend judgment (last 3 bi highs/lows):")
    if len(c.bi_list) >= 3:
        recent = c.bi_list[-3:]
        highs = [bi.high for bi in recent]
        lows = [bi.low for bi in recent]
        if highs[-1] > highs[0] and lows[-1] > lows[0]:
            print("    Highs and lows both rising -> Uptrend")
        elif highs[-1] < highs[0] and lows[-1] < lows[0]:
            print("    Highs and lows both falling -> Downtrend")
        else:
            print("    No clear direction -> Sideways")
    else:
        print("    Not enough bi (< 3) for trend judgment")

    # 7. Incremental update simulation
    print("\n[7] Incremental update test (last 10 bars simulating live feed):")
    c2 = CZSC(bars[:-10])
    bi_before = len(c2.bi_list)
    for bar in bars[-10:]:
        c2.update(bar)
    bi_after = len(c2.bi_list)
    print("    bi before:", bi_before, " bi after:", bi_after)
    print("    [OK] Incremental update completed without error")

    print("\n" + "=" * 60)
    print("[OK] Step 2.2 ALL CHECKS PASSED - czsc analysis engine working")
    print("=" * 60)


if __name__ == "__main__":
    main()
