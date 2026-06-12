"""
阶段三API路由
- 技术指标接口
- 信号接口
- 自选股接口
- 投资组合接口
- 模拟交易接口
"""
from app.utils.error_handlers import handle_exceptions
from flask import Blueprint, request, jsonify
from app import db
from app.models import (
    TechnicalIndicator, Signal, Watchlist,
    Portfolio, PortfolioHolding, PaperTrade, Stock, DailyData
)
from app.indicators import TechnicalIndicatorEngine
from app.signals import SignalGenerator
from app.data import DataManager
from datetime import datetime, date
import pandas as pd

phase3_bp = Blueprint('phase3', __name__, url_prefix='/api/v3')

indicator_engine = TechnicalIndicatorEngine()
signal_generator = SignalGenerator()

# 懒加载data_manager
_data_manager = None

def get_data_manager():
    global _data_manager
    if _data_manager is None:
        _data_manager = DataManager()
    return _data_manager


# ====================
# 技术指标接口
# ====================
@handle_exceptions
@phase3_bp.route('/indicators/<ts_code>', methods=['GET'])
def get_indicators(ts_code):
    """获取技术指标数据"""
    limit = request.args.get('limit', 100, type=int)
    
    indicators = TechnicalIndicator.query.filter_by(
        ts_code=ts_code
    ).order_by(TechnicalIndicator.trade_date.desc()).limit(limit).all()
    
    return jsonify({
        'success': True,
        'data': [i.to_dict() for i in indicators]
    })
@handle_exceptions
@phase3_bp.route('/indicators/<ts_code>/calculate', methods=['POST'])
def calculate_indicators(ts_code):
    """计算技术指标"""
    start_date = request.json.get('start_date')
    end_date = request.json.get('end_date')
    
    try:
        data_manager = get_data_manager()
        daily_data = data_manager.get_cached_daily_data(ts_code, start_date, end_date)
        
        if daily_data.empty:
            return jsonify({
                'success': False,
                'message': 'No daily data found'
            }), 404
        
        # 计算技术指标
        result = indicator_engine.calculate_all_indicators(daily_data)
        
        # 保存到数据库
        for _, row in result.iterrows():
            existing = TechnicalIndicator.query.filter_by(
                ts_code=ts_code,
                trade_date=row['trade_date']
            ).first()
            
            if not existing:
                ind = TechnicalIndicator(
                    ts_code=ts_code,
                    trade_date=row['trade_date'],
                    ma5=row.get('ma5'),
                    ma10=row.get('ma10'),
                    ma20=row.get('ma20'),
                    macd_dif=row.get('macd_dif'),
                    macd_dea=row.get('macd_dea'),
                    macd_bar=row.get('macd_bar'),
                    rsi=row.get('rsi'),
                    kdj_k=row.get('kdj_k'),
                    kdj_d=row.get('kdj_d'),
                    kdj_j=row.get('kdj_j'),
                    boll_upper=row.get('boll_upper'),
                    boll_middle=row.get('boll_middle'),
                    boll_lower=row.get('boll_lower')
                )
                db.session.add(ind)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'data': result.to_dict('records')
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


# ====================
# 信号接口
# ====================
@handle_exceptions
@phase3_bp.route('/signals', methods=['GET'])
def get_signals():
    """获取信号列表"""
    ts_code = request.args.get('ts_code')
    limit = request.args.get('limit', 50, type=int)
    
    query = Signal.query
    if ts_code:
        query = query.filter_by(ts_code=ts_code)
    
    signals = query.order_by(Signal.created_at.desc()).limit(limit).all()
    
    return jsonify({
        'success': True,
        'data': [s.to_dict() for s in signals]
    })
@handle_exceptions
@phase3_bp.route('/signals/generate', methods=['POST'])
def generate_signals():
    """生成信号"""
    ts_code = request.json.get('ts_code')
    
    try:
        data_manager = get_data_manager()
        daily_data = data_manager.get_cached_daily_data(ts_code)
        
        if daily_data.empty:
            return jsonify({
                'success': False,
                'message': 'No daily data'
            }), 404
        
        signals = signal_generator.generate_all_signals(daily_data)
        
        return jsonify({
            'success': True,
            'data': signals
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


# ====================
# 自选股接口
# ====================
@handle_exceptions
@phase3_bp.route('/watchlist', methods=['GET'])
def get_watchlist():
    """获取自选股列表"""
    watchlist = Watchlist.query.order_by(Watchlist.added_at.desc()).all()
    return jsonify({
        'success': True,
        'data': [w.to_dict() for w in watchlist]
    })
@handle_exceptions
@phase3_bp.route('/watchlist', methods=['POST'])
def add_to_watchlist():
    """添加到自选股"""
    ts_code = request.json.get('ts_code')
    notes = request.json.get('notes', '')
    
    existing = Watchlist.query.filter_by(ts_code=ts_code).first()
    
    if existing:
        return jsonify({
            'success': False,
            'message': 'Already in watchlist'
        }), 409
    
    watchlist = Watchlist(ts_code=ts_code, notes=notes)
    db.session.add(watchlist)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'data': watchlist.to_dict()
    })
