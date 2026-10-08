"""
机会标的库 CRUD API v3

标的库生命周期管理路由，支持 lib_level 筛选、ts_code/name 模糊搜索、完整增删改查。
"""
import logging
from datetime import datetime

from flask import Blueprint, jsonify, request

from app import db
from app.models.opportunity_library import OpportunityLibrary
from app.utils.error_handlers import handle_exceptions

logger = logging.getLogger(__name__)

library_bp = Blueprint('opportunity_library', __name__, url_prefix='/api/v3/opportunity-library')

# 允许的 lib_level 值
VALID_LEVELS = {'core', 'watch', 'scan', 'park', 'done'}

# 创建时允许的字段白名单
CREATABLE_FIELDS = {
    'ts_code', 'name', 'category', 'pipeline', 'lib_level',
    'added_date', 'added_reason', 'last_update', 'status',
    'days_in_status', 'total_days', 'manual_keep', 'is_active',
    'park_trigger_count', 'park_last_signal', 'park_entered_signal',
    'base_value_score', 'base_trend_score', 'base_event_score',
    'base_technical_score', 'factor_bonus_score', 'vibe_bonus_score',
    'total_score', 'operation_advice',
}

# 更新时允许的字段（ts_code 不可改）
UPDATABLE_FIELDS = CREATABLE_FIELDS - {'ts_code'}

# 509号 #J35：数值列（Integer/Float）——dict/list/str 灌入会静默损坏或 flush 报错
_INT_FIELDS = {'days_in_status', 'total_days', 'manual_keep', 'is_active',
               'park_trigger_count'}
_FLOAT_FIELDS = {'park_entered_signal', 'base_value_score', 'base_trend_score',
                 'base_event_score', 'base_technical_score', 'factor_bonus_score',
                 'vibe_bonus_score', 'total_score'}
_NUMERIC_FIELDS = _INT_FIELDS | _FLOAT_FIELDS


def _coerce_field(field: str, value):
    """白名单字段类型/None 校验：数值列强制 cast，非法值返回错误（509号 #J35）。

    Returns:
        (coerced_value, None) 或 (None, error_str)
    """
    if field == 'lib_level':
        # 509号 #J34：lib_level 域校验在 setattr 前完成（原 setattr 后校验→非法值已 dirty ORM）
        if value is None:
            return None, 'lib_level 不能为 null'
        value = str(value)
        if value not in VALID_LEVELS:
            levels_str = ','.join(sorted(VALID_LEVELS))
            return None, f'无效的 level 值，可选: {levels_str}'
        return value, None
    if field in _NUMERIC_FIELDS:
        if value is None:
            return None, f'{field} 不能为 null'
        if isinstance(value, bool) or isinstance(value, (dict, list)):
            return None, f'{field} 须为数值'
        try:
            if field in _FLOAT_FIELDS:
                return float(value), None
            return int(value), None
        except (TypeError, ValueError):
            return None, f'{field} 须为数值'
    # 字符串/文本列：非 None 时统一转 str，避免 dict/list 静默灌入
    if value is None:
        return None, None
    if isinstance(value, (dict, list)):
        return None, f'{field} 须为字符串'
    return str(value), None


@library_bp.route('', methods=['GET'])
@handle_exceptions
def list_library():
    """获取标的库列表，支持 level 筛选和 search 模糊搜索（509号 #J37：通配符转义 + 分页）"""
    level = request.args.get('level')
    search = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)
    page_size = request.args.get('page_size', 50, type=int)
    page = max(1, page)
    page_size = max(1, min(100, page_size))

    query = OpportunityLibrary.query

    if level:
        if level not in VALID_LEVELS:
            levels_str = ','.join(sorted(VALID_LEVELS))
            return jsonify({'success': False, 'error': f'无效的 level 值，可选: {levels_str}'}), 400
        query = query.filter_by(lib_level=level)

    if search:
        # 509号 #J37：转义 SQL 通配符，避免 %/_ 被当作模式 → 搜索静默全表返回
        escaped = (search.replace('\\', '\\\\')
                   .replace('%', '\\%')
                   .replace('_', '\\_'))
        pattern = f'%{escaped}%'
        query = query.filter(
            db.or_(
                OpportunityLibrary.ts_code.ilike(pattern, escape='\\'),
                OpportunityLibrary.name.ilike(pattern, escape='\\'),
            )
        )

    total = query.count()
    items = (query.order_by(OpportunityLibrary.updated_at.desc())
             .offset((page - 1) * page_size).limit(page_size).all())
    return jsonify({
        'success': True,
        'data': [item.to_dict() for item in items],
        'total': total,
        'page': page,
        'page_size': page_size,
    })


