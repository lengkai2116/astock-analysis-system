"""
黑马型量价形态检测器（10种）
==============================
基于《量价狙击》第八章的 10 种黑马型形态定义。

每种形态对应一个独立检测方法（_p_3_1 ~ _p_3_10），
返回 PatternResult 或 None（未检测到）。

检测器消费 PatternDetector 基类接口，产出统一 PatternResult。
"""
from typing import List, Optional, Dict
import pandas as pd
import numpy as np

from app.engine.patterns import (
    PatternResult, PatternCategory, PatternStage, PatternLevel,
)
from app.engine.patterns.detectors.base import PatternDetector


class BlackHorsePatternDetector(PatternDetector):
    """黑马型形态检测器 — 检测 10 种黑马型量价形态"""

    # 形态名称映射（注册表 code → 中文名）
    _NAMES = {
        "P-3-1":  "底部异动放量",
        "P-3-2":  "缩量挖坑后放量",
        "P-3-3":  "低位连续小阳堆量",
        "P-3-4":  "突破年线放量",
        "P-3-5":  "底部涨停板",
        "P-3-6":  "长期缩量后突然放量",
        "P-3-7":  "底部连续阳线不破前低",
        "P-3-8":  "低位巨量长下影",
        "P-3-9":  "老鸭头形态放量",
        "P-3-10": "N字形态放量突破",
    }

    def detect(self, df: pd.DataFrame, context: Optional[Dict] = None) -> List[PatternResult]:
        """检测所有黑马型形态"""
        if df.empty or len(df) < 30:
            return []

        results: List[PatternResult] = []
        detectors = [
            self._p_3_1,  self._p_3_2,  self._p_3_3,  self._p_3_4,  self._p_3_5,
            self._p_3_6,  self._p_3_7,  self._p_3_8,  self._p_3_9,  self._p_3_10,
        ]

        for detector in detectors:
            try:
                p = detector(df, context)
                if p is not None:
                    results.append(p)
            except Exception:
                continue

        return results

    # ── 通用辅助 ──────────────────────────────────────

    @staticmethod
    def _vol_ma(vol: pd.Series, window: int = 20) -> float:
        """计算成交量均线（取最近 window 日均值）"""
        if len(vol) < window:
            return float(vol.mean()) if len(vol) > 0 else 0.0
        return float(vol.iloc[-window:].mean())

    @staticmethod
    def _ma(series: pd.Series, window: int) -> pd.Series:
        """移动平均"""
        return series.rolling(window=window, min_periods=1).mean()

    @staticmethod
    def _is_doji(row: pd.Series) -> bool:
        """判断单根K线是否为十字星"""
        body = abs(row['close'] - row['open'])
        amplitude = row['high'] - row['low']
        if amplitude <= 0:
            return False
        return body / amplitude < 0.1

    @staticmethod
    def _is_yang(row: pd.Series) -> bool:
        """判断是否为阳线"""
        return row['close'] > row['open']

    @staticmethod
    def _is_yin(row: pd.Series) -> bool:
        """判断是否为阴线"""
        return row['close'] < row['open']

    @staticmethod
    def _body(row: pd.Series) -> float:
        """实体大小（绝对值）"""
        return abs(row['close'] - row['open'])

    def _make_result(
        self,
        code: str,
        strength: float,
        stage: PatternStage,
        completion: float,
        conditions: List[str],
        interpretation: str,
        levels: Optional[PatternLevel] = None,
        detail: Optional[Dict] = None,
        invalidation: Optional[List[str]] = None,
    ) -> PatternResult:
        """统一构造 PatternResult"""
        name = self._NAMES.get(code, code)
        return PatternResult(
            name=code,
            category=PatternCategory.BLACKHORSE,
            direction='bullish',
            strength=round(strength, 2),
            stage=stage,
            completion=round(completion, 1),
            conditions=conditions,
            levels=levels or PatternLevel(),
            invalidation=invalidation or [],
            interpretation=interpretation,
            detail=detail or {},
            source="wiki_volume_price",
        )

    # ══════════════════════════════════════════════════
    # P-3-1: 底部异动放量
    # 低位突然出现异常放量（3倍以上均量），价格小幅上涨，
    # 疑似主力资金秘密建仓，可能是黑马启动前兆
    # ══════════════════════════════════════════════════
    def _p_3_1(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 30:
            return None

        latest = df.iloc[-1]
        close = df['close']
        vol = df['volume']

        # 条件1: 价格在低位（近60日最低30%区域）
        lookback = min(60, len(df))
        low_60 = float(df['low'].iloc[-lookback:].min())
        high_60 = float(df['high'].iloc[-lookback:].max())
        if high_60 <= low_60:
            return None
        price_pos = (close.iloc[-1] - low_60) / (high_60 - low_60)
        if price_pos > 0.35:
            return None

        # 条件2: 成交量 > 20日均量的3倍（异常放量）
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio < 3.0:
            return None

        # 条件3: 价格上涨但涨幅不超过6%（温和上涨非暴涨）
        if len(df) < 2:
            return None
        pct = (latest['close'] / df.iloc[-2]['close'] - 1)
        if pct < 0 or pct > 0.06:
            return None

        # 条件4: 前期成交量萎缩（前5日均量 < 20日均量的70%）
        vol_prev5 = float(vol.iloc[-6:-1].mean())
        if vol_prev5 > vol_avg * 0.7:
            return None

        strength = 0.65 + (0.15 if vol_ratio > 5.0 else 0.0) + (0.10 if price_pos < 0.20 else 0.0)
        return self._make_result(
            code="P-3-1",
            strength=min(strength, 0.90),
            stage=PatternStage.FORMING,
            completion=45.0,
            conditions=[
                f"价格处于低位{price_pos*100:.0f}%区域",
                f"成交量为20日均量的{vol_ratio*100:.0f}%（异常放量）",
                f"当日涨幅{pct*100:.1f}%（温和上涨）",
                "前期成交量萎缩（前5日均量低于70%均量）",
            ],
            interpretation="低位突然出现异常放量，疑似主力资金秘密建仓，黑马启动前兆",
            levels=PatternLevel(
                support=float(df['low'].iloc[-5:].min()),
                resistance=float(close.iloc[-1] * 1.08),
            ),
            detail={"vol_ratio": round(vol_ratio, 2), "price_pos": round(price_pos, 3), "pct_change": round(float(pct), 4)},
        )

    # ══════════════════════════════════════════════════
    # P-3-2: 缩量挖坑后放量
    # 价格在低位缩量挖坑（3~5日下跌），随后突然放量反弹，
    # 量能急剧扩大，主力挖坑吸筹结束、准备拉升
    # ══════════════════════════════════════════════════
    def _p_3_2(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 20:
            return None

        close = df['close']
        vol = df['volume']

        # 条件1: 近5~8日前有缩量下跌阶段（连续3日成交量递减+价格下跌）
        shrink_found = False
        for start in range(-8, -4):
            if start < -len(df) + 2:
                continue
            v_dec = vol.iloc[start] < vol.iloc[start - 1] < vol.iloc[start - 2]
            p_dec = close.iloc[start] < close.iloc[start - 1]
            if v_dec and p_dec:
                shrink_found = True
                break
        if not shrink_found:
            return None

        # 条件2: 当日为阳线
        if not self._is_yang(df.iloc[-1]):
            return None

        # 条件3: 当日成交量 > 前3日均量的2倍以上（放量启动）
        vol_prev3 = float(vol.iloc[-4:-1].mean())
        if vol_prev3 <= 0:
            return None
        vol_ratio_vs_prev = float(vol.iloc[-1] / vol_prev3)
        if vol_ratio_vs_prev < 2.0:
            return None

        # 条件4: 当日成交量 > 20日均量
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0 or vol.iloc[-1] <= vol_avg:
            return None

        # 条件5: 当日收盘 > 3日前收盘（反弹确认）
        if close.iloc[-1] <= close.iloc[-4]:
            return None

        vol_ratio = float(vol.iloc[-1] / vol_avg)
        strength = 0.60 + (0.15 if vol_ratio_vs_prev > 3.0 else 0.0) + (0.10 if close.iloc[-1] > close.iloc[-3] * 1.02 else 0.0)
        return self._make_result(
            code="P-3-2",
            strength=min(strength, 0.90),
            stage=PatternStage.CONFIRMING,
            completion=65.0,
            conditions=[
                "近5~8日前存在缩量挖坑阶段（连续3日量价齐缩）",
                "当日为阳线",
                f"成交量为前3日均量的{vol_ratio_vs_prev*100:.0f}%（放量反弹）",
                f"成交量超过20日均量（{vol_ratio*100:.0f}%）",
            ],
            interpretation="缩量挖坑后突然放量反弹，主力挖坑吸筹结束准备拉升",
            detail={"vol_ratio_vs_prev3": round(vol_ratio_vs_prev, 2), "vol_ratio": round(vol_ratio, 2)},
        )

    # ══════════════════════════════════════════════════
    # P-3-3: 低位连续小阳堆量
    # 低位连续多日小阳线且成交量逐步放大，主力缓慢建仓，
    # 筹码持续堆积，黑马酝酿中
    # ══════════════════════════════════════════════════
    def _p_3_3(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 30:
            return None

        close = df['close']
        vol = df['volume']

        # 条件1: 价格在低位（近60日最低35%区域）
        lookback = min(60, len(df))
        low_60 = float(df['low'].iloc[-lookback:].min())
        high_60 = float(df['high'].iloc[-lookback:].max())
        if high_60 <= low_60:
            return None
        price_pos = (close.iloc[-1] - low_60) / (high_60 - low_60)
        if price_pos > 0.40:
            return None

        # 条件2: 连续5日阳线
        for i in range(-5, 0):
            if not self._is_yang(df.iloc[i]):
                return None

        # 条件3: 每根涨幅不超过3%（小阳线）
        for i in range(-5, 0):
            if i == -5:
                continue
            pct = (close.iloc[i] / close.iloc[i - 1] - 1)
            if pct > 0.03:
                return None

        # 条件4: 成交量逐步放大（5日均量 > 前10日均量的1.3倍）
        vol_5 = float(vol.iloc[-5:].mean())
        vol_10 = float(vol.iloc[-15:-5].mean()) if len(vol) >= 15 else float(vol.iloc[:-5].mean())
        if vol_10 <= 0 or vol_5 < vol_10 * 1.3:
            return None

        # 条件5: 5日成交量递增（总体趋势向上）
        vol_increasing = all(vol.iloc[i] > vol.iloc[i - 1] for i in range(-4, 0))
        if not vol_increasing:
            # 允许不完全递增，但至少最后3日递增
            vol_increasing = all(vol.iloc[i] > vol.iloc[i - 1] for i in range(-3, 0))
            if not vol_increasing:
                return None

        strength = 0.60 + (0.15 if vol_5 > vol_10 * 1.8 else 0.0) + (0.10 if price_pos < 0.25 else 0.0)
        return self._make_result(
            code="P-3-3",
            strength=min(strength, 0.90),
            stage=PatternStage.FORMING,
            completion=50.0,
            conditions=[
                f"价格处于低位{price_pos*100:.0f}%区域",
                "连续5日小阳线（每根涨幅<3%）",
                f"5日成交量均值为前10日的{vol_5/vol_10*100:.0f}%（堆量）",
                "近期成交量逐步放大",
            ],
            interpretation="低位连续小阳线伴随堆量，主力缓慢建仓筹码持续堆积",
            levels=PatternLevel(
                support=float(df['low'].iloc[-5:].min()),
                resistance=float(close.iloc[-1] * 1.08),
            ),
            detail={"vol_ratio_5_10": round(float(vol_5 / vol_10), 2), "price_pos": round(price_pos, 3)},
        )

    # ══════════════════════════════════════════════════
    # P-3-4: 突破年线放量
    # 价格放量突破250日均线（年线），长期趋势反转信号，
    # 常见于黑马启动初期
    # ══════════════════════════════════════════════════
    def _p_3_4(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 250:
            return None

        close = df['close']
        vol = df['volume']

        # 条件1: 计算年线（MA250）
        ma250 = self._ma(close, 250)
        ma250_val = float(ma250.iloc[-1])

        # 条件2: 前一日收盘低于年线
        if close.iloc[-2] >= ma250_val:
            return None

        # 条件3: 当日收盘站上年线
        if close.iloc[-1] <= ma250_val:
            return None

        # 条件4: 成交量 > 20日均量的2倍
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio < 2.0:
            return None

        # 条件5: 当日阳线
        if not self._is_yang(df.iloc[-1]):
            return None

        strength = 0.70 + (0.10 if vol_ratio > 3.0 else 0.0) + (0.10 if close.iloc[-1] > ma250_val * 1.02 else 0.0)
        return self._make_result(
            code="P-3-4",
            strength=min(strength, 0.95),
            stage=PatternStage.CONFIRMING,
            completion=70.0,
            conditions=[
                f"年线(MA250)位于{ma250_val:.2f}",
                f"前日收盘{close.iloc[-2]:.2f}低于年线，当日收盘{close.iloc[-1]:.2f}突破年线",
                f"成交量为20日均量的{vol_ratio*100:.0f}%",
                "阳线确认突破",
            ],
            interpretation="放量突破年线，长期趋势反转信号，黑马启动初期特征",
            levels=PatternLevel(
                support=ma250_val,
                resistance=float(close.iloc[-1] * 1.08),
            ),
            detail={"ma250": round(ma250_val, 2), "vol_ratio": round(vol_ratio, 2)},
        )

    # ══════════════════════════════════════════════════
    # P-3-5: 底部涨停板
    # 低位突然涨停（或接近涨停），成交量显著放大，
    # 主力发动行情信号，往往是黑马启动标志
    # ══════════════════════════════════════════════════
    def _p_3_5(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 20:
            return None

        latest = df.iloc[-1]
        close = df['close']
        vol = df['volume']

        # 条件1: 价格在低位（近60日最低35%区域）
        lookback = min(60, len(df))
        low_60 = float(df['low'].iloc[-lookback:].min())
        high_60 = float(df['high'].iloc[-lookback:].max())
        if high_60 <= low_60:
            return None
        price_pos = (close.iloc[-1] - low_60) / (high_60 - low_60)
        if price_pos > 0.40:
            return None

        # 条件2: 当日涨幅 >= 9%（接近涨停或涨停）
        if len(df) < 2:
            return None
        pct = (latest['close'] / df.iloc[-2]['close'] - 1)
        if pct < 0.09:
            return None

        # 条件3: 成交量 > 20日均量的3倍
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio < 3.0:
            return None

        # 条件4: 阳线实体大（实体占振幅 > 60%）
        amplitude = latest['high'] - latest['low']
        body = self._body(latest)
        if amplitude <= 0 or body / amplitude < 0.6:
            return None

        strength = 0.70 + (0.10 if pct >= 0.095 else 0.0) + (0.10 if vol_ratio > 5.0 else 0.0)
        return self._make_result(
            code="P-3-5",
            strength=min(strength, 0.95),
            stage=PatternStage.CONFIRMING,
            completion=80.0,
            conditions=[
                f"价格处于低位{price_pos*100:.0f}%区域",
                f"当日涨幅{pct*100:.1f}%（接近涨停）",
                f"成交量为20日均量的{vol_ratio*100:.0f}%",
                f"大阳线实体占比{body/amplitude*100:.0f}%",
            ],
            interpretation="低位涨停伴随放量，主力发动行情信号，黑马启动标志",
            levels=PatternLevel(
                support=float(close.iloc[-1] * 0.95),
                resistance=float(close.iloc[-1] * 1.10),
            ),
            detail={"pct_change": round(float(pct), 4), "vol_ratio": round(vol_ratio, 2)},
        )

    # ══════════════════════════════════════════════════
    # P-3-6: 长期缩量后突然放量
    # 成交量持续萎缩20日以上后，突然出现放量（2倍以上均量），
    # 意味着有新资金入场，可能是黑马启动信号
    # ══════════════════════════════════════════════════
    def _p_3_6(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 40:
            return None

        vol = df['volume']
        close = df['close']

        # 条件1: 近20日成交量均值 < 前20日成交量均值（量能持续萎缩）
        vol_recent20 = float(vol.iloc[-20:].mean())
        vol_prior20 = float(vol.iloc[-40:-20].mean()) if len(vol) >= 40 else float(vol.iloc[:-20].mean())
        if vol_prior20 <= 0:
            return None
        shrink_ratio = vol_recent20 / vol_prior20
        if shrink_ratio > 0.7:
            return None

        # 条件2: 当日成交量 > 20日均量的2倍（突然放量）
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio < 2.0:
            return None

        # 条件3: 当日为阳线
        if not self._is_yang(df.iloc[-1]):
            return None

        # 条件4: 当日成交量 > 前20日均量的1.5倍（确认是新资金入场）
        if vol.iloc[-1] < vol_prior20 * 1.5:
            return None

        strength = 0.65 + (0.15 if shrink_ratio < 0.4 else 0.0) + (0.10 if vol_ratio > 3.5 else 0.0)
        return self._make_result(
            code="P-3-6",
            strength=min(strength, 0.90),
            stage=PatternStage.FORMING,
            completion=50.0,
            conditions=[
                f"近20日成交量萎缩为前期的{shrink_ratio*100:.0f}%",
                f"当日成交量为近20日均量的{vol_ratio*100:.0f}%（突然放量）",
                f"当日成交量为前期均量的{float(vol.iloc[-1]/vol_prior20)*100:.0f}%",
                "阳线确认",
            ],
            interpretation="长期缩量后突然放量，新资金入场信号，可能是黑马启动",
            detail={"shrink_ratio": round(shrink_ratio, 2), "vol_ratio": round(vol_ratio, 2)},
        )

    # ══════════════════════════════════════════════════
    # P-3-7: 底部连续阳线不破前低
    # 低位连续出现阳线且每根低点都不低于前一根低点，
    # 表明下方支撑力度强，多方逐步主导，黑马蓄势待发
    # ══════════════════════════════════════════════════
    def _p_3_7(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 30:
            return None

        close = df['close']
        low = df['low']
        vol = df['volume']

        # 条件1: 价格在低位（近60日最低35%区域）
        lookback = min(60, len(df))
        low_60 = float(df['low'].iloc[-lookback:].min())
        high_60 = float(df['high'].iloc[-lookback:].max())
        if high_60 <= low_60:
            return None
        price_pos = (close.iloc[-1] - low_60) / (high_60 - low_60)
        if price_pos > 0.40:
            return None

        # 条件2: 近5日有4日或以上为阳线
        yang_count = sum(1 for i in range(-5, 0) if self._is_yang(df.iloc[i]))
        if yang_count < 4:
            return None

        # 条件3: 最近3日低点逐步抬高
        lows_rising = all(low.iloc[i] > low.iloc[i - 1] for i in range(-3, 0))
        if not lows_rising:
            return None

        # 条件4: 最近3日收盘价均不低于3日前低点
        ref_low = float(low.iloc[-4])
        for i in range(-3, 0):
            if close.iloc[i] < ref_low:
                return None

        # 条件5: 近3日成交量 > 前10日均量（量能配合）
        vol_avg = self._vol_ma(vol, 20)
        vol_3 = float(vol.iloc[-3:].mean())
        vol_10 = float(vol.iloc[-13:-3].mean()) if len(vol) >= 13 else float(vol.iloc[:-3].mean())
        if vol_10 <= 0 or vol_3 < vol_10 * 1.1:
            return None

        strength = 0.60 + (0.15 if yang_count == 5 else 0.0) + (0.10 if price_pos < 0.25 else 0.0)
        return self._make_result(
            code="P-3-7",
            strength=min(strength, 0.90),
            stage=PatternStage.FORMING,
            completion=55.0,
            conditions=[
                f"价格处于低位{price_pos*100:.0f}%区域",
                f"近5日中有{yang_count}日为阳线",
                "最近3日低点逐步抬高",
                f"近3日成交量为前10日均量的{vol_3/vol_10*100:.0f}%",
            ],
            interpretation="低位连续阳线不破前低，下方支撑力度强，黑马蓄势待发",
            levels=PatternLevel(
                support=float(low.iloc[-3:].min()),
                resistance=float(close.iloc[-1] * 1.08),
            ),
            detail={"yang_count": yang_count, "price_pos": round(price_pos, 3)},
        )

    # ══════════════════════════════════════════════════
    # P-3-8: 低位巨量长下影
    # 低位出现巨量（3倍以上均量）且带有长下影线，
    # 表明下方有大量买单承接，主力护盘意图明显
    # ══════════════════════════════════════════════════
    def _p_3_8(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 20:
            return None

        latest = df.iloc[-1]
        close = df['close']
        vol = df['volume']

        # 条件1: 价格在低位（近60日最低35%区域）
        lookback = min(60, len(df))
        low_60 = float(df['low'].iloc[-lookback:].min())
        high_60 = float(df['high'].iloc[-lookback:].max())
        if high_60 <= low_60:
            return None
        price_pos = (close.iloc[-1] - low_60) / (high_60 - low_60)
        if price_pos > 0.40:
            return None

        # 条件2: 成交量 > 20日均量的3倍（巨量）
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio < 3.0:
            return None

        # 条件3: 长下影线（下影线占振幅 > 40%）
        amplitude = latest['high'] - latest['low']
        if amplitude <= 0:
            return None
        lower_shadow = min(latest['close'], latest['open']) - latest['low']
        if lower_shadow / amplitude < 0.4:
            return None

        # 条件4: 收盘价不低于开盘价太多（非大阴线）
        body = self._body(latest)
        if self._is_yin(latest) and body / amplitude > 0.3:
            return None

        strength = 0.65 + (0.15 if vol_ratio > 5.0 else 0.0) + (0.10 if lower_shadow / amplitude > 0.5 else 0.0)
        return self._make_result(
            code="P-3-8",
            strength=min(strength, 0.90),
            stage=PatternStage.FORMING,
            completion=50.0,
            conditions=[
                f"价格处于低位{price_pos*100:.0f}%区域",
                f"成交量为20日均量的{vol_ratio*100:.0f}%（巨量）",
                f"长下影线占比{lower_shadow/amplitude*100:.0f}%",
                "下方大量买单承接",
            ],
            interpretation="低位巨量长下影，下方大量买单承接，主力护盘意图明显",
            levels=PatternLevel(
                support=float(latest['low']),
                resistance=float(close.iloc[-1] * 1.08),
            ),
            detail={"vol_ratio": round(vol_ratio, 2), "lower_shadow_ratio": round(lower_shadow / amplitude, 2)},
        )

    # ══════════════════════════════════════════════════
    # P-3-9: 老鸭头形态放量
    # 均线先金叉后死叉再金叉（鸭头形态），第二次金叉
    # 伴随放量，代表主力完成洗盘、准备拉升
    # ══════════════════════════════════════════════════
    def _p_3_9(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 60:
            return None

        close = df['close']
        vol = df['volume']

        # 计算MA5和MA10
        ma5 = self._ma(close, 5)
        ma10 = self._ma(close, 10)

        # 条件1: 当前MA5 > MA10（金叉状态）
        if float(ma5.iloc[-1]) <= float(ma10.iloc[-1]):
            return None

        # 条件2: 在近30~60根K线内，之前有过MA5 < MA10（死叉阶段）
        dead_cross_found = False
        for i in range(-30, -10):
            if float(ma5.iloc[i]) < float(ma10.iloc[i]):
                dead_cross_found = True
                break
        if not dead_cross_found:
            return None

        # 条件3: 在更早之前（-60到-30），有MA5 > MA10（第一次金叉）
        early_golden = False
        for i in range(-60, -30):
            if float(ma5.iloc[i]) > float(ma10.iloc[i]):
                early_golden = True
                break
        if not early_golden:
            return None

        # 条件4: 成交量 > 20日均量的1.5倍（放量）
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio < 1.5:
            return None

        # 条件5: 当日阳线
        if not self._is_yang(df.iloc[-1]):
            return None

        # 条件6: 当前MA5和MA10都上行
        if len(ma5) < 6 or len(ma10) < 6:
            return None
        ma5_rising = float(ma5.iloc[-1]) > float(ma5.iloc[-3])
        ma10_rising = float(ma10.iloc[-1]) > float(ma10.iloc[-3])
        if not (ma5_rising and ma10_rising):
            return None

        strength = 0.65 + (0.15 if vol_ratio > 2.5 else 0.0) + (0.10 if float(ma5.iloc[-1]) > float(ma10.iloc[-1]) * 1.01 else 0.0)
        return self._make_result(
            code="P-3-9",
            strength=min(strength, 0.90),
            stage=PatternStage.CONFIRMING,
            completion=70.0,
            conditions=[
                f"老鸭头形态: 第一次金叉→死叉→第二次金叉",
                f"当前MA5({float(ma5.iloc[-1]):.2f}) > MA10({float(ma10.iloc[-1]):.2f})",
                f"成交量为20日均量的{vol_ratio*100:.0f}%",
                "当日阳线确认，均线同步上行",
            ],
            interpretation="老鸭头形态第二次金叉伴随放量，主力完成洗盘准备拉升",
            levels=PatternLevel(
                support=float(ma10.iloc[-1]),
                resistance=float(close.iloc[-1] * 1.08),
            ),
            detail={"ma5": round(float(ma5.iloc[-1]), 2), "ma10": round(float(ma10.iloc[-1]), 2), "vol_ratio": round(vol_ratio, 2)},
        )

    # ══════════════════════════════════════════════════
    # P-3-10: N字形态放量突破
    # 价格呈N字形走势（上涨→回调→再上涨突破前高），
    # 第二次突破前高时伴随放量，主升浪启动信号
    # ══════════════════════════════════════════════════
    def _p_3_10(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 30:
            return None

        close = df['close']
        high = df['high']
        vol = df['volume']

        # 搜索近30日的N字形态
        search_len = min(30, len(df))
        closes = close.iloc[-search_len:].values

        # 寻找第一个高点（前半段的局部高点）
        first_half = closes[:search_len // 2 + 1]
        if len(first_half) < 3:
            return None
        peak1_idx = int(np.argmax(first_half))
        peak1 = float(first_half[peak1_idx])

        # 寻找回调低点（高点到当前之间的局部低点）
        if peak1_idx >= search_len - 5:
            return None
        trough_segment = closes[peak1_idx:search_len - 2]
        if len(trough_segment) < 3:
            return None
        trough_idx = int(np.argmin(trough_segment)) + peak1_idx
        trough = float(closes[trough_idx])

        # 条件1: 回调幅度 > 3%（有效回调）
        if peak1 <= 0 or (peak1 - trough) / peak1 < 0.03:
            return None

        # 条件2: 回调幅度 < 15%（不是趋势反转）
        if (peak1 - trough) / peak1 > 0.15:
            return None

        # 条件3: 当日收盘突破前高
        if close.iloc[-1] <= peak1:
            return None

        # 条件4: 成交量 > 20日均量的1.5倍（放量突破）
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio < 1.5:
            return None

        # 条件5: 当日阳线
        if not self._is_yang(df.iloc[-1]):
            return None

        # 回调段成交量萎缩
        vol_pullback = float(vol.iloc[trough_idx - search_len:trough_idx - search_len + len(closes)].mean()) if trough_idx > peak1 else 0
        # 用更简单的方式计算回调期均量
        pullback_start = max(0, trough_idx - search_len + len(df))
        pullback_end = min(len(df), len(df) - search_len + trough_idx + 1)
        if pullback_start < pullback_end:
            vol_pullback = float(vol.iloc[pullback_start:pullback_end].mean())
        else:
            vol_pullback = vol_avg

        strength = 0.65 + (0.15 if vol_ratio > 2.5 else 0.0) + (0.10 if vol_pullback < vol_avg * 0.8 else 0.0)
        return self._make_result(
            code="P-3-10",
            strength=min(strength, 0.90),
            stage=PatternStage.CONFIRMING,
            completion=70.0,
            conditions=[
                f"N字形态: 第一高点{peak1:.2f}→回调低点{trough:.2f}→突破前高{close.iloc[-1]:.2f}",
                f"回调幅度{(peak1-trough)/peak1*100:.1f}%",
                f"成交量为20日均量的{vol_ratio*100:.0f}%",
                "阳线确认突破",
            ],
            interpretation="N字形走势放量突破前高，主升浪启动信号",
            levels=PatternLevel(
                support=trough,
                resistance=float(close.iloc[-1] * 1.08),
            ),
            detail={"peak1": round(peak1, 2), "trough": round(trough, 2), "vol_ratio": round(vol_ratio, 2)},
        )
