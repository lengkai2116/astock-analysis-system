"""321号 机会图谱跨维仲裁核心（机会状态机 + 显式仲裁优先级表）

背景：机会图谱 4 条平行维度链（潜力/时机/阶段/共识）各自独立产标签、并列展示，
缺跨维串联仲裁 → 矛盾输出（实证：否决+建仓 305 / 否决+看多类型 490 /
否决+看多共识 522 / 否决+仓位>0）。本模块作为**唯一结论收敛层**：
输入 4 链标签（+ 可选 门禁/L4 共识），输出单一 opportunity_state + state_evidence，
所有消费点（颜色/操作建议/verdict/仓位）从状态派生，消除并列矛盾。

仲裁优先级（321号 §3.2，从上到下逐级判定，命中即止）：
  P0 硬否决    right_side_confirm=否决 → avoid（覆盖一切）
  P1 硬风险    gate.hard_risks 含 event_negative（监管立案）→ avoid
  P2 深度高估  gate.valuation=deep → avoid
  P3 强看空    L4 direction=bearish 且 consensus_rate≥0.65 → avoid
  P4 未确认    right_side_confirm=未确认 → wait
  P5 可轻仓    right_side_confirm=基础确认 且 非强看空 → light
  P6 可入场    right_side_confirm=强确认 且 bullish≥0.55 → enter
  P7 默认      其余 → wait（保守）

gate/consensus 缺省时从 tags 内部推导（P4.5 预计算阶段无 diagnose 也可独立运行）。
"""
from __future__ import annotations

from typing import Any

# 状态枚举（321号 §3.1）
STATE_ENTER = 'enter'    # 可入场 🟦
STATE_LIGHT = 'light'    # 可轻仓 🟨
STATE_WAIT = 'wait'      # 等待 ⬜
STATE_AVOID = 'avoid'    # 回避 🟫

# 轻量投票口径（与 cross_validate.VOTE_MAP / _compute_snapshot_consensus_rate 一致）
_LIGHT_VOTES: dict[str, dict[str, int]] = {
    'main_force_phase': {
        'building': 1, 'lifting': 1, 'distributing': -1, 'washing': 0, 'unknown': 0,
    },
    'valuation_level': {'extreme_low': 1, 'low': 1, 'fair': 0, 'high': -1, 'extreme_high': -1},
    'trend_alignment': {'up_aligned': 1, 'down_aligned': -1, 'mixed': 0, 'no_trend': 0},
    'fund_flow': {'5d_inflow': 1, '5d_outflow': -1, 'mixed': 0, 'none': 0},
    'fina_health': {'pass': 1, 'suspicious': 0, 'fail': -1},
    'buy_sell_point': {
        'first_buy': 1, 'first_buy_p': 1, 'second_buy': 1, 'third_buy': 1,
        'third_buy_a': 1, 'third_buy_b': 1, 'first_sell': -1, 'first_sell_p': -1,
        'second_sell': -1, 'third_sell': -1, 'none': 0,
    },
    'ma_alignment': {'bullish': 1, 'bearish': -1, 'mixed': 0},
    'price_position': {'low_zone': 1, 'mid_zone': 0, 'high_zone': -1},
    'sector_heat': {'top_10': 1, 'top_20': 0.5, 'normal': 0, 'none': 0},
    'signal_strength': {},  # 数值：>=70 → +1, <=40 → -1（见 _light_vote）
}

# 正面催化剂（看多票）
_POS_EVENTS = {'earnings', 'lhb', 'concept', 'buyback', 'breakout', 'new_high', 'profit_growth'}
# 负面催化剂（看空票）
_NEG_EVENTS = {'pledge', 'float', 'reduce', 'fraud_sign', 'regulatory', 'lawsuit', 'decline'}

# P3 强看空阈值
_BEARISH_STRONG = 0.67   # 336号 C1：对齐知识库 ≥2/3（原 0.65，阈值迁移 yaml status_engine.yaml）
# P6 可入场看多阈值
_BULLISH_ENTER = 0.67    # 336号 C1：对齐知识库 ≥2/3（原 0.55）
# 335号 S2.3：深度高估（deep）不再硬否决——估值非绝对精准、可能突破，改强提示
_DEEP_HINT = '深度高估：价格高位风险，注意追涨（估值非绝对精准，存在突破可能）'


def _load_thresholds() -> None:
    """从 config/status_engine.yaml 加载共识阈值（336号 §7，版本化可回滚）"""
    global _BEARISH_STRONG, _BULLISH_ENTER
    try:
        from app.services.status_config import get_status_engine_config
        _cons = get_status_engine_config().get('consensus', {})
        _BEARISH_STRONG = float(_cons.get('bearish_strong', 0.67))
        _BULLISH_ENTER = float(_cons.get('enter_threshold', 0.67))
    except Exception:
        pass