@library_bp.route('/<ts_code>', methods=['GET'])
@handle_exceptions
def get_library_item(ts_code):
    """获取单条标的详情"""
    item = OpportunityLibrary.query.get(ts_code)
    if not item:
        return jsonify({'success': False, 'error': '标的不存在'}), 404
    return jsonify({'success': True, 'data': item.to_dict()})


@library_bp.route('', methods=['POST'])
@handle_exceptions
def create_library_item():
    """新增标的"""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': '请求体不能为空'}), 400

    ts_code = data.get('ts_code')
    if not ts_code:
        return jsonify({'success': False, 'error': 'ts_code 不能为空'}), 400

    existing = OpportunityLibrary.query.get(ts_code)
    if existing:
        return jsonify({'success': False, 'error': f'标的 {ts_code} 已存在'}), 409

    item = OpportunityLibrary(ts_code=ts_code)
    for field in CREATABLE_FIELDS:
        if field in data:
            # 509号 #J35：先做类型/None 校验再 setattr，非法值不入 ORM
            value, err = _coerce_field(field, data[field])
            if err:
                return jsonify({'success': False, 'error': err}), 400
            setattr(item, field, value)

    if not item.lib_level:
        # 未显式提供 lib_level（或未传）时取默认档位（域校验已由 _coerce_field 保证）
        item.lib_level = 'scan'
    if not item.added_date:
        item.added_date = datetime.now().strftime('%Y-%m-%d')
    if item.last_update is None:
        item.last_update = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    db.session.add(item)
    try:
        db.session.commit()
    except Exception:
        # 509号 #J36：commit 失败回滚，防 PendingRollbackError 级联污染同 worker 后续请求
        db.session.rollback()
        raise

    return jsonify({'success': True, 'data': item.to_dict()}), 201


@library_bp.route('/<ts_code>', methods=['PUT'])
@handle_exceptions
def update_library_item(ts_code):
    """更新标的（部分更新）"""
    item = OpportunityLibrary.query.get(ts_code)
    if not item:
        return jsonify({'success': False, 'error': '标的不存在'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': '请求体不能为空'}), 400

    for field in UPDATABLE_FIELDS:
        if field in data:
            # 509号 #J34：先校验后 setattr——非法值不入 ORM（原 setattr 后再校验，
            #   返回 400 时 ORM 已 dirty，下一次任意请求 commit 会持久化非法值）
            value, err = _coerce_field(field, data[field])
            if err:
                return jsonify({'success': False, 'error': err}), 400
            setattr(item, field, value)

    item.last_update = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    item.updated_at = datetime.utcnow()
    try:
        db.session.commit()
    except Exception:
        # 509号 #J36：commit 失败回滚，防 PendingRollbackError 级联
        db.session.rollback()
        raise

    return jsonify({'success': True, 'data': item.to_dict()})


@library_bp.route('/<ts_code>', methods=['DELETE'])
@handle_exceptions
def delete_library_item(ts_code):
    """删除标的"""
    item = OpportunityLibrary.query.get(ts_code)
    if not item:
        return jsonify({'success': False, 'error': '标的不存在'}), 404

    db.session.delete(item)
    try:
        db.session.commit()
    except Exception:
        # 509号 #J36：commit 失败回滚，防 PendingRollbackError 级联
        db.session.rollback()
        raise

    return jsonify({'success': True, 'message': f'标的 {ts_code} 已删除'})


@library_bp.route('/radar', methods=['GET'])
@handle_exceptions
def radar():
    """机会雷达：非自选股中信号强度最高的股票

    Query Parameters:
        limit (int, optional): 返回数量上限，默认 20

    Returns:
        雷达信号列表，每项含 ts_code/name/signal_strength/trigger_reason
    """
    limit = request.args.get('limit', 20, type=int)
    limit = max(5, min(100, limit))

    from app.opportunity_atlas.radar_service import RadarService
    radar_svc = RadarService()
    signals = radar_svc.get_radar_signals(limit=limit)

    return jsonify({
        'success': True,
        'data': signals,
        'total': len(signals),
    })
