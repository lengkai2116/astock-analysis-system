"""495号 批次1：JUD 判定单源权威化（A1+A2）回归

  A1  双共识/双状态条单源化：dim8 展示层**单向消费判定层**（v390=判定、dim8=展示派生）
      - 有 jud_result → consensus_rate = 判定层映射（v390 [-1,1] → 展示 [0,1]）
      - status_bar 由 opportunity_state+direction 派生（消除矛盾组合）
      - direction / overall_light / text 均由判定层结果驱动
      - 无 jud_result → 回退自算（既有行为不变，独立调用/降级兼容）
  A2  ② legacy dims 与 ③ 判定无因果 → status_verdict 与 seven_dim summary 同源
      （daemon JUD 步骤回填 single-source seven_dim，见 data_daemon._backfill_seven_dim_jud）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.opportunity_atlas.dimensions.dim8_summary_engine import (  # noqa: E402
    Dim8SummaryEngine,
    _calc_consensus_rate,
    _derive_status_bar,
    _derive_status_bar_v390,
    _jud_consensus_rate,
)


def _dr():
    """构造可自算共识的 dim_results（全绿高置信）"""
    def _dim(light='green', conf=0.8):
        return {
            'status_description': {},
            'judgment': {'overall_light': light, 'overall_direction': 1,
                         'continuous_value': conf},
            'audit': {'confidence': conf},
        }
    return {
        'signal': _dim(), 'structure': _dim(), 'volume_price': _dim(),
        'chip_fund': _dim(), 'emotion': _dim(), 'risk': _dim(),
        'valuation': _dim(),
    }


def _v390_result(consensus_rate=0.8, direction='bull', state='enter'):
    """v390 判定层 l2 结构（_v390_result 产出，含 final_score 标记）"""
    return {
        'opportunity_state': state,
        'state_evidence': [],
        'consensus_rate': consensus_rate,
        'direction': direction,
        'bullish_dims': 0.5, 'bearish_dims': 0.1,
        'conflict_evidence': [],
        'final_score': 80.0,
        'semantic_type': '', 'reliability_summary': {}, 'consensus_detail': {},
        'advice': {},
    }


def _evaluate(jud_result=None, dr=None):
    return Dim8SummaryEngine().evaluate(
        dims={}, tags={},
        lifecycle={'dim_results': dr if dr is not None else _dr(),
                   'jud_result': jud_result} if jud_result else
                  {'dim_results': dr if dr is not None else _dr()})


# ── A1：判定层消费（单源化路径） ─────────────────────────

class TestJudSingleSource:

    def test_consensus_rate_mapped_from_v390(self):
        # v390 cr=0.8 ∈ [-1,1] → 展示 (0.8+1)/2 = 0.9
        out = _evaluate(jud_result=_v390_result(consensus_rate=0.8))
        assert out['judgment']['consensus_rate'] == 0.9

    def test_consensus_rate_negative_mapped(self):
        out = _evaluate(jud_result=_v390_result(consensus_rate=-0.6, direction='bear',
                                                state='wait'))
        assert out['judgment']['consensus_rate'] == 0.2

    def test_consensus_rate_capped(self):
        out = _evaluate(jud_result=_v390_result(consensus_rate=-1.5))
        assert out['judgment']['consensus_rate'] == 0.0
        out2 = _evaluate(jud_result=_v390_result(consensus_rate=1.5))
        assert out2['judgment']['consensus_rate'] == 1.0

    def test_status_bar_derived_from_opportunity_state(self):
        cases = [
            ('avoid', 'bull', 'risk_warning'),
            ('reduce', 'bull', 'cautious'),
            ('wait', 'neutral', 'neutral'),
            ('light', 'bull', 'light_confirm'),
            ('enter', 'bull', 'strong_confirm'),
        ]
        for state, direction, expect in cases:
            out = _evaluate(jud_result=_v390_result(state=state, direction=direction))
            assert out['judgment']['status_bar'] == expect, f'{state}/{direction}'

    def test_bear_direction_downgrades_to_bearish(self):
        out = _evaluate(jud_result=_v390_result(state='wait', direction='bear'))
        assert out['judgment']['status_bar'] == 'bearish'

    def test_avoid_never_positive(self):
        # 矛盾组合消除：v390=avoid → dim8 不再 strong/trend/light_confirm
        for d in ('bull', 'bear', 'neutral'):
            out = _evaluate(jud_result=_v390_result(state='avoid', direction=d))
            assert out['judgment']['status_bar'] == 'risk_warning'

    def test_direction_from_jud(self):
        out = _evaluate(jud_result=_v390_result(direction='bear'))
        assert out['judgment']['direction'] == -1
        out2 = _evaluate(jud_result=_v390_result(direction='bull'))
        assert out2['judgment']['direction'] == 1

    def test_overall_light_driven_by_jud_consensus(self):
        # v390 cr=-0.9 → 展示 0.05 → red
        out = _evaluate(jud_result=_v390_result(consensus_rate=-0.9, direction='bear',
                                                state='avoid'))
        assert out['judgment']['overall_light'] == 'red'

    def test_text_uses_jud_consensus(self):
        out = _evaluate(jud_result=_v390_result(consensus_rate=0.8))  # → 0.9
        assert '共识90%' in out['status_description']['text']

    def test_eight_dim_summary_uses_jud_consensus(self):
        # eight_dim_summary 的 summary 行灯由判定层映射共识率驱动
        out = _evaluate(jud_result=_v390_result(consensus_rate=-0.9, direction='bear',
                                                state='avoid'))
        assert out['status_description']['eight_dim_summary']['summary']['light'] == 'red'

    def test_legacy_jud_passthrough(self):
        # legacy l2（无 final_score）consensus_rate 已 [0,1] → 透传；bullish → 1
        jr = {'opportunity_state': 'wait', 'consensus_rate': 0.4, 'direction': 'bullish'}
        out = _evaluate(jud_result=jr)
        assert out['judgment']['consensus_rate'] == 0.4
        assert out['judgment']['direction'] == 1
        assert out['judgment']['status_bar'] == 'neutral'

    def test_build_seven_dim_report_with_jud_result(self):
        # daemon JUD 回填路径：build_seven_dim_report 传 jud_result → summary 段单源化
        report = Dim8SummaryEngine().build_seven_dim_report(
            _dr(), tags={}, ts_code=None, jud_result=_v390_result(consensus_rate=0.8))
        s_sum = report['summary']
        assert s_sum['judgment']['consensus_rate'] == 0.9
        assert s_sum['judgment']['overall_light'] == 'green'
        assert '共识90%' in s_sum['text']


# ── A1：回退路径（无判定层 → 既有行为不变） ───────────────

class TestFallback:

    def test_no_jud_result_falls_back_to_self_calc(self):
        dr = _dr()
        expect = _calc_consensus_rate(dr)
        out = _evaluate(dr=dr)
        jg = out['judgment']
        # 回退路径 = 自算口径（与 _calc_consensus_rate / _derive_status_bar 逐值一致）
        assert jg['consensus_rate'] == expect
        assert jg['direction'] == (1 if expect >= 0.5 else (-1 if expect < 0.3 else 0))
        assert jg['status_bar'] == _derive_status_bar(dr, expect, [])
        assert jg['caliber'] == 'display_derived'

    def test_helper_jud_consensus_rate_none_on_empty(self):
        assert _jud_consensus_rate(None) is None
        assert _jud_consensus_rate({}) is None
        assert _jud_consensus_rate({'consensus_rate': 'bad'}) is None

    def test_helper_status_bar_v390_none_on_empty(self):
        assert _derive_status_bar_v390(None) is None
        assert _derive_status_bar_v390({}) is None
        assert _derive_status_bar_v390({'direction': 'bull'}) is None  # 无 opportunity_state


# ── A2：StatusEngine.evaluate 注入判定层（顺序 + 数据流） ──

class TestStatusEngineInjection:

    def test_evaluate_injects_jud_result_to_dim8(self, monkeypatch):
        import app.data.sharding_manager as sm_mod
        import app.opportunity_atlas.status_engine as se_mod
        from app.opportunity_atlas.dimensions import dim8_summary_engine as d8_mod

        eng = se_mod.StatusEngine.__new__(se_mod.StatusEngine)
        eng.cfg = {'jud_engine_version': 'v390'}
        eng.registry = {}
        eng.dm = None

        monkeypatch.setattr(eng, '_load_tags', lambda code: {'state_label': '上升'})
        monkeypatch.setattr(eng, '_load_signals', lambda code: {})
        monkeypatch.setattr(eng, '_signal_lifecycle', lambda code, t, s: {})
        monkeypatch.setattr(eng, '_build_dim_engine_results',
                            lambda t, s, x, lc, ts_code=None: {'risk': {'judgment': {}}})
        monkeypatch.setattr(eng, '_convert_to_dims_format', lambda de, t: {})
        monkeypatch.setattr(eng, '_apply_l0',
                            lambda *a, **k: {'hold_only': False, 'position_coeff': 1.0,
                                             'soft_risks': [], 'hard_veto': False})
        monkeypatch.setattr(eng, '_detect_market_regime', lambda t, d: 'ranging')
        monkeypatch.setattr(eng, 'MARKET_REGIME_WEIGHTS', {'ranging': {}})

        _v390 = _v390_result()
        monkeypatch.setattr(eng, '_aggregate_v390', lambda *a, **k: _v390)
        monkeypatch.setattr(eng, '_detect_registered_signals', lambda t, s: [])
        monkeypatch.setattr(eng, '_assemble', lambda *a, **k: {})

        captured = {}

        def _spy_eval(self, dims, tags, signals=None, lifecycle=None):
            captured['lifecycle'] = lifecycle
            return {'status_description': {}, 'judgment': {}, 'audit': {}}

        monkeypatch.setattr(d8_mod.Dim8SummaryEngine, 'evaluate', _spy_eval)

        # StatusEngine.evaluate 内部 from ... import Dim8SummaryEngine 是函数内导入，
        # 需同时 patch 状态引擎模块符号——但函数内 from 导入每次都会取模块属性，
        # 故直接 patch 源头即可。
        eng.evaluate('000001.SZ', dim_results={'risk': {'judgment': {}}})
        lc = captured['lifecycle']
        # dim_results 内 evaluate 写回 dim8 summary（既有行为），risk 原样保留
        assert lc['dim_results']['risk'] == {'judgment': {}}
        assert 'summary' in lc['dim_results']
        # 判定层结果注入（A1 单源化核心：dim8 在判定后拿到 l2）
        assert lc['jud_result'] is _v390
