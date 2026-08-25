"""
条件稽核器（364号Phase 1）
================================
为每个维度的判定结果提供条件稽核能力，输出audit字段。

核心原则（360号7.3）：
- 现状描述的本质是条件稽核
- 对每个维度结论性输出背后的条件、规则、逻辑进行核查
- 报告哪些条件被满足、实际值是多少、阈值是多少
"""

import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class ConditionAuditor:
    """条件稽核器基类"""
    
    def audit(self, dims: dict, tags: dict, signals: dict) -> dict:
        """
        稽核该维度的判定条件
        
        Returns:
            {
                "conditions": [
                    {"name": "条件名称", "satisfied": True/False, 
                     "actual": "实际值", "threshold": "阈值", "detail": "详细说明"}
                ],
                "satisfied_count": int,
                "total_count": int,
                "confidence": float
            }
        """
        raise NotImplementedError


class SignalConditionAuditor(ConditionAuditor):
    """第1维：信号确认条件稽核"""
    
    def audit(self, dims: dict, tags: dict, signals: dict) -> dict:
        conditions = []
        
        # 条件1：信号触发
        active_signal = tags.get('active_signal', {})
        if isinstance(active_signal, str):
            import ast
            try:
                active_signal = ast.literal_eval(active_signal)
            except:
                active_signal = {}
        signal_triggered = bool(active_signal and active_signal.get('date'))
        conditions.append({
            'name': '信号触发',
            'satisfied': signal_triggered,
            'actual': '已触发' if signal_triggered else '未触发',
            'threshold': '需有活跃信号',
            'detail': f'活跃信号日期：{active_signal.get("date", "无")}' if signal_triggered else '无活跃信号'
        })
        
        # 条件2：信号验证
        time_dim = dims.get('time', {})
        lifecycle_stage = time_dim.get('state', '中期')
        verified = lifecycle_stage in ('初期', '中期')  # 初期/中期视为已验证
        conditions.append({
            'name': '信号验证',
            'satisfied': verified,
            'actual': lifecycle_stage,
            'threshold': '初期或中期（非已延伸/回撤）',
            'detail': f'生命周期阶段：{lifecycle_stage}'
        })
        
        # 条件3：共振维度
        resonance_count = self._count_resonance(dims)
        conditions.append({
            'name': '共振维度',
            'satisfied': resonance_count >= 2,
            'actual': f'{resonance_count}维',
            'threshold': '≥2维',
            'detail': f'共振维度数：{resonance_count}'
        })
        
        # 条件4：风险等级
        risk_level = dims.get('risk', {}).get('state', '中')
        conditions.append({
            'name': '风险等级',
            'satisfied': risk_level in ('低', '中'),
            'actual': risk_level,
            'threshold': '<高',
            'detail': f'风险等级：{risk_level}'
        })
        
        satisfied_count = sum(1 for c in conditions if c['satisfied'])
        total_count = len(conditions)
        
        return {
            'conditions': conditions,
            'satisfied_count': satisfied_count,
            'total_count': total_count,
            'confidence': satisfied_count / total_count if total_count > 0 else 0
        }
    
    def _count_resonance(self, dims: dict) -> int:
        """统计共振维度数"""
        count = 0
        for dim in ['structure', 'vp', 'chip_fund', 'factor']:
            if dims.get(dim, {}).get('confidence', 0) > 0.5:
                count += 1
        return count


