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

# 457号：多级别联立分析器（周/日/60min 区间套 + 方向一致性 + 关键价位）
from app.engine.framework.chanlun_multi_level import MultiLevelChanlunAnalyzer
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
            # 446号：日线=长线，走线段中枢（知识库"中长线强制线段中枢"）；段不足自动回退笔中枢
            analyzer = ChanlunAnalyzer({'bi_zs_mode': False})
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

        # 1b. 多级别联立（457号：周/日/60min 区间套，445 §6.1「级别定理/多周期联立」接线）
        #    周线/60min 数据由 dim1 loader 注入 data_context['weekly_df']/['hourly_df']；
        #    缺省时自动降级只有日线（框架 _build_direction_text 可处理），绝不阻塞主链。
        multi_level = None
        if data_context:
            try:
                _ml_dict = {}
                if 'daily_df' in data_context:
                    _ml_dict['daily'] = data_context['daily_df']
                if 'weekly_df' in data_context:
                    _ml_dict['weekly'] = data_context['weekly_df']
                if 'hourly_df' in data_context:
                    _ml_dict['hourly'] = data_context['hourly_df']
                if _ml_dict:
                    # 对齐 bi_zs_mode（各级别统一线段中枢）+ enabled 开关（ChanlunConfig multi_level）
                    _ml_config = ChanlunConfig.default()
                    _ml_analyzer = MultiLevelChanlunAnalyzer(config=_ml_config)
                    multi_level = _ml_analyzer.analyze(_ml_dict)
            except Exception as e:
                logger.debug(f"多级别联立分析失败: {e}")
                multi_level = None

        # 2. 支撑阻力
        indicator_ma = data_context.get('indicator_ma_df') if data_context else None
        geo = calc_support_resistance(df if df is not None else None, indicator_ma_df=indicator_ma)

        # 3. 5子维度
        latest_close = float(df['close'].iloc[-1]) if df is not None and not df.empty else 0.0
        _last_date = str(df['trade_date'].iloc[-1])[:10] if (df is not None and not df.empty
                                                             and 'trade_date' in df.columns) else None
        vs_zhongshu = _assess_vs_zhongshu(tags, dims, chanlun_result, latest_close,
                                          last_date=_last_date)
        vs_ma = _assess_vs_ma(tags)
        vs_sr = _assess_vs_support_resistance(geo)
        vs_chip = _assess_vs_chip(tags)
        vs_indicator = _assess_vs_indicator(tags)

        # 4. 结构强度（0-100 域；ChanlunScorer.score 返回 {'score': 0-100, 'details', 'recommendation'}）
        strength = 50  # 无缠论结果/评分异常时中性分（0-100 域，对应 continuous_value=0.5）
        if chanlun_result:
            try:
                scorer = ChanlunScorer()
                # 464-5C：补传 latest_close + market_context——原只传 analysis_result，
                #   价格匹配度（买点跌破/追高惩罚、卖点反弹加分）与换手/大单市场调整全部被跳过。
                score_result = scorer.score(chanlun_result, latest_close=latest_close,
                                            market_context=_build_market_context(data_context))
                # 464号修复：原取 'strength' 键恒回退 0.5（返回值无此键）→ 真实结构强度从未接入；
                #   正确键 'score'（0-100，score() 内部 +50 归一 clamp [0,100]）。
                strength = float(score_result.get('score', 50)) if isinstance(score_result, dict) else 50
            except Exception:
                pass
        if isinstance(strength, dict):
            strength = strength.get('score', 50)

        # 5. 买卖点
        buy_sell_points = []
        if chanlun_result:
            buy_sell_points = (chanlun_result.get('buy_points', []) or []) + \
                              (chanlun_result.get('sell_points', []) or [])

        # ── 445 §6.1：7 契约键真实接线（补产出，消解 dim_adapter/conflict_matrix 增强静默失效） ──
        # ① divergence（背驰）
        divergence_obj = chanlun_result.get('divergence') if chanlun_result else None
        divergence = ''
        divergence_type = ''
        divergence_strength = 0.0
        if divergence_obj is not None:
            divergence = '底背驰' if divergence_obj.direction == 'up' else '顶背驰'
            # 契约键：类型映射 to 中文（conflict_matrix C6/C10 读 '趋势背驰'）
            _div_type_cn = {
                'trend': '趋势背驰', 'consolidation': '盘整背驰', 'zhongshu': '中枢背驰',
            }
            divergence_type = _div_type_cn.get(divergence_obj.type, divergence_obj.type)
            divergence_strength = round(float(divergence_obj.confidence), 4)

        # ② buy_sell_points_detail（序列化；consumer 读 type='buy'/'sell' + confirmed）
        buy_sell_points_detail = []
        for _ptype, _pts in (('buy', chanlun_result.get('buy_points', []) if chanlun_result else []),
                             ('sell', chanlun_result.get('sell_points', []) if chanlun_result else [])):
            for _p in (_pts or []):
                _pos = getattr(_p, 'position', None) or {}
                buy_sell_points_detail.append({
                    'type': _ptype,
                    'point_type': getattr(_p, 'type', ''),
                    'confirmed': float(getattr(_p, 'confidence', 0) or 0) >= 0.6,
                    'confidence': round(float(getattr(_p, 'confidence', 0) or 0), 4),
                    'price': float(_pos.get('price', 0) or 0),
                    'date': _resolve_bsp_date(_pos, df),
                    'index': _pos.get('idx'),
                    'reason': str(getattr(_p, 'reason', '') or ''),
                })

        # ③ chanlun_phase（健康/欲病，取自 11 定理 overall_score）
        chanlun_phase = '欲病'
        if chanlun_result:
            _tc = chanlun_result.get('theorem_check') or {}
            _tc_sum = _tc.get('summary') or {}
            _overall = float(_tc_sum.get('overall_score', 0.0) or 0.0)
            chanlun_phase = '健康' if _overall >= 0.6 else '欲病'

        # ④ stage_name（结构态，见 step 6 计算后赋值）

        # ⑤ level_cross_score（真实接线 ChanlunLevelValidator，死 import 复活）
        level_cross_score = 0.5
        try:
            if df is not None and not df.empty and len(df) >= 30:
                _validator = ChanlunLevelValidator()
                _vf = _validator.validate(df)
                level_cross_score = float(_vf.get('cross_score', 0.5) or 0.5)
        except Exception as e:
            logger.debug(f"级别校验失败: {e}")

        # ⑥⑦ trend_structure_signal + ts_strength（真实接线 TrendStructureDetector；strength 字符串→float）
        trend_structure_signal = ''
        ts_strength = 0.0
        try:
            if df is not None and not df.empty and len(df) >= 30:
                _tsd = TrendStructureDetector()
                _ts = _tsd.detect(df)
                if _ts:
                    trend_structure_signal = str(_ts.get('signal') or '')
                    # consumer dim_adapter 读 ts_strength 为 float；detector 返回 'strong'/'basic' 字符串 → 映射
                    _ts_strength_map = {'strong': 0.3, 'basic': 0.1}
                    _ts_strength_raw = str(_ts.get('strength') or '')
                    ts_strength = _ts_strength_map.get(_ts_strength_raw, 0.0)
        except Exception as e:
            logger.debug(f"趋势结构检测失败: {e}")

        # 6. 白话文本
        plain = _structure_plain(vs_zhongshu, vs_ma, vs_sr, vs_chip, vs_indicator)
        # 440号：结构态改为引擎自产（缠论 trend 映射），不再读空 dims['structure']
        _t = (chanlun_result.get('trend', '') if chanlun_result else '') or str(tags.get('state_label', ''))
        if _t in ('up', 'down', '上升', '下降'):
            struct_state = '上升' if _t in ('up', '上升') else '下降'
        else:
            struct_state = '盘整'
        stage_name = struct_state
        pos_state = str(tags.get('price_position', '') or '中位')

        status_description = {
            'vs_zhongshu': vs_zhongshu['detail'],
            'vs_ma': vs_ma['detail'],
            'vs_support_resistance': vs_sr['detail'],
            'vs_chip': vs_chip['detail'],
            'vs_indicator': vs_indicator['detail'],
            'chanlun_direction': chanlun_result.get('trend', '未知') if chanlun_result else '未知',
            'trend_basis': chanlun_result.get('trend_basis', '') if chanlun_result else '',
            'chanlun_strength': round(strength, 2) if isinstance(strength, (int, float)) else str(strength),
            'buy_sell_points': [str(p) for p in buy_sell_points[:3]],
            'plain': plain,
            # ── 457号：多级别联立（周/日/60min 区间套 + 方向一致性 + 关键价位）──
            #   multi_level 键与 strategy_analyze/dim4/tag_extractor/fallback_description 契约一致
            #   （direction_text/direction_map/near_levels/levels/enabled）；数据不足时不产键（保持原空壳语义）。
            'multi_level': multi_level if isinstance(multi_level, dict) and multi_level else None,
            'multi_level_direction_text': (multi_level or {}).get('direction_text', '仅单级别分析，无跨级别验证数据') if isinstance(multi_level, dict) else '仅单级别分析，无跨级别验证数据',
            # ── 445 §6.1 7 契约键（补产出，消解 dim_adapter/conflict_matrix/reliability 增强静默失效） ──
            'level_cross_score': level_cross_score,
            'chanlun_phase': chanlun_phase,
            'trend_structure_signal': trend_structure_signal,
            'ts_strength': ts_strength,
            'buy_sell_points_detail': buy_sell_points_detail,
            'stage_name': stage_name,
            'divergence': divergence,
            # 补充 conflict_matrix C6/C10 契约键（类型/强度）
            'divergence_type': divergence_type,
            'divergence_strength': divergence_strength,
        }

        # 7. judgment
        light = 'yellow'
        if struct_state == '上升': light = 'green'
        elif struct_state == '下降': light = 'red'
        judgment = {
            'structure': struct_state, 'position': pos_state,
            'light': light, 'overall_light': light,
            'overall_direction': 1 if struct_state == '上升' else (-1 if struct_state == '下降' else 0),
            # continuous_value 统一 0-1 置信语义（chanlun_strength 为 0-100 域，归一 /100）
            'continuous_value': round(strength / 100.0, 4) if isinstance(strength, (int, float)) else 0.5,
        }

        # 8. audit
        # 454号：消除「全为有数据级门槛」恒真。对齐 dim3 先例——
        #   保留 2 条数据完整门槛（趋势方向/价格vs中枢），新增 3 条判读结论条件
        #   （结构健康 chanlun_phase / 无背驰 / 有确认买点）。
        trend_val = chanlun_result.get('trend', '未知') if chanlun_result else '无数据'
        # 判读：结构健康度（11定理 overall_score≥0.6 → 健康，D10 产出）
        _phase_ok = chanlun_phase == '健康'
        # 判读：无背驰（顶背驰是结构性警示；无背驰才满足）
        _no_div = not divergence  # '' 为无背驰
        # 判读：有确认买点（buy_sell_points_detail 含 type='buy' 且 confirmed）
        _buy_confirmed = any(
            p.get('type') == 'buy' and p.get('confirmed') for p in buy_sell_points_detail)
        conditions = [
            {'name': '趋势方向', 'satisfied': trend_val not in ('未知', '无', '无数据', 'unknown'),
             'actual': trend_val, 'threshold': '有明确缠论方向'},
            {'name': '价格vs中枢', 'satisfied': bool(vs_zhongshu['position']),
             'actual': vs_zhongshu['position'] or '未知', 'threshold': '有明确位置'},
            {'name': '结构健康度', 'satisfied': _phase_ok,
             'actual': chanlun_phase, 'threshold': '11定理评分≥0.6（健康）'},
            {'name': '背驰检测', 'satisfied': _no_div,
             'actual': divergence if divergence else '无背驰', 'threshold': '无背驰信号'},
            {'name': '有确认买点', 'satisfied': _buy_confirmed,
             'actual': '有确认买点' if _buy_confirmed else '无确认买点',
             'threshold': '存在 confirmed 买点'},
        ]
        satisfied_count = sum(1 for c in conditions if c['satisfied'])
        total_count = len(conditions)
        audit = {'conditions': conditions, 'satisfied_count': satisfied_count,
                 'total_count': total_count, 'confidence': satisfied_count / total_count if total_count > 0 else 0}

        return {'status_description': status_description, 'judgment': judgment, 'audit': audit}

    def get_data_dependencies(self) -> list:
        return ['daily_cache (market_cache.db)', 'weekly_df/hourly_df (dim1 注入数据上下文, 457号)',
                'tags (pre_feat_cache)', 'dims (StatusEngine)']


