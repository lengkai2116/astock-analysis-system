from flask import Blueprint, jsonify
from sqlalchemy import text

health_bp = Blueprint('health', __name__)

@health_bp.route('/api/v1/health', methods=['GET'])
def health_check():
    return jsonify({
        'success': True,
        'status': 'healthy',
        'message': 'A股股票分析系统运行正常'
    })

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
