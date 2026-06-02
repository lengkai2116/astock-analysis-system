"""
回测API路由 V2
提供增强回测引擎的API接口
文件路径：backend/app/routes/backtest.py
"""
from flask import Blueprint, request, jsonify, current_app
import pandas as pd
import numpy as np
from datetime import datetime
import logging
from typing import Dict, List, Optional

from app.engine.backtest_v2 import (
    AShareBacktestEngine, 
    BacktestConfig, 
    BacktestResultV2,
    create_default_engine
)
from app.services.benchmark_service import (
    BenchmarkService, 
    BenchmarkIndex,
    create_benchmark_service
)
from app.data.tushare_provider import TushareProvider
from app.utils.error_handlers import handle_exceptions

backtest_bp = Blueprint('backtest', __name__, url_prefix='/api/v3/backtest')

logger = logging.getLogger(__name__)


@backtest_bp.route('/indices', methods=['GET'])
def get_available_indices():
    """
    获取支持的基准指数列表
    """
    try:
        service = create_benchmark_service()
        indices = service.get_index_list()
        
        return jsonify({
            'success': True,
            'data': indices
        })
    except Exception as e:
        logger.error(f"获取指数列表失败: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@backtest_bp.route('/indices/<ts_code>/info', methods=['GET'])
def get_index_info(ts_code):
    """
    获取指数基本信息
    """
    try:
        service = create_benchmark_service()
        info = service.get_index_basic_info(ts_code)
        
        if not info:
            return jsonify({
                'success': False,
                'error': f'指数 {ts_code} 不存在'
            }), 404
        
        return jsonify({
            'success': True,
            'data': info
        })
    except Exception as e:
        logger.error(f"获取指数信息失败: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@backtest_bp.route('/indices/<ts_code>/data', methods=['GET'])
def get_index_data(ts_code):
    """
    获取指数历史数据
    """
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        service = create_benchmark_service()
        df = service.get_index_daily(ts_code, start_date, end_date)
        
        if df.empty:
            return jsonify({
                'success': False,
                'error': '没有获取到数据'
            }), 404
        
        return jsonify({
            'success': True,
            'data': df.to_dict(orient='records')
        })
    except Exception as e:
        logger.error(f"获取指数数据失败: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@backtest_bp.route('/indices/<ts_code>/metrics', methods=['GET'])
def get_index_metrics(ts_code):
    """
    计算指数绩效指标
    """
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        service = create_benchmark_service()
        metrics = service.calculate_benchmark_metrics(ts_code, start_date, end_date)
        
        if not metrics:
            return jsonify({
                'success': False,
                'error': '计算失败'
            }), 400
        
        return jsonify({
            'success': True,
            'data': metrics
        })
    except Exception as e:
        logger.error(f"计算指数指标失败: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@backtest_bp.route('/compare', methods=['POST'])
def compare_indices():
    """
    对比多个指数绩效
    """
    try:
        data = request.json
        ts_codes = data.get('ts_codes', [BenchmarkIndex.HS300, BenchmarkIndex.ZZ500])
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        
        service = create_benchmark_service()
        df = service.compare_benchmarks(ts_codes, start_date, end_date)
        
        if df.empty:
            return jsonify({
                'success': False,
                'error': '对比失败'
            }), 400
        
        return jsonify({
            'success': True,
            'data': df.to_dict(orient='records')
        })
    except Exception as e:
        logger.error(f"对比指数失败: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@backtest_bp.route('/run', methods=['POST'])
@handle_exceptions
def run_backtest():
    """
    运行回测
    """
    try:
        data = request.json
        
        price_data = data.get('price_data', [])
        signals_data = data.get('signals', [])
        benchmark_ts_code = data.get('benchmark', BenchmarkIndex.HS300)
        
        config_data = data.get('config', {})
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        
        if not price_data:
            return jsonify({
                'success': False,
                'error': '价格数据不能为空'
            }), 400
        
        price_df = pd.DataFrame(price_data)
        if 'trade_date' not in price_df.columns and 'date' in price_df.columns:
            price_df = price_df.rename(columns={'date': 'trade_date'})
        
        signals_df = pd.DataFrame(signals_data) if signals_data else None
        
        config = BacktestConfig(
            initial_capital=config_data.get('initial_capital', 100000),
            commission_rate=config_data.get('commission_rate', 0.0003),
            stamp_duty_rate=config_data.get('stamp_duty_rate', 0.001),
            slippage_rate=config_data.get('slippage_rate', 0.0001),
            min_commission=config_data.get('min_commission', 5.0),
            max_position=config_data.get('max_position', 10),
            price_limit_check=config_data.get('price_limit_check', True)
        )
        
        engine = AShareBacktestEngine(config)
        
        benchmark_df = None
        if benchmark_ts_code:
            benchmark_service = create_benchmark_service()
            benchmark_df = benchmark_service.get_index_daily(
                benchmark_ts_code, start_date, end_date
            )
        
        result = engine.run_backtest(
            price_data=price_df,
            signals=signals_df,
            benchmark_data=benchmark_df,
            start_date=start_date,
            end_date=end_date
        )
        
        return jsonify({
            'success': True,
            'data': result.to_dict()
        })
    
    except Exception as e:
        logger.error(f"回测运行失败: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@backtest_bp.route('/simple', methods=['POST'])
@handle_exceptions
def run_simple_backtest():
    """
    简单回测（使用信号列表）
    """
    try:
        data = request.json
        
        price_data = data.get('price_data', [])
        trades = data.get('trades', [])
        initial_capital = data.get('initial_capital', 100000)
        
        if not price_data:
            return jsonify({
                'success': False,
                'error': '价格数据不能为空'
            }), 400
        
        price_df = pd.DataFrame(price_data)
        if 'trade_date' not in price_df.columns and 'date' in price_df.columns:
            price_df = price_df.rename(columns={'date': 'trade_date'})
        
        engine = create_default_engine()
        
        signals_df = None
        if trades:
            signals_df = pd.DataFrame(trades)
            if 'trade_date' not in signals_df.columns and 'date' in signals_df.columns:
                signals_df = signals_df.rename(columns={'date': 'trade_date'})
        
        result = engine.run_backtest(
            price_data=price_df,
            signals=signals_df,
            start_date=data.get('start_date'),
            end_date=data.get('end_date')
        )
        
        return jsonify({
            'success': True,
            'data': result.to_dict()
        })
    
    except Exception as e:
        logger.error(f"简单回测失败: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@backtest_bp.route('/equity-curve', methods=['POST'])
@handle_exceptions
def get_equity_curve():
    """
    获取权益曲线
    """
    try:
        data = request.json
        
        price_data = data.get('price_data', [])
        signals_data = data.get('signals', [])
        
        if not price_data:
            return jsonify({
                'success': False,
                'error': '价格数据不能为空'
            }), 400
        
        price_df = pd.DataFrame(price_data)
        if 'trade_date' not in price_df.columns and 'date' in price_df.columns:
            price_df = price_df.rename(columns={'date': 'trade_date'})
        
        signals_df = pd.DataFrame(signals_data) if signals_data else None
        
        engine = create_default_engine()
        result = engine.run_backtest(price_df, signals_df)
        
        equity_curve = []
        for equity in result.daily_equity:
            equity_curve.append({
                'date': equity.date,
                'total_value': equity.total_value,
                'position_value': equity.position_value,
                'cash': equity.cash,
                'daily_return': equity.daily_return,
                'total_pnl': equity.total_pnl
            })
        
        return jsonify({
            'success': True,
            'data': equity_curve
        })
    
    except Exception as e:
        logger.error(f"获取权益曲线失败: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@backtest_bp.route('/trades', methods=['POST'])
@handle_exceptions
def get_trades_analysis():
    """
    获取交易记录分析
    """
    try:
        data = request.json
        
        price_data = data.get('price_data', [])
        signals_data = data.get('signals', [])
        
        if not price_data:
            return jsonify({
                'success': False,
                'error': '价格数据不能为空'
            }), 400
        
        price_df = pd.DataFrame(price_data)
        if 'trade_date' not in price_df.columns and 'date' in price_df.columns:
            price_df = price_df.rename(columns={'date': 'trade_date'})
        
        signals_df = pd.DataFrame(signals_data) if signals_data else None
        
        engine = create_default_engine()
        result = engine.run_backtest(price_df, signals_df)
        
        trades = []
        for trade in result.trades:
            trades.append({
                'trade_id': trade.trade_id,
                'date': trade.date,
                'ts_code': trade.ts_code,
                'side': trade.side.value,
                'price': trade.price,
                'quantity': trade.quantity,
                'amount': trade.amount,
                'commission': trade.commission,
                'stamp_duty': trade.stamp_duty,
                'slippage': trade.slippage,
                'total_cost': trade.total_cost
            })
        
        return jsonify({
            'success': True,
            'data': {
                'trades': trades,
                'summary': {
                    'total_trades': len(trades),
                    'buy_trades': sum(1 for t in trades if t['side'] == 'buy'),
                    'sell_trades': sum(1 for t in trades if t['side'] == 'sell'),
                    'total_commission': result.metrics.get('total_commission', 0),
                    'total_stamp_duty': result.metrics.get('total_stamp_duty', 0),
                    'total_slippage': result.metrics.get('total_slippage', 0)
                }
            }
        })
    
    except Exception as e:
        logger.error(f"获取交易记录失败: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@backtest_bp.route('/metrics', methods=['POST'])
@handle_exceptions
def calculate_metrics():
    """
    计算绩效指标
    """
    try:
        data = request.json
        
        equity_curve = data.get('equity_curve', [])
        benchmark_data = data.get('benchmark_data', [])
        
        if not equity_curve:
            return jsonify({
                'success': False,
                'error': '权益曲线数据不能为空'
            }), 400
        
        equity_df = pd.DataFrame(equity_curve)
        if 'date' in equity_df.columns and 'trade_date' not in equity_df.columns:
            equity_df = equity_df.rename(columns={'date': 'trade_date'})
        
        total_value = equity_df['total_value']
        if len(total_value) < 2:
            return jsonify({
                'success': False,
                'error': '数据点不足'
            }), 400
        
        initial_capital = total_value.iloc[0]
        final_value = total_value.iloc[-1]
        total_return = (final_value - initial_capital) / initial_capital
        
        trading_days = len(total_value)
        annual_return = (1 + total_return) ** (252 / trading_days) - 1
        
        daily_returns = total_value.pct_change().dropna()
        volatility = daily_returns.std() * np.sqrt(252)
        
        cummax = total_value.cummax()
        drawdown = (cummax - total_value) / cummax
        max_drawdown = drawdown.max()
        
        risk_free_rate = 0.03
        excess_returns = daily_returns - risk_free_rate / 252
        sharpe_ratio = np.sqrt(252) * excess_returns.mean() / (daily_returns.std() + 1e-10)
        
        downside_returns = daily_returns[daily_returns < 0]
        downside_std = downside_returns.std() if len(downside_returns) > 0 else 1e-10
        sortino_ratio = np.sqrt(252) * excess_returns.mean() / downside_std
        
        win_rate = (daily_returns > 0).mean()
        
        metrics = {
            'initial_capital': float(initial_capital),
            'final_value': float(final_value),
            'total_return': float(total_return),
            'annual_return': float(annual_return),
            'volatility': float(volatility),
            'max_drawdown': float(max_drawdown),
            'sharpe_ratio': float(sharpe_ratio),
            'sortino_ratio': float(sortino_ratio),
            'win_rate': float(win_rate),
            'trading_days': trading_days
        }
        
        if benchmark_data:
            benchmark_df = pd.DataFrame(benchmark_data)
            if 'close' in benchmark_df.columns and len(benchmark_df) > 1:
                bm_return = (benchmark_df['close'].iloc[-1] / benchmark_df['close'].iloc[0]) - 1
                metrics['benchmark_return'] = float(bm_return)
                metrics['excess_return'] = float(total_return - bm_return)
        
        return jsonify({
            'success': True,
            'data': metrics
        })
    
    except Exception as e:
        logger.error(f"计算指标失败: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@backtest_bp.route('/benchmark/run', methods=['POST'])
@handle_exceptions
def run_with_benchmark():
    """
    带基准对比的回测
    """
    try:
        data = request.json
        
        price_data = data.get('price_data', [])
        signals_data = data.get('signals', [])
        benchmark_ts_code = data.get('benchmark', BenchmarkIndex.HS300)
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        
        if not price_data:
            return jsonify({
                'success': False,
                'error': '价格数据不能为空'
            }), 400
        
        price_df = pd.DataFrame(price_data)
        if 'trade_date' not in price_df.columns and 'date' in price_df.columns:
            price_df = price_df.rename(columns={'date': 'trade_date'})
        
        signals_df = pd.DataFrame(signals_data) if signals_data else None
        
        engine = create_default_engine()
        benchmark_service = create_benchmark_service()
        
        benchmark_df = benchmark_service.get_index_daily(
            benchmark_ts_code, start_date, end_date
        )
        
        result = engine.run_backtest(
            price_data=price_df,
            signals=signals_df,
            benchmark_data=benchmark_df,
            start_date=start_date,
            end_date=end_date
        )
        
        result_dict = result.to_dict()
        result_dict['benchmark_info'] = {
            'ts_code': benchmark_ts_code,
            'name': BenchmarkIndex.NAMES.get(benchmark_ts_code, benchmark_ts_code)
        }
        
        return jsonify({
            'success': True,
            'data': result_dict
        })
    
    except Exception as e:
        logger.error(f"带基准回测失败: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@backtest_bp.route('/config/options', methods=['GET'])
def get_config_options():
    """
    获取回测配置选项
    """
    return jsonify({
        'success': True,
        'data': {
            'commission_rates': [
                {'label': '万三(默认)', 'value': 0.0003},
                {'label': '万二', 'value': 0.0002},
                {'label': '万一', 'value': 0.0001},
                {'label': '万五', 'value': 0.0005}
            ],
            'slippage_rates': [
                {'label': '万一(默认)', 'value': 0.0001},
                {'label': '万二', 'value': 0.0002},
                {'label': '万三', 'value': 0.0003},
                {'label': '无滑点', 'value': 0.0}
            ],
            'max_positions': [1, 3, 5, 10, 15, 20],
            'initial_capitals': [10000, 50000, 100000, 200000, 500000, 1000000]
        }
    })


@backtest_bp.route('/status', methods=['GET'])
def get_status():
    """
    获取回测服务状态
    """
    try:
        provider = TushareProvider()
        success, msg = provider.test_connection()
        
        return jsonify({
            'success': True,
            'data': {
                'tushare_connected': success,
                'tushare_status': msg,
                'engine_version': 'V2',
                'supported_rules': [
                    'T+1交易',
                    '涨跌停限制',
                    '手续费(默认万三)',
                    '印花税(卖出千分之一)',
                    '滑点(默认万一)'
                ]
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
