"""
个股策略分析路由 (215号 Phase 1)

提供策略分析流水线和交叉验证端点。
底层复用现有的 SignalComputationService / UPFEngine / StatusOutputService 等组件。
"""

import logging
from flask import Blueprint, request, jsonify
from typing import Dict, List, Optional

from app.services.signal_computation_service import SignalComputationService
from app.services.status_output_service import StatusOutputService
from app.engine.framework.conflict_arbiter import ConflictArbiter
from app.engine.framework.unified_practical_framework import UPFEngine
from app.services.kronos_forecaster import KronosForecaster

logger = logging.getLogger(__name__)

strategy_analyze_bp = Blueprint('strategy_analyze', __name__)


# ──────────────────────────────────────────────
# 全局缓存：KronosForecaster 单例（进程级）
# ──────────────────────────────────────────────
_kronos_forecaster: Optional[KronosForecaster] = None


def _get_kronos_forecaster() -> KronosForecaster:
    global _kronos_forecaster
    if _kronos_forecaster is None:
        _kronos_forecaster = KronosForecaster()
    return _kronos_forecaster


# ──────────────────────────────────────────────
# 信号 → 五维展示格式 映射辅助
# ──────────────────────────────────────────────

def _find_signal(signals: List[Dict], keyword: str) -> Optional[Dict]:
    """从信号列表中按策略名关键词查找"""
    for s in signals:
        if keyword in s.get('strategy_name', ''):
            return s
    return None


def _safe_str(val, default='未知') -> str:
    return str(val) if val is not None else default


def _build_chanlun_dimension(sig: Optional[Dict]) -> Dict:
    """从缠论信号构建卡1格式"""
    if not sig:
        return {'direction': 'neutral', 'status_text': '无缠论信号'}
    sr = sig.get('status_recognition', {})
    trend = sr.get('trend', {})
    levels = sr.get('support_resistance', {})
    # 从evidence获取描述性文本，优于signal_label
    evidence = sig.get('evidence', [])
    status_text = '; '.join(evidence[:2]) if evidence else sig.get('signal_label', '')
    return {
        'direction': sig.get('signal', 'neutral'),
        'buy_point': sig.get('signal_label', ''),
        'level': trend.get('stage', '30min'),
        'zhongshu_range': [levels.get('support', 0), levels.get('resistance', 0)],
        'zhongshu_position': trend.get('direction', ''),
        'trend_type': trend.get('stage', ''),
        'ma_alignment': trend.get('strength', ''),
        'critical_levels': {'support': levels.get('support', 0), 'resistance': levels.get('resistance', 0)},
        'status_text': status_text,
    }


def _build_volume_price_dimension(sig: Optional[Dict]) -> Dict:
    """从量价信号构建卡2格式"""
    if not sig:
        return {'direction': 'neutral', 'status_text': '无量价信号'}
    sr = sig.get('status_recognition', {})
    trend = sr.get('trend', {})
    levels = sr.get('support_resistance', {})
    evidence = sig.get('evidence', [])
    status_text = '; '.join(evidence[:2]) if evidence else sig.get('signal_label', '')
    return {
        'direction': sig.get('signal', 'neutral'),
        'phase': trend.get('stage', 'RANGING'),
        'phase_label': trend.get('direction', '横盘'),
        'volume_price_relation': sr.get('volume', {}).get('state', ''),
        'active_pattern': sr.get('volume', {}).get('structure', ''),
        'ma_alignment': trend.get('strength', ''),
        'support': levels.get('support', 0),
        'resistance': levels.get('resistance', 0),
        'trend_strength': min(1.0, abs(sig.get('confidence', 0.5))),
        'status_text': status_text,
    }


def _build_chip_dimension(sig: Optional[Dict]) -> Dict:
    """从筹码信号构建卡3格式"""
    if not sig:
        return {'direction': 'neutral', 'status_text': '无筹码信号'}
    sr = sig.get('status_recognition', {})
    evidence = sig.get('evidence', [])
    status_text = '; '.join(evidence[:2]) if evidence else sig.get('signal_label', '')
    return {
        'direction': sig.get('signal', 'neutral'),
        'profit_ratio': sr.get('support_resistance', {}).get('support', 42.0),
        'avg_cost': sr.get('support_resistance', {}).get('resistance', 12.50),
        'concentration': sr.get('risk_level', '中等'),
        'trend': sr.get('volume', {}).get('state', ''),
        'main_force_direction': sig.get('signal_label', ''),
        'large_order_net': sr.get('momentum', {}).get('score', 0),
        'lock_up_ratio': sr.get('risk_level') == 'HIGH' and 55.0 or 35.0,
        'status_text': status_text,
    }