class StructureConditionAuditor(ConditionAuditor):
    """第2维：结构位置条件稽核"""
    
    def audit(self, dims: dict, tags: dict, signals: dict) -> dict:
        conditions = []
        
        # 条件1：价格vs中枢
        position_vs_zs = tags.get('position_vs_zs', '')
        conditions.append({
            'name': '价格vs中枢',
            'satisfied': bool(position_vs_zs),
            'actual': position_vs_zs or '未知',
            'threshold': '有明确位置（上方/下方/内部）',
            'detail': f'价格位于中枢{position_vs_zs}' if position_vs_zs else '中枢位置数据缺失'
        })
        
        # 条件2：均线排列
        ma_alignment = tags.get('ma_alignment', '')
        conditions.append({
            'name': '均线排列',
            'satisfied': bool(ma_alignment),
            'actual': ma_alignment or '未知',
            'threshold': '有明确排列（多头/空头/缠绕）',
            'detail': f'均线排列：{ma_alignment}' if ma_alignment else '均线数据缺失'
        })
        
        # 条件3：价格位置
        price_position = tags.get('price_position', '')
        conditions.append({
            'name': '价格位置',
            'satisfied': bool(price_position),
            'actual': price_position or '中位',
            'threshold': '有明确位置',
            'detail': f'价格位置：{price_position}' if price_position else '位置数据缺失'
        })
        
        satisfied_count = sum(1 for c in conditions if c['satisfied'])
        total_count = len(conditions)
        
        return {
            'conditions': conditions,
            'satisfied_count': satisfied_count,
            'total_count': total_count,
            'confidence': satisfied_count / total_count if total_count > 0 else 0
        }


class VolumePriceConditionAuditor(ConditionAuditor):
    """第3维：量价健康条件稽核"""
    
    def audit(self, dims: dict, tags: dict, signals: dict) -> dict:
        conditions = []
        
        # 条件1：量价关系
        vp_state = dims.get('vp', {}).get('state', '中性')
        conditions.append({
            'name': '量价关系',
            'satisfied': vp_state in ('强健康', '健康'),
            'actual': vp_state,
            'threshold': '健康或强健康',
            'detail': f'量价状态：{vp_state}'
        })
        
        # 条件2：背离检测
        vp_evidence = dims.get('vp', {}).get('evidence', [])
        has_divergence = any('背离' in str(e) for e in vp_evidence)
        conditions.append({
            'name': '背离检测',
            'satisfied': not has_divergence,
            'actual': '有背离' if has_divergence else '无背离',
            'threshold': '无背离信号',
            'detail': '存在背离信号' if has_divergence else '无背离'
        })
        
        # 条件3：量比
        vol_ratio = tags.get('volume_ratio', 1.0)
        conditions.append({
            'name': '量比状态',
            'satisfied': 0.8 <= vol_ratio <= 3.0,
            'actual': f'{vol_ratio:.1f}',
            'threshold': '0.8-3.0（正常放量）',
            'detail': f'量比：{vol_ratio:.1f}'
        })
        
        satisfied_count = sum(1 for c in conditions if c['satisfied'])
        total_count = len(conditions)
        
        return {
            'conditions': conditions,
            'satisfied_count': satisfied_count,
            'total_count': total_count,
            'confidence': satisfied_count / total_count if total_count > 0 else 0
        }


class ChipFundConditionAuditor(ConditionAuditor):
    """第4维：资金筹码条件稽核"""
    
    def audit(self, dims: dict, tags: dict, signals: dict) -> dict:
        conditions = []
        
        # 条件1：主力阶段
        main_force_phase = tags.get('main_force_phase', '')
        phase_map = {'building': '建仓期', 'washing': '洗盘期', 'raising': '拉升期', 'distributing': '出货期'}
        conditions.append({
            'name': '主力阶段',
            'satisfied': bool(main_force_phase),
            'actual': phase_map.get(main_force_phase, main_force_phase or '未知'),
            'threshold': '有明确阶段判定',
            'detail': f'主力阶段：{phase_map.get(main_force_phase, main_force_phase)}' if main_force_phase else '主力阶段数据缺失'
        })
        
        # 条件2：资金流向
        fund_flow = tags.get('fund_flow', '')
        conditions.append({
            'name': '资金流向',
            'satisfied': bool(fund_flow),
            'actual': fund_flow or '未知',
            'threshold': '有明确流向',
            'detail': f'资金流向：{fund_flow}' if fund_flow else '资金流向数据缺失'
        })
        
        # 条件3：筹码集中度
        chip_concentration = tags.get('chip_concentration', '')
        conditions.append({
            'name': '筹码集中度',
            'satisfied': bool(chip_concentration),
            'actual': chip_concentration or '未知',
            'threshold': '有明确状态',
            'detail': f'筹码状态：{chip_concentration}' if chip_concentration else '筹码数据缺失'
        })
        
        satisfied_count = sum(1 for c in conditions if c['satisfied'])
        total_count = len(conditions)
        
        return {
            'conditions': conditions,
            'satisfied_count': satisfied_count,
            'total_count': total_count,
            'confidence': satisfied_count / total_count if total_count > 0 else 0
        }


