"""
条件库管理 API 路由

提供条件库的 CRUD + 统计查询 + 使用追踪
全量条件存储在 condition_registry 表中
前端概览面板仅展示统计聚合

端点设计：
  - 条件库概览（dashboard 查看端口）: 仅返回统计
  - 条件库全量管理（系统诊断入口）: 支持 CRUD
"""
from flask import Blueprint, jsonify, request
from sqlalchemy import func, case, desc

from app import db

conditions_bp = Blueprint('conditions', __name__, url_prefix='/api/v3/conditions')


@conditions_bp.route('/overview', methods=['GET'])
def get_conditions_overview():
    """条件库概览统计 — 供前端仪表盘查看端口调用

    返回汇总统计（不包含条件全量列表），包括：
      - 条件总数
      - data_readiness 分布（ready/pending/qmt_needed/insufficient）
      - 难度分布
      - 分类分布
      - Top N 最常见条件
      - 低频/从未使用条件
    """
    from app.models.condition import ConditionRegistry

    total = db.session.query(func.count(ConditionRegistry.id)).scalar() or 0

    # 按 data_readiness 分组
    readiness_stats = db.session.query(
        ConditionRegistry.data_readiness,
        func.count(ConditionRegistry.id)
    ).group_by(ConditionRegistry.data_readiness).all()
    readiness_dist = {row[0]: row[1] for row in readiness_stats} if readiness_stats else {}

    # 按难度分组
    difficulty_stats = db.session.query(
        ConditionRegistry.difficulty_level,
        func.count(ConditionRegistry.id)
    ).group_by(ConditionRegistry.difficulty_level).all()
    difficulty_dist = {row[0]: row[1] for row in difficulty_stats} if difficulty_stats else {}

    # 按分类分组
    category_stats = db.session.query(
        ConditionRegistry.category,
        func.count(ConditionRegistry.id)
    ).group_by(ConditionRegistry.category).all()
    category_dist = {row[0]: row[1] for row in category_stats} if category_stats else {}

    # Top 10 最常见
    top_used = ConditionRegistry.query \
        .order_by(desc(ConditionRegistry.usage_count)) \
        .limit(10).all()

    # 从未被使用
    unused = ConditionRegistry.query \
        .filter(ConditionRegistry.usage_count == 0) \
        .order_by(ConditionRegistry.name) \
        .all()

    return jsonify({
        'success': True,
        'data': {
            'total': total,
            'readiness_distribution': readiness_dist,
            'difficulty_distribution': difficulty_dist,
            'category_distribution': category_dist,
            'top_used': [c.to_overview() for c in top_used],
            'unused': [c.to_overview() for c in unused],
            'unused_count': len(unused),
        }
    })


@conditions_bp.route('', methods=['GET'])
@conditions_bp.route('/list', methods=['GET'])
def list_conditions():
    """全量条件列表（分页）— 供条件库管理后台调用

    Query params:
      - page: int (default 1)
      - per_page: int (default 20)
      - readiness: str (筛选状态)
      - category: str (筛选分类)
      - difficulty: str (筛选难度)
      - search: str (模糊搜索)
    """
    from app.models.condition import ConditionRegistry

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    readiness_filter = request.args.get('readiness')
    category_filter = request.args.get('category')
    difficulty_filter = request.args.get('difficulty')
    search = request.args.get('search')

    query = ConditionRegistry.query

    if readiness_filter:
        query = query.filter(ConditionRegistry.data_readiness == readiness_filter)
    if category_filter:
        query = query.filter(ConditionRegistry.category == category_filter)
    if difficulty_filter:
        query = query.filter(ConditionRegistry.difficulty_level == difficulty_filter)
    if search:
        like_pattern = f'%{search}%'
        query = query.filter(
            ConditionRegistry.name.ilike(like_pattern) |
            ConditionRegistry.display_name.ilike(like_pattern) |
            ConditionRegistry.condition_id.ilike(like_pattern)
        )

    query = query.order_by(ConditionRegistry.category, ConditionRegistry.name)

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'success': True,
        'data': {
            'items': [c.to_dict() for c in pagination.items],
            'total': pagination.total,
            'page': pagination.page,
            'per_page': pagination.per_page,
            'pages': pagination.pages,
        }
    })


