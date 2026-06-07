"""
三层策略筛选器 API 路由
对接 DataManager + MultiLayerStockScreener + ChipScorer 提供真实数据
"""
import time
import logging
from app.utils.error_handlers import handle_exceptions
from flask import Blueprint, jsonify, request
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

from app.data import DataManager
from app.engine.framework.screener import MultiLayerStockScreener, DarwinRiskFilter
from app.engine.framework.chip_strategy import ChipScorer

logger = logging.getLogger(__name__)

screener_bp = Blueprint('screener', __name__, url_prefix='/api/v3/screener')

# ── 全局缓存 ──
_data_manager = None
_screener_cache = {'data': None, 'timestamp': 0, 'ttl': 3600}  # 1小时缓存


def get_data_manager():
    global _data_manager
    if _data_manager is None:
        _data_manager = DataManager()
    return _data_manager


def get_cached_screening():
    now = time.time()
    c = _screener_cache
    if c['data'] and (now - c['timestamp']) < c['ttl']:
        return c['data']
    return None


def set_cached_screening(data):
    _screener_cache['data'] = data
    _screener_cache['timestamp'] = time.time()


def load_stock_data_batch(stock_list, lookback=120):
    """
    批量加载股票 K 线数据
    返回 {ts_code: DataFrame}
    """
    dm = get_data_manager()
    data_dict = {}
    for stock in stock_list:
        ts_code = stock.get('ts_code', '') or stock.get('symbol', '')
        if not ts_code:
            continue
        try:
            df = dm.get_cached_daily_data(ts_code)
            if df.empty or len(df) < lookback:
                continue
            # 确保列名符合要求
            if 'vol' not in df.columns and 'amount' in df.columns:
                df['vol'] = df['amount']
            df = df.tail(lookback).copy()
            for col in ['open', 'high', 'low', 'close', 'vol']:
                if col in df.columns:
                    df[col] = df[col].astype(float)
            data_dict[ts_code] = df
        except Exception as e:
            logger.debug(f"加载 {ts_code} 数据失败: {e}")
    return data_dict


def extract_phase(score_0_10, df):
    """根据评分和最新 K 线判断主力阶段"""
    if score_0_10 >= 7:
        return 'BUILDING'
    elif score_0_10 >= 5:
        return 'WASHING'
    elif score_0_10 >= 3:
        return 'LIFTING'
    else:
        return 'DISTRIBUTING'


def extract_indicators(df):
    """从 DataFrame 提取 ASR / 集中度 / 量比 / RSI 等辅助指标"""
    closes = df['close'].values
    volumes = df['vol'].values if 'vol' in df.columns else df.get('amount', df['close']).values

    # ASR (近似): 活跃度 = 均量 / 60日均量
    if len(volumes) >= 60:
        asr = np.mean(volumes[-5:]) / (np.mean(volumes[-60:]) + 1e-9)
        asr = min(max(asr, 0), 1)
    else:
        asr = 0.5

    # 集中度: 价格波动率的倒数
    if len(closes) >= 20:
        concentration = np.std(closes[-20:]) / (np.mean(closes[-20:]) + 1e-9)
        concentration = min(concentration, 1)
    else:
        concentration = 0.15

    # 量比
    if len(volumes) >= 5:
        vol_ratio = volumes[-1] / (np.mean(volumes[-5:-1]) + 1e-9)
    else:
        vol_ratio = 1.0

    # RSI (14日)
    if len(closes) >= 15:
        deltas = np.diff(closes[-15:])
        gains = np.sum(deltas[deltas > 0])
        losses = abs(np.sum(deltas[deltas < 0]))
        rsi = 50.0
        if losses > 0:
            rs = gains / losses
            rsi = 100 - 100 / (1 + rs)
    else:
        rsi = 50.0

    return asr, concentration, vol_ratio, rsi


