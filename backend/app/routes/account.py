"""
账户管理 API 路由 — P3.1

12个端点覆盖 125 号文档全部需求：
  交易 CRUD | 持仓 | 总览 | 资金曲线 | 绩效 | 复盘 | 信号匹配 | 虚拟验证
"""
import logging
from datetime import date, datetime
from flask import Blueprint, request, jsonify

from app import db
from app.models.trade import Trade
from app.services.account_service import AccountService
from app.services.signal_match_service import SignalMatchService
from app.services.review_engine import ReviewEngine
from app.services.report_generator import ReportGenerator
from app.utils.error_handlers import handle_exceptions

logger = logging.getLogger(__name__)

account_bp = Blueprint('account', __name__, url_prefix='/api/v1/account')

_account_svc = AccountService()
_match_svc = SignalMatchService()
_review_engine = ReviewEngine()
_report_gen = ReportGenerator()

# ═══════════════════════════════════════════════
# Tab A: 交易记录
# ═══════════════════════════════════════════════

@account_bp.route('/trades', methods=['GET'])
@handle_exceptions
def list_trades():
    """交易记录列表（分页+筛选）"""
    ts_code = request.args.get('ts_code')
    start = request.args.get('start_date')
    end = request.args.get('end_date')
    direction = request.args.get('direction')
    page = int(request.args.get('page', 1))
    per_page = min(int(request.args.get('per_page', 50)), 200)

    start_date = datetime.strptime(start, '%Y-%m-%d').date() if start else None
    end_date = datetime.strptime(end, '%Y-%m-%d').date() if end else None

    trades, total = _account_svc.get_trades(ts_code, start_date, end_date, direction, page, per_page)
    return jsonify({
        'success': True,
        'data': [t.to_dict() for t in trades],
        'total': total,
        'page': page,
        'per_page': per_page,
    })


@account_bp.route('/trades', methods=['POST'])
@handle_exceptions
def create_trade():
    """新增交易记录"""
    data = request.json or {}
    required = ['ts_code', 'direction', 'trade_date', 'price', 'quantity']
    missing = [k for k in required if k not in data]
    if missing:
        return jsonify({'success': False, 'error': f'缺少参数: {", ".join(missing)}'}), 400

    trade_date = data['trade_date']
    if isinstance(trade_date, str):
        trade_date = datetime.strptime(trade_date[:10], '%Y-%m-%d').date()

    trade = _account_svc.create_trade(
        ts_code=data['ts_code'],
        stock_name=data.get('stock_name', ''),
        direction=data['direction'],
        trade_date=trade_date,
        price=float(data['price']),
        quantity=int(data['quantity']),
        commission=float(data.get('commission', 0)),
        notes=data.get('notes', ''),
    )
    if trade:
        # 自动匹配信号
        try:
            result = _match_svc.match_trade(trade)
            if result.get('signal_id'):
                trade.matched_signal_id = result['signal_id']
                trade.matched_signal_type = result.get('signal_type')
                trade.matched_signal_confidence = result.get('signal_confidence')
                trade.match_score = result.get('match_score')
                db.session.commit()
        except Exception:
            pass
        return jsonify({'success': True, 'data': trade.to_dict()}), 201
    return jsonify({'success': False, 'error': '创建失败'}), 500


@account_bp.route('/trades/<int:trade_id>', methods=['PUT'])
@handle_exceptions
def update_trade(trade_id):
    """修改交易记录"""
    data = request.json or {}
    allowed = ['ts_code', 'stock_name', 'direction', 'trade_date', 'price', 'quantity', 'commission', 'notes']
    kwargs = {k: v for k, v in data.items() if k in allowed and v is not None}
    if 'trade_date' in kwargs and isinstance(kwargs['trade_date'], str):
        kwargs['trade_date'] = datetime.strptime(kwargs['trade_date'][:10], '%Y-%m-%d').date()
    trade = _account_svc.update_trade(trade_id, **kwargs)
    if trade:
        return jsonify({'success': True, 'data': trade.to_dict()})
    return jsonify({'success': False, 'error': '交易记录不存在'}), 404


@account_bp.route('/trades/<int:trade_id>', methods=['DELETE'])
@handle_exceptions
def delete_trade(trade_id):
    """删除交易记录"""
    ok = _account_svc.delete_trade(trade_id)
    if ok:
        return jsonify({'success': True, 'message': '已删除'})
    return jsonify({'success': False, 'error': '交易记录不存在'}), 404


