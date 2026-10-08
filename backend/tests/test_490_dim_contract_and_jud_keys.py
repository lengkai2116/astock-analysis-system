"""490号：SIG dim2-dim7 输出项 × JUD 消费键契约修复（A/B/C 三类）单元测试

覆盖：
  A 类（引擎补产出，消费侧契约不变）——由探针 _490_sig_contract_probe.py 以真实数据核验；
     本文件覆盖消费侧对新增键的取值正确性（dim3/dim5/dim7）。
  B 类（路径/形态/键名错位）——legacy dims 三维 state、temp/vol/股息 数值键、
     JUD 内 signal 桥接 state 提取。
  C 类（跨维取错）——conflict_matrix 容器与子键、多周期一致性跨维主源、
     cross_validate dim_engine→legacy 的 chip 维。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.conflict_matrix import detect as conflict_detect  # noqa: E402
from app.opportunity_atlas.cross_validate import (  # noqa: E402
    _convert_dim_engine_to_legacy,
)
from app.opportunity_atlas.dim_adapter import (  # noqa: E402
    convert_to_factors,
    multi_level_consistency,
)
from app.opportunity_atlas.status_engine import _dim_state_for_signal  # noqa: E402


def _dim_results_full():
    """构造一次「所有冲突规则可触发」的 dim_results（键位置均按引擎真实契约）"""
    return {
        'structure': {
            'status_description': {
                'chanlun_phase': '欲病',
                'divergence_type': '趋势背驰',
                'divergence_strength': 0.8,
                'trend_structure_signal': '123_buy_breakout',
                'level_cross_score': 0.5,
                'consistency_component': 1.0,
                'chanlun_strength_components': {'strength': 0.8},
                'divergence_multi_algo': {'macd': {'agree': True},
                                          'strength': {'agree': True},
                                          'dual_confirmed': {'agree': True}},
                'multi_level': {'direction_map': {'daily': 'up', 'weekly': 'down'}},
            },
            'judgment': {'overall_direction': 1, 'continuous_value': 0.7},
        },
        'volume_price': {
            'status_description': {
                'vp_state': '健康',
                'state_machine_direction': 'BUY',
                'state_machine_confidence': 0.8,
                'resonance_score': 3,
                'stage_confidence': 0.8,
                'three_laws': {'effort_result': '正常'},
                'divergence_type': 'top',
                'vol_ratio_value': 0.4,
                'risk_notes': ['跌破防守位'],
                'entry_zone': [10.0, 10.5],
                'target_zone': [12.0, 13.0],
            },
            'judgment': {'state': '健康', 'overall_direction': 1, 'continuous_value': 0.8},
        },
        'chip_fund': {
            'status_description': {
                'phase': '建仓（PhaseDetector）',
                'phase_confidence': 0.7,
                'pde_conflict': False,
                'pde_vote_ratio': {'building': 3},
                'pde_price_position': 'mid_zone',
                'crowding_level': 'HIGH_CROWDING',
                'retail_institution': '主力出货（散户追入）',
                # 509号 #J6：C4+ 改读独立枚举 retail_tendency（非展示文本）
                'retail_tendency': 'distribution',
                'cost_concentration': 'concentrating',
                'cost_profit_ratio': 0.85,
            },
            'judgment': {'phase': 'building', 'direction': 'inflow',
                         'overall_direction': 1, 'continuous_value': 0.6},
        },
        'emotion': {
            'status_description': {
                'market_phase': 'ice',
                'temperature': '冰冷12.0/100',
                'temperature_value': 12.0,
                'sector_heat': 'none',
                'bociasi_fast_signal': 'BUY',
                'bociasi_slow_signal': 'BEARISH',
                'bociasi_slow_confidence': 0.7,
                'bociasi_quadrant': 'LH',
            },
            'judgment': {'overall_light': 'yellow', 'overall_direction': 1,
                         'continuous_value': 0.6},
        },
        'risk': {
            'status_description': {
                'risk_level': '高', 'atr_pct': 0.8, 'rr_value': 0.5,
                'volatility_percentile': 0.5,
                'dist_to_support_pct': -3.0, 'dist_to_resistance_pct': 8.0,
                'dist_to_prev_high_pct': -5.0,
            },
            'judgment': {'level': '高', 'overall_direction': 0, 'continuous_value': 0.5},
        },
        'valuation': {
            'status_description': {
                'valuation_level': '极度低估（composite=0.8）',
                'composite_rating': 0.8,
                'valuation_deviation': -10.0,
                'dividend_yield': '股息率5.0%',
                'dividend_yield_value': 5.0,
                'revenue_growth': '营收同比25.0%',
                'revenue_growth_value': 25.0,
                'pe_percentile_5y': 30, 'pb_percentile_5y': 25, 'ps_percentile_5y': 20,
                'asset_anchor_rating': -1.0, 'earnings_anchor_rating': 1.0,
                'potential_strength': 65,
            },
            'judgment': {'valuation_level': {'value': 'extreme_low'},
                         'fina_health': {'value': 'healthy'},
                         'overall_direction': 1, 'continuous_value': 0.6},
        },
    }


def _dims_factor_full():
    return {
        'structure': {'direction': 1, 'strength': 0.7},
        'vp': {'direction': 1, 'strength': 0.8},
        'chip_fund': {'direction': 1, 'strength': 0.7},
        'emotion': {'direction': -1, 'strength': 0.7},
        'risk': {'direction': -1, 'strength': 0.4},
        'valuation': {'direction': 1, 'strength': 0.8},
    }


# ── C 类：conflict_matrix 容器/子键 ──

def test_conflict_matrix_fires_with_real_containers():
    dr = _dim_results_full()
    # consensus_rate=0.8：C10 需 >0.7（C5 需 <0.5，故不在本用例断言）
    res = conflict_detect(_dims_factor_full(), {'right_side_confirm': '强确认'},
                          dr, consensus_rate=0.8)
    all_conf = ' | '.join(res['all_conflicts'])
    # C1/C2b/C3/C4/C4+/C4++/C6/C10/C11+/C12/C14 全部应命中真实输入
    for tag in ('C1:', 'C2b:', 'C3:', 'C4:', 'C4+:', 'C4++:', 'C6:', 'C10:', 'C11+:', 'C12:', 'C14:'):
        assert tag in all_conf, f'{tag} 未触发（容器/子键仍错位）：{all_conf}'
    # C2 已按 490 号删除（无产出源）
    assert 'C2:' not in all_conf


def test_conflict_matrix_safe_when_dims_absent():
    """缺维/空 sd 不得抛异常、不得误报（防回归）"""
    res = conflict_detect({}, {}, {}, consensus_rate=0.5)
    assert res['all_conflicts'] == []
    res2 = conflict_detect({}, {}, {'structure': {}, 'volume_price': None,
                                    'chip_fund': {}, 'risk': {}, 'valuation': {}},
                           consensus_rate=0.5)
    assert isinstance(res2['all_conflicts'], list)


def test_conflict_c11_uses_structured_divergence_and_real_vol_ratio():
    dr = _dim_results_full()
    res = conflict_detect(_dims_factor_full(), {}, dr, consensus_rate=0.5,
                          vol_ratio=1.0)  # 入参故意为 1.0，真实值须取自 sd.vol_ratio_value=0.4
    assert any(c.startswith('C11+:') for c in res['all_conflicts'])


# ── B 类：legacy dims 三维 state ──

def test_legacy_dims_states_from_real_keys():
    from app.opportunity_atlas.status_engine import StatusEngine
    dims = StatusEngine.__new__(StatusEngine)._convert_to_dims_format(_dim_results_full(), {})
    assert dims['vp']['state'] == '健康'          # dim3 judgment.state（原读 judgment.vp_state 恒"中性"）
    assert dims['chip_fund']['state'] == '流入'    # dim4 judgment.direction（原读 flow_direction 恒"中性"）
    assert dims['emotion']['state'] == '冰点'      # dim5 sd.market_phase（原读 judgment.phase 恒"正常"）
    assert dims['valuation']['state'] == '极度低估'  # dim7 judgment.valuation_level.value
    assert dims['finance']['state'] == '健康'      # dim7 judgment.fina_health.value


def test_dim_state_for_signal_mapping():
    assert _dim_state_for_signal('structure', {'structure': '上升'}, {}) == '上升'
    assert _dim_state_for_signal('volume_price', {'state': '背离'}, {}) == '背离'
    assert _dim_state_for_signal('chip_fund', {'direction': 'outflow'}, {}) == '流出'
    assert _dim_state_for_signal('emotion', {}, {'market_phase': 'ferment'}) == '发酵'
    assert _dim_state_for_signal('risk', {'risk_level': '高'}, {}) == '高'
    assert _dim_state_for_signal('valuation',
                                 {'valuation_level': {'value': 'low'}}, {}) == '低估'
    assert _dim_state_for_signal('structure', {}, {}) == ''


# ── C 类：多周期一致性跨维主源 + cross_validate chip 维 ──

def test_multi_level_consistency_helper():
    dr = _dim_results_full()
    c, sub = multi_level_consistency(dr)
    assert c == '冲突（BUY+SELL）' and sub == 'BUY+SELL'
    dr2 = {'structure': {'status_description': {
        'multi_level': {'direction_map': {'daily': 'up', 'weekly': 'up', 'hourly': 'up'}}}}}
    assert multi_level_consistency(dr2) == ('一致（BUY）', '')
    assert multi_level_consistency({}) == ('', '')


def test_cross_validate_dim_engine_to_legacy_includes_chip():
    der = {
        'structure': {'judgment': {'overall_direction': 1}},
        'volume_price': {'judgment': {'overall_direction': 1}},
        'chip_fund': {'judgment': {'overall_direction': 1, 'phase': 'building'}},
        'emotion': {'judgment': {'overall_light': 'green'}},
        'signal': {'judgment': {'overall_direction': 0}},
    }
    dims = _convert_dim_engine_to_legacy(der)
    assert 'chip' in dims and dims['chip']['direction'] == 'up'   # 原读 fund_chip → 筹码维永缺
    assert 'chanlun' in dims and 'volume_price' in dims


# ── A 类消费侧：dim3/dim5/dim7 真实键取值 ──

def test_adapter_dim3_uses_state_machine_and_resonance():
    dr = _dim_results_full()
    f = convert_to_factors(dr, {})
    # state_machine_direction=BUY → dir 1；但日/周多周期冲突（BUY+SELL）→ dir 归零、strength 0.3
    assert f['vp']['direction'] == 0
    assert abs(f['vp']['strength'] - 0.3) < 1e-6


def test_adapter_dim3_without_multi_level_conflict():
    dr = _dim_results_full()
    dr['structure']['status_description'].pop('multi_level')
    f = convert_to_factors(dr, {})
    assert f['vp']['direction'] == 1
    # 0.7*0.8 + 0.3*((3+5)/10) = 0.8
    assert abs(f['vp']['strength'] - 0.8) < 1e-6
    assert f['vp']['vol_ratio'] == 0.4        # 数值键（原文本"量比1.5"解析失败→0.0）


def test_adapter_dim5_phase_and_temperature_value():
    dr = _dim_results_full()
    f = convert_to_factors(dr, {})
    assert f['emotion']['direction'] == 1     # ice→看多（均值回归口径）
    # |12-50|/50 = 0.76，快慢线不一致（BUY/BEARISH）无共振加成，slow=BEARISH 且 dir>0 → ×0.6
    assert abs(f['emotion']['strength'] - 0.76 * 0.6) < 1e-6
    assert f['emotion']['slow_confidence'] == 0.7


def test_adapter_dim7_composite_and_value_keys():
    dr = _dim_results_full()
    f = convert_to_factors(dr, {})
    assert f['valuation']['direction'] == 1   # composite_rating=0.8 ≥ 0.5（原未落 sd → 恒 0）
    assert f['valuation']['strength'] > 0.5   # 0.6*0.4 + 0.4*1.0 + 0.1(股息) + 0.1(营收) → clamp
    assert f['valuation']['asset_anchor_rating'] == '-1.0'
    assert f['valuation']['earnings_anchor_rating'] == '1.0'


def test_reliability_uses_real_sources():
    from app.opportunity_atlas.reliability_assessor import assess
    dr = _dim_results_full()
    f = convert_to_factors(dr, {})
    rel = assess(f, dr)
    # 491号（R7）：量价维可靠性键为 'vp'（L1 因子键）；冗余历史键 'volume_price' 已清理
    assert set(rel.keys()) >= {'structure', 'vp', 'chip_fund', 'emotion',
                               'risk', 'valuation'}
    assert 'volume_price' not in rel
    # dim2 三源：level_cross 0.5 + consistency 1.0 + chanlun 0.8 → 0.25+0.3+0.16=0.71，
    # 多算法 3 项全同意 +0.1 → 0.81
    assert abs(rel['structure'] - 0.81) < 0.02
    # dim4：pde_conflict=False 且 phase_confidence 0.7>0.6 → 0.8
    assert abs(rel['chip_fund'] - 0.8) < 1e-6
    # dim5：bociasi_slow_confidence 0.7，sector_heat='none' → ×0.8 = 0.56
    assert abs(rel['emotion'] - 0.56) < 1e-6
