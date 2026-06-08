"""
"数据缓存管理 API 路由
提供缓存状态检查、手动刷新、同步控制等功能"
"""
import os
from app.utils.error_handlers import handle_exceptions
from flask import Blueprint, jsonify, request
from app import db
from app.data import DataManager
from app.models import Stock, DailyData
from datetime import datetime

cache_bp = Blueprint('cache', __name__, url_prefix='/api/cache')
@handle_exceptions
@cache_bp.route('/sync', methods=['POST'])
def sync_data():
    """同步数据"""
    try:
        ts_code = request.json.get('ts_code')
        start_date = request.json.get('start_date')
        end_date = request.json.get('end_date')
        force_refresh = request.json.get('force_refresh', False)
        
        data_manager = DataManager()
        
        # 同步股票列表
        stock_count = data_manager.sync_stock_list()
        
        daily_count = 0
        
        if ts_code:
            # 同步单只股票
            daily_count = data_manager.sync_daily_data(
                ts_code, 
                use_cache=not force_refresh,
                start_date=start_date,
                end_date=end_date
            )
        else:
            # 同步所有股票
            daily_count = data_manager.sync_all_daily_data()
        
        return jsonify({
            'success': True,
            'data': {
                'stock_count': stock_count,
                'daily_count': daily_count,
                'ts_code': ts_code,
                'start_date': start_date,
                'end_date': end_date
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500
@handle_exceptions
@cache_bp.route('/data/<ts_code>', methods=['GET'])
def get_cached_data(ts_code):
    """获取缓存数据"""
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        data_manager = DataManager()
        cached_df = data_manager.get_cached_daily_data(ts_code, start_date, end_date)
        
        # 转换为字典列表
        data = cached_df.to_dict('records')
        
        return jsonify({
            'success': True,
            'data': data,
            'count': len(data)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500
@handle_exceptions
@cache_bp.route('/stats', methods=['GET'])
def get_cache_stats():
    """获取缓存统计"""
    try:
        data_manager = DataManager()
        stats_df = data_manager.get_cache_stats()
        
        # 获取PostgreSQL数据统计
        stock_count = Stock.query.count()
        daily_count = DailyData.query.count()
        
        # 转换为字典
        result = {
            'postgres': {
                'stock_count': int(stock_count),
                'daily_count': int(daily_count)
            }
        }
        
        if not stats_df.empty:
            for col in stats_df.columns:
                value = stats_df.iloc[0][col]
                # 转换数值类型为Python原生类型
                if hasattr(value, 'item'):
                    value = value.item()
                elif hasattr(value, 'astype'):
                    value = int(value) if value.is_integer() else float(value)
                result[col] = value
        
        return jsonify({
            'success': True,
            'data': result
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500
@handle_exceptions
@cache_bp.route('/strategy', methods=['GET'])
def get_cache_strategy():
    """获取缓存策略配置"""
    return jsonify({
        'success': True,
        'data': {
            'strategy': '3-tier-cache',
            'layers': [
                'Redis (热点数据)',
                'DuckDB (主缓存)',
                'PostgreSQL (持久化)',
                'Tushare API (数据源)'
            ],
            'priority': 'Redis → DuckDB → PostgreSQL → API',
            'redis_ttl': '1小时',
            'cache_preload': '支持缓存预热',
            'invalidation': '支持时间过期和手动清除'
        }
    })
@handle_exceptions
@cache_bp.route('/warmup', methods=['POST'])
def warmup_cache():
    """缓存预热"""
    try:
        data_manager = DataManager()
        data_manager.preload_cache()
        
        return jsonify({
            'success': True,
            'message': '缓存预热完成'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500
@handle_exceptions
@cache_bp.route('/invalidate', methods=['POST'])
def invalidate_cache():
    """清除缓存"""
    try:
        ts_code = request.json.get('ts_code')
        days = request.json.get('days', 30)
        
        data_manager = DataManager()
        
        if ts_code:
            data_manager.cache.redis_cache.invalidate_daily(ts_code)
        else:
            data_manager.cache.invalidate_old_data(days)
        
        return jsonify({
            'success': True,
            'message': f'缓存清除成功 (保留最近{days}天)'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500
@handle_exceptions
@cache_bp.route('/batch', methods=['POST'])
def batch_sync():
    """批量同步"""
    try:
        limit = request.json.get('limit', 50)
        skip_existing = request.json.get('skip_existing', True)
        shuffle = request.json.get('shuffle', True)
        
        import subprocess
        import sys
        
        # 调用批量同步脚本 - 使用绝对路径
        current_dir = os.path.dirname(os.path.abspath(__file__))
        script_path = os.path.join(current_dir, '..', '..', 'bulk_sync.py')
        script_path = os.path.abspath(script_path)
        
        cmd = [
            sys.executable, 
            script_path,
            '--limit', str(limit)
        ]
        
        if skip_existing:
            cmd.append('--skip-existing')
        if shuffle:
            cmd.append('--shuffle')
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        return jsonify({
            'success': True,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'exit_code': result.returncode
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500