def _resolve_bsp_date(position, df):
    """465-2：买卖点 position.date 回填——一买/一卖 position=divergence.position 仅含 idx 无 date，
    从 daily_df 反查交易日；二三买 date 已由 detector 显式带，原样返回。"""
    _date = str(position.get('date', '') or '')
    if _date:
        return _date
    if df is not None and not df.empty and 'trade_date' in df.columns:
        try:
            _idx = position.get('idx')
            if _idx is not None:
                _i = int(_idx)
                if 0 <= _i < len(df):
                    return str(df['trade_date'].iloc[_i])[:10]
        except Exception:
            pass
    return ''


def _build_market_context(data_context):
    """从 data_context 提取 ChanlunScorer 消费的市场上下文键（464-5C：事实接线，缺键不产）

    - turnover_rate ← daily_basic_df（最新交易日）
    - net_lg_amount ← moneyflow_df（最新交易日）
    - index_condition 无独立数据源（data_context 无指数环境键）→ 不产，scorer .get 缺省不调整
    """
    if not data_context:
        return None
    mc = {}
    try:
        _dbb = data_context.get('daily_basic_df')
        if _dbb is not None and not _dbb.empty and 'turnover_rate' in _dbb.columns:
            _tr = pd.to_numeric(_dbb['turnover_rate'], errors='coerce').dropna()
            if not _tr.empty:
                mc['turnover_rate'] = float(_tr.iloc[-1])
    except Exception:
        pass
    try:
        _mf = data_context.get('moneyflow_df')
        if _mf is not None and not _mf.empty and 'net_lg_amount' in _mf.columns:
            _nl = pd.to_numeric(_mf['net_lg_amount'], errors='coerce').dropna()
            if not _nl.empty:
                mc['net_lg_amount'] = float(_nl.iloc[-1])
    except Exception:
        pass
    return mc if mc else None


