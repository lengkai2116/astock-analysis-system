"""418号方案回归测试：JUD管线接入 + signal消费链补齐

覆盖：
- Step 1: signal_analyzer输出并入results['signal']（修复JUD消费链键名错位）
- Step 2: _aggregate_v390 L1-L6管线（convert_to_factors→assess→consensus→conflict→factor_arbiter→advice）
- Step 3: evaluate() jud_engine_version版本分支 + _assemble 390号字段扩展
- legacy路径回归（输出结构不变）
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from unittest import mock

import pytest
from app.opportunity_atlas.dim_adapter import convert_to_factors
from app.opportunity_atlas.reliability_assessor import assess

# ── 共享 mock 数据（对齐 test_390_integration.py 结构）─────────

MOCK_DIM_RESULTS = {
    'signal': {
        'status_quality': {'data_loaded': True, 'quality_level': 'good',
                           'completeness_score': 0.9, 'missing_tables': []},
        'data_context': {'daily_df': None},
    },
    'structure': {
        'status_description': {
            'chanlun_strength': 0.7,
            'level_cross_score': 0.8,
            'chanlun_phase': '健康',
            'trend_structure_signal': '123_buy_breakout',
            'trend_structure_strength': 'strong',
            'chanlun_strength_components': {'strength': 0.6, 'consistency': 0.7},
            'divergence_multi_algo': {'macd': {'agree': True}, 'rsi': {'agree': True},
                                      'kdj': {'agree': True}},
        },
        'judgment': {'overall_direction': 1, 'continuous_value': 0.65},
    },
    'volume_price': {
        'status_description': {
            'vp_state': '健康',
            'state_machine_direction': 'BUY',
            'state_machine_confidence': 0.75,
            'multi_timeframe_consistency': '一致',
            'resonance_score': 3,
            'stage_name': 'UPTREND_ACTIVE',
            'stage_confidence': 0.8,
            'three_laws': {'effort_result': '正常'},
        },
        'judgment': {'vp_state': {'value': '健康'}, 'continuous_value': 0.7},
    },
    'chip_fund': {
        'status_description': {
            'phase': 'lifting', 'phase_confidence': 0.7,
            'pde_conflict': False, 'crowding_level': 'MEDIUM',
        },
        'judgment': {'flow_direction': {'value': '流入'}, 'continuous_value': 0.6},
    },
    'emotion': {
        'status_description': {
            'market_phase': 'normal', 'temperature': 55,
            'bociasi_fast_signal': 'NEUTRAL', 'bociasi_slow_signal': 'BULLISH',
            'bociasi_slow_confidence': 0.6, 'sector_heat': 'medium',
        },
        'judgment': {'phase': {'value': '正常'}, 'continuous_value': 0.5},
    },
    'risk': {
        'status_description': {
            'level': '中', 'rr_value': 2.0, 'atr_pct': 0.4,
            'support_price': 10.2, 'resistance_price': 12.5,
            'volatility_percentile': 0.5,
        },
        'judgment': {'risk_level': {'value': '中'}, 'continuous_value': 0.4},
    },
    'valuation': {
        'status_description': {
            'composite_rating': 0.8, 'potential_score': 65,
            'dividend_yield': 2.5, 'revenue_growth': 15,
            'valuation_deviation': -10,
        },
        'judgment': {'valuation': {'value': '低估'}, 'continuous_value': 0.7},
    },
}

MOCK_TAGS = {'right_side_confirm': '强确认', 'ts_code': '000001.SZ'}


def _merge_signal_analysis(dim_results: dict) -> dict:
    """模拟 Step 1 改造后的 results['signal']（dim1门禁 + signal_analysis合并）"""
    from app.opportunity_atlas.signal_analyzer import analyze_signal
    dims_for_signal = {}
    for key in ['structure', 'volume_price', 'chip_fund', 'emotion', 'risk', 'valuation']:
        r = dim_results.get(key)
        if r and isinstance(r, dict):
            judg = r.get('judgment', {})
            state_val = '中性'
            for jk, jv in judg.items():
                if jk not in ('overall_light', 'overall_direction', 'continuous_value') \
                        and isinstance(jv, dict):
                    state_val = jv.get('value', '中性')
                    break
            dims_for_signal[key] = {'state': state_val,
                                    'confidence': judg.get('continuous_value', 0.5)}
    sig_analysis = analyze_signal(dims_for_signal, MOCK_TAGS, {'verified': True})
    merged = dict(dim_results)
    merged['signal'] = {**dim_results.get('signal', {}), **sig_analysis}
    return merged


def _make_engine(cfg_version: str = 'v390'):
    """构造 StatusEngine 实例（mock cfg，避免依赖真实 DataManager）"""
    from app.opportunity_atlas.status_engine import StatusEngine
    engine = StatusEngine.__new__(StatusEngine)
    engine.cfg = {'jud_engine_version': cfg_version}
    return engine


# ── Step 1: signal判定并入 results['signal'] ─────────────────

class TestStep1_SignalMerged:

    def test_signal_analysis_merged_into_signal(self):
        """_build_dim_engine_results后 results['signal'] 含 judgment.attribute.code"""
        from app.opportunity_atlas.status_engine import StatusEngine
        engine = StatusEngine.__new__(StatusEngine)
        engine.cfg = {}
        with mock.patch.object(StatusEngine, '_signal_lifecycle', return_value={}):
            pass
        # 直接调用 _build_dim_engine_results（mock dim1/dim2-dim7）
        merged = _merge_signal_analysis(dict(MOCK_DIM_RESULTS))
        _sig = merged.get('signal') or {}
        _judg = _sig.get('judgment') or {}
        _attr = _judg.get('attribute') or {}
        assert _attr.get('code') in (
            'right_confirmed', 'right_emerging', 'left_probing',
            'trend_running', 'consolidating', 'neutral', 'risk_warning'), \
            f"signal判定未并入: attribute={_attr}"
        # dim1门禁字段仍保留
        assert 'status_quality' in _sig, "dim1门禁结果被覆盖丢失"

    def test_dim_adapter_reads_signal(self):
        """convert_to_factors 从合并后的 signal 提取 direction（right_confirmed→1）"""
        merged = _merge_signal_analysis(dict(MOCK_DIM_RESULTS))
        dims_factor = convert_to_factors(merged, MOCK_TAGS)
        assert 'signal' in dims_factor
        assert dims_factor['signal']['direction'] == 1, \
            f"signal direction 应为1（right_confirmed），实际 {dims_factor['signal']['direction']}"

    def test_reliability_assessor_signal(self):
        """reliability_assessor 从合并后的 signal 提取 maintenance.status（healthy→0.8）"""
        merged = _merge_signal_analysis(dict(MOCK_DIM_RESULTS))
        dims_factor = convert_to_factors(merged, MOCK_TAGS)
        reliability = assess(dims_factor, merged)
        assert 'signal' in reliability
        assert reliability['signal'] == 0.8, \
            f"signal reliability 应为0.8（healthy），实际 {reliability.get('signal')}"

    def test_dim8_signal_direction_restored(self):
        """dim8 _extract_dim_direction 从合并后的 signal 恢复方向"""
        from app.opportunity_atlas.dimensions.dim8_summary_engine import _extract_dim_direction
        merged = _merge_signal_analysis(dict(MOCK_DIM_RESULTS))
        direction = _extract_dim_direction(merged, 'signal')
        assert direction != 0, "signal 方向应为非0（right_confirmed→1）"


# ── Step 2: _aggregate_v390 L1-L6管线 ────────────────────────

class TestStep2_AggregateV390:

    def test_aggregate_v390_basic(self):
        """_aggregate_v390 返回含 390号 新增字段的完整结构"""
        from app.opportunity_atlas.status_engine import StatusEngine
        engine = _make_engine('v390')
        engine._detect_market_regime = staticmethod(lambda tags, dims: 'ranging')
        engine.MARKET_REGIME_WEIGHTS = StatusEngine.MARKET_REGIME_WEIGHTS
        merged = _merge_signal_analysis(dict(MOCK_DIM_RESULTS))
        l0 = {'position_coeff': 1.0, 'hold_only': False, 'soft_risks': [],
              'hard_veto': False, 'hard_reason': '', 'emotion_position_cap': None}
        result = engine._aggregate_v390(MOCK_TAGS, {}, l0, {}, merged, '000001.SZ')
        assert 'opportunity_state' in result
        assert result['opportunity_state'] in ('enter', 'light', 'wait', 'avoid')
        assert 'final_score' in result
        assert 'semantic_type' in result
        assert 'reliability_summary' in result
        assert 'consensus_detail' in result
        assert 'consensus_rate' in result
        assert 'direction' in result
        assert 'conflict_evidence' in result

    def test_aggregate_v390_hard_veto(self):
        """l0.hard_veto=True → 直接 avoid"""
        from app.opportunity_atlas.status_engine import StatusEngine
        engine = _make_engine('v390')
        engine.MARKET_REGIME_WEIGHTS = StatusEngine.MARKET_REGIME_WEIGHTS
        merged = _merge_signal_analysis(dict(MOCK_DIM_RESULTS))
        l0 = {'position_coeff': 1.0, 'hold_only': False, 'soft_risks': [],
              'hard_veto': True, 'hard_reason': '监管立案', 'emotion_position_cap': None}
        result = engine._aggregate_v390(MOCK_TAGS, {}, l0, {}, merged, '000001.SZ')
        assert result['opportunity_state'] == 'avoid'

    def test_aggregate_v390_fatal_conflict(self):
        """conflict.fatal_to_veto 非空 → 返回 wait"""
        from app.opportunity_atlas.status_engine import StatusEngine
        engine = _make_engine('v390')
        engine.MARKET_REGIME_WEIGHTS = StatusEngine.MARKET_REGIME_WEIGHTS
        merged = _merge_signal_analysis(dict(MOCK_DIM_RESULTS))
        l0 = {'position_coeff': 1.0, 'hold_only': False, 'soft_risks': [],
              'hard_veto': False, 'hard_reason': '', 'emotion_position_cap': None}
        # 构造 fatal 冲突：结构风险 HIGH + 右侧确认（C12 风险收益不匹配）
        dr = dict(merged)
        dr['risk'] = dict(dr['risk'])
        dr['risk']['status_description'] = dict(dr['risk']['status_description'])
        dr['risk']['status_description']['level'] = '高'
        with mock.patch('app.opportunity_atlas.conflict_matrix.detect',
                        return_value={'fatal_to_veto': ['结构风险 HIGH vs 右侧确认'],
                                      'warn_for_semantic': [], 'semantic_type': 'conflict',
                                      'semantic_adjustment': 0.8, 'all_conflicts': ['x']}):
            result = engine._aggregate_v390(MOCK_TAGS, {}, l0, {}, dr, '000001.SZ')
        assert result['opportunity_state'] == 'wait'


# ── Step 3: evaluate() 版本分支 + _assemble 字段扩展 ──────────

class TestStep3_VersionBranch:

    @staticmethod
    def _stub_engine(engine, dim_results, l2_result):
        """stub evaluate 依赖：tags/signals/lifecycle/dims/l0/aggregate/hits"""
        engine._load_tags = mock.Mock(return_value={'ts_code': '000001.SZ',
                                                    'right_side_confirm': '强确认'})
        engine._load_signals = mock.Mock(return_value={})
        engine._signal_lifecycle = mock.Mock(return_value={})
        engine._build_dim_engine_results = mock.Mock(return_value=dict(dim_results))
        engine._convert_to_dims_format = mock.Mock(return_value={})
        engine._apply_l0 = mock.Mock(return_value={'position_coeff': 1.0, 'hold_only': False,
                                                   'soft_risks': [], 'hard_veto': False,
                                                   'hard_reason': '', 'emotion_position_cap': None})
        engine._detect_registered_signals = mock.Mock(return_value=[])
        engine._aggregate = mock.Mock(return_value=l2_result)
        engine._aggregate_v390 = mock.Mock(return_value=l2_result)
        return engine

    def test_version_branch_legacy(self):
        """jud_engine_version=legacy → 调用 _aggregate（旧管线）"""
        from app.opportunity_atlas.status_engine import StatusEngine
        engine = _make_engine('legacy')
        l2 = {'opportunity_state': 'wait', 'state_evidence': [], 'consensus_rate': 0.5,
              'direction': 'neutral', 'bullish_dims': 0.0, 'bearish_dims': 0.0,
              'conflict_evidence': []}
        engine = self._stub_engine(engine, MOCK_DIM_RESULTS, l2)
        engine.evaluate('000001.SZ')
        engine._aggregate.assert_called_once()
        engine._aggregate_v390.assert_not_called()

    def test_version_branch_v390(self):
        """jud_engine_version=v390 → 调用 _aggregate_v390（新管线）"""
        from app.opportunity_atlas.status_engine import StatusEngine
        engine = _make_engine('v390')
        l2 = {'opportunity_state': 'wait', 'state_evidence': [], 'consensus_rate': 0.5,
              'direction': 'neutral', 'bullish_dims': 0.0, 'bearish_dims': 0.0,
              'conflict_evidence': [], 'final_score': 50.0, 'semantic_type': '',
              'reliability_summary': {}, 'consensus_detail': {}, 'advice': {}}
        engine = self._stub_engine(engine, MOCK_DIM_RESULTS, l2)
        engine.evaluate('000001.SZ')
        engine._aggregate_v390.assert_called_once()
        engine._aggregate.assert_not_called()

    def test_assemble_390_fields_added(self):
        """_assemble 在 v390 输出下追加 final_score 等字段，legacy 键不变"""
        from app.opportunity_atlas.status_engine import StatusEngine
        engine = _make_engine('v390')
        l2 = {'opportunity_state': 'wait', 'state_evidence': [], 'consensus_rate': 0.5,
              'direction': 'neutral', 'bullish_dims': 0.0, 'bearish_dims': 0.0,
              'conflict_evidence': [], 'final_score': 60.0, 'semantic_type': 'conflict',
              'reliability_summary': {'signal': 0.8}, 'consensus_detail': {'risk': {}},
              'advice': {'max_position_ratio': 0.4, 'stop_loss_price': 9.8}}
        l0 = {'position_coeff': 1.0, 'hold_only': False, 'soft_risks': [], 'hard_veto': False}
        result = engine._assemble('000001.SZ', {}, None, l0, l2, [], None)
        assert result['final_score'] == 60.0
        assert result['semantic_type'] == 'conflict'
        assert 'reliability_summary' in result
        assert 'consensus_detail' in result
        # legacy 键全部保留
        for key in ['ts_code', 'dim_states', 'status_bar', 'opportunity_state',
                    'state_evidence', 'conflict_evidence', 'consensus_rate',
                    'direction', 'l0', 'lifecycle', 'advice_params', 'signals']:
            assert key in result, f"legacy键缺失: {key}"
        # L6 advice 并入 advice_params
        ap = __import__('json').loads(result['advice_params'])
        assert ap.get('stop_loss_price') == 9.8

    def test_legacy_output_unchanged(self):
        """legacy 路径输出结构与改造前一致（无 final_score 等390号字段）"""
        from app.opportunity_atlas.status_engine import StatusEngine
        engine = _make_engine('legacy')
        l2 = {'opportunity_state': 'wait', 'state_evidence': [], 'consensus_rate': 0.5,
              'direction': 'neutral', 'bullish_dims': 0.0, 'bearish_dims': 0.0,
              'conflict_evidence': []}
        l0 = {'position_coeff': 1.0, 'hold_only': False, 'soft_risks': [], 'hard_veto': False}
        result = engine._assemble('000001.SZ', {}, None, l0, l2, [], None)
        assert 'final_score' not in result
        assert 'semantic_type' not in result
        assert result['opportunity_state'] == 'wait'


# ── dim7 残缺实现修复回归（418号补充）─────────────────────────

class TestDim7Restored:

    def test_potential_score_int_string(self):
        """_potential_score_int 解析字符串 '潜力评分53/100' → 53"""
        from app.opportunity_atlas.dim_adapter import _potential_score_int
        assert _potential_score_int({'potential_score': '潜力评分53/100'}) == 53
        assert _potential_score_int({'potential_score': '92/100'}) == 92
        assert _potential_score_int({'potential_score': '80'}) == 80

    def test_potential_score_int_numeric(self):
        """_potential_score_int 优先读数字 potential_strength"""
        from app.opportunity_atlas.dim_adapter import _potential_score_int
        assert _potential_score_int({'potential_strength': 70}) == 70
        assert _potential_score_int({'potential_strength': 70, 'potential_score': '潜力评分53/100'}) == 70
        assert _potential_score_int({}) == 50

    def test_dim_adapter_no_int_crash_on_string(self):
        """convert_to_factors 对字符串 potential_score 不崩溃，factor 维正常"""
        dr = dict(MOCK_DIM_RESULTS)
        dr['valuation'] = {
            'status_description': {
                'composite_rating': 0.8, 'potential_score': '潜力评分80/100',
                'potential_strength': 80, 'dividend_yield': 5.0,
                'revenue_growth': 25, 'valuation_deviation': -5,
            },
            'judgment': {'overall_direction': 1, 'continuous_value': 0.7},
        }
        dims_factor = convert_to_factors(dr, MOCK_TAGS)
        assert 'factor' in dims_factor
        assert dims_factor['factor']['direction'] == 1  # 80>=70 → 看多
        assert dims_factor['factor']['strength'] == 0.8
        assert dims_factor['valuation']['direction'] == 1  # composite>=0.5 → 看多

    def test_dim7_evaluate_structure(self):
        """dim7 evaluate 返回完整 status_description/judgment/audit（mock ecm）"""
        import pandas as pd
        from app.opportunity_atlas.dimensions.dim7_valuation_engine import Dim7ValuationEngine
        engine = Dim7ValuationEngine.__new__(Dim7ValuationEngine)
        engine._dm = None
        engine._comp_percentile = None
        engine._industry_mean = {}
        engine._fcf_percentile = None
        engine._potential_tables = {}
        engine._get_dm = lambda: type('_D', (), {'cache': mock.Mock()})()

        class _FakeECM:
            def get_cached_daily_basic(self, *a, **k):
                return pd.DataFrame()
            def get_cached_income(self, *a, **k):
                return pd.DataFrame()
            def get_cached_balancesheet(self, *a, **k):
                return pd.DataFrame()
            def get_cached_cashflow(self, *a, **k):
                return pd.DataFrame()
            def get_cached_fina_indicator(self, *a, **k):
                return pd.DataFrame()
            def get_cached_finance_report(self, *a, **k):
                return pd.DataFrame()

        ecm = _FakeECM()
        engine._get_dm = lambda: type('_D', (), {'cache': ecm})()
        with mock.patch('app.data.DataManager',
                        return_value=mock.Mock(get_stock_industry=mock.Mock(return_value=None))):
            result = engine.evaluate({}, {'ts_code': '000001.SZ'})
        assert 'status_description' in result
        assert 'judgment' in result
        assert 'audit' in result
        assert 'valuation_level' in result['judgment']
        assert 'potential_strength' in result['status_description']
        assert isinstance(result['status_description']['potential_strength'], (int, float))