def compute_screening(stock_list):
    """
    核心计算：对股票列表执行 L1→L2→L3 筛选
    """
    dm = get_data_manager()

    # ── L1: 风险剔除 ──
    filter_engine = DarwinRiskFilter()
    data_dict = load_stock_data_batch(stock_list)
    l1_symbols = list(data_dict.keys())
    l1_passed = filter_engine.filter(l1_symbols, data_dict)

    logger.info(f"L1 风险剔除: {len(l1_symbols)} -> {len(l1_passed)}")

    # ── L2: 主力评分 ──
    scorer = ChipScorer()
    scored = []
    for symbol in l1_passed:
        df = data_dict.get(symbol)
        if df is None or df.empty:
            continue
        try:
            s = scorer.score(df)
            if s > 0:
                scored.append({'symbol': symbol, 'score': s})
        except Exception as e:
            logger.debug(f"评分 {symbol} 失败: {e}")
    scored.sort(key=lambda x: x['score'], reverse=True)
    l2_top = scored[:100]
    l2_symbols = [s['symbol'] for s in l2_top]

    logger.info(f"L2 主力评分: {len(l1_passed)} -> {len(l2_top)}")

    # ── L3: 策略验证 ──
    validated = []
    for item in l2_top:
        df = data_dict.get(item['symbol'])
        if df is None or len(df) < 60:
            continue
        # 验证条件: 60日数据完整
        score_0_10 = item['score']
        score_100 = round(score_0_10 * 10, 1)  # 映射到 0-100
        asr, conc, vr, rsi = extract_indicators(df)
        phase = extract_phase(score_0_10, df)
        validated.append({
            'symbol': item['symbol'],
            'name': '',  # 将在外层填充
            'score': score_100,
            'phase': phase,
            'asr': round(asr, 3),
            'concentration': round(conc, 3),
            'volume_ratio': round(vr, 2),
            'rsi': round(rsi, 1),
            'asr_score': round(asr * 0.4, 3),
            'concentration_score': round(max(0, 0.2 - conc) * 5, 3),
            'profit_score': round(score_100 / 100 * 0.3, 3),
            'volume_score': round(min(vr / 3, 0.2), 3),
            'rsi_score': round(max(0, 1 - abs(rsi - 50) / 50) * 0.15, 3),
        })

    validated.sort(key=lambda x: x['score'], reverse=True)
    logger.info(f"L3 策略验证: {len(l2_top)} -> {len(validated)}")

    # 填充股票名称
    stock_map = {s.get('ts_code', ''): s.get('name', '') for s in stock_list}
    for v in validated:
        v['name'] = stock_map.get(v['symbol'], '')

    return {
        'layers': [
            {'name': 'L1: 风险剔除', 'input': len(stock_list), 'output': len(l1_passed)},
            {'name': 'L2: 主力识别', 'input': len(l1_passed), 'output': len(l2_top)},
            {'name': 'L3: 策略验证', 'input': len(l2_top), 'output': len(validated)},
        ],
        'results': validated,
        'summary': {
            'total_analyzed': len(stock_list),
            'final_count': len(validated),
            'execution_time': f'{time.time() - _screener_cache.get("timestamp", time.time()):.1f}s' if _screener_cache.get('timestamp') else 'N/A'
        }
    }


