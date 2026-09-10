"""维度适配器 — 从status_engine提取维度转换逻辑（387号方案模块拆分）

提供：
- 维度方向/顺序/状态映射常量
- dim_results → dims格式转换（替代StatusEngine._convert_to_dims_format）
- 多空得分计算（替代StatusEngine._aggregate内联逻辑）
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ── 维度方向映射（state → +1看多 / 0中性 / -1看空） ──
DIM_DIRECTION: dict[str, dict[str, int]] = {
    'valuation': {'极度低估': 2, '低估': 1, '合理': 0, '高估': -1, '极度高估': -2},
    'structure': {'上升': 1, '盘整': 0, '下降': -1},
    'vp': {'强健康': 2, '健康': 1, '中性': 0, '背离': -1, '严重背离': -2},
    'position': {'站上防守位': 1, '中位': 0, '跌破': -1},
    'chip_fund': {'建仓': 1, '拉升': 2, '流入': 1, '中性': 0,
                  '洗盘': 0, '派发': -1, '流出': -1, '未知': 0},
    'emotion': {'积极': 1, '复苏': 1, '正常': 0, '中性': 0,
                '消极': -1, '退潮·高潮': -1, '退潮': -1, '冰点': -1},
    'finance': {'健康': 1, '关注': 0, '风险': -1},
    'event': {'正向': 1, '中性': 0, '负面': -1},
    'time': {'初期': 1, '中期': 0, '已延伸': -1, '回撤': -1},
    'risk': {'低': 1, '中': 0, '高': -1},
    'factor': {'看多': 1, '中性': 0, '看空': -1},
}

# 维度灯色映射（从方向映射自动推导）
DIM_LIGHT: dict[str, dict[str, str]] = {
    dim: {s: ('green' if v > 0 else ('yellow' if v == 0 else 'red'))
          for s, v in mapping.items()}
    for dim, mapping in DIM_DIRECTION.items()
}

# 维度聚合顺序（_aggregate遍历顺序）
DIM_ORDER = ['valuation', 'structure', 'vp', 'position', 'chip_fund', 'emotion',
             'finance', 'event', 'time', 'risk', 'factor']

# 366号方案：维度引擎输出英文 state 值，DIM_DIRECTION 键为中文
# 此映射在 convert_to_dims_format 中将英文 state 转为中文，同时服务：
#   1. _aggregate → DIM_DIRECTION 共识率计算（需要中文键）
#   2. dim_states → status_snapshot → 前端展示（需要中文显示）
ENGINE_STATE_TO_CN = {
    'valuation': {
        'extreme_low': '极度低估', 'low': '低估', 'fair': '合理',
        'high': '高估', 'extreme_high': '极度高估',
    },
    'position': {
        'mid': '中位', 'low_zone': '跌破', 'high_zone': '站上防守位',
    },
    'finance': {
        'suspicious': '关注', 'fail': '风险', 'healthy': '健康',
    },
    'event': {
        'none': '中性', 'breakout': '正向', 'lhb': '负面',
        'regulatory': '负面', 'concept': '中性', 'fraud_sign': '负面',
    },
    'signal_confirm': {
        'unconfirmed': '未确认', 'strong_confirm': '强确认',
    },
    'emotion': {
        'positive': '积极', 'neutral': '中性', 'negative': '消极',
        'recovery': '复苏', 'climax': '高潮', 'ebb': '退潮', 'ice': '冰点',
        '正常': '正常',
    },
    'chip_fund': {
        'inflow': '流入', 'outflow': '流出', 'neutral': '中性',
        '中性': '中性',
        'building': '建仓', 'washing': '洗盘', 'lifting': '拉升',
        'raising': '拉升', 'distributing': '派发', 'unknown': '未知',
    },
    'structure': {
        '上升': '上升', '盘整': '盘整', '下降': '下降',
        'bullish': '上升', 'mixed': '盘整', 'bearish': '下降',
    },
    'risk': {
        'LOW': '低', 'HIGH': '高', 'MEDIUM': '中',
        '低': '低', '中': '中', '高': '高',
    },
}


def convert_to_dims_format(dim_results: dict, tags: dict) -> dict:
    """387号v3.0：将维度引擎输出转为旧dims格式，增强SIG字段消费

    从StatusEngine._convert_to_dims_format提取为独立函数（与status_engine.py保持一致）。

    v3.0变更：
    - dim2: level_cross_score→confidence增强 + evidence提取
    - dim3: 量价五态（强健康/健康/中性/背离/严重背离）
    - dim5: temperature→confidence增强 +time_rhythm→time维
    - dim6: atr_pct→confidence增强
    - dim7: composite_rating替代tags粗粒度标签（judgment.valuation_level是嵌套dict）

    Args:
        dim_results: 维度引擎预计算结果（{dim_name: engine_output}）
        tags: pre_feat_cache扁平化标签

    Returns:
        dims格式dict（{dim_key: {state, light, confidence, evidence}}）
    """
    dims = {}
    _t = ENGINE_STATE_TO_CN

    # ── dim2 结构维 ──
    s = dim_results.get('structure')
    if s and isinstance(s, dict):
        judg = s.get('judgment', {})
        sd = s.get('status_description', {})
        _confidence = 0.7
        _cross = sd.get('level_cross_score')
        if _cross is not None:
            _confidence = min(0.9, max(0.3, float(_cross)))
        dims['structure'] = {
            'state': judg.get('structure', tags.get('state_label', '盘整')),
            'light': judg.get('light', 'yellow'),
            'confidence': _confidence,
            'evidence': [sd.get('plain', '')],
        }
    else:
        _ind_status = tags.get('indicator_status', '')
        _ma_val = '盘整'
        if 'ma=' in str(_ind_status):
            _ma_part = str(_ind_status).split('ma=')[1].split(',')[0].strip()
            _ma_val = _t['structure'].get(_ma_part, '盘整')
        elif tags.get('state_label') and tags['state_label'] != 'unknown':
            _ma_val = _t['structure'].get(tags['state_label'], '盘整')
        dims['structure'] = {'state': _ma_val, 'light': 'yellow', 'confidence': 0.5, 'evidence': []}

    # ── dim3 量价维（388号升级C：state_machine_direction+multi_timeframe_consistency接入） ──
    vp = dim_results.get('volume_price')
    if vp and isinstance(vp, dict):
        judg = vp.get('judgment', {})
        sd = vp.get('status_description', {})
        _vp_confidence = judg.get('continuous_value', 0.6)
        _vp_evidence = []
        # 388号升级C：state_machine_direction增强方向判定
        _sm_dir = str(sd.get('state_machine_direction', ''))
        if _sm_dir == 'BUY':
            _vp_evidence.append('状态机方向=BUY')
            _vp_confidence = min(0.9, _vp_confidence + 0.1)
        elif _sm_dir == 'SELL':
            _vp_evidence.append('状态机方向=SELL')
            _vp_confidence = min(0.9, _vp_confidence + 0.1)
        # 388号升级C：multi_timeframe_consistency增强信号
        _mtf = str(sd.get('multi_timeframe_consistency', ''))
        if '一致' in _mtf and ('BUY' in _mtf or 'BULLISH' in _mtf):
            _vp_evidence.append('日线+周线一致→信号强化')
            _vp_confidence = min(0.95, _vp_confidence + 0.05)
        elif '冲突' in _mtf or '分歧' in _mtf:
            _vp_evidence.append('日线+周线分歧→信号弱化')
            _vp_confidence = max(0.3, _vp_confidence - 0.1)
        dims['vp'] = {
            'state': judg.get('vp_state', '中性'),
            'light': judg.get('light', 'yellow'),
            'confidence': round(_vp_confidence, 4),
            'evidence': _vp_evidence,
        }
    else:
        dims['vp'] = {'state': '中性', 'light': 'yellow', 'confidence': 0.5, 'evidence': []}

    # ── dim4 筹码维（388号升级E：fund_flow+phase_confidence+cost_profit_ratio接入） ──
    cf = dim_results.get('chip_fund')
    if cf and isinstance(cf, dict):
        judg = cf.get('judgment', {})
        sd = cf.get('status_description', {})
        _cf_phase = judg.get('phase', '')
        _cf_phase_cn = _t.get('chip_fund', {}).get(_cf_phase, _cf_phase)
        _cf_confidence = 0.5
        _cf_evidence = []
        # 388号升级E：phase_confidence增强置信度
        _phase_conf = sd.get('phase_confidence')
        if _phase_conf is not None:
            _cf_confidence = min(0.85, max(0.4, float(_phase_conf)))
        # 388号升级E：fund_flow增强方向信号
        _fund_flow = str(sd.get('fund_flow', ''))
        if _fund_flow == '强流入':
            _cf_evidence.append('资金强流入')
            _cf_confidence = min(0.9, _cf_confidence + 0.05)
        elif _fund_flow == '强流出':
            _cf_evidence.append('资金强流出')
            _cf_confidence = min(0.9, _cf_confidence + 0.05)
        dims['chip_fund'] = {
            'state': _cf_phase_cn or judg.get('direction', '中性'),
            'light': judg.get('light', 'yellow'),
            'confidence': round(_cf_confidence, 4),
            'evidence': _cf_evidence,
        }
    else:
        dims['chip_fund'] = {'state': '中性', 'light': 'yellow', 'confidence': 0.5, 'evidence': []}

    # ── dim5 情绪维（388号升级D：bociasi_fast_signal+quadrant接入） ──
    _emotion_raw = tags.get('stock_emotion', tags.get('sentiment_phase', '中性'))
    _emotion_cn = _t['emotion'].get(_emotion_raw, _emotion_raw)
    _emo_confidence = 0.5
    _emo_evidence = []
    emo = dim_results.get('emotion')
    if emo and isinstance(emo, dict):
        sd = emo.get('status_description', {})
        _temp = sd.get('temperature')
        if _temp is not None:
            _t_val = float(_temp)
            _emo_confidence = min(0.8, max(0.3, 0.3 + _t_val / 200))
        # 388号升级D：bociasi_fast_signal增强方向
        _fast = str(sd.get('bociasi_fast_signal', ''))
        if _fast == 'BUY':
            _emo_evidence.append('快线=BUY')
            _emo_confidence = min(0.85, _emo_confidence + 0.05)
        elif _fast == 'BEARISH':
            _emo_evidence.append('快线=BEARISH')
            _emo_confidence = min(0.85, _emo_confidence + 0.05)
        # 388号升级D：bociasi_quadrant增强权重感知
        _quadrant = str(sd.get('bociasi_quadrant', ''))
        if _quadrant in ('LL', 'HH'):
            _emo_evidence.append(f'四象限={_quadrant}')
    dims['emotion'] = {'state': _emotion_cn, 'light': 'yellow', 'confidence': round(_emo_confidence, 4),
                       'evidence': _emo_evidence}

    # ── dim6 风险维 ──
    r = dim_results.get('risk')
    if r and isinstance(r, dict):
        judg = r.get('judgment', {})
        _risk_confidence = 0.6
        sd = r.get('status_description', {})
        _atr = sd.get('atr_pct')
        if _atr is not None:
            _risk_confidence = min(0.8, max(0.4, 0.4 + float(_atr) / 2))
        dims['risk'] = {
            'state': judg.get('risk_level', '中'),
            'light': judg.get('light', 'yellow'),
            'confidence': _risk_confidence,
            'evidence': [],
        }
    else:
        _risk_raw = tags.get('risk_level', '中')
        _risk_cn = _t['risk'].get(_risk_raw, _risk_raw)
        dims['risk'] = {'state': _risk_cn, 'light': 'yellow', 'confidence': 0.5, 'evidence': []}

    # ── dim7 估值维（388号升级B：composite_rating连续值替代tags粗粒度标签） ──
    val = dim_results.get('valuation')
    if val and isinstance(val, dict):
        judg = val.get('judgment', {})
        sd = val.get('status_description', {})
        # 使用composite_rating连续值判定state（替代judgment.valuation_level英文标签）
        _composite = sd.get('composite_rating')
        if _composite is not None:
            _cr = float(_composite)
            if _cr <= -1.5:
                _val_state = 'extreme_high'
            elif _cr <= -0.5:
                _val_state = 'high'
            elif _cr >= 1.5:
                _val_state = 'extreme_low'
            elif _cr >= 0.5:
                _val_state = 'low'
            else:
                _val_state = 'fair'
        else:
            # 降级：使用judgment.valuation_level嵌套dict
            _val_judg = judg.get('valuation_level', {})
            if isinstance(_val_judg, dict):
                _val_state = _val_judg.get('value', tags.get('valuation_level', '合理'))
            else:
                _val_state = str(_val_judg) if _val_judg else tags.get('valuation_level', '合理')
        _val_cn = _t['valuation'].get(_val_state, _val_state)
        # confidence：从pe_percentile_5y增强（分位越高=估值越确定）
        _val_confidence = 0.7
        _pe_pct = sd.get('pe_percentile_5y')
        if _pe_pct is not None:
            _pe_v = float(_pe_pct)
            if _pe_v > 90 or _pe_v < 10:
                _val_confidence = 0.9  # 极端分位=高确定性
            elif _pe_v > 70 or _pe_v < 30:
                _val_confidence = 0.8
        # evidence：包含composite_rating和潜力评分
        _val_evidence = []
        if _composite is not None:
            _val_evidence.append(f'composite={float(_composite):.2f}')
        if sd.get('potential_score') is not None or sd.get('potential_strength') is not None:
            _val_evidence.append(f'潜力={_potential_score_int(sd)}/100')
        dims['valuation'] = {
            'state': _val_cn,
            'light': judg.get('overall_light', 'yellow'),
            'confidence': _val_confidence,
            'evidence': _val_evidence,
        }
        # factor维：从potential_score引擎输出替代固定"中性"
        _ps_int = _potential_score_int(sd)
        if _ps_int != 50 or sd.get('potential_score') is not None or sd.get('potential_strength') is not None:
            if _ps_int >= 70:
                _factor_state = '看多'
            elif _ps_int <= 30:
                _factor_state = '看空'
            else:
                _factor_state = '中性'
            _ps_judg = judg.get('potential_strength', {})
            _factor_light = _ps_judg.get('light', 'yellow') if isinstance(_ps_judg, dict) else 'yellow'
            dims['factor'] = {'state': _factor_state, 'light': _factor_light,
                              'confidence': min(0.9, _ps_int / 100), 'evidence': [f'潜力={_ps_int}/100']}
    else:
        _val_raw = tags.get('valuation_level', '合理')
        dims['valuation'] = {
            'state': _t['valuation'].get(_val_raw, _val_raw),
            'light': 'yellow', 'confidence': 0.5, 'evidence': [],
        }

    # ── 其他维度 ──
    # finance维：优先使用dim7引擎的fina_health精确值，降级到tags
    _fin_engine = None
    if val and isinstance(val, dict):
        _fin_judg = (val.get('judgment') or {}).get('fina_health', {})
        if isinstance(_fin_judg, dict) and _fin_judg.get('value'):
            _fin_engine = _fin_judg['value']
    _fin_raw = _fin_engine or tags.get('fina_health', '关注')
    _fin_light = 'yellow'
    if val and isinstance(val, dict):
        _fin_jg = (val.get('judgment') or {}).get('fina_health', {})
        if isinstance(_fin_jg, dict):
            _fin_light = _fin_jg.get('light', 'yellow')
    dims['finance'] = {'state': _t['finance'].get(_fin_raw, _fin_raw), 'light': _fin_light, 'confidence': 0.5, 'evidence': []}
    _evt_raw = tags.get('catalyst_event', '中性')
    dims['event'] = {'state': _t['event'].get(_evt_raw, _evt_raw), 'light': 'yellow', 'confidence': 0.5, 'evidence': []}

    # time维：387号路径A增强，从dim5.time_rhythm读取
    _time_state = '中期'
    if emo and isinstance(emo, dict):
        _tr = (emo.get('status_description') or {}).get('time_rhythm', '')
        if '变盘' in str(_tr):
            _time_state = '初期'
        elif '延伸' in str(_tr):
            _time_state = '已延伸'
    dims['time'] = {'state': _time_state, 'light': 'yellow', 'confidence': 0.5, 'evidence': []}

    _pos_raw = tags.get('price_position', '中位')
    dims['position'] = {'state': _t['position'].get(_pos_raw, _pos_raw), 'light': 'yellow', 'confidence': 0.5, 'evidence': []}
    # factor维：388号升级B从dim7.potential_score设置；若dim7未输出则回退到固定"中性"
    if 'factor' not in dims:
        dims['factor'] = {'state': '中性', 'light': 'yellow', 'confidence': 0.5, 'evidence': []}
    # 411号Phase 2：signal_confirm由classify_attribute()分析结果生成
    try:
        from app.opportunity_atlas.signal_analyzer import LIGHT_MAP as _SIG_LIGHT_MAP
        from app.opportunity_atlas.signal_analyzer import classify_attribute
        _attr = classify_attribute(dims, tags, {})
        _attr_code = _attr.get('code', 'neutral')
        dims['signal_confirm'] = {
            'state': _attr.get('name', '中性观望'),
            'light': _SIG_LIGHT_MAP.get(_attr_code, 'yellow'),
            'confidence': 0.6,
            'evidence': [_attr.get('detail', '')],
        }
    except Exception:
        _rsc_raw = tags.get('right_side_confirm', '未确认')
        dims['signal_confirm'] = {'state': _t['signal_confirm'].get(_rsc_raw, _rsc_raw), 'light': 'yellow', 'confidence': 0.5, 'evidence': []}

    return dims


def extract_direction_score(dims: dict, weights: dict) -> dict:
    """基于维度状态+权重计算多空得分

    从StatusEngine._aggregate核心计算逻辑提取。

    Args:
        dims: convert_to_dims_format输出（{dim: {state, ...}}）
        weights: 权重dict（{dim: weight}），来自weight_engine

    Returns:
        {
            'bull': float,        # 多头总权重
            'bear': float,        # 空头总权重
            'consensus_rate': float,  # 一致性比率 [0, 1]
            'direction': str,     # 'bullish' | 'bearish' | 'neutral'
        }
    """
    bull = bear = 0.0
    for dim in DIM_ORDER:
        state = dims.get(dim, {}).get('state', '')
        v = DIM_DIRECTION[dim].get(state, 0)
        w = weights.get(dim, 0.1)
        if v > 0:
            bull += w
        elif v < 0:
            bear += w

    total_w = bull + bear
    if total_w > 0:
        consensus_rate = round(max(bull, bear) / total_w, 3)
        direction = 'bullish' if bull > bear else 'bearish'
    elif bull == bear and bull > 0:
        consensus_rate = 0.0
        direction = 'neutral'
    else:
        consensus_rate = 0.0
        direction = 'neutral'

    return {
        'bull': bull,
        'bear': bear,
        'consensus_rate': consensus_rate,
        'direction': direction,
    }


# ── 390号方案v3.0：L1维度适配层 —— 8维度引擎输出 → JUD因子格式 ──

# dim1 signal attribute.code → direction 映射
_SIGNAL_CODE_DIRECTION: dict[str, int] = {
    'right_confirmed': 1,
    'right_emerging': 1,
    'trend_running': 1,
    'risk_warning': -1,
    'neutral': 0,
}

# dim5 emotion state → direction 映射
# 设计意图（均值回归策略）：冰点=反转看多机会（恐慌创造低估），积极=过热看空风险（亢奋追涨危险）
# 与dim5引擎的temperature方向一致：temperature<50=偏冷→看多机会，>50=偏热→看空风险
_EMOTION_DIRECTION: dict[str, int] = {
    'ice': 1,
    'ebb': 0,
    'normal': 0,
    'recovery': 1,
    'positive': -1,
    # 中文键兼容
    '冰点': 1,
    '退潮': 0,
    '退潮·高潮': 0,
    '正常': 0,
    '中性': 0,
    '复苏': 1,
    '积极': -1,
    '消极': 0,
}


def _safe_float(val, default: float = 0.0) -> float:
    """安全提取 float，None/异常均返回 default"""
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _potential_score_int(sd: dict) -> int:
    """从 dim7 status_description 提取数字潜力评分

    优先读 potential_strength（数字）；回退解析 potential_score 字符串（"潜力评分53/100"）。
    均不可解析时返回 50（默认中性）。
    """
    if not sd:
        return 50
    ps = sd.get('potential_strength')
    if ps is not None:
        try:
            return int(round(float(ps)))
        except (TypeError, ValueError):
            pass
    raw = sd.get('potential_score')
    if raw is not None:
        s = str(raw)
        # 匹配 "潜力评分53/100" 或 "53" 或 "53/100"
        import re
        m = re.search(r'(\d+)', s)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
    return 50

def _clamp(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    """将 value 限制在 [lo, hi] 区间"""
    return max(lo, min(hi, value))


def convert_to_factors(dim_results: dict, tags: dict) -> dict:
    """L1维度适配层：将8维度引擎输出转换为JUD因子格式（390号方案v3.0）

    Returns:
        dims_factor: dict mapping dim_name → {direction: int, strength: float, evidence: list}
            direction: -1 看空 / 0 中性 / 1 看多
            strength: 信号强度 [0.0, 1.0]
            evidence: 支撑证据字符串列表（供L4审计）
    """
    factors: dict[str, dict] = {}

    # ── dim1 signal ──────────────────────────────────────────────────
    _sig = dim_results.get('signal')
    _sig_attr_code = 'neutral'
    if _sig and isinstance(_sig, dict):
        _sig_judg = _sig.get('judgment', {})
        _sig_attr = _sig_judg.get('attribute', {})
        _sig_attr_code = str(_sig_attr.get('code', 'neutral')) if isinstance(_sig_attr, dict) else 'neutral'
    _dim1_dir = _SIGNAL_CODE_DIRECTION.get(_sig_attr_code, 0)
    factors['signal'] = {
        'direction': _dim1_dir,
        'strength': 0.5,  # 初始固定值，后续优化
        'evidence': [f'信号类型={_sig_attr_code}'],
    }

    # ── dim2 structure ───────────────────────────────────────────────
    _str = dim_results.get('structure')
    _dim2_dir = 0
    _dim2_str = 0.0
    _dim2_evidence: list[str] = []
    _dim2_extras: dict = {}
    if _str and isinstance(_str, dict):
        _str_judg = _str.get('judgment', {})
        _str_sd = _str.get('status_description', {})
        # direction 来自 overall_direction（整数或字符串）
        _overall_dir = _str_judg.get('overall_direction', 0)
        try:
            _dim2_dir = int(_overall_dir)
        except (TypeError, ValueError):
            if str(_overall_dir).lower() in ('bullish', '上升'):
                _dim2_dir = 1
            elif str(_overall_dir).lower() in ('bearish', '下降'):
                _dim2_dir = -1
            else:
                _dim2_dir = 0
        # strength: 0.4*chanlun_strength + 0.4*level_cross_score + 0.2*continuous_value
        _chanlun_str = _safe_float(_str_sd.get('chanlun_strength'), 0.5)
        _cross_score = _safe_float(_str_sd.get('level_cross_score'), 0.5)
        _cont_val = _safe_float(_str_judg.get('continuous_value'), 0.5)
        _dim2_str = 0.4 * _chanlun_str + 0.4 * _cross_score + 0.2 * _cont_val
        # 123_buy_breakout 增强
        _ts_signal = str(_str_sd.get('trend_structure_signal', ''))
        if _ts_signal == '123_buy_breakout' and _dim2_dir > 0:
            _ts_strength = _safe_float(_str_sd.get('ts_strength'), 0.0)
            _dim2_str += _ts_strength + 0.05
        # 欲病折减
        _chanlun_phase = str(_str_sd.get('chanlun_phase', ''))
        if '欲病' in _chanlun_phase:
            _dim2_str *= 0.7
        _dim2_str = _clamp(_dim2_str, 0.0, 1.0)
        # buy_sell_points_detail 增强 direction（方案390：dim2买卖点详情消费）
        _bsp = _str_sd.get('buy_sell_points_detail') or []
        if isinstance(_bsp, list) and _bsp:
            _confirmed_buys = sum(1 for p in _bsp if isinstance(p, dict) and p.get('type') == 'buy' and p.get('confirmed'))
            _confirmed_sells = sum(1 for p in _bsp if isinstance(p, dict) and p.get('type') == 'sell' and p.get('confirmed'))
            if _confirmed_buys > 0 and _confirmed_sells == 0 and _dim2_dir <= 0:
                _dim2_dir = 1  # 确认买点→看多
                _dim2_evidence.append(f'买卖点增强：{_confirmed_buys}个确认买点')
            elif _confirmed_sells > 0 and _confirmed_buys == 0 and _dim2_dir >= 0:
                _dim2_dir = -1  # 确认卖点→看空
                _dim2_evidence.append(f'买卖点削弱：{_confirmed_sells}个确认卖点')
        # L4 提取
        _dim2_extras['stage_name'] = str(_str_sd.get('stage_name', ''))
        _dim2_extras['divergence'] = str(_str_sd.get('divergence', ''))
        _dim2_evidence.append(f'overall_direction={_overall_dir}')
    else:
        # 无引擎输出时回退到 tags
        _state_label = tags.get('state_label', '盘整')
        _dim2_dir = DIM_DIRECTION.get('structure', {}).get(_state_label, 0)
        _dim2_str = 0.3

    factors['structure'] = {
        'direction': _dim2_dir,
        'strength': round(_dim2_str, 4),
        'evidence': _dim2_evidence if _dim2_evidence else ['structure:tag_fallback'],
        **_dim2_extras,
    }

    # ── dim3 volume_price ────────────────────────────────────────────
    _vp = dim_results.get('volume_price')
    _dim3_dir = 0
    _dim3_str = 0.5
    _dim3_evidence: list[str] = []
    _dim3_extras: dict = {}
    if _vp and isinstance(_vp, dict):
        _vp_judg = _vp.get('judgment', {})
        _vp_sd = _vp.get('status_description', {})
        # step 1: direction 来自 state_machine_direction
        _sm_dir = str(_vp_sd.get('state_machine_direction', 'HOLD'))
        if _sm_dir == 'BUY':
            _dim3_dir = 1
        elif _sm_dir == 'SELL':
            _dim3_dir = -1
        else:
            _dim3_dir = 0
        # step 2: base strength = 0.7*state_machine_confidence + 0.3*resonance_norm
        _sm_conf = _safe_float(_vp_sd.get('state_machine_confidence'), 0.5)
        _resonance_raw = _safe_float(_vp_sd.get('resonance_score'), 0.0)
        _resonance_norm = max(0.0, min(1.0, (_resonance_raw + 5.0) / 10.0))  # [-5,5] → [0,1]
        _dim3_str = 0.7 * _sm_conf + 0.3 * _resonance_norm
        # step 3: multi_timeframe_consistency 冲突/分歧修正（方向 + 强度）
        _mtf = str(_vp_sd.get('multi_timeframe_consistency', ''))
        _has_conflict = '冲突' in _mtf
        _has_divergence = '分歧' in _mtf
        if _has_conflict or _has_divergence:
            _mtf_sub = str(_vp_sd.get('multi_timeframe_sub_states', ''))
            _buy_sell_clash = (
                ('BUY' in _mtf_sub and 'SELL' in _mtf_sub)
                or ('BULLISH' in _mtf_sub and 'BEARISH' in _mtf_sub)
            )
            if _buy_sell_clash:
                # BUY+SELL冲突 → 方向归零，强度固定0.3
                _dim3_dir = 0
                _dim3_str = 0.3
                _dim3_evidence.append('multi_timeframe冲突→方向归零,strength=0.3')
            elif 'HOLD' in _mtf_sub or 'WATCH' in _mtf_sub:
                # 一方HOLD/WATCH → 保持方向，强度×0.7
                _dim3_str *= 0.7
                _dim3_evidence.append('multi_timeframe分歧→强度×0.7')
        _dim3_str = _clamp(_dim3_str, 0.0, 1.0)
        _dim3_evidence.append(f'state_machine={_sm_dir}')
        # L4 提取
        _dim3_extras['stage_name'] = str(_vp_sd.get('stage_name', ''))
        _dim3_extras['divergence'] = str(_vp_sd.get('divergence', ''))
        _dim3_extras['vol_ratio'] = _safe_float(_vp_sd.get('vol_ratio'), 0.0)
    else:
        _dim3_str = 0.3

    factors['vp'] = {
        'direction': _dim3_dir,
        'strength': round(_dim3_str, 4),
        'evidence': _dim3_evidence if _dim3_evidence else [],
        **_dim3_extras,
    }

    # ── dim4 chip_fund ───────────────────────────────────────────────
    _cf = dim_results.get('chip_fund')
    _dim4_dir = 0
    _dim4_str = 0.5
    _dim4_evidence: list[str] = []
    _dim4_extras: dict = {}
    if _cf and isinstance(_cf, dict):
        _cf_judg = _cf.get('judgment', {})
        _cf_sd = _cf.get('status_description', {})
        # direction: phase → DIM_DIRECTION['chip_fund']
        _cf_phase = str(_cf_judg.get('phase', ''))
        _cf_phase_cn = ENGINE_STATE_TO_CN.get('chip_fund', {}).get(_cf_phase, _cf_phase)
        _dim4_dir = DIM_DIRECTION.get('chip_fund', {}).get(_cf_phase_cn, 0)
        _dim4_evidence.append(f'phase={_cf_phase}')
        # strength: phase_confidence, fallback continuous_value
        _phase_conf = _safe_float(_cf_sd.get('phase_confidence'), -1.0)
        if _phase_conf >= 0:
            _dim4_str = min(1.0, max(0.0, _phase_conf))
        else:
            _dim4_str = _safe_float(_cf_judg.get('continuous_value'), 0.5)
        # pde_conflict 折减
        _pde_conflict = str(_cf_sd.get('pde_conflict', ''))
        if _pde_conflict in ('true', 'True', '1', 'yes'):
            _dim4_str *= 0.7
            _dim4_evidence.append('pde_conflict→×0.7')
        # L4 提取
        _dim4_extras['pde_price_position'] = str(_cf_sd.get('pde_price_position', ''))
        _dim4_extras['retail_institution'] = str(_cf_sd.get('retail_institution', ''))
        _dim4_extras['pde_vote_ratio'] = str(_cf_sd.get('pde_vote_ratio', ''))
        _dim4_extras['cost_concentration'] = str(_cf_sd.get('cost_concentration', ''))
    else:
        _dim4_str = 0.3

    factors['chip_fund'] = {
        'direction': _dim4_dir,
        'strength': round(_dim4_str, 4),
        'evidence': _dim4_evidence if _dim4_evidence else [],
        **_dim4_extras,
    }

    # ── dim5 emotion ─────────────────────────────────────────────────
    _emo = dim_results.get('emotion')
    _dim5_dir = 0
    _dim5_str = 0.0
    _dim5_evidence: list[str] = []
    _dim5_extras: dict = {}
    # 提取 emotion state（优先引擎status_description.market_phase，降级tags）
    _emo_state_raw = '中性'
    _temperature = 50.0
    if _emo and isinstance(_emo, dict):
        _emo_judg = _emo.get('judgment', {})
        _emo_sd = _emo.get('status_description', {})
        # 优先从status_description.market_phase读取（390方案§3.2 dim5）
        _emo_state_raw = str(_emo_sd.get('market_phase', ''))
        if not _emo_state_raw or _emo_state_raw == 'None':
            _emo_state_raw = tags.get('stock_emotion', tags.get('sentiment_phase', '中性'))
        # 中文键兼容
        _emo_state_cn = ENGINE_STATE_TO_CN.get('emotion', {}).get(_emo_state_raw, _emo_state_raw)
        _dim5_dir = _EMOTION_DIRECTION.get(_emo_state_cn, _EMOTION_DIRECTION.get(_emo_state_raw, 0))
        # temperature
        _temperature = _safe_float(_emo_sd.get('temperature'), 50.0)
        _dim5_str = abs(_temperature - 50.0) / 50.0
        # bociasi fast/slow 共振加成
        _bociasi_fast = str(_emo_sd.get('bociasi_fast_signal', ''))
        _bociasi_slow = str(_emo_sd.get('bociasi_slow_signal', ''))
        _slow_confidence = _safe_float(_emo_sd.get('bociasi_slow_confidence'), 0.5)
        if _bociasi_fast and _bociasi_slow and _bociasi_fast == _bociasi_slow:
            _dim5_str += 0.15
            _dim5_evidence.append(f'bociasi快慢共振={_bociasi_fast}')
        # slow signal 修正
        if _bociasi_slow == 'BEARISH' and _dim5_dir > 0:
            _dim5_str *= 0.6
            _dim5_evidence.append('slow=BEARISH但dir>0→×0.6')
        elif _bociasi_slow == 'BULLISH' and _dim5_dir < 0:
            _dim5_str *= 0.6
            _dim5_evidence.append('slow=BULLISH但dir<0→×0.6')
        elif _bociasi_slow == 'BULLISH' and _dim5_dir > 0:
            _dim5_str += 0.1
            _dim5_evidence.append('slow=BULLISH且dir>0→+0.1')
        # sector_heat 加成（优先从status_description读取）
        _sector_heat = str(_emo_sd.get('sector_heat', tags.get('sector_heat', '')))
        if _sector_heat == 'top_10' and _dim5_dir > 0:
            _dim5_str += 0.05
            _dim5_evidence.append('sector_heat=top_10→+0.05')
        # L2 提取
        _dim5_extras['slow_confidence'] = _slow_confidence
    else:
        # 无引擎输出时从 tags 回退
        _emo_raw = tags.get('stock_emotion', tags.get('sentiment_phase', '中性'))
        _emo_cn = ENGINE_STATE_TO_CN.get('emotion', {}).get(_emo_raw, _emo_raw)
        _dim5_dir = _EMOTION_DIRECTION.get(_emo_cn, _EMOTION_DIRECTION.get(_emo_raw, 0))
        _dim5_str = 0.3

    _dim5_str = _clamp(_dim5_str, 0.0, 1.0)
    factors['emotion'] = {
        'direction': _dim5_dir,
        'strength': round(_dim5_str, 4),
        'evidence': _dim5_evidence if _dim5_evidence else [],
        **_dim5_extras,
    }

    # ── dim6 risk ────────────────────────────────────────────────────
    _risk = dim_results.get('risk')
    _dim6_dir = 0
    _dim6_str = 0.5
    _dim6_evidence: list[str] = []
    _dim6_extras: dict = {}
    if _risk and isinstance(_risk, dict):
        _risk_judg = _risk.get('judgment', {})
        _risk_sd = _risk.get('status_description', {})
        _risk_level = str(_risk_judg.get('level', _risk_judg.get('risk_level', '中')))
        _rr = _safe_float(_risk_sd.get('rr_value', _risk_judg.get('rr', -1.0)), -1.0)
        # direction 规则
        if _risk_level == '低' and _rr >= 1:
            _dim6_dir = 1
        elif _risk_level == '低' and _rr < 1:
            _dim6_dir = 0
        elif _risk_level in ('高', '极高'):
            _dim6_dir = -1
        else:
            _dim6_dir = 0
        # strength
        if _rr > 0:
            _dim6_str = min(1.0, _rr / 3.0)
        else:
            _dim6_str = 0.3
        # atr_pct > 0.8 折减
        _atr_pct = _safe_float(_risk_sd.get('atr_pct'), 0.0)
        if _atr_pct > 0.8:
            _dim6_str *= 0.6
            _dim6_evidence.append(f'atr_pct={_atr_pct:.2f}>0.8→×0.6')
        # L2/L4/L6 提取
        _dim6_extras['volatility_percentile'] = _safe_float(_risk_sd.get('volatility_percentile'), 0.0)
        _dim6_extras['dist_to_support_pct'] = _safe_float(_risk_sd.get('dist_to_support_pct'), 0.0)
        _dim6_extras['dist_to_resistance_pct'] = _safe_float(_risk_sd.get('dist_to_resistance_pct'), 0.0)
    else:
        _dim6_str = 0.3

    _dim6_str = _clamp(_dim6_str, 0.0, 1.0)
    factors['risk'] = {
        'direction': _dim6_dir,
        'strength': round(_dim6_str, 4),
        'evidence': _dim6_evidence if _dim6_evidence else [],
        **_dim6_extras,
    }

    # ── dim7 valuation ───────────────────────────────────────────────
    _val = dim_results.get('valuation')
    _dim7_dir = 0
    _dim7_str = 0.5
    _dim7_evidence: list[str] = []
    _dim7_extras: dict = {}
    if _val and isinstance(_val, dict):
        _val_judg = _val.get('judgment', {})
        _val_sd = _val.get('status_description', {})
        # direction: composite_rating
        _composite = _safe_float(_val_sd.get('composite_rating'), 0.0)
        if _composite >= 0.5:
            _dim7_dir = 1
        elif _composite <= -0.5:
            _dim7_dir = -1
        else:
            _dim7_dir = 0
        _dim7_evidence.append(f'composite_rating={_composite:.2f}')
        # strength: 0.6*cr_strength + 0.4*deviation_norm
        _cr_str = abs(_composite) / 2.0  # 归一化到 [0, 1]
        _cr_str = min(1.0, max(0.0, _cr_str))
        _deviation = _safe_float(_val_sd.get('valuation_deviation', _val_sd.get('deviation')), 0.0)
        _deviation_norm = min(1.0, abs(_deviation) / 2.0)
        _dim7_str = 0.6 * _cr_str + 0.4 * _deviation_norm
        # dividend_yield > 4 加成
        _div_yield = _safe_float(_val_sd.get('dividend_yield'), 0.0)
        if _div_yield > 4:
            _dim7_str += 0.1
            _dim7_evidence.append(f'股息率={_div_yield:.1f}%>4→+0.1')
        # revenue_growth > 20 加成
        _rev_growth = _safe_float(_val_sd.get('revenue_growth'), 0.0)
        if _rev_growth > 20:
            _dim7_str += 0.1
            _dim7_evidence.append(f'营收增速={_rev_growth:.1f}%>20→+0.1')
        # potential_score 加减（数字优先，字符串防御解析）
        _potential = float(_potential_score_int(_val_sd))
        if _potential >= 70:
            _dim7_str += 0.1
            _dim7_evidence.append(f'潜力分={int(_potential)}≥70→+0.1')
        elif _potential <= 30:
            _dim7_str -= 0.1
            _dim7_evidence.append(f'潜力分={int(_potential)}≤30→-0.1')
        # L4 提取
        _dim7_extras['asset_anchor_rating'] = str(_val_sd.get('asset_anchor_rating', ''))
        _dim7_extras['earnings_anchor_rating'] = str(_val_sd.get('earnings_anchor_rating', ''))
    else:
        _dim7_str = 0.3

    _dim7_str = _clamp(_dim7_str, 0.0, 1.0)
    factors['valuation'] = {
        'direction': _dim7_dir,
        'strength': round(_dim7_str, 4),
        'evidence': _dim7_evidence if _dim7_evidence else [],
        **_dim7_extras,
    }

    # ── 辅助维度（time/finance/event/factor/position/signal_confirm）──
    # time: 从emotion.time_rhythm推导
    _time_dir = 0
    _time_str = 0.5
    if _emo and isinstance(_emo, dict):
        _tr = str((_emo.get('status_description') or {}).get('time_rhythm', ''))
        if '变盘' in _tr:
            _time_dir = 1  # 变盘临近→初期看多
        elif '延伸' in _tr:
            _time_dir = -1  # 已延伸→看空
    factors['time'] = {'direction': _time_dir, 'strength': _time_str, 'evidence': []}

    # finance: 从dim7.fina_health推导
    _fin_dir = 0
    _fin_str = 0.5
    if _val and isinstance(_val, dict):
        _fin_val = str((_val.get('judgment') or {}).get('fina_health', {}).get('value', ''))
        if _fin_val == 'pass':
            _fin_dir = 1
        elif _fin_val == 'fail':
            _fin_dir = -1
    factors['finance'] = {'direction': _fin_dir, 'strength': _fin_str, 'evidence': []}

    # event: 从tags.catalyst_event推导
    _evt_dir = 0
    _evt_str = 0.5
    _evt_raw = tags.get('catalyst_event', 'none')
    if _evt_raw in ('breakout',):
        _evt_dir = 1
    elif _evt_raw in ('lhb', 'regulatory', 'fraud_sign'):
        _evt_dir = -1
    factors['event'] = {'direction': _evt_dir, 'strength': _evt_str, 'evidence': []}

    # factor: 从dim7.potential_score推导
    _fac_dir = 0
    _fac_str = 0.5
    if _val and isinstance(_val, dict):
        _val_sd7 = _val.get('status_description') or {}
        if _val_sd7.get('potential_score') is not None or _val_sd7.get('potential_strength') is not None:
            _ps_int = _potential_score_int(_val_sd7)
            if _ps_int >= 70:
                _fac_dir = 1
            elif _ps_int <= 30:
                _fac_dir = -1
            _fac_str = min(1.0, _ps_int / 100.0)
    factors['factor'] = {'direction': _fac_dir, 'strength': round(_fac_str, 4), 'evidence': []}

    # position: 从tags.price_position推导
    _pos_dir = 0
    _pos_str = 0.5
    _pos_raw = tags.get('price_position', '中位')
    _pos_dir = DIM_DIRECTION.get('position', {}).get(
        ENGINE_STATE_TO_CN.get('position', {}).get(_pos_raw, _pos_raw), 0)
    factors['position'] = {'direction': _pos_dir, 'strength': _pos_str, 'evidence': []}

    # 411号Phase 2：signal_confirm由classify_attribute()分析结果生成
    try:
        from app.opportunity_atlas.signal_analyzer import classify_attribute as _classify_attr
        _sc_attr = _classify_attr(dims, tags, {})
        _sc_code = _sc_attr.get('code', 'neutral')
        # ponytail: 使用模块级_SIGNAL_CODE_DIRECTION，避免局部变量遮蔽导致UnboundLocalError
        _rsc_dir = _SIGNAL_CODE_DIRECTION.get(_sc_code, 0)
        _rsc_str = 0.6
        factors['signal_confirm'] = {'direction': _rsc_dir, 'strength': _rsc_str, 'evidence': [_sc_attr.get('detail', '')]}
    except Exception:
        _rsc_dir = 0
        _rsc_str = 0.5
        _rsc_raw = tags.get('right_side_confirm', '未确认')
        if _rsc_raw in ('强确认',):
            _rsc_dir = 1
        elif _rsc_raw in ('否决',):
            _rsc_dir = -1
        factors['signal_confirm'] = {'direction': _rsc_dir, 'strength': _rsc_str, 'evidence': []}

    return factors
