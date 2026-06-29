"""
策略沙箱 API 路由 — 保留信号记录查询

原为虚拟实盘验证 API（virtual_verify.py），2026-06-25 改造为策略沙箱信号数据源。
废弃端点：virtual-position / virtual-positions / run-checkpoint / run-batch-eval（由复盘中心替代）。
"""
import logging
from datetime import date, timedelta
from flask import Blueprint, request, jsonify

from app import db
from app.models.verification import SignalRecord
from app.utils.error_handlers import handle_exceptions

logger = logging.getLogger(__name__)
sandbox_bp = Blueprint('sandbox_v1', __name__, url_prefix='/api/v1/verify')


@sandbox_bp.route('/signal-records', methods=['GET'])
@handle_exceptions
def list_signal_records():
    """获取策略信号记录 — 策略沙箱的明细数据源"""
    ts_code = request.args.get('ts_code')
    days = int(request.args.get('days', 30))

    query = SignalRecord.query
    if ts_code:
        query = query.filter_by(ts_code=ts_code)
    cutoff = date.today() - timedelta(days=days)
    query = query.filter(SignalRecord.signal_date >= cutoff)
    records = query.order_by(SignalRecord.signal_date.desc()).limit(200).all()

    return jsonify({
        'success': True,
        'data': [r.to_dict() for r in records]
    })
