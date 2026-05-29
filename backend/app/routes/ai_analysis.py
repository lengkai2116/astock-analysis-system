"""
AI分析助手后端接口
提供多角色分析师协作分析功能
"""

import os
import json
import time
from datetime import datetime
from flask import Blueprint, request, jsonify

from app.services.deepseek_analysis_service import (
    start_analysis,
    get_progress,
    get_final_report,
    get_health,
    ANALYST_ROLES
)

ai_analysis_bp = Blueprint('ai_analysis', __name__)


@ai_analysis_bp.route('/api/v3/ai/analyze', methods=['POST'])
def analyze_stock():
    """开始AI分析"""
    try:
        data = request.get_json() or {}
        ts_code = data.get('ts_code', '600519.SH')
        stock_name = data.get('stock_name', '')

        analysis_id = start_analysis(ts_code, stock_name)

        return jsonify({
            'success': True,
            'data': {
                'analysis_id': analysis_id,
                'ts_code': ts_code,
                'stock_name': stock_name,
                'status': 'running',
                'analysts': [r['id'] for r in ANALYST_ROLES]
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@ai_analysis_bp.route('/api/v3/ai/analysts', methods=['GET'])
def get_analysts():
    """获取分析师列表"""
    return jsonify({
        'success': True,
        'data': {r['id']: {'name': r['name'], 'icon': r['icon']} for r in ANALYST_ROLES}
    })


@ai_analysis_bp.route('/api/v3/ai/analyst-progress', methods=['GET'])
def get_analyst_progress():
    """获取分析进度"""
    analysis_id = request.args.get('analysis_id')
    if not analysis_id:
        return jsonify({'success': False, 'error': 'analysis_id is required'}), 400

    progress = get_progress(analysis_id)
    if progress is None:
        return jsonify({'success': False, 'error': 'analysis_id not found'}), 404

    return jsonify({'success': True, 'data': progress})


@ai_analysis_bp.route('/api/v3/ai/final-report', methods=['GET'])
def get_final_report_route():
    """获取最终投研报告"""
    analysis_id = request.args.get('analysis_id')
    if not analysis_id:
        return jsonify({'success': False, 'error': 'analysis_id is required'}), 400

    report = get_final_report(analysis_id)
    if report is None:
        # 可能还在进行中
        progress = get_progress(analysis_id)
        if progress:
            return jsonify({'success': False, 'error': '分析尚未完成', 'progress': progress}), 200
        return jsonify({'success': False, 'error': 'analysis_id not found'}), 404

    return jsonify({'success': True, 'data': report})


@ai_analysis_bp.route('/api/v3/ai/health', methods=['GET'])
def health_check():
    """健康检查"""
    health = get_health()
    return jsonify({
        'success': True,
        'status': 'healthy',
        'config': health,
        'timestamp': datetime.now().isoformat()
    })
