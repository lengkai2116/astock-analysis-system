"""
指标图表数据接口
为前端 K线图表提供统一格式的数据
"""
import logging
from app.utils.error_handlers import handle_exceptions
from flask import Blueprint, request, jsonify
from app import db
from app.indicators import TechnicalIndicatorEngine
from app.data import DataManager
import pandas as pd
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

chart_bp = Blueprint('chart', __name__, url_prefix='/api/v3/chart')

indicator_engine = TechnicalIndicatorEngine()
_data_manager = None

def get_data_manager():
    global _data_manager
    if _data_manager is None:
        _data_manager = DataManager()
    return _data_manager

# ============ 指标配置 ============

# 主图指标（叠加在K线上）
OVERLAY_INDICATORS = {
    'ma5':   {'name': 'MA5',   'color': '#ffffff', 'type': 'overlay'},
    'ma10':  {'name': 'MA10',  'color': '#ff9800', 'type': 'overlay'},
    'ma20':  {'name': 'MA20',  'color': '#2196f3', 'type': 'overlay'},
    'boll_upper':  {'name': 'BOLL上轨',  'color': '#e91e63', 'type': 'overlay', 'line_style': 'dashed'},
    'boll_middle': {'name': 'BOLL中轨',  'color': '#4caf50', 'type': 'overlay', 'line_style': 'solid'},
    'boll_lower':  {'name': 'BOLL下轨',  'color': '#e91e63', 'type': 'overlay', 'line_style': 'dashed'},
}

# 副图指标（独立面板）
SUB_INDICATORS = {
    'vol':      {'name': 'VOL',      'panel': 1},
    'macd':     {'name': 'MACD',     'panel': 2},
    'rsi':      {'name': 'RSI',      'panel': 3},
    'kdj':      {'name': 'KDJ',      'panel': 4},
}


def _format_time(ts_code, trade_date):
    """将trade_date转换为TradingView时间戳（秒级）"""
    if pd.isna(trade_date):
        return None
    if isinstance(trade_date, str):
        dt = datetime.strptime(trade_date, '%Y%m%d') if len(str(trade_date)) == 8 else datetime.strptime(str(trade_date), '%Y-%m-%d')
    elif isinstance(trade_date, datetime):
        dt = trade_date
    elif isinstance(trade_date, pd.Timestamp):
        dt = trade_date.to_pydatetime()
    else:
        dt = datetime.strptime(str(trade_date), '%Y-%m-%d')
    return int(dt.timestamp())


def _get_kline_data(data_manager, ts_code, limit=200, period='D'):
    """
    获取K线数据
    period: D (日线)/W (周线)/M (月线)/1m/5m/15m/30m/60m
    """
    # 分钟线数据暂时通过日线降采样或返回提示，目前优先用日线
    if period in ['1m', '5m', '15m', '30m', '60m']:
        # 分钟线暂时降级到日线，后续可接入实时行情源
        kline_data = data_manager.get_cached_daily_data(ts_code, start_date=None, end_date=None)
    else:
        # 使用DataManager的get_kline_data方法获取对应周期的数据
        kline_data = data_manager.get_kline_data(ts_code, period=period, start_date=None, end_date=None)
    
    if kline_data.empty:
        return None, None
    
    # 转换Decimal类型为float类型，避免类型错误
    for col in ['open', 'high', 'low', 'close', 'vol', 'amount', 'pct_chg']:
        if col in kline_data.columns:
            try:
                kline_data[col] = kline_data[col].astype(float)
            except Exception:
                pass
    
    return kline_data, None
