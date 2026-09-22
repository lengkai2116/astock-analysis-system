"""469号：dim4 观察项处置（① retail 同源 ② divergence 兜底中性态）锁定测试

覆盖（2026-09-22，用户拍板：1改/2改/3留/4留）：
 ① _assess_retail_institution 改由 evaluate 传「覆盖后」phase/fund_flow——与 phase 同源；
    不再自读 tags，避免 PhaseDetectionEngine 覆盖后 retail 与 phase 自相矛盾。
 ② fund_price_divergence 兜底路径加中性态：|5日变化|≤1% 判 no_trend
    （原一律判 down → 平盘误判背离），对齐 PhaseEngine 的 up/down/mixed/no_trend。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pandas as pd
import pytest

from app.opportunity_atlas.dimensions import dim4_chip_fund_engine as dim4_mod
from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import (
    CrowdingFactor, Dim4ChipFundEngine, PhaseDetectionEngine, _assess_retail_institution,
)


# ── ① retail_institution 同源 ─────────────────────────────

class TestAssessRetailInstitution:

    def test_signature_takes_phase_fund_flow(self):
        """签名改为 (phase, fund_flow)，不再自读 tags"""
        import inspect
        sig = inspect.signature(_assess_retail_institution)
        params = list(sig.parameters)
        assert params == ['phase', 'fund_flow']

    def test_building_with_5d_inflow(self):
        assert _assess_retail_institution('building', '5d_inflow')['detail'] == '主力建仓+资金流入（机构买入）'

    def test_distributing(self):
        assert _assess_retail_institution('distributing', '')['detail'] == '主力出货（抛压风险）'

    def test_other_fallback_neutral(self):
        assert _assess_retail_institution('lifting', 'mixed')['detail'] == '散户与机构博弈中性'

    def test_evaluate_uses_overridden_phase(self, monkeypatch):
        """evaluate 里 retail 用覆盖后 phase（与 phase 同源）：
        tags 说 distributing，但引擎覆盖为 building+5d_inflow → retail 应随覆盖值=建仓。"""
        res = _run_evaluate(monkeypatch, phase='building',
                            tags={'main_force_phase': 'distributing', 'ts_code': '000001.SZ'})
        assert res['status_description']['phase'].startswith('建仓期')
        assert res['status_description']['retail_institution'] == '主力建仓+资金流入（机构买入）'

    def test_evaluate_fallback_tags_when_no_engine(self, monkeypatch):
        """引擎失效（无 daily_df）→ 用 tags 兜底值"""
        res = _run_evaluate(monkeypatch, phase=None, tags={'main_force_phase': 'distributing'})
        assert res['status_description']['retail_institution'] == '主力出货（抛压风险）'


def _mk_df(closes):
    n = len(closes)
    return pd.DataFrame({
        'trade_date': pd.date_range('2025-12-01', periods=n).strftime('%Y-%m-%d'),
        'open': closes, 'high': [c * 1.02 for c in closes],
        'low': [c * 0.98 for c in closes], 'close': closes,
        'vol': [1_000_000] * n, 'amount': [10_000_000] * n,
    })


def _run_evaluate(monkeypatch, phase=None, tags=None):
    fake_dm = type('_DM', (), {'cache': None})()
    monkeypatch.setattr(Dim4ChipFundEngine, '_get_dm', lambda self: fake_dm)
    if phase is None:
        payload = {}
    else:
        payload = {'main_force_phase': phase, 'phase_confidence': 0.7,
                   'fund_flow': '5d_inflow', 'trend_alignment': 'up_aligned',
                   'price_position': 'mid_zone'}
    monkeypatch.setattr(PhaseDetectionEngine, 'compute_tags',
                        staticmethod(lambda *a, **k: payload))
    monkeypatch.setattr(CrowdingFactor, 'evaluate',
                        lambda self, *a, **k: {
                            'crowding_level': 'MODERATE', 'crowding_score': 0.5,
                            'risk_advice': '拥挤度适中',
                            'details': {'margin_ratio': 0.01, 'turnover_state': 'NORMAL_TURNOVER',
                                        'volatility_state': 'MODERATE_CROWDING', 'valid_signals': 3}})
    engine = Dim4ChipFundEngine()
    return engine.evaluate({}, tags or {'ts_code': '000001.SZ'},
                           data_context={'daily_df': _mk_df([10.0] * 60)})


# ── ② divergence 兜底中性态 ───────────────────────────────

class TestFundPriceDivergenceFallbackNeutral:
    """引擎失效 + df 兜底：|5日变化|≤1% → no_trend（不再误判 down）→ 数据不足而非背离"""

    def _price_direction(self, closes):
        # 复现 evaluate 兜底段的 price_direction 计算
        _c = [float(x) for x in closes]
        _s5 = (_c[-1] / _c[-6] - 1) if len(_c) >= 6 else 0.0
        return 'up' if _s5 > 0.01 else ('down' if _s5 < -0.01 else 'no_trend')

    def test_flat_price_neutral(self):
        # 5 日涨幅 0% → no_trend（原判 down）
        closes = [10.0] * 54 + [10.0, 10.0]
        assert self._price_direction(closes) == 'no_trend'

    def test_micro_rise_within1pct_neutral(self):
        # +0.5% → no_trend（原判 up 阈值 1% 未超，实判 down——错误）
        closes = [10.0] * 55 + [10.05]
        assert self._price_direction(closes) == 'no_trend'

    def test_rise_over1pct_up(self):
        closes = [10.0] * 55 + [10.15]
        assert self._price_direction(closes) == 'up'

    def test_decline_over1pct_down(self):
        closes = [10.0] * 55 + [9.85]
        assert self._price_direction(closes) == 'down'

    def test_micro_decline_within1pct_neutral(self):
        closes = [10.0] * 55 + [9.97]
        assert self._price_direction(closes) == 'no_trend'

    def test_evaluate_flat_returns_none(self, monkeypatch):
        """evaluate 平盘（5日 0%）→ fund_price_divergence_status 为 none（数据不足）而非背离"""
        df = _mk_df([10.0] * 60)
        fake_dm = type('_DM', (), {'cache': None})()
        monkeypatch.setattr(Dim4ChipFundEngine, '_get_dm', lambda self: fake_dm)
        monkeypatch.setattr(PhaseDetectionEngine, 'compute_tags',
                            staticmethod(lambda *a, **k: {}))
        monkeypatch.setattr(CrowdingFactor, 'evaluate',
                            lambda self, *a, **k: {
                                'crowding_level': 'MODERATE', 'crowding_score': 0.5,
                                'risk_advice': '拥挤度适中',
                                'details': {'margin_ratio': 0.01, 'turnover_state': 'NORMAL_TURNOVER',
                                            'volatility_state': 'MODERATE_CROWDING', 'valid_signals': 3}})
        engine = Dim4ChipFundEngine()
        # 引擎 compute_tags 返回空 → phase_engine_result 为 dict {}(不是 None)？
        # 注意：compute_tags 返回 {} 时，phase_engine_result={}，兜底路径走 df 斜率。
        res = engine.evaluate({}, {'ts_code': '000001.SZ'},
                             data_context={'daily_df': df})
        assert res['status_description']['fund_price_divergence_status'] == 'none'
