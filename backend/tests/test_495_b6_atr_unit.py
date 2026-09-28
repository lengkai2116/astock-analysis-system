"""495号（B3）：atr_pct 单位修复测试

用户 2026-09-28 拍板「修复」——dim6 产出 atr_pct 为百分数（3.98=3.98%），而 390 方案消费端
阈值按小数语义（0.8/0.3/0.7），致全市场恒触发折减（L6 仓位恒 ×0.6、L1 dim6 strength 恒 ×0.6、
L2 risk reliability 恒 0.4）。修复：阈值对齐百分数语义（8.0/3.0/7.0），
知识库《ATR止损》「低波动 3-5%、中 5-8%、高 8-12%」背书——仅高波动（>8%）折减。

B3 主向 = 维持现状（三键能力已由 494 R-3 ATR 止损取较高 + 452 流动性双门槛实现，
atr_14d/两流动性原值零直接消费无独立增益）。
"""
import inspect

from app.opportunity_atlas.advice_engine import compute_advice
from app.opportunity_atlas.dim_adapter import convert_to_factors
from app.opportunity_atlas.reliability_assessor import _assess_risk


def _risk_dim(atr_pct):
    return {'risk': {'status_description': {
        'atr_pct': atr_pct, 'rr_value': 2.0,
        'support_price': 11.0, 'resistance_price': 15.0,
        'dist_to_support_pct': -5.0,
    }}}


class TestL6PositionAdjust:
    """advice_engine 波动率调整：仅高波动（atr_pct>8.0）折减 ×0.6"""

    def test_normal_volatility_no_cut(self):
        a1 = compute_advice(80.0, {}, {}, _risk_dim(3.98), 'T.SZ', entry_price=12.0)
        a2 = compute_advice(80.0, {}, {}, _risk_dim(2.0), 'T.SZ', entry_price=12.0)
        assert a1['max_position_ratio'] == a2['max_position_ratio'], \
            '正常波动（<8%）不应触发折减（3.98 与 2.0 同仓）'

    def test_high_volatility_cut_06(self):
        normal = compute_advice(80.0, {}, {}, _risk_dim(4.0), 'T.SZ', entry_price=12.0)
        high = compute_advice(80.0, {}, {}, _risk_dim(9.5), 'T.SZ', entry_price=12.0)
        assert high['max_position_ratio'] < normal['max_position_ratio'], '高波动（>8%）应折减'
        assert abs(high['max_position_ratio'] - normal['max_position_ratio'] * 0.6) < 0.02, \
            '高波动折减系数应为 ×0.6'


class TestL1Dim6Strength:
    """dim_adapter：atr_pct>8.0 才给 dim6 strength ×0.6"""

    def test_normal_volatility_no_evidence(self):
        f = convert_to_factors(_risk_dim(3.98), {})
        ev = '；'.join(f['risk']['evidence'])
        assert '>8.0' not in ev, '正常波动不应出现折减 evidence'

    def test_high_volatility_has_evidence(self):
        f = convert_to_factors(_risk_dim(9.5), {})
        assert any('>8.0→×0.6' in e for e in f['risk']['evidence']), '高波动应出现折减 evidence'


class TestL2RiskReliability:
    """reliability_assessor：atr_pct 分档（<3 低波动→0.9 / >7 高波动→0.4 / 中→0.6）"""

    def test_low_volatility_high_reliability(self):
        assert _assess_risk(_risk_dim(2.0)) == 0.9

    def test_mid_volatility_mid_reliability(self):
        assert _assess_risk(_risk_dim(5.0)) == 0.6

    def test_high_volatility_low_reliability(self):
        assert _assess_risk(_risk_dim(9.0)) == 0.4

    def test_missing_atr_default(self):
        assert _assess_risk({'risk': {'status_description': {}}}) == 0.5


class TestUnitFixRegistered:
    """源码登记断言（防回归：阈值百分数语义 + 495-B3 注释）"""

    def test_thresholds_in_sources(self):
        from app.opportunity_atlas import advice_engine, dim_adapter
        assert '> 8.0' in inspect.getsource(advice_engine.compute_advice), 'advice_engine 阈值应 8.0'
        assert '> 8.0' in inspect.getsource(dim_adapter.convert_to_factors), 'dim_adapter 阈值应 8.0'
        src = inspect.getsource(_assess_risk)
        assert 'atr < 3.0' in src and 'atr > 7.0' in src, 'L2 分档应 3.0/7.0（百分数）'

    def test_b3_comment_present(self):
        assert '495号（B3）' in inspect.getsource(compute_advice), 'advice_engine 缺 495-B3 注释'
