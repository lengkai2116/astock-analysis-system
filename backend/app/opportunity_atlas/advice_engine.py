"""L6 操作建议层 — 390号方案 §8

根据 final_score + dims_factor + l0 + dim_results 计算动态仓位、
止损位、目标位等操作建议。

替代旧 advice_builder.py（322号）和 advice_generator.py。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def compute_advice(
    final_score: float,
    dims_factor: dict,
    l0: dict,
    dim_results: dict,
    ts_code: str,
    entry_price: float = None,
) -> dict:
    """§8.2 动态仓位模型 + §8.3 操作建议输出

    Returns:
        dict: 含 max_position_ratio / hold_only / soft_risks / hard_veto /
              stop_loss_price / target_price / risk_reward_ratio / entry_zone /
              invalidation_conditions / temperature / atr_pct /
              risk_budget_position / final_score / semantic_type /
              consensus_detail / conflict_summary / reliability_summary
    """
    # ── 基础仓位（§8.2 Step 1）──
    if final_score >= 70:
        base = 0.6
    elif final_score >= 55:
        base = 0.4
    elif final_score >= 30:
        base = 0.1
    else:
        base = 0.0

    # ── L0软风险系数连乘（§8.2 Step 2）──
    position = base * l0.get('position_coeff', 1.0)

    # ── 情绪阶段上限（§8.2 Step 3）──
    emotion_cap = l0.get('emotion_position_cap')
    if emotion_cap is not None:
        position = min(position, emotion_cap)

    # ── 风险预算约束（§8.2 Step 4）──
    risk_budget_pos = None
    if dim_results:
        risk_sd = (dim_results.get('risk') or {}).get('status_description') or {}
        _stop_loss = risk_sd.get('support_price')
        _entry = entry_price
        # 若调用方未传入entry_price，尝试从daily_cache获取最新收盘价
        if _entry is None and ts_code:
            try:
                from app.data import DataManager
                _dm = DataManager()
                _latest = _dm.cache.get_latest_daily(ts_code)
                if _latest and 'close' in _latest:
                    _entry = float(_latest['close'])
            except Exception:
                pass
        if _stop_loss and _entry and _entry > _stop_loss:
            _risk_per_share = _entry - _stop_loss
            _max_loss = 1000000.0 * 0.02  # 100万账户，2%规则
            risk_budget_pos = min(0.30, _max_loss / _risk_per_share * _entry / 1000000.0)
            position = min(position, risk_budget_pos)

    # ── 波动率调整（§8.2 Step 5）──
    _atr_pct = 0.0
    if dim_results:
        _atr_pct = _safe_float(
            (dim_results.get('risk') or {}).get('status_description', {}).get('atr_pct', 0.0)
        )
    if _atr_pct > 0.8:
        position *= 0.6

    # ── 盈亏比调整（§8.2 Step 6）──
    _rr = 1.0
    if dim_results:
        _rr = _safe_float(
            (dim_results.get('risk') or {}).get('status_description', {}).get('rr_value', 1.0)
        )
    if _rr > 0:
        position *= min(_rr / 2.0, 1.0)

    # ── 距防守位调整（§8.2 Step 7）──
    risk_factor = dims_factor.get('risk', {})
    _dist_support = -5.0
    if isinstance(risk_factor, dict):
        _dist_support = _safe_float(risk_factor.get('dist_to_support_pct', -5.0))
    if _dist_support > -2:
        position *= 0.6

    # ── 单票上限30%（§8.2 Step 8）──
    position = min(position, 0.30)
    position = max(position, 0.0)

    # ── hold_only覆盖 ──
    hold_only = l0.get('hold_only', False)
    if hold_only:
        position = 0.0

    # ── 组装操作建议（§8.3）──
    advice = {
        'max_position_ratio': round(position, 2),
        'hold_only': hold_only,
        'soft_risks': l0.get('soft_risks', []),
        'hard_veto': l0.get('hard_veto', False),
        'final_score': round(final_score, 1),
        'semantic_type': '',
        'consensus_detail': {},
        'conflict_summary': {},
        'reliability_summary': {},
    }

    # ── 从dim_results提取止损/目标/盈亏比等 ──
    if dim_results:
        risk_sd = (dim_results.get('risk') or {}).get('status_description') or {}
        if risk_sd.get('support_price'):
            advice['stop_loss_price'] = risk_sd['support_price']
        if risk_sd.get('resistance_price'):
            advice['target_price'] = risk_sd['resistance_price']
        if risk_sd.get('rr_value') is not None:
            advice['risk_reward_ratio'] = risk_sd['rr_value']
        if risk_sd.get('invalidation'):
            advice['invalidation_conditions'] = risk_sd['invalidation']
        if risk_sd.get('atr_pct') is not None:
            advice['atr_pct'] = risk_sd['atr_pct']
        emo_sd = (dim_results.get('emotion') or {}).get('status_description') or {}
        if emo_sd.get('temperature') is not None:
            advice['temperature'] = emo_sd['temperature']
        vp_sd = (dim_results.get('volume_price') or {}).get('status_description') or {}
        if vp_sd.get('entry_zone'):
            advice['entry_zone'] = vp_sd['entry_zone']
        # 391号P1: 消费dim3 target_zone（量价引擎精确目标区间）
        if vp_sd.get('target_zone'):
            advice['target_zone'] = vp_sd['target_zone']
        if risk_budget_pos is not None:
            advice['risk_budget_position'] = risk_budget_pos

    return advice


# ── 从 advice_builder.py 迁移的辅助函数（391号方案清理）──

_STATE_CN = {'enter': '可入场', 'light': '可轻仓', 'wait': '等待', 'avoid': '回避'}
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


def _geometric(df) -> dict:
    """几何化指标：距支撑/压力%、盈亏比、信号天数、防守位（K线不足返回空）

    - support_price：近端防守位 = max(MA20, 近20日低点)（2026-08-13 知识库修正：
      60日低点对右侧拉升股过宽，如 301119 现价22.35/止损16.69=-25.3% 不合理；
      知识库《短线风险控制/交易计划制订》止损锚定突破大阳线实体近端结构位，
      《短线高手的交易语言》止损≤1/2止盈即盈亏比≥2。取近端结构位 max(MA20,
      lo20)，距现价不超过 15% 上限）。止损必须低于现价（322号 H3 教训：
      600519 中枢下沿 1367 > 现价 1309 致止损立即触发，近端位高于现价时
      回退 60日低点）。
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
    # 压力位：取高于现价的最近位（364f修复：原逻辑min(hi60,ma60)在ma60<现价时返回低于现价的阻力位）
    ma60 = float(df['close'].tail(60).mean()) if len(df) >= 60 else None
    resistance = hi60
    resistance_candidates = [x for x in [hi60, ma60] if x is not None and x > price]
    if resistance_candidates:
        resistance = min(resistance_candidates)
    ma20 = float(df['close'].tail(20).mean()) if len(df) >= 20 else None
    lo20 = float(df['low'].tail(20).min()) if len(df) >= 20 and 'low' in df.columns else None
    # 近端结构位：MA20 与 近20日低点取高者（更贴近现价的支撑）
    near = None
    if ma20 is not None and lo20 is not None:
        near = max(ma20, lo20)
    elif ma20 is not None:
        near = ma20
    elif lo20 is not None:
        near = lo20
    support = near
    # 止损必须低于现价（H3 教训）：近端位高于现价时回退 60日低点
    if support is not None and price is not None and support >= price:
        support = lo60
    # 止损距离上限 15%：近端结构位过远时压缩（知识库：止损不宜过宽）
    if support is not None and price is not None:
        max_stop_pct = 0.15
        min_support = price * (1 - max_stop_pct)
        if support < min_support:
            support = min_support
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


