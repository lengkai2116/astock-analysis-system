"""
自选监控（Watchlist）API路由 v3
核心：批量行情聚合端点 GET /api/v3/watchlist/quotes
文件路径：backend/app/routes/watchlist.py
"""
from flask import Blueprint, request, jsonify, current_app
from datetime import datetime, timedelta
import logging
from typing import Dict, List, Optional

from app import db
from app.models import Watchlist
from app.data.tushare_provider import TushareProvider
from app.data.enhanced_cache_manager import EnhancedCacheManager
from app.data.memory_cache import TieredMemoryCache
from app.utils.error_handlers import handle_exceptions

watchlist_bp = Blueprint('watchlist', __name__, url_prefix='/api/v3/watchlist')

logger = logging.getLogger(__name__)


def _get_cache():
    """获取内存缓存实例"""
    import app.data.memory_cache as mc
    return mc.TieredMemoryCache()


def _get_tp() -> Optional[TushareProvider]:
    """获取Tushare数据源实例（处理不可用情况）"""
    try:
        tp = TushareProvider()
        if tp.pro:
            return tp
    except Exception:
        pass
    return None


# ── W5: GET /api/v3/watchlist/quotes — 批量行情聚合（P0）──
@watchlist_bp.route('/quotes', methods=['GET'])
@handle_exceptions
def get_watchlist_quotes():
    """
    批量行情聚合端点
    返回自选股列表中各只股票的全部行情数据（基础行情 + 策略评分 + 资金流向 + 基本面）

    查询参数:
    - ts_codes: 逗号分隔的股票代码（如 000762.SZ,000001.SZ），为空时返回全部自选
    """
    ts_codes_str = request.args.get('ts_codes', '')
    cache = _get_cache()
    tp = _get_tp()

    # 解析股票列表
    if ts_codes_str:
        ts_codes = [c.strip() for c in ts_codes_str.split(',') if c.strip()]
    else:
        # 从数据库获取全部自选股
        items = Watchlist.query.order_by(Watchlist.created_at).all()
        ts_codes = [w.ts_code for w in items]

    if not ts_codes:
        return jsonify({'code': 0, 'data': {'stocks': {}, 'total_count': 0}})

    # 去重，限制最大20只
    ts_codes = list(dict.fromkeys(ts_codes))[:20]
    stocks = {}
    evaluated = {}

    for ts_code in ts_codes:
        # 检查缓存
        cache_key = f'watchlist_quote:{ts_code}'
        from app.routes.market import _get_cache_level
        cache_level = _get_cache_level()
        cached = cache.get(cache_key, cache_level)
        if cached is not None:
            stocks[ts_code] = cached
            evaluated[ts_code] = True
            continue

        if not tp:
            # 数据源不可用，返回空结构
            stocks[ts_code] = _empty_stock(ts_code)
            evaluated[ts_code] = False
            continue

        stock_data = _fetch_stock_quotes(ts_code, tp)
        stocks[ts_code] = stock_data
        evaluated[ts_code] = True

        # 缓存（实时: 3s / 分析: 30min）
        ttl_s = 3 if cache_level == 'realtime' else 1800
        cache.set(cache_key, stock_data, ttl=ttl_s)

    # 获取股票名称
    stock_names = _batch_get_names(list(stocks.keys()), tp)
    for code, data in stocks.items():
        if code in stock_names:
            data['name'] = stock_names[code]

    return jsonify({
        'code': 0,
        'data': {
            'ts_codes': list(stocks.keys()),
            'stocks': stocks,
            'evaluated': evaluated,
            'total_count': len(stocks),
            'generated_at': datetime.now().isoformat()
        }
    })


