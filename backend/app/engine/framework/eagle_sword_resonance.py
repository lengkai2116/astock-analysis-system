"""
EagleSwordResonance — "鹰眼大宝剑" 双系统共振模型

鹰眼系统 (Eagle Eye — Trend System)
    方向: chanlun_result.trend.direction (up/down/ranging)
    强度: volume_price_signal 的 MA 排列 + 格兰维尔信号

大宝剑系统 (Big Sword — Sentiment System)
    情绪: bociasi_quick + bociasi_slow 聚合
    拥挤度: crowding_factor

共振判定: 双系统交叉表 → 统一买卖信号
"""

from typing import Dict, List, Optional


# ──────────────────────────────────────────────
# 共振判定表 (action, base_confidence)
# ──────────────────────────────────────────────
_RESONANCE_TABLE: Dict[str, Dict[str, tuple]] = {
    # eagle_state → {sword_state: (action, base_conf)}
    "UP": {
        "BULLISH":    ("BUY",          0.85),
        "NEUTRAL":    ("WATCH_BUY",    0.60),
        "BEARISH":    ("CONFLICT",     0.30),
    },
    "RANGING": {
        "BULLISH":    ("CAUTIOUS_BUY", 0.50),
        "NEUTRAL":    ("NEUTRAL",      0.20),
        "BEARISH":    ("CAUTIOUS_SELL", 0.50),
    },
    "DOWN": {
        "BULLISH":    ("CONFLICT",     0.30),
        "NEUTRAL":    ("WATCH_SELL",   0.60),
        "BEARISH":    ("SELL",         0.85),
    },
}

# 兜底
_FALLBACK_ACTION = ("NEUTRAL", 0.15)


