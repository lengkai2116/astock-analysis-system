"""
选股系统 L3 策略引擎集成模块
将 volume_price_strategy / chanlun_strategy 接入选股 L3 流水线

架构定位（139号方案§2）:
  L1 风险剔除 → L2 筹码策略(主力识别) → L3 多策略验证(缠论+量价+因子)
                                     └── L3 是正交于筹码的独立验证层

输出格式符合 214 号方案 §2.1 的 strategy_detail 规范
"""
import logging
from datetime import datetime
from typing import Dict, List, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# ── L3 引擎健康度指标（生产监控用） ──
# 每次 run_screener 调用后更新，可通过 GET /api/v3/screener/stats 查看
_L3_ENGINE_HEALTH = {
    'total_runs': 0,
    'total_stocks_processed': 0,
    'total_errors': 0,
    'chanlun_errors': 0,
    'vp_errors': 0,
    'last_run_status': 'idle',
    'last_error': None,
    'last_error_time': None,
}


def _record_engine_error(error_type: str, symbol: str = ''):
    """记录 L3 引擎异常（供生产监控面板使用）"""
    _L3_ENGINE_HEALTH['total_errors'] += 1
    if error_type == 'chanlun':
        _L3_ENGINE_HEALTH['chanlun_errors'] += 1
    elif error_type == 'volume_price':
        _L3_ENGINE_HEALTH['vp_errors'] += 1
    _L3_ENGINE_HEALTH['last_error'] = f'{error_type}: {symbol}'
    _L3_ENGINE_HEALTH['last_error_time'] = str(datetime.now())
    # 自愈触发：单次运行错误率 > 20% 时提示
    total = _L3_ENGINE_HEALTH['total_stocks_processed']
    errs = _L3_ENGINE_HEALTH['total_errors']
    if total > 50 and errs > total * 0.2:
        logger.warning(
            f"L3 引擎错误率 {errs}/{total} ({errs/total*100:.0f}%) 超过 20%，"
            "建议检查数据源或策略引擎配置"
        )


def _score_to_grade(score: float) -> str:
    """0-10 评分映射到评级"""
    if score >= 8:
        return 'S'
    if score >= 7:
        return 'A'
    if score >= 5.5:
        return 'B'
    if score >= 4:
        return 'C'
    return 'D'


def _compute_chanlun_score(chanlun_result: Dict) -> Tuple[float, str, str]:
    """
    从缠论分析结果提取选股评分（0-10）

    Returns:
        (score_0_10, signal_text, direction)
    """
    if not chanlun_result or not chanlun_result.get('success'):
        return 0.0, '分析失败', 'neutral'

    buy_pts = chanlun_result.get('buy_points', [])
    sell_pts = chanlun_result.get('sell_points', [])
    trend = chanlun_result.get('trend', 'unknown')
    summary = chanlun_result.get('summary', {})

    score = 5.0  # 基础分

    # 买点加分
    signal_texts = []
    for bp in buy_pts:
        bp_type = (bp.type if hasattr(bp, 'type')
                   else bp.get('type', '') if isinstance(bp, dict) else '')
        confidence = (bp.confidence if hasattr(bp, 'confidence')
                      else bp.get('confidence', 0.5) if isinstance(bp, dict) else 0.5)
        if 'first_buy' in str(bp_type):
            score += 3.0 * confidence
            signal_texts.append('一买')
        elif 'second_buy' in str(bp_type):
            score += 2.5 * confidence
            signal_texts.append('二买')
        elif 'third_buy' in str(bp_type):
            score += 2.0 * confidence
            signal_texts.append('三买')

    # 卖点扣分
    for sp in sell_pts:
        sp_type = (sp.type if hasattr(sp, 'type')
                   else sp.get('type', '') if isinstance(sp, dict) else '')
        confidence = (sp.confidence if hasattr(sp, 'confidence')
                      else sp.get('confidence', 0.5) if isinstance(sp, dict) else 0.5)
        if 'sell' in str(sp_type):
            score -= 2.0 * confidence
            signal_texts.append(str(sp_type))

    # 趋势加分
    if trend == 'up':
        score += 0.5
    elif trend == 'down':
        score -= 0.5

    # 中枢数量加分（有中枢说明结构完整）
    zs_count = summary.get('total_zhongshu', 0)
    if zs_count >= 1:
        score += 0.3

    score = max(0.0, min(10.0, score))
    direction = 'bullish' if score >= 6 else ('bearish' if score <= 4 else 'neutral')
    signal_text = '+'.join(signal_texts) if signal_texts else '无明确信号'

    return round(score, 2), signal_text, direction


