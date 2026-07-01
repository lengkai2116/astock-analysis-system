"""
监控通知 API 路由

P0-P3 共 20+ 个端点 + 批量操作/克隆/睡眠管理/增强功能
"""
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify
from app.utils.error_handlers import handle_exceptions

logger = logging.getLogger(__name__)
notifications_bp = Blueprint('notifications', __name__, url_prefix='/api/v3/notifications')


# ─── P0: 规则 CRUD ───────────────────────────────────────

@notifications_bp.route('/rules', methods=['GET'])
@handle_exceptions
def list_rules():
    """规则列表 — 支持筛选+分页+排序"""
    from app.services.notification_service import list_rules as svc_list_rules

    status = request.args.get('status')
    rule_type = request.args.get('type')
    scope_type = request.args.get('range')
    search = request.args.get('search')
    sort = request.args.get('sort', 'recent')
    limit = request.args.get('limit', 20, type=int)
    offset = request.args.get('offset', 0, type=int)

    result = svc_list_rules(
        status=status, rule_type=rule_type, scope_type=scope_type,
        search=search, sort=sort, limit=limit, offset=offset,
    )
    return jsonify({'success': True, 'data': result})


@notifications_bp.route('/rules/<rule_id>', methods=['GET'])
@handle_exceptions
def get_rule(rule_id):
    """规则详情（含触发历史）"""
    from app.services.notification_service import get_rule as svc_get_rule

    result = svc_get_rule(rule_id)
    if result is None:
        return jsonify({'success': False, 'error': f'规则 {rule_id} 不存在'}), 404
    return jsonify({'success': True, 'data': {'rule': result}})


@notifications_bp.route('/rules', methods=['POST'])
@handle_exceptions
def create_rule():
    """创建规则"""
    from app.services.notification_service import create_rule as svc_create_rule

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': '请求体为空'}), 400
    if not data.get('name'):
        return jsonify({'success': False, 'error': '必填字段缺失: name'}), 400

    result = svc_create_rule(data)
    return jsonify({'success': True, 'data': {'id': result.get('id'), 'created_at': result.get('created_at')}}), 201


@notifications_bp.route('/rules/<rule_id>', methods=['PUT'])
@handle_exceptions
def update_rule(rule_id):
    """更新规则（部分更新）"""
    from app.services.notification_service import update_rule as svc_update_rule

    data = request.get_json()
    result = svc_update_rule(rule_id, data)
    if result is None:
        return jsonify({'success': False, 'error': f'规则 {rule_id} 不存在'}), 404
    return jsonify({'success': True, 'data': result})


@notifications_bp.route('/rules/<rule_id>', methods=['DELETE'])
@handle_exceptions
def delete_rule(rule_id):
    """删除规则（软删除）"""
    from app.services.notification_service import delete_rule as svc_delete_rule

    ok = svc_delete_rule(rule_id)
    if not ok:
        return jsonify({'success': False, 'error': f'规则 {rule_id} 不存在'}), 404
    return jsonify({'success': True, 'message': f'规则 {rule_id} 已删除'})


# ─── P0: 通知查询 ─────────────────────────────────────────

@notifications_bp.route('/recent', methods=['GET'])
@handle_exceptions
def recent_notifications():
    """最近通知列表"""
    from app.services.notification_service import list_recent_notifications

    limit = request.args.get('limit', 20, type=int)
    unread_only = request.args.get('unread_only', 'true').lower() == 'true'
    result = list_recent_notifications(limit=limit, unread_only=unread_only)
    return jsonify({'success': True, 'data': result})


@notifications_bp.route('/summary', methods=['GET'])
@handle_exceptions
def get_summary():
    """汇总统计（页面头部统计条）"""
    from app.services.notification_service import get_summary as svc_get_summary

    result = svc_get_summary()
    return jsonify({'success': True, 'data': result})


@notifications_bp.route('/today-unread', methods=['GET'])
@handle_exceptions
def get_today_unread():
    """今日未处理通知（顶部滚动区用）"""
    from app.services.notification_service import get_today_unread as svc_get_today_unread

    result = svc_get_today_unread()
    return jsonify({'success': True, 'data': result})


# ─── P1: 操作端点 ──────────────────────────────────────────

@notifications_bp.route('/rules/<rule_id>/ack', methods=['POST'])
@handle_exceptions
def acknowledge(rule_id):
    """隐式确认通知"""
    from app.services.notification_service import acknowledge as svc_ack

    data = request.get_json() or {}
    action = data.get('action', '')
    result = svc_ack(rule_id, action)
    return jsonify({'success': True, 'data': result})


@notifications_bp.route('/rules/batch', methods=['POST'])
@handle_exceptions
def batch_operation():
    """批量操作（暂停/启用/删除）"""
    from app.services.notification_service import batch_operation as svc_batch

    data = request.get_json() or {}
    rule_ids = data.get('rule_ids', [])
    action = data.get('action', 'pause')

    if not rule_ids:
        return jsonify({'success': False, 'error': 'rule_ids 不能为空'}), 400

    result = svc_batch(rule_ids, action)
    return jsonify({'success': True, 'data': result})


