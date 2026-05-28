from flask import Blueprint, request, jsonify
from app import db
from app.services.strategy_output_service import StrategyOutputService
from app.services.strategy_template_service import StrategyTemplateService
from app.utils.error_handlers import handle_exceptions
from datetime import datetime

strategy_bp = Blueprint('strategy', __name__, url_prefix='/api/v2/strategy')

@strategy_bp.route('/outputs', methods=['GET'])
@handle_exceptions
def get_strategy_outputs():
    ts_code = request.args.get('ts_code')
    strategy_name = request.args.get('strategy_name')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    limit = int(request.args.get('limit', 100))
    
    if start_date:
        start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
    if end_date:
        end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
    
    outputs = StrategyOutputService.get_strategy_outputs(
        ts_code=ts_code,
        strategy_name=strategy_name,
        start_date=start_date,
        end_date=end_date,
        limit=limit
    )
    
    return jsonify({
        'success': True,
        'data': [o.to_dict() for o in outputs]
    })

@strategy_bp.route('/outputs', methods=['POST'])
@handle_exceptions
def create_strategy_output():
    data = request.json
    
    output = StrategyOutputService.create_strategy_output(
        ts_code=data.get('ts_code'),
        strategy_name=data.get('strategy_name'),
        signal=data.get('signal'),
        signal_date=datetime.strptime(data.get('signal_date'), '%Y-%m-%d').date(),
        confidence=data.get('confidence'),
        entry_zone=data.get('entry_zone'),
        risk_line=data.get('risk_line'),
        target_zone=data.get('target_zone'),
        position_suggestion=data.get('position_suggestion'),
        holding_period=data.get('holding_period'),
        evidence=data.get('evidence'),
        risk_notes=data.get('risk_notes')
    )
    
    return jsonify({
        'success': True,
        'data': output.to_dict()
    })

@strategy_bp.route('/outputs/<int:output_id>', methods=['DELETE'])
@handle_exceptions
def delete_strategy_output(output_id):
    success = StrategyOutputService.delete_strategy_output(output_id)
    return jsonify({
        'success': success,
        'message': '删除成功' if success else '删除失败'
    })

@strategy_bp.route('/outputs/latest', methods=['GET'])
@handle_exceptions
def get_latest_signal():
    ts_code = request.args.get('ts_code')
    if not ts_code:
        return jsonify({
            'success': False,
            'message': '缺少ts_code参数'
        }), 400
    
    signal = StrategyOutputService.get_latest_signal(ts_code)
    return jsonify({
        'success': True,
        'data': signal.to_dict() if signal else None
    })

@strategy_bp.route('/templates', methods=['GET'])
@handle_exceptions
def get_templates():
    template_type = request.args.get('template_type')
    is_system = request.args.get('is_system')
    
    if is_system is not None:
        is_system = is_system.lower() == 'true'
    
    templates = StrategyTemplateService.get_templates(
        template_type=template_type,
        is_system=is_system
    )
    
    return jsonify({
        'success': True,
        'data': [t.to_dict() for t in templates]
    })

@strategy_bp.route('/templates', methods=['POST'])
@handle_exceptions
def create_template():
    data = request.json
    template = StrategyTemplateService.create_template(
        name=data.get('name'),
        description=data.get('description'),
        template_type=data.get('template_type', 'indicator'),
        code_template=data.get('code_template'),
        author=data.get('author')
    )
    return jsonify({
        'success': True,
        'data': template.to_dict()
    })

@strategy_bp.route('/templates/<int:template_id>', methods=['GET'])
@handle_exceptions
def get_template(template_id):
    template = StrategyTemplateService.get_template_by_id(template_id)
    if not template:
        return jsonify({
            'success': False,
            'message': '模板不存在'
        }), 404
    
    return jsonify({
        'success': True,
        'data': template.to_dict()
    })

@strategy_bp.route('/templates/<int:template_id>', methods=['PUT'])
@handle_exceptions
def update_template(template_id):
    data = request.json
    template = StrategyTemplateService.update_template(
        template_id=template_id,
        name=data.get('name'),
        description=data.get('description'),
        code_template=data.get('code_template'),
        is_active=data.get('is_active')
    )
    
    if not template:
        return jsonify({
            'success': False,
            'message': '模板不存在'
        }), 404
    
    return jsonify({
        'success': True,
        'data': template.to_dict()
    })

@strategy_bp.route('/templates/<int:template_id>', methods=['DELETE'])
@handle_exceptions
def delete_template(template_id):
    success = StrategyTemplateService.delete_template(template_id)
    return jsonify({
        'success': success,
        'message': '删除成功' if success else '删除失败'
    })

@strategy_bp.route('/templates/<int:template_id>/use', methods=['POST'])
@handle_exceptions
def use_template(template_id):
    StrategyTemplateService.increment_usage(template_id)
    return jsonify({
        'success': True,
        'message': '使用次数已更新'
    })
