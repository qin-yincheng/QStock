"""
基于 czsc 内置信号 + 笔结构分析的缠论买卖点信号模块 v3（第七阶段优化版）

v3 优化：
  - 新增 4 个买卖信号：一卖、五笔形态、双中枢、趋势跟随
  - 新增 3 个过滤器：MACD 强弱、MACD 方向、均线系统
  - 替换 tas_macd_bc_V221201（几乎不触发）→ tas_macd_bc_V230803
  - 背驰阈值从 0.8 放宽至 0.9（更早捕捉背驰）
  - 基于过滤器进行信号强度升降级
"""

from czsc import CZSC, RawBar, Direction
from typing import List, Optional, Tuple, Dict
import czsc.signals as sigs


class ChanSignalGenerator:
    """缠论买卖点信号生成器 v3"""

    _SIGNAL_PRIORITY = {
        "BUY_1": 5, "SELL_1": 5,
        "BUY_2": 4, "SELL_2": 4,
        "BUY_3": 3, "SELL_3": 3,
        "BUY_5BI": 3, "SELL_5BI": 3,
        "BUY_DZS": 3, "SELL_DZS": 3,
        "BUY_TREND": 2, "SELL_TREND": 2,
        "BUY_DIV": 2, "SELL_DIV": 2,
        "HOLD": 0,
    }

    def __init__(self, bars: List[RawBar]):
        self.czsc = CZSC(bars)

    def update(self, bar: RawBar):
        self.czsc.update(bar)

    def analyze(self) -> dict:
        """生成当前缠论信号（含过滤器增强）"""
        c = self.czsc
        result = {
            "signal": "HOLD",
            "detail": "无明确信号",
            "trend": "unknown",
            "fx_count": len(c.fx_list),
            "bi_count": len(c.bi_list),
            "last_bi_direction": None,
            "filters": {},
        }

        if len(c.bi_list) < 3:
            result["detail"] = f"笔数量不足({len(c.bi_list)}笔)，等待更多数据"
            return result

        result["last_bi_direction"] = c.bi_list[-1].direction.value
        result["trend"] = self._analyze_trend()

        filters = self._get_filters()
        result["filters"] = filters

        signal, detail = self._check_czsc_signals()

        if signal == "HOLD" and len(c.bi_list) >= 5:
            signal, detail = self._manual_analysis()

        signal = self._apply_filter_adjustment(signal, filters)
        result["signal"] = signal
        result["detail"] = detail
        return result

    # ------------------------------------------------------------------ #
    #  czsc 内置信号检测（扩展版）                                          #
    # ------------------------------------------------------------------ #

    def _check_czsc_signals(self) -> Tuple[str, str]:
        c = self.czsc
        candidates: List[Tuple[int, str, str]] = []

        signal_checks = [
            ("BUY_1",        5, sigs.cxt_first_buy_V221126,  {"di": 1}),
            ("SELL_1",       5, sigs.cxt_first_sell_V221126,  {"di": 1}),
            ("BUY_2/SELL_2", 4, sigs.cxt_second_bs_V230320,  {"di": 1}),
            ("BUY_3",        3, sigs.cxt_third_buy_V230228,   {"di": 1}),
            ("FIVE_BI",      3, sigs.cxt_five_bi_V230619,     {"di": 1}),
            ("DOUBLE_ZS",    3, sigs.cxt_double_zs_V230311,   {"di": 1}),
            ("TREND_BS",     2, sigs.cxt_bs_V240526,          {}),
            ("MACD_BC",      2, sigs.tas_macd_bc_V230803,     {}),
        ]

        if hasattr(sigs, "cxt_third_bs_V230318"):
            signal_checks.append(
                ("BUY_3/SELL_3", 3, sigs.cxt_third_bs_V230318, {"di": 1})
            )

        for tag, priority, fn, kwargs in signal_checks:
            try:
                res = fn(c, **kwargs)
            except Exception:
                continue

            for _k, v in res.items():
                v_str = str(v)
                if v_str.startswith("其他") or "其他" in v_str:
                    continue

                if tag == "BUY_1":
                    candidates.append((priority, "BUY_1", f"一类买点: {v_str}"))

                elif tag == "SELL_1":
                    if "卖" in v_str or "SELL" in v_str.upper():
                        candidates.append((priority, "SELL_1", f"一类卖点: {v_str}"))

                elif tag == "BUY_2/SELL_2":
                    if "卖" in v_str:
                        candidates.append((priority, "SELL_2", f"二类卖点: {v_str}"))
                    else:
                        candidates.append((priority, "BUY_2", f"二类买点: {v_str}"))

                elif tag == "BUY_3":
                    candidates.append((priority, "BUY_3", f"三类买点: {v_str}"))

                elif tag == "BUY_3/SELL_3":
                    if "卖" in v_str:
                        candidates.append((priority, "SELL_3", f"三类卖点: {v_str}"))
                    else:
                        candidates.append((priority, "BUY_3", f"三类买点: {v_str}"))

                elif tag == "FIVE_BI":
                    if any(kw in v_str for kw in ("类三买", "底背驰", "aAb式底背驰", "上颈线突破")):
                        candidates.append((priority, "BUY_5BI", f"五笔买点: {v_str}"))
                    elif any(kw in v_str for kw in ("类三卖", "顶背驰", "下颈线突破")):
                        candidates.append((priority, "SELL_5BI", f"五笔卖点: {v_str}"))

                elif tag == "DOUBLE_ZS":
                    if "看多" in v_str or "多" in v_str:
                        candidates.append((priority, "BUY_DZS", f"双中枢看多: {v_str}"))
                    elif "看空" in v_str or "空" in v_str:
                        candidates.append((priority, "SELL_DZS", f"双中枢看空: {v_str}"))

                elif tag == "TREND_BS":
                    if "买" in v_str:
                        candidates.append((priority, "BUY_TREND", f"趋势跟随买: {v_str}"))
                    elif "卖" in v_str:
                        candidates.append((priority, "SELL_TREND", f"趋势跟随卖: {v_str}"))

                elif tag == "MACD_BC":
                    if "多头" in v_str or "底" in v_str:
                        candidates.append((priority, "BUY_DIV", f"MACD底背驰: {v_str}"))
                    elif "空头" in v_str or "顶" in v_str:
                        candidates.append((priority, "SELL_DIV", f"MACD顶背驰: {v_str}"))

        if not candidates:
            return ("HOLD", "")

        candidates.sort(key=lambda x: x[0], reverse=True)
        return (candidates[0][1], candidates[0][2])

    # ------------------------------------------------------------------ #
    #  过滤器：不产生独立信号，用于调整信号强度                                  #
    # ------------------------------------------------------------------ #

    def _get_filters(self) -> Dict[str, str]:
        """获取 MACD 强弱 / MACD 方向 / 均线系统 三个过滤器状态"""
        c = self.czsc
        filters: Dict[str, str] = {
            "macd_power": "unknown",
            "macd_direction": "unknown",
            "ma_system": "unknown",
        }

        filter_checks = [
            ("macd_power",     sigs.tas_macd_power_V221108,  {"di": 1}),
            ("macd_direction", sigs.tas_macd_direct_V221106,  {"di": 1}),
            ("ma_system",      sigs.tas_ma_system_V230513,    {"di": 1, "ma_seq": "5#10#20"}),
        ]

        for name, fn, kwargs in filter_checks:
            try:
                res = fn(c, **kwargs)
                for _k, v in res.items():
                    v_str = str(v)
                    if not v_str.startswith("其他"):
                        filters[name] = v_str
                        break
            except Exception:
                pass

        return filters

    def _apply_filter_adjustment(self, signal: str, filters: Dict[str, str]) -> str:
        """根据过滤器调整信号强度"""
        if signal == "HOLD":
            return signal

        macd_pwr = filters.get("macd_power", "")
        ma_sys = filters.get("ma_system", "")

        if signal.startswith("BUY"):
            if "超弱" in macd_pwr:
                return "HOLD"
            if "超强" in macd_pwr and "多头" in ma_sys:
                if signal in ("BUY_2", "BUY_3", "BUY_5BI", "BUY_DZS", "BUY_TREND"):
                    return "BUY_1"

        if signal.startswith("SELL"):
            if "超强" in macd_pwr and "多头" in ma_sys:
                if signal in ("SELL_DIV",):
                    return "HOLD"

        return signal

    # ------------------------------------------------------------------ #
    #  笔结构手动分析（降级方案）— 背驰阈值放宽至 0.9                          #
    # ------------------------------------------------------------------ #

    def _manual_analysis(self) -> Tuple[str, str]:
        bis = self.czsc.bi_list

        zhongshu = self._find_zhongshu(bis[-7:])
        if zhongshu:
            sig, det = self._check_third_buy_sell(bis, zhongshu)
            if sig != "HOLD":
                return sig, det

        sig, det = self._check_second_buy_sell(bis)
        if sig != "HOLD":
            return sig, det

        sig, det = self._check_divergence(bis)
        if sig != "HOLD":
            return sig, det

        return ("HOLD", "笔结构分析无明确信号")

    def _find_zhongshu(self, bis) -> Optional[Tuple[float, float]]:
        if len(bis) < 3:
            return None
        for i in range(len(bis) - 2):
            three = bis[i : i + 3]
            zg = min(bi.high for bi in three)
            zd = max(bi.low for bi in three)
            if zg > zd:
                return (zg, zd)
        return None

    def _check_third_buy_sell(self, bi_list, zhongshu) -> Tuple[str, str]:
        zg, zd = zhongshu
        if len(bi_list) < 3:
            return ("HOLD", "")

        last = bi_list[-1]
        prev = bi_list[-2]

        if last.direction == Direction.Down and last.low > zg and prev.high > zg:
            return (
                "BUY_3",
                f"三类买点: 回踩不破中枢上沿 ZG={zg:.2f}, 低点={last.low:.2f}",
            )

        if last.direction == Direction.Up and last.high < zd and prev.low < zd:
            return (
                "SELL_3",
                f"三类卖点: 反弹不破中枢下沿 ZD={zd:.2f}, 高点={last.high:.2f}",
            )

        return ("HOLD", "")

    def _check_second_buy_sell(self, bi_list) -> Tuple[str, str]:
        if len(bi_list) < 4:
            return ("HOLD", "")

        last, prev, prev2, prev3 = (bi_list[-1], bi_list[-2], bi_list[-3], bi_list[-4])

        if (
            last.direction == Direction.Up
            and prev.direction == Direction.Down
            and prev.low > prev3.low
            and prev2.direction == Direction.Up
        ):
            return ("BUY_2", f"二类买点: 回调低点{prev.low:.2f} > 前低{prev3.low:.2f}")

        if (
            last.direction == Direction.Down
            and prev.direction == Direction.Up
            and prev.high < prev3.high
            and prev2.direction == Direction.Down
        ):
            return (
                "SELL_2",
                f"二类卖点: 反弹高点{prev.high:.2f} < 前高{prev3.high:.2f}",
            )

        return ("HOLD", "")

    def _check_divergence(self, bi_list) -> Tuple[str, str]:
        if len(bi_list) < 4:
            return ("HOLD", "")

        last = bi_list[-1]
        same_dir = [bi for bi in bi_list[-5:] if bi.direction == last.direction]
        if len(same_dir) < 2:
            return ("HOLD", "")

        bi_new, bi_old = same_dir[-1], same_dir[-2]
        amp_new = abs(bi_new.fx_b.fx - bi_new.fx_a.fx)
        amp_old = abs(bi_old.fx_b.fx - bi_old.fx_a.fx)

        if amp_old == 0:
            return ("HOLD", "")

        if (
            last.direction == Direction.Up
            and bi_new.high > bi_old.high
            and amp_new < amp_old * 0.9
        ):
            return (
                "SELL_DIV",
                f"上涨背驰: 新笔幅度{amp_new:.2f} < 前笔{amp_old:.2f}×0.9",
            )

        if (
            last.direction == Direction.Down
            and bi_new.low < bi_old.low
            and amp_new < amp_old * 0.9
        ):
            return (
                "BUY_DIV",
                f"下跌背驰: 新笔幅度{amp_new:.2f} < 前笔{amp_old:.2f}×0.9",
            )

        return ("HOLD", "")

    # ------------------------------------------------------------------ #
    #  趋势分析                                                            #
    # ------------------------------------------------------------------ #

    def _analyze_trend(self) -> str:
        bis = self.czsc.bi_list
        if len(bis) < 3:
            return "unknown"

        recent = bis[-3:]
        highs = [bi.high for bi in recent]
        lows = [bi.low for bi in recent]

        if highs[-1] > highs[0] and lows[-1] > lows[0]:
            return "up"
        if highs[-1] < highs[0] and lows[-1] < lows[0]:
            return "down"
        return "sideways"
