"""323号 S0：深度字段提取器——从 P2 信号/phase_detector 提取深度字段供标签库落库

目的：引擎B（个股页五维）需要缠论结构/筹码分布/资金风险深度字段（约 20 个），
当前存于 strategy_signal_detail 信号 status_recognition 或 phase_detector 内部，
未落 opportunity_tags_cache 标签库。本模块提取这些字段，供 P4 预计算落库。

实证（2026-08-09）：
- 缠论深度字段（support_resistance/zhongshu_strength/multi_level 等）在 P2 信号中 99% 覆盖；
- 筹码深度字段（asr/cyqkl/concentration/profit_ratio/ssrp/chip_peak）由 ChipIndicators
  产出（phase_detector._last_chip_indicators 已含），但 P2 信号筹码深度缺失（仅 1.2%）；
- tag_group 列已存在（derived/direction/environment/position/quality/unknown），
  深度字段采用新增组 structure/chip_deep/fund_risk。
"""
from __future__ import annotations

import json
import logging

from app.data import DataManager

logger = logging.getLogger(__name__)


def extract_chanlun_deep_tags(ts_code: str) -> dict:
    """从 strategy_signal_detail 缠论信号提取深度字段（缠论结构组）

    Returns:
        {support_resistance: JSON, zhongshu_strength: str, multi_level: JSON,
         near_levels_filtered: JSON, active_signal: str, active_signal_label: str,
         level_upper_limit: str, momentum: JSON, state_label: str, risk_level: str}
        信号缺失时返回空 dict。
    """
    try:
        dm = DataManager()
        cached = dm.cache.get_latest_signal_detail(ts_code)
        if not cached:
            return {}
        signals = cached.get('signals', {})
        chanlun = None
        for name, s in signals.items():
            if '缠论' in name:
                chanlun = s
                break
        if not chanlun:
            return {}
        sr = chanlun.get('status_recognition', {})
        out = {}
        # 缠论结构深度字段（structure 组）
        if 'support_resistance' in sr:
            out['support_resistance'] = json.dumps(sr['support_resistance'], ensure_ascii=False)
        if 'zhongshu_strength' in sr:
            out['zhongshu_strength'] = str(sr['zhongshu_strength'])
        if 'multi_level' in sr:
            out['multi_level'] = json.dumps(sr['multi_level'], ensure_ascii=False)
        if 'near_levels_filtered' in sr:
            out['near_levels_filtered'] = json.dumps(sr['near_levels_filtered'], ensure_ascii=False)
        if 'active_signal' in sr:
            out['active_signal'] = str(sr['active_signal'])
        if 'active_signal_label' in sr:
            out['active_signal_label'] = str(sr['active_signal_label'])
        if 'level_upper_limit' in sr:
            out['level_upper_limit'] = str(sr['level_upper_limit'])
        if 'momentum' in sr:
            out['momentum'] = json.dumps(sr['momentum'], ensure_ascii=False)
        if 'state_label' in sr:
            out['state_label'] = str(sr['state_label'])
        if 'risk_level' in sr:
            out['risk_level'] = str(sr['risk_level'])
        return out
    except Exception as e:
        logger.debug(f"extract_chanlun_deep_tags 失败 ({ts_code}): {e}")
        return {}


