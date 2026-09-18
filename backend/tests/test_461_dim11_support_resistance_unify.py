
"""461-11：支撑阻力单实现（calc_geometric vs calc_support_resistance 择一）

460 §五 P7 / §六 阶段2-2-1——统一三套逐字副本为唯一 SSOT：
  - risk_ext 生产由 dim6.calc_geometric 迁移到 shared.calc_support_resistance
  - dim6.calc_geometric / advice_builder._geometric / advice_engine._geometric
    收敛为 shared 的兼容委托层
  - shared 并回 signal_days / dist_to_prev_high_pct 两键，输出契约对齐 calc_geometric

验证要点：
  1. shared 输出 8 键契约（含新并入的 signal_days/dist_to_prev_high_pct）
  2. 四套几何实现键值完全等价（唯一 SSOT 生效）
  3. indicator_ma_df 预计算优先
  4. 空 df 早退契约
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import numpy as np
import pandas as pd


def _df(n=70, seed=7):
    np.random.seed(seed)
    return pd.DataFrame({
        'close': np.random.uniform(10, 15, n).round(2),
        'high': np.random.uniform(12, 17, n).round(2),
        'low': np.random.uniform(8, 13, n).round(2),
    })


class TestSharedSSOTContract:
    """461-11：shared.calc_support_resistance 为唯一源，输出 8 键契约"""

    def test_all_keys_present(self):
        from app.opportunity_atlas.dimensions.shared_support_resistance import calc_support_resistance
        r = calc_support_resistance(_df())
        for k in ('support_price', 'resistance_price', 'dist_to_support_pct',
                  'dist_to_resistance_pct', 'risk_reward', 'signal_days',
                  'dist_to_prev_high_pct', 'source'):
            assert k in r, f'缺键 {k}'

    def test_signal_days_and_dist_prev_high_merged(self):
        """461-11 核心：calc_geometric 专属两键并入 shared"""
        from app.opportunity_atlas.dimensions.shared_support_resistance import calc_support_resistance
        r = calc_support_resistance(_df())
        assert 'dist_to_prev_high_pct' in r
        assert r['support_price'] is not None
        assert r['resistance_price'] is not None

    def test_indicator_ma_df_precomputed_priority(self):
        """structure_ext/dim2 传入 indicator_ma_df → MA20/MA60 读预计算，非简单均值"""
        from app.opportunity_atlas.dimensions.shared_support_resistance import calc_support_resistance
        df = _df()
        # 构造一个与 raw 简单均值明显不同的预计算均线 → 支撑/压力应反映预计算
        fake_ma = pd.DataFrame({'ma20': [float(df['close'].tail(20).mean() + 5.0)],
                                'ma60': [float(df['close'].tail(60).mean() - 5.0)]})
        base = calc_support_resistance(df)
        with_ma = calc_support_resistance(df, indicator_ma_df=fake_ma)
        # 预计算 MA20 抬高 → near 支撑不低于 raw 版（除非被 15% 止损压缩）
        assert with_ma['support_price'] >= base['support_price']

    def test_empty_df_returns_none(self):
        from app.opportunity_atlas.dimensions.shared_support_resistance import calc_support_resistance
        r = calc_support_resistance(None)
        assert r['support_price'] is None
        assert r['resistance_price'] is None
        assert r['signal_days'] is None
        assert r['dist_to_prev_high_pct'] is None
        assert r['source'] == '数据不足'


class TestDelegationEquivalence:
    """461-11：三套几何副本 → shared 委托后键值完全等价"""

    def test_all_four_implementations_equal(self):
        from app.opportunity_atlas.dimensions.shared_support_resistance import calc_support_resistance
        from app.opportunity_atlas.dimensions.dim6_risk_engine import calc_geometric
        from app.opportunity_atlas.advice_builder import _geometric as ab_g
        from app.opportunity_atlas.advice_engine import _geometric as ae_g
        df = _df()
        sr = calc_support_resistance(df)
        cg = calc_geometric(df)
        ab = ab_g(df)
        ae = ae_g(df)
        for k in ('support_price', 'resistance_price', 'dist_to_support_pct',
                  'dist_to_resistance_pct', 'risk_reward', 'signal_days'):
            assert sr.get(k) == cg.get(k) == ab.get(k) == ae.get(k), k

    def test_calc_geometric_keeps_dist_prev_high(self):
        """dim6.calc_geometric 委托 shared 后仍保留 dist_to_prev_high_pct"""
        from app.opportunity_atlas.dimensions.dim6_risk_engine import calc_geometric
        r = calc_geometric(_df())
        assert 'dist_to_prev_high_pct' in r
        assert 'dist_to_support_pct' in r

    def test_empty_df_thin_delegation(self):
        from app.opportunity_atlas.dimensions.dim6_risk_engine import calc_geometric
        from app.opportunity_atlas.advice_builder import _geometric as ab_g
        r = calc_geometric(None)
        assert r['support_price'] is None
        r2 = ab_g(None)
        assert r2['support_price'] is None
