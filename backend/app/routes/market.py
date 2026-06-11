"""
"市场数据 API 路由
提供行情数据、市场概况、板块涨跌等信息"
"""
from flask import Blueprint, request, jsonify
import logging
from datetime import datetime
from app.services.market_service import MarketService
from app.utils.error_handlers import handle_exceptions

market_bp = Blueprint('market', __name__)
market_service = MarketService()
logger = logging.getLogger(__name__)

@market_bp.route('/api/v3/stocks', methods=['GET'])
@market_bp.route('/api/v1/stocks', methods=['GET'])
@handle_exceptions
def get_stocks():
    page = request.args.get('page', 1, type=int)
    page_size = request.args.get('page_size', 20, type=int)
    industry = request.args.get('industry')
    market = request.args.get('market')
    
    result = market_service.get_stock_list(page, page_size, industry, market)
    return jsonify(result)

@market_bp.route('/api/v3/stocks/<ts_code>', methods=['GET'])
@market_bp.route('/api/v1/stocks/<ts_code>', methods=['GET'])
@handle_exceptions
def get_stock_detail(ts_code):
    stock = market_service.get_stock_detail(ts_code)
    if not stock:
        return jsonify({'success': False, 'message': '股票不存在'}), 404
    return jsonify({'success': True, 'data': stock})

@market_bp.route('/api/v3/stocks/<ts_code>/daily', methods=['GET'])
@market_bp.route('/api/v1/stocks/<ts_code>/daily', methods=['GET'])
@handle_exceptions
def get_daily_data(ts_code):
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    data = market_service.get_daily_data(ts_code, start_date, end_date)
    return jsonify({'success': True, 'data': data})

@market_bp.route('/api/v3/stocks/sync', methods=['POST'])
@market_bp.route('/api/v1/stocks/sync', methods=['POST'])
@handle_exceptions
def sync_stocks():
    result = market_service.sync_stock_data()
    return jsonify(result)

@market_bp.route('/api/v3/stocks/<ts_code>/sync', methods=['POST'])
@market_bp.route('/api/v1/stocks/<ts_code>/sync', methods=['POST'])
@handle_exceptions
def sync_stock_daily(ts_code):
    result = market_service.sync_daily_data(ts_code)
    return jsonify(result)

@market_bp.route('/api/v3/market/index', methods=['GET'])
@market_bp.route('/api/v1/market/index', methods=['GET'])
@handle_exceptions
def get_index_data():
    indices = market_service.get_index_data()
    return jsonify({'success': True, 'data': indices})

@market_bp.route('/api/v3/market/industries', methods=['GET'])
@market_bp.route('/api/v1/market/industries', methods=['GET'])
@handle_exceptions
def get_industries():
    industries = market_service.get_industries()
    return jsonify({'success': True, 'data': industries})

@market_bp.route('/api/v3/market/markets', methods=['GET'])
@market_bp.route('/api/v1/market/markets', methods=['GET'])
@handle_exceptions
def get_markets():
    markets = market_service.get_markets()
    return jsonify({'success': True, 'data': markets})


@market_bp.route('/api/v3/market/overview', methods=['GET'])
@handle_exceptions
def get_market_overview():
    """仪表盘市场概况：返回指数实时数据"""
    indices = market_service.get_index_data()
    indexes_data = []

    from app.data.tushare_provider import TushareProvider
    _tushare = TushareProvider()

    for idx in indices:
        try:
            idx_data = _tushare.get_index_daily(idx['ts_code'])
            if idx_data and len(idx_data) > 0:
                latest = idx_data[0]
                prev_data = idx_data[1] if len(idx_data) > 1 else None
                prev_close = prev_data['close'] if prev_data else latest.get('pre_close', latest['close'])
                change = latest['close'] - prev_close
                change_pct = (change / prev_close * 100) if prev_close > 0 else 0

                indexes_data.append({
                    'symbol': idx['ts_code'],
                    'name': idx['name'],
                    'value': float(latest['close']),
                    'change': round(float(change), 2),
                    'changePercent': round(float(change_pct), 2),
                })
            else:
                logger.warning(f"指数 {idx['name']} 数据为空")
        except Exception as e:
            logger.warning(f"指数 {idx['name']} 数据失败: {e}")

    return jsonify({
        'success': True,
        'data': {
            'indexes': indexes_data,
            'timestamp': datetime.now().isoformat(),
        }
    })


@market_bp.route('/api/v1/market/overview', methods=['GET'])
def get_market_overview_v1():
    return get_market_overview()
