"""507号批次6：死代码/防御/性能清理验证（#S13/#S14/#S25 + §五）

方案档：`002-方案存档/507-SIG板块OCR核查与处置.md` §四.5/§五/§七。

覆盖（拍板口径：补产键修复 / ecm 优先 / 删除已确认死副本 / 范围仅 §五+死副本）：
  #S14 dim4 ChipIndicators 补产 vol_status/cyqkl_status（对齐生效副本分档阈值）
       → TradingPhaseDetector 洗盘/拉升/出货评分分支恢复加分
  #S25 valuation_estimator.build_fcf_percentile ecm 优先（原恒用 self._get_dm().cache）
  死副本删除：dim4 内零实例化类（ChipPositionManager/ChipDistributionSignalGenerator/
       策略模型群/过滤器群/ChipRiskExecutor）已删；LIVE 类保留
  §五 死参数（build_audit maintenance / _assess_vs_zhongshu dims）、dim3 macd 死代码
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

_DIM4 = 'app.opportunity_atlas.dimensions.dim4_chip_fund_engine'


def _mk_kline(n=120, last_vol=None, base_vol=1000.0):
    """构造 n 行日线（前复权口径字段），最后一根量可指定（默认=base_vol）"""
    idx = pd.date_range('2026-01-01', periods=n, freq='B')
    df = pd.DataFrame({
        'open': np.linspace(10.0, 12.0, n),
        'high': np.linspace(10.2, 12.4, n),
        'low': np.linspace(9.8, 11.6, n),
        'close': np.linspace(10.1, 12.1, n),
        'vol': [base_vol] * n,
        'trade_date': [d.strftime('%Y-%m-%d') for d in idx],
    })
    if last_vol is not None:
        df.iloc[-1, df.columns.get_loc('vol')] = last_vol
    return df


def _mk_chip_bins(price=12.0):
    """简单筹码分布：3 档集中在现价附近"""
    step = 0.2
    return [
        {'price_bin': round(price - step, 2), 'chip_ratio': 0.3},
        {'price_bin': round(price, 2), 'chip_ratio': 0.4},
        {'price_bin': round(price + step, 2), 'chip_ratio': 0.3},
    ]


# ── #S14 补产键 ──────────────────────────────────────────

def test_s14_calculate_all_indicators_produces_status_keys():
    """dim4 ChipIndicators.calculate_all_indicators 产 vol_status/cyqkl_status"""
    from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import ChipIndicators

    inds = ChipIndicators()
    res = inds.calculate_all_indicators(_mk_chip_bins(), 12.0,
                                        kline_data=_mk_kline())
    assert 'cyqkl_status' in res, '缺 cyqkl_status 生产者'
    assert 'vol_status' in res, '缺 vol_status 生产者'
    assert res['vol_status'] in ('天量', '显著放量', '放量', '地量', '缩量', '正常')


def test_s14_vol_status_classify_thresholds():
    """_classify_vol_status 对齐生效副本 get_volume_status 阈值"""
    from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import ChipIndicators

    c = ChipIndicators()
    assert c._classify_vol_status(3.0) == '天量'
    assert c._classify_vol_status(2.0) == '显著放量'
    assert c._classify_vol_status(1.5) == '放量'
    assert c._classify_vol_status(0.3) == '地量'
    assert c._classify_vol_status(0.7) == '缩量'
    assert c._classify_vol_status(1.0) == '正常'


def test_s14_cyqkl_status_classify_thresholds():
    """_classify_cyqkl_status 对齐生效副本 get_cyqkl_status 阈值"""
    from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import ChipIndicators

    c = ChipIndicators()
    assert c._classify_cyqkl_status(5) == '弱'
    assert c._classify_cyqkl_status(20) == '中等'
    assert c._classify_cyqkl_status(45) == '强'
    assert c._classify_cyqkl_status(70) == '很强'
    assert c._classify_cyqkl_status(90) == '极强'


def test_s14_washing_score_recovers_on_vol_status():
    """_score_washing 在 vol_status='缩量' 时恢复 +2.0（原恒 0）"""
    from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import TradingPhaseDetector

    det = object.__new__(TradingPhaseDetector)
    base = det._score_washing(_mk_kline(), _mk_chip_bins(),
                              {'rsi': 40, 'asr': 40, 'ssrp': 0})
    with_vol = det._score_washing(_mk_kline(), _mk_chip_bins(),
                                  {'rsi': 40, 'asr': 40, 'ssrp': 0,
                                   'vol_status': '缩量'})
    assert with_vol >= base + 2.0, f'缩量分支未加分: base={base} with={with_vol}'


def test_s14_raising_score_recovers_on_status():
    """_score_raising 在 vol_status='放量'/cyqkl_status='强' 时恢复加分"""
    from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import TradingPhaseDetector

    det = object.__new__(TradingPhaseDetector)
    base = det._score_raising(_mk_kline(), _mk_chip_bins(),
                              {'ssrp': 0, 'rsi': 60})
    with_status = det._score_raising(
        _mk_kline(), _mk_chip_bins(),
        {'ssrp': 0, 'rsi': 60, 'vol_status': '放量', 'cyqkl_status': '强'})
    assert with_status >= base + 3.0, f'放量/cyqkl 分支未加分: base={base} with={with_status}'


# ── #S25 ecm 优先 ─────────────────────────────────────────

def test_s25_build_fcf_percentile_uses_ecm_when_given(monkeypatch):
    """build_fcf_percentile 传 ecm 时优先用 ecm（原恒用 self._get_dm().cache）"""
    from app.opportunity_atlas.valuation_estimator import ValuationEngine

    ve = ValuationEngine()
    calls = {'cache': None, 'dm': False}

    class _FakeCache:
        def _query_shard(self, *a, **k):
            calls['cache'] = 'ecm'
            import pandas as _pd
            return _pd.DataFrame(columns=['ts_code'])

        def get_cached_daily_basic(self, code):
            return None

        def get_cached_cashflow(self, code):
            return None

    class _FakeDM:
        cache = object()  # 若误用 self._get_dm().cache 会在 _query_shard 上抛 AttributeError

        def get_cached_daily_basic(self, code):
            return None

        def get_cached_cashflow(self, code):
            return None

    monkeypatch.setattr(ve, '_get_dm', lambda: _FakeDM())
    ve.build_fcf_percentile(_FakeCache())
    assert calls['cache'] == 'ecm', '未使用传入 ecm（仍走 self._get_dm().cache）'


def test_s25_build_fcf_percentile_falls_back_to_dm_without_ecm(monkeypatch):
    """不传 ecm 时回退 self._get_dm().cache（保持原语义）"""
    from app.opportunity_atlas.valuation_estimator import ValuationEngine

    ve = ValuationEngine()
    calls = {'cache': None}

    class _FakeCache:
        def _query_shard(self, *a, **k):
            calls['cache'] = 'dm'
            import pandas as _pd
            return _pd.DataFrame(columns=['ts_code'])

        def get_cached_daily_basic(self, code):
            return None

        def get_cached_cashflow(self, code):
            return None

    monkeypatch.setattr(ve, '_get_dm', lambda: type('DM', (), {'cache': _FakeCache()})())
    ve.build_fcf_percentile()
    assert calls['cache'] == 'dm'


# ── 死副本删除（本批核心） ───────────────────────────────

_DEAD_CLASSES = [
    'ChipPositionManager', 'ChipDistributionSignalGenerator',
    'ChipUniverseSelectionModel', 'ChipAlphaModel', 'ChipRiskManagementModel',
    'ChipScorer', 'MarketEnvironmentFilter', 'CircuitBreaker',
    'EligibilityFilter', 'LiquidityFilter', 'MarketCapAdapter',
    'ChipPreFilter', 'FinancialRiskFilter', 'ROCEIndicator', 'ChipRiskExecutor',
]

_LIVE_CLASSES = [
    'Dim4ChipFundEngine', 'PhaseDetectionEngine', 'TradingPhaseDetector',
    'MainForceScorer', 'CrowdingFactor', 'ChipIndicators',
]


@pytest.mark.parametrize('cls', _DEAD_CLASSES)
def test_dead_class_removed(cls):
    """零实例化死副本类已从 dim4 模块删除"""
    import importlib
    m = importlib.import_module(_DIM4)
    assert not hasattr(m, cls), f'{cls} 应已删除'


@pytest.mark.parametrize('cls', _LIVE_CLASSES)
def test_live_class_kept(cls):
    """LIVE 类保留（被 Dim4ChipFundEngine.evaluate / daemon 引用）"""
    import importlib
    m = importlib.import_module(_DIM4)
    assert hasattr(m, cls), f'{cls} 不应被删'


def test_dim4_module_line_count_shrunk():
    """dim4 死副本删除后文件显著缩减（6200+ → <3600 行）"""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'app', 'opportunity_atlas', 'dimensions',
                        'dim4_chip_fund_engine.py')
    n = sum(1 for _ in open(path, encoding='utf-8'))
    assert n < 3600, f'dim4 仍 {n} 行，死副本未删净'


# ── §五 死参数 / 死代码 ───────────────────────────────────

def test_dead_param_maintenance_removed_from_build_audit():
    """build_audit 不再接收 maintenance（原死参数）"""
    import inspect
    from app.opportunity_atlas.signal_analyzer import build_audit

    params = list(inspect.signature(build_audit).parameters)
    assert 'maintenance' not in params, params


def test_dead_param_dims_removed_from_assess_vs_zhongshu():
    """_assess_vs_zhongshu 不再接收 dims（原死参数）"""
    import inspect
    from app.opportunity_atlas.dimensions import dim2_structure_engine as d2

    params = list(inspect.signature(d2._assess_vs_zhongshu).parameters)
    assert 'dims' not in params, params


def test_dim3_macd_dead_code_removed():
    """dim3 内 _load_precomputed_macd/_MACD_PRECOMPUTED_CACHE 死代码已删"""
    import importlib
    m = importlib.import_module('app.opportunity_atlas.dimensions.dim3_vp_engine')
    assert not hasattr(m, '_load_precomputed_macd'), 'dim3 macd 死副本未删'
    assert not hasattr(m, '_MACD_PRECOMPUTED_CACHE'), 'dim3 macd 缓存未删'


def test_shared_vol_ratio_no_module_logger():
    """shared_vol_ratio 已删未用模块级 logger"""
    import importlib
    m = importlib.import_module('app.opportunity_atlas.dimensions.shared_vol_ratio')
    assert not hasattr(m, 'logger')
