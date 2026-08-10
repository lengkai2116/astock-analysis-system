"""322号 操作建议生成器（现状描述化：七维红绿灯 + 几何指标 + 情景概率 + executable）

结论层复用 321 号 arbitrate 状态机（与机会图谱同源）；五维信号 + K线 → 状态刻画。
仅按需生成（analyze 响应时），不落库不入快照。
"""
from __future__ import annotations

from app.opportunity_atlas.arbiter import arbitrate

_STATE_CN = {'enter': '可入场', 'light': '可轻仓', 'wait': '等待', 'avoid': '回避'}

# 看多/看空方向值域归一化（真实五维 direction 值域不统一：
# chanlun='上升'/'下降'、volume_price='up'/'down'、chip/emotion='bullish'/'bearish'、
# factor.trend='bullish'/'bearish'/'neutral'）
_BULLISH_VALUES = {'up', 'bullish', '上升', '看多'}
_BEARISH_VALUES = {'down', 'bearish', '下降', '看空'}


def _dir_is_bullish(v) -> bool:
    return str(v or '') in _BULLISH_VALUES


def _dir_is_bearish(v) -> bool:
    return str(v or '') in _BEARISH_VALUES


def _dim_directions(dimensions: dict) -> list[int]:
    """五维方向统计（+1 看多 / -1 看空 / 0 中性），供共识与情景概率复用"""
    dirs = []
    for k in ('chanlun', 'volume_price', 'chip', 'emotion', 'factor'):
        d = (dimensions.get(k) or {}).get('direction')
        # factor 无 direction 字段，用 trend 兜底
        if d is None and k == 'factor':
            d = (dimensions.get(k) or {}).get('trend')
        if _dir_is_bullish(d):
            dirs.append(1)
        elif _dir_is_bearish(d):
            dirs.append(-1)
        else:
            dirs.append(0)
    return dirs


def _consensus_from_dirs(dirs: list[int]) -> dict:
    """五维方向 → L4 共识近似（direction + consensus_rate，供 arbitrate P3/P6）"""
    n_bull = sum(1 for x in dirs if x > 0)
    n_bear = sum(1 for x in dirs if x < 0)
    if n_bull + n_bear > 0:
        direction = 'bullish' if n_bull >= n_bear else 'bearish'
        consensus_rate = max(n_bull, n_bear) / (n_bull + n_bear)
    else:
        direction = 'neutral'
        consensus_rate = 0.0
    return {'direction': direction, 'consensus_rate': consensus_rate}


def _scenario_base(dimensions: dict) -> dict:
    """情景概率规则基线：五维方向一致度 → 趋势延续/冲高回落/破位下行"""
    dirs = _dim_directions(dimensions)
    up = sum(1 for x in dirs if x > 0)
    down = sum(1 for x in dirs if x < 0)
    n = max(len(dirs), 1)
    prob_a = 0.4 + 0.5 * (up / n)          # 趋势延续
    prob_c = 0.1 + 0.5 * (down / n)        # 破位下行
    prob_b = max(0.05, 1.0 - prob_a - prob_c)  # 冲高回落
    return {'a': prob_a, 'b': prob_b, 'c': prob_c}


def _normalize_scenarios(raw: list[dict]) -> list[dict]:
    """概率归一化（非负、和为1）"""
    total = sum(max(0.0, s.get('prob', 0)) for s in raw)
    if total <= 0:
        total = 1.0
    return [{**s, 'prob': round(max(0.0, s.get('prob', 0)) / total, 3)} for s in raw]


