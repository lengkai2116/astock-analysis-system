"""
[P2-#39] UIDF统一投资决策框架 (Unified Investment Decision Framework)

与UPF互补，增加AI解读层的标准接口规范
"""

import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
import datetime

logger = logging.getLogger(__name__)


@dataclass
class AIInterpretInput:
    ts_code: str = ''
    stock_name: str = ''
    upf_result: Optional[Dict] = None
    status_recognition: Optional[Dict] = None
    market_context: Optional[Dict] = None
    signals: List[Dict] = field(default_factory=list)


@dataclass
class AIInterpretOutput:
    operation_plan: str = ''
    entry_range: Dict = field(default_factory=lambda: {'lower': 0.0, 'upper': 0.0})
    stop_loss: float = 0.0
    target: float = 0.0
    risk_warning: str = ''
    analysis_summary: str = ''
    confidence: float = 0.0

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class DecisionResult:
    signal: str = 'NEUTRAL'
    confidence: float = 0.0
    ai_interpret: Optional[AIInterpretOutput] = None
    decision_detail: Dict = field(default_factory=dict)
    timestamp: str = ''

    def to_dict(self) -> Dict:
        d = {'signal': self.signal, 'confidence': self.confidence,
             'decision_detail': self.decision_detail, 'timestamp': self.timestamp}
        if self.ai_interpret:
            d['ai_interpret'] = self.ai_interpret.to_dict()
        return d


class UIDFEngine:
    def consolidate(self, upf_result: Optional[Dict] = None, ai_output: Optional[Dict] = None) -> Dict:
        if not upf_result and not ai_output:
            return DecisionResult(signal='NEUTRAL', confidence=0.0, decision_detail={'error': '无输入'}).to_dict()

        upf_sig = upf_result.get('signal', 'NEUTRAL') if upf_result else 'NEUTRAL'
        upf_conf = upf_result.get('confidence', 0.0) if upf_result else 0.0

        ai_sig = 'NEUTRAL'
        ai_conf = 0.0
        if ai_output:
            plan = ai_output.get('operation_plan', '')
            if '做多' in plan or '买入' in plan:
                ai_sig = 'BULLISH'
            elif '做空' in plan or '卖出' in plan:
                ai_sig = 'BEARISH'
            ai_conf = ai_output.get('confidence', 0.0)

        if ai_conf > 0:
            val_map = {'BULLISH': 1, 'BEARISH': -1, 'NEUTRAL': 0}
            fv = val_map.get(upf_sig, 0) * upf_conf * 0.6 + val_map.get(ai_sig, 0) * ai_conf * 0.4
            fc = upf_conf * 0.6 + ai_conf * 0.4
            sig = 'BULLISH' if fv > 0.1 else 'BEARISH' if fv < -0.1 else 'NEUTRAL'
        else:
            sig, fc = upf_sig, upf_conf

        interpret = AIInterpretOutput()
        if ai_output:
            interpret = AIInterpretOutput(
                operation_plan=ai_output.get('operation_plan', ''),
                entry_range=ai_output.get('entry_range', {'lower': 0, 'upper': 0}),
                stop_loss=ai_output.get('stop_loss', 0.0),
                target=ai_output.get('target', 0.0),
                risk_warning=ai_output.get('risk_warning', ''),
                analysis_summary=ai_output.get('analysis_summary', ''),
                confidence=ai_output.get('confidence', 0.0),
            )

        decision = DecisionResult(
            signal=sig, confidence=round(fc, 2), ai_interpret=interpret,
            decision_detail={
                'upf_signal': upf_sig, 'upf_confidence': round(upf_conf, 2),
                'ai_signal': ai_sig, 'ai_confidence': round(ai_conf, 2),
                'fusion_mode': 'UPF+AI' if ai_conf > 0 else 'UPF_only',
            },
            timestamp=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        )
        return decision.to_dict()

    def consolidate_with_conflicts(self, upf_result=None, verification_chains=None,
                                    conflicts_for_ai=None, ai_mode="summary_only",
                                    ai_arbitration=None):
        """Three-mode decision based on verification chain quality."""
        if ai_mode == "summary_only":
            if upf_result:
                sig = upf_result.get("signal", "NEUTRAL")
                conf = min(upf_result.get("confidence", 0.5) * 1.05, 1.0)
                return DecisionResult(signal=sig, confidence=round(conf, 2),
                    decision_detail={"mode": "summary_only", "chain_quality": "high"}).to_dict()
        elif ai_mode == "arbitrate_conflicts":
            has_arbitration = ai_arbitration is not None and len(conflicts_for_ai or []) > 0
            if has_arbitration:
                adj = sum(a.get("confidence_adjustment", 0) for a in ai_arbitration)
                sig = "BULLISH" if adj > 0.1 else "BEARISH" if adj < -0.1 else "NEUTRAL"
                conf = min(0.5 + abs(adj), 1.0)
            else:
                sig = "NEUTRAL"
                conf = 0.3
            return DecisionResult(signal=sig, confidence=round(conf, 2),
                decision_detail={"mode": "arbitrate_conflicts",
                    "unresolved_conflicts": len(conflicts_for_ai or []),
                    "has_arbitration": has_arbitration}).to_dict()
        else:
            return DecisionResult(signal="NEUTRAL", confidence=0.2,
                decision_detail={"mode": "full_analysis", "requires_full_ai": True}).to_dict()

    def build_ai_context(self, upf_result=None, signals=None) -> AIInterpretInput:
        return AIInterpretInput(upf_result=upf_result, signals=signals or [])
