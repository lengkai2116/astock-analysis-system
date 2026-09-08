"""395号方案 Phase 1-4 — 六维三层描述构建器测试"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.opportunity_atlas.dimensions.dim8_summary_engine import (
    DIM_TEXT_BUILDERS,
    SIX_DIM_PRIORITY,
    _build_chip_fund_text,
    _build_emotion_text,
    _build_risk_text,
    _build_structure_text,
    _build_valuation_text,
    _build_volume_price_text,
    _translate_fields,
)

# ═══════════════════════════════════════════════════════════
# Phase 1：翻译函数测试
# ═══════════════════════════════════════════════════════════

def test_translate_fields_structure():
    sd = {'vs_ma': {'alignment': 'bullish'}, 'chanlun_direction': 'down'}
    result = _translate_fields('structure', sd)
    assert result['vs_ma']['alignment'] == '多头排列'
    assert result['chanlun_direction'] == '向下'


def test_translate_fields_volume_price():
    sd = {'stage_name': 'UPTREND_ACTIVE', 'state_machine_direction': 'BUY',
          'divergence': 'top', 'vol_state_trend': 'STABLE'}
    result = _translate_fields('volume_price', sd)
    assert result['stage_name'] == '上升趋势活跃期'
    assert result['state_machine_direction'] == '买入'
    assert result['divergence'] == '顶背离'
    assert result['vol_state_trend'] == '平量'


def test_translate_fields_chip_fund():
    sd = {'phase': 'raising', 'crowding_level': 'MODERATE', 'signal_type': 'first_buy'}
    result = _translate_fields('chip_fund', sd)
    assert result['phase'] == '拉升期'
    assert result['crowding_level'] == '适中'
    assert result['signal_type'] == '一买'


def test_translate_fields_emotion():
    sd = {'bociasi_quadrant': 'LL', 'bociasi_fast_signal': 'BUY',
          'bociasi_slow_signal': 'BULLISH', 'sector_heat': 'top_10'}
    result = _translate_fields('emotion', sd)
    assert result['bociasi_quadrant'] == '情绪底部，高性价比区间'
    assert result['bociasi_fast_signal'] == '看多'
    assert result['bociasi_slow_signal'] == '看多'
    assert result['sector_heat'] == '前10'


def test_translate_fields_nested_momentum():
    sd = {'momentum': {'level': 'BULL_MODERATE', 'interpretation': '多方偏强'}}
    result = _translate_fields('volume_price', sd)
    assert result['momentum']['level'] == '多方偏强'


def test_translate_fields_no_english_leak():
    """翻译后不应残留英文"""
    sd = {'stage_name': 'UPTREND_ACTIVE', 'vp_state': 'VP-1',
          'state_machine_direction': 'WATCH', 'divergence': 'none',
          'vol_state_trend': 'EXPANDING', 'vol_state_structure': 'BEARISH',
          'vol_state_institutional': 'RAISING', 'momentum': {'level': 'BULL_STRONG'}}
    result = _translate_fields('volume_price', sd)
    for key, val in result.items():
        if isinstance(val, str):
            for en in ['UPTREND', 'VP-', 'BUY', 'SELL', 'WATCH', 'STABLE',
                       'EXPANDING', 'BEARISH', 'RAISING', 'BULL']:
                assert en not in val, f"{key} contains English: {val}"


def test_six_dim_priority():
    assert SIX_DIM_PRIORITY[0] == 'risk'
    assert SIX_DIM_PRIORITY[-1] == 'chip_fund'
    assert len(SIX_DIM_PRIORITY) == 6


def test_dim_text_builders_complete():
    """6个构建器全部注册"""
    for dim in SIX_DIM_PRIORITY:
        assert dim in DIM_TEXT_BUILDERS, f"Missing builder for {dim}"


# ═══════════════════════════════════════════════════════════
# Phase 2：dim6 风险边界构建器测试
# ═══════════════════════════════════════════════════════════

def test_build_risk_text_full():
    sd = {
        'risk_level': '中', 'risk_detail': '无高风险源',
        'support_price': 11.39, 'dist_to_support_pct': -2.3,
        'resistance_price': 11.75, 'dist_to_resistance_pct': 0.9,
        'rr_value': 0.39, 'rr_level': '不划算',
        'volatility_level': 'medium', 'volatility_percentile': 0.45,
        'risk_factors': [], 'invalidation': ['收盘跌破11.39元'],
    }
    text = _build_risk_text(sd)
    assert '11.39' in text
    assert '0.39' in text
    assert '止损' in text
    assert '中' in text


def test_build_risk_text_with_factors():
    sd = {
        'risk_level': '高', 'risk_factors': ['财务：财务异常（高）', '事件风险：商誉减值（高）'],
        'support_price': 10.0, 'dist_to_support_pct': -5.0,
        'resistance_price': 11.0, 'dist_to_resistance_pct': 5.0,
        'rr_value': 1.0, 'rr_level': '一般',
        'volatility_level': 'high', 'volatility_percentile': 0.85,
        'invalidation': ['收盘跌破10元'],
    }
    text = _build_risk_text(sd)
    assert '财务' in text
    assert '高' in text


def test_build_risk_text_empty():
    """空输入不崩溃"""
    text = _build_risk_text({})
    assert len(text) > 0


def test_build_risk_text_with_events():
    sd = {
        'risk_level': '低', 'risk_factors': [],
        'support_price': 10.0, 'dist_to_support_pct': -2.0,
        'resistance_price': 10.5, 'dist_to_resistance_pct': 3.0,
        'rr_value': 1.5, 'rr_level': '可考虑',
        'volatility_level': 'low', 'volatility_percentile': 0.2,
        'invalidation': ['收盘跌破10元'],
        'event_summary': ['突破站上60日线'],
        'signal_days': 3,
    }
    text = _build_risk_text(sd)
    assert '突破站上60日线' in text
    assert '已持续3天' in text


# ═══════════════════════════════════════════════════════════
# Phase 3：dim7 估值构建器测试
# ═══════════════════════════════════════════════════════════

def test_build_valuation_text_full():
    # 使用实际字段名（valuation_level含composite字符串，pe_percentile为字符串）
    sd = {
        'valuation_level': '偏高（composite=-1.0）',
        'pe_percentile': 'PE近5年95.4%分位',
        'fcf_yield': '9.20%',
        'fina_health': '财务健康⚠️(suspicious)',
        'potential_score': '潜力评分92/100',
    }
    text = _build_valuation_text(sd)
    assert '偏高' in text
    assert '-1.0' in text
    assert '95.4' in text


def test_build_valuation_text_empty():
    text = _build_valuation_text({})
    assert len(text) > 0


# ═══════════════════════════════════════════════════════════
# Phase 3：dim5 情绪环境构建器测试
# ═══════════════════════════════════════════════════════════

def test_build_emotion_text_full():
    # 使用实际数据格式（旧字段名+字符串值）
    sd = {
        'market': '市场处于发酵（板块轮动活跃）',
        'bociasi_quick': '快线=BUY（0.65）',
        'bociasi_slow': '慢线=BULLISH（0.60）',
        'temperature': '62/100',
        'quadrant': 'LL — 情绪底部，高性价比区间',
        'sector': '板块银行（排名3，前10）',
        'stock': '个股积极（量价配合良好）',
    }
    text = _build_emotion_text(sd)
    assert '发酵' in text
    assert 'LL —' not in text  # 英文象限代码应被翻译（检查"LL —"模式而非子串）
    assert '情绪底部' in text
    assert '银行' in text
    assert '快慢线一致' in text


def test_build_emotion_text_empty():
    text = _build_emotion_text({})
    assert len(text) > 0


def test_build_emotion_text_partial_fields():
    sd = {'market': '市场处于冰点（极度低迷）', 'temperature': '15/100'}
    text = _build_emotion_text(sd)
    assert '冰点' in text
    assert '15/100' in text


# ═══════════════════════════════════════════════════════════
# Phase 4：dim2 结构位置构建器测试
# ═══════════════════════════════════════════════════════════

def test_build_structure_text_full():
    sd = {
        'vs_zhongshu': {'position': '上方', 'distance_pct': 4.7, 'duration_days': 81},
        'vs_ma': {'alignment': 'bullish', 'ma5': 11.62, 'bias_20': 2.3},
        'vs_indicator': {'rsi14': 65, 'rsi_status': '中性', 'kdj_status': '金叉', 'macd_status': '多头'},
        'chanlun_direction': 'down', 'chanlun_phase': '欲病', 'chanlun_strength': 0.54,
        'buy_sell_points': ['第二类买点'],
        'level_cross_score': 0.63,
    }
    sd = _translate_fields('structure', sd)  # 翻译后再传入构建器
    text = _build_structure_text(sd)
    assert '上方' in text
    assert '多头排列' in text  # 英文已翻译
    assert '欲病' in text
    assert '第二类买点' in text


def test_build_structure_text_empty():
    text = _build_structure_text({})
    assert len(text) > 0


# ═══════════════════════════════════════════════════════════
# Phase 4：dim3 量价健康构建器测试
# ═══════════════════════════════════════════════════════════

def test_build_volume_price_text_full():
    # 使用实际字段名（无stage_name，用vp_state/volume_energy/divergence/pattern/vol_ratio/health_score）
    sd = {
        'vp_state': 'VP-1 价涨量增(强势)',
        'volume_energy': '量比1.8，温和放量',
        'divergence': '顶背离',
        'pattern': '价涨量增(强势)',
        'vol_ratio': '量比1.8',
        'health_score': '8/10（健康）',
    }
    text = _build_volume_price_text(sd)
    assert 'VP-1' in text
    assert '价涨量增' in text
    assert '1.8' in text
    assert '顶背离' in text


def test_build_volume_price_text_empty():
    text = _build_volume_price_text({})
    assert len(text) > 0


# ═══════════════════════════════════════════════════════════
# Phase 4：dim4 资金筹码构建器测试
# ═══════════════════════════════════════════════════════════

def test_build_chip_fund_text_full():
    # 使用实际字段名（phase为字符串，cost_structure为字符串）
    sd = {
        'phase': 'raising（拉升期）',
        'fund_flow': '强流入',
        'cost_structure': '筹码单峰密集，获利盘75%',
        'signal': '一买信号',
    }
    text = _build_chip_fund_text(sd)
    assert '拉升' in text
    assert '强流入' in text
    assert '单峰密集' in text
    assert '一买' in text


def test_build_chip_fund_text_empty():
    text = _build_chip_fund_text({})
    assert len(text) > 0


def test_build_chip_fund_text_no_english():
    """验证所有英文值被翻译"""
    sd = {
        'phase': 'building', 'fund_flow_detail': 'inflow',
        'crowding_level': 'HIGH_CROWDING', 'signal_type': 'first_buy',
    }
    sd = _translate_fields('chip_fund', sd)  # 翻译后再传入构建器
    text = _build_chip_fund_text(sd)
    assert 'building' not in text
    assert 'inflow' not in text
    assert 'HIGH_CROWDING' not in text
    assert 'first_buy' not in text


# ═══════════════════════════════════════════════════════════
# Phase 6：边界测试
# ═══════════════════════════════════════════════════════════

def test_translate_fields_unknown_dim():
    """未知维度key不崩溃"""
    result = _translate_fields('unknown', {'foo': 'bar'})
    assert result == {'foo': 'bar'}


def test_translate_fields_empty_sd():
    """空status_description不崩溃"""
    result = _translate_fields('risk', {})
    assert result == {}


def test_build_risk_text_partial_fields():
    """只有部分字段时不崩溃"""
    text = _build_risk_text({'risk_level': '低'})
    assert '低' in text


def test_build_valuation_text_partial_fields():
    text = _build_valuation_text({'valuation_level_cn': '合理'})
    assert '合理' in text


def test_build_emotion_text_boundary():
    """边界：只有market字段"""
    text = _build_emotion_text({'market': '市场处于冰点（极度低迷）', 'temperature': '15/100'})
    assert '冰点' in text
    assert '15/100' in text


def test_build_structure_text_partial_fields():
    text = _build_structure_text({'vs_zhongshu': {'position': '下方'}})
    assert '下方' in text


def test_build_volume_price_text_partial_fields():
    # stage_name不被读取，用vp_state
    sd = _translate_fields('volume_price', {'vp_state': '缩量横盘'})
    text = _build_volume_price_text(sd)
    assert '缩量横盘' in text


def test_build_chip_fund_text_partial_fields():
    sd = _translate_fields('chip_fund', {'phase': 'distributing'})
    text = _build_chip_fund_text(sd)
    assert '出货期' in text


def test_six_dim_priority_no_duplicates():
    assert len(SIX_DIM_PRIORITY) == len(set(SIX_DIM_PRIORITY))


def test_all_builders_handle_empty_input():
    """所有构建器对空输入不崩溃"""
    for dim_key, builder in DIM_TEXT_BUILDERS.items():
        text = builder({})
        assert isinstance(text, str), f"{dim_key} builder didn't return str"
        assert len(text) > 0, f"{dim_key} builder returned empty string"
    import pytest
    pytest.main([__file__, '-v'])
