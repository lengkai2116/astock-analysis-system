"""权重计算引擎 — IC动态权重 + 静态矩阵 + 情绪联动（387号方案5.5）

替代status_engine.MARKET_REGIME_WEIGHTS静态矩阵。
"""
from __future__ import annotations

import logging
import math
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# 静态权重矩阵（387号方案§1.3，作为IC失败回退）
STATIC_WEIGHTS = {
    'trending_up':    {'signal': 0.15, 'structure': 0.20, 'vp': 0.15, 'chip_fund': 0.10, 'emotion': 0.10, 'risk': 0.15, 'valuation': 0.15},
    'ranging':        {'signal': 0.10, 'structure': 0.15, 'vp': 0.20, 'chip_fund': 0.10, 'emotion': 0.10, 'risk': 0.20, 'valuation': 0.15},
    'trending_down':  {'signal': 0.10, 'structure': 0.10, 'vp': 0.10, 'chip_fund': 0.10, 'emotion': 0.10, 'risk': 0.30, 'valuation': 0.20},
    'extreme_panic':  {'signal': 0.05, 'structure': 0.05, 'vp': 0.05, 'chip_fund': 0.10, 'emotion': 0.10, 'risk': 0.40, 'valuation': 0.25},
}

# 情绪周期权重乘数（387号方案§5.4，从dim5.quadrant读取）
EMOTION_MULTIPLIERS = {
    'LL': 1.15,  # 情绪底部：风险维度权重↑
    'LH': 1.05,
    'MM': 1.00,
    'HL': 0.90,
    'HH': 0.75,  # 情绪顶部：风险维度权重↓
}


def detect_market_regime(tags: dict, dims: Optional[dict] = None) -> str:
    """从tags/dims推导当前市场状态"""
    dims = dims or {}
    status_bar = str(tags.get('status_bar', ''))
    if '强确认' in status_bar or '趋势确认' in status_bar:
        return 'trending_up'
    if '谨慎' in status_bar or '观望' in status_bar:
        return 'ranging'
    if '风险' in status_bar or '看空' in status_bar:
        return 'trending_down'
    emotion_state = str(dims.get('emotion', {}).get('state', ''))
    if '退潮' in emotion_state or '高潮' in emotion_state:
        return 'extreme_panic'
    risk_state = str(dims.get('risk', {}).get('state', ''))
    if risk_state == '高':
        return 'trending_down'
    return 'ranging'


def get_static_weights(regime: str) -> dict:
    """获取静态权重矩阵（IC失败回退）"""
    return STATIC_WEIGHTS.get(regime, STATIC_WEIGHTS['ranging'])


def compute_ic_weights(
    ic_values: Optional[Dict[str, float]],
    regime: str,
    emotion_quadrant: str = 'MM',
    min_significance: float = 0.1,
) -> Optional[dict]:
    """基于IC值计算动态权重（v3.0-M1修正：60日窗口+t检验）

    Args:
        ic_values: {dim_name: IC_value} 各维度的IC值（已通过显著性检验）
        regime: 市场状态
        emotion_quadrant: BOCIASI象限（LL/LH/HL/HH/MM）
        min_significance: IC显著性门槛（p<0.1 → |t|>1.363）

    Returns:
        权重dict 或 None（IC不显著时回退到静态矩阵）
    """
    if not ic_values:
        return None

    # 检查IC显著性（v3.0-M1修正）
    significant_ics = {}
    for dim, ic in ic_values.items():
        if ic is not None and not math.isnan(ic) and abs(ic) > min_significance:
            significant_ics[dim] = ic

    # 如果有效IC不足3个维度，回退到静态矩阵
    if len(significant_ics) < 3:
        logger.debug(f"IC显著性不足({len(significant_ics)}/7)，回退到静态矩阵")
        return None

    # softmax归一化（确保正值权重）
    weights = {}
    total = 0.0
    for dim, ic in significant_ics.items():
        w = math.exp(ic)  # exp确保正值
        weights[dim] = w
        total += w

    if total <= 0:
        return None

    for dim in weights:
        weights[dim] = round(weights[dim] / total, 3)

    # 对未参与IC计算的维度，使用静态权重的对应值
    static = get_static_weights(regime)
    for dim in ['signal', 'structure', 'vp', 'chip_fund', 'emotion', 'risk', 'valuation']:
        if dim not in weights:
            weights[dim] = static.get(dim, 0.1)

    # 重新归一化（确保总权重=1）
    total = sum(weights.values())
    if total > 0:
        weights = {k: round(v / total, 3) for k, v in weights.items()}

    # 应用情绪象限乘数（v3.0-5.4 + ISSUE-2修复：扩展到emotion维度）
    multiplier = EMOTION_MULTIPLIERS.get(emotion_quadrant, 1.0)
    if multiplier != 1.0:
        # 风险、估值和情绪维度受情绪象限影响
        for dim in ['risk', 'valuation', 'emotion']:
            if dim in weights:
                weights[dim] = round(weights[dim] * multiplier, 3)
        # 重新归一化
        total = sum(weights.values())
        if total > 0:
            weights = {k: round(v / total, 3) for k, v in weights.items()}

    return weights


