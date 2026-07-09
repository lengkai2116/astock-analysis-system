"""
实时行情 API 路由 — 推拉结合数据管道
======================================
架构（240号方案 §4）：
  推送：AkshareCollector 5线程 → InMemoryStateStore → WsBridge → SocketIO → 前端
  拉取：REST API 降级（前端 WS 断连时自动轮询）

Flask-SocketIO 事件协议：
  前端事件 → 后端         后端推事件 → 前端
  ────────────────────     ────────────────────────
  subscribe_watchlist      market:summary
  subscribe_kline           market:top_stocks
  subscribe_qmt_tick       market:sectors
  join_room                stock:quotes
"""
import logging
from datetime import datetime

from flask import Blueprint, request
from flask_socketio import emit, join_room

from .. import socketio
from ..data.in_memory_store import store
from ..utils.trading_hours import is_trading_time

logger = logging.getLogger(__name__)

realtime_bp = Blueprint('realtime', __name__)

# ponytail: 惰性初始化，避免模块导入时连接外部服务
_tushare = None
_akshare = None
_ak = None


def _get_tushare():
    global _tushare
    if _tushare is None:
        from ..data.tushare_provider import TushareProvider
        _tushare = TushareProvider()
    return _tushare


def _get_akshare():
    global _akshare
    if _akshare is None:
        from ..data.akshare_provider import AkShareRealtimeProvider
        _akshare = AkShareRealtimeProvider()
    return _akshare


def _get_ak():
    global _ak
    if _ak is None:
        from ..data.akshare_provider import AkshareProvider
        _ak = AkshareProvider()
    return _ak


# ── 辅助函数（替换旧 RealtimeDataService._fetch_current_market_data） ──────

_DEFAULT_WATCHLIST = ['600519.SH', '000001.SZ', '000002.SZ']


def _fetch_current_market_data() -> dict:
    """从 InMemoryStateStore 读取当前市场数据（兼容旧返回格式）"""
    snapshot = store.get_snapshot()
    # 按默认自选股过滤
    data = [s for s in snapshot if s.get('ts_code') in _DEFAULT_WATCHLIST]
    # 如果没有数据（非交易时段），降级为当日 DuckDB 数据
    if not data:
        for code in _DEFAULT_WATCHLIST:
            try:
                daily = _get_tushare().get_daily_data(code)
                if daily and len(daily) > 0:
                    latest = daily[0]
                    data.append({
                        'ts_code': code,
                        'name': '—',
                        'price': float(latest.get('close', 0)),
                        'change': round(float(latest.get('change', 0)), 2),
                        'change_pct': round(float(latest.get('pct_chg', 0)), 2),
                        'volume': latest.get('vol', 0),
                        'amount': latest.get('amount', 0),
                        'timestamp': datetime.now().isoformat(),
                        'source': 'tushare',
                    })
            except Exception:
                continue
    return {
        'type': 'market_realtime',
        'data': data,
        'timestamp': datetime.now().isoformat(),
    }


# ══════════════════════════════════════════════════════════════════════
# SocketIO 事件处理器
# ══════════════════════════════════════════════════════════════════════


@socketio.on('connect')
def handle_connect():
    """处理客户端连接"""
    logger.info(f"客户端已连接 - 会话ID: {request.sid}")
    emit('connected', {'status': 'connected', 'message': '已连接到实时数据服务'})


@socketio.on('disconnect')
def handle_disconnect():
    """处理客户端断开连接"""
    logger.info(f"客户端已断开 - 会话ID: {request.sid}")


@socketio.on('subscribe_watchlist')
def handle_subscribe_watchlist(data):
    """订阅自选股更新 — 注册到桥接器自动推送 + 初始快照"""
    watchlist = data.get('watchlist', [])
    join_room('watchlist')
    logger.info(f"客户端订阅自选股: {len(watchlist)} 只")

    # 注册到 WsBridge，后续采集循环自动推送
    try:
        from app.data.ws_bridge import ws_bridge
        ws_bridge.update_watchlist_codes(watchlist)
    except Exception:
        pass

    quotes = store.batch_get(watchlist)
    emit('watchlist_update', {
        'type': 'watchlist_update',
        'data': quotes or [],
        'timestamp': datetime.now().isoformat(),
    }, room='watchlist')


