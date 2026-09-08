"""L5 多因子仲裁器（390号方案 §7.3）

390号方案新增 L5 层：在现有 L4 共识 + conflict_detector 基础上，
引入多因子评分（semantic_adjustment + right_side_confirm gate + emotion extreme correction），
将仲裁从纯规则优先级表升级为 **评分 + 规则混合** 模型。

流水线（390 §7.3）：
  Step 1: 硬否决检查（right_side_confirm=否决 / catalyst=regulatory / fatal_to_veto）
  Step 2: 基础分 = consensus_rate × 100
  Step 3: 语义调整 = base × conflict.semantic_adjustment
  Step 4: right_side_confirm 门控（强确认1.0 / 基础确认0.8 / 未确认0.5）
  Step 5: 情绪极端修正（冰点+看多 或 正向+看空 → ×0.85 警示）
  Step 6: 映射 → opportunity_state（≥70 enter / 55-69 light / 30-54 wait / <30 avoid）

与 arbiter.py 的区别：
  - arbiter.py（321号）：纯规则优先级表（P0-P7），无评分
  - factor_arbiter.py（390号）：评分 + 规则混合，输出 final_score 供前端展示

消费场景：status_engine 调用本模块替代或补充 arbiter.arbitrate()，
最终状态写入 opportunity_state，分数写入 opportunity_score。
"""
from __future__ import annotations

# ── 常量 ──
STATE_ENTER = 'enter'    # 可入场 🟦
STATE_LIGHT = 'light'    # 可轻仓 🟨
STATE_WAIT = 'wait'      # 等待 ⬜
STATE_AVOID = 'avoid'    # 回避 🟫

# right_side_confirm 乘数映射（390 §7.3 Step 4）
_RSC_MULTIPLIER: dict[str, float] = {
    '强确认': 1.0,
    '基础确认': 0.8,
    '未确认': 0.5,
}
_RSC_DEFAULT = 0.5  # 未知或缺失时的保守默认值

# 情绪极端阈值（390 §7.3 Step 5）
_EMOTION_EXTREME_THRESHOLD = 0.6
_EMOTION_PENALTY = 0.85  # 极端情绪 × 冷静折扣

# 评分 → 状态映射阈值（390 §7.3 Step 6）
_THRESHOLDS = [
    (70, STATE_ENTER),
    (55, STATE_LIGHT),
    (30, STATE_WAIT),
]


def _map_score_to_state(final_score: float) -> str:
    """Step 6: 将最终评分映射为 opportunity_state"""
    for threshold, state in _THRESHOLDS:
        if final_score >= threshold:
            return state
    return STATE_AVOID


def _append_evidence(evidence: list[str], text: str) -> None:
    """非重复追加仲裁依据"""
    if text not in evidence:
        evidence.append(text)


