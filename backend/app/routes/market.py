"""
"市场数据 API 路由
提供行情数据、市场概况、板块涨跌等信息"
"""
from flask import Blueprint, request, jsonify
import logging
from datetime import datetime
from app.services.market_service import MarketService
from app.services.dashboard_service import DashboardService
from app.utils.error_handlers import handle_exceptions

market_bp = Blueprint('market', __name__)
market_service = MarketService()
dashboard_service = DashboardService()
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


# ══════════════════════════════════════════════════
# E07: 个股行情综合端点（28字段）
# ══════════════════════════════════════════════════

def _get_cache_level() -> str:
    """根据交易时段返回缓存级别 — 盘中 realtime(3s)，盘后 analysis(30min)"""
    try:
        from app.utils.trading_hours import is_trading_time
        return 'realtime' if is_trading_time() else 'analysis'
    except Exception:
        return 'realtime'


@market_bp.route('/api/v3/stock/<ts_code>/quote', methods=['GET'])
@handle_exceptions
def get_stock_quote(ts_code):
    """
    E07: 个股行情综合端点 — 聚合4个Tushare数据源返回28字段

    数据源:
      1. pro.daily()        → open/high/low/close/pre_close/volume/amount/pct_chg
      2. pro.daily_basic()  → turnover_rate/volume_ratio/pe_ttm/pb/total_mv/circ_mv
      3. pro.stk_limit()    → high_limit/low_limit
      4. pro.fina_indicator() → eps/bvps (5000积分)

    缓存: realtime(3s 盘中) / analysis(30min 盘后), key=`quote:{ts_code}`
    错误: 全源失败 → 503 DataUnavailable
    """
    from app.data.tushare_provider import TushareProvider
    from app.data.memory_cache import TieredMemoryCache
    from datetime import timedelta

    cache = TieredMemoryCache()
    cache_key = f'quote:{ts_code}'
    cache_level = _get_cache_level()

    # 尝试缓存
    cached = cache.get(cache_key, cache_level)
    if cached is not None:
        return jsonify({'code': 0, 'data': cached})

    tp = TushareProvider()
    if not tp.pro:
        return jsonify({
            'code': -1, 'message': 'Tushare 数据源不可用',
            'error_type': 'DataUnavailable',
        }), 503

    # 1. 获取最新日线数据
    start = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')
    end = datetime.now().strftime('%Y%m%d')
    daily_list = tp.get_daily_data(ts_code, start, end)
    if not daily_list:
        return jsonify({
            'code': -1, 'message': '个股行情数据不可用',
            'error_type': 'DataUnavailable',
        }), 503

    latest = daily_list[-1]
    trade_date = latest['trade_date']

    open_price = latest.get('open')
    high = latest.get('high')
    low = latest.get('low')
    close = latest.get('close')
    pre_close = latest.get('pre_close')
    vol = latest.get('vol')
    amount = latest.get('amount')
    pct_chg = latest.get('pct_chg')

    # avg_price = amount / (vol × 100)
    avg_price = round(amount / (vol * 100), 2) if (amount and vol and vol > 0) else None

    # 2. daily_basic
    turnover_rate = volume_ratio = pe_ttm = pb = total_mv = circ_mv = None
    try:
        basic_list = tp.get_daily_basic(ts_code, start, end)
        if basic_list:
            basic = basic_list[-1]
            turnover_rate = basic.get('turnover_rate')
            volume_ratio = basic.get('volume_ratio')
            pe_ttm = basic.get('pe_ttm')
            pb = basic.get('pb')
            total_mv = basic.get('total_mv')
            circ_mv = basic.get('circ_mv')
    except Exception as e:
        logger.warning(f"daily_basic 获取失败 ({ts_code}): {e}")

    # 3. stk_limit
    high_limit = low_limit = None
    try:
        limit_all = tp.get_stk_limit(trade_date)
        if limit_all:
            limit_row = next((r for r in limit_all if r.get('ts_code') == ts_code), None)
            if limit_row:
                high_limit = limit_row.get('high_limit')
                low_limit = limit_row.get('low_limit')
    except Exception as e:
        logger.warning(f"stk_limit 获取失败 ({ts_code}): {e}")

    # 4. fina_indicator (5000积分)
    eps = bvps = None
    try:
        fina_list = tp.get_fina_indicator(ts_code)
        if fina_list:
            fina = fina_list[-1]
            eps = fina.get('eps')
            bvps = fina.get('bvps')
    except Exception as e:
        logger.warning(f"fina_indicator 获取失败 ({ts_code}): {e}")

    # 5. 复权因子
    adj_close = None
    try:
        adj_list = tp.get_adj_factor(ts_code, start, end)
        if adj_list:
            adj_latest = adj_list[-1]
            adj_close = round(close * adj_latest.get('adj_factor', 1), 2) if close else None
    except Exception as e:
        logger.warning(f"adj_factor 获取失败 ({ts_code}): {e}")

    data = {
        'ts_code': ts_code,
        'trade_date': trade_date,
        'open': open_price,
        'high': high,
        'low': low,
        'close': close,
        'pre_close': pre_close,
        'volume': vol,
        'amount': amount,
        'avg_price': avg_price,
        'pct_chg': pct_chg,
        'high_limit': high_limit,
        'low_limit': low_limit,
        'turnover_rate': turnover_rate,
        'volume_ratio': volume_ratio,
        'pe_ttm': pe_ttm,
        'pb': pb,
        'total_mv': total_mv,
        'circ_mv': circ_mv,
        'eps': eps,
        'bvps': bvps,
        'adj_close': adj_close,
        'inside': None,
        'outside': None,
    }

    cache.set(cache_key, data, cache_level)
    return jsonify({'code': 0, 'data': data})