# ── 从 advice_builder.py 完整迁移（391号方案最终清理）──
import ast as _ast
import json as _json

from app.opportunity_atlas.arbiter import arbitrate


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


def _apply_degradation(state: str, dirs: list[int], sentiment_phase: str = '',
                       df=None) -> tuple:
    """方向冲突降级 + 市场状态过滤（§三：1维反向→仓位减半由调用方处理；≥2维→强制观望）

    dirs: 五维方向（_dim_directions 输出：+1 看多 / -1 看空 / 0 中性）
    sentiment_phase: '高潮期'/'退潮期' 等中文（rotation_state）
    Returns: (state, reason) —— reason 为降级原因（None=未降级），供 state_reason 使用（336号 S1.1）
    """
    n_bear = sum(1 for x in dirs if x < 0)
    sum(1 for x in dirs if x > 0)
    # ≥2 维反向 → 强制观望（L4 tie 先例：分歧降级谨慎）
    if state in ('enter', 'light') and n_bear >= 2:
        return 'wait', '多维度方向冲突（≥2 维反向），建议观望'
    # 市场高潮/退潮期 → 买入类降级（不做重仓；wait 保持）
    if state in ('enter', 'light'):
        _sent = str(sentiment_phase or '')
        if '高潮' in _sent or '退潮' in _sent:
            return 'light', '市场情绪高潮/退潮，仓位压缩'
    return state, None


