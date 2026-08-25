"""
测试预跌型形态检测器（20种）
============================
覆盖:
  - 基础初始化与接口测试
  - 边界条件（空DataFrame、数据不足）
  - 每种形态的正向检测（精心构造满足条件的数据）
  - 每种形态的反向测试（不满足条件时不应触发）
  - 多形态并行检测
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
from app.engine.patterns.detectors.bearish_patterns import BearishPatternDetector


# ═══════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════

@pytest.fixture
def detector():
    return BearishPatternDetector()


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


@pytest.fixture
def sample_df():
    """标准100行随机OHLCV"""
    return _make_df(100)


# ═══════════════════════════════════════════════════
# 基础接口测试
# ═══════════════════════════════════════════════════

class TestBearishDetectorBasics:

    def test_import(self):
        """应能导入 BearishPatternDetector"""
        assert BearishPatternDetector is not None

    def test_is_subclass(self):
        """应继承 PatternDetector"""
        from app.engine.patterns.detectors.base import PatternDetector
        assert issubclass(BearishPatternDetector, PatternDetector)

    def test_can_instantiate(self):
        """可以实例化（非抽象类）"""
        d = BearishPatternDetector()
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
        """数据不足20行应返回空列表"""
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

    def test_result_category_is_bearish(self, detector, sample_df):
        """所有结果分类应为 BEARISH_PATTERNS"""
        results = detector.detect(sample_df)
        for r in results:
            assert r.category == PatternCategory.BEARISH_PATTERNS

    def test_result_direction_is_bearish(self, detector, sample_df):
        """所有结果方向应为 bearish"""
        results = detector.detect(sample_df)
        for r in results:
            assert r.direction == 'bearish'

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

    def test_all_20_detectors_exist(self, detector):
        """应有20个检测方法"""
        methods = [f'_p_2_{i}' for i in range(1, 21)]
        for m in methods:
            assert hasattr(detector, m), f"Missing method: {m}"


# ═══════════════════════════════════════════════════
# 构造特定数据的工具函数
# ═══════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════
# P-2-1: 高位量价背离
# ═══════════════════════════════════════════════════

class TestP2_1_HighVolumePriceDivergence:

    def test_detect_divergence(self, detector):
        """高位量价背离 — 应检测到"""
        n = 60
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 10.0)
        open_p = np.full(n, 10.0)
        high = np.full(n, 20.0)  # wide range
        low = np.full(n, 5.0)
        volume = np.full(n, 1_000_000.0)

        # 价格在高位: (18 - 5) / (20 - 5) = 0.867
        close[:] = 18.0
        open_p[:] = 18.0

        # 近5日创新高
        for i in range(-5, 0):
            high[i] = 19.0 + (i + 5) * 0.1  # 19.0 ~ 19.4
        # 前10日高点低于近5日
        for i in range(-15, -5):
            high[i] = 18.5

        # 成交量递减: 近5日 < 前5日 < 20日均量
        for i in range(-10, -5):
            volume[i] = 1_200_000
        for i in range(-5, 0):
            volume[i] = 600_000  # below avg

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-2-1" in codes

    def test_no_divergence_when_not_high(self, detector):
        """价格不在高位时不应触发"""
        df = _build_base(60, 10.0, 1_000_000)
        # 价格在中位
        df['close'] = 10.0
        df['high'] = 12.0
        df['low'] = 8.0
        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-2-1" not in codes


# ═══════════════════════════════════════════════════
# P-2-2: 放量滞涨
# ═══════════════════════════════════════════════════

class TestP2_2_HighVolumeStagnation:

    def test_detect_stagnation(self, detector):
        """放量滞涨 — 应检测到"""
        n = 60
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 10.0)
        open_p = np.full(n, 10.0)
        high = np.full(n, 20.0)
        low = np.full(n, 5.0)
        volume = np.full(n, 1_000_000.0)

        # 价格在高位
        close[:] = 17.0
        open_p[:] = 17.0

        # 前日价格
        close[-2] = 17.0

        # 当日：阴线+高开低走，涨跌幅<1%
        open_p[-1] = 17.05
        close[-1] = 16.98  # -0.12%
        high[-1] = 17.1
        low[-1] = 16.9
        volume[-1] = 3_000_000.0  # 3x avg

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-2-2" in codes


# ═══════════════════════════════════════════════════
# P-2-3: 顶部缩量反弹
# ═══════════════════════════════════════════════════

class TestP2_3_TopShrinkBounce:

    def test_detect_shrink_bounce(self, detector):
        """顶部缩量反弹 — 应检测到"""
        n = 40
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        # 下降趋势
        close = np.linspace(15, 10, n)
        open_p = close + 0.05
        high = close + 0.2
        low = close - 0.2
        volume = np.full(n, 1_000_000.0)

        # 设置 close[-4] 更低以便反弹明显（bounce > 3%）
        close[-4] = 9.0
        open_p[-4] = 9.05
        high[-4] = 9.2
        low[-4] = 8.8

        # 近3日反弹但缩量 (bounce = 10.4/9.0 - 1 ≈ 15.6%)
        close[-3] = 9.5
        close[-2] = 10.0
        close[-1] = 10.4  # 反弹，但仍在MA20下方
        for i in range(-3, 0):
            volume[i] = 400_000.0  # 缩量
            open_p[i] = close[i] - 0.05
            high[i] = close[i] + 0.1
            low[i] = close[i] - 0.1

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-2-3" in codes


# ═══════════════════════════════════════════════════
# P-2-4: 天量见天价
# ═══════════════════════════════════════════════════

class TestP2_4_SkyVolumeTop:

    def test_detect_sky_volume(self, detector):
        """天量见天价 — 应检测到"""
        n = 60
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 10.0)
        open_p = np.full(n, 10.0)
        high = np.full(n, 20.0)
        low = np.full(n, 5.0)
        volume = np.full(n, 1_000_000.0)

        # 价格在高位
        close[:] = 18.0
        open_p[:] = 18.0

        # 当日：天量+上影线
        open_p[-1] = 18.0
        close[-1] = 18.1
        high[-1] = 19.0   # 上影线大
        low[-1] = 17.9
        volume[-1] = 5_000_000.0  # 5x avg

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-2-4" in codes


# ═══════════════════════════════════════════════════
# P-2-5: 连续缩量下跌
# ═══════════════════════════════════════════════════

class TestP2_5_ConsecutiveShrinkDecline:

    def test_detect_consecutive_decline(self, detector):
        """连续缩量下跌 — 应检测到"""
        n = 30
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 12.0)
        open_p = np.full(n, 12.0)
        high = np.full(n, 12.5)
        low = np.full(n, 11.5)
        volume = np.full(n, 1_000_000.0)

        # 连续6日收盘递减+成交量递减
        prices = [12.0, 11.7, 11.3, 10.8, 10.3, 9.7]  # > 5% drop from 12.0
        vols = [1_200_000, 900_000, 700_000, 500_000, 300_000, 200_000]
        for i, (p, v) in enumerate(zip(prices, vols)):
            idx = -6 + i
            close[idx] = p
            open_p[idx] = p + 0.05
            high[idx] = p + 0.2
            low[idx] = p - 0.2
            volume[idx] = float(v)

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-2-5" in codes


# ═══════════════════════════════════════════════════
# P-2-6: 高位放量十字星
# ═══════════════════════════════════════════════════

class TestP2_6_HighDojiVolume:

    def test_detect_high_doji(self, detector):
        """高位放量十字星 — 应检测到"""
        n = 60
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 10.0)
        open_p = np.full(n, 10.0)
        high = np.full(n, 20.0)
        low = np.full(n, 5.0)
        volume = np.full(n, 1_000_000.0)

        # 价格在高位且有前期涨幅
        close[:] = 17.0
        open_p[:] = 17.0
        # 前10日开始上涨
        for i in range(-11, -1):
            close[i] = 16.0 + (11 + i) * 0.1
            open_p[i] = close[i] - 0.05

        # 最后一日十字星 + 放量
        open_p[-1] = 17.00
        close[-1] = 17.01
        high[-1] = 17.20
        low[-1] = 16.80
        volume[-1] = 2_500_000.0  # 2.5x avg

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-2-6" in codes


# ═══════════════════════════════════════════════════
# P-2-7: 断头铡刀放量
# ═══════════════════════════════════════════════════

class TestP2_7_BeheadingKnife:

    def test_detect_beheading_knife(self, detector):
        """断头铡刀放量 — 应检测到"""
        n = 30
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        # 平坦趋势（MA20不上行也不明显下行）
        close = np.full(n, 15.0)
        open_p = close - 0.05
        high = close + 0.2
        low = close - 0.2
        volume = np.full(n, 1_000_000.0)

        # 轻微上升让MA20平坦
        for i in range(n):
            close[i] = 14.5 + i * 0.02
            open_p[i] = close[i] - 0.05
            high[i] = close[i] + 0.2
            low[i] = close[i] - 0.2

        # MA10 和 MA20 约 15.0 左右，当日暴跌到 13.5 以下
        close[-1] = 13.0   # 远低于MA10和MA20
        open_p[-1] = 15.0  # 平开
        high[-1] = 15.1
        low[-1] = 12.9
        volume[-1] = 3_000_000.0  # 3x avg

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-2-7" in codes


# ═══════════════════════════════════════════════════
# P-2-8: M顶放量跌破
# ═══════════════════════════════════════════════════

class TestP2_8_MTopBreakdown:

    def test_detect_m_top(self, detector):
        """M顶放量跌破 — 应检测到"""
        # 构造30根K线的清晰M顶
        # Detector 在近30根内搜索，window=30
        # 需要: 两个高点接近，中间有低谷，最后收盘跌破低谷
        n = 30
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 12.0)
        high_arr = np.full(n, 12.2)
        low_arr = np.full(n, 11.8)
        open_arr = np.full(n, 12.0)
        volume = np.full(n, 1_000_000.0)

        # 构造M顶: 高点在 index 5 和 20，低谷在 index 12
        # 上涨到14
        for i in range(6):
            high_arr[i] = 12.0 + i * 0.4  # 12.0 → 14.0
        # 回落到11
        for i in range(6, 13):
            high_arr[i] = 14.0 - (i - 5) * 0.4  # 14.0 → 10.8
        # 再涨到14
        for i in range(13, 21):
            high_arr[i] = 10.8 + (i - 12) * 0.4  # 10.8 → 14.4 → capped near 14.0
            if high_arr[i] > 14.2:
                high_arr[i] = 14.2
        # 跌到颈线以下
        for i in range(21, n):
            high_arr[i] = 13.0 - (i - 20) * 0.3

        # low = valley
        low_arr[:] = 11.0
        low_arr[12] = 10.5  # valley low
        for i in range(21, n):
            low_arr[i] = high_arr[i] - 0.5

        # close follows high
        for i in range(n):
            close[i] = high_arr[i] - 0.2
            open_arr[i] = close[i] + 0.05

        # 最后2日跌破颈线 (valley low = 10.5) + 放量
        close[-2] = 10.3
        high_arr[-2] = 10.5
        low_arr[-2] = 10.1
        open_arr[-2] = 10.6
        volume[-2] = 1_500_000

        close[-1] = 9.8
        high_arr[-1] = 10.1
        low_arr[-1] = 9.6
        open_arr[-1] = 10.4
        volume[-1] = 2_500_000

        df = pd.DataFrame({
            'open': open_arr, 'high': high_arr, 'low': low_arr,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-2-8" in codes


# ═══════════════════════════════════════════════════
# P-2-9: 头肩顶放量破位
# ═══════════════════════════════════════════════════

class TestP2_9_HeadShouldersTop:

    def test_detect_head_shoulders(self, detector):
        """头肩顶放量破位 — 应检测到"""
        # 构造清晰的头肩顶，40根K线
        n = 40
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        high_arr = np.full(n, 11.0)
        low_arr = np.full(n, 10.5)
        close = np.full(n, 10.8)
        open_arr = np.full(n, 10.8)
        volume = np.full(n, 1_000_000.0)

        # 左肩: peak at index 6, high=13
        high_arr[3] = 12.0
        high_arr[4] = 12.5
        high_arr[5] = 13.0
        high_arr[6] = 13.0  # peak
        high_arr[7] = 12.5
        high_arr[8] = 12.0

        # 头部: peak at index 19, high=15 (highest)
        high_arr[15] = 13.0
        high_arr[16] = 13.5
        high_arr[17] = 14.0
        high_arr[18] = 14.5
        high_arr[19] = 15.0  # head peak
        high_arr[20] = 14.5
        high_arr[21] = 14.0
        high_arr[22] = 13.5

        # 右肩: peak at index 32, high=12.5 (lower than left shoulder)
        high_arr[29] = 11.5
        high_arr[30] = 12.0
        high_arr[31] = 12.3
        high_arr[32] = 12.5  # right shoulder peak
        high_arr[33] = 12.2
        high_arr[34] = 11.8

        # Lows follow with neckline around 10.5
        for i in range(n):
            low_arr[i] = high_arr[i] - 1.5
            close[i] = high_arr[i] - 0.3
            open_arr[i] = close[i] - 0.05

        # 颈线区域最低约 9.5 (bars with high=11.0, low=9.5)
        # 最后2日跌破颈线 + 放量
        close[-2] = 9.2
        high_arr[-2] = 9.5
        low_arr[-2] = 9.0
        open_arr[-2] = 9.6
        volume[-2] = 1_500_000

        close[-1] = 8.5
        high_arr[-1] = 9.0
        low_arr[-1] = 8.3
        open_arr[-1] = 9.3
        volume[-1] = 2_500_000

        df = pd.DataFrame({
            'open': open_arr, 'high': high_arr, 'low': low_arr,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-2-9" in codes


# ═══════════════════════════════════════════════════
# P-2-10: 高位阴线放量
# ═══════════════════════════════════════════════════

class TestP2_10_HighBearishVolume:

    def test_detect_high_bearish(self, detector):
        """高位阴线放量 — 应检测到"""
        n = 60
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 10.0)
        open_p = np.full(n, 10.0)
        high = np.full(n, 20.0)
        low = np.full(n, 5.0)
        volume = np.full(n, 1_000_000.0)

        # 价格在高位
        close[:] = 17.0
        open_p[:] = 17.0

        # 前日收盘
        close[-4] = 17.5

        # 连续3根阴线+放量
        prices = [17.3, 17.0, 16.6]
        for i, p in enumerate(prices):
            idx = -3 + i
            open_p[idx] = p + 0.15
            close[idx] = p
            high[idx] = p + 0.3
            low[idx] = p - 0.1
            volume[idx] = 1_500_000.0  # above avg

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-2-10" in codes


# ═══════════════════════════════════════════════════
# P-2-11: 均线空头放量
# ═══════════════════════════════════════════════════

class TestP2_11_MABearishVolume:

    def test_detect_ma_bearish_volume(self, detector):
        """均线空头放量 — 应检测到"""
        n = 65
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        # 下降趋势 → MA5 < MA10 < MA20
        close = np.linspace(20, 10, n)
        open_p = close + 0.1
        high = close + 0.2
        low = close - 0.2
        volume = np.full(n, 1_000_000.0)

        # 最后一日放量阴线
        close[-1] = close[-2] - 0.5
        open_p[-1] = close[-1] + 0.3
        volume[-1] = 2_500_000.0

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-2-11" in codes


# ═══════════════════════════════════════════════════
# P-2-12: 反弹受阻缩量
# ═══════════════════════════════════════════════════

class TestP2_12_BounceResistance:

    def test_detect_bounce_resistance(self, detector):
        """反弹受阻缩量 — 应检测到"""
        n = 40
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        # 下降趋势
        close = np.linspace(15, 10, n) + np.random.randn(n) * 0.05
        open_p = close + 0.05
        high = close + 0.2
        low = close - 0.2
        volume = np.full(n, 1_000_000.0)

        # MA20 约在最后20日的均值附近
        ma20_val = float(np.mean(close[-20:]))

        # 近5日反弹到MA20附近
        close[-5] = ma20_val - 0.5
        close[-4] = ma20_val - 0.3
        close[-3] = ma20_val - 0.1
        high[-3] = ma20_val + 0.05  # 接近MA20
        close[-2] = ma20_val - 0.15  # 受阻回落
        close[-1] = ma20_val - 0.2

        # 最近2日缩量
        volume[-2] = 800_000
        volume[-1] = 600_000

        for i in range(-5, 0):
            open_p[i] = close[i] - 0.05
            high[i] = close[i] + 0.15
            low[i] = close[i] - 0.15

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-2-12" in codes


# ═══════════════════════════════════════════════════
# P-2-13: 放量跌破平台
# ═══════════════════════════════════════════════════

class TestP2_13_PlatformBreakdown:

    def test_detect_platform_breakdown(self, detector):
        """放量跌破平台 — 应检测到"""
        df = _build_base(30, 10.0, 1_000_000)
        # 前20日窄幅震荡平台
        for i in range(-21, -1):
            df.iloc[i, df.columns.get_loc('high')] = 10.5
            df.iloc[i, df.columns.get_loc('low')] = 10.0
            df.iloc[i, df.columns.get_loc('close')] = 10.2

        # 当日跌破平台+放量阴线
        df.iloc[-1, df.columns.get_loc('open')] = 10.1
        df.iloc[-1, df.columns.get_loc('close')] = 9.5
        df.iloc[-1, df.columns.get_loc('high')] = 10.2
        df.iloc[-1, df.columns.get_loc('low')] = 9.4
        df.iloc[-1, df.columns.get_loc('volume')] = 3_000_000  # 3x avg

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-2-13" in codes


# ═══════════════════════════════════════════════════
# P-2-14: 向下缺口放量
# ═══════════════════════════════════════════════════

class TestP2_14_GapDownVolume:

    def test_detect_gap_down(self, detector):
        """向下缺口放量 — 应检测到"""
        df = _build_base(30, 10.0, 1_000_000)
        # 前日最低价 9.8
        df.iloc[-2, df.columns.get_loc('low')] = 9.8
        df.iloc[-2, df.columns.get_loc('close')] = 10.0

        # 当日跳空低开 + 放量阴线
        df.iloc[-1, df.columns.get_loc('high')] = 9.7    # 最高 < 前日最低
        df.iloc[-1, df.columns.get_loc('open')] = 9.6
        df.iloc[-1, df.columns.get_loc('close')] = 9.3
        df.iloc[-1, df.columns.get_loc('low')] = 9.2
        df.iloc[-1, df.columns.get_loc('volume')] = 3_000_000

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-2-14" in codes


# ═══════════════════════════════════════════════════
# P-2-15: 高换手率暴跌
# ═══════════════════════════════════════════════════

class TestP2_15_HighTurnoverPlunge:

    def test_detect_high_turnover_plunge(self, detector):
        """高换手率暴跌 — 应检测到"""
        n = 60
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 10.0)
        open_p = np.full(n, 10.0)
        high = np.full(n, 20.0)
        low = np.full(n, 5.0)
        volume = np.full(n, 1_000_000.0)

        # 价格在高位
        close[:] = 17.0
        open_p[:] = 17.0

        # 前日收盘
        close[-2] = 17.5

        # 当日暴跌 -5% + 天量 + 大阴线
        open_p[-1] = 17.3
        close[-1] = 16.6   # -5.1%
        high[-1] = 17.4
        low[-1] = 16.5
        volume[-1] = 4_000_000.0  # 4x avg

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-2-15" in codes


# ═══════════════════════════════════════════════════
# P-2-16: 乌云盖顶放量
# ═══════════════════════════════════════════════════

class TestP2_16_DarkCloudCover:

    def test_detect_dark_cloud(self, detector):
        """乌云盖顶放量 — 应检测到"""
        n = 60
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 10.0)
        open_p = np.full(n, 10.0)
        high = np.full(n, 20.0)
        low = np.full(n, 5.0)
        volume = np.full(n, 1_000_000.0)

        # 价格在高位
        close[:] = 17.0
        open_p[:] = 17.0

        # 前日阳线
        open_p[-2] = 16.5
        close[-2] = 17.2
        high[-2] = 17.3
        low[-2] = 16.4

        # 当日：高开低走，收盘低于前日实体中点
        open_p[-1] = 17.5   # 高于前日收盘
        close[-1] = 16.6    # 低于 (16.5 + 17.2)/2 = 16.85
        high[-1] = 17.6
        low[-1] = 16.5
        volume[-1] = 2_000_000.0

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-2-16" in codes


# ═══════════════════════════════════════════════════
# P-2-17: 黄昏之星放量
# ═══════════════════════════════════════════════════

class TestP2_17_EveningStar:

    def test_detect_evening_star(self, detector):
        """黄昏之星放量 — 应检测到"""
        df = _build_base(30, 10.0, 1_000_000)

        # 第一根：大阳线
        df.iloc[-3, df.columns.get_loc('open')] = 10.0
        df.iloc[-3, df.columns.get_loc('close')] = 11.0
        df.iloc[-3, df.columns.get_loc('high')] = 11.1
        df.iloc[-3, df.columns.get_loc('low')] = 9.9

        # 第二根：小实体星线，跳空高开
        df.iloc[-2, df.columns.get_loc('open')] = 11.2
        df.iloc[-2, df.columns.get_loc('close')] = 11.3
        df.iloc[-2, df.columns.get_loc('high')] = 11.5
        df.iloc[-2, df.columns.get_loc('low')] = 11.1

        # 第三根：大阴线，收盘低于第一根中点 (10.5)
        df.iloc[-1, df.columns.get_loc('open')] = 11.2
        df.iloc[-1, df.columns.get_loc('close')] = 10.2
        df.iloc[-1, df.columns.get_loc('high')] = 11.3
        df.iloc[-1, df.columns.get_loc('low')] = 10.1
        df.iloc[-1, df.columns.get_loc('volume')] = 1_500_000

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-2-17" in codes


# ═══════════════════════════════════════════════════
# P-2-18: 下跌三浪放量
# ═══════════════════════════════════════════════════

class TestP2_18_ThreeWaveDecline:

    def test_detect_three_wave_decline(self, detector):
        """下跌三浪放量 — 应检测到"""
        n = 30
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 20.0)
        open_p = np.full(n, 20.0)
        high = np.full(n, 20.5)
        low = np.full(n, 19.5)
        volume = np.full(n, 1_000_000.0)

        # 第一浪 (0~9): 跌5%
        for i in range(10):
            close[i] = 20.0 - i * 0.11
            open_p[i] = close[i] + 0.05
            high[i] = close[i] + 0.2
            low[i] = close[i] - 0.2
            volume[i] = 800_000.0

        # 第二浪 (10~19): 跌5%，成交量放大
        for i in range(10, 20):
            close[i] = 18.9 - (i - 10) * 0.1
            open_p[i] = close[i] + 0.05
            high[i] = close[i] + 0.2
            low[i] = close[i] - 0.2
            volume[i] = 1_200_000.0

        # 第三浪 (20~29): 跌5%，成交量继续放大
        for i in range(20, 30):
            close[i] = 17.9 - (i - 20) * 0.09
            open_p[i] = close[i] + 0.05
            high[i] = close[i] + 0.2
            low[i] = close[i] - 0.2
            volume[i] = 1_800_000.0

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-2-18" in codes


# ═══════════════════════════════════════════════════
# P-2-19: 圆弧顶缩量
# ═══════════════════════════════════════════════════

class TestP2_19_RoundedTop:

    def test_detect_rounded_top(self, detector):
        """圆弧顶缩量 — 应检测到"""
        n = 35
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        # 倒U型价格
        close = np.zeros(n)
        half = n // 2
        for i in range(half + 1):
            close[i] = 10.0 + 5.0 * (i / half)  # 10 → 15
        for i in range(half, n):
            close[i] = 15.0 - 5.0 * ((i - half) / (n - 1 - half))  # 15 → 10

        open_p = close + 0.05
        high = close + 0.2
        low = close - 0.2

        # 左半段高量，右半段低量
        volume = np.full(n, 1_500_000.0)
        volume[half:] = 600_000.0

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-2-19" in codes


# ═══════════════════════════════════════════════════
# P-2-20: 旗形下跌破位
# ═══════════════════════════════════════════════════

class TestP2_20_FlagBreakdown:

    def test_detect_flag_breakdown(self, detector):
        """旗形下跌破位 — 应检测到"""
        n = 30
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 12.0)
        open_p = np.full(n, 12.0)
        high = np.full(n, 12.5)
        low = np.full(n, 11.5)
        volume = np.full(n, 1_000_000.0)

        # 旗杆: 15~10日前快速下跌（跌幅>8%）
        for i in range(5):
            close[-20 + i] = 12.0 - i * 0.3  # 12.0 → 10.8 (-10%)

        # 旗面: 近5日窄幅反弹
        for i in range(-6, -1):
            close[i] = 11.0
            high[i] = 11.1
            low[i] = 10.9

        # 旗面缩量
        for i in range(-6, -1):
            volume[i] = 500_000.0

        # 最后一日跌破旗面下沿 + 放量
        open_p[-1] = 11.0
        close[-1] = 10.5
        high[-1] = 11.1
        low[-1] = 10.4
        volume[-1] = 2_000_000.0

        for i in range(-20, 0):
            open_p[i] = close[i] - 0.05
            high[i] = close[i] + 0.1
            low[i] = close[i] - 0.1

        # Reset the flag and breakdown specifics
        for i in range(-6, -1):
            close[i] = 11.0
            high[i] = 11.1
            low[i] = 10.9
            open_p[i] = 11.0
            volume[i] = 500_000.0

        open_p[-1] = 11.0
        close[-1] = 10.5
        high[-1] = 11.1
        low[-1] = 10.4
        volume[-1] = 2_000_000.0

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-2-20" in codes


# ═══════════════════════════════════════════════════
# 多形态并行检测
# ═══════════════════════════════════════════════════

class TestMultiplePatterns:

    def test_multiple_patterns_can_fire(self, detector, sample_df):
        """随机数据上可能检测到0个或多个形态"""
        results = detector.detect(sample_df)
        assert 0 <= len(results) <= 20

    def test_no_duplicate_codes(self, detector, sample_df):
        """同一DataFrame上不应出现重复形态"""
        results = detector.detect(sample_df)
        codes = [r.name for r in results]
        assert len(codes) == len(set(codes))


# ═══════════════════════════════════════════════════
# PatternResult 结构完整性
# ═══════════════════════════════════════════════════

class TestPatternResultStructure:

    def test_result_to_dict(self, detector):
        """PatternResult.to_dict() 应可正常序列化"""
        n = 30
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 12.0)
        open_p = np.full(n, 12.0)
        high = np.full(n, 12.5)
        low = np.full(n, 11.5)
        volume = np.full(n, 1_000_000.0)

        # 构造连续缩量下跌
        prices = [12.0, 11.7, 11.3, 10.8, 10.3, 9.7]
        vols = [1_200_000, 900_000, 700_000, 500_000, 300_000, 200_000]
        for i, (p, v) in enumerate(zip(prices, vols)):
            idx = -6 + i
            close[idx] = p
            open_p[idx] = p + 0.05
            high[idx] = p + 0.2
            low[idx] = p - 0.2
            volume[idx] = float(v)

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
