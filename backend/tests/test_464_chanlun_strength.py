# -*- coding: utf-8 -*-
"""464号：chanlun_strength 取键修复（恒 0.5 bug）

背景：ChanlunScorer.score 返回键为 'score'（0-100，内部 +50 归一 clamp），
原 dim2 evaluate 取 .get('strength', 0.5) —— 返回值无此键 → 恒回退 0.5，
真实结构强度从未接入，continuous_value 恒 0.5（前端"置信50%"）。

本测试验证：
- dim2 evaluate：score 真实接入 → chanlun_strength=0-100、continuous_value=strength/100（0-1）
- 无缠论/异常路径：中性分 50 → continuous_value=0.5（保持原语义）
- dim_adapter 加权：chanlun_strength(0-100) 归一为 0-1 后参与 0.4/0.4/0.2 加权
  （原混单位：0-100 与 cross/cont 的 0-1 直接相加会爆表）
"""
import numpy as np
import pandas as pd
from unittest import mock

from app.opportunity_atlas.dimensions import dim2_structure_engine
from app.opportunity_atlas.dimensions.dim2_structure_engine import ChanlunAnalyzer, Dim2StructureEngine
from app.opportunity_atlas.dim_adapter import convert_to_factors


def _mk_df(n=90):
    closes = np.linspace(10, 20, n) + np.sin(np.linspace(0, 8, n)) * 0.5
    idx = pd.date_range('2025-01-01', periods=n, freq='B')
    return pd.DataFrame({
        'ts_code': 'T.XSHG', 'open': closes, 'high': closes * 1.01,
        'low': closes * 0.99, 'close': closes, 'vol': [1e5] * n, 'amount': [3e5] * n,
    }, index=idx)


def _mk_analyzer_result(trend='up'):
    return {
        'trend': trend,
        'zhongshu': [],
        'divergence': None,
        'buy_points': [],
        'sell_points': [],
        'theorem_check': {'summary': {'overall_score': 0.7}},
    }


_DEFAULT = object()


def _evaluate(score_result=None, analyze=_DEFAULT):
    """在 patch analyze + patch ChanlunScorer.structure_health_score 下跑 evaluate。

    score_result=None → 健康度 mock 返回 {'score': 72}（正常值）；
    analyze=_DEFAULT → analyze mock 返回 _mk_analyzer_result()；analyze=None → 无缠论。
    """
    df = _mk_df()
    eng = Dim2StructureEngine()
    tags = {'ts_code': 'T.XSHG', 'ma_alignment': 'bullish',
            'chip_concentration': 'concentrating', 'profit_ratio': 0.5,
            'indicator_status': 'ma=bullish', 'rsi': 70}
    _analyze_val = _mk_analyzer_result() if analyze is _DEFAULT else analyze
    _score_val = {'score': 72, 'details': [], 'recommendation': 'BUY'} \
        if score_result is None else score_result
    with mock.patch.object(ChanlunAnalyzer, 'analyze', return_value=_analyze_val):
        with mock.patch.object(dim2_structure_engine.ChanlunScorer,
                               'structure_health_score', return_value=_score_val):
            return eng.evaluate({}, tags, data_context={'daily_df': df})


class TestDim2StrengthRealtime:
    """score 真实接入（0-100 → continuous_value 0-1）。"""

    def test_score_72(self):
        out = _evaluate({'score': 72, 'details': [], 'recommendation': 'BUY'})
        sd, jg = out['status_description'], out['judgment']
        assert sd['chanlun_strength'] == 72.0
        assert jg['continuous_value'] == 0.72

    def test_score_100(self):
        out = _evaluate({'score': 100, 'details': [], 'recommendation': 'STRONG_BUY'})
        assert out['status_description']['chanlun_strength'] == 100.0
        assert out['judgment']['continuous_value'] == 1.0

    def test_score_0(self):
        out = _evaluate({'score': 0, 'details': [], 'recommendation': 'HOLD'})
        assert out['status_description']['chanlun_strength'] == 0.0
        assert out['judgment']['continuous_value'] == 0.0

    def test_score_mid_range_value(self):
        out = _evaluate({'score': 37, 'details': [], 'recommendation': 'HOLD'})
        assert out['status_description']['chanlun_strength'] == 37.0
        assert out['judgment']['continuous_value'] == 0.37

    def test_judgment_structure_unaffected(self):
        out = _evaluate({'score': 72, 'details': [], 'recommendation': 'BUY'})
        assert out['judgment']['structure'] == '上升'
        assert out['judgment']['light'] == 'green'
        assert out['judgment']['overall_direction'] == 1