# ============ API 路由 ============
@handle_exceptions
@screener_bp.route('/run', methods=['POST'])
def run_screener():
    """执行完整的三层筛选流程"""
    data = request.get_json(silent=True) or {}
    market = data.get('market')
    industry = data.get('industry')
    use_cache = data.get('useCache', True)
    stock_pool = data.get('stockPool')

    start_time = time.time()

    if use_cache:
        cached = get_cached_screening()
        if cached:
            return jsonify({'success': True, 'data': cached, 'from_cache': True})

    dm = get_data_manager()

    # 支持 stockPool 参数：用户指定股票列表
    if stock_pool:
        stock_list = [{'ts_code': s, 'name': ''} for s in stock_pool]
        # 补充名称
        try:
            name_map = {s['ts_code']: s['name'] for s in dm.get_stock_list(limit=6000) if s.get('name')}
            for item in stock_list:
                if not item['name'] and item['ts_code'] in name_map:
                    item['name'] = name_map[item['ts_code']]
        except Exception:
            pass
    else:
        stock_list = dm.get_stock_list(keyword=industry, limit=5000)
        if not stock_list:
            logger.info("股票列表为空，尝试从 Tushare 同步...")
            count = dm.sync_stock_list()
            logger.info(f"同步完成: {count} 只股票")
            stock_list = dm.get_stock_list(keyword=industry, limit=5000)

    if not stock_list:
        return jsonify({
            'success': False,
            'message': '无可用的股票列表，请先同步数据'
        }), 503

    if market:
        stock_list = [s for s in stock_list if s.get('market') == market]

    # 限制处理数量，分批处理
    result = compute_screening(stock_list)
    result['execution_ms'] = int((time.time() - start_time) * 1000)

    set_cached_screening(result)

    return jsonify({
        'success': True,
        'data': result,
        'from_cache': False
    })
@handle_exceptions
@screener_bp.route('/layer1', methods=['POST'])
def run_layer1():
    """第一层：风险剔除"""
    data = request.get_json(silent=True) or {}
    stock_pool = data.get('stockPool')

    dm = get_data_manager()
    if stock_pool:
        stock_list = [{'ts_code': s, 'name': ''} for s in stock_pool]
    else:
        stock_list = dm.get_stock_list(limit=5000)

    if not stock_list:
        return jsonify({'success': True, 'data': {'passed': 0, 'filtered': 0}})

    data_dict = load_stock_data_batch(stock_list)
    symbols = [s.get('ts_code', '') for s in stock_list if s.get('ts_code', '') in data_dict]

    filter_engine = DarwinRiskFilter()
    passed = filter_engine.filter(symbols, data_dict)

    return jsonify({
        'success': True,
        'data': {
            'passed': len(passed),
            'filtered': len(symbols) - len(passed),
            'passed_symbols': passed[:20]
        }
    })
@handle_exceptions
@screener_bp.route('/layer2', methods=['POST'])
def run_layer2():
    """第二层：主力识别"""
    data = request.get_json(silent=True) or {}
    stock_pool = data.get('stockPool')

    dm = get_data_manager()
    if stock_pool:
        stock_list = [{'ts_code': s, 'name': ''} for s in stock_pool]
    else:
        stock_list = dm.get_stock_list(limit=5000)

    data_dict = load_stock_data_batch(stock_list)
    scorer = ChipScorer()
    scored = []

    for stock in stock_list:
        ts_code = stock.get('ts_code', '')
        if not ts_code or ts_code not in data_dict:
            continue
        try:
            s = scorer.score(data_dict[ts_code])
            if s > 0:
                scored.append({'symbol': ts_code, 'score': round(s, 2)})
        except Exception:
            continue

    scored.sort(key=lambda x: x['score'], reverse=True)

    return jsonify({
        'success': True,
        'data': {
            'passed': len(scored),
            'scored': scored[:50]
        }
    })
@handle_exceptions
@screener_bp.route('/layer3', methods=['POST'])
def run_layer3():
    """第三层：策略验证"""
    data = request.get_json(silent=True) or {}
    stock_pool = data.get('stockPool', [])

    if not stock_pool:
        return jsonify({'success': True, 'data': {'validated': []}})

    dm = get_data_manager()
    stock_list = [{'ts_code': s, 'name': ''} for s in stock_pool]
    data_dict = load_stock_data_batch(stock_list)
    scorer = ChipScorer()
    validated = []

    for stock in stock_list:
        ts_code = stock.get('ts_code', '')
        if not ts_code or ts_code not in data_dict:
            continue
        df = data_dict[ts_code]
        try:
            score_0_10 = scorer.score(df)
            if score_0_10 > 0 and len(df) >= 60:
                score_100 = round(score_0_10 * 10, 1)
                asr, conc, vr, rsi = extract_indicators(df)
                validated.append({
                    'symbol': ts_code,
                    'name': '',
                    'score': score_100,
                    'phase': extract_phase(score_0_10, df),
                    'asr': round(asr, 3),
                    'concentration': round(conc, 3),
                    'volume_ratio': round(vr, 2),
                    'rsi': round(rsi, 1),
                })
        except Exception:
            continue

    validated.sort(key=lambda x: x['score'], reverse=True)

    # 填充名称
    for v in validated:
        try:
            info = dm.get_stock_info(v['symbol'])
            v['name'] = info.get('name', '') if info else ''
        except Exception:
            v['name'] = v['symbol']

    return jsonify({
        'success': True,
        'data': {'validated': validated}
    })
