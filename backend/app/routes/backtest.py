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
from app.services.backtest_service import (
    CrossSectionalBacktestService,
    ParameterOptimizer,
    _init_task, get_progress, get_result,
    save_snapshot, list_snapshots,
)

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


# ══════════════════════════════════════════════════════════════
# B2: POST /strategy-run — 横截面回测提交（218号 Phase 1）
# ══════════════════════════════════════════════════════════════

@backtest_bp.route('/strategy-run', methods=['POST'])
@handle_exceptions
def run_strategy_backtest():
    """
    提交横截面回测任务（B2）
    对多只股票并行执行统一策略回测 → 横截面聚合 → 9区域输出

    请求体:
    {
        "ts_codes": ["000001.SZ", "000762.SZ", ...],
        "start_date": "20250101",
        "end_date": "20250630",
        "config": {
            "initial_capital": 100000,
            "commission_rate": 0.0003,
            "signal_method": "combined",
            "allocation_per_stock": 0.2
        }
    }
    """
    data = request.get_json() or {}
    ts_codes = data.get('ts_codes', [])
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    config = data.get('config', {})

    if not ts_codes:
        return jsonify({'success': False, 'error': 'ts_codes 不能为空'}), 400
    if not start_date or not end_date:
        return jsonify({'success': False, 'error': 'start_date 和 end_date 不能为空'}), 400

    # 创建任务
    task_id = _init_task(ts_codes, start_date, end_date)

    # 异步执行回测（在请求内同步执行，大池会阻塞 — 当前为同步，前端需loading）
    service = CrossSectionalBacktestService()
    result = service.run_strategy_backtest(
        ts_codes=ts_codes,
        start_date=start_date,
        end_date=end_date,
        config=config,
        task_id=task_id,
    )

    return jsonify(result)


# ══════════════════════════════════════════════════════════════
# B3: GET /strategy-run/<task_id>/progress — 进度轮询
# ══════════════════════════════════════════════════════════════

@backtest_bp.route('/strategy-run/<task_id>/progress', methods=['GET'])
@handle_exceptions
def get_strategy_run_progress(task_id):
    """
    获取回测任务进度（B3）

    进度阶段映射:
    pending → data_fetch → signal_gen → backtest → metrics → aggregation → done
    """
    progress = get_progress(task_id)
    if not progress:
        return jsonify({'success': False, 'error': f'任务 {task_id} 不存在'}), 404

    return jsonify({
        'success': True,
        'data': {
            'task_id': progress.task_id,
            'status': progress.status,
            'progress_pct': progress.progress_pct,
            'message': progress.message,
            'current_stock': progress.current_stock,
            'stocks_completed': progress.stocks_completed,
            'stocks_total': progress.stocks_total,
            'error': progress.error,
            'created_at': progress.created_at,
            'completed_at': progress.completed_at,
        }
    })


# ══════════════════════════════════════════════════════════════
# B4: GET /strategy-run/<task_id>/result — 完整结果（9区域）
# ══════════════════════════════════════════════════════════════

@backtest_bp.route('/strategy-run/<task_id>/result', methods=['GET'])
@handle_exceptions
def get_strategy_run_result(task_id):
    """
    获取回测完整结果（B4）
    返回9大区域：summary / equity_curve / trades / metrics / cross_sectional / benchmark / checkpoints / config / strategy_info
    """
    result = get_result(task_id)
    if not result:
        progress = get_progress(task_id)
        if progress:
            return jsonify({
                'success': False,
                'error': '任务尚未完成',
                'data': {'status': progress.status, 'progress_pct': progress.progress_pct}
            }), 409
        return jsonify({'success': False, 'error': f'任务 {task_id} 不存在'}), 404

    return jsonify(result)


# ══════════════════════════════════════════════════════════════
# 基准切换: GET /benchmark/<code> — 获取基准指数行情数据
# ══════════════════════════════════════════════════════════════

@backtest_bp.route('/benchmark/<code>', methods=['GET'])
@handle_exceptions
def get_benchmark_data(code):
    """
    获取基准指数行情数据（供前端对比展示）

    URL参数:
    - start_date: 开始日期
    - end_date: 结束日期
    """
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    service = create_benchmark_service()
    df = service.get_index_daily(code, start_date, end_date)

    if df.empty:
        return jsonify({'success': False, 'error': f'基准 {code} 数据为空'}), 404

    return jsonify({
        'success': True,
        'data': {
            'ts_code': code,
            'name': BenchmarkIndex.NAMES.get(code, code),
            'records': df.to_dict(orient='records'),
            'metrics': service.calculate_benchmark_metrics(code, start_date, end_date),
        }
    })


# ══════════════════════════════════════════════════════════════
# 指标配置同步: GET /indicator-config/<ts_code>
# ══════════════════════════════════════════════════════════════

