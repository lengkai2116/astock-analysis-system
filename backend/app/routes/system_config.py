"""
系统管理 API 路由（Blueprint: system_bp）

提供：服务配置热更新、系统日志查询、定时调度配置管理、日终同步手动触发

命名空间前缀：/api/v3/system

生产环境约束：
  - 配置存储于 SQLite system_config 表（JSON 列）
  - 定时调度通过 APScheduler 动态管理（reschedule_job）
"""
import json
import logging
import os
from datetime import datetime

from flask import Blueprint, jsonify, request

from app.utils.error_handlers import handle_exceptions

logger = logging.getLogger(__name__)

system_bp = Blueprint('system', __name__, url_prefix='/api/v3/system')

# ──────────────────────────────────────────
# 种子数据：默认调度配置（21 项参数，对齐 232号方案 §3.2）
# ──────────────────────────────────────────

DEFAULT_SCHEDULING_CONFIG = {
    "daily_sync": {
        "enabled": True,
        "trigger_time": "15:30",
        "mode": "incremental",
        "data_types": ["daily", "basic", "moneyflow", "index", "adj_factor"],
        "warmup_cache": True,
        "timeout_minutes": 30
    },
    "intraday": {
        "enabled": True,
        "moneyflow_interval_min": 30,
        "index_mode": "on_demand",
        "quote_ttl_sec": 3
    },
    "analysis": {
        "weekly_eval": {"enabled": True, "day_of_week": "mon", "time": "06:00"},
        "health_check": {"enabled": True, "day_of_week": "mon", "time": "06:30"},
        "weekly_report": {"enabled": True, "day_of_week": "sun", "time": "20:00"},
        "param_plateau": {"enabled": True, "day_of_month": 1, "time": "05:00"}
    },
    "monitor": {
        "default_scan_interval_min": 15,
        "post_market_eval_time": "15:30",
        "auto_sleep": {"enabled": True}
    }
}

DEFAULT_LLM_CONFIG = {
    "provider": "mock",
    "deepseek_api_key": "",
    "deepseek_base_url": "https://api.deepseek.com/v1",
    "deepseek_model": "deepseek-v4-flash",
    "lm_studio_endpoint": "http://localhost:1234/v1",
    "lm_studio_model": "local-model"
}

DEFAULT_DATA_SOURCE_CONFIG = {
    "tushare_token": ""
}

DEFAULT_NOTIFICATION_CONFIG = {
    "smtp": {
        "host": "",
        "port": 587,
        "username": "",
        "password": "",
        "to": ""
    },
    "webhook_url": ""
}


def _get_runtime_config_manager():
    """懒加载 RuntimeConfigManager"""
    from app.services.runtime_config import runtime_config_manager
    return runtime_config_manager


# ════════════════════════════════════════════
# 数据源状态
# ════════════════════════════════════════════

@handle_exceptions
@system_bp.route('/data-source/status', methods=['GET'])
def get_data_source_status():
    """获取数据源状态快照（迁移自 phase3_bp）"""
    try:
        from app.data.data_source_manager import data_source_manager
        snapshot = data_source_manager.get_status_snapshot()
        return jsonify({'success': True, 'data': snapshot.get('data', snapshot)})
    except Exception as e:
        logger.warning(f"获取数据源状态失败: {e}")
        return jsonify({
            'success': True,
            'data': {
                'sources': [
                    {'name': 'Tushare Pro', 'status': 'unknown'},
                    {'name': 'AKShare', 'status': 'unknown'},
                    {'name': 'QMT', 'status': 'disconnected'}
                ]
            }
        })


# ════════════════════════════════════════════
# 服务配置（config/save + config/load）
# ════════════════════════════════════════════

@handle_exceptions
@system_bp.route('/config/save', methods=['POST'])
def save_config():
    """全量保存服务配置（运行时热更新）

    请求体：{llm: {...}, data_source: {...}, notification: {...}}
    """
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': '请求体不能为空'}), 400

    rcm = _get_runtime_config_manager()
    rcm.save(data)

    # 同时更新环境变量级别的配置（用于不通过 RuntimeConfigManager 读取的老代码）
    _sync_env_from_config(data)

    return jsonify({
        'success': True,
        'message': '配置已保存（部分配置需要重启后生效）'
    })


@handle_exceptions
@system_bp.route('/config/load', methods=['GET'])
def load_config():
    """加载服务配置（供前端 Tab③ 回填）"""
    rcm = _get_runtime_config_manager()

    llm_config = rcm.get('llm', DEFAULT_LLM_CONFIG)
    data_source_config = rcm.get('data_source', DEFAULT_DATA_SOURCE_CONFIG)
    notification_config = rcm.get('notification', DEFAULT_NOTIFICATION_CONFIG)

    return jsonify({
        'success': True,
        'data': {
            'llm': llm_config,
            'data_source': data_source_config,
            'notification': notification_config
        }
    })


def _sync_env_from_config(config: dict):
    """将配置同步到 os.environ（兼容老代码直读环境变量）"""
    if 'llm' in config:
        llm = config['llm']
        if llm.get('provider'):
            os.environ['LLM_PROVIDER'] = llm['provider']
        if llm.get('deepseek_api_key'):
            os.environ['DEEPSEEK_API_KEY'] = llm['deepseek_api_key']
        if llm.get('deepseek_base_url'):
            os.environ['DEEPSEEK_BASE_URL'] = llm['deepseek_base_url']
        if llm.get('deepseek_model'):
            os.environ['DEEPSEEK_MODEL'] = llm['deepseek_model']
    if 'data_source' in config:
        ds = config['data_source']
        if ds.get('tushare_token'):
            os.environ['TUSHARE_TOKEN'] = ds['tushare_token']


