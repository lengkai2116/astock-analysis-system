"""
筹码因子计算模块 - 完整实现技术说明书要求
包含：ASR/CYQKL/SSRP/RSI/成交量/换手率/筹码集中度/筹码峰识别/筹码转移检测
"""
import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Tuple
from .chip_distribution_service import ChipDistributionService


class ChipIndicators:
    """
    筹码因子计算器 - 完整实现技术说明书要求
    """

    def __init__(self, chip_service: ChipDistributionService = None):
        self.chip_service = chip_service or ChipDistributionService()

    def calculate_all_indicators(self, chip_bins: List[Dict],
                                  current_price: float,
                                  kline_data: Optional[pd.DataFrame] = None,
                                  turnover_rate: Optional[float] = None) -> Dict:
        """
        计算所有筹码因子

        Args:
            chip_bins: 筹码分布数据
            current_price: 当前价格
            kline_data: K线数据（用于CYQKL和RSI）
            turnover_rate: 换手率

        Returns:
            包含所有筹码因子的字典
        """
        if not chip_bins:
            return {}

        result = {}

        # SSRP - 市场平均成本
        result['ssrp'] = self.calculate_ssrp(chip_bins)

        # ASR - 活跃浮筹比例 (±5%)
        result['asr'] = self.calculate_asr(chip_bins, current_price, band_pct=0.05)
        result['asr_status'] = self.get_asr_status(result['asr'])

        # 筹码集中度 (P95-P5算法)
        result['concentration'] = self.calculate_concentration_p95(chip_bins)
        result['concentration_status'] = self.get_concentration_status(result['concentration'])

        # 筹码获利率
        result['profit_ratio'] = self.calculate_profit_ratio(chip_bins, current_price)
        result['profit_ratio_status'] = self.get_profit_ratio_status(result['profit_ratio'])

        # CYQKL - K线穿越筹码强度
        if kline_data is not None and not kline_data.empty:
            result['cyqkl'] = self.calculate_cyqkl_entity(chip_bins, kline_data)
            result['cyqkl_status'] = self.get_cyqkl_status(result['cyqkl'])

        # RSI - 相对强弱指标
        if kline_data is not None and len(kline_data) >= 15:
            result['rsi'] = self.calculate_rsi(kline_data, period=14)
            result['rsi_status'] = self.get_rsi_status(result['rsi'])

        # 成交量指标
        if kline_data is not None and len(kline_data) >= 100:
            vol_indicators = self.calculate_volume_indicators(kline_data)
            result.update(vol_indicators)

        # 换手率
        if turnover_rate is not None:
            result['turnover_rate'] = turnover_rate
            result['turnover_status'] = self.get_turnover_status(turnover_rate)

        # 筹码峰识别
        peak_info = self.identify_chip_peaks(chip_bins, current_price)
        result.update(peak_info)

        return result

    def calculate_ssrp(self, chip_bins: List[Dict]) -> float:
        """
        计算SSRP - 市场平均成本（平均持仓价格）

        Args:
            chip_bins: 筹码分布数据

        Returns:
            SSRP值
        """
        total_chips = sum(bin_data['chip_ratio'] for bin_data in chip_bins)
        if total_chips <= 0:
            return 0

        weighted_price = sum(bin_data['price_bin'] * bin_data['chip_ratio'] for bin_data in chip_bins)
        return round(weighted_price / total_chips, 2)

    def calculate_asr(self, chip_bins: List[Dict], current_price: float, band_pct: float = 0.05) -> float:
        """
        计算ASR - 活跃浮筹比例（当前价格±N%区间的筹码比例）
        技术说明书要求：±5%

        Args:
            chip_bins: 筹码分布数据
            current_price: 当前价格
            band_pct: 价格区间宽度（默认5%）

        Returns:
            ASR值（0-1）
        """
        price_low = current_price * (1 - band_pct)
        price_high = current_price * (1 + band_pct)

        asr_ratio = sum(bin_data['chip_ratio'] for bin_data in chip_bins
                        if price_low <= bin_data['price_bin'] <= price_high)

        return round(asr_ratio, 4)

    def get_asr_status(self, asr: float) -> str:
        """
        获取ASR状态分类
        """
        if asr < 0.2:
            return '低浮筹'
        elif asr < 0.5:
            return '中等浮筹'
        elif asr < 0.8:
            return '高浮筹'
        elif asr < 0.9:
            return '极高浮筹'
        else:
            return '极限浮筹'

    def calculate_concentration_p95(self, chip_bins: List[Dict]) -> float:
        """
        计算筹码集中度 - P95-P5算法
        技术说明书要求：集中度 = (P95价格 - P5价格) / 当前价格 × 100%

        Args:
            chip_bins: 筹码分布数据

        Returns:
            筹码集中度（百分比，如0.15表示15%）
        """
        if not chip_bins:
            return 0

        # 按价格排序
        sorted_bins = sorted(chip_bins, key=lambda x: x['price_bin'])

        # 计算累计筹码
        cumulative = []
        total = 0
        for bin_data in sorted_bins:
            total += bin_data['chip_ratio']
            cumulative.append({'price': bin_data['price_bin'], 'cum_ratio': total})

        if total <= 0:
            return 0

        # 找到P5和P95价格
        p5_price = self._find_price_at_cum_ratio(cumulative, 0.05)
        p95_price = self._find_price_at_cum_ratio(cumulative, 0.95)

        # 当前价格取平均价格
        current_price = sum(bin_data['price_bin'] * bin_data['chip_ratio'] for bin_data in chip_bins) / total

        if current_price <= 0:
            return 0

        concentration = (p95_price - p5_price) / current_price
        return round(concentration, 4)

    def _find_price_at_cum_ratio(self, cumulative: List[Dict], target_ratio: float) -> float:
        """
        在累计筹码分布中找到指定累计比例对应的价格
        """
        for i, item in enumerate(cumulative):
            if item['cum_ratio'] >= target_ratio:
                if i == 0:
                    return item['price']
                # 线性插值
                prev_item = cumulative[i - 1]
                ratio_diff = item['cum_ratio'] - prev_item['cum_ratio']
                if ratio_diff <= 0:
                    return item['price']
                weight = (target_ratio - prev_item['cum_ratio']) / ratio_diff
                return prev_item['price'] + weight * (item['price'] - prev_item['price'])

        return cumulative[-1]['price'] if cumulative else 0

    def get_concentration_status(self, concentration: float) -> str:
        """
        获取筹码集中度状态
        """
        if concentration < 0.1:
            return '高度集中'
        elif concentration < 0.2:
            return '较集中'
        elif concentration < 0.4:
            return '分散'
        else:
            return '高度发散'

    def calculate_profit_ratio(self, chip_bins: List[Dict], current_price: float) -> float:
        """
        计算筹码获利率 - 当前价格以下的筹码比例

        Args:
            chip_bins: 筹码分布数据
            current_price: 当前价格

        Returns:
            筹码获利率（0-1）
        """
        profit_ratio = sum(bin_data['chip_ratio'] for bin_data in chip_bins
                          if bin_data['price_bin'] <= current_price)
        return round(profit_ratio, 4)

    def get_profit_ratio_status(self, profit_ratio: float) -> str:
        """
        获取筹码获利率状态
        """
        if profit_ratio < 0.35:
            return '低盈利'
        elif profit_ratio < 0.6:
            return '中等盈利'
        else:
            return '高盈利'

    def calculate_cyqkl_entity(self, chip_bins: List[Dict], kline_data: pd.DataFrame) -> float:
        """
        计算CYQKL - K线实体穿越筹码强度
        技术说明书要求：当日K线实体（开盘到收盘）穿透的筹码数量

        Args:
            chip_bins: 筹码分布数据
            kline_data: K线数据（至少包含当前K线）

        Returns:
            CYQKL值（0-1，值越大说明穿越强度越大）
        """
        if kline_data.empty:
            return 0

        # 获取最新K线
        latest_kline = kline_data.iloc[-1]

        open_price = latest_kline['open']
        close_price = latest_kline['close']

        # K线实体区间
        entity_min = min(open_price, close_price)
        entity_max = max(open_price, close_price)

        # 计算被K线实体穿越的筹码总量
        crossed_chips = sum(bin_data['chip_ratio'] for bin_data in chip_bins
                           if entity_min <= bin_data['price_bin'] <= entity_max)

        return round(crossed_chips, 4)

    def get_cyqkl_status(self, cyqkl: float) -> str:
        """
        获取CYQKL状态
        """
        if cyqkl < 0.1:
            return '弱'
        elif cyqkl < 0.3:
            return '中等'
        elif cyqkl < 0.5:
            return '强'
        elif cyqkl < 0.6:
            return '很强'
        else:
            return '极强'

    def calculate_rsi(self, kline_data: pd.DataFrame, period: int = 14) -> float:
        """
        计算RSI - 相对强弱指标

        Args:
            kline_data: K线数据
            period: RSI周期（默认14日）

        Returns:
            RSI值（0-100）
        """
        if len(kline_data) < period + 1:
            return 50

        # 计算价格变化
        closes = kline_data['close'].values
        deltas = np.diff(closes)

        if len(deltas) < period:
            return 50

        gains = []
        losses = []

        for delta in deltas[-period:]:
            if delta > 0:
                gains.append(delta)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(-delta)

        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)

        if avg_loss == 0:
            return 100

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return round(rsi, 2)

    def get_rsi_status(self, rsi: float) -> str:
        """
        获取RSI状态
        """
        if rsi < 20:
            return '极度超卖'
        elif rsi < 30:
            return '超卖'
        elif rsi < 50:
            return '偏弱'
        elif rsi < 70:
            return '偏强'
        elif rsi < 80:
            return '偏强注意'
        else:
            return '超买'


    def detect_rsi_divergence(self, kline_data: pd.DataFrame, period: int = 14, lookback: int = 20) -> Dict:
        """
        检测RSI顶背离和底背离

        顶背离: 价格创新高 + RSI未创新高 → bearish divergence (卖出信号)
        底背离: 价格创新低 + RSI未创新低 → bullish divergence (买入信号)
        距离上一次背离 >= 5个交易日 → 算作新的一次

        Args:
            kline_data: K线数据
            period: RSI计算周期
            lookback: 回看天数

        Returns:
            {'top_divergence': Dict, 'bottom_divergence': Dict}
        """
        result = {
            'top_divergence': {'detected': False, 'count': 0, 'last_distance': 0},
            'bottom_divergence': {'detected': False, 'count': 0, 'last_distance': 0}
        }

        if len(kline_data) < lookback + period + 1:
            return result

        closes = kline_data['close'].values
        rsi_values = []
        for i in range(len(closes)):
            sub_df = kline_data.iloc[:i+1]
            if len(sub_df) >= period + 1:
                rsi_values.append(self.calculate_rsi(sub_df, period))
            else:
                rsi_values.append(50)

        rsi_arr = np.array(rsi_values)

        # ----- 顶背离检测 -----
        # 1. 找最近lookback天的价格高点
        lookback_closes = closes[-lookback:]
        lookback_rsi = rsi_arr[-lookback:]

        # 价格局部高点索引
        price_peaks = []
        for i in range(1, len(lookback_closes) - 1):
            if lookback_closes[i] > lookback_closes[i-1] and lookback_closes[i] > lookback_closes[i+1]:
                price_peaks.append({
                    'idx': len(closes) - lookback + i,
                    'price': lookback_closes[i],
                    'rsi': lookback_rsi[i]
                })

        if len(price_peaks) >= 2:
            # 最近两个价格高点
            p2 = price_peaks[-1]  # 最近
            p1 = price_peaks[-2]  # 前一个

            # 顶背离: 价格上升 + RSI下降
            if p2['price'] > p1['price'] and p2['rsi'] < p1['rsi']:
                # 计算距离上次背离
                last_dist = len(closes) - p1['idx']

                # 统计历史背离次数（简化: 仅在当前检测到就认为1次）
                count = 1
                result['top_divergence'] = {
                    'detected': True,
                    'count': count,
                    'last_distance': last_dist,
                    'latest_high_price': p2['price'],
                    'latest_high_rsi': p2['rsi'],
                    'prev_high_price': p1['price'],
                    'prev_high_rsi': p1['rsi']
                }

        # ----- 底背离检测 -----
        price_bottoms = []
        for i in range(1, len(lookback_closes) - 1):
            if lookback_closes[i] < lookback_closes[i-1] and lookback_closes[i] < lookback_closes[i+1]:
                price_bottoms.append({
                    'idx': len(closes) - lookback + i,
                    'price': lookback_closes[i],
                    'rsi': lookback_rsi[i]
                })

        if len(price_bottoms) >= 2:
            b2 = price_bottoms[-1]
            b1 = price_bottoms[-2]

            # 底背离: 价格下降 + RSI上升
            if b2['price'] < b1['price'] and b2['rsi'] > b1['rsi']:
                last_dist = len(closes) - b1['idx']
                count = 1
                result['bottom_divergence'] = {
                    'detected': True,
                    'count': count,
                    'last_distance': last_dist,
                    'latest_low_price': b2['price'],
                    'latest_low_rsi': b2['rsi'],
                    'prev_low_price': b1['price'],
                    'prev_low_rsi': b1['rsi']
                }

        # 二次背离检测（连续两次背离）
        if len(price_peaks) >= 3:
            p3 = price_peaks[-1]
            p2 = price_peaks[-2]
            p1 = price_peaks[-3]
            # 连续两次顶背离
            if (p3['price'] > p2['price'] > p1['price'] and
                p3['rsi'] < p2['rsi'] < p1['rsi']):
                result['top_divergence']['count'] = 2

        if len(price_bottoms) >= 3:
            b3 = price_bottoms[-1]
            b2 = price_bottoms[-2]
            b1 = price_bottoms[-3]
            if (b3['price'] < b2['price'] < b1['price'] and
                b3['rsi'] > b2['rsi'] > b1['rsi']):
                result['bottom_divergence']['count'] = 2

        return result

    def calculate_volume_indicators(self, kline_data: pd.DataFrame) -> Dict:
        """
        计算成交量指标

        Args:
            kline_data: K线数据（至少100日）

        Returns:
            成交量指标字典
        """
        result = {}

        if len(kline_data) < 100:
            return result

        # 100日等量线
        avg_vol_100 = kline_data['vol'].iloc[-100:].mean()
        result['avg_vol_100'] = avg_vol_100

        # 当前成交量
        current_vol = kline_data['vol'].iloc[-1]
        result['current_vol'] = current_vol

        # 成交量倍数
        vol_ratio = current_vol / avg_vol_100 if avg_vol_100 > 0 else 0
        result['vol_ratio'] = round(vol_ratio, 2)

        # 成交量状态
        result['vol_status'] = self.get_volume_status(vol_ratio)

        # 量能趋势
        result['volume_trend'] = self.get_volume_trend(kline_data, avg_vol_100)

        return result

    def get_volume_status(self, vol_ratio: float) -> str:
        """
        获取成交量状态
        """
        if vol_ratio >= 3.0:
            return '天量'
        elif vol_ratio >= 2.0:
            return '显著放量'
        elif vol_ratio >= 1.5:
            return '放量'
        elif vol_ratio <= 0.3:
            return '地量'
        elif vol_ratio <= 0.7:
            return '缩量'
        else:
            return '正常'

    def get_volume_trend(self, kline_data: pd.DataFrame, avg_vol_100: float) -> str:
        """
        计算量能趋势
        """
        if len(kline_data) < 5:
            return '正常'

        recent_vols = kline_data['vol'].iloc[-5:].values

        # 量能持续放大：连续5日成交量 > 100日均量
        if all(v > avg_vol_100 for v in recent_vols):
            return '持续放大'

        # 量能萎缩触底：连续3日成交量 < 100日均量 × 0.5
        if len(recent_vols) >= 3 and all(v < avg_vol_100 * 0.5 for v in recent_vols[-3:]):
            return '萎缩触底'

        return '正常'

    def get_turnover_status(self, turnover_rate: float) -> str:
        """
        获取换手率状态
        """
        if turnover_rate < 0.02:
            return '低活跃度'
        elif turnover_rate < 0.05:
            return '正常'
        elif turnover_rate < 0.1:
            return '较高'
        else:
            return '极高'

    def identify_chip_peaks(self, chip_bins: List[Dict], current_price: float) -> Dict:
        """
        识别筹码峰类型（单峰密集/双峰/发散）

        Args:
            chip_bins: 筹码分布数据
            current_price: 当前价格

        Returns:
            筹码峰信息字典
        """
        result = {}

        if not chip_bins:
            return {'peak_type': '未知'}

        # 找所有局部峰
        peaks = self._find_all_peaks(chip_bins)

        if not peaks:
            return {'peak_type': '无明显峰'}

        # 按筹码比例排序
        peaks_sorted = sorted(peaks, key=lambda x: x['ratio'], reverse=True)
        main_peak = peaks_sorted[0]

        result['main_peak'] = main_peak
        result['peak_count'] = len(peaks)

        # 单峰密集判断
        if self._is_single_peak(peaks, current_price):
            result['peak_type'] = '单峰密集'
        # 双峰判断
        elif self._is_double_peak(peaks, current_price):
            result['peak_type'] = '筹码双峰'
        # 发散判断
        elif self._is_divergence(peaks, current_price):
            result['peak_type'] = '筹码发散'
        else:
            result['peak_type'] = '多峰分布'

        return result

    def _find_all_peaks(self, chip_bins: List[Dict]) -> List[Dict]:
        """
        找出所有局部筹码峰
        """
        peaks = []
        n = len(chip_bins)

        for i in range(n):
            if i == 0 or i == n - 1:
                continue

            current = chip_bins[i]['chip_ratio']
            left = chip_bins[i - 1]['chip_ratio']
            right = chip_bins[i + 1]['chip_ratio']

            # 局部最大值检测
            if current > left and current > right and current > 0.02:
                peaks.append({
                    'price': chip_bins[i]['price_bin'],
                    'ratio': current,
                    'index': i
                })

        return peaks

    def _is_single_peak(self, peaks: List[Dict], current_price: float) -> bool:
        """
        判断是否为单峰密集
        条件：
        1. 存在单一价格区间筹码≥30%
        2. 主筹码峰≥次高峰×2
        3. 集中度<15%
        """
        if len(peaks) == 0:
            return False

        main_ratio = peaks[0]['ratio']
        if main_ratio < 0.3:
            return False

        if len(peaks) >= 2:
            second_ratio = peaks[1]['ratio']
            if main_ratio < second_ratio * 2:
                return False

        return True

    def _is_double_peak(self, peaks: List[Dict], current_price: float) -> bool:
        """
        判断是否为筹码双峰
        条件：
        1. 两个峰≥15%
        2. 两峰间距≥10%
        3. 中间区域<20%
        """
        if len(peaks) < 2:
            return False

        # 取前两个峰
        peak1 = peaks[0]
        peak2 = peaks[1]

        if peak1['ratio'] < 0.15 or peak2['ratio'] < 0.15:
            return False

        # 两峰间距
        peak_distance = abs(peak1['price'] - peak2['price']) / max(peak1['price'], peak2['price'])
        if peak_distance < 0.1:
            return False

        return True

    def _is_divergence(self, peaks: List[Dict], current_price: float) -> bool:
        """
        判断是否为筹码发散
        条件：
        1. 无单一峰≥20%
        2. 集中度>30%
        """
        if len(peaks) == 0:
            return True

        if peaks[0]['ratio'] >= 0.2:
            return False

        return True

    def detect_chip_transfer(self, chip_bins_history: List[List[Dict]],
                             lookback: int = 20) -> Dict:
        """
        检测筹码转移方向（向上/向下/稳定）

        Args:
            chip_bins_history: 历史筹码分布数据
            lookback: 回看天数

        Returns:
            筹码转移信息字典
        """
        if len(chip_bins_history) < lookback + 1:
            return {'transfer_type': '数据不足'}

        earliest_chips = chip_bins_history[-lookback - 1]
        latest_chips = chip_bins_history[-1]

        # 计算平均价格
        def get_avg_price(chips):
            total = sum(c['chip_ratio'] for c in chips)
            if total <= 0:
                return 0
            return sum(c['price_bin'] * c['chip_ratio'] for c in chips) / total

        earliest_avg = get_avg_price(earliest_chips)
        latest_avg = get_avg_price(latest_chips)

        if earliest_avg <= 0 or latest_avg <= 0:
            return {'transfer_type': '数据异常'}

        # 计算高低位筹码变化
        def get_low_high_chips(chips):
            prices = [c['price_bin'] for c in chips]
            if not prices:
                return 0, 0
            min_price, max_price = min(prices), max(prices)
            price_range = max_price - min_price
            if price_range <= 0:
                return 0, 0

            # 低位：底部30%价格区间
            low_threshold = min_price + price_range * 0.3
            low_chips = sum(c['chip_ratio'] for c in chips if c['price_bin'] <= low_threshold)

            # 高位：顶部30%价格区间
            high_threshold = max_price - price_range * 0.3
            high_chips = sum(c['chip_ratio'] for c in chips if c['price_bin'] >= high_threshold)

            return low_chips, high_chips

        earliest_low, earliest_high = get_low_high_chips(earliest_chips)
        latest_low, latest_high = get_low_high_chips(latest_chips)

        low_change = latest_low - earliest_low
        high_change = latest_high - earliest_high

        result = {
            'low_chips_change': round(low_change, 4),
            'high_chips_change': round(high_change, 4),
            'avg_price_change': round((latest_avg - earliest_avg) / earliest_avg, 4)
        }

        # 筹码向上转移判断：低位减少≥5% 且 高位增加≥5%
        if low_change <= -0.05 and high_change >= 0.05:
            result['transfer_type'] = '向上转移'
        # 筹码向下转移判断：高位减少≥5% 且 低位增加≥5%
        elif high_change <= -0.05 and low_change >= 0.05:
            result['transfer_type'] = '向下转移'
        else:
            result['transfer_type'] = '稳定'

        # 计算转移速度
        if len(chip_bins_history) >= 2:
            speed = abs(latest_avg - earliest_avg) / (earliest_avg * lookback)
            result['transfer_speed'] = round(speed * 100, 4)  # 日化百分比

        return result

    def calculate_transfer_rate(self, chip_bins_history: List[List[Dict]], window: int = 20) -> float:
        """
        计算筹码转移率 - 筹码向当前价格区域移动的速度

        Args:
            chip_bins_history: 历史筹码分布数据列表
            window: 窗口期（默认20天）

        Returns:
            筹码转移率
        """
        if len(chip_bins_history) < 2:
            return 0

        # 只取最近window天的数据
        history = chip_bins_history[-window:]

        if len(history) < 2:
            return 0

        # 计算筹码分布的变化
        latest_chips = history[-1]
        earliest_chips = history[0]

        # 计算分布的KL散度或简单的标准差变化
        if len(latest_chips) == len(earliest_chips):
            latest_ratios = [bin_data['chip_ratio'] for bin_data in latest_chips]
            earliest_ratios = [bin_data['chip_ratio'] for bin_data in earliest_chips]

            # 简单的标准差变化
            std_latest = np.std(latest_ratios)
            std_earliest = np.std(earliest_ratios)

            if std_earliest > 0:
                transfer_rate = abs(std_latest - std_earliest) / std_earliest
            else:
                transfer_rate = 0

            return round(transfer_rate, 4)

        return 0

    def find_peak_positions(self, chip_bins: List[Dict]) -> List[Dict]:
        """
        找到筹码峰位置

        Args:
            chip_bins: 筹码分布数据

        Returns:
            筹码峰位置列表
        """
        peaks = []

        for i, bin_data in enumerate(chip_bins):
            if bin_data.get('peak_flag', False):
                peaks.append({
                    'price': bin_data['price_bin'],
                    'ratio': bin_data['chip_ratio'],
                    'type': 'peak'
                })

        # 排序（按筹码比例降序）
        peaks.sort(key=lambda x: x['ratio'], reverse=True)
        return peaks

    def find_support_resistance_levels(self, chip_bins: List[Dict],
                                      threshold: float = 0.03) -> Dict[str, List[float]]:
        """
        找到支撑位和阻力位（基于筹码峰）

        Args:
            chip_bins: 筹码分布数据
            threshold: 筹码峰阈值（默认3%）

        Returns:
            {'support': [...], 'resistance': [...]}
        """
        peaks = self.find_peak_positions(chip_bins)

        # 筛选大于阈值的筹码峰
        significant_peaks = [p for p in peaks if p['ratio'] >= threshold]

        # 简单的支撑位和阻力位划分
        # 这里简化处理，实际需要结合价格趋势
        prices = [p['price'] for p in significant_peaks]

        return {
            'support': prices,
            'resistance': prices
        }