def _compute_volume_price_score(vp_result: Dict) -> Tuple[float, str, str]:
    """
    从量价分析结果提取选股评分（0-10）

    Returns:
        (score_0_10, signal_text, direction)
    """
    if not vp_result or not vp_result.get('success'):
        return 0.0, '分析失败', 'neutral'

    signal_output = vp_result.get('signal_output', {})
    direction = signal_output.get('signal', 'NEUTRAL')
    confidence = signal_output.get('confidence', 0.0)
    signal_label = signal_output.get('signal_label', '')
    stage = vp_result.get('stage', {})

    dir_map = {'BULLISH': 7.0, 'WATCH': 5.5, 'HOLD': 5.0, 'NEUTRAL': 5.0, 'BEARISH': 3.0}
    base = dir_map.get(direction, 5.0)
    score = base * confidence * 2  # confidence 0-1, 乘2映射到0-10
    score = max(0.0, min(10.0, score))

    # 阶段加分
    current_stage = stage.get('current_stage', '')
    if current_stage in ('UPTREND_ACTIVE',):
        score += 0.5
    elif current_stage in ('DOWNTREND_ACTIVE',):
        score -= 0.5

    score = max(0.0, min(10.0, score))
    direction_str = (
        'bullish' if direction in ('BULLISH',)
        else 'bearish' if direction in ('BEARISH',)
        else 'neutral'
    )
    signal_text = signal_label if signal_label else direction

    return round(score, 2), signal_text, direction_str


def _compute_combined_score(chanlun_score: float, vp_score: float,
                            chanlun_dir: str, vp_dir: str) -> float:
    """
    综合评分（L3 多策略共振评分）

    L3 仅包含缠论+量价，筹码评分已在 L2 独立完成，两者正交不重复。
    权重: 缠论 50% + 量价 50%（等权，因为同属策略验证层）
    """
    total = chanlun_score * 0.5 + vp_score * 0.5

    # 方向一致性加分: 缠论和量价同向 +1
    if chanlun_dir == vp_dir and chanlun_dir != 'neutral':
        total += 1.0

    return min(10.0, max(0.0, total))


def _extract_chanlun_evidence(chanlun_result: Dict) -> List[str]:
    """从缠论结果提取依据文本"""
    evidences = []
    if not chanlun_result or not chanlun_result.get('success'):
        return evidences

    summary = chanlun_result.get('summary', {})
    buy_pts = chanlun_result.get('buy_points', [])

    if buy_pts:
        bp_types = []
        for bp in buy_pts:
            bt = (
                bp.type if hasattr(bp, 'type')
                else bp.get('type', 'unknown') if isinstance(bp, dict)
                else 'unknown'
            )
            bp_types.append(str(bt))
        evidences.append(f"缠论买点: {', '.join(bp_types)}")

    zs_count = summary.get('total_zhongshu', 0)
    if zs_count > 0:
        evidences.append(f"中枢: {zs_count}个")

    trend = chanlun_result.get('trend', '')
    if trend:
        evidences.append(f"趋势: {trend}")

    check = chanlun_result.get('theorem_check', {})
    if isinstance(check, dict):
        t10 = check.get('T10', {})
        t10_score = t10.get('score', 1.0) if isinstance(t10, dict) else 1.0
    else:
        t10_score = 1.0
    if t10_score < 0.8:
        evidences.append("动力结构偏弱")

    return evidences


def _extract_vp_evidence(vp_result: Dict) -> List[str]:
    """从量价结果提取依据文本"""
    evidences = []
    if not vp_result or not vp_result.get('success'):
        return evidences

    signal_output = vp_result.get('signal_output', {})
    signal_label = signal_output.get('signal_label', '')
    if signal_label:
        evidences.append(f"量价信号: {signal_label}")

    stage = vp_result.get('stage', {})
    current_stage = stage.get('current_stage', '')
    stage_note = stage.get('note', '')
    if current_stage:
        evidences.append(f"波段: {current_stage}")
    if stage_note:
        evidences.append(stage_note)

    relation = vp_result.get('relation', {})
    pattern = relation.get('current_pattern', '')
    if pattern:
        evidences.append(f"形态: {pattern}")

    momentum = relation.get('aux_momentum', {})
    mom_level = momentum.get('level', '')
    if mom_level:
        evidences.append(f"动量: {mom_level}")

    return evidences


