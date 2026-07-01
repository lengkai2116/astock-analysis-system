"""
AI 投研路由（V3）
Phase 1: 6角色并行分析 + 三元组输出 + 综合报告 + 单角色重跑
"""
from datetime import datetime
from app.utils.error_handlers import handle_exceptions
from flask import Blueprint, request, jsonify

from app.services.deepseek_analysis_service import (
    start_analysis,
    get_progress,
    get_final_report,
    get_health,
    rerun_role,
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
    """A1: 启动6角色并行分析
    请求体: {ts_code, stock_name?, roles?}
    - roles 可选，指定部分角色分析
    """
    data = request.get_json(silent=True) or {}
    ts_code = data.get('ts_code', '').strip()
    stock_name = data.get('stock_name', '')
    roles = data.get('roles')

    if not ts_code:
        return jsonify({'success': False, 'error': '缺少 ts_code',
                        'error_type': 'BadRequest'}), 400

    analysis_id = start_analysis(ts_code, stock_name, roles)

    return jsonify({
        'success': True,
        'data': {
            'analysis_id': analysis_id,
            'ts_code': ts_code,
            'stock_name': stock_name or ts_code,
            'status': 'running',
            'roles': roles or [r['id'] for r in ANALYST_ROLES],
        }
    })


@handle_exceptions
@ai_analysis_bp.route('/api/v3/ai/analysts', methods=['GET'])
def get_analysts():
    """A2: 获取分析师列表（6角色完整信息，返回列表）"""
    return jsonify({
        'success': True,
        'data': [
            {
                'id': r['id'],
                'name': r['name'],
                'icon': r['icon'],
                'direction': r.get('direction', 'neutral'),
                'tag': r.get('tag', '中性'),
                'description': r.get('role_prompt', '').split('\n')[0],
            }
            for r in ANALYST_ROLES
        ]
    })


@handle_exceptions
@ai_analysis_bp.route('/api/v3/ai/analyst-progress', methods=['GET'])
def get_analyst_progress():
    """A3: 获取分析进度（含6角色独立进度）"""
    analysis_id = request.args.get('analysis_id', '')
    if not analysis_id:
        return jsonify({'success': False, 'error': '缺少 analysis_id',
                        'error_type': 'BadRequest'}), 400

    progress = get_progress(analysis_id)
    if progress is None:
        return jsonify({'success': False, 'error': '分析任务不存在',
                        'error_type': 'NotFound'}), 404

    return jsonify({'success': True, 'data': progress})


@handle_exceptions
@ai_analysis_bp.route('/api/v3/ai/final-report', methods=['GET'])
def get_final_report_route():
    """A4: 获取完整投研报告（含6角色三元组 + 综合报告）"""
    analysis_id = request.args.get('analysis_id', '')
    if not analysis_id:
        return jsonify({'success': False, 'error': '缺少 analysis_id',
                        'error_type': 'BadRequest'}), 400

    report = get_final_report(analysis_id)
    if report is None:
        progress = get_progress(analysis_id)
        if progress:
            return jsonify({
                'success': False, 'error': '分析尚未完成',
                'error_type': 'AnalysisInProgress',
                'progress': progress,
            }), 200
        return jsonify({'success': False, 'error': '分析任务不存在',
                        'error_type': 'NotFound'}), 404

    return jsonify({'success': True, 'data': report})


@handle_exceptions
@ai_analysis_bp.route('/api/v3/ai/health', methods=['GET'])
def health_check():
    """A5: 健康检查"""
    health = get_health()
    return jsonify({
        'success': True,
        'status': 'healthy',
        'config': health,
        'timestamp': datetime.now().isoformat(),
    })


@handle_exceptions
@ai_analysis_bp.route('/api/v3/ai/signal-explain', methods=['POST'])
def signal_explain():
    """A6: 信号解读（供 indicator-ide 使用）"""
    data = request.get_json(silent=True) or {}
    ts_code = data.get('ts_code', '')
    stock_name = data.get('stock_name', '')
    signals = data.get('signals', [])

    if not ts_code:
        return jsonify({'success': False, 'error': '缺少 ts_code',
                        'error_type': 'BadRequest'}), 400
    if not signals:
        return jsonify({'success': False, 'error': '缺少 signals',
                        'error_type': 'BadRequest'}), 400

    result = explain_signal(ts_code, stock_name, signals)

    return jsonify({
        'success': True,
        'data': {
            'ts_code': ts_code,
            'explanations': result.get('explanations', []),
            'composite_advice': result.get('composite_advice', ''),
        }
    })


@handle_exceptions
@ai_analysis_bp.route('/api/v3/ai/status-interpret', methods=['POST'])
def status_interpret():
    """A7: 现状识别 → AI解读（供 indicator-ide 使用）"""
    data = request.get_json(silent=True) or {}
    ts_code = data.get('ts_code', '')
    stock_name = data.get('stock_name', '')

    if not ts_code:
        return jsonify({'success': False, 'error': '缺少 ts_code',
                        'error_type': 'BadRequest'}), 400

    try:
        computation_service = SignalComputationService()
        signals = computation_service.compute_for_stock(ts_code)

        market_state = "UNKNOWN"
        market_state_sigs = [s for s in signals if s.get('market_state') and s['market_state'] != 'UNKNOWN']
        if market_state_sigs:
            from collections import Counter
            state_counts = Counter(s['market_state'] for s in market_state_sigs)
            market_state = state_counts.most_common(1)[0][0]

        status_service = StatusOutputService()
        try:
            aggregated_status = status_service.aggregate_v2(signals, market_state)
        except Exception:
            aggregated_status = status_service.aggregate(signals)

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
        logging.getLogger(__name__).error(f"Status interpret failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@handle_exceptions
@ai_analysis_bp.route('/api/v3/ai/rerun', methods=['POST'])
def rerun_analysis_role():
    """A8: 单角色重新分析"""
    data = request.get_json(silent=True) or {}
    analysis_id = data.get('analysis_id', '')
    role_id = data.get('role_id', '')

    if not analysis_id:
        return jsonify({'success': False, 'error': '缺少 analysis_id',
                        'error_type': 'BadRequest'}), 400
    if not role_id:
        return jsonify({'success': False, 'error': '缺少 role_id',
                        'error_type': 'BadRequest'}), 400

    result = rerun_role(analysis_id, role_id)
    if result is None:
        return jsonify({'success': False, 'error': '分析任务不存在或角色无效',
                        'error_type': 'NotFound'}), 404

    return jsonify({'success': True, 'data': result})


@handle_exceptions
@ai_analysis_bp.route('/api/v3/ai/reports', methods=['GET'])
def list_reports():
    """A9: 列出已完成的分析报告列表"""
    reports = []
    with _lock:
        for analysis_id, state in list(_analysis_store.items()):
            if state.get('status') == 'completed':
                reports.append({
                    'analysis_id': analysis_id,
                    'ts_code': state.get('ts_code', ''),
                    'stock_name': state.get('stock_name', ''),
                    'created_at': state.get('created_at', ''),
                    'completed_at': state.get('completed_at', ''),
                })

    # 按创建时间降序
    reports.sort(key=lambda r: r.get('created_at', ''), reverse=True)
    return jsonify({
        'success': True,
        'data': {'reports': reports[:50], 'total': len(reports)}
    })


@handle_exceptions
@ai_analysis_bp.route('/api/v3/ai-analysis/signals', methods=['GET'])
def get_ai_analysis_signals():
    """A10: 仪表盘 - AI 分析信号摘要 + 共振评分（来自6角色方向）"""
    signals = []
    resonance_scores = []

    with _lock:
        for analysis_id, state in list(_analysis_store.items()):
            if state.get('status') == 'completed':
                ts_code = state.get('ts_code', '')
                stock_name = state.get('stock_name', '')
                roles = state.get('roles', {})
                direction_map = {
                    '看多': 1, '偏多': 0.75, '中性偏多': 0.6,
                    '中性': 0.5, '中性偏空': 0.4, '偏空': 0.25, '看空': 0,
                    '可参与': 0.6, '观望': 0.3,
                }

                scores = []
                for rid, role_data in roles.items():
                    if role_data.get('status') == 'completed':
                        d = role_data.get('direction', '中性')
                        scores.append(direction_map.get(d, 0.5))

                overall = round((sum(scores) / len(scores) * 100) if scores else 50, 1)

                signals.append({
                    'ts_code': ts_code,
                    'stock_name': stock_name,
                    'type': 'bullish' if overall > 55 else 'bearish',
                    'overall_score': overall,
                    'analysis_id': analysis_id,
                })

                resonance_scores.append({
                    'id': analysis_id[-8:],
                    'name': stock_name or ts_code,
                    'score': overall,
                    'weight': 1.0,
                })

    overall_score = sum(s['score'] for s in resonance_scores) / len(resonance_scores) if resonance_scores else 0
    dims = sorted(resonance_scores, key=lambda x: x['score'], reverse=True)[:5]

    return jsonify({
        'success': True,
        'data': {
            'signals': signals[:10],
            'resonance': {
                'overall_score': round(overall_score, 1),
                'dimensions': dims,
            }
        }
    })
