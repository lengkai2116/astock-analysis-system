"""
测试黑马型形态检测器（10种）
==============================
覆盖:
  - 基础初始化与接口测试
  - 边界条件（空DataFrame、数据不足）
  - 每种形态的正向检测（精心构造满足条件的数据）
  - 每种形态的反向测试（不满足条件时不应触发）
  - 多形态并行检测
  - PatternResult 结构完整性
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pytest
import pandas as pd
import numpy as np

from app.engine.patterns import PatternCategory, PatternStage, PatternResult
from app.engine.patterns.detectors.blackhorse_patterns import BlackHorsePatternDetector


# ═══════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════

@pytest.fixture
def detector():
    return BlackHorsePatternDetector()


def _make_df(rows: int = 100, seed: int = 42) -> pd.DataFrame:
    """生成标准OHLCV测试数据"""
    dates = pd.date_range(start='2025-01-01', periods=rows, freq='B')
    rng = np.random.RandomState(seed)
    close = 100 + np.cumsum(rng.randn(rows) * 2)
    open_p = close + rng.randn(rows) * 0.5
    high = np.maximum(close, open_p) + np.abs(rng.randn(rows) * 1)
    low = np.minimum(close, open_p) - np.abs(rng.randn(rows) * 1)
    volume = rng.randint(1_000_000, 5_000_000, rows).astype(float)
    return pd.DataFrame({
        'open': open_p, 'high': high, 'low': low,
        'close': close, 'volume': volume,
    }, index=dates)


def _build_base(n=60, start_price=10.0, base_vol=1_000_000):
    """构造基础DataFrame"""
    dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
    df = pd.DataFrame({
        'open': np.full(n, start_price),
        'high': np.full(n, start_price * 1.01),
        'low': np.full(n, start_price * 0.99),
        'close': np.full(n, start_price),
        'volume': np.full(n, float(base_vol)),
    }, index=dates)
    return df


@pytest.fixture
def sample_df():
    """标准100行随机OHLCV"""
    return _make_df(150)


# ═══════════════════════════════════════════════════
# 基础接口测试
# ═══════════════════════════════════════════════════

class TestBlackHorseDetectorBasics:

    def test_import(self):
        """应能导入 BlackHorsePatternDetector"""
        assert BlackHorsePatternDetector is not None

    def test_is_subclass(self):
        """应继承 PatternDetector"""
        from app.engine.patterns.detectors.base import PatternDetector
        assert issubclass(BlackHorsePatternDetector, PatternDetector)

    def test_can_instantiate(self):
        """可以实例化（非抽象类）"""
        d = BlackHorsePatternDetector()
        assert d is not None

    def test_detect_returns_list(self, detector, sample_df):
        """detect 应返回列表"""
        results = detector.detect(sample_df)
        assert isinstance(results, list)

    def test_empty_dataframe(self, detector):
        """空DataFrame应返回空列表"""
        df = pd.DataFrame()
        assert detector.detect(df) == []

    def test_short_dataframe(self, detector):
        """数据不足30行应返回空列表"""
        df = pd.DataFrame({
            'open': [100, 101],
            'high': [102, 103],
            'low': [99, 100],
            'close': [101, 102],
            'volume': [1e6, 1.1e6],
        })
        assert detector.detect(df) == []

    def test_result_is_pattern_result(self, detector, sample_df):
        """检测结果应为 PatternResult 实例"""
        results = detector.detect(sample_df)
        for r in results:
            assert isinstance(r, PatternResult)

    def test_result_category_is_blackhorse(self, detector, sample_df):
        """所有结果分类应为 BLACKHORSE"""
        results = detector.detect(sample_df)
        for r in results:
            assert r.category == PatternCategory.BLACKHORSE

    def test_result_direction_is_bullish(self, detector, sample_df):
        """所有结果方向应为 bullish（黑马型是看涨信号）"""
        results = detector.detect(sample_df)
        for r in results:
            assert r.direction == 'bullish'

    def test_result_has_valid_strength(self, detector, sample_df):
        """strength 应在 [0, 1] 范围"""
        results = detector.detect(sample_df)
        for r in results:
            assert 0 <= r.strength <= 1

    def test_result_has_valid_stage(self, detector, sample_df):
        """stage 应为合法枚举值"""
        results = detector.detect(sample_df)
        for r in results:
            assert r.stage in (PatternStage.FORMING, PatternStage.CONFIRMING,
                               PatternStage.COMPLETED, PatternStage.INVALIDATED)

    def test_exception_silenced(self, detector):
        """内部异常不应传播（graceful degradation）"""
        df = pd.DataFrame({'x': [1, 2, 3]})
        try:
            results = detector.detect(df)
            assert isinstance(results, list)
        except Exception:
            pytest.fail("detect() should not raise on bad input")

    def test_all_10_detectors_exist(self, detector):
        """应有10个检测方法"""
        methods = [f'_p_3_{i}' for i in range(1, 11)]
        for m in methods:
            assert hasattr(detector, m), f"Missing method: {m}"


# ═══════════════════════════════════════════════════
# P-3-1: 底部异动放量
# ═══════════════════════════════════════════════════

class TestP3_1_BottomAnomalousVolume:

    def test_detect_bottom_anomalous_volume(self, detector):
        """底部异动放量 — 应检测到"""
        n = 60
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 6.0)
        open_p = np.full(n, 6.0)
        high = np.full(n, 20.0)  # wide range for price position
        low = np.full(n, 5.0)
        volume = np.full(n, 1_000_000.0)

        # price position: (6 - 5) / (20 - 5) = 0.067
        close[:] = 6.0
        open_p[:] = 6.0

        # 前5日缩量（低于70%均量）
        for i in range(-6, -1):
            volume[i] = 600_000.0

        # 当日异常放量 + 温和上涨
        open_p[-1] = 6.0
        close[-1] = 6.15  # +2.5%
        high[-1] = 6.20
        low[-1] = 5.95
        volume[-1] = 4_000_000.0  # 4x avg

        # 前日收盘
        close[-2] = 6.0

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-3-1" in codes

    def test_no_p3_1_when_high_position(self, detector):
        """高位时不应触发底部异动放量"""
        n = 60
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 18.0)
        open_p = np.full(n, 18.0)
        high = np.full(n, 20.0)
        low = np.full(n, 5.0)
        volume = np.full(n, 1_000_000.0)

        volume[-1] = 5_000_000.0
        close[-2] = 17.5
        close[-1] = 18.0
        open_p[-1] = 17.5

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-3-1" not in codes


# ═══════════════════════════════════════════════════
# P-3-2: 缩量挖坑后放量
# ═══════════════════════════════════════════════════

class TestP3_2_ShrinkPitThenVolume:

    def test_detect_shrink_pit_then_volume(self, detector):
        """缩量挖坑后放量 — 应检测到"""
        n = 30
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 10.0)
        open_p = np.full(n, 10.0)
        high = np.full(n, 10.5)
        low = np.full(n, 9.5)
        volume = np.full(n, 1_000_000.0)

        # 缩量下跌阶段（-8 to -5）: 连续3日volume递减 + close递减
        for i, idx in enumerate(range(-8, -5)):
            volume[idx] = float(500_000 - i * 50_000)
            close[idx] = 10.5 - i * 0.1

        # 近4日
        for i in range(-4, -1):
            volume[i] = 300_000.0
            close[i] = 10.0
            open_p[i] = 10.0

        # 当日放量阳线反弹
        open_p[-1] = 9.9
        close[-1] = 10.3
        high[-1] = 10.4
        low[-1] = 9.8
        volume[-1] = 2_500_000.0

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-3-2" in codes


# ═══════════════════════════════════════════════════
# P-3-3: 低位连续小阳堆量
# ═══════════════════════════════════════════════════

class TestP3_3_ContinuousSmallYang:

    def test_detect_continuous_small_yang(self, detector):
        """低位连续小阳堆量 — 应检测到"""
        n = 60
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 6.0)
        open_p = np.full(n, 6.0)
        high = np.full(n, 20.0)
        low = np.full(n, 5.0)
        volume = np.full(n, 800_000.0)

        # 低位: (6-5)/(20-5) = 0.067
        close[:] = 6.0
        open_p[:] = 6.0

        # 前15日低量
        for i in range(-15, -5):
            volume[i] = 600_000.0

        # 连续5日小阳线 + 堆量
        base = 6.0
        for i in range(-5, 0):
            open_p[i] = base
            close[i] = base + 0.05  # 小阳
            high[i] = close[i] + 0.05
            low[i] = open_p[i] - 0.05
            base = close[i]
            volume[i] = float(1_200_000 + (5 + i) * 200_000)  # 递增堆量

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-3-3" in codes


# ═══════════════════════════════════════════════════
# P-3-4: 突破年线放量
# ═══════════════════════════════════════════════════

class TestP3_4_BreakAboveAnnualMA:

    def test_detect_break_above_annual_ma(self, detector):
        """突破年线放量 — 应检测到"""
        n = 260
        dates = pd.date_range(start='2024-01-01', periods=n, freq='B')
        # 构造先低于年线、后突破的数据
        close = np.full(n, 10.0)
        # 前200日缓慢下降到8
        for i in range(200):
            close[i] = 12.0 - i * 0.02
        # 后60日上升到突破年线
        for i in range(200, n):
            close[i] = 8.0 + (i - 200) * 0.04  # 慢慢回升

        open_p = close - 0.1
        high = close + 0.2
        low = close - 0.2
        volume = np.full(n, 1_000_000.0)

        # 计算年线
        ma250 = np.convolve(close, np.ones(250)/250, mode='valid')
        ma250_last = float(ma250[-1])

        # 确保前一日低于年线，当日高于年线
        close[-2] = ma250_last - 0.2
        close[-1] = ma250_last + 0.3
        open_p[-2] = close[-2] - 0.1
        open_p[-1] = close[-1] - 0.2
        high[-1] = close[-1] + 0.1
        low[-1] = close[-1] - 0.1

        # 放量
        volume[-1] = 3_000_000.0

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-3-4" in codes


# ═══════════════════════════════════════════════════
# P-3-5: 底部涨停板
# ═══════════════════════════════════════════════════

class TestP3_5_BottomLimitUp:

    def test_detect_bottom_limit_up(self, detector):
        """底部涨停板 — 应检测到"""
        n = 60
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 6.0)
        open_p = np.full(n, 6.0)
        high = np.full(n, 20.0)
        low = np.full(n, 5.0)
        volume = np.full(n, 1_000_000.0)

        # 低位: (6-5)/(20-5) = 0.067
        close[:] = 6.0
        open_p[:] = 6.0

        # 前日收盘
        close[-2] = 6.0
        open_p[-2] = 6.0

        # 当日涨停 +10%
        open_p[-1] = 6.0
        close[-1] = 6.6
        high[-1] = 6.6
        low[-1] = 5.95
        volume[-1] = 5_000_000.0

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-3-5" in codes

    def test_no_p3_5_when_high_position(self, detector):
        """高位涨停不应触发底部涨停板"""
        n = 60
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 18.0)
        open_p = np.full(n, 18.0)
        high = np.full(n, 20.0)
        low = np.full(n, 5.0)
        volume = np.full(n, 1_000_000.0)

        close[-2] = 18.0
        close[-1] = 20.0
        open_p[-1] = 18.0
        high[-1] = 20.0
        low[-1] = 17.9
        volume[-1] = 5_000_000.0

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-3-5" not in codes


# ═══════════════════════════════════════════════════
# P-3-6: 长期缩量后突然放量
# ═══════════════════════════════════════════════════

class TestP3_6_LongTermShrinkThenVolume:

    def test_detect_long_term_shrink_then_volume(self, detector):
        """长期缩量后突然放量 — 应检测到"""
        n = 50
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 10.0)
        open_p = np.full(n, 10.0)
        high = np.full(n, 10.5)
        low = np.full(n, 9.5)
        volume = np.full(n, 2_000_000.0)

        # 前20日（-40到-20）: 较高成交量
        for i in range(-40, -20):
            if i >= -n:
                volume[i] = 2_000_000.0

        # 近20日: 明显缩量
        for i in range(-20, -1):
            volume[i] = 600_000.0  # 缩减到30%

        # 当日突然放量阳线
        open_p[-1] = 9.9
        close[-1] = 10.2
        high[-1] = 10.3
        low[-1] = 9.8
        volume[-1] = 3_000_000.0

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-3-6" in codes


# ═══════════════════════════════════════════════════
# P-3-7: 底部连续阳线不破前低
# ═══════════════════════════════════════════════════

class TestP3_7_ContinuousYangNoBreakLow:

    def test_detect_continuous_yang_no_break(self, detector):
        """底部连续阳线不破前低 — 应检测到"""
        n = 60
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 6.0)
        open_p = np.full(n, 6.0)
        high = np.full(n, 20.0)
        low = np.full(n, 5.0)
        volume = np.full(n, 800_000.0)

        # 低位: (6-5)/(20-5) = 0.067
        close[:] = 6.0
        open_p[:] = 6.0

        # 前13日较低量
        for i in range(-13, -3):
            volume[i] = 600_000.0

        # 前4日低点设置
        for i in range(-5, -1):
            low[i] = 5.8 + (5 + i) * 0.05  # 低点逐步抬高

        # 连续5日阳线 + 低点抬高 + 量能配合
        base_low = 5.80
        for i in range(-5, 0):
            open_p[i] = base_low + 0.05
            close[i] = base_low + 0.15
            high[i] = close[i] + 0.05
            low[i] = base_low
            base_low += 0.05
            volume[i] = float(1_200_000 + (5 + i) * 100_000)

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-3-7" in codes


# ═══════════════════════════════════════════════════
# P-3-8: 低位巨量长下影
# ═══════════════════════════════════════════════════

class TestP3_8_BottomMassiveVolumeLongShadow:

    def test_detect_massive_volume_long_shadow(self, detector):
        """低位巨量长下影 — 应检测到"""
        n = 60
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 6.0)
        open_p = np.full(n, 6.0)
        high = np.full(n, 20.0)
        low = np.full(n, 5.0)
        volume = np.full(n, 1_000_000.0)

        # 低位
        close[:] = 6.0
        open_p[:] = 6.0

        # 当日: 巨量 + 长下影线
        # 下影线占振幅 > 40%
        open_p[-1] = 6.0
        close[-1] = 6.05  # 接近十字星
        high[-1] = 6.10
        low[-1] = 5.60   # 振幅=0.50, 下影线=6.0-5.6=0.4, 占比=0.4/0.5=80%
        volume[-1] = 5_000_000.0

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-3-8" in codes


# ═══════════════════════════════════════════════════
# P-3-9: 老鸭头形态放量
# ═══════════════════════════════════════════════════

class TestP3_9_OldDuckHeadPattern:

    def test_detect_old_duck_head(self, detector):
        """老鸭头形态放量 — 应检测到"""
        n = 70
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.zeros(n)
        volume = np.full(n, 1_000_000.0)

        # 阶段1 (-70 to -50): 上涨 → MA5 > MA10（第一次金叉）
        for i in range(20):
            close[i] = 10.0 + i * 0.1

        # 阶段2 (-50 to -30): 回调 → MA5 < MA10（死叉）
        for i in range(20, 40):
            close[i] = 12.0 - (i - 20) * 0.1

        # 阶段3 (-30 to -1): 重新上涨 → MA5 > MA10（第二次金叉）
        for i in range(40, 70):
            close[i] = 10.0 + (i - 40) * 0.1

        open_p = close - 0.05
        high = close + 0.2
        low = close - 0.2

        # 当日放量阳线
        volume[-1] = 2_500_000.0

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-3-9" in codes


# ═══════════════════════════════════════════════════
# P-3-10: N字形态放量突破
# ═══════════════════════════════════════════════════

class TestP3_10_NShapeBreakout:

    def test_detect_n_shape_breakout(self, detector):
        """N字形态放量突破 — 应检测到"""
        n = 35
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 10.0)
        open_p = np.full(n, 10.0)
        high = np.full(n, 10.5)
        low = np.full(n, 9.5)
        volume = np.full(n, 1_000_000.0)

        # N字形: 上涨→回调→突破
        # 第一波上涨（-35 to -25）
        for i in range(-35, -25):
            close[i] = 10.0 + (i + 35) * 0.1
        # 回调（-25 to -15）回到低点
        for i in range(-25, -12):
            close[i] = 11.0 - (i + 25) * 0.08
        # 第二波上涨（-12 to -1）
        for i in range(-12, -1):
            close[i] = 10.0 + (i + 12) * 0.08

        # 最后一根突破前高 (前高≈11.0)
        close[-1] = 11.3
        close[-2] = 10.8

        open_p = close - 0.05
        high = close + 0.15
        low = close - 0.15

        # 放量
        volume[-1] = 2_500_000.0

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-3-10" in codes


# ═══════════════════════════════════════════════════
# 多形态并行检测
# ═══════════════════════════════════════════════════

class TestMultiplePatterns:

    def test_multiple_patterns_can_fire(self, detector, sample_df):
        """随机数据上可能检测到0个或多个形态"""
        results = detector.detect(sample_df)
        assert 0 <= len(results) <= 10

    def test_no_duplicate_codes(self, detector, sample_df):
        """同一DataFrame上不应出现重复形态"""
        results = detector.detect(df=sample_df)
        codes = [r.name for r in results]
        assert len(codes) == len(set(codes))


# ═══════════════════════════════════════════════════
# PatternResult 结构完整性
# ═══════════════════════════════════════════════════

class TestPatternResultStructure:

    def test_result_to_dict(self, detector):
        """PatternResult.to_dict() 应可正常序列化"""
        n = 60
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 6.0)
        open_p = np.full(n, 6.0)
        high = np.full(n, 20.0)
        low = np.full(n, 5.0)
        volume = np.full(n, 1_000_000.0)

        close[:] = 6.0
        open_p[:] = 6.0

        # 制造一个P-3-1触发条件
        for i in range(-6, -1):
            volume[i] = 600_000.0
        close[-2] = 6.0
        open_p[-1] = 6.0
        close[-1] = 6.15
        high[-1] = 6.20
        low[-1] = 5.95
        volume[-1] = 4_000_000.0

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        for r in results:
            d = r.to_dict()
            assert 'name' in d
            assert 'category' in d
            assert 'direction' in d
            assert 'strength' in d
            assert 'stage' in d
            assert 'conditions' in d
            assert isinstance(d['conditions'], list)
            assert isinstance(d['levels'], dict)

    def test_result_source_set(self, detector, sample_df):
        """source 应设为 wiki_volume_price"""
        results = detector.detect(sample_df)
        for r in results:
            assert r.source == "wiki_volume_price"
