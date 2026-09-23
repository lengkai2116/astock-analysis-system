"""479号-3 dim3 补产出单测（A5 状态机透传 / A6 量能连续性 / A7 pattern conditions /
A8 背离检测条件 / A9 granville 命中值）

覆盖（479-3，dim3 定稿 §三.5 细项1/2/4/5/8）：
  - A5 _fmt/透传：dim3 status_description 透传 vp_state_label/vp_rule；dim8 T 表消费
  - A6 _calc_volume_consec：连续放量/缩量/无/数据不足
  - A7 _fmt_pattern_detail：conditions 每条判定条件拼接；无 conditions 回退形态名
  - A8：dim3 透传 divergence 三字段；div_txt 含置信/MACD（定稿细项5）
  - A9 _classify_granville：返回补 price_chg/vr；status_description 拼接"5日涨跌/量能"
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

from app.opportunity_atlas.dimensions import dim3_vp_engine as dim3
from app.opportunity_atlas.dimensions.dim3_vp_engine import (
    Dim3VPEngine,
    _calc_volume_consec,
    _fmt_pattern_detail,
    _classify_granville,
)


def _mk_df(n=40, close_base=10.0, vol_val=1e5):
    idx = pd.date_range('2025-01-01', periods=n, freq='B')
    closes = np.linspace(close_base, close_base + n * 0.1, n)
    return pd.DataFrame({
        'ts_code': 'T.XSHG', 'open': closes, 'high': closes * 1.01,
        'low': closes * 0.99, 'close': closes,
        'vol': [vol_val] * n, 'volume': [vol_val] * n, 'amount': [3e5] * n,
    }, index=idx)


def _mk_vol_df(tail_vols, n=40, base=1e5):
    """构造量能序列：前 n-5 根 base，末 5 根 tail_vols"""
    vols = [base] * (n - 5) + list(tail_vols)
    idx = pd.date_range('2025-01-01', periods=n, freq='B')
    closes = np.linspace(10, 10 + n * 0.1, n)
    return pd.DataFrame({'ts_code': 'T.XSHG', 'open': closes, 'high': closes * 1.01,
                         'low': closes * 0.99, 'close': closes, 'vol': vols}, index=idx)


# ── A6: 量能多日连续性 ────────────────────────────────────

class TestVolumeConsec:

    def test_consec_expand(self):
        """最近 3 日连续放量（>基准×1.5）→ '连续3日放量'"""
        df = _mk_vol_df([3e5, 3e5, 3e5, 3e5, 1e5])  # 基准 1e5，末 4 根 3e5（>1.5e5）
        assert _calc_volume_consec(df) == '连续4日放量'

    def test_consec_shrink(self):
        """最近 4 日连续缩量（<基准×0.8）→ '连续4日缩量'"""
        df = _mk_vol_df([2e4, 2e4, 2e4, 2e4, 2e4])  # 末 5 根全缩量（<0.8×基准）
        assert _calc_volume_consec(df) == '连续4日缩量'

    def test_no_consec(self):
        """正常波动 → ''（不占位）"""
        df = _mk_vol_df([1e5, 1.2e5, 0.9e5, 1e5, 1.1e5])
        assert _calc_volume_consec(df) == ''

    def test_insufficient_data(self):
        """不足 22 根 → ''"""
        df = _mk_df(n=10)
        assert _calc_volume_consec(df) == ''

    def test_empty_df(self):
        """空 df → ''"""
        assert _calc_volume_consec(pd.DataFrame()) == ''


# ── A7: pattern conditions ────────────────────────────────

class TestPatternDetail:

    def test_conditions_appended(self):
        """形态话术补 conditions（每条判定条件=因）"""
        pd_ = {'pattern_count': 1, 'patterns': [
            {'name': 'P-WB', 'direction': 'bullish', 'strength': 0.8,
             'conditions': ['两次探底', '放量突破颈线']}]}
        s = _fmt_pattern_detail(pd_)
        assert '两次探底' in s and '放量突破颈线' in s

    def test_no_conditions_fallback(self):
        """无 conditions → 形态名原样（不崩、非空）"""
        pd_ = {'pattern_count': 1, 'patterns': [
            {'name': 'P-WB', 'direction': 'bullish', 'strength': 0.8}]}
        s = _fmt_pattern_detail(pd_)
        assert s and s != '无明确形态'

    def test_no_pattern(self):
        """无形态 → '无明确形态'"""
        assert _fmt_pattern_detail(None) == '无明确形态'
        assert _fmt_pattern_detail({'pattern_count': 0, 'patterns': []}) == '无明确形态'


# ── A9: granville 命中值 ──────────────────────────────────

class TestGranvilleValues:

    def test_price_chg_vr_present(self):
        """_classify_granville 返回补 price_chg/vr（放量下跌：5日跌 + 末 5 日量大）"""
        closes = [30 - i * 0.3 for i in range(40)]  # 30 → 18.3 持续下跌
        vols = [1e5] * 35 + [3e5] * 5
        idx = pd.date_range('2025-01-01', periods=40, freq='B')
        df = pd.DataFrame({'ts_code': 'T.XSHG', 'open': closes, 'high': [c * 1.01 for c in closes],
                           'low': [c * 0.99 for c in closes], 'close': closes, 'vol': vols}, index=idx)
        r = _classify_granville(df, 3.0, {})
        assert 'price_chg' in r and 'vr' in r
        assert r['price_chg'] < -2.0
        assert r['vr'] > 0

    def test_insufficient_df_no_values(self):
        """df 不足 5 根 → 无 price_chg/vr 键（提前返回）"""
        r = _classify_granville(_mk_df(n=4), 1.0, {})
        assert 'price_chg' not in r


# ── A5/A7/A8/A9: evaluate 集成 ────────────────────────────

class TestEvaluatePassthrough:

    def _run_evaluate(self, tags, pattern_details=None):
        df = _mk_df()
        eng = Dim3VPEngine()
        with mock.patch.object(eng, 'pattern_engine') as _pe:
            _pe.evaluate.return_value = (7.0, pattern_details or {'pattern_count': 0, 'patterns': []})
            with mock.patch.object(eng, '_get_dm') as _dm:
                _dm.return_value.cache.get_cached_daily.return_value = df
                return eng.evaluate({}, tags, data_context={'daily_df': df})

    def test_vp_state_label_rule_passthrough(self):
        """A5：dim3 透传 vp_state_label/vp_rule"""
        res = self._run_evaluate({'ts_code': 'T.XSHG', 'volume_price_fit': 'healthy',
                                  'vp_state_label': '放量突破(筹码转换)',
                                  'vp_rule': '放量突破关键位'})
        sd = res['status_description']
        assert sd['vp_state_label'] == '放量突破(筹码转换)'
        assert sd['vp_rule'] == '放量突破关键位'

    def test_divergence_conditions(self):
        """A8：dim3 透传 divergence 三字段 + div_txt 含置信/MACD"""
        res = self._run_evaluate({'ts_code': 'T.XSHG', 'volume_price_fit': 'diverging',
                                  'divergence_type': '顶背离',
                                  'divergence_confidence': 0.6,
                                  'divergence_macd_confirmed': True})
        sd = res['status_description']
        assert sd['divergence'] == '顶背离（置信0.60，MACD确认）'
        assert sd['divergence_type'] == '顶背离'
        assert sd['divergence_confidence'] == 0.6
        assert sd['divergence_macd_confirmed'] is True

    def test_divergence_none_placeholder(self):
        """A8：无背离 → div_txt 保持'无背离信号'、三键透传空/None"""
        res = self._run_evaluate({'ts_code': 'T.XSHG', 'volume_price_fit': 'healthy',
                                  'divergence_type': '', 'divergence_confidence': None,
                                  'divergence_macd_confirmed': False})
        sd = res['status_description']
        assert sd['divergence'] == '无背离信号'
        assert sd['divergence_type'] == ''

    def test_granville_concat(self):
        """A9：status_description.granville 拼接 5日涨跌/量能"""
        res = self._run_evaluate({'ts_code': 'T.XSHG', 'volume_price_fit': 'healthy',
                                  'volume_ratio': 1.0})
        sd = res['status_description']
        assert 'granville' in sd
        assert '5日涨跌' in sd['granville'] or '量能' in sd['granville'] or '（' in sd['granville']

    def test_pattern_conditions_in_text(self):
        """A7：pattern 话术含 conditions（evaluate 链路）"""
        pd_ = {'pattern_count': 1, 'patterns': [
            {'name': 'P-WB', 'direction': 'bullish', 'strength': 0.8,
             'conditions': ['两次探底', '放量突破颈线']}]}
        res = self._run_evaluate({'ts_code': 'T.XSHG', 'volume_price_fit': 'healthy'}, pattern_details=pd_)
        assert '两次探底' in res['status_description']['pattern']


# ── dim8 侧 ───────────────────────────────────────────────

class TestDim8Side:

    def test_t_e_table_has_new_fields(self):
        """dim8 T/E 表 volume_price 含 479-3 新字段"""
        from app.opportunity_atlas.dimensions.dim8_summary_engine import _DIM8_T_SUBJECTS, _DIM8_E_FIELDS
        vp_t = _DIM8_T_SUBJECTS['volume_price']
        assert 'vp_state_label' in vp_t and 'vp_rule' in vp_t
        vp_e = _DIM8_E_FIELDS['volume_price']
        assert 'divergence_type' in vp_e
        assert 'divergence_confidence' in vp_e
        assert 'divergence_macd_confirmed' in vp_e

    def test_text_uses_state_machine(self):
        """dim8 volume_price text 消费 vp_state_label/vp_rule（先因后果）"""
        from app.opportunity_atlas.dimensions.dim8_summary_engine import _compose_dim_text
        sd = {'vp_state_label': '放量突破(筹码转换)', 'vp_rule': '放量突破关键位',
              'vp_state': '强健康', 'volume_energy': '量比1.5，温和放量'}
        text = _compose_dim_text('volume_price', {}, sd)
        assert '量价状态机:放量突破(筹码转换)' in text
        assert '状态规则:放量突破关键位' in text
        assert '量价状态:强健康' in text
