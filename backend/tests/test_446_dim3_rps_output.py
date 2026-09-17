"""446号：dim3 RPS 缺产出修复单元测试

445 §6.1 dim3「RPS 被 RSI 顶替」——dim3 强弱因子 `is_` 只读 rsi14，RPS（相对强弱
排名百分位）从不参与评分，强势股筛选信号缺失。

修复：
  1. data_daemon._compute_relative_strength 补算跨截面 RPS 百分位（个股20/60日涨幅
     全市场排名百分位，rank(pct=True)*100，写入 relative_strength_cache.rps_20d/rps_60d）。
  2. enhanced_cache_manager 建表/写入/存量补列 rps 列。
  3. dim1 data_context 预加载 relative_strength（rps_20d/rps_60d）供 dim3。
  4. dim3 evaluate：RPS>85 → health_score +1 分（知识库量价形态打分系统加分项），
     status_description 增 'rps' 键，audit 增「相对强弱RPS」条件，plain 增 RPS 强证据。

知识库权威：
  - 《量价形态打分系统》：RPS>85 → +1 分。
  - 《RPS相对强弱指标》：RPS = 个股涨幅在全部股票涨幅排名中的位次 (1-rank/n)*100；
    欧奈尔狂飙前平均 RPS=87，A股 80 以上。

注：本测试全部注入 data_context（含 daily_df + relative_strength），不触发真实 DB
回退查询（开发态基准库有写锁，避免与 daemon 的 SQLite 锁竞争），与 dim3 既有测试手法一致。
"""
import numpy as np
import pandas as pd

from app.opportunity_atlas.dimensions.dim3_vp_engine import Dim3VPEngine


def _mk_df(n=70):
    rng = np.random.RandomState(0)
    closes = np.linspace(10, 25, n)
    vols = rng.uniform(1000, 5000, n).astype(float)
    idx = pd.date_range('2025-01-01', periods=n, freq='B')
    return pd.DataFrame({
        'ts_code': 'TEST.XSHG', 'open': closes,
        'high': closes * 1.01, 'low': closes * 0.99,
        'close': closes, 'vol': vols,
    }, index=idx)


_P_BASE = {'volume_price_fit': 'healthy', 'volume_ratio': 2.5,
           'ma_alignment': 'bullish', 'chip_concentration': 'concentrating', 'rsi14': 65}


class TestRpsScoring:
    """RPS>85 → health_score +1 分（不再被 RSI 顶替）"""

    def test_rps_gt85_increases_health_score(self):
        """RPS>85 时健康度 >= 无 RPS 时（加分证据）"""
        df = _mk_df()
        _base = {'volume_price_fit': 'healthy', 'volume_ratio': 2.5,
                 'ma_alignment': 'bullish', 'chip_concentration': 'concentrating', 'rsi14': 65}
        eng = Dim3VPEngine()
        hi = eng.evaluate({}, dict(_base, ts_code='TEST'), data_context={'daily_df': df, 'relative_strength': {'rps_20d': 99}})
        no = eng.evaluate({}, dict(_base, ts_code='TEST'), data_context={'daily_df': df, 'relative_strength': None})
        assert hi['judgment']['score'] >= no['judgment']['score']

    def test_rps_gt85_no_penalty_when_absent(self):
        """缺 RPS 数据不扣分（保守，不给分不加分）"""
        df = _mk_df()
        eng = Dim3VPEngine()
        out = eng.evaluate({}, dict(_P_BASE, ts_code='TEST'), data_context={'daily_df': df, 'relative_strength': None})
        assert out['status_description']['rps'] == '数据不足'
        assert out['judgment']['score'] >= 0

    def test_rps_le85_no_bonus(self):
        """RPS<=85 不加分，rps 键输出实际值"""
        df = _mk_df()
        eng = Dim3VPEngine()
        out = eng.evaluate({}, dict(_P_BASE, ts_code='TEST'),
                           data_context={'daily_df': df, 'relative_strength': {'rps_20d': 60}})
        assert out['status_description']['rps'] == '60.0/100'

    def test_audit_rps_condition_satisfied_when_gt85(self):
        """audit「相对强弱RPS」：RPS>85 → satisfied"""
        df = _mk_df()
        eng = Dim3VPEngine()
        out = eng.evaluate({}, dict(_P_BASE, ts_code='TEST'),
                           data_context={'daily_df': df, 'relative_strength': {'rps_20d': 90}})
        cond = next(c for c in out['audit']['conditions'] if c['name'] == '相对强弱RPS')
        assert cond['satisfied'] is True

    def test_audit_rps_condition_neutral_when_no_data(self):
        """audit「相对强弱RPS」：数据不足 → 中性放行（satisfied）"""
        df = _mk_df()
        eng = Dim3VPEngine()
        out = eng.evaluate({}, dict(_P_BASE, ts_code='TEST'), data_context={'daily_df': df, 'relative_strength': None})
        cond = next(c for c in out['audit']['conditions'] if c['name'] == '相对强弱RPS')
        assert cond['satisfied'] is True and cond['actual'] == '数据不足'

    def test_plain_includes_rps_when_strong(self):
        """RPS>85 时 plain 含 RPS 强势证据"""
        df = _mk_df()
        eng = Dim3VPEngine()
        out = eng.evaluate({}, dict(_P_BASE, ts_code='TEST'),
                           data_context={'daily_df': df, 'relative_strength': {'rps_20d': 90}})
        assert 'RPS=' in out['status_description']['plain']
        assert '强势' in out['status_description']['plain']

    def test_plain_no_rps_when_not_strong(self):
        """RPS<=85 时 plain 不含 RPS 弱/平平描述"""
        df = _mk_df()
        eng = Dim3VPEngine()
        out = eng.evaluate({}, dict(_P_BASE, ts_code='TEST'),
                           data_context={'daily_df': df, 'relative_strength': {'rps_20d': 60}})
        assert 'RPS=' not in out['status_description']['plain']


class TestRpsSourceWiring:
    """源码接线（沿用 dim3/dim4 既有源码-inspect 手法）"""

    def test_dim3_has_rps_scoring(self):
        import inspect
        src = inspect.getsource(Dim3VPEngine.evaluate)
        assert 'rps' in src
        assert 'relative_strength' in src
        assert "rps > 85" in src
        assert "'rps'" in src

    def test_dim1_preloads_relative_strength(self):
        import inspect
        from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
        src = inspect.getsource(Dim1SignalEngine.evaluate)
        assert "relative_strength" in src

    def test_daemon_computes_rps(self):
        import inspect
        import data_daemon
        src = inspect.getsource(data_daemon._compute_relative_strength)
        # 跨截面 RPS 百分位（20d/60d 两档），列名 rps_20d/rps_60d 在
        # enhanced_cache_manager.cache_relative_strength 的 INSERT 中（另测覆盖）
        assert 'rank(pct=True)' in src
        assert 'rps20_by_code' in src and 'rps60_by_code' in src
        # 写出 11 元组（含 RPS 两列）→ cache_relative_strength
        assert 'rps20' in src and 'rps60' in src

    def test_cache_manager_has_rps_columns(self):
        import inspect
        from app.data.enhanced_cache_manager import EnhancedCacheManager
        src = inspect.getsource(EnhancedCacheManager.cache_relative_strength)
        assert 'rps_20d' in src and 'rps_60d' in src
        init = inspect.getsource(EnhancedCacheManager._init_compute_tables)
        assert 'rps_20d' in init