@socketio.on('subscribe_kline')
def handle_subscribe_kline(data):
    """订阅K线更新"""
    ts_code = data.get('ts_code')
    freq = data.get('freq', '15min')

    if ts_code:
        room = f'kline_{ts_code}'
        join_room(room)
        logger.info(f"客户端订阅K线: {ts_code} ({freq})")

        try:
            kline_data = _get_tushare().get_minute_data(ts_code, freq) if _get_tushare else []
            if kline_data:
                emit('kline_init', {
                    'ts_code': ts_code,
                    'freq': freq,
                    'data': kline_data,
                }, room=room)
        except Exception as e:
            logger.warning(f"获取初始K线失败: {e}")


@socketio.on('subscribe_qmt_tick')
def handle_subscribe_qmt_tick(data):
    """订阅 QMT Tick 数据（L2 行情）

    客户端消息: {'ts_codes': ['600519.SH', ...]}
    盘中若无 QMT → 降级为 InMemoryStateStore 批量行情
    """
    ts_codes = data.get('ts_codes', [])
    if not ts_codes:
        return

    room = 'qmt_tick'
    join_room(room)
    logger.info(f"客户端订阅 QMT Tick: {len(ts_codes)} 只")

    # 尝试 QMT
    try:
        from app.data.qmt_provider import QmtDataProvider
        qmt = QmtDataProvider()
        if qmt.connect():
            snapshot = qmt.get_market_snapshot(ts_codes)
            if snapshot:
                emit('qmt_tick_init', {
                    'data': snapshot,
                    'ts_codes': ts_codes,
                    'source': 'qmt',
                }, room=room)
                return
    except Exception as e:
        logger.warning(f"QMT 不可用，降级为 InMemoryStateStore 快照: {e}")

    # 降级：InMemoryStateStore 批量行情
    quotes = store.batch_get(ts_codes)
    emit('qmt_tick_init', {
        'data': quotes or [],
        'ts_codes': ts_codes,
        'source': 'in_memory_store',
    }, room=room)


@socketio.on('join_room')
def handle_join_room(data):
    """加入指定房间"""
    room = data.get('room')
    if room:
        join_room(room)
        logger.info(f"客户端加入房间: {room}")


# ══════════════════════════════════════════════════════════════════════
# REST API 端点
# ══════════════════════════════════════════════════════════════════════


@realtime_bp.route('/api/v3/market/realtime', methods=['GET'])
def get_realtime_market():
    """获取最新市场数据 — 从 InMemoryStateStore 读取"""
    return _fetch_current_market_data(), 200


@realtime_bp.route('/api/v3/market/indexes', methods=['GET'])
def get_indexes_realtime():
    """获取指数最新数据 — REST API"""
    indices = [
        {'ts_code': '000001.SH', 'name': '上证指数'},
        {'ts_code': '399001.SZ', 'name': '深证成指'},
        {'ts_code': '399006.SZ', 'name': '创业板指'},
    ]

    result = []
    for idx in indices:
        try:
            # 盘中 → InMemoryStateStore 实时指数（从 snapshot 过滤）
            if is_trading_time():
                snapshot = store.get_snapshot()
                matched = [s for s in snapshot if s.get('ts_code') == idx['ts_code']]
                if matched:
                    r = matched[0]
                    result.append({
                        'ts_code': idx['ts_code'],
                        'name': idx['name'],
                        'value': r.get('price', 0),
                        'change': round(r.get('change', 0), 2),
                        'changePercent': round(r.get('change_pct', 0), 2),
                        'open': r.get('open', 0),
                        'high': r.get('high', 0),
                        'low': r.get('low', 0),
                        'close': r.get('price', 0),
                        'pre_close': r.get('prev_close', 0),
                        'volume': r.get('volume', 0),
                        'amount': r.get('amount', 0),
                    })
                    continue

            # 盘后 → Tushare
            idx_data = _get_tushare().get_index_daily(idx['ts_code'])
            if idx_data and len(idx_data) > 0:
                latest = idx_data[0]
                prev_data = idx_data[1] if len(idx_data) > 1 else None
                prev_close = prev_data['close'] if prev_data else latest.get('pre_close', latest['close'])
                change = latest['close'] - prev_close
                change_pct = (change / prev_close * 100) if prev_close > 0 else 0

                result.append({
                    'ts_code': idx['ts_code'],
                    'name': idx['name'],
                    'value': latest['close'],
                    'change': round(change, 2),
                    'changePercent': round(change_pct, 2),
                    'open': latest['open'],
                    'high': latest['high'],
                    'low': latest['low'],
                    'close': latest['close'],
                    'pre_close': prev_close,
                    'volume': latest['vol'],
                    'amount': latest['amount'],
                })
            else:
                result.append({
                    'ts_code': idx['ts_code'],
                    'name': idx['name'],
                    'value': 0, 'change': 0, 'changePercent': 0,
                    'open': 0, 'high': 0, 'low': 0, 'close': 0,
                    'pre_close': 0, 'volume': 0, 'amount': 0,
                })
        except Exception as e:
            logger.warning(f'获取指数 {idx["name"]} 数据失败: {e}')
            result.append({
                'ts_code': idx['ts_code'],
                'name': idx['name'],
                'value': 0, 'change': 0, 'changePercent': 0,
                'open': 0, 'high': 0, 'low': 0, 'close': 0,
                'pre_close': 0, 'volume': 0, 'amount': 0,
            })

    return {'success': True, 'data': result}, 200


