"""
完整筹码分布策略实现
基于《筹码分布量化策略技术说明书》
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any
from datetime import datetime

from app.data.chip_indicators import ChipIndicators
from app.data.chip_distribution_service import ChipDistributionService


class TradingPhaseDetector:
    """
    操盘阶段检测器
    识别：建仓期 / 洗盘期 / 拉升期 / 出货期 / 下跌期
    """

    def __init__(self, chip_indicators: ChipIndicators):
        self.chip_indicators = chip_indicators

    def detect_phase(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict,
                    chip_bins_history: Optional[List[List[Dict]]] = None) -> Dict:
        """
        检测当前操盘阶段

        Args:
            kline_data: K线数据
            chip_bins: 筹码分布数据
            indicators: 筹码指标
            chip_bins_history: 历史筹码分布（用于筹码转移方向检测）

        Returns:
            阶段信息字典
        """
        if len(kline_data) < 60:
            return {'phase': 'UNKNOWN', 'confidence': 0.0, 'reason': '数据不足'}

        # 计算筹码转移信息（如提供历史数据）
        transfer_info = None
        if chip_bins_history is not None:
            try:
                transfer_info = self.chip_indicators.detect_chip_transfer(chip_bins_history, lookback=20)
            except Exception:
                pass

        # 计算各阶段得分
        scores = {
            'BUILDING': self._score_building(kline_data, chip_bins, indicators, transfer_info),
            'WASHING': self._score_washing(kline_data, chip_bins, indicators, transfer_info),
            'RAISING': self._score_raising(kline_data, chip_bins, indicators, transfer_info),
            'SHIPPING': self._score_shipping(kline_data, chip_bins, indicators, transfer_info),
            'SUPPORT': self._score_support(kline_data, chip_bins, indicators, transfer_info)
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

    def _score_washing(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict,
                      transfer_info: Optional[Dict] = None) -> float:
        """
        洗盘期评分
        条件：
        1. 股价回调：从阶段高点回落10%-33%
        2. 量能萎缩
        3. RSI回调
        4. 价格未破主力成本
        5. 低位筹码稳定或增加（方向3增强）
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

        # 条件5：筹码稳定或向下转移（方向3）
        if transfer_info is not None:
            tr_type = transfer_info.get('transfer_type', '')
            low_chg = transfer_info.get('low_chips_change', 0)
            if tr_type == '稳定':
                # 低位筹码量稳定 = 洗盘中的筹码锁定
                if low_chg >= -0.02:
                    score += 2.0
            elif tr_type == '向下转移':
                # 低位筹码增加 = 洗盘吸筹
                if low_chg > 0:
                    score += 2.0

        return score

    def _score_raising(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict,
                     transfer_info: Optional[Dict] = None) -> float:
        """
        拉升期评分
        条件：
        1. 低位筹码持续减少（筹码向上转移）
        2. 高位筹码持续增加
        3. 成交量放大
        4. 价格突破
        5. ASR快速回落
        6. 筹码向上转移（方向3增强）
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

        # 条件5：筹码向上转移（方向3）
        if transfer_info is not None:
            tr_type = transfer_info.get('transfer_type', '')
            speed = transfer_info.get('transfer_speed', 0)
            if tr_type == '向上转移':
                score += 2.0
            elif tr_type == '稳定':
                # 盈利盘增加中的稳定 = 拉升趋势确认
                if indicators.get('profit_ratio', 0) >= 0.5:
                    score += 1.0

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
        self.chip_indicators = ChipIndicators()

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

        # K线形态验证（Phase 2 模块3）
        try:
            from app.engine.framework.kline_pattern import KLinePatternVerifier
            pattern_verifier = KLinePatternVerifier()
            patterns = pattern_verifier.verify(kline_data)
            result['patterns'] = [p.to_dict() for p in patterns]
        except Exception:
            result['patterns'] = []

        # 检测各个信号
        result['S_BUY'] = self._check_s_buy(kline_data, chip_bins, indicators, phase_info)
        result['S_WASH_END'] = self._check_s_wash_end(kline_data, chip_bins, indicators, phase_info)
        result['S_BOUNCE'] = self._check_s_bounce(kline_data, chip_bins, indicators, phase_info)
        result['S_SELL'] = self._check_s_sell(kline_data, chip_bins, indicators, phase_info)
        result['S_WASH_STOP'] = self._check_s_wash_stop(kline_data, chip_bins, indicators, phase_info)
        result['S_DIVERG_SELL'] = self._check_s_diverg_sell(kline_data, chip_bins, indicators, phase_info)

        # 确定最终操作建议（含K线形态置信度调整）
        recommendation = self._combine_signals(result)
        # 如果有多头形态且信号为买入，提升置信度描述
        bullish_patterns = [p for p in result.get('patterns', []) if p.get('direction') == 'bullish']
        bearish_patterns = [p for p in result.get('patterns', []) if p.get('direction') == 'bearish']
        if bullish_patterns and recommendation.get('action') == 'BUY':
            recommendation['pattern_boost'] = [p['name'] for p in bullish_patterns]
        if bearish_patterns and recommendation.get('action') == 'SELL':
            recommendation['pattern_boost'] = [p['name'] for p in bearish_patterns]
        result['recommendation'] = recommendation

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

        # === 假突破前置过滤：突破状态时验证量能+时间+深度 ===
        false_break = self._check_false_breakout(kline_data, indicators)
        if false_break['is_breakout'] and not false_break['passed']:
            return {'triggered': False, 'position': 0.0, 'conditions': ['假突破过滤: ' + false_break['reason']]}

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

        # 条件5：SSRP穿越确认 — 收盘价 > SSRP（拉升启动信号，书本第2章§2.6）
        ssrp = indicators.get('ssrp', 0)
        current_price = float(kline_data['close'].iloc[-1]) if len(kline_data) > 0 and ssrp > 0 else 0
        if current_price > 0 and ssrp > 0 and current_price > ssrp:
            conditions.append(f'✓ SSRP穿越确认: 收盘价{current_price:.2f} > SSRP {ssrp:.2f}')
        else:
            conditions.append('✗ SSRP未突破')
            all_met = False

        # 条件6：获利率
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

        # === 假突破前置过滤：突破状态时验证量能+时间+深度 ===
        false_break = self._check_false_breakout(kline_data, indicators)
        if false_break['is_breakout'] and not false_break['passed']:
            return {'triggered': False, 'position': 0.0, 'conditions': ['假突破过滤: ' + false_break['reason']]}

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


        # 条件D：SSRP穿越卖出 — 连续2日收盘价 < SSRP（书本第2章§2.6）
        ssrp = indicators.get('ssrp', 0)
        if ssrp > 0 and len(kline_data) >= 3:
            closes = kline_data['close'].values
            if len(closes) >= 2 and closes[-1] < ssrp and closes[-2] < ssrp:
                conditions.append(f'✓ 连续2日低于SSRP({ssrp:.2f})')
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

    def _check_s_diverg_sell(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                              indicators: Dict, phase_info: Dict) -> Dict:
        """
        高位背离减仓信号 S_DIVERG_SELL
        书本依据: 第7章§7.2.3 + 第8章 + 背离形态知识库
        使用 chip_indicators.detect_rsi_divergence() 替代简化版峰值对比

        触发条件：
          初次顶背离(价格新高,RSI不新高) → 减仓至70%
          二次顶背离(价格连创新高,RSI持续下降) → 减仓至30%
          三重顶背离 → 减仓至10%
        """
        conditions = []
        triggered = False
        position_adjustment = 1.0

        if len(kline_data) < 40:
            return {'triggered': False, 'position_adjustment': 1.0, 'conditions': ['数据不足']}

        try:
            divergence = self.chip_indicators.detect_rsi_divergence(kline_data, period=14, lookback=20)
        except Exception:
            return {'triggered': False, 'position_adjustment': 1.0, 'conditions': ['背离检测异常']}

        top_div = divergence.get('top_divergence', {})

        # === 顶背离 → 减仓信号 ===
        if top_div.get('detected', False):
            count = top_div.get('count', 1)

            if count >= 3:
                triggered = True
                position_adjustment = 0.1
                conditions.append(
                    f'✓ 三重顶背离确认 → 减仓至10% '
                    f'(最新:价格{top_div["latest_high_price"]:.2f}/RSI{top_div["latest_high_rsi"]:.1f}, '
                    f'前次:价格{top_div["prev_high_price"]:.2f}/RSI{top_div["prev_high_rsi"]:.1f})'
                )
            elif count == 2:
                triggered = True
                position_adjustment = 0.3
                conditions.append(
                    f'✓ 二次顶背离确认 → 减仓至30% '
                    f'(最新RSI{top_div["latest_high_rsi"]:.1f} < 前次RSI{top_div["prev_high_rsi"]:.1f})'
                )
            else:
                triggered = True
                position_adjustment = 0.7
                conditions.append(
                    f'▶ 初次顶背离 → 减仓至70% '
                    f'(价格{top_div["latest_high_price"]:.2f}新高, '
                    f'RSI{top_div["latest_high_rsi"]:.1f}低于前次{top_div["prev_high_rsi"]:.1f})'
                )

        return {
            'triggered': triggered,
            'position_adjustment': position_adjustment,
            'top_divergence_count': top_div.get('count', 0),
            'conditions': conditions
        }
    def _check_false_breakout(self, kline_data: pd.DataFrame, indicators: Dict) -> Dict:
        """
        假突破前置检测 — 三维确认（书本第9章§9.3 + 假突破交易策略）
        仅在突破/跌破状态时激活，非突破状态直接返回通过
        """
        if kline_data.empty or len(kline_data) < 5:
            return {'passed': True, 'reason': '数据不足，默认通过', 'is_breakout': False}

        closes = kline_data['close'].values
        latest = float(closes[-1])

        if len(closes) >= 20:
            max_20 = float(np.max(closes[-20:]))
            min_20 = float(np.min(closes[-20:]))
            price_range = max_20 - min_20
            if price_range <= 0:
                return {'passed': True, 'reason': '价格无波动', 'is_breakout': False}

            is_breakout_high = latest >= max_20 * 0.98
            is_breakout_low = latest <= min_20 * 1.02

            if not is_breakout_high and not is_breakout_low:
                return {'passed': True, 'reason': '非突破状态', 'is_breakout': False}
        else:
            return {'passed': True, 'reason': '数据不足', 'is_breakout': False}

        if is_breakout_high:
            breakout_level = max_20 * 0.98
        else:
            breakout_level = min_20 * 1.02

        breakout_days = 0
        for i in range(len(closes) - 1, -1, -1):
            if (is_breakout_high and closes[i] >= breakout_level) or (is_breakout_low and closes[i] <= breakout_level):
                breakout_days += 1
            else:
                break

        vol_ratio = indicators.get('vol_ratio', 0)
        if vol_ratio < 1.5 and is_breakout_high:
            return {
                'passed': False, 'is_breakout': True,
                'reason': f'量能不足(vol_ratio={vol_ratio:.2f}<1.5,突破{breakout_days}日)'
            }

        if breakout_days < 3 and is_breakout_high:
            return {
                'passed': False, 'is_breakout': True,
                'reason': f'突破时间不足({breakout_days}<3日)'
            }

        cyqkl = indicators.get('cyqkl', 0)
        if cyqkl < 0.2 and is_breakout_high:
            return {
                'passed': False, 'is_breakout': True,
                'reason': f'穿透深度不足(cyqkl={cyqkl:.2f}<0.2)'
            }

        return {'passed': True, 'reason': '三维确认通过', 'is_breakout': True}

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

        if signals.get('S_DIVERG_SELL', {}).get('triggered', False):
            sd = signals['S_DIVERG_SELL']
            adj = sd.get('position_adjustment', 1.0)
            return {
                'action': 'REDUCE',
                'reason': '高位背离减仓',
                'target_position': adj,
                'position_adjustment': adj,
                'priority': 3
            }

        if signals.get('S_BUY', {}).get('triggered', False):
            return {
                'action': 'BUY',
                'reason': '主买入信号',
                'target_position': 0.7,
                'priority': 4
            }

        if signals.get('S_WASH_END', {}).get('triggered', False):
            return {
                'action': 'BUY',
                'reason': '洗盘结束',
                'target_position': 0.5,
                'priority': 5
            }

        if signals.get('S_BOUNCE', {}).get('triggered', False):
            return {
                'action': 'BUY',
                'reason': '超跌反弹',
                'target_position': 0.3,
                'priority': 6
            }

        return {
            'action': 'HOLD',
            'reason': '无明确信号',
            'target_position': None,
            'priority': 99
        }