class TestDim2MarketContextWired:
    """466号 ③④：structure_health_score 传 market_context（换手/大盘环境微调生效）。

    注：健康度不传 latest_close（价格匹配惩罚是 score() 买卖点信号语义，与结构健康度无关）。
    """

    @staticmethod
    def _capture_evaluate(data_context):
        df = _mk_df()
        eng = Dim2StructureEngine()
        captured = {'calls': []}

        def _fake_score(*args, **kwargs):
            captured['calls'].append((args, kwargs))
            return {'score': 66, 'details': [], 'recommendation': 'BUY'}

        tags = {'ts_code': 'T.XSHG'}
        dc = {'daily_df': df}
        dc.update(data_context or {})
        with mock.patch.object(ChanlunAnalyzer, 'analyze', return_value=_mk_analyzer_result()):
            with mock.patch.object(dim2_structure_engine.ChanlunScorer,
                                   'structure_health_score', side_effect=_fake_score):
                out = eng.evaluate({}, tags, data_context=dc)
        return out, captured

    def test_market_context_passed(self):
        dbb = pd.DataFrame({
            'trade_date': pd.date_range('2025-01-01', periods=3, freq='B'),
            'turnover_rate': [1.0, 5.0, 12.0],
        })
        mf = pd.DataFrame({
            'trade_date': pd.date_range('2025-01-01', periods=3, freq='B'),
            'net_lg_amount': [1e6, -5e5, 8e7],
        })
        df = _mk_df()
        out, captured = self._capture_evaluate({'daily_basic_df': dbb, 'moneyflow_df': mf})
        _args, _kwargs = captured['calls'][0]       # 第一次 = dim2 evaluate 第 4 步
        assert 'latest_close' not in _kwargs          # 健康度不传价格匹配（score 语义）
        mc = _kwargs['market_context']
        assert mc['turnover_rate'] == 12.0          # 最新交易日换手率（健康度微调用）
        assert out['status_description']['chanlun_strength'] == 66.0
        assert out['status_description']['structure_health_score'] == 66.0
        assert out['judgment']['continuous_value'] == 0.66

    def test_missing_market_sources_ok(self):
        """data_context 无 daily_basic/moneyflow → market_context 缺省不炸，健康度正常。"""
        df = _mk_df()
        out, captured = self._capture_evaluate(None)
        _args, _kwargs = captured['calls'][0]
        mc = _kwargs.get('market_context')
        assert mc is None or mc == {} or 'turnover_rate' not in mc
        assert out['status_description']['chanlun_strength'] == 66.0

    def test_dirty_market_values_skipped(self):
        """脏值（NaN）被 dropna 剔除，不产键。"""
        dbb = pd.DataFrame({
            'trade_date': pd.date_range('2025-01-01', periods=3, freq='B'),
            'turnover_rate': [float('nan'), float('nan'), float('nan')],
        })
        mf = pd.DataFrame({
            'trade_date': pd.date_range('2025-01-01', periods=3, freq='B'),
            'net_lg_amount': [None, None, None],
        })
        out, captured = self._capture_evaluate({'daily_basic_df': dbb, 'moneyflow_df': mf})
        _args, _kwargs = captured['calls'][0]
        mc = _kwargs.get('market_context')
        assert mc is None or mc == {}
        assert out['status_description']['chanlun_strength'] == 66.0


class TestDim2StrengthFallback:
    """无缠论/异常路径：中性分 50（continuous_value=0.5 保持原语义）。"""

    def test_no_chanlun(self):
        out = _evaluate(analyze=None)
        assert out['status_description']['chanlun_strength'] == 50.0
        assert out['judgment']['continuous_value'] == 0.5

    def test_analyze_raises(self):
        df = _mk_df()
        eng = Dim2StructureEngine()
        with mock.patch.object(ChanlunAnalyzer, 'analyze',
                               side_effect=RuntimeError('boom')):
            out = eng.evaluate({}, {'ts_code': 'T.XSHG'}, data_context={'daily_df': df})
        assert out['status_description']['chanlun_strength'] == 50.0
        assert out['judgment']['continuous_value'] == 0.5

    def test_score_raises(self):
        df = _mk_df()
        eng = Dim2StructureEngine()
        with mock.patch.object(ChanlunAnalyzer, 'analyze',
                               return_value=_mk_analyzer_result()):
            with mock.patch.object(dim2_structure_engine.ChanlunScorer,
                                   'structure_health_score',
                                   side_effect=RuntimeError('boom')):
                out = eng.evaluate({}, {'ts_code': 'T.XSHG'},
                                   data_context={'daily_df': df})
        assert out['status_description']['chanlun_strength'] == 50.0
        assert out['judgment']['continuous_value'] == 0.5


class TestDimAdapterStrength:
    """dim_adapter 加权归一：chanlun_strength(0-100) 归一 0-1 后参与 0.4/0.4/0.2。"""

    @staticmethod
    def _mk_structure(chanlun_strength, cont_val, cross=0.5):
        return {'structure': {
            'judgment': {'overall_direction': 1, 'continuous_value': cont_val},
            'status_description': {
                'chanlun_strength': chanlun_strength,
                'level_cross_score': cross,
                'trend_structure_signal': '',
                'chanlun_phase': '健康',
                'buy_sell_points_detail': [],
                'stage_name': '上升',
                'divergence': '',
            },
        }}

    def test_realtime_strength_normalized(self):
        # 0.4*0.72 + 0.4*0.5 + 0.2*0.72 = 0.632（chanlun_strength 72 → /100）
        fac = convert_to_factors(self._mk_structure(72.0, 0.72), {})
        assert abs(fac['structure']['strength'] - 0.632) < 1e-6

    def test_legacy_half_compat(self):
        # 旧数据恒 0.5（bug 产物）：<=1 视为 0-1 域不除 → 0.4*0.5+0.4*0.5+0.2*0.5=0.5
        fac = convert_to_factors(self._mk_structure(0.5, 0.5), {})
        assert abs(fac['structure']['strength'] - 0.5) < 1e-6

    def test_missing_strength_default(self):
        d = self._mk_structure(None, 0.5)
        del d['structure']['status_description']['chanlun_strength']
        fac = convert_to_factors(d, {})
        assert abs(fac['structure']['strength'] - 0.5) < 1e-6
