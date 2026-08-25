"""
四类八种量价状态检测器
======================
基于 Wiki 动态量价状态感知策略。

四类：
  1. 健康动量 — S-1 价涨量增, S-2 价跌量缩
  2. 背离预警 — S-3 价涨量缩, S-4 价跌量增
  3. 极端信号 — S-5 天量天价, S-6 地量地价
  4. 筹码转换 — S-7 放量突破, S-8 缩量回踩

每种状态对应一个独立检测方法（_s_1 ~ _s_8），
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


class StateDetector(PatternDetector):
    """四类八种状态检测器"""

    # 状态名称映射
    _NAMES = {
        "S-1": "价涨量增",
        "S-2": "价跌量缩",
        "S-3": "价涨量缩",
        "S-4": "价跌量增",
        "S-5": "天量天价",
        "S-6": "地量地价",
        "S-7": "放量突破",
        "S-8": "缩量回踩",
    }

    # 状态分类映射
    _CATEGORIES = {
        "S-1": "健康动量",
        "S-2": "健康动量",
        "S-3": "背离预警",
        "S-4": "背离预警",
        "S-5": "极端信号",
        "S-6": "极端信号",
        "S-7": "筹码转换",
        "S-8": "筹码转换",
    }

    def detect(self, df: pd.DataFrame, context: Optional[Dict] = None) -> List[PatternResult]:
        """检测所有状态"""
        if df.empty or len(df) < 20:
            return []

        results: List[PatternResult] = []
        detectors = [
            self._s_1, self._s_2, self._s_3, self._s_4,
            self._s_5, self._s_6, self._s_7, self._s_8,
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

    def _make_result(
        self,
        code: str,
        strength: float,
        stage: PatternStage,
        completion: float,
        conditions: List[str],
        interpretation: str,
        direction: str = 'neutral',
        levels: Optional[PatternLevel] = None,
        detail: Optional[Dict] = None,
        invalidation: Optional[List[str]] = None,
    ) -> PatternResult:
        """统一构造 PatternResult"""
        return PatternResult(
            name=code,
            category=PatternCategory.STATE,
            direction=direction,
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
    # 健康动量类
    # ══════════════════════════════════════════════════

    def _s_1(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        """
        S-1: 价涨量增 — 健康动量
        收盘价>前收盘价 且 成交量>20日均量×1.2
        """
        close = df['close']
        vol = df['volume']

        # 条件1: 收盘价 > 前收盘价
        if close.iloc[-1] <= close.iloc[-2]:
            return None

        # 条件2: 成交量 > 20日均量 × 1.2
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio < 1.2:
            return None

        # 计算涨幅
        pct_change = float((close.iloc[-1] / close.iloc[-2] - 1))

        strength = 0.50 + (0.15 if vol_ratio > 1.5 else 0.0) + (0.10 if pct_change > 0.02 else 0.0)
        return self._make_result(
            code="S-1",
            strength=min(strength, 0.85),
            stage=PatternStage.CONFIRMING,
            completion=70.0,
            direction='bullish',
            conditions=[
                f"收盘价{close.iloc[-1]:.2f} > 前收盘{close.iloc[-2]:.2f}",
                f"成交量为20日均量的{vol_ratio * 100:.0f}%",
            ],
            interpretation="价涨量增，多方力量健康释放，上涨趋势确认中",
            detail={
                "pct_change": round(pct_change, 4),
                "vol_ratio": round(vol_ratio, 2),
            },
        )

    def _s_2(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        """
        S-2: 价跌量缩 — 健康动量
        收盘价<前收盘价 且 成交量<20日均量×0.8
        """
        close = df['close']
        vol = df['volume']

        # 条件1: 收盘价 < 前收盘价
        if close.iloc[-1] >= close.iloc[-2]:
            return None

        # 条件2: 成交量 < 20日均量 × 0.8
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio >= 0.8:
            return None

        pct_change = float((close.iloc[-1] / close.iloc[-2] - 1))

        strength = 0.40 + (0.15 if vol_ratio < 0.5 else 0.0) + (0.10 if abs(pct_change) < 0.02 else 0.0)
        return self._make_result(
            code="S-2",
            strength=min(strength, 0.75),
            stage=PatternStage.CONFIRMING,
            completion=65.0,
            direction='bullish',
            conditions=[
                f"收盘价{close.iloc[-1]:.2f} < 前收盘{close.iloc[-2]:.2f}",
                f"成交量为20日均量的{vol_ratio * 100:.0f}%",
            ],
            interpretation="价跌量缩，下跌动能减弱，缩量回调为健康调整信号",
            detail={
                "pct_change": round(pct_change, 4),
                "vol_ratio": round(vol_ratio, 2),
            },
        )

    # ══════════════════════════════════════════════════
    # 背离预警类
    # ══════════════════════════════════════════════════

    def _s_3(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        """
        S-3: 价涨量缩 — 背离预警
        收盘价创新高（近20日） 但 成交量连续3日低于均量
        """
        close = df['close']
        vol = df['volume']

        if len(df) < 20:
            return None

        # 条件1: 收盘价创近20日新高
        high_20 = float(close.iloc[-21:-1].max())
        if close.iloc[-1] <= high_20:
            return None

        # 条件2: 成交量连续3日低于20日均量
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        for i in range(-3, 0):
            if float(vol.iloc[i]) >= vol_avg:
                return None

        # 量比（最近3日平均 vs 均量）
        vol_ratio_3d = float(vol.iloc[-3:].mean() / vol_avg)

        strength = 0.55 + (0.15 if vol_ratio_3d < 0.5 else 0.0) + (0.10 if float(close.iloc[-1]) > high_20 * 1.01 else 0.0)
        return self._make_result(
            code="S-3",
            strength=min(strength, 0.85),
            stage=PatternStage.FORMING,
            completion=60.0,
            direction='bearish',
            conditions=[
                f"收盘价{close.iloc[-1]:.2f}创近20日新高(前高{high_20:.2f})",
                f"成交量连续3日低于均量，3日平均量比{vol_ratio_3d:.2f}",
            ],
            interpretation="价涨量缩，价格创新高但量能萎缩，顶背离预警信号",
            invalidation=["成交量恢复放大超过均量", "价格突破前高后量能配合"],
            detail={
                "high_20": round(high_20, 2),
                "vol_ratio_3d": round(vol_ratio_3d, 2),
            },
        )

    def _s_4(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        """
        S-4: 价跌量增 — 背离预警
        收盘价新低（近20日） 但 成交量连续放大（连续3日递增）
        """
        close = df['close']
        vol = df['volume']

        if len(df) < 20:
            return None

        # 条件1: 收盘价创近20日新低
        low_20 = float(close.iloc[-21:-1].min())
        if close.iloc[-1] >= low_20:
            return None

        # 条件2: 成交量连续放大（连续3日递增）
        for i in range(-3, -1):
            if float(vol.iloc[i]) >= float(vol.iloc[i + 1]):
                return None

        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)

        strength = 0.55 + (0.15 if vol_ratio > 1.5 else 0.0) + (0.10 if float(close.iloc[-1]) < low_20 * 0.99 else 0.0)
        return self._make_result(
            code="S-4",
            strength=min(strength, 0.85),
            stage=PatternStage.FORMING,
            completion=60.0,
            direction='bearish',
            conditions=[
                f"收盘价{close.iloc[-1]:.2f}创近20日新低(前低{low_20:.2f})",
                f"成交量连续3日递增，最新量比{vol_ratio:.2f}",
            ],
            interpretation="价跌量增，价格创新低伴随放量，恐慌抛售或底部换手信号",
            invalidation=["成交量迅速萎缩至均量以下", "价格止跌企稳"],
            detail={
                "low_20": round(low_20, 2),
                "vol_ratio": round(vol_ratio, 2),
            },
        )

    # ══════════════════════════════════════════════════
    # 极端信号类
    # ══════════════════════════════════════════════════

    def _s_5(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        """
        S-5: 天量天价 — 极端信号
        成交量创60日新高 且 价格创20日新高
        """
        close = df['close']
        high = df['high']
        vol = df['volume']

        if len(df) < 60:
            return None

        # 条件1: 成交量创60日新高
        vol_60_max = float(vol.iloc[-61:-1].max())
        if float(vol.iloc[-1]) <= vol_60_max:
            return None

        # 条件2: 价格创20日新高（用最高价判断）
        high_20 = float(high.iloc[-21:-1].max())
        if float(high.iloc[-1]) <= high_20:
            return None

        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)

        strength = 0.65 + (0.10 if vol_ratio > 3.0 else 0.0) + (0.10 if float(high.iloc[-1]) > high_20 * 1.02 else 0.0)
        return self._make_result(
            code="S-5",
            strength=min(strength, 0.90),
            stage=PatternStage.CONFIRMING,
            completion=75.0,
            direction='bearish',
            conditions=[
                f"成交量创60日新高({vol.iloc[-1]:.0f} > {vol_60_max:.0f})",
                f"价格创20日新高({high.iloc[-1]:.2f} > {high_20:.2f})",
                f"成交量为20日均量的{vol_ratio * 100:.0f}%",
            ],
            interpretation="天量天价，成交量与价格同步创新高，极端行情需警惕反转",
            invalidation=["成交量快速萎缩", "价格回落至20日均线下方"],
            levels=PatternLevel(
                resistance=float(high.iloc[-1]),
                support=float(close.iloc[-2]),
            ),
            detail={
                "vol_60_max_prev": round(vol_60_max, 0),
                "high_20_prev": round(high_20, 2),
                "vol_ratio": round(vol_ratio, 2),
            },
        )

    def _s_6(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        """
        S-6: 地量地价 — 极端信号
        成交量创60日新低 且 价格创20日新低
        """
        close = df['close']
        low = df['low']
        vol = df['volume']

        if len(df) < 60:
            return None

        # 条件1: 成交量创60日新低
        vol_60_min = float(vol.iloc[-61:-1].min())
        if float(vol.iloc[-1]) >= vol_60_min:
            return None

        # 条件2: 价格创20日新低（用最低价判断）
        low_20 = float(low.iloc[-21:-1].min())
        if float(low.iloc[-1]) >= low_20:
            return None

        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)

        strength = 0.55 + (0.15 if vol_ratio < 0.3 else 0.0) + (0.10 if float(low.iloc[-1]) < low_20 * 0.98 else 0.0)
        return self._make_result(
            code="S-6",
            strength=min(strength, 0.85),
            stage=PatternStage.FORMING,
            completion=55.0,
            direction='bullish',
            conditions=[
                f"成交量创60日新低({vol.iloc[-1]:.0f} < {vol_60_min:.0f})",
                f"价格创20日新低({low.iloc[-1]:.2f} < {low_20:.2f})",
                f"成交量仅为20日均量的{vol_ratio * 100:.0f}%",
            ],
            interpretation="地量地价，卖盘枯竭价格触底，可能接近底部反转区域",
            invalidation=["成交量突然放大伴随价格继续下跌", "跌破新低后继续放量下杀"],
            levels=PatternLevel(
                support=float(low.iloc[-1]),
                resistance=float(close.iloc[-1] * 1.05),
            ),
            detail={
                "vol_60_min_prev": round(vol_60_min, 0),
                "low_20_prev": round(low_20, 2),
                "vol_ratio": round(vol_ratio, 2),
            },
        )

    # ══════════════════════════════════════════════════
    # 筹码转换类
    # ══════════════════════════════════════════════════

    def _s_7(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        """
        S-7: 放量突破 — 筹码转换
        股价突破关键均线（MA20） 且 放量（成交量>20日均量×1.5）
        """
        close = df['close']
        vol = df['volume']

        # 计算 MA20
        ma20 = self._ma(close, 20)
        ma20_val = float(ma20.iloc[-1])

        # 条件1: 收盘价突破 MA20（当日收盘 > MA20 且 前日收盘 <= MA20）
        if len(ma20) < 2:
            return None
        prev_ma20 = float(ma20.iloc[-2])
        if float(close.iloc[-1]) <= ma20_val:
            return None
        if float(close.iloc[-2]) > prev_ma20:
            return None  # 已经在均线上方，不算突破

        # 条件2: 放量（成交量 > 20日均量 × 1.5）
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio < 1.5:
            return None

        strength = 0.60 + (0.15 if vol_ratio > 2.5 else 0.0) + (0.10 if float(close.iloc[-1]) > ma20_val * 1.01 else 0.0)
        return self._make_result(
            code="S-7",
            strength=min(strength, 0.90),
            stage=PatternStage.CONFIRMING,
            completion=70.0,
            direction='bullish',
            conditions=[
                f"收盘价{close.iloc[-1]:.2f}突破MA20({ma20_val:.2f})",
                f"成交量为20日均量的{vol_ratio * 100:.0f}%",
            ],
            interpretation="放量突破关键均线，筹码由空方转向多方，趋势转换信号",
            invalidation=["价格回落至MA20下方", "成交量快速萎缩"],
            levels=PatternLevel(
                support=ma20_val,
                resistance=float(close.iloc[-1] * 1.05),
            ),
            detail={
                "ma20": round(ma20_val, 2),
                "vol_ratio": round(vol_ratio, 2),
            },
        )

    def _s_8(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        """
        S-8: 缩量回踩 — 筹码转换
        股价回踩不破关键均线（MA20） 且 大幅缩量（成交量<20日均量×0.5）
        """
        close = df['close']
        low = df['low']
        vol = df['volume']

        # 计算 MA20
        ma20 = self._ma(close, 20)
        ma20_val = float(ma20.iloc[-1])

        # 条件1: 收盘价在 MA20 上方（维持趋势）
        if float(close.iloc[-1]) <= ma20_val:
            return None

        # 条件2: 最低价回踩 MA20 附近不破（低点 >= MA20 的 97%）
        if float(low.iloc[-1]) < ma20_val * 0.97:
            return None

        # 条件3: 大幅缩量（成交量 < 20日均量 × 0.5）
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio >= 0.5:
            return None

        # 条件4: 前5日有放量行为（至少有1日量能 > 均量，说明之前有过拉升）
        recent_vol = vol.iloc[-6:-1]
        had_volume = any(float(v) > vol_avg for v in recent_vol)
        if not had_volume:
            return None

        strength = 0.55 + (0.15 if vol_ratio < 0.3 else 0.0) + (0.10 if float(close.iloc[-1]) > ma20_val * 1.005 else 0.0)
        return self._make_result(
            code="S-8",
            strength=min(strength, 0.85),
            stage=PatternStage.CONFIRMING,
            completion=65.0,
            direction='bullish',
            conditions=[
                f"收盘价{close.iloc[-1]:.2f}在MA20({ma20_val:.2f})之上",
                f"最低价回踩MA20附近不破",
                f"成交量仅为20日均量的{vol_ratio * 100:.0f}%（大幅缩量）",
            ],
            interpretation="缩量回踩关键均线不破，洗盘结束筹码锁定，即将再次拉升",
            invalidation=["价格跌破MA20支撑", "回踩后成交量持续放大但价格不涨"],
            levels=PatternLevel(
                support=ma20_val,
                resistance=float(close.iloc[-1] * 1.08),
            ),
            detail={
                "ma20": round(ma20_val, 2),
                "vol_ratio": round(vol_ratio, 2),
            },
        )
