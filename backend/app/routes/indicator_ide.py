"""
"指标 IDE API 路由
提供指标合约解析、质量检查、沙箱运行等功能"
DEPRECATED: /api/v2/indicator will be removed in future; use /api/v3/indicator
"""
from app.utils.error_handlers import handle_exceptions
from flask import Blueprint, request, jsonify
from app.services.indicator_contract import IndicatorContractParser
from app.services.indicator_quality import IndicatorQualityChecker
from app.services.indicator_sandbox import IndicatorSandbox
import pandas as pd
import numpy as np

indicator_ide_bp = Blueprint('indicator_ide', __name__, url_prefix='/api/v2/indicator')

parser = IndicatorContractParser()
checker = IndicatorQualityChecker()
sandbox = IndicatorSandbox()
@handle_exceptions
@indicator_ide_bp.route('/parse', methods=['POST'])
def parse_indicator():
    code = request.json.get('code')
    
    if not code:
        return jsonify({
            'success': False,
            'message': '缺少指标代码'
        }), 400
    
    try:
        parse_result = parser.parse(code)
        config = parser.generate_config(parse_result)
        
        return jsonify({
            'success': True,
            'data': {
                'parsing': parse_result,
                'config': config
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'解析失败: {str(e)}'
        }), 500
@handle_exceptions
@indicator_ide_bp.route('/check', methods=['POST'])
def check_indicator():
    code = request.json.get('code')
    
    if not code:
        return jsonify({
            'success': False,
            'message': '缺少指标代码'
        }), 400
    
    try:
        check_result = checker.check(code)
        
        return jsonify({
            'success': True,
            'data': check_result
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'检查失败: {str(e)}'
        }), 500
@handle_exceptions
@indicator_ide_bp.route('/execute', methods=['POST'])
def execute_indicator():
    code = request.json.get('code')
    params = request.json.get('params', {})
    ts_code = request.json.get('ts_code')
    start_date = request.json.get('start_date')
    end_date = request.json.get('end_date')
    
    if not code:
        return jsonify({
            'success': False,
            'message': '缺少指标代码'
        }), 400
    
    try:
        df = None
        if ts_code:
            df = _get_stock_data(ts_code, start_date, end_date)
        
        execute_result = sandbox.execute(code, df, **params)
        
        if execute_result['success']:
            return jsonify({
                'success': True,
                'data': execute_result
            })
        else:
            return jsonify({
                'success': False,
                'message': execute_result.get('error', '执行失败'),
                'data': execute_result
            }), 400
            
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'执行失败: {str(e)}'
        }), 500
@handle_exceptions
@indicator_ide_bp.route('/validate', methods=['POST'])
def validate_indicator():
    code = request.json.get('code')
    
    if not code:
        return jsonify({
            'success': False,
            'message': '缺少指标代码'
        }), 400
    
    try:
        parse_result = parser.parse(code)
        check_result = checker.check(code)
        execute_result = sandbox.dry_run(code)
        
        all_issues = check_result.get('issues', [])
        all_warnings = check_result.get('warnings', [])
        
        if not execute_result['success']:
            all_issues.append({
                'type': 'execution_error',
                'severity': 'error',
                'message': execute_result.get('error', '执行失败')
            })
        
        return jsonify({
            'success': len(all_issues) == 0,
            'data': {
                'parsing': parse_result,
                'check': {
                    'issues': all_issues,
                    'warnings': all_warnings
                },
                'execution': execute_result
            }
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'验证失败: {str(e)}'
        }), 500


def _get_stock_data(ts_code: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    try:
        from app.data import DataManager
        data_manager = DataManager()
        df = data_manager.get_cached_daily_data(ts_code, start_date, end_date)
        
        if df is not None and not df.empty:
            required_columns = ['trade_date', 'open', 'high', 'low', 'close', 'vol']
            for col in required_columns:
                if col not in df.columns:
                    raise ValueError(f'缺少必需的数据列: {col}')
            return df
        
        from flask import jsonify
        raise ValueError(f'股票 {ts_code} 日线数据不可用，无法计算指标')
        
    except Exception as e:
        logger.warning(f"获取股票数据失败 ({ts_code}): {e}")
        raise ValueError(f'股票 {ts_code} 日线数据不可用，无法计算指标')


# ═══════════════════════════════════════════════
# v3 Blueprint (primary version)
# ═══════════════════════════════════════════════

indicator_ide_v3_bp = Blueprint('indicator_ide_v3', __name__, url_prefix='/api/v3/indicator')

indicator_ide_v3_bp.add_url_rule('/parse', view_func=parse_indicator, methods=['POST'])
indicator_ide_v3_bp.add_url_rule('/check', view_func=check_indicator, methods=['POST'])
indicator_ide_v3_bp.add_url_rule('/execute', view_func=execute_indicator, methods=['POST'])
indicator_ide_v3_bp.add_url_rule('/validate', view_func=validate_indicator, methods=['POST'])