def _geometric(df) -> dict:
    """几何化指标：距支撑/压力%、盈亏比、信号天数、防守位（K线不足返回空）

    - support_price：真实防守位 = 60日低点（lo60，现价下方空间）；缠论中枢下沿
      是上方阻力区，不当止损（600519 实证：中枢下沿 1367 而现价 1309）。
    - signal_days：突破信号后已持续交易日数（收盘价站上前60日高点后至今）
    """
    if df is None or df.empty or 'close' not in df.columns or len(df) < 20:
        return {'dist_to_support_pct': None, 'dist_to_resistance_pct': None,
                'risk_reward': None, 'signal_days': None, 'support_price': None,
                'resistance_price': None}
    closes = df['close'].values
    price = float(closes[-1])
    hi60 = float(df['high'].tail(60).max()) if len(df) >= 60 and 'high' in df.columns else None
    lo60 = float(df['low'].tail(60).min()) if len(df) >= 60 and 'low' in df.columns else None
    # 压力位：60日高点与 MA60 取较低者（更贴近的阻力）；支撑位：60日低点
    ma60 = float(df['close'].tail(60).mean()) if len(df) >= 60 else None
    resistance = hi60
    if hi60 is not None and ma60 is not None:
        resistance = min(hi60, ma60)   # 更贴近的压力参考
    support = lo60
    dist_sup = (support / price - 1) * 100 if support else None
    dist_res = (resistance / price - 1) * 100 if resistance else None
    rr = abs(dist_res / dist_sup) if dist_sup and dist_res else None
    # 信号天数：突破前60日高点后持续天数（收盘 > 前60日高点 = 突破成立日）
    signal_days = None
    if len(closes) >= 62:
        prior_hi = float(df['high'].iloc[-61:-1].max())
        if prior_hi > 0 and closes[-1] > prior_hi:
            days = 0
            for i in range(len(closes) - 1, -1, -1):
                if closes[i] > prior_hi:
                    days += 1
                else:
                    break
            signal_days = days if days > 0 else None
    return {'dist_to_support_pct': round(dist_sup, 2) if dist_sup is not None else None,
            'dist_to_resistance_pct': round(dist_res, 2) if dist_res is not None else None,
            'risk_reward': round(rr, 2) if rr is not None else None,
            'signal_days': signal_days,
            'support_price': round(support, 2) if support is not None else None,
            'resistance_price': round(resistance, 2) if resistance is not None else None}


