"""
[P2-#40] 状态依赖因子合成

根据市场状态动态调整因子权重矩阵
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class StateDependentFactorWeight:
    WEIGHT_MATRIX = {
        'TRENDING_BULL': {
            'momentum': 0.35, 'reversal': 0.15, 'sentiment': 0.25, 'chip': 0.25,
            'description': '牛市偏动量',
        },
        'TRENDING_BEAR': {
            'momentum': 0.10, 'reversal': 0.40, 'sentiment': 0.20, 'chip': 0.30,
            'description': '熊市偏防御(反转)',
        },
        'RANGING': {
            'momentum': 0.20, 'reversal': 0.30, 'sentiment': 0.20, 'chip': 0.30,
            'description': '震荡市均衡偏反转',
        },
        'HIGH_VOL': {
            'momentum': 0.20, 'reversal': 0.20, 'sentiment': 0.40, 'chip': 0.20,
            'description': '高波动偏情绪',
        },
        'MOMENTUM': {
            'momentum': 0.60, 'reversal': 0.05, 'sentiment': 0.20, 'chip': 0.15,
            'description': 'Momentum phase',
        },
        'MEAN_REV': {
            'momentum': 0.05, 'reversal': 0.65, 'sentiment': 0.15, 'chip': 0.15,
            'description': 'Mean reversion phase',
        },
        'BOX': {
            'momentum': 0.10, 'reversal': 0.30, 'sentiment': 0.20, 'chip': 0.40,
            'description': 'Box range phase',
        },
        'MACRO': {
            'momentum': 0.15, 'reversal': 0.15, 'sentiment': 0.50, 'chip': 0.20,
            'description': 'Macro event phase',
        },
        'WOLF': {
            'momentum': 0.05, 'reversal': 0.50, 'sentiment': 0.25, 'chip': 0.20,
            'description': 'Panic sell phase',
        },
        'EAGLE': {
            'momentum': 0.45, 'reversal': 0.15, 'sentiment': 0.20, 'chip': 0.20,
            'description': 'Healthy bull phase',
        },
    }
    DEFAULT_WEIGHTS = {
        'momentum': 0.25, 'reversal': 0.25, 'sentiment': 0.25, 'chip': 0.25,
        'description': '默认等权',
    }

    def get_weights(self, market_state: Optional[str] = None) -> Dict:
        if market_state and market_state in self.WEIGHT_MATRIX:
            return dict(self.WEIGHT_MATRIX[market_state])
        return dict(self.DEFAULT_WEIGHTS)

    def compute_weighted_score(self, factor_scores: Dict[str, float],
                                market_state: Optional[str] = None) -> Dict:
        weights = self.get_weights(market_state)
        weighted_sum = sum(factor_scores.get(k, 0) * w for k, w in weights.items() if k != 'description')
        total_w = sum(w for k, w in weights.items() if k != 'description')

        if total_w <= 0:
            return {'score': 0.0, 'signal': 'NEUTRAL', 'confidence': 0.0, 'weight_detail': weights}
        final_score = weighted_sum / total_w
        if final_score > 0.2:
            signal = 'BULLISH'
        elif final_score < -0.2:
            signal = 'BEARISH'
        else:
            signal = 'NEUTRAL'
        return {
            'score': round(final_score, 3), 'signal': signal,
            'confidence': round(min(1.0, abs(final_score)), 2),
            'weight_detail': weights, 'market_state': market_state or 'UNKNOWN',
        }

    def list_available_states(self) -> List[str]:
        return list(self.WEIGHT_MATRIX.keys())

    def compare_weights(self, state_a: str, state_b: str) -> Dict:
        wa = self.get_weights(state_a)
        wb = self.get_weights(state_b)
        diffs = {k: round(wa.get(k, 0) - wb.get(k, 0), 2) for k in ['momentum', 'reversal', 'sentiment', 'chip']}
        return {'state_a': state_a, 'state_b': state_b, 'differences': diffs}
