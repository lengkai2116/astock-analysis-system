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


@library_bp.route('', methods=['GET'])
@handle_exceptions
def list_library():
    """获取标的库列表，支持 level 筛选和 search 模糊搜索"""
    level = request.args.get('level')
    search = request.args.get('search', '').strip()

    query = OpportunityLibrary.query.order_by(OpportunityLibrary.updated_at.desc())

    if level:
        if level not in VALID_LEVELS:
            levels_str = ','.join(sorted(VALID_LEVELS))
            return jsonify({'success': False, 'error': f'无效的 level 值，可选: {levels_str}'}), 400
        query = query.filter_by(lib_level=level)

    if search:
        pattern = f'%{search}%'
        query = query.filter(
            db.or_(
                OpportunityLibrary.ts_code.ilike(pattern),
                OpportunityLibrary.name.ilike(pattern),
            )
        )

    items = query.all()
    return jsonify({
        'success': True,
        'data': [item.to_dict() for item in items],
        'total': len(items),
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
            setattr(item, field, data[field])

    if not item.lib_level or item.lib_level not in VALID_LEVELS:
        item.lib_level = 'scan'
    if not item.added_date:
        item.added_date = datetime.now().strftime('%Y-%m-%d')
    if item.last_update is None:
        item.last_update = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    db.session.add(item)
    db.session.commit()

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
            setattr(item, field, data[field])

    if item.lib_level and item.lib_level not in VALID_LEVELS:
        levels_str = ','.join(sorted(VALID_LEVELS))
        return jsonify({'success': False, 'error': f'无效的 level 值，可选: {levels_str}'}), 400

    item.last_update = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    item.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({'success': True, 'data': item.to_dict()})


@library_bp.route('/<ts_code>', methods=['DELETE'])
@handle_exceptions
def delete_library_item(ts_code):
    """删除标的"""
    item = OpportunityLibrary.query.get(ts_code)
    if not item:
        return jsonify({'success': False, 'error': '标的不存在'}), 404

    db.session.delete(item)
    db.session.commit()

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
