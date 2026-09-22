"""第6维 风险边界引擎

358号方案 v4.1：第6维风险边界维度引擎。

整合源：
  - risk_boundary_builder.py（382行）：风险等级5级 + 波动率 + 盈亏比 + 失效条件
  - advice_engine._geometric()：支撑位/阻力位/盈亏比/ATR%/信号天数
  - event_monitor.py（925行）中的关键事件风险检测

统一接口：evaluate(dims, tags, signals, lifecycle) → {status_description, judgment, audit}
"""

from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# === DataAwareMixin (app/data/mixins.py) ===

from app.data.mixins import DataAwareMixin

# ═══════════════════════════════════════════════════════════
# 风险等级常量
# ═══════════════════════════════════════════════════════════

RISK_LEVEL_LIGHT = {
    '极低': 'green', '低': 'green', '中': 'yellow',
    '高': 'red', '极高': 'red',
}

EVENT_RISK_SET = {'fraud_sign', 'regulatory', 'delist_risk', 'goodwill_risk', 'st_warning'}

# 453号 st_warning 分档：*ST/退市整理（direction<=-2）同退市风险升「极高」（SIG 供 JUD 硬否决），
# 普通 ST（direction=-1）作「高」事件风险源。检测器在 event_monitor._detect_st_warning（C3）。
ST_WARNING_EVENT = 'st_warning'
ST_WARNING_EXTREME_DIR = -2  # *ST / 退市整理


# ═══════════════════════════════════════════════════════════
# 几何化指标（从 advice_engine._geometric() 完整迁移）
# ═══════════════════════════════════════════════════════════

def calc_geometric(df: pd.DataFrame) -> dict:
    """几何化指标：支撑/阻力位、盈亏比、信号天数、防守位

    461-11：统一到 shared.calc_support_resistance（唯一 SSOT），本函数为兼容委托层，
             补 dist_to_prev_high_pct（shared 已并入）；输出键契约保持不变。
    """
    from app.opportunity_atlas.dimensions.shared_support_resistance import calc_support_resistance
    geo = calc_support_resistance(df)
    return {k: geo.get(k) for k in (
        'support_price', 'resistance_price', 'dist_to_support_pct',
        'dist_to_resistance_pct', 'risk_reward', 'signal_days',
        'dist_to_prev_high_pct')}


# ═══════════════════════════════════════════════════════════
# 波动率计算
# ═══════════════════════════════════════════════════════════

def _calc_volatility(df=None, tags: dict = None) -> dict:
    tags = tags or {}
    level = str(tags.get('volatility_level', 'medium'))
    atr_14d = 0.0
    atr_pct = 0.0
    percentile = 0.5

    if df is not None and not df.empty and len(df) >= 20:
        try:
            close = df['close'].astype(float)
            high = df['high'].astype(float)
            low = df['low'].astype(float)
            tr = pd.concat([high - low, (high - close.shift(1)).abs(),
                           (low - close.shift(1)).abs()], axis=1).max(axis=1)
            atr_14d = tr.rolling(14).mean().iloc[-1] if len(tr) >= 14 else tr.mean()
            current_price = close.iloc[-1]
            atr_pct = (atr_14d / current_price * 100) if current_price > 0 else 0
            returns = close.pct_change().dropna()
            if len(returns) >= 20:
                # 461-4：档位判据与框架 `volume_price_strategy:4177` 逐字对齐——
                # 未年化 20 日滚动 std × 100（high>4 / medium>2 / low）。原实现算出场率
                # atr_pct/percentile 却依赖外部 tags 判档（空 tags → 恒 medium，见 460 P2）。
                vol20 = returns.rolling(20).std().iloc[-1]
                if pd.notna(vol20):
                    _vp = float(vol20) * 100.0
                    level = 'high' if _vp > 4.0 else ('medium' if _vp > 2.0 else 'low')
                # 历史分位仍用年化波动率（rank 不受 ×sqrt(252) 常数影响）
                vol_20d = returns.rolling(20).std() * math.sqrt(252)
                vol_20d = vol_20d.dropna()
                if len(vol_20d) >= 2:
                    current_vol = vol_20d.iloc[-1]
                    percentile = float((vol_20d < current_vol).sum() / len(vol_20d))
        except Exception as e:
            logger.debug("403号Q-01 _calc_volatility 计算异常: %s", e)

    return {'level': level, 'atr_14d': atr_14d, 'atr_pct': atr_pct,
            'percentile': percentile}


