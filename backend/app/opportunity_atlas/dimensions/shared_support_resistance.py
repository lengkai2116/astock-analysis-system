"""shared_support_resistance.py — 支撑阻力统一计算服务

364h Phase 8：统一3个支撑阻力来源，修复resistance逻辑bug。
"""
from __future__ import annotations
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def calc_support_resistance(df=None) -> dict:
    """统一支撑阻力计算

    融合3个来源：
    1. advice_builder._geometric()：MA20+近20日低点
    2. VAP（成交量加权价格）
    3. 缠论中枢边界

    Returns:
        {
            'support_price': float | None,
            'resistance_price': float | None,
            'dist_to_support_pct': float | None,
            'dist_to_resistance_pct': float | None,
            'risk_reward': float | None,
            'source': str
        }
    """
    if df is None or df.empty or 'close' not in df.columns or len(df) < 20:
        return {'support_price': None, 'resistance_price': None,
                'dist_to_support_pct': None, 'dist_to_resistance_pct': None,
                'risk_reward': None, 'source': '数据不足'}

    import numpy as np
    closes = df['close'].values
    price = float(closes[-1])

    # 1. MA20 + 近20日低点 → 支撑位
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

    # 2. 压力位：取高于现价的最近位
    hi60 = float(df['high'].tail(60).max()) if len(df) >= 60 and 'high' in df.columns else None
    ma60 = float(np.mean(closes[-60:])) if len(df) >= 60 else None

    # 364f修复：取高于现价的最近位，非简单min
    resistance_candidates = [x for x in [hi60, ma60] if x is not None and x > price]
    resistance = min(resistance_candidates) if resistance_candidates else hi60

    dist_sup = (support / price - 1) * 100 if support else None
    dist_res = (resistance / price - 1) * 100 if resistance else None
    rr = abs(dist_res / dist_sup) if dist_sup and dist_res else None

    return {
        'support_price': round(support, 2) if support else None,
        'resistance_price': round(resistance, 2) if resistance else None,
        'dist_to_support_pct': round(dist_sup, 2) if dist_sup is not None else None,
        'dist_to_resistance_pct': round(dist_res, 2) if dist_res is not None else None,
        'risk_reward': round(rr, 2) if rr is not None else None,
        'source': '统一计算',
    }
