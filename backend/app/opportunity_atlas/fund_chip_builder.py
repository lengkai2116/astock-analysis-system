"""fund_chip_builder.py — 第4维资金筹码输出结构化构建器

364c Phase 3：将资金筹码维度拆解为6个子维度的结构化输出。
"""
from __future__ import annotations
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def build_fund_chip(
    dims: dict,
    tags: dict,
    signals: dict,
    l0: dict = None,
    sub_scores: dict = None,
) -> dict:
    """构建第4维资金筹码结构化输出

    Returns:
        {
            'status_description': {phase, fund_flow, cost_structure, signal,
                                    retail_institution, margin, plain},
            'judgment': {phase, direction, light},
            'audit': {conditions, satisfied_count, total_count, confidence}
        }
    """
    l0 = l0 or {}
    sub_scores = sub_scores or {}

    phase_info = _assess_phase(tags, dims)
    fund_flow_info = _assess_fund_flow(tags, sub_scores)
    cost_structure = _assess_cost_structure(tags)
    signal_info = _assess_signal(tags, dims)
    retail_inst = _assess_retail_institution(tags, dims)
    margin_info = _assess_margin(tags)

    plain = _fund_chip_plain(phase_info, fund_flow_info, cost_structure, signal_info, retail_inst, margin_info)

    status_description = {
        'phase': f"{phase_info['phase_cn']}（{phase_info['detail']}）",
        'fund_flow': f"{fund_flow_info['level_cn']}（{fund_flow_info['detail']}）",
        'cost_structure': cost_structure['detail'],
        'signal': signal_info['detail'],
        'retail_institution': retail_inst['detail'],
        'margin': margin_info['detail'],
        'plain': plain,
    }

    judgment = {
        'phase': phase_info['phase'],
        'direction': fund_flow_info['direction'],
        'light': phase_info['light'],
    }

    audit_conditions = [
        {'name': '主力阶段', 'satisfied': bool(phase_info['phase']),
         'actual': phase_info['phase_cn'], 'threshold': '有明确阶段判定',
         'detail': phase_info['detail']},
        {'name': '资金流向', 'satisfied': fund_flow_info['level'] != 'none',
         'actual': fund_flow_info['level_cn'], 'threshold': '有明确流向',
         'detail': fund_flow_info['detail']},
        {'name': '筹码集中', 'satisfied': bool(cost_structure.get('concentration')),
         'actual': cost_structure.get('concentration', '未知'), 'threshold': '有集中度数据',
         'detail': cost_structure['detail']},
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


def _assess_phase(tags: dict, dims: dict) -> dict:
    """主力阶段判定"""
    mfp = str(tags.get('main_force_phase', ''))
    phase_map = {
        'building': ('建仓期', '低位吸筹阶段'),
        'washing': ('洗盘期', '清洗浮筹阶段'),
        'raising': ('拉升期', '快速上涨阶段'),
        'distributing': ('出货期', '高位派发阶段'),
        'support': ('护盘期', '支撑维护阶段'),
    }
    if mfp in phase_map:
        cn, desc = phase_map[mfp]
        light = 'green' if mfp in ('building', 'raising') else ('red' if mfp == 'distributing' else 'yellow')
        return {'phase': mfp, 'phase_cn': cn, 'detail': desc, 'light': light}
    return {'phase': 'unknown', 'phase_cn': '未知', 'detail': '主力阶段数据缺失', 'light': 'yellow'}


def _assess_fund_flow(tags: dict, sub_scores: dict) -> dict:
    """资金流向5级强度分层"""
    ff = str(tags.get('fund_flow', ''))
    if ff == '5d_inflow':
        level = 'strong'
        level_cn = '强流入'
        direction = 'inflow'
        detail = '大单5日净流入'
    elif ff == '5d_outflow':
        level = 'strong_out'
        level_cn = '强流出'
        direction = 'outflow'
        detail = '大单5日净流出'
    else:
        level = 'none'
        level_cn = '中性'
        direction = 'neutral'
        detail = '无明确资金流向'

    moneyflow = sub_scores.get('moneyflow', 0)
    if moneyflow > 2.0:
        level = 'very_strong'
        level_cn = '极强流入'
        detail = f'资金评分{moneyflow:.1f}/3.0（极强）'
    elif moneyflow > 1.0:
        level = 'strong'
        level_cn = '强流入'
        detail = f'资金评分{moneyflow:.1f}/3.0（强）'
    elif moneyflow > 0.5:
        level = 'medium'
        level_cn = '中等'
        detail = f'资金评分{moneyflow:.1f}/3.0（中等）'
    elif moneyflow > 0:
        level = 'weak'
        level_cn = '弱'
        detail = f'资金评分{moneyflow:.1f}/3.0（弱）'

    return {'level': level, 'level_cn': level_cn, 'direction': direction, 'detail': detail}


def _assess_cost_structure(tags: dict) -> dict:
    """成本分布结构"""
    parts = []
    concentration = str(tags.get('chip_concentration', ''))
    if concentration:
        parts.append(f"筹码{concentration}")

    asr = tags.get('asr')
    if asr is not None:
        try:
            asr_val = float(asr)
            parts.append(f"ASR={asr_val:.0f}")
        except (TypeError, ValueError):
            pass

    profit_ratio = tags.get('profit_ratio')
    if profit_ratio is not None:
        try:
            pr_val = float(profit_ratio)
            parts.append(f"获利盘{pr_val:.0%}")
        except (TypeError, ValueError):
            pass

    detail = '，'.join(parts) if parts else '筹码数据不足'
    return {'detail': detail, 'concentration': concentration}


def _assess_signal(tags: dict, dims: dict) -> dict:
    """筹码信号状态"""
    bsp = str(tags.get('buy_sell_point', ''))
    signal_map = {
        'first_buy': '一买信号',
        'second_buy': '二买信号',
        'third_buy': '三买信号',
        'first_sell': '一卖信号',
        'second_sell': '二卖信号',
    }
    if bsp in signal_map:
        return {'detail': signal_map[bsp], 'signal': bsp}
    return {'detail': '无明确筹码信号', 'signal': 'none'}


def _assess_retail_institution(tags: dict, dims: dict) -> dict:
    """散户与机构博弈"""
    mfp = str(tags.get('main_force_phase', ''))
    fund_flow = str(tags.get('fund_flow', ''))

    if mfp == 'building' and fund_flow == '5d_inflow':
        return {'detail': '主力建仓+资金流入（机构买入）'}
    elif mfp == 'distributing':
        return {'detail': '主力出货（抛压风险）'}
    else:
        return {'detail': '散户与机构博弈中性'}


def _assess_margin(tags: dict) -> dict:
    """融资杠杆变化"""
    margin_change = tags.get('margin_change_5d')
    if margin_change is not None:
        try:
            mc = float(margin_change)
            if mc > 10:
                return {'detail': f'融资余额5日增加{mc:.0f}%（散户杠杆在上升）'}
            elif mc < -10:
                return {'detail': f'融资余额5日减少{abs(mc):.0f}%（散户在去杠杆）'}
            else:
                return {'detail': f'融资余额5日变化{mc:+.0f}%（正常范围）'}
        except (TypeError, ValueError):
            pass
    return {'detail': '融资数据不足'}


def _fund_chip_plain(phase, fund_flow, cost, signal, retail_inst, margin) -> str:
    """第4维plain白话文本生成（365号修订）

    358号要求：描述"谁在买、筹码如何"的具体事实，用交易者语言。
    """
    parts = []

    # 主力行为描述
    phase_name = phase.get('phase', 'unknown')
    phase_cn = phase.get('phase_cn', '')
    if phase_name == 'building':
        parts.append(f'大资金在逐步建仓（{phase.get("detail", "低位吸筹")}）')
    elif phase_name == 'raising':
        parts.append(f'主力正在拉升（{phase.get("detail", "")}）')
    elif phase_name == 'washing':
        parts.append(f'主力在洗盘（清洗浮筹）')
    elif phase_name == 'distributing':
        parts.append(f'主力在高位派发（出货风险）')
    elif phase_name != 'unknown':
        parts.append(f'主力处于{phase_cn}')

    # 资金流向 → 连续性描述
    flow_detail = fund_flow.get('detail', '')
    flow_dir = fund_flow.get('direction', '')
    if flow_dir == 'inflow':
        parts.append(f'资金净流入（{flow_detail}）')
    elif flow_dir == 'outflow':
        parts.append(f'资金净流出（{flow_detail}）')

    # 筹码结构 → 集中/分散
    cost_detail = cost.get('detail', '')
    if cost_detail and '数据不足' not in cost_detail:
        parts.append(f'筹码{cost.get("concentration", "")}（{cost_detail}）')

    # 融资情况
    margin_detail = margin.get('detail', '')
    if margin_detail and '数据不足' not in margin_detail:
        parts.append(margin_detail)

    return '，'.join(parts) if parts else '资金筹码数据不足，无法判断主力动向'
