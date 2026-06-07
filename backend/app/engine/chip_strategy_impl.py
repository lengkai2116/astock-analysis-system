"""
完整筹码分布策略实现 — V1+V2 全部完成
基于《筹码分布量化策略技术说明书》+ 知识库14概念对齐

版本变更:
  V1: S_DIVERG_SELL/假突破/筹码流动/金字塔建仓 (4方向)
  V2: 资金流向集成/情绪周期/主力测试识别/7种筹码形态/洗盘结束增强 (5方向)
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any, Tuple
import logging
from datetime import datetime, date

from app.data.chip_indicators import ChipIndicators
from app.data.chip_distribution_service import ChipDistributionService

logger = logging.getLogger(__name__)


class TradingPhaseDetector:
    """
    操盘阶段检测器
    识别：建仓期 / 洗盘期 / 拉升期 / 出货期 / 下跌期

    V2改进: 资金流向集成 — 各阶段评分加入 moneyflow 大单维度
    """

    def __init__(self, chip_indicators: ChipIndicators):
        self.chip_indicators = chip_indicators

    def detect_phase(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict,
                    chip_bins_history: Optional[List[List[Dict]]] = None,
                    moneyflow_data: Optional[pd.DataFrame] = None) -> Dict:
        """
        检测当前操盘阶段

        Args:
            kline_data: K线数据
            chip_bins: 筹码分布数据
            indicators: 筹码指标
            chip_bins_history: 历史筹码分布（用于筹码转移方向检测）
            moneyflow_data: 资金流向数据（V2方向5新增）

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

        # 计算资金流向评分（V2方向5）
        moneyflow_score = self._calc_moneyflow_score(moneyflow_data)

        # 计算各阶段得分
        scores = {
            'BUILDING': self._score_building(kline_data, chip_bins, indicators, transfer_info, moneyflow_score),
            'WASHING': self._score_washing(kline_data, chip_bins, indicators, transfer_info, moneyflow_score),
            'RAISING': self._score_raising(kline_data, chip_bins, indicators, transfer_info, moneyflow_score),
            'SHIPPING': self._score_shipping(kline_data, chip_bins, indicators, transfer_info, moneyflow_score),
            'SUPPORT': self._score_support(kline_data, chip_bins, indicators, transfer_info, moneyflow_score)
        }

        best_phase = max(scores.items(), key=lambda x: x[1])
        total_score = sum(scores.values())

        confidence = best_phase[1] / max(total_score, 1)

        return {
            'phase': best_phase[0],
            'confidence': round(confidence, 4),
            'scores': scores,
            'moneyflow_score': moneyflow_score
        }

    def _calc_moneyflow_score(self, moneyflow_data: Optional[pd.DataFrame], period: int = 5) -> Dict:
        """
        计算资金流向评分 (V2方向5)

        Returns:
            {'avg_net_lg': float, 'positive_ratio': float,
             'is_positive_streak': bool, 'is_negative_streak': bool,
             'direction': int}  # 1=净流入, -1=净流出, 0=中性
        """
        default = {
            'avg_net_lg': 0, 'positive_ratio': 0.0,
            'is_positive_streak': False, 'is_negative_streak': False,
            'direction': 0, 'available': False
        }
        if moneyflow_data is None or moneyflow_data.empty:
            return default
        try:
            recent = moneyflow_data.tail(period)
            net_lg = recent['net_lg_amount'].values
            if len(net_lg) == 0:
                return default
            avg_net = float(np.mean(net_lg))
            positive_days = sum(1 for v in net_lg if v > 0)
            return {
                'avg_net_lg': avg_net,
                'positive_ratio': positive_days / len(net_lg),
                'is_positive_streak': bool(all(v > 0 for v in net_lg)),
                'is_negative_streak': bool(all(v < 0 for v in net_lg)),
                'direction': 1 if avg_net > 0 else (-1 if avg_net < 0 else 0),
                'available': True
            }
        except Exception:
            return default

    def _score_building(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict,
                        transfer_info: Optional[Dict] = None,
                        moneyflow_score: Optional[Dict] = None) -> float:
        """建仓期评分"""
        score = 0.0

        if indicators.get('profit_ratio', 0) < 0.4:
            score += 2.0
        if indicators.get('asr', 0) >= 0.7:
            score += 2.0
        conc_status = indicators.get('concentration_status', '')
        if conc_status == '高度集中' or conc_status == '较集中':
            score += 2.0
        if len(kline_data) >= 60:
            closes = kline_data['close'].values
            min_60, max_60 = np.min(closes[-60:]), np.max(closes[-60:])
            if max_60 - min_60 > 0 and (closes[-1] - min_60) / (max_60 - min_60) < 0.4:
                score += 2.0

        # V2方向5: 大单净额持续为正但股价不涨 => 建仓吸筹
        if moneyflow_score and moneyflow_score.get('available'):
            if moneyflow_score['is_positive_streak']:
                closes = kline_data['close'].values
                price_up = (closes[-1] / closes[-min(5, len(closes))] - 1) < 0.03 if len(closes) >= 5 else False
                if price_up:
                    score += 2.0  # 持续净流入但股价不涨 -> 建仓痕迹
                else:
                    score += 1.5  # 持续净流入且慢涨 -> 建仓偏拉升

        return score

    def _score_washing(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict,
                       transfer_info: Optional[Dict] = None,
                       moneyflow_score: Optional[Dict] = None) -> float:
        """洗盘期评分"""
        score = 0.0

        rsi = indicators.get('rsi', 50)
        if 30 <= rsi <= 55:
            score += 2.0
        vol_status = indicators.get('vol_status', '')
        if vol_status in ('缩量', '地量'):
            score += 2.0
        asr = indicators.get('asr', 0)
        if 0.3 <= asr <= 0.6:
            score += 1.5
        ssrp = indicators.get('ssrp', 0)
        if ssrp > 0 and len(kline_data) > 0:
            cp = kline_data['close'].iloc[-1]
            if ssrp * 0.9 < cp < ssrp * 1.05:
                score += 1.5

        if transfer_info is not None:
            tr_type = transfer_info.get('transfer_type', '')
            low_chg = transfer_info.get('low_chips_change', 0)
            if tr_type == '稳定' and low_chg >= -0.02:
                score += 2.0
            elif tr_type == '向下转移' and low_chg > 0:
                score += 2.0

        # V2方向5: 大单净额为负后转正企稳 => 洗盘尾声
        if moneyflow_score and moneyflow_score.get('available'):
            if moneyflow_score['direction'] == 1 and moneyflow_score['positive_ratio'] >= 0.6:
                score += 1.5  # 净流入转正 -> 洗盘结束征兆

        return score

    def _score_raising(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict,
                       transfer_info: Optional[Dict] = None,
                       moneyflow_score: Optional[Dict] = None) -> float:
        """拉升期评分"""
        score = 0.0

        ssrp = indicators.get('ssrp', 0)
        if ssrp > 0 and len(kline_data) > 0:
            cp = kline_data['close'].iloc[-1]
            if cp > ssrp * 1.05:
                score += 2.0
        if indicators.get('profit_ratio', 0) >= 0.6:
            score += 2.0
        vol_status = indicators.get('vol_status', '')
        if vol_status in ('放量', '显著放量', '天量'):
            score += 2.0
        if indicators.get('cyqkl_status', '') in ('强', '很强', '极强'):
            score += 1.5

        if transfer_info is not None:
            tr_type = transfer_info.get('transfer_type', '')
            if tr_type == '向上转移':
                score += 2.0
            elif tr_type == '稳定' and indicators.get('profit_ratio', 0) >= 0.5:
                score += 1.0

        # V2方向5: 大单净额持续为正且放大 => 拉升
        if moneyflow_score and moneyflow_score.get('available'):
            if moneyflow_score['is_positive_streak'] and abs(moneyflow_score['avg_net_lg']) > 0:
                score += 2.0

        return score

    def _score_shipping(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict,
                        transfer_info: Optional[Dict] = None,
                        moneyflow_score: Optional[Dict] = None) -> float:
        """出货期评分"""
        score = 0.0

        profit_ratio = indicators.get('profit_ratio', 0)
        if profit_ratio >= 0.7 and len(kline_data) >= 5:
            closes = kline_data['close'].values
            if closes[-1] < closes[-5]:
                score += 2.5
        vol_status = indicators.get('vol_status', '')
        if vol_status in ('缩量', '地量'):
            score += 2.0
        rsi = indicators.get('rsi', 0)
        if rsi >= 70:
            score += 1.5

        # V2方向5: 大单净额为负且小单为正 => 出货
        if moneyflow_score and moneyflow_score.get('available'):
            if moneyflow_score['is_negative_streak']:
                score += 2.0

        return score

    def _score_support(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict,
                       transfer_info: Optional[Dict] = None,
                       moneyflow_score: Optional[Dict] = None) -> float:
        """下跌支撑期评分"""
        score = 0.0
        if indicators.get('profit_ratio', 0) < 0.35:
            score += 2.0
        if indicators.get('rsi', 50) < 30:
            score += 2.0
        ssrp = indicators.get('ssrp', 0)
        if ssrp > 0 and len(kline_data) > 0:
            cp = kline_data['close'].iloc[-1]
            if cp < ssrp * 0.9:
                score += 2.0
        return score


