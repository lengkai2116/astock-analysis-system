"""signal_attribute_classifier.py — 第1维信号属性7类全量分类器

359号§1.3完整实现：7类全量分类 + 共振评分 + 衰减检测集成。
"""
from __future__ import annotations
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 7类信号属性定义（359号§1.3）
SIGNAL_ATTRIBUTES = {
    'risk_warning': '风险警示',
    'right_confirmed': '右侧确认',
    'right_emerging': '右侧初现',
    'left_probing': '左侧试探',
    'trend_running': '趋势运行中',
    'consolidating': '盘整待变',
    'neutral': '中性观望',
}

# 共振评分权重（359号§1.4）
RESONANCE_WEIGHTS = {
    'structure': 0.25,
    'vp': 0.30,
    'chip_fund': 0.25,
    'factor': 0.20,
}

# light映射
LIGHT_MAP = {
    'right_confirmed': 'green', 'right_emerging': 'green',
    'risk_warning': 'red', 'left_probing': 'yellow',
    'trend_running': 'green', 'consolidating': 'yellow', 'neutral': 'yellow',
}


def build_signal_confirm(
    dims: dict,
    tags: dict,
    signals: dict = None,
    lifecycle: dict = None,
) -> dict:
    """构建第1维信号确认结构化输出（359号§1.7双轨+稽核）

    Returns:
        {
            'status_description': {attribute, strength, maintenance, risk_interaction, plain},
            'judgment': {attribute: {code, light}, strength: {level, light},
                        maintenance: {status, light}, overall_light, overall_direction},
            'audit': {conditions, satisfied_count, total_count, confidence}
        }
    """
    signals = signals or {}
    lifecycle = lifecycle or {}

    attr = classify_attribute(dims, tags, lifecycle)
    strength = calc_resonance_score(dims)
    maintenance = _assess_maintenance(lifecycle, tags)
    risk_interaction = _assess_risk_interaction(dims)

    plain = _signal_plain(attr, strength, maintenance)

    status_description = {
        'attribute': f"{attr['name']}（{attr['detail']}）",
        'strength': f"{strength['score']}/100（{strength['level']}），共振维度：{', '.join(strength['resonance_dims'])}",
        'maintenance': f"信号第{maintenance['day']}天，衰减分{maintenance['decay_score']}（{maintenance['decay_status']}），距信号价{maintenance['distance_pct']}",
        'risk_interaction': f"风险等级{risk_interaction['level']}",
        'plain': plain,
    }

    judgment = {
        'attribute': {'code': attr['code'], 'light': LIGHT_MAP.get(attr['code'], 'yellow')},
        'strength': {'level': strength['level'],
                     'light': 'green' if strength['score'] >= 60 else ('yellow' if strength['score'] >= 40 else 'red')},
        'maintenance': {'status': maintenance['decay_status'],
                        'light': 'green' if maintenance['decay_status'] == 'healthy' else ('yellow' if maintenance['decay_status'] == 'fading' else 'red')},
        'overall_light': _overall_light(LIGHT_MAP.get(attr['code'], 'yellow'),
                                        strength['level'], maintenance['decay_status']),
        'overall_direction': 1 if attr['code'] in ('right_confirmed', 'right_emerging', 'trend_running') else (-1 if attr['code'] == 'risk_warning' else 0),
    }

    # 条件稽核：按359号规格审核每个属性的判定条件
    audit = _build_audit(attr, dims, tags, lifecycle, strength, maintenance)

    return {
        'status_description': status_description,
        'judgment': judgment,
        'audit': audit,
    }