@handle_exceptions
@chart_bp.route('/kline/<ts_code>', methods=['GET'])
def get_kline_chart_data(ts_code):
    """
    获取K线图表数据（主图K线 + 叠加指标 + 副图指标 + 信号）
    
    Query params:
        indicators: 逗号分隔的指标列表，如 ma5,ma20,macd,rsi
        period: 时间周期，支持 D(日线)/W(周线)/M(月线)/1m/5m/15m/30m/60m
        limit: 数据条数，默认200
    
    Response:
    {
        "success": true,
        "data": {
            "kline": [{time, open, high, low, close, volume}, ...],
            "overlays": [{"name", "data": [{time, value}], "color", "line_style"}, ...],
            "subcharts": [{"name", "panel", "data": [{time, dif, dea, hist}, ...]}, ...],
            "signals": [{"time", "type", "price", "text"}, ...],
            "stock": {"ts_code", "name", "industry"}
        }
    }
    """
    limit = request.args.get('limit', 200, type=int)
    indicators_param = request.args.get('indicators', '')
    period = request.args.get('period', 'D')
    
    # 规范化周期参数：数字转换为带m的格式，其他保持原样
    if period in ['1', '5', '15', '30', '60']:
        period = period + 'm'
    # 小周期降级到日线
    if period in ['1m', '5m', '15m', '30m', '60m']:
        period = 'D'
    
    # 解析指标列表
    requested_indicators = [i.strip() for i in indicators_param.split(',') if i.strip()] if indicators_param else ['ma5', 'ma20', 'macd', 'rsi', 'kdj']
    
    # 处理BOLL特殊情况：请求boll时自动包含boll_upper/middle/lower
    if 'boll' in requested_indicators:
        for boll_key in ['boll_upper', 'boll_middle', 'boll_lower']:
            if boll_key not in requested_indicators:
                requested_indicators.append(boll_key)
    
    # 分离主图和副图指标
    overlay_keys = [k for k in requested_indicators if k in OVERLAY_INDICATORS]
    sub_keys = [k for k in requested_indicators if k in SUB_INDICATORS]
    
    # 默认包含VOL
    if 'vol' not in sub_keys and 'volume' in requested_indicators:
        sub_keys.append('vol')
    elif 'vol' not in sub_keys and 'volume' not in requested_indicators:
        sub_keys.insert(0, 'vol')  # 默认加入VOL
    
    # 调试输出
    logger.debug(f"requested_indicators: {requested_indicators}")
    logger.debug(f"overlay_keys: {overlay_keys}")
    logger.debug(f"sub_keys: {sub_keys}")
    
    try:
        data_manager = get_data_manager()
        daily_data, _ = _get_kline_data(data_manager, ts_code, limit=limit, period=period)
        
        if daily_data is None or daily_data.empty:
            return jsonify({
                'success': False,
                'message': f'未找到{period}周期数据'
            }), 404
        
        # 指标计算需要足够的数据（至少50条），所以先取足够数据
        min_data_for_indicators = 50
        actual_limit = max(limit, min_data_for_indicators)
        daily_data = daily_data.tail(actual_limit) if len(daily_data) > actual_limit else daily_data
        
        # 计算所有技术指标
        df = indicator_engine.calculate_all_indicators(daily_data)
        
        # 调试输出：查看计算后的DataFrame列
        logger.debug(f"DataFrame columns: {list(df.columns)}")
        logger.debug(f"DataFrame rows: {len(df)}")
        
        # ---- K线数据 ----
        kline_data = []
        for _, row in df.iterrows():
            t = _format_time(ts_code, row.get('trade_date'))
            if t is None:
                continue
            kline_data.append({
                'time': t,
                'open': float(row.get('open', 0)),
                'high': float(row.get('high', 0)),
                'low': float(row.get('low', 0)),
                'close': float(row.get('close', 0)),
                'volume': float(row.get('vol', 0)) if pd.notna(row.get('vol')) else 0,
                'pct_chg': float(row.get('pct_chg', 0)) if pd.notna(row.get('pct_chg')) else 0
            })
        
        # ---- 叠加指标 ----
        overlays = []
        for key in overlay_keys:
            if key.startswith('ma'):
                col = key  # ma5, ma10, ma20
                info = OVERLAY_INDICATORS.get(key, {'name': key.upper(), 'color': '#ffffff'})
                series_data = []
                for _, row in df.iterrows():
                    t = _format_time(ts_code, row.get('trade_date'))
                    if t is None or pd.isna(row.get(col)):
                        continue
                    series_data.append({'time': t, 'value': float(row[col])})
                if series_data:
                    overlays.append({
                        'id': key,
                        'name': info['name'],
                        'data': series_data,
                        'color': info['color'],
                        'line_style': info.get('line_style', 'solid'),
                        'panel': 0
                    })
            elif key.startswith('boll'):
                info = OVERLAY_INDICATORS.get(key, {'name': key, 'color': '#4caf50'})
                series_data = []
                for _, row in df.iterrows():
                    t = _format_time(ts_code, row.get('trade_date'))
                    if t is None or pd.isna(row.get(key)):
                        continue
                    series_data.append({'time': t, 'value': float(row[key])})
                if series_data:
                    overlays.append({
                        'id': key,
                        'name': info['name'],
                        'data': series_data,
                        'color': info['color'],
                        'line_style': info.get('line_style', 'solid'),
                        'panel': 0
                    })
        
        # ---- 副图指标 ----
        subcharts = []
        
        # VOL
        if 'vol' in sub_keys:
            vol_data = []
            for _, row in df.iterrows():
                t = _format_time(ts_code, row.get('trade_date'))
                if t is None or pd.isna(row.get('vol')):
                    continue
                vol_data.append({
                    'time': t,
                    'value': float(row['vol']),
                    'color': '#22C55E' if float(row.get('close', 0)) >= float(row.get('open', 0)) else '#EF4444'
                })
            if vol_data:
                subcharts.append({
                    'id': 'vol',
                    'name': '成交量',
                    'panel': 1,
                    'data': vol_data
                })
        
        # MACD
        if 'macd' in sub_keys:
            macd_data = []
            for _, row in df.iterrows():
                t = _format_time(ts_code, row.get('trade_date'))
                if t is None:
                    continue
                dif_val = row.get('macd_dif')
                dea_val = row.get('macd_dea')
                hist_val = row.get('macd_hist')
                if pd.isna(dif_val) or pd.isna(dea_val) or pd.isna(hist_val):
                    continue
                macd_data.append({
                    'time': t,
                    'dif': float(dif_val),
                    'dea': float(dea_val),
                    'hist': float(hist_val)
                })
            if macd_data:
                subcharts.append({
                    'id': 'macd',
                    'name': 'MACD',
                    'panel': 2,
                    'data': macd_data
                })
        
        # RSI
        if 'rsi' in sub_keys:
            rsi_data = []
            for _, row in df.iterrows():
                t = _format_time(ts_code, row.get('trade_date'))
                if t is None or pd.isna(row.get('rsi14')):
                    continue
                rsi_data.append({
                    'time': t,
                    'value': float(row['rsi14'])
                })
            if rsi_data:
                subcharts.append({
                    'id': 'rsi',
                    'name': 'RSI',
                    'panel': 3,
                    'data': rsi_data
                })
        
        # KDJ
        if 'kdj' in sub_keys:
            kdj_data = []
            for _, row in df.iterrows():
                t = _format_time(ts_code, row.get('trade_date'))
                if t is None:
                    continue
                k_val = row.get('kdj_k')
                d_val = row.get('kdj_d')
                j_val = row.get('kdj_j')
                if pd.isna(k_val) or pd.isna(d_val) or pd.isna(j_val):
                    continue
                kdj_data.append({
                    'time': t,
                    'k': float(k_val),
                    'd': float(d_val),
                    'j': float(j_val)
                })
            if kdj_data:
                subcharts.append({
                    'id': 'kdj',
                    'name': 'KDJ',
                    'panel': 4,
                    'data': kdj_data
                })
        
        # ---- 股票信息 ----
        stock_info = data_manager.get_stock_info(ts_code)

        # ---- 最新行情（头部栏用） ----
        last_k = kline_data[-1] if kline_data else {}

        return jsonify({
            'success': True,
            'data': {
                'kline': kline_data,
                'overlays': overlays,
                'subcharts': subcharts,
                'stock': stock_info if stock_info else {},
                'latest': {
                    'close': last_k.get('close', 0),
                    'pct_chg': last_k.get('pct_chg', 0)
                }
            }
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500
@handle_exceptions
@chart_bp.route('/signals/<ts_code>', methods=['GET'])
def get_chart_signals(ts_code):
    """
    获取指定股票的信号标记数据
    返回 TradingView 格式的信号点
    """
    limit = request.args.get('limit', 100, type=int)
    
    try:
        data_manager = get_data_manager()
        daily_data = data_manager.get_cached_daily_data(ts_code, start_date=None, end_date=None)
        
        if daily_data.empty:
            return jsonify({
                'success': False,
                'message': '未找到日线数据'
            }), 404
        
        # 转换Decimal类型为float类型
        for col in ['open', 'high', 'low', 'close', 'vol', 'amount', 'pct_chg']:
            if col in daily_data.columns:
                try:
                    daily_data[col] = daily_data[col].astype(float)
                except Exception:
                    pass
        
        # 取最后N条
        daily_data = daily_data.tail(limit) if len(daily_data) > limit else daily_data
        
        # 计算指标
        df = indicator_engine.calculate_all_indicators(daily_data)
        
        # 使用信号生成器
        from app.signals import SignalGenerator
        sg = SignalGenerator()
        signals_list = sg.generate_all_signals(df)
        
        # 转换为图表格式
        signal_markers = []
        for sig in signals_list:
            t = _format_time(ts_code, sig.get('date'))
            if t is None:
                continue
            sig_type = sig.get('signal_type', 'neutral')
            signal_markers.append({
                'time': t,
                'type': 'buy' if sig_type == 'buy' else 'sell',
                'price': float(sig.get('price', 0)),
                'text': 'B' if sig_type == 'buy' else 'S',
                'color': '#22C55E' if sig_type == 'buy' else '#EF4444',
                'indicator': sig.get('indicator', ''),
                'confidence': sig.get('confidence', 0)
            })
        
        return jsonify({
            'success': True,
            'data': signal_markers
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500
@handle_exceptions
@chart_bp.route('/indicators', methods=['GET'])
def get_indicator_list():
    """
    获取可用指标列表（用于前端指标选择器）
    """
    result = {
        'overlays': [
            {'id': 'ma5',   'name': 'MA5',   'category': '均线', 'default': True},
            {'id': 'ma10',  'name': 'MA10',  'category': '均线', 'default': False},
            {'id': 'ma20',  'name': 'MA20',  'category': '均线', 'default': True},
            {'id': 'boll_upper',  'name': 'BOLL上轨', 'category': '布林带', 'default': False},
            {'id': 'boll_middle', 'name': 'BOLL中轨', 'category': '布林带', 'default': False},
            {'id': 'boll_lower',  'name': 'BOLL下轨', 'category': '布林带', 'default': False},
        ],
        'subcharts': [
            {'id': 'vol',   'name': '成交量', 'category': '成交量', 'default': True},
            {'id': 'macd',  'name': 'MACD',   'category': '趋势',   'default': True},
            {'id': 'rsi',   'name': 'RSI',    'category': '动量',   'default': True},
            {'id': 'kdj',   'name': 'KDJ',    'category': '动量',   'default': True},
        ]
    }
    return jsonify({
        'success': True,
        'data': result
    })
@handle_exceptions
@chart_bp.route('/stock-list', methods=['GET'])
def get_stock_list():
    """
    获取股票列表（用于前端股票搜索）
    """
    limit = request.args.get('limit', 50, type=int)
    keyword = request.args.get('keyword', '')
    
    try:
        data_manager = get_data_manager()
        stocks = data_manager.get_stock_list(keyword=keyword, limit=limit)
        
        return jsonify({
            'success': True,
            'data': stocks
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500
