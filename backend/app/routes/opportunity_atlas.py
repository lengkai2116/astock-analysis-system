"""
机汇地图 Treemap API 路由
提供 market / opportunity / value 三种模式的 Treemap 数据

数据来源（严格遵循四层架构红线）：
- 快照优先：ECM.treemap_snapshot（日终预提取，305号§2.2）
- 回退路径：ECM.daily_cache + ECM.daily_basic_cache + ECM.opportunity_tags_cache
- 实时行情：ECM.as_market_snapshot（仅 market 模式覆盖 pct_change）
"""
import logging
from datetime import datetime, timedelta

import pandas as pd
from flask import Blueprint, jsonify, request

from app.utils.error_handlers import handle_exceptions

logger = logging.getLogger(__name__)

opportunity_bp = Blueprint('opportunity_atlas', __name__, url_prefix='/api/v3/opportunity-atlas')

_data_manager = None
_tm_cache = None


def get_data_manager():
    global _data_manager
    if _data_manager is None:
        from app.data import DataManager
        _data_manager = DataManager()
    return _data_manager


def _get_memory_cache():
    """延迟获取 TieredMemoryCache 实例"""
    global _tm_cache
    if _tm_cache is None:
        from app.data.memory_cache import TieredMemoryCache
        _tm_cache = TieredMemoryCache()
    return _tm_cache


def _treemap_cache_key(mode: str, tags: str = '', industry: str = '') -> str:
    """生成 treemap 缓存键（305号§2.3.2）"""
    if mode == 'market':
        return 'treemap:market'
    return f'treemap:{mode}:{tags}:{industry}'


def _merge_snapshot_with_realtime(items: list[dict], realtime_list: list[dict]) -> list[dict]:
    """用盘中实时快照覆盖快照中的 pct_change（market 模式）"""
    rt_map = {}
    for s in realtime_list:
        p = float(s.get('price', 0))
        if 0.01 < p < 10000:
            rt_map[s['ts_code']] = s
    for item in items:
        rt = rt_map.get(item['ts_code'])
        if rt:
            item['pct_change'] = round(float(rt['change_pct']), 2)
            item['price'] = round(float(rt['price']), 2)
            item['snapshot'] = True
    return items


def _collect_ts_codes(mode: str, dm, ts_codes_param: str, tags_param: str) -> list[str]:
    """根据 mode 和参数收集目标 ts_codes（与旧版保持一致）"""
    if mode == 'market':
        if ts_codes_param:
            return [c.strip() for c in ts_codes_param.split(',') if c.strip()]
        return dm.get_all_ts_codes()

    tag_filters = {}
    if tags_param:
        for pair in tags_param.split(','):
            if ':' in pair:
                k, v = pair.split(':', 1)
                k, v = k.strip(), v.strip()
                if k and v:
                    tag_filters.setdefault(k, []).append(v)

    if mode == 'opportunity':
        if not tag_filters:
            return []
        results = dm.cache.query_tags(tag_filters)
        return [r['ts_code'] for r in results]

    if mode == 'value':
        if not tag_filters:
            tag_filters = {'valuation_level': [
                'extreme_low', 'low', 'fair', 'high', 'extreme_high',
            ]}
        results = dm.cache.query_tags(tag_filters)
        return [r['ts_code'] for r in results]

    return []