def _light_vote(tag_name: str, value: Any) -> float:
    """单标签轻量投票（口径同 L4 VOTE_MAP，用于 P4.5 无 diagnose 时的方向推导）"""
    if value is None or value == '':
        return 0
    mapping = _LIGHT_VOTES.get(tag_name)
    if tag_name == 'signal_strength':
        try:
            v = float(value)
            return 1 if v >= 70.0 else (-1 if v <= 40.0 else 0)
        except (TypeError, ValueError):
            return 0
    if tag_name == 'catalyst_event':
        v = str(value).strip()
        if v in _POS_EVENTS:
            return 1
        if v in _NEG_EVENTS:
            return -1
        return 0
    if mapping is None:
        return 0
    return mapping.get(value, mapping.get(str(value), 0))


def _derive_consensus(tags: dict) -> dict:
    """无 diagnose 共识时，从 tags 轻量投票推导方向与共识率

    口径与 _compute_snapshot_consensus_rate 一致：共识率 = 优势方向票 / 方向票总数
    （中性票不稀释；全中性 → 0）。票数 <3 视为信号不足（direction=neutral）。
    """
    bullish = bearish = total = 0
    for tag_name in _LIGHT_VOTES:
        v = _light_vote(tag_name, tags.get(tag_name))
        total += 1
        if v > 0:
            bullish += 1
        elif v < 0:
            bearish += 1
    if total < 3:
        return {'direction': 'neutral', 'consensus_rate': 0.0}
    direction_active = bullish + bearish
    if direction_active == 0:
        return {'direction': 'neutral', 'consensus_rate': 0.0}
    if bullish > bearish:
        return {'direction': 'bullish', 'consensus_rate': round(bullish / direction_active, 3)}
    if bearish > bullish:
        return {'direction': 'bearish', 'consensus_rate': round(bearish / direction_active, 3)}
    return {'direction': 'neutral', 'consensus_rate': 0.0}


def _derive_gate(tags: dict) -> dict:
    """无 gate 传入时，从 tags 推导门禁关键项（与 cross_validate._evaluate_gate 同语义）

    仅推导本仲裁需要的判定项：
      - hard_risks：catalyst_event=regulatory → event_negative（监管立案）
      - valuation：valuation_level ∈ (high, extreme_high) 且 (PE分位>90 或 dev<-20) → deep
    """
    hard_risks: list[str] = []
    if str(tags.get('catalyst_event', '')).strip() == 'regulatory':
        hard_risks.append('event_negative')

    valuation = 'none'
    level = tags.get('valuation_level', '')
    if level in ('high', 'extreme_high'):
        try:
            pe_pct = float(tags.get('pe_percentile_5y') or 0)
        except (TypeError, ValueError):
            pe_pct = 0.0
        try:
            dev = float(tags.get('valuation_deviation') or 0)
        except (TypeError, ValueError):
            dev = 0.0
        if pe_pct > 90 or dev < -20:
            valuation = 'deep'

    return {'valuation': valuation, 'hard_risks': hard_risks, 'soft_risks': []}


def _append(evidence: list[str], text: str, check: bool = True) -> None:
    """收集仲裁依据（非重复追加）"""
    if check and text not in evidence:
        evidence.append(text)


