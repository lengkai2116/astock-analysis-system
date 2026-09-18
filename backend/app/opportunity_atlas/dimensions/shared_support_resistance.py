"""shared_support_resistance.py — 支撑阻力统一计算服务（461-11 唯一 SSOT）

364h Phase 8：统一3个支撑阻力来源，修复resistance逻辑bug。
461-11：收敛 dim6.calc_geometric / advice_builder._geometric / advice_engine._geometric
    三份逐字副本为唯一源；signal_days、dist_to_prev_high_pct 自 calc_geometric 并入。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def calc_support_resistance(df=None, indicator_ma_df=None) -> dict:
    """统一支撑阻力计算

    融合3个来源：
    1. advice_builder._geometric()：MA20+近20日低点
    2. VAP（成交量加权价格）
    3. 缠论中枢边界

    indicator_ma_df: 可选，data_context 中的 MA 预计算 DataFrame（含 ma20/ma60 列）。
    412号方案B1 v3.0 / 434号收敛：MA20/MA60 优先从 indicator_ma_df 读取，保留 raw fallback。

    Returns:
        {
            'support_price': float | None,
            'resistance_price': float | None,
            'dist_to_support_pct': float | None,
            'dist_to_resistance_pct': float | None,
            'risk_reward': float | None,
            'source': str,
            'signal_days': int | None,
            'dist_to_prev_high_pct': float | None,
        }
    """
    if df is None or df.empty or 'close' not in df.columns or len(df) < 20:
        return {'support_price': None, 'resistance_price': None,
                'dist_to_support_pct': None, 'dist_to_resistance_pct': None,
                'risk_reward': None, 'source': '数据不足',
                'signal_days': None, 'dist_to_prev_high_pct': None}

    import numpy as np
    closes = df['close'].values
    price = float(closes[-1])

    # 1. MA20 + 近20日低点 → 支撑位（MA20 优先 indicator_ma_df，raw fallback）
    ma20 = None
    if indicator_ma_df is not None and not indicator_ma_df.empty and 'ma20' in indicator_ma_df.columns:
        val = indicator_ma_df['ma20'].iloc[-1]
        if val is not None:
            ma20 = float(val)
    if ma20 is None:
        ma20 = float(np.mean(closes[-20:]))
    lo20 = float(df['low'].tail(20).min()) if 'low' in df.columns else None
    support_candidates = [x for x in [ma20, lo20] if x is not None]
    support = max(support_candidates) if support_candidates else None

    # 止损必须低于现价
    if support is not None and support >= price:
        lo60 = float(df['low'].tail(60).min()) if len(df) >= 60 and 'low' in df.columns else None
        support = lo60

    # 止损距离上限15%
    if support is not None:
        max_stop_pct = 0.15
        min_support = price * (1 - max_stop_pct)
        if support < min_support:
            support = min_support

    # 2. 压力位：取高于现价的最近位（MA60 优先 indicator_ma_df，raw fallback）
    hi60 = float(df['high'].tail(60).max()) if len(df) >= 60 and 'high' in df.columns else None
    ma60 = None
    if indicator_ma_df is not None and not indicator_ma_df.empty and 'ma60' in indicator_ma_df.columns:
        val = indicator_ma_df['ma60'].iloc[-1]
        if val is not None:
            ma60 = float(val)
    if ma60 is None:
        ma60 = float(np.mean(closes[-60:])) if len(df) >= 60 else None

    # 364f修复：取高于现价的最近位，非简单min
    resistance_candidates = [x for x in [hi60, ma60] if x is not None and x > price]
    resistance = min(resistance_candidates) if resistance_candidates else hi60

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

    # 距前高%（20日内最高价）——461-11 收敛自 calc_geometric 输出
    dist_prev_high = None
    if len(df) >= 20 and 'high' in df.columns:
        prev_high = float(df['high'].tail(20).max())
        if prev_high > 0 and price is not None:
            dist_prev_high = round((price / prev_high - 1) * 100, 2)

    return {
        'support_price': round(support, 2) if support else None,
        'resistance_price': round(resistance, 2) if resistance else None,
        'dist_to_support_pct': round(dist_sup, 2) if dist_sup is not None else None,
        'dist_to_resistance_pct': round(dist_res, 2) if dist_res is not None else None,
        'risk_reward': round(rr, 2) if rr is not None else None,
        'source': '统一计算',
        'signal_days': signal_days,
        'dist_to_prev_high_pct': dist_prev_high,
    }
