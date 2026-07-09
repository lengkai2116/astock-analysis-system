"""
"市场数据 API 路由
提供行情数据、市场概况、板块涨跌等信息"
"""
from flask import Blueprint, request, jsonify
import logging
from datetime import datetime, timedelta
from app.services.market_service import MarketService
from app.services.dashboard_service import DashboardService
from app.utils.error_handlers import handle_exceptions

market_bp = Blueprint('market', __name__)
market_service = MarketService()
dashboard_service = DashboardService()
logger = logging.getLogger(__name__)

_data_manager = None

def _get_dm():
    global _data_manager
    if _data_manager is None:
        from app.data import DataManager
        _data_manager = DataManager()
    return _data_manager


def _sf(val, default=None):
    """safe float: 处理 None/NaN，缺失返回 default"""
    if val is None:
        return default
    try:
        v = float(val)
        return v if v == v else default
    except (TypeError, ValueError):
        return default

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
    E07: 个股行情综合端点 — ECM缓存优先，Tushare降级（252号方案 Phase 5）

    数据源:
      1. daily_cache        → open/high/low/close/pre_close/volume/amount/pct_chg
      2. daily_basic_cache  → turnover_rate/volume_ratio/pe_ttm/pb/total_mv/circ_mv
      3. stk_limit_cache    → high_limit/low_limit
      4. fina_indicator_cache → eps/bvps
      5. adj_factor_cache   → 复权收盘价

    缓存: TieredMemoryCache reaaltime(3s盘中) / analysis(30min盘后)
    错误: 全源失败 → 503 DataUnavailable
    """
    from app.data.memory_cache import TieredMemoryCache
    from app.data.enhanced_cache_manager import get_ecm_instance

    cache = TieredMemoryCache()
    cache_key = f'quote:{ts_code}'
    cache_level = _get_cache_level()

    cached = cache.get(cache_key, cache_level)
    if cached is not None:
        return jsonify({'code': 0, 'data': cached})

    ecm = get_ecm_instance()
    tp = None
    _lazy_tp = None

    def _get_tp():
        nonlocal tp
        if tp is None:
            from app.data.tushare_provider import TushareProvider
            tp = TushareProvider()
        return tp

    # ── 1. 日线：ECM daily_cache 优先 ────────────────────
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=30)
    start_str = start_dt.strftime('%Y%m%d')
    end_str = end_dt.strftime('%Y%m%d')

    daily_df = ecm.get_cached_daily(ts_code, start_date=start_str, end_date=end_str)
    daily_fallback = daily_df.empty
    if daily_df.empty:
        _tp = _get_tp()
        if _tp.pro:
            raw = _tp.get_daily_data(ts_code, start_str, end_str)
            if raw:
                import pandas as pd
                daily_df = pd.DataFrame(raw)

    if daily_df.empty:
        return jsonify({
            'code': -1, 'message': '个股行情数据不可用',
            'error_type': 'DataUnavailable',
        }), 503

    if isinstance(daily_df, pd.DataFrame):
        # ECM 返回已排序，取最后一条
        latest = daily_df.iloc[-1].to_dict()
    else:
        latest = daily_df[-1]

    trade_date = latest.get('trade_date')
    if hasattr(trade_date, 'strftime'):
        trade_date = trade_date.strftime('%Y%m%d')
    else:
        trade_date = str(trade_date).replace('-', '')

    open_price = _sf(latest.get('open'))
    high = _sf(latest.get('high'))
    low = _sf(latest.get('low'))
    close = _sf(latest.get('close'))
    pre_close = _sf(latest.get('pre_close'))
    vol = _sf(latest.get('vol', latest.get('volume', 0)))
    amount = _sf(latest.get('amount'))
    pct_chg = _sf(latest.get('pct_chg'))

    avg_price = round(amount / (vol * 100), 2) if (amount and vol and vol > 0) else None

    # ── 2. daily_basic：ECM → Tushare ────────────────────
    turnover_rate = volume_ratio = pe_ttm = pb = total_mv = circ_mv = None
    basic_df = ecm.get_cached_daily_basic(ts_code, start_date=start_str, end_date=end_str)
    if not basic_df.empty:
        basic = basic_df.iloc[-1].to_dict()
        turnover_rate = basic.get('turnover_rate')
        volume_ratio = basic.get('volume_ratio')
        pe_ttm = basic.get('pe_ttm')
        pb = basic.get('pb')
        total_mv = basic.get('total_mv')
        circ_mv = basic.get('circ_mv')
    else:
        try:
            _tp = _get_tp()
            basic_list = _tp.get_daily_basic(ts_code, start_str, end_str)
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

    # ── 3. 涨跌停：ECM → Tushare ────────────────────────
    high_limit = low_limit = None
    limit_df = ecm.get_cached_stk_limit(trade_date)
    if not limit_df.empty:
        row = limit_df[limit_df['ts_code'] == ts_code]
        if not row.empty:
            high_limit = _sf(row.iloc[0].get('high_limit'))
            low_limit = _sf(row.iloc[0].get('low_limit'))
    else:
        try:
            _tp = _get_tp()
            limit_all = _tp.get_stk_limit(trade_date)
            if limit_all:
                limit_row = next((r for r in limit_all if r.get('ts_code') == ts_code), None)
                if limit_row:
                    high_limit = _sf(limit_row.get('high_limit'))
                    low_limit = _sf(limit_row.get('low_limit'))
        except Exception as e:
            logger.warning(f"stk_limit 获取失败 ({ts_code}): {e}")

    # ── 4. 财务指标：ECM → Tushare ──────────────────────
    eps = bvps = None
    fina_df = ecm.get_cached_fina_indicator(ts_code)
    if not fina_df.empty:
        fina = fina_df.iloc[-1].to_dict()
        eps = fina.get('eps')
        bvps = fina.get('bvps')
    else:
        try:
            _tp = _get_tp()
            fina_list = _tp.get_fina_indicator(ts_code)
            if fina_list:
                fina = fina_list[-1]
                eps = fina.get('eps')
                bvps = fina.get('bvps')
        except Exception as e:
            logger.warning(f"fina_indicator 获取失败 ({ts_code}): {e}")

    # ── 5. 复权因子：ECM → Tushare ──────────────────────
    adj_close = None
    adj_df = ecm.get_cached_adj_factor(ts_code, start_date=start_str, end_date=end_str)
    if not adj_df.empty:
        adj_factor = _sf(adj_df.iloc[-1].get('adj_factor', 1))
        adj_close = round(_sf(close) * adj_factor, 2) if close and adj_factor else None
    else:
        try:
            _tp = _get_tp()
            adj_list = _tp.get_adj_factor(ts_code, start_str, end_str)
            if adj_list:
                adj_factor = _sf(adj_list[-1].get('adj_factor', 1))
                adj_close = round(_sf(close) * adj_factor, 2) if close and adj_factor else None
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
    E10: 个股资金流向端点 — ECM moneyflow_cache 优先（252号方案 Phase 5）

    数据源: moneyflow_cache（全市场日终同步，T+1可用）
    缓存: TieredMemoryCache analysis(30min)
    错误: 全源失败 → 503 DataUnavailable
    """
    from app.data.memory_cache import TieredMemoryCache
    from app.data.enhanced_cache_manager import get_ecm_instance

    cache = TieredMemoryCache()
    cache_key = f'moneyflow:{ts_code}'

    cached = cache.get(cache_key, 'analysis')
    if cached is not None:
        return jsonify({'code': 0, 'data': cached})

    ecm = get_ecm_instance()

    # 从 moneyflow_cache 取最近30日数据
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=30)
    mf_df = ecm.get_cached_moneyflow(
        ts_code=ts_code,
        start_date=start_dt.strftime('%Y-%m-%d'),
        end_date=end_dt.strftime('%Y-%m-%d')
    )

    # 如果 ECM 无数据，降级 Tushare
    if mf_df.empty:
        try:
            from app.data.tushare_provider import TushareProvider
            tp = TushareProvider()
            if tp.pro:
                records = []
                for i in range(30):
                    d = (end_dt - timedelta(days=i)).strftime('%Y%m%d')
                    raw = tp.get_moneyflow(trade_date=d)
                    if raw:
                        row = next((r for r in raw if r.get('ts_code') == ts_code), None)
                        if row:
                            records.append(row)
                            if len(records) >= 5:
                                break
                if records:
                    return jsonify({'code': 0, 'data': _build_moneyflow_response(ts_code, records)})
        except Exception as e:
            logger.warning(f"资金流向 Tushare 降级失败 ({ts_code}): {e}")
        return jsonify({
            'code': -1, 'message': '资金流向数据不可用',
            'error_type': 'DataUnavailable',
        }), 503

    # 从 DataFrame 提取最近5个交易日
    mf_df = mf_df.sort_values('trade_date', ascending=False)
    unique_dates = mf_df['trade_date'].unique()[:5]
    records = []
    for d in unique_dates:
        day = mf_df[mf_df['trade_date'] == d]
        if not day.empty:
            records.append(day.iloc[0].to_dict())

    if not records:
        return jsonify({
            'code': -1, 'message': '资金流向数据不可用',
            'error_type': 'DataUnavailable',
        }), 503

    result = _build_moneyflow_response(ts_code, records)
    cache.set(cache_key, result, 'analysis')
    return jsonify({'code': 0, 'data': result})


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


