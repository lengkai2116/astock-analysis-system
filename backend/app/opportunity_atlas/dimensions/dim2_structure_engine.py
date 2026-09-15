"""第2维 结构位置引擎 — 独立完整文件

369号方案 P1 维度引擎整合：物理合并以下文件为独立完整文件：
  - chanlun_config.py — 缠论参数配置
  - chanlun_level_validator.py — 缠论级别校验
  - chanlun_multi_level.py — 多级别缠论分析
  - trend_structure_detector.py — 趋势结构检测
  - chanlun_strategy.py — 缠论核心（分型→笔→中枢→背驰→买卖点→评分）
  - Dim2StructureEngine 输出格式 + 条件稽核
  - shared_support_resistance 支撑阻力

统一接口：Dim2StructureEngine.evaluate() → {status_description, judgment, audit}
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.data.mixins import DataAwareMixin

logger = logging.getLogger(__name__)



# 434号 批次2（2026-09-14）：删除内联 vendored 缠论 4 区块，改 import framework 权威 + shared 共享服务。
# 缠论能力全局单一代码源（framework）；支撑阻力统一走 shared_support_resistance。
from app.engine.framework.chanlun_config import (
    BiConfig,
    BuySellConfig,
    ChanlunConfig,
    DivergenceConfig,
    MultiLevelConfig,
    SegmentConfig,
    ZhongshuConfig,
)
from app.engine.framework.chanlun_level_validator import ChanlunLevelValidator
from app.engine.framework.chanlun_strategy import (
    _MACD_PRECOMPUTED_CACHE,
    BiZhongshuFinder,
    BuySellPoint,
    BuySellPointDetector,
    ChanlunAlphaModel,
    ChanlunAnalyzer,
    ChanlunScorer,
    ChanlunTheoremValidator,
    Divergence,
    DivergenceDetector,
    Fractal,
    FractalDetector,
    KLine,
    KLineMerger,
    Segment,
    SegmentAnalyzer,
    SignalFusion,
    StrategyValidationLayer,
    Stroke,
    StrokeBuilder,
    Zhongshu,
    ZhongshuAnalyzer,
    ZhongshuFactorSwitch,
    _load_precomputed_macd,
    analyze_chanlun,
    calc_macd,
    get_chanlun_tags,
)
from app.engine.framework.trend_structure_detector import TrendStructureDetector
from app.opportunity_atlas.dimensions.enum_cn_map import chip_concentration_cn, ma_alignment_cn
from app.opportunity_atlas.dimensions.shared_support_resistance import calc_support_resistance

# ═══════════════════════════════════════════════════════════
# 第2维 引擎
# ═══════════════════════════════════════════════════════════

class Dim2StructureEngine(DataAwareMixin):
    """第2维 结构位置引擎 — 缠论分析 + 均线排列 + 支撑阻力 + 5子维度"""

    def __init__(self):
        self._dm = None

    def evaluate(self, dims: dict, tags: dict, signals: dict = None,
                 lifecycle: dict = None, data_context: dict = None) -> dict:
        """统一评估入口

        411号Phase 6：优先使用data_context预加载数据，回退独立查询。
        """
        ts_code = tags.get('ts_code', '')

        # 1. 缠论分析
        chanlun_result = None
        df = None
        try:
            analyzer = ChanlunAnalyzer()
            # 411号Phase 6：优先使用data_context
            if data_context and 'daily_df' in data_context:
                df = data_context['daily_df']
            else:
                ecm = self._get_dm().cache
                df = ecm.get_cached_daily(ts_code)
            if df is not None and not df.empty and len(df) >= 30:
                chanlun_result = analyzer.analyze(df)
        except Exception as e:
            logger.debug(f"缠论分析失败: {e}")

        # 2. 支撑阻力
        indicator_ma = data_context.get('indicator_ma_df') if data_context else None
        geo = calc_support_resistance(df if df is not None else None, indicator_ma_df=indicator_ma)

        # 3. 5子维度
        latest_close = float(df['close'].iloc[-1]) if df is not None and not df.empty else 0.0
        vs_zhongshu = _assess_vs_zhongshu(tags, dims, chanlun_result, latest_close)
        vs_ma = _assess_vs_ma(tags)
        vs_sr = _assess_vs_support_resistance(geo)
        vs_chip = _assess_vs_chip(tags)
        vs_indicator = _assess_vs_indicator(tags)

        # 4. 结构强度
        strength = 0.5
        if chanlun_result:
            try:
                scorer = ChanlunScorer()
                score_result = scorer.score(chanlun_result)
                strength = score_result.get('strength', 0.5) if isinstance(score_result, dict) else 0.5
            except Exception:
                pass
        if isinstance(strength, dict):
            strength = strength.get('score', 0.5)

        # 5. 买卖点
        buy_sell_points = []
        if chanlun_result:
            buy_sell_points = (chanlun_result.get('buy_points', []) or []) + \
                              (chanlun_result.get('sell_points', []) or [])

        # 6. 白话文本
        plain = _structure_plain(vs_zhongshu, vs_ma, vs_sr, vs_chip, vs_indicator)
        # 440号：结构态改为引擎自产（缠论 trend 映射），不再读空 dims['structure']
        _t = (chanlun_result.get('trend', '') if chanlun_result else '') or str(tags.get('state_label', ''))
        if _t in ('up', 'down', '上升', '下降'):
            struct_state = '上升' if _t in ('up', '上升') else '下降'
        else:
            struct_state = '盘整'
        pos_state = str(tags.get('price_position', '') or '中位')

        status_description = {
            'vs_zhongshu': vs_zhongshu['detail'],
            'vs_ma': vs_ma['detail'],
            'vs_support_resistance': vs_sr['detail'],
            'vs_chip': vs_chip['detail'],
            'vs_indicator': vs_indicator['detail'],
            'chanlun_direction': chanlun_result.get('trend', '未知') if chanlun_result else '未知',
            'chanlun_strength': round(strength, 2) if isinstance(strength, (int, float)) else str(strength),
            'buy_sell_points': [str(p) for p in buy_sell_points[:3]],
            'plain': plain,
        }

        # 7. judgment
        light = 'yellow'
        if struct_state == '上升': light = 'green'
        elif struct_state == '下降': light = 'red'
        judgment = {
            'structure': struct_state, 'position': pos_state,
            'light': light, 'overall_light': light,
            'overall_direction': 1 if struct_state == '上升' else (-1 if struct_state == '下降' else 0),
            'continuous_value': round(float(strength) if isinstance(strength, (int, float)) else 0.5, 4),
        }

        # 8. audit
        trend_val = chanlun_result.get('trend', '未知') if chanlun_result else '无数据'
        conditions = [
            {'name': '价格vs中枢', 'satisfied': bool(vs_zhongshu['position']),
             'actual': vs_zhongshu['position'] or '未知', 'threshold': '有明确位置'},
            {'name': '均线排列', 'satisfied': bool(vs_ma['alignment']),
             'actual': vs_ma['alignment'] or '未知', 'threshold': '有明确排列'},
            {'name': '支撑阻力', 'satisfied': geo.get('support_price') is not None,
             'actual': f"支撑位{geo.get('support_price', '无')}元" if geo.get('support_price') else '数据不足',
             'threshold': '有支撑位数据'},
            {'name': '缠论分析', 'satisfied': trend_val not in ('未知', '无', '无数据', 'unknown'),
             'actual': trend_val, 'threshold': '有缠论分析结果'},
        ]
        satisfied_count = sum(1 for c in conditions if c['satisfied'])
        total_count = len(conditions)
        audit = {'conditions': conditions, 'satisfied_count': satisfied_count,
                 'total_count': total_count, 'confidence': satisfied_count / total_count if total_count > 0 else 0}

        return {'status_description': status_description, 'judgment': judgment, 'audit': audit}

    def get_data_dependencies(self) -> list:
        return ['daily_cache (market_cache.db)', 'tags (pre_feat_cache)', 'dims (StatusEngine)']


def _assess_vs_zhongshu(tags, dims, chanlun_result=None, latest_close=0.0):
    if chanlun_result:
        zs_list = chanlun_result.get('zhongshu', [])
        if zs_list:
            zs = zs_list[-1]
            zs_h, zs_l = getattr(zs, 'high', 0), getattr(zs, 'low', 0)
            price = latest_close
            if price > zs_h:
                return {'position': '上方', 'detail': f"价格位于中枢上方({zs_l:.2f}~{zs_h:.2f})"}
            elif price < zs_l:
                return {'position': '下方', 'detail': f"价格位于中枢下方({zs_l:.2f}~{zs_h:.2f})"}
            else:
                return {'position': '内部', 'detail': f"价格在中枢内部({zs_l:.2f}~{zs_h:.2f})"}
    pos = str(tags.get('position_vs_zs', ''))
    if pos:
        return {'position': pos, 'detail': f"价格位于中枢{pos}"}
    return {'position': '', 'detail': '中枢位置数据不足'}


def _assess_vs_ma(tags):
    alignment = str(tags.get('ma_alignment', ''))
    if alignment:
        return {'alignment': alignment, 'detail': f"均线{ma_alignment_cn(alignment)}"}
    return {'alignment': '', 'detail': '均线数据不足'}


def _assess_vs_support_resistance(geo):
    s, r = geo.get('support_price'), geo.get('resistance_price')
    ds, dr = geo.get('dist_to_support_pct'), geo.get('dist_to_resistance_pct')
    if s and r and ds is not None and dr is not None:
        return {'detail': f"距支撑位{s}元({ds:+.1f}%)，距压力位{r}元({dr:+.1f}%)"}
    elif s and ds is not None:
        return {'detail': f"距支撑位{s}元({ds:+.1f}%)"}
    return {'detail': '支撑阻力数据不足'}


def _assess_vs_chip(tags):
    parts = []
    c = str(tags.get('chip_concentration', ''))
    if c: parts.append(f"筹码{chip_concentration_cn(c)}")
    pr = tags.get('profit_ratio')
    if pr is not None:
        try: parts.append(f"获利盘{float(pr):.0%}")
        except: pass
    return {'detail': '，'.join(parts) if parts else '筹码数据不足'}


def _assess_vs_indicator(tags):
    parts = []
    for key, label in [('rsi14', 'RSI'), ('kdj_j', 'KDJ_J')]:
        v = tags.get(key)
        if v is not None:
            try: parts.append(f"{label}={float(v):.0f}")
            except: pass
    return {'detail': '，'.join(parts) if parts else '指标数据不足'}


def _structure_plain(vs_z, vs_ma, vs_sr, vs_chip, vs_ind):
    parts = []
    pos = vs_z.get('position', '')
    if pos == '上方': parts.append("价格突破中枢上沿，离开成本区")
    elif pos == '下方': parts.append("价格在中枢下方运行")
    elif pos == '内部': parts.append("价格在中枢箱体内震荡")
    ma = vs_ma.get('alignment', '')
    if ma: parts.append(f"均线{ma_alignment_cn(ma)}")
    sr = vs_sr.get('detail', '')
    if sr and '数据不足' not in sr: parts.append(sr)
    chip = vs_chip.get('detail', '')
    if chip and '数据不足' not in chip: parts.append(chip)
    return '，'.join(parts) if parts else '结构数据不足'
