"""emotion_builder.py — 第5维情绪环境输出结构化构建器

364d Phase 4：将情绪环境维度拆解为三层面（市场/板块/个股）的结构化输出。
"""
from __future__ import annotations
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def build_emotion(
    dims: dict,
    tags: dict,
    l0: dict = None,
    bociasi_signal: str = '',
) -> dict:
    """构建第5维情绪环境结构化输出

    Returns:
        {
            'status_description': {market, sector, stock, plain},
            'judgment': {market_light, sector_light, stock_light, overall_light},
            'audit': {conditions, satisfied_count, total_count, confidence}
        }
    """
    l0 = l0 or {}
    market = _assess_market_emotion(tags, dims)
    sector = _assess_sector_emotion(tags, dims)
    stock = _assess_stock_emotion(tags, dims)

    plain = _emotion_plain(market, sector, stock)

    status_description = {
        'market': f"市场处于{market['phase']}（{market['detail']}）",
        'sector': f"板块{sector['heat']}（{sector['detail']}）",
        'stock': f"个股{stock['emotion']}（{stock['detail']}）",
        'plain': plain,
    }

    judgment = {
        'market_light': market['light'],
        'sector_light': sector['light'],
        'stock_light': stock['light'],
        'overall_light': _overall_light(market['light'], sector['light'], stock['light']),
    }

    audit_conditions = [
        {'name': '市场情绪', 'satisfied': market['phase'] not in ('退潮', '冰点'),
         'actual': market['phase'], 'threshold': '非退潮/冰点',
         'detail': market['detail']},
        {'name': '板块热度', 'satisfied': sector['heat'] in ('top_10', 'top_20'),
         'actual': sector['heat'], 'threshold': 'top_20以内',
         'detail': sector['detail']},
        {'name': '个股情绪', 'satisfied': stock['emotion'] not in ('极度消极',),
         'actual': stock['emotion'], 'threshold': '非极度消极',
         'detail': stock['detail']},
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


def _assess_market_emotion(tags: dict, dims: dict) -> dict:
    """市场情绪判定 — 以dim_states为主，tags为辅"""
    # 优先使用dim_states中的emotion判定
    dim_emotion = str(dims.get('emotion', {}).get('state', ''))
    dim_light = str(dims.get('emotion', {}).get('light', ''))
    if dim_emotion:
        light = 'red' if dim_light == 'red' else ('green' if dim_light == 'green' else 'yellow')
        return {'phase': dim_emotion, 'detail': f'L1判定情绪={dim_emotion}', 'light': light}

    sp = str(tags.get('sentiment_phase', ''))
    phase_map = {
        'ice': ('冰点', '市场极度低迷', 'red'),
        'sprout': ('萌芽', '市场情绪开始萌芽，出现连板龙头', 'yellow'),
        'ferment': ('发酵', '市场情绪发酵中，板块轮动活跃', 'green'),
        'climax': ('高潮', '市场情绪过热', 'red'),
        'ebb': ('退潮', '市场情绪开始降温', 'yellow'),
        'regression': ('回归', '市场情绪回归常态', 'yellow'),
        'recovery': ('复苏', '市场情绪开始回暖', 'green'),  # 兼容旧四阶段
    }
    if sp in phase_map:
        name, desc, light = phase_map[sp]
        return {'phase': name, 'detail': desc, 'light': light}
    return {'phase': '正常', 'detail': '情绪数据不足', 'light': 'yellow'}


def _assess_sector_emotion(tags: dict, dims: dict) -> dict:
    """板块情绪判定"""
    heat = str(tags.get('sector_heat', ''))
    heat_map = {
        'top_10': ('top_10', '板块排名前10（强势板块）', 'green'),
        'top_20': ('top_20', '板块排名11-20（活跃板块）', 'green'),
        'normal': ('normal', '板块排名20以外', 'yellow'),
        'none': ('none', '板块数据不足', 'yellow'),
    }
    if heat in heat_map:
        name, desc, light = heat_map[heat]
        return {'heat': name, 'detail': desc, 'light': light}
    return {'heat': 'normal', 'detail': '板块数据不足', 'light': 'yellow'}


def _assess_stock_emotion(tags: dict, dims: dict) -> dict:
    """个股情绪判定"""
    vp = str(dims.get('vp', {}).get('state', ''))
    if vp in ('强健康', '健康'):
        return {'emotion': '健康', 'detail': f"量价状态{vp}，趋势确认强势", 'light': 'green'}
    elif vp in ('背离', '严重背离'):
        return {'emotion': '关注', 'detail': f"量价状态{vp}，需警惕", 'light': 'yellow'}
    else:
        return {'emotion': '中性', 'detail': '量价数据不足', 'light': 'yellow'}


def _overall_light(market_light: str, sector_light: str, stock_light: str) -> str:
    """综合灯色"""
    lights = [market_light, sector_light, stock_light]
    if 'red' in lights:
        return 'red'
    if lights.count('green') >= 2:
        return 'green'
    return 'yellow'


def _emotion_plain(market: dict, sector: dict, stock: dict) -> str:
    """第5维plain白话文本生成（365号修订）

    358号要求：描述"现在是不是好时候"的具体市场氛围。
    """
    parts = []

    # 市场情绪 → 氛围描述
    phase = market.get('phase', '')
    detail = market.get('detail', '')
    if phase in ('冰点',):
        parts.append(f'市场极度低迷（{detail}）')
    elif phase in ('萌芽',):
        parts.append(f'市场开始回暖（{detail}）')
    elif phase in ('发酵',):
        parts.append(f'市场氛围偏暖（{detail}）')
    elif phase in ('高潮',):
        parts.append(f'市场情绪过热（{detail}）')
    elif phase in ('退潮',):
        parts.append(f'市场情绪降温（{detail}）')
    elif phase in ('回归', '复苏'):
        parts.append(f'市场情绪{phase}（{detail}）')
    elif phase:
        parts.append(f'市场情绪{phase}')
    else:
        parts.append('市场情绪数据不足')

    # 板块热度 → 风口/冷门
    heat = sector.get('heat', '')
    sector_detail = sector.get('detail', '')
    if heat == 'top_10':
        parts.append(f'所在板块在风口（{sector_detail}）')
    elif heat == 'top_20':
        parts.append(f'所在板块较活跃（{sector_detail}）')
    elif heat not in ('normal', 'none', ''):
        parts.append(f'板块{heat}')

    # 个股情绪
    stock_emo = stock.get('emotion', '')
    stock_detail = stock.get('detail', '')
    if stock_emo in ('健康',):
        parts.append(f'个股情绪健康（{stock_detail}）')
    elif stock_emo in ('关注',):
        parts.append(f'个股需关注（{stock_detail}）')
    elif stock_emo and stock_emo not in ('中性',):
        parts.append(f'个股{stock_emo}')

    return '，'.join(parts)
