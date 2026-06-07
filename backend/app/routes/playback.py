"""
回放复盘 API 路由 — 151-P3-1
"""
import logging
from app.utils.error_handlers import handle_exceptions
from flask import Blueprint, request, jsonify
from app.services.playback_service import PlaybackService, PlaybackSnapshot

logger = logging.getLogger(__name__)
playback_bp = Blueprint('playback', __name__)

_service = PlaybackService()

@playback_bp.route('/api/playback/load', methods=['POST'])
@handle_exceptions
def load_playback():
    body = request.get_json(silent=True) or {}
    ts_code = body.get('ts_code', '')
    kline_data = body.get('kline_data', [])
    if not ts_code or not kline_data:
        return jsonify({'code': -1, 'msg': '缺少 ts_code 或 kline_data'})
    signals = body.get('signals')
    positions = body.get('positions')
    total = _service.load(ts_code, kline_data, signals, positions)
    return jsonify({'code': 0, 'data': {'total_dates': total, 'ts_code': ts_code}})

@playback_bp.route('/api/playback/next', methods=['GET'])
@handle_exceptions
def next_snapshot():
    try:
        for snap in _service.play():
            return jsonify({'code': 0, 'data': snap.to_dict(), 'progress': _service.progress})
        return jsonify({'code': 0, 'data': None, 'progress': 100, 'msg': '回放结束'})
    except Exception as e:
        return jsonify({'code': -1, 'msg': str(e)})

@playback_bp.route('/api/playback/seek', methods=['POST'])
@handle_exceptions
def seek_playback():
    body = request.get_json(silent=True) or {}
    index = body.get('index')
    date_str = body.get('date')
    try:
        if date_str:
            snap = _service.seek_to_date(date_str)
        elif index is not None:
            snap = _service.seek(int(index))
        else:
            return jsonify({'code': -1, 'msg': '需要 index 或 date'})
        return jsonify({'code': 0, 'data': snap.to_dict() if snap else None})
    except Exception as e:
        return jsonify({'code': -1, 'msg': str(e)})

@playback_bp.route('/api/playback/speed', methods=['POST'])
@handle_exceptions
def set_speed():
    body = request.get_json(silent=True) or {}
    speed = float(body.get('speed', 1.0))
    _service.speed = speed
    return jsonify({'code': 0, 'data': {'speed': _service.speed}})

@playback_bp.route('/api/playback/timeline', methods=['GET'])
@handle_exceptions
def get_timeline():
    return jsonify({'code': 0, 'data': _service.get_timeline()})

@playback_bp.route('/api/playback/summary', methods=['GET'])
@handle_exceptions
def get_summary():
    return jsonify({'code': 0, 'data': _service.get_summary()})
