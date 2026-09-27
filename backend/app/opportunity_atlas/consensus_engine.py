"""
L3 Consensus Aggregation Engine
================================
Implements the L3 consensus logic from the 390 plan.

Aggregates dimension-level scores into family-level consensus scores,
then combines families into a final consensus rate with reliability-adjusted weighting.

Family structure (6 families):
    - main_behavior  : chip_fund (phase + fund_flow + crowding)
    - structure_trend: structure, signal, time
    - volume_price   : vp (independent)
    - valuation_quality: valuation, finance
    - environment    : emotion, event, factor
    - risk           : risk (independent)

Each family's contribution is weighted by:
    1. Emotion-phase-dependent STATE_WEIGHTS (情绪周期阶段权重)
    2. Market-regime weights MARKET_REGIME_WEIGHTS (大盘状态权重；492号 K3 接线)
    3. Family-level reliability (aggregate of individual dimension reliabilities)
"""

from __future__ import annotations

from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GROUP_MAPPING: Dict[str, List[str]] = {
    'main_behavior': ['chip_fund'],  # 主力行为族：chip_fund内含phase+fund_flow+crowding
    'structure_trend': ['structure', 'signal', 'time', 'position', 'signal_confirm'],  # 结构趋势族
    'volume_price': ['vp'],  # 量价状态族（独立）
    'valuation_quality': ['valuation', 'finance'],  # 估值质量族
    'environment': ['emotion', 'event', 'factor'],  # 环境族
    'risk': ['risk'],  # 风险族（独立）
}

STATE_WEIGHTS: Dict[str, Dict[str, float]] = {
    'ice': {
        'main_behavior': 0.15,
        'structure_trend': 0.15,
        'volume_price': 0.20,
        'valuation_quality': 0.30,
        'environment': 0.10,
        'risk': 0.10,
    },
    'ebb': {
        'main_behavior': 0.20,
        'structure_trend': 0.20,
        'volume_price': 0.20,
        'valuation_quality': 0.20,
        'environment': 0.10,
        'risk': 0.10,
    },
    'normal': {
        'main_behavior': 0.25,
        'structure_trend': 0.20,
        'volume_price': 0.20,
        'valuation_quality': 0.15,
        'environment': 0.10,
        'risk': 0.10,
    },
    'recovery': {
        'main_behavior': 0.25,
        'structure_trend': 0.20,
        'volume_price': 0.20,
        'valuation_quality': 0.15,
        'environment': 0.10,
        'risk': 0.10,
    },
    'positive': {
        'main_behavior': 0.20,
        'structure_trend': 0.20,
        'volume_price': 0.20,
        'valuation_quality': 0.15,
        'environment': 0.15,
        'risk': 0.10,
    },
    'climax': {
        'main_behavior': 0.15,
        'structure_trend': 0.15,
        'volume_price': 0.20,
        'valuation_quality': 0.10,
        'environment': 0.20,
        'risk': 0.20,
    },
}

# All valid emotion phases for validation
_VALID_PHASES: set = set(STATE_WEIGHTS.keys())

# 492号（K3 接线）：MARKET_REGIME_WEIGHTS 是「大盘状态×维度」权重表（键为
#   status_engine._DIM_ORDER 的维度名），本引擎按「族」聚合 → 需归并：
#   structure_trend 族取 signal+structure 均值，environment 族取 emotion+factor 均值。
#   缺失族/维度一律按等权 0.1 兜底（与 status_engine 消费侧默认一致）。
_REGIME_DIM_ALIASES: Dict[str, tuple] = {
    'main_behavior': ('chip_fund',),
    'structure_trend': ('signal', 'structure'),
    'volume_price': ('vp',),
    'valuation_quality': ('valuation',),
    'environment': ('emotion', 'factor'),
    'risk': ('risk',),
}


def _family_regime_weight(regime_weights: Dict[str, float], family: str) -> float:
    """MARKET_REGIME_WEIGHTS（维度权重）→ 族权重（族内维度均值）。

    regime_weights 为 None/空 → 返回 0.1（等权兜底）。
    """
    dims = _REGIME_DIM_ALIASES.get(family, ())
    if not isinstance(regime_weights, dict) or not dims:
        return 0.1
    vals = [float(regime_weights.get(d, 0.1)) for d in dims if regime_weights.get(d) is not None]
    if not vals:
        return 0.1
    return sum(vals) / len(vals)


# ---------------------------------------------------------------------------
# Intra-family merge
# ---------------------------------------------------------------------------