# ═══════════════════════════════════════════════════════════
# 风险等级评估（从 risk_boundary_builder 迁移）
# ═══════════════════════════════════════════════════════════

# 452号 流动性口径（445 §6.3 dim6 偏差）：
# KB 权威《量化财务门槛/风险剔除逻辑体系》流动性门槛 = 日均成交额>5000万 + 流通市值>30亿。
# 原实现用「换手率<1%」当流动性风险源，口径不符（换手率低≠成交枯竭，蓝筹也可低换手）。
# 单位（332号 P0 教训）：daily_df.amount 为千元，daily_basic.circ_mv 为万元。
_LIQUIDITY_MIN_AVG_AMOUNT_WAN = 5000.0   # 日均成交额 5000 万元
_LIQUIDITY_MIN_CIRC_MV_WAN = 300000.0   # 流通市值 30 亿元 = 30*10000 万元


def _assess_liquidity(df=None, basic_df=None, tags: dict = None) -> dict:
    """流动性风险判定（KB 双门槛：日均成交额<5000万 或 流通市值<30亿 → 触发）

    数据不足任一来源时默认不触发（保守，对齐 443「无数据不惩罚」；不误伤正常股）。
    Returns: {'triggered': bool, 'avg_amount_wan': float|None, 'circ_mv_wan': float|None, 'detail': str}
    """
    tags = tags or {}
    avg_amount_wan = None
    circ_mv_wan = None
    triggered = False
    reasons = []

    # 1) 日均成交额（daily_df.amount，单位千元 → 万元 = /10）
    if df is not None and not df.empty and 'amount' in df.columns:
        try:
            amt = df['amount'].astype(float).dropna()
            if not amt.empty:
                avg = float(amt.tail(20).mean())  # 千元
                avg_amount_wan = round(avg / 10.0, 1)  # 万元
                if avg_amount_wan < _LIQUIDITY_MIN_AVG_AMOUNT_WAN:
                    reasons.append(f'日均成交额{avg_amount_wan:.0f}万<5000万')
        except Exception:
            pass

    # 2) 流通市值（daily_basic.circ_mv，单位：万元）
    if basic_df is not None and hasattr(basic_df, 'columns') and 'circ_mv' in basic_df.columns:
        try:
            cm = basic_df['circ_mv'].astype(float).dropna()
            if not cm.empty:
                circ_mv_wan = float(cm.iloc[-1])
                if circ_mv_wan < _LIQUIDITY_MIN_CIRC_MV_WAN:
                    reasons.append(f'流通市值{circ_mv_wan/10000:.1f}亿<30亿')
        except Exception:
            pass

    if reasons:
        triggered = True
    return {
        'triggered': triggered,
        'avg_amount_wan': avg_amount_wan,
        'circ_mv_wan': circ_mv_wan,
        'detail': '；'.join(reasons) if reasons else '流动性达标',
    }


