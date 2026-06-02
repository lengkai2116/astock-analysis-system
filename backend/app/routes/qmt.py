import logging

logger = logging.getLogger(__name__)
"""
QMT行情API路由
提供实时行情数据接口
"""
from flask import Blueprint, jsonify, request
from app.data.qmt_provider import QmtDataProvider
import threading

qmt_bp = Blueprint('qmt', __name__, url_prefix='/api/v3/qmt')

qmt_provider = None
qmt_lock = threading.Lock()


def get_qmt_provider():
    """获取QMT提供者（单例）"""
    global qmt_provider
    with qmt_lock:
        if qmt_provider is None:
            qmt_provider = QmtDataProvider()
    return qmt_provider


@qmt_bp.route('/connect', methods=['POST'])
def connect_qmt():
    """连接miniQMT"""
    provider = get_qmt_provider()
    success = provider.connect()
    return jsonify({
        'success': success,
        'message': '连接成功' if success else '连接失败，请确保miniQMT已启动并登录'
    })


@qmt_bp.route('/disconnect', methods=['POST'])
def disconnect_qmt():
    """断开miniQMT连接"""
    provider = get_qmt_provider()
    provider.disconnect()
    return jsonify({'success': True, 'message': '已断开连接'})


@qmt_bp.route('/snapshot', methods=['GET'])
def get_snapshot():
    """获取市场快照"""
    provider = get_qmt_provider()
    
    codes = request.args.get('codes', '')
    if codes:
        stock_codes = [c.strip() for c in codes.split(',')]
    else:
        stock_codes = ['600519.SH', '000001.SZ', '000002.SZ']
    
    snapshot = provider.get_market_snapshot(stock_codes)
    return jsonify({'success': True, 'data': snapshot})


@qmt_bp.route('/tick', methods=['GET'])
def get_tick():
    """获取Tick数据"""
    provider = get_qmt_provider()
    
    codes = request.args.get('codes', '')
    if codes:
        stock_codes = [c.strip() for c in codes.split(',')]
    else:
        stock_codes = ['600519.SH']
    
    tick_data = provider.get_tick(stock_codes)
    return jsonify({'success': True, 'data': tick_data})


@qmt_bp.route('/kline/<ts_code>', methods=['GET'])
def get_kline(ts_code):
    """获取K线数据"""
    provider = get_qmt_provider()
    
    period = request.args.get('period', '1d')
    count = request.args.get('count', 100, type=int)
    
    kline = provider.get_kline(ts_code, period=period, count=count)
    if kline:
        return jsonify({'success': True, 'data': kline})
    else:
        return jsonify({'success': False, 'message': '获取K线数据失败'}), 500


@qmt_bp.route('/subscribe', methods=['POST'])
def subscribe():
    """订阅实时行情"""
    provider = get_qmt_provider()
    
    data = request.get_json()
    stock_codes = data.get('codes', [])
    period = data.get('period', 'tick')
    
    if not stock_codes:
        return jsonify({'success': False, 'message': '请提供股票代码'}), 400
    
    if period == 'tick':
        seq = provider.subscribe_tick(stock_codes, _default_callback)
        return jsonify({'success': seq > 0, 'subscription_id': seq})
    else:
        results = provider.subscribe_kline(stock_codes, period=period)
        return jsonify({'success': True, 'data': results})


def _default_callback(datas):
    """默认回调函数"""
    logger.info(f"收到行情数据: {len(datas)} 只股票")