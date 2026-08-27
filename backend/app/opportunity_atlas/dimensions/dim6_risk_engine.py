"""第6维 风险边界引擎

358号方案 v4.1：第6维风险边界维度引擎。

整合源：
  - risk_boundary_builder.py（382行）：风险等级5级 + 波动率 + 盈亏比 + 失效条件
  - advice_builder._geometric()：支撑位/阻力位/盈亏比/ATR%/信号天数
  - event_monitor.py（925行）中的关键事件风险检测
  - cscv_validator.py（307行）：CSCV校验逻辑
  - eagle_sword_resonance.py（399行）：鹰刀共振（含BOCIASI情绪输入）

统一接口：evaluate(dims, tags, signals, lifecycle) → {status_description, judgment, audit}
"""

from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime
from typing import Optional, Dict, List, Tuple, Any
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

EVENT_RISK_SET = {'fraud_sign', 'regulatory', 'delist_risk', 'goodwill_risk'}

# ── 事件→维度前缀映射（A/B/C/D/E）──
_EVENT_DIM_MAP = {
    # A 财务事件
    'earnings_surprise': 'A', 'earnings_confirm': 'A', 'report_date': 'A',
    'dividend': 'A', 'fraud_sign': 'A',
    # B 资本运作
    'share_float': 'B', 'pledge_risk': 'B', 'holder_reduce': 'B',
    'underwater_ipo': 'B', 'buyback': 'B', 'incentive': 'B',
    # C 监管事件
    'regulatory': 'C', 'delist_risk': 'C', 'st_warning': 'C', 'goodwill_risk': 'C',
    # D 市场情绪
    'longhubang': 'D', 'limit_move': 'D', 'holder_concentration': 'D', 'margin_risk': 'D',
    # E 特殊事件
    'breakout': 'E', 'concept_heat': 'E',
}


def _event_dim_prefix(event_name: str) -> str:
    """将事件类型映射到 A/B/C/D/E 维度前缀"""
    return _EVENT_DIM_MAP.get(event_name, 'E')


def _direction_to_sign(direction: int) -> int:
    """将方向值转为符号（-1/0/+1）"""
    if direction > 0:
        return 1
    elif direction < 0:
        return -1
    return 0


# ── 催化剂事件映射 ──
CATALYST_EVENT_MAP = {
    'earnings_surprise': 'earnings', 'earnings_confirm': 'earnings',
    'longhubang': 'lhb', 'limit_move': 'lhb',
    'buyback': 'buyback', 'incentive': 'buyback',
    'breakout': 'breakout', 'concept_heat': 'concept',
    'share_float': 'float', 'pledge_risk': 'pledge', 'holder_reduce': 'reduce',
    'fraud_sign': 'fraud_sign', 'regulatory': 'regulatory',
    'st_warning': 'regulatory', 'goodwill_risk': 'fraud_sign',
    'delist_risk': 'decline', 'underwater_ipo': 'decline',
    'holder_concentration': 'decline', 'margin_risk': 'decline',
}

# ── 鹰眼大宝剑共振查表 ──
_RESONANCE_TABLE = {
    "UP": {
        "BULLISH":  ("BUY", 0.70),
        "BEARISH":  ("CONFLICT", 0.40),
        "NEUTRAL":  ("WATCH_BUY", 0.55),
    },
    "DOWN": {
        "BULLISH":  ("CONFLICT", 0.40),
        "BEARISH":  ("SELL", 0.70),
        "NEUTRAL":  ("WATCH_SELL", 0.55),
    },
    "RANGING": {
        "BULLISH":  ("CAUTIOUS_BUY", 0.50),
        "BEARISH":  ("CAUTIOUS_SELL", 0.50),
        "NEUTRAL":  ("NEUTRAL", 0.30),
    },
    "UNKNOWN": {
        "BULLISH":  ("CAUTIOUS_BUY", 0.45),
        "BEARISH":  ("CAUTIOUS_SELL", 0.45),
        "NEUTRAL":  ("NEUTRAL", 0.25),
    },
}
_FALLBACK_ACTION = ("NEUTRAL", 0.25)


# ═══════════════════════════════════════════════════════════
# 几何化指标（从 advice_builder._geometric() 完整迁移）
# ═══════════════════════════════════════════════════════════

def calc_geometric(df: pd.DataFrame) -> dict:
    """几何化指标：支撑/阻力位、盈亏比、信号天数、防守位"""
    if df is None or df.empty or 'close' not in df.columns or len(df) < 20:
        return {'dist_to_support_pct': None, 'dist_to_resistance_pct': None,
                'risk_reward': None, 'signal_days': None,
                'support_price': None, 'resistance_price': None}

    closes = df['close'].values
    price = float(closes[-1])
    hi60 = float(df['high'].tail(60).max()) if len(df) >= 60 and 'high' in df.columns else None
    lo60 = float(df['low'].tail(60).min()) if len(df) >= 60 and 'low' in df.columns else None

    ma60 = float(df['close'].tail(60).mean()) if len(df) >= 60 else None
    resistance = hi60
    resistance_candidates = [x for x in [hi60, ma60] if x is not None and x > price]
    if resistance_candidates:
        resistance = min(resistance_candidates)

    ma20 = float(df['close'].tail(20).mean()) if len(df) >= 20 else None
    lo20 = float(df['low'].tail(20).min()) if len(df) >= 20 and 'low' in df.columns else None
    near = None
    if ma20 is not None and lo20 is not None:
        near = max(ma20, lo20)
    elif ma20 is not None:
        near = ma20
    elif lo20 is not None:
        near = lo20
    support = near

    if support is not None and price is not None and support >= price:
        support = lo60
    if support is not None and price is not None:
        max_stop_pct = 0.15
        min_support = price * (1 - max_stop_pct)
        if support < min_support:
            support = min_support

    dist_sup = (support / price - 1) * 100 if support else None
    dist_res = (resistance / price - 1) * 100 if resistance else None
    rr = abs(dist_res / dist_sup) if dist_sup and dist_res else None

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

    # P8: 距前高%（20日内最高价）
    dist_prev_high = None
    if len(df) >= 20 and 'high' in df.columns:
        prev_high = float(df['high'].tail(20).max())
        if prev_high > 0 and price is not None:
            dist_prev_high = round((price / prev_high - 1) * 100, 2)

    return {
        'dist_to_support_pct': round(dist_sup, 2) if dist_sup is not None else None,
        'dist_to_resistance_pct': round(dist_res, 2) if dist_res is not None else None,
        'dist_to_prev_high_pct': dist_prev_high,  # P8新增
        'risk_reward': round(rr, 2) if rr is not None else None,
        'signal_days': signal_days,
        'support_price': round(support, 2) if support is not None else None,
        'resistance_price': round(resistance, 2) if resistance is not None else None,
    }


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
                vol_20d = returns.rolling(20).std() * math.sqrt(252)
                vol_20d = vol_20d.dropna()
                if len(vol_20d) >= 2:
                    current_vol = vol_20d.iloc[-1]
                    percentile = float((vol_20d < current_vol).sum() / len(vol_20d))
        except Exception:
            pass

    return {'level': level, 'atr_14d': atr_14d, 'atr_pct': atr_pct,
            'percentile': percentile}


# ═══════════════════════════════════════════════════════════
# 风险等级评估（从 risk_boundary_builder 迁移）
# ═══════════════════════════════════════════════════════════

def _assess_risk_level(dims: dict, l0: dict, tags: dict) -> dict:
    risk_sources = []
    high_count = 0

    dim_risk = str(dims.get('risk', {}).get('state', ''))
    dim_risk_light = str(dims.get('risk', {}).get('light', ''))
    if dim_risk == '高' or dim_risk_light == 'red':
        return {'level': '高', 'light': 'red', 'detail': f'L1判定风险=高'}

    rl = str(tags.get('risk_level', ''))
    if rl == 'HIGH':
        high_count += 1
    risk_sources.append({'name': '缠论风险', 'level': '高' if rl == 'HIGH' else '低'})

    vl = str(tags.get('volatility_level', ''))
    if vl == 'high':
        high_count += 1
    risk_sources.append({'name': '波动率风险', 'level': '高' if vl == 'high' else '低'})

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

    try:
        tr = float(tags.get('turnover_rate', 999))
        if tr < 1.0:
            high_count += 1
    except (TypeError, ValueError):
        pass

    if l0.get('hard_veto'):
        return {'level': '极高', 'light': 'red', 'detail': f"硬否决：{l0.get('hard_reason', '')}"}

    if high_count >= 2:
        level, light = '高', 'red'
    elif high_count == 1:
        level, light = '中', 'yellow'
    else:
        level, light = '低', 'green'

    return {'level': level, 'light': light, 'detail': f'{high_count}个高风险源' if high_count else '无高风险源'}