# ════════════════════════════════════════════
# 系统日志
# ════════════════════════════════════════════

@handle_exceptions
@system_bp.route('/logs', methods=['GET'])
def get_system_logs():
    """获取最近系统日志

    参数：
      level: all(默认) / warn / error
      limit: 默认 20，最大 100
    """
    level = request.args.get('level', 'all').strip().lower()
    limit = min(request.args.get('limit', 20, type=int), 100)

    # 从日志文件中读取最近的符合条件的条目
    log_dir = os.environ.get('LOG_DIR', '')
    log_entries = []

    if log_dir:
        log_file = os.path.join(log_dir, 'app.log')
    else:
        from app.config import Config
        log_file = os.path.join(Config.DATA_DIR, 'logs', 'app.log')

    try:
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            all_lines = f.readlines()
            # 从尾部开始读取（最新的日志在文件末尾）
            for line in reversed(all_lines):
                line = line.strip()
                if not line:
                    continue
                # 解析日志级别
                level_match = 'error' if '[ERROR]' in line else ('warn' if '[WARNING]' in line else 'info')
                if level != 'all' and level_match != level:
                    continue
                # 解析时间（取行首的 ISO 时间）
                time_str = line[:19] if len(line) > 19 else ''
                if time_str and time_str[4] == '-' and time_str[7] == '-':
                    time_str = time_str[11:19]  # HH:MM:SS
                else:
                    time_str = datetime.now().strftime('%H:%M:%S')

                log_entries.append({
                    'time': time_str,
                    'level': level_match,
                    'message': line[20:] if len(line) > 20 else line
                })
                if len(log_entries) >= limit:
                    break
    except (FileNotFoundError, IOError):
        # 日志文件不存在或不可读，返回空列表
        pass
    except Exception as e:
        logger.warning(f"读取日志文件失败: {e}")

    return jsonify({
        'success': True,
        'data': {
            'logs': log_entries,
            'total': len(log_entries),
            'level': level
        }
    })


# ════════════════════════════════════════════
# 定时调度配置（21 项参数，232号方案 §3.2）
# ════════════════════════════════════════════

@handle_exceptions
@system_bp.route('/schedule/config', methods=['GET'])
def get_schedule_config():
    """获取定时调度配置（21 项用户可配置参数）"""
    rcm = _get_runtime_config_manager()
    config = rcm.get('scheduling', DEFAULT_SCHEDULING_CONFIG)
    return jsonify({
        'success': True,
        'data': config
    })


@handle_exceptions
@system_bp.route('/schedule/config', methods=['POST'])
def save_schedule_config():
    """保存定时调度配置 + 动态更新 APScheduler Job"""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': '请求体不能为空'}), 400

    # 合并：保留未传入的默认值
    rcm = _get_runtime_config_manager()
    current = rcm.get('scheduling', DEFAULT_SCHEDULING_CONFIG)
    merged = {**current, **data}
    rcm.save_section('scheduling', merged)

    # 通知 APScheduler 动态更新 Job
    try:
        from app.scheduler_manager import scheduler_manager
        scheduler_manager.reschedule_from_config(merged)
    except Exception as e:
        logger.warning(f"APScheduler 动态更新失败（定时将在下次启动时生效）: {e}")

    return jsonify({
        'success': True,
        'message': '调度配置已保存，定时任务已动态更新'
    })


@handle_exceptions
@system_bp.route('/schedule/sync-now', methods=['POST'])
def trigger_sync_now():
    """手动触发日终同步"""
    try:
        from app.scheduler_manager import scheduler_manager
        result = scheduler_manager.run_daily_sync()
        return jsonify({
            'success': True,
            'data': result,
            'message': '同步已启动'
        })
    except Exception as e:
        logger.error(f"手动触发同步失败: {e}")
        return jsonify({'success': False, 'error': f'同步启动失败: {str(e)}'}), 500


@handle_exceptions
@system_bp.route('/schedule/logs', methods=['GET'])
def get_schedule_logs():
    """获取调度执行日志

    参数：
      limit: 默认 20，最大 100
    """
    limit = min(request.args.get('limit', 20, type=int), 100)
    offset = request.args.get('offset', 0, type=int)

    try:
        from app.models.system_config import SyncLog
        from app import db

        query = SyncLog.query.order_by(SyncLog.started_at.desc())
        total = query.count()
        logs = query.offset(offset).limit(limit).all()

        return jsonify({
            'success': True,
            'data': {
                'logs': [l.to_dict() for l in logs],
                'total': total,
                'offset': offset,
                'limit': limit
            }
        })
    except Exception as e:
        logger.warning(f"读取调度日志失败（表可能不存在）: {e}")
        return jsonify({
            'success': True,
            'data': {
                'logs': [],
                'total': 0,
                'offset': offset,
                'limit': limit
            }
        })


@handle_exceptions
@system_bp.route('/schedule/next-runs', methods=['GET'])
def get_next_runs():
    """获取所有 APScheduler Job 下次执行时间"""
    try:
        from app.scheduler_manager import scheduler_manager
        jobs = scheduler_manager.get_jobs()
        return jsonify({
            'success': True,
            'data': {
                'jobs': jobs
            }
        })
    except Exception as e:
        logger.warning(f"获取下次执行时间失败: {e}")
        return jsonify({
            'success': True,
            'data': {
                'jobs': [],
                'error': str(e)
            }
        })