def merge_family(
    dim_scores: Dict[str, float],
    dim_reliabilities: Dict[str, float],
    family_dims: List[str],
    dim_strengths: Dict[str, float] = None,
) -> Tuple[str, float, bool]:
    """
    Merge individual dimension scores within a single family.

    Parameters
    ----------
    dim_scores : dict
        Mapping of dimension name -> direction score in [-1, 1].
        Positive = bullish, negative = bearish.
    dim_reliabilities : dict
        Mapping of dimension name -> reliability in [0, 1].
    family_dims : list[str]
        Dimension names belonging to this family.

    Returns
    -------
    direction : str
        ``'bull'``, ``'bear'``, or ``'neutral'``.
    strength : float
        Aggregated absolute strength in [0, 1].
    has_conflict : bool
        True when both positive and negative directions are present.
    """
    # Collect valid (direction, strength, reliability) tuples
    entries: List[Tuple[str, float, float]] = []
    _str = dim_strengths or {}
    for dim in family_dims:
        score = dim_scores.get(dim)
        rel = dim_reliabilities.get(dim)
        if score is None or rel is None:
            continue
        try:
            score = float(score)
            rel = float(rel)
        except (TypeError, ValueError):
            continue

        # 使用真实strength值（而非direction绝对值），保留引擎精细强度信息
        abs_score = _str.get(dim, abs(score))
        abs_score = max(0.0, min(1.0, abs_score))
        rel = max(0.0, min(1.0, rel))

        if score > 0:
            entries.append(('bull', abs_score, rel))
        elif score < 0:
            entries.append(('bear', abs_score, rel))
        else:
            entries.append(('neutral', 0.0, rel))

    # No valid data -> neutral with zero strength
    if not entries:
        return ('neutral', 0.0, False)

    # Separate by direction
    bull_entries = [e for e in entries if e[0] == 'bull']
    bear_entries = [e for e in entries if e[0] == 'bear']
    has_conflict = len(bull_entries) > 0 and len(bear_entries) > 0

    # Reliability-weighted mean strength per direction
    def _weighted_mean(group: List[Tuple[str, float, float]]) -> float:
        if not group:
            return 0.0
        total_rel = sum(e[2] for e in group)
        if total_rel == 0:
            return 0.0
        return sum(e[1] * e[2] for e in group) / total_rel

    bull_strength = _weighted_mean(bull_entries)
    bear_strength = _weighted_mean(bear_entries)

    # Majority direction by count; ties broken by weighted strength
    if len(bull_entries) > len(bear_entries):
        majority_dir = 'bull'
    elif len(bear_entries) > len(bull_entries):
        majority_dir = 'bear'
    else:
        # Equal count -- pick the one with higher weighted strength
        majority_dir = 'bull' if bull_strength >= bear_strength else 'bear'

    if has_conflict:
        # Conflict penalty: scale majority strength by 0.6
        majority_strength = (
            bull_strength if majority_dir == 'bull' else bear_strength
        )
        strength = majority_strength * 0.6
    else:
        # No conflict: take mean strength of whichever direction exists
        strength = bull_strength if majority_dir == 'bull' else bear_strength

    strength = max(0.0, min(1.0, strength))

    return (majority_dir, strength, has_conflict)


# ---------------------------------------------------------------------------
# Public compute entry-point
# ---------------------------------------------------------------------------

