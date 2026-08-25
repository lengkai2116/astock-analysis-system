"""323号 S0：深度字段提取器——从 P2 信号/筹码指标提取深度字段供标签库落库

目的：引擎B（个股页五维）需要缠论结构/筹码分布/资金风险深度字段（约 20 个），
当前存于 strategy_signal_detail 信号 status_recognition 或 phase_detector 内部，
未落 opportunity_tags_cache 标签库。本模块提取这些字段，供原料加工环节落库。

实证（2026-08-09）：
- 缠论深度字段（support_resistance/zhongshu_strength/multi_level 等）在 P2 信号中 99% 覆盖；
- 筹码深度字段（asr/cyqkl/concentration/profit_ratio/ssrp/chip_peak）由 ChipIndicators
  产出，但 P2 信号筹码深度缺失（仅 1.2%）；
- tag_group 列已存在（derived/direction/environment/position/quality/unknown），
  深度字段采用新增组 structure/chip_deep/fund_risk。

2026-08-19 重构（357号方案决策1）：
- extract_chip_deep_tags 不再依赖 phase_detector._last_chip_indicators
- 改为独立调用 ChipDistributionEstimator + ChipIndicators
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
        # 2026-08-10 核查修复：None 值跳过（原 str(None) 产生字面 "None" 假值）
        def _mk(v, is_json=False):
            if v is None:
                return None
            return (json.dumps(v, ensure_ascii=False) if is_json else str(v))
        if 'support_resistance' in sr:
            _v = _mk(sr['support_resistance'], is_json=True)
            if _v is not None:
                out['support_resistance'] = _v
        if 'zhongshu_strength' in sr:
            _v = _mk(sr['zhongshu_strength'])
            if _v is not None:
                out['zhongshu_strength'] = _v
        if 'multi_level' in sr:
            _v = _mk(sr['multi_level'], is_json=True)
            if _v is not None:
                out['multi_level'] = _v
        if 'near_levels_filtered' in sr:
            _v = _mk(sr['near_levels_filtered'], is_json=True)
            if _v is not None:
                out['near_levels_filtered'] = _v
        if 'active_signal' in sr:
            _v = _mk(sr['active_signal'])
            if _v is not None:
                out['active_signal'] = _v
        if 'active_signal_label' in sr:
            _v = _mk(sr['active_signal_label'])
            if _v is not None:
                out['active_signal_label'] = _v
        if 'level_upper_limit' in sr:
            _v = _mk(sr['level_upper_limit'])
            if _v is not None:
                out['level_upper_limit'] = _v
        if 'momentum' in sr:
            _v = _mk(sr['momentum'], is_json=True)
            if _v is not None:
                out['momentum'] = _v
        if 'state_label' in sr:
            _v = _mk(sr['state_label'])
            if _v is not None:
                out['state_label'] = _v
        if 'risk_level' in sr:
            _v = _mk(sr['risk_level'])
            if _v is not None:
                out['risk_level'] = _v
        return out
    except Exception as e:
        logger.debug(f"extract_chanlun_deep_tags 失败 ({ts_code}): {e}")
        return {}


def extract_chip_deep_tags(ts_code: str) -> dict:
    """独立提取筹码深度字段（筹码分布组）——不依赖 phase_detector

    直接调用 ChipDistributionEstimator + ChipIndicators 计算筹码指标，
    产出 asr/cyqkl/concentration/profit_ratio/ssrp/chip_peak 等深度字段。

    重构依据：357号方案决策1（深度字段解耦），消除对 phase_detector._last_chip_indicators 的依赖。

    Returns:
        {chip_peak, asr, cyqkl, concentration, profit_ratio, ssrp, ...}
        计算失败时返回空 dict。
    """
    try:
        from app.data import DataManager
        from app.data.chip_distribution_service import ChipDistributionEstimator
        from app.data.chip_indicators import ChipIndicators
        dm = DataManager()
        df = dm.get_cached_daily_data(ts_code)
        if df is None or df.empty or len(df) < 30:
            return {}

        # 1. 估算筹码分布
        estimator = ChipDistributionEstimator()
        chip_dist, min_p, max_p, step = estimator.estimate(df)
        if step <= 0:
            return {}

        # 2. 构建 chip_bins
        total = chip_dist.sum() or 1
        chip_bins = [
            {"price_bin": round(min_p + i * step, 2),
             "chip_ratio": float(chip_dist[i] / total)}
            for i in range(len(chip_dist))
        ]

        # 3. 计算筹码指标
        chip_inds = ChipIndicators()
        current_price = float(df["close"].values[-1])
        ind = chip_inds.calculate_all_indicators(
            chip_bins, current_price, kline_data=df
        ) or {}

        # 4. 提取深度字段
        out = {}
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
    'peak_count': 'chip_deep', 'peak_type': 'chip_deep',
    'avg_vol_100': 'chip_deep', 'vol_ratio': 'chip_deep',
    # fund_risk 组（资金/风险）
    'net_lg_amount_5d': 'fund_risk', 'margin_cost_price': 'fund_risk',
    'risk_level': 'fund_risk',
}


def extract_fund_risk_tags(ts_code: str) -> dict:
    """提取资金/风险深度字段（fund_risk 组）

    2026-08-10 325档案修复：弃用 P2 筹码信号路径（覆盖仅 0.77% 致组近空），
    改从 ECM 全市场表直接提取：
    - net_lg_amount_5d：moneyflow_cache 近5日 net_lg_amount 求和（覆盖 5558 只）
    - margin_cost_price：margin_cache rzmje(融资买入额) 加权成本价（覆盖 4414 只）
    Returns: {net_lg_amount_5d, margin_cost_price}，缺失返回空 dict。
    """
    try:
        dm = DataManager()
        out = {}
        # net_lg_amount_5d：moneyflow_cache 近5日大单净额求和
        try:
            mf = dm.cache.get_cached_moneyflow(ts_code)
            if mf is not None and not mf.empty and 'net_lg_amount' in mf.columns:
                net5 = mf['net_lg_amount'].dropna().tail(5).sum()
                if abs(net5) > 0:
                    out['net_lg_amount_5d'] = str(round(float(net5), 2))
        except Exception:
            pass
        # margin_cost_price：margin_cache rzmje 加权均价（近60日融资买入日）
        try:
            margin_df = dm.get_cached_margin(ts_code)
            if margin_df is not None and not margin_df.empty and 'rzmje' in margin_df.columns:
                _df = margin_df.tail(60)
                _buy = _df[_df['rzmje'].fillna(0) > 0]
                if len(_buy) >= 3:
                    # margin 表无 K 线列——用 daily_cache 收盘价近似当日均价
                    _k = dm.get_cached_daily_data(ts_code)
                    _close_map = {}
                    if _k is not None and not _k.empty and 'trade_date' in _k.columns:
                        _close_map = dict(zip(_k['trade_date'].astype(str), _k['close']))
                    _weights = []
                    _prices = []
                    for _i, _row in _buy.iterrows():
                        _w = float(_row.get('rzmje') or 0)
                        if _w <= 0:
                            continue
                        _p = _close_map.get(str(_row.get('trade_date')))
                        if _p is None:
                            continue
                        _weights.append(_w)
                        _prices.append(float(_p))
                    if len(_weights) >= 3 and sum(_weights) > 0:
                        out['margin_cost_price'] = str(round(
                            sum(w * p for w, p in zip(_weights, _prices)) / sum(_weights), 2))
        except Exception:
            pass
        return out
    except Exception as e:
        logger.debug(f"extract_fund_risk_tags 失败 ({ts_code}): {e}")
        return {}
