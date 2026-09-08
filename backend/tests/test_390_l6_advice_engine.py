"""L6 advice_engine 单元测试 — 390号方案§8"""
from app.opportunity_atlas.advice_engine import compute_advice


def test_enter_high_score():
    """综合分>=70 → enter，基础仓位0.6"""
    result = compute_advice(
        final_score=75.0,
        dims_factor={'emotion': {'direction': 0, 'strength': 0.5}},
        l0={'position_coeff': 1.0, 'hold_only': False, 'soft_risks': [],
            'hard_veto': False, 'emotion_position_cap': None},
        dim_results={},
        ts_code='000001.SZ',
    )
    assert result['max_position_ratio'] > 0
    assert result['hard_veto'] is False


def test_avoid_low_score():
    """综合分<30 → avoid，仓位0"""
    result = compute_advice(
        final_score=20.0,
        dims_factor={},
        l0={'position_coeff': 1.0, 'hold_only': False, 'soft_risks': [],
            'hard_veto': False, 'emotion_position_cap': None},
        dim_results={},
        ts_code='000001.SZ',
    )
    assert result['max_position_ratio'] == 0.0


def test_emotion_cap():
    """emotion_position_cap限制仓位上限"""
    result = compute_advice(
        final_score=80.0,
        dims_factor={'emotion': {'direction': 0, 'strength': 0.5}},
        l0={'position_coeff': 1.0, 'hold_only': False, 'soft_risks': [],
            'hard_veto': False, 'emotion_position_cap': 0.15},
        dim_results={},
        ts_code='000001.SZ',
    )
    assert result['max_position_ratio'] <= 0.15


def test_position_ceiling_30pct():
    """单票上限30%"""
    result = compute_advice(
        final_score=95.0,
        dims_factor={'emotion': {'direction': 0, 'strength': 0.5}},
        l0={'position_coeff': 1.0, 'hold_only': False, 'soft_risks': [],
            'hard_veto': False, 'emotion_position_cap': None},
        dim_results={},
        ts_code='000001.SZ',
    )
    assert result['max_position_ratio'] <= 0.30


def test_hold_only():
    """hold_only=True → position=0"""
    result = compute_advice(
        final_score=80.0,
        dims_factor={},
        l0={'position_coeff': 1.0, 'hold_only': True, 'soft_risks': [],
            'hard_veto': False, 'emotion_position_cap': None},
        dim_results={},
        ts_code='000001.SZ',
    )
    assert result['max_position_ratio'] == 0.0
    assert result['hold_only'] is True


def test_risk_fields_present():
    """输出包含§8.3定义的所有新增字段"""
    result = compute_advice(
        final_score=60.0,
        dims_factor={'emotion': {'direction': 0, 'strength': 0.5}},
        l0={'position_coeff': 1.0, 'hold_only': False, 'soft_risks': [],
            'hard_veto': False, 'emotion_position_cap': None},
        dim_results={},
        ts_code='000001.SZ',
    )
    for key in ('final_score', 'semantic_type', 'consensus_detail',
                'conflict_summary', 'reliability_summary'):
        assert key in result, f"Missing key: {key}"


def test_light_medium_score():
    """综合分55-69 → light，基础仓位0.4（rr=1.0时再×0.5=0.2）"""
    result = compute_advice(
        final_score=60.0,
        dims_factor={},
        l0={'position_coeff': 1.0, 'hold_only': False, 'soft_risks': [],
            'hard_veto': False, 'emotion_position_cap': None},
        dim_results={},
        ts_code='000001.SZ',
    )
    # base=0.4, rr=1.0→×0.5=0.2
    assert result['max_position_ratio'] == 0.2


def test_position_coeff_multiplier():
    """position_coeff=0.5 → 仓位减半"""
    result = compute_advice(
        final_score=80.0,
        dims_factor={},
        l0={'position_coeff': 0.5, 'hold_only': False, 'soft_risks': [],
            'hard_veto': False, 'emotion_position_cap': None},
        dim_results={},
        ts_code='000001.SZ',
    )
    # 80分 → base=0.6, ×0.5=0.30, rr=1.0→×0.5=0.15
    assert result['max_position_ratio'] == 0.15


def test_high_rr_boosts_position():
    """rr=2.0 → 盈亏比不打折（min(2.0/2, 1.0)=1.0）"""
    result = compute_advice(
        final_score=80.0,
        dims_factor={},
        l0={'position_coeff': 1.0, 'hold_only': False, 'soft_risks': [],
            'hard_veto': False, 'emotion_position_cap': None},
        dim_results={'risk': {'status_description': {'rr_value': 2.0}}},
        ts_code='000001.SZ',
    )
    # base=0.6, rr=2.0→×1.0=0.6, max 0.30
    assert result['max_position_ratio'] == 0.30
