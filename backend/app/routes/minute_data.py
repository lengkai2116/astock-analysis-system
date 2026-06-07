"""
分钟级数据 API 路由 — 151-P1-1
"""
import logging
from app.utils.error_handlers import handle_exceptions
from flask import Blueprint, request, jsonify
from app.data.minute_data_manager import MinuteDataManager

logger = logging.getLogger(__name__)
minute_data_bp = Blueprint('minute_data', __name__)
minute_mgr = MinuteDataManager()

@minute_data_bp.route('/api/minute/<ts_code>', methods=['GET'])
@handle_exceptions
def get_minute_kline(ts_code):
    freq = request.args.get('freq', '15min')
    days_back = request.args.get('days_back', '5')
    try:
        data = minute_mgr.get_minute_data(
            ts_code, freq=freq, days_back=int(days_back)
        )
        return jsonify({'code': 0, 'data': data, 'total': len(data)})
    except Exception as e:
        logger.error(f"分钟数据获取失败: {e}")
        return jsonify({'code': -1, 'msg': str(e), 'data': []})

@minute_data_bp.route('/api/minute/batch', methods=['POST'])
@handle_exceptions
def batch_minute_kline():
    body = request.get_json(silent=True) or {}
    ts_codes = body.get('ts_codes', [])
    freq = body.get('freq', '15min')
    days_back = body.get('days_back', 5)
    try:
        result = minute_mgr.batch_get(ts_codes, freq=freq, days_back=days_back)
        return jsonify({'code': 0, 'data': result})
    except Exception as e:
        logger.error(f"批量分钟数据获取失败: {e}")
        return jsonify({'code': -1, 'msg': str(e), 'data': {}})

@minute_data_bp.route('/api/minute/supported-freqs', methods=['GET'])
@handle_exceptions
def supported_freqs():
    return jsonify({'code': 0, 'data': list(MinuteDataManager.FREQ_MAP.keys())})