def _fetch_stock_quotes(ts_code: str, tp: TushareProvider) -> Dict:
    """获取单只股票的全量行情数据（基础行情+基本面+资金流向）"""
    today = datetime.now().strftime('%Y%m%d')
    start_30 = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')
    start_10 = (datetime.now() - timedelta(days=10)).strftime('%Y%m%d')

    stock = {
        'ts_code': ts_code,
        'name': '',
        # ── 基础行情 ──
        'price': None, 'change_pct': None, 'volume': None, 'amount': None,
        'turnover': None, 'amplitude': None, 'high': None, 'low': None,
        'open': None, 'pre_close': None,
        # ── 策略评分（占位，由评估端点填充）──
        'composite_score': None, 'chanlun_score': None,
        'volume_price_score': None, 'factor_score': None,
        'signal_tags': [], 'buy_signal': None, 'sell_signal': None,
        'tech_pattern': None,
        # ── 资金流向 ──
        'fund_net': None, 'fund_vol': None, 'fund_inflow': None, 'fund_outflow': None,
        'big_net': None, 'big_in': None, 'big_out': None,
        'mid_net': None, 'sml_net': None,
        'big_5d': None, 'big_10d': None,
        'fund_add_td': None, 'fund_add_2d': None, 'fund_add_5d': None,
        # ── 基本面 ──
        'pe_ttm': None, 'pe_static': None, 'pb': None,
        'roe_ttm': None, 'np_growth': None, 'gross_margin': None,
        'debt_ratio': None, 'eps': None, 'bps': None,
        'mkt_cap_circ': None, 'mkt_cap_total': None,
        'shares_total': None, 'shares_circ': None,
        'shareholder_n': None, 'major_holder': None,
        'list_date': None, 'industry': '', 'industry_full': '',
    }

    # 1. 日线数据
    try:
        daily_list = tp.get_daily_data(ts_code, start_30, today)
        if daily_list:
            latest = daily_list[-1]
            stock['price'] = latest.get('close')
            stock['open'] = latest.get('open')
            stock['high'] = latest.get('high')
            stock['low'] = latest.get('low')
            stock['pre_close'] = latest.get('pre_close')
            stock['volume'] = latest.get('vol')
            stock['amount'] = latest.get('amount')
            stock['change_pct'] = latest.get('pct_chg')
            if stock['high'] and stock['low'] and stock['pre_close'] and stock['pre_close'] > 0:
                stock['amplitude'] = round((stock['high'] - stock['low']) / stock['pre_close'] * 100, 2)
    except Exception as e:
        logger.warning(f"日线数据获取失败({ts_code}): {e}")

    # 2. daily_basic
    try:
        basic_list = tp.get_daily_basic(ts_code, start_10, today)
        if basic_list:
            basic = basic_list[-1]
            stock['turnover'] = basic.get('turnover_rate')
            stock['pe_ttm'] = basic.get('pe_ttm')
            stock['pb'] = basic.get('pb')
            stock['mkt_cap_circ'] = basic.get('circ_mv')
            stock['mkt_cap_total'] = basic.get('total_mv')
    except Exception as e:
        logger.warning(f"daily_basic获取失败({ts_code}): {e}")

    # 3. 资金流向
    try:
        mf_list = tp.get_moneyflow_data(ts_code)
        if mf_list:
            mf = mf_list[-1] if isinstance(mf_list[-1], dict) else mf_list[-1]
            stock['fund_net'] = mf.get('net_mf_amount') or mf.get('fund_net')
            stock['fund_vol'] = mf.get('net_mf_vol') or mf.get('fund_vol')
            stock['fund_inflow'] = mf.get('buy_sm_vol') or mf.get('fund_inflow')
            stock['fund_outflow'] = mf.get('sell_sm_vol') or mf.get('fund_outflow')
            stock['big_net'] = mf.get('buy_lg_amount') or mf.get('big_net')
            stock['big_in'] = mf.get('buy_lg_vol') or mf.get('big_in')
            stock['big_out'] = mf.get('sell_lg_vol') or mf.get('big_out')
            stock['mid_net'] = mf.get('buy_md_amount') or mf.get('mid_net')
            stock['sml_net'] = mf.get('buy_sm_amount') or mf.get('sml_net')
    except Exception as e:
        logger.warning(f"资金流向获取失败({ts_code}): {e}")

    # 4. 财务指标
    try:
        fina_list = tp.get_fina_indicator(ts_code)
        if fina_list:
            fina = fina_list[-1]
            stock['eps'] = fina.get('eps')
            stock['bps'] = fina.get('bvps')
            stock['roe_ttm'] = fina.get('roe')
            stock['np_growth'] = fina.get('npr_ttm') or fina.get('np_growth')
            stock['gross_margin'] = fina.get('gross_margin')
            stock['debt_ratio'] = fina.get('debt_to_assets')
    except Exception as e:
        logger.warning(f"财务指标获取失败({ts_code}): {e}")

    # 5. 上市日期
    try:
        stock_basic = tp.get_stock_info(ts_code)
        if stock_basic:
            stock['list_date'] = stock_basic.get('list_date')
            stock['industry'] = stock_basic.get('industry', '')
            stock['industry_full'] = stock_basic.get('industry_full', stock_basic.get('industry', ''))
            stock['shares_total'] = stock_basic.get('total_share')
            stock['shares_circ'] = stock_basic.get('float_share')
    except Exception as e:
        pass

    return stock


