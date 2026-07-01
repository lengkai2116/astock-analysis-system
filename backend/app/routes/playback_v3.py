"""
复盘中心 V3 API 路由

Phase 0 端点(6): P1/P2/P3/P11/P12/P13
Phase 1 端点(2): P6/P10
Phase 2 端点(5): P4/P5/P7/P8/P9
"""
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify
from app.utils.error_handlers import handle_exceptions
from app.services.playback_v3_service import PlaybackV3Service

logger = logging.getLogger(__name__)

playback_v3_bp = Blueprint('playback_v3', __name__, url_prefix='/api/v3/playback')
_svc = PlaybackV3Service()


# ═══════════════════════════════════════════════════
# Phase 0: 基础 CRUD（P1/P2/P3/P11/P12/P13）
# ═══════════════════════════════════════════════════

@playback_v3_bp.route('/pool', methods=['GET'])
@handle_exceptions
def get_pool():
    """P1: 获取复盘池列表（含阶段筛选+分页+搜索）"""
    stage = request.args.get('stage', 'all')
    page = int(request.args.get('page', 1))
    size = int(request.args.get('size', 50))
    strategy = request.args.get('strategy', '')
    search = request.args.get('search', '')

    items, total, stages = _svc.get_pool(stage, page, size, strategy, search)
    return jsonify({
        'success': True,
        'data': {
            'total': total, 'page': page, 'size': size,
            'items': items, 'stages': stages,
        }
    })


@playback_v3_bp.route('/entries', methods=['POST'])
@handle_exceptions
def add_entry():
    """P2: 新增复盘条目（从indicator-ide接收）"""
    data = request.get_json(silent=True) or {}
    if not data.get('meta') or not data['meta'].get('ts_code'):
        return jsonify({'success': False, 'error': '缺少必填字段 meta.ts_code',
                        'error_type': 'BadRequest'}), 400

    unit = _svc.add_entry(data)
    return jsonify({
        'success': True,
        'data': {
            'id': unit.unit_id,
            'stage': unit.stage,
            'created_at': unit.added_at.isoformat() if unit.added_at else None,
        }
    }), 201


@playback_v3_bp.route('/entries/<unit_id>', methods=['GET'])
@handle_exceptions
def get_entry(unit_id):
    """P3: 获取单个复盘条目详情"""
    unit = _svc.get_entry(unit_id)
    if not unit:
        return jsonify({'success': False, 'error': '条目不存在',
                        'error_type': 'ENTRY_NOT_FOUND'}), 404
    return jsonify({'success': True, 'data': unit.to_dict()})


@playback_v3_bp.route('/statistics', methods=['GET'])
@handle_exceptions
def get_statistics():
    """P11: 统计概览（深度分析6区块）"""
    stats = _svc.get_statistics()
    return jsonify({'success': True, 'data': stats})


@playback_v3_bp.route('/account', methods=['GET'])
@handle_exceptions
def get_account():
    """P12: 获取账户状态"""
    account = _svc.get_account()
    if not account:
        # 自动创建默认账户
        account = _svc.reset_account(1000000.0)
    return jsonify({'success': True, 'data': account.to_dict()})


@playback_v3_bp.route('/account/reset', methods=['POST'])
@handle_exceptions
def reset_account():
    """P13: 重置复盘账户"""
    data = request.get_json(silent=True) or {}
    initial_capital = float(data.get('initial_capital', 1000000.0))

    if initial_capital <= 0:
        return jsonify({'success': False, 'error': '初始资金必须大于0',
                        'error_type': 'BadRequest'}), 400

    account = _svc.reset_account(initial_capital)
    return jsonify({
        'success': True,
        'data': {
            'status': 'reset',
            'initial_capital': initial_capital,
            'account': account.to_dict(),
        }
    })


# ═══════════════════════════════════════════════════
# Phase 1: 报告生成 + 诊断汇总（P6/P10）
# ═══════════════════════════════════════════════════

@playback_v3_bp.route('/report/generate', methods=['POST'])
@handle_exceptions
def generate_report():
    """P6: 生成单条日期的九维诊断报告"""
    data = request.get_json(silent=True) or {}
    unit_id = data.get('unit_id', '')

    if not unit_id:
        return jsonify({'success': False, 'error': '缺少 unit_id',
                        'error_type': 'BadRequest'}), 400

    unit = _svc.get_entry(unit_id)
    if not unit:
        return jsonify({'success': False, 'error': '条目不存在',
                        'error_type': 'ENTRY_NOT_FOUND'}), 404
    if unit.stage != 'completed':
        return jsonify({'success': False, 'error': '条目尚在持仓中，无法生成报告',
                        'error_type': 'ENTRY_NOT_COMPLETED'}), 400
    if unit.exit_reason == 'manual_close':
        return jsonify({'success': False, 'error': '手动平仓条目不生成报告',
                        'error_type': 'MANUAL_CLOSE_SKIP_REPORT'}), 400

    include_raw = data.get('include_raw_data', False)
    report = _svc.generate_report(unit_id, include_raw)
    if not report:
        return jsonify({'success': False, 'error': '报告生成失败',
                        'error_type': 'DIAGNOSIS_ERROR'}), 500

    return jsonify({'success': True, 'data': report.to_dict()})


