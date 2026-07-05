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
from app.models import Watchlist, Stock
from app.data.enhanced_cache_manager import EnhancedCacheManager
from app.data.memory_cache import TieredMemoryCache
from app.data import DataManager
from app.utils.error_handlers import handle_exceptions

watchlist_bp = Blueprint('watchlist', __name__, url_prefix='/api/v3/watchlist')

logger = logging.getLogger(__name__)


def _get_cache():
    """获取内存缓存实例"""
    import app.data.memory_cache as mc
    return mc.TieredMemoryCache()


def _get_dm() -> DataManager:
    """获取 DataManager 实例"""
    return DataManager()


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
    dm = _get_dm()

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

        if not dm:
            # 数据源不可用，返回空结构
            stocks[ts_code] = _empty_stock(ts_code)
            evaluated[ts_code] = False
            continue

        stock_data = _fetch_stock_quotes(ts_code, dm)
        stocks[ts_code] = stock_data
        evaluated[ts_code] = True

        # 缓存（实时: 3s / 分析: 30min）
        ttl_s = 3 if cache_level == 'realtime' else 1800
        cache.set(cache_key, stock_data, ttl=ttl_s)

    # 获取股票名称（从 PG Stock 表）
    stock_names = _batch_get_names(list(stocks.keys()))
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


def _fetch_stock_quotes(ts_code: str, dm: DataManager) -> Dict:
    """获取单只股票的全量行情数据（基础行情+基本面+资金流向）—— 通过 DataManager 走 DuckDB"""
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

    # 1. 日线数据（从 DuckDB）
    try:
        df_daily = dm.get_cached_daily_data(ts_code, start_30, today)
        if not df_daily.empty:
            latest = df_daily.iloc[-1]
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

    # 2. daily_basic（从 DuckDB）
    try:
        df_basic = dm.get_cached_daily_basic(ts_code, start_10, today)
        if not df_basic.empty:
            basic = df_basic.iloc[-1]
            stock['turnover'] = basic.get('turnover_rate')
            stock['pe_ttm'] = basic.get('pe_ttm')
            stock['pb'] = basic.get('pb')
            stock['mkt_cap_circ'] = basic.get('circ_mv')
            stock['mkt_cap_total'] = basic.get('total_mv')
    except Exception as e:
        logger.warning(f"daily_basic获取失败({ts_code}): {e}")

    # 3. 资金流向（从 DuckDB）
    try:
        df_mf = dm.get_cached_moneyflow(ts_code=ts_code)
        if not df_mf.empty:
            mf = df_mf.iloc[-1]
            stock['fund_net'] = mf.get('net_mf_amount')
            stock['fund_vol'] = mf.get('net_mf_vol')
            stock['big_net'] = mf.get('buy_lg_amount')
    except Exception as e:
        logger.warning(f"资金流向获取失败({ts_code}): {e}")

    # 4. 财务指标
    try:
        fina_list = dm.get_fina_indicator(ts_code)
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
        stock_basic = dm.get_stock_info(ts_code)
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


def _batch_get_names(ts_codes: List[str]) -> Dict[str, str]:
    """从 PG Stock 表批量获取股票名称"""
    names = {}
    if not ts_codes:
        return names
    try:
        stocks = Stock.query.filter(Stock.ts_code.in_(ts_codes)).all()
        for s in stocks:
            names[s.ts_code] = s.name
    except Exception as e:
        logger.warning(f"批量获取股票名称失败: {e}")
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
    """看板级自选汇总 — 含涨跌统计"""
    items = Watchlist.query.order_by(Watchlist.created_at.desc()).all()
    dm = DataManager()

    stocks_data = []
    up_count = 0
    down_count = 0
    total_change = 0.0
    total_amount = 0.0
    for item in items:
        try:
            df = dm.get_cached_daily_data(item.ts_code)
            if not df.empty:
                latest = df.iloc[-1]
                pct_chg = float(latest.get('pct_chg', 0)) or 0.0
                amount = float(latest.get('amount', 0)) or 0.0
                stocks_data.append({
                    'ts_code': item.ts_code,
                    'name': latest.get('name', ''),
                    'price': float(latest.get('close', 0)),
                    'changePercent': pct_chg,
                    'pct_chg': pct_chg,
                    'volume': float(latest.get('vol', 0)),
                    'amount': amount,
                })
                if pct_chg > 0:
                    up_count += 1
                elif pct_chg < 0:
                    down_count += 1
                total_change += pct_chg
                total_amount += amount
        except Exception:
            continue

    total = len(stocks_data)
    return jsonify({
        'code': 0,
        'data': {
            'stocks': stocks_data,
            'total': total,
            'totalStocks': total,
            'up_count': up_count,
            'down_count': down_count,
            'avg_change': round(total_change / max(total, 1), 2),
            'total_amount': total_amount,
        }
    })