def compute_ic_from_history(dm, ts_code: str, lookback: int = 60, forward_days: int = 5) -> Optional[Dict[str, float]]:
    """387号§5.5：从历史数据计算各维度IC值（信息系数）

    BUG-1修复：从status_snapshot_history读取历史dim_engine_results，
    而非反复读取当天pre_feat_cache快照。

    IC = corr(dim_direction[t], return[t+forward_days])
    显著性检验：t = |IC| / (std_IC / sqrt(n))，p<0.1 才采信

    Args:
        dm: DataManager实例
        ts_code: 股票代码
        lookback: 回看窗口（交易日数，默认60，12个独立5日数据点）
        forward_days: 未来收益天数（默认5）

    Returns:
        {dim_name: IC_value} 或 None（计算失败/数据不足时）
    """
    try:
        import numpy as np
    except ImportError:
        logger.debug("numpy不可用，跳过IC计算")
        return None

    try:
        # 获取日线数据（含close）
        df = dm.get_cached_daily_data(ts_code)
        if df is None or df.empty or 'close' not in df.columns or 'trade_date' not in df.columns:
            return None

        df = df.sort_values('trade_date').reset_index(drop=True)
        if len(df) < lookback + forward_days:
            return None

        # 计算未来N日收益率
        df['future_return'] = df['close'].shift(-forward_days) / df['close'] - 1
        df = df.dropna(subset=['future_return'])

        if len(df) < lookback:
            return None

        # 取最近lookback行
        recent = df.tail(lookback)
        date_list = [str(row.get('trade_date', ''))[:10] for _, row in recent.iterrows()]

        # BUG-1修复：从status_snapshot_history批量读取历史dim_engine_results
        # 而非反复读取当天pre_feat_cache快照
        hist_results = {}
        try:
            history_rows = dm.get_snapshot_history(
                ts_code=ts_code, start_date=date_list[0], end_date=date_list[-1],
                table='status_snapshot_history')
            for row in (history_rows or []):
                td = str(row.get('trade_date', '') or row.get('snapshot_date', ''))[:10]
                der = row.get('dim_engine_results')
                if der and td:
                    import json as _j
                    hist_results[td] = _j.loads(der) if isinstance(der, str) else der
        except Exception as e:
            logger.debug(f"status_snapshot_history读取失败({ts_code})，降级到pre_feat: {e}")

        # 各维度方向信号：优先从历史dim_engine_results提取，降级到当天pre_feat_cache标签
        dim_signals: Dict[str, list] = {
            'structure': [], 'vp': [], 'chip_fund': [],
            'emotion': [], 'risk': [], 'valuation': [],
        }

        for td in date_list:
            try:
                direction = _extract_dim_directions_from_history(hist_results.get(td))
                if direction is None:
                    # 降级：从pre_feat_cache读取（仅当天数据，信息量有限）
                    direction = _extract_dim_directions_from_pre_feat(dm, ts_code)
                if direction is not None:
                    for dim_name in dim_signals:
                        dim_signals[dim_name].append(direction.get(dim_name, 0))
                else:
                    for dim_name in dim_signals:
                        dim_signals[dim_name].append(0)
            except Exception:
                for dim_name in dim_signals:
                    dim_signals[dim_name].append(0)

        returns = recent['future_return'].values
        n = len(returns)
        if n < 10:
            return None

        ic_values: Dict[str, float] = {}
        for dim, signals_list in dim_signals.items():
            if len(signals_list) < n:
                signals_list = signals_list + [0] * (n - len(signals_list))
            sig_arr = np.array(signals_list[:n], dtype=float)

            if np.all(sig_arr == 0):
                continue

            ic = float(np.corrcoef(sig_arr, returns)[0, 1])
            if np.isnan(ic):
                continue

            # t检验显著性：t = |IC| * sqrt(n)（Fisher z近似）
            t_stat = abs(ic) * math.sqrt(n)
            # p<0.1 → |t|>1.363 (df=n-2)
            if t_stat > 1.363:
                ic_values[dim] = round(ic, 4)

        if len(ic_values) < 3:
            logger.debug(f"IC显著性维度不足({len(ic_values)}/7)，回退到静态矩阵")
            return None

        logger.debug(f"IC计算完成({ts_code})：{ic_values}")
        return ic_values

    except Exception as e:
        logger.debug(f"IC计算失败({ts_code}): {e}")
        return None


