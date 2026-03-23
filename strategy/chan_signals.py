"""
基于 czsc 内置信号 + 笔结构分析的缠论买卖点信号模块

信号检测策略：
1. 优先使用 czsc.signals 内置信号函数（Step 2.3 已验证）
2. 内置信号无触发时，退化为笔结构手动分析（中枢/二买卖/背驰）

信号函数来源（Step 2.3 验证通过）:
  cxt_first_buy_V221126   → 一类买点
  cxt_second_bs_V230320   → 二类买卖点
  cxt_third_buy_V230228   → 三类买点
  cxt_third_bs_V230318    → 三类买卖点
  tas_macd_bc_V221201     → MACD 背驰
"""
from czsc import CZSC, RawBar, Direction
from typing import List, Optional, Tuple
import czsc.signals as sigs


class ChanSignalGenerator:
    """缠论买卖点信号生成器"""

    _SIGNAL_PRIORITY = {
        'BUY_1': 5, 'SELL_1': 5,
        'BUY_2': 4, 'SELL_2': 4,
        'BUY_3': 3, 'SELL_3': 3,
        'BUY_DIV': 2, 'SELL_DIV': 2,
        'HOLD': 0,
    }

    def __init__(self, bars: List[RawBar]):
        self.czsc = CZSC(bars)

    def update(self, bar: RawBar):
        """逐 K 线更新（实盘用）"""
        self.czsc.update(bar)

    def analyze(self) -> dict:
        """生成当前缠论信号"""
        c = self.czsc
        result = {
            'signal': 'HOLD',
            'detail': '无明确信号',
            'trend': 'unknown',
            'fx_count': len(c.fx_list),
            'bi_count': len(c.bi_list),
            'last_bi_direction': None,
        }

        if len(c.bi_list) < 3:
            result['detail'] = f'笔数量不足({len(c.bi_list)}笔)，等待更多数据'
            return result

        result['last_bi_direction'] = c.bi_list[-1].direction.value
        result['trend'] = self._analyze_trend()

        signal, detail = self._check_czsc_signals()

        if signal == 'HOLD' and len(c.bi_list) >= 5:
            signal, detail = self._manual_analysis()

        result['signal'] = signal
        result['detail'] = detail
        return result

    # ------------------------------------------------------------------ #
    #  czsc 内置信号检测                                                    #
    # ------------------------------------------------------------------ #

    def _check_czsc_signals(self) -> Tuple[str, str]:
        """调用 czsc 内置信号函数检测买卖点"""
        c = self.czsc
        candidates: List[Tuple[int, str, str]] = []

        signal_checks = [
            ('BUY_1', 5, sigs.cxt_first_buy_V221126, {'di': 1}),
            ('BUY_2/SELL_2', 4, sigs.cxt_second_bs_V230320, {'di': 1}),
            ('BUY_3', 3, sigs.cxt_third_buy_V230228, {'di': 1}),
            ('MACD_BC', 2, sigs.tas_macd_bc_V221201, {'di': 1}),
        ]

        if hasattr(sigs, 'cxt_third_bs_V230318'):
            signal_checks.append(
                ('BUY_3/SELL_3', 3, sigs.cxt_third_bs_V230318, {'di': 1})
            )

        for tag, priority, fn, kwargs in signal_checks:
            try:
                res = fn(c, **kwargs)
            except Exception:
                continue

            for _k, v in res.items():
                v_str = str(v)
                if v_str.startswith('其他'):
                    continue

                if tag == 'BUY_1':
                    candidates.append((priority, 'BUY_1', f'一类买点: {v_str}'))
                elif tag == 'BUY_2/SELL_2':
                    if '卖' in v_str:
                        candidates.append((priority, 'SELL_2', f'二类卖点: {v_str}'))
                    else:
                        candidates.append((priority, 'BUY_2', f'二类买点: {v_str}'))
                elif tag == 'BUY_3':
                    candidates.append((priority, 'BUY_3', f'三类买点: {v_str}'))
                elif tag == 'BUY_3/SELL_3':
                    if '卖' in v_str:
                        candidates.append((priority, 'SELL_3', f'三类卖点: {v_str}'))
                    else:
                        candidates.append((priority, 'BUY_3', f'三类买点: {v_str}'))
                elif tag == 'MACD_BC':
                    trend = self._analyze_trend()
                    if trend == 'down' or '底' in v_str:
                        candidates.append((priority, 'BUY_DIV', f'底部背驰: {v_str}'))
                    else:
                        candidates.append((priority, 'SELL_DIV', f'顶部背驰: {v_str}'))

        if not candidates:
            return ('HOLD', '')

        candidates.sort(key=lambda x: x[0], reverse=True)
        return (candidates[0][1], candidates[0][2])

    # ------------------------------------------------------------------ #
    #  笔结构手动分析（降级方案）                                            #
    # ------------------------------------------------------------------ #

    def _manual_analysis(self) -> Tuple[str, str]:
        """当 czsc 内置信号全部为"其他"时，用笔结构手动判断"""
        bis = self.czsc.bi_list

        zhongshu = self._find_zhongshu(bis[-7:])
        if zhongshu:
            sig, det = self._check_third_buy_sell(bis, zhongshu)
            if sig != 'HOLD':
                return sig, det

        sig, det = self._check_second_buy_sell(bis)
        if sig != 'HOLD':
            return sig, det

        sig, det = self._check_divergence(bis)
        if sig != 'HOLD':
            return sig, det

        return ('HOLD', '笔结构分析无明确信号')

    def _find_zhongshu(self, bis) -> Optional[Tuple[float, float]]:
        """识别中枢：连续 3 笔的重叠区间，返回 (ZG, ZD) 或 None"""
        if len(bis) < 3:
            return None
        for i in range(len(bis) - 2):
            three = bis[i:i + 3]
            zg = min(bi.high for bi in three)
            zd = max(bi.low for bi in three)
            if zg > zd:
                return (zg, zd)
        return None

    def _check_third_buy_sell(self, bi_list, zhongshu) -> Tuple[str, str]:
        """三买：离开中枢后回踩不破 ZG；三卖：反弹不破 ZD"""
        zg, zd = zhongshu
        if len(bi_list) < 3:
            return ('HOLD', '')

        last = bi_list[-1]
        prev = bi_list[-2]

        if (last.direction == Direction.Down
                and last.low > zg
                and prev.high > zg):
            return ('BUY_3',
                    f'三类买点: 回踩不破中枢上沿 ZG={zg:.2f}, 低点={last.low:.2f}')

        if (last.direction == Direction.Up
                and last.high < zd
                and prev.low < zd):
            return ('SELL_3',
                    f'三类卖点: 反弹不破中枢下沿 ZD={zd:.2f}, 高点={last.high:.2f}')

        return ('HOLD', '')

    def _check_second_buy_sell(self, bi_list) -> Tuple[str, str]:
        """二买：回调不创新低；二卖：反弹不创新高"""
        if len(bi_list) < 4:
            return ('HOLD', '')

        last, prev, prev2, prev3 = (
            bi_list[-1], bi_list[-2], bi_list[-3], bi_list[-4]
        )

        if (last.direction == Direction.Up
                and prev.direction == Direction.Down
                and prev.low > prev3.low
                and prev2.direction == Direction.Up):
            return ('BUY_2',
                    f'二类买点: 回调低点{prev.low:.2f} > 前低{prev3.low:.2f}')

        if (last.direction == Direction.Down
                and prev.direction == Direction.Up
                and prev.high < prev3.high
                and prev2.direction == Direction.Down):
            return ('SELL_2',
                    f'二类卖点: 反弹高点{prev.high:.2f} < 前高{prev3.high:.2f}')

        return ('HOLD', '')

    def _check_divergence(self, bi_list) -> Tuple[str, str]:
        """背驰：同向笔幅度缩小（价格创新高/新低但力度减弱）"""
        if len(bi_list) < 4:
            return ('HOLD', '')

        last = bi_list[-1]
        same_dir = [bi for bi in bi_list[-5:]
                     if bi.direction == last.direction]
        if len(same_dir) < 2:
            return ('HOLD', '')

        bi_new, bi_old = same_dir[-1], same_dir[-2]
        amp_new = abs(bi_new.fx_b.fx - bi_new.fx_a.fx)
        amp_old = abs(bi_old.fx_b.fx - bi_old.fx_a.fx)

        if amp_old == 0:
            return ('HOLD', '')

        if (last.direction == Direction.Up
                and bi_new.high > bi_old.high
                and amp_new < amp_old * 0.8):
            return ('SELL_DIV',
                    f'上涨背驰: 新笔幅度{amp_new:.2f} < 前笔{amp_old:.2f}×0.8')

        if (last.direction == Direction.Down
                and bi_new.low < bi_old.low
                and amp_new < amp_old * 0.8):
            return ('BUY_DIV',
                    f'下跌背驰: 新笔幅度{amp_new:.2f} < 前笔{amp_old:.2f}×0.8')

        return ('HOLD', '')

    # ------------------------------------------------------------------ #
    #  趋势分析                                                            #
    # ------------------------------------------------------------------ #

    def _analyze_trend(self) -> str:
        """从最近 3 笔高低点判断趋势方向"""
        bis = self.czsc.bi_list
        if len(bis) < 3:
            return 'unknown'

        recent = bis[-3:]
        highs = [bi.high for bi in recent]
        lows = [bi.low for bi in recent]

        if highs[-1] > highs[0] and lows[-1] > lows[0]:
            return 'up'
        if highs[-1] < highs[0] and lows[-1] < lows[0]:
            return 'down'
        return 'sideways'
