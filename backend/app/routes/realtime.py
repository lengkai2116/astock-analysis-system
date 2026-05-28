import os
import json
import time
import threading
from datetime import datetime, timedelta
from flask import Blueprint, request
from flask_socketio import emit, join_room
from .. import socketio
from ..data.tushare_provider import TushareProvider
from ..data.akshare_provider import AkShareRealtimeProvider
from ..data.enhanced_cache_manager import EnhancedCacheManager
from ..data.redis_cache_manager import RedisCacheManager

realtime_bp = Blueprint('realtime', __name__)

tushare = TushareProvider()
akshare = AkShareRealtimeProvider()
cache_manager = EnhancedCacheManager()
redis_manager = RedisCacheManager()

class RealtimeDataService:
    """实时数据服务 - 定时拉取并推送"""
    
    def __init__(self):
        self.running = False
        self.thread = None
        self.publisher = redis_manager.client
        if self.publisher:
            self.subscriber = self.publisher.pubsub()
            self.subscriber.subscribe('market_realtime')
        else:
            self.subscriber = None
        self.tushare = tushare
        self.akshare = akshare
        self.default_watchlist = ['600519.SH', '000001.SZ', '000002.SZ']
        
    def start(self):
        """启动实时数据服务"""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._data_publisher_loop, daemon=True)
            self.thread.start()
            print("✅ 实时数据服务已启动")
    
    def stop(self):
        """停止实时数据服务"""
        self.running = False
        if self.thread:
            self.thread.join()
        print("✅ 实时数据服务已停止")
    
    def _data_publisher_loop(self):
        """定时发布实时数据"""
        while self.running:
            try:
                data = self._fetch_current_market_data()
                if data:
                    self.publisher.publish('market_realtime', json.dumps(data))
                    print(f"📡 已推送实时数据 - {datetime.now().strftime('%H:%M:%S')}")
            except Exception as e:
                print(f"❌ 获取实时数据失败: {e}")
            
            time.sleep(3)
    
    def _fetch_current_market_data(self):
        """获取当前市场数据"""
        market_data = []
        
        try:
            for ts_code in self.default_watchlist:
                try:
                    data = self._get_stock_realtime_data(ts_code)
                    if data:
                        market_data.append(data)
                except Exception as e:
                    print(f"⚠️ 获取 {ts_code} 数据失败: {e}")
                    continue
        except Exception as e:
            print(f"❌ 批量获取失败: {e}")
        
        return {
            'type': 'market_realtime',
            'data': market_data,
            'timestamp': datetime.now().isoformat()
        }
    
    def _get_stock_realtime_data(self, ts_code):
        """获取单只股票的实时数据"""
        # 首先尝试使用Tushare日线数据（更稳定）
        try:
            daily_data = self.tushare.get_daily_data(ts_code)
            
            if not daily_data or len(daily_data) == 0:
                return None
            
            latest = daily_data[0]
            prev_close = float(latest.get('pre_close', latest.get('close', 0)))
            current_price = float(latest.get('close', 0))
            
            change = current_price - prev_close
            change_pct = (change / prev_close * 100) if prev_close > 0 else 0
            
            return {
                'ts_code': ts_code,
                'name': self._get_stock_name(ts_code),
                'price': current_price,
                'change': round(change, 2),
                'change_pct': round(change_pct, 2),
                'volume': latest.get('vol', 0),
                'amount': latest.get('amount', 0),
                'high': latest.get('high', 0),
                'low': latest.get('low', 0),
                'open': latest.get('open', 0),
                'close': latest.get('close', 0),
                'turnover_rate': 0,
                'pe': 0,
                'pb': 0,
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            print(f"⚠️ 处理 {ts_code} 数据失败: {e}")
            return None
    
    def _get_stock_name(self, ts_code):
        """获取股票名称"""
        name_map = {
            '600519.SH': '贵州茅台',
            '000001.SZ': '平安银行',
            '000002.SZ': '万科A',
            '000858.SZ': '五粮液',
            '000063.SZ': '中兴通讯'
        }
        return name_map.get(ts_code, ts_code)

realtime_service = RealtimeDataService()

@socketio.on('connect')
def handle_connect():
    """处理客户端连接"""
    print(f"🔌 客户端已连接 - 会话ID: {request.sid}")
    emit('connected', {'status': 'connected', 'message': '已连接到实时数据服务'})

@socketio.on('disconnect')
def handle_disconnect():
    """处理客户端断开连接"""
    print(f"❌ 客户端已断开 - 会话ID: {request.sid}")

@socketio.on('subscribe_watchlist')
def handle_subscribe_watchlist(data):
    """订阅自选股更新"""
    watchlist = data.get('watchlist', [])
    join_room('watchlist')
    print(f"📋 客户端订阅自选股: {watchlist}")
    
    initial_data = realtime_service._fetch_current_market_data()
    emit('watchlist_update', initial_data, room='watchlist')

@socketio.on('subscribe_kline')
def handle_subscribe_kline(data):
    """订阅K线更新"""
    ts_code = data.get('ts_code')
    freq = data.get('freq', '15min')
    
    if ts_code:
        room = f'kline_{ts_code}'
        join_room(room)
        print(f"📊 客户端订阅K线: {ts_code} ({freq})")
        
        try:
            kline_data = tushare.get_minute_data(ts_code, freq)
            if kline_data:
                emit('kline_init', {
                    'ts_code': ts_code,
                    'freq': freq,
                    'data': kline_data
                }, room=room)
        except Exception as e:
            print(f"⚠️ 获取初始K线失败: {e}")

@socketio.on('join_room')
def handle_join_room(data):
    """加入指定房间"""
    room = data.get('room')
    if room:
        join_room(room)
        print(f"🏠 客户端加入房间: {room}")

@realtime_bp.route('/api/v3/market/realtime', methods=['GET'])
def get_realtime_market():
    """获取最新市场数据 - REST API"""
    data = realtime_service._fetch_current_market_data()
    return data, 200

@realtime_bp.route('/api/v3/market/indexes', methods=['GET'])
def get_indexes_realtime():
    """获取指数最新数据 - REST API"""
    indices = [
        {'ts_code': '000001.SH', 'name': '上证指数'},
        {'ts_code': '399001.SZ', 'name': '深证成指'},
        {'ts_code': '399006.SZ', 'name': '创业板指'}
    ]
    
    result = []
    for idx in indices:
        # 直接使用Tushare日线数据（更稳定）
        try:
            idx_data = tushare.get_index_daily(idx['ts_code'])
            if idx_data and len(idx_data) > 0:
                latest = idx_data[0]
                prev_data = idx_data[1] if len(idx_data) > 1 else None
                prev_close = prev_data['close'] if prev_data else latest['pre_close']
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
                    'amount': latest['amount']
                })
            else:
                result.append({
                    'ts_code': idx['ts_code'],
                    'name': idx['name'],
                    'value': 0,
                    'change': 0,
                    'changePercent': 0,
                    'open': 0,
                    'high': 0,
                    'low': 0,
                    'close': 0,
                    'pre_close': 0,
                    'volume': 0,
                    'amount': 0
                })
        except Exception as e:
            print(f'⚠️ 获取指数 {idx["name"]} 数据失败: {e}')
            result.append({
                'ts_code': idx['ts_code'],
                'name': idx['name'],
                'value': 0,
                'change': 0,
                'changePercent': 0,
                'open': 0,
                'high': 0,
                'low': 0,
                'close': 0,
                'pre_close': 0,
                'volume': 0,
                'amount': 0
            })
    
    return {'success': True, 'data': result}, 200