def _list_risk_factors(tags: dict, dims: dict, l0: dict) -> list[dict]:
    factors = []
    fh = str(tags.get('fina_health', ''))
    if fh == 'fail':
        factors.append({'category': '财务', 'factor': '财务异常', 'severity': '高', 'satisfied': True})
    elif fh == 'suspicious':
        factors.append({'category': '财务', 'factor': '财务关注', 'severity': '中', 'satisfied': True})

    ce = str(tags.get('catalyst_event', ''))
    event_map = {'regulatory': ('监管问题', '高'), 'fraud_sign': ('造假信号', '极高')}
    if ce in event_map:
        name, sev = event_map[ce]
        factors.append({'category': '事件', 'factor': name, 'severity': sev, 'satisfied': True})

    mfp = str(tags.get('main_force_phase', ''))
    if mfp == 'distributing':
        factors.append({'category': '主力', 'factor': '主力出货', 'severity': '中', 'satisfied': True})

    vl = str(tags.get('valuation_level', ''))
    if vl in ('high', 'extreme_high'):
        factors.append({'category': '估值', 'factor': '估值过高', 'severity': '中', 'satisfied': True})

    try:
        tr = float(tags.get('turnover_rate', 999))
        if tr < 1.0:
            factors.append({'category': '流动性', 'factor': '流动性不足', 'severity': '高', 'satisfied': True})
    except (TypeError, ValueError):
        pass

    try:
        pr = float(tags.get('profit_ratio', 0))
        if pr >= 0.8:
            factors.append({'category': '获利盘', 'factor': '获利盘过高', 'severity': '中', 'satisfied': True})
    except (TypeError, ValueError):
        pass

    for sr in l0.get('soft_risks', []):
        if sr == 'low_liquidity':
            factors.append({'category': '流动性', 'factor': '流动性不足(L0)', 'severity': '中', 'satisfied': True})

    if not factors:
        factors.append({'category': '综合', 'factor': '无显著风险', 'severity': '无', 'satisfied': True})

    return factors


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


def _build_invalidation(support, tags, dims) -> list[dict]:
    conditions = []
    if support is not None:
        conditions.append({'source': '防守位', 'condition': f'收盘跌破{support}元', 'priority': 1})
    sp = str(tags.get('sentiment_phase', ''))
    if sp in ('ebb', 'climax'):
        conditions.append({'source': '情绪', 'condition': '大盘进入退潮/高潮期', 'priority': 2})
    if str(tags.get('right_side_confirm', '')) == '否决':
        conditions.append({'source': '右侧', 'condition': '右侧确认转否决', 'priority': 3})
    return conditions


# ═══════════════════════════════════════════════════════════
# 白话文本
# ═══════════════════════════════════════════════════════════

def _risk_plain(level, factors, geo, rr, vol, invalidation) -> str:
    parts = []
    level_cn = {'低': '低风险', '中': '中等风险', '高': '高风险'}.get(level, f'{level}风险')
    parts.append(level_cn)

    support = geo.get('support_price')
    dist_sup = geo.get('dist_to_support_pct')
    if support and dist_sup is not None:
        parts.append(f'防守位{support}元（距现价{dist_sup:+.1f}%）')

    resistance = geo.get('resistance_price')
    dist_res = geo.get('dist_to_resistance_pct')
    if resistance and dist_res is not None:
        parts.append(f'压力位{resistance}元（距现价{dist_res:+.1f}%）')

    rr_val = rr.get('rr_value')
    if rr_val:
        if rr_val >= 3:
            parts.append(f'盈亏比{rr_val}（优质）')
        elif rr_val >= 2:
            parts.append(f'盈亏比{rr_val}（较好）')
        elif rr_val >= 1:
            parts.append(f'盈亏比{rr_val}（一般）')
        else:
            parts.append(f'盈亏比{rr_val}（不划算）')

    vol_level = vol.get('level', '')
    vol_cn = {'low': '低波动', 'medium': '中等波动', 'high': '高波动'}.get(vol_level, '')
    if vol_cn:
        parts.append(vol_cn)

    key_factors = [f['factor'] for f in factors if f.get('satisfied') and f.get('severity') in ('高', '极高')]
    if key_factors:
        parts.append(f'需关注：{"、".join(key_factors)}')

    if invalidation:
        parts.append(f'止损条件：{invalidation[0].get("condition", "")}')

    return '，'.join(parts) if parts else '风险数据不足'


# ═══════════════════════════════════════════════════════════
# 第6维 引擎
# ═══════════════════════════════════════════════════════════