def apply_soft_risk_position(max_pct: float, soft_risks: list, valuation: str = 'none') -> float:
    """L0b 软风险仓位约束共享函数（336号 S1.3，双模块同路径）

    口径对齐 cross_validate._evaluate_gate 的 soft_risks 系数：
      fina_weak/fina_fail ×0.5、distributing ×0.7、low_liquidity ×0.7、
      估值 moderate ×0.5 / mild ×0.8
    """
    if 'fina_weak' in soft_risks or 'fina_fail' in soft_risks:
        max_pct = round(max_pct * 0.5, 2)
    if 'distributing' in soft_risks:
        max_pct = round(max_pct * 0.7, 2)
    if 'low_liquidity' in soft_risks:
        max_pct = round(max_pct * 0.7, 2)
    if valuation == 'moderate':
        max_pct = round(max_pct * 0.5, 2)
    elif valuation == 'mild':
        max_pct = round(max_pct * 0.8, 2)
    return max_pct


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


def _build_invalidation(state, support, sentiment_phase, rsc, tags=None) -> list[str]:
    """失效条件派生（§3.3：止损位 + 情绪退潮 + 右侧否决 + 330号改进1：接入 exit_conditions）

    330号改进1：读取机会图谱标签 exit_conditions（P4 预计算，按机会类型模板生成
    {desc, check} 列表），将 desc 中文化并入失效条件——原实现只显示"收盘跌破止损位"
    一条，漏掉"跌破MA20且3日未收回/主力出货/估值退出"等真实退出信号。
    """
    conditions = []
    if support is not None:
        conditions.append(f'收盘跌破止损位 {support}')
    if sentiment_phase in ('ebb', 'climax'):
        conditions.append('大盘进入退潮/高潮期，追涨风险大')
    if rsc == '否决':
        conditions.append('右侧确认已转为否决（卖出/背离/预跌信号）')
    # 330号改进1：接入标签库真实退出条件（exit_conditions 是 {desc, check} JSON 列表）
    if tags:
        try:
            ec = tags.get('exit_conditions')
            if ec:
                parsed = _json.loads(ec) if isinstance(ec, str) else ec
                if isinstance(parsed, list):
                    for item in parsed:
                        desc = str(item.get('desc') or '').strip()
                        if desc and desc not in conditions:
                            conditions.append(desc)
        except Exception:
            pass
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
    """目标位派生（330号改进1：真实压力位，消灭 ×1.15 虚构）

    目标1 = 60日高点压力位（上方第一真实压力）；
    目标2 = MA60 若高于目标1 则作为第二压力，否则不返回（避免倒序）。
    仅返回高于现价的真实压力位；无压力位时返回空。
    """
    if df is None or df.empty or 'high' not in df.columns or len(df) < 60:
        return []
    closes = df['close'].values
    price = float(closes[-1])
    hi60 = float(df['high'].tail(60).max())
    ma60 = float(df['close'].tail(60).mean()) if len(df) >= 60 else None
    levels = []
    # 目标1：60日高点（真实压力位，须高于现价）
    if hi60 > price:
        levels.append({'price': round(hi60, 2), 'reason': '60日高点压力位'})
    # 目标2：MA60 真实压力，须高于目标1（防倒序）
    if ma60 and ma60 > price and (not levels or ma60 > levels[0]['price'] + 0.5):
        levels.append({'price': round(ma60, 2), 'reason': 'MA60 压力位'})
    return levels


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
    # confidence：共识率（L1 九维或五维推导）+证据数+冲突数
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
    # invalidation：止损位 + 情绪退潮 + 右侧否决 + exit_conditions（330号改进1）
    _sent = str(dims.get('emotion', {}).get('rotation_state') or '')
    _sent_phase = ('ebb' if '退潮' in _sent else
                   ('climax' if '高潮' in _sent else ''))
    _rsc = str((tags or {}).get('right_side_confirm') or '')
    invalidation = _build_invalidation(state, support, _sent_phase, _rsc, tags=tags)

    return {
        'signal_light': _light_map.get(state, '🟡'),
        'action_label': action_label,
        'target_levels': _build_target_levels(df),
        'expected_holding': _build_expected_holding(tags),
        'invalidation': invalidation,
        'confidence': confidence,
        'evidence_top3': evidence_top3,
    }


