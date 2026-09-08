"""可靠性评估层 — 390号方案v3.0 §4.2 L2 可靠性判定

将L1维度判定输出（dims_factor）与原始引擎数据（dim_results）融合，
为每个维度计算一个 0-1 的可靠性分数，用于L3仲裁层的加权聚合。

维度可靠性规则摘要（§4.2）：
  dim1  signal      → 信号衰减状态
  dim2  structure   → 三源融合 + 多算法一致性加成
  dim3  volume_price→ 多周期一致性 + 周线方向修正 + 量价三律修正
  dim4  chip_fund   → PDE冲突判定 + 票差修正
  dim5  emotion     → bociasi置信度 + 板块热度修正
  dim6  risk        → ATR占比分档 + 波动分位修正
  dim7  valuation   → PE分位存在性 + PB/PS极端估值加成
  其余维度           → 默认0.5（数据不足时的保守估计）

调用方式：
    from app.opportunity_atlas.reliability_assessor import assess
    reliability = assess(dims_factor, dim_results)
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── 常量 ──
_DEFAULT_RELIABILITY = 0.5

# 所有已知维度 → 若未命中任何专属规则则归入默认
_KNOWN_DIMS = {
    'signal', 'structure', 'volume_price', 'chip_fund',
    'emotion', 'risk', 'valuation',
}

# 默认0.5的维度（数据不足，保守估计）
_DEFAULT_DIMS = {
    'finance', 'event', 'time', 'factor', 'signal_confirm', 'position',
}


def _safe_float(val: Any, default: float = 0.0) -> float:
    """安全浮点转换，None / 非数值均返回 default。"""
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_get(dim_results: dict, dim_key: str) -> dict:
    """安全取 dim_results[dim_key]，缺省返回空 dict。"""
    return (dim_results.get(dim_key) or {})


def _assess_signal(dim_results: dict) -> float:
    """dim1 信号可靠性 — 基于 maintenance.decay_status。"""
    signal = _safe_get(dim_results, 'signal')
    maintenance = (signal.get('judgment') or {}).get('maintenance') or {}
    status = str(maintenance.get('status', '')).lower()

    mapping = {
        'healthy': 0.8,
        'fading': 0.5,
        'decayed': 0.2,
    }
    return mapping.get(status, _DEFAULT_RELIABILITY)


def _assess_structure(dim_results: dict) -> float:
    """dim2 结构可靠性 — 三源融合 + 多算法一致性加成。

    三源融合公式：0.5*level_cross_score + 0.3*consistency_component + 0.2*chanlun_component
    加成：divergence_multi_algo 三算法全同意 +0.1，≤1同意 -0.1。
    """
    structure = _safe_get(dim_results, 'structure')
    sd = structure.get('status_description') or {}

    # 三源分量（归一化到 0-1）
    level_cross = _safe_float(sd.get('level_cross_score'), 0.5)
    consistency = _safe_float(sd.get('consistency_component'), 0.5)
    # chanlun_strength_components 可能是 dict（含 strength）或直接数值
    chanlun_raw = sd.get('chanlun_strength_components') or sd.get('chanlun_component')
    if isinstance(chanlun_raw, dict):
        chanlun = _safe_float(chanlun_raw.get('strength'), 0.5)
    else:
        chanlun = _safe_float(chanlun_raw, 0.5)

    base = 0.5 * level_cross + 0.3 * consistency + 0.2 * chanlun
    base = max(0.0, min(1.0, base))

    # 多算法一致性加成
    div = sd.get('divergence_multi_algo') or {}
    agree_count = 0
    if isinstance(div, dict):
        for _algo, info in div.items():
            if isinstance(info, dict) and info.get('agree'):
                agree_count += 1
    elif isinstance(div, list):
        agree_count = sum(
            1 for item in div
            if isinstance(item, dict) and item.get('agree')
        )

    if agree_count >= 3:
        base += 0.1
    elif agree_count <= 1:
        base -= 0.1

    return max(0.0, min(1.0, base))


def _assess_volume_price(dim_results: dict) -> float:
    """dim3 量价可靠性 — 多周期一致性 + 周线方向修正 + 量价三律修正。

    基础：multi_timeframe_consistency '一致'→0.9, '冲突'→0.3, else 0.5
    修正：weekly_direction=='SELL' → ×0.5
    修正：three_laws.effort_result 含 '异常' → ×0.8
    回退：consistency 缺失时使用 stage_confidence
    """
    vp = _safe_get(dim_results, 'volume_price')
    sd = vp.get('status_description') or {}

    # 基础分
    consistency = str(sd.get('multi_timeframe_consistency', ''))
    if '一致' in consistency:
        base = 0.9
    elif '冲突' in consistency:
        base = 0.3
    else:
        base = _DEFAULT_RELIABILITY

    # 回退：consistency 缺失时使用 stage_confidence
    if not consistency:
        stage_conf = sd.get('stage_confidence')
        if stage_conf is not None:
            base = _safe_float(stage_conf, _DEFAULT_RELIABILITY)

    # 周线方向修正
    weekly_dir = str(sd.get('weekly_direction', '')).upper()
    if weekly_dir == 'SELL':
        base *= 0.5

    # 量价三律修正
    three_laws = sd.get('three_laws') or {}
    effort_result = str(three_laws.get('effort_result', ''))
    if '异常' in effort_result:
        base *= 0.8

    return max(0.0, min(1.0, base))


def _assess_chip_fund(dim_results: dict) -> float:
    """dim4 筹码可靠 — PDE冲突判定 + 票差修正。

    如果 pde_conflict=False AND phase_confidence>0.6 → 0.8
    如果 pde_conflict=True → 0.4
    else → 0.5
    修正：pde_vote_ratio 最大票/total<0.6 → ×0.7
    """
    cf = _safe_get(dim_results, 'chip_fund')
    sd = cf.get('status_description') or {}

    pde_conflict = sd.get('pde_conflict')
    phase_conf = _safe_float(sd.get('phase_confidence'), 0.0)

    if pde_conflict is False and phase_conf > 0.6:
        base = 0.8
    elif pde_conflict is True:
        base = 0.4
    else:
        base = _DEFAULT_RELIABILITY

    # 票差修正：解析 pde_vote_ratio，若 max票/total < 0.6 则打折
    vote_ratio = sd.get('pde_vote_ratio')
    if vote_ratio is not None:
        try:
            if isinstance(vote_ratio, dict):
                vals = list(vote_ratio.values())
                nums = [float(v) for v in vals if v is not None]
                if nums:
                    ratio = max(nums) / max(sum(nums), 1)
                    if ratio < 0.6:
                        base *= 0.7
            elif isinstance(vote_ratio, (list, tuple)) and len(vote_ratio) > 0:
                nums = [float(v) for v in vote_ratio if v is not None]
                if nums:
                    ratio = max(nums) / max(sum(nums), 1)
                    if ratio < 0.6:
                        base *= 0.7
            elif isinstance(vote_ratio, str):
                # 尝试解析 "3:1" 或类似格式
                parts = [
                    float(p.strip())
                    for p in vote_ratio.replace('/', ':').split(':')
                    if p.strip().replace('.', '', 1).replace('-', '').isdigit()
                ]
                if parts:
                    ratio = max(parts) / max(sum(parts), 1)
                    if ratio < 0.6:
                        base *= 0.7
        except (TypeError, ValueError, ZeroDivisionError):
            pass  # 解析失败不修正

    return max(0.0, min(1.0, base))


def _assess_emotion(dim_results: dict) -> float:
    """dim5 情绪可靠 — bociasi_slow_confidence 基础 + 板块热度修正。

    base = bociasi_slow_confidence（0-1 直接使用）
    修正：sector_heat=='none' → ×0.8
    """
    emo = _safe_get(dim_results, 'emotion')
    sd = emo.get('status_description') or {}

    base = _safe_float(
        sd.get('bociasi_slow_confidence'), _DEFAULT_RELIABILITY
    )

    sector_heat = str(sd.get('sector_heat', '')).lower()
    if sector_heat == 'none':
        base *= 0.8

    return max(0.0, min(1.0, base))


def _assess_risk(dim_results: dict) -> float:
    """dim6 风险可靠 — ATR占比分档 + 波动分位修正。

    ATR：<0.3→0.9, >0.7→0.4, else 0.6
    修正：volatility_percentile>0.85 → ×0.7
    """
    risk = _safe_get(dim_results, 'risk')
    sd = risk.get('status_description') or {}

    atr_raw = sd.get('atr_pct')
    atr = _safe_float(atr_raw, None)  # sentinel: None means missing
    if atr_raw is None:
        base = _DEFAULT_RELIABILITY
    elif atr < 0.3:
        base = 0.9
    elif atr > 0.7:
        base = 0.4
    else:
        base = 0.6

    vol_raw = sd.get('volatility_percentile')
    vol_pct = _safe_float(vol_raw, 0.0)
    if vol_raw is not None and vol_pct > 0.85:
        base *= 0.7

    return max(0.0, min(1.0, base))


def _assess_valuation(dim_results: dict) -> float:
    """dim7 估值可靠 — PE分位存在性 + PB/PS极端估值加成。

    pe_percentile_5y is not None → 0.8, else → 0.3
    修正：pb_percentile_5y>90 AND ps_percentile_5y>90 → 0.95
    """
    val = _safe_get(dim_results, 'valuation')
    sd = val.get('status_description') or {}

    pe_pct = sd.get('pe_percentile_5y')
    if pe_pct is not None:
        base = 0.8
    else:
        base = 0.3

    pb_raw = sd.get('pb_percentile_5y')
    ps_raw = sd.get('ps_percentile_5y')
    pb_pct = _safe_float(pb_raw, 0.0)
    ps_pct = _safe_float(ps_raw, 0.0)
    if pb_raw is not None and ps_raw is not None:
        if pb_pct > 90 and ps_pct > 90:
            base = 0.95

    return max(0.0, min(1.0, base))


# ── 维度评估分派表 ──
_DIM_ASSESSORS = {
    'signal': _assess_signal,
    'structure': _assess_structure,
    'volume_price': _assess_volume_price,
    'chip_fund': _assess_chip_fund,
    'emotion': _assess_emotion,
    'risk': _assess_risk,
    'valuation': _assess_valuation,
}


def assess(dims_factor: dict, dim_results: dict) -> dict:
    """L2 可靠性评估（390号方案v3.0 §4.2）。

    对每个维度，根据 dim_results 引擎原始输出计算 0-1 可靠性分数。
    每个维度独立 try/except，单维失败不影响其他维度。

    Parameters
    ----------
    dims_factor : dict
        L1 输出，形如 ``{dim_name: {'direction': ..., 'strength': ..., 'evidence': ...}}``。
        此函数主要用它来确定需要评估哪些维度。
    dim_results : dict
        原始引擎输出，形如 ``{dim_name: {'judgment': ..., 'status_description': ...}}``。

    Returns
    -------
    dict
        ``{dim_name: float}`` — 每个维度的可靠性分数（0-1）。
    """
    reliability: dict[str, float] = {}

    # 从 dims_factor 提取所有出现过的维度名
    all_dims = set(dims_factor.keys()) if dims_factor else set()

    for dim_name in sorted(all_dims):
        if dim_name in _DEFAULT_DIMS:
            # 默认维度：数据不足，保守 0.5
            reliability[dim_name] = _DEFAULT_RELIABILITY
            continue

        assessor = _DIM_ASSESSORS.get(dim_name)
        if assessor is None:
            # 未知维度 → 默认
            reliability[dim_name] = _DEFAULT_RELIABILITY
            continue

        try:
            reliability[dim_name] = assessor(dim_results)
        except Exception as exc:
            logger.warning(
                "reliability_assessor: 维度 '%s' 评估失败，回退默认 %.1f: %s",
                dim_name, _DEFAULT_RELIABILITY, exc,
            )
            reliability[dim_name] = _DEFAULT_RELIABILITY

    # 补充 dim_results 中存在但 dims_factor 中缺失的维度
    for dim_name in sorted(_KNOWN_DIMS | _DEFAULT_DIMS):
        if dim_name not in reliability:
            reliability[dim_name] = _DEFAULT_RELIABILITY

    return reliability
