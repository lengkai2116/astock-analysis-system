"""
BOCIASI 快线四指标（情绪层）

从零建立情绪维度的四个快速指标，仅依赖 OHLCV 日线数据：
  1. fast_vol    — 今日量 > 5日均量 × 1.5（放量确认）
  2. fast_price  — 今日收 > 5日均价（价格强势）
  3. fast_mom    — 5日涨幅 > 3%（短期动量）
  4. fast_breadth— 日内振幅 > 3%（波动活跃度）

综合判定规则：
  ≥3 项通过 → BUY（情绪积极）
  ≥2 项通过 → WATCH（情绪中性偏暖）
  否则       → HOLD（情绪平淡或低迷）
"""
from typing import Dict, Optional
import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


class BociasiQuickLine:
    """
    BOCIASI 快线 — 四个快速情绪指标
    """

    def __init__(self):
        self.results = {}

    def evaluate(self, df: pd.DataFrame) -> Dict:
        """
        对单只股票计算 BOCIASI 快线四指标

        Args:
            df: OHLCV DataFrame，需含 open/high/low/close/vol 列

        Returns:
            {
                "signal": "BUY" | "WATCH" | "NEUTRAL",
                "confidence": float,
                "indicators": { "fast_vol": bool, "fast_price": bool, ... },
                "details": { ... },
                "pass_count": int,
            }
        """
        if df.empty or len(df) < 6:
            return self._empty_result("数据不足")

        closes = df['close'].values
        opens = df['open'].values
        highs = df['high'].values
        lows = df['low'].values
        volumes = df['vol'].values if 'vol' in df.columns else df['amount'].values
        latest_close = float(closes[-1])

        # 指标 1: 放量确认
        vol_ma5 = np.mean(volumes[-6:-1])  # 前5日均量（不含今日）
        fast_vol = volumes[-1] > vol_ma5 * 1.5
        vol_ratio = float(volumes[-1] / vol_ma5) if vol_ma5 > 0 else 0.0

        # 指标 2: 价格强势
        price_ma5 = np.mean(closes[-6:-1])
        fast_price = latest_close > price_ma5
        price_offset = float((latest_close / price_ma5 - 1) * 100) if price_ma5 > 0 else 0.0

        # 指标 3: 短期动量
        close_5d_ago = float(closes[-6]) if len(closes) >= 6 else latest_close
        mom_5d = (latest_close / close_5d_ago - 1) * 100
        fast_mom = mom_5d > 3.0

        # 指标 4: 波动活跃度
        daily_amplitude = (highs[-1] - lows[-1]) / latest_close * 100
        fast_breadth = daily_amplitude > 3.0

        # 判定
        indicators = {
            "fast_vol": bool(fast_vol),
            "fast_price": bool(fast_price),
            "fast_mom": bool(fast_mom),
            "fast_breadth": bool(fast_breadth),
        }
        pass_count = sum(1 for v in indicators.values() if v)

        if pass_count >= 3:
            signal = "BUY"
            base_conf = 0.65
        elif pass_count >= 2:
            signal = "WATCH"
            base_conf = 0.50
        else:
            signal = "NEUTRAL"
            base_conf = 0.35

        # 置信度微调
        if fast_vol and fast_mom:
            base_conf += 0.05  # 量价齐升加分
        if fast_breadth and not fast_price:
            base_conf -= 0.05  # 宽幅震荡但价格不强
        confidence = max(0.1, min(0.9, base_conf))

        details = {
            "vol_ratio": round(vol_ratio, 2),
            "price_offset_pct": round(price_offset, 2),
            "mom_5d_pct": round(mom_5d, 2),
            "amplitude_pct": round(daily_amplitude, 2),
        }

        return {
            "signal": signal,
            "confidence": round(confidence, 2),
            "indicators": indicators,
            "details": details,
            "pass_count": pass_count,
            "latest_close": round(latest_close, 2),
        }

    def _empty_result(self, reason: str) -> Dict:
        return {
            "signal": "NEUTRAL",
            "confidence": 0.0,
            "indicators": {},
            "details": {"reason": reason},
            "pass_count": 0,
            "latest_close": 0.0,
        }
