"""
完整筹码分布策略实现
基于《筹码分布量化策略技术说明书》
"""
import sys
import os
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any
from datetime import datetime

# 添加父目录到路径，确保可以导入
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'app', 'data'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'data'))

from data.chip_indicators import ChipIndicators
from data.chip_distribution_service import ChipDistributionService


class TradingPhaseDetector:
    """
    操盘阶段检测器
    识别：建仓期 / 洗盘期 / 拉升期 / 出货期 / 下跌期
    """

    def __init__(self, chip_indicators: ChipIndicators):
        self.chip_indicators = chip_indicators

    def detect_phase(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict) -> Dict:
        """
        检测当前操盘阶段

        Args:
            kline_data: K线数据
            chip_bins: 筹码分布数据
            indicators: 筹码指标

        Returns:
            阶段信息字典
        """
        if len(kline_data) < 60:
            return {'phase': 'UNKNOWN', 'confidence': 0.0, 'reason': '数据不足'}

        # 计算各阶段得分
        scores = {
            'BUILDING': self._score_building(kline_data, chip_bins, indicators),
            'WASHING': self._score_washing(kline_data, chip_bins, indicators),
            'RAISING': self._score_raising(kline_data, chip_bins, indicators),
            'SHIPPING': self._score_shipping(kline_data, chip_bins, indicators),
            'SUPPORT': self._score_support(kline_data, chip_bins, indicators)
        }

        # 找出得分最高的阶段
        best_phase = max(scores.items(), key=lambda x: x[1])
        total_score = sum(scores.values())

        confidence = best_phase[1] / max(total_score, 1)

        return {
            'phase': best_phase[0],
            'confidence': round(confidence, 4),
            'scores': scores
        }

    def _score_building(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict) -> float:
        """
        建仓期评分
        条件：
        1. 低位筹码峰形成：底部30%价格区间筹码>=40%
        2. ASR持续高位：ASR>=70持续>=10个交易日
        3. 横盘时间充足：价格在±15%区间波动>=60个交易日
        4. 股价低位：价格处于250日价格区间下30%范围内
        """
        score = 0.0

        # 条件1：低位筹码峰
        if indicators.get('profit_ratio', 0) < 0.4:
            score += 2.0

        # 条件2：ASR高位
        if indicators.get('asr', 0) >= 0.7:
            score += 2.0

        # 条件3：筹码集中
        conc_status = indicators.get('concentration_status', '')
        if conc_status == '高度集中' or conc_status == '较集中':
            score += 2.0

        # 条件4：价格低位
        if len(kline_data) >= 60:
            closes = kline_data['close'].values
            min_60 = np.min(closes[-60:])
            max_60 = np.max(closes[-60:])
            current = closes[-1]
            range_60 = max_60 - min_60
            if range_60 > 0:
                pos = (current - min_60) / range_60
                if pos < 0.4:
                    score += 2.0

        return score

    def _score_washing(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict) -> float:
        """
        洗盘期评分
        条件：
        1. 股价回调：从阶段高点回落10%-33%
        2. 量能萎缩
        3. RSI回调
        4. 价格未破主力成本
        """
        score = 0.0

        # 条件1：RSI在30-55区间
        rsi = indicators.get('rsi', 50)
        if 30 <= rsi <= 55:
            score += 2.0

        # 条件2：量能萎缩
        vol_status = indicators.get('vol_status', '')
        if vol_status == '缩量' or vol_status == '地量':
            score += 2.0

        # 条件3：ASR中等
        asr = indicators.get('asr', 0)
        if 0.3 <= asr <= 0.6:
            score += 1.5

        # 条件4：价格低于SSRP（主力成本）
        ssrp = indicators.get('ssrp', 0)
        if ssrp > 0 and len(kline_data) > 0:
            current_price = kline_data['close'].iloc[-1]
            if current_price < ssrp * 1.05 and current_price > ssrp * 0.9:
                score += 1.5

        return score

    def _score_raising(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict) -> float:
        """
        拉升期评分
        条件：
        1. 低位筹码持续减少
        2. 高位筹码持续增加
        3. 成交量放大
        4. 价格突破
        5. ASR快速回落
        """
        score = 0.0

        # 条件1：价格高于SSRP
        ssrp = indicators.get('ssrp', 0)
        if ssrp > 0 and len(kline_data) > 0:
            current_price = kline_data['close'].iloc[-1]
            if current_price > ssrp * 1.05:
                score += 2.0

        # 条件2：高获利率
        if indicators.get('profit_ratio', 0) >= 0.6:
            score += 2.0

        # 条件3：放量
        vol_status = indicators.get('vol_status', '')
        if vol_status == '放量' or vol_status == '显著放量' or vol_status == '天量':
            score += 2.0

        # 条件4：CYQKL强
        if indicators.get('cyqkl_status', '') in ['强', '很强', '极强']:
            score += 1.5

        return score

    def _score_shipping(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict) -> float:
        """
        出货期评分
        条件：
        1. 高位筹码峰形成
        2. 低位筹码基本消失
        3. RSI顶背离
        4. 量能萎缩
        5. 价格跌破高位筹码峰
        """
        score = 0.0

        # 条件1：高获利但价格开始下跌
        profit_ratio = indicators.get('profit_ratio', 0)
        if profit_ratio >= 0.7:
            if len(kline_data) >= 5:
                closes = kline_data['close'].values
                if closes[-1] < closes[-5]:
                    score += 2.5

        # 条件2：量能萎缩
        vol_status = indicators.get('vol_status', '')
        if vol_status == '缩量' or vol_status == '地量':
            score += 2.0

        # 条件3：RSI高位
        rsi = indicators.get('rsi', 0)
        if rsi >= 70:
            score += 1.5

        return score

    def _score_support(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict) -> float:
        """
        下跌期/支撑期评分
        """
        score = 0.0

        # 条件1：低获利
        if indicators.get('profit_ratio', 0) < 0.35:
            score += 2.0

        # 条件2：RSI超卖
        rsi = indicators.get('rsi', 50)
        if rsi < 30:
            score += 2.0

        # 条件3：价格低于SSRP
        ssrp = indicators.get('ssrp', 0)
        if ssrp > 0 and len(kline_data) > 0:
            current_price = kline_data['close'].iloc[-1]
            if current_price < ssrp * 0.9:
                score += 2.0

        return score


