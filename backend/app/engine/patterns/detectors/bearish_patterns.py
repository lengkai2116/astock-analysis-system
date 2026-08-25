"""
预跌型量价形态检测器（20种）
============================
基于《量价狙击》第七章的 20 种预跌型形态定义。

每种形态对应一个独立检测方法（_p_2_1 ~ _p_2_20），
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


class BearishPatternDetector(PatternDetector):
    """预跌型形态检测器 — 检测 20 种看跌量价形态"""

    # 形态名称映射（注册表 code → 中文名）
    _NAMES = {
        "P-2-1":  "高位量价背离",
        "P-2-2":  "放量滞涨",
        "P-2-3":  "顶部缩量反弹",
        "P-2-4":  "天量见天价",
        "P-2-5":  "连续缩量下跌",
        "P-2-6":  "高位放量十字星",
        "P-2-7":  "断头铡刀放量",
        "P-2-8":  "M顶放量跌破",
        "P-2-9":  "头肩顶放量破位",
        "P-2-10": "高位阴线放量",
        "P-2-11": "均线空头放量",
        "P-2-12": "反弹受阻缩量",
        "P-2-13": "放量跌破平台",
        "P-2-14": "向下缺口放量",
        "P-2-15": "高换手率暴跌",
        "P-2-16": "乌云盖顶放量",
        "P-2-17": "黄昏之星放量",
        "P-2-18": "下跌三浪放量",
        "P-2-19": "圆弧顶缩量",
        "P-2-20": "旗形下跌破位",
    }

    def detect(self, df: pd.DataFrame, context: Optional[Dict] = None) -> List[PatternResult]:
        """检测所有预跌型形态"""
        if df.empty or len(df) < 20:
            return []

        results: List[PatternResult] = []
        detectors = [
            self._p_2_1,  self._p_2_2,  self._p_2_3,  self._p_2_4,  self._p_2_5,
            self._p_2_6,  self._p_2_7,  self._p_2_8,  self._p_2_9,  self._p_2_10,
            self._p_2_11, self._p_2_12, self._p_2_13, self._p_2_14, self._p_2_15,
            self._p_2_16, self._p_2_17, self._p_2_18, self._p_2_19, self._p_2_20,
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
            category=PatternCategory.BEARISH_PATTERNS,
            direction='bearish',
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
    # P-2-1: 高位量价背离
    # 价格创新高但成交量递减，上涨动力衰竭
    # ══════════════════════════════════════════════════
    def _p_2_1(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 30:
            return None

        close = df['close']
        high = df['high']
        vol = df['volume']

        # 条件1: 价格在高位（近60日最高20%区域）
        lookback = min(60, len(df))
        high_60 = float(high.iloc[-lookback:].max())
        low_60 = float(df['low'].iloc[-lookback:].min())
        if high_60 <= low_60:
            return None
        price_pos = (close.iloc[-1] - low_60) / (high_60 - low_60)
        if price_pos < 0.75:
            return None

        # 条件2: 近5日价格创新高（最高价 > 前10日最高价）
        recent_high_5 = float(high.iloc[-5:].max())
        prior_high_10 = float(high.iloc[-15:-5].max())
        if recent_high_5 <= prior_high_10:
            return None

        # 条件3: 近5日成交量均值 < 前5日成交量均值（量能递减）
        vol_recent5 = float(vol.iloc[-5:].mean())
        vol_prior5 = float(vol.iloc[-10:-5].mean())
        if vol_prior5 <= 0 or vol_recent5 >= vol_prior5:
            return None

        # 条件4: 最新成交量 < 20日均量
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0 or vol.iloc[-1] >= vol_avg:
            return None

        vol_ratio = float(vol.iloc[-1] / vol_avg)
        strength = 0.65 + (0.15 if vol_ratio < 0.6 else 0.0) + (0.10 if price_pos > 0.90 else 0.0)
        return self._make_result(
            code="P-2-1",
            strength=min(strength, 0.95),
            stage=PatternStage.FORMING,
            completion=55.0,
            conditions=[
                f"价格处于近高位{price_pos*100:.0f}%区域",
                f"近5日价格创新高({recent_high_5:.2f})",
                f"成交量递减: {vol_prior5:.0f} → {vol_recent5:.0f}",
                f"成交量仅为20日均量的{vol_ratio*100:.0f}%",
            ],
            interpretation="价格创新高但成交量递减，上涨动力衰竭",
            levels=PatternLevel(
                resistance=float(high_60),
                target=float(close.iloc[-1] * 0.92),
            ),
            detail={"price_position": round(price_pos, 3), "vol_ratio": round(vol_ratio, 2)},
        )

    # ══════════════════════════════════════════════════
    # P-2-2: 放量滞涨
    # 成交量显著放大但价格未能上涨，主力出货迹象
    # ══════════════════════════════════════════════════
    def _p_2_2(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 20:
            return None

        latest = df.iloc[-1]
        close = df['close']
        vol = df['volume']

        # 条件1: 价格在高位（近60日最高30%区域）
        lookback = min(60, len(df))
        high_60 = float(df['high'].iloc[-lookback:].max())
        low_60 = float(df['low'].iloc[-lookback:].min())
        if high_60 <= low_60:
            return None
        price_pos = (close.iloc[-1] - low_60) / (high_60 - low_60)
        if price_pos < 0.70:
            return None

        # 条件2: 成交量 > 20日均量的2倍
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio < 2.0:
            return None

        # 条件3: 价格涨幅 < 1%（滞涨）
        if len(df) < 2:
            return None
        pct_change = (latest['close'] / df.iloc[-2]['close'] - 1)
        if pct_change > 0.01:
            return None

        # 条件4: 阴线或十字星（非强势阳线）
        if self._is_yang(latest) and self._body(latest) / (latest['high'] - latest['low'] + 1e-9) > 0.5:
            return None

        strength = 0.65 + (0.15 if vol_ratio > 3.0 else 0.0) + (0.10 if pct_change < -0.01 else 0.0)
        return self._make_result(
            code="P-2-2",
            strength=min(strength, 0.95),
            stage=PatternStage.CONFIRMING,
            completion=70.0,
            conditions=[
                f"价格处于高位{price_pos*100:.0f}%区域",
                f"成交量为20日均量的{vol_ratio*100:.0f}%（显著放量）",
                f"当日涨跌幅{pct_change*100:.1f}%（滞涨）",
                "阴线或十字星形态",
            ],
            interpretation="成交量显著放大但价格未能上涨，主力出货迹象",
            levels=PatternLevel(
                resistance=float(high_60),
                target=float(close.iloc[-1] * 0.90),
            ),
            detail={"vol_ratio": round(vol_ratio, 2), "pct_change": round(float(pct_change), 4)},
        )

    # ══════════════════════════════════════════════════
    # P-2-3: 顶部缩量反弹
    # 下跌趋势中缩量反弹，反弹力度弱不可持续
    # ══════════════════════════════════════════════════
    def _p_2_3(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 25:
            return None

        close = df['close']
        vol = df['volume']

        # 条件1: MA20 下行（当前MA20 < 5日前MA20）
        ma20 = self._ma(close, 20)
        if len(ma20) < 6:
            return None
        ma20_declining = float(ma20.iloc[-1]) < float(ma20.iloc[-6])
        if not ma20_declining:
            return None

        # 条件2: 近3日反弹（收盘价 > 3日前收盘价）
        if close.iloc[-1] <= close.iloc[-4]:
            return None
        bounce_pct = (close.iloc[-1] / close.iloc[-4] - 1)

        # 条件3: 反弹期间成交量 < 20日均量（缩量反弹）
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_bounce = float(vol.iloc[-3:].mean())
        if vol_bounce >= vol_avg:
            return None

        # 条件4: 收盘价仍低于MA20（反弹受阻于均线下方）
        ma20_val = float(ma20.iloc[-1])
        if close.iloc[-1] > ma20_val * 1.02:
            return None

        strength = 0.60 + (0.15 if vol_bounce < vol_avg * 0.6 else 0.0) + (0.10 if bounce_pct < 0.03 else 0.0)
        return self._make_result(
            code="P-2-3",
            strength=min(strength, 0.85),
            stage=PatternStage.FORMING,
            completion=50.0,
            conditions=[
                f"MA20下行({ma20_val:.2f})",
                f"近3日反弹{bounce_pct*100:.1f}%",
                f"反弹期间成交量仅为20日均量的{vol_bounce/vol_avg*100:.0f}%",
                "收盘价仍在MA20下方",
            ],
            interpretation="下跌趋势中缩量反弹，反弹力度弱不可持续",
            levels=PatternLevel(
                resistance=ma20_val,
                target=float(close.iloc[-1] * 0.93),
            ),
            detail={"bounce_pct": round(float(bounce_pct), 4), "vol_ratio": round(float(vol_bounce / vol_avg), 2)},
        )

    # ══════════════════════════════════════════════════
    # P-2-4: 天量见天价
    # 出现异常巨量后价格见顶，换手率极高主力出逃
    # ══════════════════════════════════════════════════
    def _p_2_4(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 20:
            return None

        latest = df.iloc[-1]
        close = df['close']
        vol = df['volume']

        # 条件1: 价格在高位（近60日最高20%区域）
        lookback = min(60, len(df))
        high_60 = float(df['high'].iloc[-lookback:].max())
        low_60 = float(df['low'].iloc[-lookback:].min())
        if high_60 <= low_60:
            return None
        price_pos = (close.iloc[-1] - low_60) / (high_60 - low_60)
        if price_pos < 0.80:
            return None

        # 条件2: 成交量 > 4倍20日均量（天量）
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio < 4.0:
            return None

        # 条件3: 出现上影线或十字星（冲高回落迹象）
        amplitude = latest['high'] - latest['low']
        if amplitude <= 0:
            return None
        upper_shadow = latest['high'] - max(latest['close'], latest['open'])
        has_upper_shadow = upper_shadow / amplitude > 0.3 or self._is_doji(latest)
        if not has_upper_shadow:
            return None

        strength = 0.70 + (0.15 if vol_ratio > 6.0 else 0.0) + (0.10 if upper_shadow / amplitude > 0.5 else 0.0)
        return self._make_result(
            code="P-2-4",
            strength=min(strength, 0.95),
            stage=PatternStage.CONFIRMING,
            completion=75.0,
            conditions=[
                f"价格处于高位{price_pos*100:.0f}%区域",
                f"成交量为20日均量的{vol_ratio*100:.0f}%（天量）",
                "出现上影线或十字星（冲高回落）",
            ],
            interpretation="出现异常巨量后价格见顶，换手率极高主力出逃",
            levels=PatternLevel(
                resistance=float(high_60),
                target=float(close.iloc[-1] * 0.88),
                support=float(close.iloc[-1] * 0.95),
            ),
            detail={"vol_ratio": round(vol_ratio, 2), "price_position": round(price_pos, 3)},
        )

    # ══════════════════════════════════════════════════
    # P-2-5: 连续缩量下跌
    # 连续多日成交量萎缩价格下跌，买盘枯竭
    # ══════════════════════════════════════════════════
    def _p_2_5(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 20:
            return None

        close = df['close']
        vol = df['volume']

        # 条件1: 连续5日收盘递减
        for i in range(-5, 0):
            if close.iloc[i] >= close.iloc[i - 1]:
                return None

        # 条件2: 连续5日成交量递减（或至少总体递减趋势）
        for i in range(-4, 0):
            if vol.iloc[i] >= vol.iloc[i - 1]:
                return None

        # 条件3: 5日累计跌幅 > 5%
        drop_5d = (close.iloc[-1] / close.iloc[-6] - 1)
        if drop_5d > -0.05:
            return None

        # 条件4: 最新成交量 < 20日均量的50%（地量）
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio > 0.50:
            return None

        strength = 0.60 + (0.15 if drop_5d < -0.08 else 0.0) + (0.10 if vol_ratio < 0.3 else 0.0)
        return self._make_result(
            code="P-2-5",
            strength=min(strength, 0.90),
            stage=PatternStage.CONFIRMING,
            completion=70.0,
            conditions=[
                "连续5日收盘价递减",
                "连续5日成交量递减",
                f"5日累计跌幅{drop_5d*100:.1f}%",
                f"成交量仅为20日均量的{vol_ratio*100:.0f}%（地量）",
            ],
            interpretation="连续多日成交量萎缩价格下跌，买盘枯竭",
            detail={"drop_5d": round(float(drop_5d), 4), "vol_ratio": round(vol_ratio, 2)},
        )

    # ══════════════════════════════════════════════════
    # P-2-6: 高位放量十字星
    # 高位出现放量十字星，多空分歧加大见顶信号
    # ══════════════════════════════════════════════════
    def _p_2_6(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 20:
            return None

        latest = df.iloc[-1]
        close = df['close']
        vol = df['volume']

        # 条件1: 价格在高位（近60日最高30%区域）
        lookback = min(60, len(df))
        high_60 = float(df['high'].iloc[-lookback:].max())
        low_60 = float(df['low'].iloc[-lookback:].min())
        if high_60 <= low_60:
            return None
        price_pos = (close.iloc[-1] - low_60) / (high_60 - low_60)
        if price_pos < 0.70:
            return None

        # 条件2: 最后一根为十字星
        if not self._is_doji(latest):
            return None

        # 条件3: 成交量 > 20日均量的1.5倍（放量）
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio < 1.5:
            return None

        # 条件4: 前期有上涨趋势（近10日累计涨幅 > 3%）
        gain_10d = (close.iloc[-1] / close.iloc[-11] - 1) if len(df) >= 11 else 0
        if gain_10d < 0.03:
            return None

        strength = 0.65 + (0.15 if vol_ratio > 2.5 else 0.0) + (0.10 if price_pos > 0.85 else 0.0)
        return self._make_result(
            code="P-2-6",
            strength=min(strength, 0.90),
            stage=PatternStage.CONFIRMING,
            completion=65.0,
            conditions=[
                f"价格处于高位{price_pos*100:.0f}%区域",
                "最后一根K线为十字星",
                f"成交量为20日均量的{vol_ratio*100:.0f}%（放量）",
                f"前期上涨{gain_10d*100:.1f}%",
            ],
            interpretation="高位出现放量十字星，多空分歧加大见顶信号",
            levels=PatternLevel(
                resistance=float(high_60),
                target=float(close.iloc[-1] * 0.92),
            ),
            detail={"price_position": round(price_pos, 3), "vol_ratio": round(vol_ratio, 2)},
        )

    # ══════════════════════════════════════════════════
    # P-2-7: 断头铡刀放量
    # 大阴线直接跌破多条均线伴随放量，趋势反转
    # ══════════════════════════════════════════════════
    def _p_2_7(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 25:
            return None

        latest = df.iloc[-1]
        close = df['close']
        vol = df['volume']

        # 条件1: 当日为大阴线（跌幅 > 3%）
        if len(df) < 2:
            return None
        pct = (latest['close'] / df.iloc[-2]['close'] - 1)
        if pct > -0.03:
            return None

        # 条件2: 收盘价跌破MA20和MA10
        ma10 = float(self._ma(close, 10).iloc[-1])
        ma20 = float(self._ma(close, 20).iloc[-1])
        if latest['close'] >= ma10 or latest['close'] >= ma20:
            return None

        # 条件3: MA20此前上行或平坦（前5日MA20未明显下行）
        ma20_series = self._ma(close, 20)
        if len(ma20_series) >= 6:
            ma20_slope = float(ma20_series.iloc[-6]) - float(ma20_series.iloc[-1])
            if ma20_slope > ma20 * 0.03:  # MA20已明显下行
                return None

        # 条件4: 成交量 > 20日均量的2倍
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio < 2.0:
            return None

        strength = 0.70 + (0.10 if pct < -0.05 else 0.0) + (0.10 if vol_ratio > 3.0 else 0.0)
        return self._make_result(
            code="P-2-7",
            strength=min(strength, 0.95),
            stage=PatternStage.CONFIRMING,
            completion=80.0,
            conditions=[
                f"当日跌幅{pct*100:.1f}%大阴线",
                f"跌破MA10({ma10:.2f})和MA20({ma20:.2f})",
                f"成交量为20日均量的{vol_ratio*100:.0f}%",
                "前期均线未明显下行（趋势突然反转）",
            ],
            interpretation="大阴线直接跌破多条均线伴随放量，趋势反转",
            levels=PatternLevel(
                resistance=ma20,
                target=float(close.iloc[-1] * 0.90),
                invalidation=float(ma20 * 1.02),
            ),
            detail={"pct_change": round(float(pct), 4), "vol_ratio": round(vol_ratio, 2), "ma10": round(ma10, 2), "ma20": round(ma20, 2)},
        )

    # ══════════════════════════════════════════════════
    # P-2-8: M顶放量跌破
    # M顶形态颈线位放量跌破，顶部形态确认
    # ══════════════════════════════════════════════════
    def _p_2_8(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 30:
            return None

        close = df['close']
        high = df['high']
        low = df['low']
        vol = df['volume']

        # 在近30~60根K线内搜索M顶
        search_len = min(60, len(df))
        highs_arr = high.iloc[-search_len:].values
        lows_arr = low.iloc[-search_len:].values
        closes_arr = close.iloc[-search_len:].values

        # 找两个高点（M顶的两个峰）
        window = min(30, search_len)
        seg = highs_arr[-window:]
        # 第一个峰在前半段
        idx1 = int(np.argmax(seg[:window // 2 + 1]))
        if window // 2 + 1 >= window:
            return None
        # 第二个峰在后半段
        idx2 = int(np.argmax(seg[window // 2:])) + window // 2

        if idx1 >= idx2:
            return None

        peak1 = seg[idx1]
        peak2 = seg[idx2]

        # 两个高点接近（差距 < 5%）
        if peak1 <= 0 or abs(peak2 - peak1) / peak1 > 0.05:
            return None

        # 颈线位（两个峰之间的最低点）
        valley = float(np.min(lows_arr[-window:][idx1:idx2 + 1]))
        if len(lows_arr[-window:][idx1:idx2 + 1]) < 3:
            return None

        # 条件: 收盘跌破颈线
        if close.iloc[-1] >= valley:
            return None

        # 条件: 放量（> 20日均量1.5倍）
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio < 1.5:
            return None

        strength = 0.70 + (0.10 if vol_ratio > 2.5 else 0.0) + (0.10 if abs(peak2 - peak1) / peak1 < 0.02 else 0.0)
        return self._make_result(
            code="P-2-8",
            strength=min(strength, 0.95),
            stage=PatternStage.CONFIRMING,
            completion=75.0,
            conditions=[
                f"M顶两个高点: {peak1:.2f}, {peak2:.2f}",
                f"颈线位: {valley:.2f}",
                f"收盘{close.iloc[-1]:.2f}跌破颈线",
                f"成交量为20日均量的{vol_ratio*100:.0f}%",
            ],
            interpretation="M顶形态颈线位放量跌破，顶部形态确认",
            levels=PatternLevel(
                resistance=valley,
                target=float(valley - (float(np.mean([peak1, peak2])) - valley)),
            ),
            detail={"peak1": round(float(peak1), 2), "peak2": round(float(peak2), 2), "valley": round(valley, 2), "vol_ratio": round(vol_ratio, 2)},
        )

    # ══════════════════════════════════════════════════
    # P-2-9: 头肩顶放量破位
    # 头肩顶形态右肩放量跌破颈线，经典顶部反转
    # ══════════════════════════════════════════════════
    def _p_2_9(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 40:
            return None

        close = df['close']
        high = df['high']
        low = df['low']
        vol = df['volume']

        # 在近40根K线内寻找头肩顶
        search_len = min(40, len(df))
        highs_arr = high.iloc[-search_len:].values
        lows_arr = low.iloc[-search_len:].values

        # 将搜索区间分为三段，每段找一个局部高点
        seg_len = search_len // 3
        if seg_len < 5:
            return None

        # 左肩
        left_seg = highs_arr[:seg_len]
        left_shoulder_idx = int(np.argmax(left_seg))
        left_shoulder = float(left_seg[left_shoulder_idx])

        # 头部（最高点应在中间段）
        mid_seg = highs_arr[seg_len:2 * seg_len]
        head_idx = int(np.argmax(mid_seg)) + seg_len
        head = float(highs_arr[head_idx])

        # 右肩
        right_seg = highs_arr[2 * seg_len:]
        right_shoulder_idx = int(np.argmax(right_seg)) + 2 * seg_len
        right_shoulder = float(right_seg[right_shoulder_idx - 2 * seg_len])

        # 头部应高于两肩
        if head <= left_shoulder or head <= right_shoulder:
            return None

        # 右肩低于左肩（可选但增强信号）
        right_lower = right_shoulder < left_shoulder

        # 颈线：左肩到右肩之间的最低低点
        neckline_region = lows_arr[left_shoulder_idx:right_shoulder_idx + 1]
        if len(neckline_region) < 5:
            return None
        neckline = float(np.min(neckline_region))

        # 收盘跌破颈线
        if close.iloc[-1] >= neckline:
            return None

        # 放量
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio < 1.5:
            return None

        strength = 0.70 + (0.10 if right_lower else 0.0) + (0.10 if vol_ratio > 2.5 else 0.0)
        return self._make_result(
            code="P-2-9",
            strength=min(strength, 0.95),
            stage=PatternStage.CONFIRMING,
            completion=80.0,
            conditions=[
                f"头肩顶: 左肩{left_shoulder:.2f} 头部{head:.2f} 右肩{right_shoulder:.2f}",
                f"颈线位: {neckline:.2f}",
                f"收盘{close.iloc[-1]:.2f}跌破颈线",
                f"成交量为20日均量的{vol_ratio*100:.0f}%",
            ],
            interpretation="头肩顶形态右肩放量跌破颈线，经典顶部反转",
            levels=PatternLevel(
                resistance=neckline,
                target=float(neckline - (head - neckline)),
            ),
            detail={"head": round(head, 2), "left_shoulder": round(left_shoulder, 2), "right_shoulder": round(right_shoulder, 2), "vol_ratio": round(vol_ratio, 2)},
        )

    # ══════════════════════════════════════════════════
    # P-2-10: 高位阴线放量
    # 高位连续阴线伴随放量，空方力量主导
    # ══════════════════════════════════════════════════
    def _p_2_10(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 20:
            return None

        close = df['close']
        vol = df['volume']

        # 条件1: 价格在高位（近60日最高35%区域）
        lookback = min(60, len(df))
        high_60 = float(df['high'].iloc[-lookback:].max())
        low_60 = float(df['low'].iloc[-lookback:].min())
        if high_60 <= low_60:
            return None
        price_pos = (close.iloc[-1] - low_60) / (high_60 - low_60)
        if price_pos < 0.65:
            return None

        # 条件2: 连续3根阴线
        for i in range(-3, 0):
            if not self._is_yin(df.iloc[i]):
                return None

        # 条件3: 每根成交量 > 20日均量
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        for i in range(-3, 0):
            if vol.iloc[i] <= vol_avg:
                return None

        # 条件4: 3日累计跌幅 > 3%
        drop_3d = (close.iloc[-1] / close.iloc[-4] - 1)
        if drop_3d > -0.03:
            return None

        vol_ratio = float(vol.iloc[-1] / vol_avg)
        strength = 0.65 + (0.15 if drop_3d < -0.05 else 0.0) + (0.10 if vol_ratio > 2.0 else 0.0)
        return self._make_result(
            code="P-2-10",
            strength=min(strength, 0.90),
            stage=PatternStage.CONFIRMING,
            completion=70.0,
            conditions=[
                f"价格处于高位{price_pos*100:.0f}%区域",
                "连续3根阴线",
                "每根成交量均超过20日均量",
                f"3日累计跌幅{drop_3d*100:.1f}%",
            ],
            interpretation="高位连续阴线伴随放量，空方力量主导",
            detail={"drop_3d": round(float(drop_3d), 4), "vol_ratio": round(vol_ratio, 2)},
        )

    # ══════════════════════════════════════════════════
    # P-2-11: 均线空头放量
    # 均线呈空头排列且成交量放大，趋势与量能共振向下
    # ══════════════════════════════════════════════════
    def _p_2_11(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 60:
            return None

        close = df['close']
        vol = df['volume']

        # 条件1: MA5 < MA10 < MA20（空头排列）
        ma5 = float(self._ma(close, 5).iloc[-1])
        ma10 = float(self._ma(close, 10).iloc[-1])
        ma20 = float(self._ma(close, 20).iloc[-1])
        if not (ma5 < ma10 < ma20):
            return None

        # 条件2: 当日成交量 > 20日均量1.5倍
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio < 1.5:
            return None

        # 条件3: 当日为阴线
        if not self._is_yin(df.iloc[-1]):
            return None

        strength = 0.65 + (0.10 if vol_ratio > 2.5 else 0.0) + (0.10 if ma5 < ma10 * 0.99 else 0.0)
        return self._make_result(
            code="P-2-11",
            strength=min(strength, 0.90),
            stage=PatternStage.CONFIRMING,
            completion=75.0,
            conditions=[
                f"均线空头排列: MA5({ma5:.2f}) < MA10({ma10:.2f}) < MA20({ma20:.2f})",
                f"成交量为20日均量的{vol_ratio*100:.0f}%",
                "当日阴线确认",
            ],
            interpretation="均线呈空头排列且成交量放大，趋势与量能共振向下",
            detail={"ma5": round(ma5, 2), "ma10": round(ma10, 2), "ma20": round(ma20, 2), "vol_ratio": round(vol_ratio, 2)},
        )

    # ══════════════════════════════════════════════════
    # P-2-12: 反弹受阻缩量
    # 反弹至重要阻力位成交量萎缩，上涨动能不足
    # ══════════════════════════════════════════════════
    def _p_2_12(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 25:
            return None

        close = df['close']
        vol = df['volume']

        # 条件1: MA20 下行（确认下跌趋势）
        ma20 = self._ma(close, 20)
        if len(ma20) < 6:
            return None
        ma20_declining = float(ma20.iloc[-1]) < float(ma20.iloc[-6])
        if not ma20_declining:
            return None

        ma20_val = float(ma20.iloc[-1])

        # 条件2: 近5日有反弹（最高价 > 5日前收盘价3%以上）
        recent_high = float(df['high'].iloc[-5:].max())
        ref_price = float(close.iloc[-6])
        if ref_price <= 0:
            return None
        bounce = (recent_high / ref_price - 1)
        if bounce < 0.03:
            return None

        # 条件3: 反弹最高价接近MA20（在MA20的97%~103%范围内受阻）
        if recent_high < ma20_val * 0.97 or recent_high > ma20_val * 1.03:
            return None

        # 条件4: 最近2日成交量递减（受阻缩量）
        if vol.iloc[-1] >= vol.iloc[-2]:
            return None

        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)

        strength = 0.60 + (0.15 if vol_ratio < 0.6 else 0.0) + (0.10 if close.iloc[-1] < ma20_val else 0.0)
        return self._make_result(
            code="P-2-12",
            strength=min(strength, 0.85),
            stage=PatternStage.FORMING,
            completion=55.0,
            conditions=[
                f"MA20下行({ma20_val:.2f})",
                f"反弹至MA20附近受阻(高点{recent_high:.2f})",
                "近日成交量递减",
                f"成交量仅为20日均量的{vol_ratio*100:.0f}%",
            ],
            interpretation="反弹至重要阻力位成交量萎缩，上涨动能不足",
            levels=PatternLevel(
                resistance=ma20_val,
                target=float(close.iloc[-1] * 0.93),
            ),
            detail={"bounce_pct": round(float(bounce), 4), "vol_ratio": round(vol_ratio, 2)},
        )

    # ══════════════════════════════════════════════════
    # P-2-13: 放量跌破平台
    # 成交量放大跌破整理平台，破位确认信号
    # ══════════════════════════════════════════════════
    def _p_2_13(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 25:
            return None

        close = df['close']
        low = df['low']
        vol = df['volume']
        latest = df.iloc[-1]

        # 条件1: 近20日整理平台（振幅 < 12%）
        platform_high = float(df['high'].iloc[-21:-1].max())
        platform_low = float(low.iloc[-21:-1].min())
        if platform_low <= 0:
            return None
        platform_amp = (platform_high - platform_low) / platform_low
        if platform_amp > 0.12:
            return None

        # 条件2: 最新收盘跌破平台低点
        if close.iloc[-1] >= platform_low:
            return None

        # 条件3: 成交量 > 20日均量的2倍
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio < 2.0:
            return None

        # 条件4: 阴线（确认破位力度）
        if not self._is_yin(latest):
            return None

        strength = 0.70 + (0.10 if vol_ratio > 3.0 else 0.0) + (0.10 if platform_amp < 0.08 else 0.0)
        return self._make_result(
            code="P-2-13",
            strength=min(strength, 0.95),
            stage=PatternStage.CONFIRMING,
            completion=75.0,
            conditions=[
                f"近20日整理平台振幅{platform_amp*100:.1f}%",
                f"收盘价{close.iloc[-1]:.2f}跌破平台低点{platform_low:.2f}",
                f"成交量为20日均量的{vol_ratio*100:.0f}%",
                "阴线确认破位",
            ],
            interpretation="成交量放大跌破整理平台，破位确认信号",
            levels=PatternLevel(
                resistance=platform_low,
                target=float(close.iloc[-1] - (platform_high - platform_low)),
            ),
            detail={"platform_low": round(platform_low, 2), "vol_ratio": round(vol_ratio, 2)},
        )

    # ══════════════════════════════════════════════════
    # P-2-14: 向下缺口放量
    # 向下跳空缺口伴随放量，下跌力度强
    # ══════════════════════════════════════════════════
    def _p_2_14(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 10:
            return None

        curr = df.iloc[-1]
        prev = df.iloc[-2]
        vol = df['volume']

        # 条件1: 向下跳空缺口（当日最高 < 前日最低）
        if curr['high'] >= prev['low']:
            return None

        # 条件2: 成交量 > 20日均量2倍
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio < 2.0:
            return None

        # 条件3: 阴线
        if not self._is_yin(curr):
            return None

        gap_pct = (prev['low'] - curr['high']) / prev['low']

        strength = 0.65 + (0.15 if vol_ratio > 3.0 else 0.0) + (0.10 if gap_pct > 0.02 else 0.0)
        return self._make_result(
            code="P-2-14",
            strength=min(strength, 0.90),
            stage=PatternStage.CONFIRMING,
            completion=70.0,
            conditions=[
                f"向下跳空缺口{gap_pct*100:.2f}%",
                f"成交量为20日均量的{vol_ratio*100:.0f}%",
                "阴线确认破位",
            ],
            interpretation="向下跳空缺口伴随放量，下跌力度强",
            levels=PatternLevel(
                resistance=float(prev['low']),
                target=float(curr['close'] * 0.93),
            ),
            detail={"gap_pct": round(float(gap_pct), 4), "vol_ratio": round(vol_ratio, 2)},
        )

    # ══════════════════════════════════════════════════
    # P-2-15: 高换手率暴跌
    # 高位换手率异常高伴随大幅下跌，筹码快速换手
    # ══════════════════════════════════════════════════
    def _p_2_15(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 20:
            return None

        latest = df.iloc[-1]
        close = df['close']
        vol = df['volume']

        # 条件1: 价格在高位（近60日最高30%区域）
        lookback = min(60, len(df))
        high_60 = float(df['high'].iloc[-lookback:].max())
        low_60 = float(df['low'].iloc[-lookback:].min())
        if high_60 <= low_60:
            return None
        price_pos = (close.iloc[-1] - low_60) / (high_60 - low_60)
        if price_pos < 0.60:
            return None

        # 条件2: 成交量 > 3倍20日均量（异常高换手）
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio < 3.0:
            return None

        # 条件3: 当日跌幅 > 4%
        if len(df) < 2:
            return None
        pct = (latest['close'] / df.iloc[-2]['close'] - 1)
        if pct > -0.04:
            return None

        # 条件4: 大阴线实体（实体占振幅 > 60%）
        amplitude = latest['high'] - latest['low']
        body = self._body(latest)
        if amplitude <= 0 or body / amplitude < 0.6:
            return None

        strength = 0.70 + (0.10 if vol_ratio > 5.0 else 0.0) + (0.10 if pct < -0.06 else 0.0)
        return self._make_result(
            code="P-2-15",
            strength=min(strength, 0.95),
            stage=PatternStage.CONFIRMING,
            completion=80.0,
            conditions=[
                f"价格处于高位{price_pos*100:.0f}%区域",
                f"成交量为20日均量的{vol_ratio*100:.0f}%（异常高换手）",
                f"当日跌幅{pct*100:.1f}%",
                f"大阴线实体占比{body/amplitude*100:.0f}%",
            ],
            interpretation="高位换手率异常高伴随大幅下跌，筹码快速换手",
            levels=PatternLevel(
                resistance=float(df['high'].iloc[-5:].max()),
                target=float(close.iloc[-1] * 0.88),
            ),
            detail={"vol_ratio": round(vol_ratio, 2), "pct_change": round(float(pct), 4)},
        )

    # ══════════════════════════════════════════════════
    # P-2-16: 乌云盖顶放量
    # 高位阴线覆盖前日阳线大半伴随放量，见顶信号
    # ══════════════════════════════════════════════════
    def _p_2_16(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 20:
            return None

        curr = df.iloc[-1]
        prev = df.iloc[-2]
        vol = df['volume']

        # 条件1: 前日为阳线
        if not self._is_yang(prev):
            return None

        # 条件2: 当日为阴线，开盘高于前日收盘（跳空高开），收盘低于前日实体50%
        if not self._is_yin(curr):
            return None
        if curr['open'] <= prev['close']:
            return None
        prev_mid = (prev['open'] + prev['close']) / 2
        if curr['close'] >= prev_mid:
            return None

        # 条件3: 成交量 > 20日均量1.5倍
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(vol.iloc[-1] / vol_avg)
        if vol_ratio < 1.5:
            return None

        # 条件4: 价格在高位（近60日最高35%区域）
        lookback = min(60, len(df))
        high_60 = float(df['high'].iloc[-lookback:].max())
        low_60 = float(df['low'].iloc[-lookback:].min())
        if high_60 <= low_60:
            return None
        price_pos = (float(prev['close']) - low_60) / (high_60 - low_60)
        if price_pos < 0.65:
            return None

        # 计算覆盖程度
        cover_ratio = (float(prev['close']) - float(curr['close'])) / (float(prev['close']) - float(prev['open']) + 1e-9)

        strength = 0.65 + (0.15 if cover_ratio > 0.7 else 0.0) + (0.10 if vol_ratio > 2.5 else 0.0)
        return self._make_result(
            code="P-2-16",
            strength=min(strength, 0.90),
            stage=PatternStage.CONFIRMING,
            completion=70.0,
            conditions=[
                f"前日阳线收盘{prev['close']:.2f}",
                f"当日高开低走，覆盖前日阳线{cover_ratio*100:.0f}%",
                f"成交量为20日均量的{vol_ratio*100:.0f}%",
                f"价格处于高位{price_pos*100:.0f}%区域",
            ],
            interpretation="高位阴线覆盖前日阳线大半伴随放量，见顶信号",
            detail={"cover_ratio": round(cover_ratio, 2), "vol_ratio": round(vol_ratio, 2)},
        )

    # ══════════════════════════════════════════════════
    # P-2-17: 黄昏之星放量
    # 高位三根K线形成黄昏之星且放量，反转信号
    # ══════════════════════════════════════════════════
    def _p_2_17(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 20:
            return None

        first = df.iloc[-3]   # 大阳线
        star = df.iloc[-2]    # 小实体（星线）
        third = df.iloc[-1]   # 大阴线
        vol = df['volume']

        # 条件1: 第一根为大阳线
        if not self._is_yang(first):
            return None
        first_body = self._body(first)
        first_amp = first['high'] - first['low']
        if first_amp <= 0 or first_body / first_amp < 0.5:
            return None

        # 条件2: 第二根为小实体（星线），实体 < 第一根实体的30%
        star_body = self._body(star)
        if star_body > first_body * 0.3:
            return None

        # 条件3: 星线开盘价 > 第一根收盘价（跳空高开于阳线上方）
        if star['open'] <= first['close'] * 0.998:
            return None

        # 条件4: 第三根为大阴线，收盘低于第一根实体中点
        if not self._is_yin(third):
            return None
        first_mid = (first['open'] + first['close']) / 2
        if third['close'] >= first_mid:
            return None

        # 条件5: 星线或第三根成交量 > 20日均量
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0:
            return None
        vol_ratio = float(max(vol.iloc[-1], vol.iloc[-2]) / vol_avg)
        if vol_ratio < 1.2:
            return None

        # 价格在高位
        lookback = min(60, len(df))
        high_60 = float(df['high'].iloc[-lookback:].max())
        low_60 = float(df['low'].iloc[-lookback:].min())
        if high_60 <= low_60:
            return None
        price_pos = (float(first['close']) - low_60) / (high_60 - low_60)

        strength = 0.65 + (0.15 if vol_ratio > 2.0 else 0.0) + (0.10 if price_pos > 0.75 else 0.0)
        return self._make_result(
            code="P-2-17",
            strength=min(strength, 0.90),
            stage=PatternStage.CONFIRMING,
            completion=70.0,
            conditions=[
                f"第一根大阳线(收盘{first['close']:.2f})",
                f"第二根星线(实体仅{star_body:.3f})",
                f"第三根大阴线(收盘{third['close']:.2f})",
                f"成交量放大，量比{vol_ratio:.1f}",
            ],
            interpretation="高位三根K线形成黄昏之星且放量，反转信号",
            detail={"vol_ratio": round(vol_ratio, 2), "price_position": round(price_pos, 3)},
        )

    # ══════════════════════════════════════════════════
    # P-2-18: 下跌三浪放量
    # 下跌过程中三浪推进且每浪放量，空方力量完整释放
    # ══════════════════════════════════════════════════
    def _p_2_18(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 30:
            return None

        close = df['close']
        vol = df['volume']

        # 简化检测：将近30日分为3段（每段10日）
        # 每段为一个下跌浪：段末收盘 < 段初收盘
        # 且每段成交量逐步放大
        seg_len = 10
        declines = []
        vol_avgs = []

        for i in range(3):
            start = -30 + i * seg_len
            end = start + seg_len
            seg_close_start = float(close.iloc[start])
            seg_close_end = float(close.iloc[end - 1])
            # Handle end=0 case (Python iloc slice [-10:0] is empty)
            if end == 0:
                seg_vol_avg = float(vol.iloc[start:].mean())
            else:
                seg_vol_avg = float(vol.iloc[start:end].mean())
            decline = (seg_close_end / seg_close_start - 1)
            declines.append(decline)
            vol_avgs.append(seg_vol_avg)

        # 条件1: 三段均为下跌
        for d in declines:
            if d >= -0.02:
                return None

        # 条件2: 成交量逐步放大（后浪 > 前浪）
        if not (vol_avgs[2] > vol_avgs[1] > vol_avgs[0]):
            return None

        # 条件3: 总跌幅 > 10%
        total_decline = (close.iloc[-1] / close.iloc[-30] - 1)
        if total_decline > -0.10:
            return None

        # 条件4: 最新成交量 > 20日均量
        vol_avg = self._vol_ma(vol, 20)
        if vol_avg <= 0 or vol.iloc[-1] <= vol_avg:
            return None

        vol_ratio = float(vol.iloc[-1] / vol_avg)
        strength = 0.65 + (0.15 if total_decline < -0.15 else 0.0) + (0.10 if vol_avgs[2] > vol_avgs[0] * 1.5 else 0.0)
        return self._make_result(
            code="P-2-18",
            strength=min(strength, 0.90),
            stage=PatternStage.CONFIRMING,
            completion=75.0,
            conditions=[
                f"三浪下跌: {declines[0]*100:.1f}% → {declines[1]*100:.1f}% → {declines[2]*100:.1f}%",
                f"成交量逐浪放大: {vol_avgs[0]:.0f} → {vol_avgs[1]:.0f} → {vol_avgs[2]:.0f}",
                f"总跌幅{total_decline*100:.1f}%",
                f"最新成交量为20日均量的{vol_ratio*100:.0f}%",
            ],
            interpretation="下跌过程中三浪推进且每浪放量，空方力量完整释放",
            detail={
                "declines": [round(d, 4) for d in declines],
                "vol_avgs": [round(v, 0) for v in vol_avgs],
                "total_decline": round(float(total_decline), 4),
            },
        )

    # ══════════════════════════════════════════════════
    # P-2-19: 圆弧顶缩量
    # 圆弧顶形态右侧成交量逐步缩小，顶部反转确认
    # ══════════════════════════════════════════════════
    def _p_2_19(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 30:
            return None

        close = df['close']
        vol = df['volume']

        # 简化圆弧顶检测（倒U型）：
        # 价格先升后降，最高点在中间区域
        search_len = min(30, len(df))
        closes = close.iloc[-search_len:].values

        # 找最高点位置
        max_idx = int(np.argmax(closes))
        # 最高点应在中间区域（前30%~70%之间）
        if max_idx < search_len * 0.2 or max_idx > search_len * 0.7:
            return None

        # 左半段总体上升
        left = closes[:max_idx + 1]
        if len(left) < 3:
            return None
        left_asc = left[-1] > left[0] * 1.02  # 顶部 > 起点2%以上

        # 右半段总体下降
        right = closes[max_idx:]
        if len(right) < 3:
            return None
        right_desc = right[-1] < right[0] * 0.98  # 当前 < 顶部2%以上

        if not (left_asc and right_desc):
            return None

        # 右侧成交量 < 左侧成交量（缩量）
        vol_left = float(vol.iloc[-search_len:-search_len + max_idx + 1].mean())
        vol_right = float(vol.iloc[-(search_len - max_idx):].mean())
        if vol_left <= 0:
            return None
        if vol_right >= vol_left:
            return None

        # 当日阴线
        if not self._is_yin(df.iloc[-1]):
            return None

        strength = 0.65 + (0.10 if vol_right < vol_left * 0.7 else 0.0) + (0.10 if close.iloc[-1] < closes[0] else 0.0)
        return self._make_result(
            code="P-2-19",
            strength=min(strength, 0.90),
            stage=PatternStage.FORMING,
            completion=55.0,
            conditions=[
                f"价格呈圆弧顶形态（倒U型），最高点在第{max_idx}根K线",
                f"右侧量能为左侧的{vol_right/vol_left*100:.0f}%",
                "当日阴线确认右侧下降",
            ],
            interpretation="圆弧顶形态右侧成交量逐步缩小，顶部反转确认",
            detail={"max_idx": max_idx, "vol_ratio_rl": round(float(vol_right / vol_left), 2)},
        )

    # ══════════════════════════════════════════════════
    # P-2-20: 旗形下跌破位
    # 下降旗形整理结束后放量向下破位，下跌趋势延续
    # ══════════════════════════════════════════════════
    def _p_2_20(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Optional[PatternResult]:
        if len(df) < 25:
            return None

        close = df['close']
        high = df['high']
        low = df['low']
        vol = df['volume']

        # 简化下降旗形检测：
        # 旗杆：近20日前有一段快速下跌（5日内跌幅>8%）
        # 旗面：随后价格小幅反弹/横盘（振幅<5%），成交量萎缩
        # 破位：当日放量跌破旗面下沿

        # 查找旗杆（快速下跌）
        flagpole_found = False
        pole_low = 0.0
        for start in range(-20, -8):
            if start < -len(df) + 5:
                continue
            end_idx = start + 5
            if end_idx >= 0:
                drop_5d = (close.iloc[-1] / close.iloc[start] - 1)
            else:
                drop_5d = (close.iloc[end_idx] / close.iloc[start] - 1)
            if drop_5d < -0.08:
                flagpole_found = True
                pole_low = float(low.iloc[start:end_idx].min()) if end_idx < 0 else float(low.iloc[start:].min())
                break

        if not flagpole_found:
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

        # 破位: 当日收盘 < 旗面低点 + 放量
        if close.iloc[-1] >= flag_low:
            return None
        if vol.iloc[-1] <= vol_avg * 1.5:
            return None

        vol_ratio = float(vol.iloc[-1] / vol_avg)
        strength = 0.65 + (0.10 if vol_ratio > 2.5 else 0.0) + (0.10 if flag_amp < 0.03 else 0.0)
        return self._make_result(
            code="P-2-20",
            strength=min(strength, 0.90),
            stage=PatternStage.CONFIRMING,
            completion=70.0,
            conditions=[
                "旗杆: 5日跌幅>8%",
                f"旗面: 近5日振幅{flag_amp*100:.1f}%，量缩",
                f"跌破旗面低点{flag_low:.2f}",
                f"成交量放大(量比{vol_ratio:.1f})",
            ],
            interpretation="下降旗形整理结束后放量向下破位，下跌趋势延续",
            levels=PatternLevel(
                resistance=flag_high,
                target=float(close.iloc[-1] - (flag_high - flag_low)),
            ),
            detail={"flag_amp": round(flag_amp, 4), "flag_low": round(flag_low, 2), "vol_ratio": round(vol_ratio, 2)},
        )