def _assess_vs_zhongshu(tags, dims, chanlun_result=None, latest_close=0.0, last_date=None):
    """价格 vs 当前有效中枢（463号：不再盲取 zs_list[-1] 多年旧中枢；
    daily_df 前复权口径，展示价=实际价；last_date=最后交易日（做中枢时效过滤）"""
    if chanlun_result:
        zs_list = chanlun_result.get('zhongshu', [])
        from app.engine.framework.chanlun_strategy import _select_current_zhongshu
        zs = _select_current_zhongshu(zs_list, last_date=last_date)
        if zs is not None:
            zs_h = float(getattr(zs, 'high', 0))
            zs_l = float(getattr(zs, 'low', 0))
            _span = ''
            try:
                _span = f"，中枢{str(zs.start_date)[:10]}~{str(zs.end_date)[:10]}"
            except Exception:
                pass
            price = latest_close
            if price > zs_h:
                return {'position': '上方', 'detail': f"价格位于中枢上方({zs_l:.2f}~{zs_h:.2f}{_span})"}
            elif price < zs_l:
                return {'position': '下方', 'detail': f"价格位于中枢下方({zs_l:.2f}~{zs_h:.2f}{_span})"}
            else:
                return {'position': '内部', 'detail': f"价格在中枢内部({zs_l:.2f}~{zs_h:.2f}{_span})"}
        # 无有效中枢（多年无新中枢/中枢已失效）→ 明确状态，不再拿旧中枢伪对比
        return {'position': '无有效中枢', 'detail': '当前无有效日线中枢（趋势延续或中枢已失效）'}
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
    """支撑/压力展示（daily_df 前复权口径，展示价=实际价）"""
    s, r = geo.get('support_price'), geo.get('resistance_price')
    ds, dr = geo.get('dist_to_support_pct'), geo.get('dist_to_resistance_pct')
    if s and r and ds is not None and dr is not None:
        return {'detail': f"距支撑位{s:.2f}元({ds:+.1f}%)，距压力位{r:.2f}元({dr:+.1f}%)"}
    elif s and ds is not None:
        return {'detail': f"距支撑位{s:.2f}元({ds:+.1f}%)"}
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
    # 442号缺陷③：rsi14/kdj_j 键 pre_feat 不产出（derived 组无此键），改读 indicator_status（99.7%覆盖）
    ind = str(tags.get('indicator_status', ''))
    if ind:
        ma_map = {'bullish': '均线多头排列', 'bearish': '均线空头排列', 'mixed': '均线纠缠'}
        for seg in ind.split(','):
            if seg.startswith('ma='):
                mv = seg[3:]
                if mv in ma_map:
                    parts.append(ma_map[mv])
                break
    # rsi（461-1：RSI 三键统一——SSOT=rsi，chip_fund_ext.rsi, 443 R1 全市场真实化, Wilder ewm14）。
    # 原读 rsi_percentile（market_stats 组：全市场 AVG(rsi14) 归一化，市场级当个股级展示——概念错位）。
    # 现改读个股 RSI 真值（0-100），并按强弱分档描述，不再以市场级冒充个股。
    rs = tags.get('rsi')
    if rs is not None:
        try:
            rsi_v = float(rs)
            if rsi_v >= 70:
                _rsi_desc = '偏强'
            elif rsi_v <= 30:
                _rsi_desc = '偏弱'
            else:
                _rsi_desc = '中性'
            parts.append(f'RSI {rsi_v:.0f} {_rsi_desc}')
        except (TypeError, ValueError, ZeroDivisionError):
            pass
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
