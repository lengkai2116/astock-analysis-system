"""
"系统健康检查 API 路由
提供服务状态、数据库连接等健康检查端点"
"""
from flask import Blueprint, jsonify
from datetime import datetime
import os
from sqlalchemy import text

health_bp = Blueprint('health', __name__)

@health_bp.route('/api/v3/health', methods=['GET'])
@health_bp.route('/api/v3/health/live', methods=['GET'])
def liveness():
    """K8s liveness probe"""
    return jsonify({"success": True, "status": "alive", "timestamp": datetime.utcnow().isoformat()})

@health_bp.route('/api/v3/health/ready', methods=['GET'])
def readiness():
    """K8s readiness probe"""
    deps = {"database": False, "cache": False}
    try:
        from app import db
        db.session.execute(db.text('SELECT 1'))
        deps["database"] = True
    except Exception as e:
        deps["database_error"] = str(e)
    try:
        import redis
        r = redis.Redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'))
        r.ping()
        deps["cache"] = True
    except Exception as e:
        deps["cache_error"] = str(e)
    all_healthy = all(v is True for v in deps.values())
    status_code = 200 if all_healthy else 503
    return jsonify({
        "success": all_healthy,
        "status": "ready" if all_healthy else "degraded",
        "dependencies": deps,
        "timestamp": datetime.utcnow().isoformat()
    }), status_code

@health_bp.route('/api/v1/health', methods=['GET'])
def health_check():
    return jsonify({
        'success': True,
        'status': 'healthy',
        'message': 'A股股票分析系统运行正常'
    })

@health_bp.route('/api/v3/health/database', methods=['GET'])
@health_bp.route('/api/v1/health/database', methods=['GET'])
def database_check():
    from app import db
    try:
        db.session.execute(text('SELECT 1'))
        return jsonify({
            'success': True,
            'status': 'healthy',
            'message': '数据库连接正常'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'status': 'unhealthy',
            'message': f'数据库连接失败: {str(e)}'
        })
