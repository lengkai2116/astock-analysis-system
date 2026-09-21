"""464号批次1测试：dim4 数据层六项硬问题修复锁定（445 冻结边界内直接实施）

覆盖（按依赖序）：
  TestMarginRatioColumns      —— ① 464-6 calc_margin_ratio 列名对齐（rzye + daily_basic circ_mv）
  TestCrowdingThreeDim        —— ② 464-6 evaluate 3 维制（融资维恢复真实参与 + valid_signals 订正）
  TestAnalyzeFundFlowWiring   —— ③ 464-9 _analyze_fund_flow 优先 data_context.moneyflow_df
  TestEvaluateNoSilentSwallow —— ④ 464-7 evaluate 异常改 logger.warning（不再静默吞）
  TestAssessSignalThirdSell   —— ⑤ 464-16 _assess_signal 补 third_sell（三卖不再被吞）
  TestDimFundUnit             —— ⑥ 464-15 _dim_fund net_lg_5d 万元→亿（÷1e4）
  TestFundFlowDualSource      —— ⑦ 464-8 tags 侧对称补 5d_outflow（framework + dim4 双份同步）

实证背景（2026-09-21 只读直连 market_cache.db）：
  margin_cache 列 = ts_code/trade_date/rzye(元)/rzmje/rqmcl/rzrqye/rqyl/rqchl；
  daily_basic_cache.circ_mv 单位万元（茅台 1.5715e8 万 ≈ 1.57 万亿）；
  moneyflow_cache.net_lg_amount 单位万元（茅台单日 -7989 万）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import logging

import numpy as np
import pandas as pd
import pytest
from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import (
    CrowdingFactor,
    Dim4ChipFundEngine,
    PhaseDetectionEngine,
    _assess_signal,
)


def _mk_df(n: int = 60) -> pd.DataFrame:
    dates = pd.date_range('2026-01-01', periods=n, freq='B')
    return pd.DataFrame({
        'trade_date': dates.strftime('%Y-%m-%d'),
        'open': 10.0, 'high': 11.0, 'low': 9.5, 'close': 10.5,
        'vol': 1_000_000, 'amount': 10_000_000,
    })


def _mk_outflow_moneyflow() -> pd.DataFrame:
    """5 日大单净流出（净额<0 且 5 日中≥3 日净流出）"""
    return pd.DataFrame({'net_lg_amount': [-100.0, -200.0, -150.0, -80.0, -50.0]})


class TestMarginRatioColumns:
    """464-6：calc_margin_ratio 列名对齐——rzye（融资余额）+ daily_basic circ_mv（流通市值）

    修复前：白名单 marge_balance/融资余额/marge/balance 对 margin_cache 实际列（rzye）恒不命中，
    circ_mv 在 margin_cache 中根本不存在 → 恒 None → 融资分项恒死（crowding 恒 MODERATE 0.5）。
    """

    def test_ratio_from_rzye_and_daily_basic(self):
        """rzye(元) + daily_basic circ_mv(万元) → 比例正确（茅台约 1.09%）"""
        cf = CrowdingFactor()
        margin_df = pd.DataFrame({
            'trade_date': ['2026-09-18', '2026-09-17'],
            'rzye': [1.7101602421e10, 1.7186171706e10],
        })
        basic_df = pd.DataFrame({
            'trade_date': ['2026-09-18', '2026-09-17'],
            'circ_mv': [1.571502580992e8, 1.583828385568e8],  # 万元
        })
        ratio = cf.calc_margin_ratio(
            '600519.SH',
            market_context={'margin_df': margin_df, 'daily_basic_df': basic_df},
        )
        assert ratio is not None
        # 1.71016e10 / (1.5715e8 * 1e4) ≈ 0.01088 → 1.09%（适中区间 0.01~0.05）
        assert abs(ratio - 0.01088) < 1e-4, ratio

    def test_ratio_high_threshold_reachable(self):
        """高融资占比（>5%）→ ratio 触发 high 判定（此前融资维不可达 HIGH）"""
        cf = CrowdingFactor()
        margin_df = pd.DataFrame({
            'trade_date': ['2026-09-18'],
            'rzye': [1.0e10],  # 100 亿元
        })
        basic_df = pd.DataFrame({
            'trade_date': ['2026-09-18'],
            'circ_mv': [1.0e7],  # 1000 万元 → 占比 100%
        })
        ratio = cf.calc_margin_ratio(
            '600519.SH',
            market_context={'margin_df': margin_df, 'daily_basic_df': basic_df},
        )
        assert ratio is not None and ratio > 0.05

    def test_uses_daily_basic_from_context_not_dm(self, monkeypatch):
        """daily_basic_df 由 data_context 提供时，不触碰 DataManager（锁脆弱路径）"""
        boom_calls = {'n': 0}

        class _BoomDM:
            def __init__(self, *a, **k):
                boom_calls['n'] += 1
                raise AssertionError('不应触碰 DataManager')

        monkeypatch.setattr('app.data.DataManager', _BoomDM)
        cf = CrowdingFactor()
        margin_df = pd.DataFrame({'trade_date': ['2026-09-18'], 'rzye': [1.0e10]})
        basic_df = pd.DataFrame({'trade_date': ['2026-09-18'], 'circ_mv': [1.0e7]})
        ratio = cf.calc_margin_ratio(
            '600519.SH',
            market_context={'margin_df': margin_df, 'daily_basic_df': basic_df},
        )
        assert ratio is not None
        assert boom_calls['n'] == 0

    def test_date_mismatch_falls_back_latest_basic(self):
        """融资最新日与 daily_basic 无精确匹配 → 回退 daily_basic 最新一行 circ_mv"""
        cf = CrowdingFactor()
        margin_df = pd.DataFrame({'trade_date': ['2026-09-15'], 'rzye': [1.7101602421e10]})
        basic_df = pd.DataFrame({
            'trade_date': ['2026-09-18', '2026-09-17'],
            'circ_mv': [1.571502580992e8, 1.583828385568e8],
        })
        ratio = cf.calc_margin_ratio(
            '600519.SH',
            market_context={'margin_df': margin_df, 'daily_basic_df': basic_df},
        )
        assert ratio is not None
        assert abs(ratio - 0.01088) < 1e-4, ratio

    def test_no_margin_data_returns_none(self, monkeypatch):
        """margin_df 缺失且缓存/实时均无 → None（融资分项保持"不可用"，不误报）"""

        class _EmptyDM:
            def get_cached_margin(self, *a, **k):
                return pd.DataFrame()

            def get_cached_daily_basic(self, *a, **k):
                return pd.DataFrame()

        monkeypatch.setattr('app.data.DataManager', lambda *a, **k: _EmptyDM())
        cf = CrowdingFactor()
        assert cf.calc_margin_ratio('600519.SH', market_context={}) is None


class TestCrowdingThreeDim:
    """464-6：evaluate 订正 3 维制——融资维真实参与后 HIGH/LOW 可达，valid_signals 按数据计"""

    def test_high_crowding_reachable_with_margin(self):
        """融资占比高 + 换手高 + 波动压缩 → HIGH_CROWDING（修复前融资维死后 2/2 制不可达）"""
        cf = CrowdingFactor()
        # 波动率压缩：前期波动、后期走平 → 当前布林带宽处历史低分位
        close = list(np.linspace(10.0, 14.0, 60)) + [14.0] * 20
        df = pd.DataFrame({'trade_date': pd.date_range('2026-01-01', periods=80, freq='B').strftime('%Y-%m-%d'),
                           'open': close, 'high': [c + 0.1 for c in close],
                           'low': [c - 0.1 for c in close], 'close': close,
                           'vol': 1_000_000, 'amount': 10_000_000})
        margin_df = pd.DataFrame({'trade_date': ['2026-09-18'], 'rzye': [1.0e10]})
        basic_df = pd.DataFrame({'trade_date': ['2026-09-18'], 'circ_mv': [1.0e7]})
        turnover = pd.Series([2.0] * 20 + [4.0])  # HIGH_TURNOVER
        mc = {'margin_df': margin_df, 'daily_basic_df': basic_df, 'turnover_data': turnover}
        out = cf.evaluate('600519.SH', df, market_context=mc)
        assert out['crowding_level'] == CrowdingFactor.HIGH_CROWDING, out
        assert out['crowding_score'] > 0.5
        assert out['details']['valid_signals'] == 3, out['details']

    def test_valid_signals_counts_only_data_backed_dims(self, monkeypatch):
        """融资数据缺失 + 无换手序列 → valid_signals=1（此前恒计 2）——3 维制锁定"""

        class _EmptyDM:
            def get_cached_margin(self, *a, **k):
                return pd.DataFrame()

            def get_cached_daily_basic(self, *a, **k):
                return pd.DataFrame()

        monkeypatch.setattr('app.data.DataManager', lambda *a, **k: _EmptyDM())
        cf = CrowdingFactor()
        df = _mk_df(60)  # 无换手列
        out = cf.evaluate('600519.SH', df, market_context={})  # 无 margin / 无 daily_basic
        assert out['details']['valid_signals'] == 1, out['details']
        assert out['crowding_level'] == CrowdingFactor.MODERATE

    def test_short_df_volatility_not_valid(self):
        """df 不足 60 根 → 波动维不计入 valid_signals"""
        cf = CrowdingFactor()
        df = _mk_df(40)  # < 60
        margin_df = pd.DataFrame({'trade_date': ['2026-09-18'], 'rzye': [1.0e10]})
        basic_df = pd.DataFrame({'trade_date': ['2026-09-18'], 'circ_mv': [1.0e7]})
        turnover = pd.Series([2.0] * 20 + [4.0])
        mc = {'margin_df': margin_df, 'daily_basic_df': basic_df, 'turnover_data': turnover}
        out = cf.evaluate('600519.SH', df, market_context=mc)
        # 融资(1) + 换手(1) 有效，波动(short df)不计 → valid=2
        assert out['details']['valid_signals'] == 2, out['details']


class TestAnalyzeFundFlowWiring:
    """464-9：_analyze_fund_flow 优先 data_context.moneyflow_df（不再 ECM 直读，锁脆弱）"""

    def test_uses_moneyflow_df_not_dm(self):
        """moneyflow_df 传入时，不触碰 DataManager 直读（同 443/dim2 接线）"""

        class _FakeDM:
            def get_cached_moneyflow(self, *a, **k):
                raise AssertionError('不应回退 DM 直读')

        pde = PhaseDetectionEngine(data_manager=_FakeDM())
        mf = _mk_outflow_moneyflow()
        assert pde._analyze_fund_flow('600519.SH', moneyflow_df=mf) == '5d_outflow'

    def test_empty_moneyflow_falls_back_none(self):
        """moneyflow_df 空 → 回退 DM 直读（此处假 DM 抛错被吞）→ 'none'"""

        class _FakeDM:
            def get_cached_moneyflow(self, *a, **k):
                return pd.DataFrame()

        pde = PhaseDetectionEngine(data_manager=_FakeDM())
        assert pde._analyze_fund_flow('600519.SH', moneyflow_df=pd.DataFrame()) == 'none'

    def test_compute_tags_call_site_passes_moneyflow_df(self):
        """compute_tags 内 _analyze_fund_flow 调用已透传 moneyflow_df（源码锁定）"""
        import inspect
        src = inspect.getsource(PhaseDetectionEngine.compute_tags)
        assert '_analyze_fund_flow(ts_code, moneyflow_df)' in src, \
            'compute_tags 必须把 data_context.moneyflow_df 透传给 _analyze_fund_flow'


class TestEvaluateNoSilentSwallow:
    """464-7：evaluate 两处异常不再静默吞（PhaseDetectionEngine / CrowdingFactor）"""

    def test_crowding_exception_logs_warning(self, monkeypatch, caplog):
        df = _mk_df(60)

        class _FakeDM:
            cache = None

        monkeypatch.setattr(Dim4ChipFundEngine, '_get_dm', lambda self: _FakeDM())
        monkeypatch.setattr(
            PhaseDetectionEngine, 'compute_tags',
            staticmethod(lambda *a, **k: {
                'main_force_phase': 'lifting', 'phase_confidence': 0.7,
                'fund_flow': 'inflow', 'trend_alignment': 'up_aligned',
                'price_position': 'mid_zone',
            }))

        def _boom_crowding(self, *a, **k):
            raise RuntimeError('拥挤度计算崩溃')

        monkeypatch.setattr(CrowdingFactor, 'evaluate', _boom_crowding)
        with caplog.at_level(logging.WARNING, logger='app.opportunity_atlas.dimensions.dim4_chip_fund_engine'):
            engine = Dim4ChipFundEngine()
            res = engine.evaluate({}, {'ts_code': '000001.SZ'},
                                  data_context={'daily_df': df, 'daily_basic_df': _mk_df(30)})
        assert res['status_description']['crowding'].startswith('拥挤度=unknown')
        assert any('CrowdingFactor' in r.message for r in caplog.records), \
            [r.message for r in caplog.records]

    def test_phase_engine_exception_logs_warning(self, monkeypatch, caplog):
        df = _mk_df(60)

        class _FakeDM:
            cache = None

        monkeypatch.setattr(Dim4ChipFundEngine, '_get_dm', lambda self: _FakeDM())
        monkeypatch.setattr(
            CrowdingFactor, 'evaluate',
            lambda self, *a, **k: {
                'crowding_level': 'MODERATE_CROWDING', 'crowding_score': 0.5,
                'risk_advice': '拥挤度适中',
            })

        def _boom_compute(self, *a, **k):
            raise RuntimeError('阶段分析崩溃')

        monkeypatch.setattr(PhaseDetectionEngine, 'compute_tags', _boom_compute)
        with caplog.at_level(logging.WARNING, logger='app.opportunity_atlas.dimensions.dim4_chip_fund_engine'):
            engine = Dim4ChipFundEngine()
            res = engine.evaluate({}, {'ts_code': '000001.SZ'},
                                  data_context={'daily_df': df})
        # 阶段落 tags 兜底（不抛给上层），但日志有 warning
        assert res['judgment']['phase'] in ('unknown', 'building', 'lifting', 'distributing', 'washing', 'support')
        assert any('PhaseDetectionEngine' in r.message for r in caplog.records), \
            [r.message for r in caplog.records]


class TestAssessSignalThirdSell:
    """464-16：_assess_signal 补 third_sell——三卖信号不再被吞为"无明确筹码信号" """

    def test_third_sell_mapped(self):
        out = _assess_signal({'buy_sell_point': 'third_sell'})
        assert out['detail'] == '三卖信号'
        assert out['signal'] == 'third_sell'

    def test_other_sells_unchanged(self):
        assert _assess_signal({'buy_sell_point': 'first_sell'})['signal'] == 'first_sell'
        assert _assess_signal({'buy_sell_point': 'second_sell'})['signal'] == 'second_sell'
        assert _assess_signal({'buy_sell_point': 'third_buy'})['signal'] == 'third_buy'

    def test_none_unchanged(self):
        assert _assess_signal({'buy_sell_point': 'zzz'})['signal'] == 'none'
        assert _assess_signal({})['signal'] == 'none'


class TestDimFundUnit:
    """464-15：_dim_fund net_lg_5d 单位订正——万元按 ÷1e4 归一到亿（原 /1e8 按元 → strength≈0）"""

    def test_inflow_strength_realistic(self):
        pde = PhaseDetectionEngine()
        # 茅台实测 net_lg_5d=-16037（万元）→ 1.6037 亿 → strength=min(1, 1.6037)=1.0
        out = pde._dim_fund('5d_inflow', '600519.SH', {'net_lg_5d': 16037.0})
        assert out['lifting'] == pytest.approx(0.8), out  # 0.3 + 0.5*1.0
        assert out['building'] == 0.2

    def test_outflow_strength_realistic(self):
        pde = PhaseDetectionEngine()
        out = pde._dim_fund('5d_outflow', '600519.SH', {'net_lg_5d': -16037.0})
        assert out['distributing'] == pytest.approx(0.8), out

    def test_small_net_lg_not_saturated(self):
        pde = PhaseDetectionEngine()
        # 1000 万 = 0.1 亿 → strength=0.1 → lifting=0.35
        out = pde._dim_fund('5d_inflow', '600519.SH', {'net_lg_5d': 1000.0})
        assert out['lifting'] == pytest.approx(0.35), out

    def test_mixed_none_no_vote(self):
        pde = PhaseDetectionEngine()
        assert pde._dim_fund('mixed', '600519.SH', {'net_lg_5d': 5000.0}) == {}


class TestFundFlowDualSource:
    """464-8：tags 侧对称补 5d_outflow（_score_moneyflow 打分单向 → 净流出恒落低分）"""

    @pytest.fixture
    def outflow_dm(self):
        class _FakeDM:
            def get_cached_moneyflow(self, *a, **k):
                return _mk_outflow_moneyflow()

            def get_cached_daily_data(self, *a, **k):
                return pd.DataFrame()

        return _FakeDM()

    def test_framework_tags_produce_outflow(self, monkeypatch, outflow_dm):
        """framework MainForceScorer：score<1 + 5日净流出 → fund_flow='5d_outflow'"""
        from app.engine.framework.chip_strategy import MainForceScorer as FWScorer
        scorer = object.__new__(FWScorer)
        scorer._dm = outflow_dm
        monkeypatch.setattr(FWScorer, '_score_moneyflow', lambda self, symbol: 0.5)
        monkeypatch.setattr(FWScorer, '_score_lhb', lambda self, symbol, df: 0.0)
        tags = scorer.get_tags('000001.SZ')
        assert tags.get('fund_flow') == '5d_outflow', tags

    def test_framework_tags_strong_inflow_unchanged(self, monkeypatch, outflow_dm):
        """score≥2 → 仍直接判 5d_inflow（不打流出判定）"""
        from app.engine.framework.chip_strategy import MainForceScorer as FWScorer
        scorer = object.__new__(FWScorer)
        scorer._dm = outflow_dm
        monkeypatch.setattr(FWScorer, '_score_moneyflow', lambda self, symbol: 2.5)
        monkeypatch.setattr(FWScorer, '_score_lhb', lambda self, symbol, df: 0.0)
        tags = scorer.get_tags('000001.SZ')
        assert tags.get('fund_flow') == '5d_inflow', tags

    def test_dim4_tags_produce_outflow(self, monkeypatch, outflow_dm):
        """dim4 内嵌 MainForceScorer（双份同步）：同样补 5d_outflow"""
        from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import (
            MainForceScorer as D4Scorer,
        )
        scorer = object.__new__(D4Scorer)
        scorer._data_context = {'moneyflow_df': _mk_outflow_moneyflow(),
                                'daily_df': _mk_df(30)}
        scorer._dm = outflow_dm
        monkeypatch.setattr(D4Scorer, '_score_moneyflow', lambda self, symbol: 0.5)
        monkeypatch.setattr(D4Scorer, '_score_lhb', lambda self, symbol, df: 0.0)
        tags = scorer.get_tags('000001.SZ')
        assert tags.get('fund_flow') == '5d_outflow', tags

    def test_outflow_requires_3_neg_days(self, outflow_dm):
        """净额<0 但 5 日中仅 2 日净流出 → 不算强流出（同 _analyze_fund_flow 口径）"""
        from app.engine.framework.chip_strategy import MainForceScorer as FWScorer
        scorer = object.__new__(FWScorer)
        scorer._dm = outflow_dm

        class _WeakOut:
            def get_cached_moneyflow(self, *a, **k):
                # 净额<0 但 5 日中仅 2 日净流出（-100/-200，其余 3 日为正）→ 不算强流出
                return pd.DataFrame({'net_lg_amount': [-100.0, -200.0, 50.0, 60.0, 30.0]})

        scorer._dm = _WeakOut()
        assert not scorer._moneyflow_outflow_5d('000001.SZ')