@conditions_bp.route('/<string:condition_id>', methods=['GET'])
def get_condition(condition_id):
    """获取单条条件详情"""
    from app.models.condition import ConditionRegistry

    condition = ConditionRegistry.query.filter_by(condition_id=condition_id).first()
    if not condition:
        return jsonify({'success': False, 'error': '条件不存在'}), 404

    return jsonify({'success': True, 'data': condition.to_dict()})


@conditions_bp.route('', methods=['POST'])
def create_condition():
    """新增条件"""
    from app.models.condition import ConditionRegistry

    data = request.get_json()
    if not data or not data.get('condition_id'):
        return jsonify({'success': False, 'error': 'condition_id 为必填项'}), 400

    existing = ConditionRegistry.query.filter_by(condition_id=data['condition_id']).first()
    if existing:
        return jsonify({'success': False, 'error': 'condition_id 已存在'}), 409

    condition = ConditionRegistry(
        condition_id=data['condition_id'],
        name=data.get('name', ''),
        display_name=data.get('display_name'),
        category=data.get('category'),
        category_path=data.get('category_path', []),
        difficulty_level=data.get('difficulty_level', '入门'),
        data_source=data.get('data_source'),
        data_readiness=data.get('data_readiness', 'pending'),
        default_params=data.get('default_params', {}),
        linked_strategies=data.get('linked_strategies', []),
        related_conditions=data.get('related_conditions', []),
        description=data.get('description', {}),
        notes=data.get('notes', ''),
    )
    db.session.add(condition)
    db.session.commit()

    return jsonify({'success': True, 'data': condition.to_dict()}), 201


@conditions_bp.route('/<string:condition_id>', methods=['PUT'])
def update_condition(condition_id):
    """更新条件"""
    from app.models.condition import ConditionRegistry

    condition = ConditionRegistry.query.filter_by(condition_id=condition_id).first()
    if not condition:
        return jsonify({'success': False, 'error': '条件不存在'}), 404

    data = request.get_json()
    updateable_fields = [
        'name', 'display_name', 'category', 'category_path',
        'difficulty_level', 'data_source', 'data_readiness',
        'default_params', 'linked_strategies', 'related_conditions',
        'description', 'notes',
    ]
    for field in updateable_fields:
        if field in data:
            setattr(condition, field, data[field])

    db.session.commit()
    return jsonify({'success': True, 'data': condition.to_dict()})


@conditions_bp.route('/<string:condition_id>', methods=['DELETE'])
def delete_condition(condition_id):
    """删除条件（标记删除，保留引用）"""
    from app.models.condition import ConditionRegistry

    condition = ConditionRegistry.query.filter_by(condition_id=condition_id).first()
    if not condition:
        return jsonify({'success': False, 'error': '条件不存在'}), 404

    # 硬删除（或改为标记删除）
    db.session.delete(condition)
    db.session.commit()
    return jsonify({'success': True, 'message': f'条件 {condition_id} 已删除'})


@conditions_bp.route('/<string:condition_id>/usage', methods=['POST'])
def record_usage(condition_id):
    """记录条件被使用（创建/编辑规则时调用）"""
    from app.models.condition import ConditionRegistry

    condition = ConditionRegistry.query.filter_by(condition_id=condition_id).first()
    if not condition:
        return jsonify({'success': False, 'error': '条件不存在'}), 404

    condition.usage_count = (condition.usage_count or 0) + 1
    condition.last_used = func.now()
    db.session.commit()

    return jsonify({'success': True, 'data': {'usage_count': condition.usage_count}})


@conditions_bp.route('/stats', methods=['GET'])
def get_condition_stats():
    """获取使用统计（TopN+分类分布+就绪分布）"""
    from app.models.condition import ConditionRegistry

    # 总数
    total = db.session.query(func.count(ConditionRegistry.id)).scalar() or 0

    # 按状态统计
    readiness_stats = db.session.query(
        ConditionRegistry.data_readiness,
        func.count(ConditionRegistry.id)
    ).group_by(ConditionRegistry.data_readiness).all()
    readiness_dist = {r[0]: r[1] for r in readiness_stats} if readiness_stats else {}

    # Top 20 面向前端展示
    top_used = ConditionRegistry.query \
        .order_by(desc(ConditionRegistry.usage_count)) \
        .limit(20).all()

    return jsonify({
        'success': True,
        'data': {
            'total': total,
            'readiness_distribution': readiness_dist,
            'top_used': [c.to_overview() for c in top_used],
        }
    })