def build_operation_advice(ts_code: str, dimensions: dict, signals: list, df,
                           kronos: dict = None, tags: dict = None) -> dict:
    """构建 operation_advice（analyze 响应时调用，毫秒级）

    Args:
        ts_code: 股票代码
        dimensions: 五维分析（chanlun/volume_price/chip/emotion/factor）
        signals: 策略信号列表（未直接使用，保留接口兼容）
        df: 日线 DataFrame（几何指标计算；None/不足时返回空几何）
        kronos: （S4 扩展）Kronos 推理结果 dict 或 None（{'direction', 'confidence'}）
        tags: （2026-08-09 统一两路径）机会图谱真实标签字典（opportunity_tags_cache），
              含 right_side_confirm/opportunity_state 等；优先采信真实标签，
              缺失时才用五维近似——保证个股页与机会图谱弹窗结论同源。
    """
    # 结论层：优先真实标签（与机会图谱 321 仲裁同源），缺失才用五维近似
    real_state = (tags or {}).get('opportunity_state')
    real_rsc = (tags or {}).get('right_side_confirm')
    trend = (dimensions.get('factor') or {}).get('trend', '')
    mfp = (dimensions.get('chip') or {}).get('main_force_direction', '')
    inflow = '流入' in str(mfp)
    outflow = '流出' in str(mfp)
    # right_side_confirm：真实标签优先；缺失时 factor.trend 近似
    rsc = real_rsc or ('强确认' if _dir_is_bullish(trend) else '未确认')
    arb_tags = {
        'right_side_confirm': rsc,
        'main_force_phase': 'lifting' if inflow else ('distributing' if outflow else 'unknown'),
    }
    # L4 共识近似：五维方向一致度（复用 _dim_directions，与 _scenario_base 同源）
    dirs = _dim_directions(dimensions)
    consensus = _consensus_from_dirs(dirs)
    arb = arbitrate(arb_tags, consensus=consensus)
    state = real_state or arb['opportunity_state']
    state_reason = arb['state_evidence'][0] if arb['state_evidence'] else ''

    # ── 323号 S8：映射与降级机制（建议卡 §三）──
    # 方向冲突降级 + 市场过滤 + 硬约束——实时风控，作用于最终 state
    # （含真实标签场景：实时五维与 P4 预计算冲突时保守降级）；
    # diagnose 侧会将顶层 opportunity_state 同步为降级后值（见 cross_validate）
    _pre_state = state
    state = _apply_degradation(
        state, dirs,
        sentiment_phase=str(dimensions.get('emotion', {}).get('rotation_state') or ''),
        df=df)
    if state != _pre_state:
        state_reason = '多维度方向冲突/市场情绪过激，建议观望'
    # 交易机制硬约束（T+1/涨跌停/停牌前置过滤）
    _hard = _apply_hard_constraints(df, state)
    state = _hard['state']
    if _hard.get('reason'):
        state_reason = _hard['reason']

    # 七维红绿灯（源自 LLM Wiki 框架，数据来自五维）
    vp = dimensions.get('volume_price') or {}
    chip = dimensions.get('chip') or {}
    emo = dimensions.get('emotion') or {}
    chan = dimensions.get('chanlun') or {}
    # 几何指标（真实防守位/压力位：60日低点/60日高点；先算供 structure/risk/executable 复用）
    geo = _geometric(df)
    support = geo.get('support_price')
    resistance = geo.get('resistance_price')
    # 当前价（structure/risk 维判定用；K线缺失时为 None）
    price = float(df['close'].iloc[-1]) if (df is not None and not df.empty
                                            and 'close' in df.columns) else None
    trend_up = _dir_is_bullish(trend)
    above_support = (support is not None and price is not None and price > support)
    below_support = (support is not None and price is not None and price < support)
    # 信号证据与红绿灯一致：右侧否决/缠论卖点=🔴看空 / 买点或趋势看多=✅ / 无=🟡
    buy_point = str(chan.get('buy_point') or '')
    has_buy_signal = '买点' in buy_point and '卖点' not in buy_point
    has_sell_signal = '卖点' in buy_point
    rsc_deny = (rsc == '否决')
    if rsc_deny or has_sell_signal:
        signal_light, signal_plain = '🔴', ('右侧否决' if rsc_deny else '出现卖点信号')
    elif has_buy_signal or trend_up:
        signal_light, signal_plain = '✅', '上涨信号明确'
    else:
        signal_light, signal_plain = '🟡', '方向待确认'
    dims = [
        {
            'key': 'signal',
            'light': signal_light,
            'conclusion': f'趋势方向{trend}',
            'evidence': buy_point or vp.get('active_pattern') or '',
            'plain': signal_plain,
        },
        {
            'key': 'structure',
            'light': '✅' if above_support else ('🔴' if below_support else '🟡'),
            'conclusion': '结构位置',
            'evidence': (f"防守位{support} / 压力{resistance}"
                         if support or resistance else '结构位不足'),
            'plain': '站上防守位' if above_support else ('跌破防守位' if below_support else ''),
        },
        {
            'key': 'volume_price',
            'light': ('✅' if _dir_is_bullish(vp.get('direction'))
                      else ('🔴' if _dir_is_bearish(vp.get('direction')) else '🟡')),
            'conclusion': vp.get('phase_label') or '量价中性',
            'evidence': vp.get('active_pattern') or '',
            'plain': '',
        },
        {
            'key': 'fund',
            'light': ('✅' if inflow else ('🔴' if outflow else '🟡')),
            'conclusion': str(chip.get('main_force_direction') or '中性'),
            'evidence': f"筹码方向{chip.get('direction')}",
            'plain': '',
        },
        {
            'key': 'sentiment',
            'light': ('✅' if _dir_is_bullish(emo.get('direction'))
                      else ('🔴' if _dir_is_bearish(emo.get('direction')) else '🟡')),
            'conclusion': str(emo.get('rotation_state') or '中性'),
            'evidence': emo.get('sector') or '',
            'plain': '',
        },
        {
            'key': 'risk',
            'light': '✅' if support else '🟡',
            'conclusion': '风险边界',
            'evidence': f"止损位{support}" if support else '暂无结构位',
            'plain': '止损=结构位，跌破离场',
        },
    ]

    # 情景概率（规则基线；Kronos 修正可选）
    base = _scenario_base(dimensions)
    # ── S4：Kronos 可选修正（AI 预测仅供参考，非实证）──
    if kronos and kronos.get('direction'):
        kdir = kronos.get('direction', '')
        try:
            kconf = float(kronos.get('confidence', 0.5))
        except (TypeError, ValueError):
            kconf = 0.5
        delta = 0.25 * kconf
        if kdir == 'bullish':
            base['a'] += delta
            base['c'] -= delta * 0.5
        elif kdir == 'bearish':
            base['c'] += delta
            base['a'] -= delta * 0.5
        # base 边界保护（概率非负）
        for k in base:
            base[k] = max(0.0, base[k])
    scenarios = _normalize_scenarios([
        {'id': 'a', 'name': '趋势延续', 'prob': base['a'],
         'steps': ['回踩支撑位可加仓', '突破前高追进']},
        {'id': 'b', 'name': '冲高回落', 'prob': base['b'],
         'steps': ['阻力位附近减仓', '资金流出不开新仓']},
        {'id': 'c', 'name': '破位下行', 'prob': base['c'],
         'steps': ['跌破支撑位止损', '等待底部结构']},
    ])

    # 机器可执行（虚拟实盘前置契约；support 已由 geo 提供 = 60日低点防守位）
    enter_like = state in ('enter', 'light')
    # action_type 语义：enter/light=BUY(加仓) / wait=HOLD(持有观察) / avoid=SELL
    action_type = 'BUY' if enter_like else ('HOLD' if state == 'wait' else 'SELL')
    # 仓位上限：enter/light=0.6 / wait=0.2 / avoid=0（与弹窗 diagnose max_ratio 一致）
    max_pct = 0.6 if enter_like else (0.2 if state == 'wait' else 0.0)
    # 323号 S8：1 维反向 → 仓位减半（§三：方向冲突降级）
    _n_bear = sum(1 for x in dirs if x < 0)
    if state in ('enter', 'light') and _n_bear == 1:
        max_pct = min(max_pct, 0.3)
    executable = {
        'action_type': action_type,
        # 入场=现价市价买入（trigger 用现价，避免与止损同价歧义：方案322 entry 10.20/exit 9.80 两档）
        'entry_rules': ([{'trigger': f'close <= {price}', 'action': 'BUY', 'size_pct': 30}]
                        if price and state != 'avoid' else []),
        # 止损=跌破 60 日低点防守位离场（322号 H3：真实防守位）
        'exit_rules': ([{'trigger': f'close < {support}', 'action': 'SELL', 'size_pct': 100}]
                       if support else []),
        'position': {'max_pct': max_pct, 'initial_pct': 0.3 if max_pct > 0 else 0.0},
    }

    _state_cn = _STATE_CN.get(state, state)
    result = {
        'state': state, 'state_reason': state_reason,
        'summary': f"{_state_cn}：{state_reason}" if state_reason else _state_cn,
        'dimensions': dims, 'geometric': geo,
        'scenarios': scenarios, 'executable': executable,
    }
    # ── 323号 S6：操作建议卡 6 字段（全部现有数据派生，零新采集）──
    # 注意：函数内 dims 已被七维红绿灯列表覆盖，五维原参用 dimensions；
    # consensus（五维推导）已算，供 confidence 使用（consensus_rate 标签未落库）
    result.update(_build_advice_card_fields(
        state, tags, dimensions, geo, support, signal_light, executable, df, dims,
        consensus_rate=consensus['consensus_rate']))
    # action 快照须在降级后（低置信度降级会改 executable.position.max_pct）
    result['action'] = {'max_position_ratio': executable['position']['max_pct']}
    if kronos and kronos.get('direction'):
        result['kronos_note'] = '🔬 Kronos AI 模型预测，仅供参考，非实证结论'
    return result