@handle_exceptions
@phase3_bp.route('/watchlist/<int:id>', methods=['DELETE'])
def remove_from_watchlist(id):
    """从自选股移除"""
    watchlist = Watchlist.query.get(id)
    
    if not watchlist:
        return jsonify({
            'success': False,
            'message': 'Not found'
        }), 404
    
    db.session.delete(watchlist)
    db.session.commit()
    
    return jsonify({
        'success': True
    })


# ====================
# 投资组合接口
# ====================
@handle_exceptions
@phase3_bp.route('/portfolio', methods=['GET'])
def get_portfolio():
    """获取投资组合"""
    portfolios = Portfolio.query.order_by(Portfolio.created_at.desc()).all()
    return jsonify({
        'success': True,
        'data': [p.to_dict() for p in portfolios]
    })
@handle_exceptions
@phase3_bp.route('/portfolio', methods=['POST'])
def create_portfolio():
    """创建投资组合"""
    name = request.json.get('name', 'My Portfolio')
    initial_capital = request.json.get('initial_capital', 100000.0)
    
    portfolio = Portfolio(name=name, initial_capital=initial_capital)
    db.session.add(portfolio)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'data': portfolio.to_dict()
    })
@handle_exceptions
@phase3_bp.route('/portfolio/<int:id>', methods=['GET'])
def get_portfolio_detail(id):
    """获取投资组合详情"""
    portfolio = Portfolio.query.get(id)
    if not portfolio:
        return jsonify({
            'success': False,
            'message': 'Not found'
        }), 404
    
    holdings = PortfolioHolding.query.filter_by(portfolio_id=id).all()
    
    return jsonify({
        'success': True,
        'data': {
            'portfolio': portfolio.to_dict(),
            'holdings': [h.to_dict() for h in holdings]
        }
    })
@handle_exceptions
@phase3_bp.route('/portfolio/<int:id>/trade', methods=['POST'])
def paper_trade(id):
    """模拟交易"""
    portfolio = Portfolio.query.get(id)
    if not portfolio:
        return jsonify({
            'success': False,
            'message': 'Not found'
        }), 404
    
    ts_code = request.json.get('ts_code')
    action = request.json.get('action')
    quantity = request.json.get('quantity')
    price = request.json.get('price')
    
    # 获取当前股价
    data_manager = get_data_manager()
    daily_data = data_manager.get_cached_daily_data(ts_code)
    if daily_data.empty and not price:
        return jsonify({
            'success': False,
            'message': 'Need price or no data'
        }), 400
    
    if not price and not daily_data.empty:
        latest = daily_data.iloc[-1]
        price = latest.get('close')
    
    # 记录交易
    trade = PaperTrade(
        portfolio_id=id,
        ts_code=ts_code,
        action=action,
        quantity=quantity,
        price=price
    )
    db.session.add(trade)
    
    # 更新持仓
    existing = PortfolioHolding.query.filter_by(portfolio_id=id, ts_code=ts_code).first()
    
    if action == 'BUY':
        if existing:
            avg_cost = (existing.quantity * existing.avg_cost + quantity * price) / (existing.quantity + quantity)
            existing.quantity += quantity
            existing.avg_cost = avg_cost
        else:
            holding = PortfolioHolding(
                portfolio_id=id,
                ts_code=ts_code,
                quantity=quantity,
                avg_cost=price
            )
            db.session.add(holding)
    elif action == 'SELL':
        if existing and existing.quantity >= quantity:
            existing.quantity -= quantity
            if existing.quantity == 0:
                db.session.delete(existing)
        else:
            return jsonify({
                'success': False,
                'message': 'Insufficient shares'
            }), 400
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'data': trade.to_dict()
    })