@realtime_bp.route('/api/v3/market/realtime/start', methods=['POST'])
def start_realtime_service():
    """启动 AkshareCollector（替代旧的 Redis 推流服务）"""
    try:
        from app.data.akshare_collector import akshare_collector
        akshare_collector.start()
        return {'status': 'success', 'message': 'AkshareCollector 已启动'}, 200
    except Exception as e:
        return {'status': 'error', 'message': str(e)}, 500


@realtime_bp.route('/api/v3/market/realtime/stop', methods=['POST'])
def stop_realtime_service():
    """停止 AkshareCollector"""
    try:
        from app.data.akshare_collector import akshare_collector
        akshare_collector.stop()
        return {'status': 'success', 'message': 'AkshareCollector 已停止'}, 200
    except Exception as e:
        return {'status': 'error', 'message': str(e)}, 500


@realtime_bp.route('/api/v3/market/connectivity', methods=['GET'])
def check_eastmoney_connectivity():
    """测试数据源连接状态（诊断用）

    mootdx TCP 已替代 EastMoney HTTP 作为主数据源，此端点保留为诊断兼容。
    """
    try:
        # 尝试检查 mootdx 连接
        from app.data.mootdx_collector import mootdx_collector
        is_mootdx_alive = mootdx_collector.is_running()
        return {
            'mootdx': {'status': 'running' if is_mootdx_alive else 'stopped'},
            'message': 'mootdx TCP 已替代 AKShare HTTP 作为主数据源',
        }, 200
    except Exception as e:
        return {'status': 'error', 'message': str(e)}, 500


@realtime_bp.route('/api/v3/watchlist/stream', methods=['GET'])
def get_watchlist_stream():
    """获取自选股流式数据 — REST 接口（降级用）"""
    return _fetch_current_market_data(), 200


@realtime_bp.route('/api/v3/indicator/realtime', methods=['POST'])
def get_realtime_indicator():
    """实时计算技术指标"""
    try:
        req_data = request.get_json()
        ts_code = req_data.get('ts_code')
        indicators = req_data.get('indicators', [])

        from app.indicators import TechnicalIndicatorEngine
        calculator = TechnicalIndicatorEngine()

        daily_data = _get_tushare().get_daily_data(ts_code)
        result_df = calculator.calculate_all_indicators(daily_data)
        result = calculator.get_latest_indicators(result_df)

        return {'data': result, 'timestamp': datetime.now().isoformat()}, 200
    except Exception as e:
        return {'error': str(e)}, 500


@socketio.on('trigger_publish')
def handle_trigger_publish():
    """手动触发 WsBridge 推送（用于测试 — 替代旧 Redis publish）"""
    logger.info("手动触发 WsBridge 推送")
    try:
        from app.data.ws_bridge import ws_bridge
        ws_bridge.on_collect_complete('market_snapshot')
    except Exception as e:
        logger.warning(f"WsBridge 触发失败: {e}")
    return {'status': 'published'}


# ══════════════════════════════════════════════════════════════════════
# 模块初始化
# ══════════════════════════════════════════════════════════════════════


def initialize_realtime_service():
    """初始化实时服务

    240号方案推拉模式：
      采集器启动由 __init__.py 负责（或通过 /start 端点控制）
      本模块仅负责 SocketIO 事件注册 + REST API 端点
    """
    logger.info("实时数据服务已就绪（推拉模式: collector → store → ws_bridge → socketio）")


initialize_realtime_service()
