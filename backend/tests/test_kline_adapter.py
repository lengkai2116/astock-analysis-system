"""测试重构后的 KLinePatternAdapter（委托 PatternEngine）"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pytest
import pandas as pd
import numpy as np

from app.engine.patterns import PatternResult
from app.engine.patterns.adapters.kline_adapter import KLinePatternAdapter
from app.engine.patterns.engine import PatternEngine


@pytest.fixture
def adapter():
    return KLinePatternAdapter()


@pytest.fixture
def sample_df():
    """创建样本 K 线数据（100 条）"""
    dates = pd.date_range(start='2025-01-01', periods=100, freq='D')
    np.random.seed(42)
    close = 100 + np.cumsum(np.random.randn(100) * 2)
    open_price = close + np.random.randn(100) * 0.5
    high = np.maximum(close, open_price) + np.abs(np.random.randn(100) * 1)
    low = np.minimum(close, open_price) - np.abs(np.random.randn(100) * 1)
    volume = np.random.randint(1000000, 5000000, 100).astype(float)
    return pd.DataFrame({
        'open': open_price, 'high': high, 'low': low,
        'close': close, 'volume': volume,
    }, index=dates)


# ── 基础功能 ──

def test_adapter_initialization(adapter):
    """适配器初始化成功"""
    assert adapter is not None
    assert isinstance(adapter.engine, PatternEngine)


def test_detect_returns_list(adapter, sample_df):
    """detect() 返回 List[PatternResult]"""
    results = adapter.detect(sample_df)
    assert isinstance(results, list)
    for r in results:
        assert isinstance(r, PatternResult)


def test_detect_with_context(adapter, sample_df):
    """detect() 接受可选 context 参数"""
    ctx = {'stock_code': '600519', 'market': 'SH'}
    results = adapter.detect(sample_df, context=ctx)
    assert isinstance(results, list)


def test_detect_backward_compat(adapter, sample_df):
    """向后兼容：只传 df 不传 context 也能正常工作"""
    results = adapter.detect(sample_df)
    assert isinstance(results, list)


# ── evaluate ──

def test_evaluate_returns_tuple(adapter, sample_df):
    """evaluate() 返回 (score, details)"""
    score, details = adapter.evaluate(sample_df)
    assert isinstance(score, float)
    assert isinstance(details, dict)
    assert 0 <= score <= 10


def test_evaluate_with_context(adapter, sample_df):
    """evaluate() 接受 context 参数"""
    ctx = {'stock_code': '000001'}
    score, details = adapter.evaluate(sample_df, context=ctx)
    assert 0 <= score <= 10


# ── 边界条件 ──

def test_empty_dataframe(adapter):
    """空 DataFrame 不报错"""
    df = pd.DataFrame()
    results = adapter.detect(df)
    assert isinstance(results, list)
    assert len(results) == 0


def test_short_dataframe(adapter):
    """不足 3 条记录不报错"""
    df = pd.DataFrame({
        'open': [10.0, 10.5],
        'high': [11.0, 11.5],
        'low': [9.0, 9.5],
        'close': [10.5, 11.0],
        'volume': [1e6, 2e6],
    })
    results = adapter.detect(df)
    assert isinstance(results, list)


# ── 与引擎一致性 ──

def test_detect_equals_engine(adapter, sample_df):
    """适配器 detect 结果与直接调引擎一致"""
    engine_results = adapter.engine.detect_all(sample_df)
    adapter_results = adapter.detect(sample_df)
    assert len(adapter_results) == len(engine_results)
    for a, e in zip(adapter_results, engine_results):
        assert a.name == e.name
        assert a.direction == e.direction
        assert a.strength == e.strength


def test_evaluate_equals_engine(adapter, sample_df):
    """适配器 evaluate 结果与直接调引擎一致"""
    e_score, e_details = adapter.engine.evaluate(sample_df)
    a_score, a_details = adapter.evaluate(sample_df)
    assert a_score == e_score
    assert a_details['pattern_count'] == e_details['pattern_count']
