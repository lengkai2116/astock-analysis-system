"""第3维 量价健康引擎 — 独立完整文件

369号方案 P1 维度引擎整合：物理合并以下文件为独立完整文件：
  - volume_price_strategy.py — 量价核心（四阶段链+形态+背离+阶段检测）
  - kline_pattern.py — K线形态识别
  - vp_health_builder 输出格式 + 条件稽核
  - shared_vol_ratio 量比统一

统一接口：Dim3VPEngine.evaluate() → {status_description, judgment, audit}
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.data.mixins import DataAwareMixin
from app.engine.patterns.engine import PatternEngine
from app.opportunity_atlas.dimensions.enum_cn_map import pattern_code_cn

# ═══════════════════════════════════════════════════════════
# 量比统一（shared_vol_ratio 内联）
# ═══════════════════════════════════════════════════════════



# 411号Phase 5：预计算MACD缓存（每次evaluate()调用时刷新）
# 411号Phase 5：预计算MACD缓存（每次evaluate()调用时刷新）
_MACD_PRECOMPUTED_CACHE: dict = {}

def _load_precomputed_macd(ts_code: str) -> dict:
    """从indicator_macd预计算表读取MACD数据"""
    if not ts_code:
        return {}
    cache_key = ts_code
    if cache_key in _MACD_PRECOMPUTED_CACHE:
        return _MACD_PRECOMPUTED_CACHE[cache_key]
    try:
        from app.data import DataManager
        dm = DataManager()
        wide = dm.get_cached_indicators(ts_code)
        if wide is not None and not wide.empty:
            result = {}
            for col in ('macd_dif', 'macd_dea', 'macd_hist'):
                if col in wide.columns:
                    arr = wide[col].dropna().values.astype(float)
                    if len(arr) > 0:
                        result[col] = arr
            if len(result) == 3:
                _MACD_PRECOMPUTED_CACHE[cache_key] = result
                return result
    except Exception:
        pass
    _MACD_PRECOMPUTED_CACHE[cache_key] = {}
    return {}

def calc_vol_ratio(current_vol, avg_vol_5d):
    if avg_vol_5d is None or avg_vol_5d <= 0:
        return 1.0
    return round(current_vol / avg_vol_5d, 2)

def classify_vol_ratio(vol_ratio):
    if vol_ratio >= 3.0: return '极度放量'
    elif vol_ratio >= 2.0: return '显著放量'
    elif vol_ratio >= 1.2: return '温和放量'
    elif vol_ratio >= 0.8: return '正常'
    elif vol_ratio >= 0.5: return '缩量'
    return '极度缩量'

# ═══════════════════════════════════════════════════════════
# 第3维 引擎
# ═══════════════════════════════════════════════════════════

class Dim3VPEngine(DataAwareMixin):
    """第3维 量价健康引擎 — 四阶段链 + 形态检测 + 背离检测 + 10分制评分"""

    def __init__(self):
        self._dm = None
        self.pattern_engine = PatternEngine()

    def evaluate(self, dims, tags, signals=None, lifecycle=None, data_context=None):
        """411号Phase 6：优先使用data_context预加载数据，回退独立查询。"""
        ts_code = tags.get('ts_code', '')
        # 411号Phase 6：优先使用data_context
        if data_context and 'daily_df' in data_context:
            df = data_context['daily_df']
        else:
            ecm = self._get_dm().cache
            try:
                df = ecm.get_cached_daily(ts_code)
            except:
                df = None

        # 量价状态（440号：自产，不再读空 dims['vp']——vp 由 volume_price_fit 映射）
        vp_pattern_tag = str(tags.get('volume_price_fit', ''))
        vp_state = {'healthy': '强健康', 'diverging': '背离', 'neutral': '中性'}.get(vp_pattern_tag, '中性')
        light_map = {'强健康': 'green', '健康': 'green', '中性': 'yellow', '背离': 'red', '严重背离': 'red'}
        vp_light = light_map.get(vp_state, 'yellow')

        # 10分制评分
        vp_pattern = str(tags.get('volume_price_fit', ''))
        vp_score = {'healthy': 2, 'diverging': -1}.get(vp_pattern, 1)
        # PatternEngine 10分制评分（替代原有 KLinePatternVerifier）
        pattern_score = 5.0  # 默认中性分
        pattern_details = {}
        if df is not None and not df.empty and len(df) >= 10:
            try:
                # 形态检测器使用 'volume' 列，daily_df 为 'vol'，做列名适配
                if 'vol' in df.columns and 'volume' not in df.columns:
                    df = df.rename(columns={'vol': 'volume'})
                pattern_score, pattern_details = self.pattern_engine.evaluate(df)
            except Exception as e:
                logger.warning(f"PatternEngine.evaluate 异常: {e}")
        try: vol_ratio = float(tags.get('volume_ratio', 1.0))
        except: vol_ratio = 1.0
        ve = 2 if vol_ratio > 2 else (1.5 if vol_ratio > 1.2 else (1 if vol_ratio > 0.8 else 0))
        ma = str(tags.get('ma_alignment', ''))
        ms = 1 if ma in ('多头排列', 'bullish') else (0 if ma in ('空头排列', 'bearish') else 0.5)
        cc = str(tags.get('chip_concentration', ''))
        # 445-A3 修复：chip_concentration 实际枚举为 concentrating/dispersing/stable
        # （chip_distribution_service.py:184-188 英文存储），原查'单峰密集'/'tight' 恒失配 → cs 恒 0.5
        cs = 1 if cc in ('concentrating', '单峰密集', 'tight') else 0.5
        try: rsi = float(tags.get('rsi14', 50))
        except: rsi = 50
        is_ = 0.5
        if 60 < rsi <= 70: is_ = 1
        elif 30 <= rsi < 40: is_ = 0.8
        elif rsi > 70 or rsi < 30: is_ = 0.2
        # 445号：RPS 相对强弱因子补产出（原 RPS 被 RSI 顶替——强弱只读 rsi14，RPS 从不参与评分）
        # 知识库权威（量价形态打分系统/《RPS相对强弱指标》）：RPS>85 → +1 分；欧奈尔狂飙前平均 87、A股 80+。
        # data_context 由 dim1 预加载 relative_strength（rps_20d/rps_60d）；缺省回退独立查询。
        rps_eff = None  # 取 20d 优先，缺则 60d
        if data_context:
            _rsc = data_context.get('relative_strength') or {}
        else:
            _rsc = {}
        if _rsc:
            rps_eff = _rsc.get('rps_20d')
            if rps_eff is None:
                rps_eff = _rsc.get('rps_60d')
        else:
            # 未从 data_context 读到（直接 evaluate / 旧调用）→ 独立查询 relative_strength_cache
            try:
                _ecm_rs = self._get_dm().cache
                _rs_rows = _ecm_rs.get_relative_strength(ts_code=ts_code)
                if _rs_rows:
                    _rr = _rs_rows[0]
                    rps_eff = _rr.get('rps_20d')
                    if rps_eff is None:
                        rps_eff = _rr.get('rps_60d')
            except Exception:
                rps_eff = None
        rps = None
        try:
            if rps_eff is not None:
                rps = float(rps_eff)
        except (TypeError, ValueError):
            rps = None
        # RPS>85 → +1 分（对齐知识库量价形态打分系统加分项）；无 RPS 数据时不给分不扣分（保守）
        rps_factor = 1 if (rps is not None and rps > 85) else 0
        dp = -1.5 if vp_state in ('背离', '严重背离') else 0
        raw = vp_score + ve + ms + cs + is_ + rps_factor + dp
        # 形态评分纳入健康度计算（权重15%）— 10分制映射
        pattern_deviation = (pattern_score - 5) / 5 * 1.5
        raw += pattern_deviation
        hs = max(0, min(10, int(round((raw + 4) / 12 * 10))))

        # 背离检测 —— 450号①：删除本地 MACD 兜底段。
        # 445 偏差：原实现用 MACD 代成交量、只判顶背离（pn and mn），与 framework 权威冲突。
        # 权威 `_detect_divergence_enhanced`（volume_price_strategy.py）已是成交量+MACD 三重确认、顶/底背离齐全，
        # 并经 compute_volume_price_signal 产 volume_price_fit 标签；此处完全以该标签为准，不再本地产 MACD。
        div_det = str(tags.get('volume_price_fit', '')) == 'diverging'
        div_txt = '量价背离信号已检测' if div_det else '无背离信号'

        # 量能
        if vol_ratio > 2: ve_l, ve_d = '显著放量', f'量比{vol_ratio:.1f}，显著放量'
        elif vol_ratio > 1.2: ve_l, ve_d = '温和放量', f'量比{vol_ratio:.1f}，温和放量'
        elif vol_ratio > 0.8: ve_l, ve_d = '正常', f'量比{vol_ratio:.1f}，正常'
        else: ve_l, ve_d = '量能萎缩', f'量比{vol_ratio:.1f}，量能萎缩'

        # 形态（使用 PatternEngine 评分 — 10分制）
        pat_names = []
        if pattern_details and pattern_details.get('pattern_count', 0) > 0:
            pat_names = [pattern_code_cn(p['name']) for p in pattern_details.get('patterns', [])[:3]]
        pat_det = ', '.join(pat_names) if pat_names else '无明确形态'

        # 格兰威尔量价关系八准则分类（Wiki知识库）
        granville = _classify_granville(df, vol_ratio, tags)

        # 评分等级
        if hs >= 8: sl = '强健康'
        elif hs >= 6: sl = '健康'
        elif hs >= 4: sl = '中性'
        elif hs >= 2: sl = '弱'
        else: sl = '严重背离'

        # plain
        if vp_state in ('健康', '强健康'):
            core = '上涨时有量配合'
            if ve_l == '量能萎缩': core += '，近期回调缩量（整理蓄势中）'
            elif ve_l == '温和放量': core += '，量能温和释放'
            elif ve_l == '显著放量': core += '，量能显著放大（关注持续性）'
        elif vp_state in ('背离', '严重背离'):
            core = '价量出现背离信号——价格创新高但量能未跟上，需警惕回调'
        else:
            core = f'量价关系中性，量比{vol_ratio:.1f}'
        if pat_det != '无明确形态': core += f'，{pat_det}'
        # 445号：强势 RPS 在 plain 中体现（RPS>85 加分证据）
        if rps is not None and rps > 85:
            core += f'，RPS={rps:.0f}强势（全市场涨幅居前）'
        core += f'（健康度{hs}/10，{sl}）'

        status_description = {
            'vp_state': vp_state, 'health_score': f'{hs}/10（{sl}）',
            'divergence': div_txt, 'volume_energy': ve_d,
            'pattern': pat_det, 'vol_ratio': f'量比{vol_ratio:.1f}',
            'pattern_score': f'{pattern_score:.1f}/10',
            'rps': (f'{rps:.1f}/100' if rps is not None else '数据不足'),
            'granville': f"{granville['name']}（{granville['description']}）",
            'plain': core,
        }
        judgment = {
            'state': vp_state, 'light': vp_light, 'score': hs,
            'overall_light': vp_light,
            'overall_direction': 1 if vp_state in ('健康', '强健康') else (-1 if vp_state in ('背离', '严重背离') else 0),
            'continuous_value': round(hs / 10, 4),
        }
        conditions = [
            {'name': '量价关系', 'satisfied': vp_state in ('强健康', '健康'), 'actual': vp_state, 'threshold': '健康或强健康'},
            {'name': '健康度评分', 'satisfied': hs >= 5, 'actual': f'{hs}/10', 'threshold': '≥5分'},
            {'name': '背离检测', 'satisfied': not div_det, 'actual': '有背离' if div_det else '无背离', 'threshold': '无背离信号'},
            {'name': '量能强度', 'satisfied': ve_l in ('温和放量', '显著放量'), 'actual': ve_l, 'threshold': '放量或温和放量'},
            # 445号：RPS 强弱因子（补产出，不再被 RSI 顶替）
            {'name': '相对强弱RPS', 'satisfied': rps is None or rps > 85,
             'actual': (f'RPS={rps:.1f}' if rps is not None else '数据不足'),
             'threshold': 'RPS>85（数据不足时中性放行）'},
            # 455号：量价八准则形态接入判定（消除「装饰性」）
            # 格兰威尔八准则负面形态（放量滞涨/价升量减/放量下跌/量价背离/放量破均线）→ 不满足，
            # 中性/健康类（量价齐升/井喷/回探缩量）→ 满足。granville 由纯文案升为 audit 证据项，
            # 参与 confidence，使八准则分类真正影响 SIG 结论（判定/灯色仍归 JUD，不越边界）。
            {'name': '量价八准则', 'satisfied': granville['rule'] not in (
                'heavy_pressure', 'weakening', 'selling_pressure', 'breakdown', 'diverging'),
             'actual': granville['name'], 'threshold': '非负面量价形态（放量滞涨/量减/放量跌/背离/破均线）'},
        ]
        sc = sum(1 for c in conditions if c['satisfied'])
        audit = {'conditions': conditions, 'satisfied_count': sc, 'total_count': len(conditions), 'confidence': sc / len(conditions) if conditions else 0}
        return {'status_description': status_description, 'judgment': judgment, 'audit': audit}

    def get_data_dependencies(self):
        return ['daily_cache (market_cache.db)', 'tags (pre_feat_cache)', 'dims (StatusEngine)']


# ═══════════════════════════════════════════════════════════
# 格兰威尔量价关系八准则（Wiki知识库验证）
# ═══════════════════════════════════════════════════════════

def _classify_granville(df, vol_ratio: float, tags: dict) -> dict:
    """格兰威尔量价关系八准则分类（450号②：单日粒度 → 多日窗口）

    Wiki 定义：
    1. 量价齐升（有价有市）→ healthy
    2. 量价背离（有价无市）→ diverging
    3. 价升量减（力度趋弱）→ weakening
    4. 放量滞涨（压力沉重）→ heavy_pressure
    5. 量价井喷（价市同步）→ explosive
    6. 放量下跌（抛盘涌出）→ selling_pressure
    7. 回探缩量（压力下降）→ pullback_shrinking
    8. 放量破均线（方向调整）→ breakdown

    判别粒度（450修正）：原实现用 iloc[-1]/iloc[-2] 单日涨幅 + 单日量比（vol_ratio），
    单日随机噪声大、易误判。改为 **5日区间涨幅** + **5日/20日均量比率**，对齐 Wiki 量价分析
    「以量能趋势佐证价格趋势」的多日观测口径；vol_ratio 入参仅为兜底（df 缺 volume 时）。

    455号（本条与 heavy_pressure 判据）：
      - 修正「放量滞涨」判据：原 `abs(price_chg)<1.5 and vr>20` 用 5日/20日均量**平滑均值**（单日放量
        即可触发，不保证连续）、且 abs() 允许实质下跌入选。改为对齐 framework 权威 `_is_fangliang_zhizhang`
        + wiki——近3日**每根**量 >前20日均量×1.5 且 3日涨幅和<1%（连续明显放大+价格无法加速）。
      - 八准则接入 audit：granville 分类由纯文案升为 audit 证据项（负面形态不满足 confidence），消除
        「装饰性输出」；判定/灯色仍归 JUD，不越 SIG/JUD 边界。
    """
    result = {'rule': 'unknown', 'name': '未知', 'description': ''}

    if df is None or df.empty or len(df) < 5:
        return result

    try:
        close = df['close'].astype(float)
        if 'volume' in df.columns:
            vol = df['volume'].astype(float)
        elif 'vol' in df.columns:
            vol = df['vol'].astype(float)
        else:
            vol = pd.Series([np.nan] * len(df))

        # 5日区间涨幅（多日粒度）
        price_chg = (close.iloc[-1] / close.iloc[-6] - 1) * 100 if len(close) >= 6 else (close.iloc[-1] / close.iloc[-2] - 1) * 100

        # 量能强弱：5日/20日均量比率（vol_ratio 仅作兜底）
        vs = vol.dropna()
        if len(vs) >= 20:
            vol5 = vs.iloc[-5:].mean()
            vol20 = vs.iloc[-20:].mean()
            vr = (vol5 / vol20 - 1) * 100 if vol20 > 0 else 0.0
        else:
            vr = (float(vol_ratio) - 1) * 100 if float(vol_ratio) > 0 else 0.0

        # MA20
        ma20 = close.rolling(20).mean().iloc[-1] if len(close) >= 20 else close.mean()

        # 放量滞涨（455号缺陷修正）：对齐 framework 权威 `_is_fangliang_zhizhang` + wiki。
        # wiki「放量滞涨」=「成交量**连续数日明显放大** + 价格**横向振荡/整理、无法加速**」。
        # 原判据 `abs(price_chg)<1.5 and vr>20` 两处缺陷：①vr 用 5日/20日均量**平滑均值**(>1.2×)，
        #   单日放量即可拉高均值、不保证「连续数日放大」；②abs() 允许 −1.5%~0 实质下跌入选。
        # 改为：近3日**每根**量 > 前20日均量×1.5（连续明显放大，对齐 framework 1.5× 逐日口径）
        #   + 近3日价格涨幅和 < 1%（价格无法加速，含微涨/微跌/横盘，对齐 framework `<0.01`）。
        avg20 = vs.iloc[-20:].mean() if len(vs) >= 20 else None
        recent3_vol = vs.iloc[-4:-1] if len(vs) >= 4 else None
        consec_expand = (
            avg20 is not None and recent3_vol is not None and avg20 > 0
            and all(v > avg20 * 1.5 for v in recent3_vol)
        )
        _n = len(close)
        gains3 = [(close.iloc[i] - close.iloc[i - 1]) / close.iloc[i - 1]
                  for i in range(_n - 3, _n)]
        stall_sum = sum(gains3)

        # 规则判定（5日区间 + 量能趋势）
        if price_chg > 2.0 and vr > 10:
            if vr > 40:
                result = {'rule': 'explosive', 'name': '量价井喷', 'description': '急速上涨+连续大幅放量，多方力量加速释放'}
            else:
                result = {'rule': 'healthy', 'name': '量价齐升', 'description': '价格上涨有充足买盘推动，健康上涨形态'}

        elif price_chg > 1.5 and vr < -10:
            result = {'rule': 'weakening', 'name': '价升量减', 'description': '买盘力度趋弱，上涨动力减弱'}

        elif consec_expand and stall_sum < 0.01:
            result = {'rule': 'heavy_pressure', 'name': '放量滞涨', 'description': '连续数日量能显著放大但价格无法加速，上方压力沉重'}

        elif price_chg < -2.0 and vr > 10:
            result = {'rule': 'selling_pressure', 'name': '放量下跌', 'description': '抛盘涌出，卖压释放'}

        elif price_chg < -1.0 and vr < -10:
            result = {'rule': 'pullback_shrinking', 'name': '回探缩量', 'description': '回调缩量，卖压减轻，反弹可期'}

        elif price_chg < -4.0 and vr > 10 and close.iloc[-1] < ma20:
            result = {'rule': 'breakdown', 'name': '放量破均线', 'description': '放量跌破MA20，多空格局转变'}

        elif str(tags.get('volume_price_fit', '')) == 'diverging':
            result = {'rule': 'diverging', 'name': '量价背离', 'description': '价格创新高但量能未跟上，买盘减弱'}

        else:
            result = {'rule': 'neutral', 'name': '量价中性', 'description': '无明显量价特征'}
    except Exception:
        pass

    return result