@notifications_bp.route('/rules/<rule_id>/clone', methods=['POST'])
@handle_exceptions
def clone_rule(rule_id):
    """克隆规则"""
    from app.services.notification_service import clone_rule as svc_clone

    result = svc_clone(rule_id)
    if result is None:
        return jsonify({'success': False, 'error': f'规则 {rule_id} 不存在'}), 404
    return jsonify({'success': True, 'data': {'id': result.get('id')}})


# ─── P1: 休眠管理 ──────────────────────────────────────────

@notifications_bp.route('/dormant', methods=['GET'])
@handle_exceptions
def get_dormant():
    """休眠区规则列表"""
    from app.services.notification_service import get_dormant_rules

    items = get_dormant_rules()
    return jsonify({'success': True, 'data': {'items': items}})


@notifications_bp.route('/health-check', methods=['GET'])
@handle_exceptions
def get_health_check():
    """健康检查（L3: 暂停30+天规则提醒）"""
    from app.services.notification_service import get_health_check as svc_health

    result = svc_health()
    return jsonify({'success': True, 'data': result})


# ─── P2: 触发历史 ──────────────────────────────────────────

@notifications_bp.route('/history', methods=['GET'])
@handle_exceptions
def get_history():
    """触发历史（分页+筛选）"""
    from app.services.notification_service import list_history

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    rule_id = request.args.get('rule_id')
    stock_code = request.args.get('stock_code')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    result = list_history(
        rule_id=rule_id, stock_code=stock_code,
        page=page, per_page=per_page,
        start_date=start_date, end_date=end_date,
    )
    return jsonify({'success': True, 'data': result})


# ─── Phase 3: 增强功能 ─────────────────────────────────────

@notifications_bp.route('/history/enhanced', methods=['GET'])
@handle_exceptions
def get_history_enhanced():
    """增强版触发历史（类型筛选+排序+摘要）"""
    from app.services.notification_service import list_history_enhanced

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    rule_id = request.args.get('rule_id')
    stock_code = request.args.get('stock_code')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    notif_type = request.args.get('type')
    is_unread = request.args.get('is_unread')
    sort = request.args.get('sort', 'time_desc')
    rule_name = request.args.get('rule_name')

    unread_filter = None
    if is_unread is not None:
        unread_filter = is_unread.lower() == 'true'

    result = list_history_enhanced(
        rule_id=rule_id, stock_code=stock_code,
        page=page, per_page=per_page,
        start_date=start_date, end_date=end_date,
        notif_type=notif_type, is_unread=unread_filter,
        sort=sort, rule_name=rule_name,
    )
    return jsonify({'success': True, 'data': result})


@notifications_bp.route('/history/export', methods=['GET'])
@handle_exceptions
def export_history():
    """导出触发历史（CSV/JSON）"""
    from app.services.notification_service import get_download_records

    fmt = request.args.get('format', 'csv')
    rule_id = request.args.get('rule_id')
    stock_code = request.args.get('stock_code')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    notif_type = request.args.get('type')

    data = get_download_records(
        record_type=fmt,
        rule_id=rule_id, stock_code=stock_code,
        start_date=start_date, end_date=end_date,
        notif_type=notif_type,
    )

    from flask import make_response, Response
    if fmt == 'csv':
        resp = Response(data, mimetype='text/csv; charset=utf-8')
        resp.headers['Content-Disposition'] = f'attachment; filename=notification_history_{datetime.now().strftime("%Y%m%d")}.csv'
        return resp
    else:
        return jsonify({'success': True, 'data': data, 'count': len(data) if isinstance(data, list) else 0})


@notifications_bp.route('/health-report', methods=['POST'])
@handle_exceptions
def generate_report():
    """生成健康报告并挂载到报告中心"""
    from app.services.notification_service import generate_health_report

    data = request.get_json() or {}
    rule_id = data.get('rule_id', '')

    result = generate_health_report(rule_id=rule_id)
    return jsonify({'success': True, 'data': result})


@notifications_bp.route('/health-report', methods=['GET'])
@handle_exceptions
def list_reports():
    """列出已生成的健康报告"""
    from app.models.notification import ReportArchive
    from app import db

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    pagination = ReportArchive.query.order_by(
        ReportArchive.generated_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'success': True,
        'data': {
            'items': [r.to_dict() for r in pagination.items],
            'total': pagination.total,
            'page': pagination.page,
            'per_page': pagination.per_page,
            'pages': pagination.pages,
        }
    })


@notifications_bp.route('/retry-check', methods=['POST'])
@handle_exceptions
def trigger_retry():
    """手动触发重推检查"""
    from app.services.notification_pusher import NotificationPusher

    result = NotificationPusher.run_retry_check()
    return jsonify({'success': True, 'data': result})


@notifications_bp.route('/retry-pending', methods=['GET'])
@handle_exceptions
def get_retry_pending():
    """查询待重推通知列表"""
    from app.services.notification_pusher import NotificationPusher

    pending = NotificationPusher.get_pending_retries(limit=50)
    return jsonify({
        'success': True,
        'data': {
            'pending': pending,
            'count': len(pending),
        }
    })