class ChipDistributionSignalGenerator:
    """
    筹码分布信号生成器
    生成 S_BUY / S_WASH_END / S_BOUNCE / S_SELL / S_WASH_STOP / S_DIVERG_SELL

    V1: 假突破过滤器前置 / S_DIVERG_SELL 改用 detect_rsi_divergence / 金字塔建仓
    V2: 主力测试识别 / 7种筹码形态匹配 / 洗盘结束增强
    """

    def __init__(self, phase_detector: TradingPhaseDetector):
        self.phase_detector = phase_detector
        self.chip_indicators = phase_detector.chip_indicators

    def generate_signals(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                         indicators: Dict, phase_info: Dict, moneyflow_data: Optional[pd.DataFrame] = None) -> Dict:
        """生成完整信号集合"""
        result = {}

        result['S_BUY'] = self._check_s_buy(kline_data, chip_bins, indicators, phase_info)
        result['S_WASH_END'] = self._check_s_wash_end(kline_data, chip_bins, indicators, phase_info)
        result['S_BOUNCE'] = self._check_s_bounce(kline_data, chip_bins, indicators, phase_info)
        result['S_SELL'] = self._check_s_sell(kline_data, chip_bins, indicators, phase_info)
        result['S_WASH_STOP'] = self._check_s_wash_stop(kline_data, chip_bins, indicators, phase_info)
        result['S_DIVERG_SELL'] = self._check_s_diverg_sell(kline_data, chip_bins, indicators, phase_info)

        # V2方向7: 主力测试行为检测 -> 增强S_BUY / S_WASH_END
        test_result = self._detect_mainforce_test(kline_data, chip_bins, indicators)
        result['mainforce_test'] = test_result
        if test_result.get('test_success'):
            # 测试成功 -> 强化买入信号
            if result['S_BUY'].get('triggered'):
                result['S_BUY']['position'] = max(result['S_BUY'].get('position', 0.7), 0.9)
                result['S_BUY']['mainforce_test_boost'] = '测试成功，确认突破'
            elif not result['S_BUY'].get('triggered') and test_result.get('confidence', 0) >= 0.6:
                # 测试成功但其他条件不足，仍可作为参与信号
                result['S_BUY']['triggered'] = True
                result['S_BUY']['position'] = 0.5
                result['S_BUY']['conditions'] = result['S_BUY'].get('conditions', []) + ['✓ 主力测试成功']
                result['S_BUY']['mainforce_test_boost'] = '测试成功'
        if test_result.get('test_failure'):
            # 测试失败 -> 强化洗盘结束（洗盘结束后测试突破）
            if result['S_WASH_END'].get('triggered'):
                result['S_WASH_END']['mainforce_test_boost'] = '测试失败后企稳'
                result['S_WASH_END']['position'] = min(result['S_WASH_END'].get('position', 0.5), 0.5)

        # V2方向8: 7种筹码形态匹配 -> 置信度调整
        chip_patterns = self._match_chip_pattern(chip_bins, kline_data, indicators)
        result['chip_patterns'] = chip_patterns
        for pat in chip_patterns:
            sig = pat.get('target_signal', '')
            boost = pat.get('confidence_boost', 0)
            if sig and boost > 0 and result.get(sig, {}).get('triggered'):
                cur_conf = result[sig].get('confidence', 0.5)
                result[sig]['confidence'] = min(1.0, cur_conf + boost)
                result[sig]['chip_pattern_boost'] = pat.get('pattern_name', '')
                # 仓位提升
                cur_pos = result[sig].get('position', 0.5)
                result[sig]['position'] = min(1.0, cur_pos + boost)

        # 确定最终操作建议
        recommendation = self._combine_signals(result, phase_info, indicators)
        result['recommendation'] = recommendation

        return result

    # ==============================
    # V1: 假突破前置 + S_DIVERG_SELL (已实现)
    # ==============================

    def _check_false_breakout(self, kline_data: pd.DataFrame, indicators: Dict) -> Dict:
        """假突破前置检测 — 三维确认"""
        if kline_data.empty or len(kline_data) < 5:
            return {'passed': True, 'reason': '数据不足', 'is_breakout': False}

        closes = kline_data['close'].values
        latest = float(closes[-1])

        if len(closes) >= 20:
            max_20 = float(np.max(closes[-20:]))
            min_20 = float(np.min(closes[-20:]))
            if max_20 - min_20 <= 0:
                return {'passed': True, 'reason': '价格无波动', 'is_breakout': False}

            is_breakout_high = latest >= max_20 * 0.98
            is_breakout_low = latest <= min_20 * 1.02

            if not is_breakout_high and not is_breakout_low:
                return {'passed': True, 'reason': '非突破状态', 'is_breakout': False}
        else:
            return {'passed': True, 'reason': '数据不足', 'is_breakout': False}

        breakout_level = max_20 * 0.98 if is_breakout_high else min_20 * 1.02

        breakout_days = 0
        for i in range(len(closes) - 1, -1, -1):
            if (is_breakout_high and closes[i] >= breakout_level) or \
               (is_breakout_low and closes[i] <= breakout_level):
                breakout_days += 1
            else:
                break

        vol_ratio = indicators.get('vol_ratio', 0)
        if vol_ratio < 1.5 and is_breakout_high:
            return {'passed': False, 'is_breakout': True,
                    'reason': f'量能不足(vol_ratio={vol_ratio:.2f}<1.5, 突破{breakout_days}日)'}

        if breakout_days < 3 and is_breakout_high:
            return {'passed': False, 'is_breakout': True,
                    'reason': f'突破时间不足({breakout_days}<3日)'}

        cyqkl = indicators.get('cyqkl', 0)
        if cyqkl < 0.2 and is_breakout_high:
            return {'passed': False, 'is_breakout': True,
                    'reason': f'穿透深度不足(cyqkl={cyqkl:.2f}<0.2)'}

        return {'passed': True, 'reason': '三维确认通过', 'is_breakout': True}

    def _check_s_diverg_sell(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                              indicators: Dict, phase_info: Dict) -> Dict:
        """高位背离减仓信号 — 使用 detect_rsi_divergence()"""
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

        if top_div.get('detected', False):
            count = top_div.get('count', 1)

            if count >= 3:
                triggered = True
                position_adjustment = 0.1
                conditions.append(
                    f'✓ 三重顶背离确认 → 减仓至10% '
                    f'(前次RSI{top_div["prev_high_rsi"]:.1f} > 最新RSI{top_div["latest_high_rsi"]:.1f})'
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

    # ==============================
    # V2方向9: 洗盘结束增强 — 均线支撑 / 黄金坑 / 缩量企稳
    # ==============================

    def _check_s_wash_end(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                          indicators: Dict, phase_info: Dict) -> Dict:
        """
        洗盘结束买入信号 S_WASH_END
        条件（V1）:
          1. 操盘阶段=洗盘期
          2. 成交量降至地量
          3. RSI在30-55区间企稳
          4. 收盘价>=低位筹码峰下限（主力成本区）
          5. 当日涨幅>0%且成交量较前日放大>=20%
        条件（V2方向9新增）:
          6. 均线支撑(MA20/MA60)
          7. 黄金坑(V形反转+缩量底部)
          8. 放量下跌转缩量企稳
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

        # === V2方向9新增条件 ===

        # 条件5：均线支撑 — 价格在MA20或MA60附近（±3%）
        ma20 = indicators.get('ma20')
        ma60 = indicators.get('ma60')
        if len(kline_data) > 0:
            cp = float(kline_data['close'].iloc[-1])
            if ma20 is not None and ma60 is not None and ma20 > 0 and ma60 > 0:
                near_ma20 = abs(cp - ma20) / ma20 <= 0.03
                near_ma60 = abs(cp - ma60) / ma60 <= 0.03
                if near_ma20 or near_ma60:
                    conditions.append(f'✓ 均线支撑(MA20={ma20:.2f}, MA60={ma60:.2f})')
                else:
                    conditions.append('✗ 未获均线支撑')
                    all_met = False
            else:
                # 自己算
                closes = kline_data['close'].values
                if len(closes) >= 20:
                    calc_ma20 = np.mean(closes[-20:])
                    near_ma20 = abs(cp - calc_ma20) / calc_ma20 <= 0.03
                    if near_ma20:
                        conditions.append(f'✓ 均线支撑(MA20={calc_ma20:.2f})')
                    else:
                        calc_ma60 = np.mean(closes[-min(60, len(closes)):]) if len(closes) >= 60 else 0
                        near_ma60 = calc_ma60 > 0 and abs(cp - calc_ma60) / calc_ma60 <= 0.03
                        if near_ma60:
                            conditions.append(f'✓ 均线支撑(MA60={calc_ma60:.2f})')
                        else:
                            conditions.append('✗ 未获均线支撑')
                            all_met = False

        # 条件6：黄金坑检测 — V形反转形态（先跌后涨，缩量底部）
        golden_pit = self._detect_golden_pit(kline_data)
        if golden_pit.get('detected'):
            conditions.append(f'✓ 黄金坑形态确认(跌幅{golden_pit["drop_pct"]:.1f}%, 反弹{golden_pit["rebound_pct"]:.1f}%)')
        else:
            conditions.append('✗ 无黄金坑形态')
            all_met = False

        # 条件7：放量下跌转缩量企稳
        volume_stabilize = self._detect_volume_stabilization(kline_data)
        if volume_stabilize.get('detected'):
            conditions.append('✓ 放量下跌转缩量企稳')
        else:
            conditions.append('✗ 量能未企稳')
            all_met = False

        # 金字塔仓位（V1方向4）
        ok_count = sum(1 for c in conditions if c.startswith('✓'))
        position = self._compute_pyramid_position(ok_count, 4, tier_map={3: 0.5, 5: 0.7, 7: 1.0})

        return {
            'triggered': all_met,
            'position': position,
            'conditions': conditions,
            'ok_count': ok_count
        }

    def _detect_golden_pit(self, kline_data: pd.DataFrame, lookback: int = 30) -> Dict:
        """
        黄金坑检测（V2方向9）

        特征:
          1. X日前出现阶段低点（挖坑）
          2. 从低点至坑底跌幅 >= 8%
          3. 坑底缩量（低于均量的50%）
          4. 从低点至今反弹 >= 5%（填坑）
          5. 当前价格仍在坑口下方（未填满坑）
        """
        if kline_data.empty or len(kline_data) < 10:
            return {'detected': False}
        closes = kline_data['close'].values
        volumes = kline_data['vol'].values if 'vol' in kline_data.columns else \
                  kline_data['amount'].values if 'amount' in kline_data.columns else None
        if volumes is None or len(closes) < lookback:
            return {'detected': False}

        window = min(lookback, len(closes))
        recent = closes[-window:]
        vol_recent = volumes[-window:]

        # 找到窗口内的最低点
        min_idx = np.argmin(recent)
        min_price = recent[min_idx]

        # 坑口 = 最低点之前的高点
        pre_high = np.max(recent[:min_idx+1]) if min_idx >= 3 else recent[min_idx]

        drop_pct = (pre_high - min_price) / pre_high * 100
        if drop_pct < 8 or min_idx == len(recent) - 1:
            # 跌幅不足8%或最低点就是最后一天
            return {'detected': False, 'drop_pct': drop_pct}

        # 坑底成交量是否萎缩
        bottom_vol = vol_recent[min_idx]
        avg_vol = np.mean(vol_recent[:max(min_idx, 1)])
        vol_shrink = bottom_vol < avg_vol * 0.5 if avg_vol > 0 else False

        # 从低点至今的反弹幅度
        rebound_pct = (recent[-1] - min_price) / min_price * 100
        rebound_ok = rebound_pct >= 5

        # 是否仍在坑内（未回到坑口）
        still_in_pit = recent[-1] < pre_high * 0.98

        detected = drop_pct >= 8 and vol_shrink and rebound_ok and still_in_pit

        return {
            'detected': detected,
            'drop_pct': drop_pct,
            'rebound_pct': rebound_pct,
            'low_price': min_price,
            'pit_top': pre_high,
            'vol_shrink': vol_shrink
        }

    def _detect_volume_stabilization(self, kline_data: pd.DataFrame, lookback: int = 20) -> Dict:
        """
        放量下跌转缩量企稳检测（V2方向9）

        特征:
          1. 前期有一段放量下跌（跌幅>3%且量>均量*1.3）
          2. 近期转为缩量企稳（量<均量*0.8，价格波动<2%）
        """
        if kline_data.empty or len(kline_data) < 10:
            return {'detected': False}
        closes = kline_data['close'].values
        volumes = kline_data['vol'].values if 'vol' in kline_data.columns else \
                  kline_data['amount'].values if 'amount' in kline_data.columns else None
        if volumes is None:
            return {'detected': False}

        window = min(lookback, len(closes))
        vol_window = volumes[-window:]
        close_window = closes[-window:]

        mid = window // 2
        left_vol = vol_window[:mid]
        right_vol = vol_window[mid:]
        left_close = close_window[:mid]
        right_close = close_window[mid:]

        if len(left_vol) < 3 or len(right_vol) < 3:
            return {'detected': False}

        # 前期：放量下跌
        left_drop = (left_close[0] - left_close[-1]) / left_close[0]
        avg_left_vol = np.mean(left_vol[:2]) if len(left_vol) >= 2 else left_vol[0]
        left_vol_ratio = np.mean(left_vol) / (avg_left_vol + 1e-9)

        # 近期：缩量企稳
        right_vol_ratio = np.mean(right_vol) / (np.mean(left_vol) + 1e-9)
        right_stable = (np.max(right_close) - np.min(right_close)) / np.mean(right_close)

        detected = left_drop > 0.03 and left_vol_ratio > 1.3 and right_vol_ratio < 0.8 and right_stable < 0.02

        return {
            'detected': detected,
            'left_drop': left_drop * 100,
            'left_vol_ratio': left_vol_ratio,
            'right_vol_ratio': right_vol_ratio,
            'right_stability': right_stable
        }

    # ==============================
    # V2方向7: 主力测试识别
    # ==============================

    def _detect_mainforce_test(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                                indicators: Dict, lookback: int = 30) -> Dict:
        """
        主力测试(试盘)行为检测

        特征（知识库依据）:
          - 主力突破前测试抛压，打到一个价位后不参与换手，观察盘面
          - 放量上攻 -> 缩量回落 -> 再次放量突破（测试成功）
          - 放量上攻 -> 缩量回落 -> 无法突破（测试失败）

        检测逻辑:
          1. 找到近N日最高价和最高量（测试动作）
          2. 测试后价格回落，成交量萎缩（观察盘面）
          3. 测试后如果放量突破测试高点 => 成功
          4. 测试后如果无法突破 => 失败
        """
        if kline_data.empty or len(kline_data) < 10:
            return {'detected': False, 'test_success': False, 'test_failure': False}

        closes = kline_data['close'].values
        volumes = kline_data['vol'].values if 'vol' in kline_data.columns else \
                  kline_data['amount'].values if 'amount' in kline_data.columns else None
        if volumes is None:
            return {'detected': False, 'test_success': False, 'test_failure': False}

        window = min(lookback, len(closes))
        close_w = closes[-window:]
        vol_w = volumes[-window:]

        # 找到测试动作（最高点 + 对应放量）
        test_idx = np.argmax(close_w)
        # 测试点必须是窗口的前半段（不能是最近几天），因为测试后需要观察期
        if test_idx >= len(close_w) - 5 or test_idx < 2:
            return {'detected': False, 'test_success': False, 'test_failure': False}

        test_price = close_w[test_idx]
        test_vol = vol_w[test_idx]

        # 测试日必须放量
        avg_vol_before = np.mean(vol_w[:max(test_idx, 1)])
        if test_vol < avg_vol_before * 1.3:
            return {'detected': False, 'test_success': False, 'test_failure': False}

        # 观察期：测试后至当前
        observe = close_w[test_idx + 1:]
        observe_vol = vol_w[test_idx + 1:]

        if len(observe) < 3:
            return {'detected': False, 'test_success': False, 'test_failure': False}

        # 测试后回落
        post_test_low = np.min(observe)
        pullback_pct = (test_price - post_test_low) / test_price
        pullback_ok = pullback_pct > 0.01  # 至少回落1%

        # 观察期缩量
        avg_vol_observe = np.mean(observe_vol)
        vol_shrink = avg_vol_observe < test_vol * 0.6

        if not pullback_ok or not vol_shrink:
            return {'detected': False, 'test_success': False, 'test_failure': False,
                    'reason': '未满足回落或缩量条件'}

        # 判断测试结果：当前价格是否突破测试高点
        current_price = close_w[-1]
        test_success = current_price >= test_price * 0.98
        test_failure = current_price <= post_test_low * 1.02 and \
                       close_w[-1] <= close_w[-min(3, len(close_w))] if len(close_w) >= 3 else False

        # 最近放量突破测试高点？
        recent_vol = vol_w[-min(3, len(vol_w)):]
        recent_close = close_w[-min(3, len(close_w)):]
        recent_breakout = recent_close[-1] >= test_price * 0.98 and \
                          np.mean(recent_vol) > avg_vol_observe * 1.2 if avg_vol_observe > 0 else False

        if recent_breakout:
            test_success = True
            test_failure = False

        confidence = pullback_pct  # 回落幅度作为置信度参考

        return {
            'detected': True,
            'test_success': test_success,
            'test_failure': test_failure,
            'confidence': min(confidence * 10, 0.9),
            'test_price': test_price,
            'current_price': current_price,
            'pullback_pct': pullback_pct * 100,
            'vol_shrink_ratio': avg_vol_observe / (test_vol + 1e-9)
        }

    # ==============================
    # V2方向8: 7种筹码形态匹配
    # ==============================

    def _match_chip_pattern(self, chip_bins: List[Dict], kline_data: pd.DataFrame,
                            indicators: Dict) -> List[Dict]:
        """
        7种经典筹码形态模式匹配

        参考:
          1. 放量突破单峰密集 -> 强化S_BUY
          2. 缩量回踩密集峰 -> 强化S_WASH_END
          3. 缩量振荡快移动 -> 建仓期早期信号
          4. 高点放量单峰 -> 强化S_SELL
          5. 密集峰快移 -> 趋势确认
          6. 回探滞涨 -> 减仓预警
          7. 缩量上穿密集峰 -> 买入信号
        """
        patterns = []

        if not chip_bins or len(chip_bins) < 10 or kline_data.empty or len(kline_data) < 5:
            return patterns

        try:
            peaks = self.chip_indicators.find_peak_positions(chip_bins)
            levels = self.chip_indicators.find_support_resistance_levels(chip_bins)
        except Exception:
            peaks = []
            levels = []

        closes = kline_data['close'].values
        volumes = kline_data['vol'].values if 'vol' in kline_data.columns else \
                  kline_data['amount'].values if 'amount' in kline_data.columns else None
        if volumes is None:
            return patterns

        current_price = float(closes[-1])
        vol_ratio = indicators.get('vol_ratio', 1.0)
        profit_ratio = indicators.get('profit_ratio', 0)
        cyqkl = indicators.get('cyqkl', 0)
        single_peak = len(peaks) <= 1

        # Pattern 1: 放量突破单峰密集
        if single_peak and vol_ratio >= 1.5 and profit_ratio >= 0.6:
            main_peak = peaks[0] if peaks else None
            if main_peak:
                peak_price = main_peak.get('price', 0)
                if peak_price > 0 and current_price >= peak_price * 0.98:
                    patterns.append({
                        'pattern_id': 1,
                        'pattern_name': '放量突破单峰',
                        'description': '放量突破筹码单峰密集区，拉升确认',
                        'target_signal': 'S_BUY',
                        'confidence_boost': 0.15,
                        'direction': 'bullish'
                    })

        # Pattern 2: 缩量回踩密集峰
        if vol_ratio < 1.2 and profit_ratio >= 0.3 and profit_ratio < 0.6:
            if peaks:
                # 价格回踩到主峰附近
                main_peak = peaks[0]
                peak_price = main_peak.get('price', 0)
                if peak_price > 0 and abs(current_price - peak_price) / peak_price <= 0.03:
                    patterns.append({
                        'pattern_id': 2,
                        'pattern_name': '缩量回踩密集',
                        'description': '缩量回踩筹码密集峰，洗盘结束信号',
                        'target_signal': 'S_WASH_END',
                        'confidence_boost': 0.15,
                        'direction': 'bullish'
                    })

        # Pattern 3: 缩量振荡快移动（筹码从分散到快速集中）
        if vol_ratio < 1.0 and cyqkl > 0.3:
            patterns.append({
                'pattern_id': 3,
                'pattern_name': '缩量振荡集中',
                'description': '缩量振荡中筹码快速集中',  # 修正：concentration -> 集中
                'target_signal': 'S_BUY',
                'confidence_boost': 0.10,
                'direction': 'bullish'
            })

        # Pattern 4: 高点放量单峰
        if single_peak and vol_ratio >= 1.5 and profit_ratio >= 0.7:
            patterns.append({
                'pattern_id': 4,
                'pattern_name': '高点放量单峰',
                'description': '高价位放量形成单峰密集，出货预警',
                'target_signal': 'S_SELL',
                'confidence_boost': 0.20,
                'direction': 'bearish'
            })

        # Pattern 5: 密集峰快移（筹码加速转移）
        try:
            transfer_rate = self.chip_indicators.calculate_transfer_rate([chip_bins], window=5)
        except Exception:
            transfer_rate = 0
        if transfer_rate > 0.15:
            direction = 'up' if profit_ratio >= 0.5 else 'down'
            if direction == 'up':
                patterns.append({
                    'pattern_id': 5,
                    'pattern_name': '密集峰快移向上',
                    'description': '筹码密集峰快速上移，拉升趋势确认',
                    'target_signal': 'S_BUY',
                    'confidence_boost': 0.15,
                    'direction': 'bullish'
                })
            else:
                patterns.append({
                    'pattern_id': 5,
                    'pattern_name': '密集峰快移向下',
                    'description': '筹码密集峰快速下移，下跌趋势确认',
                    'target_signal': 'S_SELL',
                    'confidence_boost': 0.15,
                    'direction': 'bearish'
                })

        # Pattern 6: 回探滞涨
        if len(closes) >= 10:
            recent_range = (np.max(closes[-10:]) - np.min(closes[-10:])) / np.mean(closes[-10:])
            if recent_range < 0.05 and profit_ratio >= 0.6:
                # 高位横盘，获利盘多 — 滞涨预警
                patterns.append({
                    'pattern_id': 6,
                    'pattern_name': '回探滞涨',
                    'description': '高位横盘滞涨，警惕出货',
                    'target_signal': 'S_DIVERG_SELL',
                    'confidence_boost': 0.10,
                    'direction': 'bearish'
                })

        # Pattern 7: 缩量上穿密集峰
        if vol_ratio < 1.3 and profit_ratio >= 0.4 and profit_ratio < 0.7:
            if peaks:
                main_peak = peaks[0]
                peak_price = main_peak.get('price', 0)
                if peak_price > 0 and current_price > peak_price * 1.01 and current_price < peak_price * 1.08:
                    patterns.append({
                        'pattern_id': 7,
                        'pattern_name': '缩量上穿密集',
                        'description': '缩量温和上穿筹码密集峰，主力控盘',
                        'target_signal': 'S_BUY',
                        'confidence_boost': 0.20,
                        'direction': 'bullish'
                    })

        return patterns

    # ==============================
    # V1方向4: 金字塔建仓（改写为分档逻辑）
    # ==============================

    def _compute_pyramid_position(self, ok_count: int, total_conditions: int,
                                   tier_map: Dict[int, float] = None) -> float:
        """
        金字塔仓位计算

        Args:
            ok_count: 满足的条件数
            total_conditions: 总条件数
            tier_map: {min_ok: position} 映射，按ok_count升序

        默认:
          <50%满足 -> 0.3（初始试探）
          50-70%   -> 0.5（基础仓位）
          70-90%   -> 0.7（加仓）
          >=90%    -> 1.0（满仓）
        """
        if tier_map is None:
            tier_map = {}

        # 默认3档金字塔
        ratios = [t for t in sorted(tier_map.keys())]
        if not ratios:
            # 默认: <50% = 0.3, 50-70% = 0.5, 70-90% = 0.8, >=90% = 1.0
            ratio = ok_count / max(total_conditions, 1)
            if ratio >= 0.9:
                return 1.0
            elif ratio >= 0.7:
                return 0.8
            elif ratio >= 0.5:
                return 0.5
            else:
                return 0.3

        ok_ratio = ok_count / max(total_conditions, 1)
        for min_ok in sorted(tier_map.keys()):
            if ok_count >= min_ok:
                return tier_map[min_ok]
        return 0.3

    def _combine_signals(self, signals: Dict, phase_info: Optional[Dict] = None,
                         indicators: Optional[Dict] = None) -> Dict:
        """
        综合各信号 -> 金字塔建仓推荐

        V1方向4: 金字塔仓位 — 根据信号满足条件数分档
        """
        # 止损/卖出 > 买入
        if signals.get('S_WASH_STOP', {}).get('triggered', False):
            return {
                'action': 'SELL', 'reason': '洗盘止损',
                'target_position': 0.0, 'priority': 1
            }

        if signals.get('S_SELL', {}).get('triggered', False):
            return {
                'action': 'SELL', 'reason': '主卖出信号',
                'target_position': 0.0, 'priority': 2
            }

        if signals.get('S_DIVERG_SELL', {}).get('triggered', False):
            sd = signals['S_DIVERG_SELL']
            adj = sd.get('position_adjustment', 1.0)
            return {
                'action': 'REDUCE', 'reason': '高位背离减仓',
                'target_position': adj, 'position_adjustment': adj, 'priority': 3
            }

        # 买入信号 -> 金字塔仓位
        if signals.get('S_BUY', {}).get('triggered', False):
            detail = signals['S_BUY']
            conditions = detail.get('conditions', [])
            ok_count = sum(1 for c in conditions if c.startswith('✓'))
            # 含K线形态增强
            total = max(len(conditions), 1)
            boost = 1 if signals.get('chip_patterns') else 0
            ok_count += boost
            position = self._compute_pyramid_position(ok_count, total + boost)
            conf = ok_count / max(total, 1)
            return {
                'action': 'BUY', 'reason': '主买入信号',
                'target_position': round(position, 2),
                'confidence': round(min(conf + 0.1, 1.0), 3),
                'priority': 4
            }

        if signals.get('S_WASH_END', {}).get('triggered', False):
            detail = signals['S_WASH_END']
            conditions = detail.get('conditions', [])
            ok_count = sum(1 for c in conditions if c.startswith('✓'))
            total = max(len(conditions), 1)
            boost = 1 if signals.get('chip_patterns') else 0
            ok_count += boost
            position = self._compute_pyramid_position(ok_count, total + boost,
                                                       tier_map={3: 0.3, 5: 0.5, 7: 0.8})
            conf = ok_count / max(total, 1)
            return {
                'action': 'BUY', 'reason': '洗盘结束',
                'target_position': round(position, 2),
                'confidence': round(min(conf + 0.1, 1.0), 3),
                'priority': 5
            }

        if signals.get('S_BOUNCE', {}).get('triggered', False):
            return {
                'action': 'BUY', 'reason': '超跌反弹',
                'target_position': 0.3, 'priority': 6
            }

        return {
            'action': 'HOLD', 'reason': '无明确信号',
            'target_position': None, 'priority': 99
        }

    # ==============================
    # 以下为 V1 已有信号 (保留原实现)
    # ==============================

    def _check_s_buy(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                     indicators: Dict, phase_info: Dict) -> Dict:
        """主买入信号 S_BUY"""
        conditions = []
        all_met = True

        # 假突破前置过滤
        false_break = self._check_false_breakout(kline_data, indicators)
        if false_break['is_breakout'] and not false_break['passed']:
            return {'triggered': False, 'position': 0.0,
                    'conditions': ['假突破过滤: ' + false_break['reason']]}

        if phase_info.get('phase') == 'RAISING':
            conditions.append('✓ 处于拉升期')
        else:
            conditions.append('✗ 非拉升期')
            all_met = False

        if len(kline_data) >= 60:
            closes = kline_data['close'].values
            max_60 = np.max(closes[-60:])
            if closes[-1] > max_60 * 0.98:
                conditions.append('✓ 价格高位')
            else:
                conditions.append('✗ 未突破')
                all_met = False

        if indicators.get('vol_ratio', 0) >= 1.5:
            conditions.append('✓ 成交量放大')
        else:
            conditions.append('✗ 成交量不足')
            all_met = False

        if indicators.get('cyqkl', 0) >= 0.2:
            conditions.append('✓ CYQKL达标')
        else:
            conditions.append('✗ CYQKL不足')
            all_met = False

        ssrp = indicators.get('ssrp', 0)
        current_price = float(kline_data['close'].iloc[-1]) if len(kline_data) > 0 and ssrp > 0 else 0
        if current_price > 0 and ssrp > 0 and current_price > ssrp:
            conditions.append(f'✓ SSRP穿越确认: {current_price:.2f} > SSRP {ssrp:.2f}')
        else:
            conditions.append('✗ SSRP未突破')
            all_met = False

        if indicators.get('profit_ratio', 0) >= 0.6:
            conditions.append('✓ 获利率达标')
        else:
            conditions.append('✗ 获利率不足')
            all_met = False

        ok_count = sum(1 for c in conditions if c.startswith('✓'))
        position = self._compute_pyramid_position(ok_count, len(conditions))

        return {
            'triggered': all_met,
            'position': position,
            'conditions': conditions,
            'ok_count': ok_count
        }

    def _check_s_bounce(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                        indicators: Dict, phase_info: Dict) -> Dict:
        """超跌反弹买入信号 S_BOUNCE"""
        conditions = []
        all_met = True

        if phase_info.get('phase') == 'SUPPORT':
            conditions.append('✓ 处于支撑期')
        else:
            conditions.append('✗ 非支撑期')
            all_met = False

        rsi = indicators.get('rsi', 50)
        if rsi < 30:
            conditions.append('✓ RSI超卖')
        else:
            conditions.append('✗ RSI未超卖')
            all_met = False

        profit_ratio = indicators.get('profit_ratio', 0)
        if profit_ratio < 0.2:
            conditions.append('✓ 低获利率')
        else:
            conditions.append('✗ 获利率过高')
            all_met = False

        return {
            'triggered': all_met,
            'position': 0.3,
            'conditions': conditions
        }

    def _check_s_sell(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                      indicators: Dict, phase_info: Dict) -> Dict:
        """主卖出信号 S_SELL"""
        conditions = []
        triggered = False

        false_break = self._check_false_breakout(kline_data, indicators)
        if false_break['is_breakout'] and not false_break['passed']:
            return {'triggered': False, 'position': 0.0,
                    'conditions': ['假突破过滤: ' + false_break['reason']]}

        if phase_info.get('phase') == 'SHIPPING':
            conditions.append('✓ 出货期确认')
            triggered = True

        profit_ratio = indicators.get('profit_ratio', 0)
        if profit_ratio >= 0.7 and len(kline_data) >= 5:
            closes = kline_data['close'].values
            if closes[-1] < closes[-5] * 0.95:
                conditions.append('✓ 高位回落')
                triggered = True

        rsi = indicators.get('rsi', 50)
        if rsi >= 80:
            conditions.append('✓ RSI超买')
            triggered = True

        ssrp = indicators.get('ssrp', 0)
        if ssrp > 0 and len(kline_data) >= 3:
            closes = kline_data['close'].values
            if len(closes) >= 2 and closes[-1] < ssrp and closes[-2] < ssrp:
                conditions.append(f'✓ 连续2日低于SSRP({ssrp:.2f})')
                triggered = True

        return {
            'triggered': triggered,
            'position': 0.0,
            'conditions': conditions
        }

    def _check_s_wash_stop(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                           indicators: Dict, phase_info: Dict) -> Dict:
        """洗盘止损信号 S_WASH_STOP"""
        conditions = []
        triggered = False

        ssrp = indicators.get('ssrp', 0)
        if ssrp > 0 and len(kline_data) > 0:
            current_price = kline_data['close'].iloc[-1]
            if current_price < ssrp * 0.9:
                conditions.append('✓ 跌破主力成本')
                triggered = True

        return {
            'triggered': triggered,
            'position': 0.0,
            'conditions': conditions
        }
