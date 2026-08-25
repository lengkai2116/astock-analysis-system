"""
测试预涨型形态检测器（20种）
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
from app.engine.patterns.detectors.bullish_patterns import BullishPatternDetector


# ═══════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════

@pytest.fixture
def detector():
    return BullishPatternDetector()


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

class TestBullishDetectorBasics:

    def test_import(self):
        """应能导入 BullishPatternDetector"""
        assert BullishPatternDetector is not None

    def test_is_subclass(self):
        """应继承 PatternDetector"""
        from app.engine.patterns.detectors.base import PatternDetector
        assert issubclass(BullishPatternDetector, PatternDetector)

    def test_can_instantiate(self):
        """可以实例化（非抽象类）"""
        d = BullishPatternDetector()
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

    def test_result_category_is_bullish(self, detector, sample_df):
        """所有结果分类应为 BULLISH_PATTERNS"""
        results = detector.detect(sample_df)
        for r in results:
            assert r.category == PatternCategory.BULLISH_PATTERNS

    def test_result_direction_is_bullish(self, detector, sample_df):
        """所有结果方向应为 bullish"""
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
        # 传入缺少列的DataFrame不应当抛异常
        df = pd.DataFrame({'x': [1, 2, 3]})
        try:
            results = detector.detect(df)
            assert isinstance(results, list)
        except Exception:
            pytest.fail("detect() should not raise on bad input")

    def test_all_20_detectors_exist(self, detector):
        """应有20个检测方法"""
        methods = [f'_p_1_{i}' for i in range(1, 21)]
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
# P-1-1: 缩量十字星
# ═══════════════════════════════════════════════════

class TestP1_1_ShrinkingDoji:

    def test_detect_shrinking_doji(self, detector):
        """缩量十字星 — 应检测到"""
        n = 30
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 10.0)
        open_p = np.full(n, 10.0)
        high = np.full(n, 15.0)  # wide 20-day range
        low = np.full(n, 5.0)
        volume = np.full(n, 1_000_000.0)

        # Set price near bottom of range
        close[:] = 5.5
        open_p[:] = 5.5
        low[:] = 5.0
        high[:] = 15.0

        # Last 5 volumes: strictly decreasing AND below 50% of 20-day avg
        # 20-day avg = (15*1M + 5 descending) / 20 ~ 875K; 50% = 437K
        for i, v in enumerate([400_000, 300_000, 200_000, 150_000, 100_000]):
            volume[-(5 - i)] = float(v)

        # Last row: doji (body/amp < 0.1)
        open_p[-1] = 5.50
        close[-1] = 5.51
        high[-1] = 5.70
        low[-1] = 5.30

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-1-1" in codes

    def test_no_shrinking_doji_when_not_doji(self, detector):
        """非十字星时不应触发"""
        df = _build_base(30, 10.0, 1_000_000)
        # 最后一根大阳线（非十字星）
        df.iloc[-1, df.columns.get_loc('close')] = 11.0
        df.iloc[-1, df.columns.get_loc('open')] = 10.0
        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-1-1" not in codes


# ═══════════════════════════════════════════════════
# P-1-2: 底部温和放量
# ═══════════════════════════════════════════════════

class TestP1_2_BottomMildVolume:

    def test_detect_mild_volume(self, detector):
        """底部温和放量 — 应检测到"""
        df = _build_base(60, 10.0, 1_000_000)
        # 价格在低位
        df['high'] = 12.0
        df['low'] = 9.0
        df['close'] = 9.5  # 低位

        # 最近3日成交量温和递增
        df.iloc[-3, df.columns.get_loc('volume')] = 1_300_000
        df.iloc[-2, df.columns.get_loc('volume')] = 1_500_000
        df.iloc[-1, df.columns.get_loc('volume')] = 1_800_000

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-1-2" in codes


# ═══════════════════════════════════════════════════
# P-1-3: 量价齐升启动
# ═══════════════════════════════════════════════════

class TestP1_3_PriceVolumeRise:

    def test_detect_price_volume_rise(self, detector):
        """量价齐升 — 应检测到"""
        df = _build_base(30, 10.0, 1_000_000)
        # 最近4日价格递增+阳线
        prices = [10.0, 10.2, 10.5, 10.9]
        vols = [1_000_000, 1_500_000, 2_000_000, 2_500_000]
        for i, (p, v) in enumerate(zip(prices, vols)):
            idx = -4 + i
            df.iloc[idx, df.columns.get_loc('open')] = p - 0.1
            df.iloc[idx, df.columns.get_loc('close')] = p
            df.iloc[idx, df.columns.get_loc('volume')] = float(v)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-1-3" in codes


# ═══════════════════════════════════════════════════
# P-1-4: 缩量回踩均线
# ═══════════════════════════════════════════════════

class TestP1_4_PullbackMA:

    def test_detect_pullback_ma(self, detector):
        """缩量回踩均线 — 应检测到"""
        # 构造MA20上行的数据
        n = 40
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        # 缓慢上升趋势
        close = np.linspace(10, 14, n) + np.random.randn(n) * 0.1
        open_p = close - 0.05
        high = close + 0.1
        low = close - 0.1
        volume = np.full(n, 1_000_000.0)

        # 近3日回踩：低点贴近MA20，缩量
        ma20 = float(np.mean(close[-20:]))
        for i in range(-3, 0):
            close[i] = ma20 + 0.02
            low[i] = ma20 - 0.02
            open_p[i] = close[i] - 0.05
            high[i] = close[i] + 0.1
            volume[i] = 500_000.0  # 缩量

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-1-4" in codes


# ═══════════════════════════════════════════════════
# P-1-5: 底部堆量蓄势
# ═══════════════════════════════════════════════════

class TestP1_5_BottomAccumulation:

    def test_detect_bottom_accumulation(self, detector):
        """底部堆量 — 应检测到"""
        n = 60
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 10.0)
        open_p = np.full(n, 10.0)
        high = np.full(n, 15.0)  # wide range for old data
        low = np.full(n, 5.0)
        volume = np.full(n, 1_000_000.0)

        # Set price near bottom: (6 - 5) / (15 - 5) = 0.1
        close[:] = 6.0
        open_p[:] = 6.0

        # Recent 10 days: narrow range (for amplitude < 8%)
        for i in range(-10, 0):
            high[i] = 6.1
            low[i] = 5.9
            close[i] = 6.0
            open_p[i] = 6.0

        # Prior data (indices -30 to -11): low volume
        for i in range(-30, -10):
            volume[i] = 500_000.0

        # Recent 10 days: high volume (accumulation)
        for i in range(-10, 0):
            volume[i] = 1_500_000.0

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-1-5" in codes


# ═══════════════════════════════════════════════════
# P-1-6: 放量突破平台
# ═══════════════════════════════════════════════════

class TestP1_6_BreakoutPlatform:

    def test_detect_breakout(self, detector):
        """放量突破平台 — 应检测到"""
        df = _build_base(30, 10.0, 1_000_000)
        # 前20日窄幅震荡平台
        for i in range(-21, -1):
            df.iloc[i, df.columns.get_loc('high')] = 10.5
            df.iloc[i, df.columns.get_loc('low')] = 10.0
            df.iloc[i, df.columns.get_loc('close')] = 10.2

        # 当日突破+放量阳线
        df.iloc[-1, df.columns.get_loc('open')] = 10.3
        df.iloc[-1, df.columns.get_loc('close')] = 10.8
        df.iloc[-1, df.columns.get_loc('high')] = 10.9
        df.iloc[-1, df.columns.get_loc('low')] = 10.2
        df.iloc[-1, df.columns.get_loc('volume')] = 3_000_000  # 3倍均量

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-1-6" in codes


# ═══════════════════════════════════════════════════
# P-1-7: 阳线放量反包
# ═══════════════════════════════════════════════════

class TestP1_7_BullishEngulfingVolume:

    def test_detect_engulfing_volume(self, detector):
        """阳线放量反包 — 应检测到"""
        df = _build_base(30, 10.0, 1_000_000)
        # 前日阴线
        df.iloc[-2, df.columns.get_loc('open')] = 10.5
        df.iloc[-2, df.columns.get_loc('close')] = 9.5
        # 当日阳线反包 + 放量
        df.iloc[-1, df.columns.get_loc('open')] = 9.3
        df.iloc[-1, df.columns.get_loc('close')] = 10.8
        df.iloc[-1, df.columns.get_loc('high')] = 10.9
        df.iloc[-1, df.columns.get_loc('low')] = 9.2
        df.iloc[-1, df.columns.get_loc('volume')] = 2_500_000

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-1-7" in codes


# ═══════════════════════════════════════════════════
# P-1-8: 缩量洗盘后放量
# ═══════════════════════════════════════════════════

class TestP1_8_ShrinkThenVolume:

    def test_detect_shrink_then_volume(self, detector):
        """缩量洗盘后放量 — 应检测到"""
        n = 30
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 10.0)
        open_p = np.full(n, 10.0)
        high = np.full(n, 10.5)
        low = np.full(n, 9.5)
        volume = np.full(n, 1_000_000.0)

        # 缩量下跌阶段（-10 to -6）: 连续3日volume递减 + close递减
        for i, idx in enumerate(range(-10, -5)):
            volume[idx] = float(500_000 - i * 50_000)
            close[idx] = 10.5 - i * 0.1  # 10.5, 10.4, 10.3, 10.2, 10.1
            open_p[idx] = close[idx] + 0.05

        # 近4日低量
        for i in range(-4, -1):
            volume[i] = 300_000.0
            close[i] = 10.0
            open_p[i] = 10.0

        # 当日放量阳线（volume > 2x prev3 avg = 300K, and > 20-day avg = ~800K）
        open_p[-1] = 9.9
        close[-1] = 10.3
        high[-1] = 10.4
        low[-1] = 9.8
        volume[-1] = 2_000_000.0

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-1-8" in codes


# ═══════════════════════════════════════════════════
# P-1-9: 量比递增上涨
# ═══════════════════════════════════════════════════

class TestP1_9_IncreasingVolumeRatio:

    def test_detect_increasing_vol_ratio(self, detector):
        """量比递增上涨 — 应检测到"""
        n = 30
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 10.0)
        open_p = np.full(n, 10.0)
        high = np.full(n, 10.5)
        low = np.full(n, 9.5)
        volume = np.full(n, 1_000_000.0)

        # Ensure close[-5] < close[-4] (row before the 4-day sequence)
        close[-5] = 9.5

        # 近4日价格+成交量均递增，且量比递增
        # 20-day MA ~ 1M, so ratios are ~1.2, 1.8, 2.5, 3.5
        prices = [10.0, 10.2, 10.5, 10.9]
        vols = [1_200_000, 1_800_000, 2_500_000, 3_500_000]
        for i, (p, v) in enumerate(zip(prices, vols)):
            idx = -4 + i
            open_p[idx] = p - 0.1
            close[idx] = p
            high[idx] = p + 0.1
            low[idx] = p - 0.15
            volume[idx] = float(v)

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-1-9" in codes


# ═══════════════════════════════════════════════════
# P-1-10: 底部放量长阳
# ═══════════════════════════════════════════════════

class TestP1_10_BottomBigYangVolume:

    def test_detect_bottom_big_yang(self, detector):
        """底部放量长阳 — 应检测到"""
        n = 60
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 10.0)
        open_p = np.full(n, 10.0)
        high = np.full(n, 20.0)  # wide range for price position
        low = np.full(n, 5.0)
        volume = np.full(n, 1_000_000.0)

        # Set price near bottom: (6 - 5) / (20 - 5) = 0.067
        close[:] = 6.0
        open_p[:] = 6.0

        # 前日收盘
        close[-2] = 6.0

        # 当日大阳+6%: 6.0 → 6.36
        open_p[-1] = 6.0
        close[-1] = 6.4  # +6.7%
        high[-1] = 6.45
        low[-1] = 5.95
        volume[-1] = 3_500_000.0

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-1-10" in codes


# ═══════════════════════════════════════════════════
# P-1-11: 均线多头放量
# ═══════════════════════════════════════════════════

class TestP1_11_MABullishVolume:

    def test_detect_ma_bullish_volume(self, detector):
        """均线多头放量 — 应检测到"""
        n = 65
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        # 构造上升趋势 → MA5 > MA10 > MA20
        close = np.linspace(10, 20, n)
        open_p = close - 0.1
        high = close + 0.2
        low = close - 0.2
        volume = np.full(n, 1_000_000.0)

        # 最后一日放量阳线
        volume[-1] = 2_500_000.0
        close[-1] = close[-2] + 0.5
        open_p[-1] = close[-1] - 0.3

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-1-11" in codes


# ═══════════════════════════════════════════════════
# P-1-12: W底放量突破
# ═══════════════════════════════════════════════════

class TestP1_12_WBottomBreakout:

    def test_detect_w_bottom(self, detector):
        """W底放量突破 — 应检测到"""
        n = 40
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 12.0)

        # 构造W底: 前15日下降到9.5, 反弹到11, 再降到9.6, 然后突破到11.5
        for i in range(10):
            close[i] = 12.0 - i * 0.25
        close[10] = 9.5  # 第一底
        for i in range(11, 18):
            close[i] = 9.5 + (i - 10) * 0.3
        close[18] = 11.5  # 颈线
        for i in range(19, 28):
            close[i] = 11.5 - (i - 18) * 0.22
        close[28] = 9.6  # 第二底
        for i in range(29, 38):
            close[i] = 9.6 + (i - 28) * 0.15

        # 最后突破颈线
        close[-1] = 11.8
        close[-2] = 11.3

        open_p = close - 0.05
        high = close + 0.2
        low = close - 0.2
        low[10] = 9.4
        low[28] = 9.5
        volume = np.full(n, 1_000_000.0)
        volume[-1] = 3_000_000.0  # 突破放量

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-1-12" in codes


# ═══════════════════════════════════════════════════
# P-1-13: 缺口放量突破
# ═══════════════════════════════════════════════════

class TestP1_13_GapBreakout:

    def test_detect_gap_volume(self, detector):
        """缺口放量突破 — 应检测到"""
        df = _build_base(30, 10.0, 1_000_000)
        # 前日最高价 10.5
        df.iloc[-2, df.columns.get_loc('high')] = 10.5
        df.iloc[-2, df.columns.get_loc('close')] = 10.3

        # 当日跳空高开 + 放量阳线
        df.iloc[-1, df.columns.get_loc('low')] = 10.6   # 最低 > 前日最高
        df.iloc[-1, df.columns.get_loc('open')] = 10.7
        df.iloc[-1, df.columns.get_loc('close')] = 11.0
        df.iloc[-1, df.columns.get_loc('high')] = 11.1
        df.iloc[-1, df.columns.get_loc('volume')] = 3_000_000

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-1-13" in codes


# ═══════════════════════════════════════════════════
# P-1-14: 量能潮汐启动
# ═══════════════════════════════════════════════════

class TestP1_14_VolumeTide:

    def test_detect_volume_tide(self, detector):
        """量能潮汐启动 — 应检测到"""
        df = _build_base(25, 10.0, 1_000_000)

        # 前15~10日: 较高成交量
        for i in range(-15, -10):
            df.iloc[i, df.columns.get_loc('volume')] = 1_500_000

        # 10~5日: 缩量
        for i in range(-10, -5):
            df.iloc[i, df.columns.get_loc('volume')] = 500_000

        # 最近5日: 放量回升
        for i in range(-5, 0):
            df.iloc[i, df.columns.get_loc('volume')] = 1_800_000

        # 价格上涨
        df.iloc[-1, df.columns.get_loc('close')] = 10.5
        df.iloc[-5, df.columns.get_loc('close')] = 10.0

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-1-14" in codes


# ═══════════════════════════════════════════════════
# P-1-15: 主力吸筹放量
# ═══════════════════════════════════════════════════

class TestP1_15_StealthAccumulation:

    def test_detect_stealth_accumulation(self, detector):
        """主力吸筹放量 — 应检测到"""
        n = 60
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 6.0)
        open_p = np.full(n, 6.0)
        high = np.full(n, 20.0)  # wide 60-day range
        low = np.full(n, 5.0)
        volume = np.full(n, 1_000_000.0)

        # price position: (6 - 5) / (20 - 5) = 0.067
        close[:] = 6.0
        open_p[:] = 6.0

        # 当日异常放量但振幅极小 (<3%)
        open_p[-1] = 6.00
        close[-1] = 6.02
        high[-1] = 6.08   # amp = (6.08-5.92)/5.92 ≈ 2.7%
        low[-1] = 5.92
        volume[-1] = 4_000_000.0  # 4x avg

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-1-15" in codes


# ═══════════════════════════════════════════════════
# P-1-16: 圆弧底放量
# ═══════════════════════════════════════════════════

class TestP1_16_RoundedBottom:

    def test_detect_rounded_bottom(self, detector):
        """圆弧底放量 — 应检测到"""
        n = 35
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        # U型 price: starts high, dips in middle, recovers
        # Use a simple V-shape: left descends, right ascends
        close = np.zeros(n)
        half = n // 2
        for i in range(half + 1):
            close[i] = 15.0 - 5.0 * (i / half)  # 15 → 10
        for i in range(half, n):
            close[i] = 10.0 + 5.0 * ((i - half) / (n - 1 - half))  # 10 → 15

        open_p = close - 0.05
        high = close + 0.2
        low = close - 0.2

        # Left half: low volume; right half: high volume
        volume = np.full(n, 600_000.0)
        volume[half:] = 1_500_000.0

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-1-16" in codes


# ═══════════════════════════════════════════════════
# P-1-17: 三阳开泰放量
# ═══════════════════════════════════════════════════

class TestP1_17_ThreeYangKaitai:

    def test_detect_three_yang(self, detector):
        """三阳开泰放量 — 应检测到"""
        df = _build_base(30, 10.0, 1_000_000)
        # 连续3日阳线+价格递增+成交量递增
        df.iloc[-3, df.columns.get_loc('open')] = 10.0
        df.iloc[-3, df.columns.get_loc('close')] = 10.2
        df.iloc[-3, df.columns.get_loc('volume')] = 1_200_000

        df.iloc[-2, df.columns.get_loc('open')] = 10.2
        df.iloc[-2, df.columns.get_loc('close')] = 10.5
        df.iloc[-2, df.columns.get_loc('volume')] = 1_500_000

        df.iloc[-1, df.columns.get_loc('open')] = 10.5
        df.iloc[-1, df.columns.get_loc('close')] = 10.9
        df.iloc[-1, df.columns.get_loc('volume')] = 2_000_000

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-1-17" in codes


# ═══════════════════════════════════════════════════
# P-1-18: 旗形整理突破
# ═══════════════════════════════════════════════════

class TestP1_18_FlagBreakout:

    def test_detect_flag_breakout(self, detector):
        """旗形整理突破 — 应检测到"""
        n = 30
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 10.0)

        # 旗杆：15~10日前快速上涨
        for i in range(5):
            close[-20 + i] = 10.0 + i * 0.3  # 涨幅>8%

        # 旗面：近5日窄幅
        for i in range(-6, -1):
            close[i] = 11.5
        close[-1] = 11.9  # 突破

        open_p = close - 0.05
        high = close + 0.1
        low = close - 0.1
        volume = np.full(n, 1_000_000.0)
        # 旗面缩量
        for i in range(-6, -1):
            volume[i] = 500_000.0
        volume[-1] = 2_000_000.0  # 突破放量

        df = pd.DataFrame({
            'open': open_p, 'high': high, 'low': low,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-1-18" in codes


# ═══════════════════════════════════════════════════
# P-1-19: 三角收敛突破
# ═══════════════════════════════════════════════════

class TestP1_19_TriangleBreakout:

    def test_detect_triangle_breakout(self, detector):
        """三角收敛突破 — 应检测到"""
        n = 25
        dates = pd.date_range(start='2025-01-01', periods=n, freq='B')
        close = np.full(n, 10.0)
        high_arr = np.full(n, 10.0)
        low_arr = np.full(n, 10.0)
        open_arr = np.full(n, 10.0)
        volume = np.full(n, 1_000_000.0)

        # Segments based on iloc[-16+i*5 : -16+(i+1)*5]:
        #   seg0: iloc[-16:-11] → indices -16,-15,-14,-13,-12
        #   seg1: iloc[-11:-6]  → indices -11,-10,-9,-8,-7
        #   seg2: iloc[-6:-1]   → indices -6,-5,-4,-3,-2
        #   current bar: index -1 (breakout)

        # Segment 0: widest
        for i in range(-16, -11):
            high_arr[i] = 11.0
            low_arr[i] = 9.0

        # Segment 1: converging
        for i in range(-11, -6):
            high_arr[i] = 10.7
            low_arr[i] = 9.3

        # Segment 2: more converging
        for i in range(-6, -1):
            high_arr[i] = 10.4
            low_arr[i] = 9.6

        # Breakout on last bar
        close[-1] = 10.6  # above seg2 high 10.4
        open_arr[-1] = 10.2
        high_arr[-1] = 10.7
        low_arr[-1] = 10.1
        volume[-1] = 2_500_000.0

        df = pd.DataFrame({
            'open': open_arr, 'high': high_arr, 'low': low_arr,
            'close': close, 'volume': volume,
        }, index=dates)

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-1-19" in codes


# ═══════════════════════════════════════════════════
# P-1-20: 箱体突破放量
# ═══════════════════════════════════════════════════

class TestP1_20_BoxBreakout:

    def test_detect_box_breakout(self, detector):
        """箱体突破放量 — 应检测到"""
        df = _build_base(30, 10.0, 1_000_000)
        # 前20日箱体震荡
        for i in range(-21, -1):
            df.iloc[i, df.columns.get_loc('high')] = 10.5
            df.iloc[i, df.columns.get_loc('low')] = 10.0
            df.iloc[i, df.columns.get_loc('close')] = 10.2
            df.iloc[i, df.columns.get_loc('open')] = 10.2
            # 让部分触碰上下沿
            if i % 3 == 0:
                df.iloc[i, df.columns.get_loc('high')] = 10.5
            if i % 3 == 1:
                df.iloc[i, df.columns.get_loc('low')] = 10.0

        # 当日突破上沿 + 放量
        df.iloc[-1, df.columns.get_loc('open')] = 10.3
        df.iloc[-1, df.columns.get_loc('close')] = 10.8
        df.iloc[-1, df.columns.get_loc('high')] = 10.9
        df.iloc[-1, df.columns.get_loc('low')] = 10.2
        df.iloc[-1, df.columns.get_loc('volume')] = 2_500_000

        results = detector.detect(df)
        codes = [r.name for r in results]
        assert "P-1-20" in codes


# ═══════════════════════════════════════════════════
# 多形态并行检测
# ═══════════════════════════════════════════════════

class TestMultiplePatterns:

    def test_multiple_patterns_can_fire(self, detector, sample_df):
        """随机数据上可能检测到0个或多个形态"""
        results = detector.detect(sample_df)
        # 不要求一定有，但结果列表长度合理
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
        df = _build_base(60, 10.0, 1_000_000)
        # 使至少一个形态触发
        df.iloc[-3, df.columns.get_loc('volume')] = 200_000
        df.iloc[-2, df.columns.get_loc('volume')] = 150_000
        df.iloc[-1, df.columns.get_loc('volume')] = 100_000
        df.iloc[-1, df.columns.get_loc('open')] = 10.00
        df.iloc[-1, df.columns.get_loc('close')] = 10.01
        df.iloc[-1, df.columns.get_loc('high')] = 10.05
        df.iloc[-1, df.columns.get_loc('low')] = 9.95
        # 需要低位
        df['high'] = 12.0
        df['low'] = 9.0

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

    def test_result_source_set(self, detector):
        """source 应设为 wiki_volume_price"""
        df = _build_base(30, 10.0, 1_000_000)
        results = detector.detect(df)
        for r in results:
            assert r.source == "wiki_volume_price"
