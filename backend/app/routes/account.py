"""
账户管理 API 路由 — P3.1 / 226号方案升级

10后端已就绪 + 4新端点 + D7/D8/D10扩充:
  Phase 0: trades CRUD/import/match | positions | summary | equity-curve | performance
  Phase 1: review(6D) | periodic-review | review-link | match-review
  D7: POST /trades/{id}/save-report | D8: GET/POST /config | D10: GET/POST /funds

DEPRECATED: /api/v1/account will be removed in future; use /api/v3/account
"""
import logging
from datetime import date, datetime, timedelta
from flask import Blueprint, request, jsonify

from app import db
from app.models.trade import Trade, AccountCashFlow
from app.services.account_service import AccountService
from app.services.signal_match_service import SignalMatchService
from app.services.review_engine import ReviewEngine6D, ReviewEngine
from app.services.report_generator import ReportGenerator
from app.utils.error_handlers import handle_exceptions

logger = logging.getLogger(__name__)

account_bp = Blueprint('account', __name__, url_prefix='/api/v1/account')

_account_svc = AccountService()
_match_svc = SignalMatchService()
_review_6d = ReviewEngine6D()
_review_7d = ReviewEngine()  # 保留旧的7维引擎
_report_gen = ReportGenerator()

# ═══════════════════════════════════════════════
# Tab A: 交易记录
# ═══════════════════════════════════════════════

@account_bp.route('/trades', methods=['GET'])
@handle_exceptions
def list_trades():
    """交易记录列表（分页+筛选+226扩展字段）"""
    ts_code = request.args.get('ts_code') or request.args.get('stock')
    start = request.args.get('start_date') or request.args.get('date_from')
    end = request.args.get('end_date') or request.args.get('date_to')
    direction = request.args.get('direction')
    page = int(request.args.get('page', 1))
    per_page = min(int(request.args.get('per_page', 50)), 200)

    start_date = datetime.strptime(start, '%Y-%m-%d').date() if start else None
    end_date = datetime.strptime(end, '%Y-%m-%d').date() if end else None

    trades, total = _account_svc.get_trades(ts_code, start_date, end_date, direction, page, per_page)
    return jsonify({
        'success': True,
        'data': {'trades': [t.to_dict() for t in trades]},
        'total': total,
        'page': page,
        'per_page': per_page,
    })


