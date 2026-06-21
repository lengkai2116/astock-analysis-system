"""
AI分析助手后端接口
提供多角色分析师协作分析功能
"""

import os
import json
import time
from datetime import datetime
from app.utils.error_handlers import handle_exceptions
from flask import Blueprint, request, jsonify

from app.services.deepseek_analysis_service import (
    start_analysis,
    get_progress,
    get_final_report,
    get_health,
    ANALYST_ROLES,
    _lock,
    _analysis_store,
    explain_signal,
    interpret_status,
)
from app.services.signal_computation_service import SignalComputationService
from app.services.status_output_service import StatusOutputService

ai_analysis_bp = Blueprint('ai_analysis', __name__)
@handle_exceptions
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
@handle_exceptions
@ai_analysis_bp.route('/api/v3/ai/analysts', methods=['GET'])
def get_analysts():
    """获取分析师列表"""
    return jsonify({
        'success': True,
        'data': {r['id']: {'name': r['name'], 'icon': r['icon']} for r in ANALYST_ROLES}
    })
@handle_exceptions
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
@handle_exceptions
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
@handle_exceptions
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
@handle_exceptions
@ai_analysis_bp.route('/api/v3/ai/signal-explain', methods=['POST'])
def signal_explain():
    """根据信号维度数据生成 AI 解读文本"""
    try:
        data = request.get_json() or {}
        ts_code = data.get('ts_code', '')
        stock_name = data.get('stock_name', '')
        signals = data.get('signals', [])

        if not ts_code:
            return jsonify({'success': False, 'error': 'ts_code is required'}), 400
        if not signals:
            return jsonify({'success': False, 'error': 'signals is required'}), 400

        result = explain_signal(ts_code, stock_name, signals)

        return jsonify({
            'success': True,
            'data': {
                'ts_code': ts_code,
                'explanations': result.get('explanations', []),
                'composite_advice': result.get('composite_advice', '')
            }
        })
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Signal explain failed: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e),
            'data': {
                'ts_code': ts_code if 'ts_code' in dir() else '',
                'explanations': [],
                'composite_advice': ''
            }
        }), 500


@handle_exceptions
@ai_analysis_bp.route('/api/v3/ai/status-interpret', methods=['POST'])
def status_interpret():
    """
    根据现状识别结果生成 AI 解读建议
    内部调用 signal_computation_service.compute_for_stock 和 StatusOutputService.aggregate
    """
    try:
        data = request.get_json() or {}
        ts_code = data.get('ts_code', '')
        stock_name = data.get('stock_name', '')

        if not ts_code:
            return jsonify({'success': False, 'error': 'ts_code is required'}), 400

        # 1. 计算多维策略信号
        computation_service = SignalComputationService()
        signals = computation_service.compute_for_stock(ts_code)

        # 2. 从信号中检测市场状态
        market_state = "UNKNOWN"
        market_state_sigs = [s for s in signals if s.get('market_state') and s['market_state'] != 'UNKNOWN']
        if market_state_sigs:
            from collections import Counter
            state_counts = Counter(s['market_state'] for s in market_state_sigs)
            market_state = state_counts.most_common(1)[0][0]

        # 3. 聚合现状视图 (V2优先，失败回退V1)
        status_service = StatusOutputService()
        try:
            aggregated_status = status_service.aggregate_v2(signals, market_state)
        except Exception:
            aggregated_status = status_service.aggregate(signals)

        # 4. AI 解读
        ai_interpretation = interpret_status(ts_code, stock_name, aggregated_status)

        return jsonify({
            'success': True,
            'data': {
                'aggregated_status': aggregated_status,
                'ai_interpretation': ai_interpretation,
            }
        })
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Status interpret failed: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e),
        }), 500


@handle_exceptions
@ai_analysis_bp.route('/api/v3/ai-analysis/signals', methods=['GET'])
def get_ai_analysis_signals():
    """仪表盘 - AI 分析信号摘要 + 共振评分"""

    signals = []
    resonance_scores = []

    # 从内存分析存储中提取最近的信号
    with _lock:
        for analysis_id, state in list(_analysis_store.items()):
            if state.get('status') == 'completed':
                ts_code = state.get('ts_code', '')
                stock_name = state.get('stock_name', '')
                progress = state.get('progress', {})
                analysts_data = progress.get('analysts', {})

                # 计算平均看多/看空评分
                total_bullish = 0
                total_bearish = 0
                analyst_count = 0
                for role_id, role_data in analysts_data.items():
                    bs = role_data.get('bullishScore', 0)
                    bears = role_data.get('bearishScore', 0)
                    if bs or bears:
                        total_bullish += bs
                        total_bearish += bears
                        analyst_count += 1

                overall = round((total_bullish / analyst_count) if analyst_count > 0 else 50, 1)
                signals.append({
                    'ts_code': ts_code,
                    'stock_name': stock_name,
                    'type': 'bullish' if overall > 50 else 'bearish',
                    'overall_score': overall,
                    'analysis_id': analysis_id,
                })

                resonance_scores.append({
                    'id': analysis_id[:8],
                    'name': stock_name or ts_code,
                    'score': overall,
                    'weight': 1.0,
                })

    # 没有信号时返回空数据
    overall_score = 0
    dims = []
    if resonance_scores:
        overall_score = round(sum(s['score'] for s in resonance_scores) / len(resonance_scores), 1)
        dims = resonance_scores[:5]

    return jsonify({
        'success': True,
        'data': {
            'signals': signals[:10],
            'resonance': {
                'overall_score': overall_score,
                'dimensions': dims,
            }
        }
    })