# === event_monitor.py ===
class EventMonitor(DataAwareMixin):
    """事件监控器"""

    def __init__(self, data_manager=None):
        self._dm = data_manager  # DataAwareMixin 统一注入点

    def _today_str(self) -> str:
        return datetime.now().strftime('%Y%m%d')

    def _date_from_str(self, s: str) -> date | None:
        try:
            s_clean = str(s).replace('-', '')[:8]
            if len(s_clean) == 8 and s_clean.isdigit():
                return datetime.strptime(s_clean, '%Y%m%d').date()
        except Exception:
            pass
        return None

    # ══════════════════════════════════════════════════════════
    # A 财务事件
    # ══════════════════════════════════════════════════════════

    def _detect_earnings_surprise(self, ts_code: str) -> dict:
        """A1 业绩预增: forecast_cache 净利润同比增长>50%"""
        result = {"detected": False, "direction": 0, "confidence": 0.0,
                   "source": "forecast_cache", "description": "", "event_date": ""}
        try:
            cache = self._get_cache()
            df = cache.get_cached_forecast(ts_code)
            if df is None or df.empty:
                return result

            # 取最新一条预告
            latest = df.sort_values('end_date', ascending=False).iloc[0]
            ftype = str(latest.get('forecast_type', ''))
            ftype_map = {
                '预增': ('正向', 1), '扭亏': ('正向', 1), '续盈': ('正向', 0),
                '略增': ('正向', 0), '减亏': ('正向', 0),
                '预减': ('负向', -1), '首亏': ('负向', -2), '续亏': ('负向', -2),
                '略减': ('负向', -1),
            }
            mapping = ftype_map.get(ftype)
            if mapping is None:
                return result

            label, base_dir = mapping
            # 检查净利同比增幅是否>50%
            n_min = latest.get('net_profit_min')
            n_max = latest.get('net_profit_max')
            direction = base_dir
            confidence = 0.5
            event_date = str(latest.get('ann_date', ''))

            if n_min is not None and n_max is not None and n_min != 0:
                avg_profit = (float(n_min) + float(n_max)) / 2
                # 如果有 end_date 可以算同比，但 forecast 表中只有绝对值
                # 简化为：预告类型正向且净利为正 → direction=+1, 大幅预增→+2
                if label == '正向' and avg_profit > 0:
                    direction = 2 if ftype == '预增' else 1
                    confidence = 0.7
                    result["detected"] = True
                elif label == '负向':
                    direction = base_dir
                    confidence = 0.6
                    result["detected"] = True

            result["direction"] = direction
            result["confidence"] = confidence
            result["description"] = f"业绩预告: {ftype}"
            result["event_date"] = event_date
        except Exception as e:
            logger.debug("A1 _detect_earnings_surprise(%s): %s", ts_code, e)
        return result

    def _detect_earnings_confirm(self, ts_code: str) -> dict:
        """A2 业绩确认: forecast_cache + fina_indicator — 偏差±10%"""
        result = {"detected": False, "direction": 0, "confidence": 0.0,
                   "source": "forecast_cache+fina_indicator", "description": "", "event_date": ""}
        try:
            cache = self._get_cache()
            df_fc = cache.get_cached_forecast(ts_code)
            df_fi = cache.get_cached_fina_indicator(ts_code)
            if df_fc is None or df_fc.empty or df_fi is None or df_fi.empty:
                return result

            latest_fc = df_fc.sort_values('end_date', ascending=False).iloc[0]
            # 匹配对应 end_date 的财报
            fc_end = str(latest_fc.get('end_date', ''))
            if not fc_end:
                return result
            match = df_fi[df_fi['end_date'] == fc_end]
            if match.empty:
                return result
            actual_eps = match.iloc[0].get('eps')
            if actual_eps is None:
                return result
            actual_eps = float(actual_eps)

            fc_eps_min = latest_fc.get('eps_min')
            fc_eps_max = latest_fc.get('eps_max')
            if fc_eps_min is None or fc_eps_max is None:
                return result
            fc_eps_min, fc_eps_max = float(fc_eps_min), float(fc_eps_max)

            if abs(fc_eps_min) < 1e-9:
                return result

            # 偏差: 实际值与预告中值比较
            fc_mid = (fc_eps_min + fc_eps_max) / 2
            if fc_mid == 0:
                return result
            deviation = (actual_eps - fc_mid) / abs(fc_mid)
            forecast_type = str(latest_fc.get('forecast_type', ''))

            # 正向偏差 = 业绩超预期
            direction = 0
            confidence = 0.0
            if abs(deviation) >= 0.1:
                result["detected"] = True
                direction = 1 if deviation > 0 else -1
                confidence = min(abs(deviation), 1.0)
                result["description"] = (
                    f"业绩确认偏差: {deviation:+.1%}, "
                    f"预告={forecast_type}, "
                    f"实际EPS={actual_eps:.4f}"
                )
                result["event_date"] = str(match.iloc[0].get('ann_date', ''))
            else:
                # 偏差<10%，确认符合预期
                pass

            result["direction"] = direction
            result["confidence"] = confidence
        except Exception as e:
            logger.debug("A2 _detect_earnings_confirm(%s): %s", ts_code, e)
        return result

    def _detect_report_date(self, ts_code: str) -> dict:
        """A3 财报预约披露日: 依赖 AKShare 巨潮公告，非采集层不可用
        第一阶段标记为未检测到。
        """
        return {"detected": False, "direction": 0, "confidence": 0.0,
                "source": "report_date", "description": "财报披露日检测待接入",
                "event_date": ""}

    def _detect_dividend(self, ts_code: str) -> dict:
        """A4 分红/送转: 依赖 AKShare 巨潮公告，非采集层不可用
        第一阶段标记为未检测到。
        """
        return {"detected": False, "direction": 0, "confidence": 0.0,
                "source": "dividend", "description": "分红送转检测待接入",
                "event_date": ""}

    def _detect_fraud_sign(self, ts_code: str) -> dict:
        """A5 财务异常: fina_indicator + income + cashflow 多项异常

        检测项（2026-08-05 收紧：原 ROE<3%/现金流<0.5 过宽，致 74.9% 股票误标 fraud_sign——
        财务质量差 ≠ 财务欺诈；收紧至真实异常阈值）:
        1) 营收连续2年下降
        2) 经营现金流为负（原 <0.5 过宽）
        3) ROE 为负（亏损，原 <3% 过宽；微利由 fina_health 覆盖）
        4) 资产负债率 > 90%
        """
        result = {"detected": False, "direction": 0, "confidence": 0.0,
                   "source": "fina_indicator+income+cashflow", "description": "", "event_date": ""}
        try:
            dm = self._get_dm()
            df_fi = dm.get_cached_fina_indicator(ts_code)
            df_inc = dm.get_cached_income(ts_code)
            df_cf = dm.cache.get_cached_cashflow(ts_code)
            df_bs = dm.get_cached_balancesheet(ts_code)

            anomalies = []

            # 1) 营收连续2年下降
            if df_inc is not None and len(df_inc) >= 2:
                inc_sorted = df_inc.sort_values('end_date', ascending=False)
                revenues = inc_sorted['revenue'].dropna()
                if len(revenues) >= 2:
                    if revenues.iloc[0] < revenues.iloc[1] * 0.9:
                        anomalies.append("营收连续下降")

            # 2) 经营现金流为负（原 <0.5 过宽，收紧为负）
            if df_cf is not None and df_inc is not None:
                cf_sorted = df_cf.sort_values('end_date', ascending=False)
                inc_sorted = df_inc.sort_values('end_date', ascending=False)
                if not cf_sorted.empty and not inc_sorted.empty:
                    ocf = cf_sorted.iloc[0].get('cashflow_oper') or 0
                    has_attr = 'n_income_attr_p' in inc_sorted.columns
                    n_col = 'n_income_attr_p' if has_attr else 'n_income'
                    ni = inc_sorted.iloc[0].get(n_col) or 0
                    if ocf < 0 and abs(ni) > 1e-6:
                        anomalies.append("经营现金流为负")

            # 3) ROE 为负（亏损；原 <3% 过宽，微利由 fina_health 覆盖）
            if df_fi is not None and 'roe' in df_fi.columns:
                roe = df_fi['roe'].dropna()
                if not roe.empty and roe.iloc[0] < 0:
                    anomalies.append(f"ROE={roe.iloc[0]:.1f}%<0")

            # 4) 资产负债率 > 90%
            if df_bs is not None:
                bs_sorted = df_bs.sort_values('end_date', ascending=False)
                ta = bs_sorted.iloc[0].get('total_assets') or 0
                tl = bs_sorted.iloc[0].get('total_liab') or 0
                if ta > 0 and tl / ta > 0.9:
                    anomalies.append(f"资产负债率>{tl/ta*100:.0f}%>90%")

            if len(anomalies) >= 2:
                result["detected"] = True
                result["direction"] = -2
                result["confidence"] = min(len(anomalies) / 4, 1.0)
                result["description"] = "多项财务异常: " + "; ".join(anomalies)
        except Exception as e:
            logger.debug("A5 _detect_fraud_sign(%s): %s", ts_code, e)
        return result

    # ══════════════════════════════════════════════════════════
    # B 资本运作
    # ══════════════════════════════════════════════════════════

    def _detect_share_float(self, ts_code: str) -> dict:
        """B1 限售股解禁>5%: share_float 表未入库，返回未检测到"""
        return {"detected": False, "direction": 0, "confidence": 0.0,
                "source": "share_float", "description": "限售股解禁数据未采集",
                "event_date": ""}

    def _detect_pledge_risk(self, ts_code: str) -> dict:
        """B2 质押>50%: pledge_stat 表未入库，返回未检测到"""
        return {"detected": False, "direction": 0, "confidence": 0.0,
                "source": "pledge_stat", "description": "质押数据未采集",
                "event_date": ""}

    def _detect_holder_reduce(self, ts_code: str) -> dict:
        """B3 减持预披露: stk_holdertrade 表未入库，返回未检测到"""
        return {"detected": False, "direction": 0, "confidence": 0.0,
                "source": "stk_holdertrade", "description": "股东减持数据未采集",
                "event_date": ""}

    def _detect_underwater_ipo(self, ts_code: str) -> dict:
        """B4 定增破发: share_float + adj_factor 表未入库，返回未检测到"""
        return {"detected": False, "direction": 0, "confidence": 0.0,
                "source": "share_float+adj_factor", "description": "定增破发检测待接入",
                "event_date": ""}

    def _detect_buyback(self, ts_code: str) -> dict:
        """B5 回购>5000万: repurchase 表未入库，返回未检测到"""
        return {"detected": False, "direction": 0, "confidence": 0.0,
                "source": "repurchase", "description": "回购数据未采集",
                "event_date": ""}

    def _detect_incentive(self, ts_code: str) -> dict:
        """B6 股权激励行权期: stk_rewards 表未入库，返回未检测到"""
        return {"detected": False, "direction": 0, "confidence": 0.0,
                "source": "stk_rewards", "description": "股权激励数据未采集",
                "event_date": ""}

    # ══════════════════════════════════════════════════════════
    # C 监管事件
    # ══════════════════════════════════════════════════════════

    def _detect_regulatory(self, ts_code: str) -> dict:
        """C1 立案调查: 检查 sentiment_pool_cache 异常波动标记"""
        result = {"detected": False, "direction": 0, "confidence": 0.0,
                   "source": "sentiment_pool_cache", "description": "", "event_date": ""}
        try:
            cache = self._get_cache()
            # 查 sentiment_pool 中是否有本股且 reason_category 含立案/调查
            df = cache.get_cached_sentiment_pool()
            if df is None or df.empty:
                return result
            df_stock = df[df['ts_code'] == ts_code]
            if df_stock.empty:
                return result
            # 检查 reason_category 是否含调查/监管关键词
            reason = str(df_stock.iloc[0].get('reason_category', ''))
            keywords = ['立案', '调查', '监管', '警示', '谴责', '处罚']
            if any(k in reason for k in keywords):
                result["detected"] = True
                result["direction"] = -2
                result["confidence"] = 0.8
                result["description"] = f"监管异常: {reason}"
                result["event_date"] = str(df_stock.iloc[0].get('trade_date', ''))
        except Exception as e:
            logger.debug("C1 _detect_regulatory(%s): %s", ts_code, e)
        return result

    def _detect_delist_risk(self, ts_code: str) -> dict:
        """C2 退市风险: 连续10日<1元 or 市值<3亿"""
        result = {"detected": False, "direction": 0, "confidence": 0.0,
                   "source": "daily_cache+daily_basic_cache", "description": "", "event_date": ""}
        try:
            dm = self._get_dm()
            df = dm.get_cached_daily_data(ts_code)
            if df is None or df.empty or len(df) < 10:
                return result

            df_sorted = df.sort_values('trade_date', ascending=False)
            recent = df_sorted.head(10)

            # 检查连续10日收盘<1元
            closes = recent['close'].dropna()
            if len(closes) >= 10 and (closes < 1.0).all():
                result["detected"] = True
                result["direction"] = -2
                result["confidence"] = 0.9
                result["description"] = f"连续10日收盘<1元 (最新{closes.iloc[0]:.2f})"
                result["event_date"] = str(recent.iloc[0]['trade_date'])
                return result

            # 检查市值<3亿
            df_basic = dm.get_cached_daily_basic(ts_code)
            if df_basic is not None and not df_basic.empty:
                mv = df_basic.sort_values('trade_date', ascending=False)
                if 'total_mv' in mv.columns:
                    latest_mv = mv['total_mv'].dropna()
                    if not latest_mv.empty and latest_mv.iloc[0] < 3e4:  # 万元
                        result["detected"] = True
                        result["direction"] = -2
                        result["confidence"] = 0.9
                        result["description"] = f"市值<3亿 (当前{latest_mv.iloc[0]:.0f}万)"
                        result["event_date"] = str(mv.iloc[0]['trade_date'])
        except Exception as e:
            logger.debug("C2 _detect_delist_risk(%s): %s", ts_code, e)
        return result

    def _detect_st_warning(self, ts_code: str) -> dict:
        """C3 ST/*ST 预警: 检查股票名称是否含 ST 标记"""
        result = {"detected": False, "direction": 0, "confidence": 0.0,
                   "source": "Stock ORM", "description": "", "event_date": self._today_str()}
        try:
            dm = self._get_dm()
            info = dm.get_stock_info(ts_code)
            if info is None:
                return result
            name = str(info.get('name', ''))
            if '*ST' in name:
                result["detected"] = True
                result["direction"] = -2
                result["confidence"] = 1.0
                result["description"] = f"*ST 预警: {name}"
            elif '退' in name:
                # 335号 S2.4：退市整理股（名称含"退"）并入 ST 预警（对齐 chip_pre_filter 检测）
                result["detected"] = True
                result["direction"] = -2
                result["confidence"] = 0.95
                result["description"] = f"退市整理: {name}"
            elif 'ST' in name:
                result["detected"] = True
                result["direction"] = -1
                result["confidence"] = 0.8
                result["description"] = f"ST 预警: {name}"
        except Exception as e:
            logger.debug("C3 _detect_st_warning(%s): %s", ts_code, e)
        return result

    def _detect_goodwill_risk(self, ts_code: str) -> dict:
        """C4 商誉暴雷风险检测（Wiki PIERS排雷检查项）

        检查逻辑：
        1. 从 balancesheet_cache 读取 goodwill（商誉）字段
        2. 商誉占总资产比例 > 30% → 高风险
        3. 商誉占净资产比例 > 50% → 极高风险
        """
        result = {"detected": False, "direction": 0, "confidence": 0.0,
                   "source": "balancesheet_cache", "description": "", "event_date": ""}
        try:
            ecm = self._get_dm().cache
            df_bs = ecm.get_cached_balancesheet(ts_code)
            if df_bs is None or df_bs.empty:
                return result

            latest = df_bs.sort_values('end_date', ascending=False).iloc[0]
            goodwill = float(latest.get('goodwill', 0) or 0)
            total_assets = float(latest.get('total_assets', 0) or 0)
            total_equity = float(latest.get('total_equity', 0) or 0)
            event_date = str(latest.get('end_date', ''))

            if goodwill <= 0:
                return result

            # 商誉占总资产比例
            gw_asset_ratio = goodwill / total_assets if total_assets > 0 else 0
            # 商誉占净资产比例
            gw_equity_ratio = goodwill / total_equity if total_equity > 0 else 0

            if gw_equity_ratio > 0.5:
                result["detected"] = True
                result["direction"] = -3
                result["confidence"] = min(gw_equity_ratio, 1.0)
                result["description"] = f"商誉暴雷风险：商誉占净资产{gw_equity_ratio:.0%}（极高风险）"
                result["event_date"] = event_date
            elif gw_asset_ratio > 0.3:
                result["detected"] = True
                result["direction"] = -2
                result["confidence"] = min(gw_asset_ratio, 1.0)
                result["description"] = f"商誉风险：商誉占总资产{gw_asset_ratio:.0%}（高风险）"
                result["event_date"] = event_date
        except Exception as e:
            logger.debug("C4 _detect_goodwill_risk(%s): %s", ts_code, e)
        return result

    # ══════════════════════════════════════════════════════════
    # D 市场情绪
    # ══════════════════════════════════════════════════════════

    def _detect_longhubang(self, ts_code: str) -> dict:
        """D1 龙虎榜: lhb_cache + lhb_detail — 机构净买>5000万"""
        result = {"detected": False, "direction": 0, "confidence": 0.0,
                   "source": "lhb_cache", "description": "", "event_date": ""}
        try:
            cache = self._get_cache()
            df_lhb = cache.get_cached_lhb(ts_code=ts_code)
            if df_lhb is None or df_lhb.empty:
                return result
            latest = df_lhb.sort_values('trade_date', ascending=False).iloc[0]
            net_amount = float(latest.get('net_amount', 0) or 0)
            event_date = str(latest.get('trade_date', ''))

            # 机构净买 > 5000万 → 正向
            if net_amount > 5e3:
                result["detected"] = True
                result["direction"] = 2
                result["confidence"] = min(net_amount / 2e4, 1.0)
                result["description"] = f"龙虎榜机构净买{net_amount/1e4:.0f}万"
                result["event_date"] = event_date

            # 机构净卖 > 5000万 → 负向
            elif net_amount < -5e3:
                result["detected"] = True
                result["direction"] = -2
                result["confidence"] = min(abs(net_amount) / 2e4, 1.0)
                result["description"] = f"龙虎榜机构净卖{abs(net_amount)/1e4:.0f}万"
                result["event_date"] = event_date

            # 也查 lhb_detail 中是否有机构席位
            if not result["detected"]:
                df_detail = cache.get_cached_lhb_detail(ts_code=ts_code)
                if df_detail is not None and not df_detail.empty:
                    detail = df_detail.sort_values('trade_date', ascending=False)
                    latest_detail = detail.iloc[0]
                    det_net = float(latest_detail.get('net_amount', 0) or 0)
                    if abs(det_net) > 5e3:
                        result["detected"] = True
                        result["direction"] = 2 if det_net > 0 else -2
                        result["confidence"] = min(abs(det_net) / 2e4, 1.0)
                        seat = latest_detail.get('seat_name', '')
                        result["description"] = f"龙虎榜席位净{abs(det_net)/1e4:.0f}万 ({seat})"
                        result["event_date"] = str(latest_detail.get('trade_date', ''))
        except Exception as e:
            logger.debug("D1 _detect_longhubang(%s): %s", ts_code, e)
        return result

    def _detect_limit_move(self, ts_code: str) -> dict:
        """D2 涨停/跌停/炸板: daily_cache pct_chg"""
        result = {"detected": False, "direction": 0, "confidence": 0.0,
                   "source": "daily_cache", "description": "", "event_date": ""}
        try:
            dm = self._get_dm()
            df = dm.get_cached_daily_data(ts_code)
            if df is None or df.empty or len(df) < 3:
                return result
            df_sorted = df.sort_values('trade_date', ascending=False)
            latest = df_sorted.iloc[0]
            prev = df_sorted.iloc[1] if len(df_sorted) > 1 else None
            pct_chg = float(latest.get('pct_chg', 0) or 0)
            event_date = str(latest.get('trade_date', ''))

            # 涨停
            if pct_chg >= 9.5:
                # 检查前一日是否涨停（连板）
                prev_limit = False
                if prev is not None:
                    prev_pct = float(prev.get('pct_chg', 0) or 0)
                    prev_limit = prev_pct >= 9.5

                direction = 2
                confidence = 0.8
                desc = "涨停"
                if prev_limit:
                    desc = "连板涨停"
                    direction = 2
                    confidence = 0.9
                result["detected"] = True
                result["direction"] = direction
                result["confidence"] = confidence
                result["description"] = desc
                result["event_date"] = event_date

            # 跌停
            elif pct_chg <= -9.5:
                result["detected"] = True
                result["direction"] = -2
                result["confidence"] = 0.8
                result["description"] = "跌停"
                result["event_date"] = event_date

            # 炸板（盘中涨停后回落）
            elif prev is not None:
                prev_pct = float(prev.get('pct_chg', 0) or 0)
                high = float(latest.get('high', 0) or 0)
                close = float(latest.get('close', 0) or 0)
                prev_close = float(prev.get('close', 0) or 0)
                if prev_close > 0 and (high / prev_close - 1) >= 0.095:
                    # 盘中触涨停但收盘回落
                    if (close / prev_close - 1) < 0.09:
                        result["detected"] = True
                        result["direction"] = -1
                        result["confidence"] = 0.6
                        result["description"] = "炸板（盘中涨停后回落）"
                        result["event_date"] = event_date
        except Exception as e:
            logger.debug("D2 _detect_limit_move(%s): %s", ts_code, e)
        return result

    def _detect_holder_concentration(self, ts_code: str) -> dict:
        """D3 股东户数减少>10%: stk_holder_cache"""
        result = {"detected": False, "direction": 0, "confidence": 0.0,
                   "source": "stk_holder_cache", "description": "", "event_date": ""}
        try:
            cache = self._get_cache()
            df = cache.get_cached_stk_holder(ts_code)
            if df is None or df.empty or len(df) < 2:
                return result
            df_sorted = df.sort_values('end_date', ascending=False)
            latest = df_sorted.iloc[0]
            prev = df_sorted.iloc[1]
            ln = float(latest.get('holder_number', 0) or 0)
            pn = float(prev.get('holder_number', 0) or 0)
            if pn <= 0:
                return result
            change = (ln - pn) / pn
            event_date = str(latest.get('end_date', ''))

            if change <= -0.10:
                result["detected"] = True
                result["direction"] = 1
                result["confidence"] = min(abs(change) * 3, 1.0)
                result["description"] = f"股东户数减少{abs(change)*100:.0f}% (集中)"
                result["event_date"] = event_date
            elif change >= 0.20:
                result["detected"] = True
                result["direction"] = -1
                result["confidence"] = min(change * 2, 1.0)
                result["description"] = f"股东户数增加{change*100:.0f}% (分散)"
                result["event_date"] = event_date
        except Exception as e:
            logger.debug("D3 _detect_holder_concentration(%s): %s", ts_code, e)
        return result

    def _detect_margin_risk(self, ts_code: str) -> dict:
        """D4 融资余额增加>20%: margin_cache"""
        result = {"detected": False, "direction": 0, "confidence": 0.0,
                   "source": "margin_cache", "description": "", "event_date": ""}
        try:
            cache = self._get_cache()
            df = cache.get_cached_margin(ts_code)
            if df is None or df.empty or len(df) < 5:
                return result
            df_sorted = df.sort_values('trade_date', ascending=False)
            # 最近5日平均 vs 之前5日平均
            recent = df_sorted.head(5)
            older = df_sorted.iloc[5:10]
            if len(older) < 3:
                return result

            recent_avg = recent['rzye'].dropna().mean()
            older_avg = older['rzye'].dropna().mean()
            if pd.isna(recent_avg) or pd.isna(older_avg) or older_avg <= 0:
                return result

            change = (recent_avg - older_avg) / older_avg
            event_date = str(df_sorted.iloc[0].get('trade_date', ''))

            if change >= 0.20:
                result["detected"] = True
                result["direction"] = 1
                result["confidence"] = min(change, 1.0)
                result["description"] = f"融资余额增加{change*100:.0f}% (>20%)"
                result["event_date"] = event_date
            elif change <= -0.15:
                result["detected"] = True
                result["direction"] = -1
                result["confidence"] = min(abs(change), 1.0)
                result["description"] = f"融资余额减少{abs(change)*100:.0f}% (>15%)"
                result["event_date"] = event_date
        except Exception as e:
            logger.debug("D4 _detect_margin_risk(%s): %s", ts_code, e)
        return result

    # ══════════════════════════════════════════════════════════
    # E 特殊事件
    # ══════════════════════════════════════════════════════════

    def _detect_breakout(self, ts_code: str) -> dict:
        """E1 突破形态: 量价突破（站上60日线+放量+创20日新高）"""
        result = {"detected": False, "direction": 0, "confidence": 0.0,
                   "source": "daily_cache", "description": "", "event_date": ""}
        try:
            dm = self._get_dm()
            df = dm.get_cached_daily_data(ts_code)
            if df is None or df.empty or len(df) < 60:
                return result
            df_sorted = df.sort_values('trade_date').reset_index(drop=True)
            closes = df_sorted['close'].values
            volumes = df_sorted['vol'].values

            if len(closes) < 60:
                return result

            cur_close = closes[-1]

            # MA60
            ma60 = np.mean(closes[-60:])

            # 站上 MA60
            above_ma60 = cur_close > ma60 * 1.02

            # 量比 >1.5（近5日均量 vs 近20日均量）
            vol_ma5 = np.mean(volumes[-5:])
            vol_ma20 = np.mean(volumes[-20:])
            vol_ratio = vol_ma5 / max(vol_ma20, 1)
            volume_surge = vol_ratio > 1.5

            # 创20日新高
            new_high = cur_close >= np.max(closes[-20:-1]) * 0.99

            factors = sum([above_ma60, volume_surge, new_high])
            if factors >= 2:
                result["detected"] = True
                result["direction"] = 1 if cur_close > ma60 else -1
                result["confidence"] = factors / 3.0
                parts = []
                if above_ma60:
                    parts.append("站上60日线")
                if volume_surge:
                    parts.append(f"放量{vol_ratio:.1f}倍")
                if new_high:
                    parts.append("20日新高")
                result["description"] = "突破: " + "+".join(parts)
                result["event_date"] = str(df_sorted.iloc[-1]['trade_date'])
        except Exception as e:
            logger.debug("E1 _detect_breakout(%s): %s", ts_code, e)
        return result

    def _detect_concept_heat(self, ts_code: str) -> dict:
        """E2 概念热度: 概念板块热度排名升20位
        第一阶段简化：检查概念所属板块数 > 3 标记为活跃概念股。
        """
        result = {"detected": False, "direction": 0, "confidence": 0.0,
                   "source": "concept_cache", "description": "", "event_date": ""}
        try:
            cache = self._get_cache()
            df = cache.get_cached_concept(ts_code)
            if df is None or df.empty:
                return result
            # 股票拥有的概念数
            n_concepts = len(df)
            # 全市场概念分布 → 找出该股票所属概念中成员最多的
            all_concepts = cache.get_cached_concept()
            if all_concepts is None or all_concepts.empty:
                return result
            concept_counts = all_concepts['concept_name'].value_counts()
            # 计算该股票所属概念的平均热度排名
            stock_concepts = df['concept_name'].unique()
            ranks = []
            for i, (cname, cnt) in enumerate(concept_counts.items()):
                if cname in stock_concepts:
                    ranks.append(i + 1)
            if not ranks:
                return result
            avg_rank = sum(ranks) / len(ranks)
            # 概念数量 > 3 且平均排名在前50% → 概念活跃
            if n_concepts > 3 and avg_rank <= len(concept_counts) / 2:
                result["detected"] = True
                result["direction"] = 1
                result["confidence"] = 0.5
                result["description"] = f"概念活跃({n_concepts}个概念, 平均排名第{avg_rank:.0f})"
        except Exception as e:
            logger.debug("E2 _detect_concept_heat(%s): %s", ts_code, e)
        return result

    # ══════════════════════════════════════════════════════════
    # 新闻质量过滤（P2.1 第一阶段简化版）
    # ══════════════════════════════════════════════════════════

    def _news_quality_filter(self, event_type: str, event: dict) -> float:
        """新闻质量过滤，返回 0~1 质量分
        仅 D 类事件（D1/D2）需要过滤：

        Phase 1 简化三因子:
        1) 来源分级（默认0.7~1.0，当前统一给 0.9）
        2) 蹭热点检测: 描述含敏感词→折扣
        3) 旧闻检测: event_date 早于3日→折扣
        """
        if event_type not in ('longhubang', 'limit_move'):
            return 1.0

        score = 0.9  # 基础分

        # 蹭热点检测
        desc = event.get('description', '')
        clickbait_keywords = ['突发', '重磅', '紧急', '震惊', '大利好', '大利空',
                              '抄底', '逃顶', '速看', '涨停板敢死队']
        for kw in clickbait_keywords:
            if kw in desc:
                score *= 0.8
                break

        # 旧闻检测（event_date 早于3天前）
        event_date_str = event.get('event_date', '')
        if event_date_str:
            try:
                ed = self._date_from_str(event_date_str)
                if ed is not None:
                    delta = (datetime.now().date() - ed).days
                    if delta > 3:
                        score *= 0.5
                    elif delta > 1:
                        score *= 0.8
            except Exception:
                pass

        return max(0.0, min(1.0, score))

    # ══════════════════════════════════════════════════════════
    # 主入口
    # ══════════════════════════════════════════════════════════

    def detect_all(self, ts_code: str) -> dict:
        """全量检测 20 类事件

        Returns:
            events: 所有检测到的事件列表
            event_composite_score: -5 ~ +5
            event_calendar_upcoming: 日历事件（待定）
            news_quality_score: 0-1
            catalyst_event: 催化剂事件类型
            catalyst_impact: 'high'|'medium'|'low'
            upward_driver: 上涨驱动力类型
        """
        # ── 各维度事件检测 ──
        detectors = [
            # A 财务
            ('earnings_surprise', self._detect_earnings_surprise),
            ('earnings_confirm', self._detect_earnings_confirm),
            ('report_date', self._detect_report_date),
            ('dividend', self._detect_dividend),
            ('fraud_sign', self._detect_fraud_sign),
            # B 资本运作
            ('share_float', self._detect_share_float),
            ('pledge_risk', self._detect_pledge_risk),
            ('holder_reduce', self._detect_holder_reduce),
            ('underwater_ipo', self._detect_underwater_ipo),
            ('buyback', self._detect_buyback),
            ('incentive', self._detect_incentive),
            # C 监管
            ('regulatory', self._detect_regulatory),
            ('delist_risk', self._detect_delist_risk),
            ('st_warning', self._detect_st_warning),
            # D 市场情绪
            ('longhubang', self._detect_longhubang),
            ('limit_move', self._detect_limit_move),
            ('holder_concentration', self._detect_holder_concentration),
            ('margin_risk', self._detect_margin_risk),
            # E 特殊
            ('breakout', self._detect_breakout),
            ('concept_heat', self._detect_concept_heat),
        ]

        events: list[dict] = []
        dim_max: dict[str, int] = {'A': 0, 'B': 0, 'C': 0, 'D': 0, 'E': 0}
        dim_direction: dict[str, int] = {'A': 0, 'B': 0, 'C': 0, 'D': 0, 'E': 0}
        quality_scores: list[float] = []

        for event_name, detect_fn in detectors:
            try:
                event = detect_fn(ts_code)
            except Exception as e:
                logger.warning("事件检测 %s(%s) 异常: %s", event_name, ts_code, e)
                event = {"detected": False, "direction": 0, "confidence": 0.0,
                          "source": event_name, "description": "", "event_date": ""}

            if event.get('detected'):
                # 新闻质量过滤（仅 D1/D2）
                event_type_key = event_name
                q = self._news_quality_filter(event_type_key, event)
                quality_scores.append(q)

                if event_type_key in ('longhubang', 'limit_move'):
                    if q < 0.3:
                        # 不进入评分，仅保留展示
                        event['confidence'] = 0.0
                    elif q < 0.7:
                        # 折扣
                        event['confidence'] *= q
                        event['description'] += " [质量折扣]"

                events.append({
                    'event_type': event_name,
                    **event,
                })

                # 更新维度极值
                prefix = _event_dim_prefix(event_name)
                abs_dir = abs(event['direction'])
                if abs_dir > abs(dim_max[prefix]):
                    dim_max[prefix] = abs_dir
                    dim_direction[prefix] = _direction_to_sign(event['direction'])

        # ── 评分合并 ──
        max_abs = 0
        composite_direction = 0
        for prefix in ['A', 'B', 'C', 'D', 'E']:
            if dim_max[prefix] > max_abs:
                max_abs = dim_max[prefix]
                composite_direction = dim_direction[prefix] if dim_direction[prefix] != 0 else 1

        event_composite_score = composite_direction * max_abs if max_abs > 0 else 0

        # ── 新闻综合质量分 ──
        news_quality_score = float(np.mean(quality_scores)) if quality_scores else 1.0

        # ── catalyst 判定（取 abs 最大的事件的类型） ──
        catalyst_event = 'none'
        catalyst_impact: str = 'low'
        best_abs = 0
        for ev in events:
            if abs(ev.get('direction', 0)) > best_abs:
                best_abs = abs(ev['direction'])
                catalyst_event = CATALYST_EVENT_MAP.get(ev.get('event_type', ''), 'none')
        if best_abs >= 2:
            catalyst_impact = 'high'
        elif best_abs >= 1:
            catalyst_impact = 'medium'

        # ── 上涨驱动力判定（upward_driver, 295号§3.4 标签25） ──
        if catalyst_event in ('earnings', 'lhb', 'buyback'):
            upward_driver = 'info_driven'
        elif catalyst_event in ('breakout',):
            upward_driver = 'emotion_driven'
        elif catalyst_event in ('concept',):
            upward_driver = 'emotion_driven'
        elif catalyst_event == 'none':
            upward_driver = 'no_upward'
        else:
            upward_driver = 'mixed'

        return {
            'events': events,
            'event_composite_score': event_composite_score,
            'event_calendar_upcoming': [],
            'news_quality_score': round(news_quality_score, 2),
            'catalyst_event': catalyst_event,
            'catalyst_impact': catalyst_impact,
            'upward_driver': upward_driver,
        }

    def compute_tags(self, ts_code: str) -> dict:
        """事件监控标签（供 opportunity_tags_cache 落库使用）"""
        try:
            result = self.detect_all(ts_code)
        except Exception as e:
            logger.error("EventMonitor.compute_tags(%s) 失败: %s", ts_code, e)
            return {
                'catalyst_event': 'none',
                'catalyst_impact': 'low',
                'event_composite_score': 0,
            }

        tags: dict[str, Any] = {
            'catalyst_event': result['catalyst_event'],
            'catalyst_impact': result['catalyst_impact'],
            'event_composite_score': result['event_composite_score'],
            'upward_driver': result.get('upward_driver', 'no_upward'),
        }

        # 写事件摘要（最多3条）
        events = result.get('events', [])
        if events:
            event_summaries = []
            for ev in events[:3]:
                desc = ev.get('description', '')
                if desc:
                    event_summaries.append(desc)
            if event_summaries:
                tags['event_summary'] = '; '.join(event_summaries)

        return tags


