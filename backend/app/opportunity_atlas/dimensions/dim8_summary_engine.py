"""第8维 状态总结引擎

358号方案 v4.1：第8维状态总结（纯整理输出）。

职责：读取 dim1-dim7 的 plain 字段和 judgment 输出，
     组装为综合状态条 + 八维红绿灯映射 + 共识率 + 冲突检测。

设计原则（358号§6.1）：
  - 第7维（状态总结）是纯整理输出，不变更内容、不判定
  - 读取前7维的 plain 字段并组装
  - 输出 status_bar + eight_dim_summary + consensus_rate + conflict + text

统一接口：evaluate(dims, tags, signals, lifecycle) → {status_description, judgment, audit}
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 状态条8态定义（358号 + 现有系统兼容）
# ═══════════════════════════════════════════════════════════

STATUS_BAR_STATES = {
    'strong_confirm': '强势确认',
    'trend_confirm': '趋势确认',
    'light_confirm': '轻仓确认',
    'neutral': '中性观望',
    'cautious': '谨慎观望',
    'risk_warning': '风险警示',
    'bearish': '看空回避',
    'exit': '退出观望',
}


# ═══════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════

def _extract_dim_judgment(dim_results: dict, dim_name: str) -> dict:
    """从维度引擎结果中提取 judgment"""
    result = dim_results.get(dim_name, {})
    if result and isinstance(result, dict):
        return result.get('judgment', {})
    return {}


def _extract_dim_light(dim_results: dict, dim_name: str) -> str:
    """从维度引擎结果中提取 overall_light"""
    jg = _extract_dim_judgment(dim_results, dim_name)
    return jg.get('overall_light', jg.get('light', 'yellow'))


def _extract_dim_direction(dim_results: dict, dim_name: str) -> int:
    """从维度引擎结果中提取 overall_direction"""
    jg = _extract_dim_judgment(dim_results, dim_name)
    return jg.get('overall_direction', 0)


def _extract_dim_plain(dim_results: dict, dim_name: str) -> str:
    """从维度引擎结果中提取 plain 文本"""
    result = dim_results.get(dim_name, {})
    if result and isinstance(result, dict):
        sd = result.get('status_description', {})
        return sd.get('plain', '')
    return ''


def _extract_dim_audit_confidence(dim_results: dict, dim_name: str) -> float:
    """从维度引擎结果中提取 audit.confidence"""
    result = dim_results.get(dim_results, {})
    if result and isinstance(result, dict):
        au = result.get('audit', {})
        return au.get('confidence', 0)
    return 0


# ═══════════════════════════════════════════════════════════
# 八维红绿灯映射
# ═══════════════════════════════════════════════════════════

def _build_eight_dim_summary(dim_results: dict) -> dict:
    """构建八维红绿灯映射"""
    dim_map = {
        'signal': '信号确认',
        'structure': '结构位置',
        'volume_price': '量价健康',
        'fund_chip': '资金筹码',
        'emotion': '情绪环境',
        'risk': '风险边界',
        'valuation': '价值估算',
        'summary': '状态总结',
    }
    summary = {}
    for key, name in dim_map.items():
        if key == 'summary':
            summary[key] = {'name': name, 'light': 'yellow'}
            continue
        light = _extract_dim_light(dim_results, key)
        summary[key] = {'name': name, 'light': light}
    return summary


# ═══════════════════════════════════════════════════════════
# 共识率计算
# ═══════════════════════════════════════════════════════════

# 维度权重（基于358号方案的动态权重简化版）
DIM_WEIGHTS = {
    'signal': 0.15,
    'structure': 0.20,
    'volume_price': 0.15,
    'fund_chip': 0.20,
    'emotion': 0.10,
    'risk': 0.15,
    'valuation': 0.05,
}


def _calc_consensus_rate(dim_results: dict) -> float:
    """加权共识率：综合7维方向的一致性

    green → +1, yellow → 0, red → -1
    加权平均后映射到0-1
    """
    light_to_value = {'green': 1.0, 'yellow': 0.0, 'red': -1.0}
    total = 0.0
    weight_sum = 0.0
    for dim_key, weight in DIM_WEIGHTS.items():
        light = _extract_dim_light(dim_results, dim_key)
        val = light_to_value.get(light, 0.0)
        total += val * weight
        weight_sum += weight

    if weight_sum > 0:
        avg = total / weight_sum
        # 映射到0-1: -1→0, 0→0.5, +1→1.0
        return round(max(0, min(1, (avg + 1) / 2)), 2)
    return 0.5


# ═══════════════════════════════════════════════════════════
# 冲突检测
# ═══════════════════════════════════════════════════════════

def _detect_conflicts(dim_results: dict) -> list[dict]:
    """检测维度间矛盾"""
    conflicts = []

    # 1. 结构上升 + 资金派发
    struct_dir = _extract_dim_direction(dim_results, 'structure')
    chip_phase = _extract_dim_judgment(dim_results, 'fund_chip').get('phase', '')
    if struct_dir == 1 and chip_phase == 'distributing':
        conflicts.append({
            'dim1': '结构位置', 'dim2': '资金筹码',
            'description': '结构上升但主力在出货——上涨可能是诱多',
            'severity': 'high',
        })

    # 2. 量价背离 + 信号确认
    vp_light = _extract_dim_light(dim_results, 'volume_price')
    signal_dir = _extract_dim_direction(dim_results, 'signal')
    if vp_light == 'red' and signal_dir == 1:
        conflicts.append({
            'dim1': '量价健康', 'dim2': '信号确认',
            'description': '量价背离但信号确认上涨——信号可靠性存疑',
            'severity': 'medium',
        })

    # 3. 情绪退潮 + 信号确认
    emotion_light = _extract_dim_light(dim_results, 'emotion')
    if emotion_light == 'red' and signal_dir == 1:
        conflicts.append({
            'dim1': '情绪环境', 'dim2': '信号确认',
            'description': '情绪退潮但信号确认上涨——追涨风险大',
            'severity': 'medium',
        })

    # 4. 风险高 + 估值低估
    risk_light = _extract_dim_light(dim_results, 'risk')
    val_light = _extract_dim_light(dim_results, 'valuation')
    if risk_light == 'red' and val_light == 'green':
        conflicts.append({
            'dim1': '风险边界', 'dim2': '价值估算',
            'description': '高风险但估值低估——可能是价值陷阱',
            'severity': 'low',
        })

    # 5. 结构下降 + 量价健康
    if struct_dir == -1 and vp_light == 'green':
        conflicts.append({
            'dim1': '结构位置', 'dim2': '量价健康',
            'description': '趋势下行但量价健康——可能是反弹',
            'severity': 'low',
        })

    return conflicts


# ═══════════════════════════════════════════════════════════
# 状态条推导
# ═══════════════════════════════════════════════════════════

def _derive_status_bar(dim_results: dict, consensus_rate: float,
                       conflicts: list) -> str:
    """从共识率+方向+冲突→8态状态条"""
    # 综合方向
    directions = []
    for dim in ['signal', 'structure', 'volume_price', 'fund_chip']:
        directions.append(_extract_dim_direction(dim_results, dim))

    pos_count = sum(1 for d in directions if d > 0)
    neg_count = sum(1 for d in directions if d < 0)

    risk_light = _extract_dim_light(dim_results, 'risk')
    emotion_light = _extract_dim_light(dim_results, 'emotion')

    # 高风险 → 风险警示/看空
    if risk_light == 'red':
        return 'risk_warning'

    # 有高严重度冲突 → 谨慎
    high_conflicts = [c for c in conflicts if c.get('severity') == 'high']
    if high_conflicts:
        return 'cautious'

    # 共识率 + 方向
    if consensus_rate >= 0.8 and pos_count >= 3:
        return 'strong_confirm'
    elif consensus_rate >= 0.7 and pos_count >= 2:
        return 'trend_confirm'
    elif consensus_rate >= 0.5 and pos_count >= 1:
        return 'light_confirm'
    elif neg_count >= 3:
        return 'bearish'
    elif consensus_rate < 0.3:
        return 'exit'
    else:
        return 'neutral'


# ═══════════════════════════════════════════════════════════
# 综合文字生成
# ═══════════════════════════════════════════════════════════

def _generate_text(dim_results: dict, status_bar: str,
                   consensus_rate: float, conflicts: list) -> str:
    """综合文字摘要"""
    bar_cn = STATUS_BAR_STATES.get(status_bar, status_bar)

    # 收集各维plain
    dim_names = ['signal', 'structure', 'volume_price', 'fund_chip', 'emotion', 'risk', 'valuation']
    dim_cn = {'signal': '信号', 'structure': '结构', 'volume_price': '量价',
              'fund_chip': '资金', 'emotion': '情绪', 'risk': '风险', 'valuation': '估值'}
    parts = []
    for dim in dim_names:
        plain = _extract_dim_plain(dim_results, dim)
        if plain:
            parts.append(f'{dim_cn.get(dim, dim)}：{plain}')

    dims_text = '；'.join(parts) if parts else '各维数据不足'

    # 冲突摘要
    conflict_text = ''
    if conflicts:
        conflict_items = [f"{c['description']}" for c in conflicts[:2]]
        conflict_text = f'（注意：{"；".join(conflict_items)}）'

    return f'{bar_cn}（共识{consensus_rate:.0%}）{conflict_text}——{dims_text}'


# ═══════════════════════════════════════════════════════════
# 第8维 引擎
# ═══════════════════════════════════════════════════════════

class Dim8SummaryEngine:
    """第8维 状态总结引擎 — 纯整理输出，读取 dim1-dim7 组装综合报告"""

    def evaluate(self, dims: dict, tags: dict, signals: dict = None,
                 lifecycle: dict = None) -> dict:
        """统一评估入口

        注意：dim_results 通过 lifecycle['dim_results'] 传入（StatusEngine 调用时注入）
        """
        dim_results = {}
        if lifecycle and isinstance(lifecycle, dict):
            dim_results = lifecycle.get('dim_results', {})
        elif signals and isinstance(signals, dict):
            dim_results = signals.get('dim_results', {})

        # 1. 八维红绿灯映射
        eight_dim_summary = _build_eight_dim_summary(dim_results)

        # 2. 共识率
        consensus_rate = _calc_consensus_rate(dim_results)

        # 3. 冲突检测
        conflicts = _detect_conflicts(dim_results)

        # 4. 状态条推导
        status_bar = _derive_status_bar(dim_results, consensus_rate, conflicts)
        status_bar_cn = STATUS_BAR_STATES.get(status_bar, status_bar)

        # 5. 综合文字
        text = _generate_text(dim_results, status_bar, consensus_rate, conflicts)

        # 6. status_description
        status_description = {
            'status_bar': status_bar_cn,
            'eight_dim_summary': eight_dim_summary,
            'consensus_rate': f"{consensus_rate:.0%}",
            'conflict_count': len(conflicts),
            'conflicts': [c['description'] for c in conflicts],
            'text': text,
            'plain': text,
        }

        # 7. judgment
        direction = 1 if consensus_rate >= 0.5 else (-1 if consensus_rate < 0.3 else 0)
        judgment = {
            'status_bar': status_bar,
            'status_bar_cn': status_bar_cn,
            'consensus_rate': consensus_rate,
            'direction': direction,
            'overall_light': 'green' if consensus_rate >= 0.6 else ('red' if consensus_rate < 0.3 else 'yellow'),
            'overall_direction': direction,
        }

        # 8. audit（纯整理的稽核：各维输出完整性）
        dim_names = ['signal', 'structure', 'volume_price', 'fund_chip', 'emotion', 'risk', 'valuation']
        conditions = []
        for dim in dim_names:
            has_output = bool(dim_results.get(dim))
            conditions.append({
                'name': f'{dim}引擎输出',
                'satisfied': has_output,
                'actual': '有输出' if has_output else '无输出',
                'threshold': '维度引擎有输出',
            })
        satisfied_count = sum(1 for c in conditions if c['satisfied'])
        total_count = len(conditions)
        audit = {
            'conditions': conditions,
            'satisfied_count': satisfied_count,
            'total_count': total_count,
            'confidence': satisfied_count / total_count if total_count > 0 else 0,
        }

        return {
            'status_description': status_description,
            'judgment': judgment,
            'audit': audit,
        }

    def get_data_dependencies(self) -> list:
        return [
            'dim1-dim7 引擎输出（通过 lifecycle["dim_results"] 传入）',
            'dims (StatusEngine) — 旧维度数据（兼容回退）',
        ]
