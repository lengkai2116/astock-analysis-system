"""signal_decay_detector.py — 5维度联合信号衰减检测器

364g Phase 7：检测信号随时间推移的失效程度。
"""
from __future__ import annotations
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# 5维度权重（359号§1.5）
DECAY_WEIGHTS = {
    'price_trend': 0.30,
    'volume_price': 0.25,
    'volume_energy': 0.20,
    'chip_change': 0.15,
    'main_force': 0.10,
}

# 衰减等级
DECAY_LEVELS = {
    'healthy': (0, 39, '健康'),
    'fading': (40, 69, '衰减中'),
    'broken': (70, 100, '已失效'),
}


def detect_decay(tags: dict, lifecycle: dict = None) -> dict:
    """5维度联合衰减检测

    Returns:
        {
            'overall_score': int (0-100),
            'overall_status': str ('healthy'/'fading'/'broken'),
            'overall_status_cn': str,
            'breakdown': {dim: {status, score}},
            'detail': str
        }
    """
    lifecycle = lifecycle or {}
    scores = {}

    # 1. 走势变化（权重30%）
    scores['price_trend'] = _score_price_trend(tags, lifecycle)

    # 2. 量价关系（权重25%）
    scores['volume_price'] = _score_volume_price(tags)

    # 3. 量能变化（权重20%）
    scores['volume_energy'] = _score_volume_energy(tags)

    # 4. 筹码变化（权重15%）
    scores['chip_change'] = _score_chip_change(tags)

    # 5. 主力行为（权重10%）
    scores['main_force'] = _score_main_force(tags)

    overall_score = sum(scores[dim] * DECAY_WEIGHTS[dim] for dim in scores)
    overall_score = int(round(overall_score))

    status = 'healthy'
    status_cn = '健康'
    for level, (low, high, cn) in DECAY_LEVELS.items():
        if low <= overall_score <= high:
            status = level
            status_cn = cn
            break

    breakdown = {dim: {'status': _score_status_name(score), 'score': score}
                 for dim, score in scores.items()}

    return {
        'overall_score': overall_score,
        'overall_status': status,
        'overall_status_cn': status_cn,
        'breakdown': breakdown,
        'detail': f'衰减评分{overall_score}/100（{status_cn}）',
    }


def _score_price_trend(tags: dict, lifecycle: dict) -> int:
    """走势变化评分"""
    day = lifecycle.get('day', 0)
    if day <= 5:
        return 0
    elif day <= 12:
        return 20
    else:
        return 50


def _score_volume_price(tags: dict) -> int:
    """量价关系衰减评分"""
    vp = str(tags.get('volume_price_fit', ''))
    if vp == 'diverging':
        return 60
    elif vp == 'healthy':
        return 10
    return 30


def _score_volume_energy(tags: dict) -> int:
    """量能变化衰减评分"""
    try:
        vol_ratio = float(tags.get('volume_ratio', 1.0))
        if vol_ratio < 0.5:
            return 50
        elif vol_ratio < 0.8:
            return 30
        return 10
    except (TypeError, ValueError):
        return 20


def _score_chip_change(tags: dict) -> int:
    """筹码变化衰减评分"""
    phase = str(tags.get('main_force_phase', ''))
    if phase == 'distributing':
        return 60
    elif phase == 'building':
        return 5
    return 20


def _score_main_force(tags: dict) -> int:
    """主力行为衰减评分"""
    ff = str(tags.get('fund_flow', ''))
    if ff == '5d_outflow':
        return 50
    elif ff == '5d_inflow':
        return 5
    return 20


def _score_status_name(score: int) -> str:
    """分数状态名"""
    if score < 20:
        return '稳定'
    elif score < 40:
        return '轻微衰减'
    elif score < 60:
        return '中等衰减'
    elif score < 80:
        return '明显衰减'
    return '严重衰减'