def _assess_risk_level(tags: dict, liquidity_info: dict = None) -> dict:
    """风险等级评估（T42修复：消除dims循环依赖，仅依赖tags）"""
    risk_sources = []
    high_count = 0

    # T42修复：移除对dims['risk']的读取（循环依赖）
    # dims['risk']由StatusEngine从dim6输出生成，读取它会形成循环
    # 原代码：dim_risk = str(dims.get('risk', {}).get('state', ''))

    rl = str(tags.get('risk_level', ''))
    if rl == 'HIGH':
        high_count += 1
    risk_sources.append({'name': '缠论风险', 'level': '高' if rl == 'HIGH' else '低'})

    fh = str(tags.get('fina_health', ''))
    if fh == 'fail':
        high_count += 1
    risk_sources.append({'name': '财务风险', 'level': '高' if fh == 'fail' else '低'})

    ce = str(tags.get('catalyst_event', ''))
    if ce in EVENT_RISK_SET:
        high_count += 1
    risk_sources.append({'name': '事件风险', 'level': '高' if ce in EVENT_RISK_SET else '低'})

    mfp = str(tags.get('main_force_phase', ''))
    if mfp == 'distributing':
        high_count += 1
    risk_sources.append({'name': '主力风险', 'level': '高' if mfp == 'distributing' else '低'})

    # 452号 波动率从风险源摘除：KB《风险定义（纳兰达版）》「波动是机会而非风险」——
    # 高波动不再计入 high_count，ATR 分位仅作参考信息输出（见 status_description.volatility_*）。
    # 452号 流动性改 KB 双门槛（成交额<5000万 / 流通市值<30亿），由 evaluate 预计算 liquidity_info 传入。
    liq_high = bool(liquidity_info and liquidity_info.get('triggered'))
    if liq_high:
        high_count += 1
    risk_sources.append({'name': '流动性风险', 'level': '高' if liq_high else '低'})

    # L0 硬否决由 StatusEngine 统一处置（l0 在 dim 引擎之后由 _apply_l0 生成，T42 时序），本引擎不参与
    if high_count >= 2:
        level, light = '高', 'red'
    elif high_count == 1:
        level, light = '中', 'yellow'
    else:
        level, light = '低', 'green'

    return {'level': level, 'light': light, 'detail': f'{high_count}个高风险源' if high_count else '无高风险源',
            'risk_sources': risk_sources}


def _list_risk_factors(tags: dict, liquidity_info: dict = None) -> list[dict]:
    """风险因素枚举（T45修复：与_assess_risk_level风险源完全对齐）"""
    factors = []

    # 与_assess_risk_level完全对齐的风险源
    rl = str(tags.get('risk_level', ''))
    if rl == 'HIGH':
        factors.append({'category': '缠论', 'factor': '缠论风险高', 'severity': '高', 'satisfied': True})

    fh = str(tags.get('fina_health', ''))
    if fh == 'fail':
        factors.append({'category': '财务', 'factor': '财务异常', 'severity': '高', 'satisfied': True})
    elif fh == 'suspicious':
        factors.append({'category': '财务', 'factor': '财务关注', 'severity': '中', 'satisfied': True})

    ce = str(tags.get('catalyst_event', ''))
    # 471号 去重：catalyst 命中事件时的事件因子不再在此产出，
    # 改由 evaluate 的 event_risks 统一装配（含 448 PIERS severity 升极高 + 事件因子去重 + 分档），
    # 否则产生「事件:造假信号(高)」与「事件风险:fraud_sign(极高)」同源双条（探针实证）。

    mfp = str(tags.get('main_force_phase', ''))
    if mfp == 'distributing':
        factors.append({'category': '主力', 'factor': '主力出货', 'severity': '中', 'satisfied': True})

    # 452号 波动率不再作为风险因子（KB《风险定义（纳兰达版）》：波动是机会而非风险）
    # 452号 流动性改 KB 双门槛（成交额<5000万 / 流通市值<30亿），由 evaluate 预计算 liquidity_info 传入
    if liquidity_info and liquidity_info.get('triggered'):
        factors.append({'category': '流动性', 'factor': f"流动性不足（{liquidity_info['detail']}）",
                        'severity': '高', 'satisfied': True})

    # L0 硬否决由 StatusEngine 统一处置（见 _assess_risk_level），本引擎不参与

    # 补充风险源（_assess_risk_level未覆盖但有判定价值）
    vl2 = str(tags.get('valuation_level', ''))
    if vl2 in ('high', 'extreme_high'):
        factors.append({'category': '估值', 'factor': '估值过高', 'severity': '中', 'satisfied': True})

    try:
        pr = float(tags.get('profit_ratio', 0))
        if pr >= 0.8:
            factors.append({'category': '获利盘', 'factor': '获利盘过高', 'severity': '中', 'satisfied': True})
    except (TypeError, ValueError):
        pass

    if not factors:
        factors.append({'category': '综合', 'factor': '无显著风险', 'severity': '无', 'satisfied': True})

    return factors


