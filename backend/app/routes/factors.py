"""
因子库API路由
提供因子列表、计算、组合管理等功能
文件路径：backend/app/routes/factors.py
"""
from flask import Blueprint, request, jsonify, current_app
import pandas as pd
import json
from datetime import datetime
import sqlite3
import os
import logging

from app.factors import get_factor_registry, FactorCalculator
from app.data.factor_precompute import FactorPrecomputeManager
from app.data.enhanced_cache_manager import EnhancedCacheManager
from app.evaluation import FactorEvaluator
from app.engine import BacktestEngine, calculate_performance_metrics, get_strategy_pipeline

# 添加异常处理模块
from app.utils.error_handlers import handle_exceptions, safe_db_operation

factors_bp = Blueprint('factors', __name__, url_prefix='/api/factors')

logger = logging.getLogger(__name__)

registry = get_factor_registry()
calculator = FactorCalculator()
cache_manager = EnhancedCacheManager()
precompute_manager = FactorPrecomputeManager(cache_manager)
evaluator = FactorEvaluator()


def get_db_path():
    """获取数据库路径"""
    return os.path.join(os.getenv('DATA_DIR', '/data'), 'duckdb', 'stock_cache.db')


@factors_bp.route('', methods=['GET'])
@handle_exceptions
def get_all_factors():
    """
    获取所有因子列表
    支持按类别、来源、关键词筛选
    """
    try:
        category = request.args.get('category')
        source = request.args.get('source')
        search = request.args.get('search')
        
        if search:
            factor_names = registry.search_factors(search)
        else:
            factor_names = registry.list_factors(category=category, source=source)
        
        factors_info = []
        for name in factor_names:
            factor = registry.get_factor(name)
            if factor:
                factors_info.append(factor.get_info())
        
        return jsonify({
            'success': True,
            'data': factors_info,
            'total': len(factors_info)
        })
    except Exception as e:
        logger.error(f"获取因子列表失败: {str(e)}")
        raise


@factors_bp.route('/categories', methods=['GET'])
def get_categories():
    """
    获取所有因子类别
    """
    categories = registry.list_categories()
    category_info = []
    
    for cat in categories:
        count = len(registry.get_category_factors(cat))
        category_info.append({
            'name': cat,
            'count': count
        })
    
    return jsonify({
        'success': True,
        'data': category_info
    })


@factors_bp.route('/sources', methods=['GET'])
def get_sources():
    """
    获取所有来源
    """
    sources = registry.list_sources()
    source_info = []
    
    for src in sources:
        count = len(registry.get_source_factors(src))
        source_info.append({
            'name': src,
            'count': count
        })
    
    return jsonify({
        'success': True,
        'data': source_info
    })


@factors_bp.route('/<factor_name>', methods=['GET'])
def get_factor_detail(factor_name):
    """
    获取单个因子详情
    """
    factor = registry.get_factor(factor_name)
    
    if factor is None:
        return jsonify({
            'success': False,
            'error': f'因子 {factor_name} 不存在'
        }), 404
    
    return jsonify({
        'success': True,
        'data': factor.get_info()
    })


