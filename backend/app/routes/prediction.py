"""
预测校准 API 路由 — 153-P1-2
"""
import logging
from flask import Blueprint, request, jsonify
from datetime import date, datetime
from app.services.prediction_calibration_service import (
    get_calibration_service, AiPrediction
)

logger = logging.getLogger(__name__)
prediction_bp = Blueprint('prediction', __name__)

@prediction_bp.route('/api/prediction/register', methods=['POST'])
def register_prediction():
    body = request.get_json(silent=True) or {}
    try:
        pred = AiPrediction(
            id=f"pred_{int(datetime.now().timestamp())}",
            ts_code=body.get('ts_code', ''),
            stock_name=body.get('stock_name', ''),
            direction=body.get('direction', 'neutral'),
            confidence_raw=float(body.get('confidence_raw', 50)),
            confidence_calibrated=float(body.get('confidence_raw', 50)),
            prediction_date=body.get('prediction_date', datetime.now().strftime('%Y-%m-%d')),
            source=body.get('source', 'deepseek'),
            verify_period=int(body.get('verify_period', 5)),
            target_price=float(body['target_price']) if body.get('target_price') else None,
            stop_loss=float(body['stop_loss']) if body.get('stop_loss') else None,
        )
        svc = get_calibration_service()
        pid = svc.register_prediction(pred)
        # 返回校准后的置信度
        calibrated = svc.calibrate_confidence(pred.confidence_raw, pred.source, pred.direction)
        return jsonify({'code': 0, 'data': {'id': pid, 'confidence_calibrated': calibrated}})
    except Exception as e:
        return jsonify({'code': -1, 'msg': str(e)})

@prediction_bp.route('/api/prediction/verify', methods=['POST'])
def verify_prediction():
    body = request.get_json(silent=True) or {}
    pid = body.get('prediction_id', '')
    actual_return = float(body.get('actual_return', 0))
    svc = get_calibration_service()
    result = svc.verify_prediction(pid, actual_return)
    if result:
        return jsonify({'code': 0, 'data': result.to_short_dict()})
    return jsonify({'code': -1, 'msg': '预测记录不存在'})

@prediction_bp.route('/api/prediction/stats', methods=['GET'])
def calibration_stats():
    source = request.args.get('source')
    svc = get_calibration_service()
    return jsonify({'code': 0, 'data': svc.get_calibration_stats(source)})

@prediction_bp.route('/api/prediction/calibrate', methods=['POST'])
def calibrate():
    body = request.get_json(silent=True) or {}
    raw = float(body.get('raw_confidence', 50))
    source = body.get('source', 'deepseek')
    direction = body.get('direction', 'neutral')
    svc = get_calibration_service()
    calibrated = svc.calibrate_confidence(raw, source, direction)
    return jsonify({'code': 0, 'data': {'raw': raw, 'calibrated': calibrated}})

@prediction_bp.route('/api/prediction/batch-verify', methods=['POST'])
def batch_verify():
    svc = get_calibration_service()
    results = svc.batch_verify_due(date.today())
    return jsonify({'code': 0, 'data': results})