def _build_stock_item(ts_code: str, name_map: dict, industry_map: dict,
                      daily_batch: dict, basic_batch: dict,
                      tags_batch: dict,
                      snapshot: dict = None) -> dict:
    """旧路径兜底用的逐项组装函数（快照表不可用时回退）"""
    name = name_map.get(ts_code, '')
    if snapshot is not None and snapshot.get('price'):
        price = float(snapshot.get('price', 0))
        prev_close = float(snapshot.get('prev_close', 0))
        pct_change = round((price - prev_close) / prev_close * 100, 2) if prev_close else 0
    else:
        df_d = daily_batch.get(ts_code)
        if df_d is not None and not df_d.empty:
            last = df_d.iloc[-1]
            price = float(last['close']) if pd.notna(last.get('close')) else 0
            pct_change = float(last['pct_chg']) if pd.notna(last.get('pct_chg')) else 0
        else:
            price = 0
            pct_change = 0
    df_b = basic_batch.get(ts_code)
    if df_b is not None and not df_b.empty:
        last_b = df_b.iloc[-1]
        market_cap = float(last_b['total_mv']) if pd.notna(last_b.get('total_mv')) else 0
    else:
        market_cap = 0
    tags = tags_batch.get(ts_code, {})
    sig_str = 0
    if tags.get('signal_strength') is not None:
        try:
            sig_str = float(tags['signal_strength'])
        except (ValueError, TypeError):
            pass
    val_dev = None
    if tags.get('valuation_deviation') is not None:
        try:
            val_dev = float(tags['valuation_deviation'])
        except (ValueError, TypeError):
            pass
    _promoted_keys = {
        'signal_strength', 'valuation_level', 'main_force_phase',
        'sentiment_phase', 'sector_heat', 'fina_health',
        'opportunity_type', 'opportunity_label', 'valuation_deviation',
    }
    return {
        'ts_code': ts_code, 'name': name,
        'price': round(price, 2), 'pct_change': round(pct_change, 2),
        'market_cap': round(market_cap, 2),
        'signal_strength': sig_str,
        'valuation_level': tags.get('valuation_level'),
        'main_force_phase': tags.get('main_force_phase'),
        'sentiment_phase': tags.get('sentiment_phase'),
        'sector_heat': tags.get('sector_heat'),
        'fina_health': tags.get('fina_health'),
        'opportunity_type': tags.get('opportunity_type'),
        'opportunity_label': tags.get('opportunity_label'),
        'val_deviation': val_dev,
        'tags': {k: v for k, v in tags.items() if k not in _promoted_keys},
        'snapshot': snapshot is not None,
    }


def _build_response(mode: str, items: list[dict]) -> dict:
    """按行业分组组装最终响应"""
    groups_dict: dict[str, list] = {}
    for item in items:
        # industry 归一化：NaN/None/非字符串 → '其他'（否则 sorted 混合类型抛 TypeError）
        raw_industry = item.get('industry')
        if isinstance(raw_industry, str) and raw_industry.strip() and raw_industry != 'nan':
            industry = raw_industry.strip()
        else:
            industry = '其他'
        groups_dict.setdefault(industry, []).append(item)
    groups_list = [
        {'industry': k, 'stocks': v}
        for k, v in sorted(groups_dict.items())
    ]
    tagged = sum(1 for it in items if it.get('signal_strength', 0) > 0)
    coverage = tagged / len(items) if items else 0.0
    # 313号：潜力快照日期（前端时间标注：潜力基于快照、时机截至实时）
    # 合规整改：经 DataManager 网关（红线5），原直连 get_ecm().conn 属违规
    _snap_date = None
    try:
        _snap_date = get_data_manager().get_snapshot_max_date()
    except Exception:
        pass
    # 327阶段3：数据交易日透出（快照 trade_date，区分构建时间 vs 数据时间）
    _data_date = None
    try:
        _data_date = get_data_manager().get_snapshot_data_date()
    except Exception:
        pass
    return {
        'code': 0,
        'data': {
            'mode': mode,
            'groups': groups_list,
            'signal_strength_fallback': coverage < 0.8,
            'data_status': 'pre_compute' if coverage < 0.8 else 'complete',
            'generated_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            'snapshot_date': _snap_date,   # 313号：潜力快照日期（时间标注）
            'data_date': _data_date,       # 327阶段3：数据交易日（前端标注"数据截至"）
        },
    }


def _fallback_legacy_treemap(mode: str, ts_codes: list[str], dm) -> list[dict]:
    """回退路径：从 daily_cache/daily_basic_cache/tags 逐表读取（旧路径）"""
    meta_batch = dm.get_stock_meta_batch(ts_codes)
    name_map = {tc: m['name'] for tc, m in meta_batch.items()}
    industry_map = {tc: m['industry'] for tc, m in meta_batch.items()}
    daily_batch = dm.cache.get_cached_daily_batch(ts_codes)
    basic_batch = dm.cache.get_cached_daily_basic_batch(ts_codes)
    snapshot_dict: dict[str, dict] = {}
    if mode == 'market':
        try:
            for s in dm.cache.get_all_market_snapshots(ts_codes):
                p = float(s.get('price', 0))
                if 0.01 < p < 10000:
                    snapshot_dict[s['ts_code']] = s
        except Exception:
            pass
    tags_batch = dm.cache.get_tags_batch(ts_codes)
    items = []
    for ts_code in ts_codes:
        item = _build_stock_item(ts_code, name_map, industry_map,
                                 daily_batch, basic_batch, tags_batch,
                                 snapshot=snapshot_dict.get(ts_code))
        item['industry'] = industry_map.get(ts_code, '')
        items.append(item)
    return items