# ─────────────────────────────────────────────
# 323号 S6：操作建议卡字段派生（§五 3.1-3.6）
# ─────────────────────────────────────────────

def _map_action_label(state: str, signal_strength: float) -> str:
    """状态→5档操作动作（§3.2：给人看；executable.action_type 保留机器 3 态）"""
    if state == 'enter' and signal_strength >= 80:
        return '重仓买入'
    if state == 'enter':
        return '买入/建仓'
    if state == 'light':
        return '轻仓试探'
    if state == 'wait':
        return '持有/观望'
    return '清仓回避'   # avoid


def _build_invalidation(state, support, sentiment_phase, rsc) -> list[str]:
    """失效条件派生（§3.3：止损位 + 情绪退潮 + 右侧否决）"""
    conditions = []
    if support is not None:
        conditions.append(f'收盘跌破止损位 {support}')
    if sentiment_phase in ('ebb', 'climax'):
        conditions.append('大盘进入退潮/高潮期，追涨风险大')
    if rsc == '否决':
        conditions.append('右侧确认已转为否决（卖出/背离/预跌信号）')
    return conditions


def _calc_confidence(consensus_rate: float, evidence_count: int,
                     conflict_count: int) -> str:
    """置信度合成（§3.4：证据阈值校准 >=4——实测值域 0-5 峰值 3）"""
    if conflict_count >= 3 or evidence_count == 0:
        return '低'
    if consensus_rate >= 0.75 and evidence_count >= 4 and conflict_count <= 1:
        return '高'
    if consensus_rate >= 0.55 or conflict_count == 2:
        return '中'
    return '低'


