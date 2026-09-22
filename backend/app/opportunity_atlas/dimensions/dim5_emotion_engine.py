"""第5维 情绪环境引擎

358号方案 v4.1：第5维情绪环境维度引擎。

整合源：
  - emotion_builder.py（182行）：三层面输出（市场/板块/个股）+ 条件稽核
  - bociasi_quickline.py / bociasi_slowline.py：BOCIASI快慢线（470号 A1 已内嵌 + framework 双类死代码清理）
  - bociasi_quadrant.py（347行）：四象限市场情绪判定
  - emotion_temperature.py（103行）：情绪温度0-100
  - sector_rotation_model.py（144行）：板块热度 top_10/top_20/normal/none
  - time_rhythm_engine.py（103行）：时间节奏 BOLL带宽+中枢横盘

统一接口：evaluate(dims, tags, signals, lifecycle) → {status_description, judgment, audit}
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from app.data.mixins import DataAwareMixin
from app.engine.framework.bociasi_quadrant import BociasiQuadrantAnalyzer
# 447号 T5：温度唯一代码源（emotion_temperature.py，SSOT），dim5 不再内嵌副本
from app.opportunity_atlas.emotion_temperature import calc_emotion_temperature
from app.opportunity_atlas.dimensions.enum_cn_map import bociasi_signal_cn, quadrant_cn

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# BOCIASI快线常量
# ═══════════════════════════════════════════════════════════

# 431号 G1 标注（批次13，2026-09-13）——本文件"硬编码常量未收敛"清单：
#   FAST_HIGH/LOW_THRESHOLD、SLOW_HIGH/LOW_THRESHOLD（BOCIASI 快慢线阈值）
#   PHASE_BASE_TEMP、TEMP_WEIGHTS（情绪温度基温与分项权重）
#   BANDWIDTH_TIGHT/NARROW、RANGE_TIGHT、CONSOLIDATION_MIN_DAYS（时间节奏阈值）
# 以上均**无 status_engine.yaml / signal_registry.yaml 对应物**（属引擎内部算法
# 常量，非台账配置），故本批**仅标注，不收敛**——收敛＝另行设计配置键，属行为变更。
FAST_HIGH_THRESHOLD = 0.70
FAST_LOW_THRESHOLD = 0.30
SLOW_HIGH_THRESHOLD = 0.70
SLOW_LOW_THRESHOLD = 0.30


# ═══════════════════════════════════════════════════════════
# 情绪温度常量
# ═══════════════════════════════════════════════════════════

PHASE_BASE_TEMP = {
    'ice': 10, 'sprout': 30, 'regression': 40, 'ferment': 60,
    'climax': 85, 'ebb': 25, 'neutral': 50,
}

TEMP_WEIGHTS = {
    'market_phase': 0.25, 'limit_up': 0.15, 'blast_rate': 0.10,
    'sector_heat': 0.15, 'volume_price': 0.15, 'margin': 0.10, 'breadth': 0.10,
}


# ═══════════════════════════════════════════════════════════
# 时间节奏常量
# ═══════════════════════════════════════════════════════════

BANDWIDTH_TIGHT = 5
BANDWIDTH_NARROW = 10
RANGE_TIGHT = 10
CONSOLIDATION_MIN_DAYS = 15

# 板块热度枚举
HEAT_TOP10 = 'top_10'
HEAT_TOP20 = 'top_20'
HEAT_NORMAL = 'normal'
HEAT_NONE = 'none'

# 六段论阶段映射（447号 T2a：去 recovery，recovery 属 daemon 兜底自造词，六段论=ice/sprout/ferment/climax/ebb/regression）
# 472号 C2：补 neutral 键（daemon 数据不足产 sentiment_phase='neutral'），对齐温度 SSOT PHASE_BASE_TEMP neutral:50，
# 不再落兜底"正常/数据不足"——市场层 neutral 语义=情绪数据不足时的中性档。
PHASE_MAP = {
    'ice': ('冰点', '市场极度低迷', 'red'),
    'sprout': ('萌芽', '市场情绪开始萌芽，出现连板龙头', 'yellow'),
    'ferment': ('发酵', '市场情绪发酵中，板块轮动活跃', 'green'),
    'climax': ('高潮', '市场情绪过热', 'red'),
    'ebb': ('退潮', '市场情绪开始降温', 'yellow'),
    'regression': ('回归', '市场情绪回归常态', 'yellow'),
    'neutral': ('正常', '情绪数据不足，市场中性', 'yellow'),
}


# ═══════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════

def _normalize(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.5
    return max(0, min(1, (value - low) / (high - low)))


# ═══════════════════════════════════════════════════════════
# BOCIASI快线（从 bociasi_quickline.py 迁移）
# ═══════════════════════════════════════════════════════════

def _bociasi_quickline(df: pd.DataFrame) -> dict:
    """BOCIASI快线4指标评估"""
    if df is None or df.empty or len(df) < 6:
        return {"signal": "NEUTRAL", "confidence": 0.0, "pass_count": 0,
                "indicators": {}, "details": {}}

    closes = df['close'].values
    highs = df['high'].values
    lows = df['low'].values
    volumes = df['vol'].values if 'vol' in df.columns else df['amount'].values
    latest_close = float(closes[-1])

    vol_ma5 = np.mean(volumes[-6:-1])
    fast_vol = bool(volumes[-1] > vol_ma5 * 1.5)
    vol_ratio = float(volumes[-1] / vol_ma5) if vol_ma5 > 0 else 0.0

    price_ma5 = np.mean(closes[-6:-1])
    fast_price = bool(latest_close > price_ma5)
    price_offset = float((latest_close / price_ma5 - 1) * 100) if price_ma5 > 0 else 0.0

    close_5d_ago = float(closes[-6]) if len(closes) >= 6 else latest_close
    mom_5d = (latest_close / close_5d_ago - 1) * 100
    fast_mom = bool(mom_5d > 3.0)

    daily_amplitude = (highs[-1] - lows[-1]) / latest_close * 100
    fast_breadth = bool(daily_amplitude > 3.0)

    indicators = {"fast_vol": fast_vol, "fast_price": fast_price,
                  "fast_mom": fast_mom, "fast_breadth": fast_breadth}
    pass_count = sum(1 for v in indicators.values() if v)

    if pass_count >= 3:
        signal, base_conf = "BUY", 0.65
    elif pass_count >= 2:
        signal, base_conf = "WATCH", 0.50
    elif not fast_price and mom_5d < -3:
        signal, base_conf = "BEARISH", 0.35
    else:
        signal, base_conf = "NEUTRAL", 0.35

    if fast_vol and fast_mom:
        base_conf += 0.05
    if fast_breadth and not fast_price:
        base_conf -= 0.05
    confidence = max(0.1, min(0.9, base_conf))

    return {
        "signal": signal, "confidence": round(confidence, 2),
        "indicators": indicators, "pass_count": pass_count,
        "details": {"vol_ratio": round(vol_ratio, 2), "price_offset_pct": round(price_offset, 2),
                    "mom_5d_pct": round(mom_5d, 2), "amplitude_pct": round(daily_amplitude, 2)},
    }


# ═══════════════════════════════════════════════════════════
# BOCIASI慢线（从 bociasi_slowline.py 迁移）
# ═══════════════════════════════════════════════════════════

def _bociasi_slowline(df: pd.DataFrame, bond_yield: float = None,
                      index_df: pd.DataFrame = None) -> dict:
    """BOCIASI慢线ERP评估（个股级，纯股权风险溢价）

    国债利率默认取全系统统一 CN_10Y_BOND_YIELD_PCT（env 可配，1.7），
    与四象限慢线/data_daemon/dim7 同源（470号 B1 统一，修复原硬编码 2.85
    导致"同 ERP 两套国债利率"）。

    471号 B2：慢线定位为**个股纯 ERP 信号**，移除从未执行的"股债位置差"
    （index_df 从不传入）死分支——个股级慢线不再混入相对强弱；全市场级
    股债维度由 BociasiQuadrantAnalyzer 慢线历史分位承担（B3 双语义分层）。
    index_df 参数保留（置 None）为向后兼容占位，不再使用。
    """
    if df is None or df.empty or len(df) < 60:
        # 471/472号 B4：len<60 是"个股 pe_ttm 日频积累不足（次新）"，与"无数据"区分
        return {'signal': 'NEUTRAL', 'confidence': 0.0,
                'details': {'error': '数据不足（个股 pe_ttm 序列<60日）'}}

    if bond_yield is None:
        from app.opportunity_atlas.valuation_estimator import CN_10Y_BOND_YIELD_PCT
        bond_yield = float(CN_10Y_BOND_YIELD_PCT)

    pe_ttm = None
    for col in ['pe_ttm', 'pe']:
        if col in df.columns and not df[col].empty:
            val = df[col].iloc[-1]
            if val is not None and val > 0:
                pe_ttm = float(val)
                break

    if pe_ttm is not None and pe_ttm > 0:
        erp = 1.0 / pe_ttm * 100 - bond_yield
        if erp > 5.0:
            erp_signal, erp_conf = 'BULLISH', 0.75
        elif erp > 3.0:
            erp_signal, erp_conf = 'BULLISH', 0.60
        elif erp < 0.5:
            erp_signal, erp_conf = 'BEARISH', 0.75
        elif erp < 1.5:
            erp_signal, erp_conf = 'BEARISH', 0.60
        else:
            erp_signal, erp_conf = 'NEUTRAL', 0.0
    else:
        erp = None
        erp_signal, erp_conf = 'NEUTRAL', 0.0

    # 471号 B2：原股债位置差（sb）死分支已删——index_df 从不传入，其窗口
    # 亦错 1 日（iloc[-20] 19日 vs iloc[-21] 20日），无保留价值。
    signals = []
    confs = []
    if erp_signal != 'NEUTRAL':
        signals.append(erp_signal)
        confs.append(erp_conf)

    if not signals:
        final_signal, final_conf = 'NEUTRAL', 0.3
    else:
        bullish = signals.count('BULLISH')
        bearish = signals.count('BEARISH')
        avg_conf = np.mean(confs) if confs else 0.3
        if bullish > bearish:
            final_signal = 'BULLISH'
            final_conf = min(0.8, avg_conf * 1.1)
        elif bearish > bullish:
            final_signal = 'BEARISH'
            final_conf = min(0.8, avg_conf * 1.1)
        else:
            final_signal = 'NEUTRAL'
            final_conf = 0.3

    return {
        'signal': final_signal, 'confidence': round(final_conf, 2),
        'details': {'erp': round(erp, 4) if erp is not None else None,
                     'erp_signal': erp_signal},
    }


# ═══════════════════════════════════════════════════════════
# BOCIASI四象限（从 bociasi_quadrant.py 简化迁移）
# ═══════════════════════════════════════════════════════════

def _bociasi_quadrant(quick_result: dict, slow_result: dict) -> dict:
    """四象限判定：快线+慢线交叉"""
    q_signal = quick_result.get('signal', 'NEUTRAL')
    s_signal = slow_result.get('signal', 'NEUTRAL')

    q_conf = quick_result.get('confidence', 0.5)
    slow_result.get('confidence', 0.5)

    q_high = q_signal == 'BUY' or (q_signal == 'WATCH' and q_conf > 0.5)
    s_high = s_signal == 'BULLISH'

    if not s_high and not q_high:
        quadrant, desc, mult = 'LL', '情绪底部，高性价比区间', 1.15
    elif not s_high and q_high:
        quadrant, desc, mult = 'LH', '底部反弹，短线活跃', 1.05
    elif s_high and not q_high:
        quadrant, desc, mult = 'HL', '高位震荡，需警惕风险', 0.90
    elif s_high and q_high:
        quadrant, desc, mult = 'HH', '上涨尾声，高度警惕', 0.75
    else:
        quadrant, desc, mult = 'MM', '市场情绪中性', 1.00

    return {'quadrant': quadrant, 'description': desc, 'weight_multiplier': mult,
            'fast_signal': q_signal, 'slow_signal': s_signal}


# ═══════════════════════════════════════════════════════════
# 情绪温度 — 447号 T5：唯一代码源 emotion_temperature.py（SSOT），
# 顶部 import calc_emotion_temperature，本文件不再内嵌副本（去双副本断链）
# ═══════════════════════════════════════════════════════════

def _assess_market_emotion(tags: dict, dims: dict) -> dict:
    # 440号：市场情绪自产（读 sentiment_phase），不再依赖空 dims['emotion'].state
    sp = str(tags.get('sentiment_phase', ''))
    if sp in PHASE_MAP:
        name, desc, light = PHASE_MAP[sp]
        return {'phase': name, 'detail': desc, 'light': light}
    return {'phase': '正常', 'detail': '情绪数据不足', 'light': 'yellow'}


def _assess_sector_emotion(tags: dict, dims: dict) -> dict:
    heat = str(tags.get('sector_heat', ''))
    heat_map = {
        'top_10': ('top_10', '板块排名前10（强势板块）', 'green'),
        'top_20': ('top_20', '板块排名11-20（活跃板块）', 'green'),
        'normal': ('normal', '板块排名21-40', 'yellow'),
        'none': ('none', '板块排名40以外（冷门板块）', 'yellow'),  # 442号缺陷④：'none' 是真实冷门等级，非数据缺失
    }
    if heat in heat_map:
        name, desc, light = heat_map[heat]
        return {'heat': name, 'detail': desc, 'light': light}
    return {'heat': 'normal', 'detail': '板块数据不足', 'light': 'yellow'}


def _assess_stock_emotion(tags: dict, dims: dict) -> dict:
    # 440号：个股情绪自产（读 volume_price_fit，不再依赖空 dims['vp'].state 的跨维联动）
    _vpf = str(tags.get('volume_price_fit', ''))
    vp = {'healthy': '强健康', 'diverging': '背离', 'neutral': '中性'}.get(_vpf, '')
    # 447号 T4a：dim3 已产 judgment.state（含 '严重背离'，health_score<2 触发），
    # 据此补"极度消极"分支，使 audit'个股情绪非极度消极'条件真实可触发（不再是恒真）
    _vp_state = None
    try:
        _vp_state = (dims.get('vp') or {}).get('judgment', {}).get('state')
    except Exception:
        _vp_state = None
    if _vp_state == '严重背离' or vp == '严重背离':
        return {'emotion': '极度消极', 'detail': f"量价严重背离（{_vp_state or '严重背离'}）", 'light': 'red'}
    if vp in ('强健康', '健康'):
        return {'emotion': '健康', 'detail': f"量价状态{vp}，趋势确认强势", 'light': 'green'}
    elif vp in ('背离',):
        return {'emotion': '关注', 'detail': f"量价状态{vp}，需警惕", 'light': 'yellow'}
    elif vp == '中性':
        return {'emotion': '中性', 'detail': '量价状态中性', 'light': 'yellow'}
    return {'emotion': '中性', 'detail': '量价数据不足', 'light': 'yellow'}


def _overall_light(market_light: str, sector_light: str, stock_light: str) -> str:
    lights = [market_light, sector_light, stock_light]
    if 'red' in lights:
        return 'red'
    if lights.count('green') >= 2:
        return 'green'
    return 'yellow'


# ═══════════════════════════════════════════════════════════
# 第5维 引擎
# ═══════════════════════════════════════════════════════════

class Dim5EmotionEngine(DataAwareMixin):
    """第5维 情绪环境引擎 — BOCIASI快慢线 + 四象限 + 温度 + 板块热度 + 时间节奏"""

    def __init__(self):
        self._dm = None

    def evaluate(self, dims: dict, tags: dict, signals: dict = None,
                 lifecycle: dict = None, data_context: dict = None) -> dict:
        """统一评估入口

        411号Phase 6：优先使用data_context预加载数据，回退独立查询。
        """

        # 1. BOCIASI快慢线 + 四象限（先于情绪评估，结果回写market）
        quick_result = {"signal": "NEUTRAL", "confidence": 0.3, "pass_count": 0}
        slow_result = {"signal": "NEUTRAL", "confidence": 0.3}
        quadrant = {'quadrant': 'MM', 'description': '市场情绪中性', 'weight_multiplier': 1.0}

        try:
            ecm = self._get_dm().cache
            ts_code = tags.get('ts_code', '')

            # 快线：从日线数据计算4指标
            if ts_code:
                try:
                    # 411号Phase 6：优先使用data_context
                    if data_context and 'daily_df' in data_context:
                        df = data_context['daily_df']
                    else:
                        df = ecm.get_cached_daily(ts_code)
                    if df is not None and not df.empty and len(df) >= 6:
                        quick_result = _bociasi_quickline(df)
                except Exception:
                    pass

            # 慢线：从日线数据计算ERP（413 P2 T7：优先data_context）
            if ts_code:
                try:
                    df_basic = data_context.get('daily_basic_df') if data_context else None
                    if df_basic is None:
                        df_basic = ecm.get_cached_daily_basic(ts_code)
                    if df_basic is not None and not df_basic.empty:
                        slow_result = _bociasi_slowline(df_basic)
                except Exception:
                    pass

            # 四象限：使用完整 BociasiQuadrantAnalyzer（含全市场DB查询）
            try:
                market_stats = data_context.get('market_stats') if data_context else None
                analyzer = BociasiQuadrantAnalyzer(ecm=ecm, market_stats=market_stats)
                full_quadrant = analyzer.analyze()
                quadrant = {
                    'quadrant': full_quadrant.get('quadrant', 'MM'),
                    'description': full_quadrant.get('description', '市场情绪中性'),
                    'weight_multiplier': full_quadrant.get('weight_multiplier', 1.0),
                    'fast_score': full_quadrant.get('fast_score', 0.5),
                    'slow_score': full_quadrant.get('slow_score', 0.5),
                    'fast_signal': quick_result.get('signal', 'NEUTRAL'),
                    'slow_signal': slow_result.get('signal', 'NEUTRAL'),
                }
            except Exception:
                quadrant = _bociasi_quadrant(quick_result, slow_result)

        except Exception:
            pass

        # 2. 三层面情绪评估（BOCIASI quadrant 结果回写 market）
        market = _assess_market_emotion(tags, dims)
        sector = _assess_sector_emotion(tags, dims)
        stock = _assess_stock_emotion(tags, dims)

        # 2b. BOCIASI四象限修正 market 情绪判定
        q = quadrant.get('quadrant', 'MM')
        if q == 'HH':
            if market['light'] == 'green':
                market = {'phase': '高位风险', 'detail': f"BOCIASI四象限={q}（{quadrant['description']}）", 'light': 'red'}
        elif q == 'LL':
            if market['light'] == 'red':
                market = {'phase': '情绪底部', 'detail': f"BOCIASI四象限={q}（{quadrant['description']}）", 'light': 'green'}
        elif q == 'HL':
            if market['light'] == 'green':
                market = {'phase': '高位震荡', 'detail': f"BOCIASI四象限={q}（{quadrant['description']}）", 'light': 'yellow'}
        elif q == 'LH':
            if market['light'] == 'red':
                market = {'phase': '底部反弹', 'detail': f"BOCIASI四象限={q}（{quadrant['description']}）", 'light': 'yellow'}

        # 3. 板块热度（419号方案B5：从dim1 data_context分拨，不再直调SectorRotationModel）
        _sector_rank = None  # 447号 T1a：供温度复用（sector_heat 权重 15% 复活）
        if tags.get('ts_code'):
            try:
                sector_heat = data_context.get('sector_heat') if data_context else None
                if sector_heat:
                    industry = self._get_dm().get_stock_industry(tags['ts_code'])
                    info = sector_heat.get(industry) if industry else None
                    if info and info.get('heat_level') and info['heat_level'] != 'none':
                        sector['heat'] = info['heat_level']
                        sector['detail'] = f"板块{industry}(排名{info.get('rank', '?')})"
                        _sector_rank = info.get('rank')
            except Exception:
                pass

        # 4. 情绪温度（融合BOCIASI真实计算分数 + P10融资余额变化率）
        sp = tags.get('sentiment_phase', 'neutral')
        vp_fit = tags.get('volume_price_fit', 'neutral')

        # 447号 T1a：涨停家数/封板率 从 data_context['emotion_ext']（daemon RAW 预计算已透传）
        _limit_up = 0
        _sealing = None
        _breadth = None
        try:
            _emotion_ext = data_context.get('emotion_ext') if data_context else None
            if _emotion_ext:
                if isinstance(_emotion_ext.get('limit_up_count'), int):
                    _limit_up = _emotion_ext['limit_up_count']
                if isinstance(_emotion_ext.get('sealing_rate'), (int, float)):
                    _sealing = float(_emotion_ext['sealing_rate'])
            # breadth：全市场 MA20 强势股占比（market_stats，daemon 预计算）
            _mstats = data_context.get('market_stats') if data_context else None
            if _mstats and isinstance(_mstats.get('ma20_ratio'), (int, float)):
                _breadth = float(_mstats['ma20_ratio'])
        except Exception:
            pass

        # P10: 获取融资余额变化率
        margin_change_pct = None
        try:
            if ts_code:
                # 413 P2 T7：优先从data_context读取margin_df
                margin_df = data_context.get('margin_df') if data_context else None
                if margin_df is None:
                    margin_df = ecm.get_cached_margin(ts_code) if ecm else None
                if margin_df is not None and not margin_df.empty and len(margin_df) >= 5:
                    rzye = margin_df['rzye'].dropna().astype(float)
                    if len(rzye) >= 5:
                        margin_change_pct = (rzye.iloc[-1] / rzye.iloc[0] - 1) if rzye.iloc[0] > 0 else None
        except Exception:
            pass

        temperature = calc_emotion_temperature(
            sentiment_phase=sp, limit_up_count=_limit_up,
            sealing_rate=_sealing if _sealing is not None else 50.0,
            sector_rank=_sector_rank, volume_price_fit=vp_fit,
            margin_change_pct=margin_change_pct, breadth=_breadth)

        # BOCIASI修正：用快慢线分数加权修正温度
        fast_score = quadrant.get('fast_score', None)
        slow_score = quadrant.get('slow_score', None)
        if fast_score is not None and slow_score is not None:
            bociasi_temp = (float(fast_score) * 0.6 + float(slow_score) * 0.4) * 100
            temperature = round(temperature * 0.4 + bociasi_temp * 0.6, 1)

        # 5. 综合灯色
        overall = _overall_light(market['light'], sector['light'], stock['light'])

        # 6. status_description
        status_description = {
            'market': f"市场处于{market['phase']}（{market['detail']}）",
            'sector': sector['detail'],
            'stock': f"个股{stock['emotion']}（{stock['detail']}）",
            'bociasi_quick': f"个股快线={bociasi_signal_cn(quick_result.get('signal'))}（{quick_result.get('confidence',0)}）",
            'bociasi_slow': f"个股慢线ERP={bociasi_signal_cn(slow_result.get('signal'))}（{slow_result.get('confidence',0)}）",
            'quadrant': f"大市四象限({quadrant_cn(quadrant.get('quadrant',''))}·全市场分位)—{quadrant.get('description','')}",
            'temperature': f"{temperature}/100",
        }

        # 7. judgment
        judgment = {
            'market_light': market['light'],
            'sector_light': sector['light'],
            'stock_light': stock['light'],
            'overall_light': overall,
            'overall_direction': 1 if overall == 'green' else (-1 if overall == 'red' else 0),
            'continuous_value': round(temperature / 100, 4),
        }

        # 8. audit
        conditions = [
            {'name': '市场情绪', 'satisfied': market['phase'] not in ('退潮', '冰点'),
             'actual': market['phase'], 'threshold': '非退潮/冰点'},
            {'name': '板块热度', 'satisfied': sector['heat'] in ('top_10', 'top_20'),
             'actual': sector['heat'], 'threshold': 'top_20以内'},
            {'name': '个股情绪', 'satisfied': stock['emotion'] not in ('极度消极',),
             'actual': stock['emotion'], 'threshold': '非极度消极'},
            {'name': 'BOCIASI快线非看空', 'satisfied': quick_result.get('signal') != 'BEARISH',
             'actual': quick_result.get('signal', 'N/A'), 'threshold': '非BEARISH'},
            {'name': '四象限非高风险', 'satisfied': quadrant.get('quadrant') != 'HH',
             'actual': quadrant.get('quadrant', ''), 'threshold': '非HH'},
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
            'tags (pre_feat_cache) — sentiment_phase / sector_heat / volume_price_fit / volume_ratio / trend_alignment',
            'dims (StatusEngine) — emotion / vp',
        ]
