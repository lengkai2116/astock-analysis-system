"""测试 PatternEngine"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pytest
import pandas as pd
import numpy as np

from app.engine.patterns.engine import PatternEngine


@pytest.fixture
def sample_df():
    """创建样本K线数据"""
    dates = pd.date_range(start='2025-01-01', periods=100, freq='D')
    np.random.seed(42)

    close = 100 + np.cumsum(np.random.randn(100) * 2)
    open_price = close + np.random.randn(100) * 0.5
    high = np.maximum(close, open_price) + np.abs(np.random.randn(100) * 1)
    low = np.minimum(close, open_price) - np.abs(np.random.randn(100) * 1)
    volume = np.random.randint(1000000, 5000000, 100).astype(float)

    df = pd.DataFrame({
        'open': open_price,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume
    }, index=dates)

    return df


def test_engine_initialization():
    """测试引擎初始化"""
    engine = PatternEngine()
    assert engine is not None


def test_detect_all_returns_list(sample_df):
    """测试 detect_all 返回列表"""
    engine = PatternEngine()
    results = engine.detect_all(sample_df)
    assert isinstance(results, list)


def test_aggregate_returns_tuple(sample_df):
    """测试 aggregate 返回元组"""
    engine = PatternEngine()
    patterns = engine.detect_all(sample_df)
    score, details = engine.aggregate(patterns)
    assert isinstance(score, float)
    assert isinstance(details, dict)
    assert 0 <= score <= 10


def test_evaluate_returns_tuple(sample_df):
    """测试 evaluate 返回元组"""
    engine = PatternEngine()
    score, details = engine.evaluate(sample_df)
    assert isinstance(score, float)
    assert isinstance(details, dict)
    assert 0 <= score <= 10


def test_empty_dataframe():
    """测试空 DataFrame"""
    engine = PatternEngine()
    df = pd.DataFrame()
    score, details = engine.evaluate(df)
    assert score == 5.0  # 基础分
    assert details['pattern_count'] == 0


def test_aggregate_no_patterns():
    """测试无形态时聚合"""
    engine = PatternEngine()
    score, details = engine.aggregate([])
    assert score == 5.0


def test_aggregate_bullish_pattern():
    """测试看涨形态聚合"""
    from app.engine.patterns import PatternResult, PatternCategory, PatternStage

    engine = PatternEngine()
    patterns = [
        PatternResult(
            name='P-1-1',
            category=PatternCategory.VOLUME_PRICE,
            direction='bullish',
            strength=0.8,
            stage=PatternStage.COMPLETED,
            completion=1.0,
        )
    ]
    score, details = engine.aggregate(patterns)
    assert score > 5.0  # 应该高于基础分


def test_aggregate_bearish_pattern():
    """测试看跌形态聚合"""
    from app.engine.patterns import PatternResult, PatternCategory, PatternStage

    engine = PatternEngine()
    patterns = [
        PatternResult(
            name='P-2-1',
            category=PatternCategory.VOLUME_PRICE,
            direction='bearish',
            strength=0.8,
            stage=PatternStage.COMPLETED,
            completion=1.0,
        )
    ]
    score, details = engine.aggregate(patterns)
    assert score < 5.0  # 应该低于基础分


def test_aggregate_multi_resonance():
    """测试多形态共振加分"""
    from app.engine.patterns import PatternResult, PatternCategory, PatternStage

    engine = PatternEngine()
    patterns = [
        PatternResult(
            name=f'P-1-{i}',
            category=PatternCategory.VOLUME_PRICE,
            direction='bullish',
            strength=0.8,
            stage=PatternStage.COMPLETED,
            completion=1.0,
        )
        for i in range(1, 4)  # 3个看涨形态
    ]
    score, details = engine.aggregate(patterns)
    assert details['bull_count'] == 3
    # 应该有共振加分


def test_aggregate_blackhorse_extra_weight():
    """测试黑马型额外加权"""
    from app.engine.patterns import PatternResult, PatternCategory, PatternStage

    engine = PatternEngine()
    # 黑马型 P-3-1 weight=5.0, 额外 1.5x
    blackhorse = PatternResult(
        name='P-3-1',
        category=PatternCategory.BLACKHORSE,
        direction='bullish',
        strength=1.0,
        stage=PatternStage.COMPLETED,
        completion=1.0,
    )
    # 普通看涨 P-1-1 weight=3.0
    regular = PatternResult(
        name='P-1-1',
        category=PatternCategory.BULLISH_PATTERNS,
        direction='bullish',
        strength=1.0,
        stage=PatternStage.COMPLETED,
        completion=1.0,
    )

    score_bh, _ = engine.aggregate([blackhorse])
    score_reg, _ = engine.aggregate([regular])

    # 黑马型得分应更高（5.0 * 1.0 * 1.5 = 7.5 vs 3.0 * 1.0 = 3.0）
    assert score_bh > score_reg


def test_aggregate_score_clamped_to_10():
    """测试得分上限为 10"""
    from app.engine.patterns import PatternResult, PatternCategory, PatternStage

    engine = PatternEngine()
    # 创建大量强力看涨形态，分数应被限制在 10
    patterns = [
        PatternResult(
            name=f'P-3-{i}',
            category=PatternCategory.BLACKHORSE,
            direction='bullish',
            strength=1.0,
            stage=PatternStage.COMPLETED,
            completion=1.0,
        )
        for i in range(1, 11)
    ]
    score, details = engine.aggregate(patterns)
    assert score == 10.0


def test_aggregate_score_clamped_to_0():
    """测试得分下限为 0"""
    from app.engine.patterns import PatternResult, PatternCategory, PatternStage

    engine = PatternEngine()
    # 创建大量强力看跌形态，分数应被限制在 0
    patterns = [
        PatternResult(
            name=f'P-2-{i}',
            category=PatternCategory.BEARISH_PATTERNS,
            direction='bearish',
            strength=1.0,
            stage=PatternStage.COMPLETED,
            completion=1.0,
        )
        for i in range(1, 21)
    ]
    score, details = engine.aggregate(patterns)
    assert score == 0.0


def test_aggregate_bearish_resonance():
    """测试看跌共振减分"""
    from app.engine.patterns import PatternResult, PatternCategory, PatternStage

    engine = PatternEngine()
    patterns = [
        PatternResult(
            name=f'P-2-{i}',
            category=PatternCategory.BEARISH_PATTERNS,
            direction='bearish',
            strength=0.5,
            stage=PatternStage.COMPLETED,
            completion=1.0,
        )
        for i in range(1, 4)  # 3个看跌形态
    ]
    score, details = engine.aggregate(patterns)
    assert details['bear_count'] == 3
    assert score < 5.0


def test_aggregate_details_structure():
    """测试聚合详情结构"""
    from app.engine.patterns import PatternResult, PatternCategory, PatternStage

    engine = PatternEngine()
    patterns = [
        PatternResult(
            name='P-1-1',
            category=PatternCategory.BULLISH_PATTERNS,
            direction='bullish',
            strength=0.8,
            stage=PatternStage.COMPLETED,
            completion=1.0,
        )
    ]
    score, details = engine.aggregate(patterns)
    assert 'bull_count' in details
    assert 'bear_count' in details
    assert 'bull_strength_avg' in details
    assert 'bear_strength_avg' in details
    assert 'pattern_count' in details
    assert 'patterns' in details
    assert details['bull_count'] == 1
    assert details['bear_count'] == 0
    assert details['pattern_count'] == 1
    assert details['patterns'][0]['name'] == 'P-1-1'


def test_aggregate_neutral_direction_ignored():
    """测试中性方向不参与评分"""
    from app.engine.patterns import PatternResult, PatternCategory, PatternStage

    engine = PatternEngine()
    patterns = [
        PatternResult(
            name='unknown_pattern',
            category=PatternCategory.CANDLESTICK,
            direction='neutral',
            strength=0.8,
            stage=PatternStage.COMPLETED,
            completion=1.0,
        )
    ]
    score, details = engine.aggregate(patterns)
    assert score == 5.0  # 中性形态不影响分数
    assert details['bull_count'] == 0
    assert details['bear_count'] == 0


def test_weight_map_coverage():
    """测试权重映射覆盖所有 Wiki 形态"""
    from app.engine.patterns.engine import WEIGHT_MAP

    # 预涨型 20 种
    for i in range(1, 21):
        assert f'P-1-{i}' in WEIGHT_MAP

    # 预跌型 20 种
    for i in range(1, 21):
        assert f'P-2-{i}' in WEIGHT_MAP

    # 黑马型 10 种
    for i in range(1, 11):
        assert f'P-3-{i}' in WEIGHT_MAP

    # 状态 8 种
    for i in range(1, 9):
        assert f'S-{i}' in WEIGHT_MAP

    # 总计 58 种
    assert len(WEIGHT_MAP) == 58
