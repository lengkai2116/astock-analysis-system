"""
SnapshotAssembler — 策略信号 → 结构化快照 JSON 组装器

从 SignalComputationService 产出的 N 个策略信号中提取各维度数据，
组装为 272 号方案 §9.2 Schema 定义的完整结构化快照 JSON。

输出格式: docs/schemas/structured_snapshot.md
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def _find_signal(signals: List[Dict], keyword: str) -> Optional[Dict]:
    """从信号列表中按策略名关键词查找"""
    for s in signals:
        if keyword in s.get('strategy_name', ''):
            return s
    return None


def _safe_float(val, default=None):
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _extract_environment(signals: List[Dict], market_context: Optional[Dict] = None) -> Dict:
    """环境定位区块"""
    env = {}
    if market_context:
        env['index_5d_ret'] = market_context.get('idx_5d_ret')
        env['index_20d_ret'] = market_context.get('idx_20d_ret')
        env['index_condition'] = market_context.get('index_condition')
        env['market_state'] = market_context.get('market_state')
        env['stock_vs_index_20d'] = market_context.get('stock_vs_index_20d')
    return env


def _extract_structure(signals: List[Dict]) -> Dict:
    """走势结构区块"""
    chanlun_sig = _find_signal(signals, '缠论走势分析')
    if not chanlun_sig:
        return {}
    sr = chanlun_sig.get('status_recognition', {})
    detail = chanlun_sig.get('chanlun_analysis_detail', {})
    trend = sr.get('trend', {})
    zs_info = detail.get('中枢分析', {})
    return {
        'level': trend.get('stage', ''),
        'trend_direction': trend.get('direction', ''),
        'trend_strength': trend.get('strength', ''),
        'zhongshu_range': [zs_info.get('最新中枢区间', [None, None])[0],
                           zs_info.get('最新中枢区间', [None, None])[1]] if zs_info else None,
        'position_vs_zhongshu': zs_info.get('价格相对位置', ''),
        'beichi': detail.get('买卖点信号', {}).get('背驰信号'),
        'active_signal': sr.get('active_signal'),
        'active_signal_label': sr.get('active_signal_label'),
        'near_levels_filtered': sr.get('near_levels_filtered', []),
        'level_upper_limit': sr.get('level_upper_limit', False),
    }


def _extract_chip(signals: List[Dict]) -> Dict:
    """筹码成本区块"""
    chip_sig = _find_signal(signals, '筹码主力分析')
    if not chip_sig:
        return {}
    sr = chip_sig.get('status_recognition', {})
    mf_cost = sr.get('main_force_cost', {})
    return {
        'chip_peak': sr.get('chip_peak'),
        'concentration': sr.get('concentration'),
        'asr': sr.get('asr'),
        'main_force_cost': _safe_float(mf_cost.get('cost_price')),
        'distance_pct': _safe_float(mf_cost.get('distance_pct')),
        'margin_cost_price': sr.get('margin_cost_price'),
        'sandwich_zone': sr.get('sandwich_zone'),
        'phase': sr.get('trend', {}).get('stage', ''),
        'retail_vs_institutional': sr.get('retail_vs_institutional'),
        'sentiment_crowding': sr.get('sentiment_crowding'),
        'sentiment_crowding_label': sr.get('sentiment_crowding_label'),
    }


def _extract_price(signals: List[Dict], market_context: Optional[Dict] = None) -> Dict:
    """价格位置区块"""
    price = {}
    if market_context:
        price['bias_ma5'] = market_context.get('bias_ma5')
        price['bias_ma20'] = market_context.get('bias_ma20')
        price['bias_ma60'] = market_context.get('bias_ma60')
        price['percentile_250d'] = market_context.get('percentile_250d')
        price['boll_bandwidth'] = market_context.get('boll_bandwidth')
        price['ma_convergence'] = market_context.get('ma_convergence')
        price['turnover_rate'] = market_context.get('turnover_rate')
    chanlun_sig = _find_signal(signals, '缠论走势分析')
    if chanlun_sig:
        sr = chanlun_sig.get('status_recognition', {})
        levels = sr.get('support_resistance', {})
        price['support'] = levels.get('support')
        price['resistance'] = levels.get('resistance')
    return price


def _extract_volume_price(signals: List[Dict], market_context: Optional[Dict] = None) -> Dict:
    """量价关系区块"""
    vp_sig = _find_signal(signals, '量价分析策略')
    if not vp_sig:
        return {}
    vp = vp_sig.get('status_recognition', {}).get('volume', {})
    return {
        'basic_form': vp.get('state', ''),
        'pattern_name': vp_sig.get('current_pattern', '') or vp.get('structure', ''),
        'enhanced_patterns': vp_sig.get('enhance_patterns', []),
        'volume_ratio': market_context.get('volume_ratio') if market_context else None,
        'turnover_rate': market_context.get('turnover_rate') if market_context else None,
    }


def _extract_capital(signals: List[Dict], market_context: Optional[Dict] = None) -> Dict:
    """资金博弈区块"""
    cap = {}
    if market_context:
        cap['net_lg_amount_5d'] = market_context.get('net_lg_amount')
        cap['net_elg_amount_5d'] = market_context.get('net_elg_amount')
        cap['net_sm_amount_5d'] = market_context.get('net_sm_amount')
        cap['retail_vs_institutional'] = market_context.get('retail_vs_institutional')
    chip_sig = _find_signal(signals, '筹码主力分析')
    if chip_sig:
        sr = chip_sig.get('status_recognition', {})
        cap['sentiment_crowding'] = sr.get('sentiment_crowding')
        cap['sentiment_crowding_label'] = sr.get('sentiment_crowding_label')
        cap['retail_vs_institutional'] = sr.get('retail_vs_institutional') or cap.get('retail_vs_institutional')
    return cap


def _extract_sentiment(signals: List[Dict]) -> Dict:
    """情绪周期区块"""
    bociasi_sig = _find_signal(signals, 'BOCIASI快线')
    if not bociasi_sig:
        return {}
    sr = bociasi_sig.get('status_recognition', {})
    return {
        'signal': bociasi_sig.get('signal', ''),
        'signal_label': bociasi_sig.get('signal_label', ''),
        'confidence': bociasi_sig.get('confidence', 0),
        'momentum_level': sr.get('momentum', {}).get('level', ''),
        'momentum_score': sr.get('momentum', {}).get('score', 0),
    }


def _extract_factor(signals: List[Dict]) -> Dict:
    """因子评分区块"""
    factor_sig = _find_signal(signals, '因子评分系统')
    if not factor_sig:
        return {}
    return {
        'score': factor_sig.get('confidence', 0),
        'signal': factor_sig.get('signal', ''),
        'signal_label': factor_sig.get('signal_label', ''),
    }


def _extract_verification(signals: List[Dict], ts_code: str = '') -> Dict:
    """273a: 辅助验证区块 — 情绪周期阶段 + 财务排雷

    Returns:
        {
            'sentiment_phase': {...},  # 来自 MarketSentimentService
            'finance_check': {...},     # 来自 FinanceReportService
        }
    """
    result = {}
    try:
        from app.services.market_sentiment_service import MarketSentimentService
        svc = MarketSentimentService()
        sentiment = svc.get_sentiment_context()
        if sentiment.get('data_available'):
            result['sentiment_phase'] = sentiment
    except Exception as e:
        logger.debug(f"情绪阶段获取跳过: {e}")

    if ts_code:
        try:
            from app.services.finance_report_service import FinanceReportService
            fr = FinanceReportService()
            verdict = fr.get_finance_verdict(ts_code)
            if verdict.get('data_available'):
                result['finance_check'] = verdict
        except Exception as e:
            logger.debug(f"财务排雷跳过: {e}")

    return result


class SnapshotAssembler:
    """策略信号 → 结构化快照 JSON 组装器"""

    def assemble(self, signals: List[Dict], ts_code: str = '',
                 market_context: Optional[Dict] = None) -> Dict:
        """从策略信号列表组装完整结构化快照

        Args:
            signals: SignalComputationService.compute_for_stock() 返回值
            ts_code: 股票代码
            market_context: 可选的扩展市场上下文

        Returns:
            符合 §9.2 Schema 的完整结构化快照
        """
        return {
            'ts_code': ts_code,
            'environment': _extract_environment(signals, market_context),
            'structure': _extract_structure(signals),
            'chip': _extract_chip(signals),
            'price_position': _extract_price(signals, market_context),
            'volume_price': _extract_volume_price(signals, market_context),
            'capital': _extract_capital(signals, market_context),
            'sentiment': _extract_sentiment(signals),
            'factor': _extract_factor(signals),
            'verification': _extract_verification(signals, ts_code),
            'return_driver': {'available': False},
        }
