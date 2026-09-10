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
    result = dim_results.get(dim_name, {})
    if result and isinstance(result, dict):
        au = result.get('audit', {})
        return au.get('confidence', 0)
    return 0


def _extract_dim_confidence(dim_results: dict, dim_name: str) -> float:
    """提取维度连续置信度（judgment.continuous_value），缺失回退 0.5（420号方案）"""
    jg = _extract_dim_judgment(dim_results, dim_name)
    try:
        return float(jg.get('continuous_value', 0.5))
    except (TypeError, ValueError):
        return 0.5


def _extract_dim_rr(dim_results: dict) -> float | None:
    """提取盈亏比（risk.status_description.rr_value），缺失返回 None（420号方案）"""
    result = dim_results.get('risk', {})
    if result and isinstance(result, dict):
        sd = result.get('status_description', {})
        if sd and isinstance(sd, dict):
            rr = sd.get('rr_value')
            if rr is None:
                return None
            try:
                return float(rr)
            except (TypeError, ValueError):
                return None
    return None


def _is_signal_decaying(dim_results: dict) -> bool:
    """信号是否老化：生命周期末期/衰竭 或 维护状态非 healthy（420号方案，对齐因子衰减概念）"""
    sig = dim_results.get('signal', {})
    if not isinstance(sig, dict):
        return False
    sd = sig.get('status_description', {})
    if isinstance(sd, dict):
        stage = str(sd.get('lifecycle_stage', ''))
        if '末' in stage or '衰竭' in stage:
            return True
    jg = sig.get('judgment', {})
    if isinstance(jg, dict):
        maint = jg.get('maintenance', {})
        if isinstance(maint, dict) and maint.get('status') not in (None, 'healthy'):
            return True
    return False


# ═══════════════════════════════════════════════════════════
# 八维红绿灯映射
# ═══════════════════════════════════════════════════════════

def _build_eight_dim_summary(dim_results: dict) -> dict:
    """构建八维红绿灯映射"""
    dim_map = {
        'signal': '信号确认',
        'structure': '结构位置',
        'volume_price': '量价健康',
        'chip_fund': '资金筹码',
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
    'chip_fund': 0.20,
    'emotion': 0.10,
    'risk': 0.15,
    'valuation': 0.05,
}