# ============================================================
# 观潮对标新增路由
# 对照 151-观潮对标-系统能力提升与稳定性优化方案.md §3.1 / §4.1
# ============================================================

# ---- 股票搜索 ----
@handle_exceptions
@phase3_bp.route('/symbols/search', methods=['GET'])
def search_symbols():
    """股票搜索（支持代码/名称/拼音）"""
    query = request.args.get('q', '').strip()
    limit = request.args.get('limit', 20, type=int)

    from app.services.stock_search_service import stock_search_service
    results = stock_search_service.search(query, limit)
    return jsonify({'code': 1, 'data': results})


@handle_exceptions
@phase3_bp.route('/symbols/search/suggestions', methods=['GET'])
def search_suggestions():
    """搜索建议（自动补全）"""
    query = request.args.get('q', '').strip()
    limit = request.args.get('limit', 8, type=int)

    from app.services.stock_search_service import stock_search_service
    results = stock_search_service.search(query, limit)
    suggestions = [f"{r['ts_code']} {r['name']}" for r in results]
    return jsonify({'code': 1, 'data': suggestions})


# ---- 数据源状态 ----
@handle_exceptions
@phase3_bp.route('/data-source/status', methods=['GET'])
def get_data_source_status():
    """获取数据源状态快照（供前端 DataSourceStatus 组件轮询）"""
    from app.data.data_source_manager import data_source_manager
    snapshot = data_source_manager.get_status_snapshot()
    return jsonify({'code': 1, 'data': snapshot})


@handle_exceptions
@phase3_bp.route('/data-source/reset/<source_name>', methods=['POST'])
def reset_data_source(source_name):
    """重置指定数据源状态"""
    from app.data.data_source_manager import data_source_manager
    data_source_manager.reset_source(source_name)
    return jsonify({'code': 1, 'message': f'数据源 {source_name} 已重置'})


# ---- 批量 K 线 ----
@handle_exceptions
@phase3_bp.route('/klines/batch', methods=['POST'])
def batch_klines():
    """批量 K 线数据（多只股票一次请求）"""
    data = request.get_json() or {}
    requests_list = data.get('requests', [])

    if not requests_list:
        return jsonify({'code': 1, 'data': []})

    dm = get_data_manager()
    results = {}

    for req in requests_list:
        ts_code = req.get('ts_code')
        period = req.get('period', 'D')
        start = req.get('start_date')
        end = req.get('end_date')

        if not ts_code:
            continue

        try:
            df = dm.get_kline_data(ts_code, period, start, end)
            if not df.empty:
                results[ts_code] = json.loads(df.to_json(orient='records', date_format='iso'))
        except Exception as e:
            logger.warning(f"批量 K 线获取失败: {ts_code}: {e}")
            results[ts_code] = None

    return jsonify({'code': 1, 'data': results})


# ---- 自选股扩展 ----
@handle_exceptions
@phase3_bp.route('/watchlist/reorder', methods=['PUT'])
def reorder_watchlist():
    """自选股排序"""
    data = request.get_json() or {}
    ts_codes = data.get('ts_codes', [])
    # 本地存储的应用端处理，后端仅记录
    return jsonify({'code': 1, 'data': {'ordered': ts_codes}})


# ---- 品种分类 ----
@handle_exceptions
@phase3_bp.route('/market/categories', methods=['GET'])
def market_categories():
    """获取品种分类树"""
    from app import models
    from sqlalchemy import func

    # 按行业分组统计
    stocks = models.Stock.query.with_entities(
        models.Stock.industry,
        func.count(models.Stock.ts_code).label('count')
    ).filter(models.Stock.industry.isnot(None)).group_by(models.Stock.industry).order_by(
        func.count(models.Stock.ts_code).desc()
    ).all()

    categories = [
        {'name': ind, 'count': cnt, 'type': 'industry'}
        for ind, cnt in stocks if ind
    ]

    # 按市场分组
    markets = models.Stock.query.with_entities(
        models.Stock.market,
        func.count(models.Stock.ts_code).label('count')
    ).filter(models.Stock.market.isnot(None)).group_by(models.Stock.market).all()

    market_list = [
        {'name': mkt, 'count': cnt, 'type': 'market'}
        for mkt, cnt in markets if mkt
    ]

    return jsonify({
        'code': 1,
        'data': {
            'industries': categories,
            'markets': market_list,
            'total': sum(c['count'] for c in categories),
        }
    })