def screen_l3_candidates(
    candidates: List[Dict],
    data_dict: Dict[str, pd.DataFrame],
) -> List[Dict]:
    """
    对L2通过的候选股执行L3策略验证（缠论+量价共振评分）

    L3 与 L2 的筹码评分 正交独立——L3 不做筹码分析，
    只做缠论买卖点 + 量价关系 的多策略共振验证。

    从 DuckDB 每日基础数据 + 资金流向数据 构建 market_context，
    传递到缠论评分系统用于环境感知评分调整。

    Args:
        candidates: L2输出的候选列表 [{symbol, score(筹码评分), ...}]
        data_dict: {symbol: DataFrame} 数据池

    Returns:
        带 strategy_detail 的最终结果列表
    """
    validated = []
    logger.info(f"L3 策略验证开始: {len(candidates)} 只候选股")
    _L3_ENGINE_HEALTH['total_runs'] += 1
    _L3_ENGINE_HEALTH['last_run_status'] = 'running'
    stocks_processed = 0

    # 构建大盘环境条件（用于全部候选股的 market_context.index_condition）
    index_condition = _compute_index_condition(data_dict)

    for item in candidates:
        symbol = item.get('symbol', item.get('ts_code', ''))
        if not symbol or symbol not in data_dict:
            continue

        df = data_dict[symbol]
        if df.empty or len(df) < 60:
            continue

        # ── 构建 market_context（从 DuckDB 每日基础 + 资金流向数据） ──
        market_context = _build_market_context(symbol, df)

        # 覆盖大盘环境条件（全局已计算）
        if market_context:
            market_context['index_condition'] = index_condition

        # ── 量价策略评分 ──
        vp_result = None
        vp_score, vp_signal, vp_dir = 0.0, 'N/A', 'neutral'
        try:
            from .volume_price_strategy import VolumePriceStrategy
            vp = VolumePriceStrategy()
            vp_result = vp.analyze(df)
            if vp_result.get('success'):
                vp_score, vp_signal, vp_dir = _compute_volume_price_score(vp_result)
        except Exception as e:
            logger.debug(f"量价分析失败 {symbol}: {e}")
            _record_engine_error('volume_price', symbol)

        # ── 缠论策略评分 ──
        cl_result = None
        cl_score, cl_signal, cl_dir = 0.0, 'N/A', 'neutral'
        try:
            from .chanlun_strategy import analyze_chanlun
            cl_result = analyze_chanlun(df)
            if cl_result.get('success'):
                cl_score, cl_signal, cl_dir = _compute_chanlun_score(cl_result)
                # market_context 环境感知评分调整（等效于 ChanlunScorer.score 的逻辑）
                cl_score = _adjust_score_with_context(cl_score, market_context)
        except Exception as e:
            logger.debug(f"缠论分析失败 {symbol}: {e}")
            _record_engine_error('chanlun', symbol)

        # ── 综合评分（仅缠论+量价，不含筹码） ──
        combined_score = _compute_combined_score(
            cl_score, vp_score, cl_dir, vp_dir,
        )
        grade = _score_to_grade(combined_score)

        # ── 信号标签 ──
        triggers = []
        if cl_dir == 'bullish' and cl_score >= 6:
            triggers.append(cl_signal)
        if vp_dir == 'bullish' and vp_score >= 6:
            triggers.append(vp_signal)
        if not triggers:
            triggers.append('待观察')

        # ── 依据合并 ──
        reasons = []
        reasons.extend(_extract_chanlun_evidence(cl_result))
        reasons.extend(_extract_vp_evidence(vp_result))
        if not reasons:
            reasons.append('基础数据通过验证')

        # ── 构建 strategy_detail（214号方案格式） ──
        strategy_detail = {
            'chanlun': {
                'direction': cl_dir,
                'score': round(cl_score / 10.0, 2),
                'signal': cl_signal,
            },
            'volume_price': {
                'direction': vp_dir,
                'score': round(vp_score / 10.0, 2),
                'signal': vp_signal,
            },
            'factor': {
                'score': round(
                    max(cl_score, vp_score) * 10, 1
                ) if cl_score > 0 or vp_score > 0 else 0,
                'grade': grade,
                'combinations': [],
                'combination_note': '缠论+量价共振评分',
            },
        }

        score_100 = round(combined_score * 10, 1)

        validated.append({
            'symbol': symbol,
            'name': item.get('name', ''),
            'score': score_100,
            'close': round(float(df['close'].iloc[-1]), 2) if 'close' in df.columns else None,
            'pct_chg': round(float(df['pct_chg'].iloc[-1]), 2) if 'pct_chg' in df.columns else None,
            'grade': grade,
            'industry': '',
            'triggers': triggers,
            'reasons': reasons,
            'strategy_detail': strategy_detail,
            'chanlun_score': round(cl_score, 2),
            'vp_score': round(vp_score, 2),
        })
        stocks_processed += 1

    validated.sort(key=lambda x: x['score'], reverse=True)
    _L3_ENGINE_HEALTH['total_stocks_processed'] += stocks_processed
    _L3_ENGINE_HEALTH['last_run_status'] = 'ok' if validated else 'no_results'
    logger.info(f"L3 策略验证完成: {len(validated)} 只通过（共处理 {stocks_processed} 只）")
    return validated


