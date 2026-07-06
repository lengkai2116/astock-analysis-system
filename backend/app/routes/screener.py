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
from app.engine.framework.chip_strategy import ChipScorer
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

    数据不足 lookback 天时触发按需补采（DataManager.sync_daily_data），
    然后重试读取一次。

    新股过滤：若已有部分数据但最早交易日距今不足 lookback 天
    （即刚上市，不可能有足够数据），跳过补采。

    返回 {ts_code: DataFrame}
    """
    from datetime import date, timedelta
    import pandas as pd

    dm = get_data_manager()
    data_dict = {}
    replenished = 0
    skipped_new = 0
    today = date.today()

    for stock in stock_list:
        ts_code = stock.get('ts_code', '') or stock.get('symbol', '')
        if not ts_code:
            continue
        try:
            df = dm.get_cached_daily_data(ts_code)
            if df.empty or len(df) < lookback:
                # 新股判断：已有部分数据但最早交易日距今不足 lookback 天 → 跳过
                if not df.empty and 'trade_date' in df.columns:
                    first_date = df['trade_date'].min()
                    if hasattr(first_date, 'strftime'):
                        first_dt = first_date
                    else:
                        first_dt = pd.Timestamp(str(first_date))
                    days_since_listing = (pd.Timestamp(today) - first_dt).days
                    if days_since_listing < lookback:
                        skipped_new += 1
                        if len(df) < lookback:
                            continue  # 新股数据不足但无可补，跳过

                # 数据不足 → 触发按需补采
                try:
                    cnt = dm.sync_daily_data(ts_code, use_cache=False)
                    if cnt > 0:
                        replenished += 1
                        logger.info(f"按需补采 {ts_code}: {cnt} 条")
                        # 重试读取
                        df = dm.get_cached_daily_data(ts_code)
                except Exception as e:
                    logger.debug(f"按需补采 {ts_code} 失败: {e}")

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

    if replenished > 0 or skipped_new > 0:
        logger.info(f"按需补采: 补齐 {replenished} 只, 跳过 {skipped_new} 只新股")
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


def compute_screening(stock_list):
    """
    核心计算：对股票列表执行 L1→L2→L3 筛选
    L3 使用真实策略（缠论+量价）评分
    """

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

    logger.info(f"L2 主力评分: {len(l1_passed)} -> {len(l2_top)}")

    # ── L3: 策略验证（缠论+量价共振评分，与L2筹码评分正交独立） ──
    #     per-stock 失败已在 screen_l3_candidates 内部处理（跳过单只）
    #     此处 catch 的是全局性失败（import错误、数据层不可用等），绝不降级到纯数据检查
    try:
        from app.engine.framework.screener_strategy_integration import screen_l3_candidates
        validated = screen_l3_candidates(l2_top, data_dict)
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
    """执行完整的三层筛选流程"""
    data = request.get_json(silent=True) or {}
    market = data.get('market')
    industry = data.get('industry')
    use_cache = data.get('useCache', True)
    stock_pool = data.get('stock_pool') or data.get('stockPool')

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
    """第二层：主力识别"""
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

    # 统计有数据的股票数量（复用原有逻辑）
    try:
        stock_count = len(set(
            row[0] for row in
            dm.get_stock_list() or []
        ))
        from app.models import Stock
        data_count = Stock.query.count()
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
    """
    filter_type = request.args.get('type', 'all')

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
            strategies.append({
                "id": f"vibe_{s.id}",
                "name": s.name,
                "type": "system" if s.is_system else "user",
                "description": s.description or "",
                "code_summary": s.catCN or s.name,
                "default_checked": s.is_system or False,
                "created_at": s.created_at.strftime('%Y-%m-%d') if s.created_at else "2026-06-12",
                "source": "strategy_templates_v2",
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
        import json
        import sqlite3

        from app.routes.factors import PRESET_COMBOS, _ensure_combo_db, get_db_path

        presets = list(PRESET_COMBOS) if filter_type in ('all', 'sys') else []
        user_combos = []
        if filter_type in ('all', 'user'):
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

        all_combos = presets + user_combos
        return jsonify({'success': True, 'data': all_combos})
    except Exception as e:
        logger.warning(f"获取因子组合失败: {e}")
        return jsonify({'success': True, 'data': []})
