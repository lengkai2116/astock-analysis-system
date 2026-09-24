"""479号-4 dim5 补产出单测（A10 快线 details+indicators / A11 慢线 ERP / A12 四象限
fast_score+_cache7指标 / A13 温度五档话术）

覆盖（479-4，dim5 定稿 §六 ①-④）：
  - A10 _fmt_quickline：details（量比/价格偏离/5日动量/振幅）+ indicators 达标数
  - A11 _fmt_slowline：ERP 数值；数据不足（erp None）不占位
  - A12 _fmt_quadrant：fast_score/slow_score + _cache 7 指标；无 details 兼容
  - A13 _temp_level_cn：五档边界（冰冷/偏冷/中性/偏热/过热）
  - evaluate 集成：status_description 透传全部
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import numpy as np
import pandas as pd
import pytest
from unittest import mock

from app.opportunity_atlas.dimensions import dim5_emotion_engine as dim5
from app.opportunity_atlas.dimensions.dim5_emotion_engine import (
    Dim5EmotionEngine,
    _fmt_quickline,
    _fmt_slowline,
    _fmt_quadrant,
    _temp_level_cn,
)


def _mk_df(n=80):
    idx = pd.date_range('2025-01-01', periods=n, freq='B')
    closes = np.linspace(10, 20, n) + np.sin(np.linspace(0, 8, n)) * 0.5
    return pd.DataFrame({
        'ts_code': 'T.XSHG', 'open': closes, 'high': closes * 1.01,
        'low': closes * 0.99, 'close': closes, 'vol': [1e5] * n, 'amount': [3e5] * n,
    }, index=idx)


# ── A10: 快线 details+indicators ──────────────────────────

class TestQuickline:

    def test_fmt_with_details_and_indicators(self):
        """快线话术含 details（量比/价格偏离/5日动量/振幅）+ indicators 达标数"""
        qr = {'signal': 'NEUTRAL', 'confidence': 0.35, 'pass_count': 1,
              'indicators': {'fast_vol': False, 'fast_price': True, 'fast_mom': False, 'fast_breadth': False},
              'details': {'vol_ratio': 1.26, 'price_offset_pct': -1.1, 'mom_5d_pct': -1.99,
                          'amplitude_pct': 0.73}}
        s = _fmt_quickline(qr)
        assert '个股快线=中性（0.35）' in s
        assert '量比1.26' in s
        assert '价格偏离-1.1%' in s
        assert '5日动量-2.0%' in s  # -1.99 → 保留 1 位 -2.0
        assert '振幅0.73%' in s
        assert '站上均线达标1/4' in s

    def test_fmt_empty_details(self):
        """无 details → 只 signal+confidence（不占位）"""
        s = _fmt_quickline({'signal': 'BUY', 'confidence': 0.7, 'pass_count': 0,
                            'indicators': {}, 'details': {}})
        assert s == '个股快线=偏多（0.7）'


# ── A11: 慢线 ERP ─────────────────────────────────────────

class TestSlowline:

    def test_fmt_with_erp(self):
        """慢线话术含 ERP 数值（因）"""
        sr = {'signal': 'BULLISH', 'confidence': 0.66, 'details': {'erp': 3.5007, 'erp_signal': 'BULLISH'}}
        s = _fmt_slowline(sr)
        assert '个股慢线ERP=看多（0.66）' in s
        assert 'ERP 3.50%' in s

    def test_fmt_erp_none_no_placeholder(self):
        """数据不足（erp None）→ 不加 ERP 数值句（437 缺则降级）"""
        sr = {'signal': 'NEUTRAL', 'confidence': 0.0,
              'details': {'error': '数据不足（个股 pe_ttm 序列<60日）'}}
        s = _fmt_slowline(sr)
        assert '个股慢线ERP=中性（0.0）' in s
        assert '，ERP' not in s  # 固定前缀"个股慢线ERP="不算数值句


# ── A12: 四象限 fast_score + _cache 7 指标 ────────────────

class TestQuadrant:

    def test_fmt_with_scores_and_details(self):
        """四象限话术含 fast_score/slow_score + _cache 7 指标（因）"""
        qd = {'quadrant': 'MM', 'description': '市场情绪中性', 'fast_score': 0.52, 'slow_score': 0.64,
              'details': {'ma20_ratio': 0.5624, 'turnover_percentile': 0.5434, 'limit_ratio': 0.5,
                          'rsi_percentile': 0.5624, 'erp_percentile': 0.6379, 'margin_trend': 0.5434,
                          'dv_bond': 0.5}}
        s = _fmt_quadrant(qd)
        assert '大市四象限(中性·全市场分位)—市场情绪中性' in s
        assert '快线0.52/慢线0.64' in s
        assert 'MA20强势占比56%' in s
        assert 'ERP分位64%' in s
        assert '融资趋势54%' in s

    def test_fmt_no_details(self):
        """无 details → 只象限+描述（简化回退路径兼容）"""
        s = _fmt_quadrant({'quadrant': 'LL', 'description': '情绪底部，高性价比区间'})
        assert '大市四象限(' in s and '情绪底部，高性价比区间' in s


# ── A13: 温度五档话术 ─────────────────────────────────────

class TestTemperatureLevel:

    def test_five_levels(self):
        """五档边界：冰冷<20/偏冷20-40/中性40-60/偏热60-80/过热≥80"""
        assert _temp_level_cn(10) == '冰冷'
        assert _temp_level_cn(20) == '偏冷'
        assert _temp_level_cn(39) == '偏冷'
        assert _temp_level_cn(40) == '中性'
        assert _temp_level_cn(57.9) == '中性'
        assert _temp_level_cn(60) == '偏热'
        assert _temp_level_cn(80) == '过热'
        assert _temp_level_cn(95) == '过热'

    def test_invalid_default_neutral(self):
        """非数值 → 中性（不崩）"""
        assert _temp_level_cn(None) == '中性'
        assert _temp_level_cn('abc') == '中性'


# ── evaluate 集成 ──────────────────────────────────────────

class TestEvaluatePassthrough:

    def _run(self, quick=None, slow=None, quadrant_details=None):
        eng = Dim5EmotionEngine()
        qr = quick or {'signal': 'NEUTRAL', 'confidence': 0.35, 'pass_count': 1,
                       'indicators': {'fast_vol': False, 'fast_price': True, 'fast_mom': False,
                                      'fast_breadth': False},
                       'details': {'vol_ratio': 1.26, 'price_offset_pct': -1.1, 'mom_5d_pct': -1.99,
                                   'amplitude_pct': 0.73}}
        sr = slow or {'signal': 'BULLISH', 'confidence': 0.66,
                      'details': {'erp': 3.5007, 'erp_signal': 'BULLISH'}}
        fq = {'quadrant': 'MM', 'description': '市场情绪中性', 'fast_score': 0.52, 'slow_score': 0.64,
              'weight_multiplier': 1.0, 'details': quadrant_details or
              {'ma20_ratio': 0.56, 'turnover_percentile': 0.54, 'rsi_percentile': 0.56,
               'erp_percentile': 0.64, 'margin_trend': 0.54}}
        with mock.patch.object(dim5, '_bociasi_quickline', return_value=qr), \
             mock.patch.object(dim5, '_bociasi_slowline', return_value=sr), \
             mock.patch.object(dim5, 'BociasiQuadrantAnalyzer') as _MQ:
            _MQ.return_value.analyze.return_value = fq
            with mock.patch.object(eng, '_get_dm') as _dm:
                _dm.return_value.cache.get_cached_daily.return_value = _mk_df()
                _dm.return_value.cache.get_cached_daily_basic.return_value = _mk_df()
                return eng.evaluate({}, {'ts_code': 'T.XSHG', 'sentiment_phase': 'ferment',
                                         'volume_price_fit': 'healthy'},
                                    data_context={'daily_df': _mk_df(),
                                                  'daily_basic_df': _mk_df()})

    def test_all_fields(self):
        """evaluate status_description 透传 A10-A13"""
        res = self._run()
        sd = res['status_description']
        assert '量比1.26' in sd['bociasi_quick'] and '站上均线达标1/4' in sd['bociasi_quick']
        assert 'ERP 3.50%' in sd['bociasi_slow']
        assert '快线0.52/慢线0.64' in sd['quadrant']
        assert 'MA20强势占比56%' in sd['quadrant']
        # 温度五档话术（ferment 基温 + healthy → 某档）
        assert any(k in sd['temperature'] for k in ('冰冷', '偏冷', '中性', '偏热', '过热'))
        assert '/100' in sd['temperature']
        # 连续值仍为 0-1（判定键不动，439 边界）
        assert 0 <= res['judgment']['continuous_value'] <= 1