# ══════════════════════════════════════════════════
# E10: 个股资金流向端点（5日聚合）
# ══════════════════════════════════════════════════

@market_bp.route('/api/v3/stock/<ts_code>/moneyflow', methods=['GET'])
@handle_exceptions
def get_stock_moneyflow(ts_code):
    """
    E10: 个股资金流向端点 — 聚合最近5交易日超大单/大单/中单/小单净额

    数据源: Tushare pro.moneyflow() — 按股票+日期查询
    缓存: analysis(30min), key=`moneyflow:{ts_code}`
    错误: 全源失败 → 503 DataUnavailable
    """
    from app.data.memory_cache import TieredMemoryCache
    from datetime import timedelta

    cache = TieredMemoryCache()
    cache_key = f'moneyflow:{ts_code}'

    cached = cache.get(cache_key, 'analysis')
    if cached is not None:
        return jsonify({'code': 0, 'data': cached})

    from app.data.tushare_provider import TushareProvider
    tp = TushareProvider()
    if not tp.pro:
        return jsonify({
            'code': -1, 'message': 'Tushare 数据源不可用',
            'error_type': 'DataUnavailable',
        }), 503

    # 最近30日内取有数据的5天
    records = []
    for i in range(30):
        d = (datetime.now() - timedelta(days=i)).strftime('%Y%m%d')
        raw = tp.get_moneyflow(trade_date=d)
        if raw:
            row = next((r for r in raw if r.get('ts_code') == ts_code), None)
            if row:
                records.append(row)
                if len(records) >= 5:
                    break

    if not records:
        return jsonify({
            'code': -1, 'message': '资金流向数据不可用',
            'error_type': 'DataUnavailable',
        }), 503

    def _net(buy_key, sell_key, rec) -> float:
        buy = float(rec.get(buy_key, 0) or 0)
        sell = float(rec.get(sell_key, 0) or 0)
        return round(buy - sell, 2)

    latest_rec = records[-1]
    xl_net = _net('buy_elg_amount', 'sell_elg_amount', latest_rec)
    lg_net = _net('buy_lg_amount', 'sell_lg_amount', latest_rec)
    md_net = _net('buy_md_amount', 'sell_md_amount', latest_rec)
    sm_net = _net('buy_sm_amount', 'sell_sm_amount', latest_rec)
    net_amount = round(xl_net + lg_net + md_net + sm_net, 2)

    main_force = xl_net + lg_net
    total_abs = abs(xl_net) + abs(lg_net) + abs(md_net) + abs(sm_net)
    main_force_pct = round(main_force / total_abs * 100, 2) if total_abs > 0 else 0.0

    history_5day = []
    for rec in records[:-1]:
        history_5day.append({
            'date': rec['trade_date'],
            'net_amount': round(
                _net('buy_elg_amount', 'sell_elg_amount', rec)
                + _net('buy_lg_amount', 'sell_lg_amount', rec)
                + _net('buy_md_amount', 'sell_md_amount', rec)
                + _net('buy_sm_amount', 'sell_sm_amount', rec),
                2
            ),
        })

    data = {
        'ts_code': ts_code,
        'trade_date': latest_rec['trade_date'],
        'latest': {
            'net_amount': net_amount,
            'sub_orders': {
                'xl_order_net': xl_net,
                'lg_order_net': lg_net,
                'md_order_net': md_net,
                'sm_order_net': sm_net,
            },
            'main_force_pct': main_force_pct,
        },
        'history_5day': history_5day,
    }

    cache.set(cache_key, data, 'analysis')
    return jsonify({'code': 0, 'data': data})


@market_bp.route('/api/v3/market/overview', methods=['GET'])
@handle_exceptions
def get_market_overview():
    """仪表盘市场概况：指数行情+总成交额+迷你K线+市场状态"""
    data = dashboard_service.get_index_summary()
    if data is None:
        return jsonify({
            'success': False,
            'message': '市场行情数据不可用，请检查网络连接或稍后重试。',
            'error_type': 'DataUnavailable',
        }), 503
    return jsonify({'success': True, 'data': data})


@market_bp.route('/api/v1/market/overview', methods=['GET'])
def get_market_overview_v1():
    return get_market_overview()