def build_operation_advice(ts_code: str, dimensions: dict, signals: list, df,
                           kronos: dict = None, tags: dict = None,
                           consensus: dict = None, dirs: list = None) -> dict:
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
    # L4 共识：优先用外部传入的 L1 九维共识（336号统一口径），否则回退五维推导
    if dirs is None:
        dirs = _dim_directions(dimensions)
    if consensus is None:
        consensus = _consensus_from_dirs(dirs)
    arb = arbitrate(arb_tags, consensus=consensus)
    state = real_state or arb['opportunity_state']
    state_reason = arb['state_evidence'][0] if arb['state_evidence'] else ''

    # ── 323号 S8：映射与降级机制（建议卡 §三）──
    _pre_state = state
    state, _degrade_reason = _apply_degradation(
        state, dirs,
        sentiment_phase=str(dimensions.get('emotion', {}).get('rotation_state') or ''),
        df=df)
    # 盈亏比门禁
    geo = _geometric(df)
    _rr = geo.get('risk_reward')
    if _rr is not None and _rr < 1.0 and state in ('enter', 'light'):
        state = 'wait'
        state_reason = f'盈亏比不足（目标收益/止损风险≈{_rr}，止损过宽），建议观望'
    elif state != _pre_state:
        state_reason = _degrade_reason or '多维度方向冲突/市场情绪过激，建议观望'
    # L0c 持有期限制
    try:
        _asig = (tags or {}).get('active_signal')
        if isinstance(_asig, str) and _asig:
            try:
                _asig = _ast.literal_eval(_asig)
            except Exception:
                try:
                    _asig = _json.loads(_asig)
                except Exception:
                    _asig = None
        if isinstance(_asig, dict) and _asig.get('price'):
            _p0 = float(_asig['price'])
            _last = float(df['close'].iloc[-1]) if (df is not None and not df.empty
                                                    and 'close' in df.columns) else None
            if _p0 > 0 and _last:
                _dist = (_last - _p0) / _p0 * 100
                try:
                    from app.services.status_config import get_signal_registry
                    _reg = get_signal_registry().get('signals', {})
                    _max_ext_pct = 0
                    for _sig_cfg in _reg.values():
                        _ext = (_sig_cfg.get('lifecycle') or {}).get('extended') or {}
                        _pct = _ext.get('dist_pct', 0)
                        if _pct > _max_ext_pct:
                            _max_ext_pct = _pct
                    _ext_threshold = _max_ext_pct * 100 if _max_ext_pct <= 1 else _max_ext_pct
                except Exception:
                    _ext_threshold = 12
                if _dist > _ext_threshold and state in ('enter', 'light'):
                    state = 'wait'
                    state_reason = f'信号已延伸（距突破位+{_dist:.0f}%），只可持有、不新开仓（L0c）'
    except Exception:
        pass
    # 交易机制硬约束
    _hard = _apply_hard_constraints(df, state)
    state = _hard['state']
    if _hard.get('reason'):
        state_reason = _hard['reason']

    # 七维红绿灯
    vp = dimensions.get('volume_price') or {}
    chip = dimensions.get('chip') or {}
    emo = dimensions.get('emotion') or {}
    chan = dimensions.get('chanlun') or {}
    # 几何指标
    support = geo.get('support_price')
    resistance = geo.get('resistance_price')
    price = float(df['close'].iloc[-1]) if (df is not None and not df.empty
                                            and 'close' in df.columns) else None
    trend_up = _dir_is_bullish(trend)
    above_support = (support is not None and price is not None and price > support)
    below_support = (support is not None and price is not None and price < support)
    # 信号证据与红绿灯一致
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
            'evidence': (f"防守位{support} / 压力{resistance if resistance and price and resistance > price else (df['high'].tail(60).max() if df is not None and not df.empty and len(df) >= 60 and 'high' in df.columns else resistance)}"
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
    # ── S4：Kronos 可选修正 ──
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
        for k in base:
            base[k] = max(0.0, base[k])
    # 情景注入真实价位
    _res_eff = resistance if (resistance and price and resistance > price) else (
        (df['high'].tail(60).max() if df is not None and not df.empty and len(df) >= 60 and 'high' in df.columns else None))
    _sup_eff = support if (support and price and support < price) else None
    _sup_s = f'{_sup_eff:.2f}' if _sup_eff else '支撑位'
    _res_s = f'{_res_eff:.2f}' if _res_eff else '压力位'
    _price_s = f'{price:.2f}' if price else '现价'
    scenarios = _normalize_scenarios([
        {'id': 'a', 'name': '趋势延续', 'prob': base['a'],
         'steps': [f'回踩 {_sup_s} 不破可加仓（现价 {_price_s}）',
                   f'放量站稳 {_res_s} 追进']},
        {'id': 'b', 'name': '冲高回落', 'prob': base['b'],
         'steps': [f'反弹至 {_res_s} 附近减仓',
                   '主力资金转流出则不开新仓']},
        {'id': 'c', 'name': '破位下行', 'prob': base['c'],
         'steps': [f'跌破 {_sup_s} 立即止损',
                   '等待次级别底背驰出现后再入场']},
    ])

    # 机器可执行
    enter_like = state in ('enter', 'light')
    action_type = 'BUY' if enter_like else ('HOLD' if state == 'wait' else 'SELL')
    max_pct = 0.6 if enter_like else (0.2 if state == 'wait' else 0.0)
    _n_bear = sum(1 for x in dirs if x < 0)
    if state in ('enter', 'light') and _n_bear == 1:
        max_pct = min(max_pct, 0.3)
    try:
        _soft_risks: list = []
        if (tags or {}).get('fina_health') == 'fail':
            _soft_risks.append('fina_fail')
        if (tags or {}).get('catalyst_event') == 'fraud_sign':
            _soft_risks.append('fina_weak')
        if (tags or {}).get('main_force_phase') == 'distributing':
            _soft_risks.append('distributing')
        _vl = (tags or {}).get('valuation_level', '')
        _val_lv = 'moderate' if _vl in ('high', 'extreme_high') else ('mild' if _vl == 'fair' else 'none')
        max_pct = apply_soft_risk_position(max_pct, _soft_risks, _val_lv)
    except Exception:
        pass
    executable = {
        'action_type': action_type,
        'entry_rules': ([{'trigger': f'close <= {price}', 'action': 'BUY', 'size_pct': 30}]
                        if price and state != 'avoid' else []),
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
    result.update(_build_advice_card_fields(
        state, tags, dimensions, geo, support, signal_light, executable, df, dims,
        consensus_rate=consensus['consensus_rate']))
    result['action'] = {'max_position_ratio': executable['position']['max_pct']}
    if kronos and kronos.get('direction'):
        result['kronos_note'] = '🔬 Kronos AI 模型预测，仅供参考，非实证结论'
    return result