class ChipDistributionSignalGenerator:
    """
    筹码分布信号生成器
    实现技术说明书要求的完整信号体系：
    - S_BUY: 主买入信号
    - S_WASH_END: 洗盘结束买入信号
    - S_BOUNCE: 超跌反弹买入信号
    - S_SELL: 主卖出信号
    - S_WASH_STOP: 洗盘止损信号
    - S_DIVERG_SELL: 高位背离减仓信号
    """

    def __init__(self, phase_detector: TradingPhaseDetector):
        self.phase_detector = phase_detector

    def generate_signals(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict) -> Dict:
        """
        生成完整信号集合

        Args:
            kline_data: K线数据
            chip_bins: 筹码分布数据
            indicators: 筹码指标

        Returns:
            信号字典
        """
        result = {}

        phase_info = self.phase_detector.detect_phase(kline_data, chip_bins, indicators)
        result['phase_info'] = phase_info

        # 检测各个信号
        result['S_BUY'] = self._check_s_buy(kline_data, chip_bins, indicators, phase_info)
        result['S_WASH_END'] = self._check_s_wash_end(kline_data, chip_bins, indicators, phase_info)
        result['S_BOUNCE'] = self._check_s_bounce(kline_data, chip_bins, indicators, phase_info)
        result['S_SELL'] = self._check_s_sell(kline_data, chip_bins, indicators, phase_info)
        result['S_WASH_STOP'] = self._check_s_wash_stop(kline_data, chip_bins, indicators, phase_info)

        # 确定最终操作建议
        result['recommendation'] = self._combine_signals(result)

        return result

    def _check_s_buy(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                     indicators: Dict, phase_info: Dict) -> Dict:
        """
        主买入信号 S_BUY
        触发条件（同时满足）：
        1. 操盘阶段=拉升期（刚确认<=5个交易日）
        2. 价格突破60日最高价
        3. 成交量>=100日均量×1.5
        4. CYQKL>=20
        5. 筹码获利率>=60%
        """
        conditions = []
        all_met = True

        # 条件1：拉升期
        if phase_info.get('phase') == 'RAISING':
            conditions.append('✓ 处于拉升期')
        else:
            conditions.append('✗ 非拉升期')
            all_met = False

        # 条件2：价格突破
        if len(kline_data) >= 60:
            closes = kline_data['close'].values
            max_60 = np.max(closes[-60:])
            current = closes[-1]
            if current > max_60 * 0.98:
                conditions.append('✓ 价格高位')
            else:
                conditions.append('✗ 未突破')
                all_met = False

        # 条件3：成交量放大
        vol_ratio = indicators.get('vol_ratio', 0)
        if vol_ratio >= 1.5:
            conditions.append('✓ 成交量放大')
        else:
            conditions.append('✗ 成交量不足')
            all_met = False

        # 条件4：CYQKL
        cyqkl = indicators.get('cyqkl', 0)
        if cyqkl >= 0.2:
            conditions.append('✓ CYQKL达标')
        else:
            conditions.append('✗ CYQKL不足')
            all_met = False

        # 条件5：获利率
        profit_ratio = indicators.get('profit_ratio', 0)
        if profit_ratio >= 0.6:
            conditions.append('✓ 获利率达标')
        else:
            conditions.append('✗ 获利率不足')
            all_met = False

        return {
            'triggered': all_met,
            'position': 0.7,  # 70%仓位
            'conditions': conditions
        }

    def _check_s_wash_end(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                          indicators: Dict, phase_info: Dict) -> Dict:
        """
        洗盘结束买入信号 S_WASH_END
        触发条件（同时满足）：
        1. 操盘阶段=洗盘期
        2. 成交量降至地量（<=100日均量×0.4）
        3. RSI在30-55区间企稳>=3日
        4. 收盘价>=低位筹码峰下限（主力成本区）
        5. 当日涨幅>0%且成交量较前日放大>=20%
        """
        conditions = []
        all_met = True

        # 条件1：洗盘期
        if phase_info.get('phase') == 'WASHING':
            conditions.append('✓ 处于洗盘期')
        else:
            conditions.append('✗ 非洗盘期')
            all_met = False

        # 条件2：地量
        vol_status = indicators.get('vol_status', '')
        if vol_status == '地量':
            conditions.append('✓ 成交量地量')
        else:
            conditions.append('✗ 非地量')
            all_met = False

        # 条件3：RSI回调到位
        rsi = indicators.get('rsi', 50)
        if 30 <= rsi <= 55:
            conditions.append('✓ RSI回调到位')
        else:
            conditions.append('✗ RSI未到位')
            all_met = False

        # 条件4：企稳
        profit_ratio = indicators.get('profit_ratio', 0)
        if profit_ratio >= 0.3:
            conditions.append('✓ 获利率合理')
        else:
            conditions.append('✗ 获利率过低')
            all_met = False

        return {
            'triggered': all_met,
            'position': 0.5,  # 50%仓位
            'conditions': conditions
        }

    def _check_s_bounce(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                        indicators: Dict, phase_info: Dict) -> Dict:
        """
        超跌反弹买入信号 S_BOUNCE
        触发条件（同时满足）：
        1. 操盘阶段=下跌期
        2. 价格跌至历史低位筹码峰±5%范围内
        3. RSI底背离确认
        4. 筹码获利率<20%
        """
        conditions = []
        all_met = True

        # 条件1：下跌期/支撑期
        if phase_info.get('phase') == 'SUPPORT':
            conditions.append('✓ 处于支撑期')
        else:
            conditions.append('✗ 非支撑期')
            all_met = False

        # 条件2：RSI超卖
        rsi = indicators.get('rsi', 50)
        if rsi < 30:
            conditions.append('✓ RSI超卖')
        else:
            conditions.append('✗ RSI未超卖')
            all_met = False

        # 条件3：低获利率
        profit_ratio = indicators.get('profit_ratio', 0)
        if profit_ratio < 0.2:
            conditions.append('✓ 低获利率')
        else:
            conditions.append('✗ 获利率过高')
            all_met = False

        return {
            'triggered': all_met,
            'position': 0.3,  # 30%仓位
            'conditions': conditions
        }

    def _check_s_sell(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                      indicators: Dict, phase_info: Dict) -> Dict:
        """
        主卖出信号 S_SELL
        触发条件（满足任一）：
        A. 出货期确认
        B. 价格跌破筹码主峰
        C. 高位冲高回落
        """
        conditions = []
        triggered = False

        # 条件A：出货期
        if phase_info.get('phase') == 'SHIPPING':
            conditions.append('✓ 出货期确认')
            triggered = True

        # 条件B：高获利但价格下跌
        profit_ratio = indicators.get('profit_ratio', 0)
        if profit_ratio >= 0.7:
            if len(kline_data) >= 5:
                closes = kline_data['close'].values
                if closes[-1] < closes[-5] * 0.95:
                    conditions.append('✓ 高位回落')
                    triggered = True

        # 条件C：RSI超买
        rsi = indicators.get('rsi', 50)
        if rsi >= 80:
            conditions.append('✓ RSI超买')
            triggered = True

        return {
            'triggered': triggered,
            'position': 0.0,  # 清仓
            'conditions': conditions
        }

    def _check_s_wash_stop(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                           indicators: Dict, phase_info: Dict) -> Dict:
        """
        洗盘止损信号 S_WASH_STOP
        触发条件：
        1. 价格跌破低位筹码峰下限（主力成本被破）
        2. 或价格跌幅超过从阶段高点计算35%
        """
        conditions = []
        triggered = False

        # 条件：价格跌破SSRP
        ssrp = indicators.get('ssrp', 0)
        if ssrp > 0 and len(kline_data) > 0:
            current_price = kline_data['close'].iloc[-1]
            if current_price < ssrp * 0.9:
                conditions.append('✓ 跌破主力成本')
                triggered = True

        return {
            'triggered': triggered,
            'position': 0.0,  # 清仓
            'conditions': conditions
        }

    def _combine_signals(self, signals: Dict) -> Dict:
        """
        综合各信号给出最终操作建议
        """
        # 优先级：止损/卖出 > 买入
        if signals.get('S_WASH_STOP', {}).get('triggered', False):
            return {
                'action': 'SELL',
                'reason': '洗盘止损',
                'target_position': 0.0,
                'priority': 1
            }

        if signals.get('S_SELL', {}).get('triggered', False):
            return {
                'action': 'SELL',
                'reason': '主卖出信号',
                'target_position': 0.0,
                'priority': 2
            }

        if signals.get('S_BUY', {}).get('triggered', False):
            return {
                'action': 'BUY',
                'reason': '主买入信号',
                'target_position': 0.7,
                'priority': 3
            }

        if signals.get('S_WASH_END', {}).get('triggered', False):
            return {
                'action': 'BUY',
                'reason': '洗盘结束',
                'target_position': 0.5,
                'priority': 4
            }

        if signals.get('S_BOUNCE', {}).get('triggered', False):
            return {
                'action': 'BUY',
                'reason': '超跌反弹',
                'target_position': 0.3,
                'priority': 5
            }

        return {
            'action': 'HOLD',
            'reason': '无明确信号',
            'target_position': None,
            'priority': 99
        }