@opportunity_bp.route('/treemap', methods=['GET'])
@handle_exceptions
def treemap():
    """Treemap 数据端点（305号§3.1：快照表优先 + 缓存）"""
    mode = request.args.get('mode', 'market')
    ts_codes_param = request.args.get('ts_codes', '')
    tags_param = request.args.get('tags', '')
    industry_param = request.args.get('industry', '')

    cache_key = _treemap_cache_key(mode, tags_param, industry_param)
    tm_cache = _get_memory_cache()

    # ── 0. 内存缓存命中（非 market 模式可安全使用缓存） ──
    if mode != 'market':
        cached = tm_cache.get(cache_key, level='treemap')
        if cached is not None:
            return jsonify(cached)

    dm = get_data_manager()

    # ── 1. 确定 ts_codes ──
    ts_codes = _collect_ts_codes(mode, dm, ts_codes_param, tags_param)

    # ── 2. 行业过滤 ──
    if industry_param and ts_codes:
        ts_codes = dm.get_ts_codes_by_industry(industry_param, ts_codes)

    if not ts_codes:
        resp = jsonify({'code': 0, 'data': {
            'mode': mode, 'groups': [],
            'signal_strength_fallback': True, 'data_status': 'no_data',
            'generated_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        }})
        return resp

    # ── 3. 尝试从快照表读取（305号§2.2） ──
    items: list[dict] = []
    try:
        items = dm.get_treemap_snapshot_items(ts_codes)
        if not items:
            raise ValueError('snapshot empty')

        # market 模式：用实时快照覆盖 pct_change
        if mode == 'market':
            try:
                rt_list = dm.cache.get_all_market_snapshots(ts_codes)
                items = _merge_snapshot_with_realtime(items, rt_list)
            except Exception:
                pass

        # 补充行业信息（快照表有 industry 字段）
        result = _build_response(mode, items)

    except Exception as _snap_exc:
        logger.warning(f'treemap_snapshot 不可用，回退到逐表查询: {type(_snap_exc).__name__}: {_snap_exc}')
        items = _fallback_legacy_treemap(mode, ts_codes, dm)
        result = _build_response(mode, items)

    # ── 4. 写入缓存（非 market 模式） ──
    if mode != 'market':
        tm_cache.set(cache_key, result, level='treemap')

    # ── 5. HTTP 响应缓存头（305号§2.4） ──
    resp = jsonify(result)
    if mode in ('opportunity', 'value'):
        resp.headers['Cache-Control'] = 'public, max-age=3600'
    else:
        resp.headers['Cache-Control'] = 'no-cache'
    return resp


@opportunity_bp.route('/diagnose', methods=['GET'])
@handle_exceptions
def diagnose_stock():
    """L4 个股诊断（共识投票引擎）

    Query Parameters:
        ts_code (str): 股票代码

    Returns:
        L4 诊断 JSON（294号§十格式）
    """
    ts_code = request.args.get('ts_code', '').strip().upper()
    if not ts_code:
        return jsonify({'success': False, 'error': 'ts_code 不能为空'}), 400

    if '.' not in ts_code:
        return jsonify({'success': False, 'error': 'ts_code 格式错误，需要包含 .SH 或 .SZ'}), 400

    # 延迟导入 L4CrossValidator（避免循环导入）
    from app.opportunity_atlas.cross_validate import L4CrossValidator
    from app.data import DataManager

    # 2026-08-06 合规整改：经 DataManager 网关读取标签（红线5），
    # 原直连 ecm.conn.execute 读 opportunity_tags_cache 属违规
    dm = DataManager()
    tags = dm.cache.get_tags(ts_code)

    if not tags:
        return jsonify({'success': False, 'error': f'股票 {ts_code} 暂无标签数据'}), 404

    validator = L4CrossValidator()
    result = validator.diagnose(ts_code, tags)

    return jsonify({'success': True, 'data': result})
