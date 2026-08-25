"""structure_builder.py — 第2维结构位置输出结构化构建器

364f Phase 6：将结构位置维度拆解为5子维度的结构化输出。
"""
from __future__ import annotations
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def build_structure(
    dims: dict,
    tags: dict,
    geo: dict = None,
) -> dict:
    """构建第2维结构位置结构化输出

    Returns:
        {
            'status_description': {vs_zhongshu, vs_ma, vs_support_resistance,
                                    vs_chip, vs_indicator, plain},
            'judgment': {structure, position, light},
            'audit': {conditions, satisfied_count, total_count, confidence}
        }
    """
    geo = geo or {}
    vs_zhongshu = _assess_vs_zhongshu(tags, dims)
    vs_ma = _assess_vs_ma(tags)
    vs_sr = _assess_vs_support_resistance(geo)
    vs_chip = _assess_vs_chip(tags)
    vs_indicator = _assess_vs_indicator(tags)

    plain = _structure_plain(vs_zhongshu, vs_ma, vs_sr, vs_chip, vs_indicator)

    status_description = {
        'vs_zhongshu': vs_zhongshu['detail'],
        'vs_ma': vs_ma['detail'],
        'vs_support_resistance': vs_sr['detail'],
        'vs_chip': vs_chip['detail'],
        'vs_indicator': vs_indicator['detail'],
        'plain': plain,
    }

    struct_state = dims.get('structure', {}).get('state', '盘整')
    pos_state = dims.get('position', {}).get('state', '中位')
    light = dims.get('structure', {}).get('light', 'yellow')

    judgment = {'structure': struct_state, 'position': pos_state, 'light': light}

    audit_conditions = [
        {'name': '价格vs中枢', 'satisfied': bool(vs_zhongshu['position']),
         'actual': vs_zhongshu['position'] or '未知', 'threshold': '有明确位置',
         'detail': vs_zhongshu['detail']},
        {'name': '均线排列', 'satisfied': bool(vs_ma['alignment']),
         'actual': vs_ma['alignment'] or '未知', 'threshold': '有明确排列',
         'detail': vs_ma['detail']},
        {'name': '支撑阻力', 'satisfied': bool(geo.get('support_price')),
         'actual': f"支撑位{geo.get('support_price', '无')}元" if geo.get('support_price') else '数据不足',
         'threshold': '有支撑位数据',
         'detail': vs_sr['detail']},
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


def _assess_vs_zhongshu(tags: dict, dims: dict) -> dict:
    """价格vs中枢"""
    position = str(tags.get('position_vs_zs', ''))
    if position:
        pct = tags.get('pct_from_zs', '')
        detail = f"价格位于中枢{position}" + (f"（距中枢{pct}）" if pct else "")
        return {'position': position, 'detail': detail}
    # 366号回退逻辑：从dims.structure.evidence提取
    struct_evidence = dims.get('structure', {}).get('evidence', [])
    for ev in struct_evidence:
        ev_str = str(ev)
        if '中枢' in ev_str:
            # 尝试从evidence中提取位置信息
            if '上方' in ev_str:
                return {'position': '上方', 'detail': f"价格位于中枢上方（{ev_str}）"}
            elif '下方' in ev_str:
                return {'position': '下方', 'detail': f"价格位于中枢下方（{ev_str}）"}
            elif '内部' in ev_str:
                return {'position': '内部', 'detail': f"价格在中枢内部（{ev_str}）"}
    return {'position': '', 'detail': '中枢位置数据不足'}


def _assess_vs_ma(tags: dict) -> dict:
    """价格vs均线"""
    alignment = str(tags.get('ma_alignment', ''))
    if alignment:
        return {'alignment': alignment, 'detail': f"均线{alignment}"}
    return {'alignment': '', 'detail': '均线数据不足'}


def _assess_vs_support_resistance(geo: dict) -> dict:
    """价格vs支撑阻力"""
    support = geo.get('support_price')
    resistance = geo.get('resistance_price')
    if support and resistance:
        return {'detail': f"距支撑位{geo.get('dist_to_support_pct', '')}，距压力位{geo.get('dist_to_resistance_pct', '')}"}
    elif support:
        return {'detail': f"距支撑位{geo.get('dist_to_support_pct', '')}"}
    return {'detail': '支撑阻力数据不足'}


def _assess_vs_chip(tags: dict) -> dict:
    """价格vs筹码"""
    conc = str(tags.get('chip_concentration', ''))
    profit = tags.get('profit_ratio')
    parts = []
    if conc:
        parts.append(f"筹码{conc}")
    if profit is not None:
        try:
            parts.append(f"获利盘{float(profit):.0%}")
        except (TypeError, ValueError):
            pass
    return {'detail': '，'.join(parts) if parts else '筹码数据不足'}


def _assess_vs_indicator(tags: dict) -> dict:
    """价格vs指标"""
    parts = []
    rsi = tags.get('RSI_14')
    if rsi is not None:
        try:
            parts.append(f"RSI={float(rsi):.0f}")
        except (TypeError, ValueError):
            pass
    kdj_j = tags.get('KDJ_J')
    if kdj_j is not None:
        try:
            parts.append(f"KDJ_J={float(kdj_j):.0f}")
        except (TypeError, ValueError):
            pass
    # 366号回退逻辑：尝试从其他key读取
    if not parts:
        # 尝试从timing组读取
        timing = tags.get('timing', {})
        if isinstance(timing, dict):
            rsi_val = timing.get('rsi14') or timing.get('RSI_14')
            if rsi_val is not None:
                try:
                    parts.append(f"RSI={float(rsi_val):.0f}")
                except (TypeError, ValueError):
                    pass
            kdj_val = timing.get('kdj_j') or timing.get('KDJ_J')
            if kdj_val is not None:
                try:
                    parts.append(f"KDJ_J={float(kdj_val):.0f}")
                except (TypeError, ValueError):
                    pass
    return {'detail': '，'.join(parts) if parts else '指标数据不足'}


def _structure_plain(vs_zhongshu, vs_ma, vs_sr, vs_chip, vs_indicator) -> str:
    """第2维plain白话文本生成（365号修订）

    358号要求：描述具体的结构位置事实，用交易者语言。
    """
    parts = []
    # 中枢位置 → 箱体/突破语言
    pos = vs_zhongshu.get('position', '')
    if pos == '上方':
        zs_det = vs_zhongshu.get('detail', '')
        parts.append("价格突破中枢上沿（%s），离开成本区" % zs_det)
    elif pos == '下方':
        parts.append(f"价格在中枢下方运行，仍处于调整区域")
    elif pos == '内部':
        parts.append(f"价格在中枢箱体内震荡，等待方向选择")

    # 均线排列 → 趋势方向
    ma = vs_ma.get('alignment', '')
    if ma and ma not in ('数据不足',):
        parts.append(f"均线{ma}")

    # 支撑阻力 → 具体价位+距离
    sr_detail = vs_sr.get('detail', '')
    if sr_detail and sr_detail != '支撑阻力数据不足':
        parts.append(sr_detail)

    # 筹码位置 → 套牢/获利状态
    chip_detail = vs_chip.get('detail', '')
    if chip_detail and chip_detail != '筹码数据不足':
        parts.append(chip_detail)

    return '，'.join(parts) if parts else '结构数据不足，无法判断当前位置'