def _build_emotion_dimension(
    sig: Optional[Dict],
    signal_context: Optional[Dict] = None
) -> Dict:
    """从BOCIASI信号构建卡4格式"""
    sr = sig.get('status_recognition', {}) if sig else {}
    # 从Stock表获取行业板块信息（比daily_basic_cache更准确）
    sector_name = '未知'
    sector_pct = 0
    if (signal_context or {}).get('sector_name'):
        sector_name = signal_context['sector_name']
        sector_pct = (signal_context or {}).get('sector_pct', 0)
    else:
        try:
            from app.models import Stock
            stk = Stock.query.get(signal_context.get('ts_code', '')) if signal_context else None
            if stk and stk.industry:
                sector_name = stk.industry
        except Exception:
            pass
    evidence = sig.get('evidence', []) if sig else []
    status_text = '; '.join(evidence[:2]) if evidence else (sig.get('signal_label', '行业板块情况正常') if sig else '行业板块情况正常')
    return {
        'direction': sig.get('signal', 'neutral') if sig else 'neutral',
        'sector': sector_name,
        'sector_pct': sector_pct,
        'market_temp': sr.get('volume', {}).get('state', '中性'),
        'valuation': '合理' if sr.get('risk_level') == 'MEDIUM' else '偏低',
        'risk_level': sr.get('risk_level', '中等'),
        'status_text': status_text,
    }


def _build_factor_dimension(signals: List[Dict]) -> Dict:
    """从所有信号的相互关系构建卡5（冲突检测）"""
    conflicted_pairs = []
    driving = None
    for i, sa in enumerate(signals):
        for sb in signals[i+1:]:
            da = sa.get('signal', 'neutral')
            db = sb.get('signal', 'neutral')
            if da != db and da != 'neutral' and db != 'neutral':
                conflicted_pairs.append({
                    'pair': f"{sa.get('strategy_name','?')}-vs-{sb.get('strategy_name','?')}",
                    'relation': '矛盾',
                    'detail': f"{da} vs {db}",
                })

    # 找置信度最高的信号作为驱动力
    if signals:
        driving = max(signals, key=lambda s: s.get('confidence', 0))
        driving_name = driving.get('strategy_name', '')

    # 判断冲突类型
    if not conflicted_pairs:
        conflict_type = '一致'
    elif len(conflicted_pairs) == 1:
        conflict_type = '轻微分歧'
    else:
        conflict_type = '严重分歧'

    return {
        'conflict_type': conflict_type,
        'conflict_items': conflicted_pairs,
        'driving_factor': driving_name if driving else 'unknown',
        'trend': driving.get('signal', '中性') if driving else '中性',
    }


# ──────────────────────────────────────────────
# E12: 策略分析流水线
# ──────────────────────────────────────────────

@strategy_analyze_bp.route('/api/v3/strategy/analyze', methods=['POST'])
def strategy_analyze():
    """
    策略分析流水线：
    1. 调用 SignalComputationService 计算5策略信号
    2. 可选执行 Kronos 推理增强
    3. 组装为五维展现格式
    """
    data = request.get_json() or {}
    ts_code = (data.get('ts_code') or '').strip()
    if not ts_code:
        return jsonify({'code': -1, 'message': 'ts_code必填'}), 400

    kronos_enabled = bool(data.get('kronos_enabled', False))

    try:
        # Step 1: 计算5策略信号
        scs = SignalComputationService()
        signals = scs.compute_for_stock(ts_code)
        data_availability = scs.last_data_availability  # 扩展数据可用性状态

        # Step 2: 构建信号上下文（包含板块信息等）
        signal_context = _build_signal_context(ts_code)

        # Step 3: 提取各维度信号
        chanlun_sig = _find_signal(signals, '缠论')
        vp_sig = _find_signal(signals, '量价')
        chip_sig = _find_signal(signals, '筹码')
        bociasi_sig = _find_signal(signals, 'BOCIASI')
        factor_sig = _find_signal(signals, '因子')

        # Step 4: 组装五维数据
        dimensions = {
            'chanlun': _build_chanlun_dimension(chanlun_sig),
            'volume_price': _build_volume_price_dimension(vp_sig),
            'chip': _build_chip_dimension(chip_sig),
            'emotion': _build_emotion_dimension(bociasi_sig, signal_context),
            'factor': _build_factor_dimension(signals),
        }

        # Step 5: 可选 Kronos 推理
        kronos_result = None
        if kronos_enabled:
            kronos_result = _compute_kronos(ts_code)

        response = {
            'code': 0,
            'data': {
                'ts_code': ts_code,
                'trade_date': _today_str(),
                'dimensions': dimensions,
                'data_availability': data_availability,
            }
        }

        # Kronos 字段：仅 kronos_enabled=true 且推理成功时存在
        if kronos_result is not None:
            response['data']['kronos'] = kronos_result

        return jsonify(response)

    except Exception as e:
        logger.error(f"策略分析失败 ({ts_code}): {e}", exc_info=True)
        return jsonify({
            'code': -1,
            'message': f'策略分析异常: {str(e)}',
            'data': {'ts_code': ts_code, 'dimensions': _empty_dimensions()}
        }), 500


