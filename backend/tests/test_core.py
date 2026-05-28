"""
核心技术模块单元测试
测试 TechnicalIndicatorEngine 和 SignalGenerator
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta


def _make_test_data(rows=100):
    """生成测试用的DataFrame"""
    np.random.seed(42)
    base_price = 10.0
    dates = [(datetime.now() - timedelta(days=i)).strftime('%Y%m%d') for i in range(rows)]
    dates.reverse()
    
    prices = base_price + np.cumsum(np.random.randn(rows) * 0.2)
    data = {
        'ts_code': ['000001.SZ'] * rows,
        'trade_date': dates,
        'open': prices + np.random.randn(rows) * 0.1,
        'high': prices + np.abs(np.random.randn(rows)) * 0.2 + 0.1,
        'low': prices - np.abs(np.random.randn(rows)) * 0.2 - 0.1,
        'close': prices,
        'vol': np.random.randint(500000, 2000000, rows),
        'amount': prices * np.random.randint(500000, 2000000, rows),
        'pct_chg': np.random.randn(rows) * 2,
    }
    return pd.DataFrame(data)


def test_ma_calculation():
    """测试MA（移动平均线）计算"""
    from app.indicators import TechnicalIndicatorEngine
    engine = TechnicalIndicatorEngine()
    
    df = _make_test_data(50)
    result = engine.calculate_ma(df)
    
    assert 'ma5' in result.columns, "MA5列缺失"
    assert 'ma10' in result.columns, "MA10列缺失"
    assert 'ma20' in result.columns, "MA20列缺失"
    
    assert pd.notna(result['ma5'].iloc[-1]), "MA5最后一个值应为有效数字"
    assert pd.notna(result['ma10'].iloc[-1]), "MA10最后一个值应为有效数字"
    assert pd.notna(result['ma20'].iloc[-1]), "MA20最后一个值应为有效数字"
    
    assert result['ma5'].iloc[-1] > 0, "MA5应大于0"
    
    print("✅ test_ma_calculation PASSED")


def test_macd_calculation():
    """测试MACD计算"""
    from app.indicators import TechnicalIndicatorEngine
    engine = TechnicalIndicatorEngine()
    
    df = _make_test_data(60)
    result = engine.calculate_macd(df)
    
    assert 'macd_dif' in result.columns, "MACD_DIF列缺失"
    assert 'macd_dea' in result.columns, "MACD_DEA列缺失"
    assert 'macd_hist' in result.columns, "MACD_HIST列缺失"
    
    assert pd.notna(result['macd_dif'].iloc[-1]), "MACD_DIF最后一个值应为有效数字"
    assert pd.notna(result['macd_dea'].iloc[-1]), "MACD_DEA最后一个值应为有效数字"
    assert pd.notna(result['macd_hist'].iloc[-1]), "MACD_HIST最后一个值应为有效数字"
    
    assert result['macd_hist'].iloc[-1] == 2 * (result['macd_dif'].iloc[-1] - result['macd_dea'].iloc[-1]), "HIST应等于2*(DIF-DEA)"
    
    print("✅ test_macd_calculation PASSED")


def test_rsi_calculation():
    """测试RSI计算"""
    from app.indicators import TechnicalIndicatorEngine
    engine = TechnicalIndicatorEngine()
    
    df = _make_test_data(50)
    result = engine.calculate_rsi(df)
    
    assert 'rsi14' in result.columns, "RSI14列缺失"
    
    last_rsi = result['rsi14'].iloc[-1]
    assert pd.notna(last_rsi), "RSI最后一个值应为有效数字"
    assert 0 <= last_rsi <= 100, f"RSI应在0-100范围内, 当前值: {last_rsi}"
    
    print("✅ test_rsi_calculation PASSED")


def test_kdj_calculation():
    """测试KDJ计算"""
    from app.indicators import TechnicalIndicatorEngine
    engine = TechnicalIndicatorEngine()
    
    df = _make_test_data(50)
    result = engine.calculate_kdj(df)
    
    assert 'kdj_k' in result.columns, "KDJ_K列缺失"
    assert 'kdj_d' in result.columns, "KDJ_D列缺失"
    assert 'kdj_j' in result.columns, "KDJ_J列缺失"
    
    assert pd.notna(result['kdj_k'].iloc[-1]), "KDJ_K最后一个值应为有效数字"
    assert pd.notna(result['kdj_d'].iloc[-1]), "KDJ_D最后一个值应为有效数字"
    assert pd.notna(result['kdj_j'].iloc[-1]), "KDJ_J最后一个值应为有效数字"
    
    assert 0 <= result['kdj_k'].iloc[-1] <= 100, "KDJ_K应在0-100"
    assert 0 <= result['kdj_d'].iloc[-1] <= 100, "KDJ_D应在0-100"
    
    print("✅ test_kdj_calculation PASSED")


def test_boll_calculation():
    """测试BOLL（布林带）计算"""
    from app.indicators import TechnicalIndicatorEngine
    engine = TechnicalIndicatorEngine()
    
    df = _make_test_data(50)
    result = engine.calculate_boll(df)
    
    assert 'boll_upper' in result.columns, "BOLL_UP列缺失"
    assert 'boll_mid' in result.columns, "BOLL_MID列缺失"
    assert 'boll_lower' in result.columns, "BOLL_LOW列缺失"
    
    last_mid = result['boll_mid'].iloc[-1]
    last_up = result['boll_upper'].iloc[-1]
    last_low = result['boll_lower'].iloc[-1]
    
    assert pd.notna(last_mid), "BOLL_MID最后一个值应为有效数字"
    assert pd.notna(last_up), "BOLL_UP最后一个值应为有效数字"
    assert pd.notna(last_low), "BOLL_LOW最后一个值应为有效数字"
    
    assert last_up > last_mid > last_low, "BOLL上轨 > 中轨 > 下轨"
    
    print("✅ test_boll_calculation PASSED")


def test_vol_indicators():
    """测试成交量指标计算"""
    from app.indicators import TechnicalIndicatorEngine
    engine = TechnicalIndicatorEngine()
    
    df = _make_test_data(50)
    result = engine.calculate_vol_indicators(df)
    
    assert 'vol_ma5' in result.columns, "VOL_MA5列缺失"
    assert 'vol_ma10' in result.columns, "VOL_MA10列缺失"
    
    assert pd.notna(result['vol_ma5'].iloc[-1]), "VOL_MA5最后一个值应为有效数字"
    assert pd.notna(result['vol_ma10'].iloc[-1]), "VOL_MA10最后一个值应为有效数字"
    
    print("✅ test_vol_indicators PASSED")


def test_calculate_all():
    """测试全量指标计算"""
    from app.indicators import TechnicalIndicatorEngine
    engine = TechnicalIndicatorEngine()
    
    df = _make_test_data(100)
    result = engine.calculate_all_indicators(df)
    
    expected_cols = ['ma5', 'ma10', 'ma20', 'macd_dif', 'macd_dea', 'macd_hist',
                     'rsi14', 'kdj_k', 'kdj_d', 'kdj_j',
                     'boll_upper', 'boll_mid', 'boll_lower',
                     'vol_ma5', 'vol_ma10']
    
    for col in expected_cols:
        assert col in result.columns, f"{col}列缺失"
    
    assert len(result) == len(df), "结果行数应与输入一致"
    
    print("✅ test_calculate_all PASSED")


def test_get_latest_indicators():
    """测试获取最新指标快照"""
    from app.indicators import TechnicalIndicatorEngine
    engine = TechnicalIndicatorEngine()
    
    df = _make_test_data(100)
    df_full = engine.calculate_all_indicators(df)
    latest = engine.get_latest_indicators(df_full)
    
    assert isinstance(latest, dict), "返回类型应为dict"
    assert 'ts_code' in latest, "应包含ts_code"
    assert latest['ts_code'] == '000001.SZ'
    
    indicator_keys = ['ma5', 'ma10', 'macd_dif', 'macd_dea', 'macd_hist', 'rsi14']
    for key in indicator_keys:
        assert key in latest, f"指标{key}缺失"
    
    print("✅ test_get_latest_indicators PASSED")


def test_small_dataset():
    """测试小数据集的边界情况"""
    from app.indicators import TechnicalIndicatorEngine
    engine = TechnicalIndicatorEngine()
    
    df = _make_test_data(5)
    result = engine.calculate_all_indicators(df)
    
    assert len(result) == 5, "小数据集应返回所有行"
    assert 'ma5' not in result.columns, "数据不足5行不应计算MA5"
    
    print("✅ test_small_dataset PASSED")


def test_signal_generator():
    """测试信号生成"""
    from app.indicators import TechnicalIndicatorEngine
    from app.signals import SignalGenerator
    engine = TechnicalIndicatorEngine()
    generator = SignalGenerator()
    
    df = _make_test_data(100)
    df_full = engine.calculate_all_indicators(df)
    
    signals = generator.generate_all_signals(df_full)
    
    assert isinstance(signals, list), "返回类型应为list"
    
    has_buy = any(s.get('signal_type') == 'buy' for s in signals)
    has_sell = any(s.get('signal_type') == 'sell' for s in signals)
    
    if len(signals) > 0:
        for s in signals:
            assert 'signal_type' in s, "信号应包含signal_type"
            assert 'signal_date' in s, "信号应包含signal_date"
            assert 'indicators' in s, "信号应包含indicators"
            assert s['signal_type'] in ('buy', 'sell', 'neutral'), f"未知信号类型: {s['signal_type']}"
    
    print(f"✅ test_signal_generator PASSED (生成{len(signals)}条信号)")


def test_signal_types():
    """测试各类信号生成逻辑"""
    from app.indicators import TechnicalIndicatorEngine
    from app.signals import SignalGenerator
    engine = TechnicalIndicatorEngine()
    generator = SignalGenerator()
    
    df = _make_test_data(100)
    df_full = engine.calculate_all_indicators(df)
    
    signals = generator.generate_all_signals(df_full)
    signal_types = set(
        s.get('indicators', {}).get('type', str(s.get('indicators')))
        for s in signals
    )
    
    print(f"  - 生成信号类型: {signal_types}")
    
    print("✅ test_signal_types PASSED")


def test_format_time():
    """测试时间戳格式化"""
    from app.routes.chart import _format_time
    
    ts_code = '000001.SZ'
    
    ts1 = _format_time(ts_code, '20260601')
    assert ts1 is not None, "YYYYMMDD格式应能解析"
    assert isinstance(ts1, int), "时间戳应为整数（秒级）"
    
    ts2 = _format_time(ts_code, pd.Timestamp('2026-06-01'))
    assert ts2 is not None, "pd.Timestamp应能解析"
    assert ts1 == ts2, "同一天的不同格式应返回相同时间戳"
    
    ts3 = _format_time(ts_code, None)
    assert ts3 is None, "None应返回None"
    
    print("✅ test_format_time PASSED")


def run_all():
    print("=" * 50)
    print("📊 核心技术模块单元测试")
    print("=" * 50)
    print()
    
    tests = [
        test_ma_calculation,
        test_macd_calculation,
        test_rsi_calculation,
        test_kdj_calculation,
        test_boll_calculation,
        test_vol_indicators,
        test_calculate_all,
        test_get_latest_indicators,
        test_small_dataset,
        test_signal_generator,
        test_signal_types,
        test_format_time,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"❌ {test.__name__} FAILED: {str(e)}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print()
    print("=" * 50)
    print(f"📋 测试结果: {passed}/{len(tests)} 通过, {failed}/{len(tests)} 失败")
    print("=" * 50)
    
    return failed == 0


if __name__ == '__main__':
    success = run_all()
    sys.exit(0 if success else 1)
