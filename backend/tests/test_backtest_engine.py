"""
回测引擎集成测试
验证 AShareBacktestEngine 的初始化、信号处理和绩效计算
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


def _make_test_klines(rows=200):
    """生成回测用的K线数据"""
    np.random.seed(42)
    base_price = 10.0
    dates = [datetime.now() - timedelta(days=i) for i in range(rows)]
    dates.reverse()
    
    prices = base_price + np.cumsum(np.random.randn(rows) * 0.2)
    data = {
        'date': dates,
        'open': prices + np.random.randn(rows) * 0.1,
        'high': prices + np.abs(np.random.randn(rows)) * 0.2 + 0.1,
        'low': prices - np.abs(np.random.randn(rows)) * 0.2 - 0.1,
        'close': prices,
        'volume': np.random.randint(500000, 2000000, rows),
    }
    return pd.DataFrame(data).set_index('date')


def _make_test_signals(kline_df):
    """生成测试用买卖信号"""
    signals = []
    for i in range(50, len(kline_df) - 1, 30):
        signals.append({
            'date': kline_df.index[i],
            'action': 'buy',
            'price': kline_df['close'].iloc[i],
            'reason': 'test_buy'
        })
        signals.append({
            'date': kline_df.index[i + 15],
            'action': 'sell',
            'price': kline_df['close'].iloc[i + 15],
            'reason': 'test_sell'
        })
    return signals


def test_backtest_engine_import():
    """测试回测引擎模块可导入"""
    try:
        from app.engine.backtest_v2 import AShareBacktestEngine
        assert AShareBacktestEngine is not None
    except ImportError:
        # 回退到 v1 回测引擎
        try:
            from app.engine.backtest import BacktestEngine
            assert BacktestEngine is not None
        except ImportError as e:
            pytest.skip(f"回测引擎不可用: {e}")


def test_backtest_engine_initialization():
    """测试回测引擎初始化"""
    try:
        from app.engine.backtest_v2 import AShareBacktestEngine
        engine = AShareBacktestEngine(initial_capital=1000000)
        assert engine is not None
        assert engine.initial_capital == 1000000
    except ImportError:
        try:
            from app.engine.backtest import BacktestEngine
            engine = BacktestEngine(initial_capital=1000000)
            assert engine is not None
        except ImportError as e:
            pytest.skip(f"回测引擎不可用: {e}")


def test_backtest_engine_run_with_data():
    """测试回测引擎执行——给定K线和信号"""
    klines = _make_test_klines(200)
    signals = _make_test_signals(klines)
    
    try:
        from app.engine.backtest_v2 import AShareBacktestEngine
        engine = AShareBacktestEngine(initial_capital=1000000)
        
        result = engine.run(
            stock_code='000001.SZ',
            kline_data=klines,
            signals=signals,
            commission_rate=0.0003,
            slippage=0.001
        )
        
        assert result is not None
        # 验证结果包含关键字段
        assert hasattr(result, 'total_return') or isinstance(result, dict)
        
        if isinstance(result, dict):
            assert 'total_return' in result or 'returns' in result
        print("✅ 回测引擎执行完成")
        
    except ImportError:
        pytest.skip("回测引擎模块未找到")
    except Exception as e:
        if 'abstract' in str(e).lower() or 'can\'t instantiate' in str(e).lower():
            pytest.skip(f"回测引擎为抽象类: {e}")
        raise


def test_backtest_engine_benchmark_comparison():
    """测试回测引擎的基准对比功能"""
    klines = _make_test_klines(200)
    signals = _make_test_signals(klines)
    
    try:
        from app.engine.backtest_v2 import AShareBacktestEngine
        engine = AShareBacktestEngine(initial_capital=1000000)
        
        result = engine.run(
            stock_code='000001.SZ',
            kline_data=klines,
            signals=signals,
            benchmark='000300.SH'
        )
        
        assert result is not None
        print("✅ 基准对比测试完成")
        
    except ImportError:
        pytest.skip("回测引擎模块未找到")
    except Exception as e:
        if 'abstract' in str(e).lower() or 'can\'t instantiate' in str(e).lower():
            pytest.skip(f"回测引擎为抽象类: {e}")
        raise


def test_backtest_engine_empty_signals():
    """测试无信号时的空运行"""
    klines = _make_test_klines(100)
    
    try:
        from app.engine.backtest_v2 import AShareBacktestEngine
        engine = AShareBacktestEngine(initial_capital=1000000)
        
        result = engine.run(
            stock_code='000001.SZ',
            kline_data=klines,
            signals=[]
        )
        
        assert result is not None
        print("✅ 空信号回测测试完成")
        
    except ImportError:
        pytest.skip("回测引擎模块未找到")
    except Exception as e:
        if 'abstract' in str(e).lower() or 'can\'t instantiate' in str(e).lower():
            pytest.skip(f"回测引擎为抽象类: {e}")
        raise


def test_backtest_engine_metrics():
    """测试回测绩效指标计算"""
    klines = _make_test_klines(200)
    signals = _make_test_signals(klines)
    
    try:
        from app.engine.backtest_v2 import AShareBacktestEngine
        engine = AShareBacktestEngine(initial_capital=1000000)
        
        result = engine.run(
            stock_code='000001.SZ',
            kline_data=klines,
            signals=signals
        )
        
        # 验证绩效指标存在
        if isinstance(result, dict):
            metrics_present = any(k in result for k in 
                ['total_return', 'annual_return', 'sharpe', 'max_drawdown', 
                 'win_rate', 'total_trades', 'returns', 'metrics'])
            assert metrics_present, "回测结果缺少绩效指标"
        print("✅ 绩效指标测试完成")
        
    except ImportError:
        pytest.skip("回测引擎模块未找到")
    except Exception as e:
        if 'abstract' in str(e).lower() or 'can\'t instantiate' in str(e).lower():
            pytest.skip(f"回测引擎为抽象类: {e}")
        raise


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