# ──────────────────────────────────────────────
# E13: 交叉验证 + 维度关系
# ──────────────────────────────────────────────

@strategy_analyze_bp.route('/api/v3/strategy/status-aggregate', methods=['POST'])
def strategy_status_aggregate():
    """
    交叉验证 + 维度关系聚合：
    使用 StatusOutputService.aggregate_v2 生成验证链和维度关系
    """
    data = request.get_json() or {}
    ts_code = (data.get('ts_code') or '').strip()
    if not ts_code:
        return jsonify({'code': -1, 'message': 'ts_code必填'}), 400

    # 可选接收已计算的维度（用于复用E12的结果）
    dimensions = data.get('dimensions')

    try:
        # Step 1: 获取策略信号
        scs = SignalComputationService()
        signals = scs.compute_for_stock(ts_code)

        # Step 2: 获取市场状态
        market_state = _detect_market_state(signals)

        # Step 3: 运行 StatusOutputService 聚合
        sos = StatusOutputService()
        aggregated = sos.aggregate_v2(signals, market_state)

        # Step 4: 构建维度关系
        if dimensions:
            dimension_relations = _build_dimension_relations(dimensions)
        else:
            dimension_relations = _build_dimension_relations_from_signals(signals)

        # Step 5: 从聚合结果提取验证链
        chains = aggregated.get('verification_chains', aggregated.get('chains', []))
        if not chains:
            chains = _build_default_chains(signals)

        pass_count = sum(1 for c in chains if c.get('passed', False))

        # 构建 uncertainties
        uncertainties = _build_uncertainties(signals)

        return jsonify({
            'code': 0,
            'data': {
                'ts_code': ts_code,
                'verification_chains': chains,
                'pass_rate': f"{pass_count}/{len(chains)}",
                'dimension_relations': dimension_relations,
                'uncertainties': uncertainties,
            }
        })

    except Exception as e:
        logger.error(f"交叉验证失败 ({ts_code}): {e}", exc_info=True)
        return jsonify({
            'code': -1,
            'message': f'交叉验证异常: {str(e)}',
            'data': {'verification_chains': [], 'dimension_relations': []}
        }), 500


# ──────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────

def _compute_kronos(ts_code: str) -> Optional[Dict]:
    """执行Kronos推理（带缓存）"""
    from app.data.memory_cache import TieredMemoryCache

    cache = TieredMemoryCache()
    cache_key = f'kronos:{ts_code}'
    cached = cache.get(cache_key, 'analysis')
    if cached is not None:
        logger.debug(f"Kronos: cache hit {cache_key}")
        return cached

    forecaster = _get_kronos_forecaster()
    if not forecaster.check_available():
        logger.debug("Kronos: torch未安装，跳过")
        return None

    # 从数据管理器取K线数据
    try:
        from app.data import DataManager
        dm = DataManager()
        df = dm.get_cached_daily_data(ts_code)
        if df is None or df.empty:
            return None

        result = forecaster.analyze(df)
        if result is not None:
            cache.set(cache_key, result, 'analysis')
        return result
    except Exception as e:
        logger.debug(f"Kronos: 数据获取/推理失败 ({ts_code}): {e}")
        return None


def _build_signal_context(ts_code: str) -> Dict:
    """构建信号上下文（板块信息等）"""
    ctx = {'ts_code': ts_code}
    # 从 Stock 表查询行业（最准确来源）
    try:
        from app.data import DataManager
        dm = DataManager()
        stk = dm.get_stock_info(ts_code)
        if stk and stk.get('industry'):
            ctx['sector_name'] = stk['industry']
    except Exception:
        pass
    # 从 daily_basic 获取板块涨跌幅
    try:
        from app.data import DataManager
        dm = DataManager()
        df_basic = dm.get_cached_daily_basic(ts_code)
        if df_basic is not None and not df_basic.empty:
            latest = df_basic.iloc[-1]
            if 'sector_name' not in ctx:
                ctx['sector_name'] = str(latest.get('industry', '未知'))
            ctx['sector_pct'] = float(latest.get('pct_chg', 0))
    except Exception:
        pass
    return ctx


def _detect_market_state(signals: List[Dict]) -> str:
    """从信号中推断市场状态"""
    for s in signals:
        sr = s.get('status_recognition', {})
        state = sr.get('state', '')
        if state:
            return state
    return 'UNKNOWN'


