"""
[P2-#38] UPF统一实战框架 (Unified Practical Framework)

四层框架：
1. 走势结构层(StructureLayer) — 缠论分析
2. 形态验证层(PatternLayer) — 量价形态
3. 情绪环境层(SentimentLayer) — BOCIASI
4. 因子决策层(FactorLayer) — 多因子评分
"""

import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class LayerResult:
    layer_name: str = ''
    signal: str = 'NEUTRAL'
    confidence: float = 0.0
    details: Dict = field(default_factory=dict)
    raw_data: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class FusedResult:
    signal: str = 'NEUTRAL'
    confidence: float = 0.0
    layer_results: List[LayerResult] = field(default_factory=list)
    fused_detail: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            'signal': self.signal,
            'confidence': self.confidence,
            'layers': [lr.to_dict() for lr in self.layer_results],
            'fused_detail': self.fused_detail,
        }


class UPFEngine:
    LAYER_WEIGHTS = {'structure': 0.30, 'pattern': 0.25, 'sentiment': 0.20, 'factor': 0.25}

    def evaluate_all(self, context: Dict) -> FusedResult:
        layers = [
            ('structure', self._evaluate_structure, context),
            ('pattern', self._evaluate_pattern, context),
            ('sentiment', self._evaluate_sentiment, context),
            ('factor', self._evaluate_factor, context),
        ]
        results = []
        for name, method, ctx in layers:
            try:
                results.append(method(ctx))
            except Exception as e:
                logger.warning(f"UPF {name}异常: {e}")
                results.append(LayerResult(layer_name=name, signal='NEUTRAL', confidence=0.0, details={'error': str(e)}))
        fused_sig, fused_conf = self._weighted_fuse(results)
        return FusedResult(
            signal=fused_sig, confidence=round(fused_conf, 2),
            layer_results=results,
            fused_detail={'layer_weights': self.LAYER_WEIGHTS, 'weighted_score': round(fused_conf, 2)},
        )

    def _evaluate_structure(self, ctx: Dict) -> LayerResult:
        c = ctx.get('chanlun_result', {})
        sig = c.get('signal', 'NEUTRAL').upper() if isinstance(c, dict) else 'NEUTRAL'
        conf = float(c.get('confidence', 0.3)) if isinstance(c, dict) else 0.3
        return LayerResult(layer_name='structure', signal=sig, confidence=conf, details={'source': 'chanlun'})

    def _evaluate_pattern(self, ctx: Dict) -> LayerResult:
        vp = ctx.get('volume_price_result', {})
        sig = vp.get('signal', 'NEUTRAL').upper() if isinstance(vp, dict) else 'NEUTRAL'
        conf = float(vp.get('confidence', 0.3)) if isinstance(vp, dict) else 0.3
        return LayerResult(layer_name='pattern', signal=sig, confidence=conf, details={'source': 'volume_price'})

    def _evaluate_sentiment(self, ctx: Dict) -> LayerResult:
        bs = ctx.get('bociasi_signal', {})
        sig = bs.get('signal', 'NEUTRAL').upper() if isinstance(bs, dict) else 'NEUTRAL'
        conf = float(bs.get('confidence', 0.3)) if isinstance(bs, dict) else 0.3
        return LayerResult(layer_name='sentiment', signal=sig, confidence=conf, details={'source': 'bociasi'})

    def _evaluate_factor(self, ctx: Dict) -> LayerResult:
        fr = ctx.get('factor_result', {})
        if isinstance(fr, dict):
            score = fr.get('score', 0)
            sig = 'BULLISH' if score > 0 else 'BEARISH' if score < 0 else 'NEUTRAL'
            conf = min(1.0, abs(score) / 100)
        else:
            sig, conf = 'NEUTRAL', 0.3
        return LayerResult(layer_name='factor', signal=sig, confidence=conf, details={'source': 'factor'})

    def _weighted_fuse(self, results: List[LayerResult]) -> tuple:
        val_map = {'BULLISH': 1, 'BEARISH': -1, 'NEUTRAL': 0}
        total_w, weighted_v = 0.0, 0.0
        for r in results:
            w = self.LAYER_WEIGHTS.get(r.layer_name, 0.2)
            weighted_v += val_map.get(r.signal, 0) * r.confidence * w
            total_w += w
        if total_w <= 0:
            return 'NEUTRAL', 0.0
        fv = weighted_v / total_w
        sig = 'BULLISH' if fv > 0.15 else 'BEARISH' if fv < -0.15 else 'NEUTRAL'
        return sig, abs(fv)
