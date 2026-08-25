"""vp_health_builder.py — 第3维量价健康输出结构化构建器

364e Phase 5：将量价健康度从confidence(0-1)重构为10分制评分。
"""
from __future__ import annotations
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# 10分制评分维度权重（359号§3.9）
VP_SCORE_WEIGHTS = {
    'vp_pattern': 0.30,      # 量价形态（-2~+3 → 归一化0-10）
    'volume_energy': 0.20,   # 量能强度（0~+2）
    'ma_alignment': 0.15,    # 均线排列（0~+1）
    'chip_density': 0.15,    # 筹码密集（0~+1）
    'indicator': 0.10,       # 指标验证（0~+1）
    'divergence_penalty': 0.10,  # 背离惩罚（-2~0）
}

# VP-1~VP-9映射到形态得分
VP_PATTERN_SCORES = {
    'VP-1': 3,   # 价涨量增 → 强健康
    'VP-2': 2,   # 价涨量平 → 健康
    'VP-3': 1,   # 价涨量缩 → 弱
    'VP-4': 1,   # 价平量增 → 中性偏强
    'VP-5': 0,   # 价平量平 → 中性
    'VP-6': -1,  # 价平量减 → 弱
    'VP-7': -2,  # 价跌量增 → 背离
    'VP-8': -1,  # 价跌量平 → 弱
    'VP-9': 0,   # 价跌量缩 → 中性偏弱
}


def build_volume_price(
    dims: dict,
    tags: dict,
    signals: dict = None,
) -> dict:
    """构建第3维量价健康结构化输出

    Returns:
        {
            'status_description': {vp_state, health_score, divergence, volume_energy,
                                    pattern, bull_bear_battle, plain},
            'judgment': {state, light, score},
            'audit': {conditions, satisfied_count, total_count, confidence}
        }
    """
    signals = signals or {}
    vp_info = _assess_vp_state(dims, tags)
    health_score = _calc_health_score_10(dims, tags, signals)
    divergence = _assess_divergence(tags)
    volume_energy = _assess_volume_energy(tags)
    pattern = _assess_pattern(tags)
    bull_bear = _assess_bull_bear(tags)

    plain = _vp_plain(vp_info, health_score, divergence, volume_energy, pattern)

    status_description = {
        'vp_state': vp_info['state'],
        'health_score': f"{health_score}/10（{_score_level(health_score)}）",
        'divergence': divergence['detail'],
        'volume_energy': volume_energy['detail'],
        'pattern': pattern['detail'],
        'bull_bear_battle': bull_bear['detail'],
        'plain': plain,
    }

    judgment = {
        'state': vp_info['state'],
        'light': vp_info['light'],
        'score': health_score,
    }

    audit_conditions = [
        {'name': '量价关系', 'satisfied': vp_info['state'] in ('强健康', '健康'),
         'actual': vp_info['state'], 'threshold': '健康或强健康',
         'detail': f"量价状态：{vp_info['state']}"},
        {'name': '健康度评分', 'satisfied': health_score >= 5,
         'actual': f"{health_score}/10", 'threshold': '≥5分',
         'detail': f"健康度评分：{health_score}/10"},
        {'name': '背离检测', 'satisfied': not divergence['detected'],
         'actual': '有背离' if divergence['detected'] else '无背离',
         'threshold': '无背离信号', 'detail': divergence['detail']},
        {'name': '量能强度', 'satisfied': volume_energy['level'] in ('温和放量', '放量'),
         'actual': volume_energy['level'], 'threshold': '放量或温和放量',
         'detail': volume_energy['detail']},
    ]
    satisfied_count = sum(1 for c in audit_conditions if c['satisfied'])

    return {
        'status_description': status_description,
        'judgment': judgment,
        'audit': {
            'conditions': audit_conditions,
            'satisfied_count': satisfied_count,
            'total_count': len(audit_conditions),
            'confidence': satisfied_count / len(audit_conditions) if audit_conditions else 0,
        },
    }


def _assess_vp_state(dims: dict, tags: dict) -> dict:
    """量价状态判定"""
    vp_state = dims.get('vp', {}).get('state', '中性')
    light_map = {'强健康': 'green', '健康': 'green', '中性': 'yellow',
                 '背离': 'red', '严重背离': 'red'}
    return {'state': vp_state, 'light': light_map.get(vp_state, 'yellow')}


