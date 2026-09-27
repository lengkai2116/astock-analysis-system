"""488号 A1 单测：情绪温度 7 入参"因"透传（dim5 status_description['temperature_basis']
+ dim8 情绪温度话术「果（因）」形态）

覆盖（dim5 定稿 §七观察项③拍板「以 7 入参明细作因透传」）：
  - _fmt_temperature_basis：7 入参齐全/缺项标「无数据」/情绪周期修正后缀
  - evaluate 集成：data_context(emotion_ext/market_stats/margin_df/sector_heat) → basis 含各值；
    judgment 键集不变（445 冻结边界：只加「因」，不动「果」）
  - dim8 _compose_dim_text('emotion')：温度句带括号因；basis 缺则不产括号
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from unittest import mock

import numpy as np
import pandas as pd
from app.opportunity_atlas.dimensions import dim5_emotion_engine as dim5
from app.opportunity_atlas.dimensions.dim5_emotion_engine import (
    Dim5EmotionEngine,
    _fmt_temperature_basis,
)
from app.opportunity_atlas.dimensions.dim8_summary_engine import _compose_dim_text


def _mk_df(n=80):
    idx = pd.date_range('2025-01-01', periods=n, freq='B')
    closes = np.linspace(10, 20, n) + np.sin(np.linspace(0, 8, n)) * 0.5
    return pd.DataFrame({
        'ts_code': 'T.XSHG', 'open': closes, 'high': closes * 1.01,
        'low': closes * 0.99, 'close': closes, 'vol': [1e5] * n, 'amount': [3e5] * n,
    }, index=idx)


def _mk_margin_df():
    return pd.DataFrame({'rzye': [100.0, 100.5, 101.0, 102.0, 103.0]})


# ── _fmt_temperature_basis（纯函数）────────────────────────

class TestTemperatureBasis:

    def test_all_seven_inputs(self):
        """7 入参齐全：阶段(基温)/涨停/封板率/板块排名/量价/融资5日/广度(近似)"""
        s = _fmt_temperature_basis(
            'ferment', '发酵', 42, True, 63.4, 15, 'healthy', 0.03, 0.39,
            fast_score=0.79, slow_score=0.48)
        assert '阶段发酵(基温60)' in s          # PHASE_BASE_TEMP[ferment]=60
        assert '涨停42家' in s
        assert '封板率63%' in s
        assert '板块排名15' in s
        assert '量价健康' in s                  # vp_fit=healthy → 中文
        assert '融资5日+3.0%' in s
        assert '广度39%(MA20占比近似)' in s
        assert '情绪周期修正(快0.79×0.6+慢0.48×0.4)' in s

    def test_missing_data_marked(self):
        """缺数据项显式标「无数据」，不臆造（437 缺则降级）"""
        s = _fmt_temperature_basis(
            'neutral', '正常', 0, False, None, None, 'neutral', None, None)
        assert '涨停无数据' in s
        assert '封板率无数据' in s
        assert '板块排名无数据' in s
        assert '融资无数据' in s
        assert '广度无数据' in s
        assert '情绪周期修正' not in s          # 无 fast/slow → 不产修正后缀
        assert '阶段正常(基温50)' in s          # PHASE_BASE_TEMP[neutral]=50

    def test_zero_limit_up_vs_missing(self):
        """涨停 0 家（有数据）与「无数据」区分"""
        assert '涨停0家' in _fmt_temperature_basis(
            'ice', '冰点', 0, True, 50.0, None, 'neutral', None, None)
        assert '涨停无数据' in _fmt_temperature_basis(
            'ice', '冰点', 0, False, 50.0, None, 'neutral', None, None)


# ── evaluate 集成 ─────────────────────────────────────────

class TestEvaluateTemperatureBasis:

    def _run(self, data_context_extra=None):
        eng = Dim5EmotionEngine()
        qr = {'signal': 'NEUTRAL', 'confidence': 0.35, 'pass_count': 1,
              'indicators': {'fast_vol': False, 'fast_price': True, 'fast_mom': False,
                             'fast_breadth': False},
              'details': {'vol_ratio': 1.26, 'price_offset_pct': -1.1,
                          'mom_5d_pct': -1.99, 'amplitude_pct': 0.73}}
        sr = {'signal': 'BULLISH', 'confidence': 0.66,
              'details': {'erp': 3.5007, 'erp_signal': 'BULLISH'}}
        fq = {'quadrant': 'MM', 'description': '市场情绪中性', 'fast_score': 0.68,
              'slow_score': 0.72, 'weight_multiplier': 1.0,
              'details': {'ma20_ratio': 0.39, 'turnover_percentile': 0.91,
                          'rsi_percentile': 0.47, 'erp_percentile': 0.03,
                          'margin_trend': 0.54}}
        ctx = {'daily_df': _mk_df(), 'daily_basic_df': _mk_df(),
               'emotion_ext': {'limit_up_count': 42, 'sealing_rate': 63.4},
               'market_stats': {'ma20_ratio': 0.39},
               'margin_df': _mk_margin_df(),
               'sector_heat': {'白酒': {'heat_level': 'normal', 'rank': 15}}}
        ctx.update(data_context_extra or {})
        with mock.patch.object(dim5, '_bociasi_quickline', return_value=qr), \
             mock.patch.object(dim5, '_bociasi_slowline', return_value=sr), \
             mock.patch.object(dim5, 'BociasiQuadrantAnalyzer') as _MQ:
            _MQ.return_value.analyze.return_value = fq
            with mock.patch.object(eng, '_get_dm') as _dm:
                _dm.return_value.cache.get_cached_daily.return_value = _mk_df()
                _dm.return_value.cache.get_cached_daily_basic.return_value = _mk_df()
                _dm.return_value.get_stock_industry.return_value = '白酒'
                return eng.evaluate({}, {'ts_code': 'T.XSHG', 'sentiment_phase': 'ferment',
                                         'volume_price_fit': 'healthy'}, data_context=ctx)

    def test_basis_passthrough(self):
        """status_description 新增 temperature_basis，七项入参值全部落位"""
        sd = self._run()['status_description']
        basis = sd['temperature_basis']
        assert '阶段发酵(基温60)' in basis
        assert '涨停42家' in basis
        assert '封板率63%' in basis
        assert '板块排名15' in basis
        assert '量价健康' in basis
        assert '融资5日+3.0%' in basis       # 100→103 = +3.0%
        assert '广度39%(MA20占比近似)' in basis
        assert '情绪周期修正(快0.68×0.6+慢0.72×0.4)' in basis
        # 果（五档话术）不受影响
        assert '/100' in sd['temperature']

    def test_judgment_keys_unchanged(self):
        """445 冻结边界：只加「因」，judgment（果）键集与值域不变"""
        res = self._run()
        assert set(res['judgment'].keys()) == {
            'market_light', 'sector_light', 'stock_light', 'overall_light',
            'overall_direction', 'continuous_value'}
        assert 0 <= res['judgment']['continuous_value'] <= 1

    def test_missing_context_marks_no_data(self):
        """无 emotion_ext/market_stats/margin_df → 因句标「无数据」（不崩、不臆造）"""
        sd = self._run(data_context_extra={
            'emotion_ext': None, 'market_stats': None, 'margin_df': None,
            'sector_heat': None})['status_description']
        basis = sd['temperature_basis']
        assert '涨停无数据' in basis
        assert '封板率无数据' in basis
        assert '板块排名无数据' in basis


# ── dim8 情绪温度话术「果（因）」──────────────────────────

class TestDim8TemperatureSentence:

    def test_merge_basis_into_temperature(self):
        """dim8 emotion 温度句：果 + 括号因（dim5 定稿 §三-7 形态）"""
        sd = {'temperature': '中性53.8/100',
              'temperature_basis': '阶段发酵(基温60)+涨停42家+量价健康'}
        s = _compose_dim_text('emotion', {}, sd)
        assert '情绪温度：中性53.8/100（阶段发酵(基温60)+涨停42家+量价健康）' in s

    def test_no_basis_no_parenthesis(self):
        """缺 basis → 不产括号（437 缺则降级，兼容旧数据）"""
        s = _compose_dim_text('emotion', {}, {'temperature': '中性53.8/100'})
        assert '情绪温度：中性53.8/100' in s
        assert '（' not in s