def _calc_consensus_rate(dim_results: dict) -> float:
    """加权共识率：灯色方向 × 连续置信度（420号方案增强）

    对齐知识库"多指标共识机制"——置信度高的维度对共识贡献更大。
    方向取灯色（green=+1/yellow=0/red=-1），权重 = DIM_WEIGHTS × 置信度修正。
    兼容性：continuous_value 缺失时置信度=0.5 → 权重同比例缩，结果与等权一致。
    """
    light_to_value = {'green': 1.0, 'yellow': 0.0, 'red': -1.0}
    total = 0.0
    weight_sum = 0.0
    for dim_key, base_w in DIM_WEIGHTS.items():
        light = _extract_dim_light(dim_results, dim_key)
        direction = light_to_value.get(light, 0.0)
        # 置信度修正：continuous_value 越高，该维对共识的贡献权重越大
        confidence = _extract_dim_confidence(dim_results, dim_key)
        eff_w = base_w * (0.3 + 0.7 * confidence)  # 保底 30% 权重，避免置信度 0 时维度失效
        total += direction * eff_w
        weight_sum += eff_w

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
    chip_phase = _extract_dim_judgment(dim_results, 'chip_fund').get('phase', '')
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

    # ── 420号方案增强4：基于未消费富字段的新冲突规则 ──

    # 6. 散户过热/减仓 + 结构上升（筹码主力视角：散户反向指标）
    chip_sd = dim_results.get('chip_fund', {})
    chip_retail = ''
    if isinstance(chip_sd, dict):
        chip_retail = str(((chip_sd.get('status_description', {}) or {}).get('retail_institution', ''))
                          or _extract_dim_judgment(dim_results, 'chip_fund').get('retail_institution', ''))
    if struct_dir == 1 and '散户' in chip_retail and '减' in chip_retail:
        conflicts.append({
            'dim1': '结构位置', 'dim2': '资金筹码',
            'description': '结构上升但散户资金在减——上涨动力存疑',
            'severity': 'medium',
        })

    # 7. 量价形态空头 + 信号确认（多形态共振：形态与信号背离）
    vp_sd = dim_results.get('volume_price', {})
    vp_pattern = ''
    if isinstance(vp_sd, dict):
        vp_pattern = str((vp_sd.get('status_description', {}) or {}).get('pattern', ''))
    if signal_dir == 1 and any(k in vp_pattern for k in ('空头', '下跌', 'breakdown', 'bear')):
        conflicts.append({
            'dim1': '量价健康', 'dim2': '信号确认',
            'description': f'量价形态{vp_pattern}但信号确认上涨——形态与信号背离',
            'severity': 'medium',
        })

    # 8. 波动率放大 + 结构下降（Barra风险：高波动下行加速）
    risk_sd = dim_results.get('risk', {})
    vol_level = ''
    if isinstance(risk_sd, dict):
        vol_level = str((risk_sd.get('status_description', {}) or {}).get('volatility_level', ''))
    if struct_dir == -1 and vol_level == 'high':
        conflicts.append({
            'dim1': '结构位置', 'dim2': '风险边界',
            'description': '趋势下行且波动率偏高——下跌可能加速',
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
    for dim in ['signal', 'structure', 'volume_price', 'chip_fund']:
        directions.append(_extract_dim_direction(dim_results, dim))

    pos_count = sum(1 for d in directions if d > 0)
    neg_count = sum(1 for d in directions if d < 0)

    risk_light = _extract_dim_light(dim_results, 'risk')
    _extract_dim_light(dim_results, 'emotion')

    # 高风险 → 风险警示/看空
    if risk_light == 'red':
        return 'risk_warning'

    # 有高严重度冲突 → 谨慎
    high_conflicts = [c for c in conflicts if c.get('severity') == 'high']
    if high_conflicts:
        return 'cautious'

    # 420号增强3：信号老化 → 强确认降级（对齐因子衰减概念）
    if _is_signal_decaying(dim_results) and consensus_rate >= 0.8 and pos_count >= 3:
        return 'light_confirm'

    # 420号增强2：盈亏比修正（对齐"回报风险比"概念）
    rr_value = _extract_dim_rr(dim_results)
    if rr_value is not None:
        if rr_value >= 2.0:
            # 高盈亏比 → 上修一档（仅当看多且非退出）
            if consensus_rate >= 0.7 and pos_count >= 2:
                return 'strong_confirm' if pos_count >= 3 else 'trend_confirm'
        elif rr_value < 1.0:
            # 低盈亏比 → 下修（抑制盲目确认）
            if consensus_rate >= 0.7 and pos_count >= 2:
                return 'light_confirm'
            elif consensus_rate >= 0.5 and pos_count >= 1:
                return 'neutral'

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
    dim_names = ['signal', 'structure', 'volume_price', 'chip_fund', 'emotion', 'risk', 'valuation']
    dim_cn = {'signal': '信号', 'structure': '结构', 'volume_price': '量价',
              'chip_fund': '资金', 'emotion': '情绪', 'risk': '风险', 'valuation': '估值'}
    parts = []
    for dim in dim_names:
        plain = _extract_dim_plain(dim_results, dim)
        if plain:
            parts.append(f'{dim_cn.get(dim, dim)}：{plain}')

    # 420号增强3：信号老化提示（对齐因子衰减概念）
    if _is_signal_decaying(dim_results):
        parts.append('信号：信号老化（进入末期/维护不佳），追涨需谨慎')

    dims_text = '；'.join(parts) if parts else '各维数据不足'

    # 420号增强5：关键量化锚点富化（盈亏比/支撑压力/情绪温度/生命周期天数）
    anchors = []
    rr = _extract_dim_rr(dim_results)
    if rr is not None:
        anchors.append(f'盈亏比{rr:.2f}')
    risk_sd = dim_results.get('risk', {})
    if isinstance(risk_sd, dict):
        risk_sd = risk_sd.get('status_description', {}) or {}
        sp = risk_sd.get('support_price')
        rp = risk_sd.get('resistance_price')
        if sp is not None and rp is not None:
            anchors.append(f'支撑{sp}/压力{rp}')
    emo_sd = dim_results.get('emotion', {})
    if isinstance(emo_sd, dict):
        temp = (emo_sd.get('status_description', {}) or {}).get('temperature', '')
        if temp:
            anchors.append(f'情绪温度{temp}')
    sig_sd = dim_results.get('signal', {})
    if isinstance(sig_sd, dict):
        ld = (sig_sd.get('status_description', {}) or {}).get('lifecycle_days')
        if ld is not None:
            anchors.append(f'信号{ld}天')
    if anchors:
        dims_text = f'{dims_text}｜关键位：{"，".join(anchors)}'

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

    def evaluate(self, dims: dict, tags: dict, signals: dict | None = None,
                 lifecycle: dict | None = None) -> dict:
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

        # 420号增强6：数据完整度提示（audit.confidence 均值 <0.7 时警示）
        dim_names7 = ['signal', 'structure', 'volume_price', 'chip_fund', 'emotion', 'risk', 'valuation']
        confidences = [_extract_dim_audit_confidence(dim_results, d) for d in dim_names7]
        data_confidence = sum(confidences) / len(confidences) if confidences else 0
        if 0 < data_confidence < 0.7:
            status_description['data_warning'] = f'数据完整度偏低（{data_confidence:.0%}），部分维度判断受限'

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
        dim_names = ['signal', 'structure', 'volume_price', 'chip_fund', 'emotion', 'risk', 'valuation']
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