# === cscv_validator.py ===
def calculate_sharpe(returns: np.ndarray, annual_factor: float = 252.0) -> float:
    """
    计算年化夏普比率。

    Parameters
    ----------
    returns : np.ndarray
        日收益率序列。
    annual_factor : float, default=252.0
        年化因子（日频数据默认 252）。

    Returns
    -------
    float
        年化夏普比率。若收益率序列长度 < 2 或标准差为零，返回 0.0。
    """
    if len(returns) < 2:
        return 0.0
    std = np.std(returns, ddof=1)
    if std == 0.0 or np.isnan(std):
        return 0.0
    mean = np.mean(returns)
    return (mean / std) * np.sqrt(annual_factor)


# ── 主类 ──────────────────────────────────────────────────────────────


class CSCVValidator:
    """
    Combinatorial Symmetric Cross-Validation (CSCV) 验证器。

    用于评估策略参数优化中的过拟合风险，输出 PBO 指标。

    Parameters
    ----------
    n_splits : int, default=6
        时间序列划分块数 S。必须为偶数，且 >= 4。
    random_state : int, optional, default=42
        随机种子，用于结果复现。
    """

    def __init__(self, n_splits: int = 6, random_state: int = 42) -> None:
        if n_splits < 4:
            raise ValueError("n_splits 必须 >= 4")
        if n_splits % 2 != 0:
            raise ValueError("n_splits 必须为偶数（标准 CSCV 要求 S/2 为整数）")
        self.n_splits = n_splits
        self.random_state = random_state
        np.random.seed(random_state)

    # ── 公共方法 ──────────────────────────────────────────────────────

    def compute_pbo(self, sharpe_matrix: np.ndarray) -> Dict[str, Any]:
        """
        基于夏普比率矩阵计算 PBO。

        Parameters
        ----------
        sharpe_matrix : np.ndarray, shape (n_configs, n_splits)
            sharpe_matrix[i][j] 表示第 i 个参数配置在第 j 个测试块上的夏普比率。
            矩阵必须为非空且行列数符合要求。

        Returns
        -------
        Dict[str, Any]
            包含以下字段:
            - pbo: float, 概率性回测过拟合指标
            - is_robust: bool, 是否鲁棒
            - n_configs: int, 参数配置数
            - n_splits: int, 划分块数
            - n_combos: int, 实际计算的组合数
            - rank_matrix: np.ndarray, shape (n_combos, n_configs), 各组合下各参数配置的排名
            - best_rank_oos: np.ndarray, shape (n_combos,), 各组合下最优参数的 OOS 排名
            - rank_below_median: int, 最优参数排名低于中位数的次数
        """
        n_configs, n_splits = sharpe_matrix.shape
        if n_configs < 1 or n_splits < 2:
            return self._empty_result(n_configs, n_splits)

        if n_splits != self.n_splits:
            self.n_splits = n_splits  # 自适应

        train_size = self.n_splits // 2
        split_indices = list(range(self.n_splits))
        combos = list(itertools.combinations(split_indices, train_size))
        n_combos = len(combos)

        rank_matrix = np.zeros((n_combos, n_configs), dtype=float)
        best_rank_oos = np.zeros(n_combos, dtype=float)

        for c_idx, train_splits in enumerate(combos):
            train_set = set(train_splits)
            test_splits = [i for i in split_indices if i not in train_set]

            # 训练集: 取各配置在训练块上的平均夏普 → 选最优配置
            train_sharpes = np.mean(sharpe_matrix[:, list(train_set)], axis=1)
            best_config = int(np.argmax(train_sharpes))

            # 测试集: 取各配置在测试块上的平均夏普 → 排秩（1=最好）
            test_sharpes = np.mean(sharpe_matrix[:, test_splits], axis=1)
            # 夏普越高，秩越小（rank=1 最高）
            ranks = np.argsort(np.argsort(-test_sharpes)) + 1
            rank_matrix[c_idx, :] = ranks

            # 记录最优配置在测试集中的排名
            best_rank_oos[c_idx] = ranks[best_config]

        # PBO = 最优配置在测试集中排名低于中位数的比例
        median_rank = (n_configs + 1) / 2.0
        rank_below_median = int(np.sum(best_rank_oos > median_rank))
        pbo = rank_below_median / n_combos if n_combos > 0 else 1.0

        return {
            "pbo": float(pbo),
            "is_robust": self.is_robust(pbo),
            "n_configs": n_configs,
            "n_splits": self.n_splits,
            "n_combos": n_combos,
            "rank_matrix": rank_matrix,
            "best_rank_oos": best_rank_oos,
            "rank_below_median": rank_below_median,
        }

    def evaluate(
        self,
        returns: np.ndarray,
        param_configs: List[Any],
        param_func: Callable[[np.ndarray, Any], float],
    ) -> Dict[str, Any]:
        """
        便捷包装器: 直接传入收益率序列和参数配置列表，自动完成 CSCV 分析。

        Parameters
        ----------
        returns : np.ndarray, shape (n_obs,)
            全样本收益率序列。
        param_configs : List[Any]
            参数配置列表，每个元素会传给 param_func 作为第二个参数。
        param_func : Callable[[np.ndarray, Any], float]
            接收 (returns_subset, param) 返回夏普比率的函数。

        Returns
        -------
        Dict[str, Any]
            包含 compute_pbo 返回的所有字段，额外包含 returns_shape。
        """
        n_obs = len(returns)
        if n_obs < self.n_splits:
            return {
                "pbo": 1.0,
                "is_robust": False,
                "n_configs": len(param_configs),
                "n_splits": self.n_splits,
                "n_combos": 0,
                "error": "收益率序列长度不足以进行划分",
                "returns_shape": returns.shape,
            }

        splits = np.array_split(returns, self.n_splits)
        n_configs = len(param_configs)
        sharpe_matrix = np.zeros((n_configs, self.n_splits), dtype=float)

        for j in range(self.n_splits):
            for i, param in enumerate(param_configs):
                sharpe_matrix[i, j] = param_func(splits[j], param)

        result = self.compute_pbo(sharpe_matrix)
        result["returns_shape"] = returns.shape
        return result

    @staticmethod
    def is_robust(pbo: float, threshold: float = 0.05) -> bool:
        """
        判断 PBO 是否在可接受阈值内。

        Parameters
        ----------
        pbo : float
            概率性回测过拟合指标。
        threshold : float, default=0.05
            阈值。PBO < threshold 认为策略鲁棒。

        Returns
        -------
        bool
            True 表示策略鲁棒，过拟合风险低。
        """
        return pbo < threshold

    @staticmethod
    def simulate_backtest_sharpes(n_params: int, n_splits: int = 6) -> np.ndarray:
        """
        生成用于测试的合成夏普比率矩阵。

        前一半参数配置为"真实有效"（夏普较高），后一半为"随机噪音"（夏普通近零）。
        用于验证 PBO 计算逻辑。

        Parameters
        ----------
        n_params : int
            参数配置数量。
        n_splits : int, default=6
            划分块数。

        Returns
        -------
        np.ndarray, shape (n_params, n_splits)
            合成的夏普比率矩阵。
        """
        np.random.seed(42)
        sharpe_matrix = np.zeros((n_params, n_splits), dtype=float)

        half = max(1, n_params // 2)

        # 前一半: 真实有效策略，各块间有一定波动
        for i in range(half):
            base_sharpe = np.random.uniform(0.8, 1.5)
            noise = np.random.normal(0, 0.15, n_splits)
            sharpe_matrix[i, :] = base_sharpe + noise

        # 后一半: 噪音策略，夏普通近零
        for i in range(half, n_params):
            sharpe_matrix[i, :] = np.random.normal(0, 0.2, n_splits)

        return sharpe_matrix

    # ── 内部方法 ──────────────────────────────────────────────────────

    def _empty_result(self, n_configs: int, n_splits: int) -> Dict[str, Any]:
        """返回空结果（用于边缘情况）。"""
        return {
            "pbo": 1.0,
            "is_robust": False,
            "n_configs": n_configs,
            "n_splits": n_splits,
            "n_combos": 0,
            "rank_matrix": np.empty((0, max(n_configs, 1))),
            "best_rank_oos": np.empty(0),
            "rank_below_median": 0,
            "error": "数据不足: 参数配置或划分块数不足",
        }


# ── 模块级便捷函数 ─────────────────────────────────────────────────────


def compute_cscv_pbo(
    returns: np.ndarray,
    param_configs: List[Any],
    param_func: Callable[[np.ndarray, Any], float],
    n_splits: int = 6,
) -> Dict[str, Any]:
    """
    一键计算 CSCV PBO 的模块级函数。

    等价于:
        validator = CSCVValidator(n_splits=n_splits)
        return validator.evaluate(returns, param_configs, param_func)

    Parameters
    ----------
    returns : np.ndarray
        全样本收益率序列。
    param_configs : List[Any]
        参数配置列表。
    param_func : Callable[[np.ndarray, Any], float]
        接收 (returns_subset, param) 返回夏普比率的函数。
    n_splits : int, default=6
        划分块数。

    Returns
    -------
    Dict[str, Any]
        CSCV 分析结果字典。
    """
    validator = CSCVValidator(n_splits=n_splits)
    return validator.evaluate(returns, param_configs, param_func)


# === eagle_sword_resonance.py ===
class EagleSwordResonance:
    """
    "鹰眼大宝剑" 双系统共振模型

    鹰眼 = 趋势系统（缠论方向 + 量价强度）
    大宝剑 = 情绪系统（BOCIASI 快慢线 + 拥挤度）
    """

    # ──────────────
    # 鹰眼系统
    # ──────────────

    @staticmethod
    def _eagle_trend_direction(chanlun_result: Dict) -> str:
        """
        从缠论结果提取趋势方向

        Args:
            chanlun_result: ChanlunAnalyzer.analyze() 的返回 dict,
                            包含键 'trend' (str), 'segments' (List), 'zhongshu' (List)

        Returns:
            'UP' | 'DOWN' | 'RANGING' | 'UNKNOWN'
        """
        trend = chanlun_result.get("trend", "unknown")
        if trend == "up":
            return "UP"
        if trend == "down":
            return "DOWN"

        segments = chanlun_result.get("segments", [])
        # 平均笔数低 + 无中枢 → RANGING
        if not segments:
            return "RANGING"

        zhongshu_list = chanlun_result.get("zhongshu", [])
        if not zhongshu_list:
            return "RANGING"

        return "RANGING"

    @staticmethod
    def _eagle_trend_strength(volume_price_signal: Dict) -> float:
        """
        从量价信号提取趋势强度 (0.0 ~ 1.0)

        考量因素:
          - MA 排列 (多头发散 / 空头发散 / 交叉 / 粘合)
          - 格兰维尔信号 (buy1~4, sell1~4)
          - 量价关系置信度

        Args:
            volume_price_signal: volume_price_strategy 的 to_output_dict() 结果

        Returns:
            float: 0.0 ~ 1.0
        """
        strength = 0.5  # 中性基准

        # --- MA 排列 ---
        status = volume_price_signal.get("status_recognition", {})
        trend = status.get("trend", {})
        direction = trend.get("direction", "")
        ma_stage = trend.get("stage", "")
        strength_label = trend.get("strength", "")

        # 趋势方向和力度
        if direction == "up" and strength_label in ("strong", "moderate"):
            strength += 0.15
        elif direction == "down" and strength_label in ("strong", "moderate"):
            strength -= 0.15

        # --- 格兰维尔信号 ---
        evidence = volume_price_signal.get("evidence", [])
        granville_buy_count = sum(1 for e in evidence if "格兰维尔" in e and "买" in e)
        granville_sell_count = sum(1 for e in evidence if "格兰维尔" in e and "卖" in e)

        if granville_buy_count > 0:
            strength += min(0.20, granville_buy_count * 0.10)
        if granville_sell_count > 0:
            strength -= min(0.20, granville_sell_count * 0.10)

        # --- 量价置信度 ---
        conf = volume_price_signal.get("confidence", 0.5)
        if conf > 0.6:
            strength += 0.10
        elif conf < 0.3:
            strength -= 0.10

        return max(0.0, min(1.0, strength))

    @staticmethod
    def _eagle_granville_signals(volume_price_signal: Dict) -> List[str]:
        """提取格兰维尔信号列表"""
        evidence = volume_price_signal.get("evidence", [])
        return [e for e in evidence if "格兰维尔" in e]

    # ──────────────
    # 大宝剑系统
    # ──────────────

    @staticmethod
    def _sword_sentiment(bociasi_quick: Dict, bociasi_slow: Dict) -> str:
        """
        聚合快慢线情绪信号

        Args:
            bociasi_quick:  BociasiQuickLine.evaluate() 返回
            bociasi_slow:   BociasiSlowLine.evaluate() 返回

        Returns:
            'BULLISH' | 'BEARISH' | 'NEUTRAL'
        """
        quick_signal = bociasi_quick.get("signal", "NEUTRAL")
        quick_conf = bociasi_quick.get("confidence", 0.0)

        slow_signal = bociasi_slow.get("signal", "NEUTRAL")
        slow_conf = bociasi_slow.get("confidence", 0.0)

        # 加权投票: 快线权重 0.6, 慢线权重 0.4
        bullish_score = 0.0
        bearish_score = 0.0

        if quick_signal == "BUY":
            bullish_score += 0.6 * quick_conf
        elif quick_signal == "NEUTRAL":
            pass  # 不贡献分数
        # quick 没有 BEARISH，只有 BUY/WATCH/NEUTRAL，WATCH 按中性处理

        if slow_signal == "BULLISH":
            bullish_score += 0.4 * slow_conf
        elif slow_signal == "BEARISH":
            bearish_score += 0.4 * slow_conf

        if bullish_score > bearish_score and bullish_score >= 0.20:
            return "BULLISH"
        if bearish_score > bullish_score and bearish_score >= 0.20:
            return "BEARISH"
        return "NEUTRAL"

    @staticmethod
    def _sword_crowding_warning(crowding_factor: Dict) -> bool:
        """
        拥挤度预警

        Args:
            crowding_factor: crowding_factor 模块的输出 dict,
                             应包含 'crowding_level' (str) 或 'risk_notes'

        Returns:
            True if 拥挤度过高
        """
        level = crowding_factor.get("crowding_level", "LOW")
        return level in ("HIGH", "EXTREME")

    @staticmethod
    def _sword_sentiment_strength(bociasi_quick: Dict, bociasi_slow: Dict) -> float:
        """情绪强度 0.0 ~ 1.0"""
        quick_conf = bociasi_quick.get("confidence", 0.0)
        slow_conf = bociasi_slow.get("confidence", 0.0)
        return round((quick_conf * 0.6 + slow_conf * 0.4), 2)

    # ──────────────
    # 共振判定
    # ──────────────

    def evaluate(
        self,
        chanlun_result: Dict,
        volume_price_signal: Dict,
        bociasi_quick: Dict,
        bociasi_slow: Dict,
        crowding: Dict,
        market_state: str = "UNKNOWN",
        kronos_result: Optional[Dict] = None,
    ) -> Dict:
        """
        双系统共振判定

        Args:
            chanlun_result:     缠论分析结果 dict
            volume_price_signal: 量价分析结果 dict (to_output_dict 格式)
            bociasi_quick:       BOCIASI 快线结果 dict
            bociasi_slow:        BOCIASI 慢线结果 dict
            crowding:            拥挤度结果 dict
            market_state:        大盘状态 ('BULL', 'BEAR', 'RANGING', 'UNKNOWN')
            kronos_result:       Kronos预测结果 dict（可选，增强鹰眼前瞻）

        Returns:
            {
                'action': str,
                'confidence': float,
                'eagle_system': {...},
                'sword_system': {...},
                'resonance_detail': {...},
                'signal_label': str,
                'risk_notes': List[str],
            }
        """
        # --- 鹰眼系统 ---
        eagle_direction = self._eagle_trend_direction(chanlun_result)
        eagle_strength = self._eagle_trend_strength(volume_price_signal)
        granville_signals = self._eagle_granville_signals(volume_price_signal)

        # --- Kronos前瞻鹰眼（融合点3）---
        kronos_forward_conf = None
        if kronos_result:
            kronos_dir = kronos_result.get('direction', 'neutral')
            kronos_strength = kronos_result.get('trend_strength', 0.0)
            if kronos_strength > 0.4:
                if kronos_dir == eagle_direction.lower():
                    kronos_forward_conf = 'confirm'
                    eagle_strength = min(1.0, eagle_strength + 0.10)
                else:
                    kronos_forward_conf = 'conflict'
                    eagle_strength = max(0.0, eagle_strength - 0.15)

        # --- 大宝剑系统 ---
        sword_sentiment = self._sword_sentiment(bociasi_quick, bociasi_slow)
        crowding_warning = self._sword_crowding_warning(crowding)
        sentiment_strength = self._sword_sentiment_strength(bociasi_quick, bociasi_slow)

        # --- 共振查表 ---
        eagle_routing = _RESONANCE_TABLE.get(eagle_direction, {})
        action, base_conf = eagle_routing.get(
            sword_sentiment, _FALLBACK_ACTION
        )

        # --- 置信度微调 ---
        confidence = base_conf
        risk_notes: List[str] = []

        # 鹰眼强度修正
        if eagle_strength > 0.7:
            confidence += 0.05
        elif eagle_strength < 0.3:
            confidence -= 0.05

        # 情绪强度修正
        if sentiment_strength > 0.65:
            confidence += 0.05
        elif sentiment_strength < 0.25:
            confidence -= 0.05

        # 拥挤度预警
        if crowding_warning:
            confidence -= 0.10
            risk_notes.append("拥挤度过高，警惕反转风险")

        # Kronos前瞻预警
        if kronos_forward_conf == 'conflict':
            risk_notes.append("Kronos前瞻与鹰眼方向冲突，注意可能拐点")
        elif kronos_forward_conf == 'confirm':
            risk_notes.append("Kronos前瞻确认鹰眼方向")

        # 大盘状态修正
        if market_state == "BEAR" and action in ("BUY", "WATCH_BUY", "CAUTIOUS_BUY"):
            confidence -= 0.10
            risk_notes.append("大盘偏空，多头信号降权")
        elif market_state == "BULL" and action in ("SELL", "WATCH_SELL", "CAUTIOUS_SELL"):
            confidence -= 0.10
            risk_notes.append("大盘偏多，空头信号降权")

        # 格兰维尔反向信号修正
        has_buy_granville = any("买" in g for g in granville_signals)
        has_sell_granville = any("卖" in g for g in granville_signals)
        if has_buy_granville and action in ("SELL", "WATCH_SELL"):
            confidence -= 0.05
            risk_notes.append("格兰维尔买点与空头方向冲突")
        if has_sell_granville and action in ("BUY", "WATCH_BUY"):
            confidence -= 0.05
            risk_notes.append("格兰维尔卖点与多头方向冲突")

        confidence = max(0.0, min(1.0, round(confidence, 2)))

        # --- 信号标签 ---
        signal_label = self._signal_label(action, eagle_direction, sword_sentiment)

        eagle_state = f"{eagle_direction}(strength={eagle_strength:.2f})"
        sword_state = f"{sword_sentiment}(strength={sentiment_strength:.2f})"

        return {
            "action": action,
            "confidence": confidence,
            "eagle_system": {
                "direction": eagle_direction,
                "strength": eagle_strength,
                "granville_signals": granville_signals,
            },
            "sword_system": {
                "sentiment": sword_sentiment,
                "crowding_warning": crowding_warning,
                "sentiment_strength": sentiment_strength,
            },
            "resonance_detail": {
                "eagle_state": eagle_state,
                "sword_state": sword_state,
                "resonant": action not in ("CONFLICT", "NEUTRAL"),
            },
            "signal_label": signal_label,
            "risk_notes": risk_notes,
        }

    # ──────────────
    # 辅助
    # ──────────────

    @staticmethod
    def _signal_label(action: str, eagle_dir: str, sword_sent: str) -> str:
        """生成中文信号标签"""
        labels = {
            "BUY":           "共振买入",
            "SELL":          "共振卖出",
            "WATCH_BUY":     "关注买入",
            "WATCH_SELL":    "关注卖出",
            "CAUTIOUS_BUY":  "谨慎买入",
            "CAUTIOUS_SELL": "谨慎卖出",
            "CONFLICT":      "信号冲突",
            "NEUTRAL":       "无明确信号",
        }
        label = labels.get(action, action)
        if action == "CONFLICT":
            label += f" (鹰眼={eagle_dir}, 大宝剑={sword_sent})"
        return label


def evaluate(
    chanlun_result: Dict,
    volume_price_signal: Dict,
    bociasi_quick: Dict,
    bociasi_slow: Dict,
    crowding: Dict,
    market_state: str = "UNKNOWN",
) -> Dict:
    """
    模块级便捷函数: 单次鹰眼大宝剑共振判定

    用法::
        from app.engine.framework.eagle_sword_resonance import evaluate
        result = evaluate(
            chanlun_result=chanlun_analysis,
            volume_price_signal=vp_signal,
            bociasi_quick=quick_result,
            bociasi_slow=slow_result,
            crowding=crowding_result,
            market_state='RANGING',
        )
    """
    return EagleSwordResonance().evaluate(
        chanlun_result=chanlun_result,
        volume_price_signal=volume_price_signal,
        bociasi_quick=bociasi_quick,
        bociasi_slow=bociasi_slow,
        crowding=crowding,
        market_state=market_state,
    )


class Dim6RiskEngine(DataAwareMixin):
    """第6维 风险边界引擎 — 风险分级 + 几何化距离 + 波动率 + 事件监控"""

    def __init__(self):
        self._dm = None

    def evaluate(self, dims: dict, tags: dict, signals: dict = None,
                 lifecycle: dict = None) -> dict:
        """统一评估入口"""
        ecm = self._get_dm().cache
        ts_code = tags.get('ts_code', '')

        # 加载日线数据
        try:
            df = ecm.get_cached_daily(ts_code)
        except Exception:
            df = None

        # 1. 风险等级
        l0 = dims.get('l0', {}) if isinstance(dims.get('l0'), dict) else {}
        risk_info = _assess_risk_level(dims, l0, tags)
        risk_factors = _list_risk_factors(tags, dims, l0)

        # 1b. EventMonitor 事件风险检测（28个检测方法 + 商誉暴雷）
        event_risks = []
        try:
            monitor = EventMonitor()
            em_tags = monitor.compute_tags(ts_code)
            if em_tags:
                # 检查事件风险标签
                for risk_key in EVENT_RISK_SET:
                    if em_tags.get(risk_key):
                        event_risks.append({'category': '事件风险', 'factor': risk_key,
                                            'severity': '高', 'satisfied': True})
                # 检查商誉暴雷
                gw = self._detect_goodwill_risk(ts_code)
                if gw.get('detected'):
                    event_risks.append({'category': '商誉风险', 'factor': gw.get('description', ''),
                                        'severity': '高', 'satisfied': True})
                # 如果检测到高风险事件，升级风险等级
                if event_risks and risk_info['level'] not in ('高', '极高'):
                    risk_info = {'level': '高', 'light': 'red',
                                 'detail': f"事件风险：{event_risks[0]['factor']}"}
        except Exception as e:
            logger.debug(f"EventMonitor检测跳过: {e}")

        # 合并事件风险到风险因素列表
        risk_factors.extend(event_risks)

        # 2. 几何化指标
        geo = calc_geometric(df) if df is not None and not df.empty else {
            'dist_to_support_pct': None, 'dist_to_resistance_pct': None,
            'risk_reward': None, 'signal_days': None, 'support_price': None, 'resistance_price': None,
        }

        # 3. 盈亏比
        rr_info = _assess_rr(geo)

        # 4. 波动率
        vol_info = _calc_volatility(df, tags)

        # 5. 失效条件
        invalidation = _build_invalidation(geo.get('support_price'), tags, dims)

        # 6. status_description
        plain = _risk_plain(risk_info['level'], risk_factors, geo, rr_info, vol_info, invalidation)
        status_description = {
            'risk_level': f"{risk_info['level']}（{risk_info['detail']}）",
            'risk_factors': [f"{f['category']}：{f['factor']}（{f['severity']}）"
                             for f in risk_factors if f.get('satisfied')],
            'support_resistance': f"防守位{geo.get('support_price', '无')}元（距现价{geo.get('dist_to_support_pct', '无')}），压力位{geo.get('resistance_price', '无')}元（距现价{geo.get('dist_to_resistance_pct', '无')}）",
            'dist_to_prev_high_pct': geo.get('dist_to_prev_high_pct'),
            'rr_assessment': rr_info['rr_assessment'],
            'volatility': f"波动率{vol_info['level']}（ATR={vol_info['atr_14d']:.2f}，历史分位{vol_info['percentile']:.0%}）" if vol_info['atr_14d'] > 0 else f"波动率{vol_info['level']}",
            'signal_days': geo.get('signal_days'),
            'invalidation': [item['condition'] for item in invalidation],
            'plain': plain,
        }

        # 7. judgment
        judgment = {
            'level': risk_info['level'],
            'light': risk_info['light'],
            'overall_light': risk_info['light'],
            'overall_direction': -1 if risk_info['level'] in ('高', '极高') else (1 if risk_info['level'] in ('低',) else 0),
            'continuous_value': round(min(rr_info.get('rr_value', 0) / 3.0, 1.0), 4) if rr_info.get('rr_value') else 0.5,  # P2: 盈亏比 [0,3+]→[0,1]
        }

        # 8. audit
        conditions = [
            {'name': '风险等级', 'satisfied': risk_info['level'] in ('低', '中'),
             'actual': risk_info['level'], 'threshold': '低或中'},
            {'name': '盈亏比', 'satisfied': rr_info.get('rr_value', 0) >= 2.0 if rr_info.get('rr_value') else False,
             'actual': f"{rr_info.get('rr_value', '无')}" if rr_info.get('rr_value') else '数据不足',
             'threshold': '≥2R'},
            {'name': '波动率', 'satisfied': vol_info['level'] != 'high',
             'actual': vol_info['level'], 'threshold': '非high'},
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
            'dims (StatusEngine) — risk',
        ]