def _build_target_levels(df) -> list[dict]:
    """目标位派生（§3.5：60日高点=目标1，×1.15=目标2；标注参考压力位）"""
    if df is None or df.empty or 'high' not in df.columns or len(df) < 60:
        return []
    hi60 = float(df['high'].tail(60).max())
    return [{'price': round(hi60, 2), 'reason': '60日高点压力位'},
            {'price': round(hi60 * 1.15, 2), 'reason': '保守扩展目标'}]


def _build_expected_holding(tags: dict) -> str:
    """预期持有派生（§3.6：time_rhythm 中文化映射；实测值域校准）"""
    tr = str((tags or {}).get('time_rhythm') or '')
    holding_map = {
        'early_consolidation': '筑底/建仓初期，波段 20-30 个交易日',
        'mid_consolidation': '箱体整理中段，短线 10-20 个交易日',
        'approaching_turn': '临近变盘，等待方向选择（5-10 个交易日）',
    }
    return holding_map.get(tr, '日线波段 20-30 个交易日')


def _build_advice_card_fields(state, tags, dims, geo, support, signal_light,
                              executable, df, light_dims=None,
                              consensus_rate=None) -> dict:
    """组装 S6 建议卡字段（§3.1：全部现有数据派生）"""
    # signal_light：state 映射（与七维 signal 灯独立，顶层信号灯）
    _light_map = {'enter': '🟢', 'light': '🟢', 'wait': '🟡', 'avoid': '🔴'}
    # action_label：5档映射
    try:
        _ss = float((tags or {}).get('signal_strength') or 0)
    except (TypeError, ValueError):
        _ss = 0.0
    action_label = _map_action_label(state, _ss)
    # confidence：共识率（五维推导）+证据数+冲突数
    # 注：consensus_rate 标签全市场缺失（实证 0 只），用函数内五维推导 consensus
    _consensus = consensus_rate if consensus_rate is not None else 0.0
    try:
        _ev_cnt = int((tags or {}).get('evidence_count') or 0)
    except (TypeError, ValueError):
        _ev_cnt = 0
    _conflicts = dims.get('factor', {}).get('conflict_items') or []
    confidence = _calc_confidence(_consensus, _ev_cnt, len(_conflicts))
    # 低置信度降级（§3.4）：强制'轻仓试探' + max_pct<=0.3
    if confidence == '低' and state in ('enter', 'light'):
        action_label = '轻仓试探'
        executable['position']['max_pct'] = min(
            executable['position'].get('max_pct', 0.0), 0.3)
        executable['position']['initial_pct'] = min(
            executable['position'].get('initial_pct', 0.0), 0.15)
    # evidence_top3：七维红绿灯 evidence 非空前 3 条，不足 state_reason 补
    evidence_top3 = []
    for _d in light_dims or dims or []:
        if not isinstance(_d, dict):
            continue
        ev = str(_d.get('evidence') or '').strip()
        if ev and ev not in evidence_top3:
            evidence_top3.append(ev)
        if len(evidence_top3) >= 3:
            break
    if len(evidence_top3) < 3:
        _reason = (tags or {}).get('state_reason') or ''
        if _reason and _reason not in evidence_top3:
            evidence_top3.append(_reason)
    # invalidation：止损位 + 情绪退潮 + 右侧否决
    _sent = str(dims.get('emotion', {}).get('rotation_state') or '')
    _sent_phase = ('ebb' if '退潮' in _sent else
                   ('climax' if '高潮' in _sent else ''))
    _rsc = str((tags or {}).get('right_side_confirm') or '')
    invalidation = _build_invalidation(state, support, _sent_phase, _rsc)

    return {
        'signal_light': _light_map.get(state, '🟡'),
        'action_label': action_label,
        'target_levels': _build_target_levels(df),
        'expected_holding': _build_expected_holding(tags),
        'invalidation': invalidation,
        'confidence': confidence,
        'evidence_top3': evidence_top3,
    }


