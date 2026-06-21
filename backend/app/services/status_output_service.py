"""
StatusOutputService — 多策略现状识别聚合服务

接收 signal_computation_service 返回的信号列表（每个含 status_recognition 字段），
输出聚合后的统一现状视图，供前端仪表盘 / 监控面板使用。
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple


@dataclass
class VerificationChainResult:
    chain_id: str = ''
    chain_name: str = ''
    passed: bool = False
    confidence_multiplier: float = 1.0
    conflict_detail: str = ''
    evidence: list = field(default_factory=list)


class StatusOutputService:
    """聚合各策略的 status_recognition 字段，输出统一现状视图"""

    # 风险等级排序（索引越小风险越高）
    RISK_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

    def aggregate(self, signals: List[Dict]) -> Dict:
        """主入口 — 输入信号列表，输出聚合后的统一现状视图

        Args:
            signals: signal_computation_service 返回的信号列表，
                     每个元素须包含 status_recognition 字段（可为 None）

        Returns:
            聚合后的现状视图 dict
        """
        if not signals:
            return self._empty_result()

        # 提取有效的 status_recognition
        status_list = [
            sig.get("status_recognition", {}) or {}
            for sig in signals
            if sig and sig.get("status_recognition")
        ]

        if not status_list:
            return self._empty_result()

        return {
            "state_consensus": self._state_consensus(status_list),
            "risk_aggregation": self._aggregate_risk(status_list),
            "momentum_consensus": self._momentum_consensus(status_list),
            "key_levels": self._aggregate_key_levels(status_list),
            "strategy_count": len(status_list),
            "strategies_detail": self._strategies_detail(signals, status_list),
        }

    # ──────────────────────────────────────────────
    # 内部方法
    # ──────────────────────────────────────────────

    def _state_consensus(self, status_list: List[Dict]) -> Dict:
        """判定各策略状态共识

        Returns:
            {
                "state": "ACCUMULATING" | "DISTRIBUTING" | "RANGING" | "UNKNOWN",
                "consensus_pct": 0.0 ~ 1.0,       # 占多数的状态占比
                "distribution": {"ACCUMULATING": N, ...}  # 各状态计数
            }
        """
        distribution = self._count_state_distribution(status_list)
        total = len(status_list)

        if total == 0:
            return {"state": "UNKNOWN", "consensus_pct": 0.0, "distribution": {}}

        # 找出现次数最多的状态
        majority_state = max(distribution, key=distribution.get)
        consensus_pct = round(distribution[majority_state] / total, 4)

        return {
            "state": majority_state,
            "consensus_pct": consensus_pct,
            "distribution": distribution,
        }

    def _risk_aggregation(self, status_list: List[Dict]) -> Dict:
        """聚合最高风险等级（别名）
        Deprecated: 用 _aggregate_risk 替代，保留以兼容旧调用
        """
        return self._aggregate_risk(status_list)

    def _aggregate_risk(self, status_list: List[Dict]) -> Dict:
        """聚合最高风险等级

        取所有策略中的最高风险等级：HIGH > MEDIUM > LOW

        Returns:
            {
                "max_risk": "HIGH" | "MEDIUM" | "LOW",
                "distribution": {"HIGH": N, "MEDIUM": N, "LOW": N}
            }
        """
        distribution: Dict[str, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for st in status_list:
            level = st.get("risk_level", "MEDIUM")
            if level in distribution:
                distribution[level] += 1

        max_risk = "LOW"
        for level in ["HIGH", "MEDIUM", "LOW"]:
            if distribution.get(level, 0) > 0:
                max_risk = level
                break

        return {
            "max_risk": max_risk,
            "distribution": distribution,
        }

    def _momentum_consensus(self, status_list: List[Dict]) -> Dict:
        """动量方向共识

        根据各策略 momentum.level 统计看涨 / 看跌 / 中性比例

        Returns:
            {
                "bullish_pct": 0.0 ~ 1.0,
                "bearish_pct": 0.0 ~ 1.0,
                "neutral_pct": 0.0 ~ 1.0,
                "consensus": "BULLISH" | "BEARISH" | "NEUTRAL" | "DIVERGENT"
            }
        """
        total = len(status_list)
        if total == 0:
            return {
                "bullish_pct": 0.0,
                "bearish_pct": 0.0,
                "neutral_pct": 0.0,
                "consensus": "DIVERGENT",
            }

        bullish = 0
        bearish = 0
        neutral = 0

        for st in status_list:
            momentum = st.get("momentum", {}) or {}
            level = str(momentum.get("level", "")).upper()

            if level in ("BUY", "BULLISH", "ACCUMULATING"):
                bullish += 1
            elif level in ("SELL", "BEARISH", "DISTRIBUTING"):
                bearish += 1
            else:
                neutral += 1

        # 判定共识
        parts = [("bullish", bullish), ("bearish", bearish), ("neutral", neutral)]
        max_label, max_count = max(parts, key=lambda x: x[1])
        majority_pct = max_count / total if total > 0 else 0.0

        if majority_pct >= 0.6:
            consensus = max_label.upper()
        else:
            consensus = "DIVERGENT"

        return {
            "bullish_pct": round(bullish / total, 4),
            "bearish_pct": round(bearish / total, 4),
            "neutral_pct": round(neutral / total, 4),
            "consensus": consensus,
        }

    def _count_state_distribution(self, status_list: List[Dict]) -> Dict[str, int]:
        """统计各状态出现次数"""
        distribution: Dict[str, int] = {}
        for st in status_list:
            state = st.get("state", "UNKNOWN")
            distribution[state] = distribution.get(state, 0) + 1
        return distribution

    def _aggregate_key_levels(self, status_list: List[Dict]) -> Dict:
        """聚合支撑 / 阻力 — 跨策略取最低支撑、最高阻力

        Returns:
            {
                "support": float,       # 所有策略中的最低支撑位
                "resistance": float,    # 所有策略中的最高阻力位
                "per_strategy": [       # 各策略原始数据
                    {"name": "...", "support": float, "resistance": float},
                    ...
                ]
            }
        """
        per_strategy = []
        min_support = float("inf")
        max_resistance = float("-inf")
        has_valid = False

        for i, st in enumerate(status_list):
            sr = st.get("support_resistance", {}) or {}
            support = sr.get("support", 0.0) or 0.0
            resistance = sr.get("resistance", 0.0) or 0.0

            if support > 0 or resistance > 0:
                has_valid = True

            per_strategy.append({
                "support": support,
                "resistance": resistance,
            })

            if support > 0 and support < min_support:
                min_support = support
            if resistance > 0 and resistance > max_resistance:
                max_resistance = resistance

        if not has_valid:
            return {"support": 0.0, "resistance": 0.0, "per_strategy": per_strategy}

        # 处理无效极值回退
        if min_support == float("inf"):
            min_support = 0.0
        if max_resistance == float("-inf"):
            max_resistance = 0.0

        return {
            "support": min_support,
            "resistance": max_resistance,
            "per_strategy": per_strategy,
        }

    # ──────────────────────────────────────────────
    # 验证链（V2）
    # ──────────────────────────────────────────────

    def _verify_chip_volume(self, status_list: List[Dict]) -> VerificationChainResult:
        """链 1：筹码 × 成交量 — 验证放量/缩量是否与筹码方向一致"""
        chip_state = None
        chip_name = ''
        volume_state = None

        for st in status_list:
            name = (st.get('strategy_name', '') or '').upper()
            if 'CHIP' in name or '筹码' in name:
                chip_state = str(st.get('state', '')).upper()
                chip_name = st.get('strategy_name', '')
            if 'VOLUME' in name or '量价' in name or '成交量' in name:
                vol_m = st.get('momentum', {}) or {}
                volume_state = str(vol_m.get('level', '')).upper()

        # Chip accumulating + volume fangliang -> uptrend confirmation
        if chip_state == 'ACCUMULATING':
            if volume_state in ('BUY', 'BULLISH', 'FANGLIANG'):
                return VerificationChainResult(
                    chain_id='chip_volume', chain_name='筹码×成交量',
                    passed=True, confidence_multiplier=1.15,
                    evidence=[f"{chip_name} ACCUMULATING + volume bullish"],
                )
            if volume_state in ('SELL', 'BEARISH', 'SUOLIANG'):
                return VerificationChainResult(
                    chain_id='chip_volume', chain_name='筹码×成交量',
                    passed=False, confidence_multiplier=0.85,
                    evidence=[f"{chip_name} ACCUMULATING but volume bearish"],
                    conflict_detail='筹码吸筹但成交量萎缩，买入信号减弱',
                )

        # Chip distributing + volume fangliang -> distribution confirmation
        if chip_state == 'DISTRIBUTING':
            if volume_state in ('BUY', 'BULLISH', 'FANGLIANG'):
                return VerificationChainResult(
                    chain_id='chip_volume', chain_name='筹码×成交量',
                    passed=True, confidence_multiplier=1.15,
                    evidence=[f"{chip_name} DISTRIBUTING + volume bearish"],
                )

        return VerificationChainResult(
            chain_id='chip_volume', chain_name='筹码×成交量',
            passed=False, confidence_multiplier=1.0,
            evidence=['Chip-volume chain: insufficient data'],
        )

    def _verify_chanlun_factor(self, status_list: List[Dict]) -> VerificationChainResult:
        """链 2：缠论 × 因子 — 验证技术结构方向与动量方向是否一致"""
        chanlun_support = 0.0
        chanlun_resistance = 0.0
        factor_momentum = ''

        for st in status_list:
            name = (st.get('strategy_name', '') or '').upper()
            if 'CHANLUN' in name or '缠' in name:
                sr = st.get('support_resistance', {}) or {}
                chanlun_support = sr.get('support', 0.0) or 0.0
                chanlun_resistance = sr.get('resistance', 0.0) or 0.0
            if 'FACTOR' in name or '因子' in name:
                mom = st.get('momentum', {}) or {}
                factor_momentum = str(mom.get('level', '')).upper()

        if factor_momentum in ('BUY', 'BULLISH') and chanlun_support > 0:
            return VerificationChainResult(
                chain_id='chanlun_factor', chain_name='缠论×因子',
                passed=True, confidence_multiplier=1.1,
                evidence=[f"factor BULLISH + chanlun support={chanlun_support}"],
            )

        if factor_momentum in ('SELL', 'BEARISH'):
            return VerificationChainResult(
                chain_id='chanlun_factor', chain_name='缠论×因子',
                passed=False, confidence_multiplier=1.0,
                evidence=[f'factor BEARISH — downtrend conflict'],
                conflict_detail='因子看空，技术结构下行压力',
            )

        return VerificationChainResult(
            chain_id='chanlun_factor', chain_name='缠论×因子',
            passed=False, confidence_multiplier=1.0,
            evidence=['Chanlun-factor chain: insufficient data'],
        )

    def _verify_emotion_fundamental(self, status_list: List[Dict]) -> VerificationChainResult:
        """链 3：情绪 × 筹码 — 验证市场情绪与筹码分布方向一致性"""
        bociasi_state = None
        chip_state = None
        chip_name = ''

        for st in status_list:
            name = (st.get('strategy_name', '') or '').upper()
            if 'BOCIASI' in name or '情绪' in name:
                bociasi_state = str(st.get('state', '')).upper()
            if 'CHIP' in name or '筹码' in name:
                chip_state = str(st.get('state', '')).upper()
                chip_name = st.get('strategy_name', '')

        bociasi_bull = bociasi_state in ('ACCUMULATING', 'BULLISH', 'BUY')
        bociasi_bear = bociasi_state in ('DISTRIBUTING', 'BEARISH', 'SELL')
        chip_bull = chip_state in ('ACCUMULATING', 'BULLISH', 'BUY')
        chip_bear = chip_state in ('DISTRIBUTING', 'BEARISH', 'SELL')

        if bociasi_bull and chip_bull:
            return VerificationChainResult(
                chain_id='emotion_fundamental', chain_name='情绪×筹码',
                passed=True, confidence_multiplier=1.15,
                evidence=['BOCIASI bullish + chip bullish — strong consensus'],
            )

        if bociasi_bear and chip_bear:
            return VerificationChainResult(
                chain_id='emotion_fundamental', chain_name='情绪×筹码',
                passed=True, confidence_multiplier=1.15,
                evidence=['BOCIASI bearish + chip bearish — strong sell consensus'],
            )

        if (bociasi_bull and chip_bear) or (bociasi_bear and chip_bull):
            return VerificationChainResult(
                chain_id='emotion_fundamental', chain_name='情绪×筹码',
                passed=False, confidence_multiplier=0.8,
                evidence=['BOCIASI and chip disagree'],
                conflict_detail='情绪与筹码方向矛盾',
            )

        return VerificationChainResult(
            chain_id='emotion_fundamental', chain_name='情绪×筹码',
            passed=False, confidence_multiplier=1.0,
            evidence=['Emotion-fundamental chain: insufficient data'],
        )

    def _verify_tech_fundamental(self, status_list: List[Dict]) -> VerificationChainResult:
        """链 4：技术基本面全维度 — 跨策略共识验证"""
        total = len(status_list)
        if total == 0:
            return VerificationChainResult(
                chain_id='tech_fundamental', chain_name='技术基本面全维度',
                passed=False, confidence_multiplier=1.0,
                evidence=['No status data'],
            )

        bullish_count = sum(
            1 for st in status_list
            if str(st.get('momentum', {}).get('level', '')).upper()
            in ('BUY', 'BULLISH', 'ACCUMULATING')
        )
        bearish_count = sum(
            1 for st in status_list
            if str(st.get('momentum', {}).get('level', '')).upper()
            in ('SELL', 'BEARISH', 'DISTRIBUTING')
        )

        if bullish_count >= total * 0.66:
            return VerificationChainResult(
                chain_id='tech_fundamental', chain_name='技术基本面全维度',
                passed=True, confidence_multiplier=1.2,
                evidence=[f'{bullish_count}/{total} strategies bullish — strong pass'],
            )

        if bearish_count >= total * 0.66:
            return VerificationChainResult(
                chain_id='tech_fundamental', chain_name='技术基本面全维度',
                passed=True, confidence_multiplier=1.2,
                evidence=[f'{bearish_count}/{total} strategies bearish — strong pass'],
            )

        if bullish_count >= total * 0.5 or bearish_count >= total * 0.5:
            return VerificationChainResult(
                chain_id='tech_fundamental', chain_name='技术基本面全维度',
                passed=True, confidence_multiplier=1.0,
                evidence=[f'{max(bullish_count, bearish_count)}/{total} majority direction'],
            )

        return VerificationChainResult(
            chain_id='tech_fundamental', chain_name='技术基本面全维度',
            passed=False, confidence_multiplier=0.8,
            evidence=['Technical dimensions divergent'],
            conflict_detail='各技术维度方向不一致，缺乏明确共识',
        )

    def aggregate_v2(self, signals, market_state='UNKNOWN'):
        """Seven-step verification chain output (V2)."""
        if not signals:
            return self._empty_result_v2()

        status_list = [
            sig.get('status_recognition', {}) or {}
            for sig in signals
            if sig and sig.get('status_recognition')
        ]

        if not status_list:
            return self._empty_result_v2()

        chains = [
            self._verify_chip_volume(status_list),
            self._verify_chanlun_factor(status_list),
            self._verify_emotion_fundamental(status_list),
            self._verify_tech_fundamental(status_list),
        ]

        chain_passed = sum(1 for c in chains if c.passed)
        chain_passed_ratio = chain_passed / 4.0

        avg_mult = sum(c.confidence_multiplier for c in chains) / 4.0

        conflicts_for_ai = [
            {
                'chain_id': c.chain_id,
                'chain_name': c.chain_name,
                'conflict_detail': c.conflict_detail,
            }
            for c in chains if not c.passed and c.conflict_detail
        ]

        base = self.aggregate(signals)

        if chain_passed_ratio >= 0.75:
            final_state = base.get('state_consensus', {}).get('state', 'UNKNOWN')
            base_conf = base.get('state_consensus', {}).get('consensus_pct', 0.5)
            final_conf = min(base_conf * avg_mult, 1.0)
            ai_mode = 'summary_only'
        elif chain_passed_ratio >= 0.25:
            final_state = base.get('state_consensus', {}).get('state', 'DIVERGENT')
            base_conf = base.get('state_consensus', {}).get('consensus_pct', 0.3)
            final_conf = min(base_conf * 0.8, 1.0)
            ai_mode = 'arbitrate_conflicts'
        else:
            final_state = 'UNCERTAIN'
            final_conf = 0.2
            ai_mode = 'full_analysis'

        return {
            'version': '2.0',
            'status': {'state': final_state, 'confidence': round(final_conf, 2), 'market_state': market_state},
            'verification_chains': [
                {
                    'chain_id': c.chain_id, 'chain_name': c.chain_name,
                    'passed': c.passed, 'confidence_multiplier': c.confidence_multiplier,
                    'conflict_detail': c.conflict_detail, 'evidence': c.evidence,
                }
                for c in chains
            ],
            'chain_passed_ratio': chain_passed_ratio,
            'conflicts_for_ai': conflicts_for_ai,
            'ai_mode': ai_mode,
            'state_consensus': base.get('state_consensus', {}),
            'risk_aggregation': base.get('risk_aggregation', {}),
            'momentum_consensus': base.get('momentum_consensus', {}),
            'dimensions': base.get('strategies_detail', []),
        }

    def _empty_result_v2(self):
        return {
            'version': '2.0',
            'status': {'state': 'UNKNOWN', 'confidence': 0.0, 'market_state': 'UNKNOWN'},
            'verification_chains': [],
            'chain_passed_ratio': 0.0, 'conflicts_for_ai': [], 'ai_mode': 'full_analysis',
            'state_consensus': {'state': 'UNKNOWN', 'consensus_pct': 0.0, 'distribution': {}},
            'risk_aggregation': {'max_risk': 'LOW', 'distribution': {'HIGH': 0, 'MEDIUM': 0, 'LOW': 0}},
            'momentum_consensus': {'bullish_pct': 0.0, 'bearish_pct': 0.0, 'neutral_pct': 0.0, 'consensus': 'DIVERGENT'},
            'dimensions': [],
        }

    def _strategies_detail(self, signals: List[Dict], status_list: List[Dict]) -> List[Dict]:
        """保留每个策略的详细现状识别

        从原始 signals 中提取 strategy_name + status_recognition，
        按输入顺序返回精简信息列表。
        """
        details = []
        for sig in signals:
            if not sig:
                continue
            sr = sig.get("status_recognition") or {}
            if not sr:
                continue
            details.append({
                "strategy_name": sig.get("strategy_name", "未命名策略"),
                "signal": sig.get("signal", ""),
                "confidence": sig.get("confidence"),
                "status_recognition": sr,
            })
        return details

    def _empty_result(self) -> Dict:
        """无信号时的空结果"""
        return {
            "state_consensus": {"state": "UNKNOWN", "consensus_pct": 0.0, "distribution": {}},
            "risk_aggregation": {
                "max_risk": "LOW",
                "distribution": {"HIGH": 0, "MEDIUM": 0, "LOW": 0},
            },
            "momentum_consensus": {
                "bullish_pct": 0.0,
                "bearish_pct": 0.0,
                "neutral_pct": 0.0,
                "consensus": "DIVERGENT",
            },
            "key_levels": {"support": 0.0, "resistance": 0.0, "per_strategy": []},
            "strategy_count": 0,
            "strategies_detail": [],
        }
