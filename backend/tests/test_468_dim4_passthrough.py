"""468-①~⑤ dim4 现状描述补产出锁定测试

覆盖（2026-09-22，464-dim8-dim4 定稿 §六）：
  ① 透传 phase_vote_ratio：evaluate phase 文本含各维投票明细（compute_tags 已算）
  ② 透传 net_lg_5d：fund_flow 文本补 5日大单净额（万元÷1e4→亿，464-15 口径）
  ③ 透传 CrowdingFactor.details：crowding 文本含融资占比/换手/波动 + 有效信号数
  ④ signal 增强：_assess_signal 读 active_signal（含 price/confidence/reason）→ 增强 detail
     + _build_active_signal 补 confidence/reason
  ⑤ audit「筹码集中」收紧为 concentrating（stable 不再满足）
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pytest

from data_daemon import _build_active_signal
from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import (
    CrowdingFactor,
    Dim4ChipFundEngine,
    PhaseDetectionEngine,
    _assess_signal,
)


# ── ④ signal 增强：_assess_signal 读 active_signal ─────────────

class TestAssessSignalEnhance:

    def test_active_signal_dict_enhances_detail(self):
        """active_signal（含 price/confidence/reason）→ 增强 detail，无回退"""
        out = _assess_signal({
            'buy_sell_point': 'third_sell',
            'active_signal': json.dumps({'type': 'third_sell', 'date': '2026-09-10',
                                         'price': 1323.0, 'confidence': 0.78,
                                         'reason': '三卖确认'}),
        })
        assert out['signal'] == 'third_sell'
        assert '三卖信号' in out['detail']
        assert '@1323元' in out['detail']
        assert '置信0.78' in out['detail']
        assert '三卖确认' in out['detail']
        assert out['price'] == pytest.approx(1323.0)
        assert out['confidence'] == pytest.approx(0.78)
        assert out['reason'] == '三卖确认'

    def test_active_signal_no_price_keeps_enum(self):
        """active_signal 无 price/confidence → 落增强键仅 type/detail（不丢）"""
        out = _assess_signal({
            'buy_sell_point': 'first_buy',
            'active_signal': json.dumps({'type': 'first_buy', 'date': '2026-09-01'}),
        })
        assert out['signal'] == 'first_buy'
        assert '一买信号' in out['detail']
        assert out['price'] is None
        assert out['confidence'] is None

    def test_no_active_signal_fallback_word(self):
        """无 active_signal → 回退单词枚举（464-16 值域保持）"""
        out = _assess_signal({'buy_sell_point': 'third_sell'})
        assert out['detail'] == '三卖信号'
        assert out['signal'] == 'third_sell'
        assert 'price' not in out or out.get('price') is None

    def test_active_signal_unknown_type_none(self):
        """active_signal type 不在枚举 → none"""
        out = _assess_signal({'buy_sell_point': 'zzz',
                              'active_signal': json.dumps({'type': 'zzz'})})
        assert out['signal'] == 'none'

    def test_active_signal_dict_input(self):
        """active_signal 直接 dict 输入也兼容"""
        out = _assess_signal({'active_signal': {'type': 'second_buy', 'price': 9.5,
                                                'confidence': 0.6, 'reason': '回踩'}})
        assert out['signal'] == 'second_buy'
        assert '@9.5元' in out['detail']


# ── ④ _build_active_signal 补 confidence/reason ───────────────

class _Pt:
    def __init__(self, type_, position, confidence=0.8, reason=''):
        self.type = type_
        self.position = position
        self.confidence = confidence
        self.reason = reason


class TestBuildActiveSignalEnhanced:

    def test_json_includes_conf_reason(self):
        cl = {'buy_points': [_Pt('second_buy', {'idx': 5, 'price': 10.2, 'date': '2026-09-10'},
                               confidence=0.85, reason='力度背驰确认')]}
        d = json.loads(_build_active_signal(cl, 'second_buy'))
        assert d['type'] == 'second_buy'
        assert d['price'] == 10.2
        assert d['confidence'] == pytest.approx(0.85)
        assert d['reason'] == '力度背驰确认'

    def test_no_price_fallback_enum_unchanged(self):
        cl = {'buy_points': [_Pt('second_buy', {'idx': 5})]}
        assert _build_active_signal(cl, 'second_buy') == 'second_buy'

    def test_none_unchanged(self):
        assert _build_active_signal({}, '') is None


# ── ① 透传 phase_vote_ratio（evaluate 集成） ────────────────

def _mk_df(n=60):
    import pandas as pd
    return pd.DataFrame({
        'trade_date': pd.date_range('2025-12-01', periods=n).strftime('%Y-%m-%d'),
        'open': 10.0, 'high': 11.0, 'low': 9.5, 'close': 10.5,
        'vol': 1_000_000, 'amount': 10_000_000,
    })


def _run_evaluate(monkeypatch, data_context, tags=None, phase_payload=None):
    """跑 dim4 evaluate 集成，固定 PhaseDetectionEngine.compute_tags + CrowdingFactor.evaluate。"""
    fake_dm = type('_DM', (), {'cache': None})()
    monkeypatch.setattr(Dim4ChipFundEngine, '_get_dm', lambda self: fake_dm)
    # 固定模块级 PhaseDetectionEngine.compute_tags
    monkeypatch.setattr(
        PhaseDetectionEngine, 'compute_tags',
        staticmethod(lambda *a, **k: phase_payload or {}))
    # 固定 CrowdingFactor.evaluate 返回 details
    monkeypatch.setattr(
        CrowdingFactor, 'evaluate',
        lambda self, *a, **k: {
            'crowding_level': 'MODERATE', 'crowding_score': 0.5,
            'risk_advice': '拥挤度适中',
            'details': {'margin_ratio': 0.012, 'turnover_state': 'NORMAL_TURNOVER',
                        'volatility_state': 'MODERATE_CROWDING', 'valid_signals': 3,
                        'evidence': []}})
    engine = Dim4ChipFundEngine()
    return engine.evaluate({}, tags or {'ts_code': '000001.SZ'},
                           data_context=data_context)


class TestVoteRatioPassthrough:

    def test_phase_text_contains_votes(self, monkeypatch):
        """phase 文本含各维投票明细（compute_tags 经 phase_vote_ratio）"""
        df = _mk_df(60)
        res = _run_evaluate(monkeypatch, {'daily_df': df, 'daily_basic_df': _mk_df(30)},
                            tags={'ts_code': '000001.SZ', 'net_lg_5d': 100.0},
                            phase_payload={
                                'main_force_phase': 'lifting', 'phase_confidence': 0.7,
                                'fund_flow': 'inflow', 'trend_alignment': 'up_aligned',
                                'price_position': 'mid_zone',
                                'phase_vote_ratio': json.dumps({
                                    'fund': {'lifting': 0.8, 'building': 0.2},
                                    'stage': {'lifting': 0.6},
                                    'asr': {'washing': 0.4},
                                    '_conflict': False, '_confidence': 0.7,
                                    '_supporters': {'lifting': 2},
                                }),
                            })
        ph = res['status_description']['phase']
        assert '投票:fund=拉升(0.80)' in ph
        assert 'stage=拉升(0.60)' in ph


# ── ② 透传 net_lg_5d ───────────────────────────────────────

class TestNetLg5dPassthrough:

    def test_fund_flow_contains_net(self, monkeypatch):
        """fund_flow 文本含 5日大单净额（万元÷1e4→亿）"""
        df = _mk_df(60)
        res = _run_evaluate(monkeypatch, {'daily_df': df, 'daily_basic_df': _mk_df(30)},
                            tags={'ts_code': '000001.SZ', 'buy_sell_point': 'none',
                                  'fund_flow': '5d_outflow', 'net_lg_5d': -16037.0})
        ff = res['status_description']['fund_flow']
        assert '强流出' in ff
        assert '净流出1.6亿' in ff


# ── ③ 透传 CrowdingFactor.details ─────────────────────────

class TestCrowdingDetailsPassthrough:

    def test_crowding_text_contains_three_signals(self, monkeypatch):
        """crowding 文本含融资占比/换手/波动 + 有效信号数"""
        df = _mk_df(60)
        res = _run_evaluate(monkeypatch, {'daily_df': df, 'daily_basic_df': _mk_df(30),
                                          'margin_df': None})
        cw = res['status_description']['crowding']
        assert '融资占比1.20%' in cw
        assert '换手正常' in cw
        assert '波动正常' in cw
        assert '3/3信号可用' in cw


# ── ⑤ audit 筹码集中收紧 ───────────────────────────────────

class TestAuditChipConcentrationTighten:

    def _run_evaluate(self, monkeypatch, chip_concentration):
        df = _mk_df(60)
        return _run_evaluate(monkeypatch, {'daily_df': df, 'daily_basic_df': _mk_df(30)},
                             tags={'ts_code': '000001.SZ', 'chip_concentration': chip_concentration})

    def test_concentrating_satisfies(self, monkeypatch):
        res = self._run_evaluate(monkeypatch, 'concentrating')
        cond = next(c for c in res['audit']['conditions'] if c['name'] == '筹码集中')
        assert cond['satisfied'] is True
        assert cond['threshold'] == '集中度=concentrating'

    def test_stable_not_satisfied(self, monkeypatch):
        """⑤ 收紧：stable 不再满足（原 bool() 偏宽）"""
        res = self._run_evaluate(monkeypatch, 'stable')
        cond = next(c for c in res['audit']['conditions'] if c['name'] == '筹码集中')
        assert cond['satisfied'] is False
        assert cond['actual'] == 'stable'

    def test_dispersing_not_satisfied(self, monkeypatch):
        res = self._run_evaluate(monkeypatch, 'dispersing')
        cond = next(c for c in res['audit']['conditions'] if c['name'] == '筹码集中')
        assert cond['satisfied'] is False