@account_bp.route('/trades', methods=['POST'])
@handle_exceptions
def create_trade():
    """新增交易记录（226号方案扩展字段）"""
    data = request.json or {}
    required = ['ts_code', 'direction', 'trade_date', 'price', 'quantity']
    # 支持 stock / stock_name 字段名
    ts_code = data.get('ts_code', data.get('stock', ''))
    stock_name = data.get('stock_name', data.get('sname', ''))
    missing = [k for k in required if k not in data and k != 'ts_code']
    if not ts_code:
        missing.append('ts_code')
    if missing:
        return jsonify({'success': False, 'error': f'缺少参数: {", ".join(missing)}'}), 400

    if not ts_code:
        return jsonify({'success': False, 'error': '缺少 ts_code'}), 400

    trade_date = data['trade_date']
    if isinstance(trade_date, str):
        trade_date = datetime.strptime(trade_date[:10], '%Y-%m-%d').date()

    trade = _account_svc.create_trade(
        ts_code=ts_code,
        stock_name=stock_name,
        direction=data['direction'],
        trade_date=trade_date,
        price=float(data['price']),
        quantity=int(data['quantity']),
        commission=float(data.get('commission', 0)),
        notes=data.get('notes', ''),
        buy_reason=data.get('buy_reason'),
        sell_reason=data.get('sell_reason'),
        review_unit_id=data.get('review_unit_id'),
        is_partial=data.get('is_partial', False),
        stamp_tax=float(data.get('stamp_tax', 0)),
        transfer_fee=float(data.get('transfer_fee', 0)),
        realized_pnl=float(data['realized_pnl']) if data.get('realized_pnl') else None,
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
    """修改交易记录（含226号方案字段）"""
    data = request.json or {}
    allowed = ['ts_code', 'stock_name', 'direction', 'trade_date', 'price', 'quantity',
               'commission', 'notes', 'buy_reason', 'sell_reason', 'review_unit_id',
               'is_partial', 'stamp_tax', 'transfer_fee', 'realized_pnl']
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
    """批量导入交易记录（含226扩展字段）"""
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
    """当前持仓列表（226号方案增强字段）"""
    positions = _account_svc.get_current_positions()
    total_pos_value = sum(p.get('market_value', 0) for p in positions)
    summary = _account_svc.get_account_summary()
    return jsonify({
        'success': True,
        'data': {
            'positions': positions,
            'total_position_value': total_pos_value,
            'total_assets': summary.get('total_assets', 0),
        }
    })


# ═══════════════════════════════════════════════
# 账户总览（KPI芯片条7项）
# ═══════════════════════════════════════════════

@account_bp.route('/summary', methods=['GET'])
@handle_exceptions
def get_summary():
    """账户总览指标（226号方案增强：7项KPI芯片+持仓汇总）"""
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
# Tab D: 六维操作复盘（226号方案）
# ═══════════════════════════════════════════════

@account_bp.route('/review', methods=['POST'])
@handle_exceptions
def run_review():
    """
    执行六维复盘（226号方案A-F维度，去评分化叙事格式）

    请求体:
    {
        "trade_ids": [1,2,3],  // 可选，指定交易ID
        "start_date": "2026-05-01",  // 可选，与 trade_ids 二选一
        "end_date": "2026-05-28",
        "format": "json"  // 支持 json/markdown
    }
    """
    data = request.json or {}
    trade_ids = data.get('trade_ids')
    start_str = data.get('start_date')
    end_str = data.get('end_date')
    fmt = data.get('format', 'json')

    if trade_ids:
        trades = Trade.query.filter(Trade.id.in_(trade_ids)).order_by(Trade.trade_date.asc()).all()
        if not trades:
            return jsonify({'success': False, 'error': '指定交易ID均不存在'}), 404
        start_date = trades[0].trade_date
        end_date = trades[-1].trade_date
    elif start_str and end_str:
        start_date = datetime.strptime(start_str[:10], '%Y-%m-%d').date()
        end_date = datetime.strptime(end_str[:10], '%Y-%m-%d').date()
        trades = Trade.query.filter(
            Trade.trade_date >= start_date, Trade.trade_date <= end_date
        ).order_by(Trade.trade_date.asc()).all()
    else:
        return jsonify({'success': False, 'error': '需要 trade_ids 或 start_date+end_date'}), 400

    review = _review_6d.run_review(trades, start_date, end_date)

    if fmt == 'markdown':
        content = _report_gen.generate_review_report(review, format='markdown')
        return jsonify({'success': True, 'data': {'review_id': review.get('review_id'), 'markdown': content}})

    return jsonify({'success': True, 'data': review})


@account_bp.route('/review/export', methods=['POST'])
@handle_exceptions
def export_review():
    """导出六维复盘报告为 Markdown 文件"""
    data = request.json or {}
    trade_ids = data.get('trade_ids')
    start_str = data.get('start_date')
    end_str = data.get('end_date')

    if trade_ids:
        trades = Trade.query.filter(Trade.id.in_(trade_ids)).order_by(Trade.trade_date.asc()).all()
        if not trades:
            return jsonify({'success': False, 'error': '指定交易ID均不存在'}), 404
        start_date = trades[0].trade_date
        end_date = trades[-1].trade_date
    elif start_str and end_str:
        start_date = datetime.strptime(start_str[:10], '%Y-%m-%d').date()
        end_date = datetime.strptime(end_str[:10], '%Y-%m-%d').date()
        trades = Trade.query.filter(
            Trade.trade_date >= start_date, Trade.trade_date <= end_date
        ).order_by(Trade.trade_date.asc()).all()
    else:
        return jsonify({'success': False, 'error': '需要 trade_ids 或 start_date+end_date'}), 400

    review = _review_6d.run_review(trades, start_date, end_date)
    content = _report_gen.generate_review_report(review, format='markdown')
    fname = f"六维复盘-{start_date}-{end_date}.md"
    path = _report_gen.save_report(content, fname)
    return jsonify({'success': True, 'data': {'filepath': path}})


# ═══════════════════════════════════════════════
# Tab E: 周期回顾（226号方案）
# ═══════════════════════════════════════════════

@account_bp.route('/periodic-review', methods=['POST'])
@handle_exceptions
def periodic_review():
    """
    周期回顾（本周/本月/本季/自定义）

    请求体:
    {
        "period": "week" | "month" | "quarter" | "custom",
        "start_date": "2026-06-01",  // 当 period=custom 时必填
        "end_date": "2026-06-30"
    }
    """
    data = request.json or {}
    period = data.get('period', 'month')
    today = date.today()

    if period == 'week':
        start_date = today - timedelta(days=today.weekday())
        end_date = today
    elif period == 'month':
        start_date = today.replace(day=1)
        end_date = today
    elif period == 'quarter':
        q_start = (today.month - 1) // 3 * 3 + 1
        start_date = today.replace(month=q_start, day=1)
        end_date = today
    elif period == 'custom':
        start_str = data.get('start_date')
        end_str = data.get('end_date')
        if not start_str or not end_str:
            return jsonify({'success': False, 'error': '自定义周期需要 start_date 和 end_date'}), 400
        start_date = datetime.strptime(start_str[:10], '%Y-%m-%d').date()
        end_date = datetime.strptime(end_str[:10], '%Y-%m-%d').date()
    else:
        return jsonify({'success': False, 'error': f'无效周期: {period}'}), 400

    trades = Trade.query.filter(
        Trade.trade_date >= start_date, Trade.trade_date <= end_date
    ).order_by(Trade.trade_date.asc()).all()

    # 运行六维复盘
    review = _review_6d.run_review(trades, start_date, end_date)
    summary = _account_svc.get_account_summary()

    # 构造周期回顾报告
    review_data = {
        'period': period,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'review': review,
        'summary': summary,
        'trade_count': len(trades),
    }

    return jsonify({'success': True, 'data': review_data})


# ═══════════════════════════════════════════════
# 复盘策略关联（226号方案）
# ═══════════════════════════════════════════════

@account_bp.route('/trades/<int:trade_id>/review-link', methods=['GET'])
@handle_exceptions
def review_link_candidates(trade_id):
    """获取可关联的复盘策略候选列表（按同票检索复盘中心RV）"""
    trade = Trade.query.get(trade_id)
    if not trade:
        return jsonify({'success': False, 'error': '交易记录不存在'}), 404

    candidates = _account_svc.get_review_candidates(trade.ts_code)
    return jsonify({'success': True, 'data': {'trade_id': trade_id, 'ts_code': trade.ts_code, 'candidates': candidates}})


@account_bp.route('/trades/<int:trade_id>/match-review', methods=['POST'])
@handle_exceptions
def match_trade_to_review(trade_id):
    """关联交易到复盘策略"""
    data = request.json or {}
    review_unit_id = data.get('review_unit_id', '')

    if not review_unit_id:
        return jsonify({'success': False, 'error': '缺少 review_unit_id'}), 400

    trade = Trade.query.get(trade_id)
    if not trade:
        return jsonify({'success': False, 'error': '交易记录不存在'}), 404

    trade.review_unit_id = review_unit_id
    db.session.commit()

    return jsonify({
        'success': True,
        'data': {
            'trade_id': trade_id,
            'review_unit_id': review_unit_id,
            'ts_code': trade.ts_code,
        }
    })


# ═══════════════════════════════════════════════
# 虚拟验证复盘分区（保持兼容）
# ═══════════════════════════════════════════════

@account_bp.route('/virtual-reviews', methods=['GET'])
@handle_exceptions
def get_virtual_reviews():
    """虚拟验证复盘分区（轨B·已完成验证）"""
    vp_data = _account_svc.get_virtual_review_data()
    return jsonify({'success': True, 'data': vp_data})


# ═══════════════════════════════════════════════
# D10: 资金变动记录
# ═══════════════════════════════════════════════

@account_bp.route('/funds', methods=['GET'])
@handle_exceptions
def list_fund_changes():
    """资金变动历史（追加/取款记录）"""
    limit = int(request.args.get('limit', 50))
    records = _account_svc.get_fund_history(limit)
    balance = _account_svc.get_current_balance()
    return jsonify({
        'success': True,
        'data': {
            'records': records,  # already Dicts from service
            'current_balance': balance,
        }
    })


@account_bp.route('/funds', methods=['POST'])
@handle_exceptions
def add_fund_change():
    """新增资金变动（追加/取款）"""
    data = request.json or {}
    change_type = data.get('change_type')
    amount = data.get('amount')
    note = data.get('note', '')

    if change_type not in ('deposit', 'withdraw'):
        return jsonify({'success': False, 'error': 'change_type 须为 deposit 或 withdraw'}), 400
    if not amount or float(amount) <= 0:
        return jsonify({'success': False, 'error': 'amount 须为正数'}), 400

    record = _account_svc.add_fund_change(
        change_date=datetime.strptime(
            data.get('change_date', date.today().isoformat())[:10], '%Y-%m-%d'
        ).date(),
        change_type=change_type,
        amount=float(amount),
        note=note,
    )
    return jsonify({'success': True, 'data': record.to_dict()}), 201


# ═══════════════════════════════════════════════
# D8: 账户配置持久化
# ═══════════════════════════════════════════════

@account_bp.route('/config', methods=['GET'])
@handle_exceptions
def load_config():
    """读取账户配置"""
    config = _account_svc.load_config()
    return jsonify({'success': True, 'data': config or {}})


@account_bp.route('/config', methods=['POST'])
@handle_exceptions
def save_config():
    """保存账户配置"""
    data = request.json or {}
    ok = _account_svc.save_config(data)
    if ok:
        return jsonify({'success': True, 'message': '配置已保存'})
    return jsonify({'success': False, 'error': '保存失败'}), 500


# ═══════════════════════════════════════════════
# D7: 将周期回顾归档到报告中心
# ═══════════════════════════════════════════════

@account_bp.route('/archive-report', methods=['POST'])
@handle_exceptions
def archive_periodic_report():
    """将周期回顾报告归档到报告中心"""
    data = request.json or {}
    content = data.get('content', '')
    report_type = data.get('report_type', '复盘回顾')
    title = data.get('title', f'周期回顾-{date.today().isoformat()}')

    try:
        from app.services.report_center_service import ReportCenterService
        svc = ReportCenterService()
        if hasattr(svc, 'save_report'):
            report_id = svc.save_report(
                title=title,
                report_type=report_type,
                content=content,
            )
            return jsonify({'success': True, 'data': {'report_id': report_id}})
    except Exception:
        pass

    # fallback: 按旧路径保存
    from app.services.report_generator import ReportGenerator
    rgen = ReportGenerator()
    fpath = rgen.save_report(content, f'{title}.md')
    return jsonify({'success': True, 'data': {'filepath': fpath}})


# ═══════════════════════════════════════════════
# v3 Blueprint (primary version)
# ═══════════════════════════════════════════════

account_v3_bp = Blueprint('account_v3', __name__, url_prefix='/api/v3/account')

account_v3_bp.add_url_rule('/trades', view_func=list_trades, methods=['GET'])
account_v3_bp.add_url_rule('/trades', view_func=create_trade, methods=['POST'])
account_v3_bp.add_url_rule('/trades/<int:trade_id>', view_func=update_trade, methods=['PUT'])
account_v3_bp.add_url_rule('/trades/<int:trade_id>', view_func=delete_trade, methods=['DELETE'])
account_v3_bp.add_url_rule('/trades/import', view_func=import_trades, methods=['POST'])
account_v3_bp.add_url_rule('/trades/match', view_func=match_trades, methods=['POST'])
account_v3_bp.add_url_rule('/positions', view_func=get_positions, methods=['GET'])
account_v3_bp.add_url_rule('/summary', view_func=get_summary, methods=['GET'])
account_v3_bp.add_url_rule('/equity-curve', view_func=get_equity_curve, methods=['GET'])
account_v3_bp.add_url_rule('/performance', view_func=get_performance, methods=['GET'])
account_v3_bp.add_url_rule('/review', view_func=run_review, methods=['POST'])
account_v3_bp.add_url_rule('/review/export', view_func=export_review, methods=['POST'])
account_v3_bp.add_url_rule('/periodic-review', view_func=periodic_review, methods=['POST'])
account_v3_bp.add_url_rule('/trades/<int:trade_id>/review-link', view_func=review_link_candidates, methods=['GET'])
account_v3_bp.add_url_rule('/trades/<int:trade_id>/match-review', view_func=match_trade_to_review, methods=['POST'])
account_v3_bp.add_url_rule('/virtual-reviews', view_func=get_virtual_reviews, methods=['GET'])
account_v3_bp.add_url_rule('/funds', view_func=list_fund_changes, methods=['GET'])
account_v3_bp.add_url_rule('/funds', view_func=add_fund_change, methods=['POST'])
account_v3_bp.add_url_rule('/config', view_func=load_config, methods=['GET'])
account_v3_bp.add_url_rule('/config', view_func=save_config, methods=['POST'])
account_v3_bp.add_url_rule('/archive-report', view_func=archive_periodic_report, methods=['POST'])