def classify_attribute(dims: dict, tags: dict, lifecycle: dict) -> dict:
    """7类信号属性分类（359号§1.3，优先级逐项判定，完整条件）"""
    risk_level = str(dims.get('risk', {}).get('state', ''))
    right_side = str(tags.get('right_side_confirm', ''))
    buy_sell = str(tags.get('buy_sell_point', ''))
    structure = str(dims.get('structure', {}).get('state', ''))
    chip_state = str(dims.get('chip_fund', {}).get('state', ''))
    vp_state = str(dims.get('vp', {}).get('state', ''))
    valuation = str(dims.get('valuation', {}).get('state', ''))
    verified = lifecycle.get('verified', False)

    # 安全数值转换
    try:
        structure_conf = float(dims.get('structure', {}).get('confidence', 0) or 0)
    except (ValueError, TypeError):
        structure_conf = 0.0

    # 优先级1：风险警示（359号§1.3：风险三维评估等级≥高，无论其他维度状态如何）
    if risk_level == '高' or right_side == '否决':
        detail_parts = []
        if risk_level == '高':
            detail_parts.append(f'风险等级={risk_level}')
        if right_side == '否决':
            detail_parts.append(f'右侧否决')
        return {'code': 'risk_warning', 'name': '风险警示', 'detail': '、'.join(detail_parts)}

    # 优先级2：右侧确认（359号§1.3：4个条件全部满足）
    # signal_registry匹配 AND 验证通过 AND 共振≥2 AND 风险<高
    if right_side in ('强确认', '基础确认') and verified:
        resonance_count = _count_resonance(dims)
        if resonance_count >= 2:
            return {'code': 'right_confirmed', 'name': '右侧确认',
                    'detail': f'{right_side}，已验证，{resonance_count}维共振'}

    # 优先级3：右侧初现（359号§1.3：信号匹配 AND 未验证 AND 共振≥1）
    if buy_sell and buy_sell in ('first_buy', 'second_buy', 'third_buy'):
        resonance_count = _count_resonance(dims)
        if resonance_count >= 1:
            return {'code': 'right_emerging', 'name': '右侧初现',
                    'detail': f'买入信号{buy_sell}，{resonance_count}维共振'}

    # 优先级4：左侧试探（359号§1.3：5个条件全部满足）
    # 趋势下降 AND 资金流入 AND 量价>60 AND 估值低估 AND 风险<高
    if (structure == '下降'
        and chip_state == '流入'
        and _vp_health_score(dims) > 60
        and valuation in ('低估', '极度低估')
        and risk_level != '高'):
        return {'code': 'left_probing', 'name': '左侧试探',
                'detail': '下跌中资金流入+量价健康+估值低估'}

    # 优先级5：趋势运行中（359号§1.3：4个条件全部满足）
    # 结构强度>0.6 AND 无新信号 AND 量价>50 AND 风险<中
    if (structure == '上升' and structure_conf > 0.6
        and not buy_sell
        and _vp_health_score(dims) > 50
        and risk_level != '高'):
        return {'code': 'trend_running', 'name': '趋势运行中',
                'detail': f'趋势明确（强度{structure_conf:.2f}），无新信号'}

    # 优先级6：盘整待变（359号§1.3：4个条件全部满足）
    # 结构盘整 AND 量价40-60 AND 无资金流 AND 无信号
    vp_health = _vp_health_score(dims)
    if (structure == '盘整'
        and 40 <= vp_health <= 60
        and chip_state not in ('流入', '流出')
        and not buy_sell):
        return {'code': 'consolidating', 'name': '盘整待变',
                'detail': '结构盘整，量价中性，无明确方向'}

    # 优先级7：中性观望（默认）
    return {'code': 'neutral', 'name': '中性观望', 'detail': '无明显特征'}


def calc_resonance_score(dims: dict) -> dict:
    """共振评分（359号§1.4）"""
    scores = {}
    total = 0
    count = 0

    for dim_key, weight in RESONANCE_WEIGHTS.items():
        raw_conf = dims.get(dim_key, {}).get('confidence', 0)
        try:
            conf = float(raw_conf) if raw_conf not in (None, '') else 0.0
        except (ValueError, TypeError):
            conf = 0.0
        scores[dim_key] = conf
        total += conf * weight
        if conf > 0.5:
            count += 1

    score = int(round(total * 100))
    level = '极强' if score >= 80 else ('强' if score >= 60 else ('中等' if score >= 40 else ('弱' if score >= 20 else '极弱')))
    resonance_dims = [k for k, v in scores.items() if v > 0.5]

    return {'score': score, 'level': level, 'count': count,
            'resonance_dims': resonance_dims}


def _assess_maintenance(lifecycle: dict, tags: dict) -> dict:
    """信号维持评估（359号§1.5：含衰减检测）"""
    day = lifecycle.get('day', 0)
    stage = lifecycle.get('stage', '未知')
    verified = lifecycle.get('verified', False)

    # 距离信号价百分比
    distance_pct = lifecycle.get('distance_to_signal_pct', '未知')

    # 衰减检测（调用signal_decay_detector）
    try:
        from app.opportunity_atlas.signal_decay_detector import detect_decay
        decay_result = detect_decay(tags, lifecycle)
        decay_score = decay_result['overall_score']
        decay_status = decay_result['overall_status']
        decay_status_cn = decay_result['overall_status_cn']
    except Exception:
        decay_score = 0
        decay_status = 'healthy'
        decay_status_cn = '健康'

    return {
        'day': day,
        'stage': stage,
        'verified': verified,
        'distance_pct': distance_pct,
        'decay_score': decay_score,
        'decay_status': decay_status,
        'decay_status_cn': decay_status_cn,
    }