# ---- 模拟交易扩展（对照 §6.1）----
@handle_exceptions
@phase3_bp.route('/sim/orders', methods=['GET'])
def get_sim_orders():
    """获取模拟订单列表"""
    status = request.args.get('status')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    from app.models import PaperTrade
    query = PaperTrade.query.order_by(PaperTrade.created_at.desc())

    if status:
        query = query.filter(PaperTrade.action == status.upper())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        'code': 1,
        'data': {
            'items': [t.to_dict() for t in pagination.items],
            'total': pagination.total,
            'page': page,
            'per_page': per_page,
        }
    })


@handle_exceptions
@phase3_bp.route('/sim/order', methods=['POST'])
def place_sim_order():
    """模拟下单"""
    data = request.get_json() or {}
    ts_code = data.get('ts_code')
    action = data.get('action', 'BUY')  # BUY / SELL
    quantity = data.get('quantity', 100, type=int)
    price = data.get('price', type=float)
    portfolio_id = data.get('portfolio_id', 1, type=int)

    if not ts_code or not action:
        return jsonify({'code': 0, 'message': '参数不足'}), 400

    # 获取价格（如果未提供）
    if not price:
        dm = get_data_manager()
        daily_data = dm.get_cached_daily_data(ts_code)
        if not daily_data.empty:
            price = float(daily_data.iloc[-1]['close'])

    from app.models import PortfolioHolding, PaperTrade

    trade = PaperTrade(
        portfolio_id=portfolio_id,
        ts_code=ts_code,
        action=action,
        quantity=quantity,
        price=price or 0
    )
    db.session.add(trade)

    # 更新持仓
    existing = PortfolioHolding.query.filter_by(
        portfolio_id=portfolio_id, ts_code=ts_code
    ).first()

    if action == 'BUY':
        if existing:
            total_cost = existing.quantity * existing.avg_cost + quantity * (price or 0)
            existing.quantity += quantity
            existing.avg_cost = total_cost / existing.quantity
        else:
            holding = PortfolioHolding(
                portfolio_id=portfolio_id,
                ts_code=ts_code,
                quantity=quantity,
                avg_cost=price or 0
            )
            db.session.add(holding)
    elif action == 'SELL':
        if existing and existing.quantity >= quantity:
            existing.quantity -= quantity
            if existing.quantity == 0:
                db.session.delete(existing)
        else:
            db.session.rollback()
            return jsonify({'code': 0, 'message': '持仓不足'}), 400

    db.session.commit()

    return jsonify({
        'code': 1,
        'data': trade.to_dict(),
        'message': f'{action} {ts_code} {quantity}股 @ {price}'
    })


@handle_exceptions
@phase3_bp.route('/sim/order/<int:order_id>/cancel', methods=['POST'])
def cancel_sim_order(order_id):
    """撤单"""
    from app.models import PaperTrade
    trade = PaperTrade.query.get(order_id)
    if not trade:
        return jsonify({'code': 0, 'message': '订单不存在'}), 404

    trade.trade_type = f'CANCEL_{trade.trade_type}'
    db.session.commit()

    return jsonify({'code': 1, 'data': trade.to_dict(), 'message': '已撤单'})


@handle_exceptions
@phase3_bp.route('/sim/positions', methods=['GET'])
def get_sim_positions():
    """获取持仓列表"""
    from app.models import PortfolioHolding
    positions = PortfolioHolding.query.all()

    # 获取最新价格
    dm = get_data_manager()
    results = []
    for p in positions:
        daily = dm.get_cached_daily_data(p.ts_code)
        current_price = float(daily.iloc[-1]['close']) if not daily.empty else p.avg_cost
        market_value = current_price * p.quantity
        cost_value = p.avg_cost * p.quantity
        pnl = market_value - cost_value
        pnl_pct = (pnl / cost_value * 100) if cost_value > 0 else 0

        results.append({
            'id': p.id,
            'ts_code': p.ts_code,
            'quantity': p.quantity,
            'avg_cost': round(p.avg_cost, 3),
            'current_price': round(current_price, 3),
            'market_value': round(market_value, 2),
            'cost_value': round(cost_value, 2),
            'pnl': round(pnl, 2),
            'pnl_pct': round(pnl_pct, 2),
            'portfolio_id': p.portfolio_id,
        })

    return jsonify({'code': 1, 'data': results})