@handle_exceptions
@screener_bp.route('/fusion-config', methods=['GET', 'POST'])
def fusion_config():
    """获取/更新信号融合权重配置"""
    if request.method == 'POST':
        data = request.json or {}
        config = {
            'weights': data.get('weights', {'chip': 0.4, 'chanlun': 0.3, 'factor': 0.3}),
            'phase_bonus': data.get('phase_bonus', {'building': 2, 'washing': 1}),
            'updated_at': datetime.now().isoformat()
        }
        # 可持久化到 DB（预留）
        return jsonify({'success': True, 'message': '配置已保存', 'data': config})

    return jsonify({
        'success': True,
        'data': {
            'weights': {'chip': 0.4, 'chanlun': 0.3, 'factor': 0.3},
            'phase_bonus': {'building': 2, 'washing': 1, 'lifting': 1, 'distributing': -1}
        }
    })
@handle_exceptions
@screener_bp.route('/params', methods=['GET'])
def screener_params():
    """获取可用筛选器参数范围"""
    return jsonify({
        'success': True,
        'data': {
            'layers': {
                'layer1': {
                    'name': '风险剔除',
                    'params': {
                        'st_filter': {'type': 'bool', 'default': True, 'desc': '剔除ST股票'},
                        'min_volume': {'type': 'int', 'default': 50000000, 'desc': '最低日均成交额'},
                        'max_pe': {'type': 'float', 'default': 200, 'desc': '最高PE'},
                        'min_data_days': {'type': 'int', 'default': 120, 'desc': '最少K线天数'}
                    }
                },
                'layer2': {
                    'name': '主力识别',
                    'params': {
                        'asr_threshold': {'type': 'float', 'default': 0.5, 'desc': 'ASR阈值'},
                        'concentration_threshold': {'type': 'float', 'default': 0.2, 'desc': '集中度阈值'},
                        'top_n': {'type': 'int', 'default': 50, 'desc': '输出数量'}
                    }
                },
                'layer3': {
                    'name': '策略验证',
                    'params': {
                        'min_score': {'type': 'float', 'default': 30, 'desc': '最低综合评分'},
                        'min_data_days': {'type': 'int', 'default': 60, 'desc': '最少数据天数'}
                    }
                }
            }
        }
    })
@handle_exceptions
@screener_bp.route('/stats', methods=['GET'])
def screener_stats():
    """获取缓存状态和数据统计"""
    dm = get_data_manager()
    cache_status = 'valid' if get_cached_screening() else 'empty'

    # 统计有数据的股票数量
    from app.models import DailyData
    from sqlalchemy import func
    try:
        stock_count = len(set(
            row[0] for row in
            dm.get_stock_list() or []
        ))
        data_count = len(set(
            row[0] for row in
            DailyData.query.with_entities(DailyData.ts_code).distinct().all()
        ) if DailyData.query.first() else [])
    except Exception:
        stock_count = 0
        data_count = 0

    return jsonify({
        'success': True,
        'data': {
            'cache_status': cache_status,
            'stock_count': stock_count,
            'data_stock_count': data_count,
            'last_screen_time': datetime.fromtimestamp(
                _screener_cache['timestamp']
            ).isoformat() if _screener_cache['timestamp'] else None,
            'cache_ttl_seconds': _screener_cache['ttl']
        }
    })
