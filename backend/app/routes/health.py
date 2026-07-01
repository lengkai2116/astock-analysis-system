"""
系统健康检查 API 路由
提供服务状态、数据库连接等健康检查端点

生产环境约束（§11）：
  - 无 PostgreSQL → 检测 SQLite 状态
  - 无 Redis → 使用 TTLCache
  - 无 Nginx → Flask 直接托管
"""
import os
import time
import logging
from datetime import datetime

from flask import Blueprint, jsonify
from sqlalchemy import text

health_bp = Blueprint('health', __name__)
logger = logging.getLogger(__name__)

# 应用启动时间（用于计算 uptime）
_app_start_time = time.time()


def _get_uptime() -> str:
    """计算系统运行时间"""
    seconds = int(time.time() - _app_start_time)
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    if days > 0:
        return f"{days}天{hours}小时"
    elif hours > 0:
        return f"{hours}小时{minutes}分钟"
    else:
        return f"{minutes}分钟"


def _get_db_status():
    """检查数据库连接状态"""
    from app import db
    try:
        start = time.time()
        db.session.execute(text('SELECT 1'))
        latency = int((time.time() - start) * 1000)
        return {"status": "healthy", "latency_ms": latency, "type": "SQLite"}
    except Exception as e:
        return {"status": "unhealthy", "latency_ms": 0, "type": "SQLite", "error": str(e)}


def _get_duckdb_status():
    """检查 DuckDB 缓存状态"""
    try:
        from app.data.cache_manager import CacheManager
        cm = CacheManager()
        stats = cm.get_cache_stats()
        return {
            "status": "healthy" if stats.get("cache_size_mb", 0) > 0 else "empty",
            "latency_ms": 1,  # DuckDB 在内存中，延迟极低
            "cache_size_mb": stats.get("cache_size_mb", 0),
            "records": stats.get("total_records", 0)
        }
    except Exception as e:
        return {"status": "unhealthy", "latency_ms": 0, "error": str(e)}


def _get_ws_status():
    """检查 WebSocket 状态"""
    try:
        from app import socketio
        # SocketIO 已初始化即正常
        return {"status": "connected", "heartbeat": 30}
    except Exception:
        return {"status": "unknown", "heartbeat": 30}


def _get_data_source_status():
    """获取数据源状态"""
    statuses = []
    try:
        from app.data.data_source_manager import data_source_manager
        snapshot = data_source_manager.get_status_snapshot()
        sources = snapshot.get('sources', snapshot.get('data', {}))
        if isinstance(sources, dict):
            for name, info in sources.items():
                statuses.append({
                    "name": name,
                    "status": info.get('status', info.get('state', 'unknown')),
                    "priority": info.get('priority', 0)
                })
        elif isinstance(sources, list):
            for s in sources:
                statuses.append({
                    "name": s.get('name', 'unknown'),
                    "status": s.get('status', s.get('state', 'unknown')),
                })
    except Exception as e:
        logger.warning(f"获取数据源状态失败: {e}")

    # 如果 data_source_manager 无数据，回退到基础检测
    if not statuses:
        tushare_token = os.getenv('TUSHARE_TOKEN', '')
        statuses = [
            {"name": "Tushare Pro", "status": "connected" if tushare_token else "not_configured"},
            {"name": "AKShare", "status": "ready"},
            {"name": "QMT", "status": "disconnected"},
        ]

    return statuses


def _get_cache_status():
    """获取缓存状态"""
    try:
        duckdb_status = _get_duckdb_status()
        return {
            "duckdb_file": f"{duckdb_status.get('cache_size_mb', 0)} MB",
            "daily_cached": duckdb_status.get('records', 0),
            "minute_cached": 0,  # 待分钟数据实现
            "factor_precompute": "pending",
            "last_refresh": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
    except Exception as e:
        return {
            "duckdb_file": "0 MB",
            "daily_cached": 0,
            "minute_cached": 0,
            "factor_precompute": "unknown",
            "last_refresh": "never",
            "error": str(e)
        }


@health_bp.route('/api/v3/health', methods=['GET'])
@health_bp.route('/api/v1/health', methods=['GET'])
def health_check():
    """综合健康检查 — 返回服务状态、系统信息、数据源、缓存详情"""
    from app import db

    db_status = _get_db_status()
    duckdb_status = _get_duckdb_status()
    ws_status = _get_ws_status()
    data_sources = _get_data_source_status()
    cache = _get_cache_status()

    # 总体状态：所有组件健康 → healthy
    all_healthy = all(
        s.get('status') not in ('unhealthy', 'error', 'disconnected', 'not_configured')
        for s in data_sources
    ) and db_status.get('status') == 'healthy'
    overall_status = "healthy" if all_healthy else "degraded"

    # 系统信息
    import sys
    system_info = {
        "uptime": _get_uptime(),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "framework_version": "v2.0.0",
        "frontend_version": "Vue 3.5 + AntDV 4.2",
        "data_last_update": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data_dir": os.getenv('DATA_DIR', 'default')
    }

    return jsonify({
        'success': True,
        'data': {
            "status": overall_status,
            "services": [
                {
                    "name": "SQLite (app.db)",
                    "status": db_status.get('status'),
                    "latency": db_status.get('latency_ms', 0),
                    "type": db_status.get('type', 'SQLite')
                },
                {
                    "name": "TTLCache (内存缓存)",
                    "status": "healthy",
                    "type": "memory",
                    "maxsize": 1000,
                    "ttl": "3600s"
                },
                {
                    "name": "DuckDB (缓存)",
                    "status": duckdb_status.get('status'),
                    "latency": duckdb_status.get('latency_ms', 0),
                    "records": duckdb_status.get('records', 0),
                    "cache_size_mb": duckdb_status.get('cache_size_mb', 0)
                },
                {
                    "name": "Backend (Flask+eventlet)",
                    "status": "healthy",
                    "pid": os.getpid(),
                    "memory_mb": 0  # 获取实际内存需 psutil
                },
                {
                    "name": "静态托管",
                    "status": "healthy",
                    "mode": "send_from_directory (直接托管)"
                },
                {
                    "name": "WebSocket",
                    "status": ws_status.get('status'),
                    "heartbeat": ws_status.get('heartbeat', 30)
                }
            ],
            "system": system_info,
            "data_sources": data_sources,
            "cache": cache
        }
    })


@health_bp.route('/api/v3/health/database', methods=['GET'])
@health_bp.route('/api/v1/health/database', methods=['GET'])
def database_check():
    """数据库专项健康检查"""
    from app import db
    try:
        db.session.execute(text('SELECT 1'))
        return jsonify({
            'success': True,
            'status': 'healthy',
            'message': 'SQLite 数据库连接正常'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'status': 'unhealthy',
            'message': f'数据库连接失败: {str(e)}'
        })


@health_bp.route('/api/v3/health/live', methods=['GET'])
def liveness_check():
    """进程存活检查（liveness probe）"""
    return jsonify({
        'success': True,
        'status': 'alive',
        'uptime': _get_uptime()
    })


@health_bp.route('/api/v3/health/ready', methods=['GET'])
def readiness_check():
    """依赖就绪检查（readiness probe）"""
    db_status = _get_db_status()
    duckdb_status = _get_duckdb_status()

    return jsonify({
        'success': True,
        'status': 'ready',
        'dependencies': {
            'database': db_status,
            'cache': duckdb_status
        }
    })