def _build_moneyflow_response(ts_code: str, records: list) -> dict:
    """从资金流向记录构建 E10 统一响应格式"""
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

    return {
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


@market_bp.route('/api/v3/stock/<ts_code>/orderbook', methods=['GET'])
@handle_exceptions
def get_stock_orderbook(ts_code):
    """E8: 盘口五档数据（实时）"""
    try:
        from app.data.in_memory_store import store as mem_store
        snapshot = mem_store.get_snapshot()
        for item in snapshot:
            if item.get('ts_code') == ts_code:
                bid = []
                ask = []
                for i in range(1, 6):
                    bp = item.get(f'bid{i}_price')
                    bv = item.get(f'bid{i}_volume')
                    if bp is not None:
                        bid.append({'price': float(bp), 'volume': int(bv or 0)})
                    ap = item.get(f'ask{i}_price')
                    av = item.get(f'ask{i}_volume')
                    if ap is not None:
                        ask.append({'price': float(ap), 'volume': int(av or 0)})
                if bid or ask:
                    return jsonify({'success': True, 'data': {'ts_code': ts_code, 'bid': bid, 'ask': ask}})
        return jsonify({'success': True, 'data': {'ts_code': ts_code, 'bid': [], 'ask': [], 'message': '非交易时段或盘口数据不可用'}})
    except Exception as e:
        logger.warning(f"盘口数据获取失败 ({ts_code}): {e}")
        return jsonify({'success': True, 'data': {'ts_code': ts_code, 'bid': [], 'ask': [], 'message': '盘口数据源未就绪'}})


@market_bp.route('/api/v3/stock/<ts_code>/stk-limit', methods=['GET'])
@handle_exceptions
def get_stock_stk_limit(ts_code):
    """E9: 涨跌停/笼子价格"""
    from app.data.enhanced_cache_manager import get_ecm_instance
    ecm = get_ecm_instance()
    today = datetime.now().strftime('%Y-%m-%d')
    df = ecm.get_cached_stk_limit(trade_date=today)
    if df is not None and not df.empty:
        row = df[df['ts_code'] == ts_code]
        if row.empty:
            return jsonify({'success': True, 'data': {'ts_code': ts_code, 'trade_date': today, 'high_limit': 0, 'low_limit': 0, 'cage_price': None, 'message': '今日无涨跌停数据'}})
        latest = row.iloc[-1].to_dict()
        high_limit = float(latest.get('high_limit', 0))
        low_limit = float(latest.get('low_limit', 0))
        result = {'success': True, 'data': {'ts_code': ts_code, 'trade_date': today, 'high_limit': high_limit, 'low_limit': low_limit, 'cage_price': None, 'cage_up_pct': 2.0, 'cage_down_pct': -2.0}}
        try:
            dm = _get_dm()
            daily_df = dm.get_cached_daily_data(ts_code, start_date=today)
            if daily_df is not None and not daily_df.empty:
                pre_close = float(daily_df.iloc[-1].get('pre_close', 0))
                if pre_close > 0:
                    result['data']['cage_price'] = pre_close
                    result['data']['cage_up_price'] = round(pre_close * 1.02, 2)
                    result['data']['cage_down_price'] = round(pre_close * 0.98, 2)
        except Exception:
            pass
        return jsonify(result)
    return jsonify({'success': True, 'data': {'ts_code': ts_code, 'trade_date': today, 'high_limit': 0, 'low_limit': 0, 'cage_price': None, 'message': '涨跌停数据不可用'}})