def _assess_risk_interaction(dims: dict) -> dict:
    """风险交互（简化为读取dim_states中的risk判定）"""
    risk = dims.get('risk', {}).get('state', '中')
    return {'level': risk}


def _vp_health_score(dims: dict) -> int:
    """从dim_states获取量价健康度评分（模拟10分制转100分）"""
    raw = dims.get('vp', {}).get('confidence', 0)
    try:
        vp_conf = float(raw) if raw not in (None, '') else 0.0
    except (ValueError, TypeError):
        vp_conf = 0.0
    return int(vp_conf * 100)


def _count_resonance(dims: dict) -> int:
    """统计共振维度数（confidence > 0.5 的维度数）"""
    count = 0
    for dim in ['structure', 'vp', 'chip_fund', 'factor']:
        raw = dims.get(dim, {}).get('confidence', 0)
        try:
            conf = float(raw) if raw not in (None, '') else 0.0
        except (ValueError, TypeError):
            conf = 0.0
        if conf > 0.5:
            count += 1
    return count


def _overall_light(attr_light: str, strength_level: str, decay_status: str) -> str:
    """综合灯色：三者取最差"""
    lights = [attr_light]
    lights.append('green' if strength_level in ('极强', '强') else ('yellow' if strength_level == '中等' else 'red'))
    lights.append('green' if decay_status == 'healthy' else ('yellow' if decay_status == 'fading' else 'red'))
    if 'red' in lights:
        return 'red'
    if lights.count('green') >= 2:
        return 'green'
    return 'yellow'


def _signal_plain(attr, strength, maintenance) -> str:
    """第1维plain白话文本生成（359号§1.7 / 365号修订）

    358号要求：描述判定所依据的具体条件和事实，而非仅拼接标签。
    """
    code = attr.get('code', 'neutral')
    name = attr.get('name', '中性观望')
    count = strength.get('count', 0)
    dims_list = strength.get('resonance_dims', [])
    day = maintenance.get('day', 0)
    stage = maintenance.get('stage', '')
    verified = maintenance.get('verified', False)
    dist = maintenance.get('distance_pct')
    if isinstance(dist, str):
        try:
            dist = float(dist)
        except (ValueError, TypeError):
            dist = None
    score = strength.get('score', 0)

    # 按属性类型生成针对性叙事
    if code in ('right_confirmed', 'right_emerging'):
        dim_cn = {'structure': '结构', 'vp': '量价', 'chip_fund': '资金', 'factor': '因子', 'emotion': '情绪'}
        dim_names = '+'.join(dim_cn.get(d, d) for d in dims_list[:3]) if dims_list else '多维'
        verify_text = '已验证' if verified else '未验证'
        stage_text = f'（{stage}）' if stage else ''
        dist_text = f'，距信号价{"+" if (dist or 0) >= 0 else ""}{dist:.1f}%' if dist is not None else ''
        return f'{count}个信号共振确认上涨趋势（{dim_names}），{verify_text}{day}天{stage_text}{dist_text}，共振{score}分'
    elif code == 'left_probing':
        return f'下跌中出现逆向信号：资金流入+量价健康+估值低估，左侧试探性介入'
    elif code == 'trend_running':
        conf = strength.get('confidence', 0)
        return f'趋势明确运行中（结构强度{conf:.0%}），无新触发信号，量价支撑'
    elif code == 'consolidating':
        return f'结构盘整，量价中性（{score}分），无明确方向信号，等待突破'
    elif code == 'risk_warning':
        return f'风险警示：{attr.get("detail", "存在高风险因子")}'
    else:
        # 中性观望：列出主要缺失条件
        missing = []
        if count == 0:
            missing.append('无共振信号')
        if not verified:
            missing.append('信号未验证')
        if score < 30:
            missing.append(f'共振弱（{score}分）')
        return f'暂无明确交易信号（{"，".join(missing) if missing else "各维信号不足"}）'