def compute(
    dims_factor: Dict[str, float],
    reliability: Dict[str, float],
    weights: Dict[str, float],
    emotion_phase: str = 'normal',
) -> dict:
    """
    L3 consensus aggregation.

    Parameters
    ----------
    dims_factor : dict
        Dimension name -> direction score in [-1, 1].
        Positive = bullish signal, negative = bearish signal.
    reliability : dict
        Dimension name -> reliability weight in [0, 1].
    weights : dict
        Dimension name -> base importance weight in [0, 1].
        （492号 K3 接线）实际为状态引擎传入的 MARKET_REGIME_WEIGHTS 单档
        （维度键），族权重由 ``_family_regime_weight`` 归并后与 STATE_WEIGHTS 相乘；
        传 None/{} 时退化为仅用 STATE_WEIGHTS（等价旧行为）。
    emotion_phase : str
        Current emotion phase key. Must be one of the keys in
        ``STATE_WEIGHTS``. Defaults to ``'normal'``.

    Returns
    -------
    dict
        consensus_rate    : float  -- final reliability-adjusted score in [-1, 1]
        raw_consensus_rate: float  -- consensus before neutral-ratio cap
        reliability_factor: float  -- total_effective_weight / max_possible_weight
        direction         : str    -- 'bull' / 'bear' / 'neutral'
        bull_score        : float  -- accumulated bullish score
        bear_score        : float  -- accumulated bearish score
        group_details     : dict   -- per-family details
    """
    # --- Validate emotion phase ---
    if emotion_phase not in _VALID_PHASES:
        raise ValueError(
            f"Invalid emotion_phase '{emotion_phase}'. "
            f"Must be one of: {sorted(_VALID_PHASES)}"
        )

    state_weights = STATE_WEIGHTS[emotion_phase]
    # 492号（K3）：族级有效权重 = 情绪阶段权重 × 大盘状态族权重（regime_weights 缺失→0.1 等权）
    family_weights: Dict[str, float] = {
        fam: state_weights[fam] * _family_regime_weight(weights, fam)
        for fam in STATE_WEIGHTS[emotion_phase]
    }
    max_possible_weight = sum(family_weights.values())  # 归一化基准（随 regime 缩放）

    total_effective_weight = 0.0
    bull_score = 0.0
    bear_score = 0.0
    neutral_dim_count = 0
    total_dim_count = 0
    group_details: Dict[str, dict] = {}

    for group_name, family_dims in GROUP_MAPPING.items():
        # --- Extract direction + strength from nested dims_factor ---
        # dims_factor has structure {dim: {direction: int, strength: float, ...}}
        flat_scores = {}
        flat_strengths = {}
        for dim in family_dims:
            dim_val = dims_factor.get(dim)
            if isinstance(dim_val, dict):
                flat_scores[dim] = dim_val.get('direction', 0)
                flat_strengths[dim] = dim_val.get('strength', abs(dim_val.get('direction', 0)))
            elif isinstance(dim_val, (int, float)):
                flat_scores[dim] = dim_val
                flat_strengths[dim] = abs(dim_val)

        # --- Family-level merge (with real strength values) ---
        family_dir, family_strength, has_conflict = merge_family(
            flat_scores, reliability, family_dims, flat_strengths
        )

        # --- Family-level reliability ---
        # Reliability = mean of dimension reliabilities in this family
        family_reliability = 0.0
        valid_rels = []
        for dim in family_dims:
            rel = reliability.get(dim)
            if rel is not None:
                try:
                    rel = float(rel)
                    rel = max(0.0, min(1.0, rel))
                    valid_rels.append(rel)
                except (TypeError, ValueError):
                    pass

        if valid_rels:
            family_reliability = sum(valid_rels) / len(valid_rels)

        # --- Effective weight（492号 K3：族权重 × 大盘状态权重 → 状态引擎传入的 weights 生效）---
        _fam_w = family_weights.get(group_name, state_weights[group_name] * 0.1)
        effective_weight = _fam_w * family_reliability
        total_effective_weight += effective_weight

        # --- Accumulate scores ---
        if family_dir == 'bull':
            bull_score += family_strength * effective_weight
        elif family_dir == 'bear':
            bear_score += family_strength * effective_weight

        # --- Count neutrals ---
        for dim in family_dims:
            total_dim_count += 1
            score = dims_factor.get(dim)
            if score is None:
                continue
            try:
                if abs(float(score)) < 1e-9:
                    neutral_dim_count += 1
            except (TypeError, ValueError):
                pass

        # --- Record group detail ---
        group_details[group_name] = {
            'direction': family_dir,
            'strength': round(family_strength, 4),
            'has_conflict': has_conflict,
            'family_reliability': round(family_reliability, 4),
            'state_weight': round(_fam_w, 4),
            'effective_weight': round(effective_weight, 4),
        }

    # --- Compute raw consensus rate ---
    total_score = bull_score + bear_score
    if total_score > 1e-9:
        dominant = max(bull_score, bear_score)
        raw_consensus_rate = dominant / total_score
        # Apply sign: positive = bull, negative = bear
        if bear_score > bull_score:
            raw_consensus_rate = -raw_consensus_rate
    else:
        raw_consensus_rate = 0.0

    # --- Apply neutral ratio cap ---
    neutral_ratio = neutral_dim_count / max(total_dim_count, 1)
    consensus_rate = raw_consensus_rate
    if neutral_ratio > 0.6:
        # Cap consensus magnitude at 0.5
        if abs(consensus_rate) > 0.5:
            consensus_rate = 0.5 if consensus_rate > 0 else -0.5

    # --- Reliability factor ---
    reliability_factor = total_effective_weight / max(max_possible_weight, 1e-9)
    reliability_factor = max(0.0, min(1.0, reliability_factor))

    # --- Direction label ---
    if consensus_rate > 0.01:
        direction = 'bull'
    elif consensus_rate < -0.01:
        direction = 'bear'
    else:
        direction = 'neutral'

    return {
        'consensus_rate': round(consensus_rate, 4),
        'raw_consensus_rate': round(raw_consensus_rate, 4),
        'reliability_factor': round(reliability_factor, 4),
        'direction': direction,
        'bull_score': round(bull_score, 4),
        'bear_score': round(bear_score, 4),
        'group_details': group_details,
    }
