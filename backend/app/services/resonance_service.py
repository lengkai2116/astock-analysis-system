"""
ResonanceService — 多策略信号共振评分系统
=========================================
实现方案152 §4.3 策略三：信号融合与共振评分（P1）

从基础加权升级为观潮风格的多维度共振评分，支持：
  - 多策略信号源权重融合
  - 三重牛/三重熊共振检测
  - 共振灯号指示 (green/red/yellow/gray)
  - 信号冲突识别
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from app.engine.patterns import PatternResult, PatternCategory, PatternStage


class ResonanceLevel(Enum):
    """共振等级"""
    TRIPLE_BULL = "triple_bull"      # >=3 策略看多
    DOUBLE_BULL = "double_bull"      # >=2 策略看多
    MIXED = "mixed"                   # 多空冲突
    DOUBLE_BEAR = "double_bear"      # >=2 策略看空
    TRIPLE_BEAR = "triple_bear"      # >=3 策略看空
    NEUTRAL = "neutral"              # 无明显信号


RESONANCE_LAMP_COLORS = {
    ResonanceLevel.TRIPLE_BULL: "green",
    ResonanceLevel.DOUBLE_BULL: "yellow",
    ResonanceLevel.MIXED: "gray",
    ResonanceLevel.DOUBLE_BEAR: "orange",
    ResonanceLevel.TRIPLE_BEAR: "red",
    ResonanceLevel.NEUTRAL: "gray",
}


@dataclass
class DimensionSignal:
    """单个策略维度的信号摘要"""
    strategy: str        # 'chip' / 'chanlun' / 'volume_price' / 'factor'
    direction: str       # 'bullish' / 'bearish' / 'neutral'
    score: float         # 0~1 信号强度
    pattern_count: int   # 该策略触发的模式数量
    detail: str = ""     # 解读

    def to_dict(self) -> Dict:
        return {
            'strategy': self.strategy,
            'direction': self.direction,
            'score': self.score,
            'pattern_count': self.pattern_count,
            'detail': self.detail,
        }


@dataclass
class ResonanceResult:
    """共振评分结果"""
    overall_score: float                   # 0~100 综合评分
    resonance_level: ResonanceLevel        # 共振等级
    lamp_color: str                        # 灯号颜色
    dimension_signals: List[DimensionSignal] = field(default_factory=list)
    bullish_count: int = 0                 # 看多策略数
    bearish_count: int = 0                 # 看空策略数
    confidence: float = 0.0                # 0~1 共振置信度
    contributing_signals: List[str] = field(default_factory=list)
    interpretation: str = ""

    def to_dict(self) -> Dict:
        return {
            'overall_score': self.overall_score,
            'resonance_level': self.resonance_level.value,
            'lamp_color': self.lamp_color,
            'dimension_signals': [d.to_dict() for d in self.dimension_signals],
            'bullish_count': self.bullish_count,
            'bearish_count': self.bearish_count,
            'confidence': self.confidence,
            'contributing_signals': self.contributing_signals,
            'interpretation': self.interpretation,
        }


class ResonanceService:
    """
    多策略信号共振评分服务

    使用方式:
        service = ResonanceService()
        result = service.score(
            ts_code="000001.SZ",
            patterns=[...],      # List[PatternResult] from all strategies
        )
    """

    # 各策略维度权重
    STRATEGY_WEIGHTS = {
        'chip': 0.25,
        'chanlun': 0.20,
        'volume_price': 0.25,
        'kline': 0.15,
        'factor': 0.15,
    }

    # 共振阈值
    RESONANCE_THRESHOLDS = {
        ResonanceLevel.TRIPLE_BULL: {'min_signals': 3, 'min_strength': 0.60},
        ResonanceLevel.DOUBLE_BULL: {'min_signals': 2, 'min_strength': 0.50},
        ResonanceLevel.TRIPLE_BEAR: {'min_signals': 3, 'min_strength': 0.60},
        ResonanceLevel.DOUBLE_BEAR: {'min_signals': 2, 'min_strength': 0.50},
    }

    def score(self, ts_code: str, patterns: List[PatternResult],
              extra_signals: Optional[Dict[str, DimensionSignal]] = None) -> ResonanceResult:
        """
        计算共振评分

        Args:
            ts_code: 股票代码
            patterns: 所有策略检测到的模式列表
            extra_signals: 额外信号（如因子评分等外部结果）

        Returns:
            ResonanceResult
        """
        # 1. 按策略维度分组
        dim_signals = self._aggregate_dimensions(patterns)

        # 2. 合并外部信号
        if extra_signals:
            for name, sig in extra_signals.items():
                dim_signals[name] = sig

        # 3. 计算各维度分数
        dims = list(dim_signals.values())
        if not dims:
            return ResonanceResult(
                overall_score=0,
                resonance_level=ResonanceLevel.NEUTRAL,
                lamp_color="gray",
                confidence=0.0,
                interpretation="无有效信号",
            )

        # 4. 计算多空计数和综合评分
        bullish_count = sum(1 for d in dims if d.direction == 'bullish')
        bearish_count = sum(1 for d in dims if d.direction == 'bearish')

        total_weight = sum(self.STRATEGY_WEIGHTS.get(d.strategy, 0.15)
                          for d in dims)
        weighted_score = sum(
            d.score * self.STRATEGY_WEIGHTS.get(d.strategy, 0.15)
            for d in dims
        ) / max(total_weight, 0.01)

        overall = min(100, max(0, weighted_score * 100))

        # 5. 判断共振等级
        resonance_level = self._classify_resonance(
            bullish_count, bearish_count, dims)

        # 6. 构建贡献信号列表
        contrib = []
        for d in dims:
            if d.score > 0.3:
                contrib.append(f"{d.strategy}: {d.direction}({d.score:.0%})")

        # 7. 置信度
        active_dims = [d for d in dims if d.score > 0.3]
        confidence = min(1.0, len(active_dims) / 5.0) * (overall / 100.0)

        # 8. 解读
        interp = self._build_interpretation(
            resonance_level, bullish_count, bearish_count, overall)

        return ResonanceResult(
            overall_score=round(overall, 1),
            resonance_level=resonance_level,
            lamp_color=RESONANCE_LAMP_COLORS.get(resonance_level, "gray"),
            dimension_signals=dims,
            bullish_count=bullish_count,
            bearish_count=bearish_count,
            confidence=round(confidence, 2),
            contributing_signals=contrib,
            interpretation=interp,
        )

    def _aggregate_dimensions(self, patterns: List[PatternResult]) -> Dict[str, DimensionSignal]:
        """
        按策略维度聚合模式

        Returns:
            {strategy_name: DimensionSignal}
        """
        # 按 strategy name 分组
        strategy_to_direction = {}  # strategy -> {bullish, bearish, neutral}
        strategy_to_patterns = {}

        for p in patterns:
            src = p.source if p.source else "unknown"
            # 将 source 映射为标准策略名
            strategy_key = self._map_source_to_strategy(src)
            if strategy_key not in strategy_to_patterns:
                strategy_to_patterns[strategy_key] = []
            strategy_to_patterns[strategy_key].append(p)

        result = {}
        for strategy_key, pats in strategy_to_patterns.items():
            if not pats:
                continue

            # 方向投票
            bull = sum(1 for p in pats if p.direction == 'bullish')
            bear = sum(1 for p in pats if p.direction == 'bearish')
            neutral = sum(1 for p in pats if p.direction == 'neutral')

            if bull > bear and bull > neutral:
                direction = 'bullish'
                total = bull
            elif bear > bull and bear > neutral:
                direction = 'bearish'
                total = bear
            else:
                direction = 'neutral'
                total = neutral

            # 平均强度
            avg_strength = sum(p.strength for p in pats) / max(len(pats), 1)

            detail_parts = []
            for p in pats[:3]:  # 最多3个
                detail_parts.append(f"{p.name}({p.strength:.0%})")

            result[strategy_key] = DimensionSignal(
                strategy=strategy_key,
                direction=direction,
                score=avg_strength,
                pattern_count=len(pats),
                detail=', '.join(detail_parts),
            )

        return result

    def _map_source_to_strategy(self, source: str) -> str:
        """将 source 文件名映射为标准策略名"""
        mapping = {
            'kline_pattern.py': 'kline',
            'volume_price_strategy.py': 'volume_price',
            'chanlun_strategy.py': 'chanlun',
            'chip_strategy.py': 'chip',
            'pipeline.py': 'chip',
        }
        for key, val in mapping.items():
            if key in source:
                return val
        return source

    def _classify_resonance(self, bullish: int, bearish: int,
                            dims: List[DimensionSignal]) -> ResonanceLevel:
        """根据多空计数和强度判断共振等级"""
        # 计算看多平均强度
        bull_dims = [d for d in dims if d.direction == 'bullish']
        bear_dims = [d for d in dims if d.direction == 'bearish']
        avg_bull = (sum(d.score for d in bull_dims) / max(len(bull_dims), 1))
        avg_bear = (sum(d.score for d in bear_dims) / max(len(bear_dims), 1))

        if bullish >= 3 and avg_bull >= 0.6:
            return ResonanceLevel.TRIPLE_BULL
        if bearish >= 3 and avg_bear >= 0.6:
            return ResonanceLevel.TRIPLE_BEAR
        if bullish >= 2 and avg_bull >= 0.5:
            return ResonanceLevel.DOUBLE_BULL
        if bearish >= 2 and avg_bear >= 0.5:
            return ResonanceLevel.DOUBLE_BEAR
        if bullish > 0 and bearish > 0:
            return ResonanceLevel.MIXED

        return ResonanceLevel.NEUTRAL

    def _build_interpretation(self, level: ResonanceLevel,
                             bullish: int, bearish: int,
                             score: float) -> str:
        """构建自然语言解读"""
        interps = {
            ResonanceLevel.TRIPLE_BULL:
                f"🚦 三牛共振（{bullish}个策略看多），综合评分{score:.0f}/100，市场共识强烈",
            ResonanceLevel.DOUBLE_BULL:
                f"🟡 双牛共振（{bullish}个策略看多），综合评分{score:.0f}/100，信号偏多",
            ResonanceLevel.MIXED:
                f"⚪ 信号冲突（看多{bullish}个/看空{bearish}个），等待方向明确",
            ResonanceLevel.DOUBLE_BEAR:
                f"🟠 双熊共振（{bearish}个策略看空），综合评分{score:.0f}/100，信号偏空",
            ResonanceLevel.TRIPLE_BEAR:
                f"🔴 三熊共振（{bearish}个策略看空），综合评分{score:.0f}/100，市场风险警示",
            ResonanceLevel.NEUTRAL:
                f"信号不明确，综合评分{score:.0f}/100",
        }
        return interps.get(level, f"综合评分{score:.0f}/100")


def compute_resonance(ts_code: str, patterns: List[PatternResult]) -> ResonanceResult:
    """快捷函数：单次共振评分计算"""
    return ResonanceService().score(ts_code, patterns)
