"""Step 1.3 -- 验证 czsc 60分钟数据通路（通过 data_provider 修复 freq bug）"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Windows 控制台编码兼容
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import czsc
from czsc import Freq

TUSHARE_TOKEN = "810cafd073d3dafa10a68b9fecfb61c291e65e63cfad68503d3b10cf"
czsc.set_url_token(token=TUSHARE_TOKEN, url="http://api.tushare.pro")

from core.data_provider import get_raw_bars


def test_60min():
    print("=" * 60)
    print("  Step 1.3: 通过 data_provider 获取60分钟 RawBar")
    print("=" * 60)

    bars = get_raw_bars(
        symbol="600519.SH#E",
        freq=Freq.F60,
        sdt="20250901",
        edt="20260319",
        fq="前复权",
    )

    if not bars:
        print("[FAIL] 未获取到数据")
        return False

    print(f"[OK] 获取到 {len(bars)} 条60分钟 RawBar")
    print(f"时间范围: {bars[0].dt} ~ {bars[-1].dt}")
    print(f"最后一根: open={bars[-1].open}, close={bars[-1].close}, "
          f"high={bars[-1].high}, low={bars[-1].low}")

    print(f"\n--- 数据格式验证 ---")
    print(f"  symbol : {bars[0].symbol}")
    print(f"  freq   : {bars[0].freq}")
    print(f"  类型   : {type(bars[0]).__name__}")
    print(f"  dt类型 : {type(bars[0].dt).__name__}")

    errors = []
    if len(bars) < 100:
        errors.append(f"数据量偏少({len(bars)}条, 半年预期约500条)")
    for bar in bars[-5:]:
        if bar.high < bar.low:
            errors.append(f"K线异常: high({bar.high}) < low({bar.low}) @ {bar.dt}")
        if bar.close <= 0:
            errors.append(f"价格异常: close={bar.close} @ {bar.dt}")

    if errors:
        print(f"\n[WARN] 发现 {len(errors)} 个问题:")
        for e in errors:
            print(f"  - {e}")
    else:
        print(f"\n[OK] 数据质量检查通过")

    return len(errors) == 0


def test_daily():
    print("\n" + "=" * 60)
    print("  对照测试: 通过 data_provider 获取日线 RawBar")
    print("=" * 60)

    bars = get_raw_bars(
        symbol="600519.SH#E",
        freq=Freq.D,
        sdt="20260101",
        edt="20260319",
        fq="前复权",
    )

    if not bars:
        print("[FAIL] 日线数据获取失败")
        return False

    print(f"[OK] 日线: {len(bars)} 条 RawBar")
    print(f"最后一根: dt={bars[-1].dt}, close={bars[-1].close}")
    return True


if __name__ == "__main__":
    ok_60 = test_60min()
    ok_d = test_daily()

    print("\n" + "=" * 60)
    print("  验证总结")
    print("=" * 60)
    if ok_60 and ok_d:
        print("[PASS] 全部通过! 数据通路已打通, 可进入第二阶段")
    elif ok_60:
        print("[WARN] 60分钟通过, 日线有问题(需排查)")
    elif ok_d:
        print("[WARN] 日线通过, 60分钟有问题(需排查)")
    else:
        print("[FAIL] 均失败, 需进一步排查")
