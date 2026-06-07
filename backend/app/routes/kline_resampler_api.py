"""
K线重采样 API 路由 — 151-P3-3
"""
import logging
from flask import Blueprint, request, jsonify
from app.data.kline_resampler import KlineResampler

logger = logging.getLogger(__name__)
kline_resampler_bp = Blueprint('kline_resampler', __name__)
_resampler = KlineResampler()

@kline_resampler_bp.route('/api/kline/resample', methods=['POST'])
def resample_kline():
    body = request.get_json(silent=True) or {}
    data = body.get('data', [])
    source_freq = body.get('source_freq', '15min')
    target_freq = body.get('target_freq', 'daily')
    try:
        result = _resampler.resample(data, source_freq, target_freq)
        return jsonify({'code': 0, 'data': result, 'total': len(result)})
    except Exception as e:
        return jsonify({'code': -1, 'msg': str(e)})

@kline_resampler_bp.route('/api/kline/resample-config', methods=['GET'])
def resample_config():
    return jsonify({
        'code': 0,
        'data': {
            'source_freqs': ['1min', '5min', '15min', '30min', '60min', 'daily'],
            'target_freqs': ['daily', 'weekly', 'monthly'],
        }
    })
