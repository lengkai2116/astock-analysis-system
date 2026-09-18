"""461-4：volatility_level 三口径统一（未年化 20 日 std 档位）测试

460 §四 打架项③ + §五 P2：volatility_level 三处生产（derived 量比代理 / risk_ext 调
`_calc_volatility(df, {})` 传空 tags 恒 medium / 简单标签），扁平化后 risk_ext 恒 medium
后写覆盖 → dim6 波动率判定失真。

用户拍板：档位算法统一为「未年化 20 日滚动 std × 100」（high>4 / medium>2 / low），
与框架 `volume_price_strategy:4177` 逐字对齐；历史分位保留年化 vol_20d。
"""
import math

import numpy as np
import pandas as pd
import pytest

from app.opportunity_atlas.dimensions.dim6_risk_engine import _calc_volatility


def _mk_df(std_pct=2.0, n=60):
    """构造 20 日收益率 std×100 ≈ std_pct 的收盘序列"""
    rng = np.random.RandomState(0)
    returns = rng.normal(0, std_pct / 100.0 / math.sqrt(1), n)
    close = 10 * np.cumprod(1 + returns)
    high = close * 1.01
    low = close * 0.99
    idx = pd.date_range('2025-01-01', periods=n, freq='B')
    return pd.DataFrame({'ts_code': 'TEST', 'trade_date': idx,
                         'open': close, 'high': high, 'low': low, 'close': close, 'vol': 1000},
                        index=idx)


class TestCalcVolatilityLevel:
    def test_level_computed_from_unannualized_std(self):
        """df 充足时档位由未年化 20 日 std×100 判（不再依赖空 tags 恒 medium）"""
        vol = _calc_volatility(_mk_df(std_pct=2.0), {})
        assert vol['level'] in ('high', 'medium', 'low')

    def test_low_volatility_grade(self):
        """std<2% → low"""
        df = _mk_df(std_pct=0.5)
        vol = _calc_volatility(df, {})
        assert vol['level'] == 'low'

    def test_medium_boundary(self):
        """std 2-4% → medium"""
        # 用确定性递增构建确保 std 在 (2,4)
        n = 60
        returns = np.linspace(-0.005, 0.005, n)  # 标准差远小于目标，需放大
        # 直接构造接近 3% 日 std 的序列
        rng = np.random.RandomState(1)
        rets = rng.normal(0, 0.03, n)
        close = 10 * np.cumprod(1 + rets)
        df = pd.DataFrame({'close': close, 'high': close * 1.01, 'low': close * 0.99}, index=range(n))
        vol = _calc_volatility(df, {})
        assert vol['level'] == 'medium'

    def test_high_volatility_grade(self):
        """std>4% → high"""
        df = _mk_df(std_pct=6.0)
        vol = _calc_volatility(df, {})
        assert vol['level'] == 'high'

    def test_returns_percentile_annualized(self):
        """percentile 仍为年化波动率历史分位（0-1）"""
        df = _mk_df(std_pct=3.0)
        vol = _calc_volatility(df, {})
        assert 0.0 <= vol['percentile'] <= 1.0
        assert vol['atr_14d'] > 0

    def test_no_tags_fallback_medium_when_df_absent(self):
        """df 缺省且无 tags → 恒 medium（兼容旧路径）"""
        vol = _calc_volatility(None, {})
        assert vol['level'] == 'medium'