# ── PIERS 硬性否决事件（448号）：event_details.event_type 命中即应升 L0a 硬否决（JUD 侧 _apply_l0 处置）
# SIG 侧只产「触发条件」，不下否决判定（SIG/JUD 边界共识）
PIERS_HARD_EVENTS = ('fraud_sign', 'delist_risk')


def _assess_piers_leverage(tags: dict, dm=None, ts_code: str = '') -> dict:
    """PIERS-E 高杠杆维度评估（SIG 现状条件，非否决）

    数据基础（445/448 核查）：debt_to_assets/roce 已落库（fina_indicator_cache），
    dim7/dim4 已消费。对齐《PIERS框架.md》E 高杠杆「资产负债率过高 + 现金流不足」。

    读取优先级：tags 预计算 valuation_ext → 回退独立查询 fina_indicator。
    """
    result = {'triggered': False, 'factors': [], 'metrics': {}}
    debt_to_assets = tags.get('debt_to_assets')
    roce = tags.get('roce')
    if debt_to_assets is None and roce is None and dm is not None and ts_code:
        try:
            dfi = dm.get_cached_fina_indicator(ts_code)
            if dfi is not None and not dfi.empty:
                latest = dfi.iloc[-1]
                debt_to_assets = latest.get('debt_to_assets')
                roce = latest.get('roce')
        except Exception:
            pass
    try:
        dta = float(debt_to_assets) if debt_to_assets is not None else None
    except (TypeError, ValueError):
        dta = None
    try:
        rce = float(roce) if roce is not None else None
    except (TypeError, ValueError):
        rce = None
    result['metrics'] = {'debt_to_assets': dta, 'roce': rce}
    if dta is not None and dta > 70:
        result['triggered'] = True
        result['factors'].append({'category': 'PIERS-E', 'factor': f'高杠杆（资产负债率{dta:.0f}%>70%）',
                                  'severity': '中', 'satisfied': True})
    if rce is not None and rce < 15:
        result['triggered'] = True
        result['factors'].append({'category': 'PIERS-E', 'factor': f'资本回报率偏低（ROCE {rce:.1f}%<15%）',
                                  'severity': '中', 'satisfied': True})
    return result


def _assess_rr(geo: dict) -> dict:
    rr = geo.get('risk_reward')
    if rr is None:
        return {'rr_value': None, 'rr_level': '未知', 'rr_assessment': '盈亏比数据不足', 'light': 'yellow'}
    if rr < 1.0:
        return {'rr_value': rr, 'rr_level': '不值得交易', 'rr_assessment': f'盈亏比{rr:.2f}<1R', 'light': 'red'}
    if rr < 2.0:
        return {'rr_value': rr, 'rr_level': '可考虑', 'rr_assessment': f'盈亏比{rr:.2f}（1R-2R）', 'light': 'yellow'}
    if rr < 3.0:
        return {'rr_value': rr, 'rr_level': '较好', 'rr_assessment': f'盈亏比{rr:.2f}（2R-3R）', 'light': 'green'}
    return {'rr_value': rr, 'rr_level': '优质', 'rr_assessment': f'盈亏比{rr:.2f}（>3R）', 'light': 'green'}


def _build_invalidation(support, tags) -> list[dict]:
    conditions = []
    if support is not None:
        conditions.append({'source': '防守位', 'condition': f'收盘跌破{support}元', 'priority': 1})
    sp = str(tags.get('sentiment_phase', ''))
    if sp in ('ebb', 'climax'):
        conditions.append({'source': '情绪', 'condition': '大盘进入退潮/高潮期', 'priority': 2})
    # 404号DATA-03: right_side_confirm在pre_feat_cache管道中只产出strong_confirm/unconfirmed，
    # '否决'值仅由_check_right_side_confirm()在treemap快照管道中产出，此处为死代码（已知限制）
    if str(tags.get('right_side_confirm', '')) == '否决':
        conditions.append({'source': '右侧', 'condition': '右侧确认转否决', 'priority': 3})
    return conditions


