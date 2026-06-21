"""
[P2-#37] 形态量化中枢v0.1

alpha(缠论结构) + beta(量价形态) 二维融合：
alpha=0.55, beta=0.45 (经验权重，非回测)
"""

import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class MorphoZhongshuFusion:
    ALPHA_WEIGHT = 0.55
    BETA_WEIGHT = 0.45

    def fuse(self, chanlun_signal: Optional[Dict] = None,
             volume_price_signal: Optional[Dict] = None) -> Dict:
        if not chanlun_signal and not volume_price_signal:
            return {'signal': 'NEUTRAL', 'confidence': 0.0, 'fusion_detail': {'error': '无信号'}}

        alpha_sig, alpha_conf = self._extract(chanlun_signal)
        beta_sig, beta_conf = self._extract(volume_price_signal)

        if alpha_sig == 'NEUTRAL' or alpha_conf <= 0:
            return {'signal': beta_sig, 'confidence': beta_conf * self.BETA_WEIGHT,
                    'fusion_detail': {'mode': 'beta_only', 'reason': '无缠论信号'}}
        if beta_sig == 'NEUTRAL' or beta_conf <= 0:
            return {'signal': alpha_sig, 'confidence': alpha_conf * self.ALPHA_WEIGHT,
                    'fusion_detail': {'mode': 'alpha_only', 'reason': '无量价信号'}}

        alpha_val = 1 if alpha_sig == 'BULLISH' else (-1 if alpha_sig == 'BEARISH' else 0)
        beta_val = 1 if beta_sig == 'BULLISH' else (-1 if beta_sig == 'BEARISH' else 0)
        fused_val = alpha_val * self.ALPHA_WEIGHT + beta_val * self.BETA_WEIGHT
        fused_conf = alpha_conf * self.ALPHA_WEIGHT + beta_conf * self.BETA_WEIGHT

        if alpha_val * beta_val > 0:
            fused_conf = min(1.0, fused_conf + 0.2)
            mode = '增强(同向)'
        elif alpha_val * beta_val < 0:
            fused_conf = max(0.1, fused_conf - 0.1)
            mode = '冲突(反向)'
        else:
            mode = '偏倚(一方中性)'

        if fused_val > 0.1:
            final_signal = 'BULLISH'
        elif fused_val < -0.1:
            final_signal = 'BEARISH'
        else:
            final_signal = 'NEUTRAL'

        return {
            'signal': final_signal,
            'confidence': round(fused_conf, 2),
            'fusion_detail': {
                'mode': mode,
                'alpha': {'signal': alpha_sig, 'confidence': round(alpha_conf, 2)},
                'beta': {'signal': beta_sig, 'confidence': round(beta_conf, 2)},
                'alpha_weight': self.ALPHA_WEIGHT,
                'beta_weight': self.BETA_WEIGHT,
                'fused_value': round(fused_val, 3),
            },
        }

    def _extract(self, signal: Optional[Dict]) -> Tuple[str, float]:
        if not signal:
            return 'NEUTRAL', 0.0
        sig = signal.get('signal', 'NEUTRAL')
        conf = signal.get('confidence', 0.3)
        return sig.upper(), float(conf)