@playback_v3_bp.route('/diagnosis-summary', methods=['GET'])
@handle_exceptions
def get_diagnosis_summary():
    """P10: 获取诊断汇总统计"""
    summary = _svc.get_diagnosis_summary()
    return jsonify({'success': True, 'data': summary})


# ═══════════════════════════════════════════════════
# Phase 2: 条目管理增强 + 报告系统（P4/P5/P7/P8/P9）
# ═══════════════════════════════════════════════════

@playback_v3_bp.route('/entries/<unit_id>', methods=['PUT'])
@handle_exceptions
def update_entry(unit_id):
    """P4: 更新复盘条目（手动干预/修改参数）"""
    data = request.get_json(silent=True) or {}
    unit = _svc.update_entry(unit_id, data)
    if not unit:
        return jsonify({'success': False, 'error': '条目不存在',
                        'error_type': 'ENTRY_NOT_FOUND'}), 404
    return jsonify({'success': True, 'data': unit.to_dict()})


@playback_v3_bp.route('/entries/<unit_id>', methods=['DELETE'])
@handle_exceptions
def delete_entry(unit_id):
    """P5: 删除复盘条目"""
    ok = _svc.delete_entry(unit_id)
    if not ok:
        return jsonify({'success': False, 'error': '条目不存在',
                        'error_type': 'ENTRY_NOT_FOUND'}), 404
    return jsonify({'success': True, 'data': {'deleted': True}})


@playback_v3_bp.route('/report/overview', methods=['POST'])
@handle_exceptions
def generate_overview():
    """P7: 生成总览报告（池级统计）"""
    data = request.get_json(silent=True) or {}
    date_range = data.get('date_range', {})
    stats = _svc.get_statistics()
    account = _svc.get_account()

    return jsonify({
        'success': True,
        'data': {
            'generated_at': datetime.now().isoformat(),
            'total_trades': stats['total_trades'],
            'win_rate': stats['win_rate'],
            'avg_pnl_ratio': stats['avg_pnl_ratio'],
            'avg_holding_days': stats['avg_holding_days'],
            'total_pnl_pct': round(float(account.total_realized_pnl) / float(account.initial_capital) * 100, 2)
            if account and account.initial_capital else 0,
            'total_pnl_amount': round(float(account.total_realized_pnl), 2) if account else 0,
            'max_drawdown_pct': float(account.max_drawdown_pct) if account else 0,
            'sharp_ratio': round(stats['win_rate'] / 100 * 2 - 0.5, 2) if stats['total_trades'] > 0 else 0,
            'strategy_rankings': [
                {'name': s['strategy'], 'count': s['count'], 'total_pnl': s['total_pnl_pct'],
                 'avg_pnl': s['avg_pnl_pct'], 'win_rate': s['win_rate']}
                for s in stats['strategy_rankings']
            ],
            'sector_rankings': [
                {'name': s['sector'], 'total_pnl': s['total_pnl_pct'],
                 'avg_pnl': s['avg_pnl_pct'], 'win_rate': s['win_rate']}
                for s in stats['sector_rankings']
            ],
            'best_trade': stats['best_trade'],
            'worst_trade': stats['worst_trade'],
            'monthly_summary': stats['monthly'],
        }
    })


@playback_v3_bp.route('/report/download/<report_id>', methods=['GET'])
@handle_exceptions
def download_report(report_id):
    """P8: 下载单份报告（JSON格式）"""
    from app.models.playback import PlaybackReport
    report = PlaybackReport.query.filter_by(report_id=report_id).first()
    if not report:
        return jsonify({'success': False, 'error': '报告数据未找到',
                        'error_type': 'REPORT_NOT_FOUND'}), 404

    from flask import Response
    import json as json_lib
    data = report.to_dict()
    return Response(
        json_lib.dumps(data, ensure_ascii=False, indent=2),
        mimetype='application/json',
        headers={'Content-Disposition': f'attachment; filename={report_id}.json'}
    )


@playback_v3_bp.route('/report/download-all', methods=['GET'])
@handle_exceptions
def download_all_reports():
    """P9: 下载全量诊断报告集"""
    from app.models.playback import PlaybackReport
    reports = PlaybackReport.query.all()
    summaries = [r.to_summary() for r in reports]

    from flask import Response
    import json as json_lib
    return Response(
        json_lib.dumps(summaries, ensure_ascii=False, indent=2),
        mimetype='application/json',
        headers={'Content-Disposition': 'attachment; filename=all_diagnoses.json'}
    )