def _empty_stock(ts_code: str) -> Dict:
    """返回空股数据结构"""
    return {
        'ts_code': ts_code, 'name': '',
        'price': None, 'change_pct': None, 'volume': None, 'amount': None,
        'turnover': None, 'amplitude': None, 'high': None, 'low': None,
        'open': None, 'pre_close': None,
        'composite_score': None, 'chanlun_score': None,
        'volume_price_score': None, 'factor_score': None,
        'signal_tags': [], 'buy_signal': None, 'sell_signal': None,
        'tech_pattern': None,
        'fund_net': None, 'fund_vol': None, 'fund_inflow': None, 'fund_outflow': None,
        'big_net': None, 'big_in': None, 'big_out': None,
        'mid_net': None, 'sml_net': None,
        'big_5d': None, 'big_10d': None,
        'fund_add_td': None, 'fund_add_2d': None, 'fund_add_5d': None,
        'pe_ttm': None, 'pe_static': None, 'pb': None,
        'roe_ttm': None, 'np_growth': None, 'gross_margin': None,
        'debt_ratio': None, 'eps': None, 'bps': None,
        'mkt_cap_circ': None, 'mkt_cap_total': None,
        'shares_total': None, 'shares_circ': None,
        'shareholder_n': None, 'major_holder': None,
        'list_date': None, 'industry': '', 'industry_full': '',
    }


def _batch_get_names(ts_codes: List[str], tp: Optional[TushareProvider]) -> Dict[str, str]:
    """批量获取股票名称"""
    names = {}
    if not tp:
        return names
    for code in ts_codes:
        try:
            info = tp.get_stock_info(code)
            if info:
                names[code] = info.get('name', '')
        except Exception:
            pass
    return names


# ── 补充：GET /api/v3/watchlist — 自选股列表（使用专用blueprint重导）──
@watchlist_bp.route('', methods=['GET'])
@handle_exceptions
def get_watchlist():
    """获取自选股列表"""
    items = Watchlist.query.order_by(Watchlist.created_at.desc()).all()
    return jsonify({
        'success': True,
        'data': [w.to_dict() for w in items]
    })


@watchlist_bp.route('', methods=['POST'])
@handle_exceptions
def add_to_watchlist():
    """添加到自选"""
    data = request.get_json()
    ts_code = data.get('ts_code') if data else None
    notes = data.get('notes', '') if data else ''

    if not ts_code:
        return jsonify({'success': False, 'error': 'ts_code 不能为空'}), 400

    existing = Watchlist.query.filter_by(ts_code=ts_code).first()
    if existing:
        return jsonify({'success': True, 'data': existing.to_dict(), 'message': '已在自选列表中'})

    item = Watchlist(ts_code=ts_code, notes=notes)
    db.session.add(item)
    db.session.commit()

    return jsonify({'success': True, 'data': item.to_dict()}), 201


@watchlist_bp.route('/<int:id>', methods=['DELETE'])
@handle_exceptions
def remove_from_watchlist(id):
    """从自选移除"""
    item = Watchlist.query.get(id)
    if not item:
        return jsonify({'success': False, 'error': '自选股不存在'}), 404

    db.session.delete(item)
    db.session.commit()

    return jsonify({'success': True, 'message': '已移除自选'})


@watchlist_bp.route('/reorder', methods=['PUT'])
@handle_exceptions
def reorder_watchlist():
    """保存自选股排序"""
    data = request.get_json()
    order = data.get('order', []) if data else []

    for i, item_id in enumerate(order):
        wl = Watchlist.query.get(item_id)
        if wl:
            wl.sort_order = i
    db.session.commit()

    return jsonify({'success': True})


@watchlist_bp.route('/dashboard', methods=['GET'])
@handle_exceptions
def get_watchlist_dashboard():
    """看板级自选汇总"""
    items = Watchlist.query.order_by(Watchlist.created_at.desc()).all()
    from app.data.tushare_provider import TushareProvider
    tp = TushareProvider()

    stocks_data = []
    for item in items:
        try:
            daily = tp.get_daily_data(item.ts_code, '', '')
            if daily:
                latest = daily[-1]
                stocks_data.append({
                    'ts_code': item.ts_code,
                    'price': latest.get('close'),
                    'change_pct': latest.get('pct_chg'),
                    'volume': latest.get('vol')
                })
        except Exception:
            continue

    return jsonify({'code': 0, 'data': {'stocks': stocks_data, 'total': len(stocks_data)}})