def _compute_index_condition(data_dict: Dict[str, pd.DataFrame]) -> str:
    """从大盘指数数据计算大盘环境条件

    参考 000001.SH（上证指数）近 5 日涨跌幅判断大盘强弱：
      - 涨 > 2% → GOOD
      - 跌 < -2% → POOR
      - 其他 → NORMAL

    Returns:
        'GOOD' / 'POOR' / 'NORMAL'
    """
    try:
        for symbol in data_dict:
            if symbol in ('000001.SH', '上证指数'):
                df = data_dict[symbol]
                if df is not None and not df.empty and len(df) >= 5:
                    pct_chg = df['pct_chg'].tail(5).sum() if 'pct_chg' in df.columns else 0
                    if pct_chg > 2:
                        return 'GOOD'
                    elif pct_chg < -2:
                        return 'POOR'
                    return 'NORMAL'
    except Exception:
        pass
    return 'NORMAL'


def _build_market_context(symbol: str, df: pd.DataFrame) -> Dict:
    """从 DuckDB 缓存构建单只股票的 market_context

    从 daily_basic_cache 获取 turnover_rate,
    从 moneyflow_cache 获取 5 日 net_lg_amount 汇总.

    Returns:
        {'turnover_rate': float, 'net_lg_amount': float} 或 None
    """
    try:
        from app.data import DataManager
        dm = DataManager()
        context = {}

        # 获取换手率（最近交易日）
        try:
            basic_df = dm.get_cached_daily_basic(symbol)
            if not basic_df.empty and 'turnover_rate' in basic_df.columns:
                tr_series = basic_df['turnover_rate'].dropna().tail(5)
                if len(tr_series) > 0:
                    context['turnover_rate'] = float(tr_series.mean())
        except Exception:
            pass

        # 获取 5 日大单净流入汇总
        try:
            mf_df = dm.get_cached_moneyflow(symbol)
            if not mf_df.empty and 'net_lg_amount' in mf_df.columns:
                net_series = mf_df['net_lg_amount'].dropna().tail(5)
                if len(net_series) > 0:
                    context['net_lg_amount'] = float(net_series.sum())
        except Exception:
            pass

        return context if context else None
    except Exception:
        return None


def _adjust_score_with_context(score_0_10: float, market_context: Dict) -> float:
    """根据市场上下文调整缠论评分（0-10 范围）

    等效于 ChanlunScorer.score() 的市场环境调整逻辑，但作用在 0-10 评分上。

    调整项：
      - 换手率 > 10%: +0.5  |  > 5%: +0.3
      - 大单净流入 > 0: +0.3 |  < 0: -0.3
      - 大盘 POOR: -0.5 | GOOD: +0.3

    Args:
        score_0_10: 缠论原始评分 (0-10)
        market_context: 市场上下文字典（可能为 None）

    Returns:
        调整后的评分 (0-10, clamped)
    """
    if not market_context:
        return score_0_10

    adjustment = 0.0

    # 换手率调整
    turnover = market_context.get('turnover_rate')
    if turnover is not None:
        if turnover > 10:
            adjustment += 0.5
        elif turnover > 5:
            adjustment += 0.3

    # 资金流向调整
    net_lg = market_context.get('net_lg_amount')
    if net_lg is not None:
        if net_lg > 0:
            adjustment += 0.3
        elif net_lg < 0:
            adjustment -= 0.3

    # 大盘环境调整
    idx_cond = market_context.get('index_condition')
    if idx_cond == 'POOR':
        adjustment -= 0.5
    elif idx_cond == 'GOOD':
        adjustment += 0.3

    return max(0.0, min(10.0, score_0_10 + adjustment))
