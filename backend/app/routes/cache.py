"""
"数据缓存管理 API 路由
提供缓存状态检查、手动刷新、同步控制等功能"
"""
import os
from app.utils.error_handlers import handle_exceptions
from flask import Blueprint, jsonify, request
from app import db
from app.data import DataManager
from app.models import Stock
from datetime import datetime

cache_bp = Blueprint('cache', __name__, url_prefix='/api/cache')
@handle_exceptions
@cache_bp.route('/sync', methods=['POST'])
def sync_data():
    """提交同步请求（通过 sync_requests 队列通知 daemon 异步执行）"""
    try:
        ts_code = request.json.get('ts_code')
        
        data_manager = DataManager()
        
        if ts_code:
            request_id = data_manager.request_data('per_stock', ts_code)
            return jsonify({
                'success': True,
                'message': f'{ts_code} 同步请求已提交（异步）',
                'request_id': request_id
            })
        else:
            request_id = data_manager.request_data('full_daily')
            return jsonify({
                'success': True,
                'message': '全市场日线同步请求已提交（异步）',
                'request_id': request_id
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
        
        # 获取缓存统计（244号方案：从 DuckDB 替代 PG DailyData）
        from app.data.enhanced_cache_manager import get_ecm_instance
        stock_count = Stock.query.count()
        try:
            ecm = get_ecm_instance()
            count_df = pd.read_sql(
                "SELECT COUNT(*) AS cnt FROM daily_cache"
            , ecm.conn)
            daily_count = int(count_df['cnt'].iloc[0]) if not count_df.empty else 0
        except Exception:
            daily_count = 0
        
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
            # 单只股票缓存清除：从 DuckDB 删除对应记录
            ecm = data_manager.cache
            ecm.conn.execute("DELETE FROM daily_cache WHERE ts_code = ?", [ts_code])
            ecm.conn.commit()
            msg = f'股票 {ts_code} 缓存已清除'
        else:
            data_manager.cache.invalidate_old_data(days)
            msg = f'缓存清除成功 (保留最近{days}天)'

        return jsonify({
            'success': True,
            'message': msg
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