# ─────────────────────────────────────────────
# 323号 S8：映射与降级机制（建议卡 §三）
# ─────────────────────────────────────────────

def _apply_degradation(state: str, dirs: list[int], sentiment_phase: str = '',
                       df=None) -> str:
    """方向冲突降级 + 市场状态过滤（§三：1维反向→仓位减半由调用方处理；≥2维→强制观望）

    dirs: 五维方向（_dim_directions 输出：+1 看多 / -1 看空 / 0 中性）
    sentiment_phase: '高潮期'/'退潮期' 等中文（rotation_state）
    Returns: 降级后的 state
    """
    n_bear = sum(1 for x in dirs if x < 0)
    n_bull = sum(1 for x in dirs if x > 0)
    # ≥2 维反向 → 强制观望（L4 tie 先例：分歧降级谨慎）
    if state in ('enter', 'light') and n_bear >= 2:
        return 'wait'
    # 市场高潮/退潮期 → 买入类降级（不做重仓；wait 保持）
    if state in ('enter', 'light'):
        _sent = str(sentiment_phase or '')
        if '高潮' in _sent or '退潮' in _sent:
            return 'light'
    return state


def _apply_hard_constraints(df, state: str) -> dict:
    """交易机制硬约束（§三：T+1/涨跌停/停牌前置过滤，本期基础版）

    - 停牌（最新 volume=0 或 K线缺失）→ 不出买入建议（wait）
    Returns: {'state': str, 'reason': str|None}
    """
    if state not in ('enter', 'light'):
        return {'state': state, 'reason': None}
    if df is None or df.empty or 'volume' not in df.columns:
        return {'state': state, 'reason': None}
    try:
        last_vol = float(df['volume'].iloc[-1])
    except (TypeError, ValueError):
        return {'state': state, 'reason': None}
    if last_vol <= 0:
        return {'state': 'wait', 'reason': '停牌/无成交，暂不建议操作'}
    return {'state': state, 'reason': None}
