"""495号（B2）：量价健康度（HS）合成公式定标测试

用户 2026-09-28 拍板「A 补依据定标」+「pattern_score 不纳入」：
  - HS 7 因子合成公式保留在 dim3（成分因子均有方案背书：framework 281/333、461-10、
    461-1、445/460（446）、450、445-A3），合成式 (raw+4)/12×10 与档位正式定标
    （依据《464-dim3-health_score判定标准来源核查与归属建议》§二 因子表）；
  - 口径登记：state_machine_confidence = hs/10（JUD L1 vp 强度主通道）、
    stage_confidence = hs/10（L2 可靠性回退）、continuous_value = hs/10——本测试锁定防回归；
  - pattern_score 维持 JUD 零消费（形态经 pattern_signal/vp_state 间接参与，不重复计票）。

短 df（<10 行）→ PatternEngine 不跑 → pattern_score 保持默认 5.0 → pattern_deviation=0，
使 hs 仅由 tags 7 因子决定，可精确断言公式（注入手法与 test_446 一致，不碰开发库）。
"""
import numpy as np
import pandas as pd
from app.opportunity_atlas.dimensions.dim3_vp_engine import Dim3VPEngine


def _mk_df(n=5):
    rng = np.random.RandomState(0)
    closes = np.linspace(10, 12, n)
    vols = rng.uniform(1000, 5000, n).astype(float)
    idx = pd.date_range('2025-01-01', periods=n, freq='B')
    return pd.DataFrame({
        'ts_code': 'TEST.XSHG', 'open': closes,
        'high': closes * 1.01, 'low': closes * 0.99,
        'close': closes, 'vol': vols,
    }, index=idx)


# 全强因子：healthy(2) + 量比2.5(2) + bullish(1) + concentrating(1) + rsi65(1) + rps99(+1) + 无背离(0)
#   raw = 8 → hs = (8+4)/12×10 = 10 → 强健康 / conf = 1.0
_P_STRONG = {'volume_price_fit': 'healthy', 'volume_ratio': 2.5,
             'ma_alignment': 'bullish', 'chip_concentration': 'concentrating',
             'rsi': 65, 'ts_code': 'TEST'}

# 全弱因子：diverging(-1) + 量比0.5(0) + bearish(0) + stable(0.5) + rsi25(0.2) + 无RPS(0) + 背离(-1.5)
#   raw = -1.8 → hs = (2.2)/12×10 ≈ 1.83 → round → 2 → 弱档 / conf = 0.2
_P_WEAK = {'volume_price_fit': 'diverging', 'volume_ratio': 0.5,
           'ma_alignment': 'bearish', 'chip_concentration': 'stable',
           'rsi': 25, 'ts_code': 'TEST'}

# 中性因子：neutral(1) + 量比1.0(1) + mixed(0.5) + stable(0.5) + rsi50(0.5) + 无RPS(0)
#   raw = 3.5 → hs = (7.5)/12×10 = 6.25 → round → 6 → 健康档 / conf = 0.6
_P_NEUTRAL = {'volume_price_fit': 'neutral', 'volume_ratio': 1.0,
              'ma_alignment': 'mixed', 'chip_concentration': 'stable',
              'rsi': 50, 'ts_code': 'TEST'}


class TestHsFormulaCalibration:
    """HS 合成式 (raw+4)/12×10 与档位映射定标锁定"""

    def test_strong_factors_hs_upper_band(self):
        eng = Dim3VPEngine()
        out = eng.evaluate({}, dict(_P_STRONG),
                           data_context={'daily_df': _mk_df(),
                                         'relative_strength': {'rps_20d': 99}})
        sd = out['status_description']
        assert sd['health_score'] == '10/10（强健康）'
        assert sd['vp_state'] == '强健康'
        assert sd['state_machine_direction'] == 'BUY'

    def test_weak_factors_hs_lower_band(self):
        eng = Dim3VPEngine()
        out = eng.evaluate({}, dict(_P_WEAK), data_context={'daily_df': _mk_df()})
        sd = out['status_description']
        assert sd['vp_state'] == '背离'
        assert sd['state_machine_direction'] == 'SELL'
        assert sd['state_machine_confidence'] <= 0.3

    def test_neutral_factors_hold(self):
        eng = Dim3VPEngine()
        out = eng.evaluate({}, dict(_P_NEUTRAL), data_context={'daily_df': _mk_df()})
        sd = out['status_description']
        assert sd['state_machine_direction'] == 'HOLD'
        assert 0.4 <= sd['state_machine_confidence'] <= 0.6


class TestHsConfidenceCalibration:
    """口径登记：state_machine_confidence / stage_confidence / continuous_value == hs/10"""

    def test_confidence_equals_hs_over_10(self):
        eng = Dim3VPEngine()
        for tags in (_P_STRONG, _P_WEAK, _P_NEUTRAL):
            out = eng.evaluate({}, dict(tags), data_context={'daily_df': _mk_df()})
            sd, jud = out['status_description'], out['judgment']
            hs = int(sd['health_score'].split('/')[0])
            expected = round(hs / 10.0, 4)
            assert sd['state_machine_confidence'] == expected, f'{tags}: sm_conf != hs/10'
            assert sd['stage_confidence'] == expected, f'{tags}: stage_conf != hs/10'
            assert jud['continuous_value'] == expected, f'{tags}: continuous_value != hs/10'
            assert jud['score'] == hs, f'{tags}: judgment.score != hs'


class TestHsAudit:
    """audit 条件2「健康度评分≥5」定标锁定"""

    def test_audit_health_ge5_satisfied(self):
        eng = Dim3VPEngine()
        out = eng.evaluate({}, dict(_P_STRONG),
                           data_context={'daily_df': _mk_df(),
                                         'relative_strength': {'rps_20d': 99}})
        cond = next(c for c in out['audit']['conditions'] if c['name'] == '健康度评分')
        assert cond['satisfied'] is True
        assert cond['actual'] == '10/10'

    def test_audit_health_lt5_unsatisfied(self):
        eng = Dim3VPEngine()
        out = eng.evaluate({}, dict(_P_WEAK), data_context={'daily_df': _mk_df()})
        cond = next(c for c in out['audit']['conditions'] if c['name'] == '健康度评分')
        assert cond['satisfied'] is False


class TestHsCalibrationRegistered:
    """源码登记断言（防回归：定标注释/公式/档位/口径不丢失）"""

    def test_dim3_has_calibration_comment(self):
        import inspect
        src = inspect.getsource(Dim3VPEngine.evaluate)
        assert '495号（B2）' in src, '缺 495-B2 定标注释'
        assert '(raw + 4) / 12' in src, '合成式须保留'
        assert '强健康' in src and '严重背离' in src, '档位映射须保留'
        assert 'state_machine_confidence' in src, '口径登记须保留'

    def test_pattern_score_not_consumed_by_jud(self):
        """pattern_score 维持 JUD 零消费（不纳入登记防回归）"""
        import inspect

        from app.opportunity_atlas.dim_adapter import convert_to_factors
        src = inspect.getsource(convert_to_factors)
        assert "'pattern_score'" not in src and '"pattern_score"' not in src, \
            'pattern_score 不应被 JUD 消费（避免形态重复计票）'
