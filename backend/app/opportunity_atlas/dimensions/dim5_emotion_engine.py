"""第5维 情绪环境引擎

358号方案 v4.1：第5维情绪环境维度引擎。

整合源：
  - emotion_builder.py（182行）：三层面输出（市场/板块/个股）+ 条件稽核
  - bociasi_quickline.py（131行）：BOCIASI快线4指标
  - bociasi_slowline.py（171行）：BOCIASI慢线ERP
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

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# BOCIASI快线常量
# ═══════════════════════════════════════════════════════════

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

# 六段论阶段映射
PHASE_MAP = {
    'ice': ('冰点', '市场极度低迷', 'red'),
    'sprout': ('萌芽', '市场情绪开始萌芽，出现连板龙头', 'yellow'),
    'ferment': ('发酵', '市场情绪发酵中，板块轮动活跃', 'green'),
    'climax': ('高潮', '市场情绪过热', 'red'),
    'ebb': ('退潮', '市场情绪开始降温', 'yellow'),
    'regression': ('回归', '市场情绪回归常态', 'yellow'),
    'recovery': ('复苏', '市场情绪开始回暖', 'green'),
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

def _bociasi_slowline(df: pd.DataFrame, bond_yield: float = 2.85,
                      index_df: pd.DataFrame = None) -> dict:
    """BOCIASI慢线ERP评估"""
    if df is None or df.empty or len(df) < 60:
        return {'signal': 'NEUTRAL', 'confidence': 0.0, 'details': {'error': '数据不足'}}

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

    sb_signal, sb_conf = 'NEUTRAL', 0.0
    if index_df is not None and not index_df.empty:
        idx_close = index_df['close'].astype(float)
        stock_close = df['close'].astype(float)
        if len(idx_close) >= 20 and len(stock_close) >= 21:
            idx_ret = idx_close.iloc[-1] / idx_close.iloc[-20] - 1
            stock_ret = stock_close.iloc[-1] / stock_close.iloc[-21] - 1
            rel_strength = stock_ret - idx_ret
            if rel_strength > 0.05:
                sb_signal = 'BULLISH'
                sb_conf = min(0.7, 0.5 + abs(rel_strength))
            elif rel_strength < -0.05:
                sb_signal = 'BEARISH'
                sb_conf = min(0.7, 0.5 + abs(rel_strength))

    signals = []
    confs = []
    if erp_signal != 'NEUTRAL':
        signals.append(erp_signal)
        confs.append(erp_conf)
    if sb_signal != 'NEUTRAL':
        signals.append(sb_signal)
        confs.append(sb_conf)

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
                     'erp_signal': erp_signal, 'sb_signal': sb_signal},
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
# 情绪温度（从 emotion_temperature.py 迁移）
# ═══════════════════════════════════════════════════════════

def calc_emotion_temperature(sentiment_phase='neutral', limit_up_count=0,
                             sealing_rate=50.0, sector_rank=None,
                             volume_price_fit='neutral',
                             margin_change_pct=None, breadth=None) -> float:
    scores = {}
    scores['market_phase'] = PHASE_BASE_TEMP.get(sentiment_phase, 50)
    scores['limit_up'] = min(100, max(0, limit_up_count))
    scores['blast_rate'] = min(100, max(0, sealing_rate))
    scores['sector_heat'] = max(0, min(100, 100 - sector_rank * 2)) if sector_rank else 50
    vp_map = {'healthy': 80, 'diverging': 20, 'neutral': 50}
    scores['volume_price'] = vp_map.get(volume_price_fit, 50)
    scores['margin'] = min(100, max(0, 50 + margin_change_pct * 600)) if margin_change_pct is not None else 50
    scores['breadth'] = min(100, max(0, breadth * 100)) if breadth is not None else 50
    total = sum(scores[k] * TEMP_WEIGHTS[k] for k in TEMP_WEIGHTS)
    return round(min(100, max(0, total)), 1)


def _assess_market_emotion(tags: dict, dims: dict) -> dict:
    dim_emotion = str(dims.get('emotion', {}).get('state', ''))
    dim_light = str(dims.get('emotion', {}).get('light', ''))
    if dim_emotion:
        light = 'red' if dim_light == 'red' else ('green' if dim_light == 'green' else 'yellow')
        return {'phase': dim_emotion, 'detail': f'L1判定情绪={dim_emotion}', 'light': light}

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
        'normal': ('normal', '板块排名20以外', 'yellow'),
        'none': ('none', '板块数据不足', 'yellow'),
    }
    if heat in heat_map:
        name, desc, light = heat_map[heat]
        return {'heat': name, 'detail': desc, 'light': light}
    return {'heat': 'normal', 'detail': '板块数据不足', 'light': 'yellow'}


def _assess_stock_emotion(tags: dict, dims: dict) -> dict:
    vp = str(dims.get('vp', {}).get('state', ''))
    if vp in ('强健康', '健康'):
        return {'emotion': '健康', 'detail': f"量价状态{vp}，趋势确认强势", 'light': 'green'}
    elif vp in ('背离', '严重背离'):
        return {'emotion': '关注', 'detail': f"量价状态{vp}，需警惕", 'light': 'yellow'}
    return {'emotion': '中性', 'detail': '量价数据不足', 'light': 'yellow'}


def _overall_light(market_light: str, sector_light: str, stock_light: str) -> str:
    lights = [market_light, sector_light, stock_light]
    if 'red' in lights:
        return 'red'
    if lights.count('green') >= 2:
        return 'green'
    return 'yellow'


def _emotion_plain(market: dict, sector: dict, stock: dict,
                   quadrant: dict = None, temperature: float = None) -> str:
    parts = []
    phase = market.get('phase', '')
    if phase in ('冰点',):
        parts.append(f'市场极度低迷（{market.get("detail", "")}）')
    elif phase in ('萌芽',):
        parts.append(f'市场开始回暖（{market.get("detail", "")}）')
    elif phase in ('发酵',):
        parts.append(f'市场氛围偏暖（{market.get("detail", "")}）')
    elif phase in ('高潮',):
        parts.append(f'市场情绪过热（{market.get("detail", "")}）')
    elif phase in ('退潮',):
        parts.append(f'市场情绪降温（{market.get("detail", "")}）')
    elif phase in ('回归', '复苏'):
        parts.append(f'市场情绪{phase}（{market.get("detail", "")}）')
    elif phase:
        parts.append(f'市场情绪{phase}')
    else:
        parts.append('市场情绪数据不足')

    if quadrant:
        parts.append(f'四象限={quadrant.get("quadrant","")}({quadrant.get("description","")})')

    if temperature is not None:
        parts.append(f'情绪温度{temperature}/100')

    heat = sector.get('heat', '')
    if heat == 'top_10':
        parts.append(f'所在板块在风口（{sector.get("detail", "")}）')
    elif heat == 'top_20':
        parts.append(f'所在板块较活跃（{sector.get("detail", "")}）')

    stock_emo = stock.get('emotion', '')
    if stock_emo == '健康':
        parts.append('个股情绪健康')
    elif stock_emo == '关注':
        parts.append('个股需关注')

    return '，'.join(parts)


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
        if tags.get('ts_code'):
            try:
                sector_heat = data_context.get('sector_heat') if data_context else None
                if sector_heat:
                    industry = self._get_dm().get_stock_industry(tags['ts_code'])
                    info = sector_heat.get(industry) if industry else None
                    if info and info.get('heat_level') and info['heat_level'] != 'none':
                        sector['heat'] = info['heat_level']
                        sector['detail'] = f"板块{industry}(排名{info.get('rank', '?')})"
            except Exception:
                pass

        # 4. 情绪温度（融合BOCIASI真实计算分数 + P10融资余额变化率）
        sp = tags.get('sentiment_phase', 'neutral')
        vp_fit = tags.get('volume_price_fit', 'neutral')

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

        temperature = calc_emotion_temperature(sentiment_phase=sp, volume_price_fit=vp_fit,
                                               margin_change_pct=margin_change_pct)

        # BOCIASI修正：用快慢线分数加权修正温度
        fast_score = quadrant.get('fast_score', None)
        slow_score = quadrant.get('slow_score', None)
        if fast_score is not None and slow_score is not None:
            bociasi_temp = (float(fast_score) * 0.6 + float(slow_score) * 0.4) * 100
            temperature = round(temperature * 0.4 + bociasi_temp * 0.6, 1)

        # 5. 综合灯色
        overall = _overall_light(market['light'], sector['light'], stock['light'])

        # 6. status_description
        plain = _emotion_plain(market, sector, stock, quadrant, temperature)
        status_description = {
            'market': f"市场处于{market['phase']}（{market['detail']}）",
            'sector': f"板块{sector['heat']}（{sector['detail']}）",
            'stock': f"个股{stock['emotion']}（{stock['detail']}）",
            'bociasi_quick': f"快线={quick_result.get('signal','N/A')}（{quick_result.get('confidence',0)}）",
            'bociasi_slow': f"慢线={slow_result.get('signal','N/A')}（{slow_result.get('confidence',0)}）",
            'quadrant': f"{quadrant.get('quadrant','')} — {quadrant.get('description','')}",
            'temperature': f"{temperature}/100",
            'plain': plain,
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