@realtime_bp.route('/api/v3/market/realtime/start', methods=['POST'])
def start_realtime_service():
    """启动实时数据服务"""
    try:
        realtime_service.start()
        return {'status': 'success', 'message': '实时数据服务已启动'}, 200
    except Exception as e:
        return {'status': 'error', 'message': str(e)}, 500

@realtime_bp.route('/api/v3/market/realtime/stop', methods=['POST'])
def stop_realtime_service():
    """停止实时数据服务"""
    try:
        realtime_service.stop()
        return {'status': 'success', 'message': '实时数据服务已停止'}, 200
    except Exception as e:
        return {'status': 'error', 'message': str(e)}, 500

@realtime_bp.route('/api/v3/watchlist/stream', methods=['GET'])
def get_watchlist_stream():
    """获取自选股流式数据 - REST接口"""
    data = realtime_service._fetch_current_market_data()
    return data, 200

@realtime_bp.route('/api/v3/indicator/realtime', methods=['POST'])
def get_realtime_indicator():
    """实时计算技术指标"""
    try:
        req_data = request.get_json()
        ts_code = req_data.get('ts_code')
        indicators = req_data.get('indicators', [])
        
        from app.indicators import TechnicalIndicatorEngine
        calculator = TechnicalIndicatorEngine()
        
        daily_data = tushare.get_daily_data(ts_code)
        result_df = calculator.calculate_all_indicators(daily_data)
        result = calculator.get_latest_indicators(result_df)
        
        return {'data': result, 'timestamp': datetime.now().isoformat()}, 200
    except Exception as e:
        return {'error': str(e)}, 500

@socketio.on('trigger_publish')
def handle_trigger_publish():
    """手动触发一次数据发布（用于测试）"""
    print("⚡ 手动触发数据发布")
    data = realtime_service._fetch_current_market_data()
    socketio.emit('watchlist_update', data, room='watchlist')
    return {'status': 'published', 'data': data}

def _redis_subscriber_thread():
    """Redis订阅线程 - 转发消息到WebSocket"""
    try:
        for message in realtime_service.subscriber.listen():
            if message['type'] == 'message':
                try:
                    data = json.loads(message['data'])
                    socketio.emit('watchlist_update', data, room='watchlist')
                except Exception as e:
                    print(f"⚠️ 转发消息失败: {e}")
    except Exception as e:
        print(f"❌ Redis订阅线程错误: {e}")

def initialize_realtime_service():
    """初始化并启动实时数据服务"""
    try:
        realtime_service.start()
        
        redis_thread = threading.Thread(target=_redis_subscriber_thread, daemon=True)
        redis_thread.start()
        
        print("🚀 实时数据服务系统初始化完成")
    except Exception as e:
        print(f"❌ 初始化实时服务失败: {e}")

initialize_realtime_service()