@backtest_bp.route('/indicator-config/<ts_code>', methods=['GET'])
@handle_exceptions
def get_indicator_config(ts_code):
    """
    获取个股在 indicator-ide 中的指标配置（供回测引擎参考哪些指标应启用）

    从 indicator-ide 服务查询该股票保存的指标合约配置。
    若无配置，返回默认配置。
    """
    try:
        from app.services.indicator_contract import IndicatorContractParser
        parser = IndicatorContractParser()
        config = parser.load_stock_config(ts_code)
    except (ImportError, AttributeError):
        config = None

    # 尝试从数据库读取保存的配置
    if not config:
        try:
            from app.models import IndicatorConfig
            db_config = IndicatorConfig.query.filter_by(ts_code=ts_code).first()
            if db_config and db_config.config:
                config = db_config.config
        except Exception:
            pass

    # 返回默认配置兜底
    if not config:
        config = {
            'ts_code': ts_code,
            'indicators': {
                'chanlun': {'enabled': True},
                'volume_price': {'enabled': True},
                'chip': {'enabled': False},
                'factor': {'enabled': False},
                'bociasi': {'enabled': True},
                'long_term': {'enabled': False},
            },
            'params': {
                'chanlun_period': '30min',
                'ma_short': 5,
                'ma_long': 20,
            }
        }

    return jsonify({'success': True, 'data': config})


# ══════════════════════════════════════════════════════════════
# 参数优化: POST /optimize — 网格搜索参数
# ══════════════════════════════════════════════════════════════

@backtest_bp.route('/optimize', methods=['POST'])
@handle_exceptions
def optimize_parameters():
    """
    参数优化（网格搜索）

    请求体:
    {
        "ts_code": "000001.SZ",
        "start_date": "20250101",
        "end_date": "20250630",
        "param_grid": {
            "short_window": [3, 5, 10],
            "long_window": [15, 20, 30],
            "rsi_period": [7, 14, 21]
        },
        "config": { ... }
    }
    """
    data = request.get_json() or {}
    ts_code = data.get('ts_code')
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    param_grid = data.get('param_grid', {})
    config = data.get('config', {})

    if not ts_code:
        return jsonify({'success': False, 'error': 'ts_code 不能为空'}), 400
    if not param_grid:
        return jsonify({'success': False, 'error': 'param_grid 不能为空'}), 400

    result = ParameterOptimizer.grid_search(
        ts_code=ts_code,
        param_grid=param_grid,
        start_date=start_date or '20250101',
        end_date=end_date or '20250630',
        base_config=config,
    )

    return jsonify(result)


# ══════════════════════════════════════════════════════════════
# 参数优化: POST /optimize/apply — 应用优化后的参数
# ══════════════════════════════════════════════════════════════

@backtest_bp.route('/optimize/apply', methods=['POST'])
@handle_exceptions
def apply_optimized_params():
    """
    应用优化后的参数（保存快照 + 标记已应用）

    请求体:
    {
        "params": {"short_window": 5, "long_window": 20},
        "metrics": {"sharpe_ratio": 1.5, "total_return": 0.25},
        "note": "基于2025H1优化的均线参数"
    }
    """
    data = request.get_json() or {}
    params = data.get('params', {})
    metrics = data.get('metrics', {})
    note = data.get('note', '')

    if not params:
        return jsonify({'success': False, 'error': 'params 不能为空'}), 400

    snapshot = save_snapshot(params, metrics, note)

    return jsonify({
        'success': True,
        'data': snapshot,
        'message': f'参数快照已保存: {snapshot["id"]}'
    }), 201


# ══════════════════════════════════════════════════════════════
# 参数优化: POST /optimize/diff — 当前参数 vs 优化参数差异
# ══════════════════════════════════════════════════════════════

@backtest_bp.route('/optimize/diff', methods=['POST'])
@handle_exceptions
def compare_optimized_params():
    """
    对比当前参数与优化参数

    请求体:
    {
        "current_params": {"short_window": 5, "long_window": 20},
        "optimized_params": {"short_window": 10, "long_window": 30}
    }
    """
    data = request.get_json() or {}
    current = data.get('current_params', {})
    optimized = data.get('optimized_params', {})

    if not current and not optimized:
        return jsonify({'success': False, 'error': '请提供待对比的参数'}), 400

    all_keys = set(list(current.keys()) + list(optimized.keys()))
    diffs = {}
    for key in sorted(all_keys):
        old_val = current.get(key)
        new_val = optimized.get(key)
        if old_val != new_val:
            diffs[key] = {
                'current': old_val,
                'optimized': new_val,
                'change': new_val - old_val if isinstance(new_val, (int, float))
                          and isinstance(old_val, (int, float)) else None,
            }

    return jsonify({
        'success': True,
        'data': {
            'diff_count': len(diffs),
            'diffs': diffs,
            'current_params': current,
            'optimized_params': optimized,
        }
    })


# ══════════════════════════════════════════════════════════════
# 参数优化: GET /optimize/snapshots — 快照列表
# ══════════════════════════════════════════════════════════════

@backtest_bp.route('/optimize/snapshots', methods=['GET'])
@handle_exceptions
def get_optimize_snapshots():
    """
    获取参数快照历史列表
    """
    limit = request.args.get('limit', 20, type=int)
    snapshots = list_snapshots(limit)

    return jsonify({
        'success': True,
        'data': snapshots,
        'total': len(snapshots),
    })
