"""390号方案新管线集成测试 — L1→L2→L3→L4→L5→L6 全链路"""
from app.opportunity_atlas.advice_engine import compute_advice
from app.opportunity_atlas.conflict_matrix import detect as conflict_detect
from app.opportunity_atlas.consensus_engine import compute as consensus_compute
from app.opportunity_atlas.dim_adapter import convert_to_factors
from app.opportunity_atlas.factor_arbiter import arbitrate as factor_arbitrate
from app.opportunity_atlas.reliability_assessor import assess

# 模拟 dim_results（8维度引擎输出）
MOCK_DIM_RESULTS = {
    'signal': {
        'judgment': {
            'attribute': {'code': 'right_confirmed', 'label': '右侧确认'},
            'maintenance': {'status': 'healthy'},
        }
    },
    'structure': {
        'status_description': {
            'overall_direction': 1,
            'continuous_value': 0.65,
            'chanlun_strength': 0.7,
            'level_cross_score': 0.8,
            'chanlun_phase': '健康',
            'trend_structure_signal': '123_buy_breakout',
            'trend_structure_strength': 'strong',
            'chanlun_strength_components': {'strength': 0.6, 'consistency': 0.7},
            'divergence_multi_algo': {
                'macd': {'agree': True},
                'rsi': {'agree': True},
                'kdj': {'agree': True},
            },
            'level_trends': '日线上升/周线上升',
        }
    },
    'volume_price': {
        'status_description': {
            'vp_state': '健康',
            'state_machine_direction': 'BUY',
            'state_machine_confidence': 0.75,
            'multi_timeframe_consistency': '一致',
            'resonance_score': 3,
            'entry_zone': [10.5, 11.0],
            'target_zone': [12.0, 13.0],
            'stage_name': 'UPTREND_ACTIVE',
            'stage_confidence': 0.8,
            'risk_notes': [],
            'three_laws': {'effort_result': '正常'},
        }
    },
    'chip_fund': {
        'status_description': {
            'phase': 'lifting',
            'phase_confidence': 0.7,
            'pde_conflict': False,
            'crowding_level': 'MEDIUM',
            'cost_profit_ratio': 0.5,
            'continuous_value': 0.6,
            'retail_institution': '主力建仓',
            'pde_price_position': 'mid',
            'pde_vote_ratio': {'bull': 60, 'bear': 40},
            'cost_concentration': '双峰分散',
        }
    },
    'emotion': {
        'status_description': {
            'market_phase': 'normal',
            'temperature': 55,
            'bociasi_fast_signal': 'NEUTRAL',
            'bociasi_slow_signal': 'BULLISH',
            'bociasi_slow_confidence': 0.6,
            'sector_heat': 'medium',
            'time_rhythm': '观望期',
        }
    },
    'risk': {
        'status_description': {
            'level': '中',
            'rr_value': 2.0,
            'atr_pct': 0.4,
            'support_price': 10.2,
            'resistance_price': 12.5,
            'invalidation': ['跌破10.2止损'],
            'volatility_percentile': 0.5,
            'dist_to_support_pct': -3.0,
            'dist_to_resistance_pct': 8.0,
            'dist_to_prev_high_pct': -5.0,
        }
    },
    'valuation': {
        'status_description': {
            'composite_rating': 0.8,
            'potential_score': 65,
            'dividend_yield': 2.5,
            'revenue_growth': 15,
            'pe_percentile_5y': 30,
            'pb_percentile_5y': 25,
            'valuation_deviation': -10,
            'asset_anchor_rating': 1,
            'earnings_anchor_rating': 0,
            'fina_health': {'value': 'good'},
        }
    },
}

MOCK_TAGS = {'right_side_confirm': '强确认'}

WEIGHTS = {
    'main_behavior': 0.25, 'structure_trend': 0.20,
    'volume_price': 0.20, 'valuation_quality': 0.15,
    'environment': 0.10, 'risk': 0.10,
}


def test_full_pipeline_produces_all_outputs():
    """全链路测试：L1→L2→L3→L4→L5→L6"""
    # L1
    dims_factor = convert_to_factors(MOCK_DIM_RESULTS, MOCK_TAGS)
    assert isinstance(dims_factor, dict)
    assert 'structure' in dims_factor
    assert 'direction' in dims_factor['structure']

    # L2
    reliability = assess(dims_factor, MOCK_DIM_RESULTS)
    assert isinstance(reliability, dict)
    assert all(0 <= v <= 1 for v in reliability.values())

    # L3
    consensus = consensus_compute(dims_factor, reliability, WEIGHTS, emotion_phase='normal')
    assert 'consensus_rate' in consensus
    assert 'direction' in consensus

    # L4
    conflict = conflict_detect(dims_factor, MOCK_TAGS, MOCK_DIM_RESULTS,
                               consensus_rate=abs(consensus.get('consensus_rate', 0)))
    assert 'fatal_to_veto' in conflict
    assert 'warn_for_semantic' in conflict
    assert 'semantic_type' in conflict

    # L5
    arb_result = factor_arbitrate(consensus, conflict, MOCK_TAGS, dims_factor, reliability)
    assert 'final_score' in arb_result
    assert 'opportunity_state' in arb_result
    assert arb_result['opportunity_state'] in ('enter', 'light', 'wait', 'avoid')

    # L6
    l0 = {'position_coeff': 1.0, 'hold_only': False, 'soft_risks': [],
           'hard_veto': False, 'emotion_position_cap': None}
    advice = compute_advice(
        final_score=arb_result['final_score'],
        dims_factor=dims_factor, l0=l0,
        dim_results=MOCK_DIM_RESULTS, ts_code='000001.SZ',
    )
    assert 'max_position_ratio' in advice
    assert 'target_zone' in advice  # 391号P1修复验证


def test_dim1_signal_factor():
    """L1: dim1 signal factor正确提取"""
    dims_factor = convert_to_factors(MOCK_DIM_RESULTS, MOCK_TAGS)
    assert dims_factor['signal']['direction'] == 1


def test_dim2_欲病降级():
    """L1: dim2 chanlun_phase=欲病 → strength降低"""
    dr = dict(MOCK_DIM_RESULTS)
    dr['structure'] = dict(dr['structure'])
    dr['structure']['status_description'] = dict(dr['structure']['status_description'])
    dr['structure']['status_description']['chanlun_phase'] = '欲病'
    dims_factor = convert_to_factors(dr, MOCK_TAGS)
    assert dims_factor['structure']['strength'] < 0.7


def test_reliability_structure_uses_correct_key():
    """L2: dim2 reliability正确读取chanlun_strength_components"""
    dims_factor = convert_to_factors(MOCK_DIM_RESULTS, MOCK_TAGS)
    reliability = assess(dims_factor, MOCK_DIM_RESULTS)
    assert 'structure' in reliability
    assert reliability['structure'] > 0


def test_advice_engine_target_zone():
    """391号P1: L6消费dim3 target_zone"""
    advice = compute_advice(
        final_score=60.0,
        dims_factor={'emotion': {'direction': 0, 'strength': 0.5}},
        l0={'position_coeff': 1.0, 'hold_only': False, 'soft_risks': [],
            'hard_veto': False, 'emotion_position_cap': None},
        dim_results=MOCK_DIM_RESULTS,
        ts_code='000001.SZ',
    )
    assert 'target_zone' in advice
    assert advice['target_zone'] == [12.0, 13.0]
