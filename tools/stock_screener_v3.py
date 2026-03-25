"""
选股工具 v3 — 基于 Step 7 全部优化成果

核心变化（vs v2）：
  1. 统一使用 fused 融合策略 + v7.2 参数（不再按 ADX 分配 chan/or/and/dragon）
  2. ADX >= 20 硬性门槛（Step 7.5 结论）
  3. 仓位按信号强度 20%-40%（v7.4 参数）
  4. 调用 SignalEngine v3 融合引擎（不再分开调 chan/dragon）
  5. 新增波动率适配度评分（趋势跟随需要适度波动）
  6. 支持实时数据（盘中自动获取新浪财经当天 K 线）
  7. 默认股票池扩展到 50 只沪深 300 成分股
"""

import sys
import os
import time
from datetime import datetime, timedelta
from typing import List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import pandas_ta as ta
from czsc import Freq

POSITION_MAP = {
    "STRONG_BUY": 0.40,
    "BUY": 0.30,
    "BUY_EARLY": 0.20,
    "BUY_WATCH": 0.20,
    "WAIT_CONFIRM": 0.15,
}

SIGNAL_SCORE = {
    "STRONG_BUY": 35,
    "BUY": 28,
    "BUY_EARLY": 18,
    "WAIT_CONFIRM": 10,
    "BUY_WATCH": 10,
    "HOLD": 0,
    "SELL_ALL": -15,
    "SELL": -15,
    "REDUCE": -10,
}

DEFAULT_POOL = [
    # --- v2 原有 24 只 ---
    ("002594.SZ#E", "比亚迪"),
    ("300750.SZ#E", "宁德时代"),
    ("600276.SH#E", "恒瑞医药"),
    ("600436.SH#E", "片仔癀"),
    ("002475.SZ#E", "立讯精密"),
    ("002371.SZ#E", "北方华创"),
    ("688981.SH#E", "中芯国际"),
    ("601899.SH#E", "紫金矿业"),
    ("601088.SH#E", "中国神华"),
    ("600519.SH#E", "贵州茅台"),
    ("000858.SZ#E", "五粮液"),
    ("000568.SZ#E", "泸州老窖"),
    ("000333.SZ#E", "美的集团"),
    ("000651.SZ#E", "格力电器"),
    ("600036.SH#E", "招商银行"),
    ("601318.SH#E", "中国平安"),
    ("601398.SH#E", "工商银行"),
    ("600030.SH#E", "中信证券"),
    ("000001.SZ#E", "平安银行"),
    ("600900.SH#E", "长江电力"),
    ("600309.SH#E", "万华化学"),
    ("601012.SH#E", "隆基绿能"),
    ("300059.SZ#E", "东方财富"),
    ("600887.SH#E", "伊利股份"),
    # --- v3 新增 26 只（覆盖更多行业） ---
    ("600585.SH#E", "海螺水泥"),     # 基建建材
    ("601668.SH#E", "中国建筑"),     # 基建
    ("600050.SH#E", "中国联通"),     # 通信运营
    ("000063.SZ#E", "中兴通讯"),     # 通信设备
    ("600941.SH#E", "中国移动"),     # 通信运营
    ("601766.SH#E", "中国中车"),     # 高端制造
    ("600031.SH#E", "三一重工"),     # 工程机械
    ("002714.SZ#E", "牧原股份"),     # 农牧
    ("300760.SZ#E", "迈瑞医疗"),     # 医药器械
    ("603259.SH#E", "药明康德"),     # 医药CXO
    ("600690.SH#E", "海尔智家"),     # 家电
    ("601888.SH#E", "中国中免"),     # 消费免税
    ("600048.SH#E", "保利发展"),     # 地产
    ("601919.SH#E", "中远海控"),     # 交运航运
    ("002230.SZ#E", "科大讯飞"),     # AI / 人工智能
    ("688036.SH#E", "传音控股"),     # 消费电子
    ("002049.SZ#E", "紫光国微"),     # 芯片设计
    ("600809.SH#E", "山西汾酒"),     # 白酒
    ("601225.SH#E", "陕西煤业"),     # 煤炭
    ("600028.SH#E", "中国石化"),     # 石化
    ("601985.SH#E", "中国核电"),     # 核电
    ("300274.SZ#E", "阳光电源"),     # 光伏
    ("002460.SZ#E", "赣锋锂业"),     # 锂电
    ("601633.SH#E", "长城汽车"),     # 汽车
    ("600406.SH#E", "国电南瑞"),     # 电力设备
    ("002032.SZ#E", "苏泊尔"),       # 小家电
]


