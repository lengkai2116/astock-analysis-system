"""
三层策略筛选器 API 路由
对接 DataManager + MultiLayerStockScreener + ChipScorer 提供真实数据
"""
import logging
import time
from datetime import datetime

import numpy as np
from flask import Blueprint, jsonify, request

from app.data import DataManager
from app.engine.framework.chip_strategy import ChipScorer, MainForceFilter
from app.engine.framework.screener import DarwinRiskFilter
from app.utils.error_handlers import handle_exceptions

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

    使用 ECM 全量预加载（1 次 SQL 读取全部日线到内存），
    然后在内存中按 ts_code 分组。

    新股过滤 + 按需补采流程不变。

    返回 {ts_code: DataFrame}
    """
    from datetime import date

    import pandas as pd

    dm = get_data_manager()
    ts_codes = []
    for stock in stock_list:
        ts_code = stock.get('ts_code', '') or stock.get('symbol', '')
        if ts_code:
            ts_codes.append(ts_code)

    # 批量获取全量日线（1次SQL → 内存 DataFrame，比逐只查询快 5-10x）
    t0 = time.time()
    # 预加载全量数据到内存（日线 + 基础数据 + 资金流向）
    dm.cache.preload_all()
    logger.info(f"全量数据预加载: {time.time()-t0:.1f}s")
    data_dict = dm.get_cached_daily_batch(ts_codes)

    # 数据足量检查 + 新股过滤 + 补采
    today = date.today()
    replenished = 0
    skipped_new = 0
    result = {}

    for ts_code in ts_codes:
        df = data_dict.get(ts_code, pd.DataFrame())
        if not df.empty and len(df) >= lookback:
            # 数据足够，直接使用
            result[ts_code] = df.tail(lookback).copy()
            continue

        # 新股判断
        if not df.empty and 'trade_date' in df.columns:
            first_date = df['trade_date'].min()
            if hasattr(first_date, 'strftime'):
                first_dt = first_date
            else:
                first_dt = pd.Timestamp(str(first_date))
            days_since_listing = (pd.Timestamp(today) - first_dt).days
            if days_since_listing < lookback:
                skipped_new += 1
                continue

        # 数据不足 → 触发按需补采
        # 数据不足 → 写 sync_requests → 跳过（daemon 异步补采）
        try:
            dm.request_data('per_stock', ts_code)
        except Exception:
            pass
        continue

        if df.empty or len(df) < lookback:
            continue

        result[ts_code] = df.tail(lookback).copy()

    # 标准化列
    for ts_code, df in result.items():
        if 'vol' not in df.columns and 'amount' in df.columns:
            df['vol'] = df['amount']
        for col in ['open', 'high', 'low', 'close', 'vol']:
            if col in df.columns:
                df[col] = df[col].astype(float)

    if replenished > 0 or skipped_new > 0:
        logger.info(f"按需补采: 补齐 {replenished} 只, 跳过 {skipped_new} 只新股")
    return result


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


def _get_grade_info(score):
    """按214号§2.1评分等级映射"""
    if score >= 85:
        return 'S', '🔥 强烈推荐'
    elif score >= 75:
        return 'A', '✅ 推荐'
    elif score >= 65:
        return 'B', '👀 关注'
    elif score >= 50:
        return 'C', '⚠️ 谨慎'
    else:
        return 'D', '❌ 回避'


def compute_screening(stock_list, weights=None, combinations=None, vibe_strategies=None):
    """
    核心计算：对股票列表执行 L1→L2→L3 筛选
    L3 使用真实策略（缠论+量价+因子组合）评分

    Args:
        stock_list: 股票列表
        weights: 信号权重 {chanlun, vp, factor, vibe} 0.0-1.0
        combinations: 选中的因子组合 ID 列表
        vibe_strategies: 选中的 Vibe 策略 ID 列表
    """

    # ── L1: 风险剔除 ──
    filter_engine = DarwinRiskFilter()
    data_dict = load_stock_data_batch(stock_list)
    l1_symbols = list(data_dict.keys())
    l1_passed = filter_engine.filter(l1_symbols, data_dict)

    logger.info(f"L1 风险剔除: {len(l1_symbols)} -> {len(l1_passed)}")

    # ── L2: 主力关注度筛选（核心层） ──
    # 使用 MainForceFilter：资金流向 + 价量特征 + 筹码集中度
    # 阈值 ≥6 分视为有主力关注，若无达标则取评分最高的 20 只兜底
    main_force_filter = MainForceFilter(min_score=6.4, top_k=20)
    # 构建带 symbol 的列表供 MainForceFilter 使用
    l1_items = [{'ts_code': s, 'name': ''} for s in l1_passed]
    # 补充名称
    name_map = {s.get('ts_code', ''): s.get('name', '') for s in stock_list}
    for it in l1_items:
        it['name'] = name_map.get(it['ts_code'], it['name'])

    l2_passed = main_force_filter.filter(l1_items, data_dict)

    logger.info(f"L2 主力关注度筛选: {len(l1_passed)} -> {len(l2_passed)} 只")
    # 携带 phase 信息到后续层
    l2_top = [{'symbol': r['symbol'], 'score': r['mf_score'],
               'phase': r['phase']} for r in l2_passed]

    # ── L3: 策略验证（缠论+量价共振评分，与L2筹码评分正交独立） ──
    #     确保候选股有分钟数据用于多级别缠论分析
    try:
        from app.data.minute_backfill import ensure_minute_data
        l2_symbols = [r['symbol'] for r in l2_top]
        n = ensure_minute_data(l2_symbols, days_back=20)
        if n > 0:
            logger.info(f"L3 分钟数据快速补足: {n}/{len(l2_symbols)} 只")
    except Exception as e:
        logger.warning(f"L3 分钟数据准备异常（非阻塞）: {e}")
    
    try:
        from app.engine.framework.screener_strategy_integration import screen_l3_candidates
        # 构建 L2 phase 映射供 L3 阶段感知评分使用
        l2_phase_map = {r['symbol']: r.get('phase', 'unknown') for r in l2_passed}
        validated = screen_l3_candidates(
            l2_top, data_dict,
            weights=weights,
            combinations=combinations,
            vibe_strategies=vibe_strategies,
            l2_phase_map=l2_phase_map,
        )
    except Exception as e:
        logger.error(f"L3 策略引擎全局异常: {e}")
        # 安全降级：只保留有有效 strategy_detail 的股票（如果有的话）
        # 如果 screen_l3_candidates 部分成功，这里不会走到
        validated = []
        # 尝试逐只调用（绕过全局 import/init 失败）
        for item in l2_top:
            try:
                df = data_dict.get(item['symbol'])
                if df is None or len(df) < 60:
                    continue
                vp_result = None
                cl_result = None
                try:
                    from app.engine.framework.volume_price_strategy import VolumePriceStrategy
                    vp = VolumePriceStrategy()
                    vp_result = vp.analyze(df)
                except Exception:
                    pass
                try:
                    from app.engine.framework.chanlun_strategy import analyze_chanlun
                    cl_result = analyze_chanlun(df)
                except Exception:
                    pass
                if vp_result or cl_result:
                    from app.engine.framework.screener_strategy_integration import (
                        _compute_chanlun_score,
                        _compute_combined_score,
                        _compute_volume_price_score,
                        _score_to_grade,
                    )
                    vp_score, vp_sig, vp_dir = (
                        _compute_volume_price_score(vp_result)
                        if vp_result else (0.0, '', 'neutral')
                    )
                    cl_score, cl_sig, cl_dir = (
                        _compute_chanlun_score(cl_result)
                        if cl_result else (0.0, '', 'neutral')
                    )
                    combined = _compute_combined_score(cl_score, vp_score, cl_dir, vp_dir)
                    validated.append({
                        'symbol': item['symbol'], 'name': '',
                        'score': round(combined * 10, 1),
                        'grade': _score_to_grade(combined),
                        'close': round(float(df['close'].iloc[-1]), 2),
                        'pct_chg': round(float(df['pct_chg'].iloc[-1]), 2) if 'pct_chg' in df.columns else None,
                        'industry': '',
                        'strategy_detail': {
                            'chanlun': {'direction': cl_dir, 'score': cl_score,
                                        'signal': cl_sig},
                            'volume_price': {'direction': vp_dir, 'score': vp_score,
                                             'signal': vp_sig},
                        },
                    })
            except Exception:
                continue
        logger.warning(f"L3 降级模式: 逐只策略调用完成, {len(validated)} 只通过")
        validated.sort(key=lambda x: x['score'], reverse=True)

    logger.info(f"L3 策略验证: {len(l2_top)} -> {len(validated)}")

    # 填充股票名称 + 行业（从 Stock ORM 一次查询）
    stock_map = {s.get('ts_code', ''): s.get('name', '') for s in stock_list}
    industry_map = {}
    try:
        from app.models import Stock
        symbols = [v['symbol'] for v in validated]
        stocks = Stock.query.filter(Stock.ts_code.in_(symbols)).all()
        industry_map = {s.ts_code: s.industry for s in stocks if s.industry}
    except Exception:
        # 从 stock_list 回退
        for s in stock_list:
            ind = s.get('industry', '')
            if ind:
                industry_map[s.get('ts_code', '')] = ind
    for v in validated:
        if not v.get('name'):
            v['name'] = stock_map.get(v['symbol'], '')
        if not v.get('industry') and v['symbol'] in industry_map:
            v['industry'] = industry_map[v['symbol']]
        # 确保 pct_chg 字段存在（主路径已有，fallback 路径可能缺失）
        if 'pct_chg' not in v or v['pct_chg'] is None:
            df = data_dict.get(v['symbol'])
            if df is not None and 'pct_chg' in df.columns and not df.empty:
                v['pct_chg'] = round(float(df['pct_chg'].iloc[-1]), 2)
            else:
                v['pct_chg'] = None

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
            'execution_time': (
                f'{time.time() - _screener_cache["timestamp"]:.1f}s'
                if _screener_cache.get('timestamp') else 'N/A'
            )
        }
    }


# ============ API 路由 ============
@handle_exceptions
@screener_bp.route('/run', methods=['POST'])
def run_screener():
    """执行完整的三层筛选流程，支持权重/组合/Vibe参数"""
    data = request.get_json(silent=True) or {}
    market = data.get('market')
    industry = data.get('industry')
    use_cache = data.get('useCache', True)
    stock_pool = data.get('stock_pool') or data.get('stockPool')

    # ── 读取策略选择与权重配置 ──
    weights = data.get('weights')  # {chanlun: 0.35, vp: 0.30, factor: 0.25, vibe: 0.10}
    combinations = data.get('combinations')  # ['p1', 'p2', ...]
    vibe_strategies = data.get('vibe_strategies')  # ['vibe_001', ...]

    # 校验格式
    if not isinstance(weights, dict):
        weights = None
    if not isinstance(combinations, list) or not combinations:
        combinations = None
    if not isinstance(vibe_strategies, list) or not vibe_strategies:
        vibe_strategies = None

    start_time = time.time()

    if use_cache:
        cached = get_cached_screening()
        if cached:
            return jsonify({'success': True, 'data': cached, 'from_cache': True})

    dm = get_data_manager()

    # 支持 stock_pool 参数：用户指定股票列表
    if stock_pool:
        if isinstance(stock_pool, list) and len(stock_pool) > 0 and isinstance(stock_pool[0], str):
            stock_list = [{'ts_code': s, 'name': ''} for s in stock_pool]
        else:
            stock_list = stock_pool
        # 补充名称
        try:
            stock_list_data = dm.get_stock_list(limit=6000) or []
            name_map = {s['ts_code']: s['name'] for s in stock_list_data if s.get('name')}
            for item in stock_list:
                if not item['name'] and item['ts_code'] in name_map:
                    item['name'] = name_map[item['ts_code']]
        except Exception:
            pass
    else:
        stock_list = dm.get_stock_list(keyword=industry, limit=5000)

    if not stock_list:
        # 数据缺失，写 sync_requests 通知 daemon 异步补采
        try:
            dm.request_data('full_stock_list')
        except Exception:
            pass
        return jsonify({
            'success': False,
            'message': '股票列表数据未就绪，数据采集进程正在同步，请稍后重试'
        }), 503

    if market:
        stock_list = [s for s in stock_list if s.get('market') == market]

    # 限制处理数量，分批处理
    result = compute_screening(
        stock_list,
        weights=weights,
        combinations=combinations,
        vibe_strategies=vibe_strategies,
    )
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
    stock_pool = data.get('stock_pool') or data.get('stockPool')

    dm = get_data_manager()
    if stock_pool:
        if isinstance(stock_pool[0], str):
            stock_list = [{'ts_code': s, 'name': ''} for s in stock_pool]
        else:
            stock_list = stock_pool
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
    """第二层：主力关注度识别"""
    data = request.get_json(silent=True) or {}
    stock_pool = data.get('stock_pool') or data.get('stockPool')

    dm = get_data_manager()
    if stock_pool:
        if isinstance(stock_pool[0], str):
            stock_list = [{'ts_code': s, 'name': ''} for s in stock_pool]
        else:
            stock_list = stock_pool
    else:
        stock_list = dm.get_stock_list(limit=5000)

    data_dict = load_stock_data_batch(stock_list)
    mf_filter = MainForceFilter(min_score=6.0, top_k=20)
    scored = mf_filter.filter(stock_list, data_dict)

    return jsonify({
        'success': True,
        'data': {
            'passed': len(scored),
            'scored': [{'symbol': s['symbol'], 'score': s['mf_score']} for s in scored[:50]]
        }
    })
@handle_exceptions
@screener_bp.route('/layer3', methods=['POST'])
def run_layer3():
    """第三层：策略验证"""
    data = request.get_json(silent=True) or {}
    stock_pool = data.get('candidates') or data.get('stock_pool') or data.get('stockPool', [])

    if not stock_pool:
        return jsonify({'success': True, 'data': {'validated': []}})

    dm = get_data_manager()
    stock_list = [{'ts_code': s, 'name': ''} for s in stock_pool]
    data_dict = load_stock_data_batch(stock_list)

    # L2 评分（作为筹码评分输入）
    scorer = ChipScorer()
    scored = []
    for stock in stock_list:
        ts_code = stock.get('ts_code', '')
        if not ts_code or ts_code not in data_dict:
            continue
        df = data_dict[ts_code]
        try:
            s = scorer.score(df)
            if s > 0:
                scored.append({'symbol': ts_code, 'score': s, 'name': ''})
        except Exception:
            continue
    scored.sort(key=lambda x: x['score'], reverse=True)

    # L3 策略验证（缠论+量价，与筹码正交）
    try:
        from app.engine.framework.screener_strategy_integration import screen_l3_candidates
        validated = screen_l3_candidates(scored, data_dict)
    except Exception as e:
        logger.error(f"L3 策略引擎异常: {e}")
        validated = []
        for item in scored:
            try:
                df = data_dict.get(item['symbol'])
                if df is None or len(df) < 60:
                    continue
                vp_r = cl_r = None
                try:
                    from app.engine.framework.volume_price_strategy import VolumePriceStrategy
                    vp_r = VolumePriceStrategy().analyze(df)
                except Exception:
                    pass
                try:
                    from app.engine.framework.chanlun_strategy import analyze_chanlun
                    cl_r = analyze_chanlun(df)
                except Exception:
                    pass
                if vp_r or cl_r:
                    from app.engine.framework.screener_strategy_integration import (
                        _compute_chanlun_score,
                        _compute_combined_score,
                        _compute_volume_price_score,
                        _score_to_grade,
                    )
                    vs, _, vd = _compute_volume_price_score(vp_r) if vp_r else (0, '', 'neutral')
                    cs, _, cd = _compute_chanlun_score(cl_r) if cl_r else (0, '', 'neutral')
                    combined = _compute_combined_score(cs, vs, cd, vd)
                    validated.append({
                        'symbol': item['symbol'], 'name': '', 'score': round(combined * 10, 1),
                        'grade': _score_to_grade(combined),
                    })
            except Exception:
                continue

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
                        'min_volume': {'type': 'int', 'default': 50000000,
                                        'desc': '最低日均成交额'},
                        'max_pe': {'type': 'float', 'default': 200, 'desc': '最高PE'},
                        'min_data_days': {'type': 'int', 'default': 120, 'desc': '最少K线天数'}
                    }
                },
                'layer2': {
                    'name': '主力识别',
                    'params': {
                        'asr_threshold': {'type': 'float', 'default': 0.5, 'desc': 'ASR阈值'},
                        'concentration_threshold': {'type': 'float', 'default': 0.2,
                                                      'desc': '集中度阈值'},
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
    """获取缓存状态和数据统计，含L3引擎健康度"""
    dm = get_data_manager()
    cache_status = 'valid' if get_cached_screening() else 'empty'

    # 统计有数据的股票数量
    try:
        from app.models import Stock
        data_count = Stock.query.count()
        stock_count = data_count  # 从 Stock 表直接获取
    except Exception:
        stock_count = 0
        data_count = 0

    # L3 引擎健康度报告
    from app.engine.framework.screener_strategy_integration import _L3_ENGINE_HEALTH
    health = _L3_ENGINE_HEALTH.copy()

    return jsonify({
        'success': True,
        'data': {
            'cache_status': cache_status,
            'stock_count': stock_count,
            'data_stock_count': data_count,
            'last_screen_time': datetime.fromtimestamp(
                _screener_cache['timestamp']
            ).isoformat() if _screener_cache['timestamp'] else None,
            'cache_ttl_seconds': _screener_cache['ttl'],
            'l3_engine_health': health,
        }
    })


@handle_exceptions
@screener_bp.route('/strategies/vibe', methods=['GET'])
def get_vibe_strategies():
    """
    获取 Vibe Coding 策略列表（214号 §2.7）
    优先从 strategy_templates_v2 数据库动态读取，回退到默认策略

    Vibe 策略应排除已内置在 L1/L2/L3 管道中的策略：
      L1: DarwinRisk, MultiLevelRiskControl
      L2: MainForceTracking, Chip
      L3: Chanlun, VolumePrice
    """
    filter_type = request.args.get('type', 'all')

    # 内置策略排除名单（已在选股系统管道中固定使用的策略）
    EXCLUDED_NAMES = {
        'DarwinRiskStrategy', 'MultiLevelRiskControlStrategy',
        'MainForceTrackingStrategy', 'ChipStrategy',
        'ChanlunStrategy', 'VolumePriceStrategy',
    }

    strategies = []

    # Phase 1: 从 strategy_templates_v2 动态读取
    try:
        from app.models.strategy import StrategyTemplateV2
        query = StrategyTemplateV2.query.filter_by(is_active=True, vibe=True)
        if filter_type == 'system':
            query = query.filter_by(is_system=True)
        elif filter_type == 'user':
            query = query.filter_by(is_system=False)
        db_strategies = query.order_by(StrategyTemplateV2.usage_count.desc()).all()

        for s in db_strategies:
            if s.name in EXCLUDED_NAMES:
                continue  # 跳过管道内置策略
            strategies.append({
                "id": f"vibe_{s.id}",
                "name": s.nameCN or s.name,
                "type": "system" if s.is_system else "user",
                "description": s.description or "",
                "code_summary": s.catCN or s.name,
                "default_checked": s.is_system or False,
                "created_at": s.created_at.strftime('%Y-%m-%d') if s.created_at else "2026-06-12",
                "source": "strategy_templates_v2",
                "ready": getattr(s, 'ready', True),
            })
    except Exception as e:
        logger.warning(f"从 strategy_templates_v2 读取失败，使用默认策略: {e}")

    # Phase 2: 无数据库数据时使用默认策略
    if not strategies:
        strategies = [
            {
                "id": "vibe_001",
                "name": "业绩超预期+MACD金叉",
                "type": "system",
                "description": "选出业绩预告超预期且MACD金叉的股票",
                "code_summary": "MACD金叉+业绩预增",
                "default_checked": True,
                "created_at": "2026-06-12",
                "source": "vibe_coding"
            },
            {
                "id": "vibe_002",
                "name": "涨停突破回调确认",
                "type": "system",
                "description": "涨停后缩量回调不破涨停底，次日放量上攻",
                "code_summary": "涨停突破+缩量回调+放量确认",
                "default_checked": False,
                "created_at": "2026-06-12",
                "source": "vibe_coding"
            },
            {
                "id": "vibe_003",
                "name": "我的短线策略",
                "type": "user",
                "description": "自建短线策略",
                "code_summary": "多因子短线评分",
                "default_checked": True,
                "created_at": "2026-06-15",
                "source": "vibe_coding"
            }
        ]

    if filter_type == 'system':
        filtered = [s for s in strategies if s['type'] == 'system']
    elif filter_type == 'user':
        filtered = [s for s in strategies if s['type'] == 'user']
    else:
        filtered = strategies

    return jsonify({
        'success': True,
        'data': {
            'strategies': filtered,
            'total_count': len(filtered),
            'synced_from': 'strategy-templates'
        }
    })


@handle_exceptions
@screener_bp.route('/factor-combinations', methods=['GET'])
def get_screener_factor_combinations():
    """
    获取选股可用的因子组合列表（214号 §2.6 标准路径 /api/v3/screener/factor-combinations）
    直接复用 factors 模块的查询逻辑，返回与前端的 /api/factors/combinations 一致
    """
    filter_type = request.args.get('type', 'all')
    try:
        from app.routes.factors import PRESET_COMBOS

        presets = list(PRESET_COMBOS) if filter_type in ('all', 'sys') else []
        # 用户自定义组合暂通过 sqlite3 直读（260 §11 V4 已知例外 — 待抽象到 DataManager 层）
        # 该路径不涉及 Tushare 直调，仅读取本地数据库文件
        user_combos = []
        if filter_type in ('all', 'user'):
            try:
                import json
                import sqlite3

                from app.routes.factors import _ensure_combo_db, get_db_path

                db_path = get_db_path()
                _ensure_combo_db()
                with sqlite3.connect(db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """SELECT id, name, description, factors, src, detail, created_at
                           FROM factor_combinations WHERE type = 'user'
                           ORDER BY created_at DESC"""
                    )
                    for row in cursor.fetchall():
                        try:
                            factors = json.loads(row[3]) if row[3] else []
                        except Exception:
                            factors = []
                        mapped = []
                        for f in factors:
                            if isinstance(f, dict):
                                mapped.append({"n": f.get("n", f.get("name", "")), "w": f.get("w", 0)})
                            else:
                                mapped.append({"n": str(f), "w": 0})
                        user_combos.append({
                            "id": f"u{row[0]}", "name": row[1], "type": "user",
                            "desc": row[2] or "", "factors": mapped, "detail": row[5] or None,
                        })
            except Exception:
                logger.warning("读取用户自定义因子组合失败，跳过")
                user_combos = []

        all_combos = presets + user_combos
        return jsonify({'success': True, 'data': all_combos})
    except Exception as e:
        logger.warning(f"获取因子组合失败: {e}")
        return jsonify({'success': True, 'data': []})


# ── W7: POST /api/v3/screener/evaluate-batch — 批量策略评分（自选监控用）──
@screener_bp.route('/evaluate-batch', methods=['POST'])
@handle_exceptions
def evaluate_batch():
    """
    对自选股批量运行 L3 策略评分（缠论/量价/因子）
    专供自选监控「🔄策略刷新」按钮使用

    请求:
    {
        "ts_codes": ["000762.SZ", "000001.SZ"],
        "strategies": ["chanlun", "volume_price", "factor"],
        "weights": {"chanlun": 0.4, "volume_price": 0.4, "factor": 0.2}
    }

    响应:
    {
        "success": true,
        "data": {
            "stocks": {
                "000762.SZ": {
                    "composite_score": 6.5,
                    "chanlun_score": 5.0,
                    "volume_price_score": 7.0,
                    "factor_score": 6.0,
                    "signal": "watch",
                    "buy_signal": null,
                    "sell_signal": null,
                    "tech_pattern": null
                },
                ...
            },
            "evaluated": {"000762.SZ": true, ...}
        }
    }
    """
    req = request.get_json() or {}
    ts_codes = req.get('ts_codes', [])
    if not ts_codes:
        return jsonify({'success': False, 'error': 'ts_codes 不能为空'}), 400
    ts_codes = list(dict.fromkeys(ts_codes))[:50]  # 去重+限制50只

    weights = req.get('weights', {'chanlun': 0.4, 'vp': 0.4, 'factor': 0.2})
    need_cl = weights.get('chanlun', 0) > 0
    need_vp = weights.get('volume_price', 0) > 0 or weights.get('vp', 0) > 0
    need_fx = weights.get('factor', 0) > 0

    dm = get_data_manager()
    dm.cache.preload_all()
    data_dict = dm.get_cached_daily_batch(ts_codes)

    stocks = {}
    evaluated = {}
    for ts_code in ts_codes:
        result = {
            'composite_score': None,
            'chanlun_score': None,
            'volume_price_score': None,
            'factor_score': None,
            'signal': None,
            'buy_signal': None,
            'sell_signal': None,
            'tech_pattern': None,
        }
        df = data_dict.get(ts_code) if data_dict else None
        if df is None or df.empty:
            stocks[ts_code] = result
            evaluated[ts_code] = False
            continue

        scores = {'chanlun': 0.0, 'vp': 0.0, 'factor': 0.0}
        signals = []
        signal_dirs = []

        # ── 缠论评分 ──
        if need_cl:
            try:
                from app.engine.framework.chanlun_strategy import analyze_chanlun
                from app.engine.framework.screener_strategy_integration import (
                    _compute_chanlun_score,
                )
                cl_r = analyze_chanlun(df)
                if cl_r and cl_r.get('success'):
                    s, sig, d = _compute_chanlun_score(cl_r)
                    scores['chanlun'] = s
                    result['chanlun_score'] = round(min(s * 10, 100), 0)
                    if sig and sig != '无明确信号':
                        signals.append(sig)
                        signal_dirs.append(d)
            except Exception as e:
                logger.debug(f"缠论评分失败({ts_code}): {e}")

        # ── 量价评分 ──
        if need_vp:
            try:
                from app.engine.framework.screener_strategy_integration import (
                    _compute_volume_price_score,
                )
                from app.engine.framework.volume_price_strategy import VolumePriceStrategy
                vp = VolumePriceStrategy()
                vp_r = vp.analyze(df)
                if vp_r and vp_r.get('success'):
                    s, sig, d = _compute_volume_price_score(vp_r)
                    scores['vp'] = s
                    result['volume_price_score'] = round(min(s * 10, 100), 0)
                    if sig and sig != 'N/A':
                        signals.append(sig)
                        signal_dirs.append(d)
            except Exception as e:
                logger.debug(f"量价评分失败({ts_code}): {e}")

        # ── 因子评分 ──
        if need_fx:
            try:
                from app.engine.framework.screener_strategy_integration import _compute_factor_score
                fx_score = _compute_factor_score(df, symbol=ts_code, dm=dm)
                scores['factor'] = float(fx_score) if fx_score else 0.0
                result['factor_score'] = round(min(scores['factor'] * 10, 100), 0)
            except Exception as e:
                logger.debug(f"因子评分失败({ts_code}): {e}")

        # ── 综合评分（加权）──
        w_chanlun = weights.get('chanlun', 0)
        w_vp = weights.get('volume_price', weights.get('vp', 0))
        w_factor = weights.get('factor', 0)
        total_w = w_chanlun + w_vp + w_factor
        if total_w > 0:
            composite = (
                scores['chanlun'] * w_chanlun +
                scores['vp'] * w_vp +
                scores['factor'] * w_factor
            ) / total_w
            result['composite_score'] = round(composite, 1)
            # 前端的 signalTagLabel 使用 0-100 分制，乘 10 对齐
            result['composite_score'] = round(min(composite * 10, 100), 0)
        else:
            result['composite_score'] = 0.0

        # ── 信号标签（0-100 分制）──
        cs = result['composite_score']
        if cs is not None:
            if cs >= 80:
                result['signal'] = 'strong_buy'
            elif cs >= 60:
                result['signal'] = 'buy'
            elif cs >= 40:
                result['signal'] = 'watch'
            else:
                result['signal'] = 'neutral'
            # 策略具体信号
            if signals:
                result['buy_signal'] = '; '.join([s for s in signals if '买' in s]) or None
                result['sell_signal'] = '; '.join([s for s in signals if '卖' in s]) or None

        stocks[ts_code] = result
        evaluated[ts_code] = True

    return jsonify({
        'success': True,
        'code': 0,
        'data': {'stocks': stocks, 'evaluated': evaluated}
    })