def _extract_dim_directions_from_history(dim_engine_results: Optional[dict]) -> Optional[Dict[str, int]]:
    """从历史dim_engine_results提取各维度方向信号（-1/0/+1）

    优先从dim_states中的state值推导（这是StatusEngine.evaluate()的输出）。
    """
    if not dim_engine_results or not isinstance(dim_engine_results, dict):
        return None

    result = {}

    # structure: 从structure.judgment.structure或status_description推导
    struct = dim_engine_results.get('structure') or {}
    j_struct = (struct.get('judgment') or {}).get('structure', '')
    if '上升' in str(j_struct) or str(j_struct) == 'bullish':
        result['structure'] = 1
    elif '下降' in str(j_struct) or str(j_struct) == 'bearish':
        result['structure'] = -1
    else:
        result['structure'] = 0

    # vp: 从volume_price.judgment.vp_state推导
    vp = dim_engine_results.get('volume_price') or {}
    j_vp = str((vp.get('judgment') or {}).get('vp_state', ''))
    if '健康' in j_vp and '背离' not in j_vp:
        result['vp'] = 1
    elif '背离' in j_vp or '严重' in j_vp:
        result['vp'] = -1
    else:
        result['vp'] = 0

    # chip_fund: 从chip_fund.judgment.phase推导
    cf = dim_engine_results.get('chip_fund') or {}
    j_phase = str((cf.get('judgment') or {}).get('phase', ''))
    if j_phase in ('building', 'lifting', 'inflow'):
        result['chip_fund'] = 1
    elif j_phase in ('distributing', 'outflow'):
        result['chip_fund'] = -1
    else:
        result['chip_fund'] = 0

    # emotion: 从emotion.judgment.market_phase或status_description推导
    emo = dim_engine_results.get('emotion') or {}
    j_mood = str((emo.get('judgment') or {}).get('market_phase', ''))
    if j_mood in ('positive', 'recovery'):
        result['emotion'] = 1
    elif j_mood in ('negative', 'ebb', 'ice'):
        result['emotion'] = -1
    else:
        result['emotion'] = 0

    # risk: 从risk.judgment.risk_level推导
    risk = dim_engine_results.get('risk') or {}
    j_risk = str((risk.get('judgment') or {}).get('risk_level', ''))
    if j_risk in ('LOW', '低'):
        result['risk'] = 1
    elif j_risk in ('HIGH', '高'):
        result['risk'] = -1
    else:
        result['risk'] = 0

    # valuation: 从valuation.judgment.valuation_level推导
    val = dim_engine_results.get('valuation') or {}
    j_val = (val.get('judgment') or {}).get('valuation_level', {})
    if isinstance(j_val, dict):
        j_val = j_val.get('value', '')
    if str(j_val) in ('extreme_low', 'low'):
        result['valuation'] = 1
    elif str(j_val) in ('high', 'extreme_high'):
        result['valuation'] = -1
    else:
        result['valuation'] = 0

    return result


def _extract_dim_directions_from_pre_feat(dm, ts_code: str) -> Optional[Dict[str, int]]:
    """降级方案：从pre_feat_cache标签提取维度方向（仅当天数据）"""
    try:
        tags = dm.cache.get_pre_feat(ts_code) or {}
        flat = {}
        for gk, gv in tags.items():
            if isinstance(gv, dict):
                for k, v in gv.items():
                    if v is not None:
                        flat[k] = v

        result = {}
        sl = str(flat.get('state_label', ''))
        result['structure'] = 1 if '上升' in sl else (-1 if '下降' in sl else 0)
        vpf = str(flat.get('volume_price_fit', ''))
        result['vp'] = 1 if vpf in ('strong_healthy', 'healthy') else (-1 if vpf in ('diverging', 'severe_diverging') else 0)
        mfp = str(flat.get('main_force_phase', ''))
        result['chip_fund'] = 1 if mfp in ('building', 'lifting', 'inflow') else (-1 if mfp in ('distributing', 'outflow') else 0)
        se = str(flat.get('stock_emotion', ''))
        result['emotion'] = 1 if se in ('积极', '复苏') else (-1 if se in ('消极', '退潮', '冰点') else 0)
        rl = str(flat.get('risk_level', ''))
        result['risk'] = 1 if rl in ('LOW', '低') else (-1 if rl in ('HIGH', '高') else 0)
        vl = str(flat.get('valuation_level', ''))
        result['valuation'] = 1 if vl in ('extreme_low', 'low') else (-1 if vl in ('high', 'extreme_high') else 0)
        return result
    except Exception:
        return None


def get_weights(
    regime: str,
    ic_values: Optional[Dict[str, float]] = None,
    emotion_quadrant: str = 'MM',
) -> dict:
    """统一权重获取接口

    优先级：IC动态权重 > 静态矩阵
    """
    if ic_values:
        ic_weights = compute_ic_weights(ic_values, regime, emotion_quadrant)
        if ic_weights:
            logger.debug(f"使用IC动态权重(regime={regime}, quadrant={emotion_quadrant})")
            return ic_weights

    logger.debug(f"使用静态权重(regime={regime})")
    return get_static_weights(regime)
