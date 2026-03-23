"""验证 Tushare 各级别数据访问权限 - Step 1.2"""

import tushare as ts

# ===== 请在此填入你的 Tushare Token =====
TUSHARE_TOKEN = (
    "810cafd073d3dafa10a68b9fecfb61c291e65e63cfad68503d3b10cf"  # <-- 修改这里
)
# =========================================

ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

# ========== 测试1: 日线数据（无积分要求） ==========
print("=" * 50)
print("测试1: 日线数据（无积分要求）")
print("=" * 50)
try:
    df_daily = pro.daily(
        ts_code="600519.SH", start_date="20260101", end_date="20260319"
    )
    print(f"✅ 日线数据: {len(df_daily)} 条")
    print(df_daily.head(3))
except Exception as e:
    print(f"❌ 日线数据获取失败: {e}")

# ========== 测试2: 60分钟K线（需要积分） ==========
print("\n" + "=" * 50)
print("测试2: 60分钟K线数据")
print("=" * 50)
MINUTE_DATA_OK = False
try:
    df_60min = ts.pro_bar(
        ts_code="600519.SH", freq="60min", start_date="20260301", end_date="20260319"
    )
    if df_60min is not None and len(df_60min) > 0:
        print(f"✅ 60分钟数据: {len(df_60min)} 条")
        print(df_60min.head(5))
        print(
            f"时间范围: {df_60min['trade_time'].min()} ~ {df_60min['trade_time'].max()}"
        )
        MINUTE_DATA_OK = True
    else:
        print("❌ 返回空数据，可能积分不够")
except Exception as e:
    print(f"❌ 60分钟数据权限不足: {e}")

# ========== 测试3: czsc 内置 ts_connector ==========
print("\n" + "=" * 50)
print("测试3: czsc ts_connector 日线数据")
print("=" * 50)
try:
    import czsc

    czsc.set_url_token(token=TUSHARE_TOKEN, url="http://api.tushare.pro")
    from czsc.connectors.ts_connector import get_raw_bars
    from czsc import Freq

    bars = get_raw_bars(
        symbol="600519.SH#E",
        freq=Freq.D,
        sdt="20260101",
        edt="20260319",
        fq="前复权",
        raw_bar=True,
    )
    print(f"✅ czsc ts_connector 日线: {len(bars)} 条 RawBar")
    print(f"最后一根: dt={bars[-1].dt}, close={bars[-1].close}")
except Exception as e:
    print(f"❌ czsc ts_connector 失败: {e}")

# ========== 测试4: czsc ts_connector 60分钟 ==========
print("\n" + "=" * 50)
print("测试4: czsc ts_connector 60分钟数据")
print("=" * 50)
try:
    from czsc.connectors.ts_connector import get_raw_bars
    from czsc import Freq

    bars_60 = get_raw_bars(
        symbol="600519.SH#E",
        freq=Freq.F60,
        sdt="20260301",
        edt="20260319",
        fq="前复权",
        raw_bar=True,
    )
    if bars_60 and len(bars_60) > 0:
        print(f"✅ czsc 60分钟数据: {len(bars_60)} 条 RawBar")
        print(f"最后一根: dt={bars_60[-1].dt}, close={bars_60[-1].close}")
        MINUTE_DATA_OK = True
    else:
        print("❌ czsc 60分钟返回空数据")
except Exception as e:
    print(f"❌ czsc 60分钟数据失败: {e}")

# ========== 总结 ==========
print("\n" + "=" * 50)
print("验证结论")
print("=" * 50)
if MINUTE_DATA_OK:
    print("🎉 方案A可行: Tushare 可获取60分钟数据")
    print("   → 全部使用 czsc 内置 ts_connector，无需 baostock/akshare")
    print("   → 下一步：修改 core/data_provider.py 中 TUSHARE_MINUTE_OK = True")
else:
    print("⚠️  需启用方案B: Tushare 无法获取分钟数据")
    print("   → 分钟数据需用 baostock(历史) + akshare(实时)")
    print("   → 建议：去 Tushare 官网提升积分（发帖、签到等可获取积分）")
    print("   → 下一步：修改 core/data_provider.py 中 TUSHARE_MINUTE_OK = False")
