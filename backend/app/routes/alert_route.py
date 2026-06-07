"""
告警通知 API 路由
"""
import logging
from flask import Blueprint, request, jsonify
from app.utils.error_handlers import handle_exceptions

logger = logging.getLogger(__name__)
alert_bp = Blueprint('alert', __name__)

@alert_bp.route('/api/alert/send', methods=['POST'])
@handle_exceptions
def send_alert():
    from app.services.alert_service import get_alert_service
    body = request.get_json(silent=True) or {}
    svc = get_alert_service()
    ok = svc.send(
        title=body.get('title', '无标题'),
        message=body.get('message', ''),
        level=body.get('level', 'info'),
        source=body.get('source', 'api'),
        data=body.get('data'),
    )
    return jsonify({'success': ok, 'data': {'sent': ok}})

@alert_bp.route('/api/alert/recent', methods=['GET'])
@handle_exceptions
def recent_alerts():
    from app.services.alert_service import get_alert_service
    limit = int(request.args.get('limit', 20))
    min_level = request.args.get('min_level', 'info')
    svc = get_alert_service()
    return jsonify({'success': True, 'data': svc.get_recent_alerts(limit, min_level)})