@handle_exceptions
@phase3_bp.route('/sim/position/<int:position_id>/close', methods=['POST'])
def close_sim_position(position_id):
    """平仓"""
    data = request.get_json() or {}
    price = data.get('price', type=float)

    from app.models import PortfolioHolding, PaperTrade
    position = PortfolioHolding.query.get(position_id)
    if not position:
        return jsonify({'code': 0, 'message': '持仓不存在'}), 404

    quantity = position.quantity

    # 记录平仓交易
    trade = PaperTrade(
        portfolio_id=position.portfolio_id,
        ts_code=position.ts_code,
        action='SELL',
        quantity=quantity,
        price=price or 0
    )
    db.session.add(trade)
    db.session.delete(position)
    db.session.commit()

    return jsonify({
        'code': 1,
        'data': trade.to_dict(),
        'message': f'已平仓 {position.ts_code} {quantity}股'
    })


@handle_exceptions
@phase3_bp.route('/sim/account/reset', methods=['POST'])
def reset_sim_account():
    """重置模拟账户"""
    from app.models import PortfolioHolding, PaperTrade

    PortfolioHolding.query.delete()
    PaperTrade.query.delete()
    db.session.commit()

    return jsonify({'code': 1, 'message': '模拟账户已重置'})


@handle_exceptions
@phase3_bp.route('/sim/trades/summary', methods=['GET'])
def get_sim_trades_summary():
    """交易汇总"""
    from app.models import PaperTrade
    import numpy as np

    trades = PaperTrade.query.all()
    if not trades:
        return jsonify({
            'code': 1,
            'data': {
                'total_trades': 0, 'win_rate': 0,
                'total_pnl': 0, 'max_drawdown': 0,
            }
        })

    buy_trades = [t for t in trades if t.trade_type == 'BUY']
    sell_trades = [t for t in trades if t.trade_type == 'SELL']

    # 简单盈亏统计（不追溯配对）
    from app.data import DataManager
    dm = DataManager()

    wins = 0
    total_pnl = 0
    pnls = []

    for t in sell_trades:
        daily = dm.get_cached_daily_data(t.ts_code)
        if not daily.empty:
            current_price = float(daily.iloc[-1]['close'])
            pnl = (current_price - t.price) * t.quantity
            pnls.append(pnl)
            total_pnl += pnl
            if pnl > 0:
                wins += 1

    win_rate = wins / max(len(sell_trades), 1)

    # 最大回撤（简化）
    max_drawdown = 0
    if pnls:
        peak = 0
        for p in sorted(pnls):
            peak = max(peak, p)
            drawdown = (peak - p) / max(peak, 1)
            max_drawdown = max(max_drawdown, drawdown)

    return jsonify({
        'code': 1,
        'data': {
            'total_trades': len(trades),
            'buy_count': len(buy_trades),
            'sell_count': len(sell_trades),
            'win_rate': round(win_rate, 3),
            'total_pnl': round(total_pnl, 2),
            'max_drawdown': round(max_drawdown, 3),
        }
    })


# ---- 告警路由 ----
@handle_exceptions
@phase3_bp.route('/alerts', methods=['GET'])
def get_alerts():
    """条件告警列表"""
    from app.models import Alert
    alerts = Alert.query.order_by(Alert.created_at.desc()).all()
    return jsonify({
        'code': 1,
        'data': [a.to_dict() for a in alerts]
    })


@handle_exceptions
@phase3_bp.route('/alerts', methods=['POST'])
def create_alert():
    """创建条件告警"""
    data = request.get_json() or {}
    from app.models import Alert
    from datetime import datetime

    alert = Alert(
        ts_code=data.get('ts_code'),
        alert_type=data.get('alert_type', 'price'),  # price / volume / signal
        condition=data.get('condition', '>'),
        threshold=data.get('threshold', 0, type=float),
        message=data.get('message', ''),
        is_active=True,
        created_at=datetime.now(),
    )
    db.session.add(alert)
    db.session.commit()

    return jsonify({'code': 1, 'data': alert.to_dict()})


@handle_exceptions
@phase3_bp.route('/alerts/<int:alert_id>', methods=['DELETE'])
def delete_alert(alert_id):
    """删除告警"""
    from app.models import Alert
    alert = Alert.query.get(alert_id)
    if not alert:
        return jsonify({'code': 0, 'message': '告警不存在'}), 404

    db.session.delete(alert)
    db.session.commit()

    return jsonify({'code': 1, 'message': '已删除'})