def _calc_health_score_10(dims: dict, tags: dict, signals: dict) -> int:
    """10分制健康度评分

    评分公式：
      raw_score = vp_pattern_score + volume_energy + ma_alignment + chip_density + indicator + divergence_penalty
      归一化到0-10分（raw_score范围约-4~+8）
    """
    vp_state = dims.get('vp', {}).get('state', '中性')

    # 1. 量价形态得分（-2~+3）
    vp_pattern = str(tags.get('volume_price_fit', ''))
    if vp_pattern == 'healthy':
        vp_pattern_score = 2
    elif vp_pattern == 'diverging':
        vp_pattern_score = -1
    else:
        vp_pattern_score = 1  # neutral默认

    # 2. 量能强度（0~2）
    vol_ratio = float(tags.get('volume_ratio', 1.0))
    if vol_ratio > 2.0:
        volume_energy = 2
    elif vol_ratio > 1.2:
        volume_energy = 1.5
    elif vol_ratio > 0.8:
        volume_energy = 1
    else:
        volume_energy = 0

    # 3. 均线排列（0~1）
    ma_align = str(tags.get('ma_alignment', ''))
    if ma_align in ('多头排列', 'bullish'):
        ma_score = 1
    elif ma_align in ('空头排列', 'bearish'):
        ma_score = 0
    else:
        ma_score = 0.5

    # 4. 筹码密集度（0~1）
    chip_conc = str(tags.get('chip_concentration', ''))
    chip_score = 1 if chip_conc in ('单峰密集', 'tight') else 0.5

    # 5. 指标验证（0~1）
    rsi = float(tags.get('RSI_14', 50))
    indicator_score = 0.5  # 默认中性
    if 40 <= rsi <= 60:
        indicator_score = 0.5
    elif 60 < rsi <= 70:
        indicator_score = 1
    elif 30 <= rsi < 40:
        indicator_score = 0.8
    elif rsi > 70 or rsi < 30:
        indicator_score = 0.2

    # 6. 背离惩罚（-2~0）
    divergence_penalty = 0
    vp_detail = dims.get('vp', {}).get('evidence', [])
    if any('背离' in str(e) for e in vp_detail):
        divergence_penalty = -1.5

    # 归一化到0-10
    raw = vp_pattern_score + volume_energy + ma_score + chip_score + indicator_score + divergence_penalty
    # raw范围约-4~+8，归一化到0-10
    normalized = max(0, min(10, int(round((raw + 4) / 12 * 10))))
    return normalized


def _assess_divergence(tags: dict) -> dict:
    """背离检测"""
    vp_detail = str(tags.get('volume_price_fit', ''))
    if vp_detail == 'diverging':
        return {'detected': True, 'level': '有背离', 'detail': '量价背离信号已检测'}
    return {'detected': False, 'level': '无背离', 'detail': '无背离信号'}


def _assess_volume_energy(tags: dict) -> dict:
    """量能强度"""
    vol_ratio = float(tags.get('volume_ratio', 1.0))
    if vol_ratio > 2.0:
        return {'level': '显著放量', 'ratio': vol_ratio, 'detail': f"量比{vol_ratio:.1f}，显著放量"}
    elif vol_ratio > 1.2:
        return {'level': '温和放量', 'ratio': vol_ratio, 'detail': f"量比{vol_ratio:.1f}，温和放量"}
    elif vol_ratio > 0.8:
        return {'level': '正常', 'ratio': vol_ratio, 'detail': f"量比{vol_ratio:.1f}，正常"}
    else:
        return {'level': '量能萎缩', 'ratio': vol_ratio, 'detail': f"量比{vol_ratio:.1f}，量能萎缩"}


def _assess_pattern(tags: dict) -> dict:
    """形态识别"""
    pattern = str(tags.get('kline_pattern', ''))
    if pattern:
        return {'detected': True, 'detail': f"匹配形态：{pattern}"}
    return {'detected': False, 'detail': '无明确形态'}


def _assess_bull_bear(tags: dict) -> dict:
    """多空对抗"""
    return {'detail': '数据不足（待实现）'}


def _score_level(score: int) -> str:
    """分数等级映射"""
    if score >= 8:
        return '强健康'
    elif score >= 6:
        return '健康'
    elif score >= 4:
        return '中性'
    elif score >= 2:
        return '弱'
    else:
        return '严重背离'


def _vp_plain(vp_info, health_score, divergence, volume_energy, pattern) -> str:
    """第3维plain白话文本生成（365号修订）

    358号要求：描述量价关系的具体行为模式，用交易者语言。
    """
    state = vp_info.get('state', '中性')
    level = volume_energy.get('level', '')
    ratio = volume_energy.get('ratio', 1.0)

    # 核心叙事：量价配合状态
    if state in ('健康', '强健康'):
        core = '上涨时有量配合'
        if level == '量能萎缩':
            core += '，近期回调缩量（整理蓄势中）'
        elif level == '温和放量':
            core += '，量能温和释放'
        elif level == '显著放量':
            core += '，量能显著放大（关注持续性）'
        else:
            core += '，量能正常'
    elif state in ('背离', '严重背离'):
        core = '价量出现背离信号——价格创新高但量能未跟上，需警惕回调'
    elif state == '中性':
        core = f'量价关系中性，量比{ratio:.1f}'
        if level == '量能萎缩':
            core += '（缩量观望）'
    else:
        core = f'量价状态{state}'

    # 形态补充
    if pattern.get('detected') and pattern.get('detail', '').find('none') == -1:
        core += f'，{pattern["detail"]}'

    # 健康度结论
    score_desc = _score_level(health_score) if health_score else ''
    if score_desc:
        core += f'（健康度{health_score}/10，{score_desc}）'

    return core