@factors_bp.route('/calculate/<factor_name>', methods=['POST'])
def calculate_single_factor(factor_name):
    """
    计算单个因子
    """
    try:
        data = request.json
        df = pd.DataFrame(data.get('data', []))
        params = data.get('params', {})
        
        factor_series = calculator.calculate_single_factor(df, factor_name, **params)
        
        if factor_series is None:
            return jsonify({
                'success': False,
                'error': '因子计算失败'
            }), 400
        
        result = factor_series.reset_index()
        result.columns = ['trade_date', 'value']
        
        return jsonify({
            'success': True,
            'data': result.to_dict(orient='records')
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@factors_bp.route('/calculate-combination', methods=['POST'])
def calculate_combination():
    """
    计算因子组合
    """
    try:
        data = request.json
        df = pd.DataFrame(data.get('data', []))
        factors_config = data.get('factors', [])
        
        result_df = calculator.calculate_multiple_factors(df, factors_config)
        
        if result_df.empty:
            return jsonify({
                'success': False,
                'error': '因子组合计算失败'
            }), 400
        
        result = result_df.reset_index()
        
        return jsonify({
            'success': True,
            'data': result.to_dict(orient='records'),
            'columns': list(result_df.columns)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@factors_bp.route('/evaluate', methods=['POST'])
def evaluate_factors():
    """
    评估因子质量
    计算IC、IR、换手率等指标
    """
    try:
        data = request.json
        factors_df = pd.DataFrame(data.get('factors_data', []))
        price_df = pd.DataFrame(data.get('price_data', []))
        periods = data.get('periods', [1, 5, 10])
        
        if factors_df.empty or price_df.empty:
            return jsonify({
                'success': False,
                'error': '数据不能为空'
            }), 400
        
        results = evaluator.evaluate_multiple_factors(factors_df, price_df, periods)
        
        return jsonify({
            'success': True,
            'data': results
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@factors_bp.route('/combinations', methods=['GET'])
def get_combinations():
    """
    获取因子组合列表
    """
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, description, factors, is_default, is_favorite, created_at, updated_at 
            FROM factor_combinations 
            ORDER BY is_default DESC, is_favorite DESC, id
        """)
        rows = cursor.fetchall()
        
        combinations = []
        for row in rows:
            try:
                factors = json.loads(row[3]) if row[3] else []
            except:
                factors = []
            
            combinations.append({
                'id': row[0],
                'name': row[1],
                'description': row[2],
                'factors': factors,
                'is_default': bool(row[4]),
                'is_favorite': bool(row[5]),
                'created_at': row[6],
                'updated_at': row[7]
            })
        
        return jsonify({
            'success': True,
            'data': combinations
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        conn.close()


@factors_bp.route('/combinations', methods=['POST'])
def save_combination():
    """
    保存因子组合
    """
    try:
        data = request.json
        name = data.get('name')
        description = data.get('description', '')
        factors = json.dumps(data.get('factors', []))
        is_favorite = data.get('is_favorite', False)
        
        db_path = get_db_path()
        conn = sqlite3.connect(db_path)
        
        try:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO factor_combinations (name, description, factors, is_favorite) 
                   VALUES (?, ?, ?, ?)""",
                (name, description, factors, is_favorite)
            )
            conn.commit()
            
            combo_id = cursor.lastrowid
            
            return jsonify({
                'success': True,
                'data': {'id': combo_id, 'name': name}
            })
        finally:
            conn.close()
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@factors_bp.route('/combinations/<int:combo_id>', methods=['PUT'])
def update_combination(combo_id):
    """
    更新因子组合
    """
    try:
        data = request.json
        name = data.get('name')
        description = data.get('description')
        factors = json.dumps(data.get('factors')) if data.get('factors') is not None else None
        is_favorite = data.get('is_favorite')
        
        db_path = get_db_path()
        conn = sqlite3.connect(db_path)
        
        try:
            cursor = conn.cursor()
            
            # 安全的字段白名单
            allowed_fields = {'name', 'description', 'factors', 'is_favorite'}
            update_fields = []
            update_values = []
            
            # 只允许更新预定义的字段，防止SQL注入
            if name is not None and 'name' in allowed_fields:
                update_fields.append("name = ?")
                update_values.append(name)
            if description is not None and 'description' in allowed_fields:
                update_fields.append("description = ?")
                update_values.append(description)
            if factors is not None and 'factors' in allowed_fields:
                update_fields.append("factors = ?")
                update_values.append(factors)
            if is_favorite is not None and 'is_favorite' in allowed_fields:
                update_fields.append("is_favorite = ?")
                update_values.append(is_favorite)
            
            if update_fields:
                update_fields.append("updated_at = CURRENT_TIMESTAMP")
                update_values.append(combo_id)
                # 使用参数化查询，字段名通过白名单验证
                cursor.execute(
                    f"UPDATE factor_combinations SET {', '.join(update_fields)} WHERE id = ?",
                    update_values
                )
                conn.commit()
            
            return jsonify({
                'success': True
            })
        finally:
            conn.close()
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@factors_bp.route('/combinations/<int:combo_id>', methods=['DELETE'])
def delete_combination(combo_id):
    """
    删除因子组合
    """
    try:
        db_path = get_db_path()
        conn = sqlite3.connect(db_path)
        
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM factor_combinations WHERE id = ?", (combo_id,))
            conn.commit()
            
            return jsonify({
                'success': True
            })
        finally:
            conn.close()
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@factors_bp.route('/combinations/<int:combo_id>/set-default', methods=['POST'])
def set_default_combination(combo_id):
    """
    设置默认组合
    """
    try:
        db_path = get_db_path()
        conn = sqlite3.connect(db_path)
        
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE factor_combinations SET is_default = 0")
            cursor.execute("UPDATE factor_combinations SET is_default = 1 WHERE id = ?", (combo_id,))
            conn.commit()
            
            return jsonify({
                'success': True
            })
        finally:
            conn.close()
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@factors_bp.route('/precompute', methods=['POST'])
def precompute_factors():
    """
    预计算因子
    批量计算并缓存因子数据
    """
    try:
        data = request.json
        ts_code = data.get('ts_code')
        df_data = data.get('data', [])
        factor_names = data.get('factors')
        
        if not ts_code or not df_data:
            return jsonify({
                'success': False,
                'error': '缺少必要参数'
            }), 400
        
        df = pd.DataFrame(df_data)
        
        if factor_names:
            results = {}
            for name in factor_names:
                success = precompute_manager.precompute_factor(ts_code, df, name)
                results[name] = success
        else:
            results = precompute_manager.precompute_all_factors(ts_code, df)
        
        success_count = sum(1 for v in results.values() if v)
        
        return jsonify({
            'success': True,
            'data': {
                'total': len(results),
                'success': success_count,
                'failed': len(results) - success_count,
                'results': results
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@factors_bp.route('/backtest', methods=['POST'])
def backtest_combination():
    """
    因子组合回测
    计算绩效指标
    """
    try:
        data = request.json
        price_data = pd.DataFrame(data.get('price_data', []))
        benchmark_data = data.get('benchmark_data')
        initial_capital = data.get('initial_capital', 100000)
        
        if price_data.empty:
            return jsonify({
                'success': False,
                'error': '价格数据不能为空'
            }), 400
        
        # 设置trade_date为索引
        if 'trade_date' in price_data.columns:
            price_data = price_data.set_index('trade_date')
        
        # 处理benchmark数据
        benchmark_df = None
        if benchmark_data:
            benchmark_df = pd.DataFrame(benchmark_data)
            if 'trade_date' in benchmark_df.columns:
                benchmark_df = benchmark_df.set_index('trade_date')
        
        # 运行回测
        engine = BacktestEngine(initial_capital=initial_capital)
        result = engine.run_simple_backtest(price_data, benchmark_data=benchmark_df)
        
        return jsonify({
            'success': True,
            'data': result.to_dict()
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@factors_bp.route('/strategies', methods=['GET'])
def list_strategies():
    """
    获取可用策略列表
    """
    try:
        pipeline = get_strategy_pipeline()
        available = pipeline.get_available_strategies()
        active = pipeline.list_strategies()
        
        return jsonify({
            'success': True,
            'data': {
                'available': available,
                'active': active
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@factors_bp.route('/strategies/pipeline/screen', methods=['POST'])
def run_strategy_screen():
    """
    运行策略筛选
    """
    try:
        data = request.json
        price_data = pd.DataFrame(data.get('price_data', []))
        
        if price_data.empty:
            return jsonify({
                'success': False,
                'error': '价格数据不能为空'
            }), 400
        
        if 'trade_date' in price_data.columns:
            price_data = price_data.set_index('trade_date')
        
        pipeline = get_strategy_pipeline()
        signals = pipeline.generate_combined_signals(price_data)
        
        return jsonify({
            'success': True,
            'data': {
                'signals': signals.to_dict() if not signals.empty else {},
                'message': '策略信号生成完成（当前为预留框架，实际策略待实现）'
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
