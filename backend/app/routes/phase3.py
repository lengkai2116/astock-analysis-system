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
