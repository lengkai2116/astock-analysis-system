"""第1维 信号确认引擎

358号方案 v4.1：第1维信号确认维度引擎。

整合源：
  - signal_attribute_classifier.py（384行）：7类信号属性分类 + 共振评分 + 条件稽核
  - signal_decay_detector.py（145行）：5维度联合衰减检测
  - confirm_layer.py（230行）中的信号验证逻辑

统一接口：evaluate(dims, tags, signals, lifecycle) → {status_description, judgment, audit}
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 常量定义
# ═══════════════════════════════════════════════════════════

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

# 5维度衰减权重（359号§1.5）
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

# 生命周期阶段阈值（358号§4.3）
LIFECYCLE_THRESHOLDS = {
    'early_max_pct': 5.0,     # 初期：距突破位≤+5%
    'mid_max_pct': 12.0,      # 中期：距突破位+5%~+12%
    # 已延伸：距突破位>+12%
}

# 验证规则
VERIFICATION_RULES = {
    'buy_point': {'days': 3, 'rule': '3日不破信号价'},
    'breakout': {'days': 3, 'rule': '3日站稳突破位'},
    'ma_alignment': {'days': 5, 'rule': '5日维持多头'},
    'platform_breakout': {'days': 3, 'rule': '3日站稳中枢上沿'},
}


# ═══════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════

def _safe_float(v, default=0.0):
    try:
        return float(v) if v not in (None, '') else default
    except (TypeError, ValueError):
        return default


def _vp_health_score(dims: dict) -> int:
    raw = dims.get('vp', {}).get('confidence', 0)
    return int(_safe_float(raw) * 100)


def _count_resonance(dims: dict) -> int:
    count = 0
    for dim in ['structure', 'vp', 'chip_fund', 'factor']:
        if _safe_float(dims.get(dim, {}).get('confidence', 0)) > 0.5:
            count += 1
    return count


def _overall_light(attr_light: str, strength_level: str, decay_status: str) -> str:
    lights = [attr_light]
    lights.append('green' if strength_level in ('极强', '强') else ('yellow' if strength_level == '中等' else 'red'))
    lights.append('green' if decay_status == 'healthy' else ('yellow' if decay_status == 'fading' else 'red'))
    if 'red' in lights:
        return 'red'
    if lights.count('green') >= 2:
        return 'green'
    return 'yellow'


def _score_status_name(score: int) -> str:
    if score < 20:
        return '稳定'
    elif score < 40:
        return '轻微衰减'
    elif score < 60:
        return '中等衰减'
    elif score < 80:
        return '明显衰减'
    return '严重衰减'


# ═══════════════════════════════════════════════════════════
# 衰减检测（从 signal_decay_detector.py 迁移）
# ═══════════════════════════════════════════════════════════

def detect_decay(tags: dict, lifecycle: dict = None) -> dict:
    """5维度联合衰减检测"""
    lifecycle = lifecycle or {}
    scores = {}

    day = lifecycle.get('day', 0)
    if day <= 5:
        scores['price_trend'] = 0
    elif day <= 12:
        scores['price_trend'] = 20
    else:
        scores['price_trend'] = 50

    vp = str(tags.get('volume_price_fit', ''))
    if vp == 'diverging':
        scores['volume_price'] = 60
    elif vp == 'healthy':
        scores['volume_price'] = 10
    else:
        scores['volume_price'] = 30

    try:
        vol_ratio = float(tags.get('volume_ratio', 1.0))
        if vol_ratio < 0.5:
            scores['volume_energy'] = 50
        elif vol_ratio < 0.8:
            scores['volume_energy'] = 30
        else:
            scores['volume_energy'] = 10
    except (TypeError, ValueError):
        scores['volume_energy'] = 20

    phase = str(tags.get('main_force_phase', ''))
    if phase == 'distributing':
        scores['chip_change'] = 60
    elif phase == 'building':
        scores['chip_change'] = 5
    else:
        scores['chip_change'] = 20

    ff = str(tags.get('fund_flow', ''))
    if ff == '5d_outflow':
        scores['main_force'] = 50
    elif ff == '5d_inflow':
        scores['main_force'] = 5
    else:
        scores['main_force'] = 20

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


# ═══════════════════════════════════════════════════════════
# 信号属性分类（从 signal_attribute_classifier.py 迁移）
# ═══════════════════════════════════════════════════════════

def classify_attribute(dims: dict, tags: dict, lifecycle: dict) -> dict:
    """7类信号属性分类（359号§1.3）"""
    risk_level = str(dims.get('risk', {}).get('state', ''))
    right_side = str(tags.get('right_side_confirm', ''))
    buy_sell = str(tags.get('buy_sell_point', ''))
    structure = str(dims.get('structure', {}).get('state', ''))
    chip_state = str(dims.get('chip_fund', {}).get('state', ''))
    valuation = str(dims.get('valuation', {}).get('state', ''))
    verified = lifecycle.get('verified', False)
    structure_conf = _safe_float(dims.get('structure', {}).get('confidence', 0))

    # 优先级1：风险警示
    if risk_level == '高' or right_side == '否决':
        detail_parts = []
        if risk_level == '高':
            detail_parts.append(f'风险等级={risk_level}')
        if right_side == '否决':
            detail_parts.append('右侧否决')
        return {'code': 'risk_warning', 'name': '风险警示', 'detail': '、'.join(detail_parts)}

    # 优先级2：右侧确认（4条件全部满足）
    if right_side in ('强确认', '基础确认') and verified:
        resonance_count = _count_resonance(dims)
        if resonance_count >= 2:
            return {'code': 'right_confirmed', 'name': '右侧确认',
                    'detail': f'{right_side}，已验证，{resonance_count}维共振'}

    # 优先级3：右侧初现（信号匹配 AND 共振≥1）
    if buy_sell and buy_sell in ('first_buy', 'second_buy', 'third_buy'):
        resonance_count = _count_resonance(dims)
        if resonance_count >= 1:
            return {'code': 'right_emerging', 'name': '右侧初现',
                    'detail': f'买入信号{buy_sell}，{resonance_count}维共振'}

    # 优先级4：左侧试探（5条件全部满足）
    if (structure == '下降'
        and chip_state == '流入'
        and _vp_health_score(dims) > 60
        and valuation in ('低估', '极度低估')
        and risk_level != '高'):
        return {'code': 'left_probing', 'name': '左侧试探',
                'detail': '下跌中资金流入+量价健康+估值低估'}

    # 优先级5：趋势运行中（4条件全部满足）
    if (structure == '上升' and structure_conf > 0.6
        and not buy_sell
        and _vp_health_score(dims) > 50
        and risk_level != '高'):
        return {'code': 'trend_running', 'name': '趋势运行中',
                'detail': f'趋势明确（强度{structure_conf:.2f}），无新信号'}

    # 优先级6：盘整待变
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
        conf = _safe_float(dims.get(dim_key, {}).get('confidence', 0))
        scores[dim_key] = conf
        total += conf * weight
        if conf > 0.5:
            count += 1

    score = int(round(total * 100))
    level = '极强' if score >= 80 else ('强' if score >= 60 else ('中等' if score >= 40 else ('弱' if score >= 20 else '极弱')))
    resonance_dims = [k for k, v in scores.items() if v > 0.5]

    return {'score': score, 'level': level, 'count': count,
            'resonance_dims': resonance_dims}


# ═══════════════════════════════════════════════════════════
# 生命周期阶段计算（358号§4.3 新增）
# ═══════════════════════════════════════════════════════════

def _calc_lifecycle_stage(lifecycle: dict) -> dict:
    """计算信号生命周期阶段（初期/中期/已延伸）

    Wiki 信号生命周期定义：
    - 初期：距突破位 ≤ +5%
    - 中期：距突破位 +5%~+12%
    - 已延伸：距突破位 > +12%
    - 验证条件：3日不破突破位
    """
    day = lifecycle.get('day', 0)
    distance_pct = _safe_float(lifecycle.get('distance_to_signal_pct', None), None)
    verified = lifecycle.get('verified', False)
    stage = lifecycle.get('stage', '未知')

    # 基于距离百分比判定阶段（Wiki标准）
    if distance_pct is not None:
        if distance_pct <= LIFECYCLE_THRESHOLDS['early_max_pct']:
            lc_stage = '初期'
        elif distance_pct <= LIFECYCLE_THRESHOLDS['mid_max_pct']:
            lc_stage = '中期'
        else:
            lc_stage = '已延伸'
    else:
        # 无距离数据时，基于天数粗判
        if day <= 5:
            lc_stage = '初期'
        elif day <= 15:
            lc_stage = '中期'
        else:
            lc_stage = '已延伸'

    # 3日不破验证（Wiki信号注册表定义）
    verify_status = '无信号'
    if verified:
        verify_status = '已验证（3日不破）'
    elif day >= 3 and distance_pct is not None and distance_pct > 0:
        # 信号已持续3天+且价格仍在突破位上方 → 自动验证
        verified = True
        verify_status = '已验证（3日不破）'
    elif day > 0:
        verify_status = '待验证（未满3日）'

    return {
        'lifecycle_days': day,
        'lifecycle_stage': lc_stage,
        'verified': verified,
        'verify_status': verify_status,
        'distance_pct': distance_pct,
        'stage_detail': stage,
    }


# ═══════════════════════════════════════════════════════════
# 白话文本生成
# ═══════════════════════════════════════════════════════════

def _signal_plain(attr, strength, maintenance, lifecycle_info) -> str:
    """第1维plain白话文本"""
    code = attr.get('code', 'neutral')
    count = strength.get('count', 0)
    dims_list = strength.get('resonance_dims', [])
    day = lifecycle_info.get('lifecycle_days', 0)
    stage = lifecycle_info.get('lifecycle_stage', '')
    verified = lifecycle_info.get('verified', False)
    dist = lifecycle_info.get('distance_pct')
    score = strength.get('score', 0)

    if code in ('right_confirmed', 'right_emerging'):
        dim_cn = {'structure': '结构', 'vp': '量价', 'chip_fund': '资金', 'factor': '因子'}
        dim_names = '+'.join(dim_cn.get(d, d) for d in dims_list[:3]) if dims_list else '多维'
        verify_text = '已验证' if verified else '未验证'
        dist_text = f'，距信号价{"+" if (dist or 0) >= 0 else ""}{dist:.1f}%' if dist is not None else ''
        return f'{count}个信号共振确认上涨趋势（{dim_names}），{verify_text}{day}天（{stage}）{dist_text}，共振{score}分'
    elif code == 'left_probing':
        return '下跌中出现逆向信号：资金流入+量价健康+估值低估，左侧试探性介入'
    elif code == 'trend_running':
        return f'趋势明确运行中，无新触发信号，量价支撑'
    elif code == 'consolidating':
        return f'结构盘整，量价中性（{score}分），无明确方向信号，等待突破'
    elif code == 'risk_warning':
        return f'风险警示：{attr.get("detail", "存在高风险因子")}'
    else:
        missing = []
        if count == 0:
            missing.append('无共振信号')
        if not verified:
            missing.append('信号未验证')
        if score < 30:
            missing.append(f'共振弱（{score}分）')
        return f'暂无明确交易信号（{"，".join(missing) if missing else "各维信号不足"}）'


# ═══════════════════════════════════════════════════════════
# 条件稽核
# ═══════════════════════════════════════════════════════════

def _build_audit(attr, dims, tags, lifecycle, strength, maintenance) -> dict:
    """条件稽核（359号§1.7）"""
    code = attr['code']
    conditions = []

    if code == 'right_confirmed':
        right_side = str(tags.get('right_side_confirm', ''))
        conditions.append({'name': '信号注册表匹配', 'satisfied': right_side in ('强确认', '基础确认'),
                           'actual': right_side or '未匹配', 'threshold': '强确认或基础确认'})
        conditions.append({'name': '信号验证期', 'satisfied': lifecycle.get('verified', False),
                           'actual': f"第{lifecycle.get('day', 0)}天", 'threshold': '3-5日不破信号价'})
        conditions.append({'name': '共振维度≥2', 'satisfied': strength['count'] >= 2,
                           'actual': f"{strength['count']}维", 'threshold': '≥2维'})
        conditions.append({'name': '风险等级<高', 'satisfied': dims.get('risk', {}).get('state', '') != '高',
                           'actual': dims.get('risk', {}).get('state', ''), 'threshold': '<高'})
    elif code == 'left_probing':
        conditions.append({'name': '趋势下降', 'satisfied': dims.get('structure', {}).get('state') == '下降',
                           'actual': dims.get('structure', {}).get('state', ''), 'threshold': '下降'})
        conditions.append({'name': '资金流入', 'satisfied': dims.get('chip_fund', {}).get('state') == '流入',
                           'actual': dims.get('chip_fund', {}).get('state', ''), 'threshold': '流入'})
        conditions.append({'name': '量价>60', 'satisfied': _vp_health_score(dims) > 60,
                           'actual': str(_vp_health_score(dims)), 'threshold': '>60'})
        conditions.append({'name': '估值低估', 'satisfied': dims.get('valuation', {}).get('state') in ('低估', '极度低估'),
                           'actual': dims.get('valuation', {}).get('state', ''), 'threshold': '低估/极度低估'})
        conditions.append({'name': '风险<高', 'satisfied': dims.get('risk', {}).get('state') != '高',
                           'actual': dims.get('risk', {}).get('state', ''), 'threshold': '<高'})
    elif code == 'risk_warning':
        conditions.append({'name': '风险等级≥高', 'satisfied': dims.get('risk', {}).get('state', '') == '高',
                           'actual': dims.get('risk', {}).get('state', ''), 'threshold': '≥高'})
        conditions.append({'name': '右侧否决', 'satisfied': str(tags.get('right_side_confirm', '')) == '否决',
                           'actual': str(tags.get('right_side_confirm', '')) or '无', 'threshold': '否决'})
    else:
        conditions.append({'name': '信号触发', 'satisfied': code not in ('neutral', 'consolidating'),
                           'actual': attr['name'], 'threshold': '有明确信号'})
        conditions.append({'name': '共振维度', 'satisfied': strength['count'] >= 2,
                           'actual': f"{strength['count']}维", 'threshold': '≥2维'})
        conditions.append({'name': '信号验证', 'satisfied': lifecycle.get('verified', False),
                           'actual': '已验证' if lifecycle.get('verified') else '未验证',
                           'threshold': '3-5日不破信号价'})

    satisfied_count = sum(1 for c in conditions if c['satisfied'])
    total_count = len(conditions)
    return {
        'conditions': conditions,
        'satisfied_count': satisfied_count,
        'total_count': total_count,
        'confidence': satisfied_count / total_count if total_count > 0 else 0,
    }


# ═══════════════════════════════════════════════════════════
# 第1维 引擎
# ═══════════════════════════════════════════════════════════


# === confirm_layer.py (辅助验证层) ===

class ConfirmLayer:
    """
    多层辅助验证层
    对候选信号进行多层验证，返回调整后的置信度和仓位建议
    """

    def verify(self, signal: Dict, context: Dict) -> Dict:
        """
        对候选信号进行多层验证

        Args:
            signal: 待验证的信号
                {'signal_type': 'BUY'|'SELL', 'confidence': float, 'position': float, ...}
            context: 上下文数据
                {'turnover_rate': float, 'transfer_speed': float,
                 'vol_ratio': float, 'cyqkl': float, 'breakout_days': int,
                 'has_qmt': bool, 'order_imbalance': float,
                 'close_prices': List[float], 'breakout_price': float}

        Returns:
            {'action': 'HOLD'|'PASS', 'reason': str,
             'confidence': float, 'position': float}
        """
        confidence = signal.get('confidence', 0.5)
        position = signal.get('position', 0.5)
        signal_type = signal.get('signal_type', 'BUY')

        reasons = []

        # 1. 换手率验证
        turnover = context.get('turnover_rate', None)
        if turnover is not None:
            adj = self._verify_turnover(turnover, signal_type)
            confidence *= adj.get('confidence_mult', 1.0)
            if adj.get('reason'):
                reasons.append(adj['reason'])

        # 2. 转移速度验证
        transfer_speed = context.get('transfer_speed', None)
        if transfer_speed is not None:
            adj = self._verify_transfer_speed(transfer_speed, signal_type)
            confidence *= adj.get('confidence_mult', 1.0)
            position *= adj.get('position_mult', 1.0)
            if adj.get('reason'):
                reasons.append(adj['reason'])

        # 3. 五档盘口不平衡验证（QMT增强项）
        if context.get('has_qmt', False):
            imbalance = context.get('order_imbalance', 0)
            adj = self._verify_order_imbalance(imbalance, signal_type)
            confidence *= adj.get('confidence_mult', 1.0)
            if adj.get('reason'):
                reasons.append(adj['reason'])

        # 4. 假突破过滤器
        breakout_check = self._false_breakout_check(context)
        if not breakout_check['passed']:
            return {
                'action': 'HOLD',
                'reason': "假突破过滤: " + breakout_check['reason'],
                'confidence': 0.0,
                'position': 0.0
            }

        return {
            'action': 'PASS',
            'reason': '; '.join(reasons) if reasons else '全部验证通过',
            'confidence': round(confidence, 4),
            'position': round(position, 4)
        }

    # ---------- 子验证方法 ----------

    def _verify_turnover(self, turnover_rate: float, signal_type: str) -> Dict:
        """
        换手率验证（书本第3章§3.6）

        规则：
          turnover < 2%   -> 低活跃度，置信度*0.5
          turnover > 10%  -> SELL加强(1.2), BUY警惕(0.8)
          其他 -> 正常
        """
        if turnover_rate < 0.02:
            return {
                'confidence_mult': 0.5,
                'reason': "换手率{:.2f}%<2%(低活跃)".format(turnover_rate * 100)
            }
        elif turnover_rate > 0.10:
            if signal_type == 'SELL':
                return {
                    'confidence_mult': 1.2,
                    'reason': "换手率{:.2f}%>10%(卖出验证)".format(turnover_rate * 100)
                }
            else:
                return {
                    'confidence_mult': 0.8,
                    'reason': "换手率{:.2f}%>10%(买入警惕)".format(turnover_rate * 100)
                }
        return {'confidence_mult': 1.0, 'reason': ''}

    def _verify_transfer_speed(self, transfer_speed: float, signal_type: str) -> Dict:
        """
        转移速度验证（筹码加速转移时追高风险）

        规则：
          transfer_speed > 1%/日 -> 加速期
            BUY信号: confidence*0.8, position*0.7
            其他信号: 无调整
        """
        if transfer_speed > 0.01 and signal_type == 'BUY':
            return {
                'confidence_mult': 0.8,
                'position_mult': 0.7,
                'reason': "筹码加速转移({:.2f}%/日)追高风险".format(transfer_speed * 100)
            }
        return {'confidence_mult': 1.0, 'position_mult': 1.0, 'reason': ''}

    def _verify_order_imbalance(self, imbalance: float, signal_type: str) -> Dict:
        """
        五档盘口不平衡验证（QMT增强项）
        """
        if signal_type == 'BUY' and imbalance > 0.2:
            return {'confidence_mult': 1.15, 'reason': '盘口买盘旺盛'}
        elif signal_type == 'SELL' and imbalance < -0.2:
            return {'confidence_mult': 1.15, 'reason': '盘口卖盘旺盛'}
        elif signal_type == 'BUY' and imbalance < -0.1:
            return {'confidence_mult': 0.8, 'reason': '信号与盘口方向相反'}
        return {'confidence_mult': 1.0, 'reason': ''}

    def _false_breakout_check(self, context: Dict) -> Dict:
        """
        假突破过滤器 - 三维确认（书本第9章§9.3）

        维度1: 量能确认 - 突破日 vol_ratio >= 1.5
        维度2: 时间确认 - 突破后连续N日未回落
        维度3: 深度确认 - CYQKL >= 20%

        Returns:
            {'passed': bool, 'reason': str}
        """
        # 维度1：量能确认
        vol_ratio = context.get('vol_ratio', 0)
        if vol_ratio < 1.5:
            return {
                'passed': False,
                'reason': "量能不足(vol_ratio={:.2f}<1.5)".format(vol_ratio)
            }

        # 维度2：时间确认（突破后3日未回落）
        breakout_days = context.get('breakout_days', 0)
        if breakout_days < 3:
            return {
                'passed': False,
                'reason': "突破时间不足(breakout_days={}<3)".format(breakout_days)
            }

        # 维度3：深度确认（CYQKL >= 20%）
        cyqkl = context.get('cyqkl', 0)
        if cyqkl < 0.2:
            return {
                'passed': False,
                'reason': "穿透深度不足(cyqkl={:.2f}<0.2)".format(cyqkl)
            }

        return {'passed': True, 'reason': ''}

    def check_false_breakout(self, df: pd.DataFrame, indicators: Dict) -> Dict:
        """
        便捷的假突破检查接口，从K线和指标上下文中提取参数

        Args:
            df: K线数据
            indicators: 筹码指标字典

        Returns:
            {'is_real': bool, 'reason': str, 'details': Dict}
        """
        if df.empty or len(df) < 5:
            return {'is_real': False, 'reason': '数据不足', 'details': {}}

        latest = df.iloc[-1]
        closes = df['close'].values

        # 判断是否处于突破状态（价格在近期高位）
        if len(closes) >= 20:
            max_20 = np.max(closes[-20:])
            is_at_high = latest['close'] >= max_20 * 0.98
        else:
            is_at_high = False

        if not is_at_high:
            return {'is_real': False, 'reason': '非突破状态', 'details': {}}

        # 计算突破持续天数
        breakout_days = 0
        if len(closes) >= 3 and is_at_high:
            breakout_level = max_20 * 0.98
            for i in range(len(closes) - 1, -1, -1):
                if closes[i] >= breakout_level:
                    breakout_days += 1
                else:
                    break

        context = {
            'vol_ratio': indicators.get('vol_ratio', 0),
            'breakout_days': breakout_days,
            'cyqkl': indicators.get('cyqkl', 0),
        }

        result = self._false_breakout_check(context)
        return {
            'is_real': result['passed'],
            'reason': result['reason'],
            'details': context
        }


class Dim1SignalEngine:
    """第1维 信号确认引擎 — 7类属性分类 + 衰减检测 + 生命周期"""

    def evaluate(self, dims: dict, tags: dict, signals: dict = None,
                 lifecycle: dict = None) -> dict:
        """统一评估入口"""
        signals = signals or {}
        lifecycle = lifecycle or {}

        # 1. 信号属性分类
        attr = classify_attribute(dims, tags, lifecycle)

        # 2. 共振评分
        strength = calc_resonance_score(dims)

        # 3. 衰减检测
        decay = detect_decay(tags, lifecycle)

        # 4. 生命周期阶段（新增）
        lifecycle_info = _calc_lifecycle_stage(lifecycle)

        # 5. 综合维持评估
        maintenance = {
            'day': lifecycle_info['lifecycle_days'],
            'stage': lifecycle_info['stage_detail'],
            'verified': lifecycle_info['verified'],
            'distance_pct': lifecycle_info['distance_pct'],
            'decay_score': decay['overall_score'],
            'decay_status': decay['overall_status'],
            'decay_status_cn': decay['overall_status_cn'],
        }

        # 6. 风险交互
        risk_level = dims.get('risk', {}).get('state', '中')

        # 7. 白话文本
        plain = _signal_plain(attr, strength, maintenance, lifecycle_info)

        # 8. status_description
        status_description = {
            'attribute': f"{attr['name']}（{attr['detail']}）",
            'strength': f"{strength['score']}/100（{strength['level']}），共振维度：{', '.join(strength['resonance_dims'])}",
            'maintenance': f"信号第{maintenance['day']}天（{lifecycle_info['lifecycle_stage']}），衰减分{maintenance['decay_score']}（{maintenance['decay_status']}）",
            'risk_interaction': f"风险等级{risk_level}",
            'lifecycle_days': lifecycle_info['lifecycle_days'],
            'lifecycle_stage': lifecycle_info['lifecycle_stage'],
            'verified': lifecycle_info['verified'],
            'decay_detail': decay['detail'],
            'plain': plain,
        }

        # 9. judgment
        judgment = {
            'attribute': {'code': attr['code'], 'light': LIGHT_MAP.get(attr['code'], 'yellow')},
            'strength': {'level': strength['level'],
                         'light': 'green' if strength['score'] >= 60 else ('yellow' if strength['score'] >= 40 else 'red')},
            'maintenance': {'status': maintenance['decay_status'],
                            'light': 'green' if maintenance['decay_status'] == 'healthy' else ('yellow' if maintenance['decay_status'] == 'fading' else 'red')},
            'overall_light': _overall_light(LIGHT_MAP.get(attr['code'], 'yellow'),
                                            strength['level'], maintenance['decay_status']),
            'overall_direction': 1 if attr['code'] in ('right_confirmed', 'right_emerging', 'trend_running') else (-1 if attr['code'] == 'risk_warning' else 0),
            'continuous_value': round(strength['score'] / 100, 4),  # P2: [0,100]→[0,1]
        }

        # 10. audit
        audit = _build_audit(attr, dims, tags, lifecycle, strength, maintenance)

        return {
            'status_description': status_description,
            'judgment': judgment,
            'audit': audit,
        }

    def get_data_dependencies(self) -> list:
        return [
            'tags (pre_feat_cache) — right_side_confirm / buy_sell_point / volume_price_fit / fund_flow / main_force_phase',
            'dims (StatusEngine旧维度) — structure / vp / chip_fund / risk / valuation / factor',
            'lifecycle (strategy_signal_detail) — day / stage / verified / distance_to_signal_pct',
        ]