class Dim6RiskEngine(DataAwareMixin):
    """第6维 风险边界引擎 — 风险分级 + 几何化距离 + 波动率 + 事件监控"""

    def __init__(self):
        self._dm = None

    def evaluate(self, dims: dict, tags: dict, signals: dict = None,
                 lifecycle: dict = None, data_context: dict = None) -> dict:
        """统一评估入口

        411号Phase 6：优先使用data_context预加载数据，回退独立查询。
        """
        ts_code = tags.get('ts_code', '')

        # 411号Phase 6：优先使用data_context
        if data_context and 'daily_df' in data_context:
            df = data_context['daily_df']
        else:
            ecm = self._get_dm().cache
            try:
                df = ecm.get_cached_daily(ts_code)
            except Exception:
                df = None

        # 452号 流动性（KB 双门槛：日均成交额<5000万 或 流通市值<30亿）
        # 数据来源：daily_df.amount（千元）+ daily_basic.circ_mv（万元，dim1 预加载 daily_basic_df）。
        basic_df = (data_context or {}).get('daily_basic_df')
        _liquidity = _assess_liquidity(df, basic_df, tags)

        # 1. 风险等级
        risk_info = _assess_risk_level(tags, liquidity_info=_liquidity)
        risk_factors = _list_risk_factors(tags, liquidity_info=_liquidity)

        # 1b. 事件风险检测（405号建议2: 从pre_feat_cache读取RAW-2预计算的事件标签）
        event_risks = []
        event_results = []
        try:
            event_details = tags.get('event_details', [])
            event_risk_factors_from_tags = tags.get('event_risk_factors', [])
            event_results = event_details if isinstance(event_details, list) else []
            if event_risk_factors_from_tags:
                event_risks.extend(event_risk_factors_from_tags)
            ce = str(tags.get('catalyst_event', ''))
            if ce in EVENT_RISK_SET:
                already = any(r.get('factor') == ce for r in event_risks)
                if not already:
                    event_risks.append({'category': '事件风险', 'factor': ce,
                                        'severity': '高', 'satisfied': True})
            # 448号 PIERS 硬性否决事件：severity 升「极高」（消除 audit「无高风险事件」恒真 + 供 JUD 判定）
            for ev in event_results:
                if isinstance(ev, dict) and str(ev.get('event_type', '')) in PIERS_HARD_EVENTS:
                    already = any(r.get('factor') == str(ev.get('event_type')) for r in event_risks)
                    if not already:
                        event_risks.append({'category': '事件风险', 'factor': str(ev.get('event_type')),
                                            'severity': '极高', 'satisfied': True})
                    else:
                        for r in event_risks:
                            if r.get('factor') == str(ev.get('event_type')):
                                r['severity'] = '极高'
            # 453号 st_warning 分档：*ST/退市整理（direction<=-2）→ 「极高」（供 JUD 硬否决），
            # 普通 ST（direction=-1）→ 「高」（事件风险源）。同 448 直读 event_details，不依赖 catalyst_event 单值。
            for ev in event_results:
                if not (isinstance(ev, dict) and str(ev.get('event_type', '')) == ST_WARNING_EVENT):
                    continue
                _sev = '极高' if int(ev.get('direction', 0)) <= ST_WARNING_EXTREME_DIR else '高'
                _st = next((r for r in event_risks if r.get('factor') == 'ST预警'), None)
                if _st is None:
                    event_risks.append({'category': '事件风险', 'factor': 'ST预警',
                                        'severity': _sev, 'satisfied': True})
                elif _sev == '极高' and _st.get('severity') != '极高':
                    _st['severity'] = '极高'  # 只升不降
            # 459号：升格口径与审计「无高风险事件」同源——仅当存在「高」严重度事件才升「高」，
            # 中档事件（财务关注/估值过高/主力出货等 severity='中'）不再误顶高风险（444-C1 残余）。
            _high_evt = any(r.get('severity') in ('高', '极高') for r in event_risks)
            if _high_evt and risk_info['level'] not in ('高', '极高'):
                risk_info = {'level': '高', 'light': 'red',
                             'detail': f"事件风险：{event_risks[0]['factor']}"}
            if any(r.get('severity') == '极高' for r in event_risks) and risk_info['level'] != '极高':
                risk_info = {'level': '极高', 'light': 'red', 'detail': '存在 PIERS 硬性否决事件（造假/退市/ST退市）'}
        except Exception as e:
            logger.debug("403号Q-05 EventMonitor检测跳过: %s", e)

        # 471号：事件因子装配完成后 extend。若本股实际存在事件风险，
        # 移除 _list_risk_factors 的空兜底「综合：无显著风险」，避免与真实事件因子并存自相矛盾
        if event_risks:
            risk_factors = [f for f in risk_factors
                            if not (f.get('category') == '综合' and f.get('factor') == '无显著风险')]
        risk_factors.extend(event_risks)

        # 1c. PIERS-E 高杠杆维度（448号；SIG 现状条件，非否决）
        _leverage = _assess_piers_leverage(tags, self._get_dm(), ts_code)
        if _leverage['triggered']:
            risk_factors.extend(_leverage['factors'])

        # 2. 几何化指标
        # 411号Phase 9：优先从tags读取预计算risk_ext，回退raw计算
        _geo_precomputed = all(tags.get(k) is not None for k in ('support_price', 'resistance_price', 'risk_reward'))
        if _geo_precomputed:
            geo = {
                'support_price': tags.get('support_price'),
                'resistance_price': tags.get('resistance_price'),
                'dist_to_support_pct': tags.get('dist_to_support_pct'),
                'dist_to_resistance_pct': tags.get('dist_to_resistance_pct'),
                'risk_reward': tags.get('risk_reward'),
                'signal_days': tags.get('signal_days'),
                'dist_to_prev_high_pct': tags.get('dist_to_prev_high_pct'),
            }
        else:
            geo = calc_geometric(df) if df is not None and not df.empty else {
                'dist_to_support_pct': None, 'dist_to_resistance_pct': None,
                'risk_reward': None, 'signal_days': None, 'support_price': None, 'resistance_price': None,
            }

        # 3. 盈亏比
        rr_info = _assess_rr(geo)

        # 4. 波动率
        # 411号Phase 9：优先从tags读取预计算波动率，回退raw计算
        _vol_precomputed = tags.get('atr_14d') is not None
        if _vol_precomputed:
            vol_info = {
                'atr_14d': float(tags.get('atr_14d', 0)),
                'atr_pct': float(tags.get('atr_pct', 0)),
                'level': str(tags.get('volatility_level', 'unknown')),
                'percentile': float(tags.get('volatility_percentile', 0.5)),
            }
        else:
            vol_info = _calc_volatility(df, tags)

        # 5. 失效条件
        invalidation = _build_invalidation(geo.get('support_price'), tags)

        # 6. status_description
        risk_evidence_parts = []
        risk_evidence_parts.append(f"风险等级={risk_info['level']}({risk_info['detail']})")
        if geo.get('support_price'):
            risk_evidence_parts.append(f"防守位={geo['support_price']}元(距{geo.get('dist_to_support_pct', '无')}%)")
        if geo.get('resistance_price'):
            risk_evidence_parts.append(f"压力位={geo['resistance_price']}元(距{geo.get('dist_to_resistance_pct', '无')}%)")
        if rr_info.get('rr_value'):
            risk_evidence_parts.append(f"盈亏比={rr_info['rr_value']}({rr_info['rr_level']})")
        risk_evidence_parts.append(f"波动率={vol_info['level']}(ATR={vol_info['atr_14d']:.2f},分位{vol_info['percentile']:.0%})" if vol_info['atr_14d'] > 0 else f"波动率={vol_info['level']}")
        active_factors = [f for f in risk_factors if f.get('satisfied') and f.get('severity') in ('高', '极高')]
        if active_factors:
            risk_evidence_parts.append(f"高风险因素={'+'.join(f['factor'] for f in active_factors)}")
        if event_results:
            event_descs = [e.get('description', '') for e in event_results[:3] if e.get('description')]
            if event_descs:
                risk_evidence_parts.append(f"事件={'; '.join(event_descs)}")
        risk_evidence = '；'.join(risk_evidence_parts)

        event_details_out = []
        for ev in event_results[:5]:
            event_details_out.append({
                'event_type': ev.get('event_type', ''),
                'description': ev.get('description', ''),
                'direction': ev.get('direction', 0),
                'confidence': ev.get('confidence', 0),
                'event_date': ev.get('event_date', ''),
            })

        status_description = {
            'risk_level': risk_info['level'],
            'risk_detail': risk_info['detail'],
            'risk_light': risk_info['light'],
            'risk_factors': [f"{f['category']}：{f['factor']}（{f['severity']}）"
                             for f in risk_factors if f.get('satisfied')],
            'piers_leverage': {k: v for k, v in _leverage['metrics'].items() if v is not None} if _leverage['triggered'] else {},
            'support_price': geo.get('support_price'),
            'resistance_price': geo.get('resistance_price'),
            'dist_to_support_pct': geo.get('dist_to_support_pct'),
            'dist_to_resistance_pct': geo.get('dist_to_resistance_pct'),
            'dist_to_prev_high_pct': geo.get('dist_to_prev_high_pct'),
            'rr_value': rr_info.get('rr_value'),
            'rr_level': rr_info['rr_level'],
            'rr_assessment': rr_info['rr_assessment'],
            'volatility_level': vol_info['level'],
            'atr_14d': vol_info['atr_14d'],
            'atr_pct': vol_info['atr_pct'],
            'volatility_percentile': vol_info['percentile'],
            'liquidity_risk': _liquidity.get('triggered', False),
            'liquidity_detail': _liquidity.get('detail', '流动性达标'),
            'liquidity_avg_amount_wan': _liquidity.get('avg_amount_wan'),
            'liquidity_circ_mv_wan': _liquidity.get('circ_mv_wan'),
            'signal_days': geo.get('signal_days'),
            'invalidation': [item['condition'] for item in invalidation],
            'event_count': len(event_results),
            'event_details': event_details_out,
            'event_summary': [e.get('description', '') for e in event_results[:5] if e.get('description')],
            'risk_evidence': risk_evidence,
            'support_resistance': f"防守位{geo.get('support_price', '无')}元（距现价{geo.get('dist_to_support_pct', '无')}），压力位{geo.get('resistance_price', '无')}元（距现价{geo.get('dist_to_resistance_pct', '无')}）",
        }

        judgment = {
            'level': risk_info['level'],
            'risk_level': risk_info['level'],
            'light': risk_info['light'],
            'overall_light': risk_info['light'],
            'overall_direction': -1 if risk_info['level'] in ('高', '极高') else (1 if risk_info['level'] in ('低',) else 0),
            'continuous_value': round(min(rr_info.get('rr_value', 0) / 3.0, 1.0), 4) if rr_info.get('rr_value') else 0.5,
        }

        conditions = [
            {'name': '风险等级', 'satisfied': risk_info['level'] in ('低', '中'),
             'actual': risk_info['level'], 'threshold': '低或中'},
            {'name': '盈亏比', 'satisfied': rr_info.get('rr_value', 0) >= 2.0 if rr_info.get('rr_value') else False,
             'actual': f"{rr_info.get('rr_value', '无')}" if rr_info.get('rr_value') else '数据不足',
             'threshold': '≥2R'},
            {'name': '流动性', 'satisfied': not _liquidity.get('triggered', False),
             'actual': _liquidity.get('detail', '数据不足'), 'threshold': '日均成交额>5000万且流通市值>30亿'},
            {'name': '无高风险事件', 'satisfied': not any(f.get('severity') in ('极高',) for f in risk_factors),
             'actual': str([f['factor'] for f in risk_factors if f.get('severity') == '极高']),
             'threshold': '无极高风险'},
            {'name': '防守位有效', 'satisfied': geo.get('support_price') is not None,
             'actual': str(geo.get('support_price', '无')), 'threshold': '有防守位'},
        ]
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
            'daily_cache (market_cache.db) — OHLCV用于几何化指标和波动率',
            'tags (pre_feat_cache) — risk_level / volatility_level / fina_health / catalyst_event / main_force_phase / valuation_level / turnover_rate',
        ]