# ---- 画图持久化 ----
@handle_exceptions
@phase3_bp.route('/drawings/batch', methods=['POST'])
def save_drawings():
    """批量存储画图"""
    data = request.get_json() or {}
    symbol = data.get('symbol')
    drawings = data.get('drawings', [])

    if not symbol:
        return jsonify({'code': 0, 'message': '缺少 symbol'}), 400

    from app.models import Drawing
    import json

    # 删除旧的画图数据
    Drawing.query.filter_by(ts_code=symbol).delete()

    # 存储新画图
    for d in drawings:
        drawing = Drawing(
            ts_code=symbol,
            drawing_type=d.get('type'),
            drawing_data=json.dumps(d.get('data', {})),
            created_at=datetime.now(),
        )
        db.session.add(drawing)

    db.session.commit()

    return jsonify({
        'code': 1,
        'message': f'已存储 {len(drawings)} 个画图对象',
        'data': {'count': len(drawings)}
    })


@handle_exceptions
@phase3_bp.route('/drawings/load', methods=['GET'])
def load_drawings():
    """读取画图"""
    symbol = request.args.get('symbol')

    if not symbol:
        return jsonify({'code': 0, 'message': '缺少 symbol'}), 400

    from app.models import Drawing
    import json

    drawings = Drawing.query.filter_by(ts_code=symbol).all()
    result = []
    for d in drawings:
        result.append({
            'id': d.id,
            'type': d.drawing_type,
            'data': json.loads(d.drawing_data) if d.drawing_data else {},
            'created_at': d.created_at.isoformat() if d.created_at else None,
        })

    return jsonify({'code': 1, 'data': result})


# ====================
# 仪表盘专用接口
# ====================
@handle_exceptions
@phase3_bp.route('/watchlist/dashboard', methods=['GET'])
def get_watchlist_dashboard():
    """仪表盘 - 自选股概览数据"""
    watchlist_items = Watchlist.query.order_by(Watchlist.created_at.desc()).all()

    stocks = []
    up_count = 0
    down_count = 0
    total_change = 0.0
    valid_count = 0

    for item in watchlist_items:
        latest = DailyData.query.filter_by(
            ts_code=item.ts_code
        ).order_by(DailyData.trade_date.desc()).first()

        if latest:
            pct = float(latest.pct_chg) if latest.pct_chg else 0
            if pct > 0:
                up_count += 1
            elif pct < 0:
                down_count += 1
            total_change += pct
            valid_count += 1

            stock_entry = {
                'name': item.ts_code,
                'symbol': item.ts_code,
                'price': float(latest.close) if latest.close else 0,
                'changePercent': round(pct, 2),
                'pct_chg': round(pct, 2),
            }

            stock_info = Stock.query.filter_by(ts_code=item.ts_code).first()
            if stock_info:
                stock_entry['name'] = stock_info.name
            stocks.append(stock_entry)
        else:
            stocks.append({
                'name': item.ts_code,
                'symbol': item.ts_code,
                'price': 0,
                'changePercent': 0,
                'pct_chg': 0,
            })

    avg_change = round(total_change / valid_count, 2) if valid_count > 0 else 0

    return jsonify({
        'success': True,
        'data': {
            'stocks': stocks[:10],
            'stocks_count': len(stocks),
            'up_count': up_count,
            'down_count': down_count,
            'avg_change': avg_change,
            'total_amount': 0,
        }
    })


@handle_exceptions
@phase3_bp.route('/signals/summary', methods=['GET'])
def get_signals_summary():
    """仪表盘 - 策略信号摘要"""
    from datetime import datetime, timedelta

    seven_days_ago = datetime.now() - timedelta(days=7)
    recent_signals = Signal.query.filter(
        Signal.created_at >= seven_days_ago
    ).order_by(Signal.created_at.desc()).limit(20).all()

    buy_count = Signal.query.filter(
        Signal.signal_type.in_(['buy', '买入']),
        Signal.created_at >= seven_days_ago
    ).count()
    sell_count = Signal.query.filter(
        Signal.signal_type.in_(['sell', '卖出']),
        Signal.created_at >= seven_days_ago
    ).count()

    signals = []
    for s in recent_signals:
        sig = s.to_dict()
        sig['stock_name'] = s.ts_code
        signals.append(sig)

    return jsonify({
        'success': True,
        'data': {
            'signals': signals,
            'active_count': len(recent_signals),
            'buy_count': buy_count,
            'sell_count': sell_count,
        }
    })
