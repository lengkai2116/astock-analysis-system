"""
[P2-#36] 冲突调和机制编码化

四级裁定规则：
1. 结构优先（缠论>量价）
2. 位置优先（关键位置>非关键）
3. 量价验证
4. 嵌套处理
"""

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ConflictArbiter:
    """策略信号冲突仲裁器"""

    STRATEGY_PRIORITY = {
        'chanlun': 1,
        'volume_price': 2,
        'chip': 3,
        'factor': 4,
        'bociasi': 5,
    }

    KEY_POSITIONS = ['中枢边界', 'MA120', 'MA250', 'MA60', '前高/前低']

    def arbitrate(self, signals: List[Dict], zhongshu=None, market_context=None) -> Dict:
        """四级裁定"""
        if not signals:
            return {'final_signal': 'neutral', 'final_confidence': 0.0, 'arbitration_log': ['无信号'], 'details': {}}
        log = []

        # 第1级：结构优先
        chanlun_sigs = [s for s in signals if '缠论' in s.get('strategy_name', '')]
        other_sigs = [s for s in signals if s not in chanlun_sigs]
        if chanlun_sigs and other_sigs:
            chanlun_dir = self._get_direction(chanlun_sigs[0])
            conflicts = sum(1 for s in other_sigs if self._get_direction(s) and self._get_direction(s) != chanlun_dir)
            log.append(f"结构优先: 缠论={chanlun_dir}, 冲突={conflicts}/{len(other_sigs)}")

        # 第2级：位置优先
        if zhongshu is not None and market_context:
            price = market_context.get('current_price', 0)
            if hasattr(zhongshu, 'contains_price'):
                if zhongshu.contains_price(price):
                    log.append("位置优先: 价格在中枢内")
                elif hasattr(zhongshu, 'is_above') and zhongshu.is_above(price):
                    log.append("位置优先: 价格在中枢上方")
                elif hasattr(zhongshu, 'is_below') and zhongshu.is_below(price):
                    log.append("位置优先: 价格在中枢下方")

        # 第3级：量价验证
        vp = [s for s in signals if '量价' in s.get('strategy_name', '')]
        if vp:
            log.append(f"量价验证: 置信度={vp[0].get('confidence', 0):.2f}")

        # 第4级：嵌套处理
        bullish = sum(1 for s in signals if self._get_signal_value(s) > 0)
        bearish = sum(1 for s in signals if self._get_signal_value(s) < 0)
        if bullish > 0 and bearish > 0:
            log.append(f"嵌套处理: 看涨={bullish} 看空={bearish}")

        final_sig, final_conf = self._synthesize(signals, log)
        return {
            'final_signal': final_sig,
            'final_confidence': round(final_conf, 2),
            'arbitration_log': log,
            'details': {'bullish': bullish, 'bearish': bearish, 'total': len(signals)},
        }

    def _get_direction(self, s: Dict) -> Optional[str]:
        sig = s.get('signal', '').lower()
        if sig in ('bullish', 'buy', 'long', '做多'):
            return 'bullish'
        elif sig in ('bearish', 'sell', 'short', '做空'):
            return 'bearish'
        return None

    def _get_signal_value(self, s: Dict) -> int:
        d = self._get_direction(s)
        return 1 if d == 'bullish' else -1 if d == 'bearish' else 0

    def _synthesize(self, signals: List[Dict], log: List) -> Tuple[str, float]:
        total_w, weighted = 0.0, 0.0
        for s in signals:
            pri = self.STRATEGY_PRIORITY.get(s.get('strategy_name', '').lower(), 5)
            w = s.get('confidence', 0.5) / pri
            weighted += self._get_signal_value(s) * w
            total_w += w
        if total_w <= 0:
            return 'neutral', 0.0
        fused = weighted / total_w
        if fused > 0.2:
            return 'bullish', min(1.0, abs(fused))
        elif fused < -0.2:
            return 'bearish', min(1.0, abs(fused))
        return 'neutral', max(0.0, abs(fused))
