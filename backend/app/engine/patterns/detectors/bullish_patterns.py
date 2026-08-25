"""
预涨型量价形态检测器（20种）
=============================
基于《量价狙击》第六章的 20 种预涨型形态定义。

每种形态对应一个独立检测方法（_p_1_1 ~ _p_1_20），
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


class BullishPatternDetector(PatternDetector):
    """预涨型形态检测器 — 检测 20 种看涨量价形态"""

    # 形态名称映射（注册表 code → 中文名）
    _NAMES = {
        "P-1-1":  "缩量十字星",
        "P-1-2":  "底部温和放量",
        "P-1-3":  "量价齐升启动",
        "P-1-4":  "缩量回踩均线",
        "P-1-5":  "底部堆量蓄势",
        "P-1-6":  "放量突破平台",
        "P-1-7":  "阳线放量反包",
        "P-1-8":  "缩量洗盘后放量",
        "P-1-9":  "量比递增上涨",
        "P-1-10": "底部放量长阳",
        "P-1-11": "均线多头放量",
        "P-1-12": "W底放量突破",
        "P-1-13": "缺口放量突破",
        "P-1-14": "量能潮汐启动",
        "P-1-15": "主力吸筹放量",
        "P-1-16": "圆弧底放量",
        "P-1-17": "三阳开泰放量",
        "P-1-18": "旗形整理突破",
        "P-1-19": "三角收敛突破",
        "P-1-20": "箱体突破放量",
    }

    def detect(self, df: pd.DataFrame, context: Optional[Dict] = None) -> List[PatternResult]:
        """检测所有预涨型形态"""
        if df.empty or len(df) < 20:
            return []

        results: List[PatternResult] = []
        detectors = [
            self._p_1_1,  self._p_1_2,  self._p_1_3,  self._p_1_4,  self._p_1_5,
            self._p_1_6,  self._p_1_7,  self._p_1_8,  self._p_1_9,  self._p_1_10,
            self._p_1_11, self._p_1_12, self._p_1_13, self._p_1_14, self._p_1_15,
            self._p_1_16, self._p_1_17, self._p_1_18, self._p_1_19, self._p_1_20,
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
            category=PatternCategory.BULLISH_PATTERNS,
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
    # P-1-1: 缩量十字星
    # 低位连续缩量后出现十字星，多空力量趋于平衡，反转信号
    # ══════════════════════════════════════════════════
    def _p_1_1(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 20:
            return None

        latest = df.iloc[-1]
        vol = df['volume']

        # 条件1: 最后一根为十字星
        if not self._is_doji(latest):
            return None

        # 条件2: 近5日成交量逐日递减（连续缩量）
        recent_vol = vol.iloc[-5:]
        shrinking = all(recent_vol.iloc[i] < recent_vol.iloc[i - 1] for i in range(1, len(recent_vol)))
        if not shrinking:
            return None

        # 条件3: 当前成交量 < 20日均量的50%（地量）
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0 or vol.iloc[-1] > vol_avg * 0.5:
            return None

        # 条件4: 价格在近20日低位区（收盘 < 20日最低价的120%区间内）
        low_20 = df['low'].iloc[-20:].min()
        high_20 = df['high'].iloc[-20:].max()
        if high_20 <= low_20:
            return None
        price_pos = (latest['close'] - low_20) / (high_20 - low_20)
        if price_pos > 0.35:
            return None

        strength = 0.65 + (0.2 if price_pos < 0.2 else 0.0) + (0.1 if vol.iloc[-1] < vol_avg * 0.3 else 0.0)
        return self._make_result(
            code="P-1-1",
            strength=min(strength, 0.95),
            stage=PatternStage.FORMING,
            completion=50.0,
            conditions=[
                "最后一根K线为十字星",
                f"近5日成交量连续递减",
                f"当前成交量为20日均量的{vol.iloc[-1]/vol_avg*100:.0f}%",
                f"价格处于近20日低位{price_pos*100:.0f}%位置",
            ],
            interpretation="低位连续缩量后出现十字星，多空力量趋于平衡，反转信号",
            levels=PatternLevel(
                support=float(low_20),
                resistance=float(latest['close'] * 1.05),
            ),
            detail={"price_position": round(price_pos, 3), "vol_ratio": round(float(vol.iloc[-1] / vol_avg), 2)},
        )

    # ══════════════════════════════════════════════════
    # P-1-2: 底部温和放量
    # 底部区域成交量温和放大，主力开始试探性建仓
    # ══════════════════════════════════════════════════
    def _p_1_2(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 20:
            return None

        vol = df['volume']
        close = df['close']

        # 条件1: 价格在低位（近60日最低25%区域）
        if len(df) >= 60:
            low_60 = df['low'].iloc[-60:].min()
            high_60 = df['high'].iloc[-60:].max()
        else:
            low_60 = df['low'].min()
            high_60 = df['high'].max()
        if high_60 <= low_60:
            return None
        price_pos = (close.iloc[-1] - low_60) / (high_60 - low_60)
        if price_pos > 0.30:
            return None

        # 条件2: 近3日成交量逐日温和放大（每根增幅在5%~50%）
        if vol.iloc[-4] <= 0:
            return None
        ratios = []
        for i in range(-3, 0):
            if vol.iloc[i - 1] <= 0:
                return None
            r = vol.iloc[i] / vol.iloc[i - 1]
            ratios.append(r)
        mild_growth = all(1.05 <= r <= 1.50 for r in ratios)
        if not mild_growth:
            return None

        # 条件3: 最新成交量在均量的1.2~3倍之间（温和放量，非暴量）
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = vol.iloc[-1] / vol_avg
        if vol_ratio < 1.2 or vol_ratio > 3.0:
            return None

        strength = 0.60 + (0.15 if price_pos < 0.15 else 0.0) + (0.1 if 1.5 < vol_ratio < 2.5 else 0.0)
        return self._make_result(
            code="P-1-2",
            strength=min(strength, 0.90),
            stage=PatternStage.FORMING,
            completion=40.0,
            conditions=[
                f"价格处于近60日低位{price_pos*100:.0f}%区域",
                "近3日成交量逐日温和放大(5%~50%)",
                f"最新成交量为20日均量的{vol_ratio*100:.0f}%",
            ],
            interpretation="底部区域成交量温和放大，主力开始试探性建仓",
            detail={"price_position": round(price_pos, 3), "vol_ratio": round(float(vol_ratio), 2)},
        )

    # ══════════════════════════════════════════════════
    # P-1-3: 量价齐升启动
    # 价格与成交量同步上升，多方力量逐步增强
    # ══════════════════════════════════════════════════
    def _p_1_3(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 10:
            return None

        close = df['close']
        vol = df['volume']

        # 条件1: 连续3日阳线 + 收盘价递增
        for i in range(-3, 0):
            if not self._is_yang(df.iloc[i]):
                return None
        price_up = all(close.iloc[i] > close.iloc[i - 1] for i in range(-2, 0))
        if not price_up:
            return None

        # 条件2: 连续3日成交量递增
        vol_up = all(vol.iloc[i] > vol.iloc[i - 1] for i in range(-2, 0))
        if not vol_up:
            return None

        # 条件3: 最新成交量 > 20日均量1.3倍
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0 or vol.iloc[-1] <= vol_avg * 1.3:
            return None

        # 条件4: 3日累计涨幅 > 3%
        gain_3d = (close.iloc[-1] / close.iloc[-4] - 1)
        if gain_3d < 0.03:
            return None

        strength = 0.65 + (0.15 if gain_3d > 0.05 else 0.0) + (0.1 if vol.iloc[-1] > vol_avg * 2 else 0.0)
        return self._make_result(
            code="P-1-3",
            strength=min(strength, 0.90),
            stage=PatternStage.CONFIRMING,
            completion=70.0,
            conditions=[
                "连续3日阳线且收盘价递增",
                "成交量连续3日递增",
                f"最新成交量为20日均量的{float(vol.iloc[-1]/vol_avg)*100:.0f}%",
                f"3日累计涨幅{gain_3d*100:.1f}%",
            ],
            interpretation="价格与成交量同步上升，多方力量逐步增强",
            detail={"gain_3d": round(float(gain_3d), 4), "vol_ratio": round(float(vol.iloc[-1] / vol_avg), 2)},
        )

    # ══════════════════════════════════════════════════
    # P-1-4: 缩量回踩均线
    # 上升趋势中缩量回踩重要均线不破，洗盘结束信号
    # ══════════════════════════════════════════════════
    def _p_1_4(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 20:
            return None

        close = df['close']
        low = df['low']
        vol = df['volume']

        # 计算 MA20
        ma20 = self._ma(close, 20)
        ma20_val = float(ma20.iloc[-1])

        # 条件1: MA20 向上（当前MA20 > 5日前MA20）
        if len(ma20) < 6:
            return None
        ma20_rising = float(ma20.iloc[-1]) > float(ma20.iloc[-6])
        if not ma20_rising:
            return None

        # 条件2: 近3日最低价回踩MA20附近不破（低点在MA20的98%~101%范围）
        near_ma20 = all(
            float(low.iloc[i]) >= ma20_val * 0.98
            for i in range(-3, 0)
        )
        if not near_ma20:
            return None

        # 条件3: 最新收盘价 > MA20（站稳）
        if close.iloc[-1] <= ma20_val:
            return None

        # 条件4: 近3日成交量 < 20日均量（缩量回踩）
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_shrink = all(vol.iloc[i] < vol_avg for i in range(-3, 0))
        if not vol_shrink:
            return None

        strength = 0.60 + (0.15 if float(close.iloc[-1]) > ma20_val * 1.01 else 0.0)
        return self._make_result(
            code="P-1-4",
            strength=min(strength, 0.85),
            stage=PatternStage.CONFIRMING,
            completion=65.0,
            conditions=[
                f"MA20上行({ma20_val:.2f})",
                "近3日低点回踩MA20不破",
                f"收盘站稳MA20之上",
                "近3日成交量低于20日均量（缩量洗盘）",
            ],
            interpretation="上升趋势中缩量回踩重要均线不破，洗盘结束信号",
            levels=PatternLevel(support=ma20_val),
            detail={"ma20": round(ma20_val, 2)},
        )

    # ══════════════════════════════════════════════════
    # P-1-5: 底部堆量蓄势
    # 低位成交量持续堆积但价格未大幅上涨，主力暗中吸筹
    # ══════════════════════════════════════════════════
    def _p_1_5(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 30:
            return None

        close = df['close']
        vol = df['volume']

        # 条件1: 价格在低位
        if len(df) >= 60:
            low_60 = df['low'].iloc[-60:].min()
            high_60 = df['high'].iloc[-60:].max()
        else:
            low_60 = df['low'].min()
            high_60 = df['high'].max()
        if high_60 <= low_60:
            return None
        price_pos = (close.iloc[-1] - low_60) / (high_60 - low_60)
        if price_pos > 0.35:
            return None

        # 条件2: 近10日成交量均值 > 前20日成交量均值的1.5倍（堆量）
        vol_recent = float(vol.iloc[-10:].mean())
        vol_prior = float(vol.iloc[-30:-10].mean()) if len(vol) >= 30 else float(vol.iloc[:-10].mean())
        if vol_prior <= 0 or vol_recent < vol_prior * 1.5:
            return None

        # 条件3: 近10日价格波动小（振幅 < 8%）
        high_10 = float(df['high'].iloc[-10:].max())
        low_10 = float(df['low'].iloc[-10:].min())
        if low_10 <= 0:
            return None
        amplitude = (high_10 - low_10) / low_10
        if amplitude > 0.08:
            return None

        strength = 0.60 + (0.15 if vol_recent > vol_prior * 2.0 else 0.0) + (0.1 if amplitude < 0.05 else 0.0)
        return self._make_result(
            code="P-1-5",
            strength=min(strength, 0.90),
            stage=PatternStage.FORMING,
            completion=45.0,
            conditions=[
                f"价格处于低位区({price_pos*100:.0f}%)",
                f"近10日量能为前20日的{vol_recent/vol_prior*100:.0f}%（堆量）",
                f"近10日振幅仅{amplitude*100:.1f}%（窄幅震荡）",
            ],
            interpretation="低位成交量持续堆积但价格未大幅上涨，主力暗中吸筹",
            detail={"vol_accum_ratio": round(float(vol_recent / vol_prior), 2), "amplitude_10d": round(amplitude, 4)},
        )

    # ══════════════════════════════════════════════════
    # P-1-6: 放量突破平台
    # 成交量显著放大突破长期整理平台，突破确认信号
    # ══════════════════════════════════════════════════
    def _p_1_6(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 25:
            return None

        close = df['close']
        high = df['high']
        vol = df['volume']
        latest = df.iloc[-1]

        # 条件1: 近20日整理平台（振幅 < 12%）
        platform_high = float(high.iloc[-21:-1].max())
        platform_low = float(df['low'].iloc[-21:-1].min())
        if platform_low <= 0:
            return None
        platform_amp = (platform_high - platform_low) / platform_low
        if platform_amp > 0.12:
            return None

        # 条件2: 最新收盘突破平台高点
        if close.iloc[-1] <= platform_high:
            return None

        # 条件3: 成交量 > 20日均量的2倍
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio < 2.0:
            return None

        # 条件4: 阳线（确认突破力度）
        if not self._is_yang(latest):
            return None

        strength = 0.70 + (0.10 if vol_ratio > 3.0 else 0.0) + (0.10 if platform_amp < 0.08 else 0.0)
        return self._make_result(
            code="P-1-6",
            strength=min(strength, 0.95),
            stage=PatternStage.CONFIRMING,
            completion=75.0,
            conditions=[
                f"近20日整理平台振幅{platform_amp*100:.1f}%",
                f"收盘价{close.iloc[-1]:.2f}突破平台高点{platform_high:.2f}",
                f"成交量为20日均量的{vol_ratio*100:.0f}%",
                "阳线确认突破",
            ],
            interpretation="成交量显著放大突破长期整理平台，突破确认信号",
            levels=PatternLevel(
                support=platform_high,
                resistance=float(close.iloc[-1] * 1.08),
            ),
            detail={"platform_high": round(platform_high, 2), "vol_ratio": round(vol_ratio, 2)},
        )

    # ══════════════════════════════════════════════════
    # P-1-7: 阳线放量反包
    # 阳线实体完全覆盖前日阴线且伴随放量，多头强势反转
    # ══════════════════════════════════════════════════
    def _p_1_7(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 5:
            return None

        curr = df.iloc[-1]
        prev = df.iloc[-2]
        vol = df['volume']

        # 条件1: 前日为阴线
        if prev['close'] >= prev['open']:
            return None

        # 条件2: 当日为阳线
        if curr['close'] <= curr['open']:
            return None

        # 条件3: 当日阳线实体完全覆盖前日阴线实体
        if not (curr['close'] > prev['open'] and curr['open'] < prev['close']):
            return None

        # 条件4: 成交量 > 20日均量1.5倍
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio < 1.5:
            return None

        strength = 0.65 + (0.15 if vol_ratio > 2.5 else 0.0) + (0.1 if self._body(curr) > self._body(prev) * 1.5 else 0.0)
        return self._make_result(
            code="P-1-7",
            strength=min(strength, 0.90),
            stage=PatternStage.CONFIRMING,
            completion=70.0,
            conditions=[
                "前日阴线，当日阳线",
                "阳线实体完全覆盖前日阴线实体",
                f"成交量为20日均量的{vol_ratio*100:.0f}%",
            ],
            interpretation="阳线实体完全覆盖前日阴线且伴随放量，多头强势反转",
            detail={"vol_ratio": round(vol_ratio, 2)},
        )

    # ══════════════════════════════════════════════════
    # P-1-8: 缩量洗盘后放量
    # 经历缩量回调后首次出现放量阳线，洗盘结束主力重新发力
    # ══════════════════════════════════════════════════
    def _p_1_8(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 15:
            return None

        close = df['close']
        vol = df['volume']

        # 条件1: 近5~10日前有缩量下跌阶段（连续3日成交量递减且价格下跌）
        shrink_found = False
        for start in range(-10, -4):
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

        # 条件3: 当日成交量 > 前3日均量的2倍（放量启动）
        vol_prev3 = float(vol.iloc[-4:-1].mean())
        if vol_prev3 <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_prev3)
        if vol_ratio < 2.0:
            return None

        # 条件4: 当日成交量 > 20日均量
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0 or vol.iloc[-1] <= vol_avg:
            return None

        strength = 0.60 + (0.15 if vol_ratio > 3.0 else 0.0) + (0.1 if close.iloc[-1] > close.iloc[-2] * 1.02 else 0.0)
        return self._make_result(
            code="P-1-8",
            strength=min(strength, 0.90),
            stage=PatternStage.CONFIRMING,
            completion=65.0,
            conditions=[
                "近5~10日前存在缩量回调阶段",
                "当日为阳线",
                f"成交量为前3日均量的{vol_ratio*100:.0f}%",
                f"成交量超过20日均量",
            ],
            interpretation="经历缩量回调后首次出现放量阳线，洗盘结束主力重新发力",
            detail={"vol_ratio_vs_prev3": round(vol_ratio, 2)},
        )

    # ══════════════════════════════════════════════════
    # P-1-9: 量比递增上涨
    # 连续多日量比递增且价格上涨，增量资金持续入场
    # ══════════════════════════════════════════════════
    def _p_1_9(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 10:
            return None

        close = df['close']
        vol = df['volume']

        # 条件1: 连续4日成交量递增
        for i in range(-4, 0):
            if vol.iloc[i] <= vol.iloc[i - 1]:
                return None

        # 条件2: 连续4日价格上涨（收盘递增）
        for i in range(-4, 0):
            if close.iloc[i] <= close.iloc[i - 1]:
                return None

        # 条件3: 最新量比（当日/20日均量）> 前日量比 > 前前日量比
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        ratios = [float(vol.iloc[i] / vol_avg) for i in range(-4, 0)]
        increasing = all(ratios[i] > ratios[i - 1] for i in range(1, len(ratios)))
        if not increasing:
            return None

        strength = 0.60 + (0.15 if ratios[-1] > 2.0 else 0.0) + (0.1 if close.iloc[-1] / close.iloc[-5] > 1.05 else 0.0)
        return self._make_result(
            code="P-1-9",
            strength=min(strength, 0.90),
            stage=PatternStage.CONFIRMING,
            completion=70.0,
            conditions=[
                "连续4日成交量递增",
                "连续4日价格上涨",
                f"量比逐日递增: {', '.join(f'{r:.1f}' for r in ratios)}",
            ],
            interpretation="连续多日量比递增且价格上涨，增量资金持续入场",
            detail={"vol_ratios": [round(r, 2) for r in ratios]},
        )

    # ══════════════════════════════════════════════════
    # P-1-10: 底部放量长阳
    # 低位出现大实体阳线伴随显著放量，底部反转强烈信号
    # ══════════════════════════════════════════════════
    def _p_1_10(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 20:
            return None

        latest = df.iloc[-1]
        close = df['close']
        vol = df['volume']

        # 条件1: 当日为大阳线（涨幅 > 4%）
        if len(df) < 2:
            return None
        pct = (latest['close'] / df.iloc[-2]['close'] - 1)
        if pct < 0.04:
            return None

        # 条件2: 实体占振幅 > 70%（光头光脚大阳）
        amplitude = latest['high'] - latest['low']
        body = self._body(latest)
        if amplitude <= 0 or body / amplitude < 0.7:
            return None

        # 条件3: 价格在低位（近60日最低30%区域）
        if len(df) >= 60:
            low_60 = df['low'].iloc[-60:].min()
            high_60 = df['high'].iloc[-60:].max()
        else:
            low_60 = df['low'].min()
            high_60 = df['high'].max()
        if high_60 <= low_60:
            return None
        price_pos = (close.iloc[-1] - low_60) / (high_60 - low_60)
        if price_pos > 0.35:
            return None

        # 条件4: 成交量 > 20日均量的2.5倍
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio < 2.5:
            return None

        strength = 0.70 + (0.10 if vol_ratio > 4.0 else 0.0) + (0.10 if pct > 0.06 else 0.0)
        return self._make_result(
            code="P-1-10",
            strength=min(strength, 0.95),
            stage=PatternStage.CONFIRMING,
            completion=80.0,
            conditions=[
                f"当日涨幅{pct*100:.1f}%大阳线",
                f"实体占比{body/amplitude*100:.0f}%",
                f"价格处于低位{price_pos*100:.0f}%",
                f"成交量为20日均量的{vol_ratio*100:.0f}%",
            ],
            interpretation="低位出现大实体阳线伴随显著放量，底部反转强烈信号",
            levels=PatternLevel(
                support=float(df['low'].iloc[-5:].min()),
                resistance=float(close.iloc[-1] * 1.08),
            ),
            detail={"pct_change": round(float(pct), 4), "vol_ratio": round(vol_ratio, 2)},
        )

    # ══════════════════════════════════════════════════
    # P-1-11: 均线多头放量
    # 均线呈多头排列且成交量放大，趋势与量能共振向上
    # ══════════════════════════════════════════════════
    def _p_1_11(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 60:
            return None

        close = df['close']
        vol = df['volume']

        # 条件1: MA5 > MA10 > MA20（多头排列）
        ma5 = float(self._ma(close, 5).iloc[-1])
        ma10 = float(self._ma(close, 10).iloc[-1])
        ma20 = float(self._ma(close, 20).iloc[-1])
        if not (ma5 > ma10 > ma20):
            return None

        # 条件2: 当日成交量 > 20日均量1.5倍
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio < 1.5:
            return None

        # 条件3: 当日为阳线
        if not self._is_yang(df.iloc[-1]):
            return None

        strength = 0.65 + (0.10 if vol_ratio > 2.5 else 0.0) + (0.10 if ma5 > ma10 * 1.01 else 0.0)
        return self._make_result(
            code="P-1-11",
            strength=min(strength, 0.90),
            stage=PatternStage.CONFIRMING,
            completion=75.0,
            conditions=[
                f"均线多头排列: MA5({ma5:.2f}) > MA10({ma10:.2f}) > MA20({ma20:.2f})",
                f"成交量为20日均量的{vol_ratio*100:.0f}%",
                "当日阳线确认",
            ],
            interpretation="均线呈多头排列且成交量放大，趋势与量能共振向上",
            detail={"ma5": round(ma5, 2), "ma10": round(ma10, 2), "ma20": round(ma20, 2), "vol_ratio": round(vol_ratio, 2)},
        )

    # ══════════════════════════════════════════════════
    # P-1-12: W底放量突破
    # W底形态颈线位伴随放量突破，底部形态确认
    # ══════════════════════════════════════════════════
    def _p_1_12(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 30:
            return None

        close = df['close']
        low = df['low']
        vol = df['volume']

        # 寻找W底：两个低点 + 中间高点（颈线）
        # 在近30~60根K线内搜索
        search_len = min(len(df), 60)
        lows_arr = low.iloc[-search_len:].values
        closes_arr = close.iloc[-search_len:].values

        # 简化W底检测：找近30日中两个局部最低点
        # 策略：先找全局最低点作为第一底，再在之后找第二个近似低点
        window = min(30, search_len)
        segment = lows_arr[-window:]
        idx1 = int(np.argmin(segment[:window // 2 + 1]))
        if window // 2 + 1 >= window:
            return None
        idx2 = int(np.argmin(segment[window // 2:])) + window // 2

        if idx1 >= idx2:
            return None

        low1 = segment[idx1]
        low2 = segment[idx2]

        # 两个低点价格接近（差距 < 5%）
        if low1 <= 0 or abs(low2 - low1) / low1 > 0.05:
            return None

        # 中间高点（颈线）
        neck_region = segment[idx1:idx2 + 1]
        if len(neck_region) < 3:
            return None
        neck_high = float(np.max(neck_region))

        # 条件: 收盘突破颈线
        if close.iloc[-1] <= neck_high:
            return None

        # 条件: 放量（> 20日均量2倍）
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio < 2.0:
            return None

        strength = 0.70 + (0.10 if vol_ratio > 3.0 else 0.0) + (0.10 if abs(low2 - low1) / low1 < 0.02 else 0.0)
        return self._make_result(
            code="P-1-12",
            strength=min(strength, 0.95),
            stage=PatternStage.CONFIRMING,
            completion=75.0,
            conditions=[
                f"W底两个低点: {low1:.2f}, {low2:.2f}",
                f"颈线位: {neck_high:.2f}",
                f"收盘{close.iloc[-1]:.2f}突破颈线",
                f"成交量为20日均量的{vol_ratio*100:.0f}%",
            ],
            interpretation="W底形态颈线位伴随放量突破，底部形态确认",
            levels=PatternLevel(
                support=float(low1),
                resistance=float(neck_high * 1.05),
            ),
            detail={"neck_high": round(float(neck_high), 2), "vol_ratio": round(vol_ratio, 2)},
        )

    # ══════════════════════════════════════════════════
    # P-1-13: 缺口放量突破
    # 向上跳空缺口伴随放量，突破力度强
    # ══════════════════════════════════════════════════
    def _p_1_13(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 10:
            return None

        curr = df.iloc[-1]
        prev = df.iloc[-2]
        vol = df['volume']

        # 条件1: 向上跳空缺口（当日最低 > 前日最高）
        if curr['low'] <= prev['high']:
            return None

        # 条件2: 成交量 > 20日均量2倍
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio < 2.0:
            return None

        # 条件3: 阳线
        if not self._is_yang(curr):
            return None

        gap_pct = (curr['low'] - prev['high']) / prev['high']

        strength = 0.65 + (0.15 if vol_ratio > 3.0 else 0.0) + (0.10 if gap_pct > 0.02 else 0.0)
        return self._make_result(
            code="P-1-13",
            strength=min(strength, 0.90),
            stage=PatternStage.CONFIRMING,
            completion=70.0,
            conditions=[
                f"向上跳空缺口{gap_pct*100:.2f}%",
                f"成交量为20日均量的{vol_ratio*100:.0f}%",
                "阳线确认突破",
            ],
            interpretation="向上跳空缺口伴随放量，突破力度强",
            levels=PatternLevel(
                support=float(prev['high']),
                resistance=float(curr['close'] * 1.05),
            ),
            detail={"gap_pct": round(float(gap_pct), 4), "vol_ratio": round(vol_ratio, 2)},
        )

    # ══════════════════════════════════════════════════
    # P-1-14: 量能潮汐启动
    # 成交量由持续萎缩转为逐步放大，量能周期拐点
    # ══════════════════════════════════════════════════
    def _p_1_14(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 20:
            return None

        vol = df['volume']
        close = df['close']

        # 条件1: 前10~5日成交量持续萎缩（均值递减）
        vol_first5 = float(vol.iloc[-15:-10].mean()) if len(vol) >= 15 else float(vol.iloc[:5].mean())
        vol_mid5 = float(vol.iloc[-10:-5].mean())
        vol_last5 = float(vol.iloc[-5:].mean())

        if vol_first5 <= 0 or vol_mid5 <= 0:
            return None

        # 先萎缩: 中间5日 < 前5日
        if vol_mid5 >= vol_first5:
            return None

        # 再放大: 最近5日 > 中间5日
        if vol_last5 <= vol_mid5:
            return None

        # 条件2: 最近5日量能 > 中间5日量能的1.5倍（明显拐点）
        if vol_mid5 <= 0 or vol_last5 < vol_mid5 * 1.5:
            return None

        # 条件3: 最新成交量 > 20日均量
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0 or vol.iloc[-1] <= vol_avg:
            return None

        strength = 0.60 + (0.15 if vol_last5 > vol_mid5 * 2.0 else 0.0) + (0.1 if close.iloc[-1] > close.iloc[-5] else 0.0)
        return self._make_result(
            code="P-1-14",
            strength=min(strength, 0.85),
            stage=PatternStage.FORMING,
            completion=50.0,
            conditions=[
                f"前期量能萎缩: {vol_first5:.0f} → {vol_mid5:.0f}",
                f"近期量能回升: {vol_mid5:.0f} → {vol_last5:.0f}",
                f"量能拐点倍率: {vol_last5/vol_mid5:.1f}x",
            ],
            interpretation="成交量由持续萎缩转为逐步放大，量能周期拐点",
            detail={"vol_before": round(vol_first5, 0), "vol_dip": round(vol_mid5, 0), "vol_after": round(vol_last5, 0)},
        )

    # ══════════════════════════════════════════════════
    # P-1-15: 主力吸筹放量
    # 低位异常放量但价格波动小，主力隐蔽建仓特征
    # ══════════════════════════════════════════════════
    def _p_1_15(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 20:
            return None

        latest = df.iloc[-1]
        vol = df['volume']
        close = df['close']

        # 条件1: 价格在低位
        if len(df) >= 60:
            low_60 = df['low'].iloc[-60:].min()
            high_60 = df['high'].iloc[-60:].max()
        else:
            low_60 = df['low'].min()
            high_60 = df['high'].max()
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

        # 条件3: 当日振幅 < 3%（价格波动小）
        if latest['low'] <= 0:
            return None
        amplitude = (latest['high'] - latest['low']) / latest['low']
        if amplitude > 0.03:
            return None

        strength = 0.65 + (0.15 if vol_ratio > 5.0 else 0.0) + (0.10 if amplitude < 0.02 else 0.0)
        return self._make_result(
            code="P-1-15",
            strength=min(strength, 0.90),
            stage=PatternStage.FORMING,
            completion=45.0,
            conditions=[
                f"价格处于低位{price_pos*100:.0f}%",
                f"成交量为20日均量的{vol_ratio*100:.0f}%（异常放量）",
                f"当日振幅仅{amplitude*100:.1f}%（窄幅波动）",
            ],
            interpretation="低位异常放量但价格波动小，主力隐蔽建仓特征",
            detail={"vol_ratio": round(vol_ratio, 2), "amplitude": round(amplitude, 4)},
        )

    # ══════════════════════════════════════════════════
    # P-1-16: 圆弧底放量
    # 圆弧底形态右侧成交量逐步放大，底部反转确认
    # ══════════════════════════════════════════════════
    def _p_1_16(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 30:
            return None

        close = df['close']
        vol = df['volume']

        # 简化圆弧底检测：
        # 1) 价格序列呈先降后升的U型（左半段降、右半段升）
        # 2) 最低点在中间偏左
        search_len = min(30, len(df))
        closes = close.iloc[-search_len:].values

        # 找最低点位置
        min_idx = int(np.argmin(closes))
        # 最低点应在中间区域（前30%~70%之间）
        if min_idx < search_len * 0.2 or min_idx > search_len * 0.7:
            return None

        # 左半段总体下降
        left = closes[:min_idx + 1]
        if len(left) < 3:
            return None
        left_desc = left[0] > left[-1] * 1.02  # 左端 > 底部2%以上

        # 右半段总体上升
        right = closes[min_idx:]
        if len(right) < 3:
            return None
        right_asc = right[-1] > right[0] * 1.02  # 右端 > 底部2%以上

        if not (left_desc and right_asc):
            return None

        # 条件2: 最近5日成交量 > 前期底部5日成交量的1.5倍（右侧放量）
        vol_bottom = float(vol.iloc[-search_len:min_idx + (-search_len + len(df)) + 1].mean()) if min_idx > 0 else float(vol.iloc[-search_len:-search_len + 5].mean())
        # 简化：取前半段均量 vs 后半段均量
        vol_left = float(vol.iloc[-search_len:-search_len + min_idx + 1].mean())
        vol_right = float(vol.iloc[-(search_len - min_idx):].mean())
        if vol_left <= 0:
            return None
        if vol_right < vol_left * 1.3:
            return None

        # 条件3: 当日阳线
        if not self._is_yang(df.iloc[-1]):
            return None

        strength = 0.65 + (0.10 if vol_right > vol_left * 1.8 else 0.0) + (0.10 if close.iloc[-1] > closes[0] else 0.0)
        return self._make_result(
            code="P-1-16",
            strength=min(strength, 0.90),
            stage=PatternStage.FORMING,
            completion=55.0,
            conditions=[
                f"价格呈圆弧底形态（U型），最低点在第{min_idx}根K线",
                f"右侧量能为左侧的{vol_right/vol_left*100:.0f}%",
                "当日阳线确认右侧上升",
            ],
            interpretation="圆弧底形态右侧成交量逐步放大，底部反转确认",
            detail={"min_idx": min_idx, "vol_ratio_rl": round(float(vol_right / vol_left), 2)},
        )

    # ══════════════════════════════════════════════════
    # P-1-17: 三阳开泰放量
    # 连续三根阳线且成交量递增，多头力量全面释放
    # ══════════════════════════════════════════════════
    def _p_1_17(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 10:
            return None

        vol = df['volume']
        close = df['close']

        # 条件1: 连续3根阳线
        for i in range(-3, 0):
            if not self._is_yang(df.iloc[i]):
                return None

        # 条件2: 成交量递增
        for i in range(-2, 0):
            if vol.iloc[i] <= vol.iloc[i - 1]:
                return None

        # 条件3: 每根收盘 > 前一根收盘（价格递增）
        for i in range(-2, 0):
            if close.iloc[i] <= close.iloc[i - 1]:
                return None

        # 条件4: 最新成交量 > 20日均量
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0 or vol.iloc[-1] <= vol_avg:
            return None

        gain_3d = (close.iloc[-1] / close.iloc[-4] - 1)

        strength = 0.65 + (0.15 if gain_3d > 0.06 else 0.0) + (0.10 if vol.iloc[-1] > vol_avg * 2 else 0.0)
        return self._make_result(
            code="P-1-17",
            strength=min(strength, 0.90),
            stage=PatternStage.CONFIRMING,
            completion=70.0,
            conditions=[
                "连续3根阳线",
                "成交量逐日递增",
                "收盘价逐日递增",
                f"3日累计涨幅{gain_3d*100:.1f}%",
            ],
            interpretation="连续三根阳线且成交量递增，多头力量全面释放",
            detail={"gain_3d": round(float(gain_3d), 4)},
        )

    # ══════════════════════════════════════════════════
    # P-1-18: 旗形整理突破
    # 旗形形态结束后放量向上突破，趋势延续信号
    # ══════════════════════════════════════════════════
    def _p_1_18(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 25:
            return None

        close = df['close']
        high = df['high']
        low = df['low']
        vol = df['volume']

        # 简化旗形检测：
        # 旗杆：近20日前有一段快速上涨（5日内涨幅>8%）
        # 旗面：随后价格小幅回调/横盘（振幅<5%），成交量萎缩
        # 突破：当日放量突破旗面上沿

        # 查找旗杆
        flagpole_found = False
        pole_high = 0.0
        for start in range(-20, -8):
            if start < -len(df) + 5:
                continue
            gain_5d = (close.iloc[start + 5] / close.iloc[start] - 1) if start + 5 < 0 else (close.iloc[-1] / close.iloc[start] - 1)
            if gain_5d > 0.08:
                flagpole_found = True
                pole_high = float(high.iloc[start + 5:start + 6].max()) if start + 6 <= 0 else float(high.iloc[-1])
                break

        if not flagpole_found or pole_high <= 0:
            return None

        # 旗面: 最近5日振幅 < 5%
        flag_high = float(high.iloc[-6:-1].max())
        flag_low = float(low.iloc[-6:-1].min())
        if flag_low <= 0:
            return None
        flag_amp = (flag_high - flag_low) / flag_low
        if flag_amp > 0.06:
            return None

        # 旗面成交量萎缩
        vol_flag = float(vol.iloc[-6:-1].mean())
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0 or vol_flag > vol_avg:
            return None

        # 突破: 当日收盘 > 旗面高点 + 放量
        if close.iloc[-1] <= flag_high:
            return None
        if vol.iloc[-1] <= vol_avg * 1.5:
            return None

        strength = 0.65 + (0.10 if float(vol.iloc[-1] / vol_avg) > 2.5 else 0.0) + (0.10 if flag_amp < 0.03 else 0.0)
        return self._make_result(
            code="P-1-18",
            strength=min(strength, 0.90),
            stage=PatternStage.CONFIRMING,
            completion=70.0,
            conditions=[
                f"旗杆: 5日涨幅>8%",
                f"旗面: 近5日振幅{flag_amp*100:.1f}%，量缩",
                f"突破旗面高点{flag_high:.2f}",
                f"成交量放大",
            ],
            interpretation="旗形形态结束后放量向上突破，趋势延续信号",
            levels=PatternLevel(support=flag_low, resistance=float(close.iloc[-1] * 1.05)),
            detail={"flag_amp": round(flag_amp, 4), "flag_high": round(flag_high, 2)},
        )

    # ══════════════════════════════════════════════════
    # P-1-19: 三角收敛突破
    # 三角形收敛末端放量向上突破，整理结束信号
    # ══════════════════════════════════════════════════
    def _p_1_19(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 25:
            return None

        close = df['close']
        high = df['high']
        low = df['low']
        vol = df['volume']

        # 简化三角形收敛检测：
        # 近15日的高点逐段降低，低点逐段抬高（振幅收窄）
        # 然后当日放量向上突破

        # 将前15日（不含当日）分成3段，计算每段高点和低点
        seg_len = 5
        segments_high = []
        segments_low = []
        for i in range(3):
            start = -16 + i * seg_len
            end = start + seg_len
            segments_high.append(float(high.iloc[start:end].max()))
            segments_low.append(float(low.iloc[start:end].min()))

        # 高点递减（至少后两段递减）
        highs_desc = segments_high[-1] < segments_high[-2] < segments_high[-3] * 1.02  # 允许2%容差
        # 低点递增
        lows_asc = segments_low[-1] > segments_low[-2] > segments_low[-3] * 0.98

        if not (highs_desc and lows_asc):
            return None

        # 振幅收窄：最后一段振幅 < 第一段的60%
        amp_first = segments_high[0] - segments_low[0]
        amp_last = segments_high[-1] - segments_low[-1]
        if amp_first <= 0 or amp_last > amp_first * 0.60:
            return None

        # 当日向上突破：收盘 > 前4日高点（突破收敛区间）
        recent_high = float(high.iloc[-5:-1].max())
        if close.iloc[-1] <= recent_high:
            return None

        # 放量
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio < 1.5:
            return None

        strength = 0.65 + (0.15 if vol_ratio > 2.5 else 0.0) + (0.10 if amp_last < amp_first * 0.4 else 0.0)
        return self._make_result(
            code="P-1-19",
            strength=min(strength, 0.90),
            stage=PatternStage.CONFIRMING,
            completion=70.0,
            conditions=[
                f"三角形收敛: 高点递减{segments_high[0]:.2f}→{segments_high[1]:.2f}→{segments_high[2]:.2f}",
                f"低点递增{segments_low[0]:.2f}→{segments_low[1]:.2f}→{segments_low[2]:.2f}",
                f"振幅收窄至{amp_last/amp_first*100:.0f}%",
                f"向上突破，成交量为20日均量的{vol_ratio*100:.0f}%",
            ],
            interpretation="三角形收敛末端放量向上突破，整理结束信号",
            levels=PatternLevel(support=segments_low[-1], resistance=float(close.iloc[-1] * 1.05)),
            detail={"amp_ratio": round(float(amp_last / amp_first), 2), "vol_ratio": round(vol_ratio, 2)},
        )

    # ══════════════════════════════════════════════════
    # P-1-20: 箱体突破放量
    # 箱体震荡区间向上突破伴随成交量放大，主升浪起点
    # ══════════════════════════════════════════════════
    def _p_1_20(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 25:
            return None

        close = df['close']
        high = df['high']
        low = df['low']
        vol = df['volume']

        # 条件1: 近20日箱体震荡（振幅 < 10%）
        box_high = float(high.iloc[-21:-1].max())
        box_low = float(low.iloc[-21:-1].min())
        if box_low <= 0:
            return None
        box_amp = (box_high - box_low) / box_low
        if box_amp > 0.10:
            return None

        # 条件2: 箱体内至少触碰上下沿各2次
        touch_high = sum(1 for i in range(-21, -1) if high.iloc[i] >= box_high * 0.995)
        touch_low = sum(1 for i in range(-21, -1) if low.iloc[i] <= box_low * 1.005)
        if touch_high < 2 or touch_low < 2:
            return None

        # 条件3: 当日向上突破箱体上沿
        if close.iloc[-1] <= box_high:
            return None

        # 条件4: 放量突破
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio < 1.8:
            return None

        strength = 0.70 + (0.10 if vol_ratio > 2.5 else 0.0) + (0.10 if box_amp < 0.06 else 0.0)
        return self._make_result(
            code="P-1-20",
            strength=min(strength, 0.95),
            stage=PatternStage.CONFIRMING,
            completion=75.0,
            conditions=[
                f"箱体震荡: 高点{box_high:.2f} 低点{box_low:.2f}（振幅{box_amp*100:.1f}%）",
                f"触碰上沿{touch_high}次、下沿{touch_low}次",
                f"收盘{close.iloc[-1]:.2f}突破箱体上沿",
                f"成交量为20日均量的{vol_ratio*100:.0f}%",
            ],
            interpretation="箱体震荡区间向上突破伴随成交量放大，主升浪起点",
            levels=PatternLevel(
                support=box_high,
                resistance=float(close.iloc[-1] + (box_high - box_low)),
            ),
            detail={"box_high": round(box_high, 2), "box_low": round(box_low, 2), "vol_ratio": round(vol_ratio, 2)},
        )