def arbitrate(
    consensus: dict,
    conflict: dict,
    tags: dict,
    dims_factor: dict,
    reliability: dict,
) -> dict:
    """L5 多因子仲裁（390号方案 §7.3）

    Args:
        consensus: L4 共识输出，需含 consensus_rate (0-1 float)
        conflict: 冲突检测输出，需含：
            - semantic_adjustment (float, 通常 0.8-1.2)
            - fatal_to_veto (list[str], 致命冲突列表)
        tags: 标签字典，需含 right_side_confirm, catalyst_event 等
        dims_factor: 维度因子引擎输出，结构：
            {
              'emotion': {'direction': 1/-1/0, 'strength': 0.0-1.0, ...},
              ... 其他维度
            }
        reliability: 可靠性指标（预留，当前未使用）

    Returns:
        {
            'opportunity_state': 'enter'|'light'|'wait'|'avoid',
            'final_score': float,          # 0-100 评分
            'state_evidence': list[str],   # 状态判定依据
            'conflict_evidence': list[str], # 冲突暴露
        }
    """
    state_evidence: list[str] = []
    conflict_evidence: list[str] = []

    # ════════════════════════════════════════════════════════════════
    # Step 1: 硬否决检查（390 §7.3）
    # ════════════════════════════════════════════════════════════════

    # 1a: right_side_confirm = 否决 → 立即回避
    # 404号DATA-03: pre_feat_cache管道只产出strong_confirm/unconfirmed，'否决'仅由treemap管道产出，此分支为死代码（已知限制）
    rsc_raw = str(tags.get('right_side_confirm', '') or '')
    if rsc_raw == '否决':
        _append_evidence(state_evidence, '硬否决：right_side_confirm=否决（出现卖出/背离/预跌信号）')
        return {
            'opportunity_state': STATE_AVOID,
            'final_score': 0.0,
            'state_evidence': state_evidence,
            'conflict_evidence': conflict_evidence,
        }

    # 1b: catalyst_event = regulatory → 立即回避
    catalyst = str(tags.get('catalyst_event', '') or '').strip()
    if catalyst == 'regulatory':
        _append_evidence(state_evidence, '硬否决：catalyst_event=regulatory（监管事件风险）')
        return {
            'opportunity_state': STATE_AVOID,
            'final_score': 0.0,
            'state_evidence': state_evidence,
            'conflict_evidence': conflict_evidence,
        }

    # 1c: fatal_to_veto 非空 → 强制降级为 wait
    fatal_list = conflict.get('fatal_to_veto', [])
    if fatal_list and len(fatal_list) > 0:
        _append_evidence(state_evidence,
                         f'强制降级（wait）：致命冲突 [{", ".join(str(f) for f in fatal_list)}]')
        for fatal_item in fatal_list:
            _append_evidence(conflict_evidence, f'致命冲突: {fatal_item}')
        return {
            'opportunity_state': STATE_WAIT,
            'final_score': 0.0,
            'state_evidence': state_evidence,
            'conflict_evidence': conflict_evidence,
        }

    # ════════════════════════════════════════════════════════════════
    # Step 2: 基础分 = consensus_rate × 100
    # ════════════════════════════════════════════════════════════════
    consensus_rate = float(consensus.get('consensus_rate', 0) or 0)
    # clamp to [0, 1] 安全范围
    consensus_rate = max(0.0, min(1.0, consensus_rate))
    base_score = consensus_rate * 100.0

    _append_evidence(state_evidence,
                     f'基础分: consensus_rate={consensus_rate:.3f} → {base_score:.1f}')

    # ════════════════════════════════════════════════════════════════
    # Step 3: 语义调整 = base × conflict.semantic_adjustment
    # ════════════════════════════════════════════════════════════════
    semantic_adj = float(conflict.get('semantic_adjustment', 1.0) or 1.0)
    # 防御性 clamp：语义调整因子通常在 [0.5, 1.5] 范围
    semantic_adj = max(0.1, min(3.0, semantic_adj))
    adjusted_score = base_score * semantic_adj

    _append_evidence(state_evidence,
                     f'语义调整: ×{semantic_adj:.3f} → {adjusted_score:.1f}')

    # ════════════════════════════════════════════════════════════════
    # Step 4: right_side_confirm 门控
    # ════════════════════════════════════════════════════════════════
    rsc = str(tags.get('right_side_confirm', '未确认') or '未确认')
    rsc_multiplier = _RSC_MULTIPLIER.get(rsc, _RSC_DEFAULT)
    final_score = adjusted_score * rsc_multiplier

    _append_evidence(state_evidence,
                     f'右侧确认门控: right_side_confirm={rsc} → ×{rsc_multiplier} → {final_score:.1f}')

    # ════════════════════════════════════════════════════════════════
    # Step 5: 情绪极端修正（390 §7.3）
    # ════════════════════════════════════════════════════════════════
    emotion_data = dims_factor.get('emotion', {})
    emotion_direction = int(emotion_data.get('direction', 0) or 0)
    emotion_strength = float(emotion_data.get('strength', 0.5) or 0.5)

    if emotion_strength > _EMOTION_EXTREME_THRESHOLD:
        if emotion_direction == 1:
            # direction=1 代表 ice（冰点），冰点+看多 = 反转看多但极端冷 → 谨慎
            final_score *= _EMOTION_PENALTY
            _append_evidence(state_evidence,
                             f'情绪极端修正: 冰点(方向=+1) 看多但极端冷(strength={emotion_strength:.3f})'
                             f' → ×{_EMOTION_PENALTY} → {final_score:.1f}')
        elif emotion_direction == -1:
            # direction=-1 代表 positive（正向），正向+看空 = 反转看空但极端热 → 谨慎
            final_score *= _EMOTION_PENALTY
            _append_evidence(state_evidence,
                             f'情绪极端修正: 正向(方向=-1) 看空但极端热(strength={emotion_strength:.3f})'
                             f' → ×{_EMOTION_PENALTY} → {final_score:.1f}')

    # 确保分数在 [0, 100] 范围
    final_score = max(0.0, min(100.0, final_score))

    # ════════════════════════════════════════════════════════════════
    # Step 6: 映射 → opportunity_state
    # ════════════════════════════════════════════════════════════════
    opportunity_state = _map_score_to_state(final_score)

    _append_evidence(state_evidence,
                     f'状态映射: final_score={final_score:.1f} → {opportunity_state}')

    # 收集非致命冲突描述（冲突暴露，供前端展示）
    warn_list = conflict.get('warn_for_semantic', []) or conflict.get('warn', [])
    if warn_list and isinstance(warn_list, list):
        for warn_item in warn_list:
            _append_evidence(conflict_evidence, f'警告冲突: {warn_item}')

    # 可靠性指标（预留：future 可用于置信区间展示）
    if reliability:
        _append_evidence(state_evidence,
                         f'可靠性指标: {reliability}')

    return {
        'opportunity_state': opportunity_state,
        'final_score': round(final_score, 2),
        'state_evidence': state_evidence,
        'conflict_evidence': conflict_evidence,
    }