def arbitrate(tags: dict, gate: dict = None, consensus: dict = None,
              dim_results: dict = None) -> dict:
    """跨维仲裁（321号 §3.2 优先级表）

    Args:
        tags: 4 链标签（right_side_confirm/main_force_phase/signal_strength 等）
        gate: 门禁评估结果（cross_validate._evaluate_gate 输出；None 则从 tags 推导）
        consensus: L4 共识（{'direction','consensus_rate'}；None 则从 tags 轻量推导）
        dim_results: 365号批次C — 维度引擎输出（可选），提供时用于增强仲裁依据

    Returns:
        {'opportunity_state': 'enter'|'light'|'wait'|'avoid',
         'state_evidence': [仲裁依据列表],
         'conflict_evidence': [矛盾维度列表]}   # 330号改进4：暴露冲突
    """
    if gate is None:
        gate = _derive_gate(tags)
    if consensus is None:
        consensus = _derive_consensus(tags)
    _load_thresholds()

    evidence: list[str] = []
    rsc = str(tags.get('right_side_confirm', '') or '')
    direction = consensus.get('direction', 'neutral')
    rate = float(consensus.get('consensus_rate') or 0)

    # ── 330号改进4：冲突维度暴露 ──
    # 检测标签间矛盾（如 缠论趋势向下 vs 多周期趋势向上 / 高位获利盘 vs 可入场 /
    # 结构高风险 vs 强确认），供前端风险边界展示——原 arbiter 硬合成掩盖冲突。
    conflict_evidence: list[str] = []
    _state_label = str(tags.get('state_label', '') or '')
    _trend_al = str(tags.get('trend_alignment', '') or '')
    _price_pos = str(tags.get('price_position', '') or '')
    _risk = str(tags.get('risk_level', '') or '')
    _mfp = str(tags.get('main_force_phase', '') or '')
    _profit = tags.get('profit_ratio')
    try:
        _profit_f = float(_profit) if _profit not in (None, '') else None
    except (TypeError, ValueError):
        _profit_f = None
    # 缠论方向 vs 多周期趋势 矛盾
    if ('下降' in _state_label and _trend_al == 'up_aligned'):
        conflict_evidence.append('缠论趋势下降 vs 多周期趋势向上（方向分歧）')
    if ('上升' in _state_label and _trend_al == 'down_aligned'):
        conflict_evidence.append('缠论趋势上升 vs 多周期趋势向下（方向分歧）')
    # 高位获利盘 + 出货 → 风险提示
    if _profit_f is not None and _profit_f >= 0.8 and '高位' in _price_pos:
        conflict_evidence.append(f'获利盘 {_profit_f:.0%} 高位（追涨风险大）')
    if _mfp == 'distributing' and rsc in ('强确认', '基础确认'):
        conflict_evidence.append('主力出货阶段 vs 右侧确认看多（资金分歧）')
    # 结构高风险 + 可入场类
    if _risk == 'HIGH' and rsc in ('强确认', '基础确认'):
        conflict_evidence.append('结构风险 HIGH vs 右侧确认（风险收益不匹配）')
    # 336号 §4.2 扩展（缺失证据类）：高位无主力在场 / 深度高估+强确认
    if _profit_f is not None and _profit_f >= 0.8 and str(tags.get('main_force_presence', '')) == 'none':
        conflict_evidence.append(f'获利盘 {_profit_f:.0%} 高位且无主力在场证据（接续乏力风险）')
    if gate.get('valuation') == 'deep' and rsc in ('强确认', '基础确认'):
        conflict_evidence.append('深度高估 + 右侧确认（价格高位风险，注意追涨）')

    # ── P0 硬否决：右侧否决（缠论卖点/量价背离/预跌形态） → avoid ──
    if rsc == '否决':
        _append(evidence, '右侧否决：出现卖出/背离/预跌信号')
        return {'opportunity_state': STATE_AVOID, 'state_evidence': evidence,
                'conflict_evidence': conflict_evidence}

    # ── P1 硬风险：监管立案等不可逆负面事件 → avoid ──
    if 'event_negative' in gate.get('hard_risks', []):
        _append(evidence, '负面事件：监管立案风险')
        return {'opportunity_state': STATE_AVOID, 'state_evidence': evidence,
                'conflict_evidence': conflict_evidence}

    # ── 335号 S2.3：deep 强提示（非否决）——正常走 P3-P7 时机判定 ──
    # 估值非绝对精准、部分股票存在较大价格突破可能性（用户决策 08-15），
    # 深度高估从"一票否决"改为"高风险机会强提示 + 仓位压缩"。
    if gate.get('valuation') == 'deep':
        _append(evidence, _DEEP_HINT)

    # ── P3 强看空：L4 bearish 共识≥65% → avoid ──
    if direction == 'bearish' and rate >= _BEARISH_STRONG:
        _append(evidence, f'L4 强看空共识 {rate:.0%}')
        return {'opportunity_state': STATE_AVOID, 'state_evidence': evidence,
                'conflict_evidence': conflict_evidence}

    # ── P4 未确认 → wait ──
    if rsc == '未确认':
        _append(evidence, '右侧未确认：等待突破信号')
        return {'opportunity_state': STATE_WAIT, 'state_evidence': evidence,
                'conflict_evidence': conflict_evidence}

    # ── P5 可轻仓：基础确认 + 非强看空 → light ──
    if rsc == '基础确认':
        _append(evidence, '右侧基础确认，可轻仓')
        return {'opportunity_state': STATE_LIGHT, 'state_evidence': evidence,
                'conflict_evidence': conflict_evidence}

    # ── P6 可入场：强确认 + bullish 共识≥55% → enter ──
    if rsc == '强确认':
        if direction == 'bullish' and rate >= _BULLISH_ENTER:
            _append(evidence, f'右侧强确认 + L4 看多共识 {rate:.0%}')
            return {'opportunity_state': STATE_ENTER, 'state_evidence': evidence,
                    'conflict_evidence': conflict_evidence}
        _append(evidence, '右侧强确认但 L4 共识不足，等待确认')
        return {'opportunity_state': STATE_WAIT, 'state_evidence': evidence,
                'conflict_evidence': conflict_evidence}

    # ── P7 默认：无明确时机信号 → wait（保守） ──
    _append(evidence, '无明确时机信号，默认等待')
    return {'opportunity_state': STATE_WAIT, 'state_evidence': evidence,
            'conflict_evidence': conflict_evidence}