class EagleSwordResonance:
    """
    "鹰眼大宝剑" 双系统共振模型

    鹰眼 = 趋势系统（缠论方向 + 量价强度）
    大宝剑 = 情绪系统（BOCIASI 快慢线 + 拥挤度）
    """

    # ──────────────
    # 鹰眼系统
    # ──────────────

    @staticmethod
    def _eagle_trend_direction(chanlun_result: Dict) -> str:
        """
        从缠论结果提取趋势方向

        Args:
            chanlun_result: ChanlunAnalyzer.analyze() 的返回 dict,
                            包含键 'trend' (str), 'segments' (List), 'zhongshu' (List)

        Returns:
            'UP' | 'DOWN' | 'RANGING' | 'UNKNOWN'
        """
        trend = chanlun_result.get("trend", "unknown")
        if trend == "up":
            return "UP"
        if trend == "down":
            return "DOWN"

        segments = chanlun_result.get("segments", [])
        # 平均笔数低 + 无中枢 → RANGING
        if not segments:
            return "RANGING"

        zhongshu_list = chanlun_result.get("zhongshu", [])
        if not zhongshu_list:
            return "RANGING"

        return "RANGING"

    @staticmethod
    def _eagle_trend_strength(volume_price_signal: Dict) -> float:
        """
        从量价信号提取趋势强度 (0.0 ~ 1.0)

        考量因素:
          - MA 排列 (多头发散 / 空头发散 / 交叉 / 粘合)
          - 格兰维尔信号 (buy1~4, sell1~4)
          - 量价关系置信度

        Args:
            volume_price_signal: volume_price_strategy 的 to_output_dict() 结果

        Returns:
            float: 0.0 ~ 1.0
        """
        strength = 0.5  # 中性基准

        # --- MA 排列 ---
        status = volume_price_signal.get("status_recognition", {})
        trend = status.get("trend", {})
        direction = trend.get("direction", "")
        ma_stage = trend.get("stage", "")
        strength_label = trend.get("strength", "")

        # 趋势方向和力度
        if direction == "up" and strength_label in ("strong", "moderate"):
            strength += 0.15
        elif direction == "down" and strength_label in ("strong", "moderate"):
            strength -= 0.15

        # --- 格兰维尔信号 ---
        evidence = volume_price_signal.get("evidence", [])
        granville_buy_count = sum(1 for e in evidence if "格兰维尔" in e and "买" in e)
        granville_sell_count = sum(1 for e in evidence if "格兰维尔" in e and "卖" in e)

        if granville_buy_count > 0:
            strength += min(0.20, granville_buy_count * 0.10)
        if granville_sell_count > 0:
            strength -= min(0.20, granville_sell_count * 0.10)

        # --- 量价置信度 ---
        conf = volume_price_signal.get("confidence", 0.5)
        if conf > 0.6:
            strength += 0.10
        elif conf < 0.3:
            strength -= 0.10

        return max(0.0, min(1.0, strength))

    @staticmethod
    def _eagle_granville_signals(volume_price_signal: Dict) -> List[str]:
        """提取格兰维尔信号列表"""
        evidence = volume_price_signal.get("evidence", [])
        return [e for e in evidence if "格兰维尔" in e]

    # ──────────────
    # 大宝剑系统
    # ──────────────

    @staticmethod
    def _sword_sentiment(bociasi_quick: Dict, bociasi_slow: Dict) -> str:
        """
        聚合快慢线情绪信号

        Args:
            bociasi_quick:  BociasiQuickLine.evaluate() 返回
            bociasi_slow:   BociasiSlowLine.evaluate() 返回

        Returns:
            'BULLISH' | 'BEARISH' | 'NEUTRAL'
        """
        quick_signal = bociasi_quick.get("signal", "NEUTRAL")
        quick_conf = bociasi_quick.get("confidence", 0.0)

        slow_signal = bociasi_slow.get("signal", "NEUTRAL")
        slow_conf = bociasi_slow.get("confidence", 0.0)

        # 加权投票: 快线权重 0.6, 慢线权重 0.4
        bullish_score = 0.0
        bearish_score = 0.0

        if quick_signal == "BUY":
            bullish_score += 0.6 * quick_conf
        elif quick_signal == "NEUTRAL":
            pass  # 不贡献分数
        # quick 没有 BEARISH，只有 BUY/WATCH/NEUTRAL，WATCH 按中性处理

        if slow_signal == "BULLISH":
            bullish_score += 0.4 * slow_conf
        elif slow_signal == "BEARISH":
            bearish_score += 0.4 * slow_conf

        if bullish_score > bearish_score and bullish_score >= 0.20:
            return "BULLISH"
        if bearish_score > bullish_score and bearish_score >= 0.20:
            return "BEARISH"
        return "NEUTRAL"

    @staticmethod
    def _sword_crowding_warning(crowding_factor: Dict) -> bool:
        """
        拥挤度预警

        Args:
            crowding_factor: crowding_factor 模块的输出 dict,
                             应包含 'crowding_level' (str) 或 'risk_notes'

        Returns:
            True if 拥挤度过高
        """
        level = crowding_factor.get("crowding_level", "LOW")
        return level in ("HIGH", "EXTREME")

    @staticmethod
    def _sword_sentiment_strength(bociasi_quick: Dict, bociasi_slow: Dict) -> float:
        """情绪强度 0.0 ~ 1.0"""
        quick_conf = bociasi_quick.get("confidence", 0.0)
        slow_conf = bociasi_slow.get("confidence", 0.0)
        return round((quick_conf * 0.6 + slow_conf * 0.4), 2)

    # ──────────────
    # 共振判定
    # ──────────────

    def evaluate(
        self,
        chanlun_result: Dict,
        volume_price_signal: Dict,
        bociasi_quick: Dict,
        bociasi_slow: Dict,
        crowding: Dict,
        market_state: str = "UNKNOWN",
    ) -> Dict:
        """
        双系统共振判定

        Args:
            chanlun_result:     缠论分析结果 dict
            volume_price_signal: 量价分析结果 dict (to_output_dict 格式)
            bociasi_quick:       BOCIASI 快线结果 dict
            bociasi_slow:        BOCIASI 慢线结果 dict
            crowding:            拥挤度结果 dict
            market_state:        大盘状态 ('BULL', 'BEAR', 'RANGING', 'UNKNOWN')

        Returns:
            {
                'action': str,
                'confidence': float,
                'eagle_system': {...},
                'sword_system': {...},
                'resonance_detail': {...},
                'signal_label': str,
                'risk_notes': List[str],
            }
        """
        # --- 鹰眼系统 ---
        eagle_direction = self._eagle_trend_direction(chanlun_result)
        eagle_strength = self._eagle_trend_strength(volume_price_signal)
        granville_signals = self._eagle_granville_signals(volume_price_signal)

        # --- 大宝剑系统 ---
        sword_sentiment = self._sword_sentiment(bociasi_quick, bociasi_slow)
        crowding_warning = self._sword_crowding_warning(crowding)
        sentiment_strength = self._sword_sentiment_strength(bociasi_quick, bociasi_slow)

        # --- 共振查表 ---
        eagle_routing = _RESONANCE_TABLE.get(eagle_direction, {})
        action, base_conf = eagle_routing.get(
            sword_sentiment, _FALLBACK_ACTION
        )

        # --- 置信度微调 ---
        confidence = base_conf
        risk_notes: List[str] = []

        # 鹰眼强度修正
        if eagle_strength > 0.7:
            confidence += 0.05
        elif eagle_strength < 0.3:
            confidence -= 0.05

        # 情绪强度修正
        if sentiment_strength > 0.65:
            confidence += 0.05
        elif sentiment_strength < 0.25:
            confidence -= 0.05

        # 拥挤度预警
        if crowding_warning:
            confidence -= 0.10
            risk_notes.append("拥挤度过高，警惕反转风险")

        # 大盘状态修正
        if market_state == "BEAR" and action in ("BUY", "WATCH_BUY", "CAUTIOUS_BUY"):
            confidence -= 0.10
            risk_notes.append("大盘偏空，多头信号降权")
        elif market_state == "BULL" and action in ("SELL", "WATCH_SELL", "CAUTIOUS_SELL"):
            confidence -= 0.10
            risk_notes.append("大盘偏多，空头信号降权")

        # 格兰维尔反向信号修正
        has_buy_granville = any("买" in g for g in granville_signals)
        has_sell_granville = any("卖" in g for g in granville_signals)
        if has_buy_granville and action in ("SELL", "WATCH_SELL"):
            confidence -= 0.05
            risk_notes.append("格兰维尔买点与空头方向冲突")
        if has_sell_granville and action in ("BUY", "WATCH_BUY"):
            confidence -= 0.05
            risk_notes.append("格兰维尔卖点与多头方向冲突")

        confidence = max(0.0, min(1.0, round(confidence, 2)))

        # --- 信号标签 ---
        signal_label = self._signal_label(action, eagle_direction, sword_sentiment)

        eagle_state = f"{eagle_direction}(strength={eagle_strength:.2f})"
        sword_state = f"{sword_sentiment}(strength={sentiment_strength:.2f})"

        return {
            "action": action,
            "confidence": confidence,
            "eagle_system": {
                "direction": eagle_direction,
                "strength": eagle_strength,
                "granville_signals": granville_signals,
            },
            "sword_system": {
                "sentiment": sword_sentiment,
                "crowding_warning": crowding_warning,
                "sentiment_strength": sentiment_strength,
            },
            "resonance_detail": {
                "eagle_state": eagle_state,
                "sword_state": sword_state,
                "resonant": action not in ("CONFLICT", "NEUTRAL"),
            },
            "signal_label": signal_label,
            "risk_notes": risk_notes,
        }

    # ──────────────
    # 辅助
    # ──────────────

    @staticmethod
    def _signal_label(action: str, eagle_dir: str, sword_sent: str) -> str:
        """生成中文信号标签"""
        labels = {
            "BUY":           "共振买入",
            "SELL":          "共振卖出",
            "WATCH_BUY":     "关注买入",
            "WATCH_SELL":    "关注卖出",
            "CAUTIOUS_BUY":  "谨慎买入",
            "CAUTIOUS_SELL": "谨慎卖出",
            "CONFLICT":      "信号冲突",
            "NEUTRAL":       "无明确信号",
        }
        label = labels.get(action, action)
        if action == "CONFLICT":
            label += f" (鹰眼={eagle_dir}, 大宝剑={sword_sent})"
        return label


def evaluate(
    chanlun_result: Dict,
    volume_price_signal: Dict,
    bociasi_quick: Dict,
    bociasi_slow: Dict,
    crowding: Dict,
    market_state: str = "UNKNOWN",
) -> Dict:
    """
    模块级便捷函数: 单次鹰眼大宝剑共振判定

    用法::
        from app.engine.framework.eagle_sword_resonance import evaluate
        result = evaluate(
            chanlun_result=chanlun_analysis,
            volume_price_signal=vp_signal,
            bociasi_quick=quick_result,
            bociasi_slow=slow_result,
            crowding=crowding_result,
            market_state='RANGING',
        )
    """
    return EagleSwordResonance().evaluate(
        chanlun_result=chanlun_result,
        volume_price_signal=volume_price_signal,
        bociasi_quick=bociasi_quick,
        bociasi_slow=bociasi_slow,
        crowding=crowding,
        market_state=market_state,
    )