class StockScreenerV3:
    """
    选股器 v3 — 基于 Step 7 优化成果

    筛选逻辑：
      1. ADX >= 20（硬性门槛，弱势股直接淘汰）
      2. 缠论趋势方向（up > sideways > down）
      3. SignalEngine v3 融合信号（统一 fused 策略）
      4. 波动率适配度（趋势跟随需要适度波动）
      5. 综合评分 → 推荐 / 关注 / 淘汰
    """

    def __init__(
        self,
        adx_threshold: float = 20.0,
        adx_period: int = 14,
        adx_avg_bars: int = 60,
        min_bars: int = 200,
        lookback_days: int = 365,
        realtime: bool = True,
        freq: Freq = Freq.F30,
    ):
        self.adx_threshold = adx_threshold
        self.adx_period = adx_period
        self.adx_avg_bars = adx_avg_bars
        self.min_bars = min_bars
        self.lookback_days = lookback_days
        self.realtime = realtime
        self.freq = freq

    def _get_bars(self, symbol: str) -> list:
        """获取 K 线数据，根据 realtime 标志选择数据源"""
        if self.realtime:
            from core.data_provider_realtime import get_raw_bars
            return get_raw_bars(symbol, self.freq, realtime=True)
        else:
            from core.data_provider import get_raw_bars
            edt = datetime.now().strftime("%Y%m%d")
            sdt = (datetime.now() - timedelta(days=self.lookback_days)).strftime("%Y%m%d")
            return get_raw_bars(symbol, self.freq, sdt, edt)

    def compute_adx(self, bars: list) -> float:
        """计算 ADX（最近 adx_avg_bars 根的均值）"""
        if len(bars) < self.adx_period + 10:
            return 0.0

        highs = pd.Series([b.high for b in bars])
        lows = pd.Series([b.low for b in bars])
        closes = pd.Series([b.close for b in bars])

        adx_df = ta.adx(highs, lows, closes, length=self.adx_period)
        vals = adx_df[f"ADX_{self.adx_period}"].dropna().values

        if len(vals) == 0:
            return 0.0

        n = min(self.adx_avg_bars, len(vals))
        avg = float(np.nanmean(vals[-n:]))
        return avg if not np.isnan(avg) else 0.0

    def check_trend(self, bars: list) -> str:
        """用缠论笔结构判断趋势方向"""
        from czsc import CZSC

        if len(bars) < 30:
            return "unknown"

        c = CZSC(bars)
        if len(c.bi_list) < 3:
            return "unknown"

        last3 = c.bi_list[-3:]
        if last3[-1].high > last3[0].high and last3[-1].low > last3[0].low:
            return "up"
        elif last3[-1].high < last3[0].high and last3[-1].low < last3[0].low:
            return "down"
        return "sideways"

    def compute_volatility_score(self, bars: list, window: int = 60) -> tuple:
        """
        计算波动率适配度。趋势跟随策略的最佳 ATR/Close 比率约 0.8%-2.5%。

        Returns:
            (score, atr_ratio)
        """
        if len(bars) < window + 1:
            return 8, 0.0

        recent = bars[-window:]
        highs = np.array([b.high for b in recent])
        lows = np.array([b.low for b in recent])
        closes = np.array([b.close for b in recent])

        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:] - closes[:-1]),
            ),
        )
        atr = float(np.mean(tr))
        avg_close = float(np.mean(closes))
        if avg_close == 0:
            return 5, 0.0

        atr_ratio = atr / avg_close

        if 0.008 <= atr_ratio <= 0.025:
            return 15, atr_ratio
        elif 0.005 <= atr_ratio <= 0.035:
            return 10, atr_ratio
        else:
            return 5, atr_ratio

    def analyze_signal(self, bars: list) -> dict:
        """调用 SignalEngine v3 获取融合信号"""
        from strategy.signal_engine import SignalEngine

        if len(bars) < 30:
            return {
                "final_signal": "HOLD",
                "confidence": 0.0,
                "reason": "数据不足",
                "chan_signal": "HOLD",
                "dragon_signal": "HOLD",
                "chan_trend": "unknown",
                "dragon_trend": "neutral",
            }

        engine = SignalEngine(bars)
        return engine.generate()

    def _score_adx(self, adx: float) -> int:
        if adx >= 30:
            return 25
        elif adx >= 25:
            return 18
        elif adx >= 20:
            return 10
        return 0

    def _score_trend(self, trend: str) -> int:
        return {"up": 25, "sideways": 10, "down": 0}.get(trend, 0)

    def _score_signal(self, signal: str) -> int:
        return SIGNAL_SCORE.get(signal, 0)

    def _grade(self, score: int) -> str:
        if score >= 55:
            return "推荐"
        elif score >= 40:
            return "关注"
        return "淘汰"

    def screen(self, symbol: str, name: str = "") -> dict:
        """筛选单只股票"""
        result = {
            "symbol": symbol.split("#")[0],
            "name": name,
            "grade": "淘汰",
            "score": 0,
            "avg_adx": 0.0,
            "trend": "unknown",
            "signal": "HOLD",
            "confidence": 0.0,
            "position_size": 0.0,
            "volatility_score": 0,
            "atr_ratio": 0.0,
            "chan_signal": "",
            "dragon_signal": "",
            "reason": "",
            "data_source": "historical",
        }

        try:
            bars = self._get_bars(symbol)

            if not bars or len(bars) < self.min_bars:
                result["reason"] = f"数据不足({len(bars) if bars else 0}根, 需{self.min_bars})"
                return result

            result["bar_count"] = len(bars)
            result["latest_price"] = bars[-1].close
            result["latest_dt"] = str(bars[-1].dt)

            # 1) ADX 硬性门槛
            avg_adx = self.compute_adx(bars)
            result["avg_adx"] = round(avg_adx, 1)

            if avg_adx < self.adx_threshold:
                result["reason"] = f"弱势股(ADX={avg_adx:.1f}<{self.adx_threshold})"
                return result

            # 2) 趋势方向
            trend = self.check_trend(bars)
            result["trend"] = trend

            # 3) 融合信号
            sig_result = self.analyze_signal(bars)
            signal = sig_result.get("final_signal", "HOLD")
            result["signal"] = signal
            result["confidence"] = sig_result.get("confidence", 0.0)
            result["chan_signal"] = sig_result.get("chan_signal", "")
            result["dragon_signal"] = sig_result.get("dragon_signal", "")
            result["data_source"] = sig_result.get("data_source", "historical")

            # 4) 波动率适配
            vol_score, atr_ratio = self.compute_volatility_score(bars)
            result["volatility_score"] = vol_score
            result["atr_ratio"] = round(atr_ratio * 100, 2)

            # 5) 综合评分
            adx_score = self._score_adx(avg_adx)
            trend_score = self._score_trend(trend)
            signal_score = self._score_signal(signal)
            total = adx_score + trend_score + signal_score + vol_score
            total = max(total, 0)

            result["score"] = total
            result["grade"] = self._grade(total)

            # 仓位映射
            result["position_size"] = POSITION_MAP.get(signal, 0.0)

            # 理由
            parts = []
            parts.append(f"ADX={avg_adx:.1f}({adx_score}分)")
            parts.append(f"趋势={trend}({trend_score}分)")
            parts.append(f"信号={signal}({signal_score}分)")
            parts.append(f"波动率={atr_ratio*100:.1f}%({vol_score}分)")
            result["reason"] = " | ".join(parts)

            return result

        except Exception as e:
            result["reason"] = f"错误: {str(e)[:80]}"
            return result

    def screen_pool(self, stock_pool: list = None, sleep_sec: float = 1.0) -> list:
        """批量筛选股票池"""
        pool = stock_pool or DEFAULT_POOL
        results = []

        for i, (symbol, name) in enumerate(pool, 1):
            print(f"[{i}/{len(pool)}] {name} ({symbol.split('#')[0]})...", end=" ")
            result = self.screen(symbol, name)
            results.append(result)

            grade = result["grade"]
            score = result["score"]
            if grade == "推荐":
                print(f">> 推荐 ({score}分) 信号:{result['signal']} 仓位:{result['position_size']:.0%}")
            elif grade == "关注":
                print(f"-- 关注 ({score}分) 信号:{result['signal']}")
            else:
                print(f"   淘汰 ({score}分) {result['reason'][:50]}")

            if i < len(pool):
                time.sleep(sleep_sec)

        results.sort(key=lambda x: (-x["score"], x["name"]))
        return results

    def generate_report(self, results: list) -> str:
        """生成 Markdown 格式的筛选报告"""
        recommended = [r for r in results if r["grade"] == "推荐"]
        watching = [r for r in results if r["grade"] == "关注"]
        eliminated = [r for r in results if r["grade"] == "淘汰"]

        lines = [
            "# 选股工具 v3 筛选报告",
            "",
            f"> **生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M')}  ",
            f"> **股票池**：{len(results)} 只  ",
            f"> **推荐**：{len(recommended)} 只 | **关注**：{len(watching)} 只 | **淘汰**：{len(eliminated)} 只  ",
            f"> **ADX 门槛**：{self.adx_threshold} | **策略**：fused（v8 参数）  ",
            f"> **频率级别**：{self.freq} | **数据模式**：{'实时+历史' if self.realtime else '纯历史'}  ",
            "",
            "---",
            "",
        ]

        if recommended:
            lines.append("## 推荐交易")
            lines.append("")
            lines.append("| # | 股票 | 得分 | ADX | 趋势 | 融合信号 | 仓位 | 缠论 | 双龙 | 波动率 | 信号时间 |")
            lines.append("|---|------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|------|")
            for i, r in enumerate(recommended, 1):
                sig_dt = r.get("latest_dt", "")
                lines.append(
                    f"| {i} | {r['name']} | **{r['score']}** | {r['avg_adx']} | {r['trend']} "
                    f"| {r['signal']} | {r['position_size']:.0%} "
                    f"| {r['chan_signal']} | {r['dragon_signal']} | {r['atr_ratio']}% | {sig_dt} |"
                )
            lines.append("")

        if watching:
            lines.append("## 关注观察")
            lines.append("")
            lines.append("| # | 股票 | 得分 | ADX | 趋势 | 信号 | 缠论 | 双龙 | 信号时间 |")
            lines.append("|---|------|:---:|:---:|:---:|:---:|:---:|:---:|------|")
            for i, r in enumerate(watching, 1):
                sig_dt = r.get("latest_dt", "")
                lines.append(
                    f"| {i} | {r['name']} | {r['score']} | {r['avg_adx']} | {r['trend']} "
                    f"| {r['signal']} | {r['chan_signal']} | {r['dragon_signal']} | {sig_dt} |"
                )
            lines.append("")

        if eliminated:
            lines.append("## 淘汰")
            lines.append("")
            lines.append("| 股票 | ADX | 原因 |")
            lines.append("|------|:---:|------|")
            for r in eliminated:
                lines.append(f"| {r['name']} | {r['avg_adx']} | {r['reason'][:60]} |")
            lines.append("")

        lines.extend([
            "---",
            "",
            "**策略说明**：",
            "- 使用缠论+双龙融合策略（fused, v7.2 参数）",
            "- v7.2 参数：lookback=5, 止损-5%, 启动止盈+5%, 回撤止盈3%, 时间止损40K线, 连亏限制3次",
            "- 仓位按信号强度：STRONG_BUY 40% / BUY 30% / BUY_EARLY 20%",
            "- ADX < 20 的弱势股自动淘汰",
            "",
            "*选股规则版本：v3（基于 Step 7 全部优化成果）*  ",
            "*免责声明：选股结果仅供参考，不构成投资建议。*",
        ])

        return "\n".join(lines)