def _build_dimension_relations(dimensions: Dict) -> List[Dict]:
    """从五维数据构建维度间关系"""
    relations = []
    dim_pairs = [
        ('chanlun', 'volume_price'),
        ('chanlun', 'chip'),
        ('volume_price', 'chip'),
        ('emotion', 'overall'),
    ]
    for a, b in dim_pairs:
        da = dimensions.get(a, {})
        if b == 'overall':
            # emotion vs overall：看emotion和其他维度是否一致
            others = [dimensions.get(k, {}) for k in dimensions if k != 'emotion']
            other_dirs = [o.get('direction') for o in others if o.get('direction') != 'neutral']
            consistent = da.get('direction') in other_dirs if other_dirs else True
            status = 'consistent' if consistent else 'deviation'
            detail = (
                f"{da.get('status_text','')[:20]} vs "
                f"{'多数维度看多' if other_dirs.count('bullish') > other_dirs.count('bearish') else '多数维度看空'}"
                if not consistent else f"{da.get('direction','')}方向与多数维度一致"
            )
        else:
            db = dimensions.get(b, {})
            da_dir = da.get('direction')
            db_dir = db.get('direction')
            if da_dir == db_dir:
                status = 'consistent'
                detail = f"{da.get('status_text','')[:20]} + {db.get('status_text','')[:20]}"
            elif da_dir == 'neutral' or db_dir == 'neutral':
                status = 'mismatch'
                detail = f"{a}中性，{b}={db_dir}"
            else:
                status = 'conflict'
                detail = f"{a}={da_dir}, {b}={db_dir}"
        relations.append({
            'from': a, 'to': b, 'status': status,
            'detail': detail if not detail.startswith('无信号') else f"{a}与{b}数据不足",
        })
    return relations


def _build_dimension_relations_from_signals(signals: List[Dict]) -> List[Dict]:
    """从信号列表构建维度关系"""
    relations = []
    names = ['缠论', '量价', '筹码', 'BOCIASI', '因子']
    for i, na in enumerate(names):
        sa = _find_signal(signals, na)
        for nb in names[i+1:]:
            sb = _find_signal(signals, nb)
            if sa and sb:
                da = sa.get('signal', 'neutral')
                db = sb.get('signal', 'neutral')
                status = 'consistent' if da == db else ('conflict' if da != 'neutral' and db != 'neutral' else 'mismatch')
                relations.append({
                    'from': na, 'to': nb, 'status': status,
                    'detail': f"{da} vs {db}" if status != 'consistent' else f"方向一致({da})",
                })
    return relations


def _build_default_chains(signals: List[Dict]) -> List[Dict]:
    """构建默认的四条验证链"""
    chains = [
        {'id': 'money', 'name': '主力行为验证', 'passed': True, 'evidence': '资金流向与筹码信号', 'confidence_multiplier': 1.0, 'conflict_detail': ''},
        {'id': 'structure', 'name': '结构位置验证', 'passed': True, 'evidence': '缠论结构信号', 'confidence_multiplier': 1.0, 'conflict_detail': ''},
        {'id': 'environment', 'name': '外部环境验证', 'passed': True, 'evidence': 'BOCIASI情绪信号', 'confidence_multiplier': 1.0, 'conflict_detail': ''},
        {'id': 'resonance', 'name': '共振验证', 'passed': True, 'evidence': '多维度综合分析', 'confidence_multiplier': 1.0, 'conflict_detail': ''},
    ]
    # 用实际信号填充
    for s in signals:
        evidence = s.get('evidence', [])
        ev_str = '; '.join(evidence[:2]) if evidence else s.get('signal_label', '')
        name = s.get('strategy_name', '')
        if '缠论' in name and chains[1]['evidence'] == '缠论结构信号':
            chains[1]['evidence'] = ev_str or '缠论信号'
        elif '筹码' in name and chains[0]['evidence'] == '资金流向与筹码信号':
            chains[0]['evidence'] = ev_str or '筹码信号'
        elif 'BOCIASI' in name and chains[2]['evidence'] == 'BOCIASI情绪信号':
            chains[2]['evidence'] = ev_str or '情绪信号'
    return chains


def _build_uncertainties(signals: List[Dict]) -> List[Dict]:
    """从信号中提取数据完整性问题"""
    uncertainties = []
    for s in signals:
        risk_notes = s.get('risk_notes', [])
        if risk_notes:
            for note in risk_notes[:2]:
                uncertainties.append({
                    'dimension': s.get('strategy_name', '未知'),
                    'factor': note,
                    'impact': '判断受限',
                    'detail': note,
                })
    return uncertainties


def _empty_dimensions() -> Dict:
    """降级时的空五维数据"""
    return {k: {'direction': 'neutral', 'status_text': '数据不可用'}
            for k in ['chanlun', 'volume_price', 'chip', 'emotion', 'factor']}


def _today_str() -> str:
    from datetime import date
    return date.today().strftime('%Y-%m-%d')