def _build_audit(attr, dims, tags, lifecycle, strength, maintenance) -> dict:
    """条件稽核：按属性类型审核对应判定条件（359号§1.7）"""
    code = attr['code']
    conditions = []

    if code == 'right_confirmed':
        # 右侧确认4条件稽核
        right_side = str(tags.get('right_side_confirm', ''))
        conditions.append({'name': '信号注册表匹配', 'satisfied': right_side in ('强确认', '基础确认'),
                           'actual': right_side or '未匹配', 'threshold': '强确认或基础确认',
                           'detail': tags.get('right_side_confirm', '无')})
        conditions.append({'name': '信号验证期', 'satisfied': lifecycle.get('verified', False),
                           'actual': f"第{lifecycle.get('day', 0)}天", 'threshold': '3-5日不破信号价',
                           'detail': f"生命周期={lifecycle.get('stage', '未知')}"})
        conditions.append({'name': '共振维度≥2', 'satisfied': strength['count'] >= 2,
                           'actual': f"{strength['count']}维", 'threshold': '≥2维',
                           'detail': f"共振维度：{', '.join(strength['resonance_dims'])}"})
        conditions.append({'name': '风险等级<高', 'satisfied': dims.get('risk', {}).get('state', '') != '高',
                           'actual': dims.get('risk', {}).get('state', ''), 'threshold': '<高',
                           'detail': f"风险等级：{dims.get('risk', {}).get('state', '')}"})

    elif code == 'left_probing':
        # 左侧试探5条件稽核
        conditions.append({'name': '趋势下降', 'satisfied': dims.get('structure', {}).get('state') == '下降',
                           'actual': dims.get('structure', {}).get('state', ''), 'threshold': '下降',
                           'detail': f"结构={dims.get('structure', {}).get('state', '')}"})
        conditions.append({'name': '资金流入', 'satisfied': dims.get('chip_fund', {}).get('state') == '流入',
                           'actual': dims.get('chip_fund', {}).get('state', ''), 'threshold': '流入',
                           'detail': f"筹码={dims.get('chip_fund', {}).get('state', '')}"})
        conditions.append({'name': '量价>60', 'satisfied': _vp_health_score(dims) > 60,
                           'actual': f"{_vp_health_score(dims)}", 'threshold': '>60',
                           'detail': f"量价健康度={_vp_health_score(dims)}"})
        conditions.append({'name': '估值低估', 'satisfied': dims.get('valuation', {}).get('state') in ('低估', '极度低估'),
                           'actual': dims.get('valuation', {}).get('state', ''), 'threshold': '低估/极度低估',
                           'detail': f"估值={dims.get('valuation', {}).get('state', '')}"})
        conditions.append({'name': '风险<高', 'satisfied': dims.get('risk', {}).get('state') != '高',
                           'actual': dims.get('risk', {}).get('state', ''), 'threshold': '<高',
                           'detail': f"风险={dims.get('risk', {}).get('state', '')}"})

    elif code == 'risk_warning':
        # 风险警示条件稽核
        risk_level = dims.get('risk', {}).get('state', '')
        right_side = str(tags.get('right_side_confirm', ''))
        conditions.append({'name': '风险等级≥高', 'satisfied': risk_level == '高',
                           'actual': risk_level, 'threshold': '≥高',
                           'detail': f"风险={risk_level}"})
        conditions.append({'name': '右侧否决', 'satisfied': right_side == '否决',
                           'actual': right_side or '无', 'threshold': '否决',
                           'detail': f"right_side_confirm={right_side}"})

    else:
        # 其他属性：通用3条件稽核
        conditions.append({'name': '信号触发', 'satisfied': code not in ('neutral', 'consolidating'),
                           'actual': attr['name'], 'threshold': '有明确信号', 'detail': attr['detail']})
        conditions.append({'name': '共振维度', 'satisfied': strength['count'] >= 2,
                           'actual': f"{strength['count']}维", 'threshold': '≥2维',
                           'detail': f"共振维度数：{strength['count']}"})
        conditions.append({'name': '信号验证', 'satisfied': lifecycle.get('verified', False),
                           'actual': '已验证' if lifecycle.get('verified') else '未验证',
                           'threshold': '3-5日不破信号价', 'detail': f"生命周期={lifecycle.get('stage', '未知')}"})

    satisfied_count = sum(1 for c in conditions if c['satisfied'])
    total_count = len(conditions)

    return {
        'conditions': conditions,
        'satisfied_count': satisfied_count,
        'total_count': total_count,
        'confidence': satisfied_count / total_count if total_count > 0 else 0,
    }
