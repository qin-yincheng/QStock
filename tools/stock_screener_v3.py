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

CHAN_SIGNAL_CN = {
    "SELL_1": "一类卖点", "SELL_2": "二类卖点", "SELL_3": "三类卖点",
    "SELL_5BI": "五笔卖点", "SELL_DZS": "双中枢看空",
    "SELL_TREND": "趋势跟随卖点", "SELL_DIV": "顶背驰",
    "BUY_1": "一类买点", "BUY_2": "二类买点", "BUY_3": "三类买点",
    "BUY_5BI": "五笔买点", "BUY_DZS": "双中枢看多",
    "BUY_TREND": "趋势跟随买点", "BUY_DIV": "底背驰",
}

TREND_CN = {"up": "上升趋势", "down": "下降趋势", "sideways": "横盘震荡"}

SIGNAL_CN = {
    "STRONG_BUY": "强烈买入", "BUY": "买入", "BUY_EARLY": "早期买入",
    "BUY_WATCH": "观察", "WAIT_CONFIRM": "等待确认",
    "SELL_ALL": "卖出(全)", "SELL": "卖出", "REDUCE": "减仓", "HOLD": "持仓等待",
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

    def compute_atr14(self, bars: list, length: int = 14) -> float:
        """计算最新 ATR14 值"""
        if len(bars) < length + 1:
            return 0.0
        highs = pd.Series([b.high for b in bars])
        lows = pd.Series([b.low for b in bars])
        closes = pd.Series([b.close for b in bars])
        atr_s = ta.atr(highs, lows, closes, length=length)
        if atr_s is None or atr_s.dropna().empty:
            return 0.0
        return float(atr_s.dropna().iloc[-1])

    def compute_operation_params(self, price: float, atr: float) -> dict:
        """基于 v8 策略参数计算止损/止盈操作价位"""
        if atr <= 0 or price <= 0:
            return {}
        atr_stop_dist = 2.0 * atr / price
        atr_stop_dist = max(atr_stop_dist, 0.03)
        atr_stop_dist = min(atr_stop_dist, 0.08)

        stop_loss_price = round(price * (1 - atr_stop_dist), 2)
        stop_loss_pct = round(-atr_stop_dist * 100, 1)

        tp_activate_dist = 1.5 * atr / price
        tp_activate_price = round(price * (1 + tp_activate_dist), 2)
        tp_trail_note = f"最高价回撤 1.0×ATR 卖出"

        time_stop_bars = 40
        bars_per_day = {"F15": 16, "F30": 8, "F60": 4}.get(
            str(self.freq).split(".")[-1], 8
        )
        time_stop_days = round(time_stop_bars / bars_per_day, 1)

        return {
            "atr14": round(atr, 2),
            "stop_loss_price": stop_loss_price,
            "stop_loss_pct": stop_loss_pct,
            "tp_activate_price": tp_activate_price,
            "tp_activate_pct": round(tp_activate_dist * 100, 1),
            "tp_trail_note": tp_trail_note,
            "time_stop_bars": time_stop_bars,
            "time_stop_days": time_stop_days,
        }

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

    def _build_readable_reason(self, r: dict) -> str:
        """从结果字段生成人类可读的淘汰/分级原因"""
        reason = r.get("reason", "")
        if "弱势" in reason or "数据不足" in reason or "错误" in reason:
            return reason

        signal = r.get("signal", "HOLD")
        trend = r.get("trend", "unknown")
        chan_signal = r.get("chan_signal", "")

        trend_cn = TREND_CN.get(trend, "趋势不明")
        chan_cn = CHAN_SIGNAL_CN.get(chan_signal, "")

        if signal == "SELL_ALL":
            sell_label = chan_cn or "缠论卖点"
            if trend == "up":
                return f"{sell_label}抵消上升趋势"
            elif trend == "sideways":
                return f"横盘震荡 + {sell_label}"
            else:
                return f"下降趋势 + {sell_label}"
        elif signal == "REDUCE":
            return f"双龙死叉减仓 + {trend_cn}"
        elif signal == "HOLD":
            if trend == "down":
                return "下降趋势 + 无买入信号"
            elif trend == "sideways":
                return "横盘震荡 + 无买入信号"
            return "无明确信号"
        elif signal in ("WAIT_CONFIRM", "BUY_WATCH", "BUY_EARLY"):
            sig_cn = SIGNAL_CN.get(signal, signal)
            return f"{trend_cn} + 信号较弱({sig_cn})"
        return f"{trend_cn} + 得分不足"

    def screen(self, symbol: str, name: str = "") -> dict:
        """筛选单只股票，附带详细操作参数"""
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
            "chan_detail": "",
            "dragon_detail": "",
            "reason": "",
            "data_source": "historical",
            "op_params": {},
            "ema5": None,
            "ema10": None,
            "dif": None,
            "dea": None,
            "bi_count": 0,
            "last_bi_direction": None,
            "filters": {},
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

            # 3) 融合信号（保留完整详情）
            sig_result = self.analyze_signal(bars)
            signal = sig_result.get("final_signal", "HOLD")
            result["signal"] = signal
            result["confidence"] = sig_result.get("confidence", 0.0)
            result["chan_signal"] = sig_result.get("chan_signal", "")
            result["dragon_signal"] = sig_result.get("dragon_signal", "")
            result["chan_detail"] = sig_result.get("chan_detail", "")
            result["dragon_detail"] = sig_result.get("dragon_detail", "")
            result["data_source"] = sig_result.get("data_source", "historical")
            result["ema5"] = sig_result.get("ema5")
            result["ema10"] = sig_result.get("ema10")
            result["dif"] = sig_result.get("dif")
            result["dea"] = sig_result.get("dea")
            result["bi_count"] = sig_result.get("bi_count", 0)
            result["last_bi_direction"] = sig_result.get("last_bi_direction")
            result["filters"] = sig_result.get("filters", {})

            # 4) 波动率适配
            vol_score, atr_ratio = self.compute_volatility_score(bars)
            result["volatility_score"] = vol_score
            result["atr_ratio"] = round(atr_ratio * 100, 2)

            # 5) ATR 及操作参数
            atr14 = self.compute_atr14(bars)
            price = bars[-1].close
            op_params = self.compute_operation_params(price, atr14)
            result["op_params"] = op_params

            # 6) 综合评分
            adx_score = self._score_adx(avg_adx)
            trend_score = self._score_trend(trend)
            signal_score = self._score_signal(signal)
            total = adx_score + trend_score + signal_score + vol_score
            total = max(total, 0)

            result["score"] = total
            result["grade"] = self._grade(total)

            # 仓位映射
            result["position_size"] = POSITION_MAP.get(signal, 0.0)

            # 理由（评分明细 + 可读原因）
            parts = []
            parts.append(f"ADX={avg_adx:.1f}({adx_score}分)")
            parts.append(f"趋势={trend}({trend_score}分)")
            parts.append(f"信号={signal}({signal_score}分)")
            parts.append(f"波动率={atr_ratio*100:.1f}%({vol_score}分)")
            result["reason"] = " | ".join(parts)
            result["readable_reason"] = self._build_readable_reason(result)

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
                readable = result.get("readable_reason", result["reason"][:50])
                print(f"   淘汰 ({score}分) {readable}")

            if i < len(pool):
                time.sleep(sleep_sec)

        results.sort(key=lambda x: (-x["score"], x["name"]))
        return results

    def generate_report(self, results: list, holdings: dict = None) -> str:
        """生成 Markdown 格式的筛选报告（含操作参数和持仓建议）"""
        holdings = holdings or {}
        recommended = [r for r in results if r["grade"] == "推荐"]
        watching = [r for r in results if r["grade"] == "关注"]
        eliminated = [r for r in results if r["grade"] == "淘汰"]

        lines = [
            "# QStock 扫描报告 v5",
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
            lines.append("## 📈 推荐交易")
            lines.append("")
            for i, r in enumerate(recommended, 1):
                sig_dt = r.get("latest_dt", "")
                op = r.get("op_params", {})
                price = r.get("latest_price", 0)
                lines.append(f"### {i}. {r['name']} ({r['symbol']}) — {r['signal']}")
                lines.append("")
                lines.append(f"| 指标 | 值 |")
                lines.append(f"|------|------|")
                lines.append(f"| 得分 | **{r['score']}** |")
                lines.append(f"| ADX | {r['avg_adx']} |")
                lines.append(f"| 趋势 | {r['trend']} |")
                lines.append(f"| 融合信号 | {r['signal']} (置信度 {r['confidence']:.0%}) |")
                lines.append(f"| 建议仓位 | {r['position_size']:.0%} |")
                lines.append(f"| 缠论 | {r['chan_signal']} |")
                lines.append(f"| 双龙 | {r['dragon_signal']} |")
                lines.append(f"| 波动率 | {r['atr_ratio']}% |")
                lines.append(f"| 信号时间 | {sig_dt} |")
                lines.append("")
                chan_detail = r.get("chan_detail", "")
                if chan_detail:
                    lines.append(f"**缠论结构**：{chan_detail}")
                    lines.append("")
                dragon_detail = r.get("dragon_detail", "")
                if dragon_detail:
                    lines.append(f"**双龙状态**：{dragon_detail}")
                    lines.append("")
                if op and op.get("atr14"):
                    lines.append("**操作参数（v8 策略）**：")
                    lines.append("")
                    lines.append(f"| 参数 | 值 |")
                    lines.append(f"|------|------|")
                    lines.append(f"| 当前价 | {price:.2f} |")
                    lines.append(f"| ATR(14) | {op['atr14']} |")
                    lines.append(f"| 止损价 | {op['stop_loss_price']} ({op['stop_loss_pct']}%) |")
                    lines.append(f"| 止盈激活 | {op['tp_activate_price']} (+{op['tp_activate_pct']}%) |")
                    lines.append(f"| 止盈回撤 | {op['tp_trail_note']} |")
                    lines.append(f"| 时间止损 | {op['time_stop_bars']}根K线 (约{op['time_stop_days']}天) |")
                    lines.append("")
                holding = holdings.get(r["symbol"], {})
                if holding and holding.get("buy_price"):
                    bp = holding["buy_price"]
                    pnl = (price - bp) / bp * 100 if bp > 0 else 0
                    lines.append(f"**已持仓**：买入价 {bp}，浮盈 {pnl:+.1f}%")
                else:
                    if op and op.get("stop_loss_price"):
                        lines.append(f"**未持仓**：可在 {price:.2f} 附近建仓 {r['position_size']:.0%}，严格止损 {op['stop_loss_price']}")
                lines.append("")

        if watching:
            lines.append("## 👀 关注观察")
            lines.append("")
            for i, r in enumerate(watching, 1):
                sig_dt = r.get("latest_dt", "")
                op = r.get("op_params", {})
                price = r.get("latest_price", 0)
                lines.append(f"### {i}. {r['name']} ({r['symbol']}) — {r['signal']}")
                lines.append("")
                lines.append(f"得分 {r['score']} | ADX {r['avg_adx']} | 趋势 {r['trend']} | 信号时间 {sig_dt}")
                lines.append("")
                chan_detail = r.get("chan_detail", "")
                if chan_detail:
                    lines.append(f"缠论结构：{chan_detail}")
                    lines.append("")
                holding = holdings.get(r["symbol"], {})
                if holding and holding.get("buy_price"):
                    bp = holding["buy_price"]
                    pnl = (price - bp) / bp * 100 if bp > 0 else 0
                    if r["signal"] in ("SELL_ALL", "SELL", "REDUCE"):
                        lines.append(f"⚠️ **已持仓**（买入价 {bp}，浮盈 {pnl:+.1f}%）→ 建议执行卖出信号")
                    else:
                        lines.append(f"已持仓（买入价 {bp}，浮盈 {pnl:+.1f}%）→ 继续持有观察")
                else:
                    if r["signal"] in ("SELL_ALL", "SELL", "REDUCE"):
                        lines.append("未持仓 → 不操作，等待买入机会")
                    else:
                        lines.append("未持仓 → 继续观察，等待信号明确")
                lines.append("")

        if eliminated:
            lines.append(f"## ❌ 淘汰（{len(eliminated)} 只）")
            lines.append("")
            for i, r in enumerate(eliminated, 1):
                sig_cn = SIGNAL_CN.get(r["signal"], r["signal"])
                readable = r.get("readable_reason", r["reason"][:60])
                lines.append(f"### {i}. {r['name']} ({r['symbol']}) — {sig_cn}")
                lines.append("")
                lines.append(
                    f"得分 {r['score']} | ADX {r['avg_adx']} | "
                    f"趋势 {r['trend']} | **淘汰原因：{readable}**"
                )
                lines.append("")
                chan_detail = r.get("chan_detail", "")
                if chan_detail:
                    lines.append(f"缠论结构：{chan_detail}")
                    lines.append("")
                dragon_detail = r.get("dragon_detail", "")
                if dragon_detail:
                    lines.append(f"双龙状态：{dragon_detail}")
                    lines.append("")
                elif r.get("ema5") is not None and r.get("ema10") is not None:
                    ema5, ema10 = r["ema5"], r["ema10"]
                    dif, dea = r.get("dif"), r.get("dea")
                    ema_st = "多头" if ema5 > ema10 else "空头"
                    macd_st = "多头" if (dif and dea and dif > dea) else "空头"
                    lines.append(
                        f"双龙状态：EMA5={ema5} {'>' if ema5 > ema10 else '<'} "
                        f"EMA10={ema10} ({ema_st}), "
                        f"DIF {'>' if dif and dea and dif > dea else '<'} DEA ({macd_st})"
                    )
                    lines.append("")
                holding = holdings.get(r["symbol"], {})
                if holding and holding.get("buy_price"):
                    bp = holding["buy_price"]
                    price = r.get("latest_price", 0)
                    pnl = (price - bp) / bp * 100 if bp > 0 else 0
                    if r["signal"] in ("SELL_ALL", "SELL", "REDUCE"):
                        lines.append(
                            f"⚠️ **已持仓**（买入价 {bp}，浮盈 {pnl:+.1f}%）"
                            f"→ 建议执行卖出信号"
                        )
                    else:
                        lines.append(
                            f"已持仓（买入价 {bp}，浮盈 {pnl:+.1f}%）"
                            f"→ 建议关注风险"
                        )
                else:
                    if r["signal"] in ("SELL_ALL", "SELL", "REDUCE"):
                        lines.append("未持仓 → 不操作，等待后续回调企稳后的买入机会")
                    else:
                        lines.append("未持仓 → 不操作，条件不足暂不关注")
                lines.append("")

        lines.extend([
            "---",
            "",
            "**策略说明**：",
            "- 使用缠论+双龙融合策略（fused, v8 参数）",
            "- ATR自适应止损：2.0×ATR（下限-3%，上限-8%）",
            "- 移动止盈：1.5×ATR激活，1.0×ATR回撤卖出",
            "- 时间止损：持仓超过40根K线仍亏损则退出",
            "- 仓位按信号强度：STRONG_BUY 40% / BUY 30% / BUY_EARLY 20%",
            "- ADX < 20 的弱势股自动淘汰",
            "",
            "*⚠️ 免责声明：扫描结果仅供参考，不构成投资建议。A股T+1制度，买入当天不能卖出。*",
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