def main():
    """独立运行入口"""
    print("=" * 70)
    print("  选股工具 v3 — 基于 Step 7 优化成果")
    print("=" * 70)
    print()
    print("  策略：统一 fused（缠论+双龙融合, v7.2 参数）")
    print(f"  ADX 门槛：20")
    print(f"  仓位映射：STRONG_BUY 40% / BUY 30% / BUY_EARLY 20%")
    print(f"  评分维度：ADX(25) + 趋势(25) + 融合信号(35) + 波动率(15)")
    print(f"  股票池：{len(DEFAULT_POOL)} 只沪深 300 成分股")
    print()
    print("=" * 70)
    print()

    screener = StockScreenerV3(realtime=False)
    results = screener.screen_pool()

    report = screener.generate_report(results)
    report_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "docs",
        "screener_v3_report.md",
    )
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n报告已保存: {report_path}")

    recommended = [r for r in results if r["grade"] == "推荐"]
    watching = [r for r in results if r["grade"] == "关注"]
    eliminated = [r for r in results if r["grade"] == "淘汰"]

    print()
    print("=" * 70)
    print(f"  推荐: {len(recommended)} 只 | 关注: {len(watching)} 只 | 淘汰: {len(eliminated)} 只")
    print("=" * 70)

    if recommended:
        print("\n  >> 推荐交易:")
        for r in recommended:
            print(
                f"     {r['name']:8s} ({r['symbol']}): "
                f"{r['signal']} 仓位{r['position_size']:.0%} "
                f"ADX={r['avg_adx']} 趋势={r['trend']} 得分={r['score']}"
            )

    print()
    print("  [!] 免责声明：选股结果仅供参考，不构成投资建议。")
    print("=" * 70)

    return results


if __name__ == "__main__":
    main()
