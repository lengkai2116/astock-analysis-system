"""
AI分析助手后端接口
提供多角色分析师协作分析功能
"""

import os
import json
import time
from datetime import datetime
from flask import Blueprint, request, jsonify

ai_analysis_bp = Blueprint('ai_analysis', __name__)

ANALYSTS = {
    'technical': {
        'name': '技术分析师',
        'icon': '📊',
        'prompt': '你是一名技术分析师，专注于通过K线形态、技术指标、成交量等技术分析手段来评估股票走势。',
        'color': '#3b82f6'
    },
    'fundamental': {
        'name': '基本面分析师',
        'icon': '📈',
        'prompt': '你是一名基本面分析师，专注于分析公司的财务报表、行业地位、竞争优势、盈利能力等基本面因素。',
        'color': '#10b981'
    },
    'macro': {
        'name': '宏观策略师',
        'icon': '🌐',
        'prompt': '你是一名宏观策略师，专注于分析宏观经济环境、政策导向、市场情绪、资金流向等宏观因素。',
        'color': '#8b5cf6'
    },
    'risk': {
        'name': '风险控制官',
        'icon': '🛡️',
        'prompt': '你是一名风险控制官，专注于识别和评估投资风险，包括市场风险、信用风险、流动性风险等。',
        'color': '#f59e0b'
    },
    'fund_manager': {
        'name': '资深基金经理',
        'icon': '💼',
        'prompt': '你是一名资深基金经理，拥有20年投资经验，擅长价值投资和风险管理，给出实际可执行的投资建议。',
        'color': '#ec4899'
    }
}

@ai_analysis_bp.route('/api/v3/ai/analyze', methods=['POST'])
def analyze_stock():
    """开始AI分析"""
    try:
        data = request.get_json()
        ts_code = data.get('ts_code', '600519.SH')
        stock_name = data.get('stock_name', '贵州茅台')

        return jsonify({
            'success': True,
            'data': {
                'analysis_id': f'analyze_{int(time.time())}',
                'ts_code': ts_code,
                'stock_name': stock_name,
                'status': 'not_configured',
                'message': 'AI 分析服务未配置。请先配置 LLM 提供商（DeepSeek / LM Studio）并设置 LLM_PROVIDER 环境变量。',
                'analysts': list(ANALYSTS.keys())
            }
        }), 503
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@ai_analysis_bp.route('/api/v3/ai/analysts', methods=['GET'])
def get_analysts():
    """获取分析师列表"""
    return jsonify({
        'success': True,
        'data': ANALYSTS
    }), 200

@ai_analysis_bp.route('/api/v3/ai/analyst-progress', methods=['GET'])
def get_analyst_progress():
    """获取分析师进度"""
    analysis_id = request.args.get('analysis_id')
    if not analysis_id:
        return jsonify({'success': False, 'error': 'analysis_id is required'}), 400

    return jsonify({
        'success': False,
        'error': 'AI 分析服务未配置。请先配置 LLM 提供商。',
        'code': 'SERVICE_NOT_CONFIGURED'
    }), 503

@ai_analysis_bp.route('/api/v3/ai/analyst-result', methods=['GET'])
def get_analyst_result():
    """获取单个分析师结果"""
    analysis_id = request.args.get('analysis_id')
    analyst_type = request.args.get('analyst_type')

    if not analysis_id or not analyst_type:
        return jsonify({
            'success': False,
            'error': 'analysis_id and analyst_type are required'
        }), 400

    analyst = ANALYSTS.get(analyst_type)
    if not analyst:
        return jsonify({'success': False, 'error': 'Invalid analyst type'}), 400

    return jsonify({
        'success': False,
        'error': 'AI 分析服务未配置。请先配置 LLM 提供商。',
        'code': 'SERVICE_NOT_CONFIGURED'
    }), 503

@ai_analysis_bp.route('/api/v3/ai/final-report', methods=['GET'])
def get_final_report():
    """获取最终投研报告"""
    analysis_id = request.args.get('analysis_id')
    if not analysis_id:
        return jsonify({'success': False, 'error': 'analysis_id is required'}), 400

    return jsonify({
        'success': False,
        'error': 'AI 分析服务未配置。请先配置 LLM 提供商。',
        'code': 'SERVICE_NOT_CONFIGURED'
    }), 503

@ai_analysis_bp.route('/api/v3/ai/health', methods=['GET'])
def health_check():
    """健康检查"""
    return jsonify({
        'success': True,
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    }), 200
