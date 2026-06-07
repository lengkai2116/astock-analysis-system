"""
量价策略适配器 — VolumePriceStrategy → PatternResult
======================================================
将现有 volume_price_strategy.py 中的模式检测输出映射为 PatternResult。

覆盖：
  - 9 种量价基础模式 (VP-1 ~ VP-9)
  - 5 种增强形态 (EnhancedPatternDetector)
  - 6 种背离形态 (DivergenceDetector)
  - 4 种趋势阶段 (StageDetector)
  - 2 种量能结构 (量托/量压)
"""

from typing import List, Optional
import pandas as pd
import numpy as np

from app.engine.patterns import (
    PatternResult, PatternCategory, PatternStage, PatternLevel
)
from app.engine.patterns.registry import PatternRegistry


class VolumePricePatternAdapter:
    """
    量价策略模式适配器
    包装 volume_price_strategy 中的各类检测，统一输出 PatternResult
    """

    def __init__(self):
        self.registry = PatternRegistry()

    def detect_base_vp(self, closes: np.ndarray, volumes: np.ndarray) -> List[PatternResult]:
        """
        检测 9 种量价基础模式
        对应 _classify_vp_pattern 的映射逻辑
        """
        results = []
        if len(closes) < 4 or len(volumes) < 4:
            return results

        price_chg = (closes[-1] - closes[-4]) / max(closes[-4], 1e-9) * 100
        vol_chg = (np.mean(volumes[-3:]) - np.mean(volumes[-7:-3])) / max(np.mean(volumes[-7:-3]), 1e-9) * 100

        price_dir = "up" if price_chg > 2 else "down" if price_chg < -2 else "flat"
        vol_dir = "expand" if vol_chg > 15 else "shrink" if vol_chg < -15 else "stable"

        vp_map = {
            ("up", "expand"): ("VP-1", 0.65),
            ("up", "stable"): ("VP-2", 0.50),
            ("up", "shrink"): ("VP-3", 0.55),
            ("flat", "expand"): ("VP-4", 0.45),
            ("flat", "stable"): ("VP-5", 0.30),
            ("flat", "shrink"): ("VP-6", 0.40),
            ("down", "expand"): ("VP-7", 0.55),
            ("down", "stable"): ("VP-8", 0.45),
            ("down", "shrink"): ("VP-9", 0.60),
        }

        key = (price_dir, vol_dir)
        if key in vp_map:
            name, strength = vp_map[key]
            meta = self.registry.get(name)
            if meta:
                results.append(PatternResult(
                    name=name,
                    category=PatternCategory.VOLUME_PRICE,
                    direction=meta.direction,
                    strength=strength,
                    stage=PatternStage.COMPLETED,
                    completion=100.0,
                    conditions=[f"价格变化{price_chg:+.1f}%", f"量能变化{vol_chg:+.0f}%"],
                    interpretation=meta.description,
                    detail={'price_chg_pct': round(price_chg, 1),
                            'vol_chg_pct': round(vol_chg, 0)},
                    source="volume_price_strategy.py",
                ))
        return results

    def detect_enhanced(self, df: pd.DataFrame) -> List[PatternResult]:
        """
        检测 5 种增强形态
        对应 EnhancedPatternDetector 逻辑
        """
        results = []
        if df.empty or len(df) < 10:
            return results

        closes = df['close'].values
        opens = df['open'].values
        highs = df['high'].values
        lows = df['low'].values
        volumes = df.get('vol', df.get('amount', df.get('volume', None)))
        if volumes is None:
            return results
        volumes = volumes.values

        # 形态1: 冲高回落急速缩量
        if self._detect_chonggao(closes, highs, lows, volumes):
            meta = self.registry.get('chonggao_huiluo_jisuo')
            if meta:
                results.append(PatternResult(
                    name='chonggao_huiluo_jisuo',
                    category=PatternCategory.VOLUME_PRICE,
                    direction='bullish',
                    strength=0.65,
                    stage=PatternStage.COMPLETED,
                    completion=100.0,
                    conditions=["冲高>3% → 收盘回落>2% → 量缩50%"],
                    interpretation=meta.description,
                    detail={'vol_shrink_pct': round(
                        (volumes[-1] / volumes[-2] - 1) * 100, 1)},
                    source="volume_price_strategy.py",
                ))

        # 形态2: 递增式放量下跌
        if self._detect_dizeng(closes, volumes):
            meta = self.registry.get('dizeng_fangliang_xiajie')
            if meta:
                results.append(PatternResult(
                    name='dizeng_fangliang_xiajie',
                    category=PatternCategory.VOLUME_PRICE,
                    direction='bearish',
                    strength=0.60,
                    stage=PatternStage.COMPLETED,
                    completion=100.0,
                    conditions=["连续3日量增价跌"],
                    interpretation=meta.description,
                    source="volume_price_strategy.py",
                ))

        # 形态3: 堆量中跌回启动点
        if self._detect_huiluo(closes, volumes):
            meta = self.registry.get('huiluo_zhangting_qiangshi')
            if meta:
                results.append(PatternResult(
                    name='huiluo_zhangting_qiangshi',
                    category=PatternCategory.VOLUME_PRICE,
                    direction='bullish',
                    strength=0.70,
                    stage=PatternStage.COMPLETED,
                    completion=100.0,
                    conditions=["跌回启动点", "缩量至峰值30%"],
                    interpretation=meta.description,
                    source="volume_price_strategy.py",
                ))

        # 形态4: 三连阳放量
        if self._detect_sanlian(closes, opens, volumes):
            meta = self.registry.get('sanlian_yang_fangliang')
            if meta:
                results.append(PatternResult(
                    name='sanlian_yang_fangliang',
                    category=PatternCategory.VOLUME_PRICE,
                    direction='bullish',
                    strength=0.65,
                    stage=PatternStage.COMPLETED,
                    completion=100.0,
                    conditions=["连续3日阳线+量增"],
                    interpretation=meta.description,
                    source="volume_price_strategy.py",
                ))

        # 形态5: 放量长阴破位
        if self._detect_fangliang_changyin(df):
            meta = self.registry.get('fangliang_changyin_tupo')
            if meta:
                results.append(PatternResult(
                    name='fangliang_changyin_tupo',
                    category=PatternCategory.VOLUME_PRICE,
                    direction='bearish',
                    strength=0.70,
                    stage=PatternStage.COMPLETED,
                    completion=100.0,
                    conditions=["实体>振幅0.6", "收盘<前低", "量>均量1.5倍"],
                    interpretation=meta.description,
                    source="volume_price_strategy.py",
                ))

        return results

    def detect_divergence(self, df: pd.DataFrame, stage_name: str = "",
                          macd_data: Optional[dict] = None) -> List[PatternResult]:
        """
        检测背离形态
        对应 _detect_divergence_enhanced 逻辑
        """
        results = []
        if df.empty or len(df) < 40:
            return results

        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        volumes = df.get('vol', df.get('amount', df.get('volume', None)))
        if volumes is None:
            return results
        volumes = volumes.values

        # 计算MACD
        dif, dea, hist = self._calc_macd(closes)

        # 顶背离: UPTREND
        if stage_name in ("UPTREND_ACTIVE", "UPTREND_TOPPING"):
            p1_idx = len(closes) - 20 - (np.argmax(highs[-20:-10]) if len(highs) >= 20 else 0)
            p2_idx = len(closes) - 10 + (np.argmax(highs[-10:]) if len(highs) >= 10 else 0)
            if 0 <= p1_idx < p2_idx < len(closes):
                p1_price, p2_price = highs[p1_idx], highs[p2_idx]
                v1 = np.mean(volumes[max(0, p1_idx-3):p1_idx+1])
                v2 = np.mean(volumes[max(0, p2_idx-3):p2_idx+1])
                if p2_price > p1_price and v2 < v1 * 0.9:
                    # MACD顶背离
                    meta = self.registry.get('macd_bearish_divergence')
                    if meta:
                        results.append(PatternResult(
                            name='macd_bearish_divergence',
                            category=PatternCategory.DIVERGENCE,
                            direction='bearish',
                            strength=0.65,
                            stage=PatternStage.COMPLETED,
                            completion=100.0,
                            conditions=[f"价新高{p2_price:.2f}>前高{p1_price:.2f}",
                                        f"量萎缩{v2:.0f}<{v1:.0f}"],
                            interpretation=meta.description,
                            detail={'p1_price': float(p1_price), 'p2_price': float(p2_price),
                                    'v1': float(v1), 'v2': float(v2)},
                            source="volume_price_strategy.py",
                        ))

                # 三重顶背离（MACD确认）
                if p2_price > p1_price and len(dif) > max(p1_idx, p2_idx):
                    d1, d2 = dif[p1_idx], dif[p2_idx]
                    if d2 < d1:
                        meta = self.registry.get('triple_bearish_divergence')
                        if meta:
                            results.append(PatternResult(
                                name='triple_bearish_divergence',
                                category=PatternCategory.DIVERGENCE,
                                direction='bearish',
                                strength=0.80,
                                stage=PatternStage.COMPLETED,
                                completion=100.0,
                                conditions=["价格+量+MACD三重顶背离"],
                                interpretation=meta.description,
                                detail={'d1': float(d1), 'd2': float(d2)},
                                source="volume_price_strategy.py",
                            ))

        # 底背离: DOWNTREND
        if stage_name in ("DOWNTREND_ACTIVE", "DOWNTREND_BOTTOMING"):
            t1_idx = len(lows) - 20 - (np.argmin(lows[-20:-10]) if len(lows) >= 20 else 0)
            t2_idx = len(lows) - 10 + (np.argmin(lows[-10:]) if len(lows) >= 10 else 0)
            if 0 <= t1_idx < t2_idx < len(lows):
                t1_price, t2_price = lows[t1_idx], lows[t2_idx]
                v1 = np.mean(volumes[max(0, t1_idx-3):t1_idx+1])
                v2 = np.mean(volumes[max(0, t2_idx-3):t2_idx+1])
                if t2_price < t1_price and v2 > v1 * 1.1:
                    meta = self.registry.get('macd_bullish_divergence')
                    if meta:
                        results.append(PatternResult(
                            name='macd_bullish_divergence',
                            category=PatternCategory.DIVERGENCE,
                            direction='bullish',
                            strength=0.65,
                            stage=PatternStage.COMPLETED,
                            completion=100.0,
                            conditions=[f"价新低{t2_price:.2f}<前低{t1_price:.2f}",
                                        f"量放大{v2:.0f}>{v1:.0f}"],
                            interpretation=meta.description,
                            detail={'t1_price': float(t1_price), 't2_price': float(t2_price),
                                    'v1': float(v1), 'v2': float(v2)},
                            source="volume_price_strategy.py",
                        ))

                # 三重底背离（MACD确认）
                if t2_price < t1_price and len(dif) > max(t1_idx, t2_idx):
                    d1, d2 = dif[t1_idx], dif[t2_idx]
                    if d2 > d1:
                        meta = self.registry.get('triple_bullish_divergence')
                        if meta:
                            results.append(PatternResult(
                                name='triple_bullish_divergence',
                                category=PatternCategory.DIVERGENCE,
                                direction='bullish',
                                strength=0.80,
                                stage=PatternStage.COMPLETED,
                                completion=100.0,
                                conditions=["价格+量+MACD三重底背离"],
                                interpretation=meta.description,
                                detail={'d1': float(d1), 'd2': float(d2)},
                                source="volume_price_strategy.py",
                            ))

        return results

    # ── 辅助检测方法 ──

    def _detect_chonggao(self, closes, highs, lows, volumes) -> bool:
        if len(closes) < 3 or len(volumes) < 2:
            return False
        today_high_pct = (highs[-2] / closes[-3] - 1) * 100
        if today_high_pct > 3:
            pullback = (highs[-2] - closes[-2]) / highs[-2]
            if pullback > 0.02 and volumes[-1] < volumes[-2] * 0.5:
                return True
        return False

    def _detect_dizeng(self, closes, volumes) -> bool:
        if len(closes) < 4 or len(volumes) < 4:
            return False
        for i in range(-3, 0):
            if closes[i] >= closes[i-1] or volumes[i] <= volumes[i-1]:
                return False
        return True

    def _detect_huiluo(self, closes, volumes) -> bool:
        if len(closes) < 10:
            return False
        base = closes[-11]
        current = closes[-1]
        if current < base * 1.02:
            vol_peak = np.max(volumes[-10:])
            vol_last = np.mean(volumes[-3:])
            if vol_last < vol_peak * 0.3:
                return True
        return False

    def _detect_sanlian(self, closes, opens, volumes) -> bool:
        if len(closes) < 4:
            return False
        for i in range(-3, 0):
            if closes[i] <= opens[i] or volumes[i] <= volumes[i-1]:
                return False
        return True

    def _detect_fangliang_changyin(self, df) -> bool:
        if len(df) < 10:
            return False
        latest = df.iloc[-1]
        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        volumes = df.get('vol', df.get('amount', df.get('volume'))).values
        body = abs(latest['close'] - latest['open'])
        range_total = latest['high'] - latest['low']
        if range_total <= 0:
            return False
        body_ratio = body / range_total
        if closes[-1] < closes[-2] and body_ratio > 0.6:
            prev_low = np.min(lows[-10:-1])
            if closes[-1] < prev_low:
                avg_vol = np.mean(volumes[-10:-1])
                if volumes[-1] > avg_vol * 1.5:
                    return True
        return False

    def _calc_macd(self, closes):
        """简易 MACD 计算"""
        arr = np.array(closes, dtype=float)
        ema12 = pd.Series(arr).ewm(span=12, adjust=False).mean().values
        ema26 = pd.Series(arr).ewm(span=26, adjust=False).mean().values
        dif = ema12 - ema26
        dea = pd.Series(dif).ewm(span=9, adjust=False).mean().values
        hist = 2 * (dif - dea)
        return dif, dea, hist
