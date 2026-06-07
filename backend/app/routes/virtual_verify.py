"""
虚拟实盘验证 API 路由 — 轨B·用户可选

用户可在单股分析页面勾选"虚拟实盘验证"后调用此接口。
"""
import logging
from datetime import date
from flask import Blueprint, request, jsonify

from app import db
from app.models.verification import VirtualPosition, SignalRecord
from app.services.backtest_evidence_service import BacktestEvidenceService
from app.utils.error_handlers import handle_exceptions

logger = logging.getLogger(__name__)
verify_bp = Blueprint('verify', __name__, url_prefix='/api/v1/verify')

_evidence_service = None

def get_evidence_service():
    global _evidence_service
    if _evidence_service is None:
        _evidence_service = BacktestEvidenceService()
    return _evidence_service


@verify_bp.route('/virtual-position', methods=['POST'])
@handle_exceptions
def create_virtual_position():
    """创建虚拟实盘验证 (轨B)"""
    data = request.json or {}
    ts_code = data.get('ts_code')
    if not ts_code:
        return jsonify({'success': False, 'error': 'ts_code 必填'}), 400

    vp = get_evidence_service().create_virtual_position(
        ts_code=ts_code,
        stock_name=data.get('stock_name', ''),
        suggestion=data.get('suggestion', 'HOLD'),
        entry_price=data.get('entry_price'),
        entry_zone_low=data.get('entry_zone', [None, None])[0],
        entry_zone_high=data.get('entry_zone', [None, None])[1] if data.get('entry_zone') else None,
        risk_line=data.get('risk_line'),
        target_price=data.get('target_price'),
        position_suggestion=data.get('position_suggestion', ''),
        confidence=data.get('confidence', 0.0),
        virtual_capital=data.get('virtual_capital', 100000.0),
    )
    if vp:
        return jsonify({'success': True, 'data': vp.to_dict()})
    return jsonify({'success': False, 'error': '创建失败'}), 500


@verify_bp.route('/virtual-positions', methods=['GET'])
@handle_exceptions
def list_virtual_positions():
    """获取虚拟持仓列表"""
    status = request.args.get('status')
    vps = get_evidence_service().get_virtual_positions(status)
    return jsonify({
        'success': True,
        'data': [vp.to_dict() for vp in vps]
    })


@verify_bp.route('/signal-records', methods=['GET'])
@handle_exceptions
def list_signal_records():
    """获取策略信号记录 (轨A)"""
    ts_code = request.args.get('ts_code')
    days = int(request.args.get('days', 30))

    query = SignalRecord.query
    if ts_code:
        query = query.filter_by(ts_code=ts_code)
    from datetime import timedelta
    cutoff = date.today() - timedelta(days=days)
    query = query.filter(SignalRecord.signal_date >= cutoff)
    records = query.order_by(SignalRecord.signal_date.desc()).limit(200).all()

    return jsonify({
        'success': True,
        'data': [r.to_dict() for r in records]
    })


@verify_bp.route('/run-checkpoint', methods=['POST'])
@handle_exceptions
def trigger_checkpoint():
    """手动触发指定偏移的回调检查"""
    days_offset = int(request.json.get('days_offset', 5))
    get_evidence_service().run_checkpoint_update(days_offset)
    return jsonify({'success': True, 'message': f'T+{days_offset} 检查完成'})


@verify_bp.route('/run-batch-eval', methods=['POST'])
@handle_exceptions
def trigger_batch_eval():
    """手动触发批量赢率评估"""
    months = int(request.json.get('months', 6))
    results = get_evidence_service().run_batch_evaluation(months)
    return jsonify({
        'success': True,
        'data': results,
        'message': f'批量评估完成: {len(results)} 类信号'
    })