class EmotionConditionAuditor(ConditionAuditor):
    """第5维：情绪环境条件稽核"""
    
    def audit(self, dims: dict, tags: dict, signals: dict) -> dict:
        conditions = []
        
        # 条件1：市场情绪
        emotion_state = dims.get('emotion', {}).get('state', '正常')
        conditions.append({
            'name': '市场情绪',
            'satisfied': emotion_state in ('复苏', '正常'),
            'actual': emotion_state,
            'threshold': '复苏或正常（非退潮）',
            'detail': f'市场情绪：{emotion_state}'
        })
        
        # 条件2：板块热度
        sector_heat = tags.get('sector_heat', '')
        conditions.append({
            'name': '板块热度',
            'satisfied': sector_heat in ('top_10', 'top_20'),
            'actual': sector_heat or '未知',
            'threshold': 'top_20以内',
            'detail': f'板块热度：{sector_heat}' if sector_heat else '板块数据缺失'
        })
        
        # 条件3：事件影响
        event_state = dims.get('event', {}).get('state', '中性')
        conditions.append({
            'name': '事件影响',
            'satisfied': event_state != '负面',
            'actual': event_state,
            'threshold': '非负面事件',
            'detail': f'事件状态：{event_state}'
        })
        
        satisfied_count = sum(1 for c in conditions if c['satisfied'])
        total_count = len(conditions)
        
        return {
            'conditions': conditions,
            'satisfied_count': satisfied_count,
            'total_count': total_count,
            'confidence': satisfied_count / total_count if total_count > 0 else 0
        }


class RiskConditionAuditor(ConditionAuditor):
    """第6维：风险边界条件稽核"""
    
    def audit(self, dims: dict, tags: dict, signals: dict) -> dict:
        conditions = []
        
        # 条件1：风险等级
        risk_level = dims.get('risk', {}).get('state', '中')
        conditions.append({
            'name': '风险等级',
            'satisfied': risk_level in ('低', '中'),
            'actual': risk_level,
            'threshold': '低或中（非高）',
            'detail': f'风险等级：{risk_level}'
        })
        
        # 条件2：估值状态
        valuation = dims.get('valuation', {}).get('state', '合理')
        conditions.append({
            'name': '估值状态',
            'satisfied': valuation in ('低估', '极度低估', '合理'),
            'actual': valuation,
            'threshold': '合理或低估',
            'detail': f'估值状态：{valuation}'
        })
        
        # 条件3：财务健康
        finance = dims.get('finance', {}).get('state', '关注')
        conditions.append({
            'name': '财务健康',
            'satisfied': finance == '健康',
            'actual': finance,
            'threshold': '健康',
            'detail': f'财务状态：{finance}'
        })
        
        satisfied_count = sum(1 for c in conditions if c['satisfied'])
        total_count = len(conditions)
        
        return {
            'conditions': conditions,
            'satisfied_count': satisfied_count,
            'total_count': total_count,
            'confidence': satisfied_count / total_count if total_count > 0 else 0
        }


# 维度稽核器映射
DIMENSION_AUDITORS = {
    'signal': SignalConditionAuditor(),
    'structure': StructureConditionAuditor(),
    'volume_price': VolumePriceConditionAuditor(),
    'fund_chip': ChipFundConditionAuditor(),
    'emotion': EmotionConditionAuditor(),
    'risk': RiskConditionAuditor(),
}


def audit_dimension(dim_key: str, dims: dict, tags: dict, signals: dict) -> dict:
    """对指定维度执行条件稽核"""
    auditor = DIMENSION_AUDITORS.get(dim_key)
    if auditor is None:
        return {'conditions': [], 'satisfied_count': 0, 'total_count': 0, 'confidence': 0}
    return auditor.audit(dims, tags, signals)
