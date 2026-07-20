"""
分钟级数据 API 路由 — 151-P1-1 / 252号方案
重构: 统一走 DataManager.get_kline_data()（274号方案P-1c）
"""
import logging
from app.utils.error_handlers import handle_exceptions
from flask import Blueprint, request, jsonify
from app.data import DataManager

logger = logging.getLogger(__name__)
minute_data_bp = Blueprint('minute_data', __name__)

FREQ_TO_PERIOD = {'1min': '1m', '5min': '5m', '15min': '15m', '30min': '30m', '60min': '60m'}

@minute_data_bp.route('/api/minute/<ts_code>', methods=['GET'])
@handle_exceptions
def get_minute_kline(ts_code):
    freq = request.args.get('freq', '15min')
    period = FREQ_TO_PERIOD.get(freq, '15m')
    try:
        dm = DataManager()
        df = dm.get_kline_data(ts_code, period=period)
        if df is not None and not df.empty:
            records = df.to_dict('records')
            return jsonify({'code': 0, 'data': records, 'total': len(records), 'source': 'cache'})
        return jsonify({'code': 0, 'data': [], 'total': 0, 'source': 'empty'})
    except Exception as e:
        logger.error(f"分钟数据获取失败: {e}")
        return jsonify({'code': -1, 'msg': str(e), 'data': []})

@minute_data_bp.route('/api/minute/batch', methods=['POST'])
@handle_exceptions
def batch_minute_kline():
    body = request.get_json(silent=True) or {}
    ts_codes = body.get('ts_codes', [])
    freq = body.get('freq', '15min')
    period = FREQ_TO_PERIOD.get(freq, '15m')
    dm = DataManager()
    result = {}
    for code in ts_codes:
        df = dm.get_kline_data(code, period=period)
        if df is not None and not df.empty:
            result[code] = df.to_dict('records')
    return jsonify({'code': 0, 'data': result})

@minute_data_bp.route('/api/minute/supported-freqs', methods=['GET'])
@handle_exceptions
def supported_freqs():
    return jsonify({'code': 0, 'data': list(FREQ_TO_PERIOD.keys())})