def extract_chip_deep_tags(ts_code: str) -> dict:
    """从 phase_detector._last_chip_indicators 提取筹码深度字段（筹码分布组）

    筹码深度字段（asr/cyqkl/concentration/profit_ratio/ssrp 等）由 ChipIndicators
    产出并缓存于 phase_detector._last_chip_indicators，但未落标签库。
    通过重新运行 phase_detector.compute_tags 触发计算后提取。

    Returns:
        {chip_peak, asr, cyqkl, concentration, profit_ratio, ssrp, ...}
        计算失败时返回空 dict。
    """
    try:
        from app.data import DataManager
        from app.opportunity_atlas.phase_detector import PhaseDetectionEngine
        dm = DataManager()
        df = dm.get_cached_daily_data(ts_code)
        if df is None or df.empty or len(df) < 30:
            return {}
        pd_engine = PhaseDetectionEngine()
        pd_engine.compute_tags(ts_code, df)   # 触发 _last_chip_indicators 填充
        ind = getattr(pd_engine, '_last_chip_indicators', {}) or {}
        out = {}
        # main_peak → chip_peak 映射（main_peak 是筹码主峰 dict {price, ratio}）
        if 'main_peak' in ind and isinstance(ind['main_peak'], dict):
            pk_price = ind['main_peak'].get('price')
            if pk_price is not None:
                try:
                    out['chip_peak'] = str(round(float(pk_price), 2))
                except (TypeError, ValueError):
                    pass
        for key in ('asr', 'cyqkl', 'concentration', 'profit_ratio', 'ssrp',
                    'sandwich_zone', 'retail_vs_institutional',
                    'sentiment_crowding', 'sentiment_crowding_label', 'fake_institution',
                    'asr_status', 'concentration_status', 'cyqkl_status',
                    'peak_count', 'peak_type', 'avg_vol_100', 'vol_ratio'):
            if key in ind and ind[key] is not None:
                val = ind[key]
                out[key] = (json.dumps(val, ensure_ascii=False)
                            if isinstance(val, (dict, list)) else str(val))
        return out
    except Exception as e:
        logger.debug(f"extract_chip_deep_tags 失败 ({ts_code}): {e}")
        return {}


# 深度字段 → tag_group 映射（323号 §二 2.2/2.1 清单校准）
DEEP_TAG_GROUPS = {
    # structure 组（缠论结构）
    'support_resistance': 'structure', 'zhongshu_strength': 'structure',
    'multi_level': 'structure', 'near_levels_filtered': 'structure',
    'active_signal': 'structure', 'active_signal_label': 'structure',
    'level_upper_limit': 'structure', 'momentum': 'structure',
    'state_label': 'structure',
    # chip_deep 组（筹码分布）
    'chip_peak': 'chip_deep', 'asr': 'chip_deep', 'cyqkl': 'chip_deep',
    'concentration': 'chip_deep', 'profit_ratio': 'chip_deep', 'ssrp': 'chip_deep',
    'sandwich_zone': 'chip_deep',
    'retail_vs_institutional': 'chip_deep', 'sentiment_crowding': 'chip_deep',
    'sentiment_crowding_label': 'chip_deep', 'fake_institution': 'chip_deep',
    'asr_status': 'chip_deep', 'concentration_status': 'chip_deep', 'cyqkl_status': 'chip_deep',
    # fund_risk 组（资金/风险）
    'net_lg_amount_5d': 'fund_risk', 'margin_cost_price': 'fund_risk',
    'risk_level': 'fund_risk',
}


def extract_fund_risk_tags(ts_code: str) -> dict:
    """从 P2 筹码信号提取资金/风险深度字段（fund_risk 组）

    net_lg_amount_5d / margin_cost_price 等——筹码信号 status_recognition 中有则提取。
    Returns: 空 dict（当前 P2 筹码信号覆盖低，此组多为空，由 ChipIndicators 补充）。
    """
    try:
        dm = DataManager()
        cached = dm.cache.get_latest_signal_detail(ts_code)
        if not cached:
            return {}
        signals = cached.get('signals', {})
        chip = None
        for name, s in signals.items():
            if '筹码' in name:
                chip = s
                break
        if not chip:
            return {}
        sr = chip.get('status_recognition', {})
        out = {}
        for key in ('net_lg_amount_5d', 'margin_cost_price'):
            if key in sr and sr[key] is not None:
                out[key] = str(sr[key])
        return out
    except Exception as e:
        logger.debug(f"extract_fund_risk_tags 失败 ({ts_code}): {e}")
        return {}