@account_bp.route('/trades/import', methods=['POST'])
@handle_exceptions
def import_trades():
    """批量导入交易记录"""
    data = request.json or {}
    trades_data = data.get('trades', [])
    if not trades_data:
        return jsonify({'success': False, 'error': 'trades 列表为空'}), 400
    ok, fail = _account_svc.import_trades_batch(trades_data)
    return jsonify({'success': True, 'data': {'imported': ok, 'failed': fail}})


@account_bp.route('/trades/match', methods=['POST'])
@handle_exceptions
def match_trades():
    """批量匹配所有未匹配交易的信号"""
    count = _match_svc.match_all_pending()
    return jsonify({'success': True, 'data': {'matched': count}})


# ═══════════════════════════════════════════════
# Tab B: 持仓概览
# ═══════════════════════════════════════════════

@account_bp.route('/positions', methods=['GET'])
@handle_exceptions
def get_positions():
    """当前持仓列表"""
    positions = _account_svc.get_current_positions()
    return jsonify({'success': True, 'data': positions})


# ═══════════════════════════════════════════════
# 账户总览
# ═══════════════════════════════════════════════

@account_bp.route('/summary', methods=['GET'])
@handle_exceptions
def get_summary():
    """账户总览指标"""
    summary = _account_svc.get_account_summary()
    return jsonify({'success': True, 'data': summary})


# ═══════════════════════════════════════════════
# Tab C: 资金曲线
# ═══════════════════════════════════════════════

@account_bp.route('/equity-curve', methods=['GET'])
@handle_exceptions
def get_equity_curve():
    """资金曲线数据（每日净值）"""
    days = int(request.args.get('days', 365))
    curve = _account_svc.get_equity_curve(days)
    return jsonify({'success': True, 'data': curve})


@account_bp.route('/performance', methods=['GET'])
@handle_exceptions
def get_performance():
    """绩效指标汇总"""
    metrics = _account_svc.get_performance_metrics()
    return jsonify({'success': True, 'data': metrics})


# ═══════════════════════════════════════════════
# Tab D: 智能复盘
# ═══════════════════════════════════════════════

@account_bp.route('/review', methods=['POST'])
@handle_exceptions
def run_review():
    """
    执行复盘

    请求体:
    {
        "start_date": "2026-05-01",
        "end_date": "2026-05-28",
        "format": "markdown" (可选, 默认返回JSON结构化数据)
    }
    """
    data = request.json or {}
    start_str = data.get('start_date')
    end_str = data.get('end_date')
    fmt = data.get('format', 'json')

    if not start_str or not end_str:
        return jsonify({'success': False, 'error': '需要 start_date 和 end_date'}), 400

    start_date = datetime.strptime(start_str[:10], '%Y-%m-%d').date()
    end_date = datetime.strptime(end_str[:10], '%Y-%m-%d').date()

    trades = Trade.query.filter(
        Trade.trade_date >= start_date,
        Trade.trade_date <= end_date,
    ).order_by(Trade.trade_date.asc()).all()

    review = _review_engine.run_review(trades, start_date, end_date)

    if fmt == 'markdown':
        content = _report_gen.generate_review_report(review, format='markdown')
        return jsonify({
            'success': True,
            'data': {
                'total_score': review['total_score'],
                'markdown': content,
            }
        })

    return jsonify({'success': True, 'data': review})


@account_bp.route('/review/export', methods=['POST'])
@handle_exceptions
def export_review():
    """导出复盘报告为 Markdown 文件"""
    data = request.json or {}
    start_str = data.get('start_date')
    end_str = data.get('end_date')
    if not start_str or not end_str:
        return jsonify({'success': False, 'error': '需要 start_date 和 end_date'}), 400

    start_date = datetime.strptime(start_str[:10], '%Y-%m-%d').date()
    end_date = datetime.strptime(end_str[:10], '%Y-%m-%d').date()
    trades = Trade.query.filter(
        Trade.trade_date >= start_date,
        Trade.trade_date <= end_date,
    ).order_by(Trade.trade_date.asc()).all()

    review = _review_engine.run_review(trades, start_date, end_date)
    content = _report_gen.generate_review_report(review, format='markdown')

    filename = f"复盘报告-{start_str}-{end_str}.md"
    path = _report_gen.save_report(content, filename)
    return jsonify({'success': True, 'data': {'filepath': path}})


@account_bp.route('/virtual-reviews', methods=['GET'])
@handle_exceptions
def get_virtual_reviews():
    """虚拟验证复盘分区（轨B·已完成验证）"""
    vp_data = _account_svc.get_virtual_review_data()
    return jsonify({'success': True, 'data': vp_data})